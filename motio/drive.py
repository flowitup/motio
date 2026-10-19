"""Google Drive as Motio's main storage, so the machine keeps only what a video in progress needs.

Motio talks to the Drive API itself (httpx, no mount, no extra package). The owner signs in once with Google's device
flow (client ID + secret of their own OAuth client, scope `drive.file`: Motio only sees the files it made). What moves:

- a finished project's heavy files (`projects/<id>/`: final video, 16:9 copy, voice, pictures, clips; anything ≥ 1 MiB),
- the downloaded source videos in `cache/sources/` that no project in progress needs.

A file is uploaded with a resumable session, then its size and md5 are compared with what Drive reports, and only then
is the local copy deleted (unless `DRIVE_KEEP_LOCAL`: Drive is then a backup). `drive_file` (SQLite) remembers where
each one went. Nothing else changes for the rest of the engine: `/media` streams a file from Drive when it is no longer
local, and a project that runs again gets its files back first (`restore_project`, `ensure`).

The SQLite database, `settings.json`, models and small files stay local. Tokens live in `settings.json` like every other
key (`DRIVE_REFRESH_TOKEN`, masked by the API); never in the repo.
"""
import fnmatch
import hashlib
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import httpx

from . import config, db
from .i18n import tr

SCOPE = "https://www.googleapis.com/auth/drive.file"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FIELDS = "id,size,md5Checksum"
CHUNK = 16 * 1024 * 1024  # a multiple of 256 KiB, as the resumable upload wants
MIN_BYTES = 1 << 20  # smaller files (scripts, captions, thumbnails…) stay local: the app reads them all the time
SOURCE_MIN_AGE = 3600  # a source downloaded in the last hour may still be in use
KEEP_HERE = ("final", "bg.mp4")  # restore_project skips what the next render makes again

_transport: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport
_sleep = time.sleep  # tests make it instant
_token = {"value": None, "expires": 0.0}
_token_lock = threading.Lock()
_pending: dict = {}  # a sign-in that waits for the owner: device_code, interval, expires
_about: dict = {"at": 0.0, "data": {}}
_sync: dict = {"running": False, "freed": 0, "error": "", "finished": 0.0}
_sync_lock = threading.Lock()


class DriveError(RuntimeError):
    """Drive refused, or could not be reached, with a message the app shows."""


# ---------- settings ----------
def client_ready() -> bool:
    return bool(config.env("DRIVE_CLIENT_ID") and config.env("DRIVE_CLIENT_SECRET"))


def configured() -> bool:
    """Signed in: files already on Drive can be read back even when the switch is off."""
    return client_ready() and bool(config.env("DRIVE_REFRESH_TOKEN"))


def enabled() -> bool:
    """Switched on and signed in: finished work moves to Drive."""
    return config.flag("DRIVE_ON") and configured()


def keep_local() -> bool:
    return config.flag("DRIVE_KEEP_LOCAL")


def root_name() -> str:
    return (config.env("DRIVE_FOLDER") or "Motio").replace("/", "-").replace("\\", "-").strip() or "Motio"


# ---------- HTTP ----------
def _client(timeout: float = 60) -> httpx.Client:
    return httpx.Client(transport=_transport, timeout=timeout, follow_redirects=True)


def _err(r: httpx.Response) -> str:
    try:
        e = r.json().get("error")
    except ValueError:
        return (r.text or "").strip()[:200] or str(r.status_code)
    if isinstance(e, dict):
        return str(e.get("message") or e.get("status") or r.status_code)[:200]
    return str(r.json().get("error_description") or e or r.status_code)[:200]


def reset_token() -> None:
    with _token_lock:
        _token.update(value=None, expires=0.0)
    _about.update(at=0.0, data={})


def access_token(force: bool = False) -> str:
    with _token_lock:
        if not force and _token["value"] and _token["expires"] > time.time() + 60:
            return _token["value"]
        if not configured():
            raise DriveError(tr("Google Drive is not signed in: add the client ID and secret, then sign in in "
                                "Settings"))
        try:
            with _client(30) as c:
                r = c.post(TOKEN_URL, data={"client_id": config.env("DRIVE_CLIENT_ID"),
                                            "client_secret": config.env("DRIVE_CLIENT_SECRET"),
                                            "refresh_token": config.env("DRIVE_REFRESH_TOKEN"),
                                            "grant_type": "refresh_token"})
        except httpx.HTTPError as e:
            raise DriveError(tr("Could not connect to Google: {error}", error=e)) from e
        if r.status_code != 200:
            raise DriveError(tr("Google refused the saved sign-in ({error}): sign in again in Settings", error=_err(r)))
        j = r.json()
        _token.update(value=j["access_token"], expires=time.time() + int(j.get("expires_in") or 3600))
        return _token["value"]


