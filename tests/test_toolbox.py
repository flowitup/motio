"""Công cụ lẻ (motio/toolbox.py): đọc / cắt phụ đề, dịch từng loạt, API tải lên + nối các job, dừng, ghi phụ đề thật."""
import io
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from motio import api, asr, config, llm, search, settings, toolbox, tts

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}
has_ffmpeg = bool(config.find("ffmpeg") and config.find("ffprobe"))

SRT = """﻿1
00:00:01,000 --> 00:00:03,000
Hello <i>there</i>,
how are you?

2
00:00:03,500 --> 00:00:05,000
I'm fine!
"""

VTT = """WEBVTT

intro
00:01.000 --> 00:02.500 align:start
{\\an8}Bonjour

00:00:03.000 --> 00:00:04.000
Au revoir
"""


@pytest.fixture(autouse=True)
def no_old_jobs():
    shutil.rmtree(toolbox.JOBS, ignore_errors=True)
    toolbox.JOBS.mkdir(parents=True)


def _width(text: str) -> float:
    return 10.0 * len(text)  # đo giả: mỗi ký tự 10 px


# ---------- phụ đề thuần ----------
def test_parse_srt_strips_tags_and_keeps_line_breaks():
    got = toolbox.parse_subs(SRT)
    assert got == [{"start": 1.0, "end": 3.0, "text": "Hello there,\nhow are you?"},
                   {"start": 3.5, "end": 5.0, "text": "I'm fine!"}]


def test_parse_vtt_without_hours_and_with_cue_settings():
    got = toolbox.parse_subs(VTT)
    assert got == [{"start": 1.0, "end": 2.5, "text": "Bonjour"}, {"start": 3.0, "end": 4.0, "text": "Au revoir"}]


def test_parse_subs_rejects_text_without_timings_and_sorts():
    with pytest.raises(ValueError, match="No subtitles"):
        toolbox.parse_subs("just some words\n\nmore words")
    two = "1\n00:00:05,000 --> 00:00:06,000\nB\n\n2\n00:00:01,000 --> 00:00:02,000\nA\n"
    assert [e["text"] for e in toolbox.parse_subs(two)] == ["A", "B"]


def test_decode_falls_back_to_cp1252():
    assert toolbox.decode("café".encode("utf-8-sig")) == "café"
    assert toolbox.decode("café".encode("cp1252")) == "café"


def test_srt_round_trip_keeps_timings_and_lines():
    entries = toolbox.parse_subs(SRT)
    again = toolbox.parse_subs(toolbox.format_srt(entries))
    assert again == entries


def test_segment_entries_split_long_segments_by_length():
    text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " * 2
    got = toolbox.segment_entries([{"start": 10.0, "end": 30.0, "text": text.strip()}])
    assert len(got) >= 2
    assert got[0]["start"] == 10.0 and got[-1]["end"] == pytest.approx(30.0)
    assert all(a["end"] == pytest.approx(b["start"]) for a, b in zip(got, got[1:], strict=False))
    for e in got:
        assert all(len(line) <= captions_max() for line in e["text"].split("\n")) and e["text"].count("\n") <= 1


def captions_max() -> int:
    from motio import captions
    return captions.MAX_CHARS + 6  # cắt ở dấu cách gần giữa nên dòng có thể dài hơn 42 một chút


def test_segment_entries_short_and_chinese():
    assert toolbox.segment_entries([{"start": 0, "end": 2, "text": "Salut"}]) == [
        {"start": 0.0, "end": 2.0, "text": "Salut"}]
    zh = "这是一个很长的句子，用来测试中文字幕是否会在合适的位置断开，而且不会超过每行的字数限制。"
    got = toolbox.segment_entries([{"start": 0, "end": 8, "text": zh}], cjk=True)
    assert len(got) >= 2 and "".join(e["text"].replace("\n", "") for e in got) == zh
    assert all(len(line) <= 16 for e in got for line in e["text"].split("\n"))


