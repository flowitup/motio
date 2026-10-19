"""Scan: read the videos of accounts, hashtags or keywords into a table (Scan screen), nothing is saved or made.

One scan = one platform, one mode, one to ten lines of input. Each line is read with what Motio already has for that
site, so the limits are the sites' own:

| platform | account (link or id)                       | hashtag / keyword                         |
| YouTube  | channel, playlist (yt-dlp)                 | ytsearch / hashtag page (yt-dlp)          |
| Bilibili | space (yt-dlp + video pages)               | tag search, most played of 7 days (trending.py, up to 20) |
| Douyin   | accounts.py (f2 signs the request)         | its own search (login), else so.douyin.com in Chrome |
| Kuaishou | accounts.py (the owner's own cookies)      | its search page, the owner's own cookies  |
| Weibo    | accounts.py (guest session)                | its search, the same guest session        |

A scan runs in a background thread and is read by polling (`view`); the rows are `clip`-shaped dicts with views and
likes when the site gives them. "Download selected" and "Follow" are done by the app through the Tools downloads and
`/api/watches`, so a scan itself never downloads anything.
"""
import threading
import time
import uuid
from urllib.parse import quote

from yt_dlp import YoutubeDL

from . import accounts, douyin_feed, trending, watch, weibo_feed
from .i18n import tr

PLATFORMS = ("youtube", "bilibili", "douyin", "kuaishou", "weibo")
MODES = {"youtube": ("account", "keyword", "hashtag"), "bilibili": ("account", "keyword", "hashtag"),
         "douyin": ("account", "keyword", "hashtag"), "kuaishou": ("account", "keyword", "hashtag"),
         "weibo": ("account", "keyword", "hashtag")}
MAX_LINES = 10
LIMITS = (20, 50, 100)
DEFAULT_LIMIT = 50
KEEP_JOBS = 8
BILI_DETAILS = 40  # a Bilibili space lists links only: this many video pages are read for title, views, date

_jobs: dict[str, dict] = {}
_stops: dict[str, threading.Event] = {}
_lock = threading.Lock()


class Stopped(RuntimeError):
    pass


def options() -> dict:
    return {"platforms": [{"site": s, "modes": list(MODES[s])} for s in PLATFORMS], "limits": list(LIMITS),
            "default_limit": DEFAULT_LIMIT, "max_lines": MAX_LINES}


def _lines(text: str) -> list[str]:
    seen: list[str] = []
    for raw in (text or "").splitlines():
        line = " ".join(raw.split())
        if line and line not in seen:
            seen.append(line)
    return seen


def check(site: str, mode: str, text: str, limit: int) -> tuple[list[str], int]:
    """The input lines and the limit, or ValueError telling what to change."""
    if site not in PLATFORMS:
        raise ValueError(tr("Unknown platform: {site}", site=str(site)[:40]))
    if mode not in MODES[site]:
        raise ValueError(tr("{site} cannot be scanned by {mode}", site=site, mode=mode))
    lines = _lines(text)
    if not lines:
        raise ValueError(tr("Enter at least one link, id, hashtag or keyword"))
    if len(lines) > MAX_LINES:
        raise ValueError(tr("At most {n} lines per scan", n=MAX_LINES))
    return lines, limit if limit in LIMITS else DEFAULT_LIMIT


# ---------- one line ----------
def _ytdlp(site: str, url: str, limit: int, w: dict) -> list[dict]:
    with YoutubeDL(watch._opts(site, limit)) as y:
        info = y.extract_info(url, download=False) or {}
    owner = info.get("channel") or info.get("uploader")
    batch = [c for c in (watch._clip(e, w, owner) for e in watch._entries(info)[:limit]) if c]
    if site == "bilibili" and batch:  # a space lists links only
        from concurrent.futures import ThreadPoolExecutor
        head = batch[:BILI_DETAILS]
        with ThreadPoolExecutor(max_workers=4) as ex:
            done = list(ex.map(watch._details, head))
        batch = [c for c in done if c.get("status") != "old"] + batch[BILI_DETAILS:]
    return batch


def _account(site: str, line: str, limit: int) -> list[dict]:
    if site in accounts.SITES:
        _name, rows = accounts.fetch(site, accounts.parse(site, line), limit)
        return rows
    w = watch.classify(line, site)
    if w["site"] != site or w["kind"] not in ("channel", "playlist", "space"):
        raise ValueError(tr("This link is not a {site} channel, playlist or account", site=site))
    rows: list[dict] = []
    for url in watch._urls({**w, "id": None}):
        rows += _ytdlp(site, url, limit, {**w, "id": None})
    return rows


