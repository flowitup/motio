"""Chi phí và thống kê: mỗi lần gọi ElevenLabs ghi một dòng vào bảng usage (số ký tự, tiền ước lượng, dự án / kênh
đang chạy), rồi gom theo ngày, tháng và kênh cho trang Stats.

`claude -p` tính vào gói Claude của chủ máy, không có tiền theo lượt nên không ghi. Giá theo Cài đặt
(ELEVENLABS_USD_PER_1K_CHARS, mặc định gói Creator); mô hình flash / turbo chỉ tính nửa giá. Ngân sách tháng
(MONTHLY_BUDGET_USD) chỉ cảnh báo trên trang Stats và dừng việc tự làm video (automake); bấm làm tay không bị chặn.
"""
import contextlib
import contextvars
import datetime as dt
import time

from . import channels, db, settings

DEFAULT_PRICE = 0.22  # USD cho 1000 ký tự (đơn giá gói Creator của ElevenLabs)
DEFAULT_CLIP_PRICE = 0.08  # USD mỗi giây clip AI ở 768P (fal, MiniMax H3 Max)
HALF_PRICE = ("flash", "turbo")  # mô hình tính 0,5 tín dụng / ký tự
WARN_AT = 0.8  # cảnh báo khi đã dùng 80 % ngân sách tháng
WINDOW_DAYS = 30

_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar("motio_usage", default=None)


@contextlib.contextmanager
def context(**fields):
    """Trong khối này, mọi lần đọc giọng ghi kèm project_id / channel_id / ref (mỗi luồng một ngữ cảnh)."""
    token = _ctx.set({**(_ctx.get() or {}), **fields})
    try:
        yield
    finally:
        _ctx.reset(token)


def _number(key: str, default: float) -> float:
    try:
        v = float((settings.get(key) or "").strip())
    except ValueError:
        return default
    return v if v >= 0 else default


def price_per_1k() -> float:
    return _number("ELEVENLABS_USD_PER_1K_CHARS", DEFAULT_PRICE)


def clip_price() -> float:
    """USD mỗi giây clip AI (AI_CLIP_USD_PER_SEC)."""
    return _number("AI_CLIP_USD_PER_SEC", DEFAULT_CLIP_PRICE)


def budget() -> float:
    """Ngân sách tháng (USD), 0 = không đặt."""
    return _number("MONTHLY_BUDGET_USD", 0.0)


def cost(chars: int, model: str = "") -> float:
    return chars * (0.5 if any(k in model for k in HALF_PRICE) else 1.0) * price_per_1k() / 1000


def record_tts(chars: int, model: str, voice: str) -> None:
    """Ghi một lần gọi ElevenLabs thành công. Không ghi được (DB bận…) thì bỏ qua, đừng làm hỏng việc đang làm."""
    if chars <= 0:
        return
    _add("tts", chars, cost(chars, model), model, voice)


def record_clip(seconds: float, model: str) -> None:
    """Ghi một clip AI vừa làm (tiền theo số giây, không có ký tự). Không ghi được thì bỏ qua như record_tts."""
    if seconds > 0:
        _add("clip", 0, seconds * clip_price(), model, "")


def _add(kind: str, chars: int, usd: float, model: str, voice: str) -> None:
    c = _ctx.get() or {}
    pid = c.get("project_id")
    cid = c.get("channel_id")
    if pid and cid is None:
        proj = db.get_project(pid)
        cid = ((proj or {}).get("meta") or {}).get("channel")
    with contextlib.suppress(Exception):
        db.add_usage(kind, chars, round(usd, 6), pid, cid, c.get("ref"), model, voice)


def _month_start(now: float) -> float:
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def month_spent(now: float | None = None) -> float:
    now = now or time.time()
    return db.usage_sum(_month_start(now))[1]


def over_budget(now: float | None = None) -> bool:
    b = budget()
    return bool(b) and month_spent(now) >= b


def for_project(pid: int) -> dict:
    chars, usd = db.usage_sum(0, project_id=pid)
    clip_usd = db.usage_sum(0, project_id=pid, kind="clip")[1]
    return {"tts_chars": chars, "usd": round(usd, 4), "clip_usd": round(clip_usd, 4)}


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def summary(now: float | None = None) -> dict:
    """Số liệu cho trang Stats: ngân sách tháng, 30 ngày gần nhất theo ngày và theo kênh, tổng từ trước tới nay."""
    now = now or time.time()
    since_month = _month_start(now)
    today = dt.datetime.fromtimestamp(now).date()
    days = [(today - dt.timedelta(days=i)).isoformat() for i in range(WINDOW_DAYS - 1, -1, -1)]
    start = time.mktime(dt.datetime.combine(dt.date.fromisoformat(days[0]), dt.time()).timetuple())
    videos_month = 0
    per_day = {d: {"date": d, "videos": 0, "chars": 0, "usd": 0.0} for d in days}
    rows: dict[int | None, dict] = {}

    def row(cid):
        return rows.setdefault(cid, {"channel": cid, "name": "", "videos": 0, "failed": 0, "sent": 0, "chars": 0,
                                     "usd": 0.0})

    for p in db.projects_since(min(start, since_month)):
        meta = p["meta"] or {}
        done = p["status"] == "done"
        if done and p["created_at"] >= since_month:
            videos_month += 1
        if p["created_at"] < start:
            continue
        r = row(meta.get("channel") or None)
        if p["status"] == "failed":
            r["failed"] += 1
        elif done:
            r["videos"] += 1
            r["sent"] += 1 if meta.get("postiz") else 0
            per_day[_day(p["created_at"])]["videos"] += 1
    for u in db.usage_since(start):
        r = row(u["channel_id"] or None)
        r["chars"] += u["chars"]
        r["usd"] += u["usd"]
        d = per_day[_day(u["at"])]
        d["chars"] += u["chars"]
        d["usd"] += u["usd"]
    names = {ch["id"]: ch["name"] for ch in channels.listing()}
    for cid, r in rows.items():
        r["name"] = names.get(cid, "") if cid else ""
        r["usd"] = round(r["usd"], 4)
        r["usd_per_video"] = round(r["usd"] / r["videos"], 4) if r["videos"] else None
    for d in per_day.values():
        d["usd"] = round(d["usd"], 4)
    chars_month, usd_month = db.usage_sum(since_month)
    chars_all, usd_all = db.usage_sum(0)
    cap = budget()
    ratio = usd_month / cap if cap else 0.0
    return {
        "price_per_1k": price_per_1k(),
        "month": {"since": _day(since_month), "chars": chars_month, "usd": round(usd_month, 4),
                  "videos": videos_month},
        "budget": {"usd": cap, "ratio": round(ratio, 4),
                   "state": "none" if not cap else "over" if ratio >= 1 else "warn" if ratio >= WARN_AT else "ok",
                   "auto_paused": bool(cap) and ratio >= 1 and any(ch["auto_score"] for ch in channels.listing())},
        "total": {"chars": chars_all, "usd": round(usd_all, 4)},
        "days": list(per_day.values()),
        "channels": sorted(rows.values(), key=lambda r: (-r["videos"], -r["usd"])),
    }
