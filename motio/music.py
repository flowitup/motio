"""Background-music library: tracks added by hand, plus the trending sounds of TikTok's Commercial Music Library.

Why only the Commercial Music Library: a sound that is trending on TikTok is, most of the time, a commercial recording
that TikTok may play inside the app but nobody may copy out of it. Motio posts to TikTok, YouTube Shorts, Facebook Reels
and X, so a copied hit would be claimed by Content ID there (and a claim costs the video its revenue). TikTok's own
Creative Center chart has no public list either: its API answers "no permission" to a request without the page's
signature, and Motio does not forge that. So trending sounds come from a licensed data API (`TIKTOK_MUSIC_API_KEY`,
`TIKTOK_MUSIC_TEAM_ID`; the tracks of the Commercial Music Library that TikTok pre-cleared for organic posts and ads),
and every track carries a license that tells what it may be used for:

- `own` / `licensed` / `cc`: the owner made it, bought it, or it is Creative Commons: usable on every platform.
- `tiktok_cml`: pre-cleared by TikTok. Its terms outside TikTok are not checked, so a video that uses it is never sent
  to Postiz without a person approving it first (`needs_review`).
- `unknown`: nothing known, the same gate.

A video picks a track in `meta.music` ({"id", "volume"}) or from its channel (`music_id`); the render lays it under the
voice, ducked while the voice speaks (`render._compose`). A French dub keeps the original video's music, so it
takes none.
"""
import hashlib
import re
import time
from pathlib import Path

import httpx

from . import config, db, qa
from .i18n import tr

API_URL = "https://api.bundle.social/api/v1/misc/tiktok/cml/trending-list"  # not run against the live service yet
EXT = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac")
MAX_BYTES = 100 * 1024**2
MIN_SECONDS = 8.0
LICENSES = ("own", "licensed", "cc", "tiktok_cml", "unknown")
OPEN = ("own", "licensed", "cc")  # nothing to check before posting anywhere
WINDOWS = ("1DAY", "7DAY", "30DAY")
DEFAULT_GENRE, DEFAULT_WINDOW, DEFAULT_LIMIT = "POP", "7DAY", 30
DEFAULT_VOLUME, MIN_VOLUME, MAX_VOLUME = 0.25, 0.05, 0.6
TIMEOUT = 40
CML_NOTE = ("TikTok Commercial Music Library: pre-cleared by TikTok for organic posts and ads. Its terms for YouTube, "
            "Facebook and X are not checked.")
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport
_GENRE = re.compile(r"^[A-Z0-9][A-Z0-9 _/&-]{0,29}$")


def folder() -> Path:
    return config.DATA / "music"


def usable_on(license: str) -> str:
    """"all" · "tiktok" (pre-cleared there only) · "none" (nothing known)."""
    return "all" if license in OPEN else "tiktok" if license == "tiktok_cml" else "none"


def view(row: dict) -> dict:
    """A track for the app."""
    f = row.get("file") or ""
    return {"id": row["id"], "title": row["title"] or "", "artist": row["artist"] or "", "source": row["source"],
            "link": row["link"] or "", "genre": row["genre"] or "", "rank": row["rank"], "duration": row["duration"],
            "license": row["license"], "usable_on": usable_on(row["license"]), "note": row["note"] or "",
            "audio": f if f and (config.DATA / f).is_file() else None,  # under /media/
            "trending_at": row["trending_at"], "added_at": row["added_at"]}


def listing() -> dict:
    return {"tracks": [view(r) for r in db.list_music()], "licenses": list(LICENSES), "fetch": fetch_ready(),
            "windows": list(WINDOWS), "default_genre": DEFAULT_GENRE, "default_window": DEFAULT_WINDOW}


def get(mid: int) -> dict:
    row = db.get_music(mid)
    if not row:
        raise LookupError(tr("Track #{id} not found", id=mid))
    return row


def _clean(title: str, artist: str, license: str, note: str) -> dict:
    title, artist = " ".join(str(title or "").split())[:140], " ".join(str(artist or "").split())[:100]
    if license not in LICENSES:
        raise ValueError(tr("License must be one of {choices}", choices=", ".join(LICENSES)))
    return {"title": title, "artist": artist, "license": license, "note": str(note or "").strip()[:400]}


def _probe(path: Path) -> float:
    """Length in seconds of an audio file; ValueError when it is not audio or too short to lay under a voice."""
    try:
        info = qa.probe(path)
    except RuntimeError as e:
        raise ValueError(tr("This audio file cannot be read: {error}", error=str(e)[:160])) from e
    if not info["audio"]:
        raise ValueError(tr("This file has no audio"))
    if info["duration"] < MIN_SECONDS:
        raise ValueError(tr("This track is too short to use (under {n} s)", n=int(MIN_SECONDS)))
    return round(info["duration"], 1)


