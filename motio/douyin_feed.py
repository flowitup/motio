"""Douyin's home recommendation feed (`douyin:feed`), its Featured tab (`douyin:featured`), its hot board
(`douyin:hot`) and keyword search (`search`) as rows for the app.

Douyin has no public category or ranking list a visitor can read. What it does show a visitor with no login is the
home feed (`/aweme/v1/web/tab/feed/`): a fresh draw of recommended videos, ~10 per answer. f2 (see douyin.py) signs
the request, Motio only calls it, with the same anonymous `ttwid` / `msToken` session the video download uses. It is not
a ranking and it has no category: the Trending screen says so.

Keyword search has two readers. Douyin's own search API (`/aweme/v1/web/general/search/single/`, signed by f2)
answers an anonymous session with status_code 2483 "please log in first": checked 2026-10-19 through f2's own signing
with a fresh ttwid/msToken, a browser-like Referer and every parameter the web page sends; the older
`/aweme/v1/web/search/item/` endpoint says the same and other `aid` values get "antispam" instead. So when the owner's
own signed-in douyin.com cookies are set up (`search.site_cookies`) the search goes that way. With no Douyin account
the public search site `so.douyin.com` is used instead: it shows the same results to a visitor with no login (checked
2026-10-19 from France), and its page asks an unsigned search endpoint of its own whose answer is the same
`aweme_info` cards; `chrome.py` reads it in a headless Chrome with a real browser user agent, because a plain HTTP
client gets the anti-spam answer and the default headless agent gets Douyin's captcha page. Nothing here logs in,
solves a captcha or fakes a session: a browser check Douyin still asks for is reported.

The Featured tab (`douyin:featured`, 精选 at douyin.com/jingxuan, the "all" tab) is another anonymous feed, a POST to
`/aweme/v2/web/module/feed/` (module 3003101) with the query signed by f2 the same way: ~20 videos per answer, mostly
long ones (several minutes up to ~45), a fresh draw each check.

The hot board (`douyin:hot`, Douyin's own "热点榜", the list a visitor sees at douyin.com/hot) is a ranking of topics,
not videos. Its list answers a visitor with no login (f2 signs it, the same way as the home feed), 50 topics with their
heat. A topic's lead video sits behind Douyin's browser check, so the videos of the first topics are read the way the
keyword search reads them: one headless Chrome on so.douyin.com asks the page's own search for each topic word. Rows are
the recent videos of the hottest topics, in the board's order, each marked with its topic (`category`).

Rows are `clip` rows like every other followed list; "Make video" then goes through `search.download`, which already
downloads a Douyin link with f2 (yt-dlp second). Photo posts, ads, live rooms and videos under 15 s are left out of the
feed; a search keeps short clips (the Scan screen wants what matches the keyword).
"""
import json
import time
from urllib.parse import quote, urlencode

from . import douyin
from . import search as search_engine
from .i18n import tr

