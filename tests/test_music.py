"""Music library: tracks added by hand, trending sounds from the (faked) music API, the pick of a video, the mix."""
import io
import json
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from motio import api, channels, config, db, music, pipeline

TOKEN = "t"
H = {"Authorization": f"Bearer {TOKEN}"}
needs_ffmpeg = pytest.mark.skipif(not config.find("ffmpeg"), reason="needs ffmpeg")


def tone(path, seconds=20, freq=330) -> bytes:
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f={freq}:d={seconds}",
                    "-c:a", "libmp3lame", str(path)], check=True)
    return path.read_bytes()


@pytest.fixture
def client(monkeypatch):
    with db.conn() as c:
        c.execute("DELETE FROM project")
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


@pytest.fixture
def cml(monkeypatch, tmp_path):
    """A fake music API. 7 days: Sunny Day (#1, playable trending cut) and No Preview (#2). 30 days: Old Hit (#1,
    playable) and Sunny Day (#2). `cml[0]` holds the charts by dateRange so a test can change them, the rest are the
    requests."""
    if not config.find("ffmpeg"):
        pytest.skip("needs ffmpeg")
    audio = tone(tmp_path / "preview.mp3", 20)
    seen = []
    sunny = {"commercial_music_name": "Sunny Day", "artist": "Ana", "duration": 180, "rank_position": "1",
             "full_duration_song_clip": {"preview_url": "https://cdn.test/full.mp3", "duration": 180,
                                         "song_clip_id": "clip-full"},
             "trending_song_clip": {"preview_url": "https://cdn.test/a.mp3", "duration": 20, "song_clip_id": "clip-a"}}
    quiet = {"commercial_music_name": "No Preview", "artist": "Bo", "rank_position": "2", "preview_url": None}
    old = {"commercial_music_name": "Old Hit", "artist": "Cy", "rank_position": "1",
           "trending_song_clip": {"preview_url": "https://cdn.test/b.mp3", "duration": 20, "song_clip_id": "clip-b"}}
    month = [old, {**sunny, "rank_position": "2"}, {"commercial_music_name": "", "artist": "ignored"}]
    charts = {"7DAY": [sunny, quiet], "30DAY": month}
    seen.append(charts)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.bundle.social":
            seen.append(req)
            if req.headers.get("x-api-key") != "k-1":
                return httpx.Response(401, json={"message": "bad key"})
            return httpx.Response(200, json=charts[req.url.params["dateRange"]])
        if req.url.path in ("/a.mp3", "/b.mp3"):
            return httpx.Response(200, content=audio, headers={"content-type": "audio/mpeg"})
        return httpx.Response(404)

    monkeypatch.setattr(music, "_transport", httpx.MockTransport(handler))
    monkeypatch.setenv("TIKTOK_MUSIC_API_KEY", "k-1")
    monkeypatch.setenv("TIKTOK_MUSIC_TEAM_ID", "team-1")
    return seen


def test_usable_on():
    assert [music.usable_on(x) for x in ("own", "licensed", "cc", "tiktok_cml", "unknown")] == \
        ["all", "all", "all", "tiktok", "none"]


