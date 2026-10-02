"""Tải video Douyin bằng f2 (motio/douyin.py): chọn luồng, hỏi lại, siêu dữ liệu, lỗi, tiến độ, an toàn link tải.
f2 và CDN đều được giả; không test nào gọi Douyin."""
import importlib.abc
import importlib.machinery
import importlib.util
import logging
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from motio import douyin

REAL_F2 = douyin._f2  # conftest tắt douyin._f2 trong mỗi test; bản thật lấy ở đây lúc nạp module test

HEADERS = {"Referer": "https://www.douyin.com/", "User-Agent": "UA/1.0"}
CDN = "https://cdn-a.example/v.mp4"
CDN_2 = "https://cdn-b.example/v.mp4"
PUBLIC_IP = "93.184.216.34"


def _stream(gear: str, w: int, h: int, bitrate: int, h265: int = 0, urls=(CDN, CDN_2)) -> dict:
    return {"gear_name": gear, "is_h265": h265, "bit_rate": bitrate,
            "play_addr": {"width": w, "height": h, "url_list": list(urls)}}


# Cùng kiểu trả lời thật của Douyin: nhiều cỡ H.264, thêm các bản H.265 nhỏ hơn về dung lượng
LADDER = [
    _stream("normal_1080_0", 1920, 1080, 1996183),
    _stream("adapt_lowest_1440_1", 2560, 1440, 1781004, h265=1),
    _stream("normal_720_0", 1280, 720, 1540328),
    _stream("low_720_0", 1280, 720, 1415706),
    _stream("low_540_0", 1024, 576, 1278110),
    _stream("720_1_1", 1280, 720, 752464, h265=1),
]
# Lần Douyin trả danh sách thiếu bản H.264 720 dù video gốc lớn (bản H.265 720 và 1440 vẫn có)
THIN_LADDER = [LADDER[1], LADDER[4], LADDER[5]]
THIN_DEFAULT = _stream("default", 1024, 576, 0)["play_addr"]


def _raw(video: dict | None = None, ladder=None, **detail) -> dict:
    video = {"duration": 65700, "bit_rate": LADDER if ladder is None else ladder, "play_addr": THIN_DEFAULT,
             **(video or {})}
    return {"aweme_detail": {"aweme_id": "7686432847778982833", "desc": "标题 #tag", "create_time": 1789638014,
                             "author": {"nickname": "王主任", "sec_uid": "MS4wLjAB"}, "video": video, **detail},
            "status_code": 0}


@pytest.fixture
def douyin_api(monkeypatch):
    """Giả f2 (trả lời của Douyin, lần lượt từng phần tử nếu là list) và CDN (httpx.MockTransport)."""
    state = {"raw": _raw(), "asked": [], "requests": [], "size": 4096, "down": set(), "type": "video/mp4",
             "hosts": {}, "redirects": {}, "drop": set()}

    async def fake_fetch(post_id):
        state["asked"].append(post_id)
        raw = state["raw"]
        if isinstance(raw, list):
            raw = raw.pop(0) if len(raw) > 1 else raw[0]
        if isinstance(raw, Exception):
            raise raw
        return raw, dict(HEADERS)

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if request.url.host in state["redirects"]:
            return httpx.Response(302, headers={"location": state["redirects"][request.url.host]})
        if request.url.host in state["drop"]:
            raise httpx.ConnectError("no route to host")
        if request.url.host in state["down"]:
            return httpx.Response(503)
        return httpx.Response(200, content=b"v" * state["size"], headers={"content-type": state["type"]})

    real_client = douyin._client
    monkeypatch.setattr(douyin, "_fetch", fake_fetch)
    monkeypatch.setattr(douyin, "_resolve_host", lambda host: state["hosts"].get(host, [PUBLIC_IP]))
    monkeypatch.setattr(douyin, "_pause", lambda: None)
    monkeypatch.setattr(douyin, "_client", lambda headers, **kw: real_client(
        headers, transport=httpx.MockTransport(handler), **kw))
    return state


def test_f2_is_installed():
    """Gói f2 có mặt (không nạp thử: nạp f2 gọi Douyin xin msToken, test không dùng mạng)."""
    assert importlib.util.find_spec("f2.apps.douyin.crawler") is not None


