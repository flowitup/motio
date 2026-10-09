"""A channel's series and recurring characters for AI videos ("Series" and "Cast" in the channel profile).

Cast: one character per line, `Name: how they look` (English, fictional people only). The look is fixed text kept
with the script (`plan["cast"]`): every scene whose picture prompt names a character gets that look put in front of the
prompt (`creator.prompt`), so the same words reach the image model each time instead of Claude re-describing the
person scene by scene. A prompt the user edits and that names a character gets the look too.

Series: the premise and rules of the story, plus a recap Claude writes for each episode (`meta.ai.recap`). The next
episode of the same channel is written knowing the last few recaps, so the story goes on instead of starting over.
"""
import re

from . import db
from .i18n import tr

MAX_CAST = 8  # characters per channel: every name and look goes into each script prompt
MAX_NAME = 40
RECENT = 6  # earlier episodes Claude is told about
_COLON = re.compile(r"\s*[:：]\s*")


def parse_cast(text: str, strict: bool = False) -> dict[str, str]:
    """"Lin: a woman in her 30s…" lines → {"Lin": "a woman in her 30s…"}. strict: ValueError for a line that is not
    `Name: look`, a repeated name or too many characters (when a profile is saved); otherwise such lines are skipped."""
    cast: dict[str, str] = {}
    for n, line in enumerate(str(text or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        m = _COLON.search(line)
        name, look = (line[:m.start()], line[m.end():]) if m else (line, "")
        name, look = " ".join(name.split()), " ".join(look.split())
        if not name or not look or len(name) > MAX_NAME or name.casefold() in {k.casefold() for k in cast}:
            if strict:
                raise ValueError(tr("Cast line {n} must look like “Name: how they look”, with a name not used before",
                                    n=n))
            continue
        cast[name] = look
    if strict and len(cast) > MAX_CAST:
        raise ValueError(tr("At most {n} characters in the cast", n=MAX_CAST))
    return dict(list(cast.items())[:MAX_CAST])


def merge(*casts: dict[str, str]) -> dict[str, str]:
    """The channel's cast with the video's own on top: a name used again (any case) takes the later look, and the
    first MAX_CAST characters are kept."""
    out: dict[str, str] = {}
    for cast in casts:
        for name, look in (cast or {}).items():
            same = next((k for k in out if k.casefold() == name.casefold()), None)
            if same:
                del out[same]
            out[name] = look
    return dict(list(out.items())[:MAX_CAST])


def for_project(ch: dict | None, proj: dict) -> dict[str, str]:
    """The cast of an AI video: the channel's characters plus the ones typed for this video."""
    own = (((proj.get("meta") or {}).get("ai") or {}).get("cast")) or ""
    return merge(parse_cast((ch or {}).get("cast") or ""), parse_cast(own))


def named(prompt_text: str, cast: dict[str, str]) -> list[str]:
    """The characters a picture prompt names (whole words, any case), in the order of the cast."""
    return [name for name in cast if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", prompt_text or "", re.I)]


def with_cast(scene: str, cast: dict[str, str] | None) -> str:
    """The scene prompt with the fixed look of every named character in front of it."""
    found = named(scene, cast or {})
    if not found:
        return scene
    looks = " ".join(f"{name}: {cast[name].rstrip('. ')}." for name in found)
    return f"Characters, always drawn exactly like this — {looks} Scene: {scene}"


def earlier(channel: int, pid: int) -> list[dict]:
    """The channel's earlier AI episodes that have a recap, oldest first: [{pid, n, title, recap}]."""
    out = []
    for p in db.list_projects(300):
        meta = p.get("meta") or {}
        ai = meta.get("ai") or {}
        if (p.get("mode") == "ai" and meta.get("channel") == channel and p["id"] < pid and p["status"] != "failed"
                and ai.get("recap")):
            out.append({"pid": p["id"], "n": int(ai.get("episode") or 0), "title": p.get("title") or "",
                        "recap": str(ai["recap"])})
    out.sort(key=lambda e: e["pid"])
    for i, e in enumerate(out, 1):  # an episode made before numbering existed counts in order
        e["n"] = e["n"] or i
    return out


def block(ch: dict | None, pid: int, cast: dict[str, str] | None = None) -> tuple[str, int | None]:
    """(text added to the AI script prompt, episode number). ("", None) with no series and no cast. `cast`: the
    video's whole cast (for_project); None = the channel's."""
    cast = parse_cast((ch or {}).get("cast") or "") if cast is None else cast
    story = str((ch or {}).get("series") or "").strip()
    if not cast and not story:
        return "", None
    parts, episode = [], None
    if story and ch:
        past = earlier(ch["id"], pid)
        episode = max((e["n"] for e in past), default=0) + 1
        parts.append(f"Série « {ch['name']} », épisode {episode}. Cadre de la série (à respecter) :\n{story}")
        if past:
            parts.append("Épisodes précédents (ne les répète pas, continue l'histoire) :\n"
                         + "\n".join(f"- Épisode {e['n']} « {e['title']} » : {e['recap']}" for e in past[-RECENT:]))
        parts.append("Ajoute au JSON la clé « recap » : 2 phrases en français qui résument ce qui se passe dans cet "
                     "épisode, pour écrire le suivant.")
    if cast:
        parts.append("Personnages récurrents (fictifs). Dans le prompt « image » d'une scène où ils apparaissent, "
                     "écris leur prénom exactement comme ci-dessous et NE décris PAS leur apparence : Motio ajoute "
                     "la description fixe devant le prompt.\n" + "\n".join(f"- {name}" for name in cast))
    return "\n\n" + "\n\n".join(parts), episode
