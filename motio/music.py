"""Music library: ideas from TikTok's trending sounds, plus tracks that can go under a video's voice.

Two kinds of track:

- A **sound idea** (`tiktok_cml`): a trending track of TikTok's Commercial Music Library, listed with its rank, genre
  and the trending cut (the short part posts use, not the whole song) to listen to. Motio never puts it in a video:
  the owner adds the sound inside the TikTok app when posting there (the official way, the sound stays TikTok's).
  A trending sound is, most of the time, a commercial recording that TikTok may play only inside its app, so a copy
  in the video file would get a Content ID claim on YouTube, Facebook and X. The chart comes from a licensed data API
  (`TIKTOK_MUSIC_API_KEY`, `TIKTOK_MUSIC_TEAM_ID`): TikTok's own Creative Center chart answers "no permission" to a
  request without the page's signature, and Motio does not forge that. That chart has no country filter, so for a
  country (France, the US…) a second source reads Apple Music's public most-played chart of that country with its
  30 s previews (`country_chart`): what people there listen to, not TikTok's own ranking. A third source reads the
  songs used by the videos of a TikTok hashtag (`tiktok_tag`, `refresh_tag`): a real browser on this computer opens
  the hashtag page and keeps the `item_list` answers the page itself loads (`tiktokweb.py`; the page does TikTok's
  request signing, Motio does not), so it shows the country of this computer's connection. Same rules: ideas only,
  nothing is downloaded.
- A **track to mix**: an audio file the owner adds (`own` / `licensed` / `cc`: usable on every platform; `unknown`:
  the video waits for approval before Postiz gets it). A video picks one in `meta.music` ({"id", "volume"}) or from
  its channel (`music_id`); the render lays it under the voice, ducked while the voice speaks (`render._compose`).
  A French dub keeps the original video's music, so it takes none.
"""
import hashlib
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from . import config, db, qa, tiktokweb
from .i18n import tr

API_URL = "https://api.bundle.social/api/v1/misc/tiktok/cml/trending-list"  # not run against the live service yet
EXT = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac")
MAX_BYTES = 100 * 1024**2
MIN_SECONDS = 8.0
LICENSES = ("own", "licensed", "cc", "tiktok_cml", "unknown")
OPEN = ("own", "licensed", "cc")  # nothing to check before posting anywhere
IDEA = "tiktok_cml"  # a sound idea: added in the TikTok app when posting, never mixed into a video
CHART = "country_chart"  # source of the ideas read from a country's most-played chart (Apple Music)
TAG = "tiktok_tag"  # source of the ideas read from the videos of a TikTok hashtag (what its videos use)
TRENDING, POPULAR = "7DAY", "30DAY"  # the service ranks over 1DAY / 7DAY / 30DAY; there is no all-time chart
# TikTok's genre tags, as the service's API lists them
GENRES = ("POP", "ROCK", "LATIN", "METAL", "ELECTRONIC", "HIP_HOP/RAP", "ALTERNATIVE/INDIE", "R&B/SOUL", "COUNTRY",
          "CLASSICAL", "JAZZ", "CHILDHOOD", "ALTERNATIVE_HIP_HOP", "AMBIENT", "BOSSA_NOVA", "BRAZILIAN_FUNK_STYLE",
          "CHILL_BEATS", "CHILLOUT", "CHINESE_POP", "CHRISTIAN_MUSIC", "COUNTRY_POP", "DANCE_POP", "DISCO", "DJ",
          "DRUM&BASS", "DUBSTEP", "EDM", "FUNK", "HOUSE", "INDIE_POP", "J-POP", "K-POP", "LATIN_POP", "LO-FI",
          "OLD_SCHOOL", "PUNK", "RUSSIAN_POP", "SOUL", "SYNTH_POP", "SOUNDTRACK", "TECHNO", "TEEN_POP")
DEFAULT_GENRE, DEFAULT_LIMIT = "POP", 30
# countries of the most-played chart (Apple's public feed): code -> name; the TikTok chart has no country filter
REGIONS = {"FR": "France", "US": "United States", "GB": "United Kingdom", "DE": "Germany", "ES": "Spain",
           "IT": "Italy", "BE": "Belgium", "CA": "Canada", "BR": "Brazil", "VN": "Vietnam"}
DEFAULT_REGION = "FR"
CHART_URL = "https://rss.marketingtools.apple.com/api/v2/{cc}/music/most-played/{n}/songs.json"
LOOKUP_URL = "https://itunes.apple.com/lookup"
DEFAULT_VOLUME, MIN_VOLUME, MAX_VOLUME = 0.25, 0.05, 0.6
TIMEOUT = 40
CML_NOTE = ("Idea from TikTok's Commercial Music Library (pre-cleared by TikTok for posts and ads on TikTok): the "
            "trending cut, not the whole song. Add the sound in the TikTok app when you post. Motio does not put it in "
            "the video.")