@pytest.mark.parametrize("url", [
    "https://www.douyin.com/video/7686432847778982833", "https://douyin.com/x", "https://v.douyin.com/iNUBcHxM/",
    "https://www.iesdouyin.com/share/video/7686432847778982833/", "http://LIVE.DOUYIN.COM/123"])
def test_douyin_links(url):
    assert douyin.is_douyin(url)


@pytest.mark.parametrize("url", ["https://notdouyin.com/video/1", "https://douyin.com.evil.example/video/1",
                                 "https://www.bilibili.com/video/BV1", "not a link", ""])
def test_other_links(url):
    assert not douyin.is_douyin(url)


@pytest.mark.parametrize("url, expected", [
    ("https://www.douyin.com/video/7686432847778982833", "7686432847778982833"),
    ("https://www.douyin.com/note/7285559250619813155?previous_page=app_code_link", "7285559250619813155"),
    ("https://www.douyin.com/slides/7285559250619813155", "7285559250619813155"),
    ("https://www.iesdouyin.com/share/video/7683844732023911406/", "7683844732023911406"),
    ("https://www.douyin.com/jingxuan?modal_id=7686432847778982833", "7686432847778982833"),
    ("https://www.douyin.com/?vid=7686432847778982833&recommend=1", "7686432847778982833"),
    ("https://v.douyin.com/iNUBcHxM/", None),  # link rút gọn: phải theo chuyển hướng mới biết mã
    ("https://www.douyin.com/user/MS4wLjAB?modal_id=abc", None),
])
def test_post_id(url, expected):
    assert douyin._post_id(url) == expected


def test_short_links_are_followed_hop_by_hop_inside_douyin_hosts(douyin_api):
    douyin_api["redirects"] = {"v.douyin.com": "https://www.iesdouyin.com/share/video/7683844732023911406/?region=CN"}
    assert douyin._resolve_id("https://v.douyin.com/iNUBcHxM/") == "7683844732023911406"
    assert [r.url.host for r in douyin_api["requests"]] == ["v.douyin.com"]  # có mã ngay sau chặng đầu
    assert douyin._resolve_id("https://www.douyin.com/video/55") == "55"  # đã có mã: không hỏi mạng
    assert len(douyin_api["requests"]) == 1


def test_a_short_link_can_take_several_hops_to_reach_the_id(douyin_api):
    douyin_api["redirects"] = {"v.douyin.com": "https://www.iesdouyin.com/share/x",
                               "www.iesdouyin.com": "https://www.douyin.com/?vid=7683844732023911406"}
    assert douyin._resolve_id("https://v.douyin.com/abc/") == "7683844732023911406"
    assert [r.url.host for r in douyin_api["requests"]] == ["v.douyin.com", "www.iesdouyin.com"]


def test_a_short_link_that_leaves_douyin_or_never_redirects_has_no_id(douyin_api):
    douyin_api["redirects"] = {"v.douyin.com": "https://login.example/?next=1"}
    assert douyin._resolve_id("https://v.douyin.com/abc/") is None
    assert [r.url.host for r in douyin_api["requests"]] == ["v.douyin.com"]  # không đi tiếp ra ngoài
    assert douyin._resolve_id("https://www.douyin.com/user/MS4wLjAB") is None  # trang 200, không chuyển hướng


def test_pick_stream_takes_the_largest_h264_up_to_the_height():
    video = _raw()["aweme_detail"]["video"]
    s = douyin.pick_stream(video, 720)
    assert (s["width"], s["height"], s["h265"], s["bitrate"]) == (1280, 720, False, 1540328)
    assert douyin.pick_stream(video, 1080)["height"] == 1080
    assert douyin.pick_stream(video, 2000)["height"] == 1080  # không có cỡ lớn hơn: lấy cái lớn nhất có
    assert douyin.pick_stream(video, 600)["height"] == 576


def test_pick_stream_takes_the_smallest_when_everything_is_taller():
    video = {"bit_rate": [_stream("a", 1024, 576, 900_000), _stream("b", 854, 480, 500_000)]}
    assert douyin.pick_stream(video, 360)["height"] == 480


