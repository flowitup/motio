"""Thông báo Slack (motio/notify.py): link hợp lệ, gửi / lỗi, nội dung từng loại tin, nút gửi thử."""
import httpx
import pytest
from fastapi.testclient import TestClient

from motio import api, channels, db, notify, settings

URL = "https://hooks.slack.com/services/T0/B0/xyz"
H = {"Authorization": "Bearer t"}


@pytest.mark.parametrize("url,ok", [
    (URL, True),
    ("https://hooks.slack.com/triggers/T0/1/abc", True),
    ("", False),
    ("http://hooks.slack.com/services/T0/B0/xyz", False),  # không https
    ("https://hooks.slack.com/", False),  # thiếu đường dẫn
    ("https://hooks.slack.com:8443/services/T0/B0/xyz", False),
    ("https://hooks.slack.com.evil.test/services/T0/B0/xyz", False),
    ("https://evil.test/hooks.slack.com/services/T0/B0/xyz", False),
    ("https://user@hooks.slack.com@evil.test/services/T0/B0/xyz", False),
    ("http://127.0.0.1:8765/api", False),
])
def test_only_slack_incoming_webhook_links_are_accepted(url, ok):
    assert notify.valid(url) is ok


def test_settings_reject_a_bad_link_and_mask_the_good_one():
    with pytest.raises(ValueError, match="hooks.slack.com"):
        settings.update({"SLACK_WEBHOOK_URL": "http://127.0.0.1:8765/api"})
    assert not notify.enabled()
    pub = settings.update({"SLACK_WEBHOOK_URL": URL})["SLACK_WEBHOOK_URL"]
    assert pub["secret"] and pub["value"] == "••••" + URL[-4:] and notify.enabled()
    settings.update({"SLACK_WEBHOOK_URL": "••••" + URL[-4:]})  # giá trị đã che: giữ nguyên, không kiểm tra lại
    assert notify.webhook() == URL
    settings.update({"SLACK_WEBHOOK_URL": ""})  # xoá = tắt
    assert not notify.enabled()


def test_escape_keeps_titles_from_pinging_the_channel():
    assert notify.escape("<!channel> A & B <https://x|y>") == "&lt;!channel&gt; A &amp; B &lt;https://x|y&gt;"


def test_send_posts_the_text_and_reports_slack_errors(monkeypatch):
    seen = []
    status = [200]

    def handler(req):
        seen.append((str(req.url), req.content))
        return httpx.Response(status[0], text="ok" if status[0] == 200 else "no_service")

    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(handler))
    with pytest.raises(notify.NotifyError, match="not set"):
        notify.send("x")
    assert not seen
    settings.update({"SLACK_WEBHOOK_URL": URL})
    notify.send("Bonjour")
    assert seen == [(URL, b'{"text":"Bonjour"}')]
    status[0] = 404
    with pytest.raises(notify.NotifyError, match="404 no_service"):
        notify.send("x")

    def down(req):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(down))
    with pytest.raises(notify.NotifyError, match="Could not reach Slack"):
        notify.send("x")


def test_nothing_happens_without_a_webhook(monkeypatch):
    def boom(req):
        raise AssertionError("no request expected")

    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(boom))
    notify.project(999999, "done")  # không có webhook: không đụng tới DB, không gửi gì


def test_messages_per_event(fake_slack):
    cid = channels.create({"name": "Chine <Info>", "postiz": ["tt1"], "send_mode": "schedule",
                              "send_times": ["07:00"]})["id"]
    pid = db.create_project("douyin:p", "Titre & <b>")
    channels.attach(pid, channels.pick(cid))
    db.update_project(pid, meta={"review": "script"})
    notify.project(pid, "review")
    db.update_project(pid, meta={"review": "video"})
    notify.project(pid, "review")
    notify.project(pid, "done", sent=True)
    db.update_project(pid, meta={"send_error": "Postiz error\nsecond line"})
    notify.project(pid, "done", sent=False)
    notify.project(pid, "done")
    notify.project(pid, "failed", error="ffmpeg failed: boom\ntraceback…")
    notify.project(pid, "failed")
    notify.project(pid, "running")  # không phải sự kiện cần báo
    t = "Titre &amp; &lt;b&gt; · Chine &lt;Info&gt;"
    assert fake_slack == [
        f":eyes: Script ready for your approval: {t}",
        f":eyes: Video ready for your approval: {t}",
        f":white_check_mark: Video ready: {t}\nSent to Postiz (schedule)",
        f":white_check_mark: Video ready: {t}\nNot sent to Postiz: Postiz error\nsecond line",
        f":white_check_mark: Video ready: {t}",
        f":x: Video failed: {t}\nffmpeg failed: boom",
        f":x: Video failed: {t}",
    ]


def test_a_video_held_by_the_quality_check_says_why(fake_slack):
    pid = db.create_project("douyin:p", "Titre")
    fail = {"level": "fail", "checks": [{"id": "audio", "level": "fail", "msg": "No sound <track>"},
                                         {"id": "black", "level": "warn", "msg": "Black stretch"}]}
    db.update_project(pid, meta={"review": "video", "qa": fail})
    notify.project(pid, "review")
    db.update_project(pid, meta={"review": "script"})  # a script waiting for approval has no picture to judge yet
    notify.project(pid, "review")
    assert fake_slack == [":eyes: Video ready for your approval: Titre\nQuality check failed: No sound &lt;track&gt;",
                          ":eyes: Script ready for your approval: Titre"]


def test_message_in_vietnamese_and_a_project_without_a_channel(fake_slack):
    settings.update({"UI_LANG": "vi"})
    pid = db.create_project("douyin:p", "Titre")
    db.update_project(pid, meta={"title": "Gấu trúc"})
    notify.project(pid, "done")
    assert fake_slack == [":white_check_mark: Video đã xong: Gấu trúc"]


def test_a_failing_slack_never_breaks_the_caller(monkeypatch):
    def down(req):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(down))
    settings.update({"SLACK_WEBHOOK_URL": URL})
    pid = db.create_project("douyin:p", "Titre")
    notify.project(pid, "done")  # chỉ ghi log


def test_test_message_route(fake_slack):
    with TestClient(api.create_app("t")) as c:
        r = c.post("/api/notify/test", headers=H)
        assert r.status_code == 200 and r.json() == {"sent": True}
        assert fake_slack == ["Motio test message: Slack alerts are working."]
        assert c.post("/api/notify/test").status_code == 401  # cần token
        settings.update({"SLACK_WEBHOOK_URL": ""})
        r = c.post("/api/notify/test", headers=H)
        assert r.status_code == 400 and "not set" in r.json()["detail"]
