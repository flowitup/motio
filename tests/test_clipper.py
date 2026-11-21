"""Chế độ Clip (clipper.py): chọn khoảnh khắc, khung crop, dự án, dựng 9:16 giữ tiếng gốc, API."""
import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from motio import api, asr, channels, clipper, config, db, delogo, llm, pipeline, qa, search

has_ffmpeg = bool(config.find("ffmpeg") and config.find("ffprobe"))
TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}
SEGS = [{"start": float(s), "end": s + 4.5, "text": f"你好 {s}"} for s in range(0, 40, 5)]


# ---------- phần thuần ----------
def test_tidy_snaps_to_sentences_keeps_length_and_drops_overlaps():
    segs = [{"start": float(s), "end": s + 4.5, "text": "x"} for s in range(0, 300, 5)]
    raw = {"clips": [{"start": 41.2, "end": 113.8, "score": 7, "hook": "  Un  hook ", "why": "ok"},
                     {"start": 60, "end": 120, "score": 9},  # chồng lên cái trước, điểm cao hơn: ở lại, cái kia bị bỏ
                     {"start": 200, "end": 215, "score": 6},  # ngắn quá: được kéo dài tới 62 s
                     {"start": "?", "end": 3},  # hỏng
                     {"start": 250, "end": 330, "score": 5}]}  # quá cuối video, không đủ 62 s: bỏ
    got = clipper.tidy(raw, 300.0, segs, 62.0, 90.0, 3)
    assert got[0]["score"] == 9 and 62 <= got[0]["end"] - got[0]["start"] <= 90
    assert [c["score"] for c in got] == [9, 6]  # le 7 chevauche le 9 ; le 6, trop court, est prolongé jusqu'à 62 s
    assert all(62 <= c["end"] - c["start"] <= 90 and c["end"] <= 300.0 for c in got)  # le 5 ne tient pas avant la fin
    one = clipper.tidy({"clips": [{"start": 41.2, "end": 113.8, "score": 7, "hook": "  Un  hook "}]}, 300.0, segs,
                       62.0, 90.0, 3)
    assert one[0]["hook"] == "Un hook" and one[0]["start"] == 39.85 and one[0]["end"] - one[0]["start"] <= 90
    assert clipper.tidy("nonsense", 300.0, segs, 62.0, 90.0, 3) == []
    assert clipper.tidy({"clips": [{"start": 0, "end": 10}]}, 10.0, segs, 62.0, 90.0, 3) == []  # video trop court
    assert clipper.tidy({"clips": [{"start": 0, "end": 10, "score": 99}]}, 10.0, segs, 5.0, 90.0, 3)[0]["score"] == 10


def test_loud_moments_pick_the_loudest_windows_without_overlap():
    levels = [-60.0] * 100
    for i in range(30, 60):
        levels[i] = -10.0
    got = clipper.loud_moments(levels, 100.0, 15.0, 25.0, 2)
    assert got[0]["start"] >= 20 and got[0]["end"] - got[0]["start"] == 20
    assert len(got) == 2 and got[1]["start"] - got[0]["start"] >= 20
    assert clipper.loud_moments([], 100.0, 15.0, 25.0, 2) == []
    assert clipper.loud_moments([-20.0] * 10, 10.0, 15.0, 25.0, 2) == []


def test_clean_crop_sorts_clamps_and_limits():
    assert clipper.clean_crop(None) == {"fit": False, "x": [[0.0, 0.5]]}
    assert clipper.clean_crop({"x": 0.3}) == {"fit": False, "x": [[0.0, 0.3]]}
    got = clipper.clean_crop({"fit": True, "x": [[5, 1.4], [1, -2], [99, 0.5]]}, 20.0)
    assert got == {"fit": True, "x": [[1.0, 0.0], [5.0, 1.0], [20.0, 0.5]]}
    with pytest.raises(ValueError):
        clipper.clean_crop({"x": []})
    with pytest.raises(ValueError):
        clipper.clean_crop({"x": [[0, 0.5]] * (clipper.MAX_KEYS + 1)})
    with pytest.raises(ValueError):
        clipper.clean_crop({"x": [["a", "b"]]})
    with pytest.raises(ValueError):
        clipper.clean_crop("left")


def test_x_expression_moves_linearly_between_keys():
    assert clipper._x_expr([[0.0, 0.5]]) == "0.5000"
    e = clipper._x_expr([[0.0, 0.2], [4.0, 0.6], [8.0, 0.6]])
    assert e.startswith("if(lt(t,4.00),0.2000+(0.4000)*max(t-0.00,0)/4.00,if(lt(t,8.00),")
    assert e.endswith(",0.6000))")


