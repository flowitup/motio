"""Tự bám mặt cho chế độ Clip (chủ dự án đồng ý thêm OpenCV, 2026-11-21).

Khung 9:16 của clip chỉ chạy ngang (`meta.clip.crop.x`: tâm khung 0..1 theo giây trong clip). Ở đây: lấy khung hình
của đoạn [start, end] mỗi 0,5 giây (FFmpeg, ảnh nhỏ), tìm mặt bằng YuNet (OpenCV `FaceDetectorYN`, mô hình ONNX 230 KB
của opencv_zoo, MIT, tải một lần về `data/models/` và kiểm tra sha256; thử 2026-11-21 thấy cả mặt nhỏ mà Haar bỏ sót)
hoặc, khi chưa tải được mô hình, bộ Haar đi kèm OpenCV. Chọn mặt lớn nhất (ưu tiên mặt gần mặt trước), nội suy chỗ
không thấy mặt, lọc median cho khỏi giật, rồi rút gọn thành vài mốc để người dùng vẫn sửa tay được. Không thấy mặt đủ
nhiều thì trả None: khung ở lại giữa hình.

Chỉ tìm vị trí mặt trong hình, không nhận ra ai và không lưu gì ngoài các mốc khung.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path

import httpx
import numpy as np

from . import config, delogo

FPS = 2.0  # khung hình phân tích mỗi giây
WIDTH = 480  # px: bề ngang ảnh phân tích
MIN_FOUND = 0.2  # tỉ lệ khung hình phải thấy mặt, ít hơn thì không đoán
MEDIAN = 5  # cửa sổ lọc median (số mẫu)
TOLERANCE = 0.03  # sai lệch tâm khung (0..1) chấp nhận khi rút gọn mốc
STILL = 0.05  # mặt dao động ít hơn thế thì giữ một mốc cố định
MAX_KEYS = 40  # như clipper.MAX_KEYS
CASCADE = "haarcascade_frontalface_alt2.xml"
SCORE = 0.7  # YuNet: ngưỡng tin cậy của một mặt
MODEL_URL = "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
MODEL_FILE = "face_detection_yunet_2023mar.onnx"
RETRY_AFTER = 600.0  # giây: tải mô hình hỏng thì 10 phút sau mới thử lại (trong lúc đó dùng Haar)

_model_lock = threading.Lock()
_model_failed = 0.0


def model_path() -> Path:
    return config.DATA / "models" / MODEL_FILE


def ensure_model() -> Path | None:
    """Mô hình YuNet (tải một lần, kiểm tra sha256), hoặc None khi không tải được."""
    global _model_failed
    path = model_path()
    with _model_lock:
        if path.is_file():
            return path
        if _model_failed and time.time() - _model_failed < RETRY_AFTER:
            return None
        part = path.with_name(path.name + ".part")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            r = httpx.get(MODEL_URL, follow_redirects=True, timeout=httpx.Timeout(15, read=30))
            r.raise_for_status()
            if hashlib.sha256(r.content).hexdigest() != MODEL_SHA256:
                raise ValueError("sha256 mismatch")
            part.write_bytes(r.content)
            os.replace(part, path)
        except (httpx.HTTPError, OSError, ValueError):
            part.unlink(missing_ok=True)
            _model_failed = time.time()
            return None
        return path


class _Haar:
    def __init__(self, cv2, det):
        self.cv2, self.det = cv2, det

    def faces(self, frame: np.ndarray) -> list[tuple[float, float]]:
        """[(tâm ngang 0..1, diện tích)] của các mặt thấy trong ảnh."""
        h, w = frame.shape[:2]
        g = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        found = self.det.detectMultiScale(g, scaleFactor=1.1, minNeighbors=5,
                                          minSize=(max(int(h * 0.07), 20),) * 2)
        return [((float(f[0]) + f[2] / 2) / w, float(f[2]) * float(f[3])) for f in found]


class _YuNet:
    def __init__(self, cv2, det):
        self.cv2, self.det = cv2, det

    def faces(self, frame: np.ndarray) -> list[tuple[float, float]]:
        h, w = frame.shape[:2]
        _, found = self.det.detect(frame)
        return [((float(f[0]) + f[2] / 2) / w, float(f[2]) * float(f[3])) for f in (found if found is not None else [])]


def _detector(w: int, h: int):
    """Bộ nhận diện mặt cho ảnh w×h (BGR): YuNet nếu có mô hình, không thì Haar của OpenCV; None khi OpenCV không có."""
    try:
        import cv2
    except ImportError:
        return None
    model = ensure_model()
    if model is not None:
        try:
            return _YuNet(cv2, cv2.FaceDetectorYN.create(str(model), "", (w, h), SCORE, 0.3, 5000))
        except Exception:  # mô hình hỏng hoặc OpenCV quá cũ: xoá để lần sau tải lại, dùng Haar
            model.unlink(missing_ok=True)
    det = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / CASCADE))
    return None if det.empty() else _Haar(cv2, det)


def _frames(path: Path, start: float, end: float, w: int, h: int):
    """Ảnh BGR (h×w×3) mỗi 1/FPS giây của [start, end] của nguồn."""
    proc = subprocess.Popen(
        [config.ffmpeg(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(path), "-an",
         "-vf", f"fps={FPS},scale={w}:{h}:flags=bilinear,format=bgr24", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def detect_x(det, frame: np.ndarray, prev: float | None) -> float | None:
    """Tâm ngang (0..1) của mặt đáng theo nhất trong một ảnh, None nếu không thấy."""
    found = det.faces(frame)
    if not found:
        return None
    big = max(a for _, a in found)
    near = [(x, a) for x, a in found if a >= 0.6 * big]  # mặt lớn ngang nhau: chọn cái gần mặt trước
    if prev is None:
        return max(near, key=lambda f: f[1])[0]
    return min((x for x, _ in near), key=lambda x: abs(x - prev))


def _fill(xs: list[float | None]) -> list[float]:
    """Nội suy tuyến tính chỗ không thấy mặt; hai đầu lấy mẫu có mặt gần nhất."""
    idx = [i for i, x in enumerate(xs) if x is not None]
    return [float(v) for v in np.interp(range(len(xs)), idx, [xs[i] for i in idx])]


def _median(xs: list[float], k: int = MEDIAN) -> list[float]:
    r = k // 2
    return [float(np.median(xs[max(0, i - r): i + r + 1])) for i in range(len(xs))]


def _simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Ramer–Douglas–Peucker theo sai lệch dọc (x) giữa mốc và đường nối hai đầu."""
    if len(pts) <= 2:
        return pts
    (t0, x0), (t1, x1) = pts[0], pts[-1]
    dev = [abs(x - (x0 + (x1 - x0) * (t - t0) / max(t1 - t0, 1e-6))) for t, x in pts[1:-1]]
    i = int(np.argmax(dev)) + 1
    if dev[i - 1] <= tol:
        return [pts[0], pts[-1]]
    return _simplify(pts[:i + 1], tol)[:-1] + _simplify(pts[i:], tol)


