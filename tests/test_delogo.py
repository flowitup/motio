"""Xoá logo (motio/delogo.py): tự tìm logo đứng yên, khung hợp lệ, API cho nguồn dự án và file tải lên, dừng."""
import json
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from motio import api, config, db, delogo, inpaint, pipeline

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
    assert boxes == [] and "barely moves" in note
    assert delogo.find_static(_frames(n=3))[0] == []


def test_clamp_boxes():
    assert delogo.clamp_boxes([{"x": -5, "y": 0, "w": 50.4, "h": 20}], 640, 360) == [{"x": 1, "y": 1, "w": 44, "h": 19}]
    assert delogo.clamp_boxes([{"x": 600, "y": 340, "w": 80, "h": 80}], 640, 360) == [{"x": 600, "y": 340, "w": 39,
                                                                                         "h": 19}]
    for bad in ([], [{"x": 10, "y": 10, "w": 2, "h": 50}], [{"x": 700, "y": 10, "w": 20, "h": 20}], [{"x": "a"}],
                [{"x": 1, "y": 1, "w": 10, "h": 10}] * 5):
        with pytest.raises(ValueError):
            delogo.clamp_boxes(bad, 640, 360)


# ---------- API (FFmpeg và mô hình giả) ----------
@pytest.fixture
def fake_ffmpeg(monkeypatch):
    calls = []

    def video(src, dst, boxes, info, progress=None, cancelled=lambda: False, ranges=None):
        calls.append((Path(src), boxes, ranges))
        progress and progress(150, 300)
        Path(dst).write_bytes(b"clean")
        return dst

    monkeypatch.setattr(delogo, "probe", lambda p: {"width": 640, "height": 360, "duration": 12.0, "fps": "25/1"})
    monkeypatch.setattr(delogo, "grab_frame", lambda src, at, out: (out.parent.mkdir(parents=True, exist_ok=True),
                                                                     out.write_bytes(b"jpg"), out)[-1])
    monkeypatch.setattr(inpaint, "video", video)
    monkeypatch.setattr(inpaint, "model_ready", lambda: True)
    return calls


@pytest.fixture
def client():
    with db.conn() as c:
        c.execute("DELETE FROM project")
    with TestClient(api.create_app(TOKEN)) as c:
        yield c


def _source_project(n=1, status="done", rendered=True) -> tuple[int, list[Path]]:
    """Dự án có n nguồn; rendered: đã dựng video final dùng mỗi nguồn một đoạn 2–5 s."""
    src_dir = config.CACHE / "sources"
    src_dir.mkdir(parents=True, exist_ok=True)
    files, sources = [], []
    for i in range(n):
        f = src_dir / f"Douyin_{time.time_ns()}{i}.mp4"
        f.write_bytes(b"orig")
        f.with_suffix(".transcript.json").write_text(json.dumps({"segments": [], "language": "zh"}), encoding="utf-8")
        files.append(f)
        sources.append({"path": str(f), "url": f"https://v.douyin.com/{f.stem}", "id": f.stem.split("_")[1],
                        "platform": "Douyin", "uploader": "chaîne", "title": "t", "duration": 12})
    pid = db.create_project(None, "Clip", mode="topic")
    db.update_project(pid, status=status, meta={"sources": sources, "rights": "unknown"})
    if rendered:
        _timeline(pid, [(i, 2.0, 3.0) for i in range(n)])
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

    # vẫn từ chối quyền khai báo không hợp lệ
    for body in ({"boxes": BOX, "rights": "unknown"}, {"boxes": BOX, "rights": ""}):
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
    assert "confirmed rights owned" in p["log"]
    assert client.get(f"/media/{v['output']}?token={TOKEN}").content == b"clean"

    # xoá logo lần nữa (thêm khung) vẫn đi từ video gốc
    client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX * 2, "rights": "licensed"})
    assert _wait(client, key)["rights"] == "licensed" and fake_ffmpeg[1][0] == orig

    v = client.delete(f"/api/delogo/targets/{key}/result", headers=H).json()
    assert v["status"] == "idle" and v["output"] is None and not clean.exists()
    s = db.get_project(pid)["meta"]["sources"][0]
    assert s["path"] == str(orig) and "orig_path" not in s and "delogo" not in s


