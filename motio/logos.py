"""The owner's own logos (Settings → Logos), used to cover a box drawn on a project's source (`motio/masks.py`).

Each logo is stored once as an RGBA PNG, `logos/<id>.png` in the data folder (id = start of its sha256, so the same
picture uploaded twice is one logo), with its name in `<id>.json`. Pictures are opened with Pillow, so only real images
are kept, and big ones are shrunk to MAX_SIDE."""
import hashlib
import io
import json
import re
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError

from . import config
from .i18n import tr

MAX_BYTES = 10 * 1024**2
MAX_SIDE = 1024
MAX_LOGOS = 20
_ID = re.compile(r"[0-9a-f]{16}")


def folder() -> Path:
    return config.DATA / "logos"


def path(lid: str | None) -> Path | None:
    """The logo's PNG, None when there is no such logo."""
    if not lid or not _ID.fullmatch(lid):
        return None
    p = folder() / f"{lid}.png"
    return p if p.is_file() else None


def _view(lid: str) -> dict:
    try:
        name = json.loads((folder() / f"{lid}.json").read_text(encoding="utf-8")).get("name") or ""
    except (OSError, ValueError):
        name = ""
    with Image.open(folder() / f"{lid}.png") as im:
        w, h = im.size
    return {"id": lid, "name": name or lid, "media": f"logos/{lid}.png", "width": w, "height": h}


def list_all() -> list[dict]:
    """Every logo, oldest first."""
    files = sorted(folder().glob("*.png"), key=lambda p: p.stat().st_mtime) if folder().is_dir() else []
    return [_view(p.stem) for p in files if _ID.fullmatch(p.stem)]


def add(filename: str, stream: BinaryIO) -> dict:
    """Keep an uploaded picture as a logo. ValueError (in the UI language) when it is not a usable image."""
    data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(tr("The logo is bigger than {mb} MB", mb=MAX_BYTES // 1024**2))
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            pic = im.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError(tr("This file is not a picture (use PNG, JPG or WebP)")) from None
    pic.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    if pic.getbbox() is None:
        raise ValueError(tr("The logo is fully transparent"))
    out = io.BytesIO()
    pic.save(out, "PNG")
    lid = hashlib.sha256(out.getvalue()).hexdigest()[:16]
    if not path(lid):
        if len(list_all()) >= MAX_LOGOS:
            raise ValueError(tr("At most {n} logos: delete one first", n=MAX_LOGOS))
        folder().mkdir(parents=True, exist_ok=True)
        (folder() / f"{lid}.png").write_bytes(out.getvalue())
    name = " ".join(Path(filename or "").stem.split())[:60]
    (folder() / f"{lid}.json").write_text(json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8")
    return _view(lid)


def remove(lid: str) -> None:
    """Delete a logo. Boxes that used it are only blurred from then on. LookupError when there is no such logo."""
    p = path(lid)
    if not p:
        raise LookupError(tr("Logo not found"))
    p.unlink()
    (folder() / f"{lid}.json").unlink(missing_ok=True)
