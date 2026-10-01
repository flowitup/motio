import os
import tempfile

# Dữ liệu test nằm trong thư mục tạm, không đụng data/ thật. Phải đặt trước khi import motio.
os.environ["MOTIO_DATA"] = tempfile.mkdtemp(prefix="motio-test-")

import pytest  # noqa: E402

from motio import settings  # noqa: E402


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    """Mỗi test bắt đầu không có settings.json, không có key trong môi trường và không có hồ sơ kênh."""
    from motio import db

    with db.conn() as c:
        c.execute("DELETE FROM channel")
    settings.path().unlink(missing_ok=True)
    for k in settings.KEYS:
        monkeypatch.delenv(k, raising=False)
    yield
    settings.path().unlink(missing_ok=True)


@pytest.fixture
def fake_postiz(monkeypatch):
    """Postiz giả qua httpx.MockTransport: 2 kênh (TikTok, YouTube). Trả danh sách request đã nhận."""
    import json

    import httpx

    from motio import postiz

    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        req.read()
        calls.append(req)
        if req.headers.get("authorization") != "pz-key":
            return httpx.Response(401, json={"message": "Invalid API key"})
        path = req.url.path.removeprefix("/api/public/v1")
        if path == "/integrations":
            return httpx.Response(200, json=[
                {"id": "tt1", "name": "Motio TikTok", "identifier": "tiktok", "disabled": False},
                {"id": "yt1", "name": "Motio YouTube", "identifier": "youtube", "disabled": False}])
        if path == "/upload":
            return httpx.Response(200, json={"id": "m1", "name": "final.mp4",
                                             "path": "https://postiz.test/uploads/final.mp4"})
        if path == "/posts":
            posts = json.loads(req.content)["posts"]
            return httpx.Response(200, json=[{"postId": f"p{i}", "integration": p["integration"]["id"]}
                                             for i, p in enumerate(posts)])
        return httpx.Response(404, json={"message": "not found"})

    monkeypatch.setattr(postiz, "_transport", httpx.MockTransport(handler))
    monkeypatch.setenv("POSTIZ_URL", "http://postiz.test/api/")
    monkeypatch.setenv("POSTIZ_API_KEY", "pz-key")
    return calls


@pytest.fixture
def fake_slack(monkeypatch):
    """Slack giả qua httpx.MockTransport. Trả danh sách nội dung các tin đã nhận."""
    import json

    import httpx

    from motio import notify

    texts: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        texts.append(json.loads(req.content)["text"])
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(notify, "_transport", httpx.MockTransport(handler))
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T0/B0/xyz")
    return texts


@pytest.fixture(autouse=True)
def quiet_qa(monkeypatch):
    """Tests that fake the render have no video file to look at: the media part of the quality check (ffprobe and
    FFmpeg) says "all fine". tests/test_qa.py keeps the real function (`real_run`) and runs it on real files."""
    from motio import qa

    monkeypatch.setattr(qa, "run", lambda path, lo, hi: {"level": "ok", "checks": [], "at": 0.0})