@pytest.mark.parametrize("project_rights", ["unknown", "owned", "licensed", "cc"])
def test_run_without_rights_preserves_project_rights(client, fake_ffmpeg, project_rights):
    pid, _ = _source_project()
    db.update_project(pid, meta={"rights": project_rights})
    key = f"p{pid}-0"
    response = client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX})
    assert response.status_code == 202
    result = _wait(client, key)
    assert result["status"] == "done" and result["rights"] is None
    project = db.get_project(pid)
    assert project["meta"]["rights"] == project_rights
    assert project["meta"]["sources"][0]["delogo"]["rights"] is None
    assert "confirmed rights" not in project["log"]


@pytest.mark.parametrize("kind", ["source", "upload"])
@pytest.mark.parametrize("rights", [None, "owned", "licensed"])
def test_rerun_without_rights_preserves_saved_rights(client, fake_ffmpeg, kind, rights):
    if kind == "source":
        pid, _ = _source_project()
        key = f"p{pid}-0"
    else:
        response = client.post("/api/delogo/uploads", headers=H,
                               files={"file": ("clip.mp4", b"video", "video/mp4")})
        assert response.status_code == 201
        key = response.json()["target"]
    body = {"boxes": BOX}
    if rights is not None:
        body["rights"] = rights
    assert client.post(f"/api/delogo/targets/{key}/run", headers=H, json=body).status_code == 202
    assert _wait(client, key)["rights"] == rights
    if kind == "source":
        db.update_project(pid, meta={"rights": "cc"})
        previous_log = db.get_project(pid)["log"]
    assert client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX * 2}).status_code == 202
    result = _wait(client, key)
    assert result["status"] == "done" and result["rights"] == rights and result["boxes"] == BOX * 2
    if kind == "source":
        project = db.get_project(pid)
        assert project["meta"]["rights"] == "cc"
        assert "confirmed rights" not in project["log"][len(previous_log):]


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


# ---------- LaMa: vùng cắt, dán lại, tải mô hình (mô hình giả) ----------
class FakeLama:
    """Thay mô hình: tô vùng mặt nạ bằng màu trung bình của phần nền. Đếm số lần chạy."""

    def __init__(self):
        self.runs = 0
        self.sizes = []

    def run(self, _outputs, feed):
        self.runs += 1
        img, mask = feed["image"], feed["mask"]
        self.sizes.append(img.shape[2:])
        assert img.dtype == mask.dtype == np.float32 and img.max() <= 1.0
        assert img.shape[3] % 16 == 0 and img.shape[2] % 8 == 0  # cỡ mô hình nhận được
        keep = mask[0, 0] == 0
        fill = np.stack([c[keep].mean() for c in img[0]])[:, None, None]
        return [np.where(mask[0] > 0, fill, img[0])[None] * 255]


