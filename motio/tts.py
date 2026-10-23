"""Giọng đọc tiếng Pháp. ElevenLabs (có mốc thời gian) hoặc Gemini TTS (đọc từng câu) nếu có key, không thì giọng macOS
để thử."""
import array
import base64
import json
import subprocess
import time
import wave
from pathlib import Path

import httpx

from . import config
from .i18n import tr

EL = "https://api.elevenlabs.io/v1"


class TTSUnavailable(RuntimeError):
    """Không có nhà cung cấp giọng đọc nào dùng được trên máy này — UI hiện thông báo này cho người dùng."""


PROVIDERS = ("elevenlabs", "gemini")  # giá trị TTS_PROVIDER; để trống = theo key đang có


def provider() -> str | None:
    """Nhà cung cấp giọng đang dùng. TTS_PROVIDER chọn rõ thì chỉ dùng nó (thiếu key thì None, không âm thầm đổi sang
    nhà khác vì mỗi nơi tính tiền riêng); để trống thì ElevenLabs, rồi Gemini, rồi giọng macOS (chỉ để thử)."""
    keys = {"elevenlabs": bool(config.env("ELEVENLABS_API_KEY")), "gemini": bool(config.env("GEMINI_API_KEY"))}
    want = config.env("TTS_PROVIDER").lower()
    if want in PROVIDERS:
        return want if keys[want] else None
    for name in PROVIDERS:
        if keys[name]:
            return name
    return "macos_say" if config.IS_MAC else None


def missing_key_message() -> str:
    want = config.env("TTS_PROVIDER").lower()
    if want == "gemini":
        return tr("No Gemini API key. Go to Settings → enter GEMINI_API_KEY.")
    if want == "elevenlabs":
        return tr("No ElevenLabs API key. Go to Settings → enter ELEVENLABS_API_KEY.")
    return tr("No voice key. Go to Settings → enter ELEVENLABS_API_KEY or GEMINI_API_KEY "
              "(the macOS voice only works on a Mac).")


def probe_duration(path: Path) -> float:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip() or 0)


