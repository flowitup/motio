"""Tách giọng nói khỏi nhạc nền / tiếng động của một đoạn video, để bản lồng tiếng Pháp giữ lại nền gốc.

Mô hình: UVR-MDX-NET-Inst_HQ_3 (MDX-Net, bản ONNX của Ultimate Vocal Remover, MIT), tải một lần về data/models/ ở
bản lồng tiếng đầu tiên và kiểm tra sha256. Chạy bằng onnxruntime trên CPU (như LaMa của Xoá logo). Cách dùng mô hình
(STFT, cắt đoạn, hệ số bù) theo python-audio-separator / UVR.

Mô hình nhận phổ STFT (n_fft 6144, hop 1024, 3072 dải tần đầu) của từng đoạn ~5,9 s âm thanh stereo 44,1 kHz và trả
phổ của phần nhạc nền; các đoạn chồng lên nhau 25 %, hoà bằng cửa sổ Hann.
"""
import hashlib
import os
import subprocess
import threading
import wave
from collections.abc import Callable
from pathlib import Path

import httpx
import numpy as np

from . import config
from .i18n import tr

MODEL_URL = ("https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/"
             "UVR-MDX-NET-Inst_HQ_3.onnx")
MODEL_SHA256 = "317554b07fe1ea5279a77f2b1520a41ea4b93432560c4ffd08792c30fddf9adc"
MODEL_BYTES = 66_759_214
MODEL_FILE = "UVR-MDX-NET-Inst_HQ_3.onnx"

SR = 44100
N_FFT, HOP, DIM_F, DIM_T = 6144, 1024, 3072, 256
COMPENSATE = 1.022  # hệ số bù âm lượng của mô hình này (bảng model_data của UVR)
CHUNK = HOP * (DIM_T - 1)  # số mẫu một đoạn đưa vào mô hình (256 khung STFT)
TRIM = N_FFT // 2
OVERLAP = 0.25

_model_lock = threading.Lock()
_session = None


def model_path() -> Path:
    return config.DATA / "models" / MODEL_FILE


def model_ready() -> bool:
    return model_path().is_file()


def ensure_model(progress: Callable[[float], None] | None = None) -> Path:
    """Tải mô hình về (một lần) và kiểm tra sha256. progress(0..1) theo phần đã tải."""
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
            raise RuntimeError(tr("Could not download the voice separation AI model ({error})", error=e)) from e
        if h.hexdigest() != MODEL_SHA256:
            part.unlink(missing_ok=True)
            raise RuntimeError(tr("The downloaded voice separation model is not the version Motio needs (sha256 "
                                  "mismatch)"))
        os.replace(part, path)
        return path


def session():
    """Phiên onnxruntime (mở một lần cho cả engine)."""
    global _session
    if _session is None:
        import onnxruntime as ort  # nặng: chỉ nạp khi lồng tiếng

        path = ensure_model()
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        try:
            _session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        except Exception as e:  # file hỏng: xoá để lần sau tải lại
            path.unlink(missing_ok=True)
            raise RuntimeError(tr("The voice separation model was corrupt and has been deleted: {error}",
                                  error=e)) from e
    return _session


# ---------- STFT như torch.stft / torch.istft (center=True, reflect, cửa sổ Hann tuần hoàn) ----------
_WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)