@needs_ffmpeg
def test_upload_list_edit_delete(client, tmp_path):
    data = tone(tmp_path / "a.mp3")
    r = client.post("/api/music", headers=H, files={"file": ("My Song.mp3", io.BytesIO(data))},
                    data={"artist": "Me", "license": "own"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["title"] == "My Song" and t["artist"] == "Me" and t["usable_on"] == "all" and t["audio"]
    assert abs(t["duration"] - 20) < 1
    assert client.get(f"/media/{t['audio']}?token={TOKEN}").status_code == 200  # the app plays it
    again = client.post("/api/music", headers=H, files={"file": ("copy.mp3", io.BytesIO(data))},
                        data={"license": "cc"}).json()
    assert again["id"] == t["id"] and again["license"] == "cc"  # same bytes = same track
    assert len(client.get("/api/music", headers=H).json()["tracks"]) == 1
    r = client.patch(f"/api/music/{t['id']}", headers=H, json={"title": "Renamed", "license": "unknown"})
    assert r.json()["title"] == "Renamed" and r.json()["usable_on"] == "none"
    assert client.patch(f"/api/music/{t['id']}", headers=H, json={"license": "gpl"}).status_code == 400
    assert client.delete(f"/api/music/{t['id']}", headers=H).status_code == 200
    assert not (config.DATA / t["audio"]).exists() and client.get("/api/music", headers=H).json()["tracks"] == []
    assert client.delete(f"/api/music/{t['id']}", headers=H).status_code == 404


@needs_ffmpeg
def test_upload_rejects_what_is_not_audio(client):
    r = client.post("/api/music", headers=H, files={"file": ("x.txt", io.BytesIO(b"hello"))})
    assert r.status_code == 400 and "audio" in r.json()["detail"]
    r = client.post("/api/music", headers=H, files={"file": ("x.mp3", io.BytesIO(b"not really audio"))})
    assert r.status_code == 400
    assert not list((config.DATA / "music").glob(".upload-*"))  # nothing half-written is left


def test_fetch_needs_a_key(client):
    r = client.post("/api/music/fetch", headers=H, json={})
    assert r.status_code == 400 and "API key" in r.json()["detail"]
    assert client.get("/api/music", headers=H).json()["fetch"] is False


def test_fetch_trending_and_popular(client, cml):
    r = client.post("/api/music/fetch", headers=H, json={"genre": "pop"})
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 3, "updated": 0, "listed": 3, "no_audio": 1, "removed": 0}
    sent = [q for q in cml[1:] if hasattr(q, "url")]
    assert {q.url.params["dateRange"] for q in sent} == {"7DAY", "30DAY"}
    assert all(q.url.params["genre"] == "POP" and q.url.params["teamId"] == "team-1" for q in sent)
    tracks = {t["title"]: t for t in client.get("/api/music", headers=H).json()["tracks"]}
    sunny, quiet, old = tracks["Sunny Day"], tracks["No Preview"], tracks["Old Hit"]
    assert sunny["license"] == quiet["license"] == "tiktok_cml" and sunny["usable_on"] == "tiktok"
    assert sunny["rank"] == 1 and sunny["rank_month"] == 2 and sunny["audio"] and sunny["duration"]
    assert "trending cut" in sunny["note"]
    assert quiet["rank"] == 2 and quiet["rank_month"] is None and quiet["audio"] is None  # nothing to listen to
    assert old["rank"] is None and old["rank_month"] == 1 and old["audio"] and old["genre"] == "POP"
    # an idea is never mixed; it points to the TikTok app's search instead
    assert not sunny["mixable"] and sunny["find"].startswith("https://www.tiktok.com/search?q=Sunny")
    # a second pull moves ranks, it does not duplicate; a track off both charts is dropped with its preview
    cml[0]["30DAY"] = cml[0]["30DAY"][1:]
    gone = config.DATA / old["audio"]
    assert gone.is_file()
    assert client.post("/api/music/fetch", headers=H, json={"genre": "POP"}).json() == \
        {"added": 0, "updated": 2, "listed": 2, "no_audio": 1, "removed": 1}
    assert len(db.list_music()) == 2 and not gone.exists()
    # another tag is a separate list, the first one is left alone
    assert client.post("/api/music/fetch", headers=H, json={"genre": "LO-FI"}).json()["added"] == 2
    assert {t["genre"] for t in db.list_music()} == {"POP", "LO-FI"} and len(db.list_music()) == 4
    assert "LO-FI" in client.get("/api/music", headers=H).json()["genres"]


def test_fetch_needs_a_tiktok_account_on_the_team(client, monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"statusCode": 400, "message": "Team does not have a Tiktok account"})

    monkeypatch.setattr(music, "_transport", httpx.MockTransport(handler))
    monkeypatch.setenv("TIKTOK_MUSIC_API_KEY", "k-1")
    monkeypatch.setenv("TIKTOK_MUSIC_TEAM_ID", "team-1")
    r = client.post("/api/music/fetch", headers=H, json={})
    assert r.status_code == 502 and "TikTok account" in r.json()["detail"]


