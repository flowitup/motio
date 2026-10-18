"""Quality check after the render (motio/qa.py): FFmpeg's detectors on real (tiny) files, the pure judging of their
answers, the repeat warnings and the hold at the video gate."""
import json
import subprocess

import pytest

from motio import channels, config, db, pipeline, qa

real_run = qa.run  # conftest stubs qa.run for the tests that fake the render; these tests want the real one
has_ffmpeg = bool(config.find("ffmpeg") and config.find("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
SIZE = f"{config.W}x{config.H}"
# a sine of this amplitude measures about -14 LUFS, what render.py normalises to
LOUD = "volume=2.45"


def make(path, video="testsrc2", audio=LOUD, seconds=4.0, size=SIZE, extra=()):
    """A small H.264 / AAC file. video: an FFmpeg lavfi source ("testsrc2", "color=c=black"); audio: a filter chain
    applied to a sine (None = no sound track, "silent" = a track of digital silence)."""
    cmd = [config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"{video}=size={size}:rate=25"
           if "=" not in video else f"{video}:size={size}:rate=25"]
    if audio == "silent":
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    elif audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-af", audio]
    cmd += ["-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", *extra]
    cmd += ["-c:a", "aac", "-ar", "48000"] if audio else ["-an"]
    subprocess.run([*cmd, str(path)], check=True, capture_output=True)
    return path


def ids(res, level=None):
    return {c["id"] for c in res["checks"] if level in (None, c["level"])}


# ---------- pure: the log and the judging ----------
LOG = """[Parsed_blackdetect_0 @ 0x1] black_start:0 black_end:1.2 black_duration:1.2
[silencedetect @ 0x2] silence_start: 2.5
[silencedetect @ 0x2] silence_end: 4.7 | silence_duration: 2.2
[silencedetect @ 0x2] silence_start: 8.6
  Summary:

  Integrated loudness:
    I:         -14.6 LUFS
    Threshold: -24.9 LUFS

  Loudness range:
    LRA:         4.2 LU

  True peak:
    Peak:       -1.9 dBFS
"""


def test_the_log_is_read():
    sc = qa.parse_scan(LOG, 9.0)
    assert sc["black"] == [(0.0, 1.2)] and sc["silence"] == [(2.5, 4.7), (8.6, 9.0)]  # an open silence runs to the end
    assert (sc["lufs"], sc["lra"], sc["peak"]) == (-14.6, 4.2, -1.9)
    assert qa.parse_scan("Summary:\n I:         -inf LUFS", 5)["lufs"] == float("-inf")
    assert qa.parse_scan("nothing useful", 5) == {"black": [], "silence": [], "lufs": None, "lra": None, "peak": None}


GOOD = {"duration": 70.0, "video": {"codec_name": "h264", "pix_fmt": "yuv420p", "width": config.W, "height": config.H},
        "audio": {"codec_name": "aac"}}
CLEAN = {"black": [], "silence": [], "lufs": -14.1, "lra": 5.0, "peak": -2.0}


def levels(info, sc, lo=62, hi=90):
    return {c["id"]: c["level"] for c in qa.findings(info, sc, lo, hi)}


def test_a_good_video_passes_every_check():
    assert set(levels(GOOD, CLEAN).values()) == {"ok"}
    assert qa.level(qa.findings(GOOD, CLEAN, 62, 90)) == "ok"


def test_what_makes_a_video_unfit_to_post():
    assert levels({**GOOD, "duration": 55}, CLEAN)["length"] == "fail"
    assert levels({**GOOD, "duration": 95}, CLEAN)["length"] == "fail"
    assert levels({**GOOD, "duration": 61.9}, CLEAN)["length"] == "ok"  # container rounding is forgiven
    assert levels({**GOOD, "audio": None}, CLEAN)["audio"] == "fail"
    assert levels({**GOOD, "video": None}, CLEAN)["video"] == "fail"
    assert levels(GOOD, {**CLEAN, "silence": [(0.0, 50.0)]})["loudness"] == "fail"  # silent for 71% of it
    assert levels(GOOD, {**CLEAN, "lufs": float("-inf")})["loudness"] == "fail"
    assert levels(GOOD, {**CLEAN, "black": [(0.0, 0.8)]})["black"] == "fail"  # the cover would be black


def test_what_is_only_shown():
    assert levels({**GOOD, "video": {**GOOD["video"], "width": 540, "height": 960}}, CLEAN)["video"] == "warn"
    assert levels(GOOD, {**CLEAN, "lufs": -19.0})["loudness"] == "warn"
    assert levels(GOOD, {**CLEAN, "lufs": -13.0, "peak": -0.1})["loudness"] == "warn"
    assert levels(GOOD, {**CLEAN, "silence": [(20.0, 22.0)]})["silence"] == "warn"
    assert levels(GOOD, {**CLEAN, "silence": [(20.0, 20.9)]})["silence"] == "ok"  # shorter than a gap
    assert levels(GOOD, {**CLEAN, "silence": [(68.0, 70.0)]})["silence"] == "ok"  # the ending, not a gap
    assert levels(GOOD, {**CLEAN, "black": [(30.0, 31.0)]})["black"] == "warn"
    assert levels(GOOD, {**CLEAN, "black": [(30.0, 30.2)]})["black"] == "ok"
    gap = qa.findings(GOOD, {**CLEAN, "silence": [(10.0, 12.0), (30.0, 32.0)]}, 62, 90)
    assert "Silence of 2.0 s at 0:10 (and 1 more)" in [c["msg"] for c in gap]
    no_scan = qa.findings({**GOOD, "audio": {"codec_name": "mp3"}}, None, 62, 90)  # no scan: file facts only
    assert no_scan[-1]["level"] == "warn"


# ---------- real files ----------
@needs_ffmpeg
def test_a_real_good_video_passes(tmp_path):
    res = real_run(make(tmp_path / "ok.mp4"), 3, 5)
    assert res["level"] == "ok", res["checks"]
    assert ids(res) == {"length", "video", "audio", "loudness", "silence", "black"}
    assert any(c["id"] == "loudness" and "LUFS" in c["msg"] for c in res["checks"])


@needs_ffmpeg
def test_real_problems_are_found(tmp_path):
    short = real_run(make(tmp_path / "s.mp4", seconds=2), 3, 5)
    assert "length" in ids(short, "fail") and short["level"] == "fail"
    assert "audio" in ids(real_run(make(tmp_path / "n.mp4", audio=None), 3, 5), "fail")
    silent = real_run(make(tmp_path / "q.mp4", audio="silent"), 3, 5)
    assert "loudness" in ids(silent, "fail")
    black = real_run(make(tmp_path / "b.mp4", video="color=c=black"), 3, 5)
    assert "black" in ids(black, "fail") and "the cover would be black" in str(black["checks"])
    # a Motio render is never pure black: its title, badge and captions light a few percent of every frame
    lit = ("-vf", "drawbox=x=0:y=0:w=iw:h=ih*0.05:color=white:t=fill")
    titled = real_run(make(tmp_path / "t.mp4", video="color=c=black", extra=lit), 3, 5)
    assert "black" in ids(titled, "fail"), titled["checks"]
    assert "black" not in ids(real_run(make(tmp_path / "g.mp4", video="color=c=gray", extra=lit), 3, 5), "fail")
    small = real_run(make(tmp_path / "m.mp4", size="540x960"), 3, 5)
    assert "video" in ids(small, "warn") and small["level"] == "warn"
    loud = real_run(make(tmp_path / "l.mp4", audio="volume=0.4"), 3, 5)  # far quieter than -14 LUFS
    assert "loudness" in ids(loud, "warn")
    muted = f"{LOUD},volume=enable='between(t,1.5,3.8)':volume=0"
    gap = real_run(make(tmp_path / "g.mp4", seconds=6, audio=muted), 3, 8)
    assert "silence" in ids(gap, "warn"), gap["checks"]


@needs_ffmpeg
def test_a_file_that_is_not_a_video_fails_without_raising(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video")
    res = real_run(junk, 62, 90)
    assert res["level"] == "fail" and "cannot be read" in res["checks"][0]["msg"]
    assert real_run(tmp_path / "missing.mp4", 62, 90)["level"] == "fail"


def test_a_missing_ffmpeg_never_crashes_the_render(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ffprobe", lambda: (_ for _ in ()).throw(FileNotFoundError("ffprobe not found")))
    res = real_run(tmp_path / "x.mp4", 62, 90)
    assert res["level"] == "fail" and "ffprobe not found" in res["checks"][0]["msg"]


# ---------- what the channel already posted ----------
@pytest.fixture
def projects():
    with db.conn() as c:
        c.execute("DELETE FROM project")
    return []


def project(title, sources=(), age_days=1, status="done", words=None):
    pid = db.create_project(None, title, mode="topic")
    db.update_project(pid, status=status, meta={"title": title, "sources": [{"platform": "Bilibili", "id": s}
                                                                              for s in sources]})
    with db.conn() as c:
        c.execute("UPDATE project SET created_at=? WHERE id=?", (__import__("time").time() - age_days * 86400, pid))
    if words:
        folder = config.PROJECTS / str(pid)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "script.json").write_text(json.dumps({"lines": [{"text": words}]}), encoding="utf-8")
    return pid


def test_the_same_source_title_or_script_within_a_month_is_pointed_out(projects):
    words = "le panda géant mange du bambou tous les jours"
    old = project("Les pandas de Chengdu", sources=["BV1abc"], age_days=3, words=words)
    new = project("Les pandas de Chengdu !", sources=["BV1abc"], words=words)
    res = qa.repeats(new)
    assert ids({"checks": res}) == {"repeat_source", "repeat_title", "repeat_script"}
    assert all(c["level"] == "warn" and f"#{old}" in c["msg"] and "3 d ago" in c["msg"] for c in res)


def test_other_videos_are_not_repeats(projects):
    project("Les pandas de Chengdu", sources=["BV1abc"], words="le panda géant mange du bambou tous les jours")
    project("Plus vieux", sources=["BV1new"], age_days=45, words="x")
    project("Un projet en échec", sources=["BV1zzz"], status="failed")
    wall = "la muraille s'étend sur des milliers de kilomètres"
    other = project("La Grande Muraille la nuit", sources=["BV1other"], words=wall)
    assert qa.repeats(other) == []
    old = project("Vieux", sources=["BV1old"], age_days=40)
    again = project("Autre titre", sources=["BV1old"])  # the same source, but 40 days ago: out of the window
    assert qa.repeats(again) == [] and old


def test_the_whole_month_is_looked_at_on_a_busy_install(projects):
    old = project("Les pandas de Chengdu", sources=["BV1same"], age_days=5)
    for i in range(qa.REPEAT_LOOKBACK // 2 + 20):  # more videos than the old 60-project look-back, all within 30 days
        project(f"Autre sujet numéro {i}", sources=[f"BV1x{i}"], age_days=2)
    new = project("Un autre titre", sources=["BV1same"])
    assert [c["id"] for c in qa.repeats(new)] == ["repeat_source"] and old


def test_the_check_is_saved_with_the_repeats_and_a_failed_one_is_seen(projects, tmp_path, monkeypatch):
    first = project("Les pandas de Chengdu", sources=["BV1abc"])
    second = project("Les pandas de Chengdu", sources=["BV1abc"])
    video = tmp_path / "final.mp4"
    video.write_bytes(b"")
    res = qa.check_project(second, video, 62, 90)  # conftest: the media part says "all fine"
    assert res["level"] == "warn" and ids(res) == {"repeat_source", "repeat_title"} and first
    assert not qa.failed({"meta": {"qa": res}}) and qa.failed({"meta": {"qa": {"level": "fail"}}})
    assert not qa.failed({"meta": {}})


# ---------- the video gate ----------
def _channel(**kw):
    return channels.create({"name": "Chine", "gate_script": False, "gate_video": False, "postiz": ["tt1"], **kw})


def test_a_failed_check_stops_a_video_that_would_have_gone_to_postiz(projects, monkeypatch):
    sent = []
    monkeypatch.setattr(pipeline, "send_to_postiz", lambda pid, ch: sent.append(pid) or True)
    ch = _channel()
    pid = project("Les pandas")
    channels.attach(pid, ch)
    fail = {"level": "fail", "checks": [{"id": "audio", "level": "fail", "msg": "No sound track"}]}
    db.update_project(pid, meta={"qa": fail})
    pipeline._deliver(pid, ch)
    p = db.get_project(pid)
    assert p["status"] == "review" and p["meta"]["review"] == "video" and not sent
    assert "quality check failed: No sound track" in p["log"]
    pipeline.approve_video(pid)  # the owner looked at it: it goes out
    assert sent == [pid]
    ok = project("Les pandas 2")
    channels.attach(ok, ch)
    db.update_project(ok, meta={"qa": {"level": "warn", "checks": []}})
    pipeline._deliver(ok, ch)
    assert db.get_project(ok)["status"] == "done" and sent == [pid, ok]  # a warning never holds a video
