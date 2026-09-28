"""Gửi video đã dựng sang Postiz (tự host) để đăng lên mạng xã hội qua Postiz Public API.

POSTIZ_URL: gốc API của Postiz, vd. https://postiz.example.com/api (trong Docker: http://postiz:5000/api).
POSTIZ_API_KEY: Postiz → Settings → Developers → Public API.
Postiz lo OAuth, lịch đăng và gọi API từng nền tảng; Motio chỉ tải video lên và tạo bài.
"""
import datetime as dt
import time
from pathlib import Path

import httpx

from . import config, db

MODES = ("draft", "schedule", "now")
_transport: httpx.BaseTransport | None = None  # test thay bằng httpx.MockTransport


class PostizError(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.env("POSTIZ_URL") and config.env("POSTIZ_API_KEY"))


def _client(timeout: float = 60) -> httpx.Client:
    if not configured():
        raise PostizError("Chưa cấu hình POSTIZ_URL và POSTIZ_API_KEY")
    return httpx.Client(base_url=config.env("POSTIZ_URL").rstrip("/") + "/public/v1",
                        headers={"Authorization": config.env("POSTIZ_API_KEY")},  # key trần, không có "Bearer"
                        timeout=timeout, transport=_transport)


def _json(r: httpx.Response):
    if r.status_code >= 400:
        raise PostizError(f"Postiz {r.status_code}: {r.text[:300]}")
    return r.json()


def channels() -> list[dict]:
    """Các kênh (Postiz gọi là integration) đã kết nối trong Postiz."""
    with _client() as c:
        data = _json(c.get("/integrations"))
    return [{"id": i["id"], "name": i.get("name") or i["id"], "provider": i.get("identifier") or "",
             "picture": i.get("picture"), "profile": i.get("profile"), "disabled": bool(i.get("disabled"))}
            for i in data]


def upload(path: Path) -> dict:
    """Tải video lên kho media của Postiz. Trả {id, path}."""
    with _client(timeout=900) as c, path.open("rb") as f:
        data = _json(c.post("/upload", files={"file": (path.name, f, "video/mp4")}))
    return {"id": data["id"], "path": data["path"]}


def _tags(hashtags: list[str]) -> list[str]:
    return [h.lstrip("#") for h in hashtags if h.lstrip("#")]


def settings_for(provider: str, title: str, hashtags: list[str]) -> dict:
    """Cài đặt riêng từng nền tảng (trường bắt buộc của Postiz). Luôn khai báo nội dung có AI khi nền tảng hỗ trợ."""
    if provider == "youtube":
        return {"__type": "youtube", "title": title[:100], "type": "public", "selfDeclaredMadeForKids": "no",
                "tags": [{"value": t, "label": t} for t in _tags(hashtags)[:15]]}
    if provider == "tiktok":
        return {"__type": "tiktok", "title": title[:90], "privacy_level": "PUBLIC_TO_EVERYONE", "duet": False,
                "stitch": False, "comment": True, "autoAddMusic": "no", "brand_content_toggle": False,
                "brand_organic_toggle": False, "video_made_with_ai": True, "content_posting_method": "DIRECT_POST"}
    if provider in ("instagram", "instagram-standalone"):
        return {"__type": provider, "post_type": "post", "is_trial_reel": False, "collaborators": []}
    if provider == "x":
        return {"__type": "x", "who_can_reply_post": "everyone"}
    return {"__type": provider}


def _date(mode: str, when: str | None) -> str:
    if mode != "schedule":
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    if not when:
        raise ValueError("Lên lịch cần thời điểm đăng (date)")
    try:
        d = dt.datetime.fromisoformat(when)
    except ValueError:
        raise ValueError(f"Thời điểm không hợp lệ: {when}") from None
    if d.tzinfo is None:
        raise ValueError("Thời điểm cần có múi giờ, vd. 2026-10-01T18:00:00+02:00")
    if d <= dt.datetime.now(dt.UTC):
        raise ValueError("Thời điểm đăng phải ở tương lai")
    return d.astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def publish(video: Path, text: str, title: str, hashtags: list[str], channel_ids: list[str],
            mode: str = "draft", when: str | None = None) -> dict:
    """Tải video lên rồi tạo một bài cho mỗi kênh. mode: draft (nháp trong Postiz), schedule (cần when), now."""
    if mode not in MODES:
        raise ValueError(f"mode phải là một trong {', '.join(MODES)}")
    if not channel_ids:
        raise ValueError("Chọn ít nhất một kênh")
    date = _date(mode, when)
    known = {c["id"]: c for c in channels()}
    missing = [i for i in channel_ids if i not in known]
    if missing:
        raise ValueError(f"Kênh không có trong Postiz: {', '.join(missing)}")
    chosen = [known[i] for i in channel_ids]
    media = upload(video)
    body = {"type": mode, "date": date, "shortLink": False, "tags": [],
            "posts": [{"integration": {"id": c["id"]},
                       "value": [{"content": text, "image": [media]}],
                       "settings": settings_for(c["provider"], title, hashtags)} for c in chosen]}
    with _client() as c:
        posts = _json(c.post("/posts", json=body))
    return {"mode": mode, "date": date, "media": media, "posts": posts,
            "channels": [{"id": c["id"], "name": c["name"], "provider": c["provider"]} for c in chosen]}


def publish_project(pid: int, channel_ids: list[str], mode: str = "draft", when: str | None = None,
                    profile: int | None = None) -> dict:
    """Gửi video đã dựng của dự án (tiêu đề + mô tả bài đăng) và ghi vào lịch sử `meta.postiz`.
    profile: id kênh Motio khi gửi tự động (để biết giờ đăng nào của kênh đã dùng). LookupError nếu chưa có video."""
    p = db.get_project(pid)
    meta = p["meta"]
    video = config.DATA / meta["video"] if meta.get("video") else None
    if not video or not video.is_file():
        raise LookupError("Dự án chưa có video hoàn chỉnh")
    title = meta.get("title") or p["title"]
    text = f"{title}\n\n{meta['description']}" if meta.get("description") else title
    res = publish(video, text, title, meta.get("hashtags") or [], channel_ids, mode, when)
    entry = {"at": time.time(), **{k: res[k] for k in ("mode", "date", "channels", "posts")}}
    if profile:
        entry["profile"] = profile
    names = ", ".join(c["name"] for c in res["channels"])
    db.update_project(pid, log=f"Postiz ({res['mode']}): {names}",
                      meta={"postiz": [*(db.get_project(pid)["meta"].get("postiz") or []), entry]})
    return res
