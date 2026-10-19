"""Google Drive as the main storage (motio/drive.py), against a fake Drive that speaks the REST calls Motio makes."""
import hashlib
import json
import os
import re
import shutil
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from motio import api, config, db, drive, edit, pipeline, postiz, settings

TOKEN = "t0ken"
H = {"Authorization": f"Bearer {TOKEN}"}
SIZE = 600 * 1024  # three chunks of 256 KiB


class FakeDrive:
    """Just enough of Google: OAuth device flow, folders, resumable upload, media download, trash, about."""

    def __init__(self):
        self.files: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.polls = 0  # device-flow polls so far
        self.pending_polls = 1  # answers "authorization_pending" this many times
        self.bad_md5 = False  # an upload that Drive stores wrongly
        self.calls: list[str] = []
        self.next = 0

    def new_id(self, kind: str) -> str:
        self.next += 1
        return f"{kind}{self.next}"

    def names(self) -> list[str]:
        """Path of every live non-folder file, e.g. Motio/projects/3/final.mp4."""
        def path(f):
            parent = self.files.get(f["parent"])
            return f"{path(parent)}/{f['name']}" if parent else f["name"]
        return sorted(path(f) for f in self.files.values() if not f["folder"] and not f["trashed"])

    def find(self, path: str) -> dict:
        return next(f for f in self.files.values() if not f["folder"] and not f["trashed"]
                    and self.names_of(f) == path)

    def names_of(self, f) -> str:
        parent = self.files.get(f["parent"])
        return f"{self.names_of(parent)}/{f['name']}" if parent else f["name"]

    def handler(self, req: httpx.Request) -> httpx.Response:
        url = urlparse(str(req.url))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.calls.append(f"{req.method} {url.path}")
        host, path = url.netloc, url.path
        if host == "oauth2.googleapis.com" and path == "/device/code":
            return httpx.Response(200, json={"device_code": "dev", "user_code": "ABCD-EFGH", "expires_in": 1800,
                                             "interval": 5, "verification_url": "https://www.google.com/device"})
        if host == "oauth2.googleapis.com" and path == "/token":
            form = parse_qs(req.content.decode())
            if form["grant_type"][0] == "refresh_token":
                if form["refresh_token"][0] != "refresh-1":
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad Request"})
                return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
            self.polls += 1
            if self.polls <= self.pending_polls:
                return httpx.Response(428, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "refresh-1", "expires_in": 3600})
        if host == "upload.fake":
            return self.upload_chunk(req, path)
        assert req.headers["authorization"] == "Bearer at-1"
        if path == "/drive/v3/about":
            return httpx.Response(200, json={"user": {"emailAddress": "owner@example.com"},
                                             "storageQuota": {"usage": "1000", "limit": "30000000000000"}})
        if path == "/upload/drive/v3/files":
            meta = json.loads(req.content)
            sid = self.new_id("session")
            self.sessions[sid] = {"meta": meta, "data": b""}
            return httpx.Response(200, headers={"Location": f"https://upload.fake/{sid}"})
        if path == "/drive/v3/files" and req.method == "GET":
            m = re.match(r"name = '(.*)' and '(.*)' in parents", q["q"])
            hits = [{"id": i} for i, f in self.files.items() if f["folder"] and f["name"] == m[1]
                    and f["parent"] == m[2] and not f["trashed"]]
            return httpx.Response(200, json={"files": hits})
        if path == "/drive/v3/files" and req.method == "POST":
            body = json.loads(req.content)
            fid = self.new_id("folder")
            self.files[fid] = {"name": body["name"], "parent": body["parents"][0], "folder": True, "trashed": False}
            return httpx.Response(200, json={"id": fid})
        m = re.fullmatch(r"/drive/v3/files/(.+)", path)
        f = self.files.get(m[1]) if m else None
        if not f:
            return httpx.Response(404, json={"error": {"code": 404, "message": "File not found"}})
        if req.method == "PATCH":
            f["trashed"] = json.loads(req.content)["trashed"]
            return httpx.Response(200, json={"id": m[1]})
        data = f["data"]
        rng = req.headers.get("range")
        if rng:
            a, b = re.fullmatch(r"bytes=(\d+)-(\d*)", rng).groups()
            a, b = int(a), int(b) if b else len(data) - 1
            return httpx.Response(206, content=data[a:b + 1],
                                  headers={"Content-Range": f"bytes {a}-{b}/{len(data)}"})
        return httpx.Response(200, content=data)

    def upload_chunk(self, req: httpx.Request, path: str) -> httpx.Response:
        s = self.sessions[path.lstrip("/")]
        total = int(req.headers["content-range"].rsplit("/", 1)[1])
        start = int(re.match(r"bytes (\d+)-", req.headers["content-range"])[1]) if req.content else len(s["data"])
        if req.content:
            assert start == len(s["data"]), "chunk out of order"
            if len(s["data"]) + len(req.content) < total:
                assert len(req.content) % (256 * 1024) == 0, "chunk must be a multiple of 256 KiB"
            s["data"] += req.content
        if len(s["data"]) < total:
            return httpx.Response(308, headers={"Range": f"bytes=0-{len(s['data']) - 1}"} if s["data"] else {})
        fid = self.new_id("file")
        md5 = "0" * 32 if self.bad_md5 else hashlib.md5(s["data"]).hexdigest()  # noqa: S324
        self.files[fid] = {"name": s["meta"]["name"], "parent": s["meta"]["parents"][0], "folder": False,
                           "trashed": False, "data": s["data"]}
        return httpx.Response(200, json={"id": fid, "size": str(total), "md5Checksum": md5})


