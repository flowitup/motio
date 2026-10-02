"""Tải video Douyin không cần đăng nhập, bằng gói f2 (Johnserf-Seed/f2, Apache-2.0).

Douyin ký mọi request (a_bogus, msToken, ttwid) nên yt-dlp hay đòi cookie trình duyệt còn mới. f2 lo phần ký đó; Motio
chỉ gọi f2 như một thư viện, không chép mã ký của nó: lên bản f2 mới là có chữ ký mới khi Douyin đổi cách ký.

`download` trả cùng dạng với `search.download`. Douyin nói rõ video không còn / riêng tư / là bài ảnh thì ném
`Unavailable`; f2 hỏng, mất mạng, Douyin từ chối hoặc trả lời không rõ lý do thì trả None để `search.download` quay về
yt-dlp. Lỗi ném từ hook tiến độ (huỷ việc đang tải) đi thẳng ra ngoài, không bị coi là f2 hỏng.

f2 không kiểm tra chứng chỉ TLS của chính nó, nên link tải trong trả lời của Douyin chỉ được dùng khi là https tới địa
chỉ công khai (kể cả sau chuyển hướng). Motio không dùng browser_cookie3 và execjs của f2 (đọc cookie trình duyệt, chạy
JavaScript cho livestream): f2 chỉ cần tên module để nạp, nên cấp module rỗng thay vì cài hai gói đó.
"""
import asyncio
import ipaddress
import logging
import os
import re
import socket
import sys
import threading
import time
import types
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from .i18n import tr

log = logging.getLogger("motio.douyin")

MAX_BYTES = 600 * 1024 * 1024  # như max_filesize của yt-dlp trong search.download
DEFAULT_HEIGHT = 1080  # trần cạnh ngắn khi người gọi không nói: lấy bản lớn nhất Douyin có, không quá 1080
TRIES = 3  # lần hỏi Douyin cho mỗi video: thỉnh thoảng 403, hoặc danh sách cỡ video thiếu bản 720
HOSTS = ("douyin.com", "iesdouyin.com")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
_POST_ID = re.compile(r"/(?:video|note|slides)/(\d+)")
_ID_PARAMS = ("modal_id", "vid")
_NOT_USED = ("browser_cookie3", "execjs")
_F2_RETRY_AFTER = 120  # giây: nạp f2 hỏng thì chưa thử nạp lại ngay, mỗi lần nạp hỏng mất cả chục giây chờ mạng

_f2_lock = threading.Lock()
_f2_loaded: tuple | None = None
_f2_failed: tuple[float, Exception] | None = None


class Unavailable(RuntimeError):
    """Douyin trả lời được, nhưng link này không có video nào để lấy."""


def is_douyin(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in HOSTS)


def _post_id(url: str) -> str | None:
    """Mã bài trong link đầy đủ (/video|note|slides/<id>, ?modal_id=<id>, ?vid=<id>); link rút gọn thì None."""
    u = urlparse(url)
    m = _POST_ID.search(u.path)
    if m:
        return m.group(1)
    query = parse_qs(u.query)
    for key in _ID_PARAMS:
        value = (query.get(key) or [""])[0]
        if value.isdigit():
            return value
    return None


