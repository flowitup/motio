"""Chế độ lồng tiếng (dub.py): chọn đoạn, dịch, đặt câu, trộn, dựng, cổng duyệt khi quyền nguồn chưa rõ."""
import json
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from motio import api, asr, channels, config, db, dub, edit, llm, pipeline, render, search, separate, tts

has_ffmpeg = bool(config.find("ffmpeg") and config.find("ffprobe"))
TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}
SEGS = [{"start": 1.0, "end": 4.0, "text": "你好，欢迎来到成都"}, {"start": 4.2, "end": 4.8, "text": "嗯"},
        {"start": 5.0, "end": 9.0, "text": "今天我们去看熊猫"}, {"start": 30.0, "end": 36.0, "text": "它们很可爱"},
        {"start": 44.0, "end": 49.5, "text": "谢谢收看"}]


# ---------- phần thuần ----------
def test_pick_excerpt_whole_short_video_and_the_users_part():
    assert dub.pick_excerpt({}, 50.0, SEGS, "t") == (0.0, 50.0, "whole video")
    assert dub.pick_excerpt({"start": 2.0, "end": 60.0}, 120.0, SEGS, "t")[:2] == (2.0, 60.0)
    segs = [{"start": s, "end": s + 4.5, "text": "x"} for s in range(0, 200, 5)]
    a, b, _ = dub.pick_excerpt({"start": 10.0}, 200.0, segs, "t")  # chỉ đặt điểm đầu: dừng ở cuối câu
    assert a == 10.0 and 62 <= b - a <= 85 and (b - 4.5) % 5 == 0
    with pytest.raises(ValueError, match="at least 38 s"):
        dub.pick_excerpt({}, 30.0, SEGS, "t")
    with pytest.raises(ValueError, match="at least 38 s"):
        dub.clean_excerpt(10, 40)
    with pytest.raises(ValueError, match="at most 88 s"):
        dub.clean_excerpt(0, 100)
    assert dub.clean_excerpt("5", None) == (5.0, None)


def test_long_video_part_is_picked_by_claude_at_sentence_edges(monkeypatch):
    segs = [{"start": s, "end": s + 4.5, "text": f"phrase {s}"} for s in range(0, 300, 5)]
    asked = []
    pick = {"start": 41.2, "end": 113.8, "why": "ok"}
    monkeypatch.setattr(llm, "ask_json", lambda p, s, **k: asked.append(p) or pick)
    a, b, why = dub.pick_excerpt({}, 300.0, segs, "Panda")
    assert (a, b, why) == (39.85, 114.8, "ok") and "de 62 à 85 secondes" in asked[0]
    monkeypatch.setattr(llm, "ask_json", lambda p, s, **k: {"start": "?"})
    a, b, why = dub.pick_excerpt({}, 300.0, segs, "Panda")
    assert a == 0.0 and 62 <= b - a <= 88 and "unusable" in why


def test_pads_and_short_lines():
    assert dub.pads(70) == (0.0, 0.0)
    assert dub.pads(50) == (6.25, 6.25)
    assert dub.pads(60) == (3.0, 3.0)  # chỗ thiếu ngắn: mỗi phần vẫn đủ cho một câu
    merged = dub.merge_short(dub.in_excerpt(SEGS, 0, 50))
    assert [g["start"] for g in merged] == [1.0, 4.2, 30.0, 44.0] and merged[1]["text"] == "嗯 今天我们去看熊猫"
    assert dub.in_excerpt(SEGS, 29.0, 40.0) == [{"start": 30.0, "end": 36.0, "text": "它们很可爱"}]


