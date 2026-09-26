"""Pipeline với mọi dịch vụ ngoài (yt-dlp, Whisper, Claude, ElevenLabs, FFmpeg) được thay bằng hàm giả."""
import json
import re
from pathlib import Path

import pytest

from motio import asr, config, db, llm, pipeline, render, scenes, search, topic, tts


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """Ghi lại bước nào đã chạy; `fail` = tên bước sẽ lỗi ở lần gọi tới."""
    calls: Calls = Calls()
    fail: set[str] = set()
    sec_per_word = [0.4]  # tốc độ đọc giả: 180 từ → 72 s
    rendered: list[dict] = []

    def boom(name):
        calls.append(name)
        if name in fail:
            fail.discard(name)
            raise RuntimeError(f"{name} hỏng")

    def candidates(kw):
        boom("search")
        return [{"site": "youtube", "url": f"https://yt/{i}", "id": f"v{i}", "title": f"t{i}", "uploader": "u",
                 "duration": 60, "views": 1, "query": "q"} for i in range(3)]

    def download(url, out_dir, cookies=False):
        boom("download" + ("+cookies" if cookies else ""))
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
        if "Sujet proposé" in prompt:
            boom("subject")
            return {"title_fr": "Le panda", "angle": "Star de Chengdu", "keywords": {"zh": ["熊猫"], "en": ["panda"]}}
        if "Choisis" in prompt:
            return {"pick": [0, 1], "why": "ok"}
        if prompt.startswith("Voici un script"):
            boom("fit")
            want = int(re.search(r"environ (\d+) mots", prompt)[1])
            return {"title_fr": "Titre", "lines": _lines(4, want // 4), "description": "Desc.", "hashtags": ["#Chine"]}
        boom("script")
        return {"title_fr": "Titre", "lines": _lines(4, 45), "description": "Desc.", "hashtags": ["#Chine"]}

    def synthesize(lines, out_dir):
        boom("voice")
        durs = [len(t.split()) * sec_per_word[0] for t in lines]
        starts = [sum(durs[:i]) for i in range(len(durs))]
        return {"audio": "n.mp3", "duration": sum(durs), "provider": "fake", "voice": "v",
                "lines": [{"start": a, "end": a + d} for a, d in zip(starts, durs, strict=True)]}

    def fake_render(plan, sources, nar, out, progress=None, min_total=0.0):
        boom("render")
        total = max(nar["duration"] + render.TAIL, min_total)
        rendered.append({"words": sum(len(ln["text"].split()) for ln in plan["lines"]), "total": total})
        (out / "final.mp4").write_bytes(b"v")
        return {"video": str(out / "final.mp4"), "thumb": "", "duration": total, "pieces": 4}

    monkeypatch.setattr(search, "candidates", candidates)
    monkeypatch.setattr(search, "download", download)
    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(llm, "ask_json", ask_json)
    monkeypatch.setattr(tts, "synthesize", synthesize)
    monkeypatch.setattr(render, "render", fake_render)
    monkeypatch.setattr(scenes, "detect", lambda path: [10.0, 20.0])
    db.upsert_trend({"id": "douyin:p", "source": "douyin", "ext_id": "p", "url": "https://x", "title_zh": "中文",
                     "title_fr": "Titre", "angle": "a", "reason": "r", "keywords": {"zh": ["中文"]}, "score": 70,
                     "rank": 1})
    calls.speed, calls.rendered = sec_per_word, rendered
    return calls, fail


class Calls(list):
    """Danh sách bước đã chạy, kèm tốc độ đọc giả (speed[0]) và các lần dựng (rendered)."""


def _lines(n: int, words: int) -> list[dict]:
    return [{"text": " ".join(["mot"] * words), "clips": []} for _ in range(n)]


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


def test_pasted_links_are_always_used_and_fill_up_with_search(fake):
    calls, _ = fake
    pid = _new()
    db.update_project(pid, meta={"links": ["https://www.douyin.com/video/7"]})
    pipeline.produce(pid)
    chosen = db.get_project(pid)["meta"]["chosen"]
    assert [c["url"] for c in chosen] == ["https://www.douyin.com/video/7", "https://yt/0", "https://yt/1"]
    assert calls[:4] == ["search", "download+cookies", "download", "download"]


def test_links_only_skips_search(fake):
    calls, _ = fake
    pid = _new()
    db.update_project(pid, meta={"links": ["https://x.com/a/status/1"], "links_only": True})
    pipeline.produce(pid)
    assert calls[:2] == ["download+cookies", "transcribe"]
    assert [s["url"] for s in db.get_project(pid)["meta"]["sources"]] == ["https://x.com/a/status/1"]


def test_add_links_then_retry_from_download(fake):
    calls, _ = fake
    pid = _new()
    pipeline.produce(pid)
    assert pipeline.add_links(pid, ["https://www.douyin.com/video/9"]) == "download"
    calls.clear()
    pipeline.resume(pid, "download")
    assert calls[:3] == ["download", "download", "download+cookies"] and "search" not in calls
    assert len(db.get_project(pid)["meta"]["sources"]) == 3
    fresh = _new()
    assert pipeline.add_links(fresh, ["https://x.com/a/status/2"]) == "search"


def test_clean_links():
    assert search.clean_links([" https://a.com/x ", "", "https://a.com/x", "http://b.fr/y"]) == [
        "https://a.com/x", "http://b.fr/y"]
    with pytest.raises(ValueError):
        search.clean_links(["douyin.com/video/1"])
    with pytest.raises(ValueError):
        search.clean_links([f"https://a.com/{i}" for i in range(11)])


@pytest.fixture
def prompts(fake, monkeypatch):
    """(prompt, system) của mọi lần gọi Claude."""
    got, inner = [], llm.ask_json

    def spy(prompt, system, **kw):
        got.append((prompt, system))
        return inner(prompt, system, **kw)

    monkeypatch.setattr(llm, "ask_json", spy)
    return got


def test_topic_searches_and_writes_an_explainer(fake, prompts):
    calls, _ = fake
    pid = topic.create("gấu trúc", ["https://www.facebook.com/reel/fb9"], duration=90, rights="cc")
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done" and p["mode"] == "topic" and p["trend_id"] is None
    assert calls == ["subject", "search", "download+cookies", "download", "download", "transcribe", "transcribe",
                     "transcribe", "script", "voice", "render"]
    assert p["meta"]["subject"]["title_fr"] == "Le panda" and p["meta"]["rights"] == "cc"
    systems = [sys for _, sys in prompts]
    assert systems == [topic.SUBJECT_SYSTEM, topic.PICK_SYSTEM, topic.SCRIPT_SYSTEM]
    script = prompts[-1][0]
    # lựa chọn 1 phút 30 nhắm 85 s cho chừa chỗ dưới trần 90 s
    assert "Sujet : gấu trúc / Le panda" in script and "de 10 à 15 lignes" in script and "≈ 85 secondes" in script


def test_topic_from_links_only(fake, prompts):
    calls, _ = fake
    pid = topic.create("", ["https://www.bilibili.com/video/BV1", "https://www.douyin.com/video/2"], duration=70)
    assert db.get_project(pid)["title"] == "Video từ www.bilibili.com (+1)"
    pipeline.produce(pid)
    assert calls == ["download+cookies", "download+cookies", "transcribe", "transcribe", "script", "voice", "render"]
    assert f"Sujet : {topic.NO_TOPIC}" in prompts[-1][0] and "de 8 à 13 lignes" in prompts[-1][0]


def test_topic_retry_keeps_the_subject(fake):
    calls, fail = fake
    pid = topic.create("gấu trúc")
    fail.add("script")
    with pytest.raises(RuntimeError):
        pipeline.produce(pid)
    calls.clear()
    pipeline.resume(pid)
    assert calls == ["script", "voice", "render"]
    calls.clear()
    pipeline.resume(pid, "search")  # tìm lại nguồn nhưng không diễn giải lại chủ đề
    assert calls[0] == "search"


@pytest.mark.parametrize("kw", [{}, {"topic": " "}, {"topic": "x", "duration": 60}, {"topic": "x", "rights": "mine"},
                                {"links": ["douyin.com/1"]}])
def test_topic_create_rejects_bad_input(kw):
    with pytest.raises(ValueError):
        topic.create(**kw)


def test_every_video_is_62_to_90_seconds(fake):
    calls, _ = fake
    pid = _new()
    pipeline.produce(pid)
    assert calls.rendered[-1]["total"] == pytest.approx(180 * 0.4 + 0.6)  # 72.6 s: không phải chỉnh
    assert "fit" not in calls


def test_short_narration_is_rewritten_then_read_again(fake):
    calls, _ = fake
    calls.speed[0] = 0.25  # đọc nhanh: 180 từ → 45 s
    pid = _new()
    pipeline.produce(pid)
    assert calls[-4:] == ["voice", "fit", "voice", "render"]
    # nhắm 80 s theo tốc độ đo được: (80 - 0.6) / 0.25 ≈ 318 từ → 4 dòng × 79 từ → 79 s
    assert calls.rendered[-1]["words"] == 316 and 62 <= calls.rendered[-1]["total"] <= 90
    saved = json.loads((config.PROJECTS / str(pid) / "script.json").read_text())
    assert pipeline._words(saved) == 316  # rerender đọc bản đã chỉnh


def test_still_short_video_is_padded_to_62_seconds(fake, monkeypatch):
    calls, _ = fake
    calls.speed[0] = 0.25
    monkeypatch.setattr(pipeline, "_fit", lambda plan, want: plan)  # Claude không viết dài ra được
    pid = _new()
    pipeline.produce(pid)
    assert calls.rendered[-1]["total"] == pipeline.MIN_SECONDS
    assert "kéo dài phần cuối" in db.get_project(pid)["log"]


def test_too_short_script_is_lengthened_before_voice(fake, monkeypatch):
    calls, _ = fake
    real = llm.ask_json

    def short_script(prompt, system, **kw):
        out = real(prompt, system, **kw)
        if system == pipeline.SCRIPT_SYSTEM:
            out["lines"] = _lines(4, 20)  # 80 từ ≈ 32 s
        return out

    monkeypatch.setattr(llm, "ask_json", short_script)
    pid = _new()
    pipeline.produce(pid)
    assert calls[-4:] == ["script", "fit", "voice", "render"]
    assert calls.rendered[-1]["words"] == 200  # 80 s × 2,5 từ/s


def test_old_lengths_are_raised():
    assert [pipeline.target_seconds(d) for d in (None, 30, 60, 75, 90, 120)] == [80, 70, 70, 75, 85, 85]


def _long_script(monkeypatch, lines: list[dict], extra_fit_words: int = 0) -> None:
    """Claude viết kịch bản `lines`; khi chỉnh độ dài thì viết dư `extra_fit_words` từ so với số từ được hỏi."""
    real = llm.ask_json

    def ask_json(prompt, system, **kw):
        out = real(prompt, system, **kw)
        if system == pipeline.SCRIPT_SYSTEM:
            out["lines"] = lines
        elif prompt.startswith("Voici un script"):
            want = int(re.search(r"environ (\d+) mots", prompt)[1]) + extra_fit_words
            q, r = divmod(want, 4)
            out["lines"] = _lines(3, q) + _lines(1, q + r)
        return out

    monkeypatch.setattr(llm, "ask_json", ask_json)


def test_90_second_option_leaves_room_for_a_long_rewrite(fake, monkeypatch):
    calls, _ = fake
    _long_script(monkeypatch, _lines(6, 45), extra_fit_words=10)  # 270 từ ≈ 108 s; Claude viết dư 10 từ
    pid = _new()
    pipeline.produce(pid, duration_sec=90)
    # nhắm 85 s: 270 × (85 - 0.6) / 108 = 211 từ, dư 10 → 221 từ → 89 s (nhắm 90 s thì ra 94 s)
    assert calls[-4:] == ["voice", "fit", "voice", "render"]
    assert calls.rendered[-1]["words"] == 221 and calls.rendered[-1]["total"] == pytest.approx(89.0)


def test_video_still_over_90_seconds_is_trimmed(fake, monkeypatch):
    calls, _ = fake
    lines = [{"text": f"{tag} " + " ".join(["mot"] * 19), "clips": []} for tag in ["debut", *"abcdefghij", "fin"]]
    _long_script(monkeypatch, lines)  # 12 câu × 20 từ = 240 từ → 96.6 s
    monkeypatch.setattr(pipeline, "_fit", lambda plan, want: plan)  # Claude không rút ngắn được
    pid = _new()
    pipeline.produce(pid)
    assert calls[-3:] == ["voice", "voice", "render"]
    assert calls.rendered[-1]["total"] == pytest.approx(88.6)  # bỏ 1 câu (8 s)
    saved = json.loads((config.PROJECTS / str(pid) / "script.json").read_text())
    tags = [ln["text"].split()[0] for ln in saved["lines"]]
    assert tags == ["debut", *"abcdefghi", "fin"]  # giữ câu mở đầu và câu kết, bỏ câu gần cuối
    assert "bỏ 1 câu gần cuối" in db.get_project(pid)["log"]


def test_trim_keeps_three_lines_and_estimates_without_timings():
    plan = {"title_fr": "T", "lines": _lines(5, 60)}  # 300 từ
    cut, n = pipeline._trim(plan, {"duration": 200.0, "lines": []})  # 40 s mỗi câu
    assert n == 2 and len(cut["lines"]) == 3 and len(plan["lines"]) == 5
