"""Accounts (motio/accounts.py): the videos of a Weibo / Douyin / Kuaishou account, followed or scanned."""
import json

import httpx
import pytest

from motio import accounts, db, douyin, kuaishou_feed, scan, search, watch, weibo_feed

SEC = "MS4wLjABAAAAv7iSuuXDJGDvJkmH_vWkzzCpzTlOqeHq0uT2jXx4tT4"
MP4 = "http://f.video.weibocdn.com/o0/a.mp4?label=mp4_hd&Expires=1792357547&ssig=x"
KS_MP4 = "https://v23-3.kwaicdn.com/upic/2026/08/22/a.mp4?pkey=abc"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(accounts, "_PAUSE", 0)
    monkeypatch.setattr(weibo_feed, "_PAUSE", 0)
    for store in (weibo_feed._store(), kuaishou_feed._store()):
        store.unlink(missing_ok=True)
    with db.conn() as c:
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")
    yield
    with db.conn() as c:
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")


# ---------- which account a link means ----------
@pytest.mark.parametrize("text,got", [
    ("https://weibo.com/u/3266943013", ("weibo", "3266943013")),
    ("https://weibo.com/3266943013", ("weibo", "3266943013")),
    ("https://m.weibo.cn/u/3266943013", ("weibo", "3266943013")),
    ("https://www.kuaishou.com/profile/3xnh5duxe4aafxk", ("kuaishou", "3xnh5duxe4aafxk")),
    ("https://live.kuaishou.com/profile/3xnh5duxe4aafxk/", ("kuaishou", "3xnh5duxe4aafxk")),
    (f"https://www.douyin.com/user/{SEC}?from_tab_name=main", ("douyin", SEC)),
    (f"https://www.iesdouyin.com/share/user/{SEC}", ("douyin", SEC)),
    ("weibo:user:3266943013", ("weibo", "3266943013")),
    (f"douyin:user:{SEC}", ("douyin", SEC)),
])
def test_identify(text, got):
    assert accounts.identify(text) == got
    assert accounts.identify(text, expand=False) == got


@pytest.mark.parametrize("text", ["", "panda", "https://weibo.com/3266943013/RnhjgpzL7",  # a post, not an account
                                  "https://www.kuaishou.com/short-video/3xaaaaaaaaaaaaa",
                                  "https://www.douyin.com/video/7512345678901234567", "https://evil.example/u/3266943013",
                                  "weibo:hot", "kuaishou:featured"])
def test_identify_ignores_other_links(text):
    assert accounts.identify(text) is None


