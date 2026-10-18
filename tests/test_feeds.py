"""AcFun rankings and Pear Video's home page (motio/feeds.py) as followed sources."""
import httpx
import pytest

from motio import db, feeds, trending, watch

PEAR = """
<li class="swiper-slide" style="background-image: url(https://image1.pearvideo.com/cont/20261016/cont-1807836-12808465.jpg);">
  <a href="video_1807836" class="actwapslide-link"><div class="actwapslidebd"><div class="actcont-playbd"></div>
  <div class="actwapslide-title">陈妤颉谈高考目标：大学最好不出省不出市</div></div></a>
  <div class="actcont-auto"><a href="author_14190390" class="column">一手Video</a></div>
</li>
<a href="video_1807825"><h2 class="vervideo-title">17岁男孩吃辣条 &amp; 查出结肠癌</h2><span>2分钟前</span></a>
<a href="video_1807825"><h2>same clip again</h2></a>
<a href="video_1807999"><img src="x.jpg"></a>
<a href="category_1">人物</a>
"""


def _item(cid, **kw):
    base = {"contentId": cid, "contentTitle": f"视频 {cid} &amp; 更多", "userName": "UP主", "duration": 120_000,
            "viewCount": 3000, "likeCount": 80, "createTimeMillis": 1_792_128_480_012, "channelName": "搞笑",
            "coverUrl": f"http://tx-free-imgs.acfun.cn/{cid}.png", "resourceType": "CONTENT_VIDEO"}
    return {**base, **kw}


@pytest.fixture
def sites(monkeypatch):
    """AcFun and Pear Video behind httpx.MockTransport. `answers`: host → body or callable(request)."""
    calls: list[httpx.Request] = []
    answers: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        a = answers.get(req.url.host)
        a = a(req) if callable(a) else a
        if a is None:
            return httpx.Response(404, text="nope")
        return httpx.Response(200, **({"text": a} if isinstance(a, str) else {"json": a}))

    monkeypatch.setattr(feeds, "_transport", httpx.MockTransport(handler))
    handler.answers, handler.calls = answers, calls
    return handler


def test_targets_parse_and_have_names():
    assert feeds.parse("acfun:rank") == ("acfun", None)
    assert feeds.parse("acfun:channel:201") == ("acfun", "201")
    assert feeds.parse("pearvideo:home") == ("pearvideo", None)
    assert feeds.name("acfun:channel:201") == "AcFun · Food"
    assert feeds.name("acfun:rank") == "AcFun ranking · all sections"
    assert feeds.name("pearvideo:home") == "Pear Video · today"
    for bad in ("acfun:channel:9999", "acfun:channel:", "acfun:other", "pearvideo:", "acfun:rank:1", "acfun:"):
        with pytest.raises(ValueError):
            feeds.parse(bad)
    assert all(feeds.parse(t) for t in feeds.TARGETS)


def test_acfun_ranking_becomes_clip_rows(sites):
    sites.answers["www.acfun.cn"] = {"result": 0, "rankList": [_item(1), _item(2, duration=5_000), _item(3)]}
    rows = feeds.fetch("acfun:rank")
    assert [r["id"] for r in rows] == ["acfun:1", "acfun:3"]  # a 5 s video is dropped
    assert rows[0] == {"id": "acfun:1", "site": "acfun", "url": "https://www.acfun.cn/v/ac1", "title": "视频 1 & 更多",
                       "uploader": "UP主", "duration": 120, "views": 3000, "likes": 80, "pubdate": 1_792_128_480.012,
                       "category": "搞笑", "thumbnail": "https://tx-free-imgs.acfun.cn/1.png", "rank": 1}
    assert rows[1]["rank"] == 3  # the rank on the site, not in the kept list
    req = sites.calls[0]
    assert req.url.params["channelId"] == "" and req.url.params["rankPeriod"] == "DAY"
    assert "acfun.cn" in req.headers["referer"]


def test_a_section_asks_for_its_channel_and_skips_articles(sites):
    sites.answers["www.acfun.cn"] = {"result": 0, "rankList": [
        _item(1, resourceType="CONTENT_ARTICLE", duration=None), _item(2), "junk"]}
    rows = feeds.fetch("acfun:channel:201")
    assert [r["id"] for r in rows] == ["acfun:2"]
    assert sites.calls[0].url.params["channelId"] == "201"


@pytest.mark.parametrize("body", [{"result": 1, "rankList": []}, {"nothing": 1}, [], "not json"])
def test_acfun_errors_are_trending_errors(sites, body):
    sites.answers["www.acfun.cn"] = body
    with pytest.raises(trending.TrendingError, match="AcFun"):
        feeds.fetch("acfun:rank")


def test_acfun_down_is_reported(sites):
    with pytest.raises(trending.TrendingError, match="AcFun returned an error"):
        feeds.fetch("acfun:rank")  # the mock answers 404


def test_pear_video_home_page_clips():
    rows = feeds.pear_clips(PEAR)
    assert [r["id"] for r in rows] == ["pearvideo:1807836", "pearvideo:1807825"]  # no title, no clip; each clip once
    assert rows[0]["title"] == "陈妤颉谈高考目标：大学最好不出省不出市"
    assert rows[0]["url"] == "https://www.pearvideo.com/video_1807836"
    assert rows[0]["thumbnail"] == "https://image1.pearvideo.com/cont/20261016/cont-1807836-12808465.jpg"
    assert rows[1]["title"] == "17岁男孩吃辣条 & 查出结肠癌" and rows[1]["thumbnail"] is None
    assert [r["rank"] for r in rows] == [1, 2] and rows[0]["duration"] is None


def test_pear_video_fetch_and_empty_page(sites):
    sites.answers["www.pearvideo.com"] = PEAR
    assert len(feeds.fetch("pearvideo:home")) == 2
    sites.answers["www.pearvideo.com"] = "<html>changed</html>"
    with pytest.raises(trending.TrendingError, match="Pear Video"):
        feeds.fetch("pearvideo:home")


# ---------- followed sources ----------
@pytest.fixture
def clean():
    with db.conn() as c:
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")
    yield
    with db.conn() as c:  # a followed source must not reach the next test file
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")


def test_classify_and_add_follow_a_feed(clean):
    w = watch.classify("acfun:channel:201")
    assert (w["kind"], w["site"], w["target"], w["name"]) == ("trending", "acfun", "acfun:channel:201", "AcFun · Food")
    assert watch.classify("pearvideo:home")["site"] == "pearvideo"
    with pytest.raises(ValueError):
        watch.classify("acfun:channel:9999")
    wid = watch.add("pearvideo:home")
    with pytest.raises(ValueError, match="already"):
        watch.add("pearvideo:home")
    assert db.get_watch(wid)["site"] == "pearvideo"


def test_checking_a_feed_stores_its_new_videos(clean, sites):
    sites.answers["www.acfun.cn"] = {"result": 0, "rankList": [_item(i) for i in range(1, 4)]}
    wid = watch.add("acfun:rank")
    result = watch.check(db.get_watch(wid))
    assert result["error"] is None and len(result["new"]) == 3
    clips = db.list_clips("new", wid)
    assert {c["id"] for c in clips} == {"acfun:1", "acfun:2", "acfun:3"} and clips[0]["site"] == "acfun"
    assert watch.check(db.get_watch(wid))["new"] == []  # seen before


def test_a_feed_that_fails_is_noted_on_the_source(clean, sites):
    wid = watch.add("acfun:rank")
    result = watch.check(db.get_watch(wid))
    assert "AcFun" in result["error"] and db.get_watch(wid)["last_checked"] is None