def test_pick_stream_measures_portrait_videos_by_their_short_side():
    video = {"bit_rate": [_stream("normal_1080_0", 1080, 1920, 3_000_000),
                          _stream("normal_720_0", 720, 1280, 1_500_000), _stream("low_540_0", 576, 1024, 900_000)]}
    assert douyin.pick_stream(video, 720)["width"] == 720
    assert douyin.pick_stream(video, 1080)["height"] == 1920


def test_pick_stream_uses_the_default_address_when_there_is_no_ladder():
    video = {"play_addr": {"width": 720, "height": 1280, "url_list": [CDN]}}
    assert douyin.pick_stream(video, 720)["urls"] == [CDN]
    assert douyin.pick_stream({}, 720) is None


def test_pick_stream_falls_back_to_h265_when_it_is_all_there_is():
    s = douyin.pick_stream({"bit_rate": [_stream("720_1_1", 1280, 720, 752464, h265=1)]}, 720)
    assert s["h265"] and s["height"] == 720


def test_the_h264_address_is_h264_even_when_the_default_one_is_h265():
    video = {"is_h265": 1, "play_addr_h264": {"width": 1280, "height": 720, "url_list": ["https://h264.example/a"]},
             "bit_rate": [_stream("720_1_1", 1280, 720, 700_000, h265=1, urls=["https://h265.example/a"])]}
    assert douyin.pick_stream(video, 720)["urls"] == ["https://h264.example/a"]


def test_download_saves_the_file_and_returns_the_metadata(douyin_api, tmp_path):
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path / "src", 720)
    path = tmp_path / "src" / "Douyin_7686432847778982833.mp4"
    assert path.read_bytes() == b"v" * 4096 and not list(path.parent.glob("*.part"))
    assert info == {"path": str(path), "url": "https://www.douyin.com/video/7686432847778982833",
                    "id": "7686432847778982833", "title": "标题 #tag", "platform": "Douyin", "uploader": "王主任",
                    "uploader_url": "https://www.douyin.com/user/MS4wLjAB", "upload_date": "20260917",
                    "duration": 65.7, "license": "", "width": 1280, "height": 720}
    sent = douyin_api["requests"][0]
    assert sent.headers["referer"] == "https://www.douyin.com/" and sent.headers["user-agent"] == "UA/1.0"
    assert douyin_api["asked"] == ["7686432847778982833"]  # bản đủ tốt ngay lần đầu: không hỏi lại


def test_without_a_height_the_largest_size_up_to_1080_is_taken(douyin_api, tmp_path):
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path)
    assert (info["width"], info["height"]) == (1920, 1080) and douyin.DEFAULT_HEIGHT == 1080


def test_download_keeps_the_same_keys_as_the_yt_dlp_path(douyin_api, tmp_path):
    info = douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert {"path", "url", "id", "title", "platform", "uploader", "uploader_url", "upload_date", "duration",
            "license", "width", "height"} <= set(info)


def test_download_reuses_a_file_that_is_already_there(douyin_api, tmp_path):
    (tmp_path / "Douyin_7686432847778982833.mp4").write_bytes(b"old")
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path)
    assert douyin_api["requests"] == [] and (tmp_path / "Douyin_7686432847778982833.mp4").read_bytes() == b"old"
    assert info["id"] == "7686432847778982833"


def test_a_short_link_goes_through_the_redirect_then_f2(douyin_api, tmp_path):
    douyin_api["redirects"] = {"v.douyin.com": "https://www.iesdouyin.com/share/video/7686432847778982833/"}
    info = douyin.download("https://v.douyin.com/iNUBcHxM/", tmp_path)
    assert douyin_api["asked"] == ["7686432847778982833"] and info["id"] == "7686432847778982833"


def test_a_thin_size_list_is_asked_again_and_the_better_answer_wins(douyin_api, tmp_path):
    douyin_api["raw"] = [_raw(ladder=THIN_LADDER), _raw()]
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path, 720)
    assert len(douyin_api["asked"]) == 2 and info["height"] == 720


