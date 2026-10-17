"""Chinese video sites besides Bilibili and Douyin (motio/platforms.py): link shapes, short links, hints."""
import httpx
import pytest

from motio import platforms


@pytest.mark.parametrize("url,key", [
    ("https://www.xiaohongshu.com/explore/69cc9795000000001b0203ab", "xiaohongshu"),
    ("http://xhslink.com/a/AbC123", "xiaohongshu"),
    ("https://m.weibo.cn/detail/5354603969514346", "weibo"),
    ("https://weibo.com/2/detail/5354603969514346", "weibo"),
    ("https://www.ixigua.com/6863073327775547912", "ixigua"),
    ("https://v.kuaishou.com/AbCdEf", "kuaishou"),
    ("https://haokan.baidu.com/v?vid=9182896717567225983", "haokan"),
    ("https://www.zhihu.com/zvideo/1387089980523728897", "zhihu"),
])
def test_identify(url, key):
    assert platforms.identify(url).key == key


@pytest.mark.parametrize("url", ["https://www.youtube.com/watch?v=a", "https://www.bilibili.com/video/BV1",
                                 "https://www.douyin.com/video/1", "https://notxiaohongshu.com/x", "not a link"])
def test_other_sites_are_not_recognised(url):
    assert platforms.identify(url) is None
    assert platforms.normalize(url) == url


@pytest.mark.parametrize("url,expected", [
    # yt-dlp reads m.weibo.cn/detail/<id> but takes "detail" for the id in weibo.com/2/detail/<id>
    ("https://weibo.com/2/detail/5354603969514346", "https://m.weibo.cn/detail/5354603969514346"),
    ("https://weibo.com/detail/IyAbC9xYz", "https://m.weibo.cn/detail/IyAbC9xYz"),
    ("https://m.weibo.cn/detail/5354603969514346", "https://m.weibo.cn/detail/5354603969514346"),
    ("https://weibo.com/1642592432/IyAbC9xYz", "https://weibo.com/1642592432/IyAbC9xYz"),  # yt-dlp's own shape
    ("https://weibo.com/u/1642592432", "https://weibo.com/u/1642592432"),  # an account, not a post
    # yt-dlp's Xigua pattern needs a character after the id or it drops the last digit
    ("https://www.ixigua.com/6863073327775547912", "https://www.ixigua.com/6863073327775547912/"),
    ("https://m.ixigua.com/video/6863073327775547912", "https://www.ixigua.com/6863073327775547912/"),
    ("https://www.ixigua.com/6863073327775547912?logTag=x", "https://www.ixigua.com/6863073327775547912/"),
    ("https://www.xiaohongshu.com/user/profile/5ff0e6410000000001003b0a/69cc9795000000001b0203ab?xsec_token=T",
     "https://www.xiaohongshu.com/explore/69cc9795000000001b0203ab?xsec_token=T"),
    ("https://www.xiaohongshu.com/explore/69cc9795000000001b0203ab", "https://www.xiaohongshu.com/explore/69cc9795000000001b0203ab"),
])
def test_normalize(url, expected):
    assert platforms.normalize(url) == expected


def _redirects(monkeypatch, table: dict[str, str]):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        nxt = table.get(str(req.url))
        return httpx.Response(302, headers={"location": nxt}) if nxt else httpx.Response(200, text="page")

    monkeypatch.setattr(platforms, "_transport", httpx.MockTransport(handler))
    return calls


def test_a_short_xiaohongshu_link_is_followed_to_the_note(monkeypatch):
    calls = _redirects(monkeypatch, {
        "http://xhslink.com/a/AbC123": "https://www.xiaohongshu.com/discovery/item/69cc9795000000001b0203ab?xsec_token=T"})
    assert platforms.expand("http://xhslink.com/a/AbC123") == (
        "https://www.xiaohongshu.com/discovery/item/69cc9795000000001b0203ab?xsec_token=T")
    assert calls == ["http://xhslink.com/a/AbC123"]


def test_other_links_are_never_fetched_to_expand_them(monkeypatch):
    calls = _redirects(monkeypatch, {})
    for url in ("https://www.xiaohongshu.com/explore/69cc9795000000001b0203ab", "https://www.youtube.com/watch?v=a",
                "http://127.0.0.1/secret"):
        assert platforms.expand(url) == url
    assert calls == []


def test_a_short_link_leading_off_the_site_or_to_http_is_not_followed(monkeypatch):
    _redirects(monkeypatch, {"http://xhslink.com/a/off": "https://example.com/x",
                             "http://xhslink.com/a/plain": "http://www.xiaohongshu.com/explore/ab12"})
    assert platforms.expand("http://xhslink.com/a/off") == "http://xhslink.com/a/off"
    assert platforms.expand("http://xhslink.com/a/plain") == "http://xhslink.com/a/plain"


def test_a_short_link_that_cannot_be_reached_comes_back_unchanged(monkeypatch):
    def down(req):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(platforms, "_transport", httpx.MockTransport(down))
    assert platforms.expand("http://xhslink.com/a/AbC123") == "http://xhslink.com/a/AbC123"


def test_hints_say_what_to_do():
    assert "add the file" in platforms.hint(platforms.BY_KEY["kuaishou"])
    assert "cookies" in platforms.hint(platforms.BY_KEY["xiaohongshu"])
    assert platforms.BY_KEY["kuaishou"].manual and not platforms.BY_KEY["haokan"].cookies
