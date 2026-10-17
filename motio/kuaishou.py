"""Kuaishou (快手) videos through videodl (CharlesPikachu/videodl, PyPI `videofetch`), run as a separate program.

yt-dlp has no Kuaishou extractor and the site answers a risk-control page to a script from a data-centre address. From a
person's own home connection videodl's `KuaishouVideoClient` reads the video page (a headless browser, then plain
requests: `window.__APOLLO_STATE__` → `VisionVideoDetailPhoto`) and works on some links, not all (Mac test of
2026-10-17: 2 of 5 links; the others parsed to nothing).

videodl is under the PolyForm Noncommercial licence, so Motio never bundles or imports it: the person installs it
(`pipx install videofetch`, or `MOTIO_VIDEODL` = the path of the `videodl` command) and Motio calls the command,
with only the Kuaishou client (`-a KuaishouVideoClient`). videodl's "generic" parsers, which send the link to
third-party watermark-removal sites, are never used. Rights stay "unknown" like for every pasted link.
"""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from . import config, qa
from .i18n import tr

CLIENT = "KuaishouVideoClient"
TIMEOUT = 300
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".flv", ".ts")


class Unavailable(RuntimeError):
    """videodl is not installed, or it could not read this link."""


def tool() -> str | None:
    """The `videodl` command (MOTIO_VIDEODL, then PATH and the usual places), or None when it is not installed."""
    return config.find("videodl")


def find_id(url: str) -> str:
    """The id at the end of a Kuaishou link (`/short-video/<id>`, `/f/<code>`), or "" when there is none."""
    last = urlparse(url).path.strip("/").split("/")[-1]
    return last if re.fullmatch(r"[0-9A-Za-z_-]{6,40}", last) else ""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)


def download(url: str, out_dir: Path, hooks: list | None = None) -> dict:
    """One Kuaishou video into out_dir/Kuaishou_<id>.mp4, answering like search.download. Unavailable when videodl
    is missing or cannot read the link."""
    exe = tool()
    if not exe:
        raise Unavailable(tr("Kuaishou needs the videodl tool, which is not installed. Install it (pipx install "
                             "videofetch; its licence is non-commercial) or download the video yourself and add the "
                             "file"))
    vid = find_id(url) or f"{int(time.time())}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"Kuaishou_{vid}.mp4"
    work = out_dir / f".kuaishou-{vid}"
    title = ""
    try:
        if not (path.is_file() and path.stat().st_size):
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            cfg = json.dumps({CLIENT: {"work_dir": str(work)}})
            try:
                _run([exe, "-i", url, "-a", CLIENT, "-c", cfg])
            except (OSError, subprocess.SubprocessError) as e:
                raise Unavailable(tr("Could not run videodl for Kuaishou: {error}", error=str(e)[:200])) from e
            files = [f for f in work.rglob("*") if f.is_file() and f.suffix.lower() in VIDEO_EXT and f.stat().st_size]
            if not files:
                raise Unavailable(tr("videodl could not read this Kuaishou link (it works on some links only). "
                                     "Download the video yourself and add the file"))
            best = max(files, key=lambda f: f.stat().st_size)
            title = best.stem
            shutil.move(str(best), path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    try:
        info = qa.probe(path)
    except (RuntimeError, OSError) as e:
        path.unlink(missing_ok=True)
        raise Unavailable(tr("videodl saved a file that is not a video: {error}", error=str(e)[:160])) from e
    video = info.get("video") or {}
    if hooks:
        size = path.stat().st_size
        for hook in hooks:
            hook({"status": "finished", "downloaded_bytes": size, "total_bytes": size})
    return {"path": str(path), "url": url, "id": vid, "title": title, "platform": "Kuaishou", "uploader": "",
            "uploader_url": "", "upload_date": "", "duration": info.get("duration") or 0, "license": "",
            "width": video.get("width"), "height": video.get("height")}