PREFIX = "douyin:"
FEED = "douyin:feed"
HOT = "douyin:hot"
FEATURED = "douyin:featured"
NAMES = {FEED: "Douyin feed", HOT: "Douyin hot board", FEATURED: "Douyin featured"}
PAGES = 5  # answers read per check (about 10 videos each, some repeated)
MIN_SECONDS = 15
TAKE_MAX = 100  # a search reads at most this many rows
SEARCH_COUNT = 20  # rows asked per search answer (the web page asks about 20)
SEARCH_PAGES = 10  # answers read at most for one search (take <= TAKE_MAX needs 5)
_SEARCH_FILTER = '{"sort_type":"0","publish_time":"0","filter_duration":"","search_range":"0"}'
_PAUSE = 0.8  # between two answers, like douyin._pause
_HOT_PAUSE = 0.5  # between two topics' searches in the browser
WEB_PAGE = "https://so.douyin.com/?keyword="
WEB_API = "/s/fe/api/aweme/v2/search/msite/general/search/single/"  # the so.douyin.com page's own search endpoint
HOT_TOPICS = 20  # topics of the board whose videos are read (one search request each, in one browser)
HOT_PER_TOPIC = 3  # recent videos kept per topic
HOT_MAX_AGE_DAYS = 7  # a hot topic's video older than this is a leftover of the same words, not the news
HOT_LIST = "/aweme/v1/web/hot/search/list/"
WEB_PAGES = 12  # cards asked per answer is 10: this many answers cover TAKE_MAX
_WEB_COMMON = """
  const base = {
    aid: '581610', device_platform: 'webapp', search_source: 'normal_search',
    app_version: '290000', version_code: '290000', version_name: '29.0.0', webapp_platform: 'mac',
    innerWidth: '756', innerHeight: '469', pd: 'general', need_filter_settings: '1',
    'options[stream]': 'false',
  };
  const rowOf = (card) => {
    const info = card && card.data && card.data.aweme_info;
    if (!info) return null;
    return {
      aweme_id: info.aweme_id, desc: info.desc, create_time: info.create_time,
      video: {duration: info.video && info.video.duration,
              cover: {url_list: (info.video && info.video.cover && info.video.cover.url_list) || []}},
      statistics: {digg_count: info.statistics && info.statistics.digg_count,
                   play_count: info.statistics && info.statistics.play_count},
      author: {nickname: info.author && info.author.nickname},
    };
  };
"""
WEB_SCRIPT = """
(async () => {
  const word = __WORD__;
  const take = __TAKE__;
__COMMON__
  const rows = [];
  let searchId = '';
  let cursor = 0;
  let error = null;
  for (let page = 0; page < __PAGES__ && rows.length < take; page++) {
    const params = Object.assign({}, base, {
      keyword: word, offset: String(page * 10), count: '10', currentPage: String(page),
    });
    if (searchId) { params.search_id = searchId; params.search_request_id = searchId; params.cursor = String(cursor); }
    let answer;
    try {
      const reply = await fetch('__API__?' + new URLSearchParams(params).toString(),
                                {headers: {'Accept': 'application/json, text/plain, */*'}, credentials: 'include'});
      answer = await reply.json();
    } catch (e) {
      error = 'fetch';
      break;
    }
    const config = answer.business_config || {};
    const nil = config.search_nil_info;
    if (nil && nil.search_nil_type) { error = nil.search_nil_type; break; }
    for (const card of answer.business_data || []) {
      const row = rowOf(card);
      if (row) rows.push(row);
    }
    const next = config.next_page;
    if (!next || !config.has_more || !next.search_id) break;
    searchId = next.search_id;
    cursor = next.cursor;
  }
  return {rows: rows, error: error};
})()
""".replace("__COMMON__", _WEB_COMMON)
# The first answer (10 cards) of the search for each word, in one page: the hot board's topics.
HOT_SCRIPT = """
(async () => {
  const words = __WORDS__;
__COMMON__
  const topics = [];
  let error = null;
  for (const word of words) {
    const params = Object.assign({}, base, {keyword: word, offset: '0', count: '10', currentPage: '0'});
    let answer;
    try {
      const reply = await fetch('__API__?' + new URLSearchParams(params).toString(),
                                {headers: {'Accept': 'application/json, text/plain, */*'}, credentials: 'include'});
      answer = await reply.json();
    } catch (e) {
      error = 'fetch';
      break;
    }
    const nil = (answer.business_config || {}).search_nil_info;
    if (nil && nil.search_nil_type) { error = nil.search_nil_type; break; }
    const rows = [];
    for (const card of answer.business_data || []) {
      const row = rowOf(card);
      if (row) rows.push(row);
    }
    topics.push({word: word, rows: rows});
    await new Promise((done) => setTimeout(done, __PAUSE__));
  }
  return {topics: topics, error: error};
})()
""".replace("__COMMON__", _WEB_COMMON)


class FeedError(RuntimeError):
    pass


