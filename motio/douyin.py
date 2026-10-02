"""Tải video Douyin không cần đăng nhập, bằng gói f2 (Johnserf-Seed/f2, Apache-2.0).

Douyin ký mọi request (a_bogus, msToken, ttwid) nên yt-dlp hay đòi cookie trình duyệt còn mới. f2 lo phần ký đó; Motio
chỉ gọi f2 như một thư viện, không chép mã ký của nó: lên bản f2 mới là có chữ ký mới khi Douyin đổi cách ký.

`download` trả cùng dạng với `search.download`. Video không còn / riêng tư / là bài ảnh thì ném `Unavailable`; f2 hỏng,
mất mạng hay Douyin từ chối thì trả None để `search.download` quay về yt-dlp. Lỗi ném từ hook tiến độ (huỷ việc đang
tải) đi thẳng ra ngoài, không bị coi là f2 hỏng.
"""
import asyncio
import logging
import os
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from .i18n import tr

log = logging.getLogger("motio.douyin")

MAX_BYTES = 600 * 1024 * 1024  # như max_filesize của yt-dlp trong search.download
_POST_ID = re.compile(r"/(?:video|note)/(\d+)")


class Unavailable(RuntimeError):
    """Douyin trả lời được, nhưng link này không có video nào để lấy."""


def is_douyin(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ("douyin.com", "iesdouyin.com"))


def _post_id(url: str) -> str | None:
    """Mã bài trong link đầy đủ (/video/<id>, /note/<id>, ?modal_id=<id>); link rút gọn v.douyin.com thì None."""
    u = urlparse(url)
    m = _POST_ID.search(u.path)
    if m:
        return m.group(1)
    modal = (parse_qs(u.query).get("modal_id") or [""])[0]
    return modal if modal.isdigit() else None


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(1) as pool:  # đang trong vòng lặp asyncio: chạy ở luồng riêng
        return pool.submit(asyncio.run, coro).result()


def _park_f2_logger() -> None:
    """Vừa nạp, f2 tạo thư mục ./logs cạnh thư mục đang chạy và in log ra console, trừ khi logger "f2" đã có handler:
    gắn sẵn một handler rỗng để nó bỏ qua cả hai."""
    lg = logging.getLogger("f2")
    if not lg.handlers:
        lg.addHandler(logging.NullHandler())
    lg.propagate = False


def _f2():
    """f2, nạp khi cần lần đầu. Nạp cũng gọi Douyin xin một msToken, nên mất mạng thì ném lỗi ở đây."""
    _park_f2_logger()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from f2.apps.douyin.crawler import DouyinCrawler
        from f2.apps.douyin.model import PostDetail
        from f2.apps.douyin.utils import AwemeIdFetcher, ClientConfManager, TokenManager
    return DouyinCrawler, PostDetail, AwemeIdFetcher, ClientConfManager, TokenManager


async def _fetch(url: str) -> tuple[dict, dict]:
    """(trả lời của Douyin cho bài này, header f2 dùng). Một video công khai chỉ cần ttwid ẩn danh, không cần cookie."""
    crawler_cls, detail_model, id_fetcher, conf, tokens = _f2()
    post_id = _post_id(url) or await id_fetcher.get_aweme_id(url)  # link rút gọn: f2 theo chuyển hướng
    try:
        ms_token = tokens.gen_real_msToken()  # token lấy lúc nạp f2 có thể đã cũ nếu engine chạy lâu
    except Exception:
        ms_token = tokens.gen_false_msToken()
    kwargs = {"headers": conf.headers(), "proxies": conf.proxies(), "cookie": f"ttwid={tokens.gen_ttwid()}",
              "timeout": 20, "max_retries": 3}
    async with crawler_cls(kwargs) as crawler:
        raw = await crawler.fetch_post_detail(detail_model(aweme_id=post_id, msToken=ms_token))
    return raw, dict(conf.headers())


def _why(raw: dict) -> str:
    reason = str((raw.get("filter_detail") or {}).get("filter_reason") or "")
    if "delete" in reason or "not_found" in reason:
        return tr("This Douyin video was removed")
    if "self_see" in reason or "private" in reason or "friend" in reason:
        return tr("This Douyin video is private or restricted")
    return tr("Douyin did not give a video for this link ({reason})", reason=reason or "?")


