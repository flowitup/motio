"""Sửa kịch bản và xoá dự án (motio/edit.py), không cần dịch vụ ngoài."""
import json
import os
import time

import pytest

from motio import config, db, edit, pipeline, tts

SOURCES = [{"platform": "YouTube", "uploader": "chaine", "url": "https://yt/1", "path": "/x.mp4"}]


def _plan(n=4, words=10) -> dict:
    return {"title_fr": "Titre", "description": "Desc.", "hashtags": ["#Chine", "#Panda"],
            "lines": [{"text": " ".join([f"mot{i}"] * words), "clips": [{"src": 0, "start": 5.0 + i, "end": 9.0 + i}]}
                      for i in range(n)]}


def _project(status="done", trend="douyin:e", plan=None) -> int:
    pid = db.create_project(trend, "Titre")
    out = config.PROJECTS / str(pid)
    out.mkdir(parents=True, exist_ok=True)
    (out / "script.json").write_text(json.dumps(plan or _plan(), ensure_ascii=False))
    (out / "final.mp4").write_bytes(b"v")
    old = time.time() - 60  # video dựng một phút trước
    os.utime(out / "final.mp4", (old, old))
    db.update_project(pid, status=status, meta={"sources": SOURCES, "title": "Titre", "description": "cũ"})
    return pid


@pytest.fixture(autouse=True)
def trend():
    db.upsert_trend({"id": "douyin:e", "source": "douyin", "ext_id": "e", "url": "https://x", "title_zh": "中文",
                     "title_fr": "Titre", "score": 50, "rank": 1})


def test_view_gives_script_and_length_numbers():
    pid = _project()
    v = edit.script_view(pid)
    assert v["script"]["title_fr"] == "Titre" and len(v["script"]["lines"]) == 4
    assert v["script"]["lines"][0]["clips"] == [{"src": 0, "start": 5.0, "end": 9.0}]
    assert (v["min_seconds"], v["max_seconds"]) == (pipeline.MIN_SECONDS, pipeline.MAX_SECONDS)
    assert v["words_per_sec"] == pipeline.WORDS_PER_SEC and v["stale"] is False and v["edited_at"] is None


def test_clean_normalises_and_rejects():
    raw = {"title_fr": "  Nouveau\n titre ", "description": " D ", "hashtags": ["chine", "#Chine", "#a,#b"],
           "lines": [{"text": "Une  ligne\navec retour", "clips": [{"src": "1", "start": 2, "end": 6}, {"src": "x"}]},
                     {"text": "   "}, {"text": "Pourquoi ?"}, {"text": "trois"}]}
    c = edit.clean(raw)
    assert c["title_fr"] == "Nouveau titre" and c["description"] == "D"
    assert [ln["text"] for ln in c["lines"]] == ["Une ligne avec retour", "Pourquoi ?", "trois"]  # NBSP giữ
    assert c["lines"][0]["clips"] == [{"src": 1, "start": 2.0, "end": 6.0}] and c["lines"][2]["clips"] == []
    assert c["hashtags"] == ["#chine", "#a", "#b"]
    for bad in ({**raw, "title_fr": " "}, {**raw, "lines": raw["lines"][:2]}, {**raw, "title_fr": "x" * 101},
                {**raw, "description": "d" * 1501}):
        with pytest.raises(ValueError):
            edit.clean(bad)


def test_edit_lines_marks_video_stale_and_updates_post():
    pid = _project()
    raw = edit.script_view(pid)["script"]
    raw["lines"][1]["text"] = "Une phrase réécrite à la main"
    raw["lines"].insert(2, {"text": "Ligne ajoutée", "clips": []})
    raw["hashtags"] = ["#Nouveau"]
    v = edit.save_script(pid, raw)
    assert v["stale"] is True and v["edited_at"]
    saved = json.loads((config.PROJECTS / str(pid) / "script.json").read_text())
    assert [ln["text"] for ln in saved["lines"]][1:3] == ["Une phrase réécrite à la main", "Ligne ajoutée"]
    assert saved["lines"][3]["clips"] == [{"src": 0, "start": 7.0, "end": 11.0}]  # dòng giữ đoạn hình của nó
    p = db.get_project(pid)
    assert p["meta"]["hashtags"] == ["#Nouveau"] and p["meta"]["description"].endswith("#Nouveau")
    assert "Voix off générée par IA." in p["meta"]["description"]
    post = (config.PROJECTS / str(pid) / "post.txt").read_text()
    assert post.startswith("Titre\n\nDesc.") and "#Nouveau" in post
    assert "Sửa kịch bản: lời bình (5 dòng" in p["log"] and "hashtag" in p["log"] and "cần dựng lại" in p["log"]