def test_place_speeds_up_then_starts_late():
    slots = [(1.0, 3.0), (3.0, 10.0), (4.0, 20.0)]
    spans = [(0.0, 2.2), (2.3, 3.3), (3.4, 5.0)]
    p = dub.place(slots, spans)
    assert p[0]["at"] == 1.0 and 1.0 < p[0]["rate"] <= dub.MAX_RATE  # 2.2 s trong chỗ 2 s: đọc nhanh hơn
    assert p[1]["at"] == 3.0 and p[1]["rate"] == 1.0
    assert p[2]["at"] == 4.08 and p[2]["rate"] == 1.0  # câu trước còn đọc: vào ngay sau nó
    tight = dub.place([(0.0, 1.0)], [(0.0, 3.0)])[0]
    assert tight["rate"] == dub.MAX_RATE and tight["end"] > 1.0  # không nhanh hơn 15 %: đọc lố


def test_tight_spans_and_shifted_alignment():
    texts = ["Salut.", "Oui."]
    text = "Salut. Oui."
    starts = [0.1 * i for i in range(len(text))]
    al = {"characters": list(text), "character_start_times_seconds": starts,
          "character_end_times_seconds": [s + 0.08 for s in starts]}
    raw = {"duration": 1.2, "alignment": al, "lines": [{"start": 0.0, "end": 0.7}, {"start": 0.7, "end": 1.2}]}
    spans = dub.tight_spans(texts, raw)
    assert spans[0] == (0.0, 0.69) and spans[1][0] == 0.67  # + 0.12 s sau chữ cuối, dừng trước câu kế
    placed = dub.place([(10.0, 20.0), (30.0, 40.0)], spans)
    shifted = dub.shift_alignment(texts, al, placed)
    assert shifted["character_start_times_seconds"][0] == 10.0
    assert shifted["character_start_times_seconds"][7] == pytest.approx(30.0 + 0.7 - 0.67, abs=1e-3)
    assert dub.shift_alignment(texts, {"characters": ["x"]}, placed) is None


def test_timeline_has_still_intro_and_outro():
    pieces = dub.timeline({"excerpt": [10.0, 50.0], "pad": [6.0, 7.0]})
    assert pieces[0].still and pieces[0].dur == 6.0 and pieces[0].src_start == 10.0
    assert pieces[-1].still and pieces[-1].dur == 7.0 and pieces[-1].src_start == 49.8
    moving = [p for p in pieces if not p.still]
    assert sum(p.dur for p in moving) == pytest.approx(40.0) and moving[0].t0 == 6.0
    assert [p.dur for p in dub.timeline({"excerpt": [0.0, 32.0], "pad": [0, 0]})] == [15.0, 17.0]


def _scene(rng, h: int, w: int) -> np.ndarray:
    img = np.tile(np.linspace(40, 200, w), (h, 1)) + rng.normal(0, 6, (h, w))
    for _ in range(5):  # vài mảng lớn di chuyển
        y, x, r = rng.integers(0, h), rng.integers(0, w), rng.integers(8, 30)
        img[max(0, y - r):y + r, max(0, x - r):x + r] = rng.integers(0, 255)
    return img


def test_find_band_finds_changing_text_and_skips_a_static_logo():
    rng = np.random.default_rng(1)
    h, w = 180, 320
    frames = []
    for _ in range(8):
        img = _scene(rng, h, w)
        cols = rng.integers(60, 260, 40)  # "chữ": nét dọc trắng / đen, mỗi khung một khác
        for c in cols:
            img[146:158, c:c + 2] = 255
            img[146:158, c + 2:c + 3] = 0
        img[20:34, 250:300:3] = 255  # logo đứng yên ở góc trên: không phải phụ đề
        frames.append(np.clip(img, 0, 255).astype(np.uint8))
    box = dub.find_band(np.stack(frames))
    assert box and box[1] < 146 / h and box[1] + box[3] > 158 / h and box[3] < 0.2
    plain = np.stack([np.clip(_scene(rng, h, w), 0, 255).astype(np.uint8) for _ in range(8)])
    assert dub.find_band(plain) is None


