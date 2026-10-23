"""Bilibili videos when yt-dlp cannot read the page: the video's own JSON API, no login.

Checked on 2026-10-23: yt-dlp's Bilibili extractor (2026.08.19 and the newest 2026.10.21) stops at "Unable to extract
initial state" for every video, because the video page is a bare shell with no data in it, and its fallback gets
"HTTP 403" from the CDN. The JSON API that trending.py already reads still answers a guest (anonymous buvid cookies,
the public "wbi" signature): `wbi/view` gives the title, owner, length and the `cid` of each part, and `wbi/playurl`
with `platform=html5&fnval=0` gives one mp4 with its sound (480p, and 720p when the video has it; 1080p wants a login).
The CDN needs neither cookie nor Referer, but a Referer is sent anyway.

Links understood: `bilibili.com/video/BV…`, the old `…/video/av<number>` (what a Bilibili search returns), `?p=<part>`
and the short `b23.tv/…`. Anything else (series, films, live) is left to yt-dlp's own answer.
"""
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from . import douyin, trending
from .i18n import tr

DEFAULT_HEIGHT = 720
TRIES = 3
HOSTS = ("bilibili.com", "b23.tv")
_QN = ((360, 16), (480, 32), (720, 64))  # (tallest picture, quality number): a guest gets 720p at most
_BV = re.compile(r"/video/(BV[0-9A-Za-z]{10})")
_AV = re.compile(r"/video/av(\d+)", re.I)
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


class NotSupported(RuntimeError):
    """The link is not a plain video link (a series, a film, a live room…): leave it to yt-dlp's answer."""


class Unavailable(RuntimeError):
    """Bilibili does not give this video (removed, paid, a part that does not exist) or its answer changed shape."""


def _host_ok(host: str | None) -> bool:
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS)


def _long_link(url: str) -> str:
    """A b23.tv short link followed, one hop at a time and only inside Bilibili's own hosts; any other link as is."""
    if (urlparse(url).hostname or "").lower() != "b23.tv":
        return url
    try:
        with douyin._client({"User-Agent": trending.UA}, follow=False, transport=_transport) as client:
            for _ in range(5):
                u = urlparse(url)
                if not _host_ok(u.hostname) or _BV.search(u.path) or _AV.search(u.path):
                    break
                with client.stream("GET", url) as r:
                    if not r.is_redirect:
                        break
                    url = urljoin(url, r.headers.get("location", ""))
    except (httpx.HTTPError, ValueError) as e:
        raise RuntimeError(tr("Could not connect to Bilibili. Check your internet connection (or VPN, proxy, DNS "
                              "filter), then try again")) from e
    return url


def find_ref(url: str) -> tuple[dict, int]:
    """({"bvid": …} or {"aid": …}, part number from 1) of a Bilibili video link. NotSupported for any other link."""
    url = _long_link(url)
    u = urlparse(url)
    if not _host_ok(u.hostname):
        raise NotSupported(url)
    if m := _BV.search(u.path):
        ref = {"bvid": m[1]}
    elif m := _AV.search(u.path):
        ref = {"aid": int(m[1])}
    else:
        raise NotSupported(url)
    part = (parse_qs(u.query).get("p") or ["1"])[0]
    return ref, int(part) if part.isdigit() and int(part) > 0 else 1


def _qn(max_height: int) -> int:
    return next((qn for h, qn in _QN if max_height <= h), _QN[-1][1])


def _tell(hooks: list | None, status: str, got: int, total: int) -> None:
    for h in hooks or []:
        h({"status": status, "downloaded_bytes": got, "total_bytes": total})


def _fetch(stream: str, part: Path, hooks: list | None) -> int:
    """Stream the mp4 into `part`; bytes written. Public https only (douyin._client checks every hop)."""
    with douyin._client({"User-Agent": trending.UA, "Referer": "https://www.bilibili.com/"},
                        transport=_transport) as client, client.stream("GET", stream) as r:
        r.raise_for_status()
        if r.headers.get("content-type", "").lower().startswith(("text/", "application/json")):
            raise Unavailable(tr("Bilibili sent a page, not a video"))
        total = int(r.headers.get("content-length") or 0)
        if total > douyin.MAX_BYTES:
            raise douyin._too_big()
        got = 0
        with part.open("wb") as f:
            for chunk in r.iter_bytes(1 << 17):
                got += len(chunk)
                if got > douyin.MAX_BYTES:
                    raise douyin._too_big()
                f.write(chunk)
                _tell(hooks, "downloading", got, total)
    if not got:
        raise Unavailable(tr("Bilibili sent an empty file"))
    return got


