"""AI video mode ("AI video"): a French explainer from a topic where every picture is made by an image model.

No source footage: Claude writes the narration as scenes (spoken line + English picture prompt + slow camera move),
`images.py` makes one 9:16 picture per scene, and the usual voice / render steps place each picture under its line
with a Ken Burns move (render.Piece.motion). Script gate, captions, badge, 16:9 copy, video gate, Postiz and Slack
work as for every project. Pictures from a provider that isn't cleared for monetized channels (Modal's Qwen 2.1
research licence, the placeholder) never go out without the owner's approval, like a dub of someone else's video.

Same faces (`plan["same_face"]`, on by default): every character of the cast (the channel's plus the video's own, see
series.py) gets one reference portrait in out/cast/, made once and cached like a scene picture, and each scene that
names characters is made from their portraits (images.REF_PROVIDERS), so the face, hair and clothes carry over from
scene to scene instead of being re-imagined from the words. A new look or a redone portrait is a new key for every scene
that shows the character, so those scenes are made again (and asked again at the picture review).
"""
import re
import time
from pathlib import Path

from . import aiclips, config, db, images, render, series, topic, usage
from .i18n import tr

MODE = "ai"
DURATIONS = topic.DURATIONS  # 70 | 80 | 90 s: every video is 62–90 s (pipeline.MIN_SECONDS / MAX_SECONDS)
MAX_PROMPT = 600
MAX_RECAP = 500
MAX_CAST_TEXT = 2500  # a video's own cast lines (same limit as a channel's)
RETRY_WAIT = 2.0  # seconds before the one retry of a picture the provider failed to make
PICTURES_FROM, PICTURES_TO = 30, 62  # progress bar range of the pictures step
CLIPS_AT = 70  # progress of the clips step: after the voice (≤ 69), where the render starts (70)

SCRIPT_SYSTEM = """Tu es créateur de vidéos explicatives pour une chaîne francophone (TikTok, Reels, Shorts), sur
tous les sujets : société, tech, science, cuisine, voyage, nature, culture, sport, insolite… Toutes les images de
la vidéo sont générées par IA : tu écris la voix off ET, pour chaque ligne, le prompt de l'image qui l'illustre.
Style : clair, vivant, précis, phrases courtes, sans sensationnalisme. Tu réponds uniquement en JSON."""

SCRIPT_PROMPT = """Sujet : {topic}

Écris un script de voix off en français de {n_min} à {n_max} lignes, {w_min}–{w_max} mots au total
(≈ {sec} secondes) :
- Ligne 1 : accroche de 14 mots maximum.
- Explique, donne le contexte, compare, apporte une analyse ou une astuce. Termine par une question ou une ouverture.
- Chaque ligne fait au plus 20 mots.
- Tu peux ajouter des connaissances générales bien établies, mais n'invente aucun fait précis (chiffre, nom, date,
  citation) dont tu n'es pas sûr. Reste neutre sur les sujets politiques.
- « image » : pour chaque ligne, un prompt EN ANGLAIS de 25 à 50 mots qui décrit UNE scène concrète et visuelle
  illustrant la ligne (sujet, décor, lumière, cadrage), comme une photo de reportage. Ce sont des illustrations
  générées par IA : pas de texte, de logo, de sous-titre ni de panneau lisible dans l'image, aucune personnalité
  réelle reconnaissable, aucune scène violente ou choquante. Varie les plans (large, moyen, gros plan) et les lieux.
  Un personnage qui revient garde exactement la même description d'une image à l'autre.
- « motion » : le mouvement lent de la caméra sur l'image, parmi zoom_in, zoom_out, pan_left, pan_right (alterne).
- « style » : une phrase en anglais (10 à 20 mots) qui fixe le style visuel commun à toutes les images (type de
  photo, palette, lumière), pour que la vidéo soit cohérente.{extra}

Réponds avec :
{{"title_fr": "titre final (max 80 caractères)", "style": "...",
  "lines": [{{"text": "...", "image": "...", "motion": "zoom_in"}}],
  "description": "2 phrases pour la description du post, sans hashtags",
  "hashtags": ["#...", "..."]}}"""


