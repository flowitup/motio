"""SQLite cho MVP (bảng trend, project). Giai đoạn 1 chuyển sang Postgres."""
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


def list_trends(hours: float = 24, limit: int = 60) -> list[dict]:
    since = time.time() - hours * 3600
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM trend WHERE last_seen >= ? AND title_fr IS NOT NULL "
            "ORDER BY score DESC, last_seen DESC LIMIT ?", (since, limit)).fetchall()
    return [_row(r) for r in rows]


def get_trend(tid: str) -> dict | None:
    with conn() as c:
        return _row(c.execute("SELECT * FROM trend WHERE id=?", (tid,)).fetchone())


# ---------- project ----------
def create_project(trend_id: str, title: str, mode: str = "news") -> int:
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
