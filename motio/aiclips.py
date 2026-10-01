"""AI clips for the AI video mode: a scene's picture becomes a short video clip (fal, MiniMax H3 Max, image to video)
instead of a slow camera move.

The picture made by `images.py` is the first frame, so the clip keeps the look the owner approved at the script
gate; the prompt only says how it moves. Every clip is `DURATION` s (the shortest the model makes, so the cheapest):
the render holds its last frame when a scene runs longer and cuts it when the scene is shorter. The model's own
sound is dropped (the voice-over is the sound). A clip is cached by (picture, prompt, seed): only a new or edited
scene is made again. Needs `FAL_KEY`, the same key as the fal pictures.
"""
import base64
import hashlib
import io
from pathlib import Path

import httpx
from PIL import Image

from . import config, render, usage
from .i18n import tr
from .images import _detail

ENDPOINT = "minimax/h3-max/image-to-video"
URL = f"https://fal.run/{ENDPOINT}"
DURATION = 5  # seconds of video per clip: the model makes 5 to 15
RESOLUTION = "768P"  # fal's default; 1080P is a paid refinement
MAX_PER_VIDEO = 6  # the owner's cap: 6 clips of 5 s, about $2.40 at the list price
TIMEOUT = 300.0
MOVES = {"zoom_in": "slow push-in", "zoom_out": "slow pull-back", "pan_left": "slow pan to the left",
         "pan_right": "slow pan to the right"}
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


class ClipError(RuntimeError):
    pass


def check_ready() -> None:
    """ValueError (translated) when there is no fal key, so the app says so before any work."""
    if not config.env("FAL_KEY"):
        raise ValueError(tr("AI clips need your fal key: add it in Settings → Image provider, or set AI clips to 0"))


def cost(n: int = 1) -> float:
    return round(n * DURATION * usage.clip_price(), 3)


def limit(proj: dict, ch: dict | None) -> int:
    """How many scenes of this video become clips: the project's own choice when it has one, else the channel's."""
    n = ((proj.get("meta") or {}).get("ai") or {}).get("clip_limit")
    if n is None:
        n = (ch or {}).get("ai_clips") or 0
    return max(0, min(int(n), MAX_PER_VIDEO))


def used(meta: dict | None) -> bool:
    """True when the last render of the project has AI clips in it (the post then says so)."""
    return bool(((meta or {}).get("ai") or {}).get("clips"))


def pick(total: int, n: int) -> list[int]:
    """Which `n` of `total` scenes get a clip: spread over the video, the first one (the hook) always included."""
    n = max(0, min(n, total))
    return [i * total // n for i in range(n)] if n else []


def prompt(scene: str, motion: str) -> str:
    """What the clip should do: the scene as the picture shows it, then how the camera and the subject move."""
    return (f"{scene.strip().rstrip('.')}. {MOVES.get(motion, 'gentle camera move').capitalize()}, natural subtle "
            "motion of the subject, cinematic, steady, no text, no cuts.")


def key(picture: Path, text: str, seed: int = 0) -> str:
    """Cache key of one clip: another picture, prompt, seed, length or size is another clip."""
    raw = b"|".join([picture.read_bytes(), f"{ENDPOINT}|{DURATION}|{RESOLUTION}|{seed}|{text}".encode()])
    return hashlib.sha1(raw).hexdigest()[:12]


def path_for(folder: Path, picture: Path, text: str, seed: int = 0) -> Path:
    return folder / f"{key(picture, text, seed)}.mp4"


def _http(method: str, url: str, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True) as c:
            return c.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise ClipError(tr("Could not reach fal: {error}", error=str(e)[:200])) from e


def _data_uri(picture: Path) -> str:
    buf = io.BytesIO()
    with Image.open(picture) as im:
        im.convert("RGB").save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def generate(picture: Path, text: str, seed: int = 0) -> bytes:
    """One clip (MP4 bytes) that starts on `picture`. ClipError (translated) on failure."""
    r = _http("POST", URL, headers={"Authorization": f"Key {config.env('FAL_KEY')}"},
              json={"prompt": text, "image_url": _data_uri(picture), "duration": DURATION, "resolution": RESOLUTION,
                    "seed": seed, "enable_safety_checker": True, "prompt_expansion_mode": "balanced"})
    if r.status_code in (401, 403):
        raise ClipError(tr("fal refused the request ({error}): check the key and the credit on your fal account",
                           error=f"{r.status_code} {_detail(r)}"))
    if r.status_code != 200:
        raise ClipError(tr("fal could not make the clip: {error}", error=f"{r.status_code} {_detail(r)}"))
    try:
        url = r.json()["video"]["url"]
    except (ValueError, KeyError, TypeError):
        raise ClipError(tr("fal returned no clip (the prompt may have been filtered)")) from None
    got = _http("GET", url)
    if got.status_code != 200 or not got.content:
        raise ClipError(tr("Could not download the clip from fal: {error}", error=got.status_code))
    return got.content


def make(picture: Path, text: str, seed: int, folder: Path) -> tuple[Path, bool]:
    """The clip for `picture` in `folder`: the cached file when there is one, else a new one. (path, was_new)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = path_for(folder, picture, text, seed)
    if path.is_file() and path.stat().st_size:
        return path, False
    raw = path.with_suffix(".raw")
    tmp = path.with_suffix(".tmp")
    raw.write_bytes(generate(picture, text, seed))
    try:  # drop the model's sound; a file FFmpeg can't read is an error here, not at the render
        render._run([config.ffmpeg(), "-y", "-v", "error", "-i", str(raw), "-an", "-c:v", "copy",
                     "-movflags", "+faststart", "-f", "mp4", str(tmp)])
    except RuntimeError as e:
        raise ClipError(tr("The clip from fal is not a readable video")) from e
    finally:
        raw.unlink(missing_ok=True)
    tmp.replace(path)
    return path, True
