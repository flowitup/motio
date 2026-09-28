"""Kênh: hồ sơ của một kênh đăng ("bộ não" trong blueprint GĐ1).

Mỗi hồ sơ giữ: nhãn đỏ trên video, ghi chú giọng văn thêm vào prompt kịch bản, giọng ElevenLabs, độ dài mặc định,
hashtag luôn có, hai cổng duyệt (kịch bản, video cuối) và các kênh Postiz để tự gửi khi video được duyệt.
Dự án trỏ tới hồ sơ bằng `meta.channel`; không có hồ sơ thì chạy như trước (không dừng duyệt, không tự gửi).
"""
import datetime as dt
import re

from . import db, topic

NEWS_BADGE = "ACTU CHINE"  # nhãn mặc định của video tin nóng khi dự án không có hồ sơ kênh
SEND_MODES = ("draft", "schedule", "now")  # như postiz.MODES
MAX_NAME, MAX_BADGE, MAX_STYLE, MAX_TAGS, MAX_TIMES = 60, 24, 1500, 6, 6
SLOT_LEAD = dt.timedelta(minutes=10)  # khung đăng sớm nhất: ít nhất 10 phút sau lúc gửi
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

DEFAULTS = {"name": "", "badge": "", "style": "", "voice_id": "", "duration": 80, "hashtags": [],
            "gate_script": True, "gate_video": True, "postiz": [], "send_mode": "draft", "send_times": []}


def _tags(raw: list[str]) -> list[str]:
    out: list[str] = []
    for t in raw:
        for w in str(t).replace(",", " ").split():
            tag = "#" + w.lstrip("#")
            if len(tag) > 1 and tag.lower() not in {x.lower() for x in out}:
                out.append(tag[:40])
    return out


def clean(data: dict) -> dict:
    """Kiểm và chuẩn hoá một hồ sơ từ app. ValueError (tiếng Việt) nếu sai."""
    d = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS and v is not None}}
    d["name"] = " ".join(str(d["name"]).split())[:MAX_NAME]
    if not d["name"]:
        raise ValueError("Kênh cần có tên")
    d["badge"] = " ".join(str(d["badge"]).split())[:MAX_BADGE]
    d["style"] = str(d["style"]).strip()[:MAX_STYLE]
    d["voice_id"] = str(d["voice_id"]).strip()
    if int(d["duration"]) not in topic.DURATIONS:
        raise ValueError(f"Độ dài phải là {', '.join(map(str, topic.DURATIONS))} giây")
    d["duration"] = int(d["duration"])
    d["hashtags"] = _tags(d["hashtags"])[:MAX_TAGS]
    d["gate_script"], d["gate_video"] = bool(d["gate_script"]), bool(d["gate_video"])
    d["postiz"] = list(dict.fromkeys(str(i) for i in d["postiz"] if str(i).strip()))
    if d["send_mode"] not in SEND_MODES:
        raise ValueError(f"Cách gửi phải là một trong {', '.join(SEND_MODES)}")
    times = []
    for t in d["send_times"]:
        m = _TIME.match(str(t).strip())
        if not m:
            raise ValueError(f"Giờ đăng không hợp lệ: {t} (dạng 18:30)")
        times.append(f"{int(m[1]):02d}:{m[2]}")
    d["send_times"] = sorted(set(times))[:MAX_TIMES]
    if d["send_mode"] == "schedule" and d["postiz"] and not d["send_times"]:
        raise ValueError("Lên lịch cần ít nhất một giờ đăng")
    return d


def create(data: dict, is_default: bool = False) -> dict:
    return db.get_channel(db.save_channel(None, clean(data), is_default))


def update(cid: int, data: dict, is_default: bool) -> dict:
    if not db.get_channel(cid):
        raise LookupError("Không có kênh này")
    return db.get_channel(db.save_channel(cid, clean(data), is_default))


def pick(channel: int | None) -> dict | None:
    """Hồ sơ cho một dự án mới: None = kênh mặc định (nếu có), 0 = không dùng kênh. LookupError nếu không có."""
    if channel is None:
        return db.default_channel()
    if channel == 0:
        return None
    ch = db.get_channel(channel)
    if not ch:
        raise LookupError("Không có kênh này")
    return ch


def attach(pid: int, ch: dict | None, news: bool = False) -> None:
    """Gắn hồ sơ vào dự án vừa tạo. Video tin nóng lấy độ dài mặc định của kênh (chế độ chủ đề tự chọn độ dài)."""
    if not ch:
        return
    meta = {"channel": ch["id"]}
    if news:
        meta["duration"] = ch["duration"]
    db.update_project(pid, log=f"Kênh: {ch['name']}", meta=meta)


def for_project(proj: dict) -> dict | None:
    """Hồ sơ của dự án, None nếu không có (hoặc đã bị xoá: dự án chạy như không có kênh)."""
    cid = (proj.get("meta") or {}).get("channel")
    ch = db.get_channel(cid) if cid else None
    return {**DEFAULTS, **ch} if ch else None


def badge_for(proj: dict) -> str:
    """Nhãn trên video: của kênh nếu dự án có kênh (rỗng = không nhãn), không thì "ACTU CHINE" cho tin nóng."""
    ch = for_project(proj)
    if ch is not None:
        return ch["badge"]
    return "" if proj.get("mode") == topic.MODE else NEWS_BADGE


def style_note(ch: dict | None) -> str:
    """Phần thêm vào system prompt của kịch bản theo ghi chú giọng văn của kênh."""
    if not ch or not ch["style"]:
        return ""
    return (f"\n\nConsignes de la chaîne « {ch['name']} » (à suivre en priorité pour le ton et le contenu) :\n"
            f"{ch['style']}")


def merge_tags(ch: dict | None, tags: list[str]) -> list[str]:
    """Hashtag của kênh đứng đầu (bài đăng chỉ dùng 6 cái đầu), rồi hashtag Claude đề xuất, bỏ trùng."""
    return _tags([*(ch["hashtags"] if ch else []), *tags])


def next_slot(ch: dict, taken: set[str], now: dt.datetime | None = None) -> str:
    """Giờ đăng kế tiếp của kênh (giờ máy chạy engine), cách lúc này ít nhất SLOT_LEAD và chưa có bài nào của kênh.
    Trả ISO 8601 có múi giờ."""
    now = (now or dt.datetime.now()).astimezone()
    for day in range(60):
        date = (now + dt.timedelta(days=day)).date()
        for t in ch["send_times"]:
            h, m = map(int, t.split(":"))
            at = dt.datetime(date.year, date.month, date.day, h, m).astimezone()
            iso = at.isoformat(timespec="seconds")
            if at >= now + SLOT_LEAD and _utc(iso) not in taken:
                return iso
    raise ValueError("Hết khung giờ đăng trong 60 ngày tới")


def _utc(iso: str) -> str:
    return dt.datetime.fromisoformat(iso).astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def taken_slots(cid: int) -> set[str]:
    """Giờ đăng (UTC, như Postiz nhận) đã dùng cho các bài lên lịch của kênh này."""
    out = set()
    for p in db.list_projects(1000):
        for e in (p["meta"] or {}).get("postiz") or []:
            if e.get("profile") == cid and e.get("mode") == "schedule" and e.get("date"):
                out.add(e["date"])
    return out
