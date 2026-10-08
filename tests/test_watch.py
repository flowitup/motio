import time

import pytest
from fastapi.testclient import TestClient

from motio import api, db, llm, pipeline, watch

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}
VOX = "https://www.youtube.com/@Vox"


class FakeYDL:
    """yt-dlp giả: `pages` cho danh sách phẳng, `details` cho trang một video (process=False)."""
    pages: dict = {}
    details: dict = {}
    opts: list = []

    def __init__(self, opts):
        FakeYDL.opts.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False, process=True):
        r = (FakeYDL.pages if process else FakeYDL.details)[url]
        if isinstance(r, Exception):
            raise r
        return r


def _yt(ids, **extra):
    return [{"id": i, "ie_key": "Youtube", "url": f"https://www.youtube.com/watch?v={i}", "title": f"Video {i}",
             "duration": 300, "view_count": 1000, **extra} for i in ids]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    with db.conn() as c:
        c.execute("DELETE FROM clip")
        c.execute("DELETE FROM watch")
        c.execute("DELETE FROM project")
    FakeYDL.pages, FakeYDL.details, FakeYDL.opts = {}, {}, []
    monkeypatch.setattr(watch, "YoutubeDL", FakeYDL)


@pytest.mark.parametrize("text,site,kind,target", [
    ("https://www.youtube.com/@Vox/videos", "youtube", "channel", VOX),
    ("https://m.youtube.com/channel/UCabc_1-x/shorts", "youtube", "channel", "https://www.youtube.com/channel/UCabc_1-x"),
    ("https://www.youtube.com/playlist?list=PL1&si=x", "youtube", "playlist", "https://www.youtube.com/playlist?list=PL1"),
    ("https://www.youtube.com/results?search_query=street+food", "youtube", "search", "street food"),
    ("https://space.bilibili.com/42/upload/video", "bilibili", "space", "https://space.bilibili.com/42/video"),
    ("https://space.bilibili.com/42/favlist?fid=9", "bilibili", "playlist", "https://space.bilibili.com/42/favlist?fid=9"),
    ("https://search.bilibili.com/all?keyword=%E7%86%8A%E7%8C%AB", "bilibili", "search", "熊猫"),
    ("  cuisine   de rue ", "youtube", "search", "cuisine de rue"),
])
def test_classify(text, site, kind, target):
    w = watch.classify(text, "bilibili" if site == "bilibili" and kind == "search" else "youtube")
    assert (w["kind"], w["site"], w["target"]) == (kind, site, target)


@pytest.mark.parametrize("text", ["", "https://www.youtube.com/watch?v=a", "https://youtu.be/a",
                                  "https://www.bilibili.com/video/BV1", "https://www.douyin.com/user/x",
                                  "https://www.facebook.com/somepage"])
def test_classify_rejects(text):
    with pytest.raises(ValueError):
        watch.classify(text)


def test_add_rejects_duplicates_and_bad_rights():
    watch.add("https://www.youtube.com/@Vox")
    with pytest.raises(ValueError, match="already"):
        watch.add("https://www.youtube.com/@Vox/shorts")
    with pytest.raises(ValueError):
        watch.add("panda", rights="mine")
    watch.add("panda", site="bilibili")  # cùng từ khoá, nơi khác: được


def test_first_check_then_only_unseen_videos():
    wid = watch.add(VOX)
    FakeYDL.pages = {
        f"{VOX}/videos": {"channel": "Vox", "entries": _yt([f"v{i}" for i in range(15)])},
        f"{VOX}/shorts": {"channel": "Vox", "entries": _yt(["s1", "s2"]) + _yt(["live"], live_status="is_upcoming")},
    }
    r = watch.check(db.get_watch(wid))
    assert len(r["new"]) == 12 and r["error"] is None  # 10 video mới nhất + 2 Shorts; bỏ buổi phát sắp tới
    assert all(o["playlistend"] == watch.PER_LIST and o["extract_flat"] == "in_playlist" for o in FakeYDL.opts)
    assert all(isinstance(o["logger"], watch._Silent) for o in FakeYDL.opts)  # lỗi yt-dlp không in ra stderr
    w = db.get_watch(wid)
    assert w["name"] == "Vox" and w["last_checked"]
    assert len(db.list_clips("old")) == 5  # còn lại: coi như đã thấy, không hiện
    c = db.get_clip("youtube:v0")
    assert c["thumbnail"] == "https://i.ytimg.com/vi/v0/hqdefault.jpg" and c["uploader"] == "Vox"

    FakeYDL.pages[f"{VOX}/videos"]["entries"] = _yt(["n1", "n2"]) + _yt([f"v{i}" for i in range(13)])
    r = watch.check(db.get_watch(wid))
    assert r["new"] == ["youtube:n1", "youtube:n2"]
    assert db.list_watches()[0]["new_count"] == 14