def _one(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def is_ai(proj: dict | None) -> bool:
    return bool(proj) and proj.get("mode") == MODE


def create(topic_text: str, duration: int = 80, clip_limit: int | None = None, review_shots: bool = False,
           cast: str = "", same_face: bool = True) -> int:
    """Create an AI video project (not started). ValueError (translated) when something is missing or wrong, or
    when the chosen image provider isn't ready, so the app says so before any work. `clip_limit`: how many scenes
    become AI clips (aiclips.py) for this video; None = the channel's setting. `review_shots`: stop after the
    pictures are made so each one can be approved or redone before the voice and the render (shots.py). `cast`: this
    video's own characters, one `Name: look` line each (fictional people only), added to the channel's. `same_face`:
    make the scenes of a character from one reference portrait of them (the scenes with characters cost a bit more)."""
    text = _one(topic_text)[:300]
    if not text:
        raise ValueError(tr("Enter a topic for the AI video"))
    if duration not in DURATIONS:
        raise ValueError(tr("Duration must be one of {choices} seconds", choices=", ".join(map(str, DURATIONS))))
    if clip_limit is not None and not 0 <= clip_limit <= aiclips.MAX_PER_VIDEO:
        raise ValueError(tr("AI clips per video must be between 0 and {n}", n=aiclips.MAX_PER_VIDEO))
    cast_text = "\n".join(ln.strip() for ln in str(cast or "").strip().splitlines() if ln.strip())[:MAX_CAST_TEXT]
    series.parse_cast(cast_text, strict=True)
    images.check_ready()
    if clip_limit:
        aiclips.check_ready()
    ai = {"provider": images.provider(), "same_face": bool(same_face)}
    ai |= ({} if clip_limit is None else {"clip_limit": clip_limit}) | ({"review_shots": True} if review_shots else {})
    ai |= {"cast": cast_text} if cast_text else {}
    pid = db.create_project(None, text, mode=MODE)
    db.update_project(pid, log=tr("AI video: {topic} · {duration} s · pictures from {provider}", topic=text,
                                  duration=duration, provider=images.provider()),
                      meta={"topic": text, "duration": duration, "ai": ai})
    return pid


def needs_review(proj: dict) -> bool:
    """Pictures from a provider that isn't cleared for a monetized channel: no auto-send, the video gate is forced."""
    if not is_ai(proj):
        return False
    ai = (proj.get("meta") or {}).get("ai") or {}
    return (images.needs_review(ai.get("provider") or images.provider())
            or bool(ai.get("clips") and aiclips.needs_review(ai.get("clip_provider"))))


def clips_need_review(proj: dict) -> bool:
    """True when it is the clips (not the pictures) that stop the video at the gate: HeyGen clips, terms not cleared."""
    ai = (proj.get("meta") or {}).get("ai") or {}
    return bool(is_ai(proj) and ai.get("clips") and aiclips.needs_review(ai.get("clip_provider")))


def tidy(plan: dict) -> dict:
    """Claude's scenes → lines with spoken text, picture prompt and camera move. Empty lines are dropped, a missing or
    unknown move rotates through MOTIONS, a missing prompt stays empty (the picture then comes from the line's text)."""
    lines = []
    for ln in plan.get("lines") or []:
        ln = ln if isinstance(ln, dict) else {"text": ln}
        text = _one(ln.get("text"))
        if not text:
            continue
        motion = ln.get("motion") if ln.get("motion") in render.MOTIONS else render.MOTIONS[len(lines) % 4]
        out = {"text": text, "image": _one(ln.get("image"))[:MAX_PROMPT], "motion": motion}
        if isinstance(ln.get("seed"), int) and ln["seed"] > 0:
            out["seed"] = ln["seed"]
        lines.append(out)
    tidy_plan = {**plan, "style": _one(plan.get("style"))[:300], "lines": lines}
    if "recap" in plan:
        tidy_plan["recap"] = _one(plan["recap"])[:MAX_RECAP]
    return tidy_plan


def _scene(plan: dict, ln: dict) -> str:
    return ln.get("image") or f"{plan.get('title_fr') or ''}: {ln.get('text') or ''}"


def _join(parts: list[str]) -> str:
    return ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip()) + "."


def faces_on(plan: dict, provider: str) -> bool:
    """Scenes are made from the characters' reference portraits (same faces) with this provider."""
    return bool(plan.get("same_face") and plan.get("cast")) and images.base(provider) in images.REF_PROVIDERS


def faces(plan: dict, ln: dict, provider: str) -> list[str]:
    """The characters whose portrait this scene is made from (none when same faces is off)."""
    if not faces_on(plan, provider):
        return []
    return series.named(_scene(plan, ln), plan["cast"])[:images.MAX_REFS]


def face_prompt(plan: dict, name: str) -> str:
    """The text of a character's reference portrait: the fixed look, a plain neutral shot, the video's style."""
    return _join([f"Character reference portrait of {name}, a fictional person: {plan['cast'][name]}",
                  "front view, head to waist, neutral expression, plain light grey studio background",
                  plan.get("style") or "", images.style()])


def face_seed(plan: dict, name: str) -> int:
    return int((plan.get("face_seeds") or {}).get(name) or 0)


def face_file(out: Path, plan: dict, name: str, provider: str) -> Path:
    return out / "cast" / f"{images.key(face_prompt(plan, name), face_seed(plan, name), provider)}.png"