def test_clip_length_follows_the_62_to_90_rule_unless_short_clips_are_on():
    ok = {"start": 10, "end": 80}
    assert clipper.clean_clip(ok, 200.0, False)["end"] == 80.0
    with pytest.raises(ValueError, match="at least 62 s"):
        clipper.clean_clip({"start": 10, "end": 40}, 200.0, False)
    assert clipper.clean_clip({"start": 10, "end": 40}, 200.0, True)["captions"] == "fr"
    with pytest.raises(ValueError, match="at least 15 s"):
        clipper.clean_clip({"start": 10, "end": 20}, 200.0, True)
    with pytest.raises(ValueError, match="at most 90 s"):
        clipper.clean_clip({"start": 0, "end": 91}, 200.0, True)
    with pytest.raises(ValueError, match="inside the video"):
        clipper.clean_clip({"start": 150, "end": 230}, 200.0, False)
    with pytest.raises(ValueError, match="Captions must be"):
        clipper.clean_clip({**ok, "captions": "klingon"}, 200.0, False)
    assert clipper.clean_clip({**ok, "hook": None}, 200.0, False)["hook"] is None  # None = Claude écrit le hook
    assert clipper.clean_clip({**ok, "hook": ""}, 200.0, False)["hook"] == ""  # "" = pas de hook


def test_export_makes_one_project_per_clip_or_none():
    clips = [{"start": 0, "end": 70}, {"start": 80, "end": 150, "hook": "Wow", "crop": {"fit": True, "x": 0.8}}]
    ids = clipper.export("https://www.youtube.com/watch?v=abc", clips, False, 300.0)
    assert len(ids) == 2
    p = db.get_project(ids[1])
    assert p["mode"] == "clip" and p["title"] == "Wow"
    assert p["meta"]["clip"]["crop"] == {"fit": True, "x": [[0.0, 0.8]]} and p["meta"]["links_only"] is True
    before = len(db.list_projects(200))
    with pytest.raises(ValueError):
        clipper.export("https://www.youtube.com/watch?v=abc", [clips[0], {"start": 0, "end": 5}], False, 300.0)
    assert len(db.list_projects(200)) == before
    with pytest.raises(ValueError, match="at least one"):
        clipper.export("https://www.youtube.com/watch?v=abc", [], False)
    with pytest.raises(ValueError, match="link"):
        clipper.create("", {"start": 0, "end": 70})


# ---------- cả pipeline: nguồn thật (FFmpeg), Claude / Whisper giả ----------
@pytest.fixture
def fake(monkeypatch, tmp_path):
    seen = {"prompts": []}
    src = tmp_path / "YouTube_c1.mp4"
    if has_ffmpeg:
        subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=1280x720:rate=25:duration=40", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=40", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt",
                        "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)

    def download(url, out_dir, cookies=False, **kw):
        seen["downloads"] = seen.get("downloads", 0) + 1
        return {"path": str(src), "url": url, "id": "c1", "title": "Trailer + reaction", "platform": "YouTube",
                "uploader": "up", "uploader_url": "", "upload_date": "", "duration": 40.0, "license": ""}

    def ask_json(prompt, system, **kw):
        seen["prompts"].append((prompt, system))
        if system.startswith("You are a professional subtitle translator"):
            n = len(json.loads(prompt)["subtitles"])
            return {"lines": [f"Bonjour {i} !" for i in range(n)]}
        if system.startswith("Tu es monteur"):
            return {"clips": [{"start": 5, "end": 29.5, "score": 9, "hook": "ÇA VA TOUT CHANGER", "why": "wow"},
                              {"start": 10, "end": 20, "score": 3}]}
        return {"title_fr": "Le trailer qui fait réagir", "description": "Une réaction.", "hashtags": ["#GTA"],
                "hook": "TRAILER. REACTION."}

    monkeypatch.setattr(search, "download", download)
    monkeypatch.setattr(asr, "transcribe", lambda path: {"language": "zh", "segments": SEGS})
    monkeypatch.setattr(llm, "ask_json", ask_json)
    return seen


def _clip(**kw) -> dict:
    return {"start": 5, "end": 25, "crop": {"fit": False, "x": [[0, 0.2], [10, 0.8]]}, **kw}