def test_bilibili_space_reads_titles_and_explains_block(monkeypatch):
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
    wid = watch.add("https://space.bilibili.com/42")
    url = "https://space.bilibili.com/42/video"
    FakeYDL.pages = {url: Exception("ERROR: [BilibiliSpaceVideo] 42: Request is blocked by server (412)")}
    r = watch.check(db.get_watch(wid))
    w = db.get_watch(wid)
    assert r["new"] == [] and "Browser cookies" in w["last_error"] and w["last_checked"] is None
    assert FakeYDL.opts[0]["cookiesfrombrowser"] == ("firefox",)

    video = "https://www.bilibili.com/video/BV1a"
    gone, blocked = "https://www.bilibili.com/video/BV1gone", "https://www.bilibili.com/video/BV1wait"
    FakeYDL.pages = {url: {"entries": [{"id": "BV1a", "ie_key": "BiliBili", "url": video},
                                       {"id": "BV1gone", "ie_key": "BiliBili", "url": gone},
                                       {"id": "BV1wait", "ie_key": "BiliBili", "url": blocked},
                                       {"id": "42_7", "ie_key": "BilibiliCollectionList", "url": "https://x"}]}}
    FakeYDL.details = {video: {"title": "熊猫吃竹子", "uploader": "UP主", "duration": 95, "view_count": 5,
                               "thumbnail": "http://i0.hdslb.com/a.jpg"},
                       gone: Exception("ERROR: [BiliBili] BV1gone: This video may be deleted or geo-restricted."),
                       blocked: Exception("ERROR: [BiliBili] BV1wait: HTTP Error 412: Precondition Failed")}
    r = watch.check(db.get_watch(wid))
    assert r["new"] == ["bilibili:BV1a"]
    c = db.get_clip("bilibili:BV1a")
    assert (c["title"], c["uploader"], c["duration"]) == ("熊猫吃竹子", "UP主", 95)
    assert c["thumbnail"] == "https://i0.hdslb.com/a.jpg"
    assert db.get_clip("bilibili:BV1gone")["status"] == "old"  # đã xoá / giới hạn vùng: không hiện trống
    assert db.get_clip("bilibili:BV1wait") is None  # bị chặn: lượt sau thử lại
    w = db.get_watch(wid)
    assert w["last_error"] is None and w["name"] == "UP主"  # không gian không có tên: lấy tên kênh của video

    FakeYDL.details[blocked] = {"title": "Finally", "uploader": "UP主"}
    assert watch.check(db.get_watch(wid))["new"] == ["bilibili:BV1wait"]


def test_bilibili_search_keeps_videos_and_dedupes_av_ids():
    assert watch.av_to_bv(170001) == "BV17x411w7KC" and watch.av_to_bv(1) == "BV1xx411c7mQ"  # cặp đã biết
    wid = watch.add("熊猫", site="bilibili")
    FakeYDL.pages = {"bilisearch15:熊猫": Exception("ERROR: [BiliBiliSearch] 熊猫: Unable to download JSON metadata: "
                                                   "HTTP Error 412: Precondition Failed")}
    watch.check(db.get_watch(wid))
    assert "Browser cookies" in db.get_watch(wid)["last_error"]  # lỗi không nhắc "bilibili" vẫn được giải thích

    FakeYDL.pages = {"bilisearch15:熊猫": {"entries": [
        {"id": "170001", "ie_key": "BiliBili", "url": "http://www.bilibili.com/video/av170001"},
        {"id": "966", "ie_key": "BiliBili", "url": "https://www.bilibili.com/cheese/play/ss966"}]}}
    FakeYDL.details = {"https://www.bilibili.com/video/BV17x411w7KC": {"title": "熊猫", "uploader": "UP"}}
    r = watch.check(db.get_watch(wid))
    assert r["new"] == ["bilibili:BV17x411w7KC"] and db.get_clip("bilibili:966") is None  # khoá học trả phí: bỏ
    assert db.get_watch(wid)["name"] == "熊猫"

    space = watch.add("https://space.bilibili.com/7")
    FakeYDL.pages = {"https://space.bilibili.com/7/video": {"entries": [
        {"id": "BV17x411w7KC", "ie_key": "BiliBili", "url": "https://www.bilibili.com/video/BV17x411w7KC"}]}}
    assert watch.check(db.get_watch(space))["new"] == []  # cùng video, đã thấy qua tìm kiếm


