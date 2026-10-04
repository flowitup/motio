"""Picture review for AI videos ("Review the pictures first"): every scene is a shot with its own picture, and the video
stops after the pictures are made so each shot can be approved or redone before the voice and the render are paid for.

How it fits the pipeline (pipeline._voice_render_post): the script gate (if the channel has one) comes first, then the
pictures are made with the ones the provider cannot make noted instead of stopping the step, then the project waits in
`meta.review == "shots"`. The app shows the grid (GET /api/projects/{id}/shots), a shot is redone at once (only that
picture is made, only that one is paid for), and "continue" is the same voice → render run as the script gate.

A shot is approved by the *key of its current picture* (images.key: provider, size, seed, prompt), kept in
`meta.ai.shots.approved`. Anything that changes the picture (prompt, seed, the video's style, a cast look, the
provider) changes the key, so that shot is simply not approved any more and its new picture has to be looked at.
`meta.ai.shots.failed` maps the key of a picture the provider could not make to its message.

Same faces (creator.faces_on): the characters' reference portraits are shown above the shots; redoing one (a new seed or
a new look) makes only that portrait now, and every shot that shows the character then needs a new picture.
"""
import json
import threading

from . import config, creator, db, images
from .i18n import tr, tr_n

REVIEW = "shots"  # meta.review while the video waits for the pictures to be approved
MAX_LOOK = 300  # characters in a look edited on the review screen


class NotWaiting(RuntimeError):
    """The project is not waiting for the picture review (running, done, or at another gate)."""


_locks: dict[int, threading.Lock] = {}
_guard = threading.Lock()


def _lock(pid: int) -> threading.Lock:
    with _guard:
        return _locks.setdefault(pid, threading.Lock())


def enabled(proj: dict | None) -> bool:
    """True for an AI video made with "review the pictures first"."""
    return bool(creator.is_ai(proj) and (((proj or {}).get("meta") or {}).get("ai") or {}).get("review_shots"))


def _project(pid: int) -> dict:
    p = db.get_project(pid)
    if not p:
        raise LookupError(tr("Project #{id} not found", id=pid))
    if not creator.is_ai(p):
        raise ValueError(tr("Only AI videos have pictures to review"))
    return p


def _read(pid: int) -> dict:
    f = config.PROJECTS / str(pid) / "script.json"
    try:
        plan = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise FileNotFoundError(tr("Project has no script yet")) from e
    except json.JSONDecodeError as e:
        raise ValueError(tr("script.json is corrupt: {error}", error=e)) from e
    if not isinstance(plan, dict) or not isinstance(plan.get("lines"), list):
        raise ValueError(tr("script.json is corrupt: the lines list is missing"))
    plan["lines"] = [ln if isinstance(ln, dict) else {"text": str(ln)} for ln in plan["lines"]]
    return plan


def _write(pid: int, plan: dict) -> None:
    f = config.PROJECTS / str(pid) / "script.json"
    f.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


def _gate(pid: int) -> tuple[dict, dict]:
    """(project, script) when the project waits for the picture review; NotWaiting otherwise."""
    p = _project(pid)
    if p["status"] != "review" or p["meta"].get("review") != REVIEW:
        raise NotWaiting(tr("Project is not awaiting picture review"))
    return p, _read(pid)


def _ai(p: dict) -> dict:
    return (p.get("meta") or {}).get("ai") or {}


def _state(p: dict) -> tuple[set[str], dict[str, str]]:
    st = _ai(p).get("shots") or {}
    return set(st.get("approved") or []), dict(st.get("failed") or {})


def _save(pid: int, ai: dict, approved: set[str], failed: dict[str, str], keys: list[str]) -> None:
    """Keep only what still matches a picture of the script (an edited shot's old key is dropped)."""
    live = set(keys)
    ai = {**ai, "shots": {"approved": sorted(approved & live),
                          "failed": {k: v for k, v in failed.items() if k in live}}}
    db.update_project(pid, meta={"ai": ai})


def _file(pid: int, plan: dict, ln: dict, provider: str):
    return creator.picture_file(config.PROJECTS / str(pid), plan, ln, provider)


def rows(pid: int, p: dict, plan: dict) -> list[dict]:
    """One row per scene: its text, prompt, seed, picture (a /media path or None) and state: approved (this very
    picture was approved), ready (made, not approved yet), failed (the provider could not make it), missing."""
    provider = _ai(p).get("provider") or images.provider()
    approved, failed = _state(p)
    out = []
    for i, ln in enumerate(plan["lines"]):
        f = _file(pid, plan, ln, provider)
        pic = creator.media(f)
        state = ("approved" if f.stem in approved else "ready") if pic else "failed" if f.stem in failed else "missing"
        out.append({"index": i, "text": str(ln.get("text") or ""), "image": str(ln.get("image") or ""),
                    "seed": int(ln.get("seed") or 0), "picture": pic, "state": state,
                    "error": failed.get(f.stem) if state == "failed" else None,
                    "cast": creator.faces(plan, ln, provider)})
    return out