def _streams(video: dict) -> list[dict]:
    """Mọi luồng mp4 của bài: kích thước cạnh ngắn, H.265 hay không, bitrate, danh sách link."""
    out = []
    entries = [(b.get("play_addr"), bool(b.get("is_h265")), b.get("bit_rate")) for b in video.get("bit_rate") or []]
    entries.append((video.get("play_addr_h264") or video.get("play_addr"), bool(video.get("is_h265")), None))
    for addr, h265, bitrate in entries:
        addr = addr or {}
        urls = [u for u in addr.get("url_list") or [] if str(u).startswith("http")]
        w, h = int(addr.get("width") or 0), int(addr.get("height") or 0)
        if urls:
            out.append({"urls": urls, "width": w, "height": h, "short": min(w, h) if w and h else 0, "h265": h265,
                        "bitrate": int(bitrate or 0)})
    return out


def pick_stream(video: dict, max_height: int) -> dict | None:
    """Luồng nên lấy: H.264 (xem được ở mọi nơi, H.265 thì không), cạnh ngắn lớn nhất không quá max_height — không có
    thì cái nhỏ nhất vượt qua — rồi bitrate cao nhất."""
    def rank(s: dict):
        fits = s["short"] <= max_height
        return not s["h265"], fits, s["short"] if fits else -s["short"], s["bitrate"]
    streams = _streams(video)
    return max(streams, key=rank) if streams else None


def _tell(hooks: list | None, status: str, done: int, total: int) -> None:
    for hook in hooks or []:  # lỗi ném trong hook là cách dừng tải, giống yt-dlp
        hook({"status": status, "downloaded_bytes": done, "total_bytes": total})


def _client(headers: dict) -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=30, headers=headers)


def _save(urls: list[str], dest: Path, headers: dict, hooks: list | None) -> bool:
    """Tải về dest.part rồi đổi tên, thử lần lượt các link CDN. False khi link nào cũng lỗi."""
    part = dest.with_name(dest.name + ".part")
    for u in urls:
        try:
            with _client(headers) as client, client.stream("GET", u) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                if total > MAX_BYTES:
                    raise Unavailable(tr("This video is larger than {mb} MB", mb=MAX_BYTES // 1024 // 1024))
                got = 0
                with part.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 17):
                        got += len(chunk)
                        if got > MAX_BYTES:
                            raise Unavailable(tr("This video is larger than {mb} MB", mb=MAX_BYTES // 1024 // 1024))
                        f.write(chunk)
                        _tell(hooks, "downloading", got, total)
            os.replace(part, dest)
            _tell(hooks, "finished", got, got)
            return True
        except (httpx.HTTPError, OSError) as e:
            log.warning("Douyin stream %s failed: %s", urlparse(u).hostname, e)
        finally:
            part.unlink(missing_ok=True)
    return False


def download(url: str, out_dir: Path, max_height: int = 720, hooks: list | None = None) -> dict | None:
    """Tải 1 video Douyin (cạnh ngắn ≤ max_height nếu có, mp4) vào out_dir/Douyin_<id>.mp4. Cùng kiểu trả về với
    search.download; None khi f2 không làm được (người gọi thử yt-dlp)."""
    try:
        raw, headers = _run(_fetch(url))
    except Exception as e:
        log.warning("f2 could not read %s: %s", url, e)
        return None
    detail = raw.get("aweme_detail")
    if not detail:
        raise Unavailable(_why(raw))
    video = detail.get("video") or {}
    stream = None if detail.get("images") else pick_stream(video, max_height)
    if not stream:
        raise Unavailable(tr("This Douyin post is photos, not a video"))
    post_id = str(detail.get("aweme_id") or _post_id(url) or "")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"Douyin_{post_id}.mp4"
    if not (path.is_file() and path.stat().st_size) and not _save(
            stream["urls"], path, {"Referer": headers.get("Referer", "https://www.douyin.com/"),
                                   "User-Agent": headers.get("User-Agent", "")}, hooks):
        return None
    author = detail.get("author") or {}
    created = int(detail.get("create_time") or 0)
    sec_uid = author.get("sec_uid") or ""
    return {"path": str(path), "url": f"https://www.douyin.com/video/{post_id}", "id": post_id,
            "title": detail.get("desc") or "", "platform": "Douyin", "uploader": author.get("nickname") or "",
            "uploader_url": f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "",
            "upload_date": time.strftime("%Y%m%d", time.gmtime(created)) if created else "",
            "duration": round((video.get("duration") or detail.get("duration") or 0) / 1000, 3), "license": "",
            "width": stream["width"] or None, "height": stream["height"] or None}
