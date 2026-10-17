"""Haokan videos (motio/haokan.py): the address in the phone page, picking a quality, the download."""
import json

import httpx
import pytest

from motio import douyin, haokan

VID = "9182896717567225983"
LOW = "https://vd2.bdstatic.com/mda-x/cae_h264/low.mp4?auth_key=a"
HIGH = "https://vd2.bdstatic.com/mda-x/hd/cae_h264/high.mp4?auth_key=b"
FULL = "https://vd2.bdstatic.com/mda-x/sc/cae_h264/full.mp4?auth_key=c"


def _page(**meta) -> str:
    base = {"id": VID, "title": "速成肉鸡", "duration": 189, "publish_time": 1694354409, "playurl": LOW,
            "clarityUrl": [{"key": "sd", "title": "标清", "url": LOW, "vodVideoHW": "360$$640"},
                           {"key": "hd", "title": "高清", "url": HIGH, "vodVideoHW": "576$$1024"},
                           {"key": "sc", "title": "超清", "url": FULL, "vodVideoHW": "720$$1280"}],
            "source_name": "鹰眼科普", "mth": {"author_name": "鹰眼科普", "author_url": "https://haokan.baidu.com/a/1"}}
    state = {"requestInfo": {}, "curVideoMeta": {**base, **meta}, "header": {"title": "x"}}
    return f"<html><script>window.__PRELOADED_STATE__ = {json.dumps(state, ensure_ascii=False)};</script></html>"


@pytest.fixture
def baidu(monkeypatch):
    """Haokan and its CDN behind httpx.MockTransport. `state`: page body, mp4 bytes, calls, failures to inject."""
    state = {"page": _page(), "mp4": b"x" * 5000, "calls": [], "resets": 0, "type": "video/mp4"}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"].append((str(req.url), req.headers.get("user-agent", "")))
        if state["resets"]:
            state["resets"] -= 1
            raise httpx.ReadError("Connection reset by peer")
        if req.url.host == "haokan.baidu.com":
            return httpx.Response(200, text=state["page"])
        return httpx.Response(200, content=state["mp4"], headers={"content-type": state["type"]})

    monkeypatch.setattr(haokan, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(douyin, "_resolve_host", lambda host: ["93.184.216.34"])
    return state


@pytest.mark.parametrize("url,vid", [
    (f"https://haokan.baidu.com/v?vid={VID}", VID),
    (f"https://haokan.baidu.com/v?vid={VID}&pd=wisenatural", VID),
    ("https://haokan.baidu.com/v?vid=abc", None),
    ("https://haokan.baidu.com/", None),
    (f"https://example.com/v?vid={VID}", None),
])
def test_find_id(url, vid):
    assert haokan.find_id(url) == vid


def test_the_best_quality_not_taller_than_the_limit_is_picked():
    meta = haokan._state(_page())["curVideoMeta"]
    assert haokan.pick(meta, 720) == (FULL, 720)
    assert haokan.pick(meta, 600) == (HIGH, 576)
    assert haokan.pick(meta, 480) == (LOW, 360)
    assert haokan.pick(meta, 100) == (LOW, 360)  # nothing fits: the smallest


def test_playurl_is_the_fallback_and_only_https_counts():
    assert haokan.pick({"playurl": LOW}, 720) == (LOW, 0)
    with pytest.raises(haokan.Unavailable):
        haokan.pick({"playurl": "http://vd2.bdstatic.com/a.mp4", "clarityUrl": [{"url": "file:///etc/passwd"}]}, 720)


def test_download_saves_the_mp4_and_describes_it(baidu, tmp_path):
    seen = []
    info = haokan.download(f"https://haokan.baidu.com/v?vid={VID}", tmp_path, 600, [seen.append])
    assert (tmp_path / f"Haokan_{VID}.mp4").read_bytes() == b"x" * 5000
    assert not list(tmp_path.glob("*.part"))
    assert info == {"path": str(tmp_path / f"Haokan_{VID}.mp4"), "url": f"https://haokan.baidu.com/v?vid={VID}",
                    "id": VID, "title": "速成肉鸡", "platform": "Haokan", "uploader": "鹰眼科普",
                    "uploader_url": "https://haokan.baidu.com/a/1", "upload_date": "20230910", "duration": 189,
                    "license": "", "width": None, "height": 576}
    assert seen[-1]["status"] == "finished" and seen[-1]["downloaded_bytes"] == 5000
    page, cdn = baidu["calls"]
    assert "iPhone" in page[1] and cdn[0] == HIGH  # the desktop page is an empty "error" page
    haokan.download(f"https://haokan.baidu.com/v?vid={VID}", tmp_path, 600)  # the file is there: not fetched again
    assert len(baidu["calls"]) == 3  # only the page again


def test_a_reset_connection_is_tried_again(baidu, tmp_path):
    baidu["resets"] = 2  # the page then the first try of the file
    info = haokan.download(f"https://haokan.baidu.com/v?vid={VID}", tmp_path)
    assert info["id"] == VID and (tmp_path / f"Haokan_{VID}.mp4").stat().st_size == 5000


def test_a_connection_that_keeps_failing_says_so(baidu, tmp_path):
    baidu["resets"] = 99
    with pytest.raises(RuntimeError, match="Could not connect to Haokan"):
        haokan.download(f"https://haokan.baidu.com/v?vid={VID}", tmp_path)


def test_a_missing_video_is_reported(baidu, tmp_path):
    baidu["page"] = "<html><script>window.__PRELOADED_STATE__ = {\"header\": {}};</script></html>"
    with pytest.raises(haokan.Unavailable, match="no such video"):
        haokan.download(f"https://haokan.baidu.com/v?vid={VID}", tmp_path)


def test_a_page_instead_of_a_video_is_refused_and_leaves_no_file(baidu, tmp_path):
    baidu["type"] = "text/html"
    with pytest.raises(haokan.Unavailable, match="not a video"):
        haokan.download(f"https://haokan.baidu.com/v?vid={VID}", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_stream_address_on_a_private_network_is_refused(baidu, tmp_path, monkeypatch):
    monkeypatch.setattr(douyin, "_resolve_host", lambda host: ["10.0.0.5"] if "bdstatic" in host else ["1.1.1.1"])
    with pytest.raises(RuntimeError, match="Could not download from Haokan"):
        haokan.download(f"https://haokan.baidu.com/v?vid={VID}", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_link_without_an_id_is_refused(tmp_path):
    with pytest.raises(haokan.Unavailable, match="video id"):
        haokan.download("https://haokan.baidu.com/", tmp_path)