def _clean() -> None:
    with db.conn() as c:
        c.execute("DELETE FROM drive_file")
        c.execute("DELETE FROM drive_folder")
        c.execute("DELETE FROM project")
    shutil.rmtree(config.PROJECTS, ignore_errors=True)
    shutil.rmtree(config.CACHE / "sources", ignore_errors=True)
    config.PROJECTS.mkdir(parents=True, exist_ok=True)
    (config.CACHE / "sources").mkdir(parents=True, exist_ok=True)


@pytest.fixture
def fake(monkeypatch):
    f = FakeDrive()
    monkeypatch.setattr(drive, "_transport", httpx.MockTransport(f.handler))
    monkeypatch.setattr(drive, "_sleep", lambda s: None)
    monkeypatch.setattr(drive, "CHUNK", 256 * 1024)
    monkeypatch.setattr(drive, "MIN_BYTES", 1000)
    drive.reset_token()
    drive._pending.clear()
    _clean()
    yield f
    _clean()  # nothing of these big files or projects reaches the next test module


@pytest.fixture
def signed_in(fake):
    settings.update({"DRIVE_CLIENT_ID": "cid", "DRIVE_CLIENT_SECRET": "csecret", "DRIVE_REFRESH_TOKEN": "refresh-1",
                     "DRIVE_ON": True})
    return fake


def _project(status="done", meta=None) -> int:
    pid = db.create_project(None, "t")
    db.update_project(pid, status=status, meta=meta)
    return pid


def _file(pid: int, name: str, size: int = SIZE):
    f = config.PROJECTS / str(pid) / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(os.urandom(size))
    return f


# ---------- sign-in ----------
def test_sign_in_flow_saves_the_refresh_token_masked(fake):
    settings.update({"DRIVE_CLIENT_ID": "cid", "DRIVE_CLIENT_SECRET": "csecret"})
    assert not drive.configured()
    start = drive.sign_in_start()
    assert start["code"] == "ABCD-EFGH" and start["url"].endswith("/device")
    assert drive.sign_in_poll() == "pending"
    assert drive.sign_in_poll() == "ok"
    assert drive.configured() and not drive.enabled()  # signed in, but the switch is the owner's
    shown = settings.public()
    assert shown["DRIVE_REFRESH_TOKEN"]["secret"] and "refresh-1" not in shown["DRIVE_REFRESH_TOKEN"]["value"]
    assert shown["DRIVE_CLIENT_SECRET"]["value"].startswith(settings.MASK)
    assert drive.access_token() == "at-1"


