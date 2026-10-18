"""Effects the user turns on by hand for a project's source videos: mirror (flip left-right) and a colour filter
(`render.COLOR_FILTERS`).

Every source may use them (owner, 2026-10-18: no source-rights declaration any more), and an AI video's pictures and
clips are made for it. Nothing here runs by itself, per channel or in batch, and it is not a way to slip someone else's
video past duplicate / Content ID detection.

Stored in `meta.effects`: {url: {"mirror": bool, "color": name | None}} per source link (like
`meta.masks`), or {"ai": {...}} for an AI video, where one setting covers every scene. `attach` hands them to the
renderer as `source["effects"]`; they work on the source picture only (never the title, badge or French captions)."""

from pathlib import Path

from . import creator, db, render
from .i18n import tr

AI_KEY = "ai"
COLORS = tuple(render.COLOR_FILTERS)
NONE = {"mirror": False, "color": None}


def clean(raw) -> dict:
    """One source's effects from the app, checked. ValueError when wrong."""
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError(tr("Effects must be an object"))
    color = raw.get("color") or None
    if color is not None and color not in COLORS:
        raise ValueError(tr("Unknown colour filter: {color}", color=color))
    return {"mirror": bool(raw.get("mirror")), "color": color}


def _keys(proj: dict) -> list[str]:
    """Where each setting is kept: one per source link, or one for a whole AI video."""
    if creator.is_ai(proj):
        return [AI_KEY]
    return [s["url"] for s in (proj.get("meta") or {}).get("sources") or []]


def attach(proj: dict, sources: list[dict]) -> list[dict]:
    """The sources with `effects` for render.render_piece (None when off)."""
    saved = (proj.get("meta") or {}).get("effects") or {}
    ai = creator.is_ai(proj)
    return [{**s, "effects": saved.get(AI_KEY if ai else s.get("url")) or None} for s in sources]


def _summary(fx: dict) -> str:
    parts = [tr("mirrored")] if fx["mirror"] else []
    if fx["color"]:
        parts.append(tr("colour filter {name}", name=fx["color"]))
    return ", ".join(parts) or tr("no effect")


def update(pid: int, items: list) -> bool:
    """Set the effects of every source of a project (one entry per source, in `meta.sources` order; one entry for an
    AI video). True when something changed. LookupError / ValueError when the project or the effects are wrong."""
    p = db.get_project(pid)
    if not p:
        raise LookupError(tr("Project not found"))
    keys = _keys(p)
    if not keys:
        raise ValueError(tr("This video has no source footage yet"))
    if not isinstance(items, list) or len(items) != len(keys):
        raise ValueError(tr("Send one set of effects per source video"))
    cleaned = [clean(x) for x in items]
    old = (p.get("meta") or {}).get("effects") or {}
    new, logs = {}, []
    for i, (k, c) in enumerate(zip(keys, cleaned, strict=True)):
        if c != NONE:
            new[k] = c
        if c != (old.get(k) or NONE):
            logs.append(_summary(c) if k == AI_KEY else tr("Source {n}: {what}", n=i + 1, what=_summary(c)))
    if not logs and new == old:
        return False
    db.update_project(pid, log=tr("Effects changed") + ": " + " · ".join(logs or [tr("no effect")]),
                      meta={"effects": new})
    return True


def view(proj: dict) -> dict | None:
    """For the project page: the colour filters and each source's video (a /media path, None for an AI video or a
    missing file) with its effects. None while the project has no source yet."""
    keys = _keys(proj)
    if not keys:
        return None
    meta = proj.get("meta") or {}
    saved = meta.get("effects") or {}
    ai = creator.is_ai(proj)
    paths = [None] if ai else [s.get("path") for s in meta.get("sources") or []]
    return {"whole_video": ai, "colors": list(COLORS),
            "sources": [{"media": creator.media(Path(path)) if path else None, **clean(saved.get(k))}
                        for k, path in zip(keys, paths, strict=True)]}
