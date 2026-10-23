"""Gemini TTS (motio/tts.py): provider choice, one request per line, spans, retries, cost, voices. No network."""
import base64
import json
import struct
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from motio import api, db, settings, tts, usage

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}
RATE = 24000


def _pcm(seconds: float, lead: float = 0.0, tail: float = 0.0) -> bytes:
    """A tone of `seconds` with silence before and after, as 16-bit mono samples."""
    tone = struct.pack("<h", 6000) * int(RATE * seconds)
    return bytes(2 * int(RATE * lead)) + tone + bytes(2 * int(RATE * tail))


def _reply(pcm: bytes, mime: str = "audio/L16;codec=pcm;rate=24000") -> httpx.Response:
    body = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": mime,
                                                                  "data": base64.b64encode(pcm).decode()}}]}}]}
    return httpx.Response(200, json=body)


@pytest.fixture
def gemini(monkeypatch):
    """Key set, requests recorded and answered by `script` (a list of responses, or a function of the request)."""
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setattr(tts, "_sleep", lambda s: None)
    sent: list[dict] = []
    answers: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append({"url": str(req.url), "key": req.headers.get("x-goog-api-key"), "json": json.loads(req.content)})
        a = answers.pop(0) if answers else _reply(_pcm(1.0))
        return a(req) if callable(a) else a

    monkeypatch.setattr(tts, "_transport", httpx.MockTransport(handler))
    return type("G", (), {"sent": sent, "answers": answers})


def test_provider_follows_the_keys_and_the_explicit_choice(monkeypatch):
    monkeypatch.setattr(tts.config, "IS_MAC", False)
    assert tts.provider() is None
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert tts.provider() == "gemini"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "e")
    assert tts.provider() == "elevenlabs"  # both keys, no choice: ElevenLabs as before
    monkeypatch.setenv("TTS_PROVIDER", "gemini")
    assert tts.provider() == "gemini"
    monkeypatch.delenv("GEMINI_API_KEY")
    assert tts.provider() is None  # chosen but no key: never a silent switch to the other paid provider
    with pytest.raises(tts.TTSUnavailable, match="GEMINI_API_KEY"):
        tts.synthesize(["x"], Path("."))


def test_one_request_per_line_with_exact_spans(gemini, tmp_path):
    gemini.answers += [_reply(_pcm(1.0, lead=0.3, tail=0.4)), _reply(_pcm(2.0, lead=0.5))]
    r = tts.synthesize([" Bonjour. ", "Deuxième ligne."], tmp_path, voice="kore")
    assert [s["json"]["contents"][0]["parts"][0]["text"] for s in gemini.sent] == ["Bonjour.", "Deuxième ligne."]
    s = gemini.sent[0]
    assert s["key"] == "g-key" and s["url"].endswith(":generateContent")
    cfg = s["json"]["generationConfig"]
    assert cfg["responseModalities"] == ["AUDIO"]
    assert cfg["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
    assert r["provider"] == "gemini" and r["voice"] == "Kore" and r["alignment"] is None
    # silence around the speech is trimmed (40 ms kept each side), a short gap follows each line
    first, second = r["lines"]
    assert first["start"] == 0 and first["end"] == pytest.approx(1.0 + 0.08 + tts.GEMINI_GAP, abs=0.02)
    assert second["start"] == first["end"] and second["end"] == pytest.approx(r["duration"], abs=0.001)
    with wave.open(r["audio"]) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1
        assert w.getnframes() / RATE == pytest.approx(r["duration"], abs=0.01)


def test_another_providers_voice_is_ignored(gemini, tmp_path, monkeypatch):
    tts.synthesize(["Salut"], tmp_path, voice="21m00Tcm4TlvDq8ikWAM")  # an ElevenLabs id on a channel
    assert gemini.sent[0]["json"]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"][
        "voiceName"] == tts.GEMINI_VOICE
    monkeypatch.setenv("GEMINI_VOICE", "Puck")
    tts.synthesize(["Salut"], tmp_path)
    assert gemini.sent[1]["json"]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"][
        "voiceName"] == "Puck"
    # and a Gemini voice name on a channel does not reach ElevenLabs
    monkeypatch.setenv("ELEVENLABS_API_KEY", "e")
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    seen = {}
    monkeypatch.setattr(tts, "_elevenlabs", lambda lines, out, voice: seen.update(voice=voice) or {})
    tts.synthesize(["Salut"], tmp_path, voice="Kore")
    assert seen == {"voice": None}