def save_upload(name: str, stream, title: str = "", artist: str = "", license: str = "unknown", note: str = "") -> dict:
    """Keep an audio file the owner picked. The same bytes added twice are one track (its license is updated)."""
    fields = _clean(title, artist, license, note)
    base = Path(name or "track.mp3").name
    ext = Path(base).suffix.lower()
    if ext not in EXT:
        raise ValueError(tr("Only audio files are accepted: {types}", types=", ".join(EXT)))
    fields["title"] = fields["title"] or Path(base).stem[:140]
    folder().mkdir(parents=True, exist_ok=True)
    raw = folder() / f".upload-{time.time_ns()}{ext}"
    digest, size = hashlib.sha256(), 0
    try:
        with raw.open("wb") as f:
            while chunk := stream.read(1 << 20):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError(tr("File too large (max {n} MB)", n=MAX_BYTES >> 20))
                digest.update(chunk)
                f.write(chunk)
        uid = digest.hexdigest()[:24]
        duration = _probe(raw)
        dest = folder() / f"{uid}{ext}"
        raw.replace(dest)
    finally:
        raw.unlink(missing_ok=True)
    rel = dest.relative_to(config.DATA).as_posix()
    have = db.find_music("upload", uid)
    mid = db.save_music(have["id"] if have else None, source="upload", ext_id=uid, file=rel, duration=duration,
                        **fields)
    return view(db.get_music(mid))


def update(mid: int, data: dict) -> dict:
    row = get(mid)
    f = _clean(data.get("title", row["title"]), data.get("artist", row["artist"]),
               data.get("license", row["license"]), data.get("note", row["note"]))
    if not f["title"]:
        raise ValueError(tr("The track needs a title"))
    db.save_music(mid, **f)
    return view(get(mid))


def delete(mid: int) -> None:
    row = get(mid)
    shared = [r for r in db.list_music() if r["id"] != mid and r["file"] == row["file"]]
    if row["file"] and not shared:
        (config.DATA / row["file"]).unlink(missing_ok=True)
    db.delete_music(mid)


# ---------- trending sounds (TikTok Commercial Music Library, through a licensed data API) ----------
def fetch_ready() -> bool:
    return bool(config.env("TIKTOK_MUSIC_API_KEY") and config.env("TIKTOK_MUSIC_TEAM_ID"))


def check_ready() -> None:
    if not fetch_ready():
        raise ValueError(tr("Add your TikTok music API key and team id in Settings → Music to fetch trending sounds. "
                            "Without them you can still add tracks by hand."))


def _http(method: str, url: str, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=True) as c:
            return c.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise RuntimeError(tr("Could not reach the music service: {error}", error=str(e)[:200])) from e


def _clip(item: dict) -> dict:
    """The clip to keep: the whole song first, then the trending part, then the plain preview."""
    for k in ("full_duration_song_clip", "trending_song_clip"):
        c = item.get(k)
        if isinstance(c, dict) and c.get("preview_url"):
            return c
    return {"preview_url": item.get("preview_url"), "duration": item.get("duration"), "song_clip_id": None}


def _download(url: str, dest_stem: Path) -> Path | None:
    """Fetch a preview (https only, size capped, kept only when it is audio). None when it cannot be used."""
    if not str(url or "").startswith("https://"):
        return None
    try:
        r = _http("GET", url)
    except RuntimeError:
        return None
    if r.status_code != 200 or not r.content or len(r.content) > MAX_BYTES:
        return None
    ctype = r.headers.get("content-type", "")
    ext = ".m4a" if "mp4" in ctype or "aac" in ctype else ".ogg" if "ogg" in ctype else ".wav" if "wav" in ctype \
        else ".mp3"
    out = dest_stem.with_suffix(ext)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    try:
        _probe(out)
    except ValueError:
        out.unlink(missing_ok=True)
        return None
    return out


