"""Weibo's public "hot" timeline (`weibo:hot`, weibo.com/hot/list) as rows for the Trending screen.

Weibo answers its hot timeline (`/ajax/feed/hottimeline?group_id=102803`) to a visitor with no account: the browser asks
Weibo's own guest endpoint (`passport.weibo.com/visitor/genvisitor2`) for a visitor session first (checked 2026-10-18
from a cloud sandbox and the owner's Mac: one POST gives the `SUB` / `SUBP` cookies, then the timeline answers 200).
Nothing is signed and nothing is faked: it is the request the web page itself makes for a person who is not logged in.
Without that guest cookie the same URL answers 403.

The timeline mixes text, photo and video posts (about half are videos); only the videos are kept. A video post carries
the address of its mp4 (`page_info.media_info.mp4_hd_url`, an http address on `*.weibocdn.com` that expires), which is
kept in `data/cache/weibo_media.json` so "Make video" can download the file even though yt-dlp needs a login for Weibo.
It is a fresh draw each time, not a ranking, and it has no category.
"""
import email.utils
import ipaddress
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config, douyin, qa
from .i18n import tr

VISITOR = "https://passport.weibo.com/visitor/genvisitor2"
TIMELINE = "https://weibo.com/ajax/feed/hottimeline"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
PREFIX = "weibo:"
HOT = "weibo:hot"
NAMES = {HOT: "Weibo hot videos"}
PAGES = 5  # answers read per check (10 posts each, about half are videos)
MIN_SECONDS = 15
TIMEOUT = 30.0
MEDIA_TTL = 2 * 86400  # how long a saved mp4 address is tried (it expires on Weibo's side after a while)
CDN_SUFFIXES = (".weibocdn.com", ".sinaimg.cn")
_PAUSE = 0.5
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


class FeedError(RuntimeError):
    pass


def parse(target: str) -> str:
    """"weibo:hot" → "hot". ValueError otherwise."""
    if target == HOT:
        return "hot"
    raise ValueError(tr("Unknown Weibo list: {target}", target=target[:80]))


def name(target: str) -> str:
    """English name saved on the source (the app translates it from the target)."""
    parse(target)
    return NAMES[target]


