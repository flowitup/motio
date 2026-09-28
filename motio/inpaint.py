"""Vẽ lại vùng logo bằng LaMa (mô hình AI, Apache 2.0) trên từng khung hình; FFmpeg chỉ giải mã và mã hoá.

Mô hình: bản ONNX của OpenCV Zoo (inpainting_lama_2025jan.onnx, 92 MB, Apache 2.0, từ advimman/lama), tải một lần
về data/models/ ở lần xoá logo đầu tiên và kiểm tra sha256. Chạy bằng onnxruntime trên CPU (macOS, Windows, Linux).

Mỗi khung hình: cắt một vùng quanh logo (logo + lề để mô hình nhìn hình xung quanh), thu về ≤ WORK px, mô hình vẽ lại
phần logo, phóng lại cỡ cũ rồi dán vào, hoà dần ở viền để không lộ khung chữ nhật. Nền quanh logo gần như không đổi
so với lần vẽ trước (cảnh tĩnh) thì dùng lại phần đã vẽ: nhanh hơn và không nhấp nháy.
"""
import hashlib
import math
import os
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from . import config

MODEL_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/inpainting_lama/"
             "inpainting_lama_2025jan.onnx")
MODEL_SHA256 = "7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2"
MODEL_BYTES = 92_591_623
MODEL_FILE = "lama-2025jan-anysize.onnx"
# File gốc khai báo đầu vào / ra cố định 1×3×512×512 nhưng đồ thị chạy được mọi cỡ (ngang bội 16, dọc bội 8).
# Đổi 6 chiều 512 (cao, rộng của image, mask, output) thành chiều tự do: mỗi chiều là 5 byte protobuf
# (dim_value=512 → dim_param="h"/"w", cùng độ dài nên không xê dịch gì khác). Vị trí đúng cho file có sha256 trên.
_DIM_512 = b"\x0a\x03\x08\x80\x04"
_FREE_DIMS = ((90_989_584, b"h"), (90_989_589, b"w"), (90_989_623, b"h"), (90_989_628, b"w"),
              (90_989_664, b"h"), (90_989_669, b"w"))
PATCHED_SHA256 = "df66660a79e0305f6c614d1f1c7614982fcac99d532646c733a5839162e7da7e"

WORK = 256  # cạnh dài nhất (px) của vùng đưa vào mô hình: nhanh gấp ~4 lần 512, vết vá không kém hơn
CONTEXT = 0.6  # lề quanh logo cho mô hình nhìn, × cạnh dài của khung (tối thiểu 24 px)
REUSE = 1.5  # nền quanh logo lệch trung bình dưới mức này (thang 0–255) so với lần vẽ trước → dùng lại


class Cancelled(RuntimeError):
    pass


_model_lock = threading.Lock()
_session = None


def model_path() -> Path:
    return config.DATA / "models" / MODEL_FILE


def model_ready() -> bool:
    return model_path().is_file()


def ensure_model(progress: Callable[[float], None] | None = None) -> Path:
    """Tải mô hình về (một lần), kiểm tra sha256, mở chiều tự do. progress(0..1) theo phần đã tải."""
    path = model_path()
    with _model_lock:
        if path.is_file():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        h = hashlib.sha256()
        try:
            with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or MODEL_BYTES)
                done = 0
                with part.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        if progress:
                            progress(min(done / total, 1.0))
        except (httpx.HTTPError, OSError) as e:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"Không tải được mô hình AI xoá logo ({e}). Kiểm tra mạng rồi thử lại.") from e
        data = bytearray(part.read_bytes())
        part.unlink(missing_ok=True)
        if h.hexdigest() != MODEL_SHA256 or any(data[o:o + 5] != _DIM_512 for o, _ in _FREE_DIMS):
            raise RuntimeError("Mô hình AI tải về không đúng bản Motio cần (sai sha256). Báo lại để cập nhật Motio.")
        for off, name in _FREE_DIMS:
            data[off:off + 5] = b"\x0a\x03\x12\x01" + name
        if hashlib.sha256(data).hexdigest() != PATCHED_SHA256:
            raise RuntimeError("Không chuẩn bị được mô hình AI xoá logo")
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return path


def session():
    """Phiên onnxruntime (mở một lần cho cả engine). Gọi ensure_model trước nếu cần báo tiến độ tải."""
    global _session
    if _session is None:
        import onnxruntime as ort  # nặng: chỉ nạp khi xoá logo

        path = ensure_model()
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        # Trọng số lưu dạng int8: giải nén sang float một lần khi mở, không phải ở mỗi khung (nhanh hơn ~28 %, kết
        # quả như cũ; mở chậm hơn vài giây, tốn thêm ~400 MB RAM).
        opts.add_session_config_entry("session.disable_quant_qdq", "1")
        try:
            _session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        except Exception as e:  # file hỏng: xoá để lần sau tải lại
            path.unlink(missing_ok=True)
            raise RuntimeError(f"Mô hình AI xoá logo bị hỏng, đã xoá để tải lại: {e}") from e
    return _session


