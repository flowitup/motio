"""Bilibili's public trending lists (ranking per category, popular, weekly must-watch) as rows for "New videos".

Plain JSON, no login and no signature (checked on the owner's Mac on 2026-10-02):
- `x/web-interface/ranking/v2?rid=<category>&type=all` (rid 0 = every category), `x/web-interface/popular`;
- the weekly list is `popular/series/list` (numbers) then `popular/series/one?number=<latest>`, which also wants an
  anonymous buvid3 / buvid4 cookie from `x/frontend/finger/spi`.
Bilibili answers code -352 to a short User-Agent ("Mozilla/5.0"), so every call sends a full browser one.

What is kept: original uploads only (`copyright` 1, a repost is somebody else's), nothing a creator marked
"no reprint" (`rights.no_reprint`), nothing paid, and nothing under 15 s. Rights stay "unknown": a ranking says what is
hot, not who may reuse it.
"""
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
MIN_SECONDS = 15
TAKE = 100  # rows read from a list (a ranking has up to 100)
TIMEOUT = 30.0
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


class TrendingError(RuntimeError):
    pass


def parse(target: str) -> tuple[str, int | None]:
    """"bilibili:ranking:181" → ("ranking", 181); "bilibili:popular" → ("popular", None). ValueError otherwise."""
    kind, _, rid = target.removeprefix(PREFIX).partition(":")
    if target.startswith(PREFIX) and kind == "ranking" and rid.isdigit() and int(rid) in RANKINGS:
        return "ranking", int(rid)
    if target.startswith(PREFIX) and not rid and kind in (POPULAR, WEEKLY):
        return kind, None
    raise ValueError(tr("Unknown Bilibili trending list: {target}", target=target[:80]))


def name(target: str) -> str:
    """English name saved on the source (the app translates it from the target)."""
    kind, rid = parse(target)
    if kind == "ranking":
        return f"Bilibili ranking · {RANKINGS[rid]}"
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
    """A video the owner could reasonably dub or comment on: an original upload with no 'no reprint' flag."""
    rights = v.get("rights") or {}
    if not v.get("bvid") or v.get("copyright") == 2 or v.get("is_ogv") or rights.get("movie"):
        return False
    if rights.get("no_reprint") or rights.get("pay") or rights.get("arc_pay") or rights.get("ugc_pay"):
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


def fetch(target: str, take: int = TAKE) -> list[dict]:
    """The videos of one trending list, best first, as `clip` rows. TrendingError when Bilibili refuses."""
    kind, rid = parse(target)
    with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True,
                      headers={"User-Agent": UA, "Referer": "https://www.bilibili.com"}) as client:
        if kind == "ranking":
            data = _get(client, "/x/web-interface/ranking/v2", {"rid": rid, "type": "all"})
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
