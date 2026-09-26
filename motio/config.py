"""Cấu hình chung: đọc .env ở gốc repo, thư mục dữ liệu."""
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = Path(os.getenv("MOTIO_DATA") or ROOT / "data")
PROJECTS = DATA / "projects"
CACHE = DATA / "cache"
for _d in (DATA, PROJECTS, CACHE):
    _d.mkdir(parents=True, exist_ok=True)


def env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def which(name: str, *extra: str) -> str:
    """Tìm binary trong PATH hoặc các chỗ cài phổ biến trên Mac."""
    found = shutil.which(name)
    if found:
        return found
    for base in (*extra, str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"):
        p = Path(base) / name
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"Không tìm thấy {name}")


FFMPEG = which("ffmpeg")
FFPROBE = which("ffprobe")

NEWSNOW_URL = env("NEWSNOW_URL", "https://newsnow.busiyi.world").rstrip("/")
NEWS_SOURCES = [s.strip() for s in env(
    "NEWS_SOURCES", "douyin,weibo,baidu,bilibili-hot-search,toutiao,thepaper").split(",") if s.strip()]

WHISPER_MODEL = env("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")

# Ghi nguồn: mặc định tắt trên video và trong mô tả bài đăng.
# Danh sách nguồn vẫn luôn được lưu nội bộ (data/projects/<id>/sources.txt).
CREDIT_ON_VIDEO = env("CREDIT_ON_VIDEO", "false").lower() in ("1", "true", "yes")
CREDIT_IN_POST = env("CREDIT_IN_POST", "false").lower() in ("1", "true", "yes")

# Khung video đầu ra
W, H, FPS = 1080, 1920, 30
