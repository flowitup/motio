"""The videos of one account (a person's or channel's page) on Kuaishou, Douyin and Weibo, as `clip` rows.

Used by the Scan screen and by followed accounts (`watch.py`, kind "account", target `<site>:user:<id>`). A row is the
same shape as every other followed list, with views and likes when the site gives them; "Make video" then downloads the
link like any pasted one.

- Weibo: the profile's video list (`/ajax/profile/getWaterFallContent`) answers the same guest session the hot feed uses
  (Weibo's own `genvisitor2`, nothing signed). Checked from a cloud sandbox.
- Douyin: f2 signs the anonymous `aweme/post` request (see douyin.py: Motio only calls f2). Not tried from the sandbox
  (Douyin's API is out of its reach); a login wall shows as an error.
- Kuaishou: an account page (`visionProfilePhotoList`) answers only a logged-in browser: with a guest `did` cookie
  Kuaishou replies with a slider captcha (checked 2026-10-18). So this reads the page with the owner's own cookies
  (the cookie file or browser of Settings → Browser cookies, `search.site_cookies`), exactly as their browser would,
  and when Kuaishou still asks for a check it says so. Nothing here solves a captcha or fakes a session.
"""
import re
import time
from urllib.parse import urlparse

import httpx

from . import douyin, douyin_feed, kuaishou_feed, search, weibo_feed
from .i18n import tr

SITES = ("kuaishou", "douyin", "weibo")
KEY = "user"  # target = "<site>:user:<id>"
TIMEOUT = 30.0
TAKE = 50
MAX_PAGES = 6
_PAUSE = 0.6
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport
KS_PROFILE = ("fragment photoContent on PhotoEntity{__typename id duration caption likeCount viewCount coverUrl "
              "photoUrl timestamp} fragment feedContent on Feed{type author{id name} photo{...photoContent}} "
              "query visionProfilePhotoList($pcursor:String,$userId:String,$page:String){"
              "visionProfilePhotoList(pcursor:$pcursor,userId:$userId,page:$page){"
              "result pcursor feeds{...feedContent}}}")


class AccountError(RuntimeError):
    pass


# ---------- which account a link or id means ----------
_ID = {"weibo": re.compile(r"\d{5,12}"), "douyin": re.compile(r"MS4wLjAB[\w-]{20,}"),
       "kuaishou": re.compile(r"[A-Za-z0-9_-]{5,32}")}
_HOSTS = {"weibo": ("weibo.com", "www.weibo.com", "m.weibo.cn", "weibo.cn"),
          "kuaishou": ("kuaishou.com", "www.kuaishou.com", "live.kuaishou.com", "v.kuaishou.com", "chenzhongtech.com",
                       "www.chenzhongtech.com", "v.m.chenzhongtech.com"),
          "douyin": ("douyin.com", "www.douyin.com", "iesdouyin.com", "www.iesdouyin.com", "v.douyin.com")}
_SHORT = ("v.douyin.com", "v.kuaishou.com")


def target(site: str, ident: str) -> str:
    return f"{site}:{KEY}:{ident}"


def split(text: str) -> tuple[str, str] | None:
    """"weibo:user:123" → ("weibo", "123"); None for any other text."""
    m = re.fullmatch(rf"({'|'.join(SITES)}):{KEY}:([\w-]+)", text.strip())
    return (m[1], m[2]) if m else None


def _path_id(site: str, path: str) -> str | None:
    pats = {"weibo": r"/(?:u/)?(\d{5,12})/?", "kuaishou": r"/profile/([A-Za-z0-9_-]{5,32})/?",
            "douyin": r"/(?:share/)?user/(MS4wLjAB[\w-]{20,})/?"}
    m = re.fullmatch(pats[site], path)
    return m[1] if m else None


def _site_of(host: str) -> str | None:
    return next((s for s, hosts in _HOSTS.items() if host in hosts), None)


def _expand(url: str) -> str:
    """A phone share link (v.douyin.com/xxx) → where it leads, followed hop by hop and only inside the site's hosts."""
    with httpx.Client(timeout=15.0, transport=_transport, follow_redirects=False,
                      headers={"User-Agent": weibo_feed.UA}) as c:
        for _ in range(5):
            host = (urlparse(url).hostname or "").lower()
            if _site_of(host) not in ("douyin", "kuaishou"):
                break
            try:
                r = c.get(url)
            except httpx.HTTPError:
                break
            if not r.is_redirect:
                break
            url = str(httpx.URL(url).join(r.headers.get("location", "")))
    return url


