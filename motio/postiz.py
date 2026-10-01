"""Gửi video đã dựng sang Postiz (tự host) để đăng lên mạng xã hội qua Postiz Public API.

POSTIZ_URL: gốc API của Postiz, vd. https://postiz.example.com/api (trong Docker: http://postiz:5000/api).
POSTIZ_API_KEY: Postiz → Settings → Developers → Public API.
Postiz lo OAuth, lịch đăng và gọi API từng nền tảng; Motio chỉ tải video lên và tạo bài.

TikTok: app TikTok của Postiz tự host chưa qua audit thì TikTok chặn Direct Post vào tài khoản công khai, nên mặc
định bài TikTok vào hộp thư (inbox) của app TikTok (Postiz `UPLOAD`): chủ kênh mở TikTok, hoàn tất và bật nhãn AI
trong 24 giờ (TikTok bỏ `video_made_with_ai` khi UPLOAD). Bật TIKTOK_DIRECT_POST khi app đã qua audit. Một video chỉ
lên một tài khoản TikTok: cùng video trên nhiều tài khoản làm TikTok gộp chúng lại và giảm lượt xem.
"""
import datetime as dt
import time
from pathlib import Path

import httpx

from . import config, db
from .i18n import tr

MODES = ("draft", "schedule", "now")
TIKTOK = ("tiktok", "tiktok-business")  # identifier của kênh TikTok trong Postiz
_transport: httpx.BaseTransport | None = None  # test thay bằng httpx.MockTransport


class PostizError(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.env("POSTIZ_URL") and config.env("POSTIZ_API_KEY"))


def tiktok_direct() -> bool:
    """TikTok Direct Post (TIKTOK_DIRECT_POST): chỉ bật khi TikTok đã audit app TikTok của Postiz. Tắt (mặc định) thì
    bài TikTok vào hộp thư của app TikTok để chủ kênh tự đăng."""
    return config.flag("TIKTOK_DIRECT_POST")


def _client(timeout: float = 60) -> httpx.Client:
    if not configured():
        raise PostizError(tr("POSTIZ_URL and POSTIZ_API_KEY are not configured"))
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


def _one_tiktok_error() -> ValueError:
    return ValueError(tr("Pick one TikTok account per video: the same video on several TikTok accounts links them "
                         "and cuts their reach"))


def one_tiktok(channel_ids: list[str]) -> None:
    """Kiểm tra hồ sơ kênh: tối đa một tài khoản TikTok trong các kênh Postiz. Postiz chưa cấu hình hoặc không trả lời
    thì bỏ qua (lúc gửi `publish` vẫn kiểm tra lại)."""
    ids = list(dict.fromkeys(channel_ids))
    if len(ids) < 2 or not configured():
        return
    try:
        known = {c["id"]: c["provider"] for c in channels()}
    except (PostizError, httpx.HTTPError):
        return
    if sum(known.get(i) in TIKTOK for i in ids) > 1:
        raise _one_tiktok_error()


def settings_for(provider: str, title: str, hashtags: list[str]) -> dict:
    """Cài đặt riêng từng nền tảng (trường bắt buộc của Postiz). Luôn khai báo nội dung có AI khi nền tảng hỗ trợ."""
    if provider == "youtube":
        return {"__type": "youtube", "title": title[:100], "type": "public", "selfDeclaredMadeForKids": "no",
                "tags": [{"value": t, "label": t} for t in _tags(hashtags)[:15]]}
    if provider in TIKTOK:  # UPLOAD: TikTok chỉ giữ tiêu đề, các trường khác (cả cờ AI) phải đặt trong app TikTok
        return {"__type": provider, "title": title[:90], "privacy_level": "PUBLIC_TO_EVERYONE", "duet": False,
                "stitch": False, "comment": True, "autoAddMusic": "no", "brand_content_toggle": False,
                "brand_organic_toggle": False, "video_made_with_ai": True,
                "content_posting_method": "DIRECT_POST" if tiktok_direct() else "UPLOAD"}
    if provider in ("instagram", "instagram-standalone"):
        return {"__type": provider, "post_type": "post", "is_trial_reel": False, "collaborators": []}
    if provider == "x":
        return {"__type": "x", "who_can_reply_post": "everyone"}
    return {"__type": provider}


