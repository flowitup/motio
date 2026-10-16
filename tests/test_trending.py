"""Bilibili trending lists (motio/trending.py) as watch sources: parsing, filtering, the weekly cookie dance, errors."""
import hashlib
import sqlite3
import time

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
    trending._wbi_cache.update(key=None, at=0.0)
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


def test_ranking_keeps_only_originals_that_may_be_reused(bili, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_REPRINT", "false")
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


def test_no_reprint_is_flagged_not_dropped_unless_the_setting_is_off(bili, monkeypatch):
    """Bilibili ticks "no reprint" by default (99 % of a ranking): dropping it would empty every list."""
    bili.answers["/x/web-interface/ranking/v2"] = {"code": 0, "data": {"list": [
        _video("BV1plain", rights={"no_reprint": 0}), _video("BV1ticked", rights={"no_reprint": 1}),
        _video("BV1paid", rights={"no_reprint": 1, "pay": 1})]}}
    rows = trending.fetch("bilibili:ranking:181")
    assert [(r["id"], r["no_reprint"]) for r in rows] == [("bilibili:BV1plain", 0), ("bilibili:BV1ticked", 1)]
    monkeypatch.setenv("ALLOW_NO_REPRINT", "false")
    assert [r["id"] for r in trending.fetch("bilibili:ranking:181")] == ["bilibili:BV1plain"]
    monkeypatch.setenv("ALLOW_NO_REPRINT", "true")
    wid = watch.add("bilibili:ranking:181")
    watch.check(db.get_watch(wid))
    assert db.get_clip("bilibili:BV1ticked")["no_reprint"] == 1  # kept on the row, shown as a flag in the app


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

    shown = db.list_clips("new")[0]  # says which list it came from, so the app can name it in its own language
    assert (shown["watch_kind"], shown["watch_target"]) == ("trending", "bilibili:ranking:181")

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


def test_categories_and_tags_parse_and_get_names():
    assert trending.parse("bilibili:category:ai") == ("category", "ai")
    assert trending.parse("bilibili:tag:AI短片") == ("tag", "AI短片")
    assert trending.name("bilibili:category:lifestyle") == "Bilibili · Lifestyle & savoir-vivre"
    assert trending.name("bilibili:tag:礼仪") == "Bilibili tag · 礼仪"
    for bad in ("bilibili:category:nope", "bilibili:category:", "bilibili:tag:", "bilibili:tag:  x",
                "bilibili:tag:a\nb", "bilibili:tag:" + "字" * 41):
        with pytest.raises(ValueError):
            trending.parse(bad)
    assert watch.classify("bilibili:category:tech")["kind"] == "trending"
    assert watch.classify("bilibili:tag:礼仪")["name"] == "Bilibili tag · 礼仪"


def test_usable_wants_a_clear_original():
    assert trending.usable(_video("BV1a")) and trending.usable(_video("BV1b", copyright=None))
    assert not trending.usable(_video("BV1c", copyright=3)) and not trending.usable(_video("BV1d", copyright=2))


def _bilibili_tags(bili, hits, details):
    """The nav pictures, anonymous cookies, a search that answers `hits` and a view that answers `details[bvid]`."""
    bili.answers["/x/frontend/finger/spi"] = {"code": 0, "data": {"b_3": "AAA", "b_4": "BBB"}}
    bili.answers["/x/web-interface/nav"] = {"code": -101, "message": "not logged in", "data": {"wbi_img": {
        "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
        "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caab00d94a2e8b6d1d7cf1b8ab7e.png"}}}
    bili.answers["/x/web-interface/wbi/search/type"] = {"code": 0, "data": {"result": [
        {"bvid": b, "typename": "软件 应用"} for b in hits]}}
    bili.answers["/x/web-interface/wbi/view"] = lambda req: (
        {"code": 0, "data": details[req.url.params["bvid"]]} if req.url.params["bvid"] in details
        else {"code": -404, "message": "gone"})


def test_a_tag_is_searched_signed_and_checked_for_rights(bili, monkeypatch):
    monkeypatch.setenv("ALLOW_NO_REPRINT", "false")
    _bilibili_tags(bili, ["BV1ok", "BV1repost", "BV1noreprint", "BV1three", "BV1gone", "BV1two"], {
        "BV1ok": _video("BV1ok", tname=""),
        "BV1repost": _video("BV1repost", copyright=2),
        "BV1noreprint": _video("BV1noreprint", rights={"no_reprint": 1}),
        "BV1three": _video("BV1three", copyright=3),
        "BV1two": _video("BV1two", stat={"view": 7, "like": 1}),
    })
    rows = trending.fetch("bilibili:tag:AI短片")
    assert [r["id"] for r in rows] == ["bilibili:BV1ok", "bilibili:BV1two"]
    assert rows[0]["category"] == "软件应用" and rows[0]["rank"] == 1  # the search's partition name, spaces dropped
    search = next(r for r in bili.calls if r.url.path.endswith("/search/type"))
    q = search.url.params
    assert (q["keyword"], q["order"], q["search_type"]) == ("AI短片", "click", "video")
    assert int(q["pubtime_end_s"]) - int(q["pubtime_begin_s"]) == trending.WINDOW_DAYS * 86400
    assert q["wts"].isdigit() and len(q["w_rid"]) == 32  # the wbi signature
    assert "buvid3=AAA" in search.headers["cookie"]
    views = [r for r in bili.calls if r.url.path.endswith("/wbi/view")]
    assert len(views) == 6 and all(len(r.url.params["w_rid"]) == 32 for r in views)
    assert sum(r.url.path.endswith("/nav") for r in bili.calls) == 1  # the key is read once for all of them


def test_the_wbi_signature_is_the_md5_of_the_sorted_clean_query_and_the_key():
    nav = {"code": -101, "data": {"wbi_img": {"img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                                              "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caab00d94a2e8b6d1d7cf1b8ab7e.png"}}}
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=nav)))
    key = trending._wbi_key(client)
    assert len(key) == 32 and set(key) <= set("7cd084941338484aae1ad9425b84077c4932caab00d94a2e8b6d1d7cf1b8ab7e")
    signed = trending._signed(client, {"zab": 1919810, "foo": "1(1)4!", "bar": "514"})
    query = f"bar=514&foo=114&wts={signed['wts']}&zab=1919810"  # sorted by name; ! ' ( ) * are dropped
    assert signed["w_rid"] == hashlib.md5((query + key).encode()).hexdigest()
    assert signed["foo"] == "1(1)4!"  # only the signature sees the cleaned value; the request keeps what was asked
    broken = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"code": -101})))
    trending._wbi_cache.update(key=None, at=0.0)
    with pytest.raises(trending.TrendingError, match="Could not reach Bilibili"):
        trending._wbi_key(broken)


