"""Xoá logo (motio/delogo.py): tự tìm logo đứng yên, khung hợp lệ, API cho nguồn dự án và file tải lên."""
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from motio import api, config, db, delogo

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}
has_ffmpeg = bool(config.find("ffmpeg") and config.find("ffprobe"))


def _frames(n=24, h=270, w=480, logo=True, bars=0, seed=0) -> np.ndarray:
    """Nền nhiễu mịn trôi ngang (máy quay lia) + logo viền trắng đứng yên ở góc trên phải."""
    rng = np.random.default_rng(seed)
    world = rng.integers(0, 256, (h, w + 4 * n)).astype(np.float32)
    world = (world + np.roll(world, 1, 0) + np.roll(world, 1, 1) + np.roll(world, 1, (0, 1))) / 4
    out = np.stack([world[:, 4 * i: 4 * i + w] for i in range(n)]).astype(np.uint8)
    if logo:
        out[:, 20:22, 380:460] = 255
        out[:, 48:50, 380:460] = 255
        out[:, 20:50, 380:382] = 255
        out[:, 20:50, 458:460] = 255
        out[:, 30:40, 395:445:6] = 255  # "chữ"
    if bars:
        out[:, :bars] = 0
        out[:, h - bars:] = 0
    return out


def _inside(box, x, y, w, h, scale=1.0):
    return (box["x"] <= x * scale and box["y"] <= y * scale and box["x"] + box["w"] >= (x + w) * scale
            and box["y"] + box["h"] >= (y + h) * scale)


def test_find_static_finds_the_logo_only():
    boxes, note = delogo.find_static(_frames(), scale=2.0)
    assert note is None and len(boxes) == 1
    b = boxes[0]
    assert _inside(b, 380, 20, 80, 30, scale=2.0)  # bao trọn logo
    assert b["w"] < 2.0 * 100 and b["h"] < 2.0 * 45  # và không lấn nhiều ra ngoài


def test_find_static_ignores_letterbox_bars():
    boxes, note = delogo.find_static(_frames(bars=12), scale=1.0)
    assert note is None and len(boxes) == 1 and _inside(boxes[0], 380, 20, 80, 30)


def test_find_static_without_logo_or_motion():
    assert delogo.find_static(_frames(logo=False))[0] == []
    still = np.repeat(_frames(n=1), 24, axis=0)  # hình đứng yên: mọi biên đều "tĩnh"
    boxes, note = delogo.find_static(still)
    assert boxes == [] and "đứng yên" in note
    assert delogo.find_static(_frames(n=3))[0] == []


def test_clamp_boxes():
    assert delogo.clamp_boxes([{"x": -5, "y": 0, "w": 50.4, "h": 20}], 640, 360) == [{"x": 1, "y": 1, "w": 44, "h": 19}]
    assert delogo.clamp_boxes([{"x": 600, "y": 340, "w": 80, "h": 80}], 640, 360) == [{"x": 600, "y": 340, "w": 39,
                                                                                         "h": 19}]
    for bad in ([], [{"x": 10, "y": 10, "w": 2, "h": 50}], [{"x": 700, "y": 10, "w": 20, "h": 20}], [{"x": "a"}],
                [{"x": 1, "y": 1, "w": 10, "h": 10}] * 5):
        with pytest.raises(ValueError):
            delogo.clamp_boxes(bad, 640, 360)


# ---------- API (FFmpeg giả) ----------
@pytest.fixture
def fake_ffmpeg(monkeypatch):
    calls = []

    def remove(src, dst, boxes, duration, progress=None):
        calls.append((Path(src), boxes))
        progress and progress(0.5)
        Path(dst).write_bytes(b"clean")
        return dst

    monkeypatch.setattr(delogo, "probe", lambda p: {"width": 640, "height": 360, "duration": 12.0})
    monkeypatch.setattr(delogo, "grab_frame", lambda src, at, out: (out.parent.mkdir(parents=True, exist_ok=True),
                                                                     out.write_bytes(b"jpg"), out)[-1])
    monkeypatch.setattr(delogo, "remove", remove)
    return calls