def _date(mode: str, when: str | None) -> str:
    if mode != "schedule":
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    if not when:
        raise ValueError(tr("Scheduling needs a posting time (date)"))
    try:
        d = dt.datetime.fromisoformat(when)
    except ValueError:
        raise ValueError(tr("Invalid time: {time}", time=when)) from None
    if d.tzinfo is None:
        raise ValueError(tr("The time needs a time zone, e.g. 2026-10-01T18:00:00+02:00"))
    if d <= dt.datetime.now(dt.UTC):
        raise ValueError(tr("The posting time must be in the future"))
    return d.astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def publish(video: Path, text: str, title: str, hashtags: list[str], channel_ids: list[str],
            mode: str = "draft", when: str | None = None, tiktok_sent: dict[str, str] | None = None) -> dict:
    """Tải video lên rồi tạo một bài cho mỗi kênh. mode: draft (nháp trong Postiz), schedule (cần when), now.
    tiktok_sent: tài khoản TikTok {id: tên} video này đã lên lịch / đã đăng; gửi sang tài khoản TikTok khác bị từ chối.
    Kết quả có `tiktok_inbox`: tên các kênh TikTok mà bài sẽ vào hộp thư app TikTok (chủ kênh phải tự đăng)."""
    if mode not in MODES:
        raise ValueError(tr("mode must be one of {choices}", choices=", ".join(MODES)))
    if not channel_ids:
        raise ValueError(tr("Pick at least one channel"))
    date = _date(mode, when)
    known = {c["id"]: c for c in channels()}
    missing = [i for i in channel_ids if i not in known]
    if missing:
        raise ValueError(tr("Channels not found in Postiz: {names}", names=", ".join(missing)))
    chosen = [known[i] for i in channel_ids]
    tiktoks = [c for c in chosen if c["provider"] in TIKTOK]
    if len(tiktoks) > 1:
        raise _one_tiktok_error()
    other = [name for i, name in (tiktok_sent or {}).items() if tiktoks and i != tiktoks[0]["id"]]
    if other:
        raise ValueError(tr("This video already went to TikTok {name}: post it on one TikTok account only",
                            name=other[0]))
    media = upload(video)
    body = {"type": mode, "date": date, "shortLink": False, "tags": [],
            "posts": [{"integration": {"id": c["id"]},
                       "value": [{"content": text, "image": [media]}],
                       "settings": settings_for(c["provider"], title, hashtags)} for c in chosen]}
    with _client() as c:
        posts = _json(c.post("/posts", json=body))
    inbox = [c["name"] for c in tiktoks] if mode != "draft" and not tiktok_direct() else []
    return {"mode": mode, "date": date, "media": media, "posts": posts, "tiktok_inbox": inbox,
            "channels": [{"id": c["id"], "name": c["name"], "provider": c["provider"]} for c in chosen]}


VERSIONS = ("vertical", "wide")  # 9:16 (meta.video) | 16:9 (meta.wide)


def project_video(meta: dict, version: str = "vertical") -> Path | None:
    """File video của dự án theo khổ, None nếu chưa có."""
    rel = meta.get("wide" if version == "wide" else "video")
    path = config.DATA / rel if rel else None
    return path if path and path.is_file() else None


def tiktok_sent(meta: dict) -> dict[str, str]:
    """Tài khoản TikTok {id: tên} mà video đã được lên lịch / đăng (nháp trong Postiz không tính: còn sửa được)."""
    return {c["id"]: c.get("name") or c["id"] for e in meta.get("postiz") or [] if e.get("mode") != "draft"
            for c in e.get("channels") or [] if c.get("provider") in TIKTOK}


def publish_project(pid: int, channel_ids: list[str], mode: str = "draft", when: str | None = None,
                    profile: int | None = None, version: str = "vertical") -> dict:
    """Gửi video đã dựng của dự án (tiêu đề + mô tả bài đăng) và ghi vào lịch sử `meta.postiz`.
    profile: id kênh Motio khi gửi tự động (để biết giờ đăng nào của kênh đã dùng). version: vertical (9:16) | wide
    (16:9). LookupError nếu chưa có video khổ đó."""
    if version not in VERSIONS:
        raise ValueError(tr("version must be one of {choices}", choices=", ".join(VERSIONS)))
    p = db.get_project(pid)
    meta = p["meta"]
    video = project_video(meta, version)
    if not video:
        raise LookupError(tr("Project has no 16:9 copy yet") if version == "wide"
                          else tr("Project has no finished video yet"))
    title = meta.get("title") or p["title"]
    text = f"{title}\n\n{meta['description']}" if meta.get("description") else title
    res = publish(video, text, title, meta.get("hashtags") or [], channel_ids, mode, when, tiktok_sent(meta))
    entry = {"at": time.time(), **{k: res[k] for k in ("mode", "date", "channels", "posts")}}
    if profile:
        entry["profile"] = profile
    if version == "wide":
        entry["version"] = "wide"
    if res["tiktok_inbox"]:
        entry["tiktok_inbox"] = res["tiktok_inbox"]
    names = ", ".join(c["name"] for c in res["channels"])
    db.update_project(pid, log=f"Postiz ({res['mode']}{', 16:9' if version == 'wide' else ''}): {names}",
                      meta={"postiz": [*(db.get_project(pid)["meta"].get("postiz") or []), entry]})
    return res
