import subprocess

import pytest

from motio import config, scenes

pytestmark = pytest.mark.skipif(not config.find("ffmpeg"), reason="needs ffmpeg")


def test_detect_finds_hard_cuts_and_caches(tmp_path):
    src = tmp_path / "cuts.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error",
                    "-f", "lavfi", "-i", "color=c=red:size=320x180:rate=25:duration=2",
                    "-f", "lavfi", "-i", "color=c=blue:size=320x180:rate=25:duration=2",
                    "-f", "lavfi", "-i", "color=c=green:size=320x180:rate=25:duration=2",
                    "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", str(src)], check=True)
    cuts = scenes.detect(src)
    assert [round(c) for c in cuts] == [2, 4]
    assert src.with_suffix(".scenes.json").exists()
    src.write_bytes(b"")  # lần sau đọc cache, không chạy FFmpeg
    assert scenes.detect(src) == cuts


def test_detect_returns_empty_on_bad_file(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    assert scenes.detect(bad) == []