def test_clean_blur():
    assert dub.clean_blur(None) is None and dub.clean_blur([]) is None
    assert dub.clean_blur([0.1, 0.9, 0.95, 0.2]) == [0.1, 0.9, 0.9, 0.1]
    with pytest.raises(ValueError):
        dub.clean_blur([0.1, 0.2, 0.001, 0.1])
    with pytest.raises(ValueError):
        dub.clean_blur(["a", 1, 2, 3])


# ---------- cả pipeline, dịch vụ ngoài giả ----------
@pytest.fixture
def fake(monkeypatch, tmp_path):
    seen = {"prompts": [], "render": [], "texts": []}

    def download(url, out_dir, cookies=False):
        f = tmp_path / "Douyin_d1.mp4"
        f.write_bytes(b"x")
        return {"path": str(f), "url": url, "id": "d1", "title": "成都熊猫", "platform": "Douyin", "uploader": "up",
                "uploader_url": "", "upload_date": "", "duration": 50.0, "license": ""}

    def transcribe(path):
        return {"language": "zh", "segments": SEGS}

    def ask_json(prompt, system, **kw):
        seen["prompts"].append((prompt, system))
        return {"title_fr": "Les pandas de Chengdu", "speakers": {"A": "la guide"}, "register": "vous : elle parle "
                "au public", "lines": [{"i": 0, "speaker": "A", "text": "Bonjour, bienvenue à Chengdu !"},
                                       {"i": 1, "speaker": "A", "text": "Aujourd'hui, on va voir les pandas."},
                                       {"i": 2, "speaker": "A", "text": ""},
                                       {"i": 3, "speaker": "A", "text": "Merci de nous avoir suivis."}],
                "intro": "Direction la Chine.", "outro": "Et vous, vous iriez ?", "description": "Desc.",
                "hashtags": ["#Chine"]}

    def synthesize(lines, out_dir, voice=None):
        seen["texts"].append(lines)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "narration.mp3").write_bytes(b"mp3")
        spans = [{"start": 2.0 * i, "end": 2.0 * i + 1.8} for i in range(len(lines))]
        return {"audio": str(out_dir / "narration.mp3"), "duration": 2.0 * len(lines), "lines": spans,
                "provider": "fake", "voice": voice or "v", "model": "m", "alignment": None}

    def fake_render(plan, sources, narration, out_dir, progress=None, min_total=0.0, badge="", wide=False,
                    pieces=None, total=None, src_volume=0.10, delay=render.NARRATION_DELAY, caption_hold=None):
        seen["render"].append({"lines": plan["lines"], "sources": sources, "pieces": pieces, "total": total,
                               "src_volume": src_volume, "delay": delay, "badge": badge,
                               "caption_hold": caption_hold})
        (out_dir / "final.mp4").write_bytes(b"v")
        return {"video": str(out_dir / "final.mp4"), "thumb": "", "duration": total, "pieces": len(pieces or []),
                "wide": None}

    def mix(voice_audio, placed, bg, how, src, a, length, pad_in, total, dst):
        seen["mix"] = {"placed": placed, "how": how, "pad_in": pad_in, "total": total}
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"wav")
        return dst

    monkeypatch.setattr(search, "download", download)
    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(llm, "ask_json", ask_json)
    monkeypatch.setattr(tts, "synthesize", synthesize)
    monkeypatch.setattr(render, "render", fake_render)
    monkeypatch.setattr(dub, "mix", mix)
    monkeypatch.setattr(dub, "background", lambda src, out, a, length, step: (None, "original"))
    monkeypatch.setattr(dub, "detect_band", lambda src, times: [0.03, 0.8, 0.94, 0.1])
    return seen


def _profile(**kw) -> dict:
    return channels.create({"name": "Chine VF", "gate_script": False, "gate_video": False, **kw})


