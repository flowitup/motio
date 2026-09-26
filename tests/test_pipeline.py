"""Pipeline với mọi dịch vụ ngoài (yt-dlp, Whisper, Claude, ElevenLabs, FFmpeg) được thay bằng hàm giả."""
import json
from pathlib import Path

import pytest

from motio import asr, config, db, llm, pipeline, render, search, tts


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """Ghi lại bước nào đã chạy; `fail` = tên bước sẽ lỗi ở lần gọi tới."""
    calls: list[str] = []
    fail: set[str] = set()

    def boom(name):
        calls.append(name)
        if name in fail:
            fail.discard(name)
            raise RuntimeError(f"{name} hỏng")

    def candidates(kw):
        boom("search")
        return [{"site": "youtube", "url": f"https://yt/{i}", "id": f"v{i}", "title": f"t{i}", "uploader": "u",
                 "duration": 60, "views": 1, "query": "q"} for i in range(3)]

    def download(url, out_dir):
        boom("download")
        vid = url.rsplit("/", 1)[-1]
        f = tmp_path / f"Youtube_{vid}.mp4"
        f.write_bytes(b"x")
        return {"path": str(f), "url": url, "id": vid, "title": "t", "platform": "YouTube", "uploader": "u",
                "uploader_url": "", "upload_date": "", "duration": 60, "license": ""}

    def transcribe(path):  # như asr.transcribe: có cache thì không bóc lời lại
        cache = Path(path).with_suffix(".transcript.json")
        if cache.exists():
            return json.loads(cache.read_text())
        boom("transcribe")
        res = {"language": "zh", "segments": [{"start": 0, "end": 2, "text": "你好"}]}
        cache.write_text(json.dumps(res))
        return res

    def ask_json(prompt, system, **kw):
        if "Choisis" in prompt:
            return {"pick": [0, 1], "why": "ok"}
        boom("script")
        return {"title_fr": "Titre", "lines": [{"text": f"Ligne {i}", "clips": []} for i in range(4)],
                "description": "Desc.", "hashtags": ["#Chine"]}

    def synthesize(lines, out_dir):
        boom("voice")
        return {"audio": "n.mp3", "duration": 8.0, "lines": [{"start": i * 2.0, "end": i * 2.0 + 2} for i in
                                                              range(len(lines))], "provider": "fake", "voice": "v"}

    def fake_render(plan, sources, nar, out, progress=None):
        boom("render")
        (out / "final.mp4").write_bytes(b"v")
        return {"video": str(out / "final.mp4"), "thumb": "", "duration": 8.0, "pieces": 4}

    monkeypatch.setattr(search, "candidates", candidates)
    monkeypatch.setattr(search, "download", download)
    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(llm, "ask_json", ask_json)
    monkeypatch.setattr(tts, "synthesize", synthesize)
    monkeypatch.setattr(render, "render", fake_render)
    db.upsert_trend({"id": "douyin:p", "source": "douyin", "ext_id": "p", "url": "https://x", "title_zh": "中文",
                     "title_fr": "Titre", "angle": "a", "reason": "r", "keywords": {"zh": ["中文"]}, "score": 70,
                     "rank": 1})
    return calls, fail


def _new() -> int:
    return db.create_project("douyin:p", "Titre")


def test_full_run(fake):
    calls, _ = fake
    pid = _new()
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done" and p["meta"]["video"] == f"projects/{pid}/final.mp4"
    assert calls == ["search", "download", "download", "transcribe", "transcribe", "script", "voice", "render"]
    assert [c["url"] for c in p["meta"]["chosen"]] == ["https://yt/0", "https://yt/1"]
    assert (config.PROJECTS / str(pid) / "sources.txt").exists()
    assert pipeline.available_steps(pid) == list(pipeline.STEPS)


@pytest.mark.parametrize("broken,resume_at,rerun", [
    ("search", "search", ["search", "download", "download", "transcribe", "transcribe", "script", "voice",
                          "render"]),
    ("script", "script", ["script", "voice", "render"]),
    ("voice", "voice", ["voice", "render"]),
    ("render", "voice", ["voice", "render"]),
])
def test_retry_resumes_at_failed_step(fake, broken, resume_at, rerun):
    calls, fail = fake
    pid = _new()
    fail.add(broken)
    with pytest.raises(RuntimeError):
        pipeline.produce(pid)
    assert db.get_project(pid)["status"] == "failed"
    assert pipeline.resume_point(pid) == resume_at
    calls.clear()
    pipeline.resume(pid)
    assert calls == rerun
    assert db.get_project(pid)["status"] == "done"


def test_retry_after_transcribe_failure_keeps_finished_transcripts(fake):
    calls, fail = fake
    pid = _new()
    # nguồn thứ hai lỗi khi bóc lời: nguồn đầu đã có cache
    orig = asr.transcribe

    def flaky(path):
        if "_1." in str(path) and "once" not in fail:
            fail.add("once")
            raise RuntimeError("whisper hỏng")
        return orig(path)

    asr.transcribe = flaky
    try:
        with pytest.raises(RuntimeError):
            pipeline.produce(pid)
    finally:
        asr.transcribe = orig
    assert pipeline.resume_point(pid) == "transcribe"
    calls.clear()
    pipeline.resume(pid)
    assert calls[:2] == ["transcribe", "script"]  # chỉ bóc lời nguồn còn thiếu, không tải lại


def test_explicit_restart_drops_later_results(fake):
    calls, _ = fake
    pid = _new()
    pipeline.produce(pid)
    calls.clear()
    pipeline.resume(pid, "download")
    assert calls[:2] == ["download", "download"] and "search" not in calls
    calls.clear()
    pipeline.resume(pid, "script")
    assert calls == ["script", "voice", "render"]
    calls.clear()
    pipeline.resume(pid, "transcribe")  # bóc lời lại từ đầu (vd. sau khi đổi model Whisper)
    assert calls == ["transcribe", "transcribe", "script", "voice", "render"]


def test_retry_needs_saved_data(fake):
    pid = _new()
    assert pipeline.available_steps(pid) == ["search"]
    with pytest.raises(ValueError):
        pipeline.resume(pid, "voice")
    assert db.get_project(pid)["status"] == "failed"


def test_missing_source_file_falls_back_to_download(fake):
    calls, _ = fake
    pid = _new()
    pipeline.produce(pid)
    for s in db.get_project(pid)["meta"]["sources"]:
        Path(s["path"]).unlink()
    assert pipeline.resume_point(pid) == "download"
    calls.clear()
    pipeline.resume(pid)
    assert calls[:2] == ["download", "download"] and db.get_project(pid)["status"] == "done"