def test_check_all_scores_new_videos(monkeypatch):
    wid = watch.add("street food")
    FakeYDL.pages = {f"https://www.youtube.com/results?search_query=street+food&sp={watch.YT_THIS_MONTH}":
                     {"entries": _yt(["a", "b"]) + [{"id": "s", "ie_key": "Youtube", "title": "Short s",
                                                     "url": "https://www.youtube.com/shorts/s"}]}}
    prompts = []

    def fake_ask(prompt, system, effort=None, **kw):
        prompts.append((prompt, effort))
        return [{"id": "youtube:a", "title_fr": "La cuisine de rue", "score": 88, "reason": "visuel"},
                {"id": "youtube:b", "score": "n/a"}]

    monkeypatch.setattr(llm, "ask_json", fake_ask)
    r = watch.check_all()
    assert r == {"checked": 1, "new": 3, "errors": {}, "scored": 3}
    assert prompts[0][1] == "low" and "Video a" in prompts[0][0]
    short = next(line for line in prompts[0][0].splitlines() if '"youtube:s"' in line)
    assert '"format": "Short"' in short and '"durée_s": null' in short  # độ dài chưa biết, không phải 0
    a, b, _ = db.list_clips()
    assert (a["id"], a["title_fr"], a["score"]) == ("youtube:a", "La cuisine de rue", 88)
    assert a["watch_name"] == "street food"
    assert b["score"] is None and b["title_fr"] is None

    db.update_watch(wid, enabled=False)
    assert watch.check_all()["checked"] == 0

    def boom(*a, **kw):
        raise llm.LLMError("No Anthropic API key: none")

    monkeypatch.setattr(llm, "ask_json", boom)
    db.update_watch(wid, enabled=True)
    FakeYDL.pages[next(iter(FakeYDL.pages))]["entries"] = _yt(["c"])
    r = watch.check_all()
    assert r["new"] == 1 and "none" in r["score_error"]


@pytest.mark.parametrize("rights,links_only,want_only,want_rights", [
    ("unknown", None, False, "unknown"),
    ("owned", None, True, "owned"),
    ("owned", False, False, "unknown"),  # thêm video tìm được của người khác → quyền không rõ
    ("unknown", True, True, "unknown"),
])
def test_produce_from_clip(rights, links_only, want_only, want_rights):
    wid = watch.add(VOX, rights=rights)
    db.insert_clips([{"id": "youtube:v1", "watch_id": wid, "site": "youtube", "url": "https://www.youtube.com/watch?v=v1",
                      "title": "Why pandas eat bamboo", "status": "new"}])
    db.score_clip("youtube:v1", "Pourquoi le panda mange du bambou", 90, "r")
    pid = watch.produce("youtube:v1", 70, links_only)
    p = db.get_project(pid)
    assert p["mode"] == "topic" and p["title"] == "Pourquoi le panda mange du bambou (Why pandas eat bamboo)"
    m = p["meta"]
    assert m["links"] == ["https://www.youtube.com/watch?v=v1"] and m["duration"] == 70 and m["clip"] == "youtube:v1"
    assert (m["links_only"], m["rights"]) == (want_only, want_rights)
    c = db.get_clip("youtube:v1")
    assert (c["status"], c["project_id"]) == ("used", pid)


