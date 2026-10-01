"""Bilibili trending lists (motio/trending.py) as watch sources: parsing, filtering, the weekly cookie dance, errors."""
import sqlite3

import httpx
import pytest

from motio import db, llm, trending, watch


def _video(bvid, **kw):
    base = {"bvid": bvid, "title": f"视频 {bvid}", "duration": 120, "pubdate": 1_790_000_000, "copyright": 1,
            "tname": "影视杂谈", "pic": f"http://i0.hdslb.com/{bvid}.jpg", "owner": {"mid": 1, "name": "UP主"},
            "stat": {"view": 100_000, "like": 5000}, "rights": {"no_reprint": 0, "pay": 0, "movie": 0}}
    return {**base, **kw}


@pytest.fixture
def bili(monkeypatch):
    """Bilibili giả qua httpx.MockTransport. `answers`: path → body; `calls`: request đã nhận."""
    calls: list[httpx.Request] = []
    answers: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        a = answers.get(req.url.path)
        if callable(a):
            a = a(req)
        if a is None:
            return httpx.Response(404, json={"code": -404, "message": "not found"})
        return httpx.Response(200, json=a)

    monkeypatch.setattr(trending, "_transport", httpx.MockTransport(handler))
    bili_calls = calls
    handler.answers, handler.calls = answers, bili_calls
    return handler


@pytest.fixture(autouse=True)
def clean():
    with db.conn() as c:
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")


def test_parse_and_name():
    assert trending.parse("bilibili:ranking:181") == ("ranking", 181)
    assert trending.parse("bilibili:popular") == ("popular", None)
    assert trending.parse("bilibili:weekly") == ("weekly", None)
    assert trending.name("bilibili:ranking:181") == "Bilibili ranking · Film & TV"
    for bad in ("bilibili:ranking:999", "bilibili:ranking", "bilibili:popular:1", "popular", "bilibili:",
                "ranking:181"):
        with pytest.raises(ValueError):
            trending.parse(bad)


def test_ranking_keeps_only_originals_that_may_be_reused(bili):
    bili.answers["/x/web-interface/ranking/v2"] = {"code": 0, "data": {"list": [
        _video("BV1ok"),
        _video("BV1repost", copyright=2),
        _video("BV1noreprint", rights={"no_reprint": 1}),
        _video("BV1paid", rights={"pay": 1}),
        _video("BV1film", rights={"movie": 1}),
        _video("BV1ogv", is_ogv=True),
        _video("BV1short", duration=8),
        {"title": "no id"},
        _video("BV1two", stat={"view": 7, "like": 1}, tname="知识"),
    ]}}
    rows = trending.fetch("bilibili:ranking:181")
    assert [r["id"] for r in rows] == ["bilibili:BV1ok", "bilibili:BV1two"]
    ok = rows[0]
    assert ok["url"] == "https://www.bilibili.com/video/BV1ok" and ok["uploader"] == "UP主"
    assert (ok["views"], ok["likes"], ok["duration"], ok["category"], ok["rank"]) == (100_000, 5000, 120, "影视杂谈", 1)
    assert ok["thumbnail"] == "https://i0.hdslb.com/BV1ok.jpg" and ok["pubdate"] == 1_790_000_000
    assert rows[1]["rank"] == 9  # the place in the list, not in the kept rows
    req = bili.calls[0]
    assert req.url.params["rid"] == "181" and req.url.params["type"] == "all"
    assert req.headers["user-agent"] == trending.UA and "Chrome/" in req.headers["user-agent"]  # a short UA gets -352
    assert req.headers["referer"] == "https://www.bilibili.com"


def test_popular_uses_the_popular_endpoint(bili):
    bili.answers["/x/web-interface/popular"] = {"code": 0, "data": {"list": [_video("BV1p")], "no_more": False}}
    assert [r["id"] for r in trending.fetch("bilibili:popular")] == ["bilibili:BV1p"]
    assert bili.calls[0].url.path == "/x/web-interface/popular"


def test_weekly_needs_the_anonymous_buvid_cookies_and_the_latest_number(bili):
    bili.answers["/x/frontend/finger/spi"] = {"code": 0, "data": {"b_3": "AAA", "b_4": "BBB"}}
    bili.answers["/x/web-interface/popular/series/list"] = {"code": 0, "data": {"list": [
        {"number": 391, "subject": "a"}, {"number": 392, "subject": "b"}, {"number": 390, "subject": "c"}]}}
    bili.answers["/x/web-interface/popular/series/one"] = {"code": 0, "data": {"config": {}, "list": [_video("BV1w")]}}
    rows = trending.fetch("bilibili:weekly")
    assert [r["id"] for r in rows] == ["bilibili:BV1w"]
    last = bili.calls[-1]
    assert last.url.path.endswith("/series/one") and last.url.params["number"] == "392"
    assert last.headers["referer"] == "https://www.bilibili.com/v/popular/weekly?num=392"
    assert last.headers["origin"] == "https://www.bilibili.com"
    assert "buvid3=AAA" in last.headers["cookie"] and "buvid4=BBB" in last.headers["cookie"]