CHART_NOTE = ("Idea from a country's most-played chart (Apple Music): a 30 s preview of a commercial recording, to "
              "listen to. Find the sound in the TikTok app when you post. Motio does not put it in the video.")
TAG_NOTE = ("Idea from the videos of a TikTok hashtag: a song used in several of its top videos. Find it in the TikTok "
            "app when you post (the link opens its sound page). Motio does not put it in the video.")
FIND_URL = "https://www.tiktok.com/search?q="
MUSIC_URL = "https://www.tiktok.com/music/"
_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


def folder() -> Path:
    return config.DATA / "music"


def usable_on(license: str) -> str:
    """"all" · "tiktok" (an idea: added in the TikTok app) · "none" (nothing known)."""
    return "all" if license in OPEN else "tiktok" if license == "tiktok_cml" else "none"


def view(row: dict) -> dict:
    """A track for the app."""
    f = row.get("file") or ""
    name = " ".join(x for x in (row["title"], row["artist"]) if x)
    page = row["link"] if row["source"] == TAG and str(row["link"] or "").startswith(MUSIC_URL) else ""
    find = page or (FIND_URL + quote(name) if row["license"] == IDEA else "")
    return {"id": row["id"], "title": row["title"] or "", "artist": row["artist"] or "", "source": row["source"],
            "link": row["link"] or "", "genre": row["genre"] or "", "region": row["region"] or "", "rank": row["rank"],
            "uses": row["uses"], "plays": row["plays"],
            "rank_month": row["rank_month"], "duration": row["duration"],
            "license": row["license"], "usable_on": usable_on(row["license"]), "note": row["note"] or "",
            "audio": f if f and (config.DATA / f).is_file() else None,  # under /media/
            "mixable": row["license"] != IDEA and bool(f and (config.DATA / f).is_file()), "find": find,
            "trending_at": row["trending_at"], "added_at": row["added_at"]}


def listing() -> dict:
    return {"tracks": [view(r) for r in db.list_music()], "licenses": list(LICENSES), "fetch": fetch_ready(),
            "genres": list(GENRES), "default_genre": DEFAULT_GENRE,
            "regions": REGIONS, "default_region": DEFAULT_REGION, "browser": tiktokweb.available()}


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
    """The clip to keep: the trending part (the cut people use in their posts), then the whole song, then the plain
    preview."""
    for k in ("trending_song_clip", "full_duration_song_clip"):
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


def _chart(genre: str, window: str) -> list[dict]:
    """One chart of the data service: [{"title", "artist", "rank", "ext_id", "clip", "duration"}] in rank order."""
    r = _http("GET", API_URL, headers={"x-api-key": config.env("TIKTOK_MUSIC_API_KEY")},
              params={"teamId": config.env("TIKTOK_MUSIC_TEAM_ID"), "genre": genre, "dateRange": window})
    if r.status_code in (401, 403):
        raise RuntimeError(tr("The music service refused the key: check the API key and team id in Settings"))
    if r.status_code == 400 and "Tiktok account" in r.text:  # the service reads the chart through a TikTok account
        raise RuntimeError(tr("The music service needs a TikTok account connected to this team: connect one in its "
                              "dashboard, then fetch again"))
    if r.status_code != 200:
        raise RuntimeError(tr("The music service answered {status}", status=r.status_code))
    try:
        items = r.json()
        items = items.get("data", items) if isinstance(items, dict) else items
        items = [i for i in items if isinstance(i, dict)]
    except (ValueError, AttributeError, TypeError) as e:
        raise RuntimeError(tr("The music service sent something Motio cannot read")) from e
    out = []
    for n, item in enumerate(items, 1):
        title = " ".join(str(item.get("commercial_music_name") or "").split())[:140]
        if not title:
            continue
        artist = " ".join(str(item.get("artist") or "").split())[:100]
        clip = _clip(item)
        clip_id = str(clip.get("song_clip_id") or hashlib.sha1(f"{title}|{artist}".encode()).hexdigest()[:16])
        try:
            rank = int(item.get("rank_position") or n)
        except (TypeError, ValueError):
            rank = n
        out.append({"title": title, "artist": artist, "rank": rank, "ext_id": f"{genre}:{clip_id}", "clip": clip,
                    "duration": clip.get("duration") or item.get("duration") or None})
    return out


