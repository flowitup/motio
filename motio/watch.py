"""Nguồn theo dõi: kênh / playlist YouTube, không gian Bilibili, tìm kiếm đã lưu, xếp hạng Bilibili → trang "Video mới".

yt-dlp chỉ liệt kê được kênh và tìm kiếm trên YouTube, Bilibili; Douyin, Facebook chỉ tải từng video (dán link
vào Tạo video). Danh sách phẳng (extract_flat) không có ngày đăng, nên "mới" = chưa thấy bao giờ.
Bảng xếp hạng / thịnh hành / "mỗi tuần một xem" của Bilibili (kind "trending") đọc qua API công khai, xem trending.py.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx
from yt_dlp import YoutubeDL

from . import accounts, db, douyin_feed, kuaishou_feed, llm, search, topic, trending, weibo_feed
from .i18n import tr

KINDS = ("channel", "playlist", "space", "search", "trending", "account")
SITES = ("youtube", "bilibili")
# the other trending lists; Bilibili's is trending.py
FEEDS = {"kuaishou": kuaishou_feed, "douyin": douyin_feed, "weibo": weibo_feed}
FIRST_TAKE = 10  # nguồn mới thêm: hiện 10 video mới nhất mỗi danh sách, phần còn lại coi như đã thấy
TRENDING_TAKE = 20  # bảng xếp hạng mới thêm: hiện 20 video đầu bảng
PER_LIST = 15  # mỗi lần kiểm tra đọc tối đa 15 mục đầu của mỗi danh sách
MAX_DETAILS = 20  # số trang video tối đa đọc thêm mỗi lượt (Bilibili chỉ trả link, không có tiêu đề)
MAX_WATCHES = 50
YT_TABS = ("videos", "shorts")  # kênh YouTube: theo dõi cả video thường và Shorts
# Tìm kiếm YouTube đã bỏ sắp xếp theo ngày: lọc "tải lên tháng này" + chỉ video (tuần này hay trả về rỗng)
YT_THIS_MONTH = "EgQIBBAB"
VIDEO_IE = {"youtube": "Youtube", "bilibili": "BiliBili"}
# A flat YouTube list has no upload time, but the channel's / playlist's RSS feed has it for its latest 15 videos
YT_FEED = "https://www.youtube.com/feeds/videos.xml"
_FEED_ENTRY = re.compile(r"<yt:videoId>([\w-]+)</yt:videoId>.*?<published>([^<]+)</published>", re.S)

_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_YT_CHANNEL = re.compile(r"^/(@[^/]+|channel/UC[\w-]+|c/[^/]+|user/[^/]+)")
NOT_A_LIST = "This is a link to a single video: paste a channel or playlist link, or use Projects → New video"
UNSUPPORTED = ("Only YouTube channels and playlists, Bilibili spaces, Kuaishou / Douyin / Weibo accounts or search "
               "keywords can be followed. Facebook and other sites: paste each video link in Projects → New video")
BILI_BLOCKED = ("Bilibili blocks requests without a login: pick a browser or set a cookie file in "
                "Settings → Browser cookies")
_BLOCK = re.compile(r"\b(412|352|401)\b")

# Bilibili: số av → mã BV (thuật toán công khai của Bilibili), để cùng một video từ tìm kiếm (av) và không gian (BV)
# không bị đếm hai lần
_BV_XOR, _BV_MAX, _BV_BASE = 23442827791579, 1 << 51, 58
_BV_ALPHABET = "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf"
_BV_ORDER = (8, 7, 0, 5, 1, 3, 2, 4, 6)


def classify(text: str, site: str = "youtube") -> dict:
    """Link kênh / playlist / không gian, hoặc từ khoá tìm → {kind, site, target, name}. ValueError nếu không được."""
    text = " ".join((text or "").split())
    if not text:
        raise ValueError(tr("Paste a channel / playlist link or enter search keywords"))
    if got := accounts.identify(text):  # a Kuaishou / Douyin / Weibo account page
        return {"kind": "account", "site": got[0], "target": accounts.target(*got), "name": None}
    if text.startswith(trending.PREFIX):  # "bilibili:ranking:181", "bilibili:popular", "bilibili:weekly"
        return {"kind": "trending", "site": "bilibili", "target": text, "name": trending.name(text)}
    if text.startswith(kuaishou_feed.PREFIX):  # "kuaishou:featured"
        return {"kind": "trending", "site": "kuaishou", "target": text, "name": kuaishou_feed.name(text)}
    if text.startswith(douyin_feed.PREFIX):  # "douyin:feed"
        return {"kind": "trending", "site": "douyin", "target": text, "name": douyin_feed.name(text)}
    if text.startswith(weibo_feed.PREFIX):  # "weibo:hot"
        return {"kind": "trending", "site": "weibo", "target": text, "name": weibo_feed.name(text)}
    if not re.match(r"^https?://", text, re.I):
        if site not in SITES:
            raise ValueError(tr("Search works only on YouTube or Bilibili, not {site}", site=site))
        return {"kind": "search", "site": site, "target": text[:200], "name": text[:200]}
    u = urlparse(text)
    host = (u.hostname or "").lower()
    q = parse_qs(u.query)
    if host in _YT_HOSTS:
        if u.path == "/playlist" and q.get("list"):
            return {"kind": "playlist", "site": "youtube", "name": None,
                    "target": f"https://www.youtube.com/playlist?list={q['list'][0]}"}
        if u.path == "/results" and q.get("search_query"):
            query = " ".join(q["search_query"][0].split())[:200]
            return {"kind": "search", "site": "youtube", "target": query, "name": query}
        if m := _YT_CHANNEL.match(u.path):
            return {"kind": "channel", "site": "youtube", "target": f"https://www.youtube.com/{m[1]}", "name": None}
        if u.path == "/watch" or u.path.startswith(("/shorts/", "/live/")):
            raise ValueError(tr(NOT_A_LIST))
    elif host == "youtu.be" or (host.endswith("bilibili.com") and u.path.startswith("/video/")):
        raise ValueError(tr(NOT_A_LIST))
    elif host == "space.bilibili.com" and (m := re.match(r"^/(\d+)", u.path)):
        if u.path[m.end():].strip("/") in ("", "video", "upload/video"):
            return {"kind": "space", "site": "bilibili", "target": f"https://space.bilibili.com/{m[1]}/video",
                    "name": None}
        return {"kind": "playlist", "site": "bilibili", "target": text, "name": None}  # series, favourites…
    elif host == "search.bilibili.com" and q.get("keyword"):
        query = " ".join(q["keyword"][0].split())[:200]
        return {"kind": "search", "site": "bilibili", "target": query, "name": query}
    raise ValueError(tr(UNSUPPORTED))


def add(text: str, site: str = "youtube") -> int:
    """Thêm nguồn (chưa kiểm tra). ValueError nếu sai / trùng / quá nhiều."""
    w = classify(text, site)
    if db.find_watch(w["site"], w["target"]):
        raise ValueError(tr("This source is already in the list"))
    if len(db.list_watches()) >= MAX_WATCHES:
        raise ValueError(tr("At most {n} sources", n=MAX_WATCHES))
    return db.add_watch(w["kind"], w["site"], w["target"], w["name"])


# ---------- đọc danh sách ----------
class _Silent:
    """yt-dlp vẫn in ERROR ra stderr dù quiet; lỗi đã được bắt và lưu vào nguồn."""
    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def _opts(site: str, n: int | None = None) -> dict:
    opts = {**search._base(), "skip_download": True, "logger": _Silent()}
    if n:
        opts |= {"extract_flat": "in_playlist", "playlistend": n}
    if site == "bilibili":
        opts |= search._cookie_opts()  # không gian Bilibili hay chặn (412 / -352) khi chưa đăng nhập
    return opts


def _urls(w: dict) -> list[str]:
    if w["kind"] in ("trending", "account"):  # đọc bằng trending.fetch / accounts.fetch, không qua yt-dlp
        return []
    if w["kind"] == "channel" and w["site"] == "youtube":
        return [f"{w['target']}/{tab}" for tab in YT_TABS]
    if w["kind"] == "search":
        if w["site"] == "youtube":
            return [f"https://www.youtube.com/results?search_query={quote_plus(w['target'])}&sp={YT_THIS_MONTH}"]
        return [f"bilisearch{PER_LIST}:{w['target']}"]
    return [w["target"]]


def _entries(info: dict) -> list[dict]:
    """Mục của danh sách, kể cả danh sách lồng nhau."""
    out = []
    for e in info.get("entries") or []:
        if isinstance(e, dict):
            out += _entries(e) if e.get("entries") is not None else [e]
    return out


def _https(url: str | None) -> str | None:
    return "https:" + url[5:] if url and url.startswith("http:") else url


def _thumb(e: dict) -> str | None:
    return _https(e.get("thumbnail") or ((e.get("thumbnails") or [{}])[-1] or {}).get("url"))


def av_to_bv(aid: int) -> str:
    tmp, out = (_BV_MAX | aid) ^ _BV_XOR, [""] * 9
    for pos in _BV_ORDER:
        out[pos] = _BV_ALPHABET[tmp % _BV_BASE]
        tmp //= _BV_BASE
    return "BV1" + "".join(out)


def _clip(e: dict, w: dict, owner: str | None) -> dict | None:
    vid = e.get("id")
    if not vid or e.get("ie_key") not in (None, VIDEO_IE[w["site"]]):
        return None  # kênh, playlist con, bộ sưu tập…
    if e.get("live_status") in ("is_live", "is_upcoming"):
        return None
    url = e.get("url") or e.get("webpage_url") or ""
    thumb = _thumb(e)
    if w["site"] == "youtube":
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={vid}"
        thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    else:
        m = re.search(r"bilibili\.com/video/(BV\w+|av(\d+))", url)
        if not m:
            return None  # khoá học trả phí (/cheese/), phim bộ… không phải video thường
        vid = m[1] if m[1].startswith("BV") else av_to_bv(int(m[2]))
        url = f"https://www.bilibili.com/video/{vid}"
    return {"id": f"{w['site']}:{vid}", "watch_id": w["id"], "site": w["site"], "url": _https(url),
            "title": (e.get("title") or "").strip(), "uploader": e.get("channel") or e.get("uploader") or owner,
            "duration": e.get("duration") or None, "views": e.get("view_count"), "thumbnail": thumb,
            "pubdate": _stamp(e)}


def _stamp(e: dict) -> float | None:
    """The upload time of a yt-dlp entry (Unix seconds), when it has one."""
    ts = e.get("timestamp") or e.get("release_timestamp")
    if ts:
        return float(ts)
    try:
        return datetime.strptime(str(e.get("upload_date")), "%Y%m%d").timestamp()
    except ValueError:
        return None


def _feed_dates(w: dict, info: dict) -> dict[str, float]:
    """`youtube:<id>` → upload time of the latest videos of a YouTube channel or playlist ({} when unreadable)."""
    if w["site"] != "youtube" or w["kind"] not in ("channel", "playlist"):
        return {}
    ident = info.get("channel_id") if w["kind"] == "channel" else info.get("id")
    if not ident or not re.fullmatch(r"[\w-]+", str(ident)):
        return {}
    key = "channel_id" if w["kind"] == "channel" else "playlist_id"
    try:
        r = httpx.get(YT_FEED, params={key: ident}, timeout=10, follow_redirects=True)
        r.raise_for_status()
        return {f"youtube:{vid}": datetime.fromisoformat(at).timestamp() for vid, at in _FEED_ENTRY.findall(r.text)}
    except (httpx.HTTPError, ValueError):
        return {}


def _details(c: dict) -> dict:
    """Danh sách Bilibili chỉ có link: đọc trang video để lấy tiêu đề, kênh, độ dài, lượt xem, ảnh.

    Không đọc được: bị chặn (412…) thì bỏ qua để lượt sau thử lại; video đã xoá / giới hạn vùng thì coi như đã thấy.
    """
    try:
        with YoutubeDL(_opts(c["site"])) as y:
            info = y.extract_info(c["url"], download=False, process=False) or {}
    except Exception as e:
        return {**c, "status": "retry" if _BLOCK.search(str(e)) else "old"}
    return {**c, "title": (info.get("title") or "").strip(), "uploader": info.get("uploader") or c["uploader"],
            "duration": info.get("duration") or c["duration"], "views": info.get("view_count") or c["views"],
            "thumbnail": _thumb(info) or c["thumbnail"], "pubdate": c.get("pubdate") or _stamp(info)}


def _short(e: Exception, site: str) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).removeprefix("ERROR: ").strip()
    if site == "bilibili" and _BLOCK.search(msg):
        msg = f"{tr(BILI_BLOCKED)} ({msg[:120]})"
    return msg[:300]


def check(w: dict) -> dict:
    """Đọc lại một nguồn, lưu video chưa thấy. Lần đầu: 10 video mới nhất mỗi danh sách, phần còn lại = đã thấy."""
    first = not w["last_checked"]
    found: dict[str, dict] = {}
    owner, errors, ok = None, [], False
    dates: dict[str, float] = {}
    if w["kind"] == "trending":
        try:
            batch = FEEDS.get(w["site"], trending).fetch(w["target"])
        except (trending.TrendingError, kuaishou_feed.FeedError, douyin_feed.FeedError,
                weibo_feed.FeedError, ValueError) as e:
            errors.append(str(e)[:300])
        else:
            ok = True
            for i, c in enumerate(batch):
                found[c["id"]] = {**c, "watch_id": w["id"], "status": "old" if first and i >= TRENDING_TAKE else "new"}
    if w["kind"] == "account":
        try:
            owner, batch = accounts.fetch(w["site"], accounts.split(w["target"])[1], PER_LIST * 2)
        except (accounts.AccountError, TypeError, ValueError) as e:
            errors.append(str(e)[:300])
        else:
            ok = True
            for i, c in enumerate(batch):
                found[c["id"]] = {**c, "watch_id": w["id"], "status": "old" if first and i >= FIRST_TAKE else "new"}
    for url in _urls(w):
        try:
            with YoutubeDL(_opts(w["site"], PER_LIST)) as y:
                info = y.extract_info(url, download=False) or {}
        except Exception as e:
            errors.append(_short(e, w["site"]))
            continue
        ok = True
        if not dates:
            dates = _feed_dates(w, info)
        if w["kind"] != "search":
            owner = owner or info.get("channel") or info.get("uploader") or info.get("title")
        batch = [c for c in (_clip(e, w, owner) for e in _entries(info)[:PER_LIST]) if c]
        for i, c in enumerate(batch):
            c["status"] = "old" if first and i >= FIRST_TAKE else "new"
            if c["id"] not in found or c["status"] == "new":
                found[c["id"]] = c
    for cid, ts in dates.items():
        if cid in found and not found[cid].get("pubdate"):
            found[cid]["pubdate"] = ts
    db.fill_pubdates(dates)  # videos seen before the feed was read
    known = db.known_clip_ids(list(found))
    fresh = [c for c in found.values() if c["id"] not in known]
    missing = [c for c in fresh if not c["title"] or (w["site"] == "bilibili" and not c.get("pubdate"))]
    need = sorted(missing, key=lambda c: c["status"] != "new")[:MAX_DETAILS]  # the new ones first
    if need:
        with ThreadPoolExecutor(max_workers=4) as ex:
            done = {c["id"]: c for c in ex.map(_details, need)}
        fresh = [done.get(c["id"], c) for c in fresh]
    fresh = [c for c in fresh if c["status"] != "retry"]
    db.insert_clips(fresh)
    if w["kind"] == "space":  # không gian Bilibili không trả tên kênh: lấy từ trang video
        owner = owner or next((c["uploader"] for c in fresh if c["uploader"]), None)
    fields = {"last_error": " · ".join(errors) or None}
    if ok:
        fields["last_checked"] = time.time()
    if owner and not w["name"]:
        fields["name"] = owner
    db.update_watch(w["id"], **fields)
    return {"new": [c["id"] for c in fresh if c["status"] == "new"], "error": fields["last_error"]}


# ---------- tiêu đề Pháp + điểm ----------
SCORE_SYSTEM = """Tu es rédacteur en chef d'une chaîne francophone (TikTok, Reels, Shorts) de vidéos explicatives
qui partent de vidéos trouvées en ligne (YouTube, Bilibili), sur tous les thèmes. Tu réponds uniquement en JSON."""

SCORE_PROMPT = """Voici de nouvelles vidéos publiées par des chaînes et des recherches suivies. Pour CHAQUE vidéo :
- title_fr : titre français court et accrocheur du sujet, factuel, sans inventer de détails (max 90 caractères)
- score : 0–100, intérêt pour un public français ET potentiel comme source d'une vidéo explicative de 60–90 s
  (images parlantes, sujet qu'on peut expliquer et remettre en contexte). Baisse le score pour les clips
  musicaux, les podcasts face caméra, les directs, les compilations sans sujet et la publicité.
- reason : 5–12 mots expliquant le score

Une durée null est inconnue (fréquent pour les Shorts) : ne baisse pas le score pour autant.
Pour une vidéo d'un classement Bilibili (catégorie, likes, âge en heures), le score mesure aussi le potentiel d'un
doublage ou d'un commentaire en français : paroles claires et courtes, situation compréhensible sans connaître la
Chine, peu de texte incrusté. Un classement dit ce qui buzze, pas ce qu'on a le droit de reprendre : ne le
suppose pas.

Réponds avec une liste JSON d'objets {{"id", "title_fr", "score", "reason"}}.

Vidéos :
{items}"""


def _int(v) -> int | None:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return None


def _trend_fields(c: dict) -> dict:
    """Catégorie, likes et âge d'une vidéo de classement (absents des autres sources)."""
    out = {"catégorie": c.get("category"), "likes": c.get("likes"),
           "âge_h": round((time.time() - c["pubdate"]) / 3600) if c.get("pubdate") else None}
    return {k: v for k, v in out.items() if v is not None}


def score(clips: list[dict]) -> int:
    """Tiêu đề Pháp + điểm cho video mới: một lần gọi Claude (effort thấp) mỗi lô 20, 4 lô song song."""
    def run(batch: list[dict]) -> int:
        lines = "\n".join(json.dumps({"id": c["id"], "plateforme": c["site"], "chaîne": c["uploader"],
                                      "format": "Short" if "/shorts/" in (c["url"] or "") else "vidéo",
                                      "durée_s": int(c["duration"]) if c["duration"] else None,
                                      "vues": c["views"], "titre": c["title"],
                                      **_trend_fields(c)}, ensure_ascii=False) for c in batch)
        result = llm.ask_json(SCORE_PROMPT.format(items=lines), SCORE_SYSTEM, effort="low", light=True)
        by_id = {r.get("id"): r for r in result if isinstance(r, dict)} if isinstance(result, list) else {}
        for c in batch:
            r = by_id.get(c["id"], {})
            db.score_clip(c["id"], str(r.get("title_fr") or "")[:120] or None, _int(r.get("score")),
                          str(r.get("reason") or "")[:200] or None)
        return len(batch)

    batches = [clips[i:i + 20] for i in range(0, len(clips), 20)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        return sum(ex.map(run, batches))


def check_all(ids: list[int] | None = None) -> dict:
    """Kiểm tra mọi nguồn đang bật (hoặc các nguồn `ids`), rồi chấm điểm video mới. Trả số liệu."""
    watches = [w for w in db.list_watches() if (w["id"] in ids if ids is not None else w["enabled"])]
    new, errors = [], {}
    for w in watches:
        r = check(w)
        new += r["new"]
        if r["error"]:
            errors[str(w["id"])] = r["error"]
    out = {"checked": len(watches), "new": len(new), "errors": errors}
    todo = [c for c in map(db.get_clip, new) if c and c["title"]]
    if todo:
        try:
            out["scored"] = score(todo)
        except llm.LLMError as e:
            out["score_error"] = str(e)[:300]
    return out


# ---------- làm video ----------
def produce(cid: str, duration: int = 80, links_only: bool | None = None, mute_voice: bool = True) -> int:
    """Dự án chủ đề từ một video mới: link của video + tiêu đề làm chủ đề. LookupError / ValueError.

    links_only: None (mặc định) hoặc False = tìm thêm video cho chủ đề; True = chỉ dùng video này. Không còn khai báo
    quyền nguồn (chủ, 2026-10-18: video từ đâu cũng được).
    mute_voice (mặc định): tiếng gốc của nguồn (giọng tiếng Trung) im hẳn dưới giọng đọc Pháp, `meta.mute_source`.
    """
    c = db.get_clip(cid)
    if not c:
        raise LookupError(tr("Video not found"))
    title_fr, title = c.get("title_fr") or "", c.get("title") or ""
    subject = f"{title_fr} ({title})" if title_fr and title and title_fr != title else title_fr or title
    pid = topic.create(subject, [c["url"]], bool(links_only), duration)
    db.set_clip_status(cid, "used", pid)
    db.update_project(pid, log=tr("From Followed: {source} · {url}", source=c.get("watch_name") or c["site"],
                                  url=c["url"]),
                      meta={"clip": cid, "mute_source": bool(mute_voice)})
    return pid
