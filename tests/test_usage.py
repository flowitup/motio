"""Chi phí và thống kê (motio/usage.py): ký tự ElevenLabs theo dự án / kênh / công cụ, giá, ngân sách, trang Stats."""
import base64
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motio import api, automake, channels, db, settings, tts, usage

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}
DAY = 86400.0


@pytest.fixture(autouse=True)
def clean_usage():
    with db.conn() as c:
        c.execute("DELETE FROM usage")
        c.execute("DELETE FROM project")
    yield
    with db.conn() as c:
        c.execute("DELETE FROM usage")


@pytest.fixture
def client():
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


def _channel(name="Chine Info", **extra) -> int:
    return db.save_channel(None, {**channels.DEFAULTS, "name": name, **extra}, False)


def _project(status="done", channel=None, created=None, postiz=False) -> int:
    pid = db.create_project(None, "p")
    meta = {**({"channel": channel} if channel else {}), **({"postiz": [{"mode": "draft"}]} if postiz else {})}
    db.update_project(pid, status=status, meta=meta)
    if created is not None:
        with db.conn() as c:
            c.execute("UPDATE project SET created_at=? WHERE id=?", (created, pid))
    return pid


def _row(**kw):
    """Một dòng usage ở thời điểm `at` (mặc định bây giờ)."""
    with db.conn() as c:
        c.execute("INSERT INTO usage (at, kind, chars, usd, project_id, channel_id, ref, model, voice) "
                  "VALUES (?, 'tts', ?, ?, ?, ?, ?, 'eleven_multilingual_v2', 'v')",
                  (kw.get("at", time.time()), kw.get("chars", 1000), kw.get("usd", 0.22), kw.get("project_id"),
                   kw.get("channel_id"), kw.get("ref")))


# ---------- giá ----------
def test_cost_uses_the_setting_and_halves_flash_models():
    assert usage.price_per_1k() == usage.DEFAULT_PRICE
    assert usage.cost(1000, "eleven_multilingual_v2") == pytest.approx(0.22)
    assert usage.cost(1000, "eleven_flash_v2_5") == pytest.approx(0.11)
    settings.update({"ELEVENLABS_USD_PER_1K_CHARS": "0.30"})
    assert usage.cost(2000, "eleven_multilingual_v2") == pytest.approx(0.60)


