"""Bilibili's public trending lists (ranking per category, popular, weekly must-watch) as rows for "New videos", plus
trending videos by category or by tag (a keyword).

Plain JSON, no login and no signature (checked on the owner's Mac on 2026-10-02):
- `x/web-interface/ranking/v2?rid=<category>&type=all` (rid 0 = every category), `x/web-interface/popular`;
- the weekly list is `popular/series/list` (numbers) then `popular/series/one?number=<latest>`, which also wants an
  anonymous buvid3 / buvid4 cookie from `x/frontend/finger/spi`.
Bilibili answers code -352 to a short User-Agent ("Mozilla/5.0"), so every call sends a full browser one.

A category (`bilibili:category:<key>`, `CATEGORIES`) is a ranking and / or a few Chinese tags; a tag
(`bilibili:tag:<word>`) is one keyword. Tags go through Bilibili's search (`x/web-interface/wbi/search/type`, most
played in the last `WINDOW_DAYS`), which wants the public "wbi" signature (a md5 of the sorted query plus a key made
from two file names that `x/web-interface/nav` hands out) and the anonymous buvid cookies. A search hit has no
copyright or rights flags, so each hit is read once more (`x/web-interface/wbi/view`) and kept or dropped by the
same rules as a ranking item.

What is kept: original uploads only (`copyright` 1, a repost is somebody else's), nothing paid, and nothing under
15 s. A creator's "no reprint" tick is Bilibili's default (about 99 % of a ranking) and says nothing, so it is ignored
(owner, 2026-10-16). Rights stay "unknown": a ranking says what is hot, not who may reuse it.
"""
import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import httpx

from .i18n import tr

API = "https://api.bilibili.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
PREFIX = "bilibili:"
# rid → English name of the ranking category (the app shows its own translated names, keyed by the target)
RANKINGS = {0: "All categories", 181: "Film & TV", 5: "Entertainment", 36: "Knowledge", 188: "Tech", 160: "Life",
            211: "Food", 4: "Games", 1: "Animation", 3: "Music", 129: "Dance", 217: "Animals", 223: "Cars",
            234: "Sports", 155: "Fashion", 119: "Memes", 168: "Chinese animation"}
POPULAR, WEEKLY = "popular", "weekly"
# Categories the owner picks from (Trending screen): English name (the app translates it from the target), the ranking
# rids it reads and the Chinese tags it searches. Adding one here is all it takes; the app lists `CATEGORIES`.
CATEGORIES = {
    "tech": {"name": "Tech", "rankings": (188,), "tags": ()},
    "ai": {"name": "AI & tools", "rankings": (), "tags": ("人工智能", "AI工具", "大模型", "AIGC")},
    "ai_film": {"name": "AI films & series", "rankings": (), "tags": ("AI短片", "AI电影", "AI短剧", "AI漫剧")},
    "film_tv": {"name": "Series & films", "rankings": (181,), "tags": ()},
    "knowledge": {"name": "Knowledge & science", "rankings": (36,), "tags": ()},
    "lifestyle": {"name": "Lifestyle & savoir-vivre", "rankings": (), "tags": ("礼仪", "生活技巧", "情商", "收纳整理")},
    "food": {"name": "Food", "rankings": (211,), "tags": ()},
    "travel": {"name": "Travel", "rankings": (), "tags": ("旅行", "旅游攻略", "citywalk")},
}
WINDOW_DAYS = 7  # a tag looks at what was posted in the last week
RANKING_MAX_AGE_DAYS = 30  # a category's ranking part skips older videos (a ranking also lists year-old ones)
TAG_TAKE = 20  # usable videos kept per tag
TAG_POOL = 30  # search hits read (rights checked) per tag at most
TAG_MAX = 40  # longest tag, in characters
MIN_SECONDS = 15
TAKE = 100  # rows read from a list (a ranking has up to 100)
TIMEOUT = 30.0
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


class TrendingError(RuntimeError):
    pass


def tag_ok(word: str) -> bool:
    """A tag is a few words with no control characters (it goes into a search query and a target string)."""
    return bool(word) and len(word) <= TAG_MAX and word == " ".join(word.split()) and word.isprintable()


def parse(target: str) -> tuple[str, int | str | None]:
    """"bilibili:ranking:181" → ("ranking", 181); "bilibili:popular" → ("popular", None);
    "bilibili:category:ai" → ("category", "ai"); "bilibili:tag:AI短片" → ("tag", "AI短片"). ValueError otherwise."""
    kind, _, rest = target.removeprefix(PREFIX).partition(":")
    if target.startswith(PREFIX):
        if kind == "ranking" and rest.isdigit() and int(rest) in RANKINGS:
            return "ranking", int(rest)
        if not rest and kind in (POPULAR, WEEKLY):
            return kind, None
        if kind == "category" and rest in CATEGORIES:
            return "category", rest
        if kind == "tag" and tag_ok(rest):
            return "tag", rest
    raise ValueError(tr("Unknown Bilibili trending list: {target}", target=target[:80]))


