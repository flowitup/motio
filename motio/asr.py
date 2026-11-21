"""Bóc lời: mlx-whisper trên Mac Apple Silicon, faster-whisper ở nơi khác. Có cache JSON cạnh file."""
import json
import subprocess
import threading
from pathlib import Path

from . import config
from .i18n import tr

MLX_DEFAULT = "mlx-community/whisper-large-v3-turbo"
FASTER_DEFAULT = "large-v3-turbo"
# Whisper chạy trong tiến trình của engine và không có giới hạn thời gian riêng: nếu nó treo, hàng đợi một-việc-mỗi-lúc
# đứng mãi. Giới hạn rộng (lần đầu còn tải model vài GB, CPU int8 chậm hơn thời gian thực): chỉ để không chờ vô hạn.
TIMEOUT_BASE = 60 * 60
TIMEOUT_PER_SECOND = 10


class Stuck(RuntimeError):
    """Whisper không trả kết quả trong giới hạn: bước bóc lời lỗi, hàng đợi chạy tiếp."""


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
                        str(out)], check=True, timeout=20 * 60)
    return out


def has_audio(src: Path) -> bool:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", str(src)], capture_output=True, text=True,
                       timeout=120)
    return bool(r.stdout.strip())


def time_limit(wav: Path) -> float:
    """Giới hạn cho một lần bóc lời, theo độ dài file wav 16 kHz mono 16 bit (32 000 byte mỗi giây)."""
    try:
        seconds = wav.stat().st_size / 32000
    except OSError:
        seconds = 0
    return TIMEOUT_BASE + TIMEOUT_PER_SECOND * seconds


def bounded(fn, limit: float):
    """Chạy fn() trong một luồng phụ và chờ tối đa `limit` giây. Quá giờ: Stuck (luồng phụ là daemon, bị bỏ lại; một
    luồng Python không dừng từ ngoài được, nên lời khuyên là khởi động lại engine)."""
    box: dict = {}

    def work():
        try:
            box["value"] = fn()
        except BaseException as e:  # lỗi của Whisper phải nổi lên ở luồng gọi, không chết lặng trong luồng phụ
            box["error"] = e

    t = threading.Thread(target=work, name="whisper", daemon=True)
    t.start()
    t.join(limit)
    if t.is_alive():
        raise Stuck(tr("Transcription did not finish after {minutes} min: restart Motio, then continue the project",
                       minutes=round(limit / 60)))
    if "error" in box:
        raise box["error"]
    return box["value"]


_faster: dict = {}
_faster_lock = threading.Lock()


def faster_model():
    """Model faster-whisper, nạp một lần cho mỗi (tên, thiết bị): trước đây mỗi nguồn nạp lại từ đĩa."""
    from faster_whisper import WhisperModel
    device, compute_type = faster_device()
    key = (model_name(), device, compute_type)
    with _faster_lock:
        if key not in _faster:
            _faster.clear()  # đổi model trong Cài đặt: bỏ model cũ khỏi bộ nhớ
            _faster[key] = WhisperModel(key[0], device=device, compute_type=compute_type)
        return _faster[key]


def _whisper(wav: Path) -> tuple[list[dict], str | None]:
    if config.IS_APPLE_SILICON:
        import mlx_whisper
        config.put_ffmpeg_on_path()
        r = mlx_whisper.transcribe(str(wav), path_or_hf_repo=model_name(),
                                   condition_on_previous_text=False)
        return ([{"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
                 for s in r.get("segments", [])], r.get("language"))
    it, info = faster_model().transcribe(str(wav), vad_filter=True)
    return ([{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in it],
            info.language)


def transcribe(src: Path) -> dict:
    src = Path(src)
    cache = src.with_suffix(".transcript.json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if not has_audio(src):
        result = {"language": None, "segments": []}
    else:
        wav = _wav(src)
        segs, lang = bounded(lambda: _whisper(wav), time_limit(wav))
        result = {"language": lang, "segments": [s for s in segs if s["text"]]}
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
