"""AI pictures for the AI video mode (creator.py): one 9:16 picture per scene.

One adapter, three providers, switched in Settings (`IMAGE_PROVIDER`):
- fal: `fal-ai/qwen-image-2512` (Apache 2.0, fine for a monetized channel), needs `FAL_KEY` and credit.
- modal: the owner's own Modal app `qwen21-uc` (Qwen-Image 2.1 UC). Its Qwen Research Licence is not for monetized
  channels and it has no safety filter, so a video made with it always stops at the video gate. Needs the `modal`
  package and a Modal login (not bundled in the installers; meant for the dev engine or the server).
- placeholder: gradient cards that show the prompt, no network. To try the flow; also stops at the video gate.
A picture is cached by (provider, size, prompt, seed): only a new or edited scene is generated again.
"""
import hashlib
import io
import textwrap
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from . import config
from .i18n import tr
from .render import FONT_BOLD, _font

PROVIDERS = ("fal", "modal", "placeholder")
DEFAULT_PROVIDER = "fal"
REVIEW_PROVIDERS = ("modal", "placeholder")  # output that must not go out without a human look
WIDTH, HEIGHT = 1088, 1920  # multiples of 16 (Qwen), close enough to 1080×1920 to be cropped
PRICE = {"fal": 0.042, "modal": 0.009, "placeholder": 0.0}  # estimated USD per picture (fal: ~$0.02 per megapixel)
FAL_URL = "https://fal.run/fal-ai/qwen-image-2512"
MODAL_APP, MODAL_CLS, MODAL_STEPS = "qwen21-uc", "Qwen21UC", 25
TIMEOUT = 240.0  # a cold Modal start takes ~70 s
DEFAULT_STYLE = "photorealistic, natural light, sharp focus, vertical 9:16 composition, no text, no watermark"
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


class ImageError(RuntimeError):
    pass


def provider() -> str:
    p = config.env("IMAGE_PROVIDER", DEFAULT_PROVIDER).lower()
    return p if p in PROVIDERS else DEFAULT_PROVIDER


def style() -> str:
    """Global picture style added to every scene prompt (Settings → Image style)."""
    return config.env("IMAGE_STYLE", DEFAULT_STYLE)


def needs_review(name: str | None = None) -> bool:
    return (name or provider()) in REVIEW_PROVIDERS


def check_ready(name: str | None = None) -> None:
    """ValueError (translated) when the chosen provider can't generate yet, so the app says so before any work."""
    name = name or provider()
    if name == "fal" and not config.env("FAL_KEY"):
        raise ValueError(tr("Add your fal key in Settings → Image provider (or choose the Placeholder provider to "
                            "try the flow)"))
    if name == "modal":
        try:
            import modal  # noqa: F401
        except ImportError:
            raise ValueError(tr("The Modal provider needs the `modal` Python package and a Modal login: it runs from "
                                "the dev engine or the server, not the packaged app")) from None


def cost(n: int, name: str | None = None) -> float:
    return round(n * PRICE[name or provider()], 3)


def key(prompt: str, seed: int = 0, name: str | None = None) -> str:
    """Cache key of one picture: a new prompt, seed, provider or size is a new picture."""
    raw = f"{name or provider()}|{WIDTH}x{HEIGHT}|{seed}|{prompt}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _http(method: str, url: str, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True) as c:
            return c.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise ImageError(tr("Could not reach the image provider: {error}", error=str(e)[:200])) from e


def _detail(r: httpx.Response) -> str:
    try:
        body = r.json()
        d = body.get("detail") if isinstance(body, dict) else None
        if isinstance(d, list):
            d = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
        return str(d or body)[:200]
    except ValueError:
        return r.text[:200]


def _fal(prompt: str, seed: int) -> bytes:
    r = _http("POST", FAL_URL, headers={"Authorization": f"Key {config.env('FAL_KEY')}"},
              json={"prompt": prompt, "image_size": {"width": WIDTH, "height": HEIGHT}, "num_images": 1,
                    "seed": seed, "output_format": "png", "enable_safety_checker": True})
    if r.status_code in (401, 403):
        raise ImageError(tr("fal refused the request ({error}): check the key and the credit on your fal account",
                            error=f"{r.status_code} {_detail(r)}"))
    if r.status_code != 200:
        raise ImageError(tr("fal could not make the picture: {error}", error=f"{r.status_code} {_detail(r)}"))
    try:
        url = r.json()["images"][0]["url"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise ImageError(tr("fal returned no picture (the prompt may have been filtered)")) from None
    got = _http("GET", url)
    if got.status_code != 200 or not got.content:
        raise ImageError(tr("Could not download the picture from fal: {error}", error=got.status_code))
    return got.content


def _modal(prompt: str, seed: int) -> bytes:
    try:
        import modal
    except ImportError:
        raise ImageError(tr("The Modal provider needs the `modal` Python package and a Modal login: it runs from "
                            "the dev engine or the server, not the packaged app")) from None
    try:
        gen = modal.Cls.from_name(MODAL_APP, MODAL_CLS)()
        return gen.generate.remote(prompt, WIDTH, HEIGHT, MODAL_STEPS, seed)
    except Exception as e:  # modal raises its own error types (auth, app not deployed, timeout…)
        raise ImageError(tr("Modal could not make the picture: {error}", error=str(e)[:200])) from e


_TINTS = [((34, 50, 92), (214, 120, 84)), ((20, 70, 66), (232, 196, 110)), ((70, 34, 90), (236, 130, 150)),
          ((28, 28, 40), (120, 160, 210)), ((80, 40, 28), (240, 210, 150))]


def _placeholder(prompt: str, seed: int) -> bytes:
    """A vertical gradient with the prompt written on it: the picture is obviously not real, and two scenes differ."""
    top, bottom = _TINTS[int(hashlib.sha1(f"{seed}|{prompt}".encode()).hexdigest(), 16) % len(_TINTS)]
    col = Image.linear_gradient("L").resize((WIDTH, HEIGHT))
    img = Image.composite(Image.new("RGB", (WIDTH, HEIGHT), bottom), Image.new("RGB", (WIDTH, HEIGHT), top), col)
    d = ImageDraw.Draw(img)
    f = _font(FONT_BOLD, 54)
    y = HEIGHT // 2 - 260
    for ln in textwrap.wrap(prompt, 34)[:9]:
        d.text((70, y), ln, font=f, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
        y += 70
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def generate(prompt: str, seed: int = 0, name: str | None = None) -> bytes:
    """One picture (image bytes) for `prompt`. ImageError (translated) on failure."""
    name = name or provider()
    return {"fal": _fal, "modal": _modal, "placeholder": _placeholder}[name](prompt, seed)


def make(prompt: str, seed: int, folder: Path, name: str | None = None) -> tuple[Path, bool]:
    """The picture for `prompt` in `folder`: the cached file when there is one, else a new one. (path, was_new)."""
    name = name or provider()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{key(prompt, seed, name)}.png"
    if path.is_file() and path.stat().st_size:
        return path, False
    data = generate(prompt, seed, name)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # not an image (an error page, an empty reply)
        raise ImageError(tr("The provider did not return a picture")) from e
    tmp = path.with_suffix(".tmp")
    img.convert("RGB").save(tmp, "PNG")
    tmp.replace(path)
    return path, True
