"""Tách giọng nói (separate.py): STFT như torch, cắt / hoà các đoạn, tải mô hình có kiểm tra."""
import wave

import numpy as np
import pytest

from motio import config, separate

has_ffmpeg = bool(config.find("ffmpeg"))


class Identity:
    """Phiên onnxruntime giả: trả lại đúng phổ đầu vào (âm thanh đi qua nguyên vẹn, trừ 3 dải tần thấp nhất)."""

    def __init__(self):
        self.shapes = []

    def run(self, _outputs, feeds):
        self.shapes.append(feeds["input"].shape)
        return [feeds["input"]]


def _tones(seconds: float) -> np.ndarray:
    t = np.arange(int(separate.SR * seconds)) / separate.SR
    return np.stack([0.5 * np.sin(2 * np.pi * 1000 * t), 0.3 * np.sin(2 * np.pi * 440 * t)]).astype(np.float32)


def test_stft_round_trip():
    x = _tones(1.0)[:, :separate.CHUNK // 4 * 4]
    x = np.pad(x, ((0, 0), (0, separate.CHUNK - x.shape[1])))
    spec = separate._stft(x)
    assert spec.shape == (2, separate.N_FFT // 2 + 1, separate.DIM_T)
    y = separate._istft(spec)
    assert y.shape == x.shape and np.abs(y - x).max() < 1e-4


def test_demix_chunks_and_blends_back_to_the_input():
    x = _tones(13.3)  # 3 đoạn chồng nhau + phần đệm
    sess = Identity()
    seen = []
    y = separate.demix(x, sess, lambda d, n: seen.append((d, n)))
    assert y.shape == x.shape
    assert all(s == (1, 4, separate.DIM_F, separate.DIM_T) for s in sess.shapes)
    assert seen[-1][0] == seen[-1][1] == len(sess.shapes) >= 3
    mid = slice(2000, -2000)  # mép đầu / cuối: sóng sin bắt đầu đột ngột, mất phần tần số thấp
    assert np.abs(y[:, mid] / separate.COMPENSATE - x[:, mid]).max() < 2e-3


def test_short_audio_is_padded_to_one_chunk():
    x = _tones(0.5)
    y = separate.demix(x, Identity())
    assert y.shape == x.shape


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg")
def test_instrumental_writes_the_asked_part(tmp_path):
    import subprocess

    src = tmp_path / "src.mp4"
    subprocess.run([config.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=500:duration=6",
                    "-ac", "2", str(src)], check=True)
    out = separate.instrumental(src, tmp_path / "bg.wav", 1.0, 3.0, sess=Identity())
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getframerate()) == (2, separate.SR)
        assert abs(w.getnframes() / separate.SR - 3.0) < 0.05


class _FakeStream:
    def __init__(self, body: bytes, status: int = 200):
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
    monkeypatch.setattr(separate.httpx, "stream", lambda *a, **k: _FakeStream(b"not the model"))
    with pytest.raises(RuntimeError, match="sha256"):
        separate.ensure_model(seen.append)
    assert seen == [1.0] and not separate.model_ready()
    assert not list(separate.model_path().parent.glob("*.part"))
    monkeypatch.setattr(separate.httpx, "stream", lambda *a, **k: _FakeStream(b"", status=404))
    with pytest.raises(RuntimeError, match="Could not download"):
        separate.ensure_model()