def test_after_the_last_try_the_best_of_a_thin_run_is_used(douyin_api, tmp_path):
    douyin_api["raw"] = [_raw(ladder=THIN_LADDER)]
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path, 720)
    assert len(douyin_api["asked"]) == douyin.TRIES and info["height"] == 576


def test_a_source_that_is_small_anyway_is_not_asked_again(douyin_api, tmp_path):
    small = [_stream("low_540_0", 1024, 576, 900_000), _stream("a", 854, 480, 500_000)]
    douyin_api["raw"] = _raw(ladder=small, video={"play_addr": small[0]["play_addr"]})
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path, 720)
    assert len(douyin_api["asked"]) == 1 and info["height"] == 576


def test_no_1080_on_offer_is_not_a_reason_to_ask_again_when_720_is_there(douyin_api, tmp_path):
    douyin_api["raw"] = _raw(ladder=LADDER[1:])  # không có bản H.264 1080, có 720
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path)
    assert len(douyin_api["asked"]) == 1 and info["height"] == 720


def test_a_lower_height_asked_is_not_a_reason_to_ask_again(douyin_api, tmp_path):
    douyin_api["raw"] = _raw(ladder=THIN_LADDER)
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path, 480)
    assert len(douyin_api["asked"]) == 1 and info["height"] == 576


def test_a_passing_403_is_tried_again(douyin_api, tmp_path):
    douyin_api["raw"] = [RuntimeError("HTTP 403"), _raw()]
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path)
    assert len(douyin_api["asked"]) == 2 and info["id"] == "7686432847778982833"


def test_a_failure_f2_already_retried_is_not_asked_again(douyin_api, tmp_path):
    class APIRetryExhaustedError(Exception):
        pass

    douyin_api["raw"] = APIRetryExhaustedError("gave up")
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None
    assert len(douyin_api["asked"]) == 1


def test_download_gives_up_quietly_when_f2_keeps_failing(douyin_api, tmp_path):
    douyin_api["raw"] = RuntimeError("f2 broke")  # not a network error: yt-dlp is worth a try
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None
    assert len(douyin_api["asked"]) == douyin.TRIES


def test_download_says_unreachable_when_every_try_fails_on_the_network(douyin_api, tmp_path):
    douyin_api["raw"] = ConnectionError("offline")
    with pytest.raises(douyin.Unreachable, match="offline"):
        douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert len(douyin_api["asked"]) == douyin.TRIES


def test_one_answer_from_douyin_means_it_was_reachable(douyin_api, tmp_path):
    """A network error on the first try, then Douyin answers with something odd: that is not 'no connection'."""
    douyin_api["raw"] = [ConnectionError("blip"), {}]
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None


def test_a_network_blip_is_retried_and_the_video_still_comes(douyin_api, tmp_path):
    douyin_api["raw"] = [TimeoutError("slow"), _raw()]
    info = douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert info["id"] == "7686432847778982833" and len(douyin_api["asked"]) == 2


def test_a_failure_that_is_not_the_network_keeps_the_fallback_even_after_a_network_error(douyin_api, tmp_path):
    class APIResponseError(Exception):
        pass

    douyin_api["raw"] = [ConnectionError("blip"), APIResponseError("bad status"), ConnectionError("blip")]
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None


class APIConnectionError(Exception):  # f2's own error, named as f2 names it
    pass


class APITimeoutError(Exception):
    pass


def _wrapped(outer: Exception, inner: Exception) -> Exception:
    try:
        try:
            raise inner
        except Exception:
            raise outer from None  # implicit __context__ stays, like f2 raising inside its except block
    except Exception as e:
        return e


@pytest.mark.parametrize("error, expected", [
    (ConnectionRefusedError(), True), (TimeoutError(), True), (socket.gaierror(-3, "Temporary failure"), True),
    (httpx.ConnectError("no route"), True), (httpx.ReadTimeout("slow"), True), (httpx.ProxyError("proxy"), True),
    (APIConnectionError("f2"), True), (APITimeoutError("f2"), True),
    (_wrapped(RuntimeError("f2 could not be loaded a moment ago"), httpx.ConnectError("x")), True),
    (_wrapped(RuntimeError("wrapper"), APITimeoutError("f2")), True),
    (RuntimeError("f2 broke"), False), (OSError("host is not a public address"), False),
    (FileNotFoundError("conf.yaml"), False), (ValueError("bad json"), False),
    (_wrapped(RuntimeError("wrapper"), ValueError("not the network")), False),
])
def test_what_counts_as_a_network_error(error, expected):
    assert douyin._is_network_error(error) is expected


