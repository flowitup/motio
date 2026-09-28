"""Tự làm video khi một tin hot đạt điểm của hồ sơ kênh (GĐ1). Chạy sau mỗi lượt tự cập nhật tin theo lịch.

Mỗi tin chỉ làm một lần (dự án đầu tiên đánh dấu tin là đã dùng), theo điểm giảm dần. Mỗi hồ sơ tự làm tối đa
`auto_daily` video mỗi ngày, và tổng số video trong ngày vẫn theo MAX_VIDEOS_PER_DAY. Dự án tự làm dừng ở các cổng
duyệt của kênh như dự án bấm tay.
"""
import time

from . import channels, db, pipeline

HOURS = 6  # tin còn trên bảng tin trong 6 giờ qua
FRESH_HOURS = 24  # và xuất hiện lần đầu trong 24 giờ qua: bật tự làm không làm lại tin cũ


def profiles() -> list[dict]:
    """Hồ sơ đang bật tự làm; kênh mặc định trước, rồi theo thứ tự tạo."""
    return sorted((ch for ch in channels.listing() if ch["auto_score"]), key=lambda ch: (not ch["default"], ch["id"]))


def picks(now: float | None = None) -> list[tuple[dict, dict]]:
    """[(tin, hồ sơ)] sẽ tự làm lúc này. Tin đi tới hồ sơ đầu tiên có ngưỡng điểm ≤ điểm tin và còn lượt hôm nay."""
    now = now or time.time()
    chans = profiles()
    if not chans:
        return []
    left = pipeline.quota_left()  # None = không giới hạn
    start = pipeline.today_start()
    room = {ch["id"]: max(ch["auto_daily"] - db.count_auto_since(start, ch["id"]), 0) for ch in chans}
    out: list[tuple[dict, dict]] = []
    for t in db.list_trends(hours=HOURS, limit=200):  # điểm giảm dần
        if left is not None and len(out) >= left:
            break
        if t["status"] != "new" or (t.get("first_seen") or 0) < now - FRESH_HOURS * 3600:
            continue
        ch = next((c for c in chans if room[c["id"]] and (t["score"] or 0) >= c["auto_score"]), None)
        if ch:
            room[ch["id"]] -= 1
            out.append((t, ch))
    return out


def start(t: dict, ch: dict) -> int:
    """Tạo dự án tin nóng cho hồ sơ, như bấm "Make video" với kênh đó. Trả id dự án (chưa chạy)."""
    pid = db.create_project(t["id"], t["title_fr"] or t["title_zh"])
    channels.attach(pid, ch, news=True)
    db.update_project(pid, meta={"auto": True},
                      log=f"Made automatically: score {t['score']} (channel {ch['name']} makes {ch['auto_score']}+)")
    return pid
