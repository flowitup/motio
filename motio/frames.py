"""Small still frames of a project's finished video, for the pictures on the app's timeline.

One JPEG per time asked, cut from `final.mp4` with FFmpeg and kept in `projects/<id>/frames/` under the video's
modification time, so a new render makes new frames and the old ones are removed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import config

MIN_WIDTH, MAX_WIDTH = 40, 480


def video_of(pid: int) -> Path:
    return config.PROJECTS / str(pid) / "final.mp4"


def frame(pid: int, at: float, width: int = 160) -> Path:
    """The frame of project `pid`'s video at `at` seconds, `width` px wide. FileNotFoundError when there is no local
    video (none yet, or it went to Google Drive), ValueError when FFmpeg cannot cut one there."""
    video = video_of(pid)
    if not video.is_file():
        raise FileNotFoundError(video)
    width = max(MIN_WIDTH, min(MAX_WIDTH, int(width)))
    at = max(0.0, float(at))
    stamp = int(video.stat().st_mtime)
    folder = video.parent / "frames"
    out = folder / f"{stamp}-{round(at * 10)}-{width}.jpg"
    if out.is_file():
        return out
    folder.mkdir(exist_ok=True)
    for old in folder.glob("*.jpg"):  # frames of an earlier render
        if not old.name.startswith(f"{stamp}-"):
            old.unlink(missing_ok=True)
    tmp = out.with_suffix(".part.jpg")
    cmd = [config.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", str(video),
           "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "6", str(tmp)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if res.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise ValueError((res.stderr or "no frame at this time").strip()[-300:])
    tmp.replace(out)
    return out