def refresh(genre: str = DEFAULT_GENRE, window: str = DEFAULT_WINDOW, limit: int = DEFAULT_LIMIT) -> dict:
    """Pull the trending Commercial Music Library tracks of a genre into the library. A track keeps one row (its clip
    id), so a second pull only moves ranks. Returns {"added", "updated", "listed", "no_audio"}."""
    check_ready()
    genre = " ".join(str(genre or DEFAULT_GENRE).upper().split())
    if not _GENRE.match(genre):
        raise ValueError(tr("Unknown genre: {genre}", genre=genre))
    if window not in WINDOWS:
        raise ValueError(tr("Period must be one of {choices}", choices=", ".join(WINDOWS)))
    r = _http("GET", API_URL, headers={"x-api-key": config.env("TIKTOK_MUSIC_API_KEY")},
              params={"teamId": config.env("TIKTOK_MUSIC_TEAM_ID"), "genre": genre, "dateRange": window})
    if r.status_code in (401, 403):
        raise RuntimeError(tr("The music service refused the key: check the API key and team id in Settings"))
    if r.status_code != 200:
        raise RuntimeError(tr("The music service answered {status}", status=r.status_code))
    try:
        items = r.json()
        items = items.get("data", items) if isinstance(items, dict) else items
        items = [i for i in items if isinstance(i, dict)]
    except (ValueError, AttributeError, TypeError) as e:
        raise RuntimeError(tr("The music service sent something Motio cannot read")) from e
    now, seen = time.time(), set()
    added = updated = no_audio = 0
    for n, item in enumerate(items[: max(1, int(limit))], 1):
        title = " ".join(str(item.get("commercial_music_name") or "").split())[:140]
        artist = " ".join(str(item.get("artist") or "").split())[:100]
        if not title:
            continue
        clip = _clip(item)
        ext_id = str(clip.get("song_clip_id") or hashlib.sha1(f"{title}|{artist}".encode()).hexdigest()[:16])
        try:
            rank = int(item.get("rank_position") or n)
        except (TypeError, ValueError):
            rank = n
        have = db.find_music("tiktok_cml", ext_id)
        fields = {"title": title, "artist": artist, "genre": genre, "region": "", "rank": rank, "trending_at": now,
                  "duration": clip.get("duration") or item.get("duration") or None}
        if not (have and have["file"] and (config.DATA / have["file"]).is_file()):
            got = _download(clip.get("preview_url"), folder() / f"cml-{hashlib.sha1(ext_id.encode()).hexdigest()[:16]}")
            if got:
                fields["file"] = got.relative_to(config.DATA).as_posix()
                fields["duration"] = _probe(got)
            else:
                no_audio += 1
        if have:
            db.save_music(have["id"], **fields)
            updated += 1
        else:
            db.save_music(None, source="tiktok_cml", ext_id=ext_id, license="tiktok_cml", note=CML_NOTE, **fields)
            added += 1
        seen.add(ext_id)
    for row in db.list_music():  # ranks of this genre that are no longer on the chart
        if row["source"] == "tiktok_cml" and row["genre"] == genre and row["ext_id"] not in seen:
            db.save_music(row["id"], rank=None, trending_at=None)
    return {"added": added, "updated": updated, "listed": len(seen), "no_audio": no_audio}


# ---------- a video's music ----------
def clamp_volume(v) -> float:
    try:
        return round(min(MAX_VOLUME, max(MIN_VOLUME, float(v))), 2)
    except (TypeError, ValueError):
        return DEFAULT_VOLUME


def choice(proj: dict, ch: dict | None) -> tuple[dict | None, float]:
    """(track row, volume) a project uses: its own pick (`meta.music`, id 0 / None = no music), else the channel's.
    A track whose file is gone is no music (the render goes on without it)."""
    if proj.get("mode") == "dub":
        return None, DEFAULT_VOLUME
    own = proj["meta"].get("music")
    if isinstance(own, dict):
        mid, vol = own.get("id"), own.get("volume")
    else:
        mid, vol = (ch or {}).get("music_id"), (ch or {}).get("music_volume")
    row = db.get_music(int(mid)) if mid else None
    if not row or not row["file"] or not (config.DATA / row["file"]).is_file():
        return None, DEFAULT_VOLUME
    return row, clamp_volume(vol if vol is not None else DEFAULT_VOLUME)


def for_render(proj: dict, ch: dict | None) -> dict | None:
    """What render.render needs: {"path", "volume"}, or None."""
    row, vol = choice(proj, ch)
    return {"path": str(config.DATA / row["file"]), "volume": vol} if row else None


def needs_review(proj: dict, ch: dict | None = None) -> bool:
    """A track that is not known to be free for every platform: a person approves the video before Postiz gets it."""
    row, _ = choice(proj, ch)
    return bool(row and row["license"] not in OPEN)


def credit(proj: dict, ch: dict | None = None) -> str:
    """One line for sources.txt; empty when the video has no music."""
    row, _ = choice(proj, ch)
    if not row:
        return ""
    by = f" – {row['artist']}" if row["artist"] else ""
    return f"Music: {row['title']}{by} [{row['license']}]" + (f" {row['link']}" if row["link"] else "")


def set_for_project(pid: int, track_id: int | None, volume=None) -> dict:
    """Save a video's pick (None = no music, even when its channel has one). Re-rendering is the caller's job."""
    proj = db.get_project(pid)
    if not proj:
        raise LookupError(tr("Project #{id} not found", id=pid))
    if proj.get("mode") == "dub":
        raise ValueError(tr("A French dub keeps the original video's music: it takes no other track"))
    if track_id:
        row = get(int(track_id))
        if not row["file"] or not (config.DATA / row["file"]).is_file():
            raise ValueError(tr("This track has no audio to mix: add the file first"))
    pick = {"id": int(track_id) if track_id else None, "volume": clamp_volume(volume)}
    db.update_project(pid, meta={"music": pick})
    return pick


def state(proj: dict, ch: dict | None) -> dict:
    """What the project page shows: the track in use (own pick or the channel's), and whether the gate is forced."""
    if proj.get("mode") == "dub":
        return {"supported": False}
    row, vol = choice(proj, ch)
    own = isinstance(proj["meta"].get("music"), dict)
    return {"supported": True, "id": row["id"] if row else None, "volume": vol, "from": ("video" if own else "channel")
            if row else None, "title": row["title"] if row else "", "artist": row["artist"] if row else "",
            "license": row["license"] if row else "", "needs_review": needs_review(proj, ch)}
