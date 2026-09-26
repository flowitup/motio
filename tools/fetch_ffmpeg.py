"""Tải ffmpeg + ffprobe bản tĩnh (không phụ thuộc thư viện hệ thống) và deno vào một thư mục bin/.

uv run python tools/fetch_ffmpeg.py <out_dir>
macOS arm64: ffmpeg.martin-riedl.de (có sha256) · Windows x64: github.com/BtbN/FFmpeg-Builds
deno (yt-dlp dùng để giải thử thách JavaScript của YouTube): github.com/denoland/deno, có sha256
"""
import hashlib
import io
import platform
import re
import stat
import sys
import zipfile
from pathlib import Path

import httpx

MAC = "https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/{name}.zip"
WIN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-9.0.zip"
DENO = "https://github.com/denoland/deno/releases/download/v2.9.7/deno-{target}.zip"
DENO_TARGET = {"Darwin": "aarch64-apple-darwin", "Windows": "x86_64-pc-windows-msvc"}


def _get(url: str) -> bytes:
    r = httpx.get(url, follow_redirects=True, timeout=300)
    r.raise_for_status()
    return r.content


def _mac(out: Path) -> None:
    for name in ("ffmpeg", "ffprobe"):
        url = MAC.format(name=name)
        data = _get(url)
        want = _get(url + ".sha256").decode().split()[0].lower()
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise SystemExit(f"sha256 sai cho {name}: {got} != {want}")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next(m for m in z.namelist() if Path(m).name == name)
            dest = out / name
            dest.write_bytes(z.read(member))
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _win(out: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(_get(WIN))) as z:
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            member = next(m for m in z.namelist() if m.endswith(f"/bin/{name}"))
            (out / name).write_bytes(z.read(member))


def _deno(out: Path, system: str) -> None:
    url = DENO.format(target=DENO_TARGET[system])
    data = _get(url)
    # macOS: "<hash>  <file>"; Windows: bảng Get-FileHash ("Hash : <HASH>")
    want = re.search(r"\b[0-9a-fA-F]{64}\b", _get(url + ".sha256sum").decode())[0].lower()
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise SystemExit(f"sha256 sai cho deno: {got} != {want}")
    name = "deno.exe" if system == "Windows" else "deno"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        dest = out / name
        dest.write_bytes(z.read(name))
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    system, machine = platform.system(), platform.machine().lower()
    if system == "Darwin" and machine == "arm64":
        _mac(out)
    elif system == "Windows" and machine in ("amd64", "x86_64"):
        _win(out)
    else:
        raise SystemExit(f"Chưa hỗ trợ đóng gói ffmpeg cho {system} {machine}")
    _deno(out, system)
    print(f"ffmpeg, ffprobe, deno -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bin")
