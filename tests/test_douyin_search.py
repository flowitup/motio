"""Douyin keyword search (motio/douyin_feed.search) as `clip` rows. f2 is switched off in tests: `_search_page` and
the owner's cookies are faked, so no test touches Douyin."""
import httpx
import pytest

from motio import douyin_feed


def _item(pid, **kw) -> dict:
    """One general-search card: {"type": 1, "aweme_info": {...post...}}, the shape Douyin answers with."""
    post = {"aweme_id": pid, "desc": f"搜索 {pid} #话题", "create_time": 1_790_000_000,
            "video": {"duration": 34000, "cover": {"url_list": [f"https://p3.douyinpic.com/{pid}.jpeg"]}},
            "statistics": {"digg_count": 2354, "play_count": 98765}, "author": {"nickname": "作者"}}
    post.update(kw)
    return {"type": 1, "aweme_info": post}


def _answer(items, has_more=False, cursor=20, impr_id="IMPR-1") -> dict:
    return {"status_code": 0, "data": items, "has_more": has_more, "cursor": cursor, "log_pb": {"impr_id": impr_id}}


@pytest.fixture
def api(monkeypatch):
    """The answers of the search: one list per call, the calls made, an error to raise, the owner's cookies."""
    state = {"pages": [], "calls": [], "raise": None, "cookies": {}, "seen_cookies": []}

    async def page(keyword, offset, count, search_id, cookies):
        state["calls"].append({"keyword": keyword, "offset": offset, "count": count, "search_id": search_id})
        state["seen_cookies"].append(cookies)
        if state["raise"]:
            raise state["raise"]
        return state["pages"][min(len(state["calls"]) - 1, len(state["pages"]) - 1)] if state["pages"] else {}

    monkeypatch.setattr(douyin_feed, "_search_page", page)
    monkeypatch.setattr(douyin_feed, "_cookies", lambda: state["cookies"])
    monkeypatch.setattr(douyin_feed, "_PAUSE", 0)
    return state


def test_search_makes_clip_rows_and_skips_photos_ads_and_no_id(api):
    api["pages"] = [_answer([
        _item("7000000000000000001", desc="  美食   探店  "),
        _item("7000000000000000002", video={"duration": 4000}),  # a short clip still matches the keyword
        _item("7000000000000000003", images=[{"x": 1}]),  # a photo post
        _item("7000000000000000004", is_ads=True),
        {"type": 1, "aweme_info": {"aweme_id": "abc"}},  # not a post id
        {"type": 68, "aweme_info": {"images": [{"x": 1}]}},
        "not a card",
    ])]
    rows = douyin_feed.search("美食", take=2)
    assert [r["id"] for r in rows] == ["douyin:7000000000000000001", "douyin:7000000000000000002"]
    r = rows[0]
    assert (r["site"], r["url"], r["title"], r["rank"]) == (
        "douyin", "https://www.douyin.com/video/7000000000000000001", "美食 探店", 1)
    assert (r["uploader"], r["duration"], r["views"], r["likes"], r["pubdate"]) == (
        "作者", 34, 98765, 2354, 1_790_000_000)
    assert r["thumbnail"].startswith("https://") and r["category"] is None
    assert rows[1]["duration"] == 4 and rows[1]["rank"] == 2
    # the keyword and the first page's request are what the web page sends
    assert api["calls"] == [{"keyword": "美食", "offset": 0, "count": 2, "search_id": ""}]


def test_a_card_that_is_the_post_itself_is_accepted(api):
    api["pages"] = [_answer([_item("7000000000000000001")["aweme_info"],
                             {"type": 2, "user_list": [{"sec_uid": "MS4wLjAB"}]}])]
    assert [r["id"] for r in douyin_feed.search("美食")] == ["douyin:7000000000000000001"]


