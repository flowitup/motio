"""Xoá logo / watermark đứng yên khỏi một video: vẽ khung, hoặc tự tìm logo tĩnh; LaMa (inpaint.py) vẽ lại chỗ đó.

Chỉ chạy khi người dùng chọn một video. Giữ quyền đã khai báo nếu có (owned | licensed).
Không bao giờ tự chạy trong pipeline (tin hot, chủ đề), không chạy hàng loạt.

Đích (target):
- "p<dự án>-<số thứ tự nguồn>": một video nguồn của dự án. Bản sạch nằm ở data/projects/<id>/delogo/<i>/clean.mp4
  và thay nguồn đó cho lần dựng sau; bản gốc vẫn ở cache, khôi phục được.
- "u<hex>": một file tải lên, ở data/tools/delogo/<hex>/ (input.*, clean.mp4).
"""
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import config, db, inpaint

RIGHTS = ("owned", "licensed")  # khai báo quyền tuỳ chọn từ client cũ
MAX_BOXES = 4
MIN_SIDE = 4  # px, cạnh nhỏ nhất của một khung
UPLOADS = config.DATA / "tools" / "delogo"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")
MAX_UPLOAD = 2 * 1024**3
BUSY = ("queued", "running")

# Tự tìm logo: khung hình xám thu nhỏ, lấy mẫu đều trong tối đa 3 phút đầu
SAMPLES = 32
SMALL_W = 480
EDGE = 24  # độ chênh sáng (0–255) giữa hai điểm ảnh liền nhau để tính là biên
PERSIST = 0.6  # biên có mặt ở cùng chỗ trong ≥ 60 % khung hình
MIN_MOTION = 0.2  # ít nhất 20 % điểm ảnh phải thay đổi, không thì không phân biệt được logo với hình


class NotFound(LookupError):
    pass


class Busy(RuntimeError):
    pass


_jobs: dict[str, dict] = {}  # target → {status: queued|running|failed, pct, error}
_lock = threading.Lock()


# ---------- FFmpeg ----------
@lru_cache(maxsize=64)
def _probe(path: str, _mtime: int, _size: int) -> dict:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,avg_frame_rate,r_frame_rate,color_space,color_primaries,color_transfer"
                        ":stream_side_data=rotation:stream_tags=rotate:format=duration",
                        "-of", "json", path], capture_output=True, text=True)
    data = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
    streams = data.get("streams") or []
    if not streams or not streams[0].get("width"):
        raise ValueError("Không đọc được hình của video này")
    s = streams[0]
    w, h = int(s["width"]), int(s["height"])
    rot = next((int(float(d["rotation"])) for d in s.get("side_data_list") or [] if "rotation" in d), 0)
    rot = rot or int(float((s.get("tags") or {}).get("rotate") or 0))
    if abs(rot) % 180 == 90:  # video quay dọc: FFmpeg tự xoay khi giải mã, toạ độ theo hình đã xoay
        w, h = h, w
    fps = next((f for f in (s.get("avg_frame_rate"), s.get("r_frame_rate")) if f and 1 <= inpaint.fps_value(f) <= 120),
               "30")
    return {"width": w, "height": h, "duration": round(float((data.get("format") or {}).get("duration") or 0), 3),
            "fps": fps, **{k: s[k] for k in ("color_space", "color_primaries", "color_transfer") if s.get(k)}}


def probe(path: Path) -> dict:
    """{width, height, duration, fps, color_*} theo hình hiển thị (đã xoay)."""
    st = Path(path).stat()
    return _probe(str(path), st.st_mtime_ns, st.st_size)


def grab_frame(src: Path, at: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(src), "-frames:v", "1",
                        "-q:v", "3", str(out)], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"Không lấy được khung hình: {r.stderr[-300:]}")
    return out


