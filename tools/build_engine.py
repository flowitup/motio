"""Đóng gói engine thành thư mục chạy được (PyInstaller onedir) + ffmpeg/ffprobe/deno trong bin/.

uv run --group build python tools/build_engine.py
→ app/src-tauri/resources/motio-engine/motio-engine[.exe]  (Tauri đưa cả thư mục vào bản cài)

uv run python tools/build_engine.py --check <thư mục motio-engine>
→ chỉ kiểm tra (macOS): mlx.metallib nằm cạnh mọi libmlx.dylib; dùng cho bản .app Tauri đã dựng
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
MLX_LIBS = ("libmlx.dylib", "libjaccl.dylib")


def bundle_root(engine: Path) -> Path:
    """PyInstaller 6 đặt thư viện trong _internal/, bản cũ hơn đặt cạnh file chạy."""
    return engine / "_internal" if (engine / "_internal").is_dir() else engine


def fix_mlx(engine: Path) -> None:
    """mlx chỉ tìm mlx.metallib cạnh libmlx.dylib mà nó nạp (dladdr), không tìm ở đâu khác.

    collect_all đặt libmlx.dylib và mlx.metallib trong mlx/lib/; PyInstaller đổi rpath của core.so sang _internal/ và
    để ở đó symlink tới libmlx.dylib, rồi Tauri chép symlink thành file thật. Bản cài (v0.7.10) có libmlx.dylib ở
    _internal/ mà mlx.metallib chỉ ở mlx/lib/, nên `import mlx.core` báo "Failed to load the default metallib".
    Ở đây: thay symlink bằng file thật (một bản, không chép đôi) rồi đặt mlx.metallib cạnh từng libmlx.dylib.
    """
    root = bundle_root(engine)
    for name in MLX_LIBS:
        link = root / name
        if link.is_symlink():
            real = link.resolve()
            link.unlink()
            if real.is_relative_to(root.resolve()):
                shutil.move(real, link)
            else:
                shutil.copy2(real, link)
    libs = sorted(root.rglob("libmlx.dylib"))
    if not libs:
        raise SystemExit("libmlx.dylib is missing from the bundle: transcription will fail on macOS")
    found = [p for p in root.rglob("mlx.metallib") if p.is_file() and not p.is_symlink()]
    if not found:
        raise SystemExit("mlx.metallib is missing from the bundle: is mlx-metal installed?")
    src = found[0]
    dirs = {lib.parent for lib in libs}
    for d in sorted(dirs):
        if not (d / "mlx.metallib").is_file():
            shutil.copy2(src, d / "mlx.metallib")
    if src.parent not in dirs:  # không thư viện nào nạp từ đó: khỏi giữ bản thứ hai (~180 MB)
        src.unlink()


def check_mlx(engine: Path) -> None:
    """Đúng điều kiện mlx cần lúc chạy: mlx.metallib là file thật cạnh mỗi libmlx.dylib trong bản đóng gói."""
    libs = sorted(bundle_root(engine).rglob("libmlx.dylib"))
    if not libs:
        raise SystemExit(f"No libmlx.dylib under {engine}: the bundle has no mlx")
    bad = [str(lib.parent.relative_to(engine)) for lib in libs if not (lib.parent / "mlx.metallib").is_file()]
    if bad:
        raise SystemExit("mlx.metallib is not next to libmlx.dylib in: " + ", ".join(bad)
                         + " (import mlx.core would fail: Failed to load the default metallib)")


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        check_mlx(Path(sys.argv[2]))
        print("mlx.metallib is next to libmlx.dylib")
        return
    args = [sys.executable, "-m", "PyInstaller", str(ROOT / "tools/engine_entry.py"),
            "--name", NAME, "--onedir", "--console", "--noconfirm", "--clean",
            "--distpath", str(OUT), "--workpath", str(WORK), "--specpath", str(WORK),
            "--paths", str(ROOT),
            "--collect-submodules", "motio", "--collect-submodules", "yt_dlp",
            "--collect-submodules", "uvicorn", "--collect-all", "yt_dlp_ejs",
            "--collect-all", "f2",  # f2 reads its yaml config and locale files from disk
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
    if platform.system() == "Darwin":
        fix_mlx(OUT / NAME)
        check_mlx(OUT / NAME)
    subprocess.run([sys.executable, str(ROOT / "tools/fetch_ffmpeg.py"), str(OUT / NAME / "bin")], check=True)
    win = platform.system() == "Windows"
    subprocess.run([str(OUT / NAME / "bin" / ("deno.exe" if win else "deno")), "--version"], check=True)
    if not any("yt_dlp_ejs" in f.parts for f in (OUT / NAME).rglob("*.js")):
        raise SystemExit("yt-dlp-ejs scripts are missing from the bundle: YouTube downloads will fail")
    if not any(p.parent.parent.name == "f2" for p in (OUT / NAME).rglob("conf.yaml")):
        raise SystemExit("f2 config files are missing from the bundle: Douyin downloads will fall back to yt-dlp")
    exe = OUT / NAME / (NAME + (".exe" if win else ""))
    print(f"Engine: {exe}")


if __name__ == "__main__":
    main()