@pytest.fixture
def client():
    with db.conn() as c:
        c.execute("DELETE FROM project")
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


def _source_project(n=1, status="done") -> tuple[int, list[Path]]:
    src_dir = config.CACHE / "sources"
    src_dir.mkdir(parents=True, exist_ok=True)
    files, sources = [], []
    for i in range(n):
        f = src_dir / f"Douyin_{time.time_ns()}{i}.mp4"
        f.write_bytes(b"orig")
        f.with_suffix(".transcript.json").write_text(json.dumps({"segments": [], "language": "zh"}))
        files.append(f)
        sources.append({"path": str(f), "url": f"https://v.douyin.com/{f.stem}", "id": f.stem.split("_")[1],
                        "platform": "Douyin", "uploader": "chaîne", "title": "t", "duration": 12})
    pid = db.create_project(None, "Clip", mode="topic")
    db.update_project(pid, status=status, meta={"sources": sources, "rights": "unknown"})
    return pid, files


def _wait(client, key, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        v = client.get(f"/api/delogo/targets/{key}", headers=H).json()
        if v["status"] in ("done", "failed"):
            return v
        time.sleep(0.02)
    raise AssertionError("job did not finish")


BOX = [{"x": 500, "y": 20, "w": 120, "h": 40}]


def test_project_source_flow(client, fake_ffmpeg):
    pid, (orig,) = _source_project()
    key = f"p{pid}-0"
    v = client.post(f"/api/delogo/targets/{key}/frame", headers=H, json={}).json()
    assert v["kind"] == "source" and v["frame"] == f"projects/{pid}/delogo/0/frame.jpg" and v["frame_at"] == 1.2
    assert v["status"] == "idle" and v["output"] is None and v["name"] == "Douyin · chaîne"

    # phải xác nhận quyền trước khi chạy
    for body in ({"boxes": BOX}, {"boxes": BOX, "rights": "unknown"}, {"boxes": BOX, "rights": ""}):
        r = client.post(f"/api/delogo/targets/{key}/run", headers=H, json=body)
        assert r.status_code in (400, 422)
    assert not fake_ffmpeg

    r = client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX, "rights": "owned"})
    assert r.status_code == 202
    v = _wait(client, key)
    assert v["status"] == "done" and v["rights"] == "owned" and v["boxes"] == BOX
    assert v["output"] == f"projects/{pid}/delogo/0/clean.mp4"
    assert fake_ffmpeg[0][0] == orig
    p = db.get_project(pid)
    s = p["meta"]["sources"][0]
    clean = config.PROJECTS / str(pid) / "delogo" / "0" / "clean.mp4"
    assert s["path"] == str(clean) and s["orig_path"] == str(orig) and s["delogo"]["rights"] == "owned"
    assert p["meta"]["rights"] == "owned"  # nguồn duy nhất đã được xác nhận
    assert clean.with_suffix(".transcript.json").exists()  # không phải bóc lời lại
    assert "xác nhận quyền owned" in p["log"]
    assert client.get(f"/media/{v['output']}?token={TOKEN}").content == b"clean"

    # xoá logo lần nữa (thêm khung) vẫn đi từ video gốc
    client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX * 2, "rights": "licensed"})
    assert _wait(client, key)["rights"] == "licensed" and fake_ffmpeg[1][0] == orig

    v = client.delete(f"/api/delogo/targets/{key}/result", headers=H).json()
    assert v["status"] == "idle" and v["output"] is None and not clean.exists()
    s = db.get_project(pid)["meta"]["sources"][0]
    assert s["path"] == str(orig) and "orig_path" not in s and "delogo" not in s


def test_rights_follow_all_sources(client, fake_ffmpeg):
    pid, _ = _source_project(n=2)
    client.post(f"/api/delogo/targets/p{pid}-0/run", headers=H, json={"boxes": BOX, "rights": "licensed"})
    _wait(client, f"p{pid}-0")
    assert db.get_project(pid)["meta"]["rights"] == "unknown"  # nguồn thứ hai chưa được xác nhận
    client.post(f"/api/delogo/targets/p{pid}-1/run", headers=H, json={"boxes": BOX, "rights": "owned"})
    _wait(client, f"p{pid}-1")
    assert db.get_project(pid)["meta"]["rights"] == "licensed"


