"""AI video series and recurring characters (motio/series.py): the cast's fixed looks, the series block of the script
prompt, recaps of earlier episodes, and how the channel profile keeps both."""
import json

import pytest
from fastapi.testclient import TestClient

from motio import api, channels, creator, db, images, llm, pipeline, render, series

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}
CAST = ("Mina: a girl of about 10 with short black hair and a red raincoat\n"
        "Bolt: a small round robot, dented silver body")


def _ai(channel: int | None, title: str = "Les toits", recap: str | None = None, status: str = "done",
        episode: int = 0) -> int:
    pid = db.create_project(None, title, mode="ai")
    ai = {k: v for k, v in {"recap": recap, "episode": episode or None}.items() if v}
    db.update_project(pid, status=status, meta={"topic": title, "ai": ai} | ({"channel": channel} if channel else {}))
    return pid


# ---------- the cast ----------
def test_cast_lines_are_name_colon_look():
    cast = series.parse_cast(" Mina :  a girl  with a red raincoat \n\nBolt：a small robot")  # full-width colon too
    assert cast == {"Mina": "a girl with a red raincoat", "Bolt": "a small robot"}
    assert list(series.parse_cast(CAST)) == ["Mina", "Bolt"]
    assert series.parse_cast("") == {} and series.parse_cast(None) == {}


def test_a_loose_cast_skips_bad_lines_and_a_strict_one_refuses_them():
    text = "Mina: a girl\nno colon here\nBolt:\nmina: the same name again\n: nameless"
    assert series.parse_cast(text) == {"Mina": "a girl"}
    for bad in ("no colon here", "Bolt:", "Mina: a girl\nMINA: again", f"{'x' * 41}: a look"):
        with pytest.raises(ValueError, match="Name: how they look"):
            series.parse_cast(bad, strict=True)
    too_many = "\n".join(f"C{i}: a look" for i in range(series.MAX_CAST + 1))
    with pytest.raises(ValueError, match=f"At most {series.MAX_CAST}"):
        series.parse_cast(too_many, strict=True)
    assert len(series.parse_cast(too_many)) == series.MAX_CAST  # not strict: the extra ones are left out


def test_a_scene_gets_the_fixed_look_of_every_character_it_names():
    cast = series.parse_cast(CAST)
    assert series.named("mina and BOLT on a roof", cast) == ["Mina", "Bolt"]
    assert series.named("Minaret at dusk, a bolted door", cast) == []  # whole words only
    assert series.named("", cast) == []
    one = series.with_cast("Mina waves from a rooftop at dawn.", cast)
    assert one == ("Characters, always drawn exactly like this — Mina: a girl of about 10 with short black hair and a "
                   "red raincoat. Scene: Mina waves from a rooftop at dawn.")
    both = series.with_cast("Bolt follows Mina.", cast)
    assert "Mina: a girl" in both and "Bolt: a small round robot, dented silver body." in both
    assert both.endswith("Scene: Bolt follows Mina.")
    assert series.with_cast("A rooftop at dawn.", cast) == "A rooftop at dawn."
    assert series.with_cast("Mina waves.", None) == "Mina waves."


def test_the_picture_prompt_carries_the_look_and_a_changed_look_makes_a_new_picture(tmp_path):
    plan = {"title_fr": "Les toits", "style": "warm light", "cast": series.parse_cast(CAST)}
    ln = {"text": "Mina court.", "image": "Mina runs across a wet rooftop."}
    first = creator.prompt(plan, ln)
    assert first.startswith("Characters, always drawn exactly like this — Mina: a girl of about 10")
    assert "Scene: Mina runs across a wet rooftop." in first and "warm light" in first
    other = {**plan, "cast": {"Mina": "a woman in her 30s with a green coat"}}
    assert creator.prompt(other, ln) != first
    assert creator.picture_file(tmp_path, plan, ln, "fal") != creator.picture_file(tmp_path, other, ln, "fal")
    nobody = {"text": "Un toit.", "image": "An empty rooftop."}  # no character named: the prompt is as before
    assert creator.prompt(plan, nobody) == creator.prompt({**plan, "cast": {}}, nobody)


# ---------- the series block of the script prompt ----------
def test_no_series_and_no_cast_leave_the_prompt_alone():
    assert series.block(None, 5) == ("", None)
    ch = channels.create({"name": "Explainers"})
    assert series.block(ch, 5) == ("", None)


def test_a_cast_alone_names_the_characters_but_does_not_number_episodes():
    ch = channels.create({"name": "Toits", "cast": CAST})
    text, episode = series.block(ch, 5)
    assert episode is None
    assert "- Mina" in text and "- Bolt" in text and "NE décris PAS leur apparence" in text
    assert "red raincoat" not in text  # the look is added by Motio, Claude never sees it
    assert "recap" not in text


