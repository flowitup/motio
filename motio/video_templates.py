"""Video templates (owner, 2026-11-23): a named look plus a few defaults, kept to dress the next video the same way.

A template holds a look (`looks.py`: caption style, title band, frame, camera move of AI pictures) and optional
production defaults: the voice, the length and the level of the source's own sound. Two kinds:
- built-in templates, in `BUILTIN` below, built from public ideas (each one says where the idea came from; nothing is
  copied from them, only the general look: colours, placement, which word lights up; the fonts are SIL OFL fonts that
  ship in `assets/fonts`, see docs/TEMPLATES.md);
- the owner's own, in the `template` table: saved from a project ("Save as template"), written by hand, or imported
  from the JSON another Motio exported.
A key names one: "b:<slug>" (built-in) or "u:<id>" (the owner's). Picking one on a new video, or giving a channel a
default one, copies it onto the project (`meta.look`, `meta.template`, `meta.voice_id`, `meta.src_volume`): the video
keeps the look it was made with when the template is edited later, and a render reads only the project.
The channel profile keeps what is about the channel (script style, hashtags, gates, Postiz); the template keeps how the
video looks, so the two do not repeat each other: a channel only points to its default template.
"""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import captions, config, db, looks, render, topic
from .i18n import tr

MAX_NAME, MAX_NOTE = 60, 200
VERSION = 1  # of the exported JSON and of the preview pictures (a new look field bumps it: previews are made again)
NONE = "none"  # as a template choice on a new video: no template at all (not even the channel's default)
DEFAULT_KEY = "b:classic"


def _look(**parts) -> dict:
    """A built-in's look: only what differs from the default is written, the rest is filled in by looks.clean."""
    return looks.clean(parts)