def _up(v: float, k: int) -> int:
    return max(16, math.ceil(v / k) * k)


class Patch:
    """Một khung logo: vùng cắt quanh nó, mặt nạ cho mô hình, độ hoà khi dán lại, và lần vẽ gần nhất."""

    def __init__(self, box: dict, width: int, height: int):
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        ring = max(4, round(max(w, h) * 0.03))  # mô hình vẽ lại cả một viền quanh khung, viền này hoà dần ra hình gốc
        mx0, my0, mx1, my1 = max(0, x - ring), max(0, y - ring), min(width, x + w + ring), min(height, y + h + ring)
        m = max(24, round(CONTEXT * max(w, h)))
        self.x0, self.y0 = max(0, mx0 - m), max(0, my0 - m)
        self.x1, self.y1 = min(width, mx1 + m), min(height, my1 + m)
        cw, ch = self.x1 - self.x0, self.y1 - self.y0
        s = min(1.0, WORK / max(cw, ch))
        self.size = (_up(cw * s, 16), _up(ch * s, 8))  # (rộng, cao) cho mô hình: rộng bội 16, cao bội 8
        tw, th = self.size
        # mặt nạ ở cỡ làm việc: phủ trọn vùng [mx0, mx1) × [my0, my1) sau khi thu nhỏ
        mask = np.zeros((th, tw), np.float32)
        fx, fy = tw / cw, th / ch
        mask[math.floor((my0 - self.y0) * fy):math.ceil((my1 - self.y0) * fy),
             math.floor((mx0 - self.x0) * fx):math.ceil((mx1 - self.x0) * fx)] = 1
        self.mask = mask[None, None]
        self.keep = mask == 0  # phần nền dùng để so với lần vẽ trước
        # độ hoà ở cỡ gốc: 1 trong khung logo, giảm dần về 0 qua viền, 0 ngoài viền
        yy, xx = np.mgrid[self.y0:self.y1, self.x0:self.x1]
        d = np.maximum(np.maximum(x - xx, xx - (x + w - 1)), np.maximum(y - yy, yy - (y + h - 1))).clip(0)
        alpha = np.clip(1 - d / (ring + 1), 0, 1).astype(np.float32)
        outside = (xx < mx0) | (xx >= mx1) | (yy < my0) | (yy >= my1)
        alpha[outside] = 0
        self.alpha = alpha[..., None]
        self.prev_in: np.ndarray | None = None
        self.prev_fill: np.ndarray | None = None

    def apply(self, frame: np.ndarray, sess) -> bool:
        """Vá khung này trên frame (H×W×3 uint8, sửa tại chỗ). Trả True nếu đã chạy mô hình."""
        crop = frame[self.y0:self.y1, self.x0:self.x1]
        small = np.asarray(Image.fromarray(crop).resize(self.size, Image.BICUBIC), np.float32)
        ran = self.prev_in is None or float(np.abs(small - self.prev_in)[self.keep].mean()) >= REUSE
        if ran:
            out = sess.run(None, {"image": (small / 255).transpose(2, 0, 1)[None], "mask": self.mask})[0][0]
            out = np.clip(out.transpose(1, 2, 0) + 0.5, 0, 255).astype(np.uint8)
            fill = np.asarray(Image.fromarray(out).resize((crop.shape[1], crop.shape[0]), Image.BICUBIC), np.float32)
            self.prev_in, self.prev_fill = small, fill
        blended = crop * (1 - self.alpha) + self.prev_fill * self.alpha
        frame[self.y0:self.y1, self.x0:self.x1] = np.clip(blended + 0.5, 0, 255).astype(np.uint8)
        return ran


def fps_value(rate: str) -> float:
    try:
        num, _, den = rate.partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _read(pipe, n: int) -> bytearray:
    buf = bytearray()
    while len(buf) < n:
        chunk = pipe.read(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def frame_spans(ranges: list[tuple[float, float]] | None, rate: float, n: int) -> list[tuple[int, float]]:
    """Khoảng thời gian (giây) → khoảng số thứ tự khung [đầu, cuối), đã gộp, trong [0, n). None = cả video."""
    if ranges is None:
        return [(0, n)]
    spans: list[tuple[int, int]] = []
    for a, b in sorted((math.floor(a * rate), min(n, math.ceil(b * rate))) for a, b in ranges):
        a = max(a, 0)
        if b <= a:
            continue
        if spans and a <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], b))
        else:
            spans.append((a, b))
    return spans