def test_wrap_px_spaced_and_cjk():
    assert toolbox.wrap_px("aa bb cc dd", _width, 55) == ["aa bb", "cc dd"]
    assert toolbox.wrap_px("one", _width, 5) == ["one"]  # từ dài hơn khung vẫn giữ nguyên
    assert toolbox.wrap_px("你好世界你好世界", _width, 40) == ["你好世界", "你好世界"]


def test_burn_cues_clip_split_and_never_overlap():
    entries = [{"start": 0.0, "end": 5.0, "text": "aa bb cc dd ee ff gg hh ii jj kk ll"},  # 12 từ, 3 ký tự mỗi từ
               {"start": 2.0, "end": 4.0, "text": "next"},
               {"start": 8.0, "end": 12.0, "text": "late"}]
    cues = toolbox.burn_cues(entries, _width, 100, total=10.0)
    assert all(len(c.lines) <= 2 for c in cues)
    assert all(a.end <= b.start + 1e-9 for a, b in zip(cues, cues[1:], strict=False))
    assert cues[0].start == 0.0 and max(c.end for c in cues) <= 10.0
    first = [c for c in cues if c.end <= 2.0 + 1e-9]
    assert len(first) >= 2  # câu dài được chia cue, câu sau chỉ bắt đầu từ giây thứ 2
    assert cues[-1].lines[0][0].text == "late" and cues[-1].end == pytest.approx(10.0)


def test_burn_layout_keeps_the_band_inside_the_frame():
    for w, h in ((1080, 1920), (1920, 1080), (640, 360)):
        for size in toolbox.SIZES:
            lay = toolbox.burn_layout(w, h, size, cjk=False)
            assert 0 < lay.cap_top and lay.cap_top + lay.cap_h <= h
    small = toolbox.burn_layout(1080, 1920, "small", False).cap_size
    large = toolbox.burn_layout(1080, 1920, "large", False).cap_size
    assert small < large


# ---------- dịch từng loạt ----------
def _fake_translator(monkeypatch, wrong_for=None):
    """llm.ask_json giả: trả "<n>|<lời gốc>" cho từng câu; wrong_for: số câu trong loạt để trả thiếu một câu."""
    seen = []

    def ask(prompt, system, *a, **kw):
        data = json.loads(prompt)
        seen.append({"before": data["context_before"], "n": [s["n"] for s in data["subtitles"]], "system": system})
        lines = [f"{s['n']}|{s['text']}" for s in data["subtitles"]]
        if wrong_for and len(lines) == wrong_for:
            lines = lines[:-1]
        return {"lines": lines}

    monkeypatch.setattr(llm, "ask_json", ask)
    return seen


def _entries(n):
    return [{"start": float(i), "end": i + 0.9, "text": f"line {i + 1}"} for i in range(n)]


def test_translate_batches_and_keeps_the_timings(monkeypatch):
    seen = _fake_translator(monkeypatch)
    progress = []
    out = toolbox.translate(_entries(45), "en", progress=lambda a, b: progress.append((a, b)))
    assert [s["n"][0] for s in seen] == [1, 41] and len(seen[0]["n"]) == toolbox.BATCH
    assert seen[0]["before"] == [] and seen[1]["before"] == ["line 38", "line 39", "line 40"]
    assert "English" in seen[0]["system"]
    assert progress == [(40, 45), (45, 45)]
    assert [e["text"] for e in out][:2] == ["1|line 1", "2|line 2"] and out[44]["text"] == "45|line 45"
    assert [(e["start"], e["end"]) for e in out] == [(e["start"], e["end"]) for e in _entries(45)]


def test_translate_splits_a_batch_when_the_count_is_wrong(monkeypatch):
    seen = _fake_translator(monkeypatch, wrong_for=8)  # loạt 8 câu bị thiếu một câu → chia 4 + 4
    out = toolbox.translate(_entries(8), "en")
    assert [len(s["n"]) for s in seen] == [8, 4, 4]
    assert [e["text"] for e in out] == [f"{i}|line {i}" for i in range(1, 9)]


def test_translate_gives_up_on_one_subtitle_that_keeps_coming_back_wrong(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda *a, **kw: {"lines": []})
    with pytest.raises(llm.LLMError, match="wrong shape"):
        toolbox.translate(_entries(2), "en")


