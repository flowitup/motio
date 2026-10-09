"""Cấu hình chung: đọc .env ở gốc repo, thư mục dữ liệu, tìm binary trên mọi hệ điều hành."""
import os
import platform
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import settings
from .i18n import tr

FROZEN = getattr(sys, "frozen", False)  # engine đóng gói bằng PyInstaller
ROOT = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent


def _user_data_dir() -> Path:
    """Bản đóng gói không ghi được vào thư mục app: dữ liệu nằm trong thư mục người dùng."""
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library/Application Support/Motio"
    if platform.system() == "Windows":
        return Path(os.getenv("APPDATA") or home / "AppData/Roaming") / "Motio"
    return Path(os.getenv("XDG_DATA_HOME") or home / ".local/share") / "motio"


DATA = Path(os.getenv("MOTIO_DATA") or (_user_data_dir() if FROZEN else ROOT / "data"))
load_dotenv(ROOT / ".env")
load_dotenv(DATA / ".env")  # bản đóng gói: .env đặt cạnh dữ liệu (không bắt buộc, nên dùng Cài đặt)
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


def disk() -> dict | None:
    """Dung lượng ổ chứa thư mục dữ liệu (byte). App nối engine từ xa cần biết máy chủ còn bao nhiêu chỗ."""
    try:
        u = shutil.disk_usage(DATA)
    except OSError:
        return None
    return {"free": u.free, "total": u.total}


# ---------- tìm binary ----------
def _bundled_bin() -> Path:
    """Thư mục bin/ cạnh engine (bản đóng gói) hoặc ở gốc repo (dev)."""
    return ROOT / "bin"


def _search_dirs() -> list[Path]:
    home = Path.home()
    dirs = [_bundled_bin(), home / ".local/bin"]
    if IS_WIN:
        local = Path(os.getenv("LOCALAPPDATA") or home / "AppData/Local")
        appdata = Path(os.getenv("APPDATA") or home / "AppData/Roaming")
        dirs += [local / "Microsoft/WinGet/Links", appdata / "npm",
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
    raise FileNotFoundError(tr("{name} not found", name=name))


def find(name: str) -> str | None:
    try:
        return which(name)
    except FileNotFoundError:
        return None


def ffmpeg() -> str:
    return which("ffmpeg")


JS_RUNTIMES = ("deno", "node", "bun")  # yt-dlp cần một runtime JavaScript (+ gói yt-dlp-ejs) để tải YouTube


def js_runtimes() -> dict:
    """Runtime JavaScript đầu tiên tìm được, theo dạng tham số `js_runtimes` của yt-dlp; {} nếu máy không có."""
    for name in JS_RUNTIMES:
        path = find(name)
        if path:
            return {name: {"path": path}}
    return {}


def ffprobe() -> str:
    return which("ffprobe")


def put_ffmpeg_on_path() -> None:
    """Thư viện gọi `ffmpeg` theo tên (mlx_whisper): thêm thư mục của ffmpeg đã tìm được vào PATH."""
    d = str(Path(ffmpeg()).parent)
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if d not in parts:
        os.environ["PATH"] = os.pathsep.join([d, *parts])


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
