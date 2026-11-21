"""Tự làm video khi một tin hot, hoặc một video mới của Trending / Followed, đạt điểm của hồ sơ kênh (GĐ1). Chạy sau
mỗi lượt tự cập nhật tin và sau mỗi lượt kiểm tra nguồn theo dõi theo lịch.

Mỗi tin / video chỉ làm một lần (dự án đầu tiên đánh dấu nó là đã dùng), theo điểm giảm dần. Mỗi hồ sơ tự làm tối đa
`auto_daily` video mỗi ngày, tính chung tin và video. Dự án tự làm dừng ở các cổng duyệt của kênh như dự án bấm tay.

Tin hot của NewsNow tắt mặc định (chủ, 2026-10-16), nên một kênh chỉ bật điểm tự làm thì không có gì để làm: kênh chọn
thêm `auto_clips` ("explainer" hoặc "dub") để tự làm từ video mới đã chấm điểm (`watch.score`). Mặc định tắt: bật nó là
việc của chủ, vì mỗi video tự làm đều tốn tiền Claude và giọng đọc.
"""
import time

from . import channels, db, dub, pipeline, usage, watch
from .i18n import tr

HOURS = 6  # tin còn trên bảng tin trong 6 giờ qua
FRESH_HOURS = 24  # và xuất hiện lần đầu trong 24 giờ qua: bật tự làm không làm lại tin cũ
CLIP_MODES = channels.AUTO_CLIPS[1:]  # explainer | dub


def profiles() -> list[dict]:
    """Hồ sơ đang bật tự làm; kênh mặc định trước, rồi theo thứ tự tạo."""
    return sorted((ch for ch in channels.listing() if ch["auto_score"]), key=lambda ch: (not ch["default"], ch["id"]))


def plan(now: float | None = None) -> list[tuple[str, dict, dict]]:
    """[(loại, tin hoặc video, hồ sơ)] sẽ tự làm lúc này; loại = "trend" | "clip", điểm giảm dần. Mỗi mục đi tới hồ sơ
    đầu tiên có ngưỡng điểm ≤ điểm của nó và còn lượt hôm nay; video mới chỉ tới hồ sơ đã bật `auto_clips`."""
    now = now or time.time()
    chans = profiles()
    if not chans or usage.over_budget(now):  # hết ngân sách tháng: tự làm dừng (bấm tay vẫn được)
        return []
    start = pipeline.today_start()
    room = {ch["id"]: max(ch["auto_daily"] - db.count_auto_since(start, ch["id"]), 0) for ch in chans}
    fresh = now - FRESH_HOURS * 3600
    items = [("trend", t) for t in db.list_trends(hours=HOURS, limit=200)
             if t["status"] == "new" and (t.get("first_seen") or 0) >= fresh]
    if any(ch["auto_clips"] in CLIP_MODES for ch in chans):
        items += [("clip", c) for c in db.list_clips("new", limit=200)
                  if c.get("score") is not None and c.get("url") and (c.get("first_seen") or 0) >= fresh]
    items.sort(key=lambda it: -(it[1]["score"] or 0))  # sort ổn định: cùng điểm thì tin trước, rồi thứ tự của db
    out: list[tuple[str, dict, dict]] = []
    for kind, item in items:
        ch = next((c for c in chans if room[c["id"]] and (item["score"] or 0) >= c["auto_score"]
                   and (kind == "trend" or c["auto_clips"] in CLIP_MODES)), None)
        if ch:
            room[ch["id"]] -= 1
            out.append((kind, item, ch))
    return out


def picks(now: float | None = None) -> list[tuple[dict, dict]]:
    """[(tin, hồ sơ)] sẽ tự làm lúc này (chỉ tin hot; `plan` gồm cả video mới)."""
    return [(item, ch) for kind, item, ch in plan(now) if kind == "trend"]


def _mark(pid: int, item: dict, ch: dict) -> None:
    db.update_project(pid, meta={"auto": True},
                      log=tr("Made automatically: score {score} (channel {name} makes {min}+)", score=item["score"],
                             name=ch["name"], min=ch["auto_score"]))


def start(t: dict, ch: dict) -> int:
    """Tạo dự án tin nóng cho hồ sơ, như bấm "Make video" với kênh đó. Trả id dự án (chưa chạy)."""
    pid = db.create_project(t["id"], t["title_fr"] or t["title_zh"])
    channels.attach(pid, ch, news=True)
    _mark(pid, t, ch)
    return pid


def start_clip(c: dict, ch: dict) -> int:
    """Tạo dự án từ một video mới cho hồ sơ, như bấm "Create" / "Dub" trên thẻ video với kênh đó: video giải thích
    (tiếng gốc tắt, độ dài của kênh) hoặc bản lồng tiếng Pháp, theo `auto_clips`. Trả id dự án (chưa chạy)."""
    pid = dub.from_clip(c["id"]) if ch["auto_clips"] == "dub" else watch.produce(c["id"], ch["duration"])
    channels.attach(pid, ch)
    _mark(pid, c, ch)
    return pid


def make(now: float | None = None) -> list[tuple[int, str, dict, dict]]:
    """Tạo các dự án của `plan` (chưa chạy). Trả [(id dự án, loại, tin hoặc video, hồ sơ)]. Một video không tạo được
    dự án (link hỏng…) bị ẩn khỏi danh sách để lượt sau không thử lại mãi, các mục khác vẫn được làm."""
    out = []
    for kind, item, ch in plan(now):
        try:
            pid = start(item, ch) if kind == "trend" else start_clip(item, ch)
        except (ValueError, LookupError):
            if kind == "clip":
                db.set_clip_status(item["id"], "hidden")
            continue
        out.append((pid, kind, item, ch))
    return out
