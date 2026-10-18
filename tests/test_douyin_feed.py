"""Douyin's home feed (motio/douyin_feed.py) as a watch source. f2 is switched off in tests: `_page` is faked."""
import httpx
import pytest

from motio import db, douyin, douyin_feed, watch


def _post(pid, **kw):
    base = {"aweme_id": pid, "desc": f"视频 {pid} #话题", "create_time": 1_790_000_000,
            "video": {"duration": 34000, "cover": {"url_list": [f"https://p3.douyinpic.com/{pid}.jpeg"]}},
            "statistics": {"digg_count": 2354, "play_count": 0}, "author": {"nickname": "作者"}}
    return {**base, **kw}


@pytest.fixture
def feed(monkeypatch):
    """The answers of the feed. `state`: one list of posts per call, the calls made, an error to raise."""
    state = {"answers": [[_post("7000000000000000001"), _post("7000000000000000002")]], "calls": [], "raise": None}

    async def page(index):
        state["calls"].append(index)
        if state["raise"]:
            raise state["raise"]
        answers = state["answers"]
        return {"aweme_list": answers[min(index - 1, len(answers) - 1)]}

    monkeypatch.setattr(douyin_feed, "_page", page)
    monkeypatch.setattr(douyin_feed, "_PAUSE", 0)
    with db.conn() as c:
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")
    yield state
    with db.conn() as c:  # the watch a test followed must not reach the next test file
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")


def test_parse_and_name():
    assert douyin_feed.parse("douyin:feed") == "feed"
    assert douyin_feed.name("douyin:feed") == "Douyin feed"
    for bad in ("douyin:", "douyin:feed:1", "kuaishou:featured", "feed"):
        with pytest.raises(ValueError):
            douyin_feed.parse(bad)


def test_fetch_makes_rows_and_skips_photos_ads_short_and_repeats(feed):
    feed["answers"] = [[_post("7000000000000000001"), _post("7000000000000000002", images=[{"x": 1}]),
                        _post("7000000000000000003", is_ads=True),
                        _post("7000000000000000004", video={"duration": 9000}),
                        _post("7000000000000000005", desc=" "), _post("abc")]]
    rows = douyin_feed.fetch("douyin:feed")
    assert [r["id"] for r in rows] == ["douyin:7000000000000000001"]  # the same answer every call: one row
    assert feed["calls"] == list(range(1, douyin_feed.PAGES + 1))
    r = rows[0]
    assert (r["site"], r["url"], r["rank"]) == ("douyin", "https://www.douyin.com/video/7000000000000000001", 1)
    assert (r["title"], r["uploader"], r["duration"], r["likes"], r["views"]) == ("视频 7000000000000000001 #话题",
                                                                                  "作者", 34, 2354, None)
    assert r["thumbnail"].startswith("https://") and r["pubdate"] == 1_790_000_000


def test_a_later_failure_keeps_what_was_read(feed, monkeypatch):
    async def page(index):
        if index == 2:
            raise RuntimeError("signature out of date")
        return {"aweme_list": [_post("7000000000000000001")]}

    monkeypatch.setattr(douyin_feed, "_page", page)
    assert [r["id"] for r in douyin_feed.fetch("douyin:feed")] == ["douyin:7000000000000000001"]


def test_nothing_read_says_why(feed):
    feed["raise"] = httpx.ConnectError("no route")
    with pytest.raises(douyin_feed.FeedError, match="Could not connect to Douyin"):
        douyin_feed.fetch("douyin:feed")
    feed["raise"] = RuntimeError("f2 is switched off in tests")
    with pytest.raises(douyin_feed.FeedError, match="Douyin returned an error: f2 is switched off"):
        douyin_feed.fetch("douyin:feed")
    feed["raise"] = None
    feed["answers"] = [[]]
    with pytest.raises(douyin_feed.FeedError, match="gave no videos"):
        douyin_feed.fetch("douyin:feed")


def test_follow_and_check_saves_the_videos(feed):
    wid = watch.add("douyin:feed")
    w = db.get_watch(wid)
    assert (w["kind"], w["site"], w["name"]) == ("trending", "douyin", "Douyin feed")
    with pytest.raises(ValueError):
        watch.add("douyin:feed")
    watch.check(w)
    assert {r["id"] for r in db.list_clips("new", wid)} == {"douyin:7000000000000000001", "douyin:7000000000000000002"}
    feed["raise"] = httpx.ConnectError("no route")
    watch.check(db.get_watch(wid))
    assert "Could not connect to Douyin" in (db.get_watch(wid)["last_error"] or "")


def test_a_row_downloads_like_any_douyin_link():
    assert douyin.find_id("https://www.douyin.com/video/7000000000000000001") == "7000000000000000001"
