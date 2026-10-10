"""AI pictures for the AI video mode (creator.py): one 9:16 picture per scene.

One adapter, three providers, switched in Settings (`IMAGE_PROVIDER`):
- fal: Seedream 5 Pro by default, needs `FAL_KEY` and credit. The model is picked in Settings (`FAL_IMAGE_MODEL`, one of
  `FAL_MODELS`); any other model than the default is named `fal:<model>` (that string is the provider name kept in
  `meta.ai.provider` and in the cache key). No fal model is cleared for a monetized channel yet (`CLEARED_FAL_MODELS`),
  so a picture from fal stops at the video gate until one is.
- modal: the owner's own Modal app `qwen21-uc` (Qwen-Image 2.1 UC). Its Qwen Research Licence is not for monetized
  channels and it has no safety filter, so a video made with it always stops at the video gate. Needs the `modal`
  package and a Modal login (not bundled in the installers; meant for the dev engine or the server).
- placeholder: gradient cards that show the prompt, no network. To try the flow; also stops at the video gate.
A picture is cached by (provider, size, prompt, seed): only a new or edited scene is generated again.

Same faces: a scene that shows recurring characters can be made from their reference portraits (`refs`) instead of
the words alone, with `fal-ai/qwen-image-edit-2511` (Apache 2.0, whatever model is picked for the other scenes). The
placeholder writes the reference names on its card; Modal has no such model, so its scenes stay text only.
"""
import base64
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
WIDTH, HEIGHT = 1088, 1920  # multiples of 16, close enough to 1080×1920 to be cropped
# fal text-to-image models the owner can pick (alias → fal path, estimated USD per picture, request fields). `px`: the
# model takes a width × height `image_size`; `seed`: it takes a seed (the others make a new picture for a new seed
# anyway, the seed is still part of the cache key). Hot models of fal's own trending list (10/2026); prices from fal's
# model pages, the ones marked "est." are worked out from a per-token or per-megapixel price. A model that is not in
# CLEARED_FAL_MODELS forces the video gate (`needs_review`).
FAL_MODELS = {
    "nano-banana-2": {"path": "fal-ai/nano-banana-2", "price": 0.12, "seed": True,  # $0.08 at 1K, ×1.5 at 2K
                      "body": {"aspect_ratio": "9:16", "resolution": "2K", "safety_tolerance": "2"}},
    "nano-banana-2.1": {"path": "google/nano-banana-2.1", "price": 0.06, "seed": True,  # est. (per token)
                        "body": {"aspect_ratio": "9:16", "resolution": "2K", "safety_tolerance": "2"}},
    "nano-banana-pro": {"path": "fal-ai/nano-banana-pro", "price": 0.15, "seed": True,
                        "body": {"aspect_ratio": "9:16", "resolution": "2K", "safety_tolerance": "2"}},
    "gpt-image-2": {"path": "openai/gpt-image-2", "price": 0.07, "px": True,  # est. (per token, medium quality)
                    "body": {"quality": "medium", "enable_safety_checker": True}},
    "flux-3": {"path": "blackforestlabs/flux-3/text-to-image", "price": 0.096,  # est. (~$0.048 per megapixel)
               "body": {"aspect_ratio": "9:16", "resolution": "2k", "safety_tolerance": 2}},
    "seedream": {"path": "bytedance/seedream/v5/pro/text-to-image", "price": 0.0675, "px": True,
                 "body": {"enable_safety_checker": True}},
}
DEFAULT_FAL_MODEL = "seedream"
CLEARED_FAL_MODELS: tuple[str, ...] = ()  # models whose licence was read and is fine for a monetized channel (none yet)
PRICE = {"fal": FAL_MODELS[DEFAULT_FAL_MODEL]["price"], "modal": 0.009, "placeholder": 0.0}  # estimated USD per picture
REF_PROVIDERS = ("fal", "placeholder")  # can make a picture from reference portraits (same faces)
REF_PRICE = {"fal": 0.063, "placeholder": 0.0}  # estimated USD per picture made from references (fal: ~$0.03 per MP)
MAX_REFS = 3  # reference portraits per picture
REF_SIDE = 768  # long side of a reference portrait sent to the provider (a smaller request, enough for a face)
FAL_RUN = "https://fal.run/"
FAL_EDIT_URL = "https://fal.run/fal-ai/qwen-image-edit-2511"
MODAL_APP, MODAL_CLS, MODAL_STEPS = "qwen21-uc", "Qwen21UC", 25
TIMEOUT = 240.0  # a cold Modal start takes ~70 s
DEFAULT_STYLE = "photorealistic, natural light, sharp focus, vertical 9:16 composition, no text, no watermark"
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


class ImageError(RuntimeError):
    pass


def fal_model() -> str:
    """The fal model alias picked in Settings (the default when unset or unknown)."""
    m = config.env("FAL_IMAGE_MODEL", DEFAULT_FAL_MODEL).lower()
    return m if m in FAL_MODELS else DEFAULT_FAL_MODEL


def base(name: str) -> str:
    """The provider of a provider name: `fal:flux-dev` → `fal`."""
    return name.split(":", 1)[0]


def _model_of(name: str) -> str:
    """The fal model alias of a provider name (the default for plain `fal` and for an unknown alias)."""
    m = name.split(":", 1)[1] if ":" in name else DEFAULT_FAL_MODEL
    return m if m in FAL_MODELS else DEFAULT_FAL_MODEL


def provider() -> str:
    """The provider name pictures are made with now: `fal` (default model), `fal:<model>`, `modal`, `placeholder`."""
    p = config.env("IMAGE_PROVIDER", DEFAULT_PROVIDER).lower()
    if p not in PROVIDERS:
        p = DEFAULT_PROVIDER
    return f"fal:{fal_model()}" if p == "fal" and fal_model() != DEFAULT_FAL_MODEL else p


