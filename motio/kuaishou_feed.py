"""Kuaishou's public "Featured" feed (精选, kuaishou.com/brilliant) as rows for the Trending screen.

The web page asks one GraphQL query, `brilliantTypeData` (`hotChannelId` "00"), and Kuaishou answers it to any visitor:
no login, no cookie, no signature (checked 2026-10-18 from a cloud sandbox; an answer carries ~20 videos, the
page cursor stays "1" so every call is a fresh draw, not a ranking). Each video comes with the address of its mp4
(`photoUrl`), which is signed and short-lived: it is kept in `data/cache/kuaishou_media.json`, so "Make video" can
download the file even though Kuaishou answers the detail query (`visionVideoDetail`) and the search only to a browser
with a `did` cookie. The other lists of the site (search, per-video detail) are not read: they want that cookie.

What is kept: videos of at least 15 s with a caption, the first `PAGES` answers merged without repeats.
"""
import json
import re
import time

import httpx

from . import config
from .i18n import tr

GRAPHQL = "https://www.kuaishou.com/graphql"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
PREFIX = "kuaishou:"
FEATURED = "kuaishou:featured"
NAMES = {FEATURED: "Kuaishou featured"}
PAGES = 3  # the feed repeats itself a little: three answers give ~50 different videos
MIN_SECONDS = 15
TIMEOUT = 30.0
MEDIA_TTL = 2 * 86400  # how long a saved mp4 address is tried (it expires on Kuaishou's side after a while)
_QUERY = ("query brilliantTypeDataQuery($hotChannelId:String,$page:String,$pcursor:String){"
          "brilliantTypeData(hotChannelId:$hotChannelId,page:$page,pcursor:$pcursor){result pcursor "
          "feeds{type author{id name} photo{... on PhotoEntity{id duration caption viewCount likeCount timestamp "
          "coverUrl photoUrl}}}}}")
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


class FeedError(RuntimeError):
    pass


def parse(target: str) -> str:
    """"kuaishou:featured" → "featured". ValueError otherwise."""
    if target == FEATURED:
        return "featured"
    raise ValueError(tr("Unknown Kuaishou list: {target}", target=target[:80]))


def name(target: str) -> str:
    """English name saved on the source (the app translates it from the target)."""
    parse(target)
    return NAMES[target]


def count(text) -> int | None:
    """Kuaishou's counts are text: "77780", "1.6万" (10 thousand), "1.2亿" (100 million)."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([万亿]?)\s*", str(text or ""))
    if not m:
        return None
    return round(float(m[1]) * {"": 1, "万": 10_000, "亿": 100_000_000}[m[2]])


def _page(client: httpx.Client) -> list[dict]:
    try:
        r = client.post(GRAPHQL, json={"operationName": "brilliantTypeDataQuery", "query": _QUERY, "variables": {
            "hotChannelId": "00", "page": "brilliant", "pcursor": ""}})
        body = r.json()
    except httpx.HTTPError as e:
        raise FeedError(tr("Could not reach Kuaishou: {error}", error=str(e)[:200])) from e
    except ValueError as e:
        raise FeedError(tr("Kuaishou returned an error: {error}", error=f"{r.status_code} not JSON")) from e
    data = ((body.get("data") or {}).get("brilliantTypeData") or {}) if isinstance(body, dict) else {}
    if r.status_code != 200 or data.get("result") != 1:
        raise FeedError(tr("Kuaishou returned an error: {error}", error=f"{r.status_code} result {data.get('result')}"))
    return [f for f in data.get("feeds") or [] if isinstance(f, dict)]


def _clip(feed: dict, rank: int) -> dict | None:
    p = feed.get("photo") or {}
    caption = " ".join(str(p.get("caption") or "").split())
    seconds = (p.get("duration") or 0) / 1000
    if not p.get("id") or not caption or seconds < MIN_SECONDS or not str(p.get("photoUrl") or "").startswith("https://"):
        return None
    cover = p.get("coverUrl")
    return {"id": f"kuaishou:{p['id']}", "site": "kuaishou", "url": f"https://www.kuaishou.com/short-video/{p['id']}",
            "title": caption, "uploader": (feed.get("author") or {}).get("name") or "", "duration": round(seconds),
            "views": count(p.get("viewCount")), "likes": count(p.get("likeCount")),
            "pubdate": int((p.get("timestamp") or 0) / 1000) or None, "category": None,
            "thumbnail": cover if str(cover or "").startswith("https://") else None, "rank": rank}


def fetch(target: str, take: int = 50) -> list[dict]:
    """The featured videos as `clip` rows, and remember their mp4 addresses. FeedError if Kuaishou says no."""
    parse(target)
    found: dict[str, tuple[dict, str]] = {}
    errors = []
    with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True,
                      headers={"User-Agent": UA, "Referer": "https://www.kuaishou.com/brilliant"}) as client:
        for _ in range(PAGES):
            try:
                feeds = _page(client)
            except FeedError as e:
                errors.append(e)
                continue
            for f in feeds:
                row = _clip(f, 0)
                if row and row["id"] not in found:
                    found[row["id"]] = (row, f["photo"]["photoUrl"])
    if errors and not found:
        raise errors[0]
    rows = []
    for i, (row, _) in enumerate(list(found.values())[:take]):
        rows.append({**row, "rank": i + 1})
    _remember({r["id"].removeprefix("kuaishou:"): found[r["id"]][1] for r in rows})
    return rows


# ---------- the mp4 addresses ----------
def _store():
    return config.CACHE / "kuaishou_media.json"


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
        pass  # only a shortcut: videodl is still there


def media_url(vid: str) -> str | None:
    """The mp4 address the feed gave for this video, while it is still fresh."""
    entry = _load().get(vid)
    if isinstance(entry, dict) and time.time() - entry.get("at", 0) < MEDIA_TTL and str(entry.get("url")).startswith("https://"):
        return entry["url"]
    return None