def synthesize(lines: list[str], out_dir: Path, voice: str | None = None) -> dict:
    """Đọc cả kịch bản một lượt. Trả {audio, duration, lines: [{start, end}], provider, voice, alignment}.

    voice: id giọng ElevenLabs hoặc tên giọng Gemini (hồ sơ kênh), bỏ trống = giọng trong Cài đặt hoặc tự chọn. Giọng
    của nhà cung cấp kia (kênh đặt giọng ElevenLabs rồi đổi sang Gemini, hay ngược lại) bị bỏ qua.
    alignment: mốc từng ký tự của ElevenLabs cho cả đoạn (các dòng nối bằng một dấu cách), None nếu không có.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    p = provider()
    is_gemini_voice = bool(voice) and voice.strip().lower() in _GEMINI_LOWER
    if p == "elevenlabs":
        return _elevenlabs(lines, out_dir, None if is_gemini_voice else voice)
    if p == "gemini":
        return _gemini(lines, out_dir, voice if is_gemini_voice else None)
    if p == "macos_say":
        return _macos_say(lines, out_dir)
    raise TTSUnavailable(missing_key_message())


# ---------- ElevenLabs ----------
def _headers() -> dict:
    return {"xi-api-key": config.env("ELEVENLABS_API_KEY")}


def list_voices() -> list[dict]:
    """Giọng của nhà cung cấp đang dùng, cùng dạng với trả lời của ElevenLabs: {voice_id, name, labels, preview_url}."""
    return voices_of(provider())


def voices_of(who: str | None) -> list[dict]:
    return gemini_voices() if who == "gemini" else _el_voices()


def _el_voices() -> list[dict]:
    r = httpx.get(f"{EL}/voices", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json().get("voices", [])


def pick_voice(voice: str | None = None) -> tuple[str, str]:
    vid = voice or config.env("ELEVENLABS_VOICE_ID")
    if vid:
        return vid, vid
    voices = _el_voices()

    def is_fr(v):
        labels = {k: str(val).lower() for k, val in (v.get("labels") or {}).items()}
        blob = " ".join(labels.values()) + " " + str(v.get("description") or "").lower()
        return labels.get("language") in ("fr", "french") or "french" in blob or "français" in blob

    for pref in (lambda v: is_fr(v), lambda v: v.get("name") in ("George", "Daniel", "Brian"), lambda v: True):
        for v in voices:
            if pref(v):
                return v["voice_id"], v.get("name", v["voice_id"])
    raise RuntimeError(tr("The ElevenLabs account has no voices"))


RETRY_PAUSES = (2.0, 6.0)  # s before the 2nd and 3rd try of a voice request


def _post_with_retry(url: str, body: dict) -> httpx.Response:
    """POST the voice request; try again on a dropped connection, a timeout, a 429 or a 5xx (nothing is billed for
    those), never on another answer."""
    for i in range(len(RETRY_PAUSES) + 1):
        try:
            r = httpx.post(url, params={"output_format": "mp3_44100_128"}, headers=_headers(), json=body, timeout=300)
        except (httpx.TransportError, httpx.TimeoutException):
            if i == len(RETRY_PAUSES):
                raise
        else:
            if r.status_code != 429 and r.status_code < 500 or i == len(RETRY_PAUSES):
                return r
        time.sleep(RETRY_PAUSES[i])
    raise AssertionError("unreachable")


EL_MAX_CHARS = 4800  # one request reads at most this many characters; a longer script goes in batches


def batches(lines: list[str], limit: int | None = None) -> list[list[str]]:
    """Consecutive lines grouped so that each group, joined with spaces, stays within `limit` characters (default
    EL_MAX_CHARS). A line longer than `limit` is alone in its group."""
    limit = limit or EL_MAX_CHARS
    out: list[list[str]] = []
    size = 0
    for ln in lines:
        n = len(ln.strip()) + 1
        if out and size + n <= limit:
            out[-1].append(ln)
            size += n
        else:
            out.append([ln])
            size = n
    return out


def _elevenlabs(lines: list[str], out_dir: Path, voice: str | None = None) -> dict:
    """One request when the script fits, else one request per batch and the batches joined into one narration."""
    parts = batches(lines)
    if len(parts) <= 1:
        return _elevenlabs_once(lines, out_dir, voice)
    runs = []
    for k, part in enumerate(parts):
        d = out_dir / f"part{k:02d}"
        d.mkdir(parents=True, exist_ok=True)
        runs.append(_elevenlabs_once(part, d, voice))
    return _join_runs(runs, parts, out_dir)


def _join_runs(runs: list[dict], parts: list[list[str]], out_dir: Path) -> dict:
    """The batches' narrations as one: audio joined (same format), each line's span and the character timings moved
    by the length of the batches before it. Characters stay in step with the lines joined by one space."""
    listing = out_dir / "parts.txt"
    listing.write_text("".join(f"file '{Path(r['audio']).resolve().as_posix()}'\n" for r in runs), encoding="utf-8")
    audio = out_dir / "narration.mp3"
    p = subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-nostdin", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-c", "copy", str(audio)], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg could not join the voice parts: {p.stderr[-400:]}")
    total = probe_duration(audio)
    spans: list[dict] = []
    chars: list[str] = []
    starts: list[float] = []
    ends: list[float] = []
    exact, cut = True, 0.0
    for k, r in enumerate(runs):
        spans += [{"start": round(s["start"] + cut, 3), "end": round(s["end"] + cut, 3)} for s in r["lines"]]
        al = r.get("alignment") or {}
        c, a, b = (al.get("characters") or []), (al.get("character_start_times_seconds") or []), \
            (al.get("character_end_times_seconds") or [])
        if not (len(c) == len(a) == len(b) == len(" ".join(x.strip() for x in parts[k]))):
            exact = False
        elif exact:
            if k:
                chars.append(" ")
                starts.append(round(cut, 3))
                ends.append(round(cut, 3))
            chars += list(c)
            starts += [round(float(x) + cut, 3) for x in a]
            ends += [round(float(x) + cut, 3) for x in b]
        cut += r["duration"]
    alignment = ({"characters": chars, "character_start_times_seconds": starts, "character_end_times_seconds": ends}
                 if exact else None)
    (out_dir / "narration.alignment.json").write_text(json.dumps(alignment, ensure_ascii=False), encoding="utf-8")
    return {"audio": str(audio), "duration": total, "lines": spans, "provider": runs[0]["provider"],
            "voice": runs[0]["voice"], "model": runs[0]["model"], "alignment": alignment}


def _elevenlabs_once(lines: list[str], out_dir: Path, voice: str | None = None) -> dict:
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
    r = _post_with_retry(f"{EL}/text-to-speech/{voice_id}/with-timestamps", body)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    from . import usage  # nhập muộn: usage → channels → db, tránh vòng lặp import
    usage.record_tts(len(text), model, voice_id)
    data = r.json()
    audio = out_dir / "narration.mp3"
    audio.write_bytes(base64.b64decode(data["audio_base64"]))
    (out_dir / "narration.alignment.json").write_text(json.dumps(data.get("alignment"), ensure_ascii=False),
                                                             encoding="utf-8")
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


# ---------- Gemini TTS ----------
GEMINI = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL = "gemini-3.1-flash-tts-preview"  # GEMINI_TTS_MODEL đổi được; xem docs/GEMINI_TTS.md
GEMINI_VOICE = "Charon"
GEMINI_GAP = 0.18  # s lặng giữa hai câu (như giọng macOS)
GEMINI_USD_PER_MIN = 0.03  # 25 token âm thanh mỗi giây × 20 USD / 1 triệu token (giá đăng 10/2026), chưa kể chữ vào
# 30 giọng có sẵn của Gemini TTS: (tên, giới tính, kiểu đọc theo tài liệu của Google). Tiếng Pháp tự nhận từ văn bản.
GEMINI_VOICES = (
    ("Zephyr", "female", "Bright"), ("Puck", "male", "Upbeat"), ("Charon", "male", "Informative"),
    ("Kore", "female", "Firm"), ("Fenrir", "male", "Excitable"), ("Leda", "female", "Youthful"),
    ("Orus", "male", "Firm"), ("Aoede", "female", "Breezy"), ("Callirrhoe", "female", "Easy-going"),
    ("Autonoe", "female", "Bright"), ("Enceladus", "male", "Breathy"), ("Iapetus", "male", "Clear"),
    ("Umbriel", "male", "Easy-going"), ("Algieba", "male", "Smooth"), ("Despina", "female", "Smooth"),
    ("Erinome", "female", "Clear"), ("Algenib", "male", "Gravelly"), ("Rasalgethi", "male", "Informative"),
    ("Laomedeia", "female", "Upbeat"), ("Achernar", "female", "Soft"), ("Alnilam", "male", "Firm"),
    ("Schedar", "male", "Even"), ("Gacrux", "female", "Mature"), ("Pulcherrima", "female", "Forward"),
    ("Achird", "male", "Friendly"), ("Zubenelgenubi", "male", "Casual"), ("Vindemiatrix", "female", "Gentle"),
    ("Sadachbia", "male", "Lively"), ("Sadaltager", "male", "Knowledgeable"), ("Sulafat", "female", "Warm"),
)
_GEMINI_LOWER = {v[0].lower(): v[0] for v in GEMINI_VOICES}
GEMINI_RETRY_PAUSES = (3.0, 10.0, 25.0, 60.0)  # s; Gemini's limits are per minute, so wait longer than for ElevenLabs
_transport: httpx.BaseTransport | None = None  # test hook
_sleep = time.sleep  # test hook


def gemini_voices() -> list[dict]:
    return [{"voice_id": n, "name": n, "labels": {"gender": g, "style": st}, "preview_url": None}
            for n, g, st in GEMINI_VOICES]


def gemini_voice(voice: str | None = None) -> str:
    """Tên giọng Gemini: giọng truyền vào, hoặc GEMINI_VOICE trong Cài đặt, hoặc mặc định. Tên lạ → mặc định."""
    for cand in (voice, config.env("GEMINI_VOICE")):
        if cand and cand.strip().lower() in _GEMINI_LOWER:
            return _GEMINI_LOWER[cand.strip().lower()]
    return GEMINI_VOICE


def _gemini_post(url: str, body: dict) -> httpx.Response:
    """POST một câu; thử lại khi rớt mạng, quá hạn mức (429) hoặc lỗi 5xx — Gemini thỉnh thoảng trả lỗi 500 khi model
    trả chữ thay vì âm thanh, gửi lại thường qua."""
    headers = {"x-goog-api-key": config.env("GEMINI_API_KEY")}
    last = len(GEMINI_RETRY_PAUSES)
    for i in range(last + 1):
        try:
            with httpx.Client(transport=_transport, timeout=180) as c:
                r = c.post(url, headers=headers, json=body)
        except (httpx.TransportError, httpx.TimeoutException):
            if i == last:
                raise
        else:
            if r.status_code != 429 and r.status_code < 500 or i == last:
                return r
        _sleep(GEMINI_RETRY_PAUSES[i])
    raise AssertionError("unreachable")


def _gemini_error(r: httpx.Response) -> str:
    try:
        msg = r.json()["error"]["message"]
    except Exception:  # noqa: BLE001 — trả lời không phải JSON: lấy đoạn đầu
        msg = r.text
    return f"Gemini {r.status_code}: {str(msg)[:300]}"


def _gemini_once(text: str, model: str, voice: str) -> tuple[bytes, int]:
    """Đọc một câu → (PCM 16 bit mono, tần số mẫu). Ghi một dòng usage cho lần gọi thành công."""
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    r = _gemini_post(f"{GEMINI}/models/{model}:generateContent", body)
    if r.status_code >= 400:
        raise RuntimeError(_gemini_error(r))
    parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    blob = next((p["inlineData"] for p in parts if (p.get("inlineData") or {}).get("data")), None)
    if blob is None:
        raise RuntimeError(tr("Gemini returned no audio for this line"))
    pcm, rate = base64.b64decode(blob["data"]), 24000
    for piece in str(blob.get("mimeType") or "").split(";"):
        if piece.strip().startswith("rate="):
            rate = int(piece.split("=")[1])
    from . import usage  # nhập muộn như ở _elevenlabs_once
    seconds = len(pcm) / 2 / rate
    usage.record_tts(len(text), model, voice, usd=seconds * usage.gemini_price_per_min() / 60)
    return pcm, rate


def _trim(pcm: bytes, rate: int, keep: float = 0.04) -> bytes:
    """Cắt khoảng lặng đầu / cuối (Gemini hay thêm vài trăm ms) để mốc thời gian của câu sát lời đọc."""
    s = array.array("h")
    s.frombytes(pcm[: len(pcm) // 2 * 2])
    loud = [i for i, v in enumerate(s) if abs(v) > 400]
    if not loud:
        return pcm
    k = int(rate * keep)
    return s[max(loud[0] - k, 0): loud[-1] + k + 1].tobytes()


def _gemini(lines: list[str], out_dir: Path, voice: str | None = None) -> dict:
    """Mỗi câu một lần gọi (Gemini không trả mốc thời gian từng từ, nên đo độ dài từng câu cho chính xác), nối bằng
    khoảng lặng ngắn thành một file wav; mốc ký tự = None (phụ đề chia theo thời gian câu như giọng macOS)."""
    name = gemini_voice(voice)
    model = config.env("GEMINI_TTS_MODEL") or GEMINI_MODEL
    chunks: list[bytes] = []
    spans: list[dict] = []
    rate, t = 24000, 0.0
    for ln in lines:
        text = ln.strip()
        pcm = b""
        if text:
            pcm, rate = _gemini_once(text, model, name)
            pcm = _trim(pcm, rate)
        gap = bytes(2 * int(rate * GEMINI_GAP))
        d = len(pcm) / 2 / rate + GEMINI_GAP
        chunks += [pcm, gap]
        spans.append({"start": round(t, 3), "end": round(t + d, 3)})
        t += d
    audio = out_dir / "narration.wav"
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(chunks))
    return {"audio": str(audio), "duration": t, "lines": spans, "provider": "gemini", "voice": name,
            "model": model, "alignment": None}


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
