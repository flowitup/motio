"""Tìm và tải video nguồn bằng yt-dlp. Mỗi nguồn giữ lại nền tảng, kênh, link và giấy phép."""
from pathlib import Path

from yt_dlp import YoutubeDL

from . import config

SEARCH_PREFIX = {"youtube": "ytsearch", "bilibili": "bilisearch"}
PLATFORM = {"Youtube": "YouTube", "BiliBili": "Bilibili", "Douyin": "Douyin", "TikTok": "TikTok",
            "Twitter": "X", "Kuaishou": "Kuaishou", "Weibo": "Weibo"}

_BASE = {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 30}


def search(query: str, site: str, n: int = 6) -> list[dict]:
    prefix = SEARCH_PREFIX[site]
    opts = {**_BASE, "extract_flat": "in_playlist", "skip_download": True}
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


def download(url: str, out_dir: Path, max_height: int = 720) -> dict:
    """Tải 1 video (≤ 720p, mp4). Trả metadata + đường dẫn file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {**_BASE,
            "format": f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/bv*[height<={max_height}]+ba/"
                      f"b[height<={max_height}]/b",
            "merge_output_format": "mp4",
            "outtmpl": str(out_dir / "%(extractor_key)s_%(id)s.%(ext)s"),
            "noplaylist": True, "max_filesize": 600 * 1024 * 1024,
            "ffmpeg_location": config.FFMPEG}
    with YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
        path = Path(y.prepare_filename(info)).with_suffix(".mp4")
    if not path.exists():
        matches = sorted(out_dir.glob(f"*_{info.get('id')}.*"))
        if not matches:
            raise FileNotFoundError(f"yt-dlp không tạo file cho {url}")
        path = matches[0]
    key = info.get("extractor_key") or ""
    return {"path": str(path), "url": info.get("webpage_url") or url, "id": info.get("id"),
            "title": info.get("title") or "", "platform": PLATFORM.get(key, key),
            "uploader": info.get("channel") or info.get("uploader") or "",
            "uploader_url": info.get("channel_url") or info.get("uploader_url") or "",
            "upload_date": info.get("upload_date") or "", "duration": info.get("duration") or 0,
            "license": info.get("license") or "", "width": info.get("width"), "height": info.get("height")}
