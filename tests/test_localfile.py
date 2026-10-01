"""A video file added by hand as a source (motio/localfile.py): upload, link, download-like result, titles."""
import io
import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient
from yt_dlp.utils import DownloadError

from motio import api, config, db, dub, localfile, pipeline, qa, search, topic

has_ffmpeg = bool(config.find("ffmpeg") and config.find("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


def make(path, seconds=3, audio=True, video=True, size="320x568"):
    cmd = [config.ffmpeg(), "-y", "-v", "error"]
    if video:
        cmd += ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    cmd += ["-t", str(seconds)]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"] if video else ["-vn"]
    cmd += ["-c:a", "aac"] if audio else ["-an"]
    subprocess.run([*cmd, str(path)], check=True, capture_output=True)
    return path


def upload(path, name=None):
    with open(path, "rb") as f:
        return localfile.save(name or path.name, f)


@needs_ffmpeg
def test_an_mp4_is_stored_with_the_downloaded_sources(tmp_path):
    saved = upload(make(tmp_path / "douyin clip.mp4"), "Douyin clip.mp4")
    uid, name = localfile.parse(saved["link"])
    assert name == "Douyin clip.mp4" and saved["name"] == "Douyin clip.mp4"
    assert saved["link"] == f"file:{uid}/Douyin clip.mp4"
    stored = config.CACHE / "sources" / f"File_{uid}.mp4"  # the pattern pipeline / Remove logo look sources up by
    assert stored.is_file() and localfile.path_of(uid) == stored
    assert (saved["width"], saved["height"]) == (320, 568) and 2.5 < saved["duration"] < 3.5
    assert not list((config.CACHE / "sources").glob(".upload-*"))


@needs_ffmpeg
def test_another_container_becomes_an_mp4(tmp_path):
    mkv = make(tmp_path / "a.mkv")
    saved = upload(mkv)
    uid, _ = localfile.parse(saved["link"])
    assert localfile.path_of(uid).suffix == ".mp4"
    assert localfile.source(saved["link"])["duration"] > 2


@needs_ffmpeg
def test_files_that_are_not_usable_videos_are_refused(tmp_path):
    with pytest.raises(ValueError, match="Only video files"):
        localfile.save("notes.txt", io.BytesIO(b"hello"))
    with pytest.raises(ValueError, match="cannot be read"):
        localfile.save("fake.mp4", io.BytesIO(b"this is not a video"))
    with pytest.raises(ValueError, match="no video"):
        upload(make(tmp_path / "sound.mp4", video=False))
    assert not list((config.CACHE / "sources").glob(".upload-*"))


def test_a_file_that_is_too_large_is_refused(monkeypatch):
    monkeypatch.setattr(localfile, "MAX_BYTES", 1000)
    with pytest.raises(ValueError, match="too large"):
        localfile.save("big.mp4", io.BytesIO(b"x" * 5000))
    assert not list((config.CACHE / "sources").glob(".upload-*"))


def test_the_link_is_told_from_web_links_and_paths():
    uid = "a" * 32
    assert localfile.parse(f"file:{uid}/clip.mp4") == (uid, "clip.mp4")
    assert localfile.parse(f"file:{uid}") == (uid, "")
    assert localfile.parse(f"  file:{uid}/x  ") == (uid, "x")
    for other in ("https://www.douyin.com/video/1", "/Users/me/clip.mp4", "file:///Users/me/x.mp4", "file:abc/x", ""):
        assert localfile.parse(other) is None


@needs_ffmpeg
def test_links_accept_a_stored_file_and_refuse_a_missing_one(tmp_path):
    saved = upload(make(tmp_path / "c.mp4"), "Mon clip.mp4")
    uid, _ = localfile.parse(saved["link"])
    renamed = f"file:{uid}/whatever.mp4"
    assert search.clean_links([renamed, saved["link"], "https://youtu.be/x.y"]) == [saved["link"], "https://youtu.be/x.y"]
    with pytest.raises(ValueError, match="no longer here"):
        search.clean_links([f"file:{'0' * 32}/gone.mp4"])
    assert search.link_candidate(saved["link"])["pinned"] is True


@needs_ffmpeg
def test_download_of_a_file_does_not_call_yt_dlp(tmp_path, monkeypatch):
    saved = upload(make(tmp_path / "c.mp4"), "Panda au zoo.mp4")
    monkeypatch.setattr(search, "YoutubeDL", lambda *a, **k: pytest.fail("yt-dlp must not be used for a file"))
    got = search.download(saved["link"], tmp_path / "out", cookies=True)
    uid, _ = localfile.parse(saved["link"])
    assert got["path"] == str(config.CACHE / "sources" / f"File_{uid}.mp4")
    assert (got["platform"], got["id"], got["url"], got["title"]) == ("File", uid, saved["link"], "Panda au zoo")
    assert got["uploader"] == "" and got["license"] == "" and 2.5 < got["duration"] < 3.5
    assert not (tmp_path / "out").exists()
    # a file taken away is reported plainly, so the Download step can skip it
    config.CACHE.joinpath("sources", f"File_{uid}.mp4").unlink()
    with pytest.raises(FileNotFoundError, match="no longer here"):
        search.download(saved["link"], tmp_path / "out")


@needs_ffmpeg
def test_dub_and_topic_projects_are_named_after_the_file(tmp_path):
    saved = upload(make(tmp_path / "c.mp4"), "Le panda géant.mp4")
    d = db.get_project(dub.create(saved["link"]))
    assert d["title"] == "Dub: Le panda géant" and d["meta"]["links"] == [saved["link"]]
    t = db.get_project(topic.create("", [saved["link"]]))
    assert t["title"] == "Video from Le panda géant" and t["meta"]["links_only"] is True


@needs_ffmpeg
def test_a_file_source_goes_through_the_download_step(tmp_path, monkeypatch):
    saved = upload(make(tmp_path / "c.mp4"), "clip.mp4")
    monkeypatch.setattr(search, "YoutubeDL", lambda *a, **k: pytest.fail("yt-dlp must not be used for a file"))
    steps = []
    got = pipeline._step_download([search.link_candidate(saved["link"])], lambda *a, **k: steps.append(a))
    assert got[0]["platform"] == "File" and got[0]["url"] == saved["link"]
    # and a project that is resumed finds the file again by its id even if the saved path moved
    pid = db.create_project(None, "t", mode="topic")
    db.update_project(pid, meta={"sources": [{**got[0], "path": str(tmp_path / "moved.mp4")}]})
    assert pipeline._load_sources(pid)[0]["path"] == got[0]["path"]


@needs_ffmpeg
def test_the_upload_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "produce", lambda pid, **kw: None)  # the route is under test, not the pipeline
    with TestClient(api.create_app(TOKEN)) as c:
        video = make(tmp_path / "up.mp4")
        assert c.post("/api/uploads", files={"file": ("up.mp4", video.read_bytes())}).status_code == 401
        r = c.post("/api/uploads", headers=H, files={"file": ("Douyin up.mp4", video.read_bytes(), "video/mp4")})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Douyin up.mp4" and body["link"].startswith("file:") and body["duration"] > 2
        bad = c.post("/api/uploads", headers=H, files={"file": ("x.mp4", b"not a video")})
        assert bad.status_code == 400 and "cannot be read" in bad.json()["detail"]
        txt = c.post("/api/uploads", headers=H, files={"file": ("x.txt", b"hello")})
        assert txt.status_code == 400
        made = c.post("/api/dubs", headers=H, json={"link": body["link"]})
        assert made.status_code == 202, made.text
        assert db.get_project(made.json()["project_id"])["meta"]["links"] == [body["link"]]


def test_douyin_without_a_browser_session_says_what_to_do(tmp_path, monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            raise DownloadError("ERROR: [Douyin] 123: Fresh cookies (not necessarily logged in) are needed")

    monkeypatch.setattr(search, "YoutubeDL", Boom)
    monkeypatch.setattr(config, "ffmpeg", lambda: "ffmpeg")  # read before yt-dlp is called; CI has no FFmpeg
    with pytest.raises(RuntimeError, match="add the file"):
        search.download("https://www.douyin.com/video/7380308675841297704", tmp_path)
    with pytest.raises(DownloadError):  # any other site keeps yt-dlp's own message
        search.download("https://example.com/video/1", tmp_path)


@needs_ffmpeg
def test_a_recording_without_a_stated_duration_is_accepted_and_gets_one(tmp_path):
    live = tmp_path / "recording.webm"  # a browser or OBS recording: the container does not say how long it is
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=25",
                    "-t", "3", "-c:v", "libvpx", "-live", "1", "-f", "webm", str(live)],
                   check=True, capture_output=True)
    assert qa.probe(live)["duration"] < 1.0  # the premise: nothing in the file says it lasts 3 s
    saved = upload(live)
    assert 2.5 < saved["duration"] < 3.5
    uid, _ = localfile.parse(saved["link"])
    assert 2.5 < qa.probe(localfile.path_of(uid))["duration"] < 3.5