def test_a_share_link_is_followed_only_inside_the_site(monkeypatch):
    hops = []

    def handler(req: httpx.Request) -> httpx.Response:
        hops.append(str(req.url))
        if req.url.host == "v.douyin.com":
            return httpx.Response(302, headers={"location": f"https://www.iesdouyin.com/share/user/{SEC}?x=1"})
        return httpx.Response(200, text="page")

    monkeypatch.setattr(accounts, "_transport", httpx.MockTransport(handler))
    assert accounts.identify("https://v.douyin.com/abc/") == ("douyin", SEC)
    assert hops == ["https://v.douyin.com/abc/", f"https://www.iesdouyin.com/share/user/{SEC}?x=1"]

    def away(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/u/3266943013"})

    monkeypatch.setattr(accounts, "_transport", httpx.MockTransport(away))
    assert accounts.identify("https://v.douyin.com/abc/") is None


def test_parse_takes_a_link_or_a_bare_id():
    assert accounts.parse("weibo", "3266943013") == "3266943013"
    assert accounts.parse("kuaishou", "https://www.kuaishou.com/profile/3xnh5duxe4aafxk") == "3xnh5duxe4aafxk"
    assert accounts.parse("douyin", SEC) == SEC
    for site, text in (("weibo", "abc"), ("douyin", "123"), ("weibo", f"https://www.douyin.com/user/{SEC}"),
                       ("youtube", "x")):
        with pytest.raises(ValueError):
            accounts.parse(site, text)


# ---------- Weibo ----------
def _post(mid, **kw):
    media = {"duration": 8, "mp4_hd_url": MP4, "online_users_number": 8781}
    page = {"object_type": "video", "page_pic": f"https://wx4.sinaimg.cn/{mid}.jpg", "media_info": media}
    post = {"mblogid": mid, "user": {"idstr": "3266943013", "screen_name": "央视网"}, "text_raw": f"视频 {mid}",
            "attitudes_count": 22, "created_at": "Sun Oct 18 21:20:00 +0800 2026", "page_info": page}
    return {**post, **kw}


@pytest.fixture
def weibo_site(monkeypatch):
    state = {"pages": [[_post("RnhjgpzL7"), _post("Rnhb97TyA")], [_post("RngW6hWfg")]], "calls": [], "guest": True}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"].append(str(req.url))
        if req.url.host == "passport.weibo.com":
            headers = {"set-cookie": "SUB=guest-sub; Domain=.weibo.com; Path=/"} if state["guest"] else {}
            return httpx.Response(200, text="ok", headers=headers)
        if "SUB=" not in req.headers.get("cookie", ""):
            return httpx.Response(403, text="forbidden")
        page = int(req.url.params.get("cursor") or 0) if req.url.params.get("cursor") != "0" else 0
        data = {"list": state["pages"][page], "next_cursor": str(page + 1) if page + 1 < len(state["pages"]) else "0"}
        return httpx.Response(200, json={"ok": 1, "data": data})

    monkeypatch.setattr(accounts, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(weibo_feed, "_transport", httpx.MockTransport(handler))
    return state


def test_weibo_account_lists_every_video_with_views_and_keeps_short_ones(weibo_site):
    name, rows = accounts.fetch("weibo", "3266943013")
    assert name == "央视网"
    assert sorted(r["id"] for r in rows) == ["weibo:RngW6hWfg", "weibo:Rnhb97TyA", "weibo:RnhjgpzL7"]
    r = rows[0]
    assert (r["views"], r["likes"], r["duration"], r["site"]) == (8781, 22, 8, "weibo")  # 8 s is kept
    assert r["url"] == "https://weibo.com/3266943013/RnhjgpzL7" and r["rank"] == 1
    assert weibo_feed.media_url("RnhjgpzL7") == MP4  # "Make video" can fetch the file


def test_weibo_asks_for_the_guest_session_first_and_says_so_when_it_fails(weibo_site):
    weibo_site["guest"] = False
    with pytest.raises(accounts.AccountError, match="Weibo"):
        accounts.fetch("weibo", "3266943013")


# ---------- Kuaishou ----------
def _ks(pid, **kw):
    photo = {"id": pid, "duration": 12000, "caption": f"视频 {pid}", "viewCount": "1.6万", "likeCount": "2354",
             "timestamp": 1_787_549_981_003, "coverUrl": f"https://p2.a.yximgs.com/{pid}.jpg", "photoUrl": KS_MP4}
    return {"type": 1, "author": {"id": "u1", "name": "作者"}, "photo": {**photo, **kw}}


@pytest.fixture
def kuaishou_site(monkeypatch):
    state = {"feeds": [_ks("3xaaaaaaaaaaaaa"), _ks("3xbbbbbbbbbbbbb")], "data": None, "calls": [],
             "cookies": {"did": "web_1"}}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"].append(req)
        op = json.loads(req.content)["operationName"]
        body = state["data"] or {op: {"result": 1, "pcursor": "no_more", "feeds": state["feeds"]}}
        return httpx.Response(200, json={"data": body})

    monkeypatch.setattr(accounts, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(search, "site_cookies", lambda domain: state["cookies"] if domain == "kuaishou.com" else {})
    return state


def test_kuaishou_account_uses_the_owners_cookies(kuaishou_site):
    name, rows = accounts.fetch("kuaishou", "3xnh5duxe4aafxk")
    assert name == "作者" and [r["id"] for r in rows] == ["kuaishou:3xaaaaaaaaaaaaa", "kuaishou:3xbbbbbbbbbbbbb"]
    assert (rows[0]["views"], rows[0]["likes"], rows[0]["duration"]) == (16000, 2354, 12)
    req = kuaishou_site["calls"][0]
    assert "did=web_1" in req.headers["cookie"] and req.headers["referer"].endswith("/profile/3xnh5duxe4aafxk")
    assert kuaishou_feed.media_url("3xaaaaaaaaaaaaa") == KS_MP4


def test_kuaishou_without_a_login_does_not_even_ask(kuaishou_site):
    kuaishou_site["cookies"] = {}
    with pytest.raises(accounts.AccountError, match="your own login"):
        accounts.fetch("kuaishou", "3xnh5duxe4aafxk")
    assert kuaishou_site["calls"] == []


def test_kuaishou_captcha_is_reported_not_worked_around(kuaishou_site):
    kuaishou_site["data"] = {"result": 400002, "url": "https://captcha.zt.kuaishou.com/iframe/index.html?x=1"}
    with pytest.raises(accounts.AccountError, match="slider captcha"):
        accounts.fetch("kuaishou", "3xnh5duxe4aafxk")
    assert len(kuaishou_site["calls"]) == 1  # no retry loop against the check


def test_kuaishou_keyword_search_uses_the_same_cookies_and_search_page(kuaishou_site):
    rows = accounts.search_kuaishou("美食")
    assert [r["id"] for r in rows] == ["kuaishou:3xaaaaaaaaaaaaa", "kuaishou:3xbbbbbbbbbbbbb"]
    req = kuaishou_site["calls"][0]
    sent = json.loads(req.content)
    assert sent["operationName"] == "visionSearchPhoto" and sent["variables"]["keyword"] == "美食"
    assert sent["variables"]["page"] == "search" and "did=web_1" in req.headers["cookie"]
    assert kuaishou_feed.media_url("3xaaaaaaaaaaaaa") == KS_MP4


def test_kuaishou_keyword_search_without_a_login_does_not_even_ask(kuaishou_site):
    kuaishou_site["cookies"] = {}
    with pytest.raises(accounts.AccountError, match="your own login"):
        accounts.search_kuaishou("美食")
    assert kuaishou_site["calls"] == []


# ---------- Douyin ----------
def _aweme(pid, **kw):
    video = {"duration": 9000, "cover": {"url_list": ["https://p3.douyinpic.com/a.jpg"]}}
    post = {"aweme_id": pid, "desc": f"视频 {pid}", "video": video, "statistics": {"play_count": 0, "digg_count": 321},
            "author": {"nickname": "某某"}, "create_time": 1_787_549_981}
    return {**post, **kw}


def test_douyin_account_pages_until_there_is_no_more(monkeypatch):
    answers = [{"aweme_list": [_aweme("7512345678901234567"), _aweme("7512345678901234568", images=[{"x": 1}])],
                "has_more": 1, "max_cursor": 111},
               {"aweme_list": [_aweme("7512345678901234569")], "has_more": 0, "max_cursor": 0}]
    asked = []

    async def page(sec, cursor):
        asked.append((sec, cursor))
        return answers[len(asked) - 1]

    monkeypatch.setattr(accounts, "_douyin_page", page)
    name, rows = accounts.fetch("douyin", SEC)
    assert asked == [(SEC, 0), (SEC, 111)] and name == "某某"
    # a photo post is out
    assert [r["id"] for r in rows] == ["douyin:7512345678901234567", "douyin:7512345678901234569"]
    assert rows[0]["likes"] == 321 and rows[0]["duration"] == 9


def test_douyin_failure_is_an_account_error(monkeypatch):
    async def page(sec, cursor):
        raise RuntimeError("signature out of date")

    monkeypatch.setattr(accounts, "_douyin_page", page)
    with pytest.raises(accounts.AccountError, match="signature out of date"):
        accounts.fetch("douyin", SEC)


def test_douyin_empty_answer_says_why_it_may_be(monkeypatch):
    async def page(sec, cursor):
        return {"aweme_list": [], "has_more": 0}

    monkeypatch.setattr(accounts, "_douyin_page", page)
    with pytest.raises(accounts.AccountError, match="private, empty"):
        accounts.fetch("douyin", SEC)


# ---------- followed accounts ----------
def test_follow_an_account_and_check_it(weibo_site):
    wid = watch.add("https://weibo.com/u/3266943013")
    w = db.get_watch(wid)
    assert (w["kind"], w["site"], w["target"]) == ("account", "weibo", "weibo:user:3266943013")
    with pytest.raises(ValueError, match="already"):
        watch.add("https://weibo.com/3266943013")
    r = watch.check(w)
    assert len(r["new"]) == 3 and r["error"] is None
    assert db.get_watch(wid)["name"] == "央视网"
    weibo_site["pages"] = [[_post("Rnew00001"), _post("RnhjgpzL7")], [_post("RngW6hWfg")]]
    assert watch.check(db.get_watch(wid))["new"] == ["weibo:Rnew00001"]  # only what was not seen


def test_a_followed_account_that_fails_keeps_its_error(kuaishou_site):
    kuaishou_site["cookies"] = {}
    wid = watch.add("https://www.kuaishou.com/profile/3xnh5duxe4aafxk")
    r = watch.check(db.get_watch(wid))
    assert r["new"] == [] and "your own login" in r["error"]
    assert db.get_watch(wid)["last_error"] and not db.get_watch(wid)["last_checked"]


# ---------- the cookie reader ----------
def test_site_cookies_reads_only_the_asked_site(tmp_path, monkeypatch):
    jar = tmp_path / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\n"
                   ".kuaishou.com\tTRUE\t/\tTRUE\t2000000000\tdid\tweb_1\n"
                   ".example.com\tTRUE\t/\tTRUE\t2000000000\tsecret\tno\n", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(jar))
    assert search.site_cookies("kuaishou.com") == {"did": "web_1"}
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(tmp_path / "missing.txt"))
    monkeypatch.delenv("YTDLP_COOKIES_FROM_BROWSER", raising=False)
    assert search.site_cookies("kuaishou.com") == {}


def test_douyin_f2_is_not_loaded_by_the_tests():
    with pytest.raises(RuntimeError, match="switched off"):
        douyin._f2()


# ---------- scan ----------
def _wait(job_id):
    import time
    for _ in range(200):
        v = scan.view(job_id)
        if v["status"] != "running":
            return v
        time.sleep(0.02)
    raise AssertionError("scan did not finish")


def test_scan_checks_its_input():
    assert scan.check("weibo", "account", "3266943013\n\n3266943013", 50) == (["3266943013"], 50)
    assert scan.check("youtube", "hashtag", "roblox", 7)[1] == scan.DEFAULT_LIMIT
    for site, mode, text in (("tiktok", "account", "x"), ("douyin", "keyword", "x"), ("weibo", "account", " \n "),
                             ("weibo", "account", "\n".join(str(10000 + i) for i in range(11)))):
        with pytest.raises(ValueError):
            scan.check(site, mode, text, 50)


def test_scan_reads_each_line_and_keeps_going_after_a_bad_one(weibo_site):
    job = scan.start("weibo", "account", "3266943013\nnot-an-id", 50)
    v = _wait(job["id"])
    assert v["status"] == "done" and len(v["rows"]) == 3
    assert len(v["errors"]) == 1 and v["errors"][0].startswith("not-an-id")
    r = v["rows"][0]
    assert (r["video_id"], r["views"], r["likes"], r["source"]) == ("RnhjgpzL7", 8781, 22, "3266943013")
    assert set(r) >= {"id", "url", "title", "uploader", "duration", "pubdate", "thumbnail"}


def test_scan_fails_when_every_line_fails():
    v = _wait(scan.start("weibo", "account", "nope", 50)["id"])
    assert v["status"] == "failed" and v["rows"] == [] and v["errors"]


def test_scan_hashtag_and_keyword_use_the_platform_search(monkeypatch):
    calls = []

    def ytdlp(site, url, limit, w):
        calls.append((site, url, limit))
        return [{"id": "youtube:abc", "site": "youtube", "url": "https://www.youtube.com/watch?v=abc", "title": "t",
                 "uploader": "u", "duration": 60, "views": 5, "likes": None, "pubdate": None, "thumbnail": None}]

    monkeypatch.setattr(scan, "_ytdlp", ytdlp)
    assert _wait(scan.start("youtube", "hashtag", "#roblox", 20)["id"])["rows"][0]["views"] == 5
    assert _wait(scan.start("youtube", "keyword", "roblox", 20)["id"])["status"] == "done"
    assert [c[1] for c in calls] == ["https://www.youtube.com/hashtag/roblox", "ytsearch20:roblox"]


def test_scan_kuaishou_keyword_and_hashtag_go_to_its_search(monkeypatch):
    asked = []

    def fake(word, take=50):
        asked.append((word, take))
        return [{"id": "kuaishou:3xaaaaaaaaaaaaa", "site": "kuaishou", "url": "https://www.kuaishou.com/short-video/3xaaaaaaaaaaaaa",
                 "title": "t", "views": 9}]

    monkeypatch.setattr(accounts, "search_kuaishou", fake)
    assert _wait(scan.start("kuaishou", "keyword", "美食", 20)["id"])["rows"][0]["views"] == 9
    assert _wait(scan.start("kuaishou", "hashtag", "#美食", 20)["id"])["status"] == "done"
    assert asked == [("美食", 20), ("美食", 20)]


def test_scan_can_be_stopped(monkeypatch):
    import threading
    gate = threading.Event()

    def slow(site, mode, line, limit):
        gate.wait(5)
        return []

    monkeypatch.setattr(scan, "_read", slow)
    job = scan.start("weibo", "account", "10000001\n10000002", 50)
    assert scan.stop(job["id"])["status"] == "running"
    gate.set()
    assert _wait(job["id"])["status"] == "stopped"