@pytest.mark.skipif(not has_ffmpeg, reason="needs FFmpeg")
def test_full_clip_run_keeps_the_original_sound_and_makes_a_vertical_video(fake):
    pid = clipper.create("https://www.youtube.com/watch?v=c1", _clip(), short=True, duration=40.0)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done", p["log"]
    out = config.PROJECTS / str(pid)
    info = delogo.probe(out / "final.mp4")
    assert (info["width"], info["height"]) == (1080, 1920) and abs(info["duration"] - 20.0) < 0.6
    assert pipeline.asr.has_audio(out / "final.mp4")  # tiếng gốc còn
    plan = json.loads((out / "script.json").read_text(encoding="utf-8"))
    assert plan["title_fr"] == "Le trailer qui fait réagir" and plan["hook"] == "TRAILER. REACTION."
    assert plan["captions"][0]["text"].startswith("Bonjour")  # lời gốc tiếng Trung được dịch sang tiếng Pháp
    assert (out / "captions.srt").read_text(encoding="utf-8").strip() and (out / "thumb.jpg").exists()
    post = (out / "post.txt").read_text(encoding="utf-8")
    assert "Voix off" not in post and "#GTA" in post  # không có giọng AI nên không có nhãn giọng AI
    assert p["meta"]["seconds"] == 20.0 and not qa.failed(p)
    assert "Motio" not in post and (out / "sources.txt").exists()
    assert p["meta"]["clip"]["hook_auto"] == "TRAILER. REACTION."
    # chỉ đổi hook / khung crop: dựng lại từ bước "voice", không gọi Claude thêm lần nào
    asked = len(fake["prompts"])
    assert clipper.update(pid, {"hook": "", "crop": {"fit": True, "x": 0.5}}) == "voice"
    assert "voice" in pipeline.available_steps(pid) and "render" not in pipeline.available_steps(pid)
    pipeline.resume(pid, "voice")
    assert len(fake["prompts"]) == asked and db.get_project(pid)["status"] == "done"
    assert clipper.update(pid, {"hook": ""}) is None
    # đổi đoạn: phải viết lại phụ đề (bước script)
    assert clipper.update(pid, {"start": 6, "end": 30}) == "script"


@pytest.mark.skipif(not has_ffmpeg, reason="needs FFmpeg")
def test_clip_without_captions_or_hook_and_a_source_without_sound(fake, tmp_path, monkeypatch):
    silent = tmp_path / "silent.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=720x1280:rate=25:duration=30", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", str(silent)], check=True)  # nguồn đã đứng, không có tiếng
    orig = search.download
    monkeypatch.setattr(search, "download", lambda url, out_dir, cookies=False, **kw:
                        {**orig(url, out_dir), "path": str(silent), "duration": 30.0})
    pid = clipper.create("https://www.youtube.com/watch?v=c1", {"start": 2, "end": 22, "captions": "off", "hook": ""},
                         short=True)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done", p["log"]
    out = config.PROJECTS / str(pid)
    info = delogo.probe(out / "final.mp4")
    assert (info["width"], info["height"]) == (1080, 1920)
    assert not any("translator" in s for _, s in fake["prompts"])  # không dịch khi không có phụ đề
    assert (out / "captions.srt").read_text(encoding="utf-8").strip() == ""


@pytest.mark.skipif(not has_ffmpeg, reason="needs FFmpeg")
def test_rms_per_second_reads_the_sound_level(fake, tmp_path):
    levels = clipper.rms_per_second(tmp_path / "YouTube_c1.mp4")
    assert 38 <= len(levels) <= 41 and all(-90 <= v < 0 for v in levels)


def test_a_clip_is_held_at_the_video_gate_like_any_video(fake, monkeypatch):
    if not has_ffmpeg:
        pytest.skip("needs FFmpeg")
    ch = channels.create({"name": "Clips", "gate_script": False, "gate_video": True})
    pid = clipper.create("https://www.youtube.com/watch?v=c1", _clip(), short=True)
    channels.attach(pid, ch)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "review" and p["meta"]["review"] == "video"


# ---------- API ----------
@pytest.fixture
def client(monkeypatch):
    queued = []
    monkeypatch.setattr(pipeline, "produce", lambda pid: queued.append(pid))
    c = TestClient(api.create_app(TOKEN, headless=True))
    c.queued = queued
    return c


def _wait(client, job_id):
    for _ in range(200):
        j = client.get(f"/api/clipper/{job_id}", headers=H).json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("analysis did not finish")


