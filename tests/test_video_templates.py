"""Video templates: looks (motio/looks.py), the starter set and the owner's own (motio/video_templates.py), and what the
renderer does with a look."""
import json
import subprocess

import pytest
from PIL import Image

from motio import captions, channels, config, db, looks, render
from motio import video_templates as vt


@pytest.fixture(autouse=True)
def _no_user_templates():
    """The database is shared by the whole test run: start each test with none of the owner's templates."""
    for row in db.list_templates():
        db.delete_template(row["id"])
    yield
    for row in db.list_templates():
        db.delete_template(row["id"])


def _cue():
    row1 = [captions.Word(t, i * .3, i * .3 + .3) for i, t in enumerate("Le vélo électrique".split())]
    row2 = [captions.Word(t, 1 + i * .3, 1.3 + i * .3) for i, t in enumerate("conquiert Shanghai".split())]
    return captions.Cue(0, 2, [row1, row2])


def _new_project(meta=None):
    pid = db.create_project(None, "Titre")
    if meta:
        db.update_project(pid, meta=meta)
    return pid


# ---------- looks ----------
def test_clean_fills_defaults_and_rejects_bad_values():
    assert looks.clean(None) == looks.DEFAULT and looks.is_default({}) and looks.is_default(looks.DEFAULT)
    got = looks.clean({"caption": {"font": "nope", "size": 500, "color": "red", "spoken": "#abc123", "box": "x",
                                   "pos": "sky", "pop": 9, "stroke_w": -3},
                       "title": {"pos": "lower", "accent": "#ffd60a", "align": "right"},
                       "frame": {"blur": 1000, "color": "#000"}, "motion": {"mode": "spin"}})
    c = got["caption"]
    assert (c["font"], c["size"], c["color"], c["spoken"], c["box"], c["pos"]) == \
        ("system", looks.SIZE_MAX, "#FFFFFF", "#ABC123", "none", "below")
    assert (c["pop"], c["stroke_w"]) == (0.4, 0)
    assert got["title"]["pos"] == "lower" and got["title"]["accent"] == "#FFD60A" and got["title"]["align"] == "left"
    assert got["frame"] == {"blur": 80, "dim": 0.1, "color": ""} and got["motion"]["mode"] == "auto"
    assert not looks.is_default(got)


def test_bundled_fonts_exist_and_have_french_letters():
    from PIL import ImageFont
    for key, (_, file) in looks.FONTS.items():
        if not file:
            continue
        path = looks.FONT_DIR / file
        assert path.exists(), key
        assert (looks.FONT_DIR / f"OFL-{path.stem.split('-')[0].lower()}.txt").exists() or key == "poppins_bold"
        f = ImageFont.truetype(str(path), 40)
        assert all(f.getmask(ch).getbbox() for ch in "éèêàçœ«»’")


def test_system_font_is_the_fallback():
    assert looks.font_candidates("system") == config.font_candidates("bold")
    assert looks.font_candidates("anton")[0].endswith("Anton-Regular.ttf")
    assert looks.font_candidates("anton", cjk=True) == config.font_candidates("cjk")


# ---------- the renderer ----------
def test_default_look_draws_what_motio_always_drew(tmp_path):
    a = render.caption_png(tmp_path / "a.png", _cue(), 2)
    b = render.caption_png(tmp_path / "b.png", _cue(), 2, render.VERTICAL, looks.clean(None))
    assert Image.open(a).tobytes() == Image.open(b).tobytes()
    o1 = render.overlay_png(tmp_path / "o1.png", title="Le vélo", badge="ACTU")
    o2 = render.overlay_png(tmp_path / "o2.png", title="Le vélo", badge="ACTU", look=looks.clean(None))
    assert Image.open(o1).tobytes() == Image.open(o2).tobytes()
    assert render.look_layout(render.VERTICAL, None) == render.VERTICAL
    assert render.look_layout(render.WIDE, None) == render.WIDE