def test_full_dub_run(fake):
    ch = _profile(glossary="熊猫 = panda géant\nChengdu", voice_id="vx", badge="VF")
    pid = dub.create("https://www.douyin.com/video/1")
    channels.attach(pid, ch)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done", p["log"]
    prompt, system = fake["prompts"][-1]
    assert "tu ;" in prompt and "place" in prompt and "« intro »" in prompt
    assert "熊猫 = panda géant" in system and "Glossaire" in system
    plan = json.loads((config.PROJECTS / str(pid) / "script.json").read_text())
    assert [ln["kind"] for ln in plan["lines"]] == ["intro", "dub", "dub", "dub", "dub", "outro"]
    assert plan["lines"][1]["zh"].startswith("你好") and plan["lines"][1]["at"] == 7.25  # 6,25 s mở + 1 s
    assert plan["dub"]["pad_in"] == 6.25 and plan["dub"]["register"].startswith("vous")
    assert fake["texts"][-1][0] == "Direction la Chine." and "" not in fake["texts"][-1]  # câu trống không đọc
    r = fake["render"][-1]
    assert r["src_volume"] == 0.0 and r["delay"] == 0.0 and r["badge"] == "VF" and r["caption_hold"] == 1.2
    assert r["sources"][0]["blur"] == [0.03, 0.8, 0.94, 0.1] and len(r["lines"]) == 5
    assert r["pieces"][0].still and r["pieces"][-1].still and 62 <= r["total"] <= 90
    assert fake["mix"]["how"] == "original" and fake["mix"]["pad_in"] == 6.25
    assert p["meta"]["dub"]["excerpt"] == [0.0, 50.0] and p["meta"]["dub"]["blur_auto"] is True
    assert "Motio" not in (config.PROJECTS / str(pid) / "post.txt").read_text()
    assert "Voix off générée par IA." in (config.PROJECTS / str(pid) / "post.txt").read_text()
    # dựng lại (vd. sau khi đổi khung làm mờ) giữ giọng và độ dài
    assert "render" in pipeline.available_steps(pid)
    dub.update(pid, {"blur": [0.1, 0.7, 0.8, 0.12]})
    pipeline.resume(pid, "render")
    assert len(fake["texts"]) == 1 and fake["render"][-1]["sources"][0]["blur"] == [0.1, 0.7, 0.8, 0.12]
    assert fake["render"][-1]["total"] == r["total"]