def test_model_and_rate_come_from_settings_and_reply(gemini, tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    gemini.answers.append(_reply(_pcm(1.0), mime="audio/L16;codec=pcm;rate=16000"))
    r = tts.synthesize(["Salut"], tmp_path)
    assert "/models/gemini-2.5-flash-preview-tts:" in gemini.sent[0]["url"] and r["model"].endswith("preview-tts")
    with wave.open(r["audio"]) as w:
        assert w.getframerate() == 16000


def test_busy_answers_are_retried_but_a_bad_key_is_not(gemini, tmp_path):
    gemini.answers += [httpx.Response(429, json={"error": {"message": "slow down"}}),
                       httpx.Response(500, text="oops"), _reply(_pcm(1.0))]
    r = tts.synthesize(["Salut"], tmp_path)
    assert len(gemini.sent) == 3 and r["lines"]
    gemini.sent.clear()
    gemini.answers.append(httpx.Response(400, json={"error": {"message": "API key not valid"}}))
    with pytest.raises(RuntimeError, match="Gemini 400: API key not valid"):
        tts.synthesize(["Salut"], tmp_path)
    assert len(gemini.sent) == 1


def test_a_reply_without_audio_is_an_error(gemini, tmp_path):
    gemini.answers.append(httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hm"}]}}]}))
    with pytest.raises(RuntimeError, match="no audio"):
        tts.synthesize(["Salut"], tmp_path)


def test_cost_is_estimated_from_the_audio_length(gemini, tmp_path, monkeypatch):
    with db.conn() as c:
        c.execute("DELETE FROM usage")
    pid = db.create_project(None, "p")
    gemini.answers += [_reply(_pcm(30.0)), _reply(_pcm(30.0))]
    with usage.context(project_id=pid):
        tts.synthesize(["Une.", "Deux."], tmp_path)
    u = usage.for_project(pid)
    assert u["tts_chars"] == len("Une.") + len("Deux.") and u["usd"] == pytest.approx(0.03, abs=0.001)
    monkeypatch.setenv("GEMINI_TTS_USD_PER_MIN", "0.06")
    gemini.answers.append(_reply(_pcm(30.0)))
    with usage.context(project_id=pid):
        tts.synthesize(["Trois."], tmp_path)
    assert usage.for_project(pid)["usd"] == pytest.approx(0.03 + 0.03, abs=0.001)


def test_voices_endpoint_lists_gemini_voices(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    with TestClient(api.create_app(TOKEN)) as c:
        vs = c.get("/api/voices", headers=H).json()
    assert len(vs) == 30 and vs[0] == {"id": "Zephyr", "name": "Zephyr", "preview_url": None,
                                       "labels": {"gender": "female", "style": "Bright"}}


def test_voices_of_a_named_provider_before_it_is_saved(monkeypatch):
    with TestClient(api.create_app(TOKEN)) as c:
        assert len(c.get("/api/voices?provider=gemini", headers=H).json()) == 30  # no key needed for a fixed list
        assert c.get("/api/voices?provider=elevenlabs", headers=H).status_code == 409
        monkeypatch.setenv("ELEVENLABS_API_KEY", "e")
        monkeypatch.setattr(tts, "_el_voices", lambda: [{"voice_id": "v1", "name": "George"}])
        assert [v["id"] for v in c.get("/api/voices", headers=H).json()] == ["v1"]


def test_settings_accept_the_new_keys_and_mask_the_secret():
    out = settings.update({"GEMINI_API_KEY": "AIza-secret-1234", "TTS_PROVIDER": "gemini", "GEMINI_VOICE": "Kore"})
    assert out["GEMINI_API_KEY"]["value"] == "••••1234" and out["TTS_PROVIDER"]["value"] == "gemini"
    with pytest.raises(ValueError, match="TTS_PROVIDER"):
        settings.update({"TTS_PROVIDER": "azure"})
    with pytest.raises(ValueError, match="GEMINI_TTS_USD_PER_MIN"):
        settings.update({"GEMINI_TTS_USD_PER_MIN": "-1"})
