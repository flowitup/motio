"""Tải video Douyin bằng f2 (motio/douyin.py): chọn luồng, siêu dữ liệu, lỗi, tiến độ. f2 và CDN đều được giả."""
import importlib.util
import logging

import httpx
import pytest

from motio import douyin

HEADERS = {"Referer": "https://www.douyin.com/", "User-Agent": "UA/1.0"}
CDN = "https://cdn-a.example/v.mp4"
CDN_2 = "https://cdn-b.example/v.mp4"


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


def _raw(video: dict | None = None, **detail) -> dict:
    video = {"duration": 65700, "bit_rate": LADDER, "play_addr": LADDER[0]["play_addr"], **(video or {})}
    return {"aweme_detail": {"aweme_id": "7686432847778982833", "desc": "标题 #tag", "create_time": 1789638014,
                             "author": {"nickname": "王主任", "sec_uid": "MS4wLjAB"}, "video": video, **detail},
            "status_code": 0}


@pytest.fixture
def douyin_api(monkeypatch):
    """Giả f2 (trả lời của Douyin) và CDN (httpx.MockTransport). Trả về nơi ghi các request tới CDN."""
    state = {"raw": _raw(), "requests": [], "size": 4096, "down": set()}

    async def fake_fetch(url):
        if isinstance(state["raw"], Exception):
            raise state["raw"]
        return state["raw"], dict(HEADERS)

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if request.url.host in state["down"]:
            return httpx.Response(503)
        return httpx.Response(200, content=b"v" * state["size"], headers={"content-type": "video/mp4"})

    monkeypatch.setattr(douyin, "_fetch", fake_fetch)
    monkeypatch.setattr(douyin, "_client", lambda headers: httpx.Client(
        transport=httpx.MockTransport(handler), headers=headers, follow_redirects=True))
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
    ("https://www.iesdouyin.com/share/video/7683844732023911406/", "7683844732023911406"),
    ("https://www.douyin.com/jingxuan?modal_id=7686432847778982833", "7686432847778982833"),
    ("https://v.douyin.com/iNUBcHxM/", None),  # link rút gọn: f2 theo chuyển hướng để biết mã
    ("https://www.douyin.com/user/MS4wLjAB?modal_id=abc", None),
])
def test_post_id(url, expected):
    assert douyin._post_id(url) == expected


def test_pick_stream_takes_h264_at_the_size_limit():
    s = douyin.pick_stream(_raw()["aweme_detail"]["video"], 720)
    assert (s["width"], s["height"], s["h265"], s["bitrate"]) == (1280, 720, False, 1540328)
    assert douyin.pick_stream(_raw()["aweme_detail"]["video"], 1080)["height"] == 1080
    assert douyin.pick_stream(_raw()["aweme_detail"]["video"], 600)["height"] == 576


def test_pick_stream_takes_the_smallest_when_nothing_fits():
    s = douyin.pick_stream(_raw()["aweme_detail"]["video"], 360)
    assert s["height"] == 576 and not s["h265"]


def test_pick_stream_measures_portrait_videos_by_their_short_side():
    video = {"bit_rate": [_stream("normal_1080_0", 1080, 1920, 3_000_000),
                          _stream("normal_720_0", 720, 1280, 1_500_000), _stream("low_540_0", 576, 1024, 900_000)]}
    assert douyin.pick_stream(video, 720)["width"] == 720


def test_pick_stream_uses_the_default_address_when_there_is_no_ladder():
    video = {"play_addr": {"width": 720, "height": 1280, "url_list": [CDN]}}
    assert douyin.pick_stream(video, 720)["urls"] == [CDN]
    assert douyin.pick_stream({}, 720) is None


def test_pick_stream_falls_back_to_h265_when_it_is_all_there_is():
    s = douyin.pick_stream({"bit_rate": [_stream("720_1_1", 1280, 720, 752464, h265=1)]}, 720)
    assert s["h265"] and s["height"] == 720


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


def test_download_keeps_the_same_keys_as_the_yt_dlp_path(douyin_api, tmp_path):
    info = douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert {"path", "url", "id", "title", "platform", "uploader", "uploader_url", "upload_date", "duration",
            "license", "width", "height"} <= set(info)


def test_download_reuses_a_file_that_is_already_there(douyin_api, tmp_path):
    (tmp_path / "Douyin_7686432847778982833.mp4").write_bytes(b"old")
    info = douyin.download("https://www.douyin.com/video/7686432847778982833", tmp_path)
    assert douyin_api["requests"] == [] and (tmp_path / "Douyin_7686432847778982833.mp4").read_bytes() == b"old"
    assert info["id"] == "7686432847778982833"


def test_download_tries_the_next_cdn_link(douyin_api, tmp_path):
    douyin_api["down"] = {"cdn-a.example"}
    info = douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert [r.url.host for r in douyin_api["requests"]] == ["cdn-a.example", "cdn-b.example"]
    assert (tmp_path / "Douyin_7686432847778982833.mp4").stat().st_size == 4096 and info["id"]


def test_download_gives_up_quietly_when_every_cdn_link_fails(douyin_api, tmp_path):
    douyin_api["down"] = {"cdn-a.example", "cdn-b.example"}
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None
    assert not list(tmp_path.glob("Douyin_*"))  # không để lại file dở


def test_download_gives_up_quietly_when_f2_fails(douyin_api, tmp_path):
    douyin_api["raw"] = ConnectionError("offline")
    assert douyin.download("https://www.douyin.com/video/1", tmp_path) is None


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


def test_a_photo_post_is_not_a_video(douyin_api, tmp_path):
    douyin_api["raw"] = _raw(video={"bit_rate": [], "play_addr": {}}, images=[{"url_list": ["https://p.example/1.jpg"]}])
    with pytest.raises(douyin.Unavailable, match="photos"):
        douyin.download("https://www.douyin.com/note/1", tmp_path)


def test_a_video_over_the_size_cap_is_refused(douyin_api, tmp_path, monkeypatch):
    monkeypatch.setattr(douyin, "MAX_BYTES", 1024)
    with pytest.raises(douyin.Unavailable, match="larger than"):
        douyin.download("https://www.douyin.com/video/1", tmp_path)
    assert not list(tmp_path.glob("Douyin_*"))


def test_f2_logger_is_parked_so_f2_makes_no_logs_folder(tmp_path, monkeypatch):
    """f2 tạo ./logs lúc nạp nếu logger "f2" chưa có handler; không nạp f2 thật ở đây (nó gọi mạng)."""
    monkeypatch.chdir(tmp_path)
    logging.getLogger("f2").handlers.clear()
    douyin._park_f2_logger()
    lg = logging.getLogger("f2")
    assert lg.hasHandlers() and not lg.propagate and not (tmp_path / "logs").exists()
