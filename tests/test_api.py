import json
import time

import pytest
from fastapi.testclient import TestClient

from motio import api, config, db, newsnow, pipeline, settings, watch

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def seeded(monkeypatch):
    """Hai tin (80 và 40 điểm) và pipeline giả, chưa tạo app."""
    with db.conn() as c:
        c.execute("DELETE FROM project")
        c.execute("DELETE FROM trend")
    db.upsert_trend({"id": "douyin:1", "source": "douyin", "ext_id": "1", "url": "https://x", "title_zh": "中文",
                     "title_fr": "Titre", "angle": "angle", "reason": "r", "keywords": {"zh": ["中文"]},
                     "score": 80, "rank": 1})
    db.upsert_trend({"id": "weibo:2", "source": "weibo", "ext_id": "2", "url": "https://y", "title_zh": "微博",
                     "title_fr": "Autre", "score": 40, "rank": 2})

    def fake_produce(pid, **kw):
        db.update_project(pid, status="running", step="Render", pct=50,
                          log="rendering" + (f" from {kw['start']}" if kw else ""))
        out = config.PROJECTS / str(pid)
        out.mkdir(parents=True, exist_ok=True)
        (out / "script.json").write_text("{}", encoding="utf-8")
        (out / "final.mp4").write_bytes(b"0123456789" * 10)
        db.update_project(pid, status="done", step="Done", pct=100, log="finished",
                          meta={"video": f"projects/{pid}/final.mp4"})

    monkeypatch.setattr(pipeline, "produce", fake_produce)
    monkeypatch.setattr(pipeline, "rerender", fake_produce)
    monkeypatch.setattr(pipeline, "resume", lambda pid, start=None: fake_produce(pid))


@pytest.fixture
def client(seeded):
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
    assert 0 < body["disk"]["free"] <= body["disk"]["total"]  # app từ xa hiện ổ của máy chủ còn bao nhiêu


def test_trends_filter(client):
    assert [t["id"] for t in client.get("/api/trends", headers=H).json()] == ["douyin:1", "weibo:2"]
    ts = client.get("/api/trends?source=weibo", headers=H).json()
    assert [t["id"] for t in ts] == ["weibo:2"] and ts[0]["source_name"] == "Weibo"


def test_produce_flow_events_and_media(client):
    r = client.post("/api/trends/douyin:1/produce", headers=H)
    assert r.status_code == 202
    pid = r.json()["project_id"]
    p = _wait_done(client, pid)
    assert p["status"] == "done" and p["trend"]["id"] == "douyin:1" and "finished" in p["log"]
    assert [x["id"] for x in client.get("/api/projects", headers=H).json()] == [pid]

    with client.stream("GET", f"/api/projects/{pid}/events?token={TOKEN}") as s:
        text = "".join(s.iter_text())
    data = json.loads(text.split("data: ", 1)[1].split("\n", 1)[0])
    assert data["status"] == "done" and data["pct"] == 100 and data["log_tail"][-1].endswith("finished")
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
    db.update_project(pid, status="failed", log="ERROR")
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


def test_edit_script(client):
    pid = client.post("/api/trends/douyin:1/produce", headers=H).json()["project_id"]
    _wait_done(client, pid)
    plan = {"title_fr": "Titre", "description": "D.", "hashtags": ["#Chine"],
            "lines": [{"text": f"ligne {i}", "clips": [{"src": 0, "start": 5, "end": 9}]} for i in range(4)]}
    (config.PROJECTS / str(pid) / "script.json").write_text(json.dumps(plan), encoding="utf-8")
    assert client.get(f"/api/projects/{pid}", headers=H).json()["has_script"] is True
    v = client.get(f"/api/projects/{pid}/script", headers=H).json()
    assert v["script"]["lines"][0]["text"] == "ligne 0" and v["max_seconds"] == pipeline.MAX_SECONDS
    body = {**v["script"], "lines": [*v["script"]["lines"][:3], {"text": "nouvelle ligne"}]}
    r = client.put(f"/api/projects/{pid}/script", headers=H, json=body)
    assert r.status_code == 200 and r.json()["script"]["lines"][3] == {"text": "nouvelle ligne", "clips": []}
    assert "Script edited" in client.get(f"/api/projects/{pid}", headers=H).json()["log"]
    short = client.put(f"/api/projects/{pid}/script", headers=H, json={**body, "lines": body["lines"][:2]})
    assert short.status_code == 400 and "3" in short.json()["detail"]
    db.update_project(pid, status="running")
    assert client.put(f"/api/projects/{pid}/script", headers=H, json=body).status_code == 409
    empty = db.create_project(None, "x", mode="topic")
    assert client.get(f"/api/projects/{empty}", headers=H).json()["has_script"] is False
    assert client.get(f"/api/projects/{empty}/script", headers=H).status_code == 404
    assert client.get("/api/projects/999/script", headers=H).status_code == 404


