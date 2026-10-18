"""What the user draws on a project's source videos to hide burned-in text or a watermark that stays in one place:

- boxes, blurred; a box can also carry one of the owner's logos (`motio/logos.py`), drawn over the blur, fitted inside;
- a keep area: only that part of the source is used, scaled up, so text or a watermark outside it leaves the frame.

Nothing here finds or applies a box on its own: they come only from the project page. They are stored per source link
in `meta.masks` ({url: {"boxes": [{"box": [x, y, w, h], "logo": id | None}], "keep": [x, y, w, h] | None}}, fractions
of the source frame), so they survive a new download or a logo clean of that source. `attach` hands them to the
renderer, which works on the source picture only (never the title, badge or French captions; `render.render_piece`)."""

import json
import subprocess
from pathlib import Path

from PIL import Image

from . import config, creator, db, logos
from .i18n import tr, tr_n

MAX_BOXES = 6  # per source video
MIN_SIDE = 0.02  # smallest box width / height, as a fraction of the frame
MIN_KEEP = 0.25  # smallest keep area width / height: at most a 4× zoom


def clean_box(box, min_side: float = MIN_SIDE) -> list[float] | None:
    """One box from the app: [x, y, w, h] as fractions of the frame, None / [] = none. ValueError when wrong."""
    if not box:
        return None
    try:
        x, y, w, h = (float(v) for v in box)
    except (TypeError, ValueError):
        raise ValueError(tr("The blur box needs x, y, width and height")) from None
    x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    w, h = min(w, 1.0 - x), min(h, 1.0 - y)
    if w < min_side or h < min_side:
        raise ValueError(tr("The blur box is too small"))
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def _clean_item(item) -> dict | None:
    """A box as [x, y, w, h] (blur only) or {"box": [...], "logo": id}."""
    if isinstance(item, dict):
        box, lid = clean_box(item.get("box")), item.get("logo") or None
    else:
        box, lid = clean_box(item), None
    if not box:
        return None
    if lid is not None and not logos.path(str(lid)):
        raise ValueError(tr("Logo not found"))
    return {"box": box, "logo": lid}


def clean(raw) -> dict:
    """The boxes and keep area of one source video, checked. ValueError when wrong or too many."""
    raw = raw or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("boxes") or [], list):
        raise ValueError(tr("Blur boxes must be a list"))
    boxes = [b for b in (_clean_item(b) for b in raw.get("boxes") or []) if b]
    if len(boxes) > MAX_BOXES:
        raise ValueError(tr("At most {n} blur boxes per video", n=MAX_BOXES))
    try:
        keep = clean_box(raw.get("keep"), MIN_KEEP)
    except ValueError:
        raise ValueError(tr("The area to keep must cover at least {pct} % of the width and height",
                            pct=round(MIN_KEEP * 100))) from None
    return {"boxes": boxes, "keep": None if keep == [0.0, 0.0, 1.0, 1.0] else keep}


def _size(path: str) -> tuple[int, int] | None:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "json", str(path)], capture_output=True, text=True, timeout=120)
    try:
        s = json.loads(r.stdout)["streams"][0]
        return int(s["width"]), int(s["height"])
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def cover_png(boxes: list[dict], size: tuple[int, int], out: Path) -> Path | None:
    """A transparent picture the size of the source with each box's logo fitted inside it, centred; None when no box
    has a logo that still exists."""
    w, h = size
    pic = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    placed = False
    for b in boxes:
        src = logos.path(b.get("logo"))
        if not src:
            continue
        x, y, bw, bh = (round(b["box"][0] * w), round(b["box"][1] * h), round(b["box"][2] * w), round(b["box"][3] * h))
        with Image.open(src) as im:
            logo = im.convert("RGBA")
        k = min(bw / logo.width, bh / logo.height)
        logo = logo.resize((max(1, round(logo.width * k)), max(1, round(logo.height * k))), Image.Resampling.LANCZOS)
        pic.alpha_composite(logo, (x + (bw - logo.width) // 2, y + (bh - logo.height) // 2))
        placed = True
    if not placed:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    pic.save(out)
    return out


def attach(proj: dict, sources: list[dict], work: Path) -> list[dict]:
    """The sources with what render.render_piece needs: `blur` (the boxes, or None), `cover` (a PNG of the logos at the
    source's size, made in `work`, or None) and `keep` (the area to keep, or None)."""
    masks = (proj.get("meta") or {}).get("masks") or {}
    out = []
    for i, s in enumerate(sources):
        m = masks.get(s.get("url")) or {}
        boxes = m.get("boxes") or []
        cover = None
        if any(logos.path(b.get("logo")) for b in boxes) and (size := _size(s["path"])):
            cover = cover_png(boxes, size, work / f"cover-{i}.png")
        out.append({**s, "blur": [b["box"] for b in boxes] or None, "cover": str(cover) if cover else None,
                    "keep": m.get("keep")})
    return out


def _summary(m: dict) -> str:
    boxes = m["boxes"]
    if not boxes and not m["keep"]:
        return tr("nothing hidden")
    parts = [tr_n(len(boxes), "blur box", "blur boxes")] if boxes else []
    if n := sum(1 for b in boxes if b["logo"]):
        parts.append(tr_n(n, "logo"))
    if m["keep"]:
        parts.append(tr("zoomed in"))
    return ", ".join(parts)


def update(pid: int, per_source: list) -> bool:
    """Set the boxes and keep area of every source of a project (one entry per source, in `meta.sources` order). True
    when something changed. LookupError / ValueError when the project or the boxes are wrong."""
    p = db.get_project(pid)
    if not p:
        raise LookupError(tr("Project not found"))
    meta = p.get("meta") or {}
    sources = meta.get("sources") or []
    if not sources or creator.is_ai(p):
        raise ValueError(tr("This video has no source footage to blur"))
    if not isinstance(per_source, list) or len(per_source) != len(sources):
        raise ValueError(tr("Send one list of blur boxes per source video"))
    old = meta.get("masks") or {}
    masks, logs = {}, []
    for i, (s, raw) in enumerate(zip(sources, per_source, strict=True)):
        m = clean(raw)
        if m["boxes"] or m["keep"]:
            masks[s["url"]] = m
        if m != (old.get(s["url"]) or {"boxes": [], "keep": None}):
            logs.append(tr("Source {n}: {what}", n=i + 1, what=_summary(m)))
    if not logs:
        return False
    db.update_project(pid, log=tr("Blur boxes changed") + ": " + " · ".join(logs), meta={"masks": masks})
    return True


def _media(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    try:
        return Path(path).resolve().relative_to(config.DATA.resolve()).as_posix()
    except ValueError:
        return None


def view(proj: dict) -> list[dict] | None:
    """For the project page: each source's video (a /media path, None when the file is gone), length, boxes and keep
    area."""
    meta = proj.get("meta") or {}
    if creator.is_ai(proj) or not meta.get("sources"):
        return None
    masks = meta.get("masks") or {}
    return [{"media": _media(s.get("path")), "duration": s.get("duration"),
             "boxes": (masks.get(s["url"]) or {}).get("boxes") or [], "keep": (masks.get(s["url"]) or {}).get("keep")}
            for s in meta["sources"]]