def test_a_series_is_written_as_the_next_episode_of_the_channel():
    ch = channels.create({"name": "Toits", "series": "Un robot et un chat explorent la ville."})
    other = channels.create({"name": "Autre", "series": "Autre histoire."})
    text, episode = series.block(ch, 100)
    assert episode == 1 and "épisode 1" in text and "Un robot et un chat" in text
    assert "Épisodes précédents" not in text and "« recap »" in text

    e1 = _ai(ch["id"], "Le premier toit", "Le robot trouve une clé.")
    _ai(other["id"], "Ailleurs", "Autre chaîne.")  # another channel's episode does not count
    _ai(ch["id"], "Raté", "Échec.", status="failed")  # a failed one does not count
    _ai(ch["id"], "Sans résumé")  # no recap, nothing to continue from
    pid = db.create_project(None, "Une vidéo normale", mode="topic")
    db.update_project(pid, meta={"channel": ch["id"], "ai": {"recap": "pas une vidéo AI"}})
    e2 = _ai(ch["id"], "Le deuxième toit", "Le chat ouvre la porte.", episode=7)
    later = _ai(ch["id"], "Plus tard", "Écrit après.")

    text, episode = series.block(ch, later)
    assert episode == 8  # follows the highest number kept on an earlier episode
    assert "Épisode 1 « Le premier toit » : Le robot trouve une clé." in text
    assert "Épisode 7 « Le deuxième toit » : Le chat ouvre la porte." in text
    assert text.index("Le premier toit") < text.index("Le deuxième toit")
    for left_out in ("Autre chaîne", "Échec", "pas une vidéo AI", "Écrit après"):
        assert left_out not in text
    assert [e["pid"] for e in series.earlier(ch["id"], later)] == [e1, e2]


def test_only_the_last_recaps_are_told_to_claude():
    ch = channels.create({"name": "Toits", "series": "Une histoire."})
    for i in range(series.RECENT + 3):
        _ai(ch["id"], f"Épisode titre {i}", f"Résumé numéro {i}.")
    text, episode = series.block(ch, 10_000)
    assert episode == series.RECENT + 4
    assert "Résumé numéro 2." not in text and "Résumé numéro 3." in text
    assert f"Résumé numéro {series.RECENT + 2}." in text


# ---------- the script step ----------
def _script(words: int = 20, lines: int = 10, **extra) -> dict:
    return {"title_fr": "Les toits", "style": "warm light", "description": "Desc.", "hashtags": ["#Toits"],
            "lines": [{"text": " ".join([f"mot{i}"] * words), "image": f"Mina on roof number {i}",
                       "motion": render.MOTIONS[i % 4]} for i in range(lines)], **extra}


def _step(pid: int, tmp_path):
    out = tmp_path / str(pid)
    out.mkdir()
    return pipeline._step_ai_script(db.get_project(pid), out, lambda *a, **k: None, 80), out