def refresh(genre: str = DEFAULT_GENRE, limit: int = DEFAULT_LIMIT) -> dict:
    """Pull the Commercial Music Library charts of one genre (a "tag"): the trending cuts of the last 7 days and the
    most popular of the last 30 days (the longest range the service has: it has no all-time chart). A track of a genre
    keeps one row, with its rank on each chart; a track that left both charts is dropped. Returns {"added", "updated",
    "listed", "no_audio", "removed"}."""
    check_ready()
    genre = " ".join(str(genre or DEFAULT_GENRE).upper().split())
    if genre not in GENRES:
        raise ValueError(tr("Unknown genre: {genre}", genre=genre))
    top = max(1, int(limit))
    charts = {col: _chart(genre, window)[:top] for col, window in (("rank", TRENDING), ("rank_month", POPULAR))}
    now = time.time()
    rows: dict[str, dict] = {}  # ext_id -> fields, ranks of both charts
    for col, chart in charts.items():
        for t in chart:
            f = rows.setdefault(t["ext_id"], {"title": t["title"], "artist": t["artist"], "clip": t["clip"],
                                              "duration": t["duration"], "rank": None, "rank_month": None})
            f[col] = t["rank"]
    added = updated = no_audio = 0
    for ext_id, f in rows.items():
        clip = f.pop("clip")
        have = db.find_music("tiktok_cml", ext_id)
        fields = {**f, "genre": genre, "region": "", "trending_at": now}
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
    removed = 0
    for row in db.list_music():  # ideas of this genre that are on neither chart any more
        if row["source"] == "tiktok_cml" and row["genre"] == genre and row["ext_id"] not in rows:
            if row["file"]:
                (config.DATA / row["file"]).unlink(missing_ok=True)
            db.delete_music(row["id"])
            removed += 1
    return {"added": added, "updated": updated, "listed": len(rows), "no_audio": no_audio, "removed": removed}


def refresh_country(region: str = DEFAULT_REGION, limit: int = DEFAULT_LIMIT) -> dict:
    """Pull a country's most-played songs (Apple Music's public chart, no key) as sound ideas, each with its 30 s
    preview. This is what people listen to in that country, not TikTok's own chart (which has no country filter). A
    song that left the chart is dropped. Returns {"added", "updated", "listed", "no_audio", "removed"}."""
    region = str(region or DEFAULT_REGION).upper().strip()
    if region not in REGIONS:
        raise ValueError(tr("Unknown country: {region}", region=region))
    top = max(1, min(int(limit), 100))
    size = next(n for n in (10, 25, 50, 100) if n >= top)  # the sizes Apple's feed offers
    url = CHART_URL.format(cc=region.lower(), n=size)
    r = _http("GET", url)
    if r.status_code in (502, 503, 504):  # the feed's edge fails now and then on a cold request: once more
        r = _http("GET", url)
    if r.status_code != 200:
        raise RuntimeError(tr("The music chart answered {status}", status=r.status_code))
    try:
        results = [i for i in r.json()["feed"]["results"] if isinstance(i, dict) and i.get("id")][:top]
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(tr("The music chart sent something Motio cannot read")) from e
    previews: dict[str, dict] = {}
    if results:
        lk = _http("GET", LOOKUP_URL, params={"id": ",".join(str(i["id"]) for i in results), "country": region.lower()})
        if lk.status_code == 200:
            try:
                previews = {str(x.get("trackId")): x for x in lk.json().get("results", []) if isinstance(x, dict)}
            except (ValueError, AttributeError):
                previews = {}
    now = time.time()
    added = updated = no_audio = 0
    kept: set[str] = set()
    for n, item in enumerate(results, 1):
        title = " ".join(str(item.get("name") or "").split())[:140]
        if not title:
            continue
        ext_id = f"{region}:{item['id']}"
        kept.add(ext_id)
        have = db.find_music(CHART, ext_id)
        fields = {"title": title, "artist": " ".join(str(item.get("artistName") or "").split())[:100],
                  "link": str(item.get("url") or ""), "genre": "", "region": region, "rank": n, "rank_month": None,
                  "trending_at": now}
        if not (have and have["file"] and (config.DATA / have["file"]).is_file()):
            got = _download(previews.get(str(item["id"]), {}).get("previewUrl"),
                            folder() / f"chart-{hashlib.sha1(ext_id.encode()).hexdigest()[:16]}")
            if got:
                fields["file"] = got.relative_to(config.DATA).as_posix()
                fields["duration"] = _probe(got)
            else:
                no_audio += 1
        if have:
            db.save_music(have["id"], **fields)
            updated += 1
        else:
            db.save_music(None, source=CHART, ext_id=ext_id, license=IDEA, note=CHART_NOTE, **fields)
            added += 1
    removed = 0
    for row in db.list_music():
        if row["source"] == CHART and row["region"] == region and row["ext_id"] not in kept:
            if row["file"]:
                (config.DATA / row["file"]).unlink(missing_ok=True)
            db.delete_music(row["id"])
            removed += 1
    return {"added": added, "updated": updated, "listed": len(kept), "no_audio": no_audio, "removed": removed}