def test_fetch_errors(client, cml, monkeypatch):
    monkeypatch.setenv("TIKTOK_MUSIC_API_KEY", "wrong")
    r = client.post("/api/music/fetch", headers=H, json={})
    assert r.status_code == 502 and "refused" in r.json()["detail"]
    assert client.post("/api/music/fetch", headers=H, json={"genre": "<script>"}).status_code == 400
    assert client.post("/api/music/fetch", headers=H, json={"genre": "NOT A TAG"}).status_code == 400


def _track(license="own", file=True, **kw) -> int:
    rel = ""
    if file:
        f = config.DATA / "music" / "t.mp3"
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(b"x")
        rel = "music/t.mp3"
    return db.save_music(None, title="T", artist="A", source="upload", ext_id=f"x{license}{kw}", file=rel,
                         license=license, **kw)


def _project(mode="news", meta=None) -> dict:
    pid = db.create_project(None, "p", mode)
    if meta:
        db.update_project(pid, meta=meta)
    return db.get_project(pid)


def test_choice_own_pick_beats_channel_and_none_means_none():
    mid = _track()
    ch = {"music_id": mid, "music_volume": 0.4}
    assert music.choice(_project(), ch)[0]["id"] == mid and music.choice(_project(), ch)[1] == 0.4
    mine = _project(meta={"music": {"id": None, "volume": 0.25}})
    assert music.choice(mine, ch)[0] is None  # "no music" on the video wins over the channel
    other = _project(meta={"music": {"id": mid, "volume": 9}})
    assert music.choice(other, None) == (db.get_music(mid), music.MAX_VOLUME)
    assert music.choice(_project("dub", {"music": {"id": mid}}), ch)[0] is None  # a dub keeps its own music


def test_choice_ignores_a_track_without_file():
    mid = _track(file=False)
    assert music.choice(_project(), {"music_id": mid})[0] is None
    assert music.for_render(_project(), {"music_id": mid}) is None


def test_needs_review_and_credit():
    free, idea, unknown = _track("own"), _track("tiktok_cml"), _track("unknown")
    assert not music.needs_review(_project(), {"music_id": free})
    assert music.needs_review(_project(), {"music_id": unknown})
    assert not music.needs_review(_project(), None) and music.credit(_project(), None) == ""
    # a sound idea is never part of a video: no mix, no credit, no gate
    assert music.choice(_project(), {"music_id": idea})[0] is None
    assert not music.needs_review(_project(), {"music_id": idea}) and music.credit(_project(), {"music_id": idea}) == ""
    assert music.for_render(_project(), {"music_id": idea}) is None


def test_video_gate_held_for_unverified_music(monkeypatch):
    mid = _track("unknown")
    ch = channels.create({"name": "Chan", "postiz": ["tt1"], "gate_video": False, "music_id": mid})
    pid = db.create_project(None, "p")
    db.update_project(pid, meta={"channel": ch["id"]})
    held = []
    monkeypatch.setattr(pipeline, "_await_review", lambda p, what, log: held.append((what, log)))
    pipeline._deliver(pid, channels.for_project(db.get_project(pid)))
    assert held and held[0][0] == "video" and "background music" in held[0][1]