def identify(text: str, expand: bool = True) -> tuple[str, str] | None:
    """A link to an account page (or a `<site>:user:<id>` target) → (site, id); None for anything else."""
    text = (text or "").strip()
    if got := split(text):
        return got
    if not re.match(r"^https?://", text, re.I):
        return None
    host = (urlparse(text).hostname or "").lower()
    if host in _SHORT and expand:
        text = _expand(text)
        host = (urlparse(text).hostname or "").lower()
    site = _site_of(host)
    ident = _path_id(site, urlparse(text).path) if site else None
    return (site, ident) if site and ident else None


def parse(site: str, text: str) -> str:
    """An account link or a bare id of `site` → its id. ValueError when it is neither."""
    if site not in SITES:
        raise ValueError(tr("Reading an account works on Kuaishou, Douyin and Weibo only"))
    text = " ".join((text or "").split())
    got = identify(text)
    if got:
        if got[0] != site:
            raise ValueError(tr("This link is not a {site} account", site=site))
        return got[1]
    if _ID[site].fullmatch(text):
        return text
    raise ValueError(tr("Not a {site} account link or id: {text}", site=site, text=text[:80]))


# ---------- Weibo ----------
def _weibo(ident: str, take: int) -> tuple[str, list[dict]]:
    rows: dict[str, tuple[dict, str]] = {}
    name, cursor = "", "0"
    with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True,
                      headers={"User-Agent": weibo_feed.UA, "Accept": "application/json, text/plain, */*"}) as client:
        try:
            weibo_feed._visit(client)
        except weibo_feed.FeedError as e:
            raise AccountError(str(e)) from e
        for i in range(MAX_PAGES):
            if i:
                time.sleep(_PAUSE)
            try:
                r = client.get("https://weibo.com/ajax/profile/getWaterFallContent",
                               params={"uid": ident, "cursor": cursor},
                               headers={"Referer": f"https://weibo.com/u/{ident}",
                                        "X-Requested-With": "XMLHttpRequest"})
                body = r.json()
            except httpx.HTTPError as e:
                raise AccountError(tr("Could not reach Weibo: {error}", error=str(e)[:200])) from e
            except ValueError as e:
                raise AccountError(tr("Weibo returned an error: {error}", error=f"{r.status_code} not JSON")) from e
            data = body.get("data") if isinstance(body, dict) else None
            if r.status_code != 200 or not isinstance(data, dict) or body.get("ok") != 1:
                raise AccountError(tr("Weibo returned an error: {error}", error=f"{r.status_code}"))
            for post in data.get("list") or []:
                if not isinstance(post, dict):
                    continue
                name = name or (post.get("user") or {}).get("screen_name") or ""
                got = weibo_feed._clip(post, 0, min_seconds=0)
                if got and got[0]["id"] not in rows:
                    media = (post.get("page_info") or {}).get("media_info") or {}
                    got[0]["views"] = int(media.get("online_users_number") or 0) or None
                    rows[got[0]["id"]] = got
            cursor = str(data.get("next_cursor") or "")
            if len(rows) >= take or not cursor or cursor == "0":
                break
    out = [row for row, _ in list(rows.values())[:take]]
    weibo_feed._remember({r["id"].removeprefix("weibo:"): rows[r["id"]][1] for r in out})
    return name, out


# ---------- Douyin ----------
async def _douyin_page(sec: str, cursor: int) -> dict:
    crawler_cls, _, conf, tokens = douyin._f2()
    from f2.apps.douyin.model import UserPost  # f2 is loaded by now (douyin._f2 above)

    try:
        ms_token = tokens.gen_real_msToken()
    except Exception:
        ms_token = tokens.gen_false_msToken()
    kwargs = {"headers": conf.headers(), "proxies": conf.proxies(), "cookie": f"ttwid={tokens.gen_ttwid()}",
              "timeout": 10, "max_retries": 2}
    async with crawler_cls(kwargs) as crawler:
        raw = await crawler.fetch_user_post(UserPost(max_cursor=cursor, count=20, sec_user_id=sec, msToken=ms_token))
    return raw if isinstance(raw, dict) else {}