def _logo_frame(h=360, w=640, seed=1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    frame = (rng.integers(90, 110, (h, w, 3))).astype(np.uint8)
    frame[20:60, 500:620] = 255
    return frame


def test_patch_geometry_and_fill():
    frame = _logo_frame()
    before = frame.copy()
    p = inpaint.Patch({"x": 500, "y": 20, "w": 120, "h": 40}, 640, 360)
    assert 0 <= p.x0 < 500 and p.x1 <= 640 and 0 <= p.y0 < 20 and p.y1 > 60  # vùng cắt có lề, nằm trong khung
    tw, th = p.size
    assert tw % 16 == 0 and th % 8 == 0 and max(tw, th) <= inpaint.WORK + 16
    assert p.alpha[20 - p.y0:60 - p.y0, 500 - p.x0:620 - p.x0].min() == 1  # cả khung được vẽ lại
    lama = FakeLama()
    assert p.apply(frame, lama) and lama.runs == 1
    assert abs(frame[20:60, 500:620].astype(int).mean() - 100) < 4  # logo trắng → màu nền
    assert (frame[:, :400] == before[:, :400]).all() and (frame[100:] == before[100:]).all()  # ngoài viền giữ nguyên
    # cảnh không đổi: dùng lại lần vẽ trước, không chạy mô hình
    again = before.copy()
    assert not p.apply(again, lama) and lama.runs == 1 and (again == frame).all()
    # nền quanh logo đổi hẳn: vẽ lại
    moved = before.copy()
    moved[:20] = 30
    assert p.apply(moved, lama) and lama.runs == 2


def test_patch_at_frame_edge_and_big_logo():
    p = inpaint.Patch({"x": 1, "y": 1, "w": 1000, "h": 300}, 1080, 1920)
    assert (p.x0, p.y0) == (0, 0) and p.x1 == 1080
    assert max(p.size) <= inpaint.WORK + 16  # logo lớn: thu nhỏ về cỡ làm việc
    frame = np.full((1920, 1080, 3), 100, np.uint8)
    frame[1:301, 1:1001] = 255
    p.apply(frame, FakeLama())
    assert frame[1:301, 1:1001].mean() < 110


class _FakeStream:
    def __init__(self, body: bytes, status=200):
        self.body, self.status_code, self.headers = body, status, {"content-length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "x"), response=httpx.Response(404))

    def iter_bytes(self, _n):
        yield self.body


def test_model_download_is_checked(monkeypatch):
    seen = []
    monkeypatch.setattr(inpaint.httpx, "stream", lambda *a, **k: _FakeStream(b"not the model"))
    with pytest.raises(RuntimeError, match="sha256"):
        inpaint.ensure_model(seen.append)
    assert seen == [1.0] and not inpaint.model_ready()
    assert not list(inpaint.model_path().parent.glob("*.part"))
    monkeypatch.setattr(inpaint.httpx, "stream", lambda *a, **k: _FakeStream(b"", status=404))
    with pytest.raises(RuntimeError, match="Could not download"):
        inpaint.ensure_model()


def test_first_run_downloads_model_then_fills(client, fake_ffmpeg, monkeypatch):
    ready = {"ok": False}
    order = []

    def ensure(progress):
        order.append("model")
        progress(0.5)
        ready["ok"] = True

    monkeypatch.setattr(inpaint, "model_ready", lambda: ready["ok"])
    monkeypatch.setattr(inpaint, "ensure_model", ensure)
    pid, _ = _source_project()
    key = f"p{pid}-0"
    assert client.get(f"/api/delogo/targets/{key}", headers=H).json()["model_ready"] is False
    client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX, "rights": "owned"})
    v = _wait(client, key)
    assert v["status"] == "done" and v["model_ready"] is True and order == ["model"] and fake_ffmpeg
    assert db.get_project(pid)["meta"]["sources"][0]["delogo"]["method"] == "lama"


def test_stop_a_running_job(client, fake_ffmpeg, monkeypatch):
    started = threading.Event()

    def slow(src, dst, boxes, info, progress=None, cancelled=lambda: False, ranges=None):
        for i in range(1, 500):
            started.set()
            if cancelled():
                raise inpaint.Cancelled("stop")
            progress(i, 1000)
            time.sleep(0.01)
        raise AssertionError("never cancelled")

    monkeypatch.setattr(inpaint, "video", slow)
    pid, _ = _source_project()
    key = f"p{pid}-0"
    assert client.post(f"/api/delogo/targets/{key}/cancel", headers=H).status_code == 400  # không có gì để dừng
    client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX, "rights": "owned"})
    assert started.wait(5)
    time.sleep(0.2)
    v = client.get(f"/api/delogo/targets/{key}", headers=H).json()
    assert v["status"] == "running" and v["phase"] == "fill" and v["pct"] > 0 and v["eta"] is not None
    v = client.post(f"/api/delogo/targets/{key}/cancel", headers=H).json()
    assert v["stopping"] is True
    end = time.time() + 5
    while client.get(f"/api/delogo/targets/{key}", headers=H).json()["status"] != "idle":
        assert time.time() < end
        time.sleep(0.02)
    p = db.get_project(pid)
    assert "delogo" not in p["meta"]["sources"][0] and "Stopped removing the logo" in p["log"]