def _builtin() -> list[dict]:
    """The starter set. `credit`: where the idea comes from (never code or assets, those are only ideas)."""
    return [
        {"slug": "classic", "name": "Classic news", "credit": "",
         "note": tr("Motio's own look: white captions under the picture, the spoken word in yellow."),
         "look": _look()},
        {"slug": "impact", "name": "Bold impact", "credit": "Public caption guides (Hormozi-style captions)",
         "note": tr("Big capitals in the middle of the frame, the spoken word pops in yellow."),
         "look": _look(caption={"font": "anton", "size": 84, "upper": True, "spoken": "#FFE600", "stroke_w": 9,
                                "pop": 0.12, "pos": "middle"}, title={"show": False})},
        {"slug": "pill", "name": "Orange pill", "credit": "pycaps (MIT) word-focus, Captioneer (MIT) pill: ideas only",
         "note": tr("The spoken word sits in an orange pill, capitals, middle of the frame."),
         "look": _look(caption={"font": "poppins", "size": 64, "upper": True, "spoken": "#FFFFFF", "stroke_w": 5,
                                "active_box": "#F76F00", "pos": "middle"}, title={"show": False})},
        {"slug": "clean_box", "name": "Clean box", "credit": "pycaps (MIT) minimalist: idea only",
         "note": tr("Calm captions on a dark box in the lower third, the spoken word brighter."),
         "look": _look(caption={"font": "poppins_bold", "size": 52, "color": "#CFCFCF", "spoken": "#FFFFFF",
                                "stroke_w": 0, "box": "line", "box_alpha": 0.62, "pos": "lower"},
                       title={"bar_alpha": 0.6}, frame={"dim": 0.2})},
        {"slug": "comic", "name": "Comic hype", "credit": "pycaps (MIT) hype: idea only",
         "note": tr("Comic lettering with a thick outline, the spoken word pops in bright yellow."),
         "look": _look(caption={"font": "bangers", "size": 76, "spoken": "#FFFF00", "stroke_w": 9, "pop": 0.1,
                                "pos": "lower"}, title={"font": "bangers", "badge": "#E8590C"})},
        {"slug": "cinema", "name": "Cinematic gold", "credit": "Captioneer (MIT) cinematic-gold: idea only",
         "note": tr("Serif captions in warm gold, a soft dark frame and a slow push-in on AI pictures."),
         "look": _look(caption={"font": "dmserif", "size": 66, "color": "#F5F1E6", "spoken": "#E8B84B",
                                "stroke_w": 4, "pos": "lower"},
                       title={"font": "dmserif", "bar": "#000000", "bar_alpha": 0.5, "badge": "#B8860B"},
                       frame={"blur": 50, "dim": 0.25}, motion={"mode": "zoom_in", "zoom": 0.1})},
        {"slug": "neon", "name": "Neon glow", "credit": "Captioneer (MIT) glow / cinematic-neon: idea only",
         "note": tr("A cyan glow on the words already spoken, a night-blue title band, alternating camera moves."),
         "look": _look(caption={"font": "archivo", "size": 62, "color": "#E6F7FF", "spoken": "#00F0FF",
                                "stroke": "#001018", "stroke_w": 4, "glow": "#00C8FF", "pos": "middle"},
                       title={"bar": "#0A0F24", "bar_alpha": 0.85, "badge": "#FF2BD6"}, frame={"dim": 0.25},
                       motion={"mode": "alternate", "zoom": 0.14})},
        {"slug": "desk", "name": "News desk", "credit": "Captioneer (MIT) news-ticker: idea only",
         "note": tr("White captions on a blue bar like a TV news desk, yellow for the spoken word."),
         "look": _look(caption={"font": "poppins_bold", "size": 50, "spoken": "#FFD60A", "stroke_w": 0,
                                "box": "line", "box_color": "#0B2A6F", "box_alpha": 0.92, "pos": "lower"},
                       title={"bar": "#0B2A6F", "bar_alpha": 0.92, "badge": "#E10600"})},
        {"slug": "highlighter", "name": "Highlighter", "credit": "Captioneer (MIT) highlighter: idea only",
         "note": tr("A yellow highlighter behind the spoken word, which turns black."),
         "look": _look(caption={"font": "poppins", "size": 56, "spoken": "#FFFFFF", "active": "#111111",
                                "stroke_w": 6, "active_box": "#FFE14D", "pos": "lower"})},
        {"slug": "gaming", "name": "Gaming pop", "credit": "Public caption guides (gaming / reaction clips)",
         "note": tr("Round lettering with a purple outline, lime green for the spoken word, lively camera moves."),
         "look": _look(caption={"font": "lilita", "size": 70, "spoken": "#7CFF3A", "stroke": "#1B0033",
                                "stroke_w": 9, "pop": 0.15, "pos": "lower"},
                       title={"font": "lilita", "bar": "#1B0033", "bar_alpha": 0.85, "badge": "#7C3AED"},
                       frame={"blur": 24, "dim": 0.05}, motion={"mode": "alternate", "zoom": 0.15})},
        {"slug": "tall", "name": "Tall caps", "credit": "Public caption guides (condensed capitals)",
         "note": tr("Tall condensed capitals in the middle, white with the spoken word in red."),
         "look": _look(caption={"font": "bebas", "size": 92, "upper": True, "spoken": "#FF3B30", "stroke_w": 7,
                                "pos": "middle"}, title={"font": "bebas", "bar_alpha": 0.6})},
        {"slug": "series_card", "name": "Series card", "credit": "Layout of a public Vietnamese TikTok series "
                                                                  "(@tuantudo86): idea only",
         "note": tr("A dark green title card in the lower part, capitals with key words in yellow "
                    "(write them between *stars*), the same on every episode."),
         "look": _look(caption={"font": "poppins_bold", "size": 52, "spoken": "#FFFFFF", "stroke_w": 7,
                                "pos": "middle"},
                       title={"font": "dmserif", "bar": "#1F3B2A", "bar_alpha": 0.94, "pos": "lower",
                              "align": "center", "upper": True, "accent": "#FFD60A"}, frame={"dim": 0.0})},
        {"slug": "documentary", "name": "Documentary", "credit": "Captioneer (MIT) documentary: idea only",
         "note": tr("Quiet captions, a flat dark frame instead of the blurred picture, a slow sideways drift."),
         "look": _look(caption={"font": "poppins_bold", "size": 48, "color": "#E8E8E8", "spoken": "#FFFFFF",
                                "active": "#FFD60A", "stroke_w": 4},
                       title={"bar": "#000000", "bar_alpha": 0.55}, frame={"color": "#0F1115"},
                       motion={"mode": "pan", "zoom": 0.08})},
    ]


def builtin() -> list[dict]:
    return [{"key": f"b:{b['slug']}", "name": b["name"], "note": b["note"], "credit": b["credit"], "builtin": True,
             "look": b["look"], "voice_id": "", "duration": None, "src_volume": None} for b in _builtin()]