def test_a_cause_chain_that_loops_does_not_hang():
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a
    assert douyin._is_network_error(a) is False


def test_download_with_the_id_already_found_does_not_look_it_up_again(douyin_api, tmp_path, monkeypatch):
    def never(url):
        raise AssertionError("the id was handed over")

    monkeypatch.setattr(douyin, "_resolve_id", never)
    info = douyin.download("https://v.douyin.com/iNUBcHxM/", tmp_path, post_id="7686432847778982833")
    assert douyin_api["asked"] == ["7686432847778982833"] and info["id"] == "7686432847778982833"


def test_find_id_follows_a_short_link(douyin_api):
    douyin_api["redirects"] = {"v.douyin.com": "https://www.iesdouyin.com/share/video/7683844732023911406/"}
    assert douyin.find_id("https://v.douyin.com/iNUBcHxM/") == "7683844732023911406"
    assert douyin.find_id("https://www.douyin.com/video/55") == "55"


def test_find_id_says_unreachable_when_the_short_link_cannot_be_followed(monkeypatch):
    def offline(url):
        raise socket.gaierror(-3, "Temporary failure in name resolution")

    monkeypatch.setattr(douyin, "_resolve_id", offline)
    with pytest.raises(douyin.Unreachable):
        douyin.find_id("https://v.douyin.com/iNUBcHxM/")


def test_find_id_gives_no_id_for_a_failure_that_is_not_the_network(monkeypatch):
    def refused(url):
        raise OSError("v.douyin.com is not a public address")

    monkeypatch.setattr(douyin, "_resolve_id", refused)
    assert douyin.find_id("https://v.douyin.com/iNUBcHxM/") is None


@pytest.mark.parametrize("raw", [{}, {"status_code": 5}, {"aweme_detail": None}, "<html>",
                                 {"aweme_detail": None, "filter_detail": {}}])
def test_an_answer_with_no_post_and_no_reason_is_not_a_verdict(douyin_api, tmp_path, raw):
    """f2 hands back {} for a body it cannot read (a challenge page): let yt-dlp try instead of calling it 'gone'."""
    douyin_api["raw"] = raw
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None


def test_download_gives_up_quietly_when_every_cdn_link_fails(douyin_api, tmp_path):
    douyin_api["down"] = {"cdn-a.example", "cdn-b.example"}
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None
    assert not list(tmp_path.glob("Douyin_*"))  # không để lại file dở


def test_download_tries_the_next_cdn_link(douyin_api, tmp_path):
    douyin_api["down"] = {"cdn-a.example"}
    info = douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert [r.url.host for r in douyin_api["requests"]] == ["cdn-a.example", "cdn-b.example"]
    assert (tmp_path / "Douyin_7686432847778982833.mp4").stat().st_size == 4096 and info["id"]


def test_an_empty_answer_from_the_cdn_is_not_a_video(douyin_api, tmp_path):
    douyin_api["size"] = 0
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None
    assert [r.url.host for r in douyin_api["requests"]] == ["cdn-a.example", "cdn-b.example"]  # thử cả hai link
    assert not list(tmp_path.glob("Douyin_*"))


def test_a_page_from_the_cdn_is_not_a_video(douyin_api, tmp_path):
    douyin_api["type"] = "text/html"
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None
    assert not list(tmp_path.glob("Douyin_*"))


def test_progress_hooks_see_downloading_then_finished(douyin_api, tmp_path):
    seen = []
    douyin.download("https://www.douyin.com/video/1", tmp_path, hooks=[seen.append])
    assert seen[0]["status"] == "downloading" and seen[0]["total_bytes"] == 4096
    assert seen[-1] == {"status": "finished", "downloaded_bytes": 4096, "total_bytes": 4096}


