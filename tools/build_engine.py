"""Đóng gói engine thành thư mục chạy được (PyInstaller onedir) + ffmpeg/ffprobe/deno trong bin/.

uv run --group build python tools/build_engine.py
→ app/src-tauri/resources/motio-engine/motio-engine[.exe]  (Tauri đưa cả thư mục vào bản cài)
"""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app/src-tauri/resources"
WORK = ROOT / "build/pyinstaller"
NAME = "motio-engine"


def main() -> None:
    args = [sys.executable, "-m", "PyInstaller", str(ROOT / "tools/engine_entry.py"),
            "--name", NAME, "--onedir", "--console", "--noconfirm", "--clean",
            "--distpath", str(OUT), "--workpath", str(WORK), "--specpath", str(WORK),
            "--paths", str(ROOT),
            "--collect-submodules", "motio", "--collect-submodules", "yt_dlp",
            "--collect-submodules", "uvicorn", "--collect-all", "yt_dlp_ejs",
            "--exclude-module", "tkinter", "--exclude-module", "motio.web"]
    if platform.system() == "Darwin":
        # torch chỉ dùng trong mlx_whisper.torch_whisper (chuyển đổi model), không cần khi bóc lời
        args += ["--collect-all", "mlx", "--collect-all", "mlx_whisper",
                 "--exclude-module", "torch", "--exclude-module", "mlx_whisper.torch_whisper"]
    else:
        args += ["--collect-all", "faster_whisper", "--collect-all", "ctranslate2"]
    if (OUT / NAME).exists():
        shutil.rmtree(OUT / NAME)
    subprocess.run(args, check=True, cwd=ROOT)
    subprocess.run([sys.executable, str(ROOT / "tools/fetch_ffmpeg.py"), str(OUT / NAME / "bin")], check=True)
    win = platform.system() == "Windows"
    subprocess.run([str(OUT / NAME / "bin" / ("deno.exe" if win else "deno")), "--version"], check=True)
    if not any("yt_dlp_ejs" in f.parts for f in (OUT / NAME).rglob("*.js")):
        raise SystemExit("Thiếu script yt-dlp-ejs trong bản đóng gói: YouTube sẽ không tải được")
    exe = OUT / NAME / (NAME + (".exe" if win else ""))
    print(f"Engine: {exe}")


if __name__ == "__main__":
    main()