def test_search_pages_with_offset_and_search_id_and_keeps_repeats_out(api):
    api["pages"] = [
        _answer([_item("7000000000000000001"), _item("7000000000000000002"), _item("7000000000000000003")],
                has_more=True, cursor=20, impr_id="IMPR-1"),
        _answer([_item("7000000000000000002"), _item("7000000000000000004")], has_more=False, cursor=40,
                impr_id="IMPR-2"),
    ]
    rows = douyin_feed.search("美食", take=20)
    assert [r["id"] for r in rows] == [f"douyin:700000000000000000{i}" for i in (1, 2, 3, 4)]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4]
    assert api["calls"] == [
        {"keyword": "美食", "offset": 0, "count": 20, "search_id": ""},
        {"keyword": "美食", "offset": 20, "count": 17, "search_id": "IMPR-1"},
    ]


def test_search_stops_at_take(api):
    api["pages"] = [_answer([_item("7000000000000000001"), _item("7000000000000000001"),
                             _item("7000000000000000002"), _item("7000000000000000003"),
                             _item("7000000000000000004")], has_more=True, cursor=20)]
    rows = douyin_feed.search("美食", take=3)
    assert [r["id"] for r in rows] == [f"douyin:700000000000000000{i}" for i in (1, 2, 3)]
    assert len(api["calls"]) == 1


def test_search_take_is_capped_at_100(api):
    api["pages"] = [_answer([_item(f"{7000000000000000000 + n * 20 + i:019d}") for i in range(20)],
                            has_more=True, cursor=(n + 1) * 20, impr_id=f"IMPR-{n + 1}") for n in range(6)]
    rows = douyin_feed.search("美食", take=500)
    assert len(rows) == douyin_feed.TAKE_MAX == 100
    assert [r["rank"] for r in rows] == list(range(1, 101))
    assert len(api["calls"]) == 5  # 5 answers of 20 rows each
    assert {c["count"] for c in api["calls"]} == {20}


def test_a_refusal_after_the_first_answer_keeps_what_was_read(api):
    api["pages"] = [
        _answer([_item("7000000000000000001")], has_more=True, cursor=20),
        {"status_code": 2483, "status_msg": "请先登录，再继续搜索吧"},
    ]
    assert [r["id"] for r in douyin_feed.search("美食")] == ["douyin:7000000000000000001"]


def test_login_refusal_says_where_to_set_the_cookies(api):
    api["pages"] = [{"status_code": 2483, "status_msg": "请先登录，再继续搜索吧"}]
    with pytest.raises(douyin_feed.FeedError, match="login before it shows search results"):
        douyin_feed.search("美食")
    with pytest.raises(douyin_feed.FeedError, match="Settings → Browser cookies"):
        douyin_feed.search("美食")


def test_risk_control_refusal_is_said_as_such(api):
    api["pages"] = [{"status_code": 0, "data": [],
                     "search_nil_info": {"search_nil_type": "antispam_check", "search_nil_item": "hit_shark"}}]
    with pytest.raises(douyin_feed.FeedError, match="refused the search"):
        douyin_feed.search("美食")


def test_another_status_code_is_an_error(api):
    api["pages"] = [{"status_code": 2154, "status_msg": "something"}]
    with pytest.raises(douyin_feed.FeedError, match="Douyin returned an error: 2154 something"):
        douyin_feed.search("美食")


def test_the_owner_cookies_are_sent_when_set_up(api):
    api["cookies"] = {"sessionid": "x", "ttwid": "t"}
    api["pages"] = [_answer([_item("7000000000000000001")])]
    douyin_feed.search("美食")
    assert api["seen_cookies"] == [{"sessionid": "x", "ttwid": "t"}]


def test_a_keyword_with_no_videos_says_so(api):
    api["pages"] = [_answer([], has_more=False, cursor=0)]
    with pytest.raises(douyin_feed.FeedError, match="gave no videos for this keyword"):
        douyin_feed.search("美食")


def test_an_empty_keyword_is_refused_before_any_request(api):
    with pytest.raises(douyin_feed.FeedError, match="Type a keyword"):
        douyin_feed.search("   ")
    assert api["calls"] == []


def test_offline_and_f2_errors_are_said_once(api):
    api["raise"] = httpx.ConnectError("no route")
    with pytest.raises(douyin_feed.FeedError, match="Could not connect to Douyin"):
        douyin_feed.search("美食")
    api["raise"] = RuntimeError("f2 is switched off in tests")
    with pytest.raises(douyin_feed.FeedError, match="Douyin returned an error: f2 is switched off"):
        douyin_feed.search("美食")
