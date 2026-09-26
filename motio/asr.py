"""Bóc lời: mlx-whisper trên Mac Apple Silicon, faster-whisper ở nơi khác. Có cache JSON cạnh file."""
import json
import subprocess
from pathlib import Path

from . import config

MLX_DEFAULT = "mlx-community/whisper-large-v3-turbo"
FASTER_DEFAULT = "large-v3-turbo"


def engine_name() -> str:
    return "mlx-whisper" if config.IS_APPLE_SILICON else "faster-whisper"


def model_name() -> str:
    """WHISPER_MODEL; tên repo mlx-community/* chỉ dùng được với mlx, nơi khác quay về mặc định faster-whisper."""
    name = config.env("WHISPER_MODEL") or config.env("FASTER_WHISPER_MODEL")
    if config.IS_APPLE_SILICON:
        return name or MLX_DEFAULT
    if not name or name.startswith("mlx-community/"):
        return FASTER_DEFAULT
    return name


def faster_device() -> tuple[str, str]:
    """(device, compute_type): cuda float16 nếu có GPU NVIDIA, không thì cpu int8."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _wav(src: Path) -> Path:
    out = src.with_suffix(".16k.wav")
    if not out.exists():
        subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                        str(out)], check=True)
    return out


def has_audio(src: Path) -> bool:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-select_streams", "a", "-show_entries",
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
        if config.IS_APPLE_SILICON:
            import mlx_whisper
            r = mlx_whisper.transcribe(str(wav), path_or_hf_repo=model_name(),
                                       condition_on_previous_text=False)
            segs = [{"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
                    for s in r.get("segments", [])]
            lang = r.get("language")
        else:
            from faster_whisper import WhisperModel
            device, compute_type = faster_device()
            model = WhisperModel(model_name(), device=device, compute_type=compute_type)
            it, info = model.transcribe(str(wav), vad_filter=True)
            segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in it]
            lang = info.language
        result = {"language": lang, "segments": [s for s in segs if s["text"]]}
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result