def parse(target: str) -> str:
    """"douyin:feed" → "feed", "douyin:hot" → "hot", "douyin:featured" → "featured". ValueError otherwise."""
    if target == FEED:
        return "feed"
    if target == HOT:
        return "hot"
    if target == FEATURED:
        return "featured"
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


FEATURED_PAGE = "/aweme/v2/web/module/feed/"  # the 精选 (Featured) tab's own feed, a POST with the query signed
FEATURED_MODULE = "3003101"  # its module id (the "all" tab: no category tag)


async def _featured_page(index: int) -> dict:
    """One answer of the Featured tab's feed (f2 signs it, same anonymous session as `_page`). Tests fake this.

    f2 has no model for this endpoint, so Motio gives f2's own signer the address (`bogus_manager.str_2_endpoint`,
    nothing copied) and f2's `_fetch_post_json` makes the request.
    """
    crawler_cls, _, conf, tokens = douyin._f2()
    try:
        ms_token = tokens.gen_real_msToken()
    except Exception:
        ms_token = tokens.gen_false_msToken()
    kwargs = {"headers": conf.headers(), "proxies": conf.proxies(), "cookie": f"ttwid={tokens.gen_ttwid()}",
              "timeout": 10, "max_retries": 2}
    params = {"device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web", "module_id": FEATURED_MODULE,
              "count": "20", "filterGids": "", "presented_ids": "", "refresh_index": str(index), "refer_id": "",
              "refer_type": "10", "pull_type": "0", "Seo-Flag": "0", "tag_id": "", "active_id": "",
              "use_lite_type": "1", "xigua_user": "0", "pc_client_type": "1", "update_version_code": "170400",
              "support_h265": "0", "support_dash": "0", "version_code": "170400", "version_name": "17.4.0",
              "cookie_enabled": "true", "browser_language": "zh-CN", "browser_platform": "MacIntel",
              "browser_name": "Chrome", "browser_version": "125.0.0.0", "browser_online": "true",
              "engine_name": "Blink", "engine_version": "125.0.0.0", "os_name": "Mac OS", "os_version": "10.15.7",
              "platform": "PC", "msToken": ms_token}
    async with crawler_cls(kwargs) as crawler:
        endpoint = crawler.bogus_manager.str_2_endpoint(crawler.headers.get("User-Agent"),
                                                        "https://www.douyin.com" + FEATURED_PAGE + "?"
                                                        + urlencode(params))
        raw = await crawler._fetch_post_json(endpoint, data={})
    return raw if isinstance(raw, dict) else {}


def _clip(post: dict, rank: int, min_seconds: float = MIN_SECONDS) -> dict | None:
    video = post.get("video") or {}
    seconds = (video.get("duration") or 0) / 1000
    desc = " ".join(str(post.get("desc") or "").split())
    pid = str(post.get("aweme_id") or "")
    if not pid.isdigit() or not desc or post.get("is_ads") or post.get("images") or seconds < min_seconds:
        return None
    stat = post.get("statistics") or {}
    cover = next((u for u in (video.get("cover") or {}).get("url_list") or [] if str(u).startswith("https://")), None)
    return {"id": f"douyin:{pid}", "site": "douyin", "url": f"https://www.douyin.com/video/{pid}", "title": desc,
            "uploader": (post.get("author") or {}).get("nickname") or "", "duration": round(seconds),
            "views": stat.get("play_count") or None, "likes": stat.get("digg_count") or None,
            "pubdate": post.get("create_time") or None, "category": None, "thumbnail": cover, "rank": rank}


def fetch(target: str, take: int = 50) -> list[dict]:
    """The videos of a list as `clip` rows: the recommended feed, or the hot board's. FeedError when Douyin cannot be
    reached or answers nothing."""
    kind = parse(target)
    if kind == "hot":
        return _fetch_hot(take)
    reader = _featured_page if kind == "featured" else _page
    found: dict[str, dict] = {}
    errors: list[Exception] = []
    answered = False
    for i in range(PAGES):
        if i:
            time.sleep(_PAUSE)
        try:
            raw = douyin._run(reader(i + 1))
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