def clean(data: dict) -> dict:
    """Validate a template from the app or an import. Raises ValueError (in the UI language) when invalid."""
    name = " ".join(str(data.get("name") or "").split())[:MAX_NAME]
    if not name:
        raise ValueError(tr("The template needs a name"))
    duration = data.get("duration")
    if duration in (None, "", 0):
        duration = None
    else:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = -1
        if duration not in topic.DURATIONS:
            raise ValueError(tr("Duration must be one of {choices} seconds",
                                choices=", ".join(map(str, topic.DURATIONS))))
    vol = data.get("src_volume")
    try:
        vol = None if vol in (None, "") else round(min(1.0, max(0.0, float(vol))), 2)
    except (TypeError, ValueError):
        vol = None
    return {"name": name, "note": str(data.get("note") or "").strip()[:MAX_NOTE],
            "look": looks.clean(data.get("look")), "voice_id": str(data.get("voice_id") or "").strip(),
            "duration": duration, "src_volume": vol}


def _user(row: dict) -> dict:
    return {**clean(row), "key": f"u:{row['id']}", "credit": "", "builtin": False,
            "created_at": row.get("created_at")}


def listing() -> list[dict]:
    """Every template, with the path of its preview picture (under /media)."""
    out = [*builtin(), *(_user(r) for r in db.list_templates())]
    for t in out:
        t["preview"] = preview(t["look"])
    return out


def get(key: str) -> dict:
    """A template by key. LookupError (in the UI language) when there is none."""
    kind, _, ident = str(key or "").partition(":")
    if kind == "b":
        for b in builtin():
            if b["key"] == key:
                return b
    elif kind == "u" and ident.isdigit():
        row = db.get_template(int(ident))
        if row:
            return _user(row)
    raise LookupError(tr("Template not found"))


def create(data: dict) -> dict:
    return get(f"u:{db.save_template(None, clean(data))}")


def update(key: str, data: dict) -> dict:
    t = get(key)
    if t["builtin"]:
        raise ValueError(tr("Built-in templates cannot be changed: duplicate it first"))
    db.save_template(int(key[2:]), clean(data))
    return get(key)


def delete(key: str) -> None:
    t = get(key)
    if t["builtin"]:
        raise ValueError(tr("Built-in templates cannot be deleted"))
    db.delete_template(int(key[2:]))


def export(key: str) -> dict:
    """The template as JSON to share or keep (import takes it back)."""
    t = get(key)
    return {"motio_template": VERSION, "name": t["name"], "note": t["note"], "look": t["look"],
            "voice_id": t["voice_id"], "duration": t["duration"], "src_volume": t["src_volume"]}


def import_json(raw) -> dict:
    """Make a template of the owner's from exported JSON (text or already parsed). ValueError when it is not one."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("look"), dict):
        raise ValueError(tr("This is not a Motio template (JSON with a name and a look)"))
    return create(data)


def from_project(pid: int, name: str) -> dict:
    """Save the way a project looks as a template: its look, its voice and the level of its source's sound."""
    p = db.get_project(pid)
    if not p:
        raise LookupError(tr("Project not found"))
    meta = p.get("meta") or {}
    return create({"name": name, "look": meta.get("look"), "voice_id": meta.get("voice_id") or "",
                   "duration": meta.get("duration") if meta.get("duration") in topic.DURATIONS else None,
                   "src_volume": meta.get("src_volume")})


# ---------- on a project ----------
def apply(pid: int, key: str, news: bool = False) -> dict:
    """Put a template on a project: its look is copied (the project keeps it when the template changes). The template's
    voice and source-sound level are used when it sets them; a news video also takes its length."""
    t = get(key)
    meta = {"look": t["look"], "template": {"key": t["key"], "name": t["name"]}}
    if t["voice_id"]:
        meta["voice_id"] = t["voice_id"]
    if t["src_volume"] is not None:
        meta["src_volume"] = t["src_volume"]
    if news and t["duration"]:
        meta["duration"] = t["duration"]
    db.update_project(pid, log=tr("Template: {name}", name=t["name"]), meta=meta)
    return t


def clear(pid: int) -> None:
    """Back to Motio's own look (the voice and sound level a template set stay as they are)."""
    db.update_project(pid, log=tr("Template removed: back to the classic look"), meta={"look": None, "template": None})