def sample_gray(src: Path, info: dict, n: int = SAMPLES, small: int = SMALL_W) -> tuple[np.ndarray, float]:
    """n khung hình xám thu nhỏ rải đều. Trả (mảng [n, h, w] uint8, hệ số từ mẫu về khung gốc)."""
    sw = max(2, min(small, info["width"]) // 2 * 2)
    sh = max(2, round(info["height"] * sw / info["width"] / 2) * 2)
    span = min(info["duration"] or 60.0, 180.0)
    r = subprocess.run([config.ffmpeg(), "-v", "error", "-t", f"{span:.3f}", "-i", str(src), "-an", "-sn",
                        "-vf", f"fps={n / max(span, 0.5):.5f},scale={sw}:{sh},format=gray", "-frames:v", str(n),
                        "-f", "rawvideo", "-"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg không đọc được video: {r.stderr.decode(errors='replace')[-300:]}")
    buf = np.frombuffer(r.stdout, np.uint8)
    k = buf.size // (sw * sh)
    return buf[: k * sw * sh].reshape(k, sh, sw), info["width"] / sw


# ---------- khung ----------
def clamp_boxes(raw: list[dict], width: int, height: int) -> list[dict]:
    """Khung (pixel của khung hình) → khung hợp lệ: nằm trong khung hình (cách mép 1 px), cạnh ≥ MIN_SIDE."""
    if not raw:
        raise ValueError("Chưa có khung nào: vẽ khung quanh logo hoặc bấm Tự tìm")
    if len(raw) > MAX_BOXES:
        raise ValueError(f"Tối đa {MAX_BOXES} khung")
    out = []
    for b in raw:
        try:
            x, y, w, h = (round(float(b[k])) for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError("Khung không hợp lệ") from e
        x0, y0 = max(x, 1), max(y, 1)
        x1, y1 = min(x + w, width - 1), min(y + h, height - 1)
        if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
            raise ValueError("Khung quá nhỏ hoặc nằm ngoài khung hình")
        out.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    return out


def _dilate(m: np.ndarray, r: int) -> np.ndarray:
    out = m.copy()
    for s in range(1, r + 1):
        out[s:, :] |= m[:-s, :]
        out[:-s, :] |= m[s:, :]
    rows = out.copy()
    for s in range(1, r + 1):
        out[:, s:] |= rows[:, :-s]
        out[:, :-s] |= rows[:, s:]
    return out


def _local_count(m: np.ndarray, r: int) -> np.ndarray:
    """Số điểm True trong ô (2r+1)² quanh mỗi điểm (ảnh tích phân)."""
    p = np.pad(m.astype(np.int32), r)
    c = np.zeros((p.shape[0] + 1, p.shape[1] + 1), np.int32)
    c[1:, 1:] = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def _components(m: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Các vùng liền nhau (4 hướng) của mặt nạ: [(y0, x0, y1, x1)], y1/x1 không tính."""
    seen = np.zeros_like(m, dtype=bool)
    h, w = m.shape
    out = []
    for y, x in zip(*np.nonzero(m), strict=True):
        if seen[y, x]:
            continue
        seen[y, x] = True
        stack, y0, x0, y1, x1 = [(y, x)], y, x, y, x
        while stack:
            cy, cx = stack.pop()
            y0, x0, y1, x1 = min(y0, cy), min(x0, cx), max(y1, cy), max(x1, cx)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < h and 0 <= nx < w and m[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append((int(y0), int(x0), int(y1) + 1, int(x1) + 1))
    return out


def find_static(frames: np.ndarray, scale: float = 1.0) -> tuple[list[dict], str | None]:
    """Tìm logo đứng yên: biên của nó ở cùng một chỗ trong hầu hết khung hình, còn hình phía sau thì thay đổi.

    frames: [n, h, w] uint8 xám. Trả (khung theo pixel gốc = pixel mẫu × scale, rõ nhất trước; lý do nếu không tìm).
    """
    n, h, w = frames.shape
    if n < 6:
        return [], "Video quá ngắn để tự tìm logo: hãy vẽ khung bằng tay"
    f = frames.astype(np.int16)
    if (f.std(axis=0) > 10).mean() < MIN_MOTION:
        return [], "Hình gần như đứng yên nên không tách được logo: hãy vẽ khung bằng tay"
    gx, gy = np.diff(f, axis=2)[:, :-1, :], np.diff(f, axis=1)[:, :, :-1]
    # biên cùng chiều ở cùng chỗ qua các khung; biên của hình chuyển động thì triệt tiêu nhau khi lấy trung bình
    steady = np.maximum(np.abs(gx.mean(axis=0)), np.abs(gy.mean(axis=0)))
    present = (np.maximum(np.abs(gx), np.abs(gy)) > EDGE).mean(axis=0)
    static = (steady > EDGE) & (present >= PERSIST)
    static &= _local_count(static, 2) >= 4  # bỏ điểm lẻ (hình có nhiều chi tiết trùng hợp đứng yên)
    static[static.mean(axis=1) > 0.5, :] = False  # mép viền đen / khung: đường thẳng dài gần hết khung hình
    static[:, static.mean(axis=0) > 0.5] = False
    if static.mean() > 0.15:
        return [], "Quá nhiều chi tiết đứng yên (khung cố định, viền đen…): hãy vẽ khung bằng tay"
    r = max(2, w // 60)  # nối các chữ của một logo thành một khối
    found = []
    for y0, x0, y1, x1 in _components(_dilate(static, r)):
        if x1 - x0 > 0.6 * w or y1 - y0 > 0.4 * h:  # viền đen, dải ngang / dọc cả khung: không phải logo
            continue
        ys, xs = np.nonzero(static[y0:y1, x0:x1])
        if ys.size == 0:
            continue
        ty0, tx0, ty1, tx1 = y0 + ys.min(), x0 + xs.min(), y0 + ys.max() + 2, x0 + xs.max() + 2
        if min(ty1 - ty0, tx1 - tx0) < 3 or (ty1 - ty0) * (tx1 - tx0) < 0.0005 * w * h:
            continue
        found.append((float(steady[y0:y1, x0:x1][static[y0:y1, x0:x1]].sum()), ty0, tx0, ty1, tx1))
    found.sort(reverse=True)
    pad = 4  # px mẫu quanh logo: phủ cả viền mờ và nền mờ của logo (phần sót lại, LaMa sẽ vẽ tiếp)
    boxes = [{"x": round((x0 - pad) * scale), "y": round((y0 - pad) * scale),
              "w": round((x1 - x0 + 2 * pad) * scale), "h": round((y1 - y0 + 2 * pad) * scale)}
             for _, y0, x0, y1, x1 in found[:MAX_BOXES]]
    return boxes, None if boxes else "Không thấy logo đứng yên: hãy vẽ khung bằng tay"


# ---------- đích ----------
@dataclass
class Target:
    key: str
    src: Path  # video gốc để xoá logo
    work: Path  # frame.jpg, clean.mp4, state.json
    name: str
    pid: int | None = None
    index: int | None = None
    url: str | None = None


def _source_file(s: dict) -> Path:
    """File gốc của một nguồn dự án; bị dời thì tìm lại trong cache theo id video (như pipeline)."""
    path = Path(s.get("orig_path") or s.get("path") or "")
    if path.is_file():
        return path
    vid = s.get("id") or str(s.get("url", "")).rsplit("=", 1)[-1]
    hits = sorted((config.CACHE / "sources").glob(f"*_{vid}.mp4")) if vid else []
    if not hits:
        raise NotFound("Mất file video nguồn: chạy lại dự án từ bước Tải video")
    return hits[0]


def resolve(key: str) -> Target:
    if m := re.fullmatch(r"p(\d+)-(\d+)", key):
        pid, i = int(m[1]), int(m[2])
        p = db.get_project(pid)
        sources = (p or {}).get("meta", {}).get("sources") or []
        if not p or i >= len(sources):
            raise NotFound("Không có video nguồn này")
        s = sources[i]
        name = " · ".join(x for x in (s.get("platform"), s.get("uploader") or s.get("title")) if x) or s["url"]
        return Target(key, _source_file(s), config.PROJECTS / str(pid) / "delogo" / str(i), name, pid, i, s["url"])
    if m := re.fullmatch(r"u([0-9a-f]{32})", key):
        d = UPLOADS / m[1]
        st = _state(d)
        if not st.get("file") or not (d / st["file"]).is_file():
            raise NotFound("Không có file này")
        return Target(key, d / st["file"], d, st.get("name") or st["file"])
    raise NotFound("Không có video này")


def _state(work: Path) -> dict:
    try:
        return json.loads((work / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(work: Path, **changes) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    st = {**_state(work), **changes}
    # Ghi file tạm rồi thay: job nền ghi trong lúc UI đang đọc, không để ai thấy state.json dở dang.
    tmp = work / f"state.{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    for attempt in range(5):
        try:
            tmp.replace(work / "state.json")
            break
        except PermissionError:  # Windows: file đang được đọc thì chưa thay được
            if attempt == 4:
                raise
            time.sleep(0.05)
    return st


def _rel(path: Path) -> str:
    return path.resolve().relative_to(config.DATA.resolve()).as_posix()


def view(key: str) -> dict:
    t = resolve(key)
    info = probe(t.src)
    st = _state(t.work)
    job = _jobs.get(key)
    out = t.work / "clean.mp4"
    record = None
    if t.pid is not None:
        s = db.get_project(t.pid)["meta"]["sources"][t.index]
        record = s.get("delogo") if s.get("path") == str(out) else None
    else:
        record = st.get("done") if st.get("done") else None
    done = bool(record) and out.is_file()
    frame = t.work / "frame.jpg"
    return {
        "target": key, "kind": "source" if t.pid is not None else "upload", "name": t.name,
        "project_id": t.pid, "index": t.index, "url": t.url,
        "width": info["width"], "height": info["height"], "duration": info["duration"],
        "frame": _rel(frame) if frame.is_file() else None, "frame_at": st.get("frame_at"),
        "boxes": (record or {}).get("boxes") or st.get("boxes") or [],
        "rights": (record or {}).get("rights") or st.get("rights"),
        "status": job["status"] if job else ("done" if done else "idle"),
        "pct": job["pct"] if job else (100 if done else 0), "error": job.get("error") if job else None,
        "phase": job.get("phase") if job else None, "eta": job.get("eta") if job else None,
        "stopping": bool(job and job.get("cancel")), "model_ready": inpaint.model_ready(),
        "output": _rel(out) if done else None, "done_at": (record or {}).get("at"),
        "folder": str(t.work),
    }


def frame(key: str, at: float | None = None) -> dict:
    """Lấy một khung hình (mặc định ở 10 % độ dài) để vẽ khung quanh logo."""
    t = resolve(key)
    dur = probe(t.src)["duration"]
    at = dur * 0.1 if at is None else at
    at = round(min(max(at, 0.0), max(dur - 0.25, 0.0)), 2)
    grab_frame(t.src, at, t.work / "frame.jpg")
    _save_state(t.work, frame_at=at)
    return view(key)


def detect(key: str) -> dict:
    """Tự tìm logo đứng yên. Trả {boxes, note}; note giải thích khi không tìm được."""
    t = resolve(key)
    info = probe(t.src)
    frames, scale = sample_gray(t.src, info)
    boxes, note = find_static(frames, scale)
    boxes = [b for b in (_try_clamp(b, info) for b in boxes) if b]
    if boxes:
        _save_state(t.work, boxes=boxes)
    return {"boxes": boxes, "note": note}


def _try_clamp(b: dict, info: dict) -> dict | None:
    try:
        return clamp_boxes([b], info["width"], info["height"])[0]
    except ValueError:
        return None


def start(key: str, boxes: list[dict], rights: str | None, submit: Callable[[Callable[[], None]], object]) -> dict:
    """Xếp hàng xoá logo; quyền khai báo là tuỳ chọn, giữ quyền đã lưu khi bỏ qua."""
    if rights is not None and rights not in RIGHTS:
        raise ValueError("Quyền nguồn không hợp lệ")
    t = resolve(key)
    info = probe(t.src)
    boxes = clamp_boxes(boxes, info["width"], info["height"])
    if t.pid is not None and db.get_project(t.pid)["status"] in BUSY:
        raise Busy("Dự án đang chạy, chờ xong rồi thử lại")
    update_rights = rights is not None
    declaration = f"người dùng xác nhận quyền {rights}, " if update_rights else ""
    if rights is None:
        rights = view(key)["rights"]
    with _lock:
        if key in _jobs and _jobs[key]["status"] in BUSY:
            raise Busy("Video này đang được xoá logo")
        job = _jobs[key] = {"status": "queued", "pct": 0, "error": None}
    _save_state(t.work, boxes=boxes, rights=rights)
    if t.pid is not None:
        db.update_project(t.pid, log=f"Xoá logo nguồn #{t.index + 1} ({t.name}): "
                                     f"{declaration}{len(boxes)} khung")
    submit(lambda: run(key, boxes, rights, t.url, job, update_rights=update_rights))
    return view(key)


def run(key: str, boxes: list[dict], rights: str | None, url: str | None = None, job: dict | None = None,
        *, update_rights: bool = True) -> None:
    job = job if job is not None else _jobs.setdefault(key, {"status": "queued", "pct": 0, "error": None})

    def finish() -> None:
        with _lock:
            if _jobs.get(key) is job:
                _jobs.pop(key)

    if job.get("cancel"):  # dừng khi còn đang chờ
        return finish()
    job.update(status="running", pct=0, phase="fill", eta=None)
    try:
        t = resolve(key)
        if t.url != url:
            raise RuntimeError("Nguồn của dự án đã đổi trong lúc chờ: chọn lại video")
        out = t.work / "clean.mp4"
        t.work.mkdir(parents=True, exist_ok=True)
        if not inpaint.model_ready():  # lần đầu: tải mô hình AI
            job.update(phase="model")
            inpaint.ensure_model(lambda f: job.update(pct=int(f * 100)))
            job.update(phase="fill", pct=0)
        started = time.monotonic()

        def tick(done: int, total: int) -> None:
            spent = time.monotonic() - started
            eta = round(spent * (total - done) / done) if done >= 10 else None  # giây còn lại, ước tính
            job.update(pct=min(done * 100 // total, 99), eta=eta)

        inpaint.video(t.src, out, boxes, probe(t.src), tick, lambda: bool(job.get("cancel")))
        record = {"boxes": boxes, "rights": rights, "method": "lama", "at": time.time()}
        if t.pid is not None:
            _apply_to_source(t, out, record, update_rights=update_rights)
        else:
            _save_state(t.work, done=record)
        finish()
    except inpaint.Cancelled:
        if t.pid is not None:
            db.update_project(t.pid, log=f"Đã dừng xoá logo nguồn #{t.index + 1}")
        finish()
    except Exception as e:
        job.update(status="failed", error=str(e)[:500])
        raise


def stop_all() -> None:
    for job in list(_jobs.values()):
        job["cancel"] = True


def cancel(key: str) -> dict:
    """Dừng việc xoá logo đang chạy hoặc đang chờ; kết quả cũ (nếu có) giữ nguyên."""
    resolve(key)
    job = _jobs.get(key)
    if not job or job["status"] not in BUSY:
        raise ValueError("Video này không có việc xoá logo nào đang chạy")
    job["cancel"] = True
    if job["status"] == "queued":
        with _lock:
            if _jobs.get(key) is job:
                _jobs.pop(key)
    return view(key)


def _apply_to_source(t: Target, out: Path, record: dict, *, update_rights: bool = True) -> None:
    """Bản sạch thay nguồn này cho lần dựng sau. Bóc lời và cắt cảnh không đổi: chép cache sang bản sạch."""
    p = db.get_project(t.pid)
    sources = list(p["meta"].get("sources") or [])
    if t.index >= len(sources) or sources[t.index].get("url") != t.url:
        raise RuntimeError("Nguồn của dự án đã đổi trong lúc xoá logo")
    s = dict(sources[t.index])
    for suffix in (".transcript.json", ".scenes.json"):
        cache = t.src.with_suffix(suffix)
        if cache.is_file():
            shutil.copyfile(cache, out.with_suffix(suffix))
    s.update(path=str(out), orig_path=str(t.src), delogo=record)
    sources[t.index] = s
    meta: dict = {"sources": sources}
    declared = [(x.get("delogo") or {}).get("rights") for x in sources]
    if update_rights and all(declared):  # mọi nguồn đều đã được xác nhận: quyền của cả dự án theo lời xác nhận
        meta["rights"] = "licensed" if "licensed" in declared else "owned"
    db.update_project(t.pid, log=f"Đã xoá logo nguồn #{t.index + 1}: bấm Chạy lại từ Giọng đọc để dựng lại video",
                      meta=meta)


def restore(key: str) -> dict:
    """Bỏ bản sạch: nguồn dự án quay về video gốc; file tải lên thì xoá kết quả."""
    t = resolve(key)
    if key in _jobs and _jobs[key]["status"] in BUSY:
        raise Busy("Video này đang được xoá logo")
    if t.pid is not None:
        p = db.get_project(t.pid)
        if p["status"] in BUSY:
            raise Busy("Dự án đang chạy, chờ xong rồi thử lại")
        sources = list(p["meta"]["sources"])
        s = {k: v for k, v in sources[t.index].items() if k not in ("orig_path", "delogo")}
        s["path"] = str(t.src)
        sources[t.index] = s
        db.update_project(t.pid, log=f"Nguồn #{t.index + 1} dùng lại video gốc (bỏ bản đã xoá logo)",
                          meta={"sources": sources})
    else:
        _save_state(t.work, done=None)
    _jobs.pop(key, None)
    for f in t.work.glob("clean.*"):
        try:
            f.unlink(missing_ok=True)
        except OSError:  # Windows: file đang mở trong trình phát; lần xoá logo sau sẽ ghi đè
            pass
    return view(key)


# ---------- file tải lên ----------
def save_upload(name: str, stream) -> str:
    """Lưu một file video tải lên (đọc từng khúc). Trả target "u<hex>"."""
    base = Path(name or "video.mp4").name
    ext = Path(base).suffix.lower()
    if ext not in VIDEO_EXT:
        raise ValueError(f"Chỉ nhận video {', '.join(VIDEO_EXT)}")
    uid = uuid.uuid4().hex
    d = UPLOADS / uid
    d.mkdir(parents=True)
    dest = d / f"input{ext}"
    size = 0
    try:
        with dest.open("wb") as f:
            while chunk := stream.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise ValueError(f"File quá lớn (tối đa {MAX_UPLOAD >> 30} GB)")
                f.write(chunk)
        probe(dest)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    _save_state(d, name=base[:200], file=dest.name, created_at=time.time())
    return f"u{uid}"


def list_uploads(limit: int = 30) -> list[dict]:
    if not UPLOADS.is_dir():
        return []
    out = []
    for d in UPLOADS.iterdir():
        st = _state(d)
        if st.get("file") and re.fullmatch(r"[0-9a-f]{32}", d.name):
            done = bool(st.get("done")) and (d / "clean.mp4").is_file()
            job = _jobs.get(f"u{d.name}")
            out.append({"target": f"u{d.name}", "name": st.get("name") or st["file"],
                        "created_at": st.get("created_at"),
                        "status": job["status"] if job else ("done" if done else "idle")})
    out.sort(key=lambda u: u["created_at"] or 0, reverse=True)
    return out[:limit]


def delete_upload(key: str) -> None:
    t = resolve(key)
    if t.pid is not None:
        raise ValueError("Chỉ xoá được file tải lên")
    if key in _jobs and _jobs[key]["status"] in BUSY:
        raise Busy("Video này đang được xoá logo")
    try:
        shutil.rmtree(t.work)
    except OSError as e:
        raise Busy(f"Không xoá được file ({e.strerror or e}). Đóng video đang mở rồi thử lại.") from e
    _jobs.pop(key, None)
