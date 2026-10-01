"""AI clips for the AI video mode: a scene's picture becomes a short video clip (image to video) instead of a slow
camera move. Two providers, picked in Settings (`CLIP_PROVIDER`): fal with MiniMax H3 Max (default) or HeyGen Video 1
(`heygen-video-1`, a post-train of H3, launched 2026-09-30, a fraction of the price but not yet cleared for monetized
channels: a video with its clips stops at the video gate, see `REVIEW_PROVIDERS`).

The picture made by `images.py` is the first frame, so the clip keeps the look the owner approved at the script
gate; the prompt only says how it moves. Every clip is `DURATION` s (the shortest the model makes, so the cheapest):
the render holds its last frame when a scene runs longer and cuts it when the scene is shorter. The model's own
sound is dropped (the voice-over is the sound). A clip is cached by (picture, prompt, seed): only a new or edited
scene is made again. fal needs `FAL_KEY` (the same key as the fal pictures), HeyGen needs `HEYGEN_API_KEY` and credit
on its API wallet.
"""
import base64
import hashlib
import io
import time
from pathlib import Path

import httpx
from PIL import Image

from . import config, render, usage
from .i18n import tr
from .images import _detail

ENDPOINT = "minimax/h3-max/image-to-video"
URL = f"https://fal.run/{ENDPOINT}"
PROVIDERS = ("fal", "heygen")
REVIEW_PROVIDERS = ("heygen",)  # terms of use for monetized channels not read yet: the video gate is forced
HEYGEN_ENDPOINT = "heygen/heygen-video-1"
HEYGEN_URL = "https://api.heygen.com/v3/models/videos"
HEYGEN_MODEL = "heygen-video-1"
HEYGEN_RESOLUTION = "768p"
POLL_EVERY = 3.0  # seconds between two looks at a HeyGen job
MAX_WAIT = 420.0  # a job still not done after this long is given up
DURATION = 5  # seconds of video per clip: the model makes 5 to 15
RESOLUTION = "768P"  # fal's default; 1080P is a paid refinement
MAX_PER_VIDEO = 6  # the owner's cap: 6 clips of 5 s, about $2.40 at the list price
TIMEOUT = 300.0
MOVES = {"zoom_in": "slow push-in", "zoom_out": "slow pull-back", "pan_left": "slow pan to the left",
         "pan_right": "slow pan to the right"}
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport
_sleep = time.sleep  # tests swap in a no-op
_override: str | None = None  # `trial` (the clipcheck command) picks a provider for one call without touching Settings


class ClipError(RuntimeError):
    pass


def provider() -> str:
    """The clip provider in Settings (CLIP_PROVIDER); anything unknown means fal."""
    name = _override or config.env("CLIP_PROVIDER", "fal").lower()
    return name if name in PROVIDERS else "fal"


def endpoint(name: str | None = None) -> str:
    """The model's name as it appears in the cache key and the usage rows."""
    return HEYGEN_ENDPOINT if (name or provider()) == "heygen" else ENDPOINT


def needs_review(name: str | None) -> bool:
    """Clips from a provider that isn't cleared for a monetized channel: no auto-send, the video gate is forced."""
    return (name or "") in REVIEW_PROVIDERS


def check_ready() -> None:
    """ValueError (translated) when there is no key for the clip provider, so the app says so before any work."""
    if provider() == "heygen":
        if not config.env("HEYGEN_API_KEY"):
            raise ValueError(tr("AI clips need your HeyGen key: add it in Settings → AI pictures, "
                                "or set AI clips to 0"))
    elif not config.env("FAL_KEY"):
        raise ValueError(tr("AI clips need your fal key: add it in Settings → Image provider, or set AI clips to 0"))


def cost(n: int = 1) -> float:
    return round(n * DURATION * usage.clip_price(provider()), 3)


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
    model = endpoint()  # fal keeps its old key, so clips made before HeyGen existed stay cached
    raw = b"|".join([picture.read_bytes(), f"{model}|{DURATION}|{RESOLUTION}|{seed}|{text}".encode()])
    return hashlib.sha1(raw).hexdigest()[:12]


def path_for(folder: Path, picture: Path, text: str, seed: int = 0) -> Path:
    return folder / f"{key(picture, text, seed)}.mp4"


def _http(method: str, url: str, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True) as c:
            return c.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise ClipError(tr("Could not reach fal: {error}", error=str(e)[:200])) from e


