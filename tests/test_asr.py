"""Whisper guard: a transcription that never returns must not hold the single worker queue forever."""
import threading

import pytest

from motio import asr


def test_bounded_returns_the_value_and_passes_errors_on():
    assert asr.bounded(lambda: 7, 5) == 7
    with pytest.raises(ZeroDivisionError):
        asr.bounded(lambda: 1 / 0, 5)


def test_bounded_gives_up_on_a_call_that_hangs():
    gate = threading.Event()
    try:
        with pytest.raises(asr.Stuck) as e:
            asr.bounded(gate.wait, 0.05)
        assert "restart Motio" in str(e.value)
    finally:
        gate.set()  # let the abandoned thread end


def test_time_limit_grows_with_the_audio(tmp_path):
    wav = tmp_path / "a.16k.wav"
    wav.write_bytes(b"\0" * 32000 * 60)  # one minute of 16 kHz mono 16-bit
    assert asr.time_limit(wav) == asr.TIMEOUT_BASE + 60 * asr.TIMEOUT_PER_SECOND
    assert asr.time_limit(tmp_path / "missing.wav") == asr.TIMEOUT_BASE


def test_transcribe_fails_instead_of_waiting_forever(tmp_path, monkeypatch):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    gate = threading.Event()
    monkeypatch.setattr(asr, "has_audio", lambda p: True)
    monkeypatch.setattr(asr, "_wav", lambda p: p)
    monkeypatch.setattr(asr, "_whisper", lambda wav: gate.wait())
    monkeypatch.setattr(asr, "time_limit", lambda wav: 0.05)
    try:
        with pytest.raises(asr.Stuck):
            asr.transcribe(src)
        assert not src.with_suffix(".transcript.json").exists()  # nothing cached: the next try transcribes again
    finally:
        gate.set()
