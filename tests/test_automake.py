"""Tự làm video khi tin hot đạt điểm của hồ sơ kênh."""
import time

import pytest

from motio import automake, channels, db


@pytest.fixture(autouse=True)
def empty_trends_and_projects():
    """Tin và dự án của các test khác (cùng DB tạm) không được tính vào lượt tự làm."""
    with db.conn() as c:
        c.execute("DELETE FROM trend")
        c.execute("DELETE FROM project")


def _trend(tid: str, score: int, first_seen: float | None = None, **kw) -> dict:
    db.upsert_trend({"id": tid, "source": "douyin", "ext_id": tid, "url": "https://x", "title_zh": "中文",
                     "title_fr": f"Titre {tid}", "angle": "a", "reason": "r", "keywords": {}, "score": score,
                     "rank": 1, **kw})
    if first_seen is not None:
        with db.conn() as c:
            c.execute("UPDATE trend SET first_seen=? WHERE id=?", (first_seen, tid))
    return db.get_trend(tid)


def _ch(name: str, score: int, daily: int = 2, default: bool = False) -> dict:
    return channels.create({"name": name, "auto_score": score, "auto_daily": daily}, default)


def _picked() -> list[tuple[str, str]]:
    return [(t["id"], ch["name"]) for t, ch in automake.picks()]


def test_nothing_without_an_auto_make_channel():
    channels.create({"name": "Manual"})
    _trend("a", 99)
    assert automake.picks() == []


def test_picks_new_fresh_trends_above_the_score_best_first():
    _ch("Chine Express", 85)
    _trend("low", 70)
    _trend("mid", 86)
    _trend("top", 95)
    _trend("old", 99, first_seen=time.time() - 30 * 3600)  # xuất hiện hơn 24 giờ trước
    _trend("made", 97)
    db.create_project("made", "déjà fait")  # tin đã làm
    assert _picked() == [("top", "Chine Express"), ("mid", "Chine Express")]


def test_daily_cap_per_channel_counts_what_was_made_today():
    ch = _ch("Chine Express", 80, daily=2)
    for tid in ("a", "b", "c"):
        _trend(tid, 90)
    t, c = automake.picks()[0]
    pid = automake.start(t, c)
    p = db.get_project(pid)
    assert p["meta"]["auto"] is True and p["meta"]["channel"] == ch["id"] and "Made automatically" in p["log"]
    assert db.get_trend(t["id"])["status"] == "used"
    assert len(automake.picks()) == 1  # còn 1 lượt hôm nay


def test_first_matching_channel_gets_the_trend_default_first():
    _ch("Strict", 90)
    _ch("Default", 80, default=True)
    _trend("t95", 95)
    _trend("t85", 85)
    assert _picked() == [("t95", "Default"), ("t85", "Default")]


def test_auto_score_zero_is_off():
    _ch("Off", 0)
    _trend("a", 100)
    assert automake.picks() == []


# ---------- new videos of Trending / Followed ----------
@pytest.fixture
def no_clips():
    with db.conn() as c:
        c.execute("DELETE FROM clip")


def _clip(cid: str, score: int | None, first_seen: float | None = None, status: str = "new") -> dict:
    db.insert_clips([{"id": cid, "watch_id": None, "site": "bilibili", "url": f"https://www.bilibili.com/video/{cid}",
                      "title": f"标题 {cid}", "uploader": "up", "duration": 120, "views": 1000, "thumbnail": None,
                      "status": status}])
    db.score_clip(cid, f"Titre {cid}", score, "r")
    if first_seen is not None:
        with db.conn() as c:
            c.execute("UPDATE clip SET first_seen=? WHERE id=?", (first_seen, cid))
    return db.get_clip(cid)


def _planned() -> list[tuple[str, str, str]]:
    return [(kind, item["id"], ch["name"]) for kind, item, ch in automake.plan()]


def test_new_videos_are_left_alone_unless_the_channel_asks_for_them(no_clips):
    _ch("Actu", 80)  # auto-make score alone: news topics only, as before
    _clip("BV1", 95)
    assert automake.plan() == []


def test_scored_new_videos_are_planned_best_first_for_a_channel_that_asks(no_clips):
    channels.create({"name": "Chine Express", "auto_score": 80, "auto_daily": 5, "auto_clips": "explainer"}, False)
    _clip("BV1", 85)
    _clip("BV2", 97)
    _clip("BV3", 60)  # under the score
    _clip("BV4", None)  # not scored yet
    _clip("BV5", 99, first_seen=time.time() - 30 * 3600)  # seen more than a day ago
    _clip("BV6", 99, status="hidden")
    _trend("t1", 90)
    assert _planned() == [("clip", "BV2", "Chine Express"), ("trend", "t1", "Chine Express"),
                          ("clip", "BV1", "Chine Express")]
    assert [t["id"] for t, _ in automake.picks()] == ["t1"]


def test_news_and_videos_share_the_daily_cap(no_clips):
    channels.create({"name": "Chine Express", "auto_score": 80, "auto_daily": 2, "auto_clips": "explainer"}, False)
    _trend("t1", 90)
    _clip("BV1", 95)
    _clip("BV2", 85)
    assert _planned() == [("clip", "BV1", "Chine Express"), ("trend", "t1", "Chine Express")]


def test_make_creates_an_explainer_with_the_source_muted(no_clips):
    ch = channels.create({"name": "Chine Express", "auto_score": 80, "auto_clips": "explainer", "duration": 90}, False)
    _clip("BV1", 95)
    (pid, kind, item, got), = automake.make()
    p = db.get_project(pid)
    assert kind == "clip" and item["id"] == "BV1" and got["id"] == ch["id"]
    assert p["mode"] == "topic" and p["meta"]["auto"] is True and p["meta"]["channel"] == ch["id"]
    assert p["meta"]["mute_source"] is True and p["meta"]["duration"] == 90
    assert p["meta"]["links"] == ["https://www.bilibili.com/video/BV1"]
    assert "Made automatically: score 95" in p["log"]
    assert db.get_clip("BV1")["status"] == "used" and automake.plan() == []  # once only


def test_make_creates_a_dub_when_the_channel_dubs(no_clips):
    channels.create({"name": "Doublage", "auto_score": 80, "auto_clips": "dub"}, False)
    _clip("BV1", 95)
    (pid, _kind, _item, _ch), = automake.make()
    p = db.get_project(pid)
    assert p["mode"] == "dub" and p["meta"]["auto"] is True and p["meta"]["clip"] == "BV1"


def test_a_video_that_cannot_become_a_project_is_hidden_and_the_rest_is_made(no_clips, monkeypatch):
    from motio import watch
    channels.create({"name": "Chine Express", "auto_score": 80, "auto_daily": 5, "auto_clips": "explainer"}, False)
    _clip("BV1", 95)
    _clip("BV2", 90)
    real = watch.produce

    def produce(cid, *a, **kw):
        if cid == "BV1":
            raise ValueError("bad link")
        return real(cid, *a, **kw)

    monkeypatch.setattr(watch, "produce", produce)
    assert [item["id"] for _pid, _kind, item, _ch in automake.make()] == ["BV2"]
    assert db.get_clip("BV1")["status"] == "hidden"


def test_auto_clips_must_be_a_known_mode():
    with pytest.raises(ValueError):
        channels.create({"name": "X", "auto_clips": "remix"}, False)
    assert channels.create({"name": "Y"}, False)["auto_clips"] == ""