def test_look_changes_the_caption_picture(tmp_path):
    base = Image.open(render.caption_png(tmp_path / "a.png", _cue(), 2)).tobytes()
    for part in ({"upper": True}, {"font": "anton"}, {"box": "line"}, {"box": "word"}, {"active_box": "#F76F00"},
                 {"pop": 0.15}, {"glow": "#00C8FF"}, {"spoken": "#00FF00"}, {"color": "#CCCCCC"}):
        look = looks.clean({"caption": part})
        lay = render.look_layout(render.VERTICAL, look)
        got = Image.open(render.caption_png(tmp_path / "b.png", _cue(), 2, lay, look)).tobytes()
        assert got != base, part


def test_caption_size_and_position_follow_the_look():
    big = looks.clean({"caption": {"size": 90, "pos": "middle"}})
    lay = render.look_layout(render.VERTICAL, big)
    assert lay.cap_size == 90 and lay.cap_line > render.VERTICAL.cap_line
    assert lay.cap_top == (render.VERTICAL.h - lay.cap_h) // 2
    low = render.look_layout(render.VERTICAL, looks.clean({"caption": {"pos": "lower"}}))
    assert low.cap_top == round(render.VERTICAL.h * 0.66)
    wide = render.look_layout(render.WIDE, looks.clean({"caption": {"size": 30}}))
    assert wide.cap_size < render.WIDE.cap_size


def test_caption_fits_measures_with_the_looks_font():
    assert render.caption_fits()("Un texte court") and not render.caption_fits()("x" * 60)
    wide_caps = looks.clean({"caption": {"font": "archivo", "size": 100, "upper": True}})
    text = "Le vélo électrique conquiert"
    assert render.caption_fits()(text) and not render.caption_fits(wide_caps)(text)


def test_title_band_follows_the_look(tmp_path):
    plain = render.overlay_png(tmp_path / "a.png", title="Le *vélo* roule")
    low = looks.clean({"title": {"pos": "lower", "align": "center", "upper": True, "accent": "#FFD60A"}})
    img = Image.open(render.overlay_png(tmp_path / "b.png", title="Le *vélo* roule", layout=render.VERTICAL, look=low))
    assert img.getbbox()[1] > render.VERTICAL.h * 0.6  # nothing in the top part
    assert Image.open(plain).getbbox()[1] < 200
    hidden = Image.open(render.overlay_png(tmp_path / "c.png", title="x", look={"title": {"show": False}}))
    assert hidden.getbbox() is None
    assert render._marked("Le *vélo électrique* roule *vite*", False) == [
        ("Le", False), ("vélo", True), ("électrique", True), ("roule", False), ("vite", True)]


def test_camera_replaces_the_moves_by_mode():
    pieces = [render.Piece(i, 0, 3, 3 * i, motion=m) for i, m in enumerate(["zoom_in", "pan_left", "", "zoom_out"])]
    assert render.camera(pieces, None) == pieces
    alt = render.camera(pieces, {"motion": {"mode": "alternate"}})
    assert [p.motion for p in alt] == ["zoom_in", "zoom_out", "", "zoom_in"]  # a source video keeps no motion
    assert [p.motion for p in render.camera(pieces, {"motion": {"mode": "pan"}})] == \
        ["pan_left", "pan_right", "", "pan_left"]
    assert {p.motion for p in render.camera(pieces, {"motion": {"mode": "zoom_out"}}) if p.motion} == {"zoom_out"}
    assert pieces[0].motion == "zoom_in"  # the originals are not touched


def test_backdrop_filter():
    assert render._backdrop(looks.DEFAULT["frame"]) == "gblur=sigma=36,eq=brightness=-0.10:saturation=0.9"
    assert "gblur" not in render._backdrop({"blur": 0, "dim": 0.3, "color": ""})
    assert render._backdrop({"blur": 9, "dim": 0.1, "color": "#0F1115"}) == \
        "drawbox=x=0:y=0:w=iw:h=ih:color=0x0F1115:t=fill"
    assert "zoompan=z='1+0.3*min" in render.kenburns("zoom_in", 5, 100, 100, 0.3)