def test_deleting_a_project_gives_its_clip_back():
    wid = watch.add(VOX)
    db.insert_clips([{"id": f"youtube:{v}", "watch_id": wid, "site": "youtube", "url": f"https://www.youtube.com/watch?v={v}",
                      "title": v, "status": "new"} for v in ("v1", "v2")])
    p1, p2 = watch.produce("youtube:v1"), watch.produce("youtube:v2")
    for pid in (p1, p2):
        db.update_project(pid, status="done")
    assert db.delete_project(p1)
    c = db.get_clip("youtube:v1")
    assert (c["status"], c["project_id"]) == ("new", None)
    db.delete_watch(wid)  # nguồn đã xoá: video đã dùng được giữ đến khi dự án bị xoá
    assert db.get_clip("youtube:v1") is None and db.get_clip("youtube:v2")["status"] == "used"
    assert db.delete_project(p2) and db.get_clip("youtube:v2") is None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(pipeline, "produce", lambda pid: db.update_project(pid, status="done"))
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


def _until(fn, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return False


def test_watch_routes(client, monkeypatch):
    checked = []
    monkeypatch.setattr(watch, "check_all", lambda ids=None: checked.append(ids) or {"checked": 1, "new": 0})
    r = client.post("/api/watches", headers=H, json={"target": "https://www.youtube.com/@Vox", "rights": "licensed"})
    assert r.status_code == 201
    w = r.json()
    assert (w["kind"], w["target"], w["rights"], w["enabled"]) == ("channel", VOX, "licensed", True)
    assert _until(lambda: checked == [[w["id"]]])  # nguồn mới được kiểm tra ngay
    assert client.post("/api/watches", headers=H, json={"target": VOX}).status_code == 400
    assert client.post("/api/watches", headers=H, json={"target": "https://youtu.be/x"}).status_code == 400
    assert client.post("/api/watches", headers=H, json={"target": "x", "site": "douyin"}).status_code == 400

    r = client.patch(f"/api/watches/{w['id']}", headers=H, json={"enabled": False, "name": " Vox FR "})
    assert r.json()["enabled"] is False and r.json()["name"] == "Vox FR"
    assert client.patch(f"/api/watches/{w['id']}", headers=H, json={"rights": "x"}).status_code == 400
    assert [x["id"] for x in client.get("/api/watches", headers=H).json()] == [w["id"]]

    assert client.post("/api/watches/check", headers=H).json() == {"started": True}
    assert _until(lambda: checked[-1] is None and not client.get("/api/state", headers=H).json()["watching"])
    st = client.get("/api/state", headers=H).json()
    assert st["last_watch_result"] == {"checked": 1, "new": 0} and st["last_watch"] and st["next_watch"] is None

    db.insert_clips([{"id": "youtube:v1", "watch_id": w["id"], "site": "youtube", "title": "Pandas",
                      "url": "https://www.youtube.com/watch?v=v1", "status": "new"}])
    clips = client.get("/api/clips", headers=H).json()
    assert [c["id"] for c in clips] == ["youtube:v1"] and clips[0]["watch_name"] == "Vox FR"
    r = client.patch("/api/clips/youtube:v1", headers=H, json={"status": "hidden"})
    assert r.json()["status"] == "hidden" and client.get("/api/clips", headers=H).json() == []
    assert len(client.get("/api/clips?status=hidden", headers=H).json()) == 1
    client.patch("/api/clips/youtube:v1", headers=H, json={"status": "new"})
    assert client.patch("/api/clips/youtube:v1", headers=H, json={"status": "used"}).status_code == 400

    r = client.post("/api/clips/youtube:v1/produce", headers=H, json={"duration": 90})
    assert r.status_code == 202
    p = db.get_project(r.json()["project_id"])
    assert p["meta"]["links_only"] is True and p["meta"]["rights"] == "licensed" and p["meta"]["duration"] == 90
    assert client.post("/api/clips/youtube:v1/produce", headers=H, json={"duration": 5}).status_code == 400
    assert client.post("/api/clips/nope/produce", headers=H).status_code == 404
    assert client.patch("/api/clips/youtube:v1", headers=H, json={"status": "hidden"}).status_code == 400

    assert client.delete(f"/api/watches/{w['id']}", headers=H).json() == {"deleted": w["id"]}
    assert client.get("/api/watches", headers=H).json() == []
    assert db.get_clip("youtube:v1")["status"] == "used"  # video đã làm giữ lại
    assert client.delete(f"/api/watches/{w['id']}", headers=H).status_code == 404