def face_rows(pid: int, plan: dict, items: list[dict], provider: str) -> list[dict]:
    """The characters' reference portraits (same faces only): name, look, seed, picture, how many shots show them."""
    if not creator.faces_on(plan, provider):
        return []
    out = config.PROJECTS / str(pid)
    return [{"index": i, "name": name, "look": look, "seed": creator.face_seed(plan, name),
             "picture": creator.media(creator.face_file(out, plan, name, provider)),
             "shots": sum(name in r["cast"] for r in items)}
            for i, (name, look) in enumerate(plan["cast"].items())]


def view(pid: int) -> dict:
    """What the picture review screen shows."""
    p = _project(pid)
    plan = _read(pid)
    items = rows(pid, p, plan)
    provider = _ai(p).get("provider") or images.provider()
    count = {s: sum(r["state"] == s for r in items) for s in ("approved", "ready", "failed", "missing")}
    return {"shots": items, "total": len(items), "approved": count["approved"], "failed": count["failed"],
            "missing": count["missing"], "ready": count["approved"] == len(items) and bool(items),
            "waiting": p["status"] == "review" and p["meta"].get("review") == REVIEW,
            "provider": provider, "price": images.cost(1, provider), "cost": _ai(p).get("cost") or 0,
            "ref_price": images.cost(1, provider, refs=True), "faces": face_rows(pid, plan, items, provider),
            "version": (config.PROJECTS / str(pid) / "script.json").stat().st_mtime}


def ready(pid: int, proj: dict, plan: dict) -> bool:
    """Every scene has a picture and it is approved (the pictures of the provider that is set now, as the run uses)."""
    approved, _ = _state(proj)
    provider = images.provider()
    files = [_file(pid, plan, ln, provider) for ln in plan["lines"]]
    return bool(files) and all(f.stem in approved and f.is_file() for f in files)


def make(pid: int, plan: dict, step, lo: int = creator.PICTURES_FROM, hi: int = creator.PICTURES_TO) -> int:
    """Make the pictures of every scene that has none (the others are kept). A scene the provider cannot make is
    noted as failed and the rest go on, so one bad prompt does not stop the whole video. Returns how many scenes
    still have no picture."""
    name = images.provider()
    images.check_ready(name)
    out = config.PROJECTS / str(pid)
    lines = plan["lines"]
    fresh, spent, failed = 0, 0.0, {}
    keys = []
    for i, ln in enumerate(lines):
        step("Pictures", lo + (hi - lo) * i // len(lines),
             tr("Picture {n} of {total} ({provider})", n=i + 1, total=len(lines), provider=name))
        keys.append(creator.picture_file(out, plan, ln, name).stem)
        try:
            _, new, usd = creator.make_picture(plan, ln, out, name)
            fresh += new
            spent += usd
        except images.ImageError as e:
            failed[keys[-1]] = str(e)[:300]
    cost = round(spent, 3)
    with _lock(pid):
        p = db.get_project(pid)
        approved, _ = _state(p)
        ai = {**_ai(p), "provider": name, "scenes": len(lines)}
        ai["cost"] = round(float(ai.get("cost") or 0) + cost, 3) if cost else ai.get("cost") or 0
        _save(pid, ai, approved, failed, keys)
    step("Pictures", hi, creator._made_log(fresh, len(lines), cost) +
         (" · " + tr("{n} could not be made", n=len(failed)) if failed else ""))
    return len(failed)


def summary(pid: int) -> str:
    """The log line when the video starts waiting: how many pictures to look at, and how many failed."""
    v = view(pid)
    text = tr("Pictures ready for your review: {n}", n=tr_n(v["total"] - v["failed"] - v["missing"], "picture"))
    return text + (" · " + tr("{n} could not be made: redo them", n=v["failed"] + v["missing"])
                   if v["failed"] + v["missing"] else "")


