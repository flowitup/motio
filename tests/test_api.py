import json
import time

import pytest
from fastapi.testclient import TestClient

from motio import api, config, db, newsnow, pipeline, settings

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(monkeypatch):
    with db.conn() as c:
        c.execute("DELETE FROM project")
        c.execute("DELETE FROM trend")
    db.upsert_trend({"id": "douyin:1", "source": "douyin", "ext_id": "1", "url": "https://x", "title_zh": "中文",
                     "title_fr": "Titre", "angle": "angle", "reason": "r", "keywords": {"zh": ["中文"]},
                     "score": 80, "rank": 1})
    db.upsert_trend({"id": "weibo:2", "source": "weibo", "ext_id": "2", "url": "https://y", "title_zh": "微博",
                     "title_fr": "Autre", "score": 40, "rank": 2})

    def fake_produce(pid):
        db.update_project(pid, status="running", step="Dựng", pct=50, log="đang dựng")
        out = config.PROJECTS / str(pid)
        out.mkdir(parents=True, exist_ok=True)
        (out / "script.json").write_text("{}")
        (out / "final.mp4").write_bytes(b"0123456789" * 10)
        db.update_project(pid, status="done", step="Xong", pct=100, log="xong",
                          meta={"video": f"projects/{pid}/final.mp4"})

    monkeypatch.setattr(pipeline, "produce", fake_produce)
    monkeypatch.setattr(pipeline, "rerender", fake_produce)
    monkeypatch.setattr(pipeline, "resume", lambda pid, start=None: fake_produce(pid))
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