# ---------- hot board ----------
async def _board() -> dict:
    """The hot board's answer (Douyin's own list at douyin.com/hot), signed by f2 like the home feed.

    f2 has no model for this endpoint, so Motio gives f2's own signer the address (`bogus_manager.str_2_endpoint`,
    nothing copied) and f2's `_fetch_get_json` makes the request, with the same anonymous ttwid / msToken session.
    Tests fake this, so pytest never touches Douyin.
    """
    crawler_cls, _, conf, tokens = douyin._f2()
    try:
        ms_token = tokens.gen_real_msToken()
    except Exception:
        ms_token = tokens.gen_false_msToken()
    kwargs = {"headers": conf.headers(), "proxies": conf.proxies(), "cookie": f"ttwid={tokens.gen_ttwid()}",
              "timeout": 10, "max_retries": 2}
    params = {"device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web", "detail_list": "1",
              "source": "6", "pc_client_type": "1", "version_code": "190500", "version_name": "19.5.0",
              "cookie_enabled": "true", "browser_language": "zh-CN", "browser_platform": "MacIntel",
              "browser_name": "Chrome", "browser_version": "125.0.0.0", "browser_online": "true",
              "engine_name": "Blink", "os_name": "Mac OS", "platform": "PC", "msToken": ms_token}
    async with crawler_cls(kwargs) as crawler:
        endpoint = crawler.bogus_manager.str_2_endpoint(crawler.headers.get("User-Agent"),
                                                        "https://www.douyin.com" + HOT_LIST + "?" + urlencode(params))
        raw = await crawler._fetch_get_json(endpoint)
    return raw if isinstance(raw, dict) else {}


def _topics(raw: dict, take: int = HOT_TOPICS) -> list[dict]:
    """The board's topics, hottest first: {word, hot, sentence_id}. A topic with no words is left out."""
    out: list[dict] = []
    for item in ((raw.get("data") or {}).get("word_list") or []):
        word = " ".join(str((item or {}).get("word") or "").split()) if isinstance(item, dict) else ""
        if word and all(t["word"] != word for t in out):
            out.append({"word": word, "hot": item.get("hot_value") or 0,
                        "sentence_id": str(item.get("sentence_id") or "")})
        if len(out) >= take:
            break
    return out


def _hot_rows(answer, topics: list[dict], now: float | None = None) -> tuple[list[dict], str]:
    """The `clip` rows of the hot-board videos and the refusal the browser reported ("" when there was none).

    Per topic, in the board's order: its recent videos (a post older than HOT_MAX_AGE_DAYS is an old video that
    matches the words, not today's news), at most HOT_PER_TOPIC, never a video twice. Each row's `category` is the
    topic.
    """
    cutoff = (now if now is not None else time.time()) - HOT_MAX_AGE_DAYS * 86400
    heat = {t["word"]: t["hot"] for t in topics}
    rows: dict[str, dict] = {}
    for topic in (answer or {}).get("topics") or []:
        word = str((topic or {}).get("word") or "")
        kept = 0
        for post in (topic or {}).get("rows") or []:
            if kept >= HOT_PER_TOPIC:
                break
            row = _clip(post, 0) if isinstance(post, dict) else None
            if not row or row["id"] in rows or (row["pubdate"] or 0) < cutoff:
                continue
            rows[row["id"]] = {**row, "category": word, "views": row["views"] or heat.get(word) or None}
            kept += 1
    return [{**row, "rank": i + 1} for i, row in enumerate(rows.values())], str((answer or {}).get("error") or "")


