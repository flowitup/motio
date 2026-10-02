"""Tìm và tải video nguồn bằng yt-dlp. Mỗi nguồn giữ lại nền tảng, kênh, link và giấy phép.

Tự tìm: YouTube, Bilibili (yt-dlp không có tìm kiếm cho Douyin, X). Link dán tay: mọi trang yt-dlp tải được.
"""
import atexit
import re
import shutil
import tempfile
import threading
from http.cookiejar import LoadError
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.cookies import YoutubeDLCookieJar
from yt_dlp.utils import DownloadError

from . import config, localfile
from .i18n import tr

SEARCH_PREFIX = {"youtube": "ytsearch", "bilibili": "bilisearch"}
PLATFORM = {"Youtube": "YouTube", "BiliBili": "Bilibili", "Douyin": "Douyin", "TikTok": "TikTok",
            "Twitter": "X", "Kuaishou": "Kuaishou", "Weibo": "Weibo"}

_BASE = {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 30}


def _base() -> dict:
    """Tuỳ chọn chung cho yt-dlp, kèm runtime JavaScript (Deno…) để giải thử thách của YouTube."""
    rt = config.js_runtimes()
    return {**_BASE, "js_runtimes": rt} if rt else dict(_BASE)


def search(query: str, site: str, n: int = 6) -> list[dict]:
    prefix = SEARCH_PREFIX[site]
    opts = {**_base(), "extract_flat": "in_playlist", "skip_download": True,
            **(_file_cookie_opts() if site == "bilibili" else {})}
    try:
        with YoutubeDL(opts) as y:
            info = y.extract_info(f"{prefix}{n}:{query}", download=False)
    except Exception:
        return []
    out = []
    for e in (info or {}).get("entries") or []:
        if not e:
            continue
        url = e.get("url") or e.get("webpage_url")
        if site == "youtube" and e.get("id") and not str(url).startswith("http"):
            url = f"https://www.youtube.com/watch?v={e['id']}"
        out.append({"site": site, "url": url, "id": e.get("id"), "title": e.get("title") or "",
                    "uploader": e.get("channel") or e.get("uploader") or "",
                    "duration": e.get("duration") or 0, "views": e.get("view_count") or 0,
                    "query": query})
    return out


def candidates(keywords: dict, per_query: int = 5) -> list[dict]:
    """Tìm trên YouTube (từ khoá Trung, Anh, Pháp) và Bilibili (từ khoá Trung). Gộp trùng theo URL."""
    queries = [("bilibili", q) for q in keywords.get("zh", [])[:2]]
    queries += [("youtube", q) for q in (keywords.get("zh", [])[:1] + keywords.get("en", [])[:2]
                                         + keywords.get("fr", [])[:1])]
    seen, out = set(), []
    for site, q in queries:
        for c in search(q, site, per_query):
            d = c["duration"] or 0
            if not c["url"] or c["url"] in seen or (d and (d < 15 or d > 1200)):
                continue
            seen.add(c["url"])
            out.append(c)
    return out


MAX_LINKS = 10
BROWSERS = ("chrome", "firefox", "safari", "edge", "brave", "chromium", "opera", "vivaldi")


def clean_links(links: list[str]) -> list[str]:
    """Link http(s) hợp lệ, bỏ trùng, giữ thứ tự. Sai định dạng thì ValueError."""
    out = []
    for raw in links:
        url = (raw or "").strip()
        if not url:
            continue
        if localfile.parse(url):  # a video file added in the app
            url = localfile.check(url)
        elif not re.match(r"^https?://[^\s/]+\.[^\s]+$", url):
            raise ValueError(tr("Invalid link: {url}", url=url[:120]))
        if url not in out:
            out.append(url)
    if len(out) > MAX_LINKS:
        raise ValueError(tr("At most {n} links", n=MAX_LINKS))
    return out


def link_candidate(url: str) -> dict:
    """Ứng viên từ link dán tay: luôn được dùng, tải kèm cookie trình duyệt nếu có cài đặt."""
    return {"site": "link", "url": url, "id": None, "title": "", "uploader": "", "duration": 0, "views": 0,
            "query": "", "pinned": True}


def _cookie_path(raw: str) -> Path:
    """Explorer "Copy as path" bọc đường dẫn trong dấu nháy: bỏ đi."""
    return Path(raw.strip().strip("\"'")).expanduser()


def cookie_file() -> Path | None:
    """YTDLP_COOKIES_FILE: cookies.txt (Netscape) xuất từ trình duyệt, dùng được trên máy không có trình duyệt
    (server, máy Windows chạy nền). None khi chưa đặt hoặc file không còn."""
    raw = config.env("YTDLP_COOKIES_FILE")
    path = _cookie_path(raw) if raw else None
    return path if path and path.is_file() else None