@pytest.mark.skipif(not config.find("ffmpeg"), reason="needs ffmpeg")
def test_render_with_a_look_makes_a_different_video(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:d=8",
                    "-f", "lavfi", "-i", "sine=f=300:d=8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(src)], check=True)
    voice = tmp_path / "voice.m4a"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=500:d=4", "-c:a", "aac",
                    str(voice)], check=True)
    plan = {"title_fr": "La Chine lance un *train* rapide",
            "lines": [{"text": "Premier point du sujet", "clips": [{"src": 0, "start": 1, "end": 4}]},
                      {"text": "Deuxième point pour finir", "clips": []}]}
    nar = {"audio": str(voice), "duration": 4.0, "lines": [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]}
    sources = [{"path": str(src), "duration": 8.0, "platform": "youtube", "uploader": "t", "url": "u"}]
    look = next(t for t in vt.builtin() if t["key"] == "b:series_card")["look"]
    a = render.render(plan, sources, nar, tmp_path / "a", badge="ACTU")
    b = render.render(plan, sources, nar, tmp_path / "b", badge="ACTU", look=look)
    c = render.render(plan, sources, nar, tmp_path / "c", badge="ACTU", look=looks.clean(None))
    frames = []
    for name, res in (("a", a), ("b", b), ("c", c)):
        f = tmp_path / f"{name}.png"
        subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-ss", "2.5", "-i", res["video"], "-frames:v", "1",
                        str(f)], check=True)
        frames.append(Image.open(f).convert("RGB"))
    assert frames[0].size == (1080, 1920) and frames[1].size == (1080, 1920)
    assert frames[0].tobytes() != frames[1].tobytes()
    assert (frames[0].tobytes() == frames[2].tobytes())  # an explicit default look = no look


# ---------- templates ----------
def test_starter_set_is_complete_and_valid():
    keys = [t["key"] for t in vt.builtin()]
    assert len(keys) == len(set(keys)) >= 12 and keys[0] == vt.DEFAULT_KEY
    for t in vt.builtin():
        assert t["builtin"] and t["note"] and t["look"] == looks.clean(t["look"])
        assert t["look"]["caption"]["font"] in looks.FONTS
    assert looks.is_default(vt.get("b:classic")["look"])
    assert all(not looks.is_default(t["look"]) for t in vt.builtin()[1:])
    assert any("tuantudo86" in t["credit"] for t in vt.builtin())  # the idea's source is named


def test_every_builtin_has_a_vietnamese_note(monkeypatch):
    from motio import i18n
    monkeypatch.setenv("UI_LANG", "vi")
    for t in vt.builtin():
        assert t["note"] in i18n.VI.values(), t["key"]


def test_user_templates_crud_export_import():
    with pytest.raises(ValueError, match="name"):
        vt.create({"name": "  "})
    t = vt.create({"name": "  Mon  style ", "look": {"caption": {"font": "bebas", "upper": True}}, "duration": 90,
                   "src_volume": 3, "voice_id": " v1 "})
    assert t["key"].startswith("u:") and t["name"] == "Mon style" and not t["builtin"]
    assert (t["duration"], t["src_volume"], t["voice_id"]) == (90, 1.0, "v1")
    assert t["look"]["caption"]["font"] == "bebas" and t["look"]["caption"]["size"] == 60
    with pytest.raises(ValueError, match="Duration"):
        vt.create({"name": "x", "duration": 33})
    up = vt.update(t["key"], {"name": "Renamed", "look": {"caption": {"size": 70}}})
    assert up["name"] == "Renamed" and up["look"]["caption"]["size"] == 70 and up["duration"] is None
    again = vt.import_json(json.dumps(vt.export(t["key"])))
    assert again["key"] != t["key"] and again["look"] == up["look"] and again["name"] == "Renamed"
    for bad in ("not json", "[]", '{"name": "x"}', '{"look": 3}'):
        with pytest.raises(ValueError, match="not a Motio template"):
            vt.import_json(bad)
    keys = [x["key"] for x in vt.listing()]
    assert t["key"] in keys and again["key"] in keys and len(keys) == len(vt.builtin()) + 2
    vt.delete(t["key"])
    with pytest.raises(LookupError):
        vt.get(t["key"])
    with pytest.raises(ValueError, match="Built-in"):
        vt.update("b:impact", {"name": "x"})
    with pytest.raises(ValueError, match="Built-in"):
        vt.delete("b:impact")
    for key in ("", "x", "b:nope", "u:999", "u:abc"):
        with pytest.raises(LookupError):
            vt.get(key)


