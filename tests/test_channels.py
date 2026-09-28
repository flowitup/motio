"""Hồ sơ kênh: kiểm dữ liệu, kênh mặc định, nhãn trên video, giờ đăng kế tiếp."""
import datetime as dt

import pytest

from motio import channels, db, topic


def _ch(**kw) -> dict:
    return channels.create({"name": "Chine Express", **kw}, kw.pop("default", False))


def test_clean_normalises_a_profile():
    d = channels.clean({"name": "  Chine   Express ", "badge": " ACTU  CHINE ", "hashtags": ["chine", "#Chine, #tech"],
                        "send_times": ["9:05", "18:30", "18:30"], "send_mode": "schedule", "postiz": ["tt1", "tt1"],
                        "unknown": 1})
    assert d["name"] == "Chine Express" and d["badge"] == "ACTU CHINE"
    assert d["hashtags"] == ["#chine", "#tech"] and d["send_times"] == ["09:05", "18:30"] and d["postiz"] == ["tt1"]
    assert d["gate_script"] is True and d["gate_video"] is True and "unknown" not in d


def test_clean_keeps_16_9_channels_inside_the_postiz_list_and_auto_make_defaults():
    d = channels.clean({"name": "x", "postiz": ["tt1", "yt1"], "wide_postiz": ["yt1", "fb9", "yt1"]})
    assert d["wide_postiz"] == ["yt1"] and d["auto_score"] == 0 and d["auto_daily"] == 2
    d = channels.clean({"name": "x", "auto_score": "88", "auto_daily": 3})
    assert (d["auto_score"], d["auto_daily"]) == (88, 3)


@pytest.mark.parametrize("bad", [{"name": " "}, {"name": "x", "duration": 60}, {"name": "x", "send_mode": "later"},
                                 {"name": "x", "send_mode": "schedule", "postiz": ["tt1"]},
                                 {"name": "x", "send_times": ["25:00"]}, {"name": "x", "auto_score": 101},
                                 {"name": "x", "auto_daily": 0}, {"name": "x", "auto_score": "high"}])
def test_clean_rejects_bad_profiles(bad):
    with pytest.raises(ValueError):
        channels.clean(bad)


def test_one_default_and_pick():
    a = _ch(default=True)
    b = channels.create({"name": "Tech"}, True)
    assert [c["default"] for c in db.list_channels()] == [False, True]
    assert channels.pick(None)["id"] == b["id"] and channels.pick(0) is None and channels.pick(a["id"])["id"] == a["id"]
    with pytest.raises(LookupError):
        channels.pick(9999)
    db.delete_channel(b["id"])
    assert channels.pick(None) is None


def test_profile_saved_before_new_fields_gets_their_defaults():
    new = ("wide_postiz", "auto_score", "auto_daily")
    old = {k: v for k, v in channels.clean({"name": "Old"}).items() if k not in new}
    cid = db.save_channel(None, old, False)
    ch = next(c for c in channels.listing() if c["id"] == cid)
    assert (ch["wide_postiz"], ch["auto_score"], ch["auto_daily"]) == ([], 0, 2)
    assert channels.pick(cid)["wide_postiz"] == []
    db.delete_channel(cid)


def test_badge_follows_the_channel_then_the_mode():
    news, explainer = {"mode": "news", "meta": {}}, {"mode": topic.MODE, "meta": {}}
    assert channels.badge_for(news) == "ACTU CHINE" and channels.badge_for(explainer) == ""
    ch = _ch(badge="INSOLITE")
    assert channels.badge_for({**explainer, "meta": {"channel": ch["id"]}}) == "INSOLITE"
    none = _ch(badge="")
    assert channels.badge_for({**news, "meta": {"channel": none["id"]}}) == ""  # kênh không nhãn: không nhãn
    assert channels.badge_for({**news, "meta": {"channel": 9999}}) == "ACTU CHINE"  # kênh đã xoá: như không có


def test_next_slot_skips_near_and_taken_times():
    ch = channels.clean({"name": "x", "send_mode": "schedule", "send_times": ["12:00", "18:00"]})
    now = dt.datetime(2026, 10, 1, 11, 55).astimezone()
    first = channels.next_slot(ch, set(), now)
    assert first.startswith("2026-10-01T18:00")  # 12:00 còn 5 phút: quá sát
    assert channels.next_slot(ch, {channels._utc(first)}, now).startswith("2026-10-02T12:00")
    assert channels.next_slot(ch, set(), dt.datetime(2026, 10, 1, 9, 0).astimezone()).startswith("2026-10-01T12:00")


def test_merge_tags_puts_channel_tags_first():
    ch = channels.clean({"name": "x", "hashtags": ["#Chine", "actu"]})
    assert channels.merge_tags(ch, ["#chine", "#tech"]) == ["#Chine", "#actu", "#tech"]