def test_post_only_edit_needs_no_render_and_no_change_writes_nothing():
    pid = _project()
    raw = edit.script_view(pid)["script"]
    before = db.get_project(pid)["log"]
    edit.save_script(pid, raw)
    assert db.get_project(pid)["log"] == before  # không đổi gì
    v = edit.save_script(pid, {**raw, "description": "Autre description."})
    assert v["stale"] is False and v["edited_at"] is None
    p = db.get_project(pid)
    assert p["meta"]["description"].startswith("Autre description.") and "cần dựng lại" not in p["log"]


def test_failed_project_keeps_post_untouched():
    pid = _project(status="failed")
    edit.save_script(pid, {**edit.script_view(pid)["script"], "title_fr": "Autre titre", "description": "Neuve"})
    p = db.get_project(pid)
    assert p["meta"]["title"] == "Autre titre" and p["meta"]["description"] == "cũ"
    assert not (config.PROJECTS / str(pid) / "post.txt").exists()


def test_speaking_rate_is_measured_then_kept_after_edit(monkeypatch):
    pid = _project(plan=_plan(4, 25))  # 100 từ
    out = config.PROJECTS / str(pid)
    audio = out / "audio" / "narration.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"a")
    now = time.time()
    os.utime(out / "script.json", (now - 30, now - 30))
    os.utime(audio, (now - 20, now - 20))  # giọng đọc mới hơn script.json: đúng bản đã đọc
    monkeypatch.setattr(tts, "probe_duration", lambda p: 25.0)
    assert edit.script_view(pid)["words_per_sec"] == 4.0
    monkeypatch.setattr(tts, "probe_duration", lambda p: 50.0)
    assert edit.script_view(pid)["words_per_sec"] == 2.0
    raw = edit.script_view(pid)["script"]
    raw["lines"][0]["text"] = "court"
    v = edit.save_script(pid, raw)  # script giờ mới hơn giọng: dùng tốc độ đã đo trước khi ghi
    assert v["words_per_sec"] == 2.0 and db.get_project(pid)["meta"]["speech_rate"] == 2.0


def test_busy_project_cannot_be_edited_or_deleted():
    pid = _project(status="running")
    with pytest.raises(edit.Busy):
        edit.save_script(pid, edit.script_view(pid)["script"])
    with pytest.raises(edit.Busy):
        edit.delete(pid)
    assert db.get_project(pid) and (config.PROJECTS / str(pid)).exists()


def test_missing_or_broken_script():
    pid = db.create_project(None, "x", mode="topic")
    with pytest.raises(FileNotFoundError):
        edit.script_view(pid)
    (config.PROJECTS / str(pid)).mkdir(parents=True)
    (config.PROJECTS / str(pid) / "script.json").write_text("{oops")
    with pytest.raises(ValueError):
        edit.script_view(pid)


def test_delete_removes_folder_and_frees_the_trend():
    db.upsert_trend({"id": "weibo:d", "source": "weibo", "ext_id": "d", "title_zh": "删", "title_fr": "T"})
    a, b = _project(trend="weibo:d"), _project(trend="weibo:d")
    edit.delete(a)
    assert db.get_project(a) is None and not (config.PROJECTS / str(a)).exists()
    assert db.get_trend("weibo:d")["status"] == "used"  # dự án b vẫn dùng tin này
    edit.delete(b)
    assert db.get_trend("weibo:d")["status"] == "new"
    with pytest.raises(LookupError):
        edit.delete(a)


def test_delete_topic_project_without_folder():
    pid = db.create_project(None, "x", mode="topic")
    db.update_project(pid, status="failed")
    edit.delete(pid)
    assert db.get_project(pid) is None


def test_cli_delete(capsys):
    from motio.__main__ import main
    pid = _project()
    main(["delete", str(pid)])
    assert f"#{pid}" in capsys.readouterr().out and db.get_project(pid) is None
    with pytest.raises(SystemExit):
        main(["delete", str(pid)])
