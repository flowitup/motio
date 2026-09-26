"""SQLite cho MVP (bảng trend, project, watch, clip). Giai đoạn 1 chuyển sang Postgres."""
import json
import sqlite3
import threading
import time

from .config import DATA

_DB = DATA / "motio.sqlite3"
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS trend (
  id TEXT PRIMARY KEY,            -- "{source}:{ext_id}"
  source TEXT, ext_id TEXT, url TEXT,
  title_zh TEXT, title_fr TEXT, angle TEXT, reason TEXT,
  keywords TEXT,                  -- JSON {"zh": [...], "en": [...], "fr": [...]}
  score INTEGER DEFAULT 0, rank INTEGER,
  first_seen REAL, last_seen REAL, status TEXT DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS project (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trend_id TEXT, mode TEXT DEFAULT 'news', title TEXT,
  status TEXT DEFAULT 'queued',   -- queued | running | done | failed
  step TEXT, pct INTEGER DEFAULT 0, log TEXT DEFAULT '',
  meta TEXT DEFAULT '{}', created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS watch (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT, site TEXT,           -- channel | playlist | space | search · youtube | bilibili
  target TEXT,                    -- URL (kênh, playlist, không gian) hoặc từ khoá tìm
  name TEXT, rights TEXT DEFAULT 'unknown', enabled INTEGER DEFAULT 1,
  created_at REAL, last_checked REAL, last_error TEXT,
  UNIQUE (site, target)
);
CREATE TABLE IF NOT EXISTS clip (
  id TEXT PRIMARY KEY,            -- "{site}:{video id}"
  watch_id INTEGER, site TEXT, url TEXT, title TEXT, title_fr TEXT, reason TEXT,
  uploader TEXT, duration REAL, views INTEGER, thumbnail TEXT, score INTEGER,
  first_seen REAL, status TEXT DEFAULT 'new',  -- new | old (có sẵn lúc thêm nguồn) | hidden | used
  project_id INTEGER
);
CREATE INDEX IF NOT EXISTS clip_feed ON clip (status, first_seen);
"""


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    return c


with conn() as _c:
    _c.executescript(SCHEMA)


def _row(r):
    if r is None:
        return None
    d = dict(r)
    for k in ("keywords", "meta"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k] or "{}")
            except json.JSONDecodeError:
                d[k] = {}
    return d


# ---------- trend ----------
def known_trend_ids() -> set[str]:
    with conn() as c:
        return {r[0] for r in c.execute("SELECT id FROM trend")}


def upsert_trend(t: dict) -> None:
    now = time.time()
    with _lock, conn() as c:
        c.execute(
            """INSERT INTO trend (id, source, ext_id, url, title_zh, title_fr, angle, reason, keywords,
                                  score, rank, first_seen, last_seen)
               VALUES (:id, :source, :ext_id, :url, :title_zh, :title_fr, :angle, :reason, :keywords,
                       :score, :rank, :now, :now)
               ON CONFLICT(id) DO UPDATE SET last_seen=:now, rank=:rank,
                 title_fr=COALESCE(:title_fr, title_fr), angle=COALESCE(:angle, angle),
                 reason=COALESCE(:reason, reason), keywords=COALESCE(:keywords, keywords),
                 score=COALESCE(:score, score)""",
            {**{k: t.get(k) for k in ("id", "source", "ext_id", "url", "title_zh", "title_fr",
                                        "angle", "reason", "score", "rank")},
             "keywords": json.dumps(t["keywords"], ensure_ascii=False) if t.get("keywords") else None,
             "now": now})


def touch_trend(tid: str, rank: int) -> None:
    with _lock, conn() as c:
        c.execute("UPDATE trend SET last_seen=?, rank=? WHERE id=?", (time.time(), rank, tid))


def list_trends(hours: float = 24, limit: int = 60, source: str | None = None) -> list[dict]:
    since = time.time() - hours * 3600
    sql, args = "SELECT * FROM trend WHERE last_seen >= ? AND title_fr IS NOT NULL", [since]
    if source:
        sql += " AND source = ?"
        args.append(source)
    with conn() as c:
        rows = c.execute(sql + " ORDER BY score DESC, last_seen DESC LIMIT ?", (*args, limit)).fetchall()
    return [_row(r) for r in rows]


def get_trend(tid: str) -> dict | None:
    with conn() as c:
        return _row(c.execute("SELECT * FROM trend WHERE id=?", (tid,)).fetchone())


# ---------- project ----------
def create_project(trend_id: str | None, title: str, mode: str = "news") -> int:
    now = time.time()
    with _lock, conn() as c:
        cur = c.execute("INSERT INTO project (trend_id, mode, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                        (trend_id, mode, title, now, now))
        c.execute("UPDATE trend SET status='used' WHERE id=?", (trend_id,))
        return cur.lastrowid


def update_project(pid: int, *, status=None, step=None, pct=None, log=None, meta=None) -> None:
    with _lock, conn() as c:
        p = c.execute("SELECT log, meta FROM project WHERE id=?", (pid,)).fetchone()
        new_log = p["log"] + (time.strftime("%H:%M:%S ") + log + "\n" if log else "")
        m = json.loads(p["meta"] or "{}")
        if meta:
            m.update(meta)
        c.execute(
            "UPDATE project SET status=COALESCE(?, status), step=COALESCE(?, step), pct=COALESCE(?, pct), "
            "log=?, meta=?, updated_at=? WHERE id=?",
            (status, step, pct, new_log, json.dumps(m, ensure_ascii=False), time.time(), pid))


def get_project(pid: int) -> dict | None:
    with conn() as c:
        return _row(c.execute("SELECT * FROM project WHERE id=?", (pid,)).fetchone())


def list_projects(limit: int = 20) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM project ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def count_projects_since(ts: float, exclude: int | None = None) -> int:
    """Số dự án tạo từ `ts`, không tính dự án lỗi."""
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM project WHERE created_at >= ? AND status != 'failed' AND id != ?",
                         (ts, exclude or -1)).fetchone()[0]


def fail_stale() -> list[int]:
    """Khi engine khởi động: dự án đang queued/running từ lần chạy trước sẽ không bao giờ xong."""
    with conn() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM project WHERE status IN ('queued', 'running')")]
    for pid in ids:
        update_project(pid, status="failed", log="LỖI: engine đã dừng khi dự án đang chạy. Bấm Dựng lại hoặc tạo lại.")
    return ids


# ---------- nguồn theo dõi (watch) và video mới (clip) ----------
WATCH_FIELDS = ("name", "rights", "enabled", "last_checked", "last_error")


def add_watch(kind: str, site: str, target: str, name: str, rights: str = "unknown") -> int:
    with _lock, conn() as c:
        return c.execute("INSERT INTO watch (kind, site, target, name, rights, created_at) VALUES (?,?,?,?,?,?)",
                         (kind, site, target, name, rights, time.time())).lastrowid


def find_watch(site: str, target: str) -> dict | None:
    with conn() as c:
        return _watch(c.execute("SELECT * FROM watch WHERE site=? AND target=?", (site, target)).fetchone())


def _watch(r) -> dict | None:
    return {**dict(r), "enabled": bool(r["enabled"])} if r else None


def get_watch(wid: int) -> dict | None:
    with conn() as c:
        return _watch(c.execute("SELECT * FROM watch WHERE id=?", (wid,)).fetchone())


def list_watches() -> list[dict]:
    """Mọi nguồn, kèm số video mới (chưa làm, chưa ẩn)."""
    with conn() as c:
        rows = c.execute("SELECT w.*, (SELECT COUNT(*) FROM clip WHERE watch_id=w.id AND status='new') AS new_count "
                         "FROM watch w ORDER BY w.id").fetchall()
    return [_watch(r) for r in rows]


def update_watch(wid: int, **fields) -> None:
    cols = [k for k in fields if k in WATCH_FIELDS]
    if not cols:
        return
    with _lock, conn() as c:
        c.execute(f"UPDATE watch SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?",
                  (*(fields[k] for k in cols), wid))


def delete_watch(wid: int) -> None:
    """Xoá nguồn và các video của nó chưa dùng làm dự án."""
    with _lock, conn() as c:
        c.execute("DELETE FROM clip WHERE watch_id=? AND status != 'used'", (wid,))
        c.execute("DELETE FROM watch WHERE id=?", (wid,))


def known_clip_ids(ids: list[str]) -> set[str]:
    if not ids:
        return set()
    with conn() as c:
        return {r[0] for r in c.execute(f"SELECT id FROM clip WHERE id IN ({','.join('?' * len(ids))})", ids)}


def insert_clips(clips: list[dict]) -> None:
    now = time.time()
    keys = ("id", "watch_id", "site", "url", "title", "uploader", "duration", "views", "thumbnail", "status")
    with _lock, conn() as c:
        c.executemany(f"INSERT OR IGNORE INTO clip ({', '.join(keys)}, first_seen) "
                      f"VALUES ({', '.join(':' + k for k in keys)}, :now)",
                      [{**{k: cl.get(k) for k in keys}, "now": now} for cl in clips])


def score_clip(cid: str, title_fr: str | None, score: int | None, reason: str | None) -> None:
    with _lock, conn() as c:
        c.execute("UPDATE clip SET title_fr=?, score=?, reason=? WHERE id=?", (title_fr, score, reason, cid))


def list_clips(status: str = "new", watch_id: int | None = None, limit: int = 200) -> list[dict]:
    sql = ("SELECT clip.*, watch.name AS watch_name, watch.kind AS watch_kind, watch.rights AS rights "
           "FROM clip LEFT JOIN watch ON watch.id = clip.watch_id WHERE clip.status = ?")
    args: list = [status]
    if watch_id:
        sql += " AND clip.watch_id = ?"
        args.append(watch_id)
    sql += " ORDER BY clip.score IS NULL, clip.score DESC, clip.first_seen DESC LIMIT ?"
    with conn() as c:
        return [dict(r) for r in c.execute(sql, (*args, limit)).fetchall()]


def get_clip(cid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT clip.*, watch.name AS watch_name, watch.rights AS rights "
                      "FROM clip LEFT JOIN watch ON watch.id = clip.watch_id WHERE clip.id=?", (cid,)).fetchone()
    return dict(r) if r else None


def set_clip_status(cid: str, status: str, project_id: int | None = None) -> None:
    with _lock, conn() as c:
        c.execute("UPDATE clip SET status=?, project_id=COALESCE(?, project_id) WHERE id=?", (status, project_id, cid))