def test_the_script_step_tells_claude_the_series_and_keeps_the_cast_and_the_recap(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_PROVIDER", "placeholder")
    ch = channels.create({"name": "Toits", "series": "Un robot et un chat explorent la ville.", "cast": CAST})
    asked = []

    def ask_json(prompt, system, **kw):
        asked.append(prompt)
        return _script(recap=f"  Résumé   de l'épisode {len(asked)}. ")

    monkeypatch.setattr(llm, "ask_json", ask_json)
    first = creator.create("Le premier toit")
    channels.attach(first, ch)
    plan, out = _step(first, tmp_path)
    assert "épisode 1" in asked[0] and "- Mina" in asked[0] and "Épisodes précédents" not in asked[0]
    assert asked[0].index("Série") < asked[0].index("Réponds avec")  # the block comes before the answer format
    assert plan["cast"] == series.parse_cast(CAST) and plan["recap"] == "Résumé de l'épisode 1."
    assert json.loads((out / "script.json").read_text(encoding="utf-8"))["cast"]["Bolt"].startswith("a small round")
    ai = db.get_project(first)["meta"]["ai"]
    assert ai["episode"] == 1 and ai["recap"] == "Résumé de l'épisode 1." and ai["provider"] == "placeholder"

    second = creator.create("Le deuxième toit")
    channels.attach(second, ch)
    plan, _ = _step(second, tmp_path)
    assert "épisode 2" in asked[1] and "Épisode 1 « Le premier toit » : Résumé de l'épisode 1." in asked[1]
    assert db.get_project(second)["meta"]["ai"]["episode"] == 2

    again = pipeline._step_ai_script(db.get_project(second), tmp_path / str(second), lambda *a, **k: None, 80)  # retry
    assert again["recap"] and "épisode 2" in asked[2]  # it does not count itself as an earlier episode


def test_a_channel_without_a_series_writes_the_script_as_before(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_PROVIDER", "placeholder")
    asked = []
    monkeypatch.setattr(llm, "ask_json", lambda prompt, system, **kw: asked.append(prompt) or _script())
    ch = channels.create({"name": "Explainers"})
    pid = creator.create("Les pandas")
    channels.attach(pid, ch)
    plan, _ = _step(pid, tmp_path)
    assert "Série" not in asked[0] and "recap" not in asked[0] and "Personnages" not in asked[0]
    assert "cast" not in plan and "recap" not in plan and "episode" not in db.get_project(pid)["meta"]["ai"]
    assert asked[0].endswith('"hashtags": ["#...", "..."]}')


def test_a_cast_without_a_series_still_keeps_the_looks_but_no_episode(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_PROVIDER", "placeholder")
    monkeypatch.setattr(llm, "ask_json", lambda prompt, system, **kw: _script())
    ch = channels.create({"name": "Toits", "cast": CAST})
    pid = creator.create("Un toit")
    channels.attach(pid, ch)
    plan, _ = _step(pid, tmp_path)
    assert plan["cast"]["Mina"].startswith("a girl of about 10")
    assert "episode" not in db.get_project(pid)["meta"]["ai"]


def test_the_pictures_step_sends_the_looks_to_the_image_model(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_PROVIDER", "placeholder")
    seen = []
    real = images.generate

    def generate(prompt, seed=0, name=None):
        seen.append(prompt)
        return real(prompt, seed, name)

    monkeypatch.setattr(images, "generate", generate)
    pid = creator.create("Un toit")
    plan = creator.tidy(_script(lines=3) | {"cast": series.parse_cast(CAST)})
    plan["lines"][2]["image"] = "An empty rooftop."
    creator.pictures(pid, plan, tmp_path, lambda *a, **k: None)
    looked = [p.startswith("Characters, always drawn exactly like this — Mina: a girl") for p in seen]
    assert looked == [True, True, False]


def test_tidy_keeps_a_clean_recap_and_the_cast():
    plan = creator.tidy({"recap": "  Un  résumé. ", "cast": {"Mina": "a girl"}, "lines": [{"text": "Un"}]})
    assert plan["recap"] == "Un résumé." and plan["cast"] == {"Mina": "a girl"}
    assert len(creator.tidy({"recap": "x" * 900, "lines": [{"text": "Un"}]})["recap"]) == creator.MAX_RECAP
    assert "recap" not in creator.tidy({"lines": [{"text": "Un"}]})


# ---------- the channel profile ----------
def test_a_profile_keeps_the_series_and_the_cast():
    ch = channels.create({"name": "Toits", "series": "  Un robot et un chat.  ", "cast": f"\n  {CAST}\n\n"})
    assert ch["series"] == "Un robot et un chat." and ch["cast"] == CAST
    assert channels.create({"name": "Vide"})["series"] == "" and channels.create({"name": "Vide 2"})["cast"] == ""
    with pytest.raises(ValueError, match="Cast line 2 must look like"):
        channels.clean({"name": "Toits", "cast": "Mina: a girl\nBolt"})
    long = channels.clean({"name": "Toits", "series": "s" * 3000, "cast": "Mina: " + "a" * 3000})
    assert len(long["series"]) == channels.MAX_SERIES and len(long["cast"]) == channels.MAX_CAST_TEXT
    # a profile saved before the fields existed reads as empty
    old = channels.full({"id": 1, "name": "Ancien"})
    assert old["series"] == "" and old["cast"] == ""


def test_the_channel_endpoints_take_the_series_and_the_cast():
    with TestClient(api.create_app(TOKEN)) as c:
        r = c.post("/api/channels", headers=H, json={"name": "Toits", "series": "Un robot.", "cast": CAST})
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        got = next(x for x in c.get("/api/channels", headers=H).json() if x["id"] == cid)
        assert got["series"] == "Un robot." and got["cast"] == CAST
        bad = c.put(f"/api/channels/{cid}", headers=H, json={"name": "Toits", "cast": "Mina without a look"})
        assert bad.status_code == 400 and "Name: how they look" in bad.json()["detail"]
        ok = c.put(f"/api/channels/{cid}", headers=H, json={"name": "Toits", "series": "", "cast": ""})
        assert ok.status_code == 200 and ok.json()["cast"] == ""
