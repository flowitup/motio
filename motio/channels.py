"""Kênh: hồ sơ của một kênh đăng ("bộ não" trong blueprint GĐ1).

Mỗi hồ sơ giữ: nhãn đỏ trên video, ghi chú giọng văn và bảng thuật ngữ thêm vào prompt kịch bản / bản dịch lồng
tiếng, giọng ElevenLabs, độ dài mặc định,
hashtag luôn có, hai cổng duyệt (kịch bản, video cuối), các kênh Postiz để tự gửi khi video được duyệt (kênh nào
nhận bản 16:9), và tự làm video khi tin hot đạt điểm (automake.py).
Dự án trỏ tới hồ sơ bằng `meta.channel`; không có hồ sơ thì chạy như trước (không dừng duyệt, không tự gửi).
"""
import datetime as dt
import re

from . import aiclips, db, topic
from .i18n import tr

NEWS_BADGE = "ACTU CHINE"  # nhãn mặc định của video tin nóng khi dự án không có hồ sơ kênh
SEND_MODES = ("draft", "schedule", "now")  # như postiz.MODES
MAX_NAME, MAX_BADGE, MAX_STYLE, MAX_GLOSSARY, MAX_TAGS, MAX_TIMES = 60, 24, 1500, 2000, 6, 6
MAX_DUB_VOICES = 3  # giọng thêm cho các người nói khác trong bản lồng tiếng (giọng chính + 3 = 4 giọng)
AUTO_SCORE = 85  # điểm tối thiểu gợi ý khi bật tự làm (app đặt sẵn)
MAX_AUTO_DAILY = 20
SLOT_LEAD = dt.timedelta(minutes=10)  # khung đăng sớm nhất: ít nhất 10 phút sau lúc gửi
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

DEFAULTS = {"name": "", "badge": "", "style": "", "glossary": "", "voice_id": "", "dub_voices": [], "duration": 80,
            "hashtags": [], "gate_script": True, "gate_video": True, "postiz": [], "send_mode": "draft",
            "send_times": [], "wide_postiz": [], "auto_score": 0, "auto_daily": 2, "ai_clips": 0}


def _tags(raw: list[str]) -> list[str]:
    out: list[str] = []
    for t in raw:
        for w in str(t).replace(",", " ").split():
            tag = "#" + w.lstrip("#")
            if len(tag) > 1 and tag.lower() not in {x.lower() for x in out}:
                out.append(tag[:40])
    return out


def clean(data: dict) -> dict:
    """Validate and normalize a profile from the app. Raises ValueError (in the UI language) when invalid."""
    d = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS and v is not None}}
    d["name"] = " ".join(str(d["name"]).split())[:MAX_NAME]
    if not d["name"]:
        raise ValueError(tr("The channel needs a name"))
    d["badge"] = " ".join(str(d["badge"]).split())[:MAX_BADGE]
    d["style"] = str(d["style"]).strip()[:MAX_STYLE]
    d["glossary"] = "\n".join(ln.strip() for ln in str(d["glossary"]).strip().splitlines())[:MAX_GLOSSARY]
    d["voice_id"] = str(d["voice_id"]).strip()
    d["dub_voices"] = [v for v in dict.fromkeys(str(v).strip() for v in d["dub_voices"])
                       if v and v != d["voice_id"]][:MAX_DUB_VOICES]
    if int(d["duration"]) not in topic.DURATIONS:
        raise ValueError(tr("Duration must be one of {choices} seconds", choices=", ".join(map(str, topic.DURATIONS))))
    d["duration"] = int(d["duration"])
    d["hashtags"] = _tags(d["hashtags"])[:MAX_TAGS]
    d["gate_script"], d["gate_video"] = bool(d["gate_script"]), bool(d["gate_video"])
    d["postiz"] = list(dict.fromkeys(str(i) for i in d["postiz"] if str(i).strip()))
    if d["send_mode"] not in SEND_MODES:
        raise ValueError(tr("Send mode must be one of {choices}", choices=", ".join(SEND_MODES)))
    times = []
    for t in d["send_times"]:
        m = _TIME.match(str(t).strip())
        if not m:
            raise ValueError(tr("Invalid posting time: {time} (format 18:30)", time=t))
        times.append(f"{int(m[1]):02d}:{m[2]}")
    d["send_times"] = sorted(set(times))[:MAX_TIMES]
    if d["send_mode"] == "schedule" and d["postiz"] and not d["send_times"]:
        raise ValueError(tr("Scheduling needs at least one posting time"))
    # kênh Postiz nhận bản 16:9: chỉ trong các kênh Postiz của hồ sơ
    d["wide_postiz"] = [i for i in dict.fromkeys(str(i) for i in d["wide_postiz"]) if i in d["postiz"]]
    try:
        d["auto_score"], d["auto_daily"] = int(d["auto_score"]), int(d["auto_daily"])
    except (TypeError, ValueError):
        raise ValueError(tr("Auto-make score and videos per day must be numbers")) from None
    if not 0 <= d["auto_score"] <= 100:
        raise ValueError(tr("Auto-make score must be between 1 and 100 (0 = off)"))
    if not 1 <= d["auto_daily"] <= MAX_AUTO_DAILY:
        raise ValueError(tr("Auto-made videos per day must be between 1 and {n}", n=MAX_AUTO_DAILY))
    try:
        d["ai_clips"] = int(d["ai_clips"])
    except (TypeError, ValueError):
        raise ValueError(tr("AI clips per video must be a number")) from None
    if not 0 <= d["ai_clips"] <= aiclips.MAX_PER_VIDEO:
        raise ValueError(tr("AI clips per video must be between 0 and {n}", n=aiclips.MAX_PER_VIDEO))
    return d


