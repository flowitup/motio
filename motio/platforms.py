"""Chinese video sites besides Bilibili and Douyin that a pasted link can come from.

What was checked from a cloud sandbox on 2026-10-16 (a person's own Mac or PC may fare better or worse):
- Xiaohongshu: yt-dlp's `XiaoHongShu` extractor read a public note without a login; many notes want a logged-in session.
- Weibo: yt-dlp reads `m.weibo.cn/detail/<id>`, but not the `weibo.com/2/detail/<id>` shape the site shows now.
- Xigua: yt-dlp asks for cookies ("not necessarily logged in"); a bare `ttwid` guest cookie was not enough.
- Haokan: yt-dlp has no extractor; the mobile page carries the video address (`haokan.py`).
- Pear Video, AcFun: yt-dlp works without a login.
- Zhihu: yt-dlp got a 403 without cookies.
- Kuaishou: no yt-dlp extractor, and its web answers a risk-control page to a script; the video has to be added by hand.
`normalize` fixes the link shapes yt-dlp does not understand, `expand` follows a short link once. Nothing here removes a
watermark or tries to hide where a video came from.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .i18n import tr

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    hosts: tuple[str, ...]
    cookies: bool = False  # the site may ask for a browser session (YTDLP_COOKIES_FILE / YTDLP_COOKIES_FROM_BROWSER)
    manual: bool = False  # nothing can download it: the video has to be added as a file


PLATFORMS = (
    Platform("xiaohongshu", "Xiaohongshu", ("xiaohongshu.com", "xhslink.com"), cookies=True),
    Platform("weibo", "Weibo", ("weibo.com", "weibo.cn"), cookies=True),
    Platform("ixigua", "Xigua", ("ixigua.com",), cookies=True),
    Platform("kuaishou", "Kuaishou", ("kuaishou.com", "chenzhongtech.com", "gifshow.com", "kwai.com"), manual=True),
    Platform("haokan", "Haokan", ("haokan.baidu.com",)),
    Platform("pearvideo", "Pear Video", ("pearvideo.com",)),
    Platform("acfun", "AcFun", ("acfun.cn",)),
    Platform("zhihu", "Zhihu", ("zhihu.com",), cookies=True),
)
BY_KEY = {p.key: p for p in PLATFORMS}
# yt-dlp's extractor_key → name shown on a source (search.PLATFORM)
EXTRACTORS = {"XiaoHongShu": "Xiaohongshu", "Weibo": "Weibo", "WeiboVideo": "Weibo", "Ixigua": "Xigua",
              "PearVideo": "Pear Video", "AcFunVideo": "AcFun", "Zhihu": "Zhihu", "BaiduVideo": "Baidu Video"}

_SHORT_HOSTS = ("xhslink.com",)
_MAX_HOPS = 4
TIMEOUT = 15.0
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def identify(url: str) -> Platform | None:
    host = _host(url)
    return next((p for p in PLATFORMS if any(host == h or host.endswith("." + h) for h in p.hosts)), None)


def normalize(url: str) -> str:
    """The link shape yt-dlp (or `haokan.py`) understands; any other link comes back unchanged."""
    p = identify(url)
    u = urlparse(url)
    if p is None or u.scheme not in ("http", "https"):
        return url
    if p.key == "weibo" and (m := re.fullmatch(r"/(?:\d+/)?detail/([A-Za-z0-9]+)/?", u.path)) \
            and _host(url) in ("weibo.com", "www.weibo.com", "m.weibo.cn"):
        return f"https://m.weibo.cn/detail/{m[1]}"  # weibo.com/2/detail/<id> is not matched by yt-dlp
    if p.key == "ixigua" and (m := re.fullmatch(r"/(?:video/)?(\d+)/?", u.path)):
        return f"https://www.ixigua.com/{m[1]}/"  # yt-dlp's pattern drops the last digit of an id with nothing after it
    if p.key == "xiaohongshu" and (m := re.fullmatch(r"/user/profile/[0-9a-f]+/([0-9a-f]{24})/?", u.path)):
        return f"https://www.xiaohongshu.com/explore/{m[1]}" + (f"?{u.query}" if u.query else "")
    return url


def expand(url: str) -> str:
    """A short link (xhslink.com) followed to the page it points to, once and only through https to a known site.
    Anything else, and any failure, gives the link back unchanged."""
    if _host(url) not in _SHORT_HOSTS:
        return url
    cur = url
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=False,
                          headers={"User-Agent": UA}) as client:
            for _ in range(_MAX_HOPS):
                r = client.get(cur)
                nxt = r.headers.get("location")
                if not r.is_redirect or not nxt:
                    break
                cur = str(httpx.URL(cur).join(nxt))
                if urlparse(cur).scheme != "https" or identify(cur) is None:
                    return url
                if _host(cur) not in _SHORT_HOSTS:
                    return normalize(cur)
    except httpx.HTTPError:
        pass
    return url


def hint(p: Platform) -> str:
    """Why a download from this site failed and what to do about it (shown instead of yt-dlp's own text)."""
    if p.manual:
        return tr("{site} cannot be downloaded by Motio (it blocks scripts and yt-dlp has no support). Download the "
                  "video yourself and add the file", site=p.name)
    return tr("{site} asks for a browser session to download this. Set a cookies file or a browser in Settings, or "
              "download the video yourself and add the file", site=p.name)