def name(target: str) -> str:
    """English name saved on the source (the app translates it from the target)."""
    kind, arg = parse(target)
    if kind == "ranking":
        return f"Bilibili ranking · {RANKINGS[arg]}"
    if kind == "category":
        return f"Bilibili · {CATEGORIES[arg]['name']}"
    if kind == "tag":
        return f"Bilibili tag · {arg}"
    return "Bilibili popular" if kind == POPULAR else "Bilibili weekly must-watch"


def _get(client: httpx.Client, path: str, params: dict | None = None, **headers) -> dict:
    try:
        r = client.get(f"{API}{path}", params=params, headers=headers)
    except httpx.HTTPError as e:
        raise TrendingError(tr("Could not reach Bilibili: {error}", error=str(e)[:200])) from e
    try:
        body = r.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    code = body.get("code")
    if r.status_code in (412, 429) or code in (-352, -412, -799):
        raise TrendingError(tr("Bilibili blocked the request ({code}): try again later", code=code or r.status_code))
    if r.status_code != 200 or code != 0 or not isinstance(body.get("data"), dict):
        raise TrendingError(tr("Bilibili returned an error: {error}", error=f"{r.status_code} {body.get('message')}"))
    return body["data"]


def _anonymous_cookies(client: httpx.Client) -> None:
    """buvid3 / buvid4 without logging in: the weekly list is refused without them."""
    data = _get(client, "/x/frontend/finger/spi")
    for key, cookie in (("b_3", "buvid3"), ("b_4", "buvid4")):
        if data.get(key):
            client.cookies.set(cookie, data[key], domain=".bilibili.com")


def _https(url: str | None) -> str | None:
    return "https:" + url[5:] if url and url.startswith("http:") else url


def usable(v: dict) -> bool:
    """A video the owner could reasonably dub or comment on: an original upload (copyright 1; 2 is a repost, 3 is
    neither clearly original nor clearly ours to reuse) and not paid."""
    rights = v.get("rights") or {}
    if not v.get("bvid") or v.get("copyright") not in (None, 1) or v.get("is_ogv") or rights.get("movie"):
        return False
    if rights.get("pay") or rights.get("arc_pay") or rights.get("ugc_pay"):
        return False
    return (v.get("duration") or 0) >= MIN_SECONDS


def clip(v: dict, rank: int) -> dict:
    """One list item → a `clip` row (see db.insert_clips)."""
    stat = v.get("stat") or {}
    return {"id": f"bilibili:{v['bvid']}", "site": "bilibili", "url": f"https://www.bilibili.com/video/{v['bvid']}",
            "title": (v.get("title") or "").strip(), "uploader": (v.get("owner") or {}).get("name") or "",
            "duration": v.get("duration") or None, "views": stat.get("view"), "likes": stat.get("like"),
            "pubdate": v.get("pubdate") or None, "category": v.get("tname") or None,
            "thumbnail": _https(v.get("pic")), "rank": rank}


# ---------- search by tag ("wbi" signature) ----------
_WBI_ORDER = (46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39,
              12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63,
              57, 62, 11, 36, 20, 34, 44, 52)
_WBI_TTL = 3600
_wbi_cache: dict = {"key": None, "at": 0.0}
_wbi_lock = threading.Lock()


def _wbi_key(client: httpx.Client) -> str:
    """The signing key: the file names of the two pictures in `nav`, shuffled by Bilibili's fixed table (an hour)."""
    with _wbi_lock:
        if _wbi_cache["key"] and time.time() - _wbi_cache["at"] < _WBI_TTL:
            return _wbi_cache["key"]
        # nav answers code -101 ("not logged in") together with the pictures, so it is read by hand, not through _get
        try:
            body = client.get(f"{API}/x/web-interface/nav").json()
            img = body["data"]["wbi_img"]
            raw = "".join(u.rsplit("/", 1)[1].split(".")[0] for u in (img["img_url"], img["sub_url"]))
            key = "".join(raw[i] for i in _WBI_ORDER)[:32]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as e:
            raise TrendingError(tr("Could not reach Bilibili: {error}", error=str(e)[:200])) from e
        _wbi_cache.update(key=key, at=time.time())
        return key


def _signed(client: httpx.Client, params: dict) -> dict:
    """`params` plus `wts` and `w_rid` (md5 of the sorted, cleaned query and the key)."""
    params = {**params, "wts": int(time.time())}
    query = urlencode({k: re.sub(r"[!'()*]", "", str(params[k])) for k in sorted(params)})
    return {**params, "w_rid": hashlib.md5((query + _wbi_key(client)).encode()).hexdigest()}