def _stft(x: np.ndarray) -> np.ndarray:
    """x: [kênh, mẫu] → phổ phức [kênh, N_FFT//2 + 1, khung]."""
    pad = np.pad(x, ((0, 0), (N_FFT // 2, N_FFT // 2)), mode="reflect")
    frames = 1 + (pad.shape[1] - N_FFT) // HOP
    idx = np.arange(frames)[:, None] * HOP + np.arange(N_FFT)[None, :]
    return np.fft.rfft(pad[:, idx] * _WINDOW, axis=-1).transpose(0, 2, 1)


def _istft(spec: np.ndarray) -> np.ndarray:
    """Phổ phức [kênh, N_FFT//2 + 1, khung] → [kênh, HOP * (khung - 1)] (cộng chồng, chia tổng cửa sổ²)."""
    frames = spec.shape[-1]
    parts = np.fft.irfft(spec.transpose(0, 2, 1), n=N_FFT, axis=-1).astype(np.float32) * _WINDOW
    n = N_FFT + HOP * (frames - 1)
    out = np.zeros((spec.shape[0], n), np.float32)
    norm = np.zeros(n, np.float32)
    sq = _WINDOW ** 2
    for t in range(frames):
        out[:, t * HOP:t * HOP + N_FFT] += parts[:, t]
        norm[t * HOP:t * HOP + N_FFT] += sq
    out /= np.where(norm > 1e-8, norm, 1.0)
    return out[:, N_FFT // 2:n - N_FFT // 2]


def _run_chunk(part: np.ndarray, sess) -> np.ndarray:
    """Một đoạn [2, CHUNK] → phần nhạc nền [2, CHUNK]."""
    spec = _stft(part)  # [2, 3073, 256]
    x = np.stack([spec.real, spec.imag], axis=1).reshape(4, spec.shape[1], DIM_T)[:, :DIM_F].astype(np.float32)
    x[:, :3] = 0  # như UVR: bỏ 3 dải tần thấp nhất
    y = sess.run(None, {"input": x[None]})[0][0]  # [4, 3072, 256]
    full = np.zeros((4, N_FFT // 2 + 1, DIM_T), np.float32)
    full[:, :DIM_F] = y
    full = full.reshape(2, 2, N_FFT // 2 + 1, DIM_T)
    return _istft(full[:, 0] + 1j * full[:, 1])


def demix(mix: np.ndarray, sess, progress: Callable[[int, int], None] | None = None) -> np.ndarray:
    """mix: [2, mẫu] float32 ở 44,1 kHz → phần nhạc nền (bỏ giọng nói), cùng cỡ."""
    n = mix.shape[1]
    gen = CHUNK - 2 * TRIM
    pad = gen + TRIM - n % gen
    x = np.concatenate([np.zeros((2, TRIM), np.float32), mix, np.zeros((2, pad), np.float32)], axis=1)
    step = int((1 - OVERLAP) * CHUNK)
    result = np.zeros_like(x)
    weight = np.zeros(x.shape[1], np.float32)
    window = np.hanning(CHUNK).astype(np.float32)
    starts = list(range(0, x.shape[1], step))
    for k, a in enumerate(starts):
        b = min(a + CHUNK, x.shape[1])
        part = x[:, a:b]
        if b - a < CHUNK:
            part = np.pad(part, ((0, 0), (0, CHUNK - (b - a))))
        out = _run_chunk(part, sess)[:, :b - a]
        w = window[:b - a]
        result[:, a:b] += out * w
        weight[a:b] += w
        if progress:
            progress(k + 1, len(starts))
    result /= np.where(weight > 1e-8, weight, 1.0)
    return result[:, TRIM:TRIM + n] * COMPENSATE


def _decode(src: Path, start: float, dur: float) -> np.ndarray:
    """Âm thanh stereo 44,1 kHz float32 [2, mẫu] của src từ `start`, dài `dur` giây."""
    r = subprocess.run([config.ffmpeg(), "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                        "-i", str(src), "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "pipe:1"],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(tr("ffmpeg could not read the audio: {error}",
                              error=r.stderr.decode(errors="replace")[-400:]))
    return np.frombuffer(r.stdout, np.float32).reshape(-1, 2).T.copy()


def write_wav(path: Path, audio: np.ndarray) -> Path:
    """[2, mẫu] float → WAV 16 bit stereo 44,1 kHz."""
    pcm = (np.clip(audio.T, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


def instrumental(src: Path, out: Path, start: float, dur: float,
                 progress: Callable[[int, int], None] | None = None, sess=None) -> Path:
    """Nhạc nền + tiếng động (không giọng nói) của src trong [start, start + dur] → out (WAV)."""
    mix = _decode(src, start, dur)
    if mix.shape[1] == 0:
        raise RuntimeError(tr("The source has no audio in this part"))
    return write_wav(out, demix(mix, sess or session(), progress))