def _visit(client: httpx.Client) -> None:
    """Ask Weibo for a guest session: its Set-Cookie answer (SUB, SUBP) stays in the client."""
    try:
        r = client.post(VISITOR, data={"cb": "visitor_gray_callback", "tid": "", "from": "weibo"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise FeedError(tr("Could not reach Weibo: {error}", error=str(e)[:200])) from e
    if "SUB" not in client.cookies.keys():
        raise FeedError(tr("Weibo returned an error: {error}", error="no guest session"))


def _page(client: httpx.Client, index: int) -> list[dict]:
    try:
        r = client.get(TIMELINE, params={"group_id": "102803", "containerid": "102803",
                                         "extparam": "discover|new_feed", "max_id": index, "count": 10},
                       headers={"Referer": "https://weibo.com/hot/list", "X-Requested-With": "XMLHttpRequest"})
        body = r.json()
    except httpx.HTTPError as e:
        raise FeedError(tr("Could not reach Weibo: {error}", error=str(e)[:200])) from e
    except ValueError as e:
        raise FeedError(tr("Weibo returned an error: {error}", error=f"{r.status_code} not JSON")) from e
    ok = body.get("ok") if isinstance(body, dict) else None
    if r.status_code != 200 or ok != 1:
        raise FeedError(tr("Weibo returned an error: {error}", error=f"{r.status_code} ok {ok}"))
    return [s for s in body.get("statuses") or [] if isinstance(s, dict)]


def _stream(media: dict) -> str | None:
    for key in ("mp4_hd_url", "mp4_720p_mp4", "mp4_sd_url", "stream_url_hd", "stream_url"):
        url = str(media.get(key) or "")
        if url.startswith(("http://", "https://")) and _cdn(url):
            return url
    return None


def _cdn(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host.endswith(s) for s in CDN_SUFFIXES)


def _date(text) -> int | None:
    parsed = email.utils.parsedate_tz(str(text or "").replace(",", ""))
    return int(email.utils.mktime_tz(parsed)) if parsed else None


def _title(status: dict) -> str:
    text = str(status.get("text_raw") or "")
    text = re.sub(r"https?://\S+", "", text).replace("​", "")
    return " ".join(text.split())


def _clip(status: dict, rank: int) -> tuple[dict, str] | None:
    """A video post as a `clip` row and the address of its mp4; None for any other post."""
    page = status.get("page_info") or {}
    media = page.get("media_info") or {}
    stream = _stream(media)
    uid = str((status.get("user") or {}).get("idstr") or "")
    mid = str(status.get("mblogid") or "")
    seconds = float(media.get("duration") or 0)
    title = _title(status)
    if page.get("object_type") != "video" or not stream or not title or seconds < MIN_SECONDS \
            or not uid.isdigit() or not re.fullmatch(r"[A-Za-z0-9]{6,16}", mid):
        return None
    cover = next((u for u in (page.get("page_pic"), ((page.get("pic_info") or {}).get("pic_big") or {}).get("url"))
                  if str(u or "").startswith("https://")), None)
    return {"id": f"weibo:{mid}", "site": "weibo", "url": f"https://weibo.com/{uid}/{mid}", "title": title,
            "uploader": (status.get("user") or {}).get("screen_name") or "", "duration": round(seconds),
            "views": None, "likes": status.get("attitudes_count") or None, "pubdate": _date(status.get("created_at")),
            "category": None, "thumbnail": cover, "rank": rank}, stream


def fetch(target: str, take: int = 50) -> list[dict]:
    """The hot videos as `clip` rows, and remember their mp4 addresses. FeedError when Weibo cannot be reached."""
    parse(target)
    found: dict[str, tuple[dict, str]] = {}
    errors: list[FeedError] = []
    with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True,
                      headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*"}) as client:
        _visit(client)
        for i in range(PAGES):
            if i:
                time.sleep(_PAUSE)
            try:
                posts = _page(client, i)
            except FeedError as e:
                errors.append(e)
                continue
            for post in posts:
                got = _clip(post, 0)
                if got and got[0]["id"] not in found:
                    found[got[0]["id"]] = got
    if not found:
        if errors:
            raise errors[0]
        raise FeedError(tr("Weibo gave no videos"))
    rows = [{**row, "rank": i + 1} for i, (row, _) in enumerate(list(found.values())[:take])]
    _remember({r["id"].removeprefix("weibo:"): found[r["id"]][1] for r in rows})
    return rows


# ---------- the mp4 addresses ----------
def _store():
    return config.CACHE / "weibo_media.json"


def _load() -> dict:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _remember(urls: dict[str, str]) -> None:
    now = time.time()
    data = {k: v for k, v in _load().items() if isinstance(v, dict) and now - v.get("at", 0) < MEDIA_TTL}
    data.update({vid: {"url": url, "at": now} for vid, url in urls.items()})
    try:
        _store().parent.mkdir(parents=True, exist_ok=True)
        _store().write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # only a shortcut: yt-dlp (with the owner's cookies) is still there


def media_url(vid: str) -> str | None:
    """The mp4 address the feed gave for this post, while it is still fresh."""
    entry = _load().get(vid)
    if isinstance(entry, dict) and time.time() - entry.get("at", 0) < MEDIA_TTL and _cdn(str(entry.get("url"))):
        return entry["url"]
    return None


def find_id(url: str) -> str:
    """The post id of a `weibo.com/<uid>/<mblogid>` link, or "" for any other link."""
    u = urlparse(url)
    if (u.hostname or "").lower() not in ("weibo.com", "www.weibo.com"):
        return ""
    m = re.fullmatch(r"/\d+/([A-Za-z0-9]{6,16})/?", u.path)
    return m[1] if m else ""


def _only_weibo_cdn(request: httpx.Request) -> None:
    """Run before every request, redirects included: only Weibo's own CDN hosts, only public addresses (the mp4 address
    is http; Weibo's CDN resets https)."""
    host = request.url.host
    if request.url.scheme not in ("http", "https") or not host or not _cdn(str(request.url)):
        raise OSError(f"not a Weibo video host: {host}")
    addresses = douyin._resolve_host(host)
    if not addresses or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise OSError(f"{host} is not a public address")


def download(url: str, out_dir: Path, hooks: list | None = None) -> dict | None:
    """A post the feed listed, from its own mp4 address, into out_dir/Weibo_<id>.mp4 (answering like search.download).
    None when the feed never gave this post, the address expired or the download failed: yt-dlp then gets its turn."""
    vid = find_id(url)
    stream = media_url(vid) if vid else None
    if not stream:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"Weibo_{vid}.mp4"
    if not (path.is_file() and path.stat().st_size):
        part = path.with_name(path.name + ".part")
        try:
            with httpx.Client(follow_redirects=True, timeout=30, transport=_transport,
                              headers={"User-Agent": UA, "Referer": "https://weibo.com/"},
                              event_hooks={"request": [_only_weibo_cdn]}) as client, \
                    client.stream("GET", stream) as r:
                r.raise_for_status()
                if r.headers.get("content-type", "").lower().startswith(("text/", "application/json")):
                    return None
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
                        for hook in hooks or []:
                            hook({"status": "downloading", "downloaded_bytes": got, "total_bytes": total})
            if not got:
                return None
            os.replace(part, path)
        except (httpx.HTTPError, OSError):
            return None
        finally:
            part.unlink(missing_ok=True)
    try:
        info = qa.probe(path)
    except (RuntimeError, OSError):
        path.unlink(missing_ok=True)
        return None
    video = info.get("video") or {}
    size = path.stat().st_size
    for hook in hooks or []:
        hook({"status": "finished", "downloaded_bytes": size, "total_bytes": size})
    return {"path": str(path), "url": url, "id": vid, "title": "", "platform": "Weibo", "uploader": "",
            "uploader_url": "", "upload_date": "", "duration": info.get("duration") or 0, "license": "",
            "width": video.get("width"), "height": video.get("height")}