def _send(method: str, url: str, *, ok: tuple[int, ...] = (200,), headers: dict | None = None, retries: int = 4,
          **kw) -> httpx.Response:
    """One authorised call. Retries a dropped connection, 429 and 5xx with a pause; a 401 gets a fresh token once."""
    refreshed = False
    for attempt in range(retries + 1):
        try:
            with _client() as c:
                r = c.request(method, url, headers={"Authorization": f"Bearer {access_token()}", **(headers or {})},
                              **kw)
        except httpx.HTTPError as e:
            if attempt == retries:
                raise DriveError(tr("Could not connect to Google: {error}", error=e)) from e
            _sleep(2 ** attempt)
            continue
        if r.status_code in ok:
            return r
        if r.status_code == 401 and not refreshed:
            refreshed = True
            access_token(force=True)
            continue
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            _sleep(2 ** attempt)
            continue
        raise DriveError(tr("Google Drive error {status}: {error}", status=r.status_code, error=_err(r)))
    raise DriveError(tr("Google Drive error {status}: {error}", status=0, error="retries"))  # pragma: no cover


# ---------- sign-in (device flow) ----------
def sign_in_start() -> dict:
    """Ask Google for a code. The owner enters it at the returned address, on any device, with the account to use."""
    if not client_ready():
        raise DriveError(tr("Fill in the Google client ID and secret first"))
    try:
        with _client(30) as c:
            r = c.post(DEVICE_URL, data={"client_id": config.env("DRIVE_CLIENT_ID"), "scope": SCOPE})
    except httpx.HTTPError as e:
        raise DriveError(tr("Could not connect to Google: {error}", error=e)) from e
    if r.status_code != 200:
        raise DriveError(tr("Google refused the sign-in ({error})", error=_err(r)))
    j = r.json()
    _pending.clear()
    _pending.update(device_code=j["device_code"], interval=int(j.get("interval") or 5),
                    expires=time.time() + int(j.get("expires_in") or 1800))
    return {"code": j["user_code"], "url": j.get("verification_url") or "https://www.google.com/device",
            "interval": _pending["interval"], "expires_in": int(j.get("expires_in") or 1800)}


