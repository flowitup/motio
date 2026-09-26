import datetime as dt
import json

import pytest

from motio import postiz


def test_settings_for_video_platforms():
    tt = postiz.settings_for("tiktok", "T" * 120, ["#chine"])
    assert tt["__type"] == "tiktok" and len(tt["title"]) == 90 and tt["video_made_with_ai"] is True
    assert {"privacy_level", "duet", "stitch", "comment", "autoAddMusic", "brand_content_toggle",
            "brand_organic_toggle", "content_posting_method"} <= tt.keys()
    yt = postiz.settings_for("youtube", "Y" * 150, ["#chine", "info", "#"])
    assert len(yt["title"]) == 100 and yt["type"] == "public"
    assert yt["tags"] == [{"value": "chine", "label": "chine"}, {"value": "info", "label": "info"}]
    assert postiz.settings_for("instagram-standalone", "t", [])["post_type"] == "post"
    assert postiz.settings_for("bluesky", "t", []) == {"__type": "bluesky"}


def test_publish_uploads_then_creates_one_post_per_channel(fake_postiz, tmp_path):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00" * 64)
    res = postiz.publish(video, "Titre\n\nDescription", "Titre", ["#chine"], ["tt1", "yt1"], "draft")

    assert [r.url.path for r in fake_postiz] == ["/api/public/v1/integrations", "/api/public/v1/upload",
                                                 "/api/public/v1/posts"]
    assert b'filename="final.mp4"' in fake_postiz[1].content
    body = json.loads(fake_postiz[2].content)
    assert body["type"] == "draft" and body["date"].endswith("Z") and body["shortLink"] is False
    assert [p["integration"]["id"] for p in body["posts"]] == ["tt1", "yt1"]
    assert [p["settings"]["__type"] for p in body["posts"]] == ["tiktok", "youtube"]
    assert body["posts"][0]["value"] == [{"content": "Titre\n\nDescription",
                                          "image": [{"id": "m1", "path": "https://postiz.test/uploads/final.mp4"}]}]
    assert [p["postId"] for p in res["posts"]] == ["p0", "p1"]
    assert [c["name"] for c in res["channels"]] == ["Motio TikTok", "Motio YouTube"]


def test_publish_rejects_bad_input_before_uploading(fake_postiz, tmp_path):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"x")
    with pytest.raises(ValueError):
        postiz.publish(video, "t", "t", [], ["nope"], "draft")
    with pytest.raises(ValueError):
        postiz.publish(video, "t", "t", [], [], "draft")
    with pytest.raises(ValueError):
        postiz.publish(video, "t", "t", [], ["tt1"], "later")
    assert all(not r.url.path.endswith("/upload") for r in fake_postiz)


def test_schedule_date_rules(fake_postiz, tmp_path):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"x")
    for when in (None, "demain", "2030-01-01T10:00:00", "2001-01-01T10:00:00+00:00"):
        with pytest.raises(ValueError):
            postiz.publish(video, "t", "t", [], ["tt1"], "schedule", when)
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).replace(microsecond=0)
    res = postiz.publish(video, "t", "t", [], ["tt1"], "schedule", future.astimezone().isoformat())
    assert res["date"] == future.isoformat().replace("+00:00", "Z")


def test_not_configured_and_bad_key(fake_postiz, monkeypatch):
    monkeypatch.setenv("POSTIZ_API_KEY", "wrong")
    with pytest.raises(postiz.PostizError, match="401"):
        postiz.channels()
    monkeypatch.delenv("POSTIZ_API_KEY")
    assert not postiz.configured()
    with pytest.raises(postiz.PostizError):
        postiz.channels()