def clean_tag(tag: str) -> str:
    """A hashtag as TikTok writes it in a link: no "#", lower case, letters and digits only (any script)."""
    words = str(tag or "").replace("#", " ").split()
    t = words[0].lower() if len(words) == 1 else ""
    if not t or len(t) > 40 or not all(c.isalnum() or c == "_" for c in t):
        raise ValueError(tr("Type one hashtag, letters and digits only"))
    return t


def tag_sounds(bodies: list, limit: int = DEFAULT_LIMIT) -> tuple[list[dict], int]:
    """The songs used by the videos in what a hashtag page loaded (`item_list` answers): one row per song with how many
    of those videos use it and their plays, most used first. A sound a person recorded themselves ("original sound")
    is not a song and is left out. Returns (rows, number of videos read)."""
    seen: set[str] = set()
    songs: dict[str, dict] = {}
    videos = 0
    for body in bodies:
        for item in (body.get("itemList") or []) if isinstance(body, dict) else []:
            if not isinstance(item, dict) or str(item.get("id")) in seen:
                continue
            seen.add(str(item.get("id")))
            videos += 1
            m = item.get("music")
            if not isinstance(m, dict) or m.get("original") or not m.get("id"):
                continue
            title = " ".join(str(m.get("title") or "").split())[:140]
            if not title:
                continue
            try:
                plays = int((item.get("stats") or {}).get("playCount") or 0)
            except (TypeError, ValueError):
                plays = 0
            artist = " ".join(str(m.get("authorName") or "").split())[:100]
            row = songs.setdefault(str(m["id"]), {"title": title, "artist": artist,
                                                  "duration": m.get("duration") or None, "uses": 0, "plays": 0})
            row["uses"] += 1
            row["plays"] += plays
    rows = sorted(songs.items(), key=lambda kv: (-kv[1]["uses"], -kv[1]["plays"]))[:max(1, int(limit))]
    return [{"id": mid, **r} for mid, r in rows], videos


def refresh_tag(tag: str, limit: int = DEFAULT_LIMIT) -> dict:
    """Open a TikTok hashtag page in a headless browser on this computer and list the songs its videos use (what the
    page shows from this computer's country). A song that is no longer in them is dropped. Ideas only, nothing is
    downloaded. Returns {"added", "updated", "listed", "videos", "removed"}."""
    tag = clean_tag(tag)
    bodies = tiktokweb.collect(f"https://www.tiktok.com/tag/{quote(tag)}", "/api/challenge/item_list")
    rows, videos = tag_sounds(bodies, limit)
    if not videos:
        raise RuntimeError(tr("TikTok showed no videos for #{tag}: the tag may not exist, or TikTok refused the page",
                              tag=tag))
    now = time.time()
    added = updated = 0
    kept: set[str] = set()
    for n, t in enumerate(rows, 1):
        ext_id = f"{tag}:{t['id']}"
        kept.add(ext_id)
        slug = "-".join("".join(c if c.isalnum() else " " for c in t["title"]).split()) or "sound"
        fields = {"title": t["title"], "artist": t["artist"], "genre": tag, "region": "", "rank": n, "rank_month": None,
                  "duration": t["duration"], "uses": t["uses"], "plays": t["plays"], "trending_at": now,
                  "link": f"{MUSIC_URL}{quote(slug)}-{t['id']}"}
        have = db.find_music(TAG, ext_id)
        if have:
            db.save_music(have["id"], **fields)
            updated += 1
        else:
            db.save_music(None, source=TAG, ext_id=ext_id, license=IDEA, note=TAG_NOTE, **fields)
            added += 1
    removed = 0
    for row in db.list_music():
        if row["source"] == TAG and row["genre"] == tag and row["ext_id"] not in kept:
            db.delete_music(row["id"])
            removed += 1
    return {"added": added, "updated": updated, "listed": len(kept), "videos": videos, "removed": removed}


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
    if not row or row["license"] == IDEA or not row["file"] or not (config.DATA / row["file"]).is_file():
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
        if row["license"] == IDEA:
            raise ValueError(tr("This is a sound idea: add it in the TikTok app when you post. Motio does not put it "
                                "in the video"))
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