def _timeline(pid: int, pieces: list[tuple[int, float, float]], url: str | None = "same") -> None:
    """Giả lần dựng gần nhất: timeline.json như render ghi (src, src_start, dur, t0, url)."""
    sources = db.get_project(pid)["meta"]["sources"]
    out = config.PROJECTS / str(pid)
    out.mkdir(parents=True, exist_ok=True)
    rows = [{"src": i, "src_start": a, "dur": d, "t0": 0.0, **({"url": sources[i]["url"] if url == "same" else url}
                                                              if url is not None else {})} for i, a, d in pieces]
    (out / "timeline.json").write_text(json.dumps(rows), encoding="utf-8")


def test_merge_pads_joins_and_clamps():
    assert delogo.merge([(5.0, 8.0), (2.0, 3.0), (10.0, 11.0)], 12.0) == [[1.0, 12.0]]
    assert delogo.merge([(0.2, 1.0), (7.0, 8.0)], 9.5) == [[0.0, 4.0], [6.0, 9.5]]
    assert delogo.merge([(20.0, 25.0)], 12.0) == []
    assert delogo.merge([], 12.0) == []


def test_only_used_parts_of_a_project_source(client, fake_ffmpeg):
    pid, _ = _source_project(n=2, rendered=False)
    key = f"p{pid}-0"
    v = client.get(f"/api/delogo/targets/{key}", headers=H).json()
    assert v["used"] is None  # chưa dựng
    r = client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX})
    assert r.status_code == 400 and "render the video first" in r.json()["detail"] and not fake_ffmpeg

    _timeline(pid, [(0, 2.0, 1.5), (1, 4.0, 3.0), (0, 3.5, 1.0), (0, 11.0, 0.5)])
    v = client.get(f"/api/delogo/targets/{key}", headers=H).json()
    assert v["used"] == [[1.0, 7.5], [10.0, 12.0]] and v["uncovered"] == []
    for body in ({"scope": "all"}, {"scope": "range", "start": 0, "end": 5}):  # nguồn dự án: chỉ đoạn final dùng
        r = client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX, **body})
        assert r.status_code == 400 and "parts the final video uses" in r.json()["detail"]
    assert client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX}).status_code == 202
    v = _wait(client, key)
    assert v["status"] == "done" and v["ranges"] == [[1.0, 7.5], [10.0, 12.0]] and v["scope"] == "used"
    assert fake_ffmpeg[-1][2] == [[1.0, 7.5], [10.0, 12.0]]
    p = db.get_project(pid)
    assert p["meta"]["sources"][0]["delogo"]["ranges"] == [[1.0, 7.5], [10.0, 12.0]]
    assert "2 parts, 8 s / 12 s" in p["log"]
    assert delogo.uncovered(pid) == []

    # dựng lại dùng một đoạn khác của nguồn 0: báo đoạn chưa xoá, không tự chạy
    _timeline(pid, [(0, 2.0, 1.5), (0, 7.4, 0.8)])
    assert client.get(f"/api/delogo/targets/{key}", headers=H).json()["uncovered"] == [[7.4, 8.2]]
    assert delogo.uncovered(pid) == [(0, [[7.4, 8.2]])]
    # nguồn đã đổi (url khác) thì timeline cũ không tính
    _timeline(pid, [(0, 2.0, 1.5)], url="https://other")
    assert client.get(f"/api/delogo/targets/{key}", headers=H).json()["used"] is None
    # timeline cũ không ghi url: tin theo số thứ tự
    _timeline(pid, [(0, 2.0, 1.5)], url=None)
    assert client.get(f"/api/delogo/targets/{key}", headers=H).json()["used"] == [[1.0, 6.5]]


