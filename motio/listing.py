"""Truy vấn nhẹ cho app: danh sách dự án có lọc + "tải thêm", đếm dự án theo trạng thái, dự án của một tin hot,
ẩn tin hot. Tách khỏi db.py để không đụng vào các hàm lõi."""
import time

from . import db

HIDDEN = "hidden"  # trend.status: ẩn khỏi Trending (db.upsert_trend không ghi đè status)
RECENT_FAILED_DAYS = 7  # "đã lỗi gần đây": số ngày tính vào huy hiệu trên thanh bên
MAX_LIMIT = 200


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def projects(limit: int = 50, before: int | None = None, channel: int | None = None, mode: str | None = None,
             status: str | None = None, q: str | None = None) -> list[dict]:
    """Dự án mới nhất trước. before: chỉ lấy id nhỏ hơn (tải thêm); channel 0 = không kênh; q: tiêu đề hoặc #id."""
    where, args = [], []
    if before:
        where.append("id < ?")
        args.append(before)
    if channel is not None:
        if channel == 0:
            where.append("json_extract(meta, '$.channel') IS NULL")
        else:
            where.append("json_extract(meta, '$.channel') = ?")
            args.append(channel)
    if mode:
        where.append("mode = ?")
        args.append(mode)
    if status:
        where.append("status = ?")
        args.append(status)
    text = (q or "").strip()
    if text:
        digits = text.lstrip("#")
        clause = "(title LIKE ? ESCAPE '\\' OR json_extract(meta, '$.title') LIKE ? ESCAPE '\\'"
        args += [_like(text), _like(text)]
        if digits.isdigit():
            clause += " OR id = ?"
            args.append(int(digits))
        where.append(clause + ")")
    sql = "SELECT id FROM project" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(int(limit), MAX_LIMIT)))
    with db.conn() as c:
        ids = [r[0] for r in c.execute(sql, args)]
    return [p for p in (db.get_project(i) for i in ids) if p]


def counts() -> dict[str, int]:
    """Số dự án theo trạng thái, và `failed_recent`: số dự án lỗi trong RECENT_FAILED_DAYS ngày gần đây (huy hiệu)."""
    out = {"queued": 0, "running": 0, "review": 0, "done": 0, "failed": 0}
    since = time.time() - RECENT_FAILED_DAYS * 86400
    with db.conn() as c:
        for status, n in c.execute("SELECT status, COUNT(*) FROM project GROUP BY status"):
            if status in out:
                out[status] = n
        out["failed_recent"] = c.execute("SELECT COUNT(*) FROM project WHERE status='failed' AND updated_at >= ?",
                                         (since,)).fetchone()[0]
    return out


def trend_projects(ids: list[str]) -> dict[str, int]:
    """Dự án mới nhất của mỗi tin hot đã làm (trend id → project id)."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    with db.conn() as c:
        rows = c.execute(f"SELECT trend_id, MAX(id) FROM project WHERE trend_id IN ({marks}) GROUP BY trend_id", ids)
        return {r[0]: r[1] for r in rows}


def set_trend_hidden(tid: str, hidden: bool) -> bool:
    """Ẩn / hiện lại một tin hot. Tin đã làm (status 'used') không ẩn được. False khi không có tin."""
    with db.conn() as c:
        row = c.execute("SELECT status FROM trend WHERE id=?", (tid,)).fetchone()
        if not row:
            return False
        if hidden and row[0] == "new":
            c.execute("UPDATE trend SET status=? WHERE id=?", (HIDDEN, tid))
        elif not hidden and row[0] == HIDDEN:
            c.execute("UPDATE trend SET status='new' WHERE id=?", (tid,))
        return True