def _fetch_hot(take: int = 50) -> list[dict]:
    """The recent videos of the hottest topics on Douyin's hot board, as `clip` rows. FeedError with an English
    message when the board or the browser cannot be read.

    The board itself needs no login. A topic's videos are read in one headless Chrome (`chrome.py`) on the public
    search site, no account; a browser check Douyin asks for is reported, never worked around.
    """
    try:
        raw = douyin._run(_board())
    except Exception as e:  # f2 not loaded / offline / signature out of date
        if douyin._is_network_error(e):
            raise FeedError(tr("Could not connect to Douyin. Check your internet connection (or VPN, proxy, "
                               "DNS filter), then try again")) from e
        raise FeedError(tr("Douyin returned an error: {error}", error=str(e)[:200])) from e
    topics = _topics(raw)
    if not topics:
        raise FeedError(tr("Douyin's hot board gave no topics"))
    from . import chrome  # the other lists never pay for this import

    script = (HOT_SCRIPT.replace("__WORDS__", json.dumps([t["word"] for t in topics], ensure_ascii=False))
                        .replace("__API__", WEB_API).replace("__PAUSE__", str(int(_HOT_PAUSE * 1000))))
    try:
        answer = chrome.evaluate(WEB_PAGE + quote(topics[0]["word"], safe=""), script, timeout=120)
    except chrome.Missing as e:
        raise FeedError(tr("Douyin's hot board needs Google Chrome (or Chromium / Edge) installed to read its videos. "
                           "Install it, then try again")) from e
    except chrome.ChromeError as e:
        raise FeedError(tr("Could not run Google Chrome for the Douyin hot board: {error}", error=str(e)[:200])) from e
    rows, refused = _hot_rows(answer, topics)
    if rows:  # a refusal on a later topic keeps what the first ones gave
        return rows[:take]
    if refused in ("verify_check", "antispam_check", "hit_shark"):
        raise FeedError(tr("Douyin asked for a browser verification for this search (it looked like a bot). Try "
                           "again in a minute"))
    raise FeedError(tr("Douyin gave no recent videos for its hot topics"))


# ---------- keyword search ----------
def _cookies() -> dict[str, str]:
    """The owner's own signed-in douyin.com cookies, name → value ({} when none are set up). Tests fake this."""
    return search_engine.site_cookies("douyin.com")


async def _search_page(keyword: str, offset: int, count: int, search_id: str, cookies: dict) -> dict:
    """One answer of Douyin's general search, signed by f2. Tests fake this, so pytest never touches Douyin.

    f2 has the endpoint and the model but no crawler method for it: its signing is `bogus_manager.model_2_endpoint`
    (a_bogus) then `_fetch_get_json`, exactly what fetch_user_post does (see docs/DOUYIN_F2.md).
    """
    crawler_cls, _, conf, tokens = douyin._f2()
    from f2.apps.douyin.api import DouyinAPIEndpoints  # f2 is loaded by now (douyin._f2 above)
    from f2.apps.douyin.model import PostSearch

    jar = dict(cookies or {})
    try:  # the owner's own msToken when it is there, else a fresh one (f2's token server can be unreachable)
        ms_token = jar.get("msToken") or tokens.gen_real_msToken()
    except Exception:
        ms_token = jar.get("msToken") or tokens.gen_false_msToken()
    jar.setdefault("msToken", ms_token)
    if "ttwid" not in jar:  # a login cookie usually has both; the guest fallback needs them
        jar["ttwid"] = tokens.gen_ttwid()
    headers = dict(conf.headers())
    headers["Referer"] = "https://www.douyin.com/search/" + quote(keyword, safe="")  # ASCII: f2 checks the encoding
    kwargs = {"headers": headers, "proxies": conf.proxies(),
              "cookie": "; ".join(f"{name}={value}" for name, value in jar.items()), "timeout": 10, "max_retries": 2}
    params = PostSearch(filter_selected=quote(_SEARCH_FILTER, safe=""), keyword=quote(keyword, safe=""),
                        search_id=search_id, offset=offset, count=count, msToken=ms_token)
    async with crawler_cls(kwargs) as crawler:
        endpoint = crawler.bogus_manager.model_2_endpoint(crawler.headers.get("User-Agent"),
                                                          DouyinAPIEndpoints.POST_SEARCH, params.model_dump())
        raw = await crawler._fetch_get_json(endpoint)
    return raw if isinstance(raw, dict) else {}