def redo(pid: int, index: int, prompt: str | None = None) -> dict:
    """Make this shot's picture again, now: a new seed (or the new `prompt`, if it differs), only this picture is
    made and paid for. A shot with no picture yet is tried again as it is. It goes back to "ready" for a new look."""
    with _lock(pid):
        p, plan = _gate(pid)
        lines = plan["lines"]
        if not 0 <= index < len(lines):
            raise ValueError(tr("Scene {n} does not exist", n=index + 1))
        name = _ai(p).get("provider") or images.provider()
        images.check_ready(name)
        ln = dict(lines[index])
        had = _file(pid, plan, ln, name).is_file()
        text = " ".join(str(prompt).split()) if prompt is not None else None
        if text and text != str(ln.get("image") or ""):
            if len(text) > creator.MAX_PROMPT:
                raise ValueError(tr("The picture prompt of line {line} is longer than {n} characters", line=index + 1,
                                    n=creator.MAX_PROMPT))
            ln["image"] = text
        elif had:
            ln["seed"] = int(ln.get("seed") or 0) + 1
        lines[index] = ln
        _write(pid, plan)
        keys = [_file(pid, plan, x, name).stem for x in lines]
        approved, failed = _state(p)
        usd = 0.0
        try:
            _, _, usd = creator.make_picture(plan, ln, config.PROJECTS / str(pid), name)
            failed.pop(keys[index], None)
        except images.ImageError as e:
            failed[keys[index]] = str(e)[:300]
        approved.discard(keys[index])
        ai = {**_ai(p)}
        if usd:
            ai["cost"] = round(float(ai.get("cost") or 0) + usd, 3)
        _save(pid, ai, approved, failed, keys)
        db.update_project(pid, log=tr("Picture redone for scene {n}", n=index + 1))
    return view(pid)


def redo_face(pid: int, index: int, look: str | None = None) -> dict:
    """Make a character's reference portrait again, now: a new seed (or the new `look`, if it differs). Only the
    portrait is made; every shot that shows the character gets a new key, so it waits for a new picture ("Redo
    failed")."""
    with _lock(pid):
        p, plan = _gate(pid)
        name = _ai(p).get("provider") or images.provider()
        if not creator.faces_on(plan, name):
            raise ValueError(tr("This video does not use reference portraits"))
        names = list(plan["cast"])
        if not 0 <= index < len(names):
            raise ValueError(tr("Character {n} does not exist", n=index + 1))
        images.check_ready(name)
        who = names[index]
        text = " ".join(str(look).split()) if look is not None else None
        if text and text != plan["cast"][who]:
            if len(text) > MAX_LOOK:
                raise ValueError(tr("A look is at most {n} characters", n=MAX_LOOK))
            plan["cast"][who] = text
        else:
            plan["face_seeds"] = {**(plan.get("face_seeds") or {}), who: creator.face_seed(plan, who) + 1}
        _write(pid, plan)
        _, new = creator.make_face(plan, who, config.PROJECTS / str(pid), name)
        ai = {**_ai(p)}
        if new:
            ai["cost"] = round(float(ai.get("cost") or 0) + images.cost(1, name), 3)
        approved, failed = _state(p)
        _save(pid, ai, approved, failed, [_file(pid, plan, ln, name).stem for ln in plan["lines"]])
        db.update_project(pid, log=tr("Portrait of {name} redone", name=who))
    return view(pid)


def approve(pid: int, index: int, on: bool = True) -> dict:
    """Approve (or take back the approval of) one shot's current picture. A shot with no picture cannot be approved."""
    with _lock(pid):
        p, plan = _gate(pid)
        items = rows(pid, p, plan)
        if not 0 <= index < len(items):
            raise ValueError(tr("Scene {n} does not exist", n=index + 1))
        if on and not items[index]["picture"]:
            raise ValueError(tr("Scene {n} has no picture yet", n=index + 1))
        _mark(pid, p, plan, items, {index}, on)
    return view(pid)


def approve_all(pid: int, on: bool = True) -> dict:
    """Approve every picture that is made (on=False: take every approval back). Failed and missing shots stay open."""
    with _lock(pid):
        p, plan = _gate(pid)
        items = rows(pid, p, plan)
        _mark(pid, p, plan, items, {r["index"] for r in items if r["picture"]}, on)
    return view(pid)


def _mark(pid: int, p: dict, plan: dict, items: list[dict], which: set[int], on: bool) -> None:
    provider = _ai(p).get("provider") or images.provider()
    approved, failed = _state(p)
    keys = [_file(pid, plan, ln, provider).stem for ln in plan["lines"]]
    for i in which:
        (approved.add if on else approved.discard)(keys[i])
    _save(pid, _ai(p), approved, failed, keys)


def check_continue(pid: int) -> None:
    """ValueError (translated) unless every shot is approved: the voice and render only start then."""
    with _lock(pid):
        p, plan = _gate(pid)
        todo = [r for r in rows(pid, p, plan) if r["state"] != "approved"]
        if todo:
            raise ValueError(tr("{n} not approved yet: approve or redo them first", n=tr_n(len(todo), "picture")))


def check_remake(pid: int) -> None:
    """ValueError (translated) when no shot is failed or missing (nothing to make again)."""
    with _lock(pid):
        p, plan = _gate(pid)
        if not any(r["state"] in ("failed", "missing") for r in rows(pid, p, plan)):
            raise ValueError(tr("No picture is failed or missing"))