def prompt(plan: dict, ln: dict, provider: str | None = None) -> str:
    """The text the image model gets: the scene (with the look of every named recurring character in front of it), the
    video's visual style, then the global style of Settings. With same faces (`provider` given), it starts by naming
    the reference portraits the picture is made from."""
    scene = series.with_cast(_scene(plan, ln), plan.get("cast"))  # a character is always described in the same words
    who = faces(plan, ln, provider) if provider else []
    lead = ""
    if who:
        lead = (", ".join(f"input picture {i} is {name}" for i, name in enumerate(who, 1))
                + ": keep each one's face, hair, build and clothes exactly as in their picture, in this new scene")
    return _join([lead, scene, plan.get("style") or "", images.style()])


def picture_file(out: Path, plan: dict, ln: dict, provider: str) -> Path:
    refs = [face_file(out, plan, n, provider).stem for n in faces(plan, ln, provider)]
    return out / "scenes" / f"{images.key(prompt(plan, ln, provider), int(ln.get('seed') or 0), provider, refs)}.png"


def _retry(make):
    for attempt in (1, 2):
        try:
            return make()
        except images.ImageError:
            if attempt == 2:
                raise
            time.sleep(RETRY_WAIT)
    raise AssertionError("unreachable")


def make_face(plan: dict, name: str, out: Path, provider: str) -> tuple[Path, bool]:
    """A character's reference portrait in out/cast/ (path, was_new), tried once more on a provider error."""
    return _retry(lambda: images.make(face_prompt(plan, name), face_seed(plan, name), out / "cast", provider))


def make_picture(plan: dict, ln: dict, out: Path, name: str) -> tuple[Path, bool, float]:
    """The picture of one scene in out/scenes/ (path, was_new, USD spent), with the reference portraits of its
    characters made first when same faces is on. A provider error is tried once more, then raised
    (images.ImageError, translated)."""
    refs, usd = [], 0.0
    for who in faces(plan, ln, name):
        f, new = make_face(plan, who, out, name)
        usd += images.cost(int(new), name)
        refs.append((f.stem, f))
    path, new = _retry(lambda: images.make(prompt(plan, ln, name), int(ln.get("seed") or 0), out / "scenes", name,
                                           refs))
    return path, new, round(usd + images.cost(int(new), name, refs=bool(refs)), 3)


def pictures(pid: int, plan: dict, out: Path, step, lo: int = PICTURES_FROM, hi: int = PICTURES_TO) -> list[dict]:
    """One picture per scene, in out/scenes/ (a scene already made is not made again). Returns the scenes as render
    sources. A picture that fails is tried once more, then the step stops: the ones already made are kept, so a retry
    only makes what is missing. `lo`..`hi`: the progress range of the step."""
    name = images.provider()
    images.check_ready(name)
    lines = plan["lines"]
    sources, fresh, cost = [], 0, 0.0
    for i, ln in enumerate(lines):
        step("Pictures", lo + (hi - lo) * i // len(lines),
             tr("Picture {n} of {total} ({provider})", n=i + 1, total=len(lines), provider=name))
        try:
            path, new, usd = make_picture(plan, ln, out, name)
        except images.ImageError as e:
            raise RuntimeError(tr("Picture {n} failed: {error}", n=i + 1, error=e)) from e
        fresh += new
        cost += usd
        sources.append({"path": str(path), "platform": "AI", "uploader": name, "title": ln["text"], "duration": 0,
                        "url": None, "id": path.stem})
    cost = round(cost, 3)
    ai = {**((db.get_project(pid) or {}).get("meta", {}).get("ai") or {}), "provider": name, "scenes": len(lines)}
    ai["cost"] = round(float(ai.get("cost") or 0) + cost, 3) if cost else ai.get("cost") or 0
    step("Pictures", hi, _made_log(fresh, len(lines), cost), ai=ai)
    return sources