def _refusal(raw: dict) -> str:
    """"login" / "risk" / "error" when Douyin refused this search answer, "" when it answered with data or nothing."""
    code = raw.get("status_code")
    nil = raw.get("search_nil_info") or {}
    if code == 2483:  # "请先登录，再继续搜索吧" (please log in first, then search)
        return "login"
    if nil.get("search_nil_type") == "antispam_check" or nil.get("search_nil_item") == "hit_shark":
        return "risk"
    return "error" if code not in (0, None) else ""


def _refused(kind: str, raw: dict) -> FeedError:
    if kind == "login":
        return FeedError(tr("Douyin asks for a login before it shows search results. Sign in to douyin.com in your "
                            "browser, then set the browser or the exported cookie file in Settings → Browser cookies"))
    if kind == "risk":
        return FeedError(tr("Douyin refused the search (the request looked like a bot). Open douyin.com in your "
                            "browser while signed in, then try again"))
    return FeedError(tr("Douyin returned an error: {error}",
                        error=f"{raw.get('status_code')} {raw.get('status_msg') or ''}".strip()[:200]))


def _search_post(item) -> dict | None:
    """The post inside one general-search card. Douyin nests it as {"type": 1, "aweme_info": {...}}; some replies put
    the post itself in the list, so both shapes are accepted. None for a user / music / hashtag card or anything
    else."""
    if not isinstance(item, dict):
        return None
    post = item.get("aweme_info")
    if isinstance(post, dict):
        return post
    return item if "aweme_id" in item and ("video" in item or "statistics" in item) else None


def _web_rows(answer) -> tuple[list[dict], str]:
    """The `clip` rows of one so.douyin.com answer and the refusal it reported ("" when it was a normal answer)."""
    rows: dict[str, dict] = {}
    for post in (answer or {}).get("rows") or []:
        row = _clip(post, 0, min_seconds=0) if isinstance(post, dict) else None
        if row and row["id"] not in rows:
            rows[row["id"]] = row
    return [{**row, "rank": i + 1} for i, row in enumerate(rows.values())], str((answer or {}).get("error") or "")


def search_web(keyword: str, take: int = 50) -> list[dict]:
    """Videos for a keyword from Douyin's public search site, with no account, as `clip` rows.

    `chrome.evaluate` opens `so.douyin.com` in a headless Chrome and runs the page's own search request in the page
    context (the page's cookies and session, nothing signed); the answer carries the same `aweme_info` cards as the
    app's other Douyin reads. FeedError when Chrome is missing or cannot run, when Douyin asks for a browser
    verification (reported, never solved) or when there is no video.
    """
    word = " ".join(str(keyword or "").split())
    if not word:
        raise FeedError(tr("Type a keyword to search Douyin"))
    take = max(1, min(int(take or 50), TAKE_MAX))
    from . import chrome  # a scan of the other sites never pays for this import

    script = (WEB_SCRIPT.replace("__WORD__", json.dumps(word, ensure_ascii=False))
                        .replace("__TAKE__", str(take)).replace("__PAGES__", str(WEB_PAGES))
                        .replace("__API__", WEB_API))
    try:
        answer = chrome.evaluate(WEB_PAGE + quote(word, safe=""), script, timeout=90)
    except chrome.Missing as e:
        raise FeedError(tr("Douyin keyword search needs Google Chrome (or Chromium / Edge) installed. Install it, or "
                           "set your own douyin.com cookies in Settings → Browser cookies")) from e
    except chrome.ChromeError as e:
        raise FeedError(tr("Could not run Google Chrome for the Douyin search: {error}", error=str(e)[:200])) from e
    rows, refused = _web_rows(answer)
    if rows:  # a refusal on a later page keeps what the first pages gave
        return rows[:take]
    if refused in ("verify_check", "antispam_check", "hit_shark"):
        raise FeedError(tr("Douyin asked for a browser verification for this search (it looked like a bot). Try "
                           "again in a minute"))
    if refused == "params_check":
        raise FeedError(tr("Douyin returned an error: {error}", error="params_check"))
    raise FeedError(tr("Douyin gave no videos for this keyword"))