def test_analyze_gives_suggestions_the_user_can_export(client, fake, monkeypatch):
    monkeypatch.setattr(delogo, "probe", lambda p: {"width": 1280, "height": 720, "duration": 40.0})
    monkeypatch.setattr(clipper.scenes, "detect", lambda p: [10.0, 20.0])
    r = client.post("/api/clipper/analyze", headers=H, json={"link": "https://www.youtube.com/watch?v=c1",
                                                           "count": 3, "short": True})
    assert r.status_code == 202
    j = _wait(client, r.json()["id"])
    assert j["status"] == "done", j
    assert j["language"] == "zh" and j["cuts"] == [10.0, 20.0] and j["source"]["duration"] == 40.0
    assert [c["score"] for c in j["clips"]] == [9] and j["clips"][0]["hook"] == "ÇA VA TOUT CHANGER"
    assert j["clips"][0]["crop"] == {"fit": False, "x": [[0.0, 0.5]]} and j["projects"] == []
    assert client.queued == []  # chế độ tự chọn: chưa tạo dự án nào
    e = client.post("/api/clipper/export", headers=H, json={"link": j["link"], "clips": [_clip()], "short": True,
                                                            "duration": 40.0})
    assert e.status_code == 202 and client.queued == e.json()["project_ids"]
    bad = client.post("/api/clipper/export", headers=H, json={"link": j["link"], "clips": [{"start": 0, "end": 5}]})
    assert bad.status_code == 400 and "at least 62 s" in bad.text
    assert client.get("/api/clipper/nope", headers=H).status_code == 404


def test_claude_picks_by_itself_and_every_moment_becomes_a_queued_project(client, fake, monkeypatch):
    monkeypatch.setattr(delogo, "probe", lambda p: {"width": 1280, "height": 720, "duration": 40.0})
    monkeypatch.setattr(clipper.scenes, "detect", lambda p: [])
    ch = client.post("/api/channels", headers=H, json={"name": "Clips"}).json()
    r = client.post("/api/clipper/analyze", headers=H, json={"link": "https://www.youtube.com/watch?v=c1",
                                                           "short": True, "auto": True, "channel": ch["id"]})
    j = _wait(client, r.json()["id"])
    assert j["status"] == "done" and len(j["projects"]) == 1 and client.queued == j["projects"]
    p = db.get_project(j["projects"][0])
    assert p["mode"] == "clip" and p["meta"]["clip"]["start"] == 4.85 and p["meta"]["channel"] == ch["id"]
    detail = client.get(f"/api/projects/{p['id']}", headers=H).json()
    assert detail["clip"]["hook"] == "ÇA VA TOUT CHANGER" and not detail["clip"]["hook_auto"]  # le hook de Claude


def test_analyze_refuses_a_bad_link_count_or_missing_key(client, monkeypatch):
    assert client.post("/api/clipper/analyze", headers=H, json={"link": ""}).status_code == 400
    assert client.post("/api/clipper/analyze", headers=H, json={"link": "https://x.com/a/status/1",
                                                              "count": 0}).status_code == 400
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.post("/api/clipper/analyze", headers=H,
                       json={"link": "https://x.com/a/status/1"}).status_code == 409


def test_a_video_shorter_than_a_clip_says_so(client, fake, monkeypatch):
    monkeypatch.setattr(delogo, "probe", lambda p: {"width": 1280, "height": 720, "duration": 40.0})
    r = client.post("/api/clipper/analyze", headers=H, json={"link": "https://www.youtube.com/watch?v=c1"})
    j = _wait(client, r.json()["id"])
    assert j["status"] == "failed" and "shorter than the 62 s" in j["error"]


def test_put_clip_changes_the_clip_and_says_where_to_rerun(client):
    pid = clipper.create("https://www.youtube.com/watch?v=c1", {"start": 0, "end": 70})
    db.update_project(pid, status="done", meta={"sources": [{"path": "x", "url": "u", "duration": 300.0}]})
    r = client.put(f"/api/projects/{pid}/clip", headers=H, json={"hook": "Nouveau", "crop": {"x": 0.9}})
    assert r.status_code == 200 and r.json()["project"]["clip"]["hook"] == "Nouveau"
    assert r.json()["project"]["clip"]["crop"]["x"] == [[0.0, 0.9]]
    assert client.put(f"/api/projects/{pid}/clip", headers=H, json={"start": 0, "end": 5}).status_code == 400
    db.update_project(pid, status="running")
    assert client.put(f"/api/projects/{pid}/clip", headers=H, json={"hook": "x"}).status_code == 409
    other = db.create_project(None, "news")
    db.update_project(other, status="done")
    assert client.put(f"/api/projects/{other}/clip", headers=H, json={"hook": "x"}).status_code == 404