def _api(client: httpx.Client, path: str, params: dict) -> dict:
    try:
        return trending._get(client, path, trending._signed(client, params))
    except trending.TrendingError as e:
        raise RuntimeError(str(e)) from e


def _view(client: httpx.Client, ref: dict) -> dict:
    v = _api(client, "/x/web-interface/wbi/view", ref)
    rights = v.get("rights") or {}
    if v.get("is_ogv") or rights.get("movie") or rights.get("pay") or rights.get("arc_pay") or rights.get("ugc_pay"):
        raise Unavailable(tr("Bilibili does not give this video to a guest (paid, a film or a series)"))
    return v


def _address(client: httpx.Client, v: dict, cid: int, max_height: int) -> str:
    data = _api(client, "/x/player/wbi/playurl", {"bvid": v["bvid"], "cid": cid, "qn": _qn(max_height), "fnval": 0,
                                                  "fnver": 0, "platform": "html5", "high_quality": 1})
    parts = data.get("durl") or []
    stream = str(parts[0].get("url") or "") if len(parts) == 1 and isinstance(parts[0], dict) else ""
    if not stream.startswith("https://"):
        raise Unavailable(tr("Bilibili did not give an address for this video"))
    return stream


def download(url: str, out_dir: Path, max_height: int | None = None, hooks: list | None = None) -> dict:
    """One Bilibili video into out_dir/BiliBili_<id>.mp4 (the name yt-dlp uses), answering like search.download.
    NotSupported for a link that is not a video, Unavailable / RuntimeError when Bilibili does not give it."""
    ref, part = find_ref(url)
    height = max_height or DEFAULT_HEIGHT
    with trending._new_client() as client:
        trending._anonymous_cookies(client)
        v = _view(client, ref)
        pages = [p for p in v.get("pages") or [] if isinstance(p, dict) and p.get("cid")]
        if part > max(len(pages), 1) or not (pages or v.get("cid")):
            raise Unavailable(tr("Bilibili has no part {n} in this video", n=part))
        page = pages[part - 1] if pages else {"cid": v["cid"], "duration": v.get("duration")}
        out_dir.mkdir(parents=True, exist_ok=True)
        vid = v["bvid"].removeprefix("BV") + (f"_p{part}" if part > 1 else "")
        path = out_dir / f"BiliBili_{vid}.mp4"
        if not (path.is_file() and path.stat().st_size):
            stream = _address(client, v, page["cid"], height)
            tmp = path.with_name(path.name + ".part")
            try:
                for attempt in range(TRIES):  # the CDN sometimes resets a connection
                    try:
                        got = _fetch(stream, tmp, hooks)
                        break
                    except (httpx.HTTPError, OSError) as e:
                        if attempt == TRIES - 1:
                            raise RuntimeError(tr("Could not download from Bilibili: {error}",
                                                  error=str(e)[:200])) from e
                os.replace(tmp, path)
                _tell(hooks, "finished", got, got)
            finally:
                tmp.unlink(missing_ok=True)
    owner = v.get("owner") if isinstance(v.get("owner"), dict) else {}
    dim = page.get("dimension") if isinstance(page.get("dimension"), dict) else v.get("dimension") or {}
    published = int(v.get("pubdate") or 0)
    title = str(v.get("title") or "")
    if len(pages) > 1 and page.get("part"):
        title = f"{title} · {page['part']}"
    return {"path": str(path), "url": f"https://www.bilibili.com/video/{v['bvid']}", "id": vid, "title": title,
            "platform": "Bilibili", "uploader": owner.get("name") or "",
            "uploader_url": f"https://space.bilibili.com/{owner['mid']}" if owner.get("mid") else "",
            "upload_date": time.strftime("%Y%m%d", time.gmtime(published)) if published else "",
            "duration": page.get("duration") or v.get("duration") or 0, "license": "",
            "width": dim.get("width") or None, "height": dim.get("height") or None}