@needs_ffmpeg
def test_a_video_that_is_too_short_is_refused_and_leaves_nothing_behind(tmp_path):
    with pytest.raises(ValueError, match="too short"):
        upload(make(tmp_path / "blink.mp4", seconds=0.5))
    assert not list((config.CACHE / "sources").glob("File_*")) or all(
        qa.probe(p)["duration"] >= 1 for p in (config.CACHE / "sources").glob("File_*.mp4"))
    assert not list((config.CACHE / "sources").glob(".upload-*"))


@needs_ffmpeg
def test_the_same_video_added_twice_is_the_same_source(tmp_path):
    one = upload(make(tmp_path / "a.mp4", seconds=2), "first name.mp4")
    again = upload(tmp_path / "a.mp4", "other name.mp4")
    other = upload(make(tmp_path / "b.mp4", seconds=3), "b.mp4")
    uid = localfile.parse(one["link"])[0]
    assert localfile.parse(again["link"])[0] == uid != localfile.parse(other["link"])[0]
    assert len(uid) == 32 and localfile.path_of(uid).is_file()
    assert localfile.source(again["link"])["id"] == uid  # so qa.repeats compares ("File", uid) with an earlier project
    pids = []
    for _ in range(2):
        pid = db.create_project(None, "t", mode="topic")
        db.update_project(pid, meta={"sources": [{"platform": "File", "id": uid}]})
        pids.append(pid)
    assert [c["id"] for c in qa.repeats(pids[1]) if c["id"] == "repeat_source"] == ["repeat_source"]