def keys_from(xs: list[float | None], half: float) -> list[list[float]] | None:
    """Dãy tâm mặt theo mẫu (None = không thấy) → các mốc [[giây, tâm khung]], hoặc None nếu thấy mặt quá ít."""
    if not xs or sum(x is not None for x in xs) < max(2, MIN_FOUND * len(xs)):
        return None
    sm = _median(_fill(xs))
    sm = [min(max(x, half), 1 - half) for x in sm]  # khung không ra ngoài hình
    if max(sm) - min(sm) < STILL:
        return [[0.0, round(float(np.median(sm)), 4)]]
    pts = [(round(i / FPS, 2), x) for i, x in enumerate(sm)]
    tol = TOLERANCE
    while True:
        kept = _simplify(pts, tol)
        if len(kept) <= MAX_KEYS:
            break
        tol *= 1.5
    keys = [[t, round(x, 4)] for t, x in kept]
    keys[0][0] = 0.0
    return keys


def crop_for(path: Path, start: float, end: float) -> dict | None:
    """Khung crop `{fit: False, x: [[giây, tâm]]}` bám mặt cho đoạn [start, end] của nguồn, hoặc None (nguồn đã đứng,
    không thấy mặt, hoặc không có OpenCV): khi đó khung ở lại như cũ."""
    if end <= start:
        return None
    info = delogo.probe(path)
    w, h = int(info["width"]), int(info["height"])
    if not w or not h or w / h <= config.W / config.H * 1.02:  # nguồn đã đứng: khung phủ kín, không có chỗ để bám
        return None
    sw = min(WIDTH, w)
    sh = max(int(round(h * sw / w)), 2)
    det = _detector(sw, sh)
    if det is None:
        return None
    half = (h * config.W / config.H / w) / 2  # nửa bề ngang khung 9:16, tính theo bề ngang nguồn
    xs: list[float | None] = []
    prev = None
    for frame in _frames(path, start, end, sw, sh):
        x = detect_x(det, frame, prev)
        xs.append(x)
        prev = x if x is not None else prev
    keys = keys_from(xs, half)
    return {"fit": False, "x": keys} if keys else None
