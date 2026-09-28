"""Giọng đọc tiếng Pháp. ElevenLabs (có mốc thời gian) nếu có key, không thì giọng macOS để thử."""
import base64
import json
import subprocess
from pathlib import Path

import httpx

from . import config

EL = "https://api.elevenlabs.io/v1"


class TTSUnavailable(RuntimeError):
    """Không có nhà cung cấp giọng đọc nào dùng được trên máy này — UI hiện thông báo này cho người dùng."""


def provider() -> str | None:
    if config.env("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    return "macos_say" if config.IS_MAC else None


def probe_duration(path: Path) -> float:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip() or 0)


def synthesize(lines: list[str], out_dir: Path, voice: str | None = None) -> dict:
    """Đọc cả kịch bản một lượt. Trả {audio, duration, lines: [{start, end}], provider, voice, alignment}.

    voice: id giọng ElevenLabs (hồ sơ kênh), bỏ trống = giọng trong Cài đặt hoặc tự chọn.
    alignment: mốc từng ký tự của ElevenLabs cho cả đoạn (các dòng nối bằng một dấu cách), None nếu không có.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    p = provider()
    if p == "elevenlabs":
        return _elevenlabs(lines, out_dir, voice)
    if p == "macos_say":
        return _macos_say(lines, out_dir)
    raise TTSUnavailable("No ElevenLabs API key. Go to Settings → enter ELEVENLABS_API_KEY "
                         "(the macOS voice only works on a Mac).")


# ---------- ElevenLabs ----------
def _headers() -> dict:
    return {"xi-api-key": config.env("ELEVENLABS_API_KEY")}


def list_voices() -> list[dict]:
    r = httpx.get(f"{EL}/voices", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json().get("voices", [])


def pick_voice(voice: str | None = None) -> tuple[str, str]:
    vid = voice or config.env("ELEVENLABS_VOICE_ID")
    if vid:
        return vid, vid
    voices = list_voices()

    def is_fr(v):
        labels = {k: str(val).lower() for k, val in (v.get("labels") or {}).items()}
        blob = " ".join(labels.values()) + " " + str(v.get("description") or "").lower()
        return labels.get("language") in ("fr", "french") or "french" in blob or "français" in blob

    for pref in (lambda v: is_fr(v), lambda v: v.get("name") in ("George", "Daniel", "Brian"), lambda v: True):
        for v in voices:
            if pref(v):
                return v["voice_id"], v.get("name", v["voice_id"])
    raise RuntimeError("The ElevenLabs account has no voices")


def _elevenlabs(lines: list[str], out_dir: Path, voice: str | None = None) -> dict:
    voice_id, voice_name = pick_voice(voice)
    model = config.env("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    text, offsets = "", []
    for ln in lines:
        if text:
            text += " "
        offsets.append(len(text))
        text += ln.strip()
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.15, "speed": 1.05}}
    if any(k in model for k in ("flash", "turbo", "v3")):
        body["language_code"] = "fr"
    r = httpx.post(f"{EL}/text-to-speech/{voice_id}/with-timestamps",
                   params={"output_format": "mp3_44100_128"}, headers=_headers(), json=body, timeout=300)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    data = r.json()
    audio = out_dir / "narration.mp3"
    audio.write_bytes(base64.b64decode(data["audio_base64"]))
    (out_dir / "narration.alignment.json").write_text(json.dumps(data.get("alignment"), ensure_ascii=False))
    total = probe_duration(audio)
    al = data.get("alignment") or {}
    starts = al.get("character_start_times_seconds") or []
    chars = al.get("characters") or []

    def t_at(off: int) -> float:
        if len(chars) == len(text) and off < len(starts):
            return float(starts[off])
        return total * off / max(len(text), 1)  # dự phòng: chia theo số ký tự

    bounds = [t_at(o) for o in offsets] + [total]
    spans = [{"start": round(bounds[i], 3), "end": round(bounds[i + 1], 3)} for i in range(len(lines))]
    return {"audio": str(audio), "duration": total, "lines": spans, "provider": "elevenlabs",
            "voice": voice_name, "model": model, "alignment": al or None}


# ---------- macOS say (chỉ để thử) ----------
def _macos_say(lines: list[str], out_dir: Path) -> dict:
    voice = config.env("SAY_VOICE", "Jacques")
    parts, spans, t = [], [], 0.0
    gap = 0.18
    for i, ln in enumerate(lines):
        aiff = out_dir / f"line_{i:02d}.aiff"
        subprocess.run(["say", "-v", voice, "-r", "190", "-o", str(aiff), ln], check=True)
        d = probe_duration(aiff)
        spans.append({"start": round(t, 3), "end": round(t + d + gap, 3)})
        parts.append(aiff)
        t += d + gap
    lst = out_dir / "say_list.txt"
    silence = out_dir / "gap.wav"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", str(gap), str(silence)], check=True)
    lst.write_text("".join(f"file '{p.name}'\nfile '{silence.name}'\n" for p in parts))
    audio = out_dir / "narration.wav"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-ar", "44100", "-ac", "1", str(audio)], check=True, cwd=out_dir)
    return {"audio": str(audio), "duration": probe_duration(audio), "lines": spans, "provider": "macos_say",
            "voice": voice, "model": "say", "alignment": None}
