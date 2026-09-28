"""Dựng thật bằng FFmpeg (bỏ qua khi máy không có FFmpeg): bản 9:16 và bản 16:9 cùng các mảnh, giọng đọc, phụ đề."""
import json
import subprocess

import pytest
from PIL import Image

from motio import config, render

pytestmark = pytest.mark.skipif(not config.find("ffmpeg"), reason="needs ffmpeg")


def _probe(path) -> dict:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    data = json.loads(r.stdout)
    return {**data["streams"][0], "duration": float(data["format"]["duration"])}


def test_render_vertical_and_wide_copy(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:d=12",
                    "-f", "lavfi", "-i", "sine=f=300:d=12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(src)], check=True)
    voice = tmp_path / "voice.m4a"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=500:d=6", "-c:a", "aac",
                    str(voice)], check=True)
    plan = {"title_fr": "La Chine lance un train à grande vitesse",
            "lines": [{"text": "Premier point du sujet", "clips": [{"src": 0, "start": 1, "end": 4}]},
                      {"text": "Deuxième point, pour finir", "clips": []}]}
    nar = {"audio": str(voice), "duration": 6.0, "lines": [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.0}]}
    sources = [{"path": str(src), "duration": 12.0, "platform": "youtube", "uploader": "test", "url": "u"}]
    out = tmp_path / "out"
    steps = []
    res = render.render(plan, sources, nar, out, progress=lambda d, t: steps.append((d, t)), badge="ACTU CHINE",
                        wide=True)
    tall, wide = _probe(res["video"]), _probe(res["wide"])
    assert (tall["width"], tall["height"]) == (1080, 1920) and (wide["width"], wide["height"]) == (1920, 1080)
    assert abs(tall["duration"] - wide["duration"]) < 0.2 and tall["duration"] >= 6.0
    assert res["wide"].endswith("final_wide.mp4") and steps[-1][0] == steps[-1][1] == 2 * res["pieces"]
    frame = out / "wide.jpg"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-ss", "2", "-i", res["wide"], "-frames:v", "1",
                    str(frame)], check=True)
    assert Image.open(frame).size == (1920, 1080)
    assert not render.render(plan, sources, nar, tmp_path / "only", badge="")["wide"]