def test_a_hook_that_raises_stops_the_download_and_the_error_comes_out(douyin_api, tmp_path):
    def stop(d):
        raise RuntimeError("Stopped")
    with pytest.raises(RuntimeError, match="Stopped"):
        douyin.download("https://www.douyin.com/video/1", tmp_path, hooks=[stop])
    assert not list(tmp_path.glob("Douyin_*"))


@pytest.mark.parametrize("reason, message", [
    ("status_deleted", "removed"), ("status_self_see", "private or restricted"), ("status_audit", "status_audit")])
def test_a_post_that_is_gone_says_why(douyin_api, tmp_path, reason, message):
    douyin_api["raw"] = {"aweme_detail": None, "filter_detail": {"filter_reason": reason}, "status_code": 0}
    with pytest.raises(douyin.Unavailable, match=message):
        douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert len(douyin_api["asked"]) == 1  # lý do rõ ràng: không hỏi lại


def test_a_photo_post_is_not_a_video(douyin_api, tmp_path):
    douyin_api["raw"] = _raw(video={"bit_rate": [], "play_addr": {}}, images=[{"url_list": ["https://p.example/1.jpg"]}])
    with pytest.raises(douyin.Unavailable, match="photos"):
        douyin.download("https://www.douyin.com/note/1", tmp_path)
    assert len(douyin_api["asked"]) == 1


def test_a_video_over_the_size_cap_is_refused(douyin_api, tmp_path, monkeypatch):
    monkeypatch.setattr(douyin, "MAX_BYTES", 1024)
    with pytest.raises(douyin.Unavailable, match="larger than"):
        douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert not list(tmp_path.glob("Douyin_*"))


@pytest.mark.parametrize("bad", ["http://cdn-a.example/v.mp4", "https://127.0.0.1/v.mp4", "https://10.0.0.5:8765/api"])
def test_a_link_to_plain_http_or_a_private_address_is_never_fetched(douyin_api, tmp_path, bad):
    """f2 does not check TLS certificates, so its reply could be forged: only https to a public address is followed."""
    douyin_api["hosts"] = {"127.0.0.1": ["127.0.0.1"], "10.0.0.5": ["10.0.0.5"]}
    douyin_api["raw"] = _raw(ladder=[_stream("a", 1280, 720, 1_000_000, urls=[bad])])
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None
    assert douyin_api["requests"] == []


def test_a_name_that_resolves_to_a_private_address_is_refused(douyin_api, tmp_path):
    douyin_api["hosts"] = {"cdn-a.example": ["10.1.2.3"], "cdn-b.example": ["8.8.8.8", "192.168.1.9"]}
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None
    assert douyin_api["requests"] == []


def test_a_redirect_from_the_cdn_to_a_private_address_is_refused(douyin_api, tmp_path):
    douyin_api["redirects"] = {"cdn-a.example": "https://internal.example/secret"}
    douyin_api["hosts"] = {"internal.example": ["127.0.0.1"]}
    info = douyin.download("https://www.douyin.com/video/1", tmp_path)
    hosts = [r.url.host for r in douyin_api["requests"]]
    assert info and hosts == ["cdn-a.example", "cdn-b.example"]  # chặng tới internal.example bị chặn trước khi gửi


def test_f2_logger_is_parked_so_f2_makes_no_logs_folder(tmp_path, monkeypatch):
    """f2 tạo ./logs lúc nạp nếu logger "f2" chưa có handler; không nạp f2 thật ở đây (nó gọi mạng)."""
    monkeypatch.chdir(tmp_path)
    logging.getLogger("f2").handlers.clear()
    douyin._park_f2_logger()
    lg = logging.getLogger("f2")
    assert lg.hasHandlers() and not lg.propagate and not (tmp_path / "logs").exists()


