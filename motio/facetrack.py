"""Tự bám mặt cho chế độ Clip (chủ dự án đồng ý thêm OpenCV, 2026-11-21).

Khung 9:16 của clip chỉ chạy ngang (`meta.clip.crop.x`: tâm khung 0..1 theo giây trong clip). Ở đây: lấy khung hình
của đoạn [start, end] mỗi 0,5 giây (FFmpeg, ảnh xám nhỏ), tìm mặt bằng bộ nhận diện Haar đi kèm OpenCV (không tải
mô hình nào), chọn mặt lớn nhất (ưu tiên mặt gần mặt trước), nội suy chỗ không thấy mặt, lọc median cho khỏi giật, rồi
rút gọn thành vài mốc để người dùng vẫn sửa tay được. Không thấy mặt đủ nhiều thì trả None: khung ở lại giữa hình.

Chỉ tìm vị trí mặt trong hình, không nhận ra ai và không lưu gì ngoài các mốc khung.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

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


def _cascade():
    """Bộ nhận diện mặt của OpenCV; None khi OpenCV không có (thiếu gói / tệp dữ liệu)."""
    try:
        import cv2
    except ImportError:
        return None
    det = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / CASCADE))
    return None if det.empty() else det


def _frames(path: Path, start: float, end: float, w: int, h: int):
    """Ảnh xám (h×w) mỗi 1/FPS giây của [start, end] của nguồn."""
    proc = subprocess.Popen(
        [config.ffmpeg(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(path), "-an",
         "-vf", f"fps={FPS},scale={w}:{h}:flags=bilinear,format=gray", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def detect_x(det, frame: np.ndarray, prev: float | None) -> float | None:
    """Tâm ngang (0..1) của mặt đáng theo nhất trong một ảnh xám, None nếu không thấy."""
    h, w = frame.shape
    found = det.detectMultiScale(frame, scaleFactor=1.1, minNeighbors=5, minSize=(max(int(h * 0.07), 20),) * 2)
    if len(found) == 0:
        return None
    big = max(int(f[2]) * int(f[3]) for f in found)
    near = [f for f in found if int(f[2]) * int(f[3]) >= 0.6 * big]  # mặt lớn ngang nhau: chọn cái gần mặt trước
    centres = [(float(f[0]) + f[2] / 2) / w for f in near]
    if prev is None:
        return max(zip(centres, near, strict=True), key=lambda c: int(c[1][2]) * int(c[1][3]))[0]
    return min(centres, key=lambda c: abs(c - prev))


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
    det = _cascade()
    if det is None or end <= start:
        return None
    info = delogo.probe(path)
    w, h = int(info["width"]), int(info["height"])
    if not w or not h or w / h <= config.W / config.H * 1.02:  # nguồn đã đứng: khung phủ kín, không có chỗ để bám
        return None
    sw = min(WIDTH, w)
    sh = max(int(round(h * sw / w)), 2)
    half = (h * config.W / config.H / w) / 2  # nửa bề ngang khung 9:16, tính theo bề ngang nguồn
    xs: list[float | None] = []
    prev = None
    for frame in _frames(path, start, end, sw, sh):
        x = detect_x(det, frame, prev)
        xs.append(x)
        prev = x if x is not None else prev
    keys = keys_from(xs, half)
    return {"fit": False, "x": keys} if keys else None
