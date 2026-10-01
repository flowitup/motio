"""HeyGen Video 1 as the second AI clip provider (aiclips.py): the request, the polling, the errors, the price and the
settings. HeyGen is faked with httpx.MockTransport; nothing here calls the real API (no key, and it costs money)."""
import json
import shutil
import types

import httpx
import pytest
from PIL import Image

from motio import aiclips, config, creator, db, render, settings, usage

API = "https://api.heygen.com/v3/models/videos"


@pytest.fixture
def heygen(monkeypatch, tmp_path):
    """HeyGen faked: `st.script` is the list of answers to the status look-ups (a dict = body, an int = HTTP code)."""
    st = types.SimpleNamespace()
    st.sent, st.script, st.create = [], [{"status": "completed", "video_url": "https://cdn.heygen.test/a.mp4"}], None

    def handler(req: httpx.Request) -> httpx.Response:
        req.read()
        st.sent.append(req)
        if req.url.host == "cdn.heygen.test":
            return httpx.Response(200, content=b"mp4")
        if req.method == "POST":
            if st.create is not None:
                return st.create
            return httpx.Response(202, json={"data": {"video_id": "v1", "status": "pending"}})
        step = st.script.pop(0) if len(st.script) > 1 else st.script[0]
        if isinstance(step, int):
            return httpx.Response(step, json={"error": {"message": "boom"}})
        return httpx.Response(200, json={"data": {"video_id": "v1", **step}})

    monkeypatch.setattr(aiclips, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(aiclips, "_sleep", lambda s: None)
    monkeypatch.setenv("CLIP_PROVIDER", "heygen")
    monkeypatch.setenv("HEYGEN_API_KEY", "hg-key")
    monkeypatch.setattr(config, "ffmpeg", lambda: "ffmpeg")  # built before the fake _run; CI has no FFmpeg
    monkeypatch.setattr(render, "_run", lambda cmd: shutil.copy(cmd[cmd.index("-i") + 1], cmd[-1]))
    pic = tmp_path / "a.png"
    Image.new("RGB", (1088, 1920), "gray").save(pic)
    st.pic, st.folder = pic, tmp_path / "clips"
    return st


def test_the_picture_is_the_first_frame_and_the_job_is_polled_until_done(heygen):
    heygen.script = [{"status": "pending"}, {"status": "processing"},
                     {"status": "completed", "video_url": "https://cdn.heygen.test/a.mp4"}]
    path, new = aiclips.make(heygen.pic, "A panda. Slow push-in.", 7, heygen.folder)
    assert new and path.read_bytes() == b"mp4"
    create = heygen.sent[0]
    body = json.loads(create.content)
    assert create.method == "POST" and str(create.url) == API and create.headers["x-api-key"] == "hg-key"
    assert body["mode"] == "image_to_video" and body["model"] == "heygen-video-1" and body["seed"] == 7
    assert body["duration"] == 5 and body["resolution"] == "768p" and "aspect_ratio" not in body
    assert body["prompt"] == "A panda. Slow push-in. Silent scene, no dialogue, no music."
    assert body["image"]["type"] == "base64" and body["image"]["media_type"] == "image/jpeg" and body["image"]["data"]
    looks = [r for r in heygen.sent if r.method == "GET" and r.url.host == "api.heygen.com"]
    assert [str(r.url) for r in looks] == [f"{API}/v1"] * 3
    assert heygen.sent[-1].url.host == "cdn.heygen.test" and "x-api-key" not in heygen.sent[-1].headers  # signed link


def test_a_clip_is_cached_per_provider(heygen, monkeypatch):
    path, _ = aiclips.make(heygen.pic, "A panda.", 0, heygen.folder)
    calls = len(heygen.sent)
    assert aiclips.make(heygen.pic, "A panda.", 0, heygen.folder) == (path, False) and len(heygen.sent) == calls
    monkeypatch.setenv("CLIP_PROVIDER", "fal")  # the same picture through fal is another clip, and the old key is kept
    assert aiclips.path_for(heygen.folder, heygen.pic, "A panda.", 0) != path
    assert aiclips.key(heygen.pic, "A panda.", 0) != ""


def test_the_status_answer_may_come_without_the_data_wrapper(heygen):
    heygen.script = [{"status": "completed", "video_url": "https://cdn.heygen.test/a.mp4"}]
    assert aiclips.generate(heygen.pic, "A panda.", 0) == b"mp4"


@pytest.mark.parametrize("create,script,message", [
    (httpx.Response(401, json={"error": {"message": "bad key"}}), None, "refused the request .401 bad key"),
    (httpx.Response(402, json={}), None, "no credit left"),
    (httpx.Response(400, json={"error": {"message": "image too large"}}), None, "create 400 image too large"),
    (httpx.Response(202, json={"data": {}}), None, "returned no clip"),
    (None, [{"status": "failed", "failure_code": "generation_failed", "failure_message": "filtered"}],
     "generation_failed filtered"),
    (None, [{"status": "completed"}], "returned no clip"),
    (None, [503], "status 503 boom")])
def test_errors_are_explained_and_leave_nothing_behind(heygen, create, script, message):
    heygen.create = create
    if script:
        heygen.script = script
    with pytest.raises(aiclips.ClipError, match=message):
        aiclips.make(heygen.pic, "A panda.", 0, heygen.folder)
    assert not list(heygen.folder.glob("*.mp4"))


def test_a_job_that_never_ends_is_given_up(heygen):
    heygen.script = [{"status": "processing"}]
    with pytest.raises(aiclips.ClipError, match="took too long"):
        aiclips.generate(heygen.pic, "A panda.", 0)
    looks = [r for r in heygen.sent if r.method == "GET"]
    assert len(looks) == int(aiclips.MAX_WAIT / aiclips.POLL_EVERY) + 1


def test_the_provider_is_a_setting_with_its_own_key_and_price(monkeypatch):
    monkeypatch.delenv("CLIP_PROVIDER", raising=False)
    assert aiclips.provider() == "fal" and usage.clip_price() == 0.08 and aiclips.endpoint() == aiclips.ENDPOINT
    with pytest.raises(ValueError, match="CLIP_PROVIDER must be one of"):
        settings.update({"CLIP_PROVIDER": "kling"})
    out = settings.update({"CLIP_PROVIDER": "heygen", "HEYGEN_API_KEY": "hg-secret-1234"})
    assert out["HEYGEN_API_KEY"] == {"value": "••••1234", "secret": True, "source": "settings"}
    assert aiclips.provider() == "heygen" and aiclips.endpoint() == "heygen/heygen-video-1"
    assert usage.clip_price() == 0.02 and aiclips.cost(6) == pytest.approx(0.6)  # 6 clips of 5 s at the list price
    settings.update({"AI_CLIP_USD_PER_SEC": "0.01"})  # the owner's own price (the October promotion) wins
    assert aiclips.cost(6) == pytest.approx(0.3)
    settings.update({"CLIP_PROVIDER": None})
    monkeypatch.setenv("CLIP_PROVIDER", "nonsense")
    assert aiclips.provider() == "fal"  # an unknown name in the environment falls back to fal


def test_each_provider_needs_its_own_key(monkeypatch):
    monkeypatch.setenv("CLIP_PROVIDER", "heygen")
    with pytest.raises(ValueError, match="need your HeyGen key"):
        aiclips.check_ready()
    monkeypatch.setenv("FAL_KEY", "fal-key")  # the fal key does not help HeyGen
    with pytest.raises(ValueError, match="need your HeyGen key"):
        aiclips.check_ready()
    monkeypatch.setenv("HEYGEN_API_KEY", "hg-key")
    aiclips.check_ready()
    monkeypatch.setenv("CLIP_PROVIDER", "fal")
    monkeypatch.delenv("FAL_KEY")
    with pytest.raises(ValueError, match="need your fal key"):
        aiclips.check_ready()


def test_heygen_clips_hold_the_video_at_the_gate_until_the_terms_are_checked():
    def proj(**ai):
        return {"mode": "ai", "meta": {"ai": {"provider": "fal", **ai}}}

    assert creator.needs_review(proj(clips=3, clip_provider="heygen"))
    assert creator.clips_need_review(proj(clips=3, clip_provider="heygen"))
    assert not creator.needs_review(proj(clips=3, clip_provider="fal"))
    assert not creator.needs_review(proj(clips=0, clip_provider="heygen"))  # re-rendered without clips: back to normal
    assert not creator.needs_review(proj())
    assert not aiclips.needs_review(None) and aiclips.needs_review("heygen")


def test_a_trial_clip_uses_the_chosen_provider_and_is_paid_and_recorded(heygen, monkeypatch):
    monkeypatch.setenv("CLIP_PROVIDER", "fal")  # Settings say fal, the try-out asks for HeyGen
    with db.conn() as c:
        c.execute("DELETE FROM usage")
    path, usd = aiclips.trial(heygen.pic, "A panda.", "heygen", heygen.folder)
    assert path.parent.name == "heygen" and path.read_bytes() == b"mp4" and usd == pytest.approx(0.1)
    assert [r.url.host for r in heygen.sent][0] == "api.heygen.com" and aiclips.provider() == "fal"  # restored
    assert db.usage_sum(0)[1] == pytest.approx(0.1)
    assert aiclips.trial(heygen.pic, "A panda.", "heygen", heygen.folder)[1] == 0.0  # cached: free
    with pytest.raises(ValueError, match="CLIP_PROVIDER must be one of"):
        aiclips.trial(heygen.pic, "A panda.", "kling", heygen.folder)
    monkeypatch.delenv("HEYGEN_API_KEY")
    with pytest.raises(ValueError, match="need your HeyGen key"):
        aiclips.trial(heygen.pic, "Another.", "heygen", heygen.folder)
    assert aiclips.provider() == "fal"