def test_sign_in_needs_the_client_and_reports_a_refusal(fake):
    with pytest.raises(drive.DriveError, match="client ID"):
        drive.sign_in_start()
    assert drive.sign_in_poll() == "expired"  # nothing was started


def test_sign_out_forgets_the_token(signed_in):
    drive.sign_out()
    assert not drive.configured()
    assert settings.public()["DRIVE_REFRESH_TOKEN"]["value"] == ""


def test_a_revoked_token_says_to_sign_in_again(fake):
    settings.update({"DRIVE_CLIENT_ID": "cid", "DRIVE_CLIENT_SECRET": "csecret", "DRIVE_REFRESH_TOKEN": "old"})
    with pytest.raises(drive.DriveError, match="sign in again"):
        drive.access_token()


# ---------- moving files ----------
def test_a_finished_project_moves_to_drive_and_small_files_stay(signed_in):
    pid = _project()
    final = _file(pid, "final.mp4")
    voice = _file(pid, "audio/narration.mp3")
    script = _file(pid, "script.json", size=200)
    keep = final.read_bytes()
    freed = drive.offload_project(pid)
    assert freed == 2 * SIZE
    assert not final.exists() and not voice.exists() and script.exists()
    assert signed_in.names() == [f"Motio/projects/{pid}/audio/narration.mp3", f"Motio/projects/{pid}/final.mp4"]
    assert signed_in.find(f"Motio/projects/{pid}/final.mp4")["data"] == keep
    assert db.drive_get(f"projects/{pid}/final.mp4")["size"] == SIZE
    assert any(c.startswith("PUT") for c in signed_in.calls)  # three chunks, so a resumable session ran


def test_keep_local_makes_drive_a_backup(signed_in):
    settings.update({"DRIVE_KEEP_LOCAL": True})
    pid = _project()
    final = _file(pid, "final.mp4")
    assert drive.offload_project(pid) == 0
    assert final.exists() and signed_in.names() == [f"Motio/projects/{pid}/final.mp4"]


def test_nothing_moves_while_the_project_runs_or_waits_for_a_script(signed_in):
    for status, meta in (("running", None), ("queued", None), ("review", {"review": "script"}),
                         ("review", {"review": "shots"})):
        pid = _project(status, meta)
        final = _file(pid, "final.mp4")
        assert drive.offload_project(pid) == 0
        assert final.exists()
    assert signed_in.names() == []
    pid = _project("review", {"review": "video"})  # waiting for the video gate: the video is finished
    final = _file(pid, "final.mp4")
    assert drive.offload_project(pid) == SIZE and not final.exists()


def test_switched_off_moves_nothing(signed_in):
    settings.update({"DRIVE_ON": False})
    pid = _project()
    final = _file(pid, "final.mp4")
    assert drive.offload_project(pid) == 0 and final.exists()


def test_a_copy_that_does_not_match_is_not_trusted(signed_in):
    signed_in.bad_md5 = True
    pid = _project()
    final = _file(pid, "final.mp4")
    with pytest.raises(drive.DriveError, match="does not match"):
        drive.offload_project(pid)
    assert final.exists() and db.drive_get(f"projects/{pid}/final.mp4") is None
    assert signed_in.names() == []  # the bad copy went to the bin


def test_an_unchanged_file_is_not_sent_twice_and_a_changed_one_replaces_the_old(signed_in):
    settings.update({"DRIVE_KEEP_LOCAL": True})
    pid = _project()
    final = _file(pid, "final.mp4")
    drive.offload_project(pid)
    uploads = sum(c.startswith("POST /upload") for c in signed_in.calls)
    drive.offload_project(pid)
    assert sum(c.startswith("POST /upload") for c in signed_in.calls) == uploads
    final.write_bytes(os.urandom(SIZE))  # a re-render
    new = final.read_bytes()
    drive.offload_project(pid)
    assert signed_in.names() == [f"Motio/projects/{pid}/final.mp4"]
    assert signed_in.find(f"Motio/projects/{pid}/final.mp4")["data"] == new