def test_bad_price_or_budget_falls_back_and_is_rejected_by_settings(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_USD_PER_1K_CHARS", "abc")
    monkeypatch.setenv("MONTHLY_BUDGET_USD", "-5")
    assert usage.price_per_1k() == usage.DEFAULT_PRICE and usage.budget() == 0.0
    for key in ("ELEVENLABS_USD_PER_1K_CHARS", "MONTHLY_BUDGET_USD"):
        for bad in ("abc", "-1"):
            with pytest.raises(ValueError, match="number"):
                settings.update({key: bad})
    settings.update({"MONTHLY_BUDGET_USD": "25"})
    assert usage.budget() == 25.0


# ---------- ghi ----------
def test_record_uses_the_context_and_finds_the_channel_from_the_project():
    cid = _channel()
    pid = _project(channel=cid)
    usage.record_tts(500, "eleven_multilingual_v2", "voice1")  # ngoài ngữ cảnh: không thuộc dự án nào
    with usage.context(project_id=pid):
        usage.record_tts(1000, "eleven_multilingual_v2", "voice1")
        with usage.context(ref="x"):  # ngữ cảnh lồng nhau gộp với ngữ cảnh ngoài
            usage.record_tts(200, "eleven_flash_v2_5", "voice2")
    usage.record_tts(0, "m", "v")  # không có ký tự: bỏ qua
    with db.conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM usage ORDER BY id")]
    assert [(r["chars"], r["project_id"], r["channel_id"], r["ref"]) for r in rows] == [
        (500, None, None, None), (1000, pid, cid, None), (200, pid, cid, "x")]
    assert rows[1]["usd"] == pytest.approx(0.22) and rows[2]["usd"] == pytest.approx(0.022)
    assert usage.for_project(pid) == {"tts_chars": 1200, "usd": pytest.approx(0.242), "clip_usd": 0}


def test_elevenlabs_call_charges_the_characters_it_sent(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    sent = {}

    class Reply:
        status_code = 200

        def json(self):
            return {"audio_base64": base64.b64encode(b"mp3").decode(), "alignment": None}

    def post(url, **kw):
        sent.update(kw["json"])
        return Reply()

    monkeypatch.setattr(tts.httpx, "post", post)
    monkeypatch.setattr(tts, "probe_duration", lambda p: 5.0)
    pid = _project()
    with usage.context(project_id=pid), tempfile.TemporaryDirectory() as d:
        tts.synthesize(["Bonjour le monde.", "Deuxième ligne."], Path(d), voice="v9")
    assert sent["text"] == "Bonjour le monde. Deuxième ligne."
    assert usage.for_project(pid)["tts_chars"] == len(sent["text"])


def test_a_failed_elevenlabs_call_is_not_charged(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")

    class Bad:
        status_code = 401
        text = "no"

    monkeypatch.setattr(tts.httpx, "post", lambda url, **kw: Bad())
    with tempfile.TemporaryDirectory() as d, pytest.raises(RuntimeError):
        tts.synthesize(["x"], Path(d), voice="v")
    assert db.usage_sum(0) == (0, 0.0)


# ---------- tổng hợp ----------
def test_summary_groups_by_month_day_and_channel():
    now = time.mktime((2026, 9, 15, 12, 0, 0, 0, 0, -1))
    a, b = _channel("Alpha"), _channel("Beta")
    p1 = _project(channel=a, created=now - 1 * DAY, postiz=True)
    p2 = _project(channel=a, created=now - 2 * DAY)
    p3 = _project(channel=b, created=now - 40 * DAY)  # ngoài 30 ngày và ngoài tháng này
    _project(status="failed", channel=a, created=now - 1 * DAY)
    _project(created=now - 3 * DAY)  # không kênh
    _row(at=now - 1 * DAY, chars=2000, usd=0.44, project_id=p1, channel_id=a)
    _row(at=now - 2 * DAY, chars=1000, usd=0.22, project_id=p2, channel_id=a)
    _row(at=now - 40 * DAY, chars=9000, usd=1.98, project_id=p3, channel_id=b)
    _row(at=now - 3 * DAY, chars=500, usd=0.11, ref="tool:x")  # công cụ lẻ, không kênh
    s = usage.summary(now)

    assert s["price_per_1k"] == usage.DEFAULT_PRICE and s["month"]["since"] == "2026-09-01"
    assert s["month"] == {"since": "2026-09-01", "chars": 3500, "usd": pytest.approx(0.77), "videos": 3}
    assert s["total"] == {"chars": 12500, "usd": pytest.approx(2.75)}
    assert len(s["days"]) == 30 and s["days"][-1]["date"] == "2026-09-15"
    day = {d["date"]: d for d in s["days"]}
    assert day["2026-09-14"] == {"date": "2026-09-14", "videos": 1, "chars": 2000, "usd": 0.44}
    assert day["2026-09-13"]["videos"] == 1 and day["2026-09-13"]["chars"] == 1000
    assert day["2026-09-12"]["videos"] == 1 and day["2026-09-12"]["chars"] == 500
    rows = {r["channel"]: r for r in s["channels"]}
    assert set(rows) == {a, None}  # Beta: mọi thứ nằm ngoài 30 ngày
    assert rows[a]["name"] == "Alpha"
    assert (rows[a]["videos"], rows[a]["failed"], rows[a]["sent"], rows[a]["chars"]) == (2, 1, 1, 3000)
    assert rows[a]["usd"] == pytest.approx(0.66) and rows[a]["usd_per_video"] == pytest.approx(0.33)
    assert rows[None]["name"] == "" and rows[None]["videos"] == 1 and rows[None]["chars"] == 500
    assert s["channels"][0]["channel"] == a  # nhiều video nhất trước


def test_month_videos_count_even_when_the_month_started_before_the_30_day_window():
    now = time.mktime((2026, 10, 31, 12, 0, 0, 0, 0, -1))  # ngày 1 cách 30 ngày: ngoài cửa sổ 30 ngày
    _project(created=now - 30 * DAY)
    assert usage.summary(now)["month"]["videos"] == 1


def test_budget_states_and_the_auto_make_pause(monkeypatch):
    now = time.mktime((2026, 9, 15, 12, 0, 0, 0, 0, -1))
    assert usage.summary(now)["budget"] == {"usd": 0.0, "ratio": 0.0, "state": "none", "auto_paused": False}
    settings.update({"MONTHLY_BUDGET_USD": "10"})
    _row(at=now - DAY, usd=7.0)
    assert usage.summary(now)["budget"]["state"] == "ok" and not usage.over_budget(now)
    _row(at=now - DAY, usd=1.5)
    assert usage.summary(now)["budget"]["state"] == "warn"
    _row(at=now - DAY, usd=2.0)
    _channel("Auto", auto_score=70)
    b = usage.summary(now)["budget"]
    assert (b["state"], b["ratio"], b["auto_paused"]) == ("over", 1.05, True) and usage.over_budget(now)
    _row(at=now - 40 * DAY, usd=100.0)  # tháng trước không tính
    assert usage.month_spent(now) == pytest.approx(10.5)


def test_auto_make_stops_when_the_month_is_over_budget(monkeypatch):
    ch = {**channels.DEFAULTS, "id": 1, "name": "A", "auto_score": 50, "auto_daily": 3, "default": True}
    monkeypatch.setattr(channels, "listing", lambda: [ch])
    monkeypatch.setattr(db, "list_trends", lambda **kw: [{"id": "t", "status": "new", "score": 90,
                                                          "first_seen": time.time()}])
    assert len(automake.picks()) == 1
    settings.update({"MONTHLY_BUDGET_USD": "1"})
    _row(usd=2.0)
    assert automake.picks() == []
    settings.update({"MONTHLY_BUDGET_USD": ""})
    assert len(automake.picks()) == 1


# ---------- API ----------
def test_stats_route_and_project_usage(client):
    assert client.get("/api/stats").status_code == 401
    pid = _project()
    _row(project_id=pid, chars=1500, usd=0.33)
    s = client.get("/api/stats", headers=H).json()
    assert s["month"]["chars"] == 1500 and s["budget"]["state"] == "none"
    assert set(s) == {"price_per_1k", "month", "budget", "total", "days", "channels"}
    full = client.get(f"/api/projects/{pid}", headers=H).json()
    assert full["usage"] == {"tts_chars": 1500, "usd": 0.33, "clip_usd": 0}


def test_a_read_aloud_job_is_charged_as_a_tool(client, monkeypatch):
    def synth(lines, out_dir, voice=None):
        usage.record_tts(len(lines[0]), "eleven_multilingual_v2", "v")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "n.mp3").write_bytes(b"x")
        return {"audio": str(Path(out_dir) / "n.mp3"), "voice": "V", "provider": "elevenlabs"}

    monkeypatch.setattr(tts, "provider", lambda: "elevenlabs")
    monkeypatch.setattr(tts, "synthesize", synth)
    r = client.post("/api/tools/speak", headers=H, data={"text": "Bonjour"})
    job_id = r.json()["id"]
    end = time.time() + 20
    while time.time() < end and client.get(f"/api/tools/jobs/{job_id}", headers=H).json()["status"] != "done":
        time.sleep(0.05)
    with db.conn() as c:
        rows = [dict(x) for x in c.execute("SELECT chars, project_id, ref FROM usage")]
    assert rows == [{"chars": 7, "project_id": None, "ref": f"tool:{job_id}"}]
