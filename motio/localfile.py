"""A video the user already has (downloaded by hand from Douyin or anywhere, a screen recording…) used as a source
like a pasted link.

It is stored with the downloaded sources, `cache/sources/File_<id>.mp4`, so every lookup that finds a source by its id
(resume, Remove logo, re-render) finds it too, and it travels as the link `file:<id>/<original name>` wherever a link is
accepted (topic videos, dub, "Source links" of a project, a trend's pasted links). The name after the slash is only for
people to read. Rights stay "unknown" until the user sets them: a file says nothing about who may reuse it.
"""
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from . import config, qa
from .i18n import tr

PLATFORM = "File"
EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".ts", ".flv")
MAX_BYTES = 2 * 1024**3
MIN_SECONDS = 1.0
STALE_UPLOAD = 6 * 3600  # an upload copy this old belongs to an engine that was stopped mid-way
_LINK = re.compile(r"file:([0-9a-f]{32})(?:/(.*))?", re.S)


def folder() -> Path:
    return config.CACHE / "sources"


def parse(link: str) -> tuple[str, str] | None:
    """"file:<id>/<name>" → (id, name); None for anything else (a web link, a path)."""
    m = _LINK.fullmatch((link or "").strip())
    return (m[1], m[2] or "") if m else None


def path_of(uid: str) -> Path | None:
    p = folder() / f"{PLATFORM}_{uid}.mp4"
    return p if p.is_file() else None


def link_for(uid: str, name: str) -> str:
    return f"file:{uid}/{' '.join(Path(name or '').name.split())[:100]}".rstrip("/")


def _meta(uid: str) -> dict:
    try:
        return json.loads((folder() / f"{PLATFORM}_{uid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def title(link: str) -> str:
    """A readable name for a project made from this file."""
    uid, name = parse(link) or ("", "")
    return Path(name or _meta(uid).get("name") or "").stem[:120] or tr("video file")


def check(link: str) -> str:
    """The link, rewritten with the saved name; ValueError when the file is not on this machine any more."""
    parsed = parse(link)
    if not parsed or not path_of(parsed[0]):
        raise ValueError(tr("The video file is no longer here: add it again"))
    uid = parsed[0]
    return link_for(uid, _meta(uid).get("name") or parsed[1])


def _remux(src: Path, dst: Path) -> None:
    """Copy the streams into an mp4 when they fit; otherwise encode H.264 / AAC."""
    base = [config.ffmpeg(), "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?"]
    for codecs in (["-c", "copy"], ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                                    "-c:a", "aac", "-b:a", "160k"]):
        r = subprocess.run(base + codecs + ["-movflags", "+faststart", str(dst)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
            return
        dst.unlink(missing_ok=True)
    raise ValueError(tr("This video file cannot be read: {error}", error=(r.stderr or "").strip()[-160:]))


def _sweep() -> None:
    """Remove the copies a stopped engine left behind (`.upload-*` older than STALE_UPLOAD)."""
    for f in folder().glob(".upload-*"):
        try:
            if time.time() - f.stat().st_mtime > STALE_UPLOAD:
                f.unlink()
        except OSError:
            pass


def save(name: str, stream) -> dict:
    """Store an uploaded video (read in chunks). {"link", "name", "duration", "width", "height", "size"}.
    The id is the hash of the file's bytes: the same video added twice is the same source, so the "used in the last 30
    days" warning of qa.py can see it."""
    base = Path(name or "video.mp4").name
    ext = Path(base).suffix.lower()
    if ext not in EXT:
        raise ValueError(tr("Only video files are accepted: {types}", types=", ".join(EXT)))
    folder().mkdir(parents=True, exist_ok=True)
    _sweep()
    raw = folder() / f".upload-{time.time_ns()}{ext}"
    digest, size = hashlib.sha256(), 0
    dest = meta = None
    try:
        with raw.open("wb") as f:
            while chunk := stream.read(1 << 20):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError(tr("File too large (max {n} GB)", n=MAX_BYTES >> 30))
                digest.update(chunk)
                f.write(chunk)
        uid = digest.hexdigest()[:32]
        dest, meta = folder() / f"{PLATFORM}_{uid}.mp4", folder() / f"{PLATFORM}_{uid}.json"
        had = dest.is_file()  # the same file was added before: nothing to convert again
        try:
            info = qa.probe(dest if had else raw)
        except RuntimeError as e:
            raise ValueError(tr("This video file cannot be read: {error}", error=str(e)[:160])) from e
        if not info["video"]:
            raise ValueError(tr("This file has no video to use"))
        if not had:
            if ext == ".mp4" and info["duration"] >= MIN_SECONDS:
                raw.replace(dest)
            else:  # another container, or a duration the file does not state (a screen recording): the mp4 writes it
                _remux(raw, dest)
                try:
                    info = qa.probe(dest)
                except RuntimeError as e:
                    raise ValueError(tr("This video file cannot be read: {error}", error=str(e)[:160])) from e
        if info["duration"] < MIN_SECONDS:
            raise ValueError(tr("This video is too short to use (under {n} s)", n=int(MIN_SECONDS)))
        meta.write_text(json.dumps({"name": base[:200], "created_at": time.time()}), encoding="utf-8")
    except Exception:
        if dest and not had:
            dest.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
        raise
    finally:
        raw.unlink(missing_ok=True)
    v = info["video"]
    return {"link": link_for(uid, base), "name": base[:200], "duration": round(info["duration"], 2),
            "width": v.get("width"), "height": v.get("height"), "size": dest.stat().st_size}


def source(link: str) -> dict:
    """What `search.download` returns for this file (nothing to download: it is already here)."""
    parsed = parse(link)
    path = path_of(parsed[0]) if parsed else None
    if not path:
        raise FileNotFoundError(tr("The video file is no longer here: add it again"))
    uid = parsed[0]
    try:
        info = qa.probe(path)
    except RuntimeError as e:
        raise FileNotFoundError(tr("This video file cannot be read: {error}", error=str(e)[:160])) from e
    v = info["video"] or {}
    return {"path": str(path), "url": link_for(uid, _meta(uid).get("name") or parsed[1]), "id": uid,
            "title": title(link), "platform": PLATFORM, "uploader": "", "uploader_url": "", "upload_date": "",
            "duration": round(info["duration"], 2), "license": "", "width": v.get("width"), "height": v.get("height")}

