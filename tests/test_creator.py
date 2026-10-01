"""AI video mode (creator.py, images.py, aiclips.py): scene script, pictures from a provider, slow camera moves, AI
clips for some scenes, the forced video gate, editing and redoing scenes. Every outside service (Claude, ElevenLabs,
fal, Modal, Postiz) is faked."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from motio import aiclips, api, channels, config, creator, db, edit, images, llm, pipeline, render, settings, tts, usage

has_ffmpeg = bool(config.find("ffmpeg") and config.find("ffprobe"))
TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}
LINES = 10  # 10 lines × 20 words × 0.4 s = 80 s of voice


def _plan(n: int = LINES, words: int = 20) -> dict:
    return {"title_fr": "Les pandas de Chengdu", "style": "warm documentary photo, soft light",
            "lines": [{"text": " ".join([f"mot{i}"] * words), "image": f"A panda number {i} eating bamboo",
                       "motion": render.MOTIONS[i % 4]} for i in range(n)],
            "description": "Desc.", "hashtags": ["#Panda"]}


@pytest.fixture
def fake(monkeypatch):
    """Claude, ElevenLabs and the renderer are faked; pictures come from the real placeholder provider."""
    monkeypatch.setenv("IMAGE_PROVIDER", "placeholder")
    monkeypatch.setattr(creator, "RETRY_WAIT", 0)
    seen = {"order": [], "prompts": [], "render": [], "generated": [], "fail": set(), "sec_per_word": 0.4}
    real_generate = images.generate

    def ask_json(prompt, system, **kw):
        seen["prompts"].append((prompt, system))
        if prompt.startswith("Voici un script"):
            seen["order"].append("fit")
            want = int(re.search(r"environ (\d+) mots", prompt)[1])
            return _plan(LINES, want // LINES)
        seen["order"].append("script")
        return _plan()

    def generate(prompt, seed=0, name=None):
        seen["generated"].append((prompt, seed))
        if len(seen["generated"]) in seen["fail"]:
            raise images.ImageError("provider said no")
        return real_generate(prompt, seed, name)

    def synthesize(lines, out_dir, voice=None):
        seen["order"].append("voice")
        durs = [len(t.split()) * seen["sec_per_word"] for t in lines]
        starts = [sum(durs[:i]) for i in range(len(durs))]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "n.mp3").write_bytes(b"mp3")
        return {"audio": str(out_dir / "n.mp3"), "duration": sum(durs), "provider": "fake", "voice": "v",
                "lines": [{"start": a, "end": a + d} for a, d in zip(starts, durs, strict=True)]}

    def fake_render(plan, sources, narration, out_dir, progress=None, min_total=0.0, badge="", wide=False,
                    pieces=None, total=None, src_volume=0.10, delay=0.15, caption_hold=None):
        seen["order"].append("render")
        seen["render"].append({"plan": plan, "sources": sources, "pieces": pieces, "total": total, "badge": badge,
                               "wide": wide})
        (out_dir / "final.mp4").write_bytes(b"v")
        if wide:
            (out_dir / "final_wide.mp4").write_bytes(b"w")
        return {"video": str(out_dir / "final.mp4"), "thumb": "", "duration": total, "pieces": len(pieces),
                "wide": str(out_dir / "final_wide.mp4") if wide else None}

    monkeypatch.setattr(llm, "ask_json", ask_json)
    monkeypatch.setattr(images, "generate", generate)
    monkeypatch.setattr(tts, "synthesize", synthesize)
    monkeypatch.setattr(render, "render", fake_render)
    return seen


def _made(pid: int) -> list:
    return sorted((config.PROJECTS / str(pid) / "scenes").glob("*.png"))


def _last_log(pid: int) -> str:
    return db.get_project(pid)["log"].rstrip("\n").split("\n")[-1]


# ---------- pure parts ----------
def test_create_checks_topic_duration_and_the_provider(monkeypatch):
    with pytest.raises(ValueError, match="Enter a topic"):
        creator.create("   ")
    with pytest.raises(ValueError, match="70, 80, 90"):
        creator.create("Pandas", 60)
    with pytest.raises(ValueError, match="fal key"):  # fal is the default and has no key yet
        creator.create("Pandas")
    monkeypatch.setenv("FAL_KEY", "k")
    pid = creator.create("  Les   pandas ", 90)
    p = db.get_project(pid)
    assert p["mode"] == "ai" and p["title"] == "Les pandas"
    assert p["meta"]["topic"] == "Les pandas" and p["meta"]["duration"] == 90 and p["meta"]["ai"] == {"provider": "fal"}
    monkeypatch.setenv("IMAGE_PROVIDER", "modal")
    monkeypatch.setitem(sys.modules, "modal", None)  # the package isn't installed
    with pytest.raises(ValueError, match="modal"):
        creator.create("Pandas")


def test_tidy_fixes_the_scenes_claude_wrote():
    plan = creator.tidy({"style": " warm  light ", "lines": [
        {"text": "Un", "image": "  A   panda ", "motion": "zoom_out", "seed": 3},
        {"text": "  "},  # empty: dropped
        {"text": "Deux", "motion": "spin", "seed": 0},  # unknown move rotates, seed 0 is the default
        "Trois", {"text": "Quatre", "image": "x" * 900}]})
    assert plan["style"] == "warm light"
    assert [ln["text"] for ln in plan["lines"]] == ["Un", "Deux", "Trois", "Quatre"]
    assert plan["lines"][0] == {"text": "Un", "image": "A panda", "motion": "zoom_out", "seed": 3}
    assert plan["lines"][1]["motion"] == "zoom_out" and "seed" not in plan["lines"][1]  # 2nd slot of the rotation
    assert plan["lines"][2]["image"] == "" and len(plan["lines"][3]["image"]) == creator.MAX_PROMPT


def test_prompt_adds_the_videos_style_then_the_global_style(monkeypatch):
    plan = {"title_fr": "Pandas", "style": "warm light."}
    ln = {"text": "Bonjour", "image": "A panda on a rock."}
    assert creator.prompt(plan, ln) == f"A panda on a rock. warm light. {images.style()}."
    assert creator.prompt({"title_fr": "Pandas"}, {"text": "Bonjour"}).startswith("Pandas: Bonjour. photorealistic")
    monkeypatch.setenv("IMAGE_STYLE", "watercolour")
    assert creator.prompt(plan, ln) == "A panda on a rock. warm light. watercolour."


def test_timeline_gives_each_scene_the_time_of_its_line():
    plan = _plan(4, 10)
    nar = {"duration": 16.0, "lines": [{"start": s, "end": s + 4} for s in (0.0, 4.0, 8.0, 12.0)]}
    pieces = creator.timeline(plan, nar, 62.0)
    assert [(p.src, p.t0, p.dur) for p in pieces] == [(0, 0.0, 4.0), (1, 4.0, 4.0), (2, 8.0, 4.0), (3, 12.0, 50.0)]
    assert [p.motion for p in pieces] == list(render.MOTIONS) and not any(p.still for p in pieces)
    nar["lines"] = []  # no per-line times: the voice is shared by words, pieces still tile the video
    pieces = creator.timeline(plan, nar, 62.0)
    assert pieces[0].t0 == 0.0 and pieces[-1].t0 + pieces[-1].dur == pytest.approx(62.0)
    assert all(abs(a.t0 + a.dur - b.t0) < 0.01 for a, b in zip(pieces, pieces[1:], strict=False))


def test_only_trusted_providers_skip_the_video_gate(monkeypatch):
    def proj(name):
        return {"mode": "ai", "meta": {"ai": {"provider": name}}}

    assert not creator.needs_review(proj("fal"))
    assert creator.needs_review(proj("modal")) and creator.needs_review(proj("placeholder"))
    assert not creator.needs_review({"mode": "topic", "meta": {}})
    monkeypatch.setenv("IMAGE_PROVIDER", "modal")  # no provider recorded yet: the current one counts
    assert creator.needs_review({"mode": "ai", "meta": {}})


# ---------- providers ----------
def test_placeholder_pictures_are_cached_and_differ(tmp_path):
    a, new_a = images.make("a quiet harbour", 0, tmp_path, "placeholder")
    again, new_again = images.make("a quiet harbour", 0, tmp_path, "placeholder")
    other, _ = images.make("a quiet harbour", 1, tmp_path, "placeholder")  # new seed = new picture
    assert (new_a, new_again) == (True, False) and a == again and other != a
    assert Image.open(a).size == (images.WIDTH, images.HEIGHT)
    assert images.key("p", 0, "fal") != images.key("p", 0, "modal") != images.key("p", 1, "modal")
    assert images.cost(12, "fal") == 0.504 and images.cost(12, "placeholder") == 0


def _fal(monkeypatch, status=200, payload=None, png=None):
    sent = []
    png = png or images._placeholder("x", 0)

    def handler(req: httpx.Request) -> httpx.Response:
        req.read()
        sent.append(req)
        if req.url.host == "fal.run":
            if status != 200:
                return httpx.Response(status, json=payload or {"detail": "nope"})
            return httpx.Response(200, json=payload or {"images": [{"url": "https://cdn.fal.test/a.png"}], "seed": 1})
        return httpx.Response(200, content=png)

    monkeypatch.setattr(images, "_transport", httpx.MockTransport(handler))
    monkeypatch.setenv("IMAGE_PROVIDER", "fal")
    monkeypatch.setenv("FAL_KEY", "fal-key")
    return sent


def test_fal_request_and_download(monkeypatch, tmp_path):
    sent = _fal(monkeypatch)
    path, new = images.make("A panda.", 7, tmp_path)
    assert new and Image.open(path).size == (images.WIDTH, images.HEIGHT)
    req = sent[0]
    body = json.loads(req.content)
    assert req.url.path == "/fal-ai/qwen-image-2512" and req.headers["authorization"] == "Key fal-key"
    assert body["prompt"] == "A panda." and body["seed"] == 7 and body["num_images"] == 1
    assert body["image_size"] == {"width": 1088, "height": 1920} and body["enable_safety_checker"] is True
    assert sent[1].url.host == "cdn.fal.test"
    assert images.make("A panda.", 7, tmp_path) == (path, False) and len(sent) == 2  # cached: no new call


@pytest.mark.parametrize("status,payload,message", [
    (401, None, "refused the request"), (403, {"detail": "Exhausted balance"}, "Exhausted balance"),
    (500, {"detail": "boom"}, "could not make the picture: 500 boom"),
    (422, {"detail": [{"msg": "bad size"}]}, "bad size")])
def test_fal_errors_are_explained(monkeypatch, tmp_path, status, payload, message):
    _fal(monkeypatch, status, payload)
    with pytest.raises(images.ImageError, match=message):
        images.make("A panda.", 0, tmp_path)
    assert not list(tmp_path.glob("*.png"))


def test_fal_without_a_picture_or_with_a_bad_file(monkeypatch, tmp_path):
    _fal(monkeypatch, payload={"images": []})
    with pytest.raises(images.ImageError, match="no picture"):
        images.make("A panda.", 0, tmp_path)
    _fal(monkeypatch, png=b"<html>not an image</html>")
    with pytest.raises(images.ImageError, match="did not return a picture"):
        images.make("A panda.", 0, tmp_path)
    assert not list(tmp_path.glob("*"))  # nothing half-written


def test_modal_provider_calls_the_deployed_app(monkeypatch, tmp_path):
    calls = []

    class Gen:
        class generate:
            @staticmethod
            def remote(prompt, w, h, steps, seed):
                calls.append((prompt, w, h, steps, seed))
                return images._placeholder(prompt, seed)

    cls = types.SimpleNamespace(from_name=lambda app, name: (calls.append((app, name)) or (lambda: Gen)))
    monkeypatch.setitem(sys.modules, "modal", types.SimpleNamespace(Cls=cls))
    path, _ = images.make("A panda.", 2, tmp_path, "modal")
    assert calls == [("qwen21-uc", "Qwen21UC"), ("A panda.", 1088, 1920, 25, 2)] and path.is_file()
    monkeypatch.setitem(sys.modules, "modal", None)
    with pytest.raises(images.ImageError, match="modal"):
        images.make("Another.", 0, tmp_path, "modal")


def test_settings_keep_the_fal_key_secret_and_check_the_provider():
    out = settings.update({"FAL_KEY": "fal-secret-1234", "IMAGE_PROVIDER": "placeholder", "IMAGE_STYLE": "ink"})
    assert out["FAL_KEY"] == {"value": "••••1234", "secret": True, "source": "settings"}
    assert out["IMAGE_PROVIDER"]["value"] == "placeholder" and images.provider() == "placeholder"
    assert images.style() == "ink" and config.env("FAL_KEY") == "fal-secret-1234"
    with pytest.raises(ValueError, match="IMAGE_PROVIDER must be one of fal, modal, placeholder"):
        settings.update({"IMAGE_PROVIDER": "dalle"})
    settings.update({"IMAGE_PROVIDER": None})
    assert images.provider() == "fal"  # the default


# ---------- the pipeline ----------
def test_full_ai_run_makes_pictures_voice_and_render(fake):
    pid = creator.create("Les pandas de Chengdu")
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done", p["log"]
    assert fake["order"] == ["script", "voice", "render"] and "Chengdu" in fake["prompts"][0][0]
    assert "Toutes les images" in fake["prompts"][0][1]
    files = _made(pid)
    assert len(files) == LINES and all(Image.open(f).size == (1088, 1920) for f in files)
    r = fake["render"][-1]
    assert len(r["sources"]) == LINES and len(r["pieces"]) == LINES and r["badge"] == ""
    assert {s["path"] for s in r["sources"]} == {str(f) for f in _made(pid)}
    assert [pc.src for pc in r["pieces"]] == list(range(LINES))
    assert all(pc.motion in render.MOTIONS for pc in r["pieces"])
    assert r["total"] == pytest.approx(80.6) and 62 <= r["total"] <= 90
    assert r["pieces"][-1].t0 + r["pieces"][-1].dur == pytest.approx(r["total"])
    ai = p["meta"]["ai"]
    assert ai["provider"] == "placeholder" and ai["scenes"] == LINES and ai["cost"] == 0
    assert creator.view(p)["needs_review"] is True and p["meta"]["title"] == "Les pandas de Chengdu"
    post = (config.PROJECTS / str(pid) / "post.txt").read_text(encoding="utf-8")
    assert "Voix off générée par IA. Images générées par IA." in post
    assert (config.PROJECTS / str(pid) / "sources.txt").read_text(encoding="utf-8").strip() == ""
    assert pipeline.available_steps(pid) == ["script", "voice", "render"]
    assert pipeline.resume_point(pid) == "render"


def test_a_short_script_is_made_longer_and_keeps_its_picture_prompts(fake, monkeypatch):
    def short_then_long(prompt, system, **kw):
        fake["prompts"].append((prompt, system))
        return _plan(LINES, 20) if prompt.startswith("Voici") else _plan(LINES, 8)

    monkeypatch.setattr(llm, "ask_json", short_then_long)
    pid = creator.create("Les pandas")
    pipeline.produce(pid)
    fit = next(p for p, _ in fake["prompts"] if p.startswith("Voici"))
    assert "image (prompt anglais)" in fit and '"image": "A panda number 0' in fit
    plan = json.loads((config.PROJECTS / str(pid) / "script.json").read_text(encoding="utf-8"))
    assert plan["style"] and all(ln["image"] and ln["motion"] in render.MOTIONS for ln in plan["lines"])
    assert db.get_project(pid)["status"] == "done"


def test_a_new_picture_for_one_scene_keeps_the_voice_and_the_other_pictures(fake):
    pid = creator.create("Les pandas")
    pipeline.produce(pid)
    made, voices = len(fake["generated"]), fake["order"].count("voice")
    view = edit.reroll_picture(pid, 2)
    assert view["script"]["lines"][2]["seed"] == 1 and view["script"]["lines"][3]["seed"] == 0
    assert view["script"]["lines"][2]["picture"] is None  # the new picture doesn't exist yet
    assert view["script"]["lines"][3]["picture"].startswith(f"projects/{pid}/scenes/")
    assert "render" in pipeline.available_steps(pid)  # the texts didn't change: the voice is still good
    pipeline.resume(pid, "render")
    assert len(fake["generated"]) == made + 1 and fake["generated"][-1][1] == 1
    assert fake["order"].count("voice") == voices and len(_made(pid)) == LINES + 1
    assert edit.script_view(pid)["script"]["lines"][2]["picture"]
    with pytest.raises(ValueError, match="Scene 11 does not exist"):
        edit.reroll_picture(pid, LINES)


def test_a_failed_picture_is_tried_once_more_then_the_run_resumes(fake):
    fake["fail"] = {3}  # one failure: the second try works
    pid = creator.create("Les pandas")
    pipeline.produce(pid)
    assert db.get_project(pid)["status"] == "done" and len(fake["generated"]) == LINES + 1

    fake["generated"].clear()
    fake["fail"] = {3, 4}  # both tries of picture 3 fail
    pid = creator.create("Les pandas 2")
    with pytest.raises(RuntimeError, match="Picture 3 failed: provider said no"):
        pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "failed" and "Picture 3 failed" in p["log"] and len(_made(pid)) == 2
    assert pipeline.resume_point(pid) == "voice" and "voice" not in fake["order"][-2:]
    fake["generated"].clear()
    fake["fail"] = set()  # the provider works again
    pipeline.resume(pid)  # the script and the two pictures are kept: only the missing 8 are made
    assert db.get_project(pid)["status"] == "done" and len(fake["generated"]) == LINES - 2 and len(_made(pid)) == LINES


def test_editing_the_scenes_marks_the_video_stale(fake):
    pid = creator.create("Les pandas")
    pipeline.produce(pid)
    view = edit.script_view(pid)
    script = view["script"]
    assert script["style"].startswith("warm") and view["ai"]["provider"] == "placeholder"
    line = script["lines"][0]
    assert line["image"].startswith("A panda number 0") and line["motion"] == "zoom_in" and line["picture"]
    assert view["dub"] is None and line["clips"] == []

    def save(line0=None, **change):
        raw = edit.script_view(pid)["script"]  # what the app would send back after the owner's edit
        raw["lines"][0].update(line0 or {})
        return edit.save_script(pid, {**raw, **change})

    final = config.PROJECTS / str(pid) / "final.mp4"
    os.utime(final, (time.time() - 60, time.time() - 60))  # the video is older than the edits below
    before = db.get_project(pid)["log"]
    save()  # nothing changed
    assert db.get_project(pid)["log"] == before
    save({"image": "A red panda on a branch"})
    assert _last_log(pid).endswith("Script edited: pictures · re-render to update the video")
    assert edit.script_view(pid)["script"]["lines"][0]["image"] == "A red panda on a branch"
    assert edit.script_view(pid)["script"]["lines"][0]["picture"] is None  # new prompt: no picture yet
    assert edit.script_view(pid)["stale"] is True
    save(style="cold blue light")  # the video's style changes every prompt
    assert _last_log(pid).endswith("Script edited: pictures · re-render to update the video")
    assert edit.script_view(pid)["script"]["style"] == "cold blue light"
    save({"motion": "pan_right"})
    assert _last_log(pid).endswith("Script edited: camera moves · re-render to update the video")
    assert edit.script_view(pid)["script"]["lines"][0]["motion"] == "pan_right"
    save({"text": "Un tout nouveau texte"})
    assert "narration" in _last_log(pid) and "render" not in pipeline.available_steps(pid)  # the voice is stale
    with pytest.raises(ValueError, match="picture prompt of line 1"):
        save({"image": "x" * (creator.MAX_PROMPT + 1)})
    save(description="Nouvelle description.")
    post = (config.PROJECTS / str(pid) / "post.txt").read_text(encoding="utf-8")
    assert "Nouvelle description." in post and "Voix off générée par IA. Images générées par IA." in post


def test_other_modes_do_not_keep_scene_fields():
    clean = edit.clean({"title_fr": "T", "lines": [{"text": "a", "image": "x", "motion": "zoom_in"}] * 3})
    assert clean["lines"][0] == {"text": "a", "clips": []} and "style" not in clean
    ai = edit.clean({"title_fr": "T", "style": " warm ", "lines": [{"text": "a", "image": " x ", "motion": "?",
                                                                    "seed": 2}] * 3}, ai=True)
    assert ai["lines"][0] == {"text": "a", "image": "x", "motion": "zoom_in", "seed": 2} and ai["style"] == "warm"


def _channel(**kw) -> dict:
    return channels.create({"name": "Explainers", "gate_script": False, "gate_video": False, "postiz": ["tt1"],
                            **kw})


def _posts(calls) -> int:
    return sum(1 for r in calls if r.url.path.endswith("/posts"))


def test_placeholder_and_modal_pictures_never_go_out_without_approval(fake, fake_postiz):
    ch = _channel()  # no video gate and a Postiz channel: a normal video would be sent at once
    pid = creator.create("Les pandas")
    channels.attach(pid, ch)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "review" and p["meta"]["review"] == "video" and _posts(fake_postiz) == 0
    assert "isn't cleared for monetized channels" in p["log"]
    pipeline.approve_video(pid)
    assert db.get_project(pid)["status"] == "done" and _posts(fake_postiz) == 1  # the owner looked: it goes out


def test_fal_pictures_go_out_like_any_other_video(fake, fake_postiz, monkeypatch):
    sent = _fal(monkeypatch)  # switches the provider to fal, with a fake fal behind it
    pid = creator.create("Les pandas")
    channels.attach(pid, _channel())
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done", p["log"]
    assert p["meta"]["ai"]["provider"] == "fal" and p["meta"]["ai"]["cost"] == pytest.approx(LINES * 0.042)
    assert "Made 10 of 10 pictures · about $0.42" in p["log"] and _posts(fake_postiz) == 1
    assert len([r for r in sent if r.url.host == "fal.run"]) == LINES
    assert not creator.needs_review(p)


def test_a_script_gate_stops_before_any_picture_is_paid_for(fake):
    ch = _channel(gate_script=True, postiz=[])
    pid = creator.create("Les pandas")
    channels.attach(pid, ch)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "review" and p["meta"]["review"] == "script" and not fake["generated"]
    assert fake["order"] == ["script"]
    db.update_project(pid, meta={"review": None})
    pipeline.produce(pid, start="voice")  # what "approve" does
    assert db.get_project(pid)["status"] == "done" and len(fake["generated"]) == LINES


# ---------- AI clips ----------
@pytest.fixture
def clip_fake(fake, monkeypatch):
    """`fake` plus a fal key and a fake H3 Max: every call is recorded in fake["clips"], and FFmpeg's sound strip is a
    plain copy. fake["clips"]["fail"] lists the call numbers (1-based, retries count) that fail."""
    monkeypatch.setenv("FAL_KEY", "fal-key")
    with db.conn() as c:
        c.execute("DELETE FROM usage")
    seen = {"calls": [], "fail": set()}

    def generate(picture, text, seed=0, **kw):
        seen["calls"].append((os.path.basename(picture), text, seed))
        if len(seen["calls"]) in seen["fail"]:
            raise aiclips.ClipError("fal said no")
        return b"mp4"

    def run(cmd):
        shutil.copy(cmd[cmd.index("-i") + 1], cmd[-1])

    monkeypatch.setattr(aiclips, "generate", generate)
    monkeypatch.setattr(config, "ffmpeg", lambda: "ffmpeg")  # built before the fake _run; CI has no FFmpeg
    monkeypatch.setattr(render, "_run", run)
    fake["clips"] = seen
    yield fake
    with db.conn() as c:
        c.execute("DELETE FROM usage")


def _clip_scenes(fake) -> list[int]:
    return [i for i, s in enumerate(fake["render"][-1]["sources"]) if s.get("clip")]


def _usd(pid: int) -> float:
    return db.usage_sum(0, project_id=pid)[1]


def test_pick_spreads_the_clips_and_always_takes_the_hook():
    assert aiclips.pick(10, 3) == [0, 3, 6] and aiclips.pick(10, 1) == [0] and aiclips.pick(10, 0) == []
    assert aiclips.pick(4, 10) == [0, 1, 2, 3] and aiclips.pick(0, 3) == []
    assert all(aiclips.pick(12, n)[0] == 0 and len(set(aiclips.pick(12, n))) == n for n in range(1, 13))


def test_the_projects_choice_beats_the_channels_and_both_are_capped():
    ch = {"ai_clips": 4}
    assert aiclips.limit({"meta": {}}, ch) == 4 and aiclips.limit({"meta": {}}, None) == 0
    assert aiclips.limit({"meta": {"ai": {"clip_limit": 0}}}, ch) == 0
    assert aiclips.limit({"meta": {"ai": {"clip_limit": 2}}}, ch) == 2
    assert aiclips.limit({"meta": {"ai": {"clip_limit": 99}}}, ch) == aiclips.MAX_PER_VIDEO == 6


def test_the_clip_prompt_describes_the_move():
    text = aiclips.prompt("A panda eating bamboo.", "pan_left")
    assert text.startswith("A panda eating bamboo. Slow pan to the left,") and text.endswith("no cuts.")
    assert "Gentle camera move" in aiclips.prompt("A panda", "")


def _fal_clip(monkeypatch, status=200, payload=None, video=b"mp4"):
    sent = []

    def handler(req: httpx.Request) -> httpx.Response:
        req.read()
        sent.append(req)
        if req.url.host == "fal.run":
            if status != 200:
                return httpx.Response(status, json=payload or {"detail": "nope"})
            return httpx.Response(200, json=payload or {"video": {"url": "https://cdn.fal.test/a.mp4"}})
        return httpx.Response(200, content=video)

    monkeypatch.setattr(aiclips, "_transport", httpx.MockTransport(handler))
    monkeypatch.setenv("FAL_KEY", "fal-key")
    monkeypatch.setattr(config, "ffmpeg", lambda: "ffmpeg")  # built before the fake _run; CI has no FFmpeg
    monkeypatch.setattr(render, "_run", lambda cmd: shutil.copy(cmd[cmd.index("-i") + 1], cmd[-1]))
    return sent


def test_fal_clip_request_download_and_cache(monkeypatch, tmp_path):
    sent = _fal_clip(monkeypatch)
    pic = tmp_path / "a.png"
    Image.new("RGB", (1088, 1920), "gray").save(pic)
    path, new = aiclips.make(pic, "A panda. Slow push-in.", 7, tmp_path / "clips")
    assert new and path.read_bytes() == b"mp4" and path.suffix == ".mp4"
    req = sent[0]
    body = json.loads(req.content)
    assert req.url.path == "/minimax/h3-max/image-to-video" and req.headers["authorization"] == "Key fal-key"
    assert body["prompt"] == "A panda. Slow push-in." and body["seed"] == 7 and body["duration"] == 5
    assert body["resolution"] == "768P" and body["enable_safety_checker"] is True
    assert body["image_url"].startswith("data:image/jpeg;base64,") and sent[1].url.host == "cdn.fal.test"
    assert aiclips.make(pic, "A panda. Slow push-in.", 7, tmp_path / "clips") == (path, False) and len(sent) == 2
    other, fresh = aiclips.make(pic, "A panda. Slow push-in.", 8, tmp_path / "clips")  # another seed: another clip
    assert fresh and other != path and not list((tmp_path / "clips").glob("*.raw"))


@pytest.mark.parametrize("status,payload,message", [
    (401, None, "refused the request"), (403, {"detail": "Exhausted balance"}, "Exhausted balance"),
    (500, {"detail": "boom"}, "could not make the clip: 500 boom"),
    (200, {"video": None}, "returned no clip"), (200, {"nothing": 1}, "returned no clip")])
def test_fal_clip_errors_are_explained(monkeypatch, tmp_path, status, payload, message):
    _fal_clip(monkeypatch, status, payload)
    pic = tmp_path / "a.png"
    Image.new("RGB", (64, 64), "gray").save(pic)
    with pytest.raises(aiclips.ClipError, match=message):
        aiclips.make(pic, "A panda.", 0, tmp_path / "clips")
    assert not list((tmp_path / "clips").glob("*.mp4"))


def test_a_clip_ffmpeg_cannot_read_is_an_error_and_leaves_nothing_behind(monkeypatch, tmp_path):
    _fal_clip(monkeypatch)

    def broken(cmd):
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(render, "_run", broken)
    pic = tmp_path / "a.png"
    Image.new("RGB", (64, 64), "gray").save(pic)
    with pytest.raises(aiclips.ClipError, match="not a readable video"):
        aiclips.make(pic, "A panda.", 0, tmp_path / "clips")
    assert list((tmp_path / "clips").iterdir()) == []


def test_ai_clips_replace_the_camera_move_on_scenes_spread_over_the_video(clip_fake):
    pid = creator.create("Les pandas", 80, 3)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done", p["log"]
    r = clip_fake["render"][-1]
    assert _clip_scenes(clip_fake) == [0, 3, 6] == aiclips.pick(LINES, 3)
    assert all(r["sources"][i]["path"].endswith(".mp4") for i in (0, 3, 6))
    assert all(r["sources"][i]["path"].endswith(".png") for i in (1, 2, 4, 5, 7, 8, 9))
    assert [pc.motion == "" for pc in r["pieces"]] == [i in (0, 3, 6) for i in range(LINES)]
    assert all(pc.motion in render.MOTIONS for pc in r["pieces"] if pc.src not in (0, 3, 6))
    assert [pc.src for pc in r["pieces"]] == list(range(LINES)) and r["total"] == pytest.approx(80.6)
    calls = clip_fake["clips"]["calls"]
    assert [c[0].endswith(".png") for c in calls] == [True] * 3 and "A panda number 0" in calls[0][1]
    assert "Slow push-in" in calls[0][1]
    assert "A panda number 3" in calls[1][1] and "Slow pan to the right" in calls[1][1]
    ai = p["meta"]["ai"]
    assert ai["clips"] == 3 and ai["clip_limit"] == 3 and ai["cost"] == pytest.approx(1.2)  # 3 × 5 s × $0.08
    assert creator.view(p)["clips"] == 3
    chars, usd = db.usage_sum(0, project_id=pid)
    assert chars == 0 and usd == pytest.approx(1.2) and usage.for_project(pid)["usd"] == pytest.approx(1.2)
    assert usage.for_project(pid)["clip_usd"] == pytest.approx(1.2)
    assert "3 of 3 AI clips ready · about $1.20" in p["log"]
    post = (config.PROJECTS / str(pid) / "post.txt").read_text(encoding="utf-8")
    assert "Voix off générée par IA. Images et vidéos générées par IA." in post


def test_a_rerender_reuses_the_clips_and_does_not_pay_again(clip_fake):
    pid = creator.create("Les pandas", 80, 2)
    pipeline.produce(pid)
    made, paid = len(clip_fake["clips"]["calls"]), _usd(pid)
    assert made == 2 and paid == pytest.approx(0.8)
    pipeline.resume(pid, "render")
    p = db.get_project(pid)
    assert p["status"] == "done" and len(clip_fake["clips"]["calls"]) == made and _usd(pid) == pytest.approx(paid)
    assert _clip_scenes(clip_fake) == [0, 5] and p["meta"]["ai"]["clips"] == 2
    assert p["meta"]["ai"]["cost"] == pytest.approx(0.8)
    assert "2 of 2 AI clips ready · about $0.00" in p["log"]


def test_heygen_clips_never_go_out_without_approval(clip_fake, fake_postiz, monkeypatch):
    _fal(monkeypatch)  # the pictures are from the cleared provider: only the clips are in question
    monkeypatch.setenv("CLIP_PROVIDER", "heygen")
    monkeypatch.setenv("HEYGEN_API_KEY", "hg-key")
    pid = creator.create("Les pandas", 80, 2)
    channels.attach(pid, _channel())  # no video gate and a Postiz channel: a normal video would be sent at once
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "review" and p["meta"]["review"] == "video" and _posts(fake_postiz) == 0
    assert p["meta"]["ai"]["clip_provider"] == "heygen" and creator.view(p)["clip_provider"] == "heygen"
    assert "terms for monetized channels are not checked yet" in p["log"]
    assert usage.for_project(pid)["clip_usd"] == pytest.approx(0.2)  # 2 clips × 5 s × $0.02
    pipeline.approve_video(pid)
    assert db.get_project(pid)["status"] == "done" and _posts(fake_postiz) == 1


def test_a_settings_change_in_the_middle_of_a_render_does_not_mix_two_clip_providers(clip_fake, monkeypatch):
    _fal(monkeypatch)  # the pictures are from the cleared provider: only the clips are in question
    real = aiclips.generate

    def switch_after_the_first(picture, text, seed=0, **kw):
        out = real(picture, text, seed, **kw)
        monkeypatch.setenv("CLIP_PROVIDER", "heygen")  # the owner changes the provider while the render runs
        monkeypatch.setenv("HEYGEN_API_KEY", "hg-key")
        return out

    monkeypatch.setattr(aiclips, "generate", switch_after_the_first)
    pid = creator.create("Les pandas", 80, 3)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done", p["log"]
    assert p["meta"]["ai"]["clips"] == 3 and p["meta"]["ai"]["clip_provider"] == "fal"
    assert usage.for_project(pid)["clip_usd"] == pytest.approx(1.2)  # 3 × 5 s × fal's $0.08, none at HeyGen's $0.02
    assert not creator.clips_need_review(p)  # all three clips came from fal, whatever Settings says now


def test_a_clip_fal_cannot_make_keeps_its_camera_move_and_the_video_finishes(clip_fake):
    clip_fake["clips"]["fail"] = {2, 3}  # scene 3 fails twice (one retry); scenes 0 and 6 work
    pid = creator.create("Les pandas", 80, 3)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done", p["log"]
    assert _clip_scenes(clip_fake) == [0, 6] and clip_fake["render"][-1]["pieces"][3].motion in render.MOTIONS
    assert "Clip for scene 4 failed (fal said no): it keeps its camera move" in p["log"]
    assert p["meta"]["ai"]["clips"] == 2 and _usd(pid) == pytest.approx(0.8)  # the failed one cost nothing
    assert "2 of 3 AI clips ready" in p["log"]


def test_no_clip_is_made_once_the_monthly_budget_is_reached(clip_fake):
    settings.update({"MONTHLY_BUDGET_USD": "0.5"})
    pid = creator.create("Les pandas", 80, 4)
    pipeline.produce(pid)
    p = db.get_project(pid)
    assert p["status"] == "done", p["log"]
    assert _clip_scenes(clip_fake) == [0, 2] and _usd(pid) == pytest.approx(0.8)  # $0.40 each: the 3rd would be over
    assert "Monthly budget reached: the other scenes keep their camera move" in p["log"]
    assert p["meta"]["ai"]["clips"] == 2


def test_the_price_per_second_is_a_setting():
    assert usage.clip_price() == usage.DEFAULT_CLIP_PRICE == 0.08 and aiclips.cost(2) == pytest.approx(0.8)
    settings.update({"AI_CLIP_USD_PER_SEC": "0.05"})
    assert aiclips.cost(1) == pytest.approx(0.25)
    with pytest.raises(ValueError, match="AI_CLIP_USD_PER_SEC must be a number"):
        settings.update({"AI_CLIP_USD_PER_SEC": "-1"})
    settings.update({"AI_CLIP_USD_PER_SEC": None})
    assert usage.clip_price() == 0.08


def test_the_channel_sets_how_many_clips_and_a_video_can_override_it(clip_fake):
    ch = _channel(gate_video=True, postiz=[], ai_clips=2)
    pid = creator.create("Les pandas")
    channels.attach(pid, ch)
    pipeline.produce(pid)
    assert _clip_scenes(clip_fake) == [0, 5] and db.get_project(pid)["meta"]["ai"]["clips"] == 2
    calls = len(clip_fake["clips"]["calls"])
    pid2 = creator.create("Les pandas 2", 80, 0)  # this video: no clips, whatever the channel says
    channels.attach(pid2, ch)
    pipeline.produce(pid2)
    assert _clip_scenes(clip_fake) == [] and len(clip_fake["clips"]["calls"]) == calls
    assert db.get_project(pid2)["meta"]["ai"].get("clips") in (None, 0)


def test_going_back_to_no_clips_clears_them_and_the_post_label(clip_fake):
    pid = creator.create("Les pandas", 80, 2)
    pipeline.produce(pid)
    meta = db.get_project(pid)["meta"]
    db.update_project(pid, meta={"ai": {**meta["ai"], "clip_limit": 0}})
    pipeline.resume(pid, "render")
    p = db.get_project(pid)
    assert _clip_scenes(clip_fake) == [] and p["meta"]["ai"]["clips"] == 0 and not creator.view(p)["clips"]
    post = (config.PROJECTS / str(pid) / "post.txt").read_text(encoding="utf-8")
    assert "Images générées par IA." in post and "vidéos" not in post


def test_editing_the_description_keeps_the_ai_clips_label(clip_fake):
    pid = creator.create("Les pandas", 80, 2)
    pipeline.produce(pid)
    view = edit.script_view(pid)
    body = view["script"]
    body["description"] = "Une autre description."
    edit.save_script(pid, body)
    post = (config.PROJECTS / str(pid) / "post.txt").read_text(encoding="utf-8")
    assert "Une autre description." in post and "Images et vidéos générées par IA." in post


def test_a_missing_fal_key_stops_before_any_picture_is_paid_for(fake, monkeypatch):
    ch = _channel(gate_video=True, postiz=[], ai_clips=2)
    pid = creator.create("Les pandas")
    channels.attach(pid, ch)
    with pytest.raises(ValueError, match="AI clips need your fal key"):
        pipeline.produce(pid)
    assert _made(pid) == [] and not fake["generated"] and db.get_project(pid)["status"] == "failed"
    with pytest.raises(ValueError, match="AI clips need your fal key"):
        creator.create("Les pandas", 80, 2)
    creator.create("Les pandas", 80, 0)  # no clips asked: no key needed


def test_the_channel_profile_validates_the_clip_count():
    assert channels.clean({"name": "A"})["ai_clips"] == 0
    assert channels.clean({"name": "A", "ai_clips": "3"})["ai_clips"] == 3
    with pytest.raises(ValueError, match="between 0 and 6"):
        channels.clean({"name": "A", "ai_clips": 7})
    with pytest.raises(ValueError, match="between 0 and 6"):
        channels.clean({"name": "A", "ai_clips": -1})
    with pytest.raises(ValueError, match="must be a number"):
        channels.clean({"name": "A", "ai_clips": "many"})
    assert channels.full(db.get_channel(channels.create({"name": "B", "ai_clips": 4})["id"]))["ai_clips"] == 4


def test_the_timeline_plays_a_clip_instead_of_a_camera_move():
    plan = _plan(3, 10)
    nar = {"duration": 12.0, "lines": [{"start": 0.0, "end": 4.0}, {"start": 4.0, "end": 8.0},
                                       {"start": 8.0, "end": 12.0}]}
    scenes = [{"path": "a.mp4", "clip": True}, {"path": "b.png"}, {"path": "c.png"}]
    pieces = creator.timeline(plan, nar, 12.6, scenes)
    assert [pc.motion for pc in pieces] == ["", "zoom_out", "pan_left"]
    assert [pc.motion for pc in creator.timeline(plan, nar, 12.6)] == ["zoom_in", "zoom_out", "pan_left"]


def test_a_script_changed_by_the_voice_step_still_has_a_picture_for_every_scene(fake, monkeypatch):
    fake["sec_per_word"] = 0.25  # the voice comes out at 50 s: the voice step asks Claude for a longer script

    def one_more_line(prompt, system, **kw):
        fake["prompts"].append((prompt, system))
        fake["order"].append("fit" if prompt.startswith("Voici") else "script")
        return _plan(LINES + 1, 30) if prompt.startswith("Voici") else _plan(LINES, 20)

    monkeypatch.setattr(llm, "ask_json", one_more_line)
    pid = creator.create("Les pandas")
    pipeline.produce(pid)
    assert db.get_project(pid)["status"] == "done" and fake["order"] == ["script", "voice", "fit", "voice", "render"]
    r = fake["render"][-1]
    assert len(r["plan"]["lines"]) == LINES + 1 and len(r["sources"]) == LINES + 1 and len(r["pieces"]) == LINES + 1
    assert len(fake["generated"]) == LINES + 1  # the ten pictures already made are reused, the new line gets its own


# ---------- API ----------
@pytest.fixture
def client(monkeypatch):
    def fake_produce(pid, **kw):
        db.update_project(pid, status="done", step="Done", pct=100)

    monkeypatch.setattr(pipeline, "produce", fake_produce)
    monkeypatch.setenv("IMAGE_PROVIDER", "placeholder")
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


def _wait_done(client, pid) -> dict:
    for _ in range(500):
        p = client.get(f"/api/projects/{pid}", headers=H).json()
        if p["status"] == "done":
            return p
        time.sleep(0.02)
    return p


def test_ai_routes(client, monkeypatch):
    r = client.post("/api/ai", headers=H, json={"topic": "Les pandas", "duration": 70})
    assert r.status_code == 202
    pid = r.json()["project_id"]
    p = _wait_done(client, pid)
    assert p["mode"] == "ai" and p["ai"]["provider"] == "placeholder" and p["ai"]["needs_review"] is True
    assert p["dub"] is None and p["meta"]["duration"] == 70 and p["retry"]["steps"] == ["script"]
    assert client.post("/api/ai", headers=H, json={"topic": " "}).status_code == 400
    assert client.post("/api/ai", headers=H, json={"topic": "x", "duration": 50}).status_code == 400
    assert client.post("/api/ai", headers=H, json={"topic": "x", "channel": 999}).status_code == 400
    monkeypatch.setenv("IMAGE_PROVIDER", "fal")  # no key
    bad = client.post("/api/ai", headers=H, json={"topic": "x"})
    assert bad.status_code == 400 and "fal key" in bad.json()["detail"]
    other = client.post("/api/projects", headers=H, json={"topic": "panda"}).json()["project_id"]
    assert _wait_done(client, other)["ai"] is None


def test_ai_route_takes_the_clip_count_and_checks_the_fal_key(client, monkeypatch):
    assert "between 0 and 6" in client.post("/api/ai", headers=H, json={"topic": "x", "clips": 7}).json()["detail"]
    no_key = client.post("/api/ai", headers=H, json={"topic": "x", "clips": 2})
    assert no_key.status_code == 400 and "fal key" in no_key.json()["detail"]
    assert client.post("/api/ai", headers=H, json={"topic": "x", "clips": 0}).status_code == 202  # none: no key needed
    monkeypatch.setenv("FAL_KEY", "fal-key")
    pid = client.post("/api/ai", headers=H, json={"topic": "x", "clips": 2}).json()["project_id"]
    assert _wait_done(client, pid)["ai"]["clip_limit"] == 2
    monkeypatch.delenv("FAL_KEY")
    default = client.post("/api/channels", headers=H, json={"name": "Clips", "ai_clips": 3, "default": True})
    assert default.status_code == 201 and default.json()["ai_clips"] == 3
    via_channel = client.post("/api/ai", headers=H, json={"topic": "x"})  # the channel's 3 clips need the key too
    assert via_channel.status_code == 400 and "fal key" in via_channel.json()["detail"]
    assert client.post("/api/ai", headers=H, json={"topic": "x", "clips": 0}).status_code == 202
    assert client.post("/api/channels", headers=H, json={"name": "Too many", "ai_clips": 7}).status_code == 400


def test_scene_routes(client, monkeypatch):
    pid = creator.create("Les pandas")
    out = config.PROJECTS / str(pid)
    out.mkdir(parents=True, exist_ok=True)
    (out / "script.json").write_text(json.dumps(_plan(4, 10)), encoding="utf-8")
    db.update_project(pid, status="done")
    r = client.get(f"/api/projects/{pid}/script", headers=H)
    assert r.status_code == 200 and r.json()["script"]["lines"][1]["motion"] == "zoom_out"
    body = r.json()["script"]
    body["lines"][1]["image"] = "A zoo at night"
    body["style"] = "neon"
    r = client.put(f"/api/projects/{pid}/script", headers=H, json=body)
    assert r.status_code == 200 and r.json()["script"]["lines"][1]["image"] == "A zoo at night"
    assert r.json()["script"]["style"] == "neon"
    r = client.post(f"/api/projects/{pid}/scenes/1/redo", headers=H)
    assert r.status_code == 200 and r.json()["script"]["lines"][1]["seed"] == 1
    assert client.post(f"/api/projects/{pid}/scenes/9/redo", headers=H).status_code == 400
    assert client.post("/api/projects/9999/scenes/0/redo", headers=H).status_code == 404
    db.update_project(pid, status="running")
    assert client.post(f"/api/projects/{pid}/scenes/1/redo", headers=H).status_code == 409
    news = db.create_project(None, "Autre", mode="topic")
    db.update_project(news, status="done")
    (config.PROJECTS / str(news)).mkdir(parents=True, exist_ok=True)
    (config.PROJECTS / str(news) / "script.json").write_text(json.dumps(_plan(4, 10)), encoding="utf-8")
    assert client.post(f"/api/projects/{news}/scenes/0/redo", headers=H).status_code == 400


# ---------- real FFmpeg ----------
def _probe(path) -> dict:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,nb_frames:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    data = json.loads(r.stdout)
    return {**data["streams"][0], "duration": float(data["format"]["duration"])}


def _frame(video, at, dest):
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1",
                    str(dest)], check=True)
    return Image.open(dest).convert("RGB")


def test_kenburns_filter_for_each_move():
    zin = render.kenburns("zoom_in", 6.0, 1080, 1920)
    assert "z='1+0.12*min(on/180,1)'" in zin and "s=1080x1920" in zin and f"fps={render.FPS}" in zin
    assert "d=189" in zin  # the move lasts 6 s; 0.3 s more so the next step can cut at the exact length
    assert "1+0.12-0.12*min(on/180,1)" in render.kenburns("zoom_out", 6.0, 1080, 1920)
    left, right = render.kenburns("pan_left", 6.0, 1080, 1920), render.kenburns("pan_right", 6.0, 1080, 1920)
    assert "x='(iw-iw/zoom)*(1-min(on/180,1))'" in left and "x='(iw-iw/zoom)*min(on/180,1)'" in right
    assert "z='1+0.12'" in left and "x='iw/2-iw/zoom/2'" in zin


def test_moving_pictures_fill_a_vertical_frame_and_sit_in_a_wide_one(tmp_path):
    f = tmp_path / "a.png"
    Image.new("RGB", (images.WIDTH, images.HEIGHT), "gray").save(f)
    assert render.moving_size(str(f), render.VERTICAL) == (1080, 1920)  # 1088×1920 is close enough to 9:16: crop
    w, h = render.moving_size(str(f), render.WIDE)
    assert h == 1080 and 600 <= w <= 620 and w % 2 == 0  # fit, with the blurred background around it
    Image.new("RGB", (1000, 1000), "gray").save(f)
    assert render.moving_size(str(f), render.VERTICAL) == (1080, 1080)


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
def test_real_render_of_ai_scenes_moves_and_keeps_both_formats(tmp_path):
    scenes = []
    for i in range(3):
        path, _ = images.make(f"Scene {i}", 0, tmp_path / "scenes", "placeholder")
        scenes.append({"path": str(path), "platform": "AI", "uploader": "placeholder", "duration": 0, "url": None})
    voice = tmp_path / "voice.m4a"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=500:d=9", "-c:a", "aac",
                    str(voice)], check=True)
    plan = {"title_fr": "Les pandas de Chengdu", "lines": [
        {"text": "Premier point du sujet", "motion": "zoom_in"}, {"text": "Deuxième point, sans détour",
                                                                  "motion": "pan_right"},
        {"text": "Troisième point, pour finir", "motion": "zoom_out"}]}
    nar = {"audio": str(voice), "duration": 9.0, "lines": [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.0},
                                                          {"start": 6.0, "end": 9.0}]}
    out = tmp_path / "out"
    res = render.render(**creator.render_args(plan, scenes, nar, 0.0), narration=nar, out_dir=out, wide=True)
    tall, wide = _probe(res["video"]), _probe(res["wide"])
    assert (tall["width"], tall["height"]) == (1080, 1920) and (wide["width"], wide["height"]) == (1920, 1080)
    assert abs(tall["duration"] - 9.6) < 0.3 and abs(wide["duration"] - tall["duration"]) < 0.2
    assert res["pieces"] == 3 and (out / "captions.srt").read_text(encoding="utf-8").strip()
    early, late = _frame(res["video"], 0.4, tmp_path / "a.png"), _frame(res["video"], 2.6, tmp_path / "b.png")
    assert ImageChops.difference(early, late).getbbox()  # the picture moved during the scene
    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    assert [t["motion"] for t in timeline] == ["zoom_in", "pan_right", "zoom_out"] and timeline[0]["url"] is None
    buf = io.BytesIO()
    early.save(buf, "PNG")
    assert buf.tell() > 1000


def _tone_clip(path, seconds=5):
    """A small vertical clip with a sound track, like what fal returns."""
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc=size=216x384:rate=24:duration={seconds}", "-f", "lavfi", "-i",
                    f"sine=f=440:d={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(path)], check=True)


def _video_seconds(path) -> float:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def _streams(path) -> list[str]:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True, check=True)
    return r.stdout.split()


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
def test_real_clip_loses_its_sound_and_a_long_scene_holds_the_last_frame(monkeypatch, tmp_path):
    src = tmp_path / "fal.mp4"
    _tone_clip(src)
    assert "audio" in _streams(src)
    monkeypatch.setenv("FAL_KEY", "fal-key")
    monkeypatch.setattr(aiclips, "generate", lambda picture, text, seed=0, **kw: src.read_bytes())
    pic, _ = images.make("Scene 0", 0, tmp_path / "scenes", "placeholder")
    clip, new = aiclips.make(pic, "A panda.", 0, tmp_path / "clips")
    assert new and _streams(clip) == ["video"]

    pic2, _ = images.make("Scene 1", 0, tmp_path / "scenes", "placeholder")
    scenes = [{"path": str(clip), "platform": "AI", "uploader": "fal", "duration": 0, "url": None, "clip": True},
              {"path": str(pic2), "platform": "AI", "uploader": "placeholder", "duration": 0, "url": None}]
    voice = tmp_path / "voice.m4a"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=500:d=12", "-c:a", "aac",
                    str(voice)], check=True)
    plan = {"title_fr": "Les pandas", "lines": [{"text": "Une scène de neuf secondes", "motion": "zoom_in"},
                                                 {"text": "Une scène de trois secondes", "motion": "pan_right"}]}
    nar = {"audio": str(voice), "duration": 12.0, "lines": [{"start": 0.0, "end": 9.0}, {"start": 9.0, "end": 12.0}]}
    out = tmp_path / "out"
    res = render.render(**creator.render_args(plan, scenes, nar, 0.0), narration=nar, out_dir=out)
    # the 5 s clip fills a 9 s scene (last frame held), so the video is as long as the voice and the next scene is
    # where the voice says it is
    assert abs(_probe(res["video"])["duration"] - 12.6) < 0.3
    assert abs(_video_seconds(out / "pieces" / "p_000.mp4") - 9.0) < 0.1  # frames all the way, no gap after the clip
    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    assert [t["motion"] for t in timeline] == ["", "pan_right"] and timeline[0]["dur"] == pytest.approx(9.0)
    early, late = _frame(res["video"], 1.0, tmp_path / "a.png"), _frame(res["video"], 4.0, tmp_path / "b.png")
    assert ImageChops.difference(early, late).getbbox()  # the clip plays
