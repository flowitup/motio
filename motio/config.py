"""Cấu hình chung: đọc .env ở gốc repo, thư mục dữ liệu, tìm binary trên mọi hệ điều hành."""
import os
import platform
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import settings

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = Path(os.getenv("MOTIO_DATA") or ROOT / "data")
PROJECTS = DATA / "projects"
CACHE = DATA / "cache"
for _d in (DATA, PROJECTS, CACHE):
    _d.mkdir(parents=True, exist_ok=True)

IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"
IS_APPLE_SILICON = IS_MAC and platform.machine() == "arm64"


def env(key: str, default: str = "") -> str:
    """data/settings.json → biến môi trường / .env → mặc định. Đọc lúc gọi."""
    return (settings.get(key) or default).strip()


def flag(key: str, default: bool = False) -> bool:
    return env(key, "true" if default else "false").lower() in ("1", "true", "yes", "on")


# ---------- tìm binary ----------
def _bundled_bin() -> Path:
    """Thư mục bin/ cạnh engine (bản đóng gói) hoặc ở gốc repo (dev)."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT
    return base / "bin"


def _search_dirs() -> list[Path]:
    home = Path.home()
    dirs = [_bundled_bin(), home / ".local/bin"]
    if IS_WIN:
        local = Path(os.getenv("LOCALAPPDATA") or home / "AppData/Local")
        appdata = Path(os.getenv("APPDATA") or home / "AppData/Roaming")
        dirs += [local / "Microsoft/WinGet/Links", local / "Programs/claude", appdata / "npm",
                 home / "scoop/shims", Path("C:/ProgramData/chocolatey/bin"), Path("C:/ffmpeg/bin")]
    elif IS_MAC:
        dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    else:
        dirs += [Path("/usr/local/bin"), Path("/usr/bin")]
    return dirs


def which(name: str) -> str:
    """MOTIO_<NAME> → bin/ đóng kèm → PATH → các chỗ cài phổ biến. Windows thử .exe/.cmd."""
    override = os.getenv(f"MOTIO_{name.upper()}")
    if override and Path(override).exists():
        return override
    names = [name + ext for ext in (".exe", ".cmd", ".bat", "")] if IS_WIN else [name]
    bundled = _bundled_bin()
    for n in names:
        if (bundled / n).is_file():
            return str(bundled / n)
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    for d in _search_dirs():
        for n in names:
            if (d / n).is_file():
                return str(d / n)
    raise FileNotFoundError(f"Không tìm thấy {name}")


def find(name: str) -> str | None:
    try:
        return which(name)
    except FileNotFoundError:
        return None


def ffmpeg() -> str:
    return which("ffmpeg")


def ffprobe() -> str:
    return which("ffprobe")


# ---------- font ----------
_FONTS = {
    "bold": {
        "Darwin": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf"],
        "Windows": ["arialbd.ttf", "segoeuib.ttf"],
        "Linux": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                  "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
    },
    "cjk": {
        "Darwin": ["/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
                   "/System/Library/Fonts/PingFang.ttc"],
        "Windows": ["msyhbd.ttc", "msyh.ttc", "simhei.ttf"],
        "Linux": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                  "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc"],
    },
}


def font_candidates(kind: str) -> list[str]:
    """Danh sách file font theo thứ tự ưu tiên: FONT_BOLD / FONT_CJK trong .env, rồi font hệ thống."""
    out = [env("FONT_BOLD" if kind == "bold" else "FONT_CJK")]
    system = platform.system()
    for p in _FONTS[kind].get(system, _FONTS[kind]["Linux"]):
        if system == "Windows":
            windir = Path(os.getenv("WINDIR") or "C:/Windows")
            out += [str(windir / "Fonts" / p),
                    str(Path(os.getenv("LOCALAPPDATA") or "") / "Microsoft/Windows/Fonts" / p)]
        else:
            out.append(p)
    return [p for p in out if p]


# ---------- nguồn tin, giới hạn ----------
DEFAULT_NEWSNOW = "https://newsnow.busiyi.world"  # bản công khai; server dùng bản tự host http://newsnow:4444
DEFAULT_SOURCES = "douyin,weibo,baidu,bilibili-hot-search,toutiao,thepaper"


def newsnow_url() -> str:
    return env("NEWSNOW_URL", DEFAULT_NEWSNOW).rstrip("/") or DEFAULT_NEWSNOW


def _int(key: str) -> int:
    try:
        return max(int(env(key, "0") or 0), 0)
    except ValueError:
        return 0


def refresh_every_min() -> int:
    """Tự cập nhật tin mỗi N phút; 0 = tắt (bấm tay)."""
    return _int("REFRESH_EVERY_MIN")


def news_sources() -> list[str]:
    return [s.strip() for s in env("NEWS_SOURCES", DEFAULT_SOURCES).split(",") if s.strip()]


def max_videos_per_day() -> int:
    """0 = không giới hạn."""
    return _int("MAX_VIDEOS_PER_DAY")


# Ghi nguồn: mặc định tắt trên video và trong mô tả bài đăng (CREDIT_ON_VIDEO, CREDIT_IN_POST).
# Danh sách nguồn vẫn luôn được lưu nội bộ (data/projects/<id>/sources.txt).

# Khung video đầu ra
W, H, FPS = 1080, 1920, 30
