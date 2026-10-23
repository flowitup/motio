"""Bilibili videos through the site's own API (motio/bilibili_dl.py): links, guest request, download, refusals."""
import httpx
import pytest

from motio import bilibili_dl, douyin, trending

BV = "BV1UaJ96UEmt"
CDN = "https://upos-hz-mirrorakam.akamaized.net/upgcxcode/16/42787211631/a.mp4?auth=1"


def _view(**kw) -> dict:
    base = {"bvid": BV, "aid": 170001, "cid": 11, "title": "老婆动起来了", "duration": 19, "pubdate": 1_790_000_000,
            "owner": {"mid": 77, "name": "UP主"}, "dimension": {"width": 1280, "height": 720},
            "pages": [{"cid": 11, "page": 1, "part": "一", "duration": 19,
                       "dimension": {"width": 1280, "height": 720}}],
            "rights": {"pay": 0, "movie": 0, "arc_pay": 0, "ugc_pay": 0}}
    return {**base, **kw}


@pytest.fixture
def bili(monkeypatch):
    """Bilibili and its CDN behind httpx.MockTransport. `s`: view / playurl bodies, the mp4, calls, failures."""
    s = {"view": _view(), "play": {"quality": 64, "durl": [{"url": CDN, "size": 5000}]}, "mp4": b"x" * 5000,
         "type": "video/mp4", "resets": 0, "calls": [], "short": "https://www.bilibili.com/video/" + BV + "/"}

    def handler(req: httpx.Request) -> httpx.Response:
        s["calls"].append(req)
        path = req.url.path
        if req.url.host == "b23.tv":
            return httpx.Response(302, headers={"location": s["short"]})
        if path == "/x/frontend/finger/spi":
            return httpx.Response(200, json={"code": 0, "data": {"b_3": "a", "b_4": "b"}})
        if path == "/x/web-interface/nav":
            img = "https://i0.hdslb.com/bfs/wbi/"
            return httpx.Response(200, json={"code": -101, "data": {"wbi_img": {
                "img_url": img + "7cd084941338484aae1ad9425b84077c.png",
                "sub_url": img + "4932caff0ff746eab6f01bf08b70ac45.png"}}})
        if path == "/x/web-interface/wbi/view":
            return httpx.Response(200, json={"code": 0, "data": s["view"]})
        if path == "/x/player/wbi/playurl":
            return httpx.Response(200, json={"code": 0, "data": s["play"]})
        if req.url.host == "upos-hz-mirrorakam.akamaized.net":
            if s["resets"]:
                s["resets"] -= 1
                raise httpx.ReadError("Connection reset by peer")
            return httpx.Response(200, content=s["mp4"], headers={"content-type": s["type"]})
        return httpx.Response(404, json={"code": -404})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(trending, "_transport", transport)
    monkeypatch.setattr(bilibili_dl, "_transport", transport)
    monkeypatch.setattr(douyin, "_resolve_host", lambda host: ["93.184.216.34"])
    trending._wbi_cache.update(key=None, at=0.0)
    return s


def _query(req: httpx.Request) -> dict:
    return dict(req.url.params)


@pytest.mark.parametrize("url,ref,part", [
    (f"https://www.bilibili.com/video/{BV}", {"bvid": BV}, 1),
    (f"https://www.bilibili.com/video/{BV}/?spm_id_from=333.1007&p=3", {"bvid": BV}, 3),
    (f"https://m.bilibili.com/video/{BV}?p=2", {"bvid": BV}, 2),
    ("http://www.bilibili.com/video/av1756033262", {"aid": 1756033262}, 1),
    (f"https://www.bilibili.com/video/{BV}?p=0", {"bvid": BV}, 1),
])
def test_find_ref(url, ref, part):
    assert bilibili_dl.find_ref(url) == (ref, part)


@pytest.mark.parametrize("url", ["https://www.bilibili.com/bangumi/play/ep12345", "https://live.bilibili.com/123",
                                 "https://space.bilibili.com/946974", f"https://example.com/video/{BV}",
                                 "https://www.bilibili.com/video/not-an-id"])
def test_other_links_are_left_to_yt_dlp(url):
    with pytest.raises(bilibili_dl.NotSupported):
        bilibili_dl.find_ref(url)


def test_a_short_link_is_followed_once(bili):
    assert bilibili_dl.find_ref("https://b23.tv/AbCdEf") == ({"bvid": BV}, 1)
    assert [str(c.url) for c in bili["calls"]] == ["https://b23.tv/AbCdEf"]


def test_a_short_link_that_leaves_bilibili_is_not_followed(bili):
    bili["short"] = "https://example.com/video/" + BV
    with pytest.raises(bilibili_dl.NotSupported):
        bilibili_dl.find_ref("https://b23.tv/AbCdEf")


