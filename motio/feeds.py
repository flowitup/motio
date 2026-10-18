"""Public lists of two more Chinese video sites as followed sources (the Trending screen's "AcFun" and "Pear Video").

Plain requests, no login (read from a cloud sandbox on 2026-10-16):
- AcFun's daily ranking, `rest/pc-direct/rank/channel?channelId=<id>&rankPeriod=DAY`: JSON, up to 100 videos with title,
  uploader, length in ms, views, likes, upload time and the section (`channelName`). `channelId` empty = every section.
- Pear Video's home page lists the day's clips in `video_<id>` links with a title; no length or view count.
Targets: `acfun:rank` (every section), `acfun:channel:<id>` (`ACFUN_CHANNELS`), `pearvideo:home`. Same row shape as
`trending.clip`, same `trending.TrendingError`. "Make video" downloads a row through `search.download` (yt-dlp has an
extractor for both sites and needs no login).
"""
import html
import re

import httpx

from . import trending
from .i18n import tr

ACFUN_PREFIX, PEAR_PREFIX = "acfun:", "pearvideo:"
PREFIXES = (ACFUN_PREFIX, PEAR_PREFIX)
SITES = {ACFUN_PREFIX: "acfun", PEAR_PREFIX: "pearvideo"}
# AcFun section id → English name (the app translates it from the target); ids read from the live ranking. Sections
# that list articles ("Life", 63) have no videos in their ranking and are left out.
ACFUN_CHANNELS = {"201": "Food", "68": "Film talk", "70": "Cars", "60": "Comedy",
                  "1": "Short films & dubbing", "59": "Games", "125": "Military", "69": "Fitness & fighting"}
TARGETS = (f"{ACFUN_PREFIX}rank", *(f"{ACFUN_PREFIX}channel:{c}" for c in ACFUN_CHANNELS), f"{PEAR_PREFIX}home")
RANK_URL = "https://www.acfun.cn/rest/pc-direct/rank/channel"
PEAR_URL = "https://www.pearvideo.com/"
MIN_SECONDS = 15
TAKE = 100
TIMEOUT = 30.0
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


def is_target(text: str) -> bool:
    return text.startswith(PREFIXES)


def site(target: str) -> str:
    return next(s for p, s in SITES.items() if target.startswith(p))


def parse(target: str) -> tuple[str, str | None]:
    """"acfun:rank" → ("acfun", None); "acfun:channel:63" → ("acfun", "63"); "pearvideo:home" → ("pearvideo", None)."""
    if target == f"{ACFUN_PREFIX}rank":
        return "acfun", None
    kind, _, rest = target.removeprefix(ACFUN_PREFIX).partition(":")
    if target.startswith(ACFUN_PREFIX) and kind == "channel" and rest in ACFUN_CHANNELS:
        return "acfun", rest
    if target == f"{PEAR_PREFIX}home":
        return "pearvideo", None
    raise ValueError(tr("Unknown trending list: {target}", target=target[:80]))


def name(target: str) -> str:
    """English name saved on the source (the app translates it from the target)."""
    which, arg = parse(target)
    if which == "pearvideo":
        return "Pear Video · today"
    return f"AcFun · {ACFUN_CHANNELS[arg]}" if arg else "AcFun ranking · all sections"


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True,
                        headers={"User-Agent": trending.UA, "Referer": "https://www.acfun.cn/"})


def _get(client: httpx.Client, url: str, what: str, **params) -> httpx.Response:
    try:
        r = client.get(url, params=params or None)
    except httpx.HTTPError as e:
        raise trending.TrendingError(tr("Could not reach {site}: {error}", site=what, error=str(e)[:200])) from e
    if r.status_code != 200:
        raise trending.TrendingError(tr("{site} returned an error: {error}", site=what, error=r.status_code))
    return r


def acfun_clip(v: dict, rank: int) -> dict | None:
    vid = v.get("contentId") or v.get("dougaId")
    seconds = round((v.get("duration") or v.get("durationMillis") or 0) / 1000)
    if not vid or seconds < MIN_SECONDS:
        return None
    ms = v.get("createTimeMillis") or v.get("contributeTime") or 0
    return {"id": f"acfun:{vid}", "site": "acfun", "url": f"https://www.acfun.cn/v/ac{vid}",
            "title": html.unescape(str(v.get("contentTitle") or v.get("title") or "")).strip(),
            "uploader": v.get("userName") or "", "duration": seconds, "views": v.get("viewCount"),
            "likes": v.get("likeCount"), "pubdate": ms / 1000 if ms else None, "category": v.get("channelName"),
            "thumbnail": trending._https(v.get("coverUrl") or v.get("videoCover")), "rank": rank}


def _acfun(client: httpx.Client, channel: str | None, take: int) -> list[dict]:
    r = _get(client, RANK_URL, "AcFun", channelId=channel or "", rankLimit=min(take, TAKE), rankPeriod="DAY")
    try:
        body = r.json()
        items = body["rankList"]
    except (ValueError, KeyError, TypeError) as e:
        raise trending.TrendingError(tr("AcFun returned an error: {error}", error="no ranking")) from e
    if body.get("result") != 0 or not isinstance(items, list):
        raise trending.TrendingError(tr("AcFun returned an error: {error}", error=body.get("result")))
    rows = (acfun_clip(v, i + 1) for i, v in enumerate(items) if isinstance(v, dict))
    return [c for c in rows if c][:take]


_PEAR_LINK = re.compile(r'<a[^>]*href="video_(\d+)"[^>]*>(.*?)</a>', re.S)
_TAG = re.compile(r"<[^>]+>")


def pear_clips(page: str, take: int = TAKE) -> list[dict]:
    """The clips of Pear Video's home page, in page order, each once (the first link with a title wins)."""
    found: dict[str, str] = {}
    for vid, inner in _PEAR_LINK.findall(page):
        text = [" ".join(html.unescape(s).split()) for s in _TAG.sub("\n", inner).split("\n")]
        title = max((s for s in text if s), key=len, default="")
        if title and vid not in found:
            found[vid] = title
    out = []
    for i, (vid, title) in enumerate(found.items()):
        pic = re.search(rf'https?://image\d*\.pearvideo\.com/cont/\d+/cont-{vid}-\d+\.jpg', page)
        out.append({"id": f"pearvideo:{vid}", "site": "pearvideo", "url": f"https://www.pearvideo.com/video_{vid}",
                    "title": title, "uploader": "", "duration": None, "views": None, "likes": None, "pubdate": None,
                    "category": None, "thumbnail": trending._https(pic[0]) if pic else None, "rank": i + 1})
    return out[:take]


def fetch(target: str, take: int = TAKE) -> list[dict]:
    """The videos of a list, best first, as `clip` rows. trending.TrendingError when the site says no."""
    which, arg = parse(target)
    with _client() as client:
        if which == "acfun":
            return _acfun(client, arg, take)
        page = _get(client, PEAR_URL, "Pear Video").text
    rows = pear_clips(page, take)
    if not rows:
        raise trending.TrendingError(tr("Pear Video returned an error: {error}", error="no clips on the page"))
    return rows