def test_blocked_and_broken_answers_are_explained(bili):
    path = "/x/web-interface/ranking/v2"
    bili.answers[path] = {"code": -352, "message": "-352"}
    with pytest.raises(trending.TrendingError, match="blocked the request"):
        trending.fetch("bilibili:ranking:0")
    bili.answers[path] = {"code": -400, "message": "bad rid"}
    with pytest.raises(trending.TrendingError, match="bad rid"):
        trending.fetch("bilibili:ranking:0")
    bili.answers[path] = ["not", "a", "dict"]
    with pytest.raises(trending.TrendingError):
        trending.fetch("bilibili:ranking:0")
    bili.answers.pop(path)  # 404
    with pytest.raises(trending.TrendingError):
        trending.fetch("bilibili:ranking:0")


def test_a_trending_list_is_a_watch_source(bili):
    wid = watch.add("bilibili:ranking:181")
    w = db.get_watch(wid)
    assert (w["kind"], w["site"], w["target"], w["name"]) == ("trending", "bilibili", "bilibili:ranking:181",
                                                              "Bilibili ranking · Film & TV")
    with pytest.raises(ValueError, match="already"):
        watch.add("bilibili:ranking:181")
    with pytest.raises(ValueError, match="Unknown Bilibili"):
        watch.add("bilibili:ranking:999")

    top = [_video(f"BV1{i:03d}") for i in range(30)]
    bili.answers["/x/web-interface/ranking/v2"] = {"code": 0, "data": {"list": top}}
    r = watch.check(db.get_watch(wid))
    assert len(r["new"]) == watch.TRENDING_TAKE and r["error"] is None  # the top of the list; the rest counts as seen
    assert len(db.list_clips("old")) == 10
    w = db.get_watch(wid)
    assert w["last_checked"] and w["last_error"] is None and w["name"] == "Bilibili ranking · Film & TV"
    c = db.get_clip("bilibili:BV1000")
    assert (c["likes"], c["category"], c["rank"], c["views"], c["watch_name"]) == (
        5000, "影视杂谈", 1, 100_000, "Bilibili ranking · Film & TV")

    bili.answers["/x/web-interface/ranking/v2"] = {"code": 0, "data": {"list": [_video("BV1new"), *top]}}
    assert watch.check(db.get_watch(wid))["new"] == ["bilibili:BV1new"]  # only what entered the list


def test_a_refused_check_is_kept_on_the_watch_and_retried(bili):
    wid = watch.add("bilibili:popular")
    bili.answers["/x/web-interface/popular"] = {"code": -352, "message": "-352"}
    r = watch.check(db.get_watch(wid))
    w = db.get_watch(wid)
    assert r["new"] == [] and "blocked the request" in w["last_error"] and w["last_checked"] is None
    bili.answers["/x/web-interface/popular"] = {"code": 0, "data": {"list": [_video("BV1p")]}}
    assert watch.check(db.get_watch(wid))["new"] == ["bilibili:BV1p"]
    assert db.get_watch(wid)["last_error"] is None


def test_scoring_sees_category_likes_and_age(bili, monkeypatch):
    wid = watch.add("bilibili:ranking:181")
    bili.answers["/x/web-interface/ranking/v2"] = {"code": 0, "data": {"list": [_video("BV1a")]}}
    prompts = []

    def fake_ask(prompt, system, effort=None, **kw):
        prompts.append(prompt)
        return [{"id": "bilibili:BV1a", "title_fr": "Le panda", "score": 77, "reason": "dialogue court"}]

    monkeypatch.setattr(llm, "ask_json", fake_ask)
    assert watch.check_all([wid])["scored"] == 1
    line = next(ln for ln in prompts[0].splitlines() if '"bilibili:BV1a"' in ln)
    assert '"catégorie": "影视杂谈"' in line and '"likes": 5000' in line and '"âge_h":' in line
    assert "classement Bilibili" in prompts[0] and "droit de reprendre" in prompts[0]
    assert db.get_clip("bilibili:BV1a")["score"] == 77


def test_old_databases_get_the_new_clip_columns():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE clip (id TEXT PRIMARY KEY, title TEXT)")
    db._migrate(c)
    db._migrate(c)  # twice: a second start must not fail
    cols = {r[1] for r in c.execute("PRAGMA table_info(clip)")}
    assert cols >= {"id", "title", "likes", "pubdate", "category", "rank"}