def test_download_saves_the_mp4_and_describes_it(bili, tmp_path):
    seen = []
    info = bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path, 720, [seen.append])
    name = "BiliBili_1UaJ96UEmt.mp4"  # what yt-dlp would call it
    assert (tmp_path / name).read_bytes() == b"x" * 5000 and not list(tmp_path.glob("*.part"))
    assert info == {"path": str(tmp_path / name), "url": f"https://www.bilibili.com/video/{BV}", "id": "1UaJ96UEmt",
                    "title": "老婆动起来了", "platform": "Bilibili", "uploader": "UP主",
                    "uploader_url": "https://space.bilibili.com/77", "upload_date": "20260921", "duration": 19,
                    "license": "", "width": 1280, "height": 720}
    assert seen[-1]["status"] == "finished" and seen[-1]["downloaded_bytes"] == 5000
    view = next(c for c in bili["calls"] if c.url.path.endswith("/wbi/view"))
    play = next(c for c in bili["calls"] if c.url.path.endswith("/wbi/playurl"))
    assert _query(view)["bvid"] == BV and "w_rid" in _query(view) and "wts" in _query(view)  # signed as a guest
    q = _query(play)
    assert (q["cid"], q["qn"], q["fnval"], q["platform"]) == ("11", "64", "0", "html5") and "w_rid" in q
    cdn = bili["calls"][-1]
    assert str(cdn.url) == CDN and cdn.headers["referer"] == "https://www.bilibili.com/"
    n = len(bili["calls"])
    bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path, 720)  # already there: not fetched again
    assert len(bili["calls"]) > n and not any(c.url.host.endswith("akamaized.net") for c in bili["calls"][n:])


def test_the_picture_limit_picks_the_quality(bili, tmp_path):
    bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path, 480)
    assert _query(next(c for c in bili["calls"] if c.url.path.endswith("/wbi/playurl")))["qn"] == "32"


def test_an_old_av_link_is_read_by_its_number_and_saved_under_the_bv_name(bili, tmp_path):
    info = bilibili_dl.download("http://www.bilibili.com/video/av170001", tmp_path)
    view = next(c for c in bili["calls"] if c.url.path.endswith("/wbi/view"))
    assert _query(view)["aid"] == "170001" and "bvid" not in _query(view)
    assert info["id"] == "1UaJ96UEmt" and (tmp_path / "BiliBili_1UaJ96UEmt.mp4").is_file()


def test_a_later_part_uses_its_own_cid(bili, tmp_path):
    bili["view"] = _view(pages=[{"cid": 11, "page": 1, "part": "一", "duration": 19},
                                {"cid": 22, "page": 2, "part": "二", "duration": 31}])
    info = bilibili_dl.download(f"https://www.bilibili.com/video/{BV}?p=2", tmp_path)
    assert _query(next(c for c in bili["calls"] if c.url.path.endswith("/wbi/playurl")))["cid"] == "22"
    assert (tmp_path / "BiliBili_1UaJ96UEmt_p2.mp4").is_file()
    assert info["id"] == "1UaJ96UEmt_p2" and info["duration"] == 31 and info["title"].endswith("· 二")
    with pytest.raises(bilibili_dl.Unavailable, match="no part 3"):
        bilibili_dl.download(f"https://www.bilibili.com/video/{BV}?p=3", tmp_path)


@pytest.mark.parametrize("rights", [{"pay": 1}, {"arc_pay": 1}, {"ugc_pay": 1}, {"movie": 1}])
def test_a_paid_video_is_refused_before_any_download(bili, tmp_path, rights):
    bili["view"] = _view(rights=rights)
    with pytest.raises(bilibili_dl.Unavailable, match="guest"):
        bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path)
    assert not any(c.url.path.endswith("/wbi/playurl") for c in bili["calls"]) and list(tmp_path.iterdir()) == []


def test_a_film_or_series_is_refused(bili, tmp_path):
    bili["view"] = _view(is_ogv=True)
    with pytest.raises(bilibili_dl.Unavailable, match="guest"):
        bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path)


@pytest.mark.parametrize("play", [{"durl": []}, {"durl": [{"url": CDN}, {"url": CDN}]},
                                  {"durl": [{"url": "http://example.com/a.mp4"}]}, {"dash": {}}])
def test_an_answer_without_one_https_mp4_is_refused(bili, tmp_path, play):
    bili["play"] = play
    with pytest.raises(bilibili_dl.Unavailable, match="address"):
        bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_reset_connection_is_tried_again(bili, tmp_path):
    bili["resets"] = 2
    assert bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path)["id"] == "1UaJ96UEmt"


def test_a_connection_that_keeps_failing_says_so(bili, tmp_path):
    bili["resets"] = 99
    with pytest.raises(RuntimeError, match="Could not download from Bilibili"):
        bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_page_instead_of_a_video_is_refused_and_leaves_no_file(bili, tmp_path):
    bili["type"] = "text/html"
    with pytest.raises(bilibili_dl.Unavailable, match="not a video"):
        bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_stream_address_on_a_private_network_is_refused(bili, tmp_path, monkeypatch):
    monkeypatch.setattr(douyin, "_resolve_host", lambda host: ["10.0.0.5"] if "akamaized" in host else ["1.1.1.1"])
    with pytest.raises(RuntimeError, match="Could not download from Bilibili"):
        bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_blocked_request_is_reported(bili, tmp_path, monkeypatch):
    monkeypatch.setattr(trending, "_transport", httpx.MockTransport(lambda req: httpx.Response(412, text="blocked")))
    trending._wbi_cache.update(key=None, at=0.0)
    with pytest.raises(RuntimeError, match="Bilibili"):
        bilibili_dl.download(f"https://www.bilibili.com/video/{BV}", tmp_path)
