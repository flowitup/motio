"""Bóc lời: mlx-whisper trên Mac Apple Silicon, faster-whisper ở nơi khác. Có cache JSON cạnh file."""
import json
import platform
import subprocess
from pathlib import Path

from . import config


def _wav(src: Path) -> Path:
    out = src.with_suffix(".16k.wav")
    if not out.exists():
        subprocess.run([config.FFMPEG, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                        str(out)], check=True)
    return out


def has_audio(src: Path) -> bool:
    r = subprocess.run([config.FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", str(src)], capture_output=True, text=True)
    return bool(r.stdout.strip())


def transcribe(src: Path) -> dict:
    src = Path(src)
    cache = src.with_suffix(".transcript.json")
    if cache.exists():
        return json.loads(cache.read_text())
    if not has_audio(src):
        result = {"language": None, "segments": []}
    else:
        wav = _wav(src)
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            import mlx_whisper
            r = mlx_whisper.transcribe(str(wav), path_or_hf_repo=config.WHISPER_MODEL,
                                       condition_on_previous_text=False)
            segs = [{"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
                    for s in r.get("segments", [])]
            lang = r.get("language")
        else:
            from faster_whisper import WhisperModel
            model = WhisperModel(config.env("FASTER_WHISPER_MODEL", "large-v3-turbo"), compute_type="int8")
            it, info = model.transcribe(str(wav), vad_filter=True)
            segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in it]
            lang = info.language
        result = {"language": lang, "segments": [s for s in segs if s["text"]]}
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result
