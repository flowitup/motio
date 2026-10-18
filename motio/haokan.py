"""Haokan (好看视频, Baidu) videos: yt-dlp has no extractor, but the page of a video carries its address.

Checked on 2026-10-16: `https://haokan.baidu.com/v?vid=<id>` with a phone User-Agent answers a page whose
`window.__PRELOADED_STATE__` holds `curVideoMeta` (title, duration, author, `playurl` and `clarityUrl`: one mp4 per
quality). The desktop User-Agent gets an empty "error" page instead. The mp4 address needs no cookie and no Referer.
Haokan also carries many videos first posted elsewhere: Motio downloads it like any pasted link.
"""
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from . import douyin
from .i18n import tr

PAGE = "https://haokan.baidu.com/v"
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/17.0 Mobile/15E148 Safari/604.1")
DEFAULT_HEIGHT = 720
TRIES = 3
_STATE = "__PRELOADED_STATE__ = "
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


class Unavailable(RuntimeError):
    """Haokan has no such video (removed, private, bad link) or its page changed shape."""


def find_id(url: str) -> str | None:
    """The `vid` of a Haokan video link, or None."""
    u = urlparse(url)
    if (u.hostname or "").lower() != "haokan.baidu.com":
        return None
    vid = (parse_qs(u.query).get("vid") or [""])[0]
    return vid if vid.isdigit() else None


def _state(html: str) -> dict:
    i = html.find(_STATE)
    if i < 0:
        return {}
    try:
        data, _ = json.JSONDecoder().raw_decode(html[i + len(_STATE):])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _height(item: dict) -> int:
    """"576$$1024" is height then width."""
    m = re.match(r"(\d+)", str(item.get("vodVideoHW") or ""))
    return int(m[1]) if m else 0


def pick(meta: dict, max_height: int) -> tuple[str, int]:
    """The best mp4 address that is not taller than `max_height` (the smallest one when all are), and its height."""
    options = [(_height(c), c["url"]) for c in meta.get("clarityUrl") or []
               if isinstance(c, dict) and str(c.get("url") or "").startswith("https://")]
    fit = [o for o in options if o[0] and o[0] <= max_height]
    if fit:
        h, url = max(fit)
    elif options:
        h, url = min(options)
    elif str(meta.get("playurl") or "").startswith("https://"):
        h, url = 0, meta["playurl"]
    else:
        raise Unavailable(tr("Haokan did not give an address for this video"))
    return url, h


def _page(vid: str) -> dict:
    for attempt in range(TRIES):  # Baidu's servers sometimes reset the first connection
        try:
            with httpx.Client(timeout=30, follow_redirects=True, transport=_transport,
                              headers={"User-Agent": MOBILE_UA}) as client:
                r = client.get(PAGE, params={"vid": vid})
            break
        except httpx.HTTPError as e:
            if attempt == TRIES - 1:
                raise RuntimeError(tr("Could not connect to Haokan. Check your internet connection (or VPN, proxy, "
                                      "DNS filter), then try again")) from e
    meta = _state(r.text).get("curVideoMeta")
    if r.status_code != 200 or not isinstance(meta, dict) or not meta.get("title") and not meta.get("playurl"):
        raise Unavailable(tr("Haokan has no such video (removed, private or the link is wrong)"))
    return meta


def _tell(hooks: list | None, status: str, got: int, total: int) -> None:
    for h in hooks or []:
        h({"status": status, "downloaded_bytes": got, "total_bytes": total})


def _fetch(stream: str, part: Path, hooks: list | None) -> int:
    """Stream the mp4 into `part`; bytes written. Public https only (douyin._client checks every hop)."""
    with douyin._client({"User-Agent": MOBILE_UA}, transport=_transport) as client, client.stream("GET", stream) as r:
        r.raise_for_status()
        if r.headers.get("content-type", "").lower().startswith(("text/", "application/json")):
            raise Unavailable(tr("Haokan sent a page, not a video"))
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
        raise Unavailable(tr("Haokan sent an empty file"))
    return got


def download(url: str, out_dir: Path, max_height: int | None = None, hooks: list | None = None) -> dict:
    """One Haokan video into out_dir/Haokan_<vid>.mp4, answering like search.download. Unavailable / RuntimeError."""
    vid = find_id(url)
    if not vid:
        raise Unavailable(tr("Haokan link without a video id: use the https://haokan.baidu.com/v?vid=… link"))
    meta = _page(vid)
    stream, height = pick(meta, max_height or DEFAULT_HEIGHT)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"Haokan_{vid}.mp4"
    if not (path.is_file() and path.stat().st_size):
        part = path.with_name(path.name + ".part")
        try:
            for attempt in range(TRIES):  # the CDN sometimes resets a connection
                try:
                    got = _fetch(stream, part, hooks)
                    break
                except (httpx.HTTPError, OSError) as e:
                    if attempt == TRIES - 1:
                        raise RuntimeError(tr("Could not download from Haokan: {error}", error=str(e)[:200])) from e
            os.replace(part, path)
            _tell(hooks, "finished", got, got)
        finally:
            part.unlink(missing_ok=True)
    author = meta.get("mth") if isinstance(meta.get("mth"), dict) else {}
    published = int(meta.get("publish_time") or 0)
    return {"path": str(path), "url": f"{PAGE}?vid={vid}", "id": vid, "title": str(meta.get("title") or ""),
            "platform": "Haokan", "uploader": author.get("author_name") or meta.get("source_name") or "",
            "uploader_url": author.get("author_url") or "",
            "upload_date": time.strftime("%Y%m%d", time.gmtime(published)) if published else "",
            "duration": meta.get("duration") or 0, "license": "", "width": None, "height": height or None}