def test_a_file_that_comes_back_is_not_uploaded_again(signed_in):
    pid = _project()
    final = _file(pid, "final.mp4")
    data = final.read_bytes()
    drive.offload_project(pid)
    assert drive.ensure(final) and final.read_bytes() == data
    uploads = sum(c.startswith("POST /upload") for c in signed_in.calls)
    settings.update({"DRIVE_KEEP_LOCAL": True})
    drive.offload_project(pid)
    assert sum(c.startswith("POST /upload") for c in signed_in.calls) == uploads


def test_ensure_returns_false_for_a_file_drive_never_had(signed_in):
    assert not drive.ensure(config.PROJECTS / "999" / "final.mp4")


# ---------- sources ----------
def test_sources_move_unless_a_project_in_progress_uses_them(signed_in):
    src = config.CACHE / "sources"
    src.mkdir(parents=True, exist_ok=True)
    free, busy = src / "Bili_free.mp4", src / "Bili_busy.mp4"
    free.write_bytes(os.urandom(SIZE))
    busy.write_bytes(os.urandom(SIZE))
    _project("running", {"sources": [{"path": str(busy), "url": "u", "id": "busy"}]})
    assert drive.offload_sources(min_age=-60) == SIZE
    assert not free.exists() and busy.exists()
    assert signed_in.names() == ["Motio/cache/sources/Bili_free.mp4"]


def test_a_fresh_download_is_left_alone(signed_in):
    src = config.CACHE / "sources"
    src.mkdir(parents=True, exist_ok=True)
    fresh = src / "Bili_fresh.mp4"
    fresh.write_bytes(os.urandom(SIZE))
    assert drive.offload_sources() == 0 and fresh.exists()


def test_a_run_brings_the_source_back_first(signed_in):
    src = config.CACHE / "sources"
    src.mkdir(parents=True, exist_ok=True)
    f = src / "Bili_abc.mp4"
    data = os.urandom(SIZE)
    f.write_bytes(data)
    pid = _project("done", {"sources": [{"path": str(f), "url": "https://b/x?v=abc", "id": "abc"}]})
    drive.offload_sources(min_age=-60)
    assert not f.exists()
    assert pipeline._load_sources(pid)[0]["path"] == str(f) and f.read_bytes() == data
    f.unlink()
    db.update_project(pid, meta={"sources": [{"path": "/old/machine/Bili_abc.mp4", "url": "https://b/x?v=abc",
                                              "id": "abc"}]})
    assert pipeline._load_sources(pid)[0]["path"] == str(f)  # found by video id, as when the path is from another PC


def test_restore_project_skips_what_the_next_render_rewrites(signed_in):
    pid = _project()
    for name in ("final.mp4", "final_wide.mp4", "audio/narration.mp3", "scenes/1.png"):
        _file(pid, name)
    drive.offload_project(pid)
    assert drive.restore_project(pid) == 2
    folder = config.PROJECTS / str(pid)
    assert (folder / "audio/narration.mp3").exists() and (folder / "scenes/1.png").exists()
    assert not (folder / "final.mp4").exists() and not (folder / "final_wide.mp4").exists()


def test_the_saved_voice_counts_when_it_is_on_drive(signed_in):
    pid = _project()
    audio = _file(pid, "audio/narration.mp3")
    out = config.PROJECTS / str(pid)
    (out / "script.json").write_text(json.dumps({"lines": [{"text": "a"}]}), encoding="utf-8")
    (out / "audio" / pipeline.NARRATION).write_text(json.dumps({"texts": ["a"], "audio": str(audio)}), encoding="utf-8")
    assert pipeline.saved_narration(pid)
    drive.offload_project(pid)
    assert not audio.exists() and pipeline.saved_narration(pid)