def test_an_upload_copy_a_stopped_engine_left_behind_is_swept(monkeypatch):
    folder = config.CACHE / "sources"
    folder.mkdir(parents=True, exist_ok=True)
    old, fresh = folder / ".upload-1.mp4", folder / ".upload-2.mp4"
    for f in (old, fresh):
        f.write_bytes(b"x")
    os.utime(old, (time.time() - localfile.STALE_UPLOAD - 60,) * 2)
    with pytest.raises(ValueError, match="Only video files"):
        localfile.save("x.txt", io.BytesIO(b""))  # refused before anything is swept
    assert old.exists() and fresh.exists()
    with pytest.raises(ValueError, match="cannot be read"):
        localfile.save("x.mp4", io.BytesIO(b"nope"))
    assert not old.exists() and fresh.exists()
    fresh.unlink()


def test_a_file_source_is_not_credited_in_the_post_or_on_the_video(tmp_path, monkeypatch):
    monkeypatch.setenv("CREDIT_IN_POST", "true")
    uid = "a" * 32
    sources = [{"platform": "File", "uploader": "", "url": f"file:{uid}/Douyin clip.mp4"},
               {"platform": "YouTube", "uploader": "Chaîne", "url": "https://youtu.be/x"}]
    plan = {"title_fr": "Titre", "description": "Desc.", "hashtags": ["#a"]}
    desc = pipeline.write_post(plan, sources, tmp_path)
    assert "Douyin clip" not in desc and "• YouTube · Chaîne — https://youtu.be/x" in desc
    internal = (tmp_path / "sources.txt").read_text(encoding="utf-8")
    assert "file:" + uid in internal and "https://youtu.be/x" in internal  # the internal list keeps both
    monkeypatch.setenv("CREDIT_IN_POST", "")
    only = tmp_path / "only"
    only.mkdir()
    assert "Sources" not in pipeline.write_post(plan, sources[:1], only)