def test_listing_has_a_preview_picture_for_each_look():
    out = vt.listing()
    assert all(t["preview"].startswith("cache/templates/") for t in out)
    sizes = {Image.open(config.DATA / t["preview"]).size for t in out}
    assert sizes == {(vt.PREVIEW_W, round(vt.PREVIEW_W * 1920 / 1080))}
    assert len({t["preview"] for t in out}) == len(out)  # each look has its own picture
    assert vt.preview(out[0]["look"]) == out[0]["preview"]  # cached by look
    assert not list((config.CACHE / "templates").glob("_*"))  # scratch folders cleaned up


def test_apply_copies_the_template_onto_the_project():
    tpl = vt.create({"name": "Mine", "look": {"caption": {"font": "anton"}}, "voice_id": "voice-9", "src_volume": 0.4,
                     "duration": 70})
    pid = _new_project()
    vt.apply(pid, tpl["key"])
    meta = db.get_project(pid)["meta"]
    assert meta["look"]["caption"]["font"] == "anton" and meta["template"] == {"key": tpl["key"], "name": "Mine"}
    assert (meta["voice_id"], meta["src_volume"]) == ("voice-9", 0.4) and "duration" not in meta
    vt.update(tpl["key"], {"name": "Mine", "look": {"caption": {"font": "bebas"}}, "duration": 70})
    assert vt.look_for(db.get_project(pid))["caption"]["font"] == "anton"  # the project keeps what it was made with
    assert vt.view(db.get_project(pid))["template"]["name"] == "Mine"
    news = _new_project()
    vt.apply(news, tpl["key"], news=True)
    assert db.get_project(news)["meta"]["duration"] == 70
    vt.clear(pid)
    assert vt.look_for(db.get_project(pid)) is None and vt.view(db.get_project(pid)) == \
        {"template": None, "classic": True}


def test_attach_picks_the_choice_then_the_channels_default():
    ch = channels.create({"name": "Chine", "template": "b:impact"})
    assert ch["template"] == "b:impact"
    p1, p2, p3, p4 = (_new_project() for _ in range(4))
    channels.attach(p1, ch)  # no choice: the channel's template
    channels.attach(p2, ch, template="b:neon")  # the video's own choice wins
    channels.attach(p3, ch, template=vt.NONE)  # explicitly none
    channels.attach(p4, None, template="b:gone")  # a template that does not exist: classic look, no error
    meta = [db.get_project(p)["meta"] for p in (p1, p2, p3, p4)]
    assert meta[0]["template"]["key"] == "b:impact" and meta[0]["channel"] == ch["id"]
    assert meta[1]["template"]["key"] == "b:neon"
    assert "look" not in meta[2] and meta[2]["channel"] == ch["id"] and "look" not in meta[3]
    assert channels.full({"id": 1, "name": "old"})["template"] == ""  # a profile saved before templates


def test_from_project_keeps_the_look_voice_and_sound():
    pid = _new_project({"look": looks.clean({"caption": {"font": "bangers"}}), "voice_id": "v2", "src_volume": 0.25,
                        "duration": 80})
    t = vt.from_project(pid, "Saved")
    assert t["look"]["caption"]["font"] == "bangers" and (t["voice_id"], t["src_volume"], t["duration"]) == \
        ("v2", 0.25, 80)
    plain = vt.from_project(_new_project(), "Plain")
    assert looks.is_default(plain["look"]) and plain["voice_id"] == "" and plain["src_volume"] is None
    with pytest.raises(LookupError):
        vt.from_project(99999, "x")