def animate(pid: int, plan: dict, scenes: list[dict], out: Path, step, want: int) -> list[dict]:
    """Turn `want` of the scenes into AI clips (aiclips.py), right before the render, once the voice fixes the script.
    Returns the scenes as render sources: a scene with a clip points at it (`clip` true), the others keep their picture
    and camera move. A clip that can't be made (fal down, refused, budget reached) leaves its scene as it was, so a
    provider problem never fails a video. A clip already made is reused and not paid for again."""
    lines = plan["lines"]
    chosen = aiclips.pick(len(lines), want)
    if not chosen:  # none wanted (any more): a render after the limit went back to 0 must not keep saying "AI clips"
        ai = (db.get_project(pid) or {}).get("meta", {}).get("ai") or {}
        if ai.get("clips"):
            db.update_project(pid, meta={"ai": {**ai, "clips": 0}})
        return list(scenes)
    name = aiclips.provider()  # read once: a change in Settings during the render cannot mix two providers
    sources, made, fresh = list(scenes), 0, 0
    for n, i in enumerate(chosen, 1):
        ln, picture = lines[i], Path(scenes[i]["path"])
        text = aiclips.prompt(prompt(plan, ln), ln.get("motion") or "")
        seed = int(ln.get("seed") or 0)
        step("Clips", CLIPS_AT, tr("Clip {n} of {total} (scene {scene})", n=n, total=len(chosen), scene=i + 1))
        if not aiclips.path_for(out / "clips", picture, text, seed, name).is_file() and usage.over_budget():
            step("Clips", CLIPS_AT, tr("Monthly budget reached: the other scenes keep their camera move"))
            break
        for attempt in (1, 2):
            try:
                path, new = aiclips.make(picture, text, seed, out / "clips", name)
                break
            except aiclips.ClipError as e:
                path = None
                if attempt == 1:
                    time.sleep(RETRY_WAIT)
                else:
                    step("Clips", CLIPS_AT, tr("Clip for scene {scene} failed ({error}): it keeps its camera move",
                                               scene=i + 1, error=e))
        if path is None:
            continue
        if new:
            fresh += 1
            usage.record_clip(aiclips.DURATION, aiclips.endpoint(name), name)
        made += 1
        sources[i] = {**scenes[i], "path": str(path), "clip": True}
    cost = aiclips.cost(fresh, name)
    ai = {**((db.get_project(pid) or {}).get("meta", {}).get("ai") or {}), "clips": made,
          "clip_provider": name if made else None}
    ai["cost"] = round(float(ai.get("cost") or 0) + cost, 3)
    step("Clips", CLIPS_AT, tr("{made} of {total} AI clips ready · about ${cost}", made=made, total=len(chosen),
                               cost=f"{cost:.2f}"), ai=ai)
    return sources


def _made_log(fresh: int, total: int, cost: float) -> str:
    if not fresh:
        return tr("All {total} pictures were already made", total=total)
    return tr("Made {fresh} of {total} pictures · about ${cost}", fresh=fresh, total=total, cost=f"{cost:.2f}")


def timeline(plan: dict, nar: dict, total: float, scenes: list[dict] | None = None) -> list[render.Piece]:
    """One piece per scene: from where its line starts to where the next one starts (the first from 0, the last to the
    end of the video), each with its camera move, except the scenes that got an AI clip (they play the clip)."""
    lines, spans = plan["lines"], nar.get("lines") or []
    if len(spans) != len(lines):  # no per-line times: share the voice by words
        words = [max(len(ln["text"].split()), 1) for ln in lines]
        starts, t = [], 0.0
        for w in words:
            starts.append(t)
            t += nar["duration"] * w / sum(words)
    else:
        starts = [s["start"] for s in spans]
    pieces = []
    for i, ln in enumerate(lines):
        t0 = 0.0 if i == 0 else starts[i]
        t1 = total if i == len(lines) - 1 else starts[i + 1]
        motion = ln.get("motion") if ln.get("motion") in render.MOTIONS else render.MOTIONS[i % 4]
        if scenes and i < len(scenes) and scenes[i].get("clip"):
            motion = ""
        pieces.append(render.Piece(i, 0.0, round(max(t1 - t0, 0.5), 3), round(t0, 3), motion=motion))
    return pieces


def render_args(plan: dict, scenes: list[dict], nar: dict, min_total: float) -> dict:
    """render.render arguments for an AI video: the scenes as sources and one moving piece per scene."""
    total = max(nar["duration"] + render.TAIL, min_total)
    return {"plan": plan, "sources": scenes, "pieces": timeline(plan, nar, total, scenes), "total": total}


def view(proj: dict) -> dict | None:
    """What the project page shows: provider, whether the video gate is forced, what the pictures cost so far, and
    the episode number with its recap when the channel has a series."""
    if not is_ai(proj):
        return None
    meta = proj.get("meta") or {}
    ai = meta.get("ai") or {}
    name = ai.get("provider") or images.provider()
    return {"topic": meta.get("topic"), "provider": name, "needs_review": needs_review(proj),
            "cost": ai.get("cost"), "scenes": ai.get("scenes"), "clips": ai.get("clips"),
            "clip_limit": ai.get("clip_limit"), "clip_provider": ai.get("clip_provider"),
            "episode": ai.get("episode"), "recap": ai.get("recap"), "review_shots": bool(ai.get("review_shots")),
            "same_face": bool(ai.get("same_face")), "cast": ai.get("cast") or ""}


def media(path: Path) -> str | None:
    """A file under the data folder as the path /media serves; None when it isn't there."""
    if not path.is_file():
        return None
    try:
        return path.resolve().relative_to(config.DATA.resolve()).as_posix()
    except ValueError:
        return None