def test_delete_project(client):
    pid = client.post("/api/trends/douyin:1/produce", headers=H).json()["project_id"]
    _wait_done(client, pid)
    assert client.get("/api/trends", headers=H).json()[0]["status"] == "used"
    db.update_project(pid, status="running")
    assert client.delete(f"/api/projects/{pid}", headers=H).status_code == 409
    db.update_project(pid, status="done")
    r = client.delete(f"/api/projects/{pid}", headers=H)
    assert r.status_code == 200 and r.json() == {"deleted": pid}
    assert client.get(f"/api/projects/{pid}", headers=H).status_code == 404
    assert not (config.PROJECTS / str(pid)).exists()
    assert client.get("/api/trends", headers=H).json()[0]["status"] == "new"  # hiện lại nút Làm video
    assert client.delete("/api/projects/999", headers=H).status_code == 404


def test_media_blocks_traversal_and_settings(client):
    settings.update({"ELEVENLABS_API_KEY": "secret-key-1234"})
    assert client.get(f"/media/settings.json?token={TOKEN}").status_code == 404
    assert client.get(f"/media/../pyproject.toml?token={TOKEN}").status_code == 404
    assert client.get(f"/media/%2e%2e/pyproject.toml?token={TOKEN}").status_code == 404


def test_media_never_serves_the_cookie_file(client):
    jar = config.CACHE / "cookies.txt"  # inside a served folder: still never served once it is the cookie file
    jar.write_text("# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tTRUE\t2000000000\tSESSDATA\tsecret\n")
    assert client.get(f"/media/cache/cookies.txt?token={TOKEN}").status_code == 200
    settings.update({"YTDLP_COOKIES_FILE": str(jar)})
    assert client.get(f"/media/cache/cookies.txt?token={TOKEN}").status_code == 404
    jar.unlink()


def test_media_serves_only_what_the_engine_made_not_the_database_or_env(client):
    assert (config.DATA / "motio.sqlite3").is_file()
    (config.DATA / ".env").write_text("ANTHROPIC_API_KEY=sk-secret\n")
    (config.CACHE / ".env.local").write_text("x=1\n")
    for p in ("motio.sqlite3", ".env", "cache/.env.local", "models/x.onnx", "projects/../motio.sqlite3"):
        assert client.get(f"/media/{p}?token={TOKEN}").status_code == 404, p
    (config.DATA / ".env").unlink()
    (config.CACHE / ".env.local").unlink()


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
    assert p["status"] == "failed" and "engine stopped" in p["log"]


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


def test_publish_the_16_9_copy(client, fake_postiz):
    pid = client.post("/api/trends/douyin:1/produce", headers=H).json()["project_id"]
    _wait_done(client, pid)
    body = {"channels": ["yt1"], "mode": "draft", "version": "wide"}
    assert client.post(f"/api/projects/{pid}/publish", headers=H, json=body).status_code == 409  # chưa có bản 16:9
    (config.PROJECTS / str(pid) / "final_wide.mp4").write_bytes(b"w")
    db.update_project(pid, meta={"wide": f"projects/{pid}/final_wide.mp4"})
    r = client.post(f"/api/projects/{pid}/publish", headers=H, json=body)
    assert r.status_code == 200
    p = client.get(f"/api/projects/{pid}", headers=H).json()
    assert p["meta"]["postiz"][-1]["version"] == "wide" and "Postiz (draft, 16:9): Motio YouTube" in p["log"]
    bad = client.post(f"/api/projects/{pid}/publish", headers=H, json={**body, "version": "square"})
    assert bad.status_code == 400


