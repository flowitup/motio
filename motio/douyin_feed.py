"""Douyin's home recommendation feed (`douyin:feed`) as rows for the Trending screen.

Douyin has no public category or ranking list a visitor can read. What it does show a visitor with no login is the
home feed (`/aweme/v1/web/tab/feed/`): a fresh draw of recommended videos, ~10 per answer. f2 (see douyin.py) signs
the request, Motio only calls it, with the same anonymous `ttwid` / `msToken` session the video download uses. It is not
a ranking and it has no category: the Trending screen says so.

Rows are `clip` rows like every other followed list; "Make video" then goes through `search.download`, which already
downloads a Douyin link with f2 (yt-dlp second). Photo posts, ads, live rooms and videos under 15 s are left out.
"""
import time

from . import douyin
from .i18n import tr

PREFIX = "douyin:"
FEED = "douyin:feed"
NAMES = {FEED: "Douyin feed"}
PAGES = 5  # answers read per check (about 10 videos each, some repeated)
MIN_SECONDS = 15
_PAUSE = 0.8  # between two answers, like douyin._pause


class FeedError(RuntimeError):
    pass


def parse(target: str) -> str:
    """"douyin:feed" → "feed". ValueError otherwise."""
    if target == FEED:
        return "feed"
    raise ValueError(tr("Unknown Douyin list: {target}", target=target[:80]))


def name(target: str) -> str:
    """English name saved on the source (the app translates it from the target)."""
    parse(target)
    return NAMES[target]


async def _page(index: int) -> dict:
    """One answer of the home feed (f2 signs it). `index` is the refresh counter the web page sends."""
    crawler_cls, _, conf, tokens = douyin._f2()
    from f2.apps.douyin.model import PostFeed  # f2 is loaded by now (douyin._f2 above); a lazy import like douyin.py

    try:
        ms_token = tokens.gen_real_msToken()
    except Exception:
        ms_token = tokens.gen_false_msToken()
    kwargs = {"headers": conf.headers(), "proxies": conf.proxies(), "cookie": f"ttwid={tokens.gen_ttwid()}",
              "timeout": 10, "max_retries": 2}
    async with crawler_cls(kwargs) as crawler:
        raw = await crawler.fetch_post_feed(PostFeed(msToken=ms_token, refresh_index=index))
    return raw if isinstance(raw, dict) else {}


def _clip(post: dict, rank: int) -> dict | None:
    video = post.get("video") or {}
    seconds = (video.get("duration") or 0) / 1000
    desc = " ".join(str(post.get("desc") or "").split())
    pid = str(post.get("aweme_id") or "")
    if not pid.isdigit() or not desc or post.get("is_ads") or post.get("images") or seconds < MIN_SECONDS:
        return None
    stat = post.get("statistics") or {}
    cover = next((u for u in (video.get("cover") or {}).get("url_list") or [] if str(u).startswith("https://")), None)
    return {"id": f"douyin:{pid}", "site": "douyin", "url": f"https://www.douyin.com/video/{pid}", "title": desc,
            "uploader": (post.get("author") or {}).get("nickname") or "", "duration": round(seconds),
            "views": stat.get("play_count") or None, "likes": stat.get("digg_count") or None,
            "pubdate": post.get("create_time") or None, "category": None, "thumbnail": cover, "rank": rank}


def fetch(target: str, take: int = 50) -> list[dict]:
    """The recommended videos as `clip` rows. FeedError when Douyin cannot be reached or answers nothing."""
    parse(target)
    found: dict[str, dict] = {}
    errors: list[Exception] = []
    answered = False
    for i in range(PAGES):
        if i:
            time.sleep(_PAUSE)
        try:
            raw = douyin._run(_page(i + 1))
        except Exception as e:  # f2 not loaded / offline / signature out of date: say so once, keep what was read
            errors.append(e)
            if douyin._is_network_error(e) or not answered:
                break
            continue
        answered = True
        for post in raw.get("aweme_list") or []:
            row = _clip(post, 0) if isinstance(post, dict) else None
            if row and row["id"] not in found:
                found[row["id"]] = row
    if not found:
        if errors:
            e = errors[0]
            if douyin._is_network_error(e):
                raise FeedError(tr("Could not connect to Douyin. Check your internet connection (or VPN, proxy, "
                                   "DNS filter), then try again")) from e
            raise FeedError(tr("Douyin returned an error: {error}", error=str(e)[:200])) from e
        raise FeedError(tr("Douyin gave no videos (its feed may want a login from this network)"))
    return [{**row, "rank": i + 1} for i, row in enumerate(list(found.values())[:take])]