def sign_in_poll() -> str:
    """pending | ok | denied | expired. On ok the refresh token is saved in settings.json."""
    from . import settings

    if not _pending:
        return "expired"
    if time.time() > _pending["expires"]:
        _pending.clear()
        return "expired"
    try:
        with _client(30) as c:
            r = c.post(TOKEN_URL, data={"client_id": config.env("DRIVE_CLIENT_ID"),
                                        "client_secret": config.env("DRIVE_CLIENT_SECRET"),
                                        "device_code": _pending["device_code"],
                                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    except httpx.HTTPError as e:
        raise DriveError(tr("Could not connect to Google: {error}", error=e)) from e
    if r.status_code == 200:
        token = r.json().get("refresh_token")
        if not token:
            raise DriveError(tr("Google gave no refresh token: remove Motio at myaccount.google.com/permissions and "
                                "sign in again"))
        settings.update({"DRIVE_REFRESH_TOKEN": token})
        _pending.clear()
        reset_token()
        db.drive_folders_clear()
        return "ok"
    code = ""
    try:
        code = r.json().get("error", "")
    except ValueError:
        pass
    if code in ("authorization_pending", "slow_down"):
        return "pending"
    if code == "access_denied":
        _pending.clear()
        return "denied"
    if code == "expired_token":
        _pending.clear()
        return "expired"
    raise DriveError(tr("Google refused the sign-in ({error})", error=_err(r)))


def sign_out() -> None:
    from . import settings

    settings.update({"DRIVE_REFRESH_TOKEN": None})
    _pending.clear()
    reset_token()
    db.drive_folders_clear()


# ---------- folders ----------
def _q(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def _folder(parts: tuple[str, ...]) -> str:
    """Id of the Drive folder at this path under My Drive, found or created."""
    key = "/".join(parts)
    cached = db.drive_folder_get(key)
    if cached:
        return cached
    parent = _folder(parts[:-1]) if len(parts) > 1 else "root"
    name = parts[-1]
    r = _send("GET", f"{API}/files", params={
        "q": f"name = '{_q(name)}' and '{parent}' in parents and mimeType = 'application/vnd.google-apps.folder' "
             "and trashed = false", "fields": "files(id)", "pageSize": 1})
    found = r.json().get("files") or []
    if found:
        fid = found[0]["id"]
    else:
        fid = _send("POST", f"{API}/files", params={"fields": "id"},
                    json={"name": name, "parents": [parent], "mimeType": "application/vnd.google-apps.folder"}
                    ).json()["id"]
    db.drive_folder_put(key, fid)
    return fid


# ---------- upload / download ----------
def _md5(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 - Drive reports md5; a checksum for integrity, not security
    with path.open("rb") as f:
        while block := f.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def _chunk(loc: str, data: bytes, offset: int, size: int) -> httpx.Response:
    end = offset + len(data) - 1
    last = None
    for attempt in range(5):
        try:
            with _client(300) as c:
                return c.put(loc, content=data, headers={"Content-Range": f"bytes {offset}-{end}/{size}"})
        except httpx.HTTPError as e:
            last = e
            _sleep(2 ** attempt)
            try:  # where did the session get to?
                with _client(60) as c:
                    r = c.put(loc, headers={"Content-Range": f"bytes */{size}"})
                if r.status_code in (200, 201):
                    return r
                if r.status_code == 308:
                    return r
            except httpx.HTTPError:
                pass
    raise DriveError(tr("Could not connect to Google: {error}", error=last))


def upload(path: Path, rel: str) -> dict:
    """Send one file to Drive at <root>/<rel>. Returns Drive's answer ({id, size, md5Checksum}) once its size and md5
    equal the local file's; a file that came back different is removed from Drive and raises."""
    st = path.stat()
    local_md5 = _md5(path)
    parts = (root_name(), *PurePosixPath(rel).parts)
    r = None
    for _ in (0, 1):
        r = _send("POST", UPLOAD, params={"uploadType": "resumable", "fields": FIELDS},
                  json={"name": parts[-1], "parents": [_folder(parts[:-1])]},
                  headers={"X-Upload-Content-Length": str(st.st_size)}, ok=(200, 404))
        if r.status_code == 200:
            break
        db.drive_folders_clear()  # a folder was deleted on Drive: look them up again
    if r is None or r.status_code != 200:
        raise DriveError(tr("Google Drive error {status}: {error}", status=404, error=_err(r)))
    loc = r.headers["Location"]
    offset, done = 0, None
    with path.open("rb") as f:
        while done is None:
            f.seek(offset)
            data = f.read(CHUNK)
            res = _chunk(loc, data, offset, st.st_size)
            if res.status_code in (200, 201):
                done = res.json()
            elif res.status_code == 308:
                rng = res.headers.get("Range")  # "bytes=0-N": what Drive has
                offset = int(rng.rsplit("-", 1)[1]) + 1 if rng else 0
            else:
                raise DriveError(tr("Google Drive error {status}: {error}", status=res.status_code, error=_err(res)))
    if int(done.get("size") or -1) != st.st_size or (done.get("md5Checksum") or local_md5) != local_md5:
        trash(done["id"])
        raise DriveError(tr("Drive's copy of {name} does not match the file; kept it here", name=path.name))
    done["md5Checksum"] = done.get("md5Checksum") or local_md5
    return done


def trash(file_id: str) -> None:
    """Move a Drive file to the bin (recoverable for 30 days). Already gone is fine."""
    _send("PATCH", f"{API}/files/{file_id}", json={"trashed": True}, ok=(200, 404))


def download(entry: dict, dest: Path) -> None:
    """Fetch a file from Drive to `dest` (through a .dl file, so a dropped connection leaves nothing half-written)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{threading.get_ident()}.dl")
    try:
        with _client(600) as c, c.stream("GET", f"{API}/files/{entry['file_id']}", params={"alt": "media"},
                                          headers={"Authorization": f"Bearer {access_token()}"}) as r:
            if r.status_code != 200:
                r.read()
                raise DriveError(tr("Google Drive error {status}: {error}", status=r.status_code, error=_err(r)))
            with tmp.open("wb") as f:
                for block in r.iter_bytes(1 << 20):
                    f.write(block)
    except httpx.HTTPError as e:
        tmp.unlink(missing_ok=True)
        raise DriveError(tr("Could not connect to Google: {error}", error=e)) from e
    except DriveError:
        tmp.unlink(missing_ok=True)
        raise
    if tmp.stat().st_size != entry["size"]:
        tmp.unlink(missing_ok=True)
        raise DriveError(tr("Drive's copy of {name} does not match the file; kept it here", name=dest.name))
    os.replace(tmp, dest)
    st = dest.stat()
    # the restored file counts as already uploaded (same size and time), so the next sweep does not send it again
    db.drive_put(entry["rel"], entry["file_id"], entry["size"], st.st_mtime_ns, entry["md5"])


def open_stream(rel: str, range_header: str | None = None) -> tuple[int, dict, Iterator[bytes]] | None:
    """For /media: the file's bytes straight from Drive (status, headers, body), None if Drive does not hold it."""
    entry = db.drive_get(rel)
    if not entry or not configured():
        return None
    client = _client(600)
    try:
        headers = {"Authorization": f"Bearer {access_token()}"}
        if range_header:
            headers["Range"] = range_header
        r = client.send(client.build_request("GET", f"{API}/files/{entry['file_id']}", params={"alt": "media"},
                                             headers=headers), stream=True)
    except (httpx.HTTPError, DriveError):
        client.close()
        return None
    if r.status_code not in (200, 206):
        r.close()
        client.close()
        return None
    out = {k: r.headers[k] for k in ("content-length", "content-range") if k in r.headers}
    out["accept-ranges"] = "bytes"

    def body() -> Iterator[bytes]:
        try:
            yield from r.iter_bytes(1 << 16)
        finally:
            r.close()
            client.close()

    return r.status_code, out, body()


# ---------- what is where ----------
def _rel(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(config.DATA.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def has(path: Path) -> bool:
    rel = _rel(path)
    return bool(rel and db.drive_get(rel))


def mtime(path: Path) -> float | None:
    """When the file was last written: here if it is here, else when the copy on Drive was made. None if neither."""
    try:
        return path.stat().st_mtime
    except OSError:
        rel = _rel(path)
        entry = db.drive_get(rel) if rel else None
        return entry["mtime_ns"] / 1e9 if entry else None


def ensure(path: Path) -> bool:
    """Make sure `path` is on this machine: True if it is (or came back from Drive), False if it can't be had."""
    if path.exists():
        return True
    rel = _rel(path)
    entry = db.drive_get(rel) if rel and configured() else None
    if not entry:
        return False
    download(entry, path)
    return True


def restore_glob(directory: Path, pattern: str) -> list[Path]:
    """Bring back the files of `directory` whose name matches `pattern` and that only Drive holds."""
    rel = _rel(directory)
    if rel is None or not configured():
        return []
    back = []
    for e in db.drive_list(rel + "/"):
        name = e["rel"][len(rel) + 1:]
        if "/" not in name and fnmatch.fnmatch(name, pattern):
            path = directory / name
            if ensure(path):
                back.append(path)
    return sorted(back)


def restore_project(pid: int) -> int:
    """Before a project runs again: fetch its files that only Drive holds, except what the next render rewrites."""
    if not configured():
        return 0
    n = 0
    for e in db.drive_list(f"projects/{pid}/"):
        name = Path(e["rel"]).name
        if name.startswith(KEEP_HERE[0]) or name.endswith(KEEP_HERE[1]):
            continue
        path = config.DATA / e["rel"]
        if not path.exists():
            download(e, path)
            n += 1
    return n


def forget_project(pid: int) -> None:
    """A project was deleted: its Drive files go to the bin and the index forgets them. Errors only leave rows behind
    (the next sync sweeps them)."""
    if not configured():
        return
    for e in db.drive_list(f"projects/{pid}/"):
        try:
            trash(e["file_id"])
            db.drive_del(e["rel"])
        except DriveError:
            return


# ---------- moving files ----------
def _idle(proj: dict) -> bool:
    """The project's files may leave this machine: it is done or failed, or finished and waits at the video gate."""
    st = proj["status"]
    return st in ("done", "failed") or (st == "review" and (proj.get("meta") or {}).get("review") == "video")


def _movable(f: Path) -> bool:
    return (f.is_file() and not f.name.startswith(".") and f.suffix not in (".part", ".dl", ".job", ".tmp")
            and f.stat().st_size >= MIN_BYTES)


def offload_file(path: Path, rel: str, before_delete=None) -> int:
    """Upload `path` if Drive does not hold this exact version, then delete it here unless DRIVE_KEEP_LOCAL.
    `before_delete()` returning False keeps the local copy. Returns the bytes freed here."""
    st = path.stat()
    old = db.drive_get(rel)
    if not old or old["size"] != st.st_size or old["mtime_ns"] != st.st_mtime_ns:
        done = upload(path, rel)
        if path.stat().st_mtime_ns != st.st_mtime_ns:  # changed while it went up: the next sweep sends the new one
            trash(done["id"])
            return 0
        db.drive_put(rel, done["id"], st.st_size, st.st_mtime_ns, done["md5Checksum"])
        if old and old["file_id"] != done["id"]:
            trash(old["file_id"])
    if keep_local() or (before_delete and not before_delete()):
        return 0
    try:
        if path.stat().st_mtime_ns != st.st_mtime_ns:
            return 0
        path.unlink()
    except OSError:  # open on Windows, or gone already
        return 0
    return st.st_size


def _project_idle(pid: int) -> bool:
    p = db.get_project(pid)
    return bool(p and _idle(p))


def offload_project(pid: int) -> int:
    """Move a finished project's heavy files to Drive. Returns the bytes freed here."""
    if not enabled() or not _project_idle(pid):
        return 0
    folder = config.PROJECTS / str(pid)
    freed = 0
    for f in sorted(folder.rglob("*")) if folder.exists() else []:
        if _movable(f) and (rel := _rel(f)):
            freed += offload_file(f, rel, lambda: _project_idle(pid))
    return freed


def _active_sources() -> set[str]:
    """Source files a project that can still run (queued, running, or waiting at a script / pictures gate) uses."""
    used = set()
    for p in db.projects_with_status(("queued", "running", "review")):
        if _idle(p):
            continue
        for s in p["meta"].get("sources") or []:
            if s.get("path"):
                used.add(str(Path(s["path"]).resolve()))
    return used


def offload_sources(min_age: float = SOURCE_MIN_AGE) -> int:
    """Move cached source videos that no project in progress needs. Returns the bytes freed here."""
    if not enabled():
        return 0
    folder = config.CACHE / "sources"
    freed = 0
    active = _active_sources()
    for f in sorted(folder.glob("*")) if folder.exists() else []:
        if not _movable(f) or time.time() - f.stat().st_mtime < min_age or str(f.resolve()) in active:
            continue
        if rel := _rel(f):
            freed += offload_file(f, rel, lambda f=f: str(f.resolve()) not in _active_sources())
    return freed


def purge_orphans() -> int:
    """Drive files of projects that no longer exist (deleted while Drive was unreachable) go to the bin."""
    n = 0
    for e in db.drive_list("projects/"):
        parts = e["rel"].split("/")
        if len(parts) > 1 and parts[1].isdigit() and not db.get_project(int(parts[1])):
            try:
                trash(e["file_id"])
                db.drive_del(e["rel"])
                n += 1
            except DriveError:
                break
    return n


def sweep() -> dict:
    """Move everything that can move now: finished projects, idle sources, then Drive files of deleted projects."""
    freed = sum(offload_project(p["id"]) for p in db.projects_with_status(("done", "failed", "review")))
    freed += offload_sources()
    purge_orphans()
    return {"freed": freed}


def start_sync() -> bool:
    """Run a sweep in the background ("Move to Drive now" in Settings). False if one is already running."""
    with _sync_lock:
        if _sync["running"]:
            return False
        _sync.update(running=True, freed=0, error="", finished=0.0)

    def run() -> None:
        try:
            if not enabled():
                _sync["error"] = tr("Google Drive is switched off or not signed in")
                return
            _sync["freed"] = sweep()["freed"]
        except Exception as e:  # shown in Settings, never a crash of the engine
            _sync["error"] = str(e)[:300]
        finally:
            _sync.update(running=False, finished=time.time())

    threading.Thread(target=run, daemon=True, name="drive-sync").start()
    return True


def after_done(pid: int) -> None:
    """A project just finished: move its files (and idle sources) to Drive in the background. Never raises."""
    if not enabled():
        return

    def run() -> None:
        try:
            offload_project(pid)
            offload_sources()
        except Exception as e:  # the video is done either way; the log says why it stayed here
            db.update_project(pid, log=tr("Could not move files to Google Drive: {error}", error=str(e)[:200]))

    threading.Thread(target=run, daemon=True, name=f"drive-{pid}").start()


# ---------- status for Settings ----------
def about() -> dict:
    """Account and space on Drive (cached for a minute). {} when it can't be read."""
    if not configured():
        return {}
    if time.time() - _about["at"] < 60 and _about["data"]:
        return _about["data"]
    try:
        j = _send("GET", f"{API}/about", params={"fields": "user(emailAddress),storageQuota"}, retries=1).json()
    except DriveError:
        return {}
    q = j.get("storageQuota") or {}
    data = {"email": (j.get("user") or {}).get("emailAddress", ""),
            "used": int(q["usage"]) if q.get("usage") else None, "limit": int(q["limit"]) if q.get("limit") else None}
    _about.update(at=time.time(), data=data)
    return data


def status() -> dict:
    n, size = db.drive_totals()
    return {"enabled": enabled(), "signed_in": configured(), "client": client_ready(), "folder": root_name(),
            "keep_local": keep_local(), "files": n, "bytes": size, "account": about(),
            "pending": bool(_pending and time.time() < _pending["expires"]), "sync": dict(_sync)}
