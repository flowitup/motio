"""Thông báo Slack: khi một dự án chờ duyệt, xong hoặc lỗi, engine gửi một tin tới Incoming Webhook của chủ máy
(SLACK_WEBHOOK_URL trong Cài đặt). Chạy trong engine nên vẫn báo khi app đã đóng (engine trên server). Chỉ một
chiều, không có nút bấm; Slack app Socket Mode có nút vẫn là việc sau này (APP_PLAN, M4).

Chỉ nhận link https://hooks.slack.com/…: engine không bị dùng để gọi tới địa chỉ khác. Gửi lỗi (mất mạng, link bị
thu hồi…) chỉ ghi log, không bao giờ làm hỏng video; nút "Send a test message" trong Cài đặt báo lỗi thật.
Bài TikTok vào hộp thư app TikTok (chưa bật TikTok Direct Post) kèm lời nhắc tự đăng trong 24 giờ và bật nhãn AI.
"""
import datetime as dt
import logging
from urllib.parse import urlparse

import httpx

from . import channels, db, settings
from .i18n import tr

log = logging.getLogger("motio.notify")

HOST = "hooks.slack.com"
EVENTS = ("review", "done", "failed")
_transport: httpx.BaseTransport | None = None  # test thay bằng httpx.MockTransport


class NotifyError(Exception):
    pass


def webhook() -> str:
    return (settings.get("SLACK_WEBHOOK_URL") or "").strip()


def valid(url: str) -> bool:
    """Link Incoming Webhook của Slack: https, đúng host, có đường dẫn."""
    try:
        u = urlparse(url)
        return u.scheme == "https" and u.hostname == HOST and u.port is None and len(u.path) > 1
    except ValueError:
        return False


def enabled() -> bool:
    return valid(webhook())


def escape(text: str) -> str:
    """Slack đọc & < > là cú pháp (link, @channel…): tiêu đề lấy từ nguồn bên ngoài nên phải che đi."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(text: str) -> None:
    """Gửi một tin tới webhook đã lưu. Ném NotifyError (đã dịch) khi chưa cấu hình hoặc Slack từ chối."""
    url = webhook()
    if not valid(url):
        raise NotifyError(tr("Slack webhook is not set, or is not a https://hooks.slack.com/… link"))
    try:
        with httpx.Client(timeout=10, transport=_transport) as c:
            r = c.post(url, json={"text": text})
    except httpx.HTTPError as e:
        raise NotifyError(tr("Could not reach Slack: {error}", error=str(e)[:200])) from e
    if r.status_code != 200:  # Slack trả chữ ngắn: invalid_token, no_service, channel_is_archived…
        raise NotifyError(tr("Slack refused the message: {error}", error=f"{r.status_code} {r.text[:120]}".strip()))


def _inbox(entry: dict) -> str:
    """Nhắc chủ kênh tự đăng bài TikTok đã vào hộp thư app TikTok (app TikTok của Postiz chưa audit), "" nếu không có.
    entry: một lần gửi Postiz (`meta.postiz[i]` hoặc kết quả `postiz.publish`)."""
    names = entry.get("tiktok_inbox") or []
    if not names:
        return ""
    who = escape(", ".join(names))
    if entry.get("mode") == "schedule" and entry.get("date"):
        at = dt.datetime.fromisoformat(entry["date"]).astimezone().strftime("%d/%m %H:%M")
        head = tr("TikTok {names}: the video lands in the TikTok app inbox at {time}.", names=who, time=at)
    else:
        head = tr("TikTok {names}: the video goes to the TikTok app inbox now.", names=who)
    return head + "\n" + tr("Open TikTok within 24 h, finish the post and turn on “AI-generated content”.")


def _text(p: dict, event: str, sent: bool | None, error: str) -> str:
    meta = p["meta"] or {}
    title = escape(meta.get("title") or p["title"] or f"#{p['id']}")
    ch = channels.for_project(p)
    where = f" · {escape(ch['name'])}" if ch else ""
    if event == "review":
        return ":eyes: " + tr("Script ready for your approval: {title}" if meta.get("review") == "script"
                              else "Video ready for your approval: {title}", title=title) + where
    if event == "failed":
        head = ":x: " + tr("Video failed: {title}", title=title) + where
        return head + (f"\n{escape(error.strip().splitlines()[0][:200])}" if error.strip() else "")
    text = ":white_check_mark: " + tr("Video ready: {title}", title=title) + where
    if sent is True and ch:
        text += "\n" + tr("Sent to Postiz ({mode})", mode=ch["send_mode"])
        # lần tự gửi của kênh (mỗi dự án chỉ tự gửi một lần): bài nào vào hộp thư TikTok thì nhắc luôn
        for e in meta.get("postiz") or []:
            if e.get("profile") == ch["id"] and (line := _inbox(e)):
                text += "\n:iphone: " + line
    elif sent is False:
        text += "\n" + tr("Not sent to Postiz: {error}", error=escape(str(meta.get("send_error") or "")[:200]))
    return text


def tiktok_inbox(pid: int, res: dict) -> None:
    """Sau khi gửi Postiz bằng tay: bài TikTok vào hộp thư app TikTok thì nhắc chủ kênh tự đăng trong 24 giờ.
    Không bao giờ ném lỗi và không làm gì khi chưa có webhook."""
    if not res.get("tiktok_inbox") or not enabled():
        return
    try:
        p = db.get_project(pid)
        title = escape((p["meta"] or {}).get("title") or p["title"] or f"#{pid}") if p else f"#{pid}"
        send(f":iphone: {title}\n{_inbox(res)}")
    except Exception as e:  # mạng, DB, Slack…: việc gửi bài đã xong, chỉ ghi log
        log.warning("Slack TikTok inbox reminder for project %s failed: %s", pid, e)


def project(pid: int, event: str, *, sent: bool | None = None, error: str = "") -> None:
    """Báo một dự án vừa chuyển sang `event` (review | done | failed). sent: kết quả gửi Postiz của lần này (None =
    không gửi). Không bao giờ ném lỗi và không làm gì khi chưa có webhook."""
    if event not in EVENTS or not enabled():
        return
    try:
        p = db.get_project(pid)
        if p:
            send(_text(p, event, sent, error))
    except Exception as e:  # mạng, DB, Slack…: video không được hỏng vì thông báo
        log.warning("Slack notification for project %s (%s) failed: %s", pid, event, e)
