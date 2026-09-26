import os
import tempfile

# Dữ liệu test nằm trong thư mục tạm, không đụng data/ thật. Phải đặt trước khi import motio.
os.environ["MOTIO_DATA"] = tempfile.mkdtemp(prefix="motio-test-")

import pytest  # noqa: E402

from motio import settings  # noqa: E402


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    """Mỗi test bắt đầu không có settings.json và không có key trong môi trường."""
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
