"""Kuaishou's featured feed (motio/kuaishou_feed.py) as a watch source, and the download from the feed's mp4 address."""
import httpx
import pytest

from motio import db, douyin, kuaishou, kuaishou_feed, qa, watch

MP4 = "https://v23-3.kwaicdn.com/upic/2026/08/22/a.mp4?pkey=abc"


def _feed(pid, **kw):
    photo = {"id": pid, "duration": 34033, "caption": f"视频 {pid} #标签", "viewCount": "1.6万", "likeCount": "2354",
             "timestamp": 1_787_549_981_003, "coverUrl": f"https://p2.a.yximgs.com/{pid}.jpg", "photoUrl": MP4}
    return {"type": 1, "author": {"id": "u1", "name": "作者"}, "photo": {**photo, **kw}}


@pytest.fixture
def kuaishou_site(monkeypatch):
    """Kuaishou's GraphQL and CDN behind httpx.MockTransport. `state`: feeds per answer, calls, the mp4 bytes."""
    state = {"feeds": [_feed("3xaaaaaaaaaaaaa"), _feed("3xbbbbbbbbbbbbb")], "result": 1, "status": 200, "calls": [],
             "mp4": b"v" * 4000, "type": "video/mp4"}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"].append(str(req.url))
        if req.url.host == "www.kuaishou.com":
            body = {"data": {"brilliantTypeData": {"result": state["result"], "pcursor": "1", "feeds": state["feeds"]}}}
            return httpx.Response(state["status"], json=body)
        return httpx.Response(200, content=state["mp4"], headers={"content-type": state["type"]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(kuaishou_feed, "_transport", transport)
    monkeypatch.setattr(kuaishou, "_transport", transport)
    monkeypatch.setattr(douyin, "_resolve_host", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(kuaishou, "tool", lambda: None)  # videodl is not there: only the feed's address can work
    monkeypatch.setattr(qa, "probe", lambda path: {"duration": 34.0, "video": {"width": 720, "height": 1280}})
    kuaishou_feed._store().unlink(missing_ok=True)
    with db.conn() as c:
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")
    return state


def test_parse_and_name():
    assert kuaishou_feed.parse("kuaishou:featured") == "featured"
    assert kuaishou_feed.name("kuaishou:featured") == "Kuaishou featured"
    for bad in ("kuaishou:", "kuaishou:featured:1", "bilibili:popular", "featured"):
        with pytest.raises(ValueError):
            kuaishou_feed.parse(bad)


@pytest.mark.parametrize("text,n", [("77780", 77780), ("1.6万", 16000), ("2.5亿", 250_000_000), ("", None),
                                    (None, None), ("abc", None)])
def test_count(text, n):
    assert kuaishou_feed.count(text) == n


def test_fetch_makes_clip_rows_without_repeats_and_skips_short_or_captionless(kuaishou_site):
    kuaishou_site["feeds"] = [_feed("3xaaaaaaaaaaaaa"), _feed("3xsssssssssssss", duration=9000),
                              _feed("3xccccccccccccc", caption=" "), _feed("3xddddddddddddd", photoUrl="http://x/a.mp4")]
    rows = kuaishou_feed.fetch("kuaishou:featured")
    assert [r["id"] for r in rows] == ["kuaishou:3xaaaaaaaaaaaaa"]  # the same answer three times, one row
    assert len(kuaishou_site["calls"]) == kuaishou_feed.PAGES
    r = rows[0]
    assert (r["site"], r["url"], r["rank"]) == ("kuaishou", "https://www.kuaishou.com/short-video/3xaaaaaaaaaaaaa", 1)
    assert (r["title"], r["uploader"], r["duration"]) == ("视频 3xaaaaaaaaaaaaa #标签", "作者", 34)
    assert (r["views"], r["likes"]) == (16000, 2354)
    assert r["thumbnail"].startswith("https://") and r["pubdate"] == 1_787_549_981


def test_a_refusal_is_an_error_not_an_empty_list(kuaishou_site):
    kuaishou_site["result"] = 2
    with pytest.raises(kuaishou_feed.FeedError, match="result 2"):
        kuaishou_feed.fetch("kuaishou:featured")


def test_follow_and_check_saves_the_videos(kuaishou_site):
    wid = watch.add("kuaishou:featured")
    w = db.get_watch(wid)
    assert (w["kind"], w["site"], w["name"]) == ("trending", "kuaishou", "Kuaishou featured")
    with pytest.raises(ValueError):
        watch.add("kuaishou:featured")
    watch.check(w)
    rows = db.list_clips("new", wid)
    assert {r["id"] for r in rows} == {"kuaishou:3xaaaaaaaaaaaaa", "kuaishou:3xbbbbbbbbbbbbb"}
    kuaishou_site["result"] = 2
    out = watch.check(db.get_watch(wid))
    assert "result 2" in (db.get_watch(wid)["last_error"] or "") and out is not None


def test_a_feed_video_downloads_from_its_own_address_without_videodl(kuaishou_site, tmp_path):
    kuaishou_feed.fetch("kuaishou:featured")
    kuaishou_site["calls"].clear()
    info = kuaishou.download("https://www.kuaishou.com/short-video/3xaaaaaaaaaaaaa", tmp_path)
    assert info["id"] == "3xaaaaaaaaaaaaa" and info["platform"] == "Kuaishou"
    assert (tmp_path / "Kuaishou_3xaaaaaaaaaaaaa.mp4").read_bytes() == b"v" * 4000
    assert kuaishou_site["calls"] == [MP4]


def test_an_expired_address_falls_back_to_videodl_message(kuaishou_site, tmp_path, monkeypatch):
    kuaishou_feed.fetch("kuaishou:featured")
    kuaishou_site["type"] = "text/html"  # the CDN answers a page
    with pytest.raises(kuaishou.Unavailable, match="videodl"):
        kuaishou.download("https://www.kuaishou.com/short-video/3xaaaaaaaaaaaaa", tmp_path)
    assert not list(tmp_path.glob("*.part"))


def test_a_video_the_feed_never_gave_goes_to_videodl(kuaishou_site, tmp_path):
    with pytest.raises(kuaishou.Unavailable, match="videodl"):
        kuaishou.download("https://www.kuaishou.com/short-video/3xzzzz", tmp_path)
    assert kuaishou_site["calls"] == []


def test_old_addresses_are_forgotten(kuaishou_site, monkeypatch):
    kuaishou_feed.fetch("kuaishou:featured")
    assert kuaishou_feed.media_url("3xaaaaaaaaaaaaa") == MP4
    monkeypatch.setattr(kuaishou_feed, "MEDIA_TTL", -1)
    assert kuaishou_feed.media_url("3xaaaaaaaaaaaaa") is None