def _wait_done(client, pid, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        p = client.get(f"/api/projects/{pid}", headers=H).json()
        if p["status"] in ("done", "failed"):
            return p
        time.sleep(0.02)
    raise AssertionError("project did not finish")


def test_requires_token(client):
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get(f"/api/health?token={TOKEN}").status_code == 401  # query chỉ cho media / SSE
    r = client.get("/api/health", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] and {"llm", "tts", "asr"} <= body["providers"].keys()


def test_trends_filter(client):
    assert [t["id"] for t in client.get("/api/trends", headers=H).json()] == ["douyin:1", "weibo:2"]
    ts = client.get("/api/trends?source=weibo", headers=H).json()
    assert [t["id"] for t in ts] == ["weibo:2"] and ts[0]["source_name"] == "Weibo"


def test_produce_flow_events_and_media(client):
    r = client.post("/api/trends/douyin:1/produce", headers=H)
    assert r.status_code == 202
    pid = r.json()["project_id"]
    p = _wait_done(client, pid)
    assert p["status"] == "done" and p["trend"]["id"] == "douyin:1" and "xong" in p["log"]
    assert [x["id"] for x in client.get("/api/projects", headers=H).json()] == [pid]

    with client.stream("GET", f"/api/projects/{pid}/events?token={TOKEN}") as s:
        text = "".join(s.iter_text())
    data = json.loads(text.split("data: ", 1)[1].split("\n", 1)[0])
    assert data["status"] == "done" and data["pct"] == 100 and data["log_tail"][-1].endswith("xong")
    assert "event: end" in text

    video = p["meta"]["video"]
    assert client.get(f"/media/{video}").status_code == 401
    m = client.get(f"/media/{video}?token={TOKEN}", headers={"Range": "bytes=0-9"})
    assert m.status_code == 206 and m.content == b"0123456789"


def test_produce_unknown_trend(client):
    assert client.post("/api/trends/nope:1/produce", headers=H).status_code == 404


def test_daily_quota(client):
    settings.update({"MAX_VIDEOS_PER_DAY": 1})
    assert client.post("/api/trends/douyin:1/produce", headers=H).status_code == 202
    r = client.post("/api/trends/weibo:2/produce", headers=H)
    assert r.status_code == 429


def test_rerender(client):
    pid = client.post("/api/trends/douyin:1/produce", headers=H).json()["project_id"]
    _wait_done(client, pid)
    assert client.post(f"/api/projects/{pid}/rerender", headers=H).status_code == 202
    assert _wait_done(client, pid)["status"] == "done"
    assert client.post("/api/projects/999/rerender", headers=H).status_code == 404


def test_retry(client):
    pid = db.create_project("douyin:1", "x")
    db.update_project(pid, status="failed", log="LỖI")
    p = client.get(f"/api/projects/{pid}", headers=H).json()
    assert p["retry"] == {"auto": "search", "steps": ["search"]}
    assert client.post(f"/api/projects/{pid}/retry", headers=H, json={"start": "voice"}).status_code == 409
    assert client.post(f"/api/projects/{pid}/retry", headers=H, json={"start": "nope"}).status_code == 400
    r = client.post(f"/api/projects/{pid}/retry", headers=H)
    assert r.status_code == 202 and r.json()["start"] == "search"
    assert _wait_done(client, pid)["status"] == "done"
    assert client.post("/api/projects/999/retry", headers=H).status_code == 404


def test_produce_with_links(client):
    r = client.post("/api/trends/douyin:1/produce", headers=H,
                    json={"links": ["https://www.douyin.com/video/1", " https://x.com/a/status/2 "]})
    assert r.status_code == 202
    meta = client.get(f"/api/projects/{r.json()['project_id']}", headers=H).json()["meta"]
    assert meta["links"] == ["https://www.douyin.com/video/1", "https://x.com/a/status/2"]
    bad = client.post("/api/trends/douyin:1/produce", headers=H, json={"links": ["douyin.com/1"]})
    assert bad.status_code == 400
    empty = client.post("/api/trends/douyin:1/produce", headers=H, json={"links": [], "links_only": True})
    assert empty.status_code == 400


def test_create_topic_project_and_set_rights(client):
    r = client.post("/api/projects", headers=H, json={"topic": "gấu trúc", "links": ["https://fb.watch/abc"],
                                                      "duration": 90})
    assert r.status_code == 202
    pid = r.json()["project_id"]
    p = _wait_done(client, pid)
    assert p["mode"] == "topic" and p["trend"] is None and p["title"] == "gấu trúc"
    assert p["meta"]["duration"] == 90 and p["meta"]["rights"] == "unknown" and not p["meta"]["links_only"]
    r = client.patch(f"/api/projects/{pid}", headers=H, json={"rights": "licensed"})
    assert r.status_code == 200 and r.json()["meta"]["rights"] == "licensed"
    assert client.patch(f"/api/projects/{pid}", headers=H, json={"rights": "x"}).status_code == 400
    assert client.post("/api/projects", headers=H, json={}).status_code == 400
    assert client.post("/api/projects", headers=H, json={"topic": "x", "duration": 10}).status_code == 400
    only = client.post("/api/projects", headers=H, json={"links": ["https://www.douyin.com/video/1"]}).json()
    assert db.get_project(only["project_id"])["meta"]["links_only"] is True


def test_add_links_queues_retry(client):
    pid = db.create_project("douyin:1", "x")
    db.update_project(pid, status="failed", meta={"chosen": [{"url": "https://yt/0"}]})
    r = client.post(f"/api/projects/{pid}/links", headers=H, json={"links": ["https://x.com/a/status/2"]})
    assert r.status_code == 202 and r.json()["start"] == "download"
    p = _wait_done(client, pid)
    assert [c["url"] for c in p["meta"]["chosen"]] == ["https://yt/0", "https://x.com/a/status/2"]
    assert client.post(f"/api/projects/{pid}/links", headers=H, json={"links": []}).status_code == 400


def test_media_blocks_traversal_and_settings(client):
    settings.update({"ELEVENLABS_API_KEY": "secret-key-1234"})
    assert client.get(f"/media/settings.json?token={TOKEN}").status_code == 404
    assert client.get(f"/media/../pyproject.toml?token={TOKEN}").status_code == 404
    assert client.get(f"/media/%2e%2e/pyproject.toml?token={TOKEN}").status_code == 404


def test_settings_roundtrip(client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env-key-4321")
    s = client.get("/api/settings", headers=H).json()
    assert s["ELEVENLABS_API_KEY"]["value"] == "••••4321"
    r = client.put("/api/settings", headers=H, json={"LLM_MODEL": "opus", "ELEVENLABS_API_KEY": "••••4321"})
    assert r.status_code == 200 and r.json()["LLM_MODEL"]["value"] == "opus"
    assert config.env("ELEVENLABS_API_KEY") == "env-key-4321"
    assert client.put("/api/settings", headers=H, json={"BAD": 1}).status_code == 400


def test_voices_without_key(client):
    assert client.get("/api/voices", headers=H).status_code == 409


def test_stale_projects_marked_failed_on_startup():
    pid = db.create_project("douyin:1", "x")
    db.update_project(pid, status="running")
    with TestClient(api.create_app(TOKEN)):
        pass
    p = db.get_project(pid)
    assert p["status"] == "failed" and "engine đã dừng" in p["log"]


def test_cors_preflight(client):
    r = client.options("/api/health", headers={"Origin": "tauri://localhost", "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "authorization"})
    assert r.headers.get("access-control-allow-origin") == "tauri://localhost"


def test_publish_to_postiz(client, fake_postiz):
    assert client.get("/api/health", headers=H).json()["postiz"] is True
    chans = client.get("/api/postiz/channels", headers=H).json()
    assert [(c["id"], c["provider"]) for c in chans] == [("tt1", "tiktok"), ("yt1", "youtube")]

    pid = client.post("/api/trends/douyin:1/produce", headers=H).json()["project_id"]
    _wait_done(client, pid)
    r = client.post(f"/api/projects/{pid}/publish", headers=H, json={"channels": ["tt1"], "mode": "draft"})
    assert r.status_code == 200 and r.json()["posts"] == [{"postId": "p0", "integration": "tt1"}]
    p = client.get(f"/api/projects/{pid}", headers=H).json()
    assert [e["mode"] for e in p["meta"]["postiz"]] == ["draft"] and "Postiz (draft): Motio TikTok" in p["log"]
    assert p["meta"]["video"] == f"projects/{pid}/final.mp4"  # meta cũ giữ nguyên

    bad = client.post(f"/api/projects/{pid}/publish", headers=H, json={"channels": ["tt1"], "mode": "schedule"})
    assert bad.status_code == 400


def test_publish_needs_config_and_finished_video(client):
    assert client.get("/api/postiz/channels", headers=H).status_code == 409
    pid = db.create_project("douyin:1", "x")
    assert client.post(f"/api/projects/{pid}/publish", headers=H, json={"channels": ["tt1"]}).status_code == 409
    assert client.post("/api/projects/999/publish", headers=H, json={"channels": ["tt1"]}).status_code == 404


def test_scheduled_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(newsnow, "refresh", lambda: calls.append(time.time()) or {"new": 0, "scored": 0, "errors": {}})
    monkeypatch.setattr(api, "SCHED_TICK", 0.01)
    monkeypatch.setattr(api, "FIRST_DELAY", 0.0)
    with TestClient(api.create_app(TOKEN)) as c:
        st = c.get("/api/state", headers=H).json()
        assert st["refresh_every_min"] == 0 and st["next_refresh"] is None
        time.sleep(0.1)
        assert calls == []  # tắt theo mặc định
        settings.update({"REFRESH_EVERY_MIN": 30})
        end = time.time() + 3
        while not calls and time.time() < end:
            time.sleep(0.01)
        assert len(calls) == 1
        st = c.get("/api/state", headers=H).json()
        assert st["refresh_every_min"] == 30 and st["next_refresh"] == pytest.approx(st["last_refresh"] + 1800)
        time.sleep(0.1)
        assert len(calls) == 1  # lần sau là 30 phút nữa
