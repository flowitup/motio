import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from motio import api, config, db, frames

TOKEN = "t"
ffmpeg = pytest.mark.skipif(not config.find("ffmpeg"), reason="needs ffmpeg")


def _video(pid: int, seconds: int = 3) -> None:
    folder = config.PROJECTS / str(pid)
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run([config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc=size=180x320:rate=10:duration={seconds}", "-pix_fmt", "yuv420p",
                    str(folder / "final.mp4")],
                   check=True)


@pytest.fixture
def pid():
    p = db.create_project(None, "Frames", "news")
    yield p
    db.delete_project(p)


def test_no_video_is_not_found(pid):
    with pytest.raises(FileNotFoundError):
        frames.frame(pid, 1.0)


@ffmpeg
def test_frame_is_cut_cached_and_replaced_after_a_new_render(pid):
    _video(pid)
    f = frames.frame(pid, 1.2, 120)
    assert f.is_file() and f.stat().st_size > 0 and f.suffix == ".jpg"
    assert frames.frame(pid, 1.2, 120) == f  # cached
    assert frames.frame(pid, 1.0, 9999).name.endswith(f"-{frames.MAX_WIDTH}.jpg")  # width is capped
    video = frames.video_of(pid)
    st = video.stat()
    os.utime(video, (st.st_atime, st.st_mtime + 10))  # a new render
    g = frames.frame(pid, 1.2, 120)
    assert g != f and not f.exists()


@ffmpeg
def test_past_the_end_is_an_error(pid):
    _video(pid, 2)
    with pytest.raises(ValueError):
        frames.frame(pid, 50)


@ffmpeg
def test_api_frame_takes_the_token_in_the_query(pid):
    _video(pid)
    with TestClient(api.create_app(TOKEN)) as c:
        assert c.get(f"/api/projects/{pid}/frame?t=1").status_code == 401
        r = c.get(f"/api/projects/{pid}/frame?t=1&w=100&token={TOKEN}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert c.get(f"/api/projects/999999/frame?t=1&token={TOKEN}").status_code == 404
        assert c.get(f"/api/projects/{pid}/frame?t=99&token={TOKEN}").status_code == 422