class FakeF2(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Cây module f2 giả để thử _f2() mà không nạp f2 thật; ghi lại module nào đang có trong sys.modules lúc nạp."""
    NAMES = ("f2", "f2.apps", "f2.apps.douyin", "f2.apps.douyin.crawler", "f2.apps.douyin.model",
             "f2.apps.douyin.utils")

    def __init__(self):
        self.fail, self.loads, self.stubs_seen = False, 0, {}
        self.hold: threading.Event | None = None  # đặt vào thì f2 giả đứng chờ nó, như mạng nuốt gói tin
        self.imports = 0  # số lần _import_f2 được gọi: mỗi lần là một luồng nạp

    def find_spec(self, name, path=None, target=None):
        if name in self.NAMES:
            return importlib.machinery.ModuleSpec(name, self, is_package=name != self.NAMES[-1])

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__name__
        if name == "f2.apps.douyin.crawler":
            self.loads += 1
            self.stubs_seen = {n: n in sys.modules for n in ("browser_cookie3", "execjs")}
            module.DouyinCrawler = object
        elif name == "f2.apps.douyin.model":
            if self.hold is not None:
                self.hold.wait(10)
            if self.fail:
                raise ConnectionError("msToken endpoint unreachable")
            module.PostDetail = object
        elif name == "f2.apps.douyin.utils":
            module.ClientConfManager = module.TokenManager = object
        else:
            module.__path__ = []


@pytest.fixture
def fake_f2(monkeypatch):
    for name in [n for n in sys.modules if n == "f2" or n.startswith("f2.")]:
        monkeypatch.delitem(sys.modules, name)
    for name in ("browser_cookie3", "execjs"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    finder = FakeF2()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    monkeypatch.setattr(douyin, "_f2_loaded", None)
    monkeypatch.setattr(douyin, "_f2_failed", None)
    monkeypatch.setattr(douyin, "_f2_thread", None)
    real_import = douyin._import_f2

    def counted():
        finder.imports += 1
        return real_import()

    monkeypatch.setattr(douyin, "_import_f2", counted)
    yield finder
    if finder.hold is not None:  # đừng để luồng nạp giả treo sang test sau
        finder.hold.set()
    if douyin._f2_thread is not None:
        douyin._f2_thread.join(5)


def test_f2_is_loaded_once_with_empty_stand_ins_for_the_two_packages_motio_does_not_install(fake_f2):
    first = REAL_F2()
    assert REAL_F2() is first and fake_f2.loads == 1
    assert fake_f2.stubs_seen == {"browser_cookie3": True, "execjs": True}  # có mặt lúc f2 nạp…
    assert "browser_cookie3" not in sys.modules and "execjs" not in sys.modules  # …rồi dọn đi


def test_f2_loads_safely_from_several_threads(fake_f2):
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: REAL_F2(), range(8)))
    assert fake_f2.loads == 1 and fake_f2.imports == 1 and all(r is results[0] for r in results)


def test_f2_that_failed_to_load_is_not_retried_straight_away(fake_f2, monkeypatch):
    fake_f2.fail = True
    clock = [1000.0]
    monkeypatch.setattr(douyin.time, "monotonic", lambda: clock[0])
    with pytest.raises(ConnectionError):
        REAL_F2()
    with pytest.raises(RuntimeError, match="a moment ago"):
        REAL_F2()
    assert fake_f2.loads == 1  # lần hai không đụng tới f2
    assert "browser_cookie3" not in sys.modules and "execjs" not in sys.modules  # nạp hỏng cũng dọn module rỗng
    clock[0] += douyin._F2_RETRY_AFTER + 1
    fake_f2.fail = False
    for name in [n for n in sys.modules if n.startswith("f2.apps.douyin.")]:
        monkeypatch.delitem(sys.modules, name)  # lần nạp hỏng để lại module nửa vời; nạp lại từ đầu
    assert REAL_F2() and fake_f2.loads == 2


def test_a_failed_load_keeps_its_cause_so_the_network_is_recognised(fake_f2):
    fake_f2.fail = True
    with pytest.raises(ConnectionError):
        REAL_F2()
    with pytest.raises(RuntimeError, match="a moment ago") as again:
        REAL_F2()
    assert isinstance(again.value.__cause__, ConnectionError) and douyin._is_network_error(again.value)


def test_a_load_that_stalls_is_given_up_after_the_wait_and_not_waited_for_again(fake_f2, monkeypatch):
    """f2 asks Douyin for a token as soon as it is imported: packets dropped on the way make that take minutes."""
    fake_f2.hold = threading.Event()
    monkeypatch.setattr(douyin, "_F2_LOAD_WAIT", 0.2)
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="still loading") as first:
        REAL_F2()
    assert time.monotonic() - start < 5 and douyin._is_network_error(first.value)
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="a moment ago") as second:
        REAL_F2()  # the load is still going: no second wait, no second load
    assert time.monotonic() - start < 0.15 and douyin._is_network_error(second.value) and fake_f2.imports == 1


def test_a_stalled_load_is_not_started_again_when_the_retry_window_is_over(fake_f2, monkeypatch):
    fake_f2.hold = threading.Event()
    monkeypatch.setattr(douyin, "_F2_LOAD_WAIT", 0.1)
    monkeypatch.setattr(douyin, "_F2_RETRY_AFTER", 0)
    for _ in range(3):
        with pytest.raises((TimeoutError, RuntimeError)):
            REAL_F2()
    assert fake_f2.imports == 1  # one load at a time, however many downloads ask


def test_a_load_that_ends_after_the_wait_serves_the_next_download(fake_f2, monkeypatch):
    fake_f2.hold = threading.Event()
    monkeypatch.setattr(douyin, "_F2_LOAD_WAIT", 0.1)
    with pytest.raises(TimeoutError):
        REAL_F2()
    fake_f2.hold.set()
    douyin._f2_thread.join(5)
    assert REAL_F2() and fake_f2.imports == 1  # f2 is there now: nothing is loaded again


def test_a_load_that_fails_after_the_wait_replaces_the_timeout_with_the_real_error(fake_f2, monkeypatch):
    fake_f2.hold = threading.Event()
    fake_f2.fail = True
    monkeypatch.setattr(douyin, "_F2_LOAD_WAIT", 0.1)
    with pytest.raises(TimeoutError):
        REAL_F2()
    fake_f2.hold.set()
    douyin._f2_thread.join(5)
    with pytest.raises(RuntimeError, match="msToken endpoint unreachable"):
        REAL_F2()


def test_a_load_that_calls_sys_exit_is_a_failure_not_a_timeout(fake_f2, monkeypatch):
    """f2 calls sys.exit(1) when its config file is broken: the thread must still leave a real failure behind."""
    def exits():
        raise SystemExit(1)

    monkeypatch.setattr(douyin, "_import_f2", exits)
    with pytest.raises(RuntimeError, match="stopped while loading") as failure:
        REAL_F2()
    assert not isinstance(failure.value, TimeoutError) and not douyin._is_network_error(failure.value)


def test_a_load_thread_that_ends_without_a_result_is_not_blamed_on_the_network(fake_f2, monkeypatch):
    monkeypatch.setattr(douyin, "_load_f2", lambda: None)
    with pytest.raises(RuntimeError, match="without a result") as failure:
        REAL_F2()
    assert not douyin._is_network_error(failure.value)


def test_a_link_that_holds_its_id_needs_no_http_client(monkeypatch):
    """A broken certificate path or a SOCKS proxy without its package makes httpx.Client fail to build."""
    def broken(*a, **k):
        raise FileNotFoundError("SSL_CERT_FILE")

    monkeypatch.setattr(douyin, "_client", broken)
    share = "https://www.iesdouyin.com/share/video/7683844732023911406/?region=CN"
    assert douyin.find_id(share) == "7683844732023911406"
    assert douyin.find_id("https://www.douyin.com/jingxuan?modal_id=7686432847778982833") == "7686432847778982833"


def test_every_cdn_link_failing_on_the_network_is_unreachable(douyin_api, tmp_path):
    douyin_api["drop"] = {"cdn-a.example", "cdn-b.example"}
    with pytest.raises(douyin.Unreachable):
        douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert not list(tmp_path.glob("Douyin_*"))


def test_a_cdn_that_answers_with_an_error_is_not_a_missing_connection(douyin_api, tmp_path):
    douyin_api["drop"], douyin_api["down"] = {"cdn-a.example"}, {"cdn-b.example"}  # one cut off, one says 503
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None


def test_one_cdn_link_that_still_works_after_a_cut_off_one_gives_the_video(douyin_api, tmp_path):
    douyin_api["drop"] = {"cdn-a.example"}
    assert douyin.download("https://www.douyin.com/video/1", tmp_path)["id"] == "7686432847778982833"