def test_publish_needs_config_and_finished_video(client):
    assert client.get("/api/postiz/channels", headers=H).status_code == 409
    pid = db.create_project("douyin:1", "x")
    assert client.post(f"/api/projects/{pid}/publish", headers=H, json={"channels": ["tt1"]}).status_code == 409
    assert client.post("/api/projects/999/publish", headers=H, json={"channels": ["tt1"]}).status_code == 404


def test_scheduled_refresh(monkeypatch):
    calls, checks = [], []
    monkeypatch.setattr(newsnow, "refresh", lambda: calls.append(time.time()) or {"new": 0, "scored": 0, "errors": {}})
    monkeypatch.setattr(watch, "check_all", lambda ids=None: checks.append(ids) or {"checked": 0, "new": 0})
    monkeypatch.setattr(api, "SCHED_TICK", 0.01)
    monkeypatch.setattr(api, "FIRST_DELAY", 0.0)
    with TestClient(api.create_app(TOKEN)) as c:
        st = c.get("/api/state", headers=H).json()
        assert st["refresh_every_min"] == 0 and st["next_refresh"] is None
        time.sleep(0.1)
        assert calls == [] and checks == []  # tắt theo mặc định
        settings.update({"REFRESH_EVERY_MIN": 30})
        end = time.time() + 3
        while not calls and time.time() < end:
            time.sleep(0.01)
        assert len(calls) == 1
        st = c.get("/api/state", headers=H).json()
        assert st["refresh_every_min"] == 30 and st["next_refresh"] == pytest.approx(st["last_refresh"] + 1800)
        while not checks and time.time() < end:
            time.sleep(0.01)
        assert checks == [None]  # nguồn theo dõi: cùng nhịp với tin hot
        st = c.get("/api/state", headers=H).json()
        assert st["next_watch"] == pytest.approx(st["last_watch"] + 1800)
        time.sleep(0.1)
        assert len(calls) == 1 and len(checks) == 1  # lần sau là 30 phút nữa


def test_scheduled_refresh_auto_makes_trends_above_a_channel_score(seeded, monkeypatch):
    monkeypatch.setattr(newsnow, "refresh", lambda: {"new": 0, "scored": 0, "errors": {}})
    monkeypatch.setattr(watch, "check_all", lambda ids=None: {"checked": 0, "new": 0})
    monkeypatch.setattr(api, "SCHED_TICK", 0.01)
    monkeypatch.setattr(api, "FIRST_DELAY", 0.0)
    with TestClient(api.create_app(TOKEN)) as c:
        ch = c.post("/api/channels", headers=H, json={"name": "Chine", "auto_score": 75, "auto_daily": 1,
                                                       "gate_script": False, "gate_video": False}).json()
        assert ch["auto_score"] == 75 and ch["wide_postiz"] == []
        settings.update({"REFRESH_EVERY_MIN": 30})
        end = time.time() + 3
        while not c.get("/api/state", headers=H).json()["last_auto"] and time.time() < end:
            time.sleep(0.02)
        auto = c.get("/api/state", headers=H).json()["last_auto"]
        assert auto and len(auto["projects"]) == 1  # douyin:1 (80) đạt 75; weibo:2 (40) thì không
        p = _wait_done(c, auto["projects"][0])
        assert p["trend_id"] == "douyin:1" and p["meta"]["auto"] is True and p["meta"]["channel"] == ch["id"]