def _search_api(keyword: str, take: int = 50) -> list[dict]:
    """Douyin's own general search, signed by f2, with the owner's own signed-in douyin.com cookies.

    At most TAKE_MAX rows. FeedError with an English message when Douyin cannot be reached, wants a login it does not
    have, or refuses the search. Only called when `_cookies()` is not empty (see `search`).
    """
    word = " ".join(str(keyword or "").split())
    if not word:
        raise FeedError(tr("Type a keyword to search Douyin"))
    take = max(1, min(int(take or 50), TAKE_MAX))
    cookies = _cookies()
    found: dict[str, dict] = {}
    errors: list[Exception] = []
    refused: tuple[str, dict] | None = None
    answered = False
    offset, search_id = 0, ""
    for i in range(SEARCH_PAGES):
        if i:
            time.sleep(_PAUSE)
        try:
            raw = douyin._run(_search_page(word, offset, max(1, min(SEARCH_COUNT, take - len(found))), search_id,
                                           cookies))
        except Exception as e:  # f2 not loaded / offline / signature out of date: say so once, keep what was read
            errors.append(e)
            if douyin._is_network_error(e) or not answered:
                break
            continue
        answered = True
        kind = _refusal(raw)
        if kind:
            refused = (kind, raw)
            break
        for item in raw.get("data") or []:  # general-search cards: {"type": 1, "aweme_info": {...post...}}
            post = _search_post(item)
            row = _clip(post, 0, min_seconds=0) if post else None
            if row and row["id"] not in found:
                found[row["id"]] = row
        search_id = str((raw.get("log_pb") or {}).get("impr_id") or search_id)
        nxt = raw.get("cursor")
        if len(found) >= take or not raw.get("has_more") or not isinstance(nxt, int) or nxt <= offset:
            break
        offset = nxt
    if found:  # a refusal or a failure after the first answer keeps what was read
        return [{**row, "rank": i + 1} for i, row in enumerate(list(found.values())[:take])]
    if refused:
        raise _refused(*refused)
    if errors:
        e = errors[0]
        if douyin._is_network_error(e):
            raise FeedError(tr("Could not connect to Douyin. Check your internet connection (or VPN, proxy, "
                               "DNS filter), then try again")) from e
        raise FeedError(tr("Douyin returned an error: {error}", error=str(e)[:200])) from e
    raise FeedError(tr("Douyin gave no videos for this keyword"))


def search(keyword: str, take: int = 50) -> list[dict]:
    """Videos for a keyword in Douyin's own order, as `clip` rows (id, url, title, uploader, duration, views, likes,
    pubdate, thumbnail, rank). At most TAKE_MAX rows. FeedError with an English message when it cannot be read.

    With the owner's own signed-in douyin.com cookies set up (`search.site_cookies`, the same pattern as Kuaishou in
    accounts.py) this is Douyin's own search API; if that refuses (an expired cookie, say) the public search site is
    tried instead. Without cookies it is the public search site, read in a headless Chrome (`chrome.py`) with no
    account at all. A login or a browser check Douyin asks for is reported as an error, never worked around.
    """
    word = " ".join(str(keyword or "").split())
    if not word:
        raise FeedError(tr("Type a keyword to search Douyin"))
    take = max(1, min(int(take or 50), TAKE_MAX))
    if _cookies():
        try:
            return _search_api(word, take)
        except FeedError as e:
            try:
                return search_web(word, take)
            except FeedError:
                raise e from None
    return search_web(word, take)
