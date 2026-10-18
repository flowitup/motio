"""Weibo's hot timeline (motio/weibo_feed.py) as a watch source, and the download from the post's own mp4 address."""
import httpx
import pytest

from motio import db, douyin, qa, search, watch, weibo_feed

MP4 = "http://f.video.weibocdn.com/o0/a.mp4?label=mp4_hd&Expires=1792357547&ssig=x"


def _post(mid, **kw):
    media = {"duration": 95.4, "mp4_hd_url": MP4, "mp4_sd_url": MP4, "stream_url": MP4}
    page = {"object_type": "video", "page_pic": f"https://wx4.sinaimg.cn/{mid}.jpg", "media_info": media}
    post = {"mblogid": mid, "user": {"idstr": "3266943013", "screen_name": "央视网"},
            "text_raw": f"【#法国多地街头火光冲天#】视频 {mid} http://t.cn/AXl1jYjZ ​", "attitudes_count": 69,
            "created_at": "Sun Oct 18 21:20:00 +0800 2026", "page_info": page}
    return {**post, **kw}


@pytest.fixture
def weibo_site(monkeypatch):
    """Weibo's guest endpoint, timeline and CDN behind httpx.MockTransport. `state`: posts per answer, calls, bytes."""
    state = {"posts": [_post("RnhjgpzL7"), _post("RngJqA77q")], "ok": 1, "status": 200, "guest": True, "calls": [],
             "mp4": b"v" * 4000, "type": "video/mp4", "cookies": []}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"].append(str(req.url))
        if req.url.host == "passport.weibo.com":
            headers = {"set-cookie": "SUB=guest-sub; Domain=.weibo.com; Path=/; Secure"} if state["guest"] else {}
            return httpx.Response(200, text='visitor_gray_callback({"retcode":20000000})', headers=headers)
        if req.url.host == "weibo.com":
            state["cookies"].append(req.headers.get("cookie", ""))
            if "SUB=" not in req.headers.get("cookie", ""):
                return httpx.Response(403, text="forbidden")
            return httpx.Response(state["status"], json={"ok": state["ok"], "statuses": state["posts"]})
        return httpx.Response(200, content=state["mp4"], headers={"content-type": state["type"]})

    monkeypatch.setattr(weibo_feed, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(weibo_feed, "_PAUSE", 0)
    monkeypatch.setattr(douyin, "_resolve_host", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(qa, "probe", lambda path: {"duration": 95.0, "video": {"width": 852, "height": 480}})
    weibo_feed._store().unlink(missing_ok=True)
    with db.conn() as c:
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")
    yield state
    with db.conn() as c:  # the watch a test followed must not reach the next test file
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")


def test_parse_and_name():
    assert weibo_feed.parse("weibo:hot") == "hot"
    assert weibo_feed.name("weibo:hot") == "Weibo hot videos"
    for bad in ("weibo:", "weibo:hot:1", "bilibili:popular", "hot"):
        with pytest.raises(ValueError):
            weibo_feed.parse(bad)


def test_fetch_asks_for_a_guest_session_first_and_keeps_only_long_enough_videos(weibo_site):
    weibo_site["posts"] = [
        _post("RnhjgpzL7"),
        _post("RnhShortA1", page_info={**_post("x")["page_info"], "media_info": {"duration": 9, "mp4_hd_url": MP4}}),
        _post("RnhPhoto11", page_info={}),  # a photo / text post
        _post("RnhNoText11", text_raw=" http://t.cn/x "),
        _post("RnhNoMp4111", page_info={"object_type": "video", "media_info": {"duration": 60}}),
        _post("RnhOtherCdn", page_info={**_post("x")["page_info"],
                                        "media_info": {"duration": 60, "mp4_hd_url": "http://evil.example/a.mp4"}}),
    ]
    rows = weibo_feed.fetch("weibo:hot")
    assert [r["id"] for r in rows] == ["weibo:RnhjgpzL7"]  # the same answer five times, one row
    assert weibo_site["calls"][0].startswith("https://passport.weibo.com/visitor/genvisitor2")
    assert len(weibo_site["calls"]) == 1 + weibo_feed.PAGES
    assert all("SUB=guest-sub" in c for c in weibo_site["cookies"])
    r = rows[0]
    assert (r["site"], r["url"], r["rank"]) == ("weibo", "https://weibo.com/3266943013/RnhjgpzL7", 1)
    assert r["title"] == "【#法国多地街头火光冲天#】视频 RnhjgpzL7" and r["uploader"] == "央视网"
    assert (r["duration"], r["likes"], r["views"]) == (95, 69, None)
    assert r["thumbnail"].startswith("https://") and r["pubdate"] == 1_792_329_600


def test_no_guest_session_is_an_error(weibo_site):
    weibo_site["guest"] = False
    with pytest.raises(weibo_feed.FeedError, match="guest session"):
        weibo_feed.fetch("weibo:hot")


def test_a_refusal_is_an_error_not_an_empty_list(weibo_site):
    weibo_site["ok"] = 0
    with pytest.raises(weibo_feed.FeedError, match="200 ok 0"):
        weibo_feed.fetch("weibo:hot")
    weibo_site["ok"], weibo_site["posts"] = 1, [_post("RnhPhoto11", page_info={})]
    with pytest.raises(weibo_feed.FeedError, match="no videos"):
        weibo_feed.fetch("weibo:hot")


def test_follow_and_check_saves_the_videos(weibo_site):
    wid = watch.add("weibo:hot")
    w = db.get_watch(wid)
    assert (w["kind"], w["site"], w["name"]) == ("trending", "weibo", "Weibo hot videos")
    with pytest.raises(ValueError):
        watch.add("weibo:hot")
    watch.check(w)
    assert {r["id"] for r in db.list_clips("new", wid)} == {"weibo:RnhjgpzL7", "weibo:RngJqA77q"}
    weibo_site["ok"] = 0
    out = watch.check(db.get_watch(wid))
    assert "ok 0" in (db.get_watch(wid)["last_error"] or "") and out is not None


def test_find_id():
    assert weibo_feed.find_id("https://weibo.com/3266943013/RnhjgpzL7") == "RnhjgpzL7"
    assert weibo_feed.find_id("https://www.weibo.com/3266943013/RnhjgpzL7/") == "RnhjgpzL7"
    for other in ("https://m.weibo.cn/detail/5355480866095661", "https://weibo.com/u/3266943013", "https://x.com/1/Abcdef1"):
        assert weibo_feed.find_id(other) == ""


def test_a_feed_video_downloads_from_its_own_address_through_search_download(weibo_site, tmp_path):
    weibo_feed.fetch("weibo:hot")
    weibo_site["calls"].clear()
    info = search.download("https://weibo.com/3266943013/RnhjgpzL7", tmp_path)
    assert info["id"] == "RnhjgpzL7" and info["platform"] == "Weibo"
    assert (tmp_path / "Weibo_RnhjgpzL7.mp4").read_bytes() == b"v" * 4000
    assert weibo_site["calls"] == [MP4]  # http: Weibo's CDN resets https
    assert not list(tmp_path.glob("*.part"))


def test_an_expired_address_or_an_unknown_post_gives_none(weibo_site, tmp_path):
    weibo_feed.fetch("weibo:hot")
    weibo_site["type"] = "text/html"  # the CDN answers a page
    assert weibo_feed.download("https://weibo.com/3266943013/RnhjgpzL7", tmp_path) is None
    assert weibo_feed.download("https://weibo.com/3266943013/RnhZzzzzz", tmp_path) is None
    assert not list(tmp_path.glob("*.part")) and not list(tmp_path.glob("*.mp4"))


def test_the_download_only_goes_to_weibos_own_cdn_at_public_addresses(weibo_site, tmp_path, monkeypatch):
    weibo_feed.fetch("weibo:hot")
    monkeypatch.setattr(douyin, "_resolve_host", lambda host: ["10.0.0.5"])  # a private address
    assert weibo_feed.download("https://weibo.com/3266943013/RnhjgpzL7", tmp_path) is None
    weibo_feed._remember({"RnhjgpzL7": "http://evil.example/a.mp4"})
    assert weibo_feed.media_url("RnhjgpzL7") is None


def test_old_addresses_are_forgotten(weibo_site, monkeypatch):
    weibo_feed.fetch("weibo:hot")
    assert weibo_feed.media_url("RnhjgpzL7") == MP4
    monkeypatch.setattr(weibo_feed, "MEDIA_TTL", -1)
    assert weibo_feed.media_url("RnhjgpzL7") is None