def _resolve_host(host: str) -> list[str]:
    return [i[4][0] for i in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


def _only_public_https(request: httpx.Request) -> None:
    """Chạy trước mỗi request, kể cả các chặng chuyển hướng: chỉ https tới địa chỉ công khai."""
    host = request.url.host
    if request.url.scheme != "https" or not host:
        raise OSError(f"not an https link: {request.url.scheme}://{host}")
    addresses = _resolve_host(host)
    if not addresses or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise OSError(f"{host} is not a public address")


def _client(headers: dict, *, follow: bool = True, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(follow_redirects=follow, timeout=30, headers=headers, transport=transport,
                        event_hooks={"request": [_only_public_https]})


def _resolve_id(url: str) -> str | None:
    """Mã bài của link. Link rút gọn (v.douyin.com/xxx) thì theo chuyển hướng từng chặng, chỉ trong host của Douyin."""
    with _client({"User-Agent": UA}, follow=False) as client:
        for _ in range(6):
            post_id = _post_id(url)
            if post_id or not is_douyin(url):
                return post_id
            with client.stream("GET", url) as r:
                if not r.is_redirect:
                    return None
                url = urljoin(url, r.headers.get("location", ""))
    return None


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
    """f2, nạp một lần (an toàn khi nhiều luồng cùng tải). Nạp cũng gọi Douyin xin một msToken, nên mất mạng thì ném
    lỗi; nạp hỏng thì mấy phút sau mới thử lại, để mỗi video không phải chờ mạng cả chục giây."""
    global _f2_loaded, _f2_failed
    with _f2_lock:
        if _f2_loaded:
            return _f2_loaded
        if _f2_failed and time.monotonic() - _f2_failed[0] < _F2_RETRY_AFTER:
            raise RuntimeError(f"f2 could not be loaded a moment ago: {_f2_failed[1]}")
        _park_f2_logger()
        stubs = {name: types.ModuleType(name) for name in _NOT_USED if name not in sys.modules}
        sys.modules.update(stubs)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from f2.apps.douyin.crawler import DouyinCrawler
                from f2.apps.douyin.model import PostDetail
                from f2.apps.douyin.utils import ClientConfManager, TokenManager
        except Exception as e:
            _f2_failed = (time.monotonic(), e)
            raise
        finally:
            for name, stub in stubs.items():  # f2 đã giữ tham chiếu, khỏi để module rỗng trong sys.modules
                if sys.modules.get(name) is stub:
                    del sys.modules[name]
        _f2_loaded = (DouyinCrawler, PostDetail, ClientConfManager, TokenManager)
        return _f2_loaded


async def _fetch(post_id: str) -> tuple[dict, dict]:
    """(trả lời của Douyin cho bài này, header f2 dùng). Một video công khai chỉ cần ttwid ẩn danh, không cần cookie."""
    crawler_cls, detail_model, conf, tokens = _f2()
    try:
        ms_token = tokens.gen_real_msToken()  # token lấy lúc nạp f2 có thể đã cũ nếu engine chạy lâu
    except Exception:
        ms_token = tokens.gen_false_msToken()
    kwargs = {"headers": conf.headers(), "proxies": conf.proxies(), "cookie": f"ttwid={tokens.gen_ttwid()}",
              "timeout": 10, "max_retries": 2}
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
    h264 = video.get("play_addr_h264")  # cờ is_h265 của bài nói về play_addr, không phải về bản H.264 này
    entries.append((h264 or video.get("play_addr"), False if h264 else bool(video.get("is_h265")), None))
    for addr, h265, bitrate in entries:
        addr = addr or {}
        urls = [u for u in addr.get("url_list") or [] if str(u).startswith("http")]
        w, h = int(addr.get("width") or 0), int(addr.get("height") or 0)
        if urls:
            out.append({"urls": urls, "width": w, "height": h, "short": min(w, h) if w and h else 0, "h265": h265,
                        "bitrate": int(bitrate or 0)})
    return out


def pick_stream(video: dict, max_height: int) -> dict | None:
    """Luồng nên lấy: H.264 (xem được ở mọi nơi, H.265 thì không) có cạnh ngắn lớn nhất không quá max_height; không có
    cái nào nhỏ đến vậy thì cái nhỏ nhất. Cùng cỡ thì bitrate cao nhất."""
    streams = _streams(video)
    pool = [s for s in streams if not s["h265"]] or streams
    fits = [s for s in pool if s["short"] <= max_height]
    if fits:
        return max(fits, key=lambda s: (s["short"], s["bitrate"]))
    return min(pool, key=lambda s: (s["short"], -s["bitrate"])) if pool else None


def _enough(video: dict, stream: dict, max_height: int) -> bool:
    """Bản này đã đủ tốt chưa? Douyin thỉnh thoảng trả danh sách thiếu bản H.264 720 dù video gốc có cỡ lớn hơn
    (bản H.265 vẫn có): khi đó đáng hỏi lại, vì lần sau thường đủ. Nguồn vốn nhỏ thì không có gì để hỏi lại."""
    floor = min(max_height, 720)
    return not stream["h265"] and (stream["short"] >= floor or not any(s["short"] >= floor for s in _streams(video)))


def _pause() -> None:
    time.sleep(0.8)


def _ask(post_id: str, max_height: int) -> tuple[dict, dict, dict | None] | None:
    """Hỏi Douyin tối đa TRIES lần, dừng khi có bản đủ tốt. Trả (trả lời, header, luồng) của lần tốt nhất; trả lời có
    lý do rõ (video không còn, bài ảnh) thì trả ngay, không hỏi lại. None khi lần nào cũng hỏng."""
    best: tuple[dict, dict, dict] | None = None
    for attempt in range(TRIES):
        if attempt:
            _pause()
        try:
            raw, headers = _run(_fetch(post_id))
        except Exception as e:
            log.warning("f2 could not read Douyin post %s (try %d/%d): %s", post_id, attempt + 1, TRIES, e)
            if type(e).__name__ == "APIRetryExhaustedError":  # f2 đã tự thử lại, hỏi tiếp chỉ kéo dài thêm
                break
            continue
        detail = raw.get("aweme_detail") if isinstance(raw, dict) else None
        if not detail:
            if isinstance(raw, dict) and (raw.get("filter_detail") or {}).get("filter_reason"):
                return raw, headers, None
            log.warning("Douyin gave neither a post nor a reason for %s: %.200s", post_id, raw)
            continue
        video = detail.get("video") or {}
        stream = pick_stream(video, max_height)
        if detail.get("images"):
            return raw, headers, None
        if not stream:
            continue
        if best is None or (not stream["h265"], stream["short"]) > (not best[2]["h265"], best[2]["short"]):
            best = (raw, headers, stream)
        if _enough(video, stream, max_height):
            break
    return best


def _tell(hooks: list | None, status: str, done: int, total: int) -> None:
    for hook in hooks or []:  # lỗi ném trong hook là cách dừng tải, giống yt-dlp
        hook({"status": status, "downloaded_bytes": done, "total_bytes": total})


def _too_big() -> Unavailable:
    return Unavailable(tr("This video is larger than {mb} MB", mb=MAX_BYTES // 1024 // 1024))


def _save(urls: list[str], dest: Path, headers: dict, hooks: list | None) -> bool:
    """Tải về dest.part rồi đổi tên, thử lần lượt các link CDN. False khi link nào cũng lỗi."""
    part = dest.with_name(dest.name + ".part")
    for u in urls:
        try:
            with _client(headers) as client, client.stream("GET", u) as r:
                r.raise_for_status()
                kind = r.headers.get("content-type", "").lower()
                if kind.startswith(("text/", "application/json")):  # trang báo lỗi chứ không phải video
                    raise OSError(f"not a video ({kind})")
                total = int(r.headers.get("content-length") or 0)
                if total > MAX_BYTES:
                    raise _too_big()
                got = 0
                with part.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 17):
                        got += len(chunk)
                        if got > MAX_BYTES:
                            raise _too_big()
                        f.write(chunk)
                        _tell(hooks, "downloading", got, total)
                if not got:  # CDN thỉnh thoảng trả 200 mà không có gì: thử link kế
                    raise OSError("empty body")
            os.replace(part, dest)
            _tell(hooks, "finished", got, got)
            return True
        except (httpx.HTTPError, OSError) as e:
            log.warning("Douyin stream %s failed: %s", urlparse(u).hostname, e)
        finally:
            part.unlink(missing_ok=True)
    return False


def download(url: str, out_dir: Path, max_height: int = DEFAULT_HEIGHT, hooks: list | None = None) -> dict | None:
    """Tải 1 video Douyin (H.264, cạnh ngắn lớn nhất không quá max_height) vào out_dir/Douyin_<id>.mp4. Cùng kiểu trả
    về với search.download; None khi f2 không làm được (người gọi thử yt-dlp)."""
    try:
        post_id = _resolve_id(url)
    except Exception as e:
        log.warning("could not find the Douyin post id of %s: %s", url, e)
        return None
    answer = _ask(post_id, max_height) if post_id else None
    if not answer:
        return None
    raw, headers, stream = answer
    detail = raw.get("aweme_detail")
    if not detail:
        raise Unavailable(_why(raw))
    if not stream:
        raise Unavailable(tr("This Douyin post is photos, not a video"))
    post_id = str(detail.get("aweme_id") or post_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"Douyin_{post_id}.mp4"
    if not (path.is_file() and path.stat().st_size) and not _save(
            stream["urls"], path, {"Referer": headers.get("Referer", "https://www.douyin.com/"),
                                   "User-Agent": headers.get("User-Agent", UA)}, hooks):
        return None
    video = detail.get("video") or {}
    author = detail.get("author") or {}
    created = int(detail.get("create_time") or 0)
    sec_uid = author.get("sec_uid") or ""
    return {"path": str(path), "url": f"https://www.douyin.com/video/{post_id}", "id": post_id,
            "title": detail.get("desc") or "", "platform": "Douyin", "uploader": author.get("nickname") or "",
            "uploader_url": f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "",
            "upload_date": time.strftime("%Y%m%d", time.gmtime(created)) if created else "",
            "duration": round((video.get("duration") or detail.get("duration") or 0) / 1000, 3), "license": "",
            "width": stream["width"] or None, "height": stream["height"] or None}