def attach(pid: int, choice: str | None, channel: dict | None, news: bool = False) -> None:
    """On a project just made: the template picked for it, else the channel's default one. `choice` NONE = no template.
    A template that no longer exists is ignored (the video is made with the classic look)."""
    key = channel.get("template", "") if (choice is None and channel) else (choice or "")
    if not key or key == NONE:
        return
    try:
        apply(pid, key, news)
    except LookupError:
        pass


def look_for(proj: dict) -> dict | None:
    """The look a render uses, None = Motio's own."""
    look = (proj.get("meta") or {}).get("look")
    return None if looks.is_default(look) else looks.clean(look)


def view(proj: dict) -> dict:
    """For the project page: the template in use (None = none was picked) and whether the look is the classic one."""
    meta = proj.get("meta") or {}
    return {"template": meta.get("template"), "classic": looks.is_default(meta.get("look"))}


# ---------- preview picture ----------
SAMPLE_TITLE = "Le *vélo électrique* conquiert Shanghai"
SAMPLE_LINES = [["Le", "vélo", "électrique"], ["conquiert", "Shanghai"]]
SAMPLE_LIT = 3  # words already spoken: the third one is the one being spoken
PREVIEW_W = 360  # the stored picture is the 9:16 frame at this width


def preview(look: dict) -> str:
    """The look drawn with the real renderer on a sample frame, cached; the path under /media (cache/templates/…)."""
    look = looks.clean(look)
    h = hashlib.sha1(json.dumps([VERSION, look], sort_keys=True).encode()).hexdigest()[:16]
    out = config.CACHE / "templates" / f"{h}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        _draw(look, out)
        _trim(out.parent)
    return f"cache/templates/{out.name}"


def _trim(folder: Path, keep: int = 150) -> None:
    """The editor draws a picture per change: keep the newest ones only (a built-in's is made again when missing)."""
    old = sorted(folder.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)[keep:]
    for f in old:
        f.unlink(missing_ok=True)


def _gradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    strip = Image.new("RGB", (1, h))
    for y in range(h):
        k = y / max(h - 1, 1)
        strip.putpixel((0, y), tuple(round(a + (b - a) * k) for a, b in zip(top, bottom, strict=True)))
    return strip.resize((w, h))


def _scene(w: int, h: int) -> Image.Image:
    """A made-up picture (sky, sun, hills) standing for the source video: no real footage or person."""
    img = _gradient(w, h, (92, 140, 196), (244, 190, 150))
    d = ImageDraw.Draw(img)
    d.ellipse((w * 0.62, h * 0.18, w * 0.62 + h * 0.3, h * 0.18 + h * 0.3), fill=(255, 226, 150))
    d.polygon([(0, h), (0, h * 0.7), (w * 0.3, h * 0.5), (w * 0.55, h * 0.72), (w * 0.8, h * 0.55), (w, h * 0.68),
               (w, h)], fill=(44, 74, 96))
    d.polygon([(0, h), (0, h * 0.86), (w * 0.4, h * 0.74), (w * 0.75, h * 0.88), (w, h * 0.8), (w, h)],
              fill=(24, 44, 62))
    return img


def _draw(look: dict, out: Path) -> None:
    L = render.VERTICAL
    fr = look["frame"]
    scene = _scene(L.w, round(L.w * 9 / 16))
    if fr["color"]:
        base = Image.new("RGB", (L.w, L.h), render.looks.rgb(fr["color"]))
    else:
        base = _scene(L.w, L.h).filter(ImageFilter.GaussianBlur(fr["blur"] or 0.1))
        dim = Image.new("RGB", base.size, (0, 0, 0))
        base = Image.blend(base, dim, fr["dim"])
    frame = base.convert("RGBA")
    frame.paste(scene, (0, (L.h - scene.height) // 2))
    work = out.parent / f"_{out.stem}"
    work.mkdir(exist_ok=True)
    ov = render.overlay_png(work / "ov.png", title=SAMPLE_TITLE, badge="ACTU", layout=L, look=look)
    frame.alpha_composite(Image.open(ov))
    cue = captions.Cue(0, 3, [[captions.Word(t, i * .3, i * .3 + .3) for i, t in enumerate(row)]
                              for row in SAMPLE_LINES])
    cl = render.look_layout(L, look)
    cap = render.caption_png(work / "cap.png", cue, SAMPLE_LIT, cl, look)
    frame.alpha_composite(Image.open(cap), (0, cl.cap_top))
    h = round(PREVIEW_W * L.h / L.w)
    frame.convert("RGB").resize((PREVIEW_W, h), Image.LANCZOS).save(out)
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
