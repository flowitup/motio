"""Phát hiện chuyển cảnh (cú cắt) bằng bộ lọc scene của FFmpeg, không cần OpenCV. Có cache JSON cạnh file."""
import json
import re
import subprocess
from pathlib import Path

from . import config

THRESHOLD = 0.3  # điểm scene 0–1 của FFmpeg; 0.3 bắt được cắt cứng, bỏ qua lia máy / zoom


def detect(src: Path, threshold: float = THRESHOLD) -> list[float]:
    """Mốc (giây) các cú cắt trong video. Lỗi FFmpeg thì trả [] để việc dựng vẫn chạy."""
    src = Path(src)
    cache = src.with_suffix(".scenes.json")
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("threshold") == threshold:
                return data["cuts"]
        except (OSError, ValueError, KeyError):
            pass
    r = subprocess.run([config.ffmpeg(), "-hide_banner", "-nostats", "-i", str(src), "-an", "-sn", "-vf",
                        f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return []
    cuts = sorted({round(float(t), 3) for t in re.findall(r"pts_time:\s*([0-9.]+)", r.stderr)})
    cache.write_text(json.dumps({"threshold": threshold, "cuts": cuts}), encoding="utf-8")
    return cuts