def _tag(site: str, mode: str, line: str, limit: int) -> list[dict]:
    word = line.lstrip("#＃").strip()
    if not word:
        raise ValueError(tr("Enter a hashtag or keyword"))
    if site == "kuaishou":  # its search page, with the owner's own cookies
        return accounts.search_kuaishou(word, limit)
    if site == "douyin":  # its own general search, signed by f2; Douyin wants the owner's login for it
        return douyin_feed.search(word, limit)
    if site == "weibo":  # its own search, the same guest session the hot feed uses
        return weibo_feed.search(word, limit)
    if site == "bilibili":  # its search, the most played of the last 7 days
        rows = trending.fetch(f"bilibili:tag:{word}", limit)
        return [{**c, "watch_id": None} for c in rows]
    w = {"id": None, "site": "youtube", "kind": "search", "target": word}
    url = f"https://www.youtube.com/hashtag/{quote(word)}" if mode == "hashtag" else f"ytsearch{limit}:{word}"
    return _ytdlp("youtube", url, limit, w)


def _read(site: str, mode: str, line: str, limit: int) -> list[dict]:
    try:
        return _account(site, line, limit) if mode == "account" else _tag(site, mode, line, limit)
    except (accounts.AccountError, trending.TrendingError, douyin_feed.FeedError, weibo_feed.FeedError) as e:
        raise RuntimeError(str(e)) from e


def _row(c: dict, line: str) -> dict:
    """The columns the table shows."""
    vid = str(c["id"]).partition(":")[2] or str(c["id"])
    return {"id": c["id"], "video_id": vid, "site": c["site"], "url": c["url"], "title": c.get("title") or "",
            "uploader": c.get("uploader") or "", "duration": c.get("duration"), "views": c.get("views"),
            "likes": c.get("likes"), "pubdate": c.get("pubdate"), "thumbnail": c.get("thumbnail"), "source": line}


# ---------- the job ----------
def _run(job_id: str, site: str, mode: str, lines: list[str], limit: int) -> None:
    stop = _stops[job_id]
    rows: dict[str, dict] = {}
    errors: list[str] = []
    try:
        for i, line in enumerate(lines):
            if stop.is_set():
                raise Stopped
            _set(job_id, message=tr("Reading {n} of {total}: {line}", n=i + 1, total=len(lines), line=line[:60]))
            try:
                for c in _read(site, mode, line, limit):
                    rows.setdefault(c["id"], _row(c, line))
            except Exception as e:  # one bad line does not stop the others
                errors.append(f"{line[:60]}: {watch._short(e, site)[:240]}")
            _set(job_id, rows=list(rows.values()), errors=list(errors))
        status = "done" if rows or not errors else "failed"
    except Stopped:
        status = "stopped"
    _set(job_id, status=status, message=None, finished_at=time.time())


def _set(job_id: str, **fields) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def start(site: str, mode: str, text: str, limit: int = DEFAULT_LIMIT) -> dict:
    """Begin a scan in the background. ValueError when the request is not usable."""
    lines, limit = check(site, mode, text, limit)
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        for old in sorted(_jobs.values(), key=lambda j: j["created_at"])[:-(KEEP_JOBS - 1)]:
            if old["status"] != "running":
                _jobs.pop(old["id"], None)
                _stops.pop(old["id"], None)
        _jobs[job_id] = {"id": job_id, "site": site, "mode": mode, "lines": lines, "limit": limit, "status": "running",
                         "message": tr("Starting…"), "rows": [], "errors": [], "created_at": time.time(),
                         "finished_at": None}
        _stops[job_id] = threading.Event()
    threading.Thread(target=_run, args=(job_id, site, mode, lines, limit), daemon=True, name="motio-scan").start()
    return view(job_id)


def view(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        return {**job, "rows": list(job["rows"]), "errors": list(job["errors"])}


def stop(job_id: str) -> dict:
    event = _stops.get(job_id)
    if event:
        event.set()
    return view(job_id)


def latest() -> dict | None:
    with _lock:
        newest = max(_jobs.values(), key=lambda j: j["created_at"], default=None)
    return view(newest["id"]) if newest else None