def test_pick_a_range_or_the_whole_video(client, fake_ffmpeg):
    r = client.post("/api/delogo/uploads", headers=H, files={"file": ("clip.mp4", b"video", "video/mp4")})
    key = r.json()["target"]
    assert r.json()["used"] is None
    for body in ({"scope": "used"}, {"scope": "range", "start": 5, "end": 5.2}, {"scope": "range"},
                 {"scope": "nope"}):
        r = client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX, **body})
        assert r.status_code == 400, body
    assert not fake_ffmpeg
    r = client.post(f"/api/delogo/targets/{key}/run", headers=H,
                    json={"boxes": BOX, "scope": "range", "start": 3, "end": 40})
    assert r.status_code == 202
    v = _wait(client, key)
    assert v["ranges"] == [[3.0, 12.0]] and v["span"] == [3.0, 12.0] and fake_ffmpeg[-1][2] == [[3.0, 12.0]]
    client.post(f"/api/delogo/targets/{key}/run", headers=H, json={"boxes": BOX})  # mặc định: cả video
    v = _wait(client, key)
    assert v["ranges"] is None and v["scope"] == "all" and fake_ffmpeg[-1][2] is None


def test_pipeline_warns_about_uncleaned_parts(monkeypatch):
    pid, _ = _source_project()
    s = db.get_project(pid)["meta"]["sources"]
    s[0]["delogo"] = {"boxes": BOX, "rights": None, "method": "lama", "at": 0, "ranges": [[1.0, 5.0]]}
    db.update_project(pid, meta={"sources": s})
    logs = []

    def render(plan, sources, nar, out, progress=None, min_total=0, badge="", wide=False):
        _timeline(pid, [(0, 2.0, 2.0), (0, 70.0, 5.0)])
        return {"pieces": 2, "duration": 70.0}

    monkeypatch.setattr(pipeline, "_voice", lambda plan, out, step, d, voice=None: (
        plan, {"duration": 66.0, "provider": "x", "voice": "v"}))
    monkeypatch.setattr(pipeline.render, "render", render)
    monkeypatch.setattr(pipeline, "write_post", lambda plan, sources, out, **kw: "desc")
    pipeline._voice_render_post(pid, {"title_fr": "t", "lines": []}, s, config.PROJECTS / str(pid),
                                lambda *a, **k: logs.append(a), time.time())
    assert any("Source #1" in (a[2] or "") and "1:10–1:15" in a[2] for a in logs)


# ---------- FFmpeg thật (mô hình giả) ----------
def _make_clip(path: Path, frames: np.ndarray, audio=True) -> None:
    n, h, w = frames.shape[:3]
    cmd = [config.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", "25",
           "-i", "-"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f=440:d={n / 25}", "-c:a", "aac"]
    subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-colorspace", "bt709", str(path)],
                   input=frames.tobytes(), check=True)