def test_translate_french_uses_french_typography_and_fills_blanks(monkeypatch):
    replies = iter([{"lines": ["Vraiment ?", ""]}])
    monkeypatch.setattr(llm, "ask_json", lambda *a, **kw: next(replies))
    out = toolbox.translate([{"start": 0, "end": 1, "text": "Really?"}, {"start": 1, "end": 2, "text": "..."}], "fr")
    assert out[0]["text"] == "Vraiment ?"
    assert out[1]["text"] == "..."  # traduction trống thì giữ câu gốc


def test_translate_adds_the_channel_glossary_to_the_prompt(monkeypatch):
    seen = _fake_translator(monkeypatch)
    toolbox.translate(_entries(1), "vi", {"name": "Chine Info", "style": "", "glossary": "熊猫 = panda"})
    assert "Vietnamese" in seen[0]["system"] and "熊猫 = panda" in seen[0]["system"]


# ---------- API ----------
@pytest.fixture
def client():
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


def _wait(client, job_id, timeout=30.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/tools/jobs/{job_id}", headers=H).json()
        if job["status"] not in toolbox.BUSY:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job still {job['status']}: {job}")


def _post(client, kind, data=None, files=None):
    return client.post(f"/api/tools/{kind}", headers=H, data=data or {}, files=files or {})


def _file(job, name):
    return next(o for o in job["outputs"] if o["name"] == name)


def test_tool_routes_need_the_token(client):
    assert client.get("/api/tools/jobs").status_code == 401
    assert client.post("/api/tools/speak", data={"text": "x"}).status_code == 401


def test_transcribe_an_upload_and_download_the_results(client, monkeypatch):
    segs = [{"start": 0.0, "end": 2.0, "text": "Bonjour tout le monde"},
            {"start": 2.0, "end": 4.0, "text": "Ceci est un test"}]
    monkeypatch.setattr(asr, "transcribe", lambda src: {"language": "fr", "segments": segs})
    r = _post(client, "transcribe", files={"file": ("Mon Clip.MP4", io.BytesIO(b"bytes"), "video/mp4")})
    assert r.status_code == 202 and r.json()["kind"] == "transcribe" and r.json()["title"] == "Mon Clip.MP4"
    job = _wait(client, r.json()["id"])
    assert job["status"] == "done" and job["pct"] == 100 and "fr" in job["message"]
    srt = _file(job, "Mon Clip.srt")
    assert srt["kind"] == "subtitles"
    body = client.get(f"/media/{srt['path']}", headers=H)
    assert body.status_code == 200 and "00:00:00,000 --> 00:00:02,000\nBonjour tout le monde" in body.text
    txt = client.get(f"/media/{_file(job, 'Mon Clip.txt')['path']}", headers=H).text
    assert txt == "Bonjour tout le monde\nCeci est un test\n"
    assert client.get("/api/tools/jobs", headers=H).json()[0]["id"] == job["id"]
    assert "params" not in job


def test_transcribe_with_no_speech_fails_clearly(client, monkeypatch):
    monkeypatch.setattr(asr, "transcribe", lambda src: {"language": None, "segments": []})
    r = _post(client, "transcribe", files={"file": ("a.mp3", io.BytesIO(b"x"), "audio/mpeg")})
    job = _wait(client, r.json()["id"])
    assert job["status"] == "failed" and "No speech" in job["error"]


def test_download_then_transcribe_then_translate_by_chaining_jobs(client, monkeypatch):
    def fake_download(url, out_dir, max_height=720, cookies=False, hooks=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "YouTube_abc.mp4"
        path.write_bytes(b"video")
        for done in (10, 50, 100):
            for h in hooks or []:
                h({"status": "downloading", "downloaded_bytes": done, "total_bytes": 100})
        return {"path": str(path), "title": "Le titre", "platform": "YouTube", "uploader": "Chaîne"}

    seen = {}
    monkeypatch.setattr(search, "download", lambda *a, **kw: seen.update(args=a, kw=kw) or fake_download(*a, **kw))
    monkeypatch.setattr(asr, "transcribe", lambda src: {"language": "zh", "segments": [
        {"start": 0, "end": 3, "text": "你好"}, {"start": 3, "end": 5, "text": "再见"}]})
    _fake_translator(monkeypatch)

    dl = _wait(client, _post(client, "download", {"url": "https://youtu.be/abc", "height": "480"}).json()["id"])
    assert dl["status"] == "done" and dl["title"] == "Le titre" and "YouTube" in dl["message"]
    assert seen["args"][2] == 480 and seen["kw"]["cookies"] is True
    video = _file(dl, "YouTube_abc.mp4")
    assert video["kind"] == "video" and client.get(f"/media/{video['path']}", headers=H).content == b"video"

    tr_job = _wait(client, _post(client, "transcribe", {"file_job": dl["id"]}).json()["id"])
    assert tr_job["status"] == "done" and tr_job["title"] == "YouTube_abc.mp4"

    fr = _wait(client, _post(client, "translate", {"subs_job": tr_job["id"], "language": "fr"}).json()["id"])
    assert fr["status"] == "done"
    out = client.get(f"/media/{_file(fr, 'YouTube_abc.fr.srt')['path']}", headers=H).text
    assert "1|你好" in out and "2|再见" in out


def test_translate_an_uploaded_vtt(client, monkeypatch):
    _fake_translator(monkeypatch)
    job = _wait(client, _post(client, "translate", {"language": "en"},
                              {"subs": ("talk.vtt", io.BytesIO(VTT.encode()), "text/vtt")}).json()["id"])
    assert job["status"] == "done"
    srt = client.get(f"/media/{job['outputs'][0]['path']}", headers=H).text
    assert "1|Bonjour" in srt and "2|Au revoir" in srt


def test_speak_writes_an_audio_file(client, monkeypatch):
    calls = []

    def synth(lines, out_dir, voice=None):
        calls.append((lines, voice))
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "narration.mp3").write_bytes(b"mp3")
        return {"audio": str(Path(out_dir) / "narration.mp3"), "voice": "George", "provider": "elevenlabs"}

    monkeypatch.setattr(tts, "provider", lambda: "elevenlabs")
    monkeypatch.setattr(tts, "synthesize", synth)
    r = _post(client, "speak", {"text": "  Bonjour   le monde\ndeux  ", "voice": "v1"})
    assert r.status_code == 202
    job = _wait(client, r.json()["id"])
    assert job["status"] == "done" and job["message"] == "Read by George"
    assert calls == [(["Bonjour le monde\ndeux"], "v1")]
    assert client.get(f"/media/{_file(job, 'speech.mp3')['path']}", headers=H).content == b"mp3"
    assert _file(job, "speech.mp3")["kind"] == "audio"


def test_speak_without_a_voice_provider_is_a_409(client, monkeypatch):
    monkeypatch.setattr(tts, "provider", lambda: None)
    r = _post(client, "speak", {"text": "Bonjour"})
    assert r.status_code == 409 and "ELEVENLABS_API_KEY" in r.json()["detail"]
    assert not any(j["kind"] == "speak" for j in client.get("/api/tools/jobs", headers=H).json())


@pytest.mark.parametrize("kind, data, files, message", [
    ("download", {}, {}, "Paste a video link"),
    ("download", {"url": "not a link"}, {}, "Invalid link"),
    ("download", {"url": "https://a.com/v", "height": "999"}, {}, "Quality must be"),
    ("transcribe", {}, {}, "Choose a video or audio file"),
    ("transcribe", {}, {"file": ("x.txt", io.BytesIO(b"x"), "text/plain")}, "Unsupported file type"),
    ("transcribe", {}, {"file": ("x.mp4", io.BytesIO(b""), "video/mp4")}, "empty"),
    ("transcribe", {"file_job": "0" * 32}, {}, "Job not found"),
    ("translate", {}, {}, "Choose a subtitle file"),
    ("translate", {"language": "xx"}, {"subs": ("a.srt", io.BytesIO(b"1"), "text/plain")}, "Language must be"),
    ("translate", {"channel": "999"}, {"subs": ("a.srt", io.BytesIO(b"1"), "text/plain")}, "Channel not found"),
    ("speak", {"text": "  "}, {}, "Type or paste"),
    ("speak", {"text": "x" * 5001}, {}, "at most 5000"),
    ("burn", {}, {"subs": ("a.srt", io.BytesIO(SRT.encode()), "text/plain")}, "Choose a video first"),
    ("burn", {}, {"file": ("a.mp4", io.BytesIO(b"v"), "video/mp4")}, "Choose a subtitle file"),
    ("burn", {"size": "huge"}, {}, "Size must be"),
])
def test_bad_requests_are_400_and_leave_no_job_behind(client, monkeypatch, kind, data, files, message):
    monkeypatch.setattr(tts, "provider", lambda: "elevenlabs")
    before = len(client.get("/api/tools/jobs", headers=H).json())
    r = _post(client, kind, data, files)
    assert r.status_code in (400, 404) and message in r.json()["detail"], r.text
    assert len(client.get("/api/tools/jobs", headers=H).json()) == before
    assert len([d for d in toolbox.JOBS.iterdir() if d.is_dir()]) == before


def test_unknown_tool_and_job_are_404(client):
    assert _post(client, "cook", {}).status_code == 404
    assert client.get(f"/api/tools/jobs/{'a' * 32}", headers=H).status_code == 404
    assert client.get("/api/tools/jobs/..%2F..", headers=H).status_code == 404
    assert client.delete("/api/tools/jobs/nope", headers=H).status_code == 404


def test_chaining_needs_a_finished_job_with_the_right_kind(client, monkeypatch):
    monkeypatch.setattr(tts, "provider", lambda: "elevenlabs")
    monkeypatch.setattr(tts, "synthesize", lambda lines, out, voice=None: (
        (Path(out).mkdir(parents=True, exist_ok=True), (Path(out) / "n.mp3").write_bytes(b"x")) and
        {"audio": str(Path(out) / "n.mp3"), "voice": "V", "provider": "elevenlabs"}))
    said = _wait(client, _post(client, "speak", {"text": "Bonjour"}).json()["id"])
    r = _post(client, "translate", {"subs_job": said["id"]})
    assert r.status_code == 400 and "no subtitles" in r.json()["detail"]
    r = _post(client, "burn", {"file_job": said["id"], "subs_job": said["id"]})
    assert r.status_code == 400 and "no video" in r.json()["detail"]


def test_cancel_stops_a_running_download_and_delete_needs_it_stopped(client, monkeypatch):
    started = threading.Event()

    def slow(url, out_dir, max_height=720, cookies=False, hooks=None):
        started.set()
        for _ in range(400):
            for h in hooks or []:
                h({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 100})
            time.sleep(0.02)
        raise AssertionError("was not cancelled")

    monkeypatch.setattr(search, "download", slow)
    job_id = _post(client, "download", {"url": "https://a.com/v"}).json()["id"]
    assert started.wait(10)
    assert client.delete(f"/api/tools/jobs/{job_id}", headers=H).status_code == 409
    assert client.post(f"/api/tools/jobs/{job_id}/cancel", headers=H).status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "cancelled" and job["message"] == "Stopped" and job["error"] is None
    assert client.delete(f"/api/tools/jobs/{job_id}", headers=H).json() == {"deleted": job_id}
    assert not (toolbox.JOBS / job_id).exists()


def test_a_failed_job_keeps_the_error_for_the_app(client, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("yt-dlp says no")

    monkeypatch.setattr(search, "download", boom)
    job = _wait(client, _post(client, "download", {"url": "https://a.com/v"}).json()["id"])
    assert job["status"] == "failed" and job["error"] == "yt-dlp says no" and job["finished_at"]
    assert client.post(f"/api/tools/jobs/{job['id']}/cancel", headers=H).json()["status"] == "failed"


def test_jobs_left_running_are_failed_when_the_engine_starts():
    d = toolbox.JOBS / ("b" * 32)
    d.mkdir(parents=True, exist_ok=True)
    (d / "work").mkdir(exist_ok=True)
    (d / "state.json").write_text(json.dumps({"id": "b" * 32, "kind": "burn", "status": "running",
                                              "created_at": time.time()}), encoding="utf-8")
    assert toolbox.recover() >= 1
    job = toolbox.get("b" * 32)
    assert job["status"] == "failed" and "restarted" in job["error"] and not (d / "work").exists()


def test_error_messages_follow_the_ui_language(client):
    settings.update({"UI_LANG": "vi"})  # conftest xoá settings sau mỗi test
    r = _post(client, "download", {})
    assert r.status_code == 400 and "Hãy dán link video" in r.json()["detail"]


# ---------- ghi phụ đề thật (FFmpeg) ----------
def _video(path: Path, w=320, h=568, seconds=3):
    picture = f"color=c=0x203040:s={w}x{h}:d={seconds}:r=25"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", picture,
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)


def _frame(video: Path, at: float) -> np.ndarray:
    r = subprocess.run([config.ffmpeg(), "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1", "-f",
                        "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True)
    return np.asarray(Image.open(io.BytesIO(r.stdout)).convert("RGB")).astype(int)


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
def test_burn_draws_the_subtitles_in_the_bottom_band_only(client, tmp_path):
    src = tmp_path / "clip.mp4"
    _video(src)
    subs = "1\n00:00:00,500 --> 00:00:01,500\nHello burned world\n\n2\n00:00:02,000 --> 00:00:02,800\nBye\n"
    with src.open("rb") as f:
        r = _post(client, "burn", {"size": "large"}, {"file": ("clip.mp4", f, "video/mp4"),
                                                        "subs": ("clip.srt", io.BytesIO(subs.encode()), "text/plain")})
    assert r.status_code == 202
    job = _wait(client, r.json()["id"], timeout=120)
    assert job["status"] == "done", job
    out = toolbox.JOBS.parent.parent / job["outputs"][0]["path"]
    assert job["outputs"][0]["name"] == "clip.subtitled.mp4" and job["outputs"][0]["kind"] == "video"
    with_text, without = _frame(out, 1.0), _frame(src, 1.0)
    assert with_text.shape == without.shape == (568, 320, 3)
    diff = np.abs(with_text - without).sum(axis=2) > 60
    rows = np.where(diff.any(axis=1))[0]
    assert rows.size > 10 and rows.min() > 568 * 0.6  # chữ chỉ nằm ở nửa dưới
    assert np.abs(_frame(out, 2.9) - _frame(src, 2.9)).sum(axis=2).max() < 60  # hết câu cuối thì không còn chữ
    probe = subprocess.run([config.ffprobe(), "-v", "error", "-select_streams", "a", "-show_entries",
                            "stream=codec_name", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
    assert probe.stdout.strip() == "aac"
    assert not (toolbox.JOBS / job["id"] / "work").exists()


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
def test_burn_uses_the_previous_jobs_video_and_subtitles(client, tmp_path, monkeypatch):
    src = tmp_path / "wide.mp4"
    _video(src, w=480, h=270, seconds=2)

    def fake_download(url, out_dir, max_height=720, cookies=False, hooks=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / "wide.mp4"
        dst.write_bytes(src.read_bytes())
        return {"path": str(dst), "title": "t", "platform": "", "uploader": ""}

    monkeypatch.setattr(search, "download", fake_download)
    _fake_translator(monkeypatch)
    dl = _wait(client, _post(client, "download", {"url": "https://a.com/v"}).json()["id"])
    tr_job = _wait(client, _post(client, "translate", {"language": "en"},
                                 {"subs": ("s.srt", io.BytesIO(SRT.encode()), "text/plain")}).json()["id"])
    burn = _wait(client, _post(client, "burn", {"file_job": dl["id"], "subs_job": tr_job["id"]}).json()["id"], 120)
    assert burn["status"] == "done", burn
    assert burn["outputs"][0]["name"] == "wide.subtitled.mp4"