def video(src: Path, dst: Path, boxes: list[dict], info: dict,
          progress: Callable[[int, int], None] | None = None,
          cancelled: Callable[[], bool] = lambda: False,
          ranges: list[tuple[float, float]] | None = None) -> Path:
    """Vá các khung logo trên khung hình của src → dst (H.264, giữ tiếng AAC), dài bằng src.

    info: probe của src (width, height, duration, fps, màu). ranges: chỉ vá trong các khoảng (giây) này, phần còn lại
    giữ nguyên hình (vẫn mã hoá lại); None = cả video. progress(khung đã vá, tổng khung cần vá, ước tính).
    """
    sess = session()
    width, height = info["width"], info["height"]
    fps = info.get("fps") or "30"
    rate = fps_value(fps) or 30
    frames = max(1, round((info.get("duration") or 0) * rate))
    spans = frame_spans(ranges, rate, frames)
    if not spans:
        raise ValueError("Khoảng cần xoá logo nằm ngoài video")
    total = sum(b - a for a, b in spans)
    if spans[-1][1] == frames:  # số khung thật có thể nhiều hơn ước tính theo độ dài: khoảng chạm cuối thì vá tới hết
        spans[-1] = (spans[-1][0], math.inf)
    patches = [Patch(b, width, height) for b in boxes]
    # đổi YUV ↔ RGB cùng một ma trận, làm tròn chính xác ở cả hai chiều: phần không vá giữ nguyên từng giá trị điểm
    # ảnh (mặc định lệch ~1 mức sáng). Nhãn màu chép từ bản gốc.
    matrix = "bt709" if info.get("color_space") == "bt709" else "bt601"
    sws = "flags=accurate_rnd+full_chroma_int"
    tags = [a for k, flag in (("color_space", "-colorspace"), ("color_primaries", "-color_primaries"),
                              ("color_transfer", "-color_trc"))
            if (v := info.get(k)) and v not in ("unknown", "reserved") for a in (flag, v)]
    part = dst.with_name(dst.stem + ".part.mp4")
    ff = config.ffmpeg()
    dec_cmd = [ff, "-v", "error", "-nostdin", "-i", str(src), "-map", "0:v:0", "-an", "-sn", "-dn",
               "-vf", f"scale={width}:{height}:in_color_matrix={matrix}:{sws}", "-fps_mode", "cfr", "-r", fps,
               "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    enc_cmd = [ff, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
               "-framerate", fps, "-i", "pipe:0", "-i", str(src), "-map", "0:v:0", "-map", "1:a:0?", "-sn", "-dn",
               "-vf", f"scale=trunc(iw/2)*2:trunc(ih/2)*2:out_color_matrix={matrix}:{sws},format=yuv420p", *tags,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", str(part)]
    size = width * height * 3
    done, broken, i, k = 0, False, 0, 0  # i: khung đang đọc, k: khoảng cần vá kế tiếp
    with tempfile.TemporaryFile() as dec_err, tempfile.TemporaryFile() as enc_err:
        dec = subprocess.Popen(dec_cmd, stdout=subprocess.PIPE, stderr=dec_err)
        enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stderr=enc_err)
        try:
            while len(buf := _read(dec.stdout, size)) == size:
                if cancelled():
                    raise Cancelled("Đã dừng xoá logo")
                while k < len(spans) and i >= spans[k][1]:
                    k += 1
                fill = k < len(spans) and spans[k][0] <= i
                if fill:
                    frame = np.frombuffer(buf, np.uint8).reshape(height, width, 3)
                    for p in patches:
                        p.apply(frame, sess)
                else:
                    for p in patches:  # sang khoảng sau là cảnh khác: không dùng lại phần đã vẽ
                        p.prev_in = None
                try:
                    enc.stdin.write(buf)
                except OSError:  # bộ mã hoá đã dừng vì lỗi: báo lỗi của nó bên dưới
                    broken = True
                    dec.kill()
                    break
                i += 1
                if fill:
                    done += 1
                    if progress:
                        progress(done, max(total, done))
            try:
                enc.stdin.close()
            except OSError:
                broken = True
            dec_rc, enc_rc = dec.wait(), enc.wait()
        except BaseException:
            for p in (dec, enc):
                p.kill()
                p.wait()
            part.unlink(missing_ok=True)
            raise
        finally:
            dec.stdout.close()
        errors = []
        for rc, f, name in ((0 if broken else dec_rc, dec_err, "giải mã"), (enc_rc, enc_err, "mã hoá")):
            if rc != 0:
                f.seek(0)
                errors.append(f"FFmpeg lỗi khi {name}: {f.read().decode(errors='replace')[-600:]}")
        if broken and not errors:
            errors.append("FFmpeg dừng giữa chừng khi mã hoá video")
    if errors or i == 0:
        part.unlink(missing_ok=True)
        raise RuntimeError("\n".join(errors) or "Không đọc được khung hình nào từ video")
    os.replace(part, dst)
    return dst
