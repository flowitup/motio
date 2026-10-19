"""Weibo's keyword search (motio/weibo_feed.search) for the Scan screen: guest session, paging, dedupe, errors."""
import httpx
import pytest

from motio import weibo_feed

MP4 = "http://f.video.weibocdn.com/o0/a.mp4?label=mp4_hd&Expires=1792357547&ssig=x"


def _video(mid, seconds=95.4):
    media = {"duration": seconds, "mp4_hd_url": MP4, "mp4_sd_url": MP4, "stream_url": MP4}
    return {"mblogid": mid, "user": {"idstr": "3266943013", "screen_name": "央视网"},
            "text_raw": f"【#猫#】视频 {mid} http://t.cn/AXl1jYjZ ​", "attitudes_count": 69,
            "created_at": "Sun Oct 18 21:20:00 +0800 2026",
            "page_info": {"object_type": "video", "page_pic": f"https://wx4.sinaimg.cn/{mid}.jpg",
                          "media_info": media}}


def _text(mid):
    return {"mblogid": mid, "user": {"idstr": "3266943013", "screen_name": "央视网"}, "text_raw": f"文字 {mid}"}


@pytest.fixture
def weibo_search(monkeypatch):
    """Weibo's guest endpoint and search answers behind httpx.MockTransport. `state["pages"]`: posts per answer."""
    state = {"pages": [], "calls": [], "guest": True, "status": 200, "ok": 1, "html": False, "fail": set()}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"].append(req)
        if req.url.host == "passport.weibo.com":
            headers = {"set-cookie": "SUB=guest-sub; Domain=.weibo.com; Path=/"} if state["guest"] else {}
            return httpx.Response(200, text="ok", headers=headers)
        page = int(req.url.params.get("page") or 1)
        if page in state["fail"] or state["html"]:
            return httpx.Response(state["status"], text="<html>busy</html>")
        posts = state["pages"][page - 1] if 0 < page <= len(state["pages"]) else []
        return httpx.Response(state["status"], json={"ok": state["ok"], "statuses": posts})

    monkeypatch.setattr(weibo_feed, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(weibo_feed, "_PAUSE", 0)
    weibo_feed._store().unlink(missing_ok=True)
    yield state
    weibo_feed._store().unlink(missing_ok=True)


def test_search_asks_for_a_guest_session_first_then_pages_until_weibo_has_no_more(weibo_search):
    weibo_search["pages"] = [[_video("RnsVideo01"), _text("RnsText01")],
                             [_video("RnsVideo02"), _video("RnsVideo01"), _text("RnsText02")]]
    rows = weibo_feed.search("猫", take=5)
    assert [r["id"] for r in rows] == ["weibo:RnsVideo01", "weibo:RnsVideo02"]  # Weibo's order, one row per post
    assert [r["rank"] for r in rows] == [1, 2]
    assert [c.url.host for c in weibo_search["calls"]] == ["passport.weibo.com"] + ["weibo.com"] * 3
    searches = weibo_search["calls"][1:]
    assert [int(c.url.params["page"]) for c in searches] == [1, 2, 3]  # page 3 was empty: no more answers
    assert all(str(c.url.params["q"]) == "猫" for c in searches)
    assert all(c.url.path == "/ajax/statuses/search" for c in searches)
    assert all("SUB=guest-sub" in (c.headers.get("cookie") or "") for c in searches)
    assert all(c.headers.get("referer") == "https://weibo.com/" for c in searches)
    assert all(c.headers.get("x-requested-with") == "XMLHttpRequest" for c in searches)


def test_search_returns_the_clip_shape_and_remembers_the_mp4_address(weibo_search):
    weibo_search["pages"] = [[_video("RnsVideo01")]]
    r = weibo_feed.search("猫", take=5)[0]
    assert (r["id"], r["site"], r["url"]) == ("weibo:RnsVideo01", "weibo", "https://weibo.com/3266943013/RnsVideo01")
    assert r["title"] == "【#猫#】视频 RnsVideo01" and r["uploader"] == "央视网"
    assert (r["duration"], r["likes"], r["views"], r["pubdate"], r["rank"]) == (95, 69, None, 1_792_329_600, 1)
    assert r["thumbnail"].startswith("https://") and r["category"] is None
    assert weibo_feed.media_url("RnsVideo01") == MP4  # "Make video" can fetch the file


def test_search_stops_at_take_and_keeps_weibos_order(weibo_search):
    weibo_search["pages"] = [[_video("RnsVideo01"), _video("RnsVideo02"), _video("RnsVideo03")]]
    rows = weibo_feed.search("猫", take=2)
    assert [r["id"] for r in rows] == ["weibo:RnsVideo01", "weibo:RnsVideo02"]
    assert [r["rank"] for r in rows] == [1, 2]
    searches = [c for c in weibo_search["calls"] if c.url.host == "weibo.com"]
    assert [int(c.url.params["page"]) for c in searches] == [1]  # a second answer was not asked for
    assert weibo_feed.media_url("RnsVideo03") is None  # rows not returned are not remembered


def test_search_keeps_short_clips_like_the_account_mode(weibo_search):
    weibo_search["pages"] = [[_video("RnsShort01", 3), _video("RnsLong001", 120), _text("RnsText01")]]
    rows = weibo_feed.search("猫", take=5)
    assert [(r["id"], r["duration"]) for r in rows] == [("weibo:RnsShort01", 3), ("weibo:RnsLong001", 120)]


def test_search_gives_no_videos_when_the_answers_hold_none(weibo_search):
    weibo_search["pages"] = [[_text("RnsText01"), _text("RnsText02")]]
    with pytest.raises(weibo_feed.FeedError, match="no videos"):
        weibo_feed.search("猫")
    weibo_search["pages"] = []  # Weibo knows no post at all for the word
    with pytest.raises(weibo_feed.FeedError, match="no videos"):
        weibo_feed.search("猫")


def test_a_refusal_or_a_broken_answer_is_an_error(weibo_search):
    weibo_search["ok"] = 0
    with pytest.raises(weibo_feed.FeedError, match="200 ok 0"):
        weibo_feed.search("猫")
    weibo_search["ok"], weibo_search["html"] = 1, True
    with pytest.raises(weibo_feed.FeedError, match="200 not JSON"):
        weibo_feed.search("猫")


def test_one_bad_answer_does_not_lose_the_others(weibo_search):
    weibo_search["pages"] = [[_video("RnsVideo01")], [_video("RnsVideo02")], [_video("RnsVideo03")]]
    weibo_search["fail"] = {2}  # a page of search sometimes answers a 500
    rows = weibo_feed.search("猫", take=5)
    assert [r["id"] for r in rows] == ["weibo:RnsVideo01", "weibo:RnsVideo03"]


def test_without_the_guest_session_it_does_not_ask_for_answers(weibo_search):
    weibo_search["guest"] = False
    with pytest.raises(weibo_feed.FeedError, match="guest session"):
        weibo_feed.search("猫")
    assert [c.url.host for c in weibo_search["calls"]] == ["passport.weibo.com"]


@pytest.mark.parametrize("word", ["", "   ", "\n"])
def test_an_empty_keyword_is_refused(word):
    with pytest.raises(ValueError, match="hashtag or keyword"):
        weibo_feed.search(word)


def test_search_normalises_the_keyword(weibo_search):
    weibo_search["pages"] = [[_video("RnsVideo01")]]
    weibo_feed.search("  猫   视频  ")
    assert str(weibo_search["calls"][1].url.params["q"]) == "猫 视频"
