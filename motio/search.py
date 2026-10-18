"""Tìm và tải video nguồn bằng yt-dlp. Mỗi nguồn giữ lại nền tảng, kênh, link và giấy phép.

Tự tìm: YouTube, Bilibili (yt-dlp không có tìm kiếm cho Douyin, X). Link dán tay: mọi trang yt-dlp tải được, cộng Douyin
(f2), Haokan (haokan.py) và các trang Trung Quốc khác trong platforms.py.
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

from . import config, douyin, haokan, kuaishou, localfile, platforms, weibo_feed
from .i18n import tr

SEARCH_PREFIX = {"youtube": "ytsearch", "bilibili": "bilisearch"}
PLATFORM = {"Youtube": "YouTube", "BiliBili": "Bilibili", "Douyin": "Douyin", "TikTok": "TikTok",
            "Twitter": "X", "Kuaishou": "Kuaishou", **platforms.EXTRACTORS}

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


_LINK = re.compile(r"^https?://[^\s/]+\.[^\s]+$")
# Link trong câu người dùng dán: dừng ở khoảng trắng và chữ Hán / dấu câu toàn chiều rộng đứng sát link
_LINK_IN_TEXT = re.compile(r"https?://[^\s\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]+")


def clean_links(links: list[str]) -> list[str]:
    """Link http(s) hợp lệ, bỏ trùng, giữ thứ tự. Sai định dạng thì ValueError. Dán cả câu chia sẻ của app Douyin
    ("7.43 复制打开抖音… https://v.douyin.com/xxx/ 复制此链接…") thì lấy link trong câu, nhưng chỉ khi câu có đúng một
    link: hai link trên một dòng vẫn là lỗi, không lặng lẽ bỏ link thứ hai."""
    out = []
    for raw in links:
        url = (raw or "").strip()
        if not url:
            continue
        if localfile.parse(url):  # a video file added in the app
            url = localfile.check(url)
        elif re.search(r"\s", url) and len(found := _LINK_IN_TEXT.findall(url)) == 1:
            url = found[0].rstrip(".,;:!?)]}>\"'")
        if not localfile.parse(url) and not _LINK.match(url):
            raise ValueError(tr("Invalid link: {url}", url=(raw or "").strip()[:120]))
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


def _cookie_opts() -> dict:
    """Cookie đăng nhập cho yt-dlp (Douyin, X, không gian Bilibili hay đòi): file YTDLP_COOKIES_FILE nếu có, không thì
    phiên của trình duyệt trong YTDLP_COOKIES_FROM_BROWSER (chrome…)."""
    file = _file_cookie_opts()
    if file:
        return file
    browser = config.env("YTDLP_COOKIES_FROM_BROWSER").lower()
    return {"cookiesfrombrowser": (browser,)} if browser in BROWSERS else {}


_ASKS_LOGIN = re.compile(r"cookie|log ?in|sign in|\b40[13]\b|captcha|verif", re.I)


def _cannot_reach_douyin() -> RuntimeError:
    return RuntimeError(tr("Could not connect to Douyin. Check your internet connection (or VPN, proxy, DNS filter), "
                           "then try again"))


def _xigua_on_douyin(url: str, out_dir: Path, max_height: int | None, hooks: list | None) -> dict | None:
    """The same video on Douyin (f2, no cookies) when Xigua mirrored it there under the same id, else None."""
    m = re.search(r"ixigua\.com/(?:video/|douyin/share/video/)?(\d{10,})", url)
    if not m:
        return None
    try:
        return douyin.download(f"https://www.douyin.com/video/{m[1]}", out_dir, max_height or douyin.DEFAULT_HEIGHT,
                               hooks, m[1])
    except (douyin.Unavailable, douyin.Unreachable):
        return None


def download(url: str, out_dir: Path, max_height: int | None = None, cookies: bool = False,
             hooks: list | None = None) -> dict:
    """Tải 1 video (≤ max_height, mp4; không nói thì 720, riêng Douyin là 1080). Trả metadata + đường dẫn file.
    cookies=True: link dán tay (cookie file hoặc trình duyệt); video Bilibili tự tìm được cũng dùng cookie file nếu
    có. Link Douyin: f2 trước (motio/douyin.py), yt-dlp sau.
    hooks: hàm gọi với tiến độ tải của yt-dlp (dict có status, downloaded_bytes, total_bytes…);
    ném lỗi trong hàm thì dừng tải."""
    if localfile.parse(url):
        return localfile.source(url)
    url = platforms.normalize(platforms.expand(url))  # short links, link shapes yt-dlp does not understand
    site = platforms.identify(url)
    if haokan.find_id(url):  # no yt-dlp extractor: the page of the video carries its address
        return haokan.download(url, out_dir, max_height, hooks)
    if site and site.key == "weibo":  # a video of the Trending list carries its own mp4 address; any other link: yt-dlp
        info = weibo_feed.download(url, out_dir, hooks)
        if info:
            return info
    if site and site.key == "kuaishou":  # no yt-dlp extractor: the separate videodl tool, when it is installed
        return kuaishou.download(url, out_dir, hooks)
    if site and site.manual:  # nothing can fetch it: say so before a long generic attempt
        raise RuntimeError(platforms.hint(site))
    on_douyin = False  # Xigua's web page is a bot check now; some of its videos are also on Douyin under the same id
    if site and site.key == "ixigua" and not (cookies and _cookie_opts()):
        on_douyin = True
        info = _xigua_on_douyin(url, out_dir, max_height, hooks)
        if info:
            return info
    offline = None  # f2 không kết nối được tới Douyin: yt-dlp vẫn được thử, nhưng nếu nó cũng hỏng thì báo lỗi mạng
    if douyin.is_douyin(url):  # f2 lấy được video Douyin công khai không cần cookie; yt-dlp chỉ khi f2 không làm được
        post_id = None
        try:
            post_id = douyin.find_id(url)  # link rút gọn (câu chia sẻ của app Douyin) theo chuyển hướng một lần, ở đây
            if post_id:
                info = douyin.download(url, out_dir, max_height or douyin.DEFAULT_HEIGHT, hooks, post_id)
                if info:
                    return info
        except douyin.Unreachable as e:
            offline = e
        if post_id:  # yt-dlp chỉ hiểu dạng www.douyin.com/video/<id>
            url = f"https://www.douyin.com/video/{post_id}"
        elif offline:  # link không có mã mà không theo được (mất mạng): yt-dlp không làm gì được với nó, khỏi thử
            raise _cannot_reach_douyin() from offline
    height = max_height or 720
    out_dir.mkdir(parents=True, exist_ok=True)
    cookie = _cookie_opts() if cookies else _file_cookie_opts() if _is_bilibili(url) else {}
    opts = {**_base(),
            "format": f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/bv*[height<={height}]+ba/b[height<={height}]/b",
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
        if douyin.is_douyin(url) and "cookies" in str(e).lower():  # yt-dlp's Douyin extractor wants a browser session
            if offline:  # nó đòi cookie cả khi mất mạng; f2 không tới được Douyin thì nguyên nhân thật là mạng
                raise _cannot_reach_douyin() from e
            raise RuntimeError(tr("Douyin asks for fresh browser cookies to download this. Download the video yourself "
                                  "and add the file, or set a cookies file in Settings")) from e
        if on_douyin and _ASKS_LOGIN.search(str(e)):  # Xigua: not on Douyin either, and the page wants a session
            raise RuntimeError(tr("Xigua asks for a browser session to download this, and the video is not on Douyin "
                                  "either. Set a cookies file or a browser in Settings, or download the video "
                                  "yourself and add the file")) from e
        if site and site.key == "xiaohongshu" and "xsec_token" not in url and "No video formats" in str(e):
            # a note link without its xsec_token is not served to a guest (tested 2026-10-17)
            raise RuntimeError(tr("Xiaohongshu did not give a video for this link. Paste the full link with its "
                                  "xsec_token (copy it from the address bar), or the share link (xhslink.com)")) from e
        if site and site.cookies and _ASKS_LOGIN.search(str(e)):  # Xiaohongshu, Weibo, Xigua, Zhihu want a session
            raise RuntimeError(platforms.hint(site)) from e
        if site and site.cookies and "No video formats" in str(e):  # a post with only pictures, or one behind a login
            raise RuntimeError(tr("{site} gave no video for this link. The post may have only pictures, or the site "
                                  "wants a browser session (a cookies file or a browser in Settings)",
                                  site=site.name)) from e
        raise  # lỗi khác của yt-dlp (403, video đã xoá…) là câu trả lời thật của Douyin: giữ nguyên
    if not path.exists():
        matches = sorted(out_dir.glob(f"*_{info.get('id')}.*"))
        if not matches:
            raise FileNotFoundError(tr("yt-dlp did not create a file for {url}", url=url))
        videos = [m for m in matches if m.suffix.lower() in localfile.EXT]
        if not videos:  # a post with only pictures: yt-dlp saved the image (Weibo), not a video
            for m in matches:
                m.unlink(missing_ok=True)
            raise RuntimeError(tr("This post has no video, only pictures: {url}", url=url))
        path = videos[0]
    key = info.get("extractor_key") or ""
    return {"path": str(path), "url": info.get("webpage_url") or url, "id": info.get("id"),
            "title": info.get("title") or "", "platform": PLATFORM.get(key, key),
            "uploader": info.get("channel") or info.get("uploader") or "",
            "uploader_url": info.get("channel_url") or info.get("uploader_url") or "",
            "upload_date": info.get("upload_date") or "", "duration": info.get("duration") or 0,
            "license": info.get("license") or "", "width": info.get("width"), "height": info.get("height")}
