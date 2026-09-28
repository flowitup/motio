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


def test_global_daily_limit_wins(monkeypatch):
    monkeypatch.setenv("MAX_VIDEOS_PER_DAY", "1")
    _ch("Chine Express", 80, daily=5)
    _trend("a", 90)
    _trend("b", 91)
    assert _picked() == [("b", "Chine Express")]


def test_auto_score_zero_is_off():
    _ch("Off", 0)
    _trend("a", 100)
    assert automake.picks() == []
