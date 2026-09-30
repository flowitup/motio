"""AI video mode (creator.py, images.py): scene script, pictures from a provider, slow camera moves, the forced video
gate, editing and redoing scenes. Every outside service (Claude, ElevenLabs, fal, Modal, Postiz) is faked."""
import io
import json
import os
import re
import subprocess
import sys
import time
import types

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from motio import api, channels, config, creator, db, edit, images, llm, pipeline, render, settings, tts

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