def _douyin(ident: str, take: int) -> tuple[str, list[dict]]:
    rows: dict[str, dict] = {}
    name, cursor, errors, answered = "", 0, [], False
    for i in range(MAX_PAGES):
        if i:
            time.sleep(_PAUSE)
        try:
            raw = douyin._run(_douyin_page(ident, cursor))
        except Exception as e:  # f2 not loaded / offline / signature out of date
            errors.append(e)
            break
        answered = True
        for post in raw.get("aweme_list") or []:
            if not isinstance(post, dict):
                continue
            name = name or (post.get("author") or {}).get("nickname") or ""
            row = douyin_feed._clip(post, 0, min_seconds=0)
            if row and row["id"] not in rows:
                rows[row["id"]] = row
        nxt = raw.get("max_cursor")
        if len(rows) >= take or not raw.get("has_more") or not nxt or nxt == cursor:
            break
        cursor = nxt
    if not rows:
        if errors:
            e = errors[0]
            if douyin._is_network_error(e):
                raise AccountError(tr("Could not connect to Douyin. Check your internet connection (or VPN, proxy, "
                                      "DNS filter), then try again")) from e
            raise AccountError(tr("Douyin returned an error: {error}", error=str(e)[:200])) from e
        raise AccountError(tr("Douyin gave no videos for this account (private, empty, or it wants a login)")
                           if answered else tr("Douyin gave no videos"))
    return name, list(rows.values())[:take]


# ---------- Kuaishou ----------
def _kuaishou(ident: str, take: int) -> tuple[str, list[dict]]:
    cookies = search.site_cookies("kuaishou.com")
    if not cookies:
        raise AccountError(tr(
            "Reading a Kuaishou account needs your own login: sign in to kuaishou.com in your browser, then set the "
            "browser or the exported cookie file in Settings → Browser cookies"))
    rows: dict[str, tuple[dict, str]] = {}
    name, cursor = "", ""
    headers = {"User-Agent": kuaishou_feed.UA, "Referer": f"https://www.kuaishou.com/profile/{ident}"}
    with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True, headers=headers,
                      cookies=cookies) as client:
        for i in range(MAX_PAGES):
            if i:
                time.sleep(_PAUSE)
            try:
                r = client.post(kuaishou_feed.GRAPHQL, json={
                    "operationName": "visionProfilePhotoList", "query": KS_PROFILE,
                    "variables": {"userId": ident, "pcursor": cursor, "page": "profile"}})
                body = r.json()
            except httpx.HTTPError as e:
                raise AccountError(tr("Could not reach Kuaishou: {error}", error=str(e)[:200])) from e
            except ValueError as e:
                raise AccountError(tr("Kuaishou returned an error: {error}", error=f"{r.status_code} not JSON")) from e
            top = (body.get("data") or {}) if isinstance(body, dict) else {}
            data = top.get("visionProfilePhotoList") or {}
            if top.get("result") == 400002 or data.get("result") == 400002:  # the slider captcha
                raise AccountError(tr(
                    "Kuaishou asks for a verification (slider captcha) before it shows this account. Open kuaishou.com "
                    "in your browser while signed in, pass the check, export the cookies again, then retry"))
            if r.status_code != 200 or data.get("result") != 1:
                raise AccountError(tr("Kuaishou returned an error: {error}",
                                      error=f"{r.status_code} result {data.get('result')}"))
            for feed in data.get("feeds") or []:
                if not isinstance(feed, dict):
                    continue
                name = name or (feed.get("author") or {}).get("name") or ""
                row = kuaishou_feed._clip(feed, 0, min_seconds=0)
                if row and row["id"] not in rows:
                    rows[row["id"]] = (row, feed["photo"]["photoUrl"])
            cursor = str(data.get("pcursor") or "")
            if len(rows) >= take or not cursor or cursor == "no_more":
                break
    out = [row for row, _ in list(rows.values())[:take]]
    kuaishou_feed._remember({r["id"].removeprefix("kuaishou:"): rows[r["id"]][1] for r in out})
    return name, out


READERS = {"weibo": _weibo, "douyin": _douyin, "kuaishou": _kuaishou}


def fetch(site: str, ident: str, take: int = TAKE) -> tuple[str, list[dict]]:
    """(account name, its videos newest first as `clip` rows). AccountError when the site says no."""
    if site not in READERS:
        raise AccountError(tr("Reading an account works on Kuaishou, Douyin and Weibo only"))
    name, rows = READERS[site](ident, take)
    rows = sorted(rows, key=lambda r: r.get("pubdate") or 0, reverse=True)
    return name, [{**r, "rank": i + 1, "uploader": r.get("uploader") or name} for i, r in enumerate(rows)]