# ---------- deleting, orphans, postiz ----------
def test_deleting_a_project_puts_its_drive_files_in_the_bin(signed_in):
    pid = _project()
    _file(pid, "final.mp4")
    drive.offload_project(pid)
    edit.delete(pid)
    assert signed_in.names() == [] and db.drive_list(f"projects/{pid}/") == []


def test_a_sweep_bins_files_of_projects_that_no_longer_exist(signed_in):
    pid = _project()
    _file(pid, "final.mp4")
    drive.offload_project(pid)
    db.delete_project(pid)  # deleted while Drive could not be reached
    assert drive.purge_orphans() == 1 and signed_in.names() == []


def test_sending_a_video_that_lives_on_drive_fetches_it(signed_in):
    pid = _project()
    final = _file(pid, "final.mp4")
    drive.offload_project(pid)
    meta = {"video": f"projects/{pid}/final.mp4"}
    assert postiz.project_video(meta) == final and final.exists()


# ---------- the API ----------
@pytest.fixture
def client():
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


def test_media_plays_a_file_from_drive_with_ranges(signed_in, client):
    pid = _project()
    final = _file(pid, "final.mp4")
    data = final.read_bytes()
    drive.offload_project(pid)
    url = f"/media/projects/{pid}/final.mp4"
    r = client.get(url, headers=H)
    assert r.status_code == 200 and r.content == data
    r = client.get(url, headers={**H, "Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == data[10:20]
    assert r.headers["content-range"] == f"bytes 10-19/{SIZE}" and r.headers["content-type"] == "video/mp4"
    assert client.get(f"/media/projects/{pid}/nothing.mp4", headers=H).status_code == 404


def test_media_never_serves_settings_from_drive(signed_in, client):
    assert client.get("/media/settings.json", headers=H).status_code == 404


def test_status_signin_and_sync_routes(fake, client):
    assert client.get("/api/drive", headers=H).json()["signed_in"] is False
    assert client.post("/api/drive/sign-in", headers=H).status_code == 400  # no client yet
    client.put("/api/settings", headers=H, json={"DRIVE_CLIENT_ID": "cid", "DRIVE_CLIENT_SECRET": "csecret",
                                                  "DRIVE_ON": True})
    r = client.post("/api/drive/sign-in", headers=H)
    assert r.json()["code"] == "ABCD-EFGH"
    assert client.post("/api/drive/sign-in/check", headers=H).json() == {"state": "pending"}
    assert client.post("/api/drive/sign-in/check", headers=H).json() == {"state": "ok"}
    st = client.get("/api/drive", headers=H).json()
    assert st["signed_in"] and st["enabled"] and st["account"]["email"] == "owner@example.com"
    assert "refresh-1" not in json.dumps(client.get("/api/settings", headers=H).json())
    assert client.post("/api/drive/sign-out", headers=H).json()["signed_in"] is False


def test_sync_moves_finished_work_in_the_background(signed_in, client):
    pid = _project()
    final = _file(pid, "final.mp4")
    assert client.post("/api/drive/sync", headers=H).status_code == 202
    end = time.time() + 5
    while drive._sync["running"] and time.time() < end:
        time.sleep(0.02)
    st = client.get("/api/drive", headers=H).json()
    assert st["sync"]["freed"] == SIZE and not st["sync"]["error"] and st["files"] == 1
    assert not final.exists()


def test_sync_refuses_when_drive_is_off(fake, client):
    assert client.post("/api/drive/sync", headers=H).status_code == 400


def test_a_video_file_added_by_hand_comes_back_from_drive(signed_in):
    from motio import localfile

    uid = "a" * 32
    f = localfile.folder() / f"{localfile.PLATFORM}_{uid}.mp4"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(os.urandom(SIZE))
    drive.offload_sources(min_age=-60)
    assert not f.exists()
    assert localfile.path_of(uid) == f and f.exists()