def create(data: dict, is_default: bool = False) -> dict:
    return db.get_channel(db.save_channel(None, clean(data), is_default))


def update(cid: int, data: dict, is_default: bool) -> dict:
    if not db.get_channel(cid):
        raise LookupError(tr("Channel not found"))
    return db.get_channel(db.save_channel(cid, clean(data), is_default))


def full(ch: dict | None) -> dict | None:
    """Hồ sơ đủ trường: hồ sơ lưu trước khi có trường mới (16:9, tự làm) lấy giá trị mặc định."""
    return {**DEFAULTS, **ch} if ch else None


def listing() -> list[dict]:
    return [full(ch) for ch in db.list_channels()]


def pick(channel: int | None) -> dict | None:
    """Hồ sơ cho một dự án mới: None = kênh mặc định (nếu có), 0 = không dùng kênh. LookupError nếu không có."""
    if channel is None:
        return full(db.default_channel())
    if channel == 0:
        return None
    ch = db.get_channel(channel)
    if not ch:
        raise LookupError(tr("Channel not found"))
    return full(ch)


def attach(pid: int, ch: dict | None, news: bool = False) -> None:
    """Gắn hồ sơ vào dự án vừa tạo. Video tin nóng lấy độ dài mặc định của kênh (chế độ chủ đề tự chọn độ dài)."""
    if not ch:
        return
    meta = {"channel": ch["id"]}
    if news:
        meta["duration"] = ch["duration"]
    db.update_project(pid, log=tr("Channel: {name}", name=ch["name"]), meta=meta)


def for_project(proj: dict) -> dict | None:
    """Hồ sơ của dự án, None nếu không có (hoặc đã bị xoá: dự án chạy như không có kênh)."""
    cid = (proj.get("meta") or {}).get("channel")
    return full(db.get_channel(cid) if cid else None)


def badge_for(proj: dict) -> str:
    """Nhãn trên video: của kênh nếu dự án có kênh (rỗng = không nhãn), không thì "ACTU CHINE" cho tin nóng."""
    ch = for_project(proj)
    if ch is not None:
        return ch["badge"]
    return NEWS_BADGE if proj.get("mode", "news") == "news" else ""


def style_note(ch: dict | None) -> str:
    """Phần thêm vào system prompt của kịch bản / bản dịch: ghi chú giọng văn và bảng thuật ngữ của kênh."""
    if not ch:
        return ""
    note = ""
    if ch["style"]:
        note += (f"\n\nConsignes de la chaîne « {ch['name']} » (à suivre en priorité pour le ton et le contenu) :\n"
                 f"{ch['style']}")
    if ch.get("glossary"):
        note += ("\n\nGlossaire de la chaîne (noms et termes : utilise exactement ces traductions et graphies) :\n"
                 f"{ch['glossary']}")
    return note


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
    raise ValueError(tr("No free posting time in the next 60 days"))


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