def test_channel_music_must_exist():
    with pytest.raises(ValueError, match="library"):
        channels.clean({"name": "C", "music_id": 99999})
    with pytest.raises(ValueError, match="library"):  # a sound idea cannot be a channel's music
        channels.clean({"name": "C", "music_id": _track("tiktok_cml")})
    d = channels.clean({"name": "C", "music_id": _track(), "music_volume": 5})
    assert d["music_volume"] == music.MAX_VOLUME


def test_project_pick_rerenders_from_the_voice_it_has(client, monkeypatch):
    mid = _track()
    pid = db.create_project(None, "p")
    out = config.PROJECTS / str(pid)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    (out / "script.json").write_text("{}")
    monkeypatch.setattr(pipeline, "available_steps", lambda p: ["search", "render"])
    calls = []
    monkeypatch.setattr(pipeline, "resume", lambda p, start=None: calls.append((p, start)))
    db.update_project(pid, status="done")
    r = client.put(f"/api/projects/{pid}/music", headers=H, json={"track_id": mid, "volume": 0.3})
    assert r.status_code == 202 and r.json()["rerender"] is True
    import time
    for _ in range(100):
        if calls:
            break
        time.sleep(0.02)
    assert calls == [(pid, "render")]
    p = client.get(f"/api/projects/{pid}", headers=H).json()
    assert p["meta"]["music"] == {"id": mid, "volume": 0.3} and p["music"]["title"] == "T"
    # unknown track, a running project, a dub
    db.update_project(pid, status="done")
    assert client.put(f"/api/projects/{pid}/music", headers=H, json={"track_id": 9999}).status_code == 404
    idea = client.put(f"/api/projects/{pid}/music", headers=H, json={"track_id": _track("tiktok_cml")})
    assert idea.status_code == 400 and "TikTok app" in idea.json()["detail"]
    dubbed = db.create_project(None, "d", "dub")
    db.update_project(dubbed, status="done")
    assert client.put(f"/api/projects/{dubbed}/music", headers=H, json={"track_id": mid}).status_code == 400
    db.update_project(pid, status="running")
    assert client.put(f"/api/projects/{pid}/music", headers=H, json={"track_id": None}).status_code == 409


@needs_ffmpeg
def test_render_mixes_music_under_the_voice(tmp_path):
    from motio import render

    src = tmp_path / "src.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:d=12",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-t", "12", str(src)], check=True)
    voice = tmp_path / "voice.m4a"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=500:d=6", "-c:a", "aac",
                    str(voice)], check=True)
    song = tmp_path / "song.mp3"
    tone(song, 8, 220)  # shorter than the video: it loops
    plan = {"title_fr": "Titre", "lines": [{"text": "Un", "clips": [{"src": 0, "start": 1, "end": 4}]},
                                          {"text": "Deux", "clips": []}]}
    nar = {"audio": str(voice), "duration": 6.0, "lines": [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.0}]}
    sources = [{"path": str(src), "duration": 12.0, "platform": "youtube", "uploader": "t", "url": "u"}]

    def level(video) -> float:  # the end of the video: the voice is over, only the track (if any) is heard
        r = subprocess.run([config.ffmpeg(), "-v", "info", "-ss", "8", "-i", str(video), "-af", "volumedetect", "-vn",
                            "-f", "null", "-"], capture_output=True, text=True)
        return float([ln for ln in r.stderr.splitlines() if "mean_volume" in ln][0].split(":")[1].split()[0])

    plain = render.render(plan, sources, nar, tmp_path / "plain", min_total=12.0)
    mixed = render.render(plan, sources, nar, tmp_path / "mixed", min_total=12.0,
                          music={"path": str(song), "volume": 0.25})
    info = json.loads(subprocess.run([config.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of",
                                      "json", mixed["video"]], capture_output=True, text=True).stdout)
    assert 11.5 < float(info["format"]["duration"]) < 13  # the looping track does not stretch the video
    assert (tmp_path / "mixed" / "final.mp4").stat().st_size > 0
    assert level(plain["video"]) < -60 < level(mixed["video"])  # the track plays on after the voice