def test_busy_project_and_bad_targets(client, fake_ffmpeg):
    pid, _ = _source_project(status="running")
    r = client.post(f"/api/delogo/targets/p{pid}-0/run", headers=H, json={"boxes": BOX, "rights": "owned"})
    assert r.status_code == 409
    for key in (f"p{pid}-5", "p999999-0", "u" + "0" * 32, "../etc", "x"):
        assert client.get(f"/api/delogo/targets/{key}", headers=H).status_code == 404
    assert client.get(f"/api/delogo/targets/p{pid}-0").status_code == 401


def test_upload_flow(client, fake_ffmpeg):
    clip = ("mon clip.MOV", b"video-bytes", "video/quicktime")
    r = client.post("/api/delogo/uploads", headers=H, files={"file": clip})
    assert r.status_code == 201
    v = r.json()
    key = v["target"]
    folder = delogo.UPLOADS / key[1:]
    assert v["kind"] == "upload" and v["name"] == "mon clip.MOV"
    assert (folder / "input.mov").read_bytes() == b"video-bytes"
    assert v["frame"] == f"tools/delogo/{key[1:]}/frame.jpg"
    assert client.get("/api/delogo/uploads", headers=H).json()[0] == {
        "target": key, "name": "mon clip.MOV", "created_at": pytest.approx(time.time(), abs=10), "status": "idle"}

    client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX, "rights": "owned"})
    v = _wait(client, key)
    assert v["status"] == "done" and v["output"] == f"tools/delogo/{key[1:]}/clean.mp4" and v["rights"] == "owned"
    assert client.delete(f"/api/delogo/targets/{key}", headers=H).json() == {"deleted": key}
    assert not folder.exists()

    r = client.post("/api/delogo/uploads", headers=H, files={"file": ("notes.txt", b"x", "text/plain")})
    assert r.status_code == 400


def test_detect_route(client, monkeypatch, fake_ffmpeg):
    pid, _ = _source_project()
    monkeypatch.setattr(delogo, "sample_gray", lambda src, info: (_frames(), 640 / 480))
    r = client.post(f"/api/delogo/targets/p{pid}-0/detect", headers=H).json()
    assert r["note"] is None and len(r["boxes"]) == 1 and _inside(r["boxes"][0], 380, 20, 80, 30, 640 / 480)
    assert client.get(f"/api/delogo/targets/p{pid}-0", headers=H).json()["boxes"] == r["boxes"]


# ---------- FFmpeg thật ----------
@pytest.mark.skipif(not has_ffmpeg, reason="cần ffmpeg")
def test_detect_and_remove_real_video(tmp_path):
    frames = _frames(n=50, h=180, w=320, seed=3)
    frames[:, 20:50, 380 - 160:] = 0  # logo "_frames" nằm ngoài khung 320: vẽ lại một logo trong khung
    frames[:, 10:12, 230:300] = 255
    frames[:, 34:36, 230:300] = 255
    frames[:, 10:36, 230:232] = 255
    frames[:, 10:36, 298:300] = 255
    src = tmp_path / "logo.mp4"
    subprocess.run([config.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "320x180",
                    "-r", "25", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
                   input=frames.tobytes(), check=True)
    info = delogo.probe(src)
    assert (info["width"], info["height"]) == (320, 180) and info["duration"] == pytest.approx(2.0, abs=0.1)
    boxes, note = delogo.find_static(*delogo.sample_gray(src, info))
    assert note is None and len(boxes) == 1 and _inside(boxes[0], 230, 10, 70, 26)
    seen = []
    out = delogo.remove(src, tmp_path / "clean.mp4", delogo.clamp_boxes(boxes, 320, 180), info["duration"],
                        seen.append)
    assert delogo.probe(out)["width"] == 320 and seen and max(seen) <= 0.99
    after, _ = delogo.sample_gray(out, delogo.probe(out))
    assert after[:, 11, 240:290].mean() < 200  # đường viền trắng của logo đã bị lấp
    assert not (tmp_path / "clean.part.mp4").exists()