def test_a_tag_stops_reading_once_it_has_enough(bili):
    hits = [f"BV1{i:03d}" for i in range(30)]
    _bilibili_tags(bili, hits, {b: _video(b) for b in hits})
    assert len(trending.fetch("bilibili:tag:AI", take=5)) == 5
    assert sum(r.url.path.endswith("/wbi/view") for r in bili.calls) == 8  # one batch of eight, not thirty


def test_a_category_mixes_its_ranking_and_its_tags(bili):
    now = int(time.time())
    _bilibili_tags(bili, ["BV1t1", "BV1t2"],
                   {"BV1t1": _video("BV1t1", pubdate=now), "BV1t2": _video("BV1t2", pubdate=now)})
    bili.answers["/x/web-interface/ranking/v2"] = {"code": 0, "data": {"list": [
        _video("BV1r1", pubdate=now), _video("BV1t1", pubdate=now), _video("BV1r2", copyright=2, pubdate=now),
        _video("BV1old", pubdate=now - 400 * 86400),  # a ranking also lists videos from last year
        _video("BV1r3", pubdate=now - 5 * 86400)]}}
    monkey = dict(trending.CATEGORIES)
    trending.CATEGORIES["mix"] = {"name": "Mix", "rankings": (188,), "tags": ("甲", "乙")}
    try:
        rows = trending.fetch("bilibili:category:mix")
    finally:
        trending.CATEGORIES.clear()
        trending.CATEGORIES.update(monkey)
    # first of each list, then second of each…, and a video seen twice once
    assert [r["id"] for r in rows] == ["bilibili:BV1r1", "bilibili:BV1t1", "bilibili:BV1t2", "bilibili:BV1r3"]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4]


def test_a_category_fails_only_when_every_part_fails(bili):
    _bilibili_tags(bili, ["BV1t1"], {"BV1t1": _video("BV1t1")})
    trending.CATEGORIES["mix"] = {"name": "Mix", "rankings": (188,), "tags": ("甲",)}
    try:
        bili.answers["/x/web-interface/ranking/v2"] = {"code": -352, "message": "-352"}
        assert [r["id"] for r in trending.fetch("bilibili:category:mix")] == ["bilibili:BV1t1"]  # the tag still answers
        bili.answers["/x/web-interface/wbi/search/type"] = {"code": -352, "message": "-352"}
        with pytest.raises(trending.TrendingError, match="blocked the request"):
            trending.fetch("bilibili:category:mix")
    finally:
        trending.CATEGORIES.pop("mix")


def test_a_category_is_a_watch_source_with_a_name(bili):
    wid = watch.add("bilibili:category:ai")
    bili.answers["/x/web-interface/wbi/search/type"] = {"code": 0, "data": {"result": []}}
    _bilibili_tags(bili, ["BV1a"], {"BV1a": _video("BV1a")})
    r = watch.check(db.get_watch(wid))
    assert r["error"] is None and r["new"] == ["bilibili:BV1a"]
    assert db.get_watch(wid)["name"] == "Bilibili · AI & tools"