def check_cookie_file(raw: str) -> None:
    """Báo lỗi (ValueError) nếu `raw` không phải file cookies.txt mà yt-dlp đọc được. Dùng khi lưu cài đặt."""
    path = _cookie_path(raw)
    if not path.is_file():
        raise ValueError(tr("Cookie file not found: {path}", path=raw))
    try:
        YoutubeDLCookieJar(str(path)).load(ignore_discard=True, ignore_expires=True)
    except (LoadError, OSError, UnicodeDecodeError):
        raise ValueError(tr("Not a cookies.txt file (Netscape format): {path}", path=raw)) from None


_jar = threading.local()
_jar_lock = threading.Lock()
_jar_dir: Path | None = None


def _own_cookie_copy(src: Path) -> str:
    """yt-dlp ghi lại file cookie khi đóng: mỗi luồng dùng một bản sao riêng (cùng lúc có luồng làm video, luồng tải
    công cụ, luồng kiểm tra nguồn), nên không ghi đè nhau và file gốc không bị sửa. Chép lại khi file gốc đổi."""
    global _jar_dir
    with _jar_lock:
        if _jar_dir is None:
            _jar_dir = Path(tempfile.mkdtemp(prefix="motio-cookies-"))
            atexit.register(shutil.rmtree, _jar_dir, ignore_errors=True)
    dst = _jar_dir / f"{threading.get_ident()}.txt"
    st = src.stat()
    stamp = (str(src), st.st_mtime_ns, st.st_size)
    if getattr(_jar, "stamp", None) != stamp or not dst.exists():
        shutil.copyfile(src, dst)
        _jar.stamp = stamp
    return str(dst)


def _file_cookie_opts() -> dict:
    src = cookie_file()
    return {"cookiefile": _own_cookie_copy(src)} if src else {}


def _is_bilibili(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "b23.tv" or host == "bilibili.com" or host.endswith(".bilibili.com")


def _is_douyin(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(("douyin.com", "iesdouyin.com"))


def _cookie_opts() -> dict:
    """Cookie đăng nhập cho yt-dlp (Douyin, X, không gian Bilibili hay đòi): file YTDLP_COOKIES_FILE nếu có, không thì
    phiên của trình duyệt trong YTDLP_COOKIES_FROM_BROWSER (chrome…)."""
    file = _file_cookie_opts()
    if file:
        return file
    browser = config.env("YTDLP_COOKIES_FROM_BROWSER").lower()
    return {"cookiesfrombrowser": (browser,)} if browser in BROWSERS else {}


def download(url: str, out_dir: Path, max_height: int = 720, cookies: bool = False, hooks: list | None = None) -> dict:
    """Tải 1 video (≤ max_height, mp4). Trả metadata + đường dẫn file. cookies=True: link dán tay (cookie file hoặc
    trình duyệt); video Bilibili tự tìm được cũng dùng cookie file nếu có.
    hooks: hàm gọi với tiến độ tải của yt-dlp (dict có status, downloaded_bytes, total_bytes…);
    ném lỗi trong hàm thì dừng tải."""
    if localfile.parse(url):
        return localfile.source(url)
    out_dir.mkdir(parents=True, exist_ok=True)
    cookie = _cookie_opts() if cookies else _file_cookie_opts() if _is_bilibili(url) else {}
    opts = {**_base(),
            "format": f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/bv*[height<={max_height}]+ba/"
                      f"b[height<={max_height}]/b",
            "merge_output_format": "mp4",
            "outtmpl": str(out_dir / "%(extractor_key)s_%(id)s.%(ext)s"),
            "noplaylist": True, "max_filesize": 600 * 1024 * 1024,
            "ffmpeg_location": config.ffmpeg(), **cookie,
            **({"progress_hooks": hooks} if hooks else {})}
    try:
        with YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
            path = Path(y.prepare_filename(info)).with_suffix(".mp4")
    except DownloadError as e:
        if _is_douyin(url) and "cookies" in str(e).lower():  # yt-dlp's Douyin extractor needs a real browser session
            raise RuntimeError(tr("Douyin asks for fresh browser cookies to download this. Download the video yourself "
                                  "and add the file, or set a cookies file in Settings")) from e
        raise
    if not path.exists():
        matches = sorted(out_dir.glob(f"*_{info.get('id')}.*"))
        if not matches:
            raise FileNotFoundError(tr("yt-dlp did not create a file for {url}", url=url))
        path = matches[0]
    key = info.get("extractor_key") or ""
    return {"path": str(path), "url": info.get("webpage_url") or url, "id": info.get("id"),
            "title": info.get("title") or "", "platform": PLATFORM.get(key, key),
            "uploader": info.get("channel") or info.get("uploader") or "",
            "uploader_url": info.get("channel_url") or info.get("uploader_url") or "",
            "upload_date": info.get("upload_date") or "", "duration": info.get("duration") or 0,
            "license": info.get("license") or "", "width": info.get("width"), "height": info.get("height")}