def _search(client: httpx.Client, word: str) -> list[dict]:
    """The most played videos of the last week for one keyword, as Bilibili search hits."""
    now = int(time.time())
    data = _get(client, "/x/web-interface/wbi/search/type", _signed(client, {
        "search_type": "video", "keyword": word, "order": "click", "page": 1, "page_size": TAG_POOL,
        "pubtime_begin_s": now - WINDOW_DAYS * 86400, "pubtime_end_s": now}))
    return [h for h in data.get("result") or [] if isinstance(h, dict) and h.get("bvid")]


def _detail(client: httpx.Client, hit: dict) -> dict | None:
    """A search hit read again for its rights (a hit carries none). None when Bilibili does not answer for this one."""
    try:
        v = _get(client, "/x/web-interface/wbi/view", _signed(client, {"bvid": hit["bvid"]}))
    except TrendingError:
        return None
    if v.get("bvid") != hit["bvid"]:
        return None
    return {**v, "tname": re.sub(r"\s+", "", hit.get("typename") or "") or v.get("tname")}  # view leaves tname empty


def _tag(client: httpx.Client, word: str, take: int) -> list[dict]:
    hits = _search(client, word)
    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i in range(0, len(hits), 8):  # a few at a time: stop reading once there are enough, and go easy on Bilibili
            found += [v for v in ex.map(lambda h: _detail(client, h), hits[i:i + 8]) if v and usable(v)]
            if len(found) >= take:
                break
    return found[:take]


def _new_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True,
                        headers={"User-Agent": UA, "Referer": "https://www.bilibili.com"})


def _ranking(client: httpx.Client, rid: int) -> list[dict]:
    data = _get(client, "/x/web-interface/ranking/v2", {"rid": rid, "type": "all"})
    return [v for v in data.get("list") or [] if isinstance(v, dict) and usable(v)]


def _category(client: httpx.Client, key: str, take: int) -> list[dict]:
    """A category: its rankings first (each best first), then the most played of each tag, interleaved by rank."""
    cat = CATEGORIES[key]
    lists, errors = [], []
    _anonymous_cookies(client)
    oldest = time.time() - RANKING_MAX_AGE_DAYS * 86400
    for rid in cat["rankings"]:
        try:
            lists.append([v for v in _ranking(client, rid) if (v.get("pubdate") or 0) >= oldest])
        except TrendingError as e:
            errors.append(e)
    per_tag = max(5, -(-take // max(len(cat["tags"]), 1)))  # a share each: they are interleaved below
    for word in cat["tags"]:
        try:
            lists.append(_tag(client, word, per_tag))
        except TrendingError as e:
            errors.append(e)
    if errors and not any(lists):
        raise errors[0]  # every part failed: say why, instead of an empty list that looks like "nothing trending"
    merged, seen = [], set()
    for rank in range(max(map(len, lists), default=0)):  # first of each list, then second of each…
        for items in lists:
            if rank < len(items) and items[rank]["bvid"] not in seen:
                seen.add(items[rank]["bvid"])
                merged.append(items[rank])
    return merged[:take]


def fetch(target: str, take: int = TAKE) -> list[dict]:
    """The videos of a trending list, category or tag, best first, as `clip` rows. TrendingError if Bilibili says no."""
    kind, arg = parse(target)
    with _new_client() as client:
        if kind == "tag":
            _anonymous_cookies(client)
            items = _tag(client, arg, min(take, TAG_TAKE))
            return [clip(v, i + 1) for i, v in enumerate(items)]
        if kind == "category":
            items = _category(client, arg, min(take, TAG_TAKE))
            return [clip(v, i + 1) for i, v in enumerate(items)]
        if kind == "ranking":
            data = _get(client, "/x/web-interface/ranking/v2", {"rid": arg, "type": "all"})
        elif kind == POPULAR:
            data = _get(client, "/x/web-interface/popular", {"ps": 50, "pn": 1})
        else:
            _anonymous_cookies(client)
            numbers = [s.get("number") or 0 for s in _get(client, "/x/web-interface/popular/series/list").get("list")
                       or []]
            if not numbers:
                raise TrendingError(tr("Bilibili returned an error: {error}", error="no weekly list"))
            n = max(numbers)
            data = _get(client, "/x/web-interface/popular/series/one", {"number": n},
                        Referer=f"https://www.bilibili.com/v/popular/weekly?num={n}", Origin="https://www.bilibili.com")
    items = [v for v in data.get("list") or [] if isinstance(v, dict)][:take]
    return [clip(v, i + 1) for i, v in enumerate(items) if usable(v)]