def _gray(path: Path, w=320, h=180) -> np.ndarray:
    r = subprocess.run([config.ffmpeg(), "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, h, w)


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
def test_detect_and_remove_real_video(tmp_path, monkeypatch):
    frames = _frames(n=50, h=180, w=320, seed=3)
    frames[:, 20:50, 380 - 160:] = 0  # logo "_frames" nằm ngoài khung 320: vẽ lại một logo trong khung
    frames[:, 10:12, 230:300] = 255
    frames[:, 34:36, 230:300] = 255
    frames[:, 10:36, 230:232] = 255
    frames[:, 10:36, 298:300] = 255
    src = tmp_path / "logo.mp4"
    _make_clip(src, frames)
    info = delogo.probe(src)
    assert (info["width"], info["height"]) == (320, 180) and info["duration"] == pytest.approx(2.0, abs=0.1)
    assert info["fps"] == "25/1" and info["color_space"] == "bt709"
    boxes, note = delogo.find_static(*delogo.sample_gray(src, info))
    assert note is None and len(boxes) == 1 and _inside(boxes[0], 230, 10, 70, 26)
    lama = FakeLama()
    monkeypatch.setattr(inpaint, "session", lambda: lama)
    seen = []
    out = inpaint.video(src, tmp_path / "clean.mp4", delogo.clamp_boxes(boxes, 320, 180), info,
                        lambda done, total: seen.append((done, total)))
    got = delogo.probe(out)
    assert (got["width"], got["height"], got["color_space"]) == (320, 180, "bt709") and got["duration"] > 1.9
    assert seen[-1][0] == 50 and lama.runs >= 1
    r = subprocess.run([config.ffprobe(), "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                        str(out)], capture_output=True, text=True)
    assert r.stdout.split() == ["video", "audio"]  # giữ tiếng
    before, after = _gray(src), _gray(out)
    assert len(after) == len(before) == 50
    assert after[:, 11, 240:290].mean() < 200  # đường viền trắng của logo đã bị lấp
    assert np.abs(after[:, 90:].astype(int) - before[:, 90:]).mean() < 4  # phần không vá giữ nguyên (chỉ mã hoá lại)
    assert not (tmp_path / "clean.part.mp4").exists()


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
def test_fill_only_the_given_ranges(tmp_path, monkeypatch):
    frames = _frames(n=50, h=180, w=320, seed=4)
    frames[:, 10:12, 230:300] = 255  # đường viền trắng của logo
    src = tmp_path / "logo.mp4"
    _make_clip(src, frames, audio=False)
    monkeypatch.setattr(inpaint, "session", FakeLama)
    seen = []
    out = inpaint.video(src, tmp_path / "clean.mp4", [{"x": 230, "y": 6, "w": 70, "h": 10}], delogo.probe(src),
                        lambda done, total: seen.append((done, total)), ranges=[(0.4, 0.8), (1.6, 5.0)])
    after = _gray(out)
    assert len(after) == 50 and seen[-1] == (20, 20)  # khung 10–19 và 40–49 (0,4–0,8 s; 1,6 s tới hết)
    line = after[:, 11, 240:290].mean(axis=1)
    assert (line[10:20] < 200).all() and (line[40:] < 200).all()
    assert (line[:10] > 230).all() and (line[20:40] > 230).all()  # ngoài khoảng: logo còn nguyên


def test_frame_spans():
    assert inpaint.frame_spans(None, 25, 100) == [(0, 100)]
    assert inpaint.frame_spans([(1.0, 2.0), (0.0, 0.5), (1.5, 3.0)], 10, 100) == [(0, 5), (10, 30)]
    assert inpaint.frame_spans([(8.0, 20.0)], 10, 100) == [(80, 100)]
    assert inpaint.frame_spans([(20.0, 30.0)], 10, 100) == []


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
def test_video_cancel_leaves_nothing(tmp_path, monkeypatch):
    src = tmp_path / "clip.mp4"
    _make_clip(src, _frames(n=40, h=180, w=320), audio=False)
    monkeypatch.setattr(inpaint, "session", FakeLama)
    calls = []
    with pytest.raises(inpaint.Cancelled):
        inpaint.video(src, tmp_path / "clean.mp4", [{"x": 230, "y": 10, "w": 70, "h": 26}], delogo.probe(src),
                      cancelled=lambda: calls.append(1) or len(calls) > 3)
    assert not (tmp_path / "clean.mp4").exists() and not (tmp_path / "clean.part.mp4").exists()
