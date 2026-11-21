"""Douyin's home feed (motio/douyin_feed.py) as a watch source. f2 is switched off in tests: `_page` is faked."""
import time

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


# ---------- the hot board ----------
NOW = 1_790_100_000


def _word(word, hot, sid):
    return {"word": word, "hot_value": hot, "sentence_id": sid, "group_id": "7600000000000000000"}


def _board(*words):
    return {"data": {"word_list": list(words)}}


@pytest.fixture
def hot(monkeypatch, feed):
    """The hot board and the browser, faked. `state`: the board's answer, the browser's answer, what it was asked."""
    from motio import chrome
    state = {"board": _board(_word("话题一", 900, "1"), _word("话题二", 800, "2"), _word("话题三", 700, "3")),
             "answer": None, "asked": [], "raise": None, "board_raise": None}

    async def board():
        if state["board_raise"]:
            raise state["board_raise"]
        return state["board"]

    def evaluate(url, script, timeout=60):
        state["asked"].append((url, script))
        if state["raise"]:
            raise state["raise"]
        return state["answer"]

    monkeypatch.setattr(douyin_feed, "_board", board)
    monkeypatch.setattr(chrome, "evaluate", evaluate)
    monkeypatch.setattr(time, "time", lambda: NOW)
    return state


def _topic(word, *posts):
    return {"word": word, "rows": list(posts)}


def _fresh(pid, **kw):
    return _post(pid, create_time=NOW - 86400, **kw)


def test_hot_target_parses_and_is_named():
    assert douyin_feed.parse("douyin:hot") == "hot"
    assert douyin_feed.name("douyin:hot") == "Douyin hot board"


def test_hot_rows_follow_the_boards_order_and_carry_their_topic(hot):
    hot["answer"] = {"error": None, "topics": [
        _topic("话题一", _fresh("7000000000000000001"), _fresh("7000000000000000002")),
        _topic("话题二", _fresh("7000000000000000003"))]}
    rows = douyin_feed.fetch("douyin:hot")
    assert [r["id"] for r in rows] == ["douyin:7000000000000000001", "douyin:7000000000000000002",
                                       "douyin:7000000000000000003"]
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert [r["category"] for r in rows] == ["话题一", "话题一", "话题二"]
    assert rows[0]["views"] == 900  # the topic's heat, since a search card carries no play count
    url, script = hot["asked"][0]
    assert "so.douyin.com" in url and "%E8%AF%9D%E9%A2%98%E4%B8%80" in url  # the page opens on the first topic
    assert '["话题一", "话题二", "话题三"]' in script


def test_hot_keeps_only_recent_short_free_videos_a_few_per_topic(hot):
    old = _post("7000000000000000009", create_time=NOW - 30 * 86400)
    short = _fresh("7000000000000000008", video={"duration": 9000})
    photo = _fresh("7000000000000000007", images=[{"x": 1}])
    many = [_fresh(f"70000000000000001{i}") for i in range(6)]
    hot["answer"] = {"error": None, "topics": [
        _topic("话题一", old, short, photo, *many),
        _topic("话题二", many[0], _fresh("7000000000000000020"))]}
    rows = douyin_feed.fetch("douyin:hot")
    assert [r["id"] for r in rows if r["category"] == "话题一"] == [f"douyin:70000000000000001{i}" for i in range(3)]
    assert [r["id"] for r in rows if r["category"] == "话题二"] == ["douyin:7000000000000000020"]  # no repeat


def test_hot_take_limits_the_rows(hot):
    hot["answer"] = {"error": None, "topics": [_topic("话题一", *[_fresh(f"700000000000000010{i}") for i in range(3)])]}
    assert len(douyin_feed.fetch("douyin:hot", 2)) == 2


def test_hot_topics_are_capped_and_empty_or_repeated_words_skipped(hot):
    hot["board"] = _board(*[_word(f"话题{i}", 100 - i, str(i)) for i in range(40)], _word("", 1, "x"),
                          _word("话题0", 1, "y"))
    hot["answer"] = {"error": None, "topics": [_topic("话题0", _fresh("7000000000000000001"))]}
    douyin_feed.fetch("douyin:hot")
    assert hot["asked"][0][1].count("话题") == douyin_feed.HOT_TOPICS


def test_a_refusal_after_the_first_topics_keeps_what_was_read(hot):
    hot["answer"] = {"error": "antispam_check", "topics": [_topic("话题一", _fresh("7000000000000000001"))]}
    assert [r["id"] for r in douyin_feed.fetch("douyin:hot")] == ["douyin:7000000000000000001"]


def test_a_browser_check_with_nothing_read_is_reported(hot):
    hot["answer"] = {"error": "verify_check", "topics": []}
    with pytest.raises(douyin_feed.FeedError, match="browser verification"):
        douyin_feed.fetch("douyin:hot")


def test_no_recent_video_says_so(hot):
    stale = _post("7000000000000000001", create_time=NOW - 99 * 86400)
    hot["answer"] = {"error": None, "topics": [_topic("话题一", stale)]}
    with pytest.raises(douyin_feed.FeedError, match="no recent videos"):
        douyin_feed.fetch("douyin:hot")


def test_the_board_failing_is_said_once(hot):
    hot["board_raise"] = httpx.ConnectError("no route")
    with pytest.raises(douyin_feed.FeedError, match="Could not connect to Douyin"):
        douyin_feed.fetch("douyin:hot")
    hot["board_raise"] = RuntimeError("signature out of date")
    with pytest.raises(douyin_feed.FeedError, match="Douyin returned an error: signature out of date"):
        douyin_feed.fetch("douyin:hot")
    hot["board_raise"] = None
    hot["board"] = _board()
    with pytest.raises(douyin_feed.FeedError, match="hot board gave no topics"):
        douyin_feed.fetch("douyin:hot")
    assert hot["asked"] == []  # no browser for an empty board


def test_no_chrome_says_to_install_it_and_a_chrome_failure_says_why(hot):
    from motio import chrome
    hot["raise"] = chrome.Missing("nope")
    with pytest.raises(douyin_feed.FeedError, match="needs Google Chrome"):
        douyin_feed.fetch("douyin:hot")
    hot["raise"] = chrome.ChromeError("no port")
    with pytest.raises(douyin_feed.FeedError, match="Could not run Google Chrome for the Douyin hot board: no port"):
        douyin_feed.fetch("douyin:hot")


def test_follow_and_check_the_hot_board_saves_the_videos(hot):
    hot["answer"] = {"error": None, "topics": [_topic("话题一", _fresh("7000000000000000001"))]}
    wid = watch.add("douyin:hot")
    assert (db.get_watch(wid)["site"], db.get_watch(wid)["name"]) == ("douyin", "Douyin hot board")
    watch.check(db.get_watch(wid))
    rows = db.list_clips("new", wid)
    assert [(r["id"], r["category"]) for r in rows] == [("douyin:7000000000000000001", "话题一")]


def test_the_search_script_still_has_its_shared_card_reader():
    assert "rowOf(card)" in douyin_feed.WEB_SCRIPT and "rowOf(card)" in douyin_feed.HOT_SCRIPT
    assert "__COMMON__" not in douyin_feed.WEB_SCRIPT + douyin_feed.HOT_SCRIPT