def test_video_over_90_seconds_is_refused(fake, monkeypatch):
    monkeypatch.setattr(dub, "MAX_RATE", 1.0)

    def slow(lines, out_dir, voice=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        return {"audio": str(out_dir / "n.mp3"), "duration": 40.0 * len(lines), "provider": "fake", "voice": "v",
                "lines": [{"start": 40.0 * i, "end": 40.0 * i + 39} for i in range(len(lines))], "alignment": None}

    monkeypatch.setattr(tts, "synthesize", slow)
    pid = dub.create("https://www.douyin.com/video/2")
    with pytest.raises(RuntimeError, match="over 90 s"):
        pipeline.produce(pid)
    assert db.get_project(pid)["status"] == "failed"


def test_dub_of_someone_elses_video_waits_for_approval_before_postiz(fake, fake_postiz):
    ch = _profile(postiz=["tt1"])
    pid = dub.create("https://www.douyin.com/video/3")
    channels.attach(pid, ch)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "review" and p["meta"]["review"] == "video" and not fake_postiz
    assert "owned, licensed or CC" in p["log"]
    pipeline.approve_video(pid)  # duyệt bằng tay: gửi
    assert db.get_project(pid)["status"] == "done" and any(r.url.path.endswith("/posts") for r in fake_postiz)


def test_dub_with_owned_rights_is_sent_by_itself(fake, fake_postiz):
    ch = _profile(postiz=["tt1"])
    pid = dub.create("https://www.douyin.com/video/4", rights="owned")
    channels.attach(pid, ch)
    pipeline.produce(pid)
    assert db.get_project(pid)["status"] == "done" and any(r.url.path.endswith("/posts") for r in fake_postiz)


def test_script_editor_keeps_one_line_per_original_line(fake):
    pid = dub.create("https://www.douyin.com/video/5")
    pipeline.produce(pid)
    view = edit.script_view(pid)
    lines = view["script"]["lines"]
    assert view["dub"]["speakers"] == {"A": "la guide"} and lines[1]["zh"].startswith("你好")
    assert lines[1]["max_chars"] > 0 and lines[0]["kind"] == "intro"
    body = {**view["script"], "lines": [{"text": ln["text"]} for ln in lines]}
    body["lines"][3] = {"text": "Là, on va voir les pandas."}
    saved = edit.save_script(pid, body)["script"]["lines"]
    assert saved[3]["text"] == "Là, on va voir les pandas." and saved[3]["zh"] == lines[3]["zh"]
    assert saved[3]["at"] == lines[3]["at"]
    with pytest.raises(ValueError, match="can't be added or removed"):
        edit.save_script(pid, {**body, "lines": body["lines"] + [{"text": "En plus"}]})
    with pytest.raises(ValueError, match="at least one French line"):
        edit.save_script(pid, {**body, "lines": [{"text": ""} for _ in lines]})


def test_update_part_and_blur():
    pid = dub.create("https://www.bilibili.com/video/BV1", start=5, end=70)
    assert db.get_project(pid)["meta"]["dub"] == {"start": 5.0, "end": 70.0}
    assert dub.update(pid, {"blur": [0.05, 0.8, 0.9, 0.1]}) == "render"
    assert dub.update(pid, {"blur": [0.05, 0.8, 0.9, 0.1]}) is None
    assert dub.update(pid, {"start": None, "end": None}) == "script"
    meta = db.get_project(pid)["meta"]["dub"]
    assert meta["start"] is None and meta["blur"] == [0.05, 0.8, 0.9, 0.1] and meta["blur_auto"] is False
    with pytest.raises(ValueError):
        dub.update(pid, {"start": 0, "end": 10})
    with pytest.raises(ValueError, match="Invalid link"):
        dub.create("douyin.com/1")


# ---------- API ----------
@pytest.fixture
def client(monkeypatch):
    def fake_produce(pid, **kw):
        db.update_project(pid, status="done", step="Done", pct=100)

    monkeypatch.setattr(pipeline, "produce", fake_produce)
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


def test_dub_routes(client):
    r = client.post("/api/dubs", headers=H, json={"link": "https://www.douyin.com/video/9", "rights": "cc"})
    assert r.status_code == 202
    pid = r.json()["project_id"]
    for _ in range(100):
        p = client.get(f"/api/projects/{pid}", headers=H).json()
        if p["status"] == "done":
            break
        time.sleep(0.02)
    assert p["mode"] == "dub" and p["dub"]["needs_review"] is False and p["dub"]["blur"] is None
    r = client.put(f"/api/projects/{pid}/dub", headers=H, json={"blur": [0.05, 0.75, 0.9, 0.12]})
    assert r.status_code == 200 and r.json()["project"]["dub"]["blur"] == [0.05, 0.75, 0.9, 0.12]
    assert r.json()["rerun"] == "search"  # chưa có dữ liệu để chỉ dựng lại: chạy lại từ đầu
    assert client.put(f"/api/projects/{pid}/dub", headers=H, json={"start": 0, "end": 5}).status_code == 400
    assert client.post("/api/dubs", headers=H, json={"link": "nope"}).status_code == 400
    assert client.post("/api/dubs", headers=H, json={"link": "https://x.com/a", "rights": "mine"}).status_code == 400
    topic_pid = client.post("/api/projects", headers=H, json={"topic": "panda"}).json()["project_id"]
    assert client.put(f"/api/projects/{topic_pid}/dub", headers=H, json={"blur": None}).status_code == 404


def test_dub_from_a_new_video(client):
    wid = db.add_watch("channel", "youtube", "https://youtube.com/@dubx", "X", "licensed")
    db.insert_clips([{"id": "youtube:z1", "watch_id": wid, "site": "youtube", "url": "https://youtube.com/watch?v=z1",
                      "title": "熊猫", "duration": 70, "status": "new"}])
    r = client.post("/api/clips/youtube:z1/dub", headers=H)
    assert r.status_code == 202
    p = db.get_project(r.json()["project_id"])
    assert p["mode"] == "dub" and p["meta"]["rights"] == "licensed" and p["title"] == "熊猫"
    assert db.get_clip("youtube:z1")["status"] == "used"
    assert client.post("/api/clips/nope/dub", headers=H).status_code == 404


# ---------- dựng thật bằng FFmpeg ----------
class Identity:
    def run(self, _outputs, feeds):
        return [feeds["input"]]


def _probe(path) -> dict:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-show_entries", "stream=codec_type,width,height:"
                        "format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
def test_real_dub_voice_mix_and_render(tmp_path, monkeypatch):
    ff = config.ffmpeg()
    src = tmp_path / "src.mp4"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=480x270:rate=25:d=45", "-f", "lavfi",
                    "-i", "sine=f=220:d=45", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(src)], check=True)

    def synthesize(lines, out_dir, voice=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        audio = out_dir / "narration.mp3"
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=600:d={2 * len(lines)}", str(audio)],
                       check=True)
        return {"audio": str(audio), "duration": 2.0 * len(lines), "provider": "fake", "voice": "v", "model": "m",
                "lines": [{"start": 2.0 * i, "end": 2.0 * i + 2} for i in range(len(lines))], "alignment": None}

    monkeypatch.setattr(tts, "synthesize", synthesize)
    monkeypatch.setattr(separate, "session", lambda: Identity())
    monkeypatch.setattr(separate, "model_ready", lambda: True)
    pad = dub.pads(45.0)
    plan = {"title_fr": "Les pandas", "description": "", "hashtags": [],
            "dub": {"start": 0.0, "end": 45.0, "pad_in": pad[0], "pad_out": pad[1]},
            "lines": [{"kind": "intro", "text": "Direction la Chine.", "at": 0.25},
                      {"kind": "dub", "text": "Bonjour à tous.", "at": pad[0] + 1.0},
                      {"kind": "dub", "text": "", "at": pad[0] + 5.0},
                      {"kind": "dub", "text": "Voici les pandas.", "at": pad[0] + 20.0},
                      {"kind": "outro", "text": "Et vous ?", "at": pad[0] + 45.3}]}
    out = tmp_path / "proj"
    steps = []
    source = {"path": str(src), "url": "u", "platform": "Douyin", "uploader": "up", "duration": 45.0}
    nar = dub.voice(plan, source, out, lambda *a, **k: steps.append(a))
    assert nar["background"] == "separated" and 62 <= nar["total"] <= 90 and nar["lines"][1]["start"] == pad[0] + 1
    with wave.open(nar["audio"]) as w:
        assert abs(w.getnframes() / w.getframerate() - nar["total"]) < 0.05
    proj = {"mode": "dub", "meta": {"dub": {"blur": [0.03, 0.8, 0.94, 0.12]}}}
    res = render.render(**dub.render_args(proj, plan, [source], nar), narration=nar, out_dir=out, badge="VF")
    info = _probe(res["video"])
    kinds = {s["codec_type"] for s in info["streams"]}
    assert kinds == {"video", "audio"} and abs(float(info["format"]["duration"]) - nar["total"]) < 0.3
    tl = json.loads((out / "timeline.json").read_text())
    assert tl[0]["still"] and tl[0]["dur"] == 0.2 and not tl[1]["still"]
    assert Path(res["thumb"]).is_file() and (out / "captions.srt").read_text().count("-->") >= 3
