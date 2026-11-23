"""Look: how a video is dressed, apart from what it says (owner, 2026-11-23: video templates).

A look is plain data kept on the project (`meta.look`) and read by `render.py`: the caption style (font, size, colours,
outline, box, the word being spoken, where the captions sit), the title band, the frame behind the source picture and
the camera move of an AI video's pictures. `DEFAULT` is exactly what Motio drew before templates existed, so a project
with no look renders as it always did. Templates (`templates.py`) are named looks plus a few defaults.
"""
import re
from pathlib import Path

from . import config

ASSETS = Path(__file__).parent / "assets"
FONT_DIR = ASSETS / "fonts"

# font key -> (label, file in assets/fonts). "system" is the operating system's bold sans (config.font_candidates).
# All bundled fonts are SIL Open Font License 1.1 (the licence text sits next to each file); see docs/TEMPLATES.md.
FONTS = {
    "system": ("System bold", None),
    "poppins": ("Poppins ExtraBold", "Poppins-ExtraBold.ttf"),
    "poppins_bold": ("Poppins Bold", "Poppins-Bold.ttf"),
    "anton": ("Anton", "Anton-Regular.ttf"),
    "bebas": ("Bebas Neue", "BebasNeue-Regular.ttf"),
    "archivo": ("Archivo Black", "ArchivoBlack-Regular.ttf"),
    "bangers": ("Bangers", "Bangers-Regular.ttf"),
    "lilita": ("Lilita One", "LilitaOne-Regular.ttf"),
    "dmserif": ("DM Serif Display", "DMSerifDisplay-Regular.ttf"),
}
BOXES = ("none", "line", "word")  # a box behind each caption line, or behind each word
POSITIONS = ("below", "lower", "middle")  # under the source picture (as before), lower third, centre of the frame
TITLE_POSITIONS = ("top", "lower")  # the title band at the top (as before) or in the lower part of the frame
MOTION_MODES = ("auto", "zoom_in", "zoom_out", "alternate", "pan", "still")
SIZE_MIN, SIZE_MAX = 36, 100  # caption size at 9:16 (the 16:9 copy scales with it)
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAULT = {
    "caption": {"font": "system", "size": 60, "color": "#FFFFFF", "spoken": "#FFD60A", "active": "",
                "stroke": "#000000", "stroke_w": 6, "box": "none", "box_color": "#000000", "box_alpha": 0.6,
                "active_box": "",
                "upper": False, "pop": 0.0, "glow": "", "pos": "below"},
    "title": {"show": True, "font": "system", "color": "#FFFFFF", "bar": "#0C1016", "bar_alpha": 0.804,
              "badge": "#DE2D26", "pos": "top", "align": "left", "upper": False, "accent": ""},
    "frame": {"blur": 36, "dim": 0.10, "color": ""},
    "motion": {"mode": "auto", "zoom": 0.12},
}


def _color(v, default: str, empty_ok: bool = False) -> str:
    s = str(v if v is not None else default).strip()
    if empty_ok and not s:
        return ""
    return s.upper() if _HEX.match(s) else default


def _num(v, default: float, lo: float, hi: float) -> float:
    try:
        return round(min(float(hi), max(float(lo), float(v))), 3)
    except (TypeError, ValueError):
        return default


def _pick(v, allowed, default):
    return v if v in allowed else default


def clean(raw) -> dict:
    """A complete, valid look from whatever was sent (missing or wrong values fall back to the default)."""
    raw = raw if isinstance(raw, dict) else {}
    d = DEFAULT
    c, t, f, m = (raw.get(k) if isinstance(raw.get(k), dict) else {} for k in ("caption", "title", "frame", "motion"))
    dc, dt, df, dm = d["caption"], d["title"], d["frame"], d["motion"]
    return {
        "caption": {
            "font": _pick(c.get("font"), FONTS, dc["font"]),
            "size": int(_num(c.get("size"), dc["size"], SIZE_MIN, SIZE_MAX)),
            "color": _color(c.get("color"), dc["color"]),
            "spoken": _color(c.get("spoken"), dc["spoken"]),
            "active": _color(c.get("active"), dc["active"], empty_ok=True),
            "stroke": _color(c.get("stroke"), dc["stroke"]),
            "stroke_w": int(_num(c.get("stroke_w"), dc["stroke_w"], 0, 12)),
            "box": _pick(c.get("box"), BOXES, dc["box"]),
            "box_color": _color(c.get("box_color"), dc["box_color"]),
            "box_alpha": _num(c.get("box_alpha"), dc["box_alpha"], 0, 1),
            "active_box": _color(c.get("active_box"), dc["active_box"], empty_ok=True),
            "upper": bool(c.get("upper", dc["upper"])),
            "pop": _num(c.get("pop"), dc["pop"], 0, 0.4),
            "glow": _color(c.get("glow"), dc["glow"], empty_ok=True),
            "pos": _pick(c.get("pos"), POSITIONS, dc["pos"]),
        },
        "title": {
            "show": bool(t.get("show", dt["show"])),
            "font": _pick(t.get("font"), FONTS, dt["font"]),
            "color": _color(t.get("color"), dt["color"]),
            "bar": _color(t.get("bar"), dt["bar"]),
            "bar_alpha": _num(t.get("bar_alpha"), dt["bar_alpha"], 0, 1),
            "badge": _color(t.get("badge"), dt["badge"]),
            "pos": _pick(t.get("pos"), TITLE_POSITIONS, dt["pos"]),
            "align": _pick(t.get("align"), ("left", "center"), dt["align"]),
            "upper": bool(t.get("upper", dt["upper"])),
            "accent": _color(t.get("accent"), dt["accent"], empty_ok=True),
        },
        "frame": {
            "blur": int(_num(f.get("blur"), df["blur"], 0, 80)),
            "dim": _num(f.get("dim"), df["dim"], 0, 0.8),
            "color": _color(f.get("color"), df["color"], empty_ok=True),
        },
        "motion": {
            "mode": _pick(m.get("mode"), MOTION_MODES, dm["mode"]),
            "zoom": _num(m.get("zoom"), dm["zoom"], 0, 0.4),
        },
    }


def rgb(hex_color: str, alpha: float | None = None) -> tuple:
    h = hex_color.lstrip("#")
    c = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return c if alpha is None else (*c, round(255 * alpha))


def font_candidates(key: str, cjk: bool = False) -> list[str]:
    """Font files to try, best first. A caption with Chinese / Japanese / Korean always uses the CJK font."""
    if cjk:
        return config.font_candidates("cjk")
    file = FONTS.get(key, FONTS["system"])[1]
    own = [str(FONT_DIR / file)] if file and (FONT_DIR / file).exists() else []
    return own + config.font_candidates("bold")


def is_default(look: dict | None) -> bool:
    return not look or clean(look) == DEFAULT