def style() -> str:
    """Global picture style added to every scene prompt (Settings → Image style)."""
    return config.env("IMAGE_STYLE", DEFAULT_STYLE)


def needs_review(name: str | None = None) -> bool:
    name = name or provider()
    return base(name) in REVIEW_PROVIDERS or (base(name) == "fal" and _model_of(name) not in CLEARED_FAL_MODELS)


def check_ready(name: str | None = None) -> None:
    """ValueError (translated) when the chosen provider can't generate yet, so the app says so before any work."""
    name = base(name or provider())
    if name == "fal" and not config.env("FAL_KEY"):
        raise ValueError(tr("Add your fal key in Settings → Image provider (or choose the Placeholder provider to "
                            "try the flow)"))
    if name == "modal":
        try:
            import modal  # noqa: F401
        except ImportError:
            raise ValueError(tr("The Modal provider needs the `modal` Python package and a Modal login: it runs from "
                                "the dev engine or the server, not the packaged app")) from None


def cost(n: int, name: str | None = None, refs: bool = False) -> float:
    name = name or provider()
    one = REF_PRICE.get(base(name), PRICE[base(name)]) if refs else PRICE[base(name)]
    if base(name) == "fal" and not refs:
        one = FAL_MODELS[_model_of(name)]["price"]
    return round(n * one, 3)


def key(prompt: str, seed: int = 0, name: str | None = None, refs: list[str] | None = None) -> str:
    """Cache key of one picture: a new prompt, seed, provider, size or reference portrait (`refs`: their keys) is a
    new picture."""
    raw = f"{name or provider()}|{WIDTH}x{HEIGHT}|{seed}|{prompt}" + (f"|refs:{','.join(refs)}" if refs else "")
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


def _data_uri(path: Path) -> str:
    """A reference portrait as a small JPEG data URI (fal reads data URIs as file inputs)."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((REF_SIDE, REF_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _fal(prompt: str, seed: int, refs: list[Path] | None = None, model: str = DEFAULT_FAL_MODEL) -> bytes:
    if refs:  # reference portraits always go to the edit model, whatever model is picked for the text-only scenes
        url = FAL_EDIT_URL
        body = {"prompt": prompt, "image_size": {"width": WIDTH, "height": HEIGHT}, "num_images": 1, "seed": seed,
                "output_format": "png", "enable_safety_checker": True,
                "image_urls": [_data_uri(f) for f in refs[:MAX_REFS]]}
    else:
        spec = FAL_MODELS[model]
        url = FAL_RUN + spec["path"]
        body = {"prompt": prompt, "num_images": 1, "output_format": "png", **spec["body"]}
        if spec.get("px"):
            body["image_size"] = {"width": WIDTH, "height": HEIGHT}
        if spec.get("seed"):
            body["seed"] = seed
    r = _http("POST", url, headers={"Authorization": f"Key {config.env('FAL_KEY')}"}, json=body)
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


def _placeholder(prompt: str, seed: int, refs: list[Path] | None = None) -> bytes:
    """A vertical gradient with the prompt written on it: the picture is obviously not real, and two scenes differ.
    With reference portraits, a small copy of each is pasted at the top, to show which ones the scene was made from."""
    top, bottom = _TINTS[int(hashlib.sha1(f"{seed}|{prompt}".encode()).hexdigest(), 16) % len(_TINTS)]
    col = Image.linear_gradient("L").resize((WIDTH, HEIGHT))
    img = Image.composite(Image.new("RGB", (WIDTH, HEIGHT), bottom), Image.new("RGB", (WIDTH, HEIGHT), top), col)
    d = ImageDraw.Draw(img)
    f = _font(FONT_BOLD, 54)
    y = HEIGHT // 2 - 260
    for ln in textwrap.wrap(prompt, 34)[:9]:
        d.text((70, y), ln, font=f, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
        y += 70
    for i, f in enumerate((refs or [])[:MAX_REFS]):
        thumb = Image.open(f).convert("RGB")
        thumb.thumbnail((240, 240))
        img.paste(thumb, (70 + i * 270, 90))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def generate(prompt: str, seed: int = 0, name: str | None = None, refs: list[Path] | None = None) -> bytes:
    """One picture (image bytes) for `prompt`, made from the reference portraits `refs` when given (only a provider
    of REF_PROVIDERS can). ImageError (translated) on failure."""
    name = name or provider()
    kind = base(name)
    if refs:
        if kind not in REF_PROVIDERS:
            raise ImageError(tr("This image provider cannot make a picture from reference portraits"))
        return {"fal": _fal, "placeholder": _placeholder}[kind](prompt, seed, refs)
    if kind == "fal":
        return _fal(prompt, seed, None, _model_of(name))
    return {"modal": _modal, "placeholder": _placeholder}[kind](prompt, seed)


def make(prompt: str, seed: int, folder: Path, name: str | None = None,
         refs: list[tuple[str, Path]] | None = None) -> tuple[Path, bool]:
    """The picture for `prompt` in `folder`: the cached file when there is one, else a new one. (path, was_new).
    `refs`: (key, file) of the reference portraits the picture is made from (their keys are part of its own key)."""
    name = name or provider()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{key(prompt, seed, name, [k for k, _ in refs or []])}.png"
    if path.is_file() and path.stat().st_size:
        return path, False
    data = generate(prompt, seed, name, [f for _, f in refs]) if refs else generate(prompt, seed, name)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # not an image (an error page, an empty reply)
        raise ImageError(tr("The provider did not return a picture")) from e
    tmp = path.with_suffix(".tmp")
    img.convert("RGB").save(tmp, "PNG")
    tmp.replace(path)
    return path, True