def test_channels_crud(client):
    assert client.get("/api/channels", headers=H).json() == []
    bad = client.post("/api/channels", headers=H, json={"name": "x", "send_mode": "schedule", "postiz": ["tt1"]})
    assert bad.status_code == 400 and "posting time" in bad.json()["detail"]
    a = client.post("/api/channels", headers=H, json={"name": "Chine Express", "badge": "ACTU CHINE", "default": True})
    assert a.status_code == 201 and a.json()["default"] is True and a.json()["gate_script"] is True
    b = client.post("/api/channels", headers=H, json={"name": "Tech", "hashtags": ["tech"], "default": True}).json()
    got = client.get("/api/channels", headers=H).json()
    assert [(c["name"], c["default"]) for c in got] == [("Chine Express", False), ("Tech", True)]
    up = client.put(f"/api/channels/{b['id']}", headers=H, json={"name": "Tech FR", "duration": 90})
    assert up.status_code == 200 and up.json()["duration"] == 90 and up.json()["default"] is False
    assert client.put("/api/channels/999", headers=H, json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/channels/{b['id']}", headers=H).status_code == 200
    assert client.delete(f"/api/channels/{b['id']}", headers=H).status_code == 404


def test_produce_picks_the_channel(client):
    ch = client.post("/api/channels", headers=H, json={"name": "Chine", "duration": 70, "default": True,
                                                        "gate_script": False, "gate_video": False}).json()
    pid = client.post("/api/trends/douyin:1/produce", headers=H).json()["project_id"]  # không nói: kênh mặc định
    meta = _wait_done(client, pid)["meta"]
    assert meta["channel"] == ch["id"] and meta["duration"] == 70
    pid = client.post("/api/trends/douyin:1/produce", headers=H, json={"channel": 0}).json()["project_id"]
    assert "channel" not in _wait_done(client, pid)["meta"]
    assert client.post("/api/trends/douyin:1/produce", headers=H, json={"channel": 999}).status_code == 400
    r = client.post("/api/projects", headers=H, json={"topic": "gấu trúc", "channel": ch["id"], "duration": 90})
    meta = _wait_done(client, r.json()["project_id"])["meta"]
    assert meta["channel"] == ch["id"] and meta["duration"] == 90  # chủ đề: giữ độ dài đã chọn


def test_approve_script_then_video(client, fake_postiz):
    ch = client.post("/api/channels", headers=H, json={"name": "Chine", "postiz": ["tt1"]}).json()
    pid = client.post("/api/trends/douyin:1/produce", headers=H, json={"channel": ch["id"]}).json()["project_id"]
    _wait_done(client, pid)
    assert client.post(f"/api/projects/{pid}/approve", headers=H).status_code == 409  # không chờ duyệt

    db.update_project(pid, status="review", step="Awaiting script approval", meta={"review": "script"})
    r = client.post(f"/api/projects/{pid}/approve", headers=H)
    assert r.status_code == 202 and r.json()["review"] == "script"
    p = _wait_done(client, pid)
    assert p["meta"]["review"] is None and "Script approved" in p["log"] and "from voice" in p["log"]

    db.update_project(pid, status="review", step="Awaiting video approval", meta={"review": "video"})
    assert client.post(f"/api/projects/{pid}/approve", headers=H, json={"send": True}).status_code == 202
    p = _wait_done(client, pid)
    assert p["status"] == "done" and [e["profile"] for e in p["meta"]["postiz"]] == [ch["id"]]


def test_starting_a_video_without_the_keys_it_needs_is_refused_before_a_project_exists(client, monkeypatch):
    before = len(client.get("/api/projects", headers=H).json())
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    r = client.post("/api/projects", headers=H, json={"topic": "pandas"})
    assert r.status_code == 409 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(api, "voice_ready", lambda: False)  # a Linux / Windows machine without a voice
    r = client.post("/api/ai", headers=H, json={"topic": "a lighthouse"})
    assert r.status_code == 409 and "ELEVENLABS_API_KEY" in r.json()["detail"]
    assert len(client.get("/api/projects", headers=H).json()) == before


def _make(name, mode="topic", status="done", **meta):
    pid = db.create_project(None, name, mode=mode)
    db.update_project(pid, status=status, meta=meta)
    return pid


def test_projects_list_filters_and_load_more(client):
    a = _make("Pandas géants", channel=7)
    b = _make("Cuisine du Sichuan", mode="ai", channel=8, title="Sichuan en 80 s")
    c = _make("Pandas roux", status="failed")
    ids = lambda **q: [p["id"] for p in client.get("/api/projects", headers=H, params=q).json()]  # noqa: E731
    assert ids() == [c, b, a]
    assert ids(channel=7) == [a] and ids(channel=8) == [b] and ids(channel=0) == [c]
    assert ids(mode="ai") == [b] and ids(status="failed") == [c]
    assert ids(q="panda") == [c, a] and ids(q="sichuan") == [b]  # the list title or meta.title
    assert ids(q=f"#{a}") == [a] and ids(q="100%") == []  # % and _ are not wildcards
    assert ids(limit=2) == [c, b] and ids(limit=2, before=b) == [a]  # load more, by id
    assert ids(channel=7, mode="ai") == []


def test_project_counts_and_recent_failures(client):
    _make("a", status="review")
    _make("b", status="running")
    old = _make("c", status="failed")
    _make("d", status="failed")
    with db.conn() as conn:
        conn.execute("UPDATE project SET updated_at = ? WHERE id = ?", (time.time() - 30 * 86400, old))
    n = client.get("/api/projects/counts", headers=H).json()
    assert n == {"queued": 0, "running": 1, "review": 1, "done": 0, "failed": 2, "failed_recent": 1}


def test_trends_know_their_project_and_can_be_hidden(client):
    pid = client.post("/api/trends/douyin:1/produce", headers=H).json()["project_id"]
    first = client.get("/api/trends", headers=H).json()[0]
    assert first["id"] == "douyin:1" and first["status"] == "used" and first["project_id"] == pid
    assert client.get("/api/trends", headers=H).json()[1]["project_id"] is None
    assert client.patch("/api/trends/weibo:2", headers=H, json={"hidden": True}).status_code == 200
    assert [t["id"] for t in client.get("/api/trends", headers=H).json()] == ["douyin:1"]
    client.patch("/api/trends/douyin:1", headers=H, json={"hidden": True})  # already made: stays visible
    assert len(client.get("/api/trends", headers=H).json()) == 1
    client.patch("/api/trends/weibo:2", headers=H, json={"hidden": False})
    assert len(client.get("/api/trends", headers=H).json()) == 2
    assert client.patch("/api/trends/nope", headers=H, json={"hidden": True}).status_code == 404


def test_resend_follows_the_channel_settings(client, fake_postiz):
    ch = client.post("/api/channels", headers=H, json={"name": "Chine", "postiz": ["tt1"], "gate_script": False,
                                                        "gate_video": False, "send_mode": "draft"}).json()
    pid = client.post("/api/trends/douyin:1/produce", headers=H, json={"channel": ch["id"]}).json()["project_id"]
    p = _wait_done(client, pid)
    assert "postiz" not in p["meta"] or p["meta"]["postiz"] == []  # the fake produce sends nothing
    r = client.post(f"/api/projects/{pid}/resend", headers=H)
    assert r.status_code == 200 and r.json() == {"sent": True, "error": None}
    p = client.get(f"/api/projects/{pid}", headers=H).json()
    assert p["status"] == "done" and p["step"] == "Done" and [e["profile"] for e in p["meta"]["postiz"]] == [ch["id"]]
    other = client.post("/api/trends/weibo:2/produce", headers=H, json={"channel": 0}).json()["project_id"]
    _wait_done(client, other)
    assert client.post(f"/api/projects/{other}/resend", headers=H).status_code == 409  # no channel, nothing to follow
    db.update_project(pid, status="running")
    assert client.post(f"/api/projects/{pid}/resend", headers=H).status_code == 409
    assert client.post("/api/projects/999/resend", headers=H).status_code == 404


def test_failed_project_in_the_list_carries_its_error(client):
    pid = _make("x", status="failed")
    db.update_project(pid, log="ERROR: Could not download the video: HTTP 412")
    db.update_project(pid, log="rerun later")
    ok = _make("y")
    rows = {p["id"]: p for p in client.get("/api/projects", headers=H).json()}
    assert rows[pid]["error"] == "Could not download the video: HTTP 412"
    assert "error" not in rows[ok]