def _jpeg_b64(picture: Path) -> str:
    buf = io.BytesIO()
    with Image.open(picture) as im:
        im.convert("RGB").save(buf, "JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _data_uri(picture: Path) -> str:
    return "data:image/jpeg;base64," + _jpeg_b64(picture)


def _fal_clip(picture: Path, text: str, seed: int) -> bytes:
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


def _heygen_http(method: str, url: str, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True) as c:
            return c.request(method, url, headers={"x-api-key": config.env("HEYGEN_API_KEY")}, **kw)
    except httpx.HTTPError as e:
        raise ClipError(tr("Could not reach HeyGen: {error}", error=str(e)[:200])) from e


def _heygen_check(r: httpx.Response, what: str) -> dict:
    """The `data` of a HeyGen answer, or ClipError (translated) with the reason HeyGen gave."""
    if r.status_code in (401, 403):
        raise ClipError(tr("HeyGen refused the request ({error}): check the API key",
                           error=f"{r.status_code} {_hg(r)}"))
    if r.status_code == 402:
        raise ClipError(tr("HeyGen has no credit left: top up the API balance in your HeyGen account"))
    if r.status_code not in (200, 201, 202):
        raise ClipError(tr("HeyGen could not make the clip: {error}", error=f"{what} {r.status_code} {_hg(r)}"))
    try:
        body = r.json()
    except ValueError:
        body = None
    data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else body
    if not isinstance(data, dict):
        raise ClipError(tr("HeyGen returned no clip"))
    return data


def _hg(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return r.text[:200]
    err = body.get("error") or body.get("message") or body if isinstance(body, dict) else body
    return str(err.get("message") if isinstance(err, dict) and err.get("message") else err)[:200]


def _heygen_clip(picture: Path, text: str, seed: int) -> bytes:
    """HeyGen Video 1, image to video: the picture is the first frame and the clip keeps its proportions. The model also
    makes dialogue and sound, which the render drops, so the prompt asks for a silent scene (no lips moving to words
    nobody hears). POST /v3/models/videos, then a look every few seconds until the job is done."""
    created = _heygen_check(_heygen_http("POST", HEYGEN_URL, json={
        "mode": "image_to_video", "model": HEYGEN_MODEL, "duration": DURATION, "resolution": HEYGEN_RESOLUTION,
        "prompt": f"{text} Silent scene, no dialogue, no music.", "seed": seed % 2**32,
        "image": {"type": "base64", "media_type": "image/jpeg", "data": _jpeg_b64(picture)}}), "create")
    vid = created.get("video_id") or created.get("id")
    if not vid:
        raise ClipError(tr("HeyGen returned no clip"))
    waited = 0.0
    while True:
        job = _heygen_check(_heygen_http("GET", f"{HEYGEN_URL}/{vid}"), "status")
        status = job.get("status")
        if status == "completed":
            break
        if status in ("failed", "cancelled"):
            raise ClipError(tr("HeyGen could not make the clip: {error}",
                               error=f"{job.get('failure_code') or status} {job.get('failure_message') or ''}".strip()))
        if waited >= MAX_WAIT:
            raise ClipError(tr("HeyGen took too long to make the clip"))
        _sleep(POLL_EVERY)
        waited += POLL_EVERY
    if not job.get("video_url"):
        raise ClipError(tr("HeyGen returned no clip"))
    got = _http("GET", job["video_url"])  # a signed link: no key sent to it
    if got.status_code != 200 or not got.content:
        raise ClipError(tr("Could not download the clip from HeyGen: {error}", error=got.status_code))
    return got.content


def generate(picture: Path, text: str, seed: int = 0) -> bytes:
    """One clip (MP4 bytes) that starts on `picture`. ClipError (translated) on failure."""
    return (_heygen_clip if provider() == "heygen" else _fal_clip)(picture, text, seed)


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
        raise ClipError(tr("The clip from HeyGen is not a readable video" if provider() == "heygen"
                           else "The clip from fal is not a readable video")) from e
    finally:
        raw.unlink(missing_ok=True)
    tmp.replace(path)
    return path, True


def trial(picture: Path, text: str, name: str, folder: Path, seed: int = 0) -> tuple[Path, float]:
    """One real clip from provider `name` for a try-out (`python -m motio clipcheck`): the same code as a real video,
    paid and recorded in the usage table like one. (path, USD). Not for the engine: it is not thread safe."""
    global _override
    if name not in PROVIDERS:
        raise ValueError(tr("CLIP_PROVIDER must be one of {choices}", choices=", ".join(PROVIDERS)))
    _override = name
    try:
        check_ready()
        path, new = make(picture, text, seed, folder / name)
        usd = cost(1) if new else 0.0
        if new:
            usage.record_clip(DURATION, endpoint(), name)
        return path, usd
    finally:
        _override = None
