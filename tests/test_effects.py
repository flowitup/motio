"""Effects the user turns on per source: mirror, reverse, colour filter. Only for footage owned / licensed / CC, or an
AI video. Checked, saved per link, handed to the render, and made for real with FFmpeg."""
import json
import subprocess

import pytest
from PIL import Image, ImageStat

from motio import config, db, effects, render


def _project(sources: list[dict], mode: str = "news", rights: str | None = "owned") -> int:
    pid = db.create_project(None, "x", mode=mode)
    db.update_project(pid, status="done", meta={"sources": sources, **({"rights": rights} if rights else {})})
    return pid


def test_clean():
    assert effects.clean(None) == effects.NONE
    assert effects.clean({"mirror": 1, "reverse": "", "color": "warm", "other": 3}) == \
        {"mirror": True, "reverse": False, "color": "warm"}
    assert effects.clean({"color": ""})["color"] is None
    for bad in ({"color": "neon"}, "mirror", [True]):
        with pytest.raises(ValueError):
            effects.clean(bad)
    assert set(effects.COLORS) == {"warm", "cool", "mono", "sepia", "vivid", "faded"}


def test_allowed_only_for_owned_footage_or_ai():
    for rights, ok in (("owned", True), ("licensed", True), ("cc", True), ("unknown", False), (None, False)):
        assert effects.allowed({"mode": "topic", "meta": {"rights": rights}}) is ok
    assert effects.allowed({"mode": "ai", "meta": {}}) is True


def test_update_attach_and_view():
    clip = config.CACHE / "sources" / "fx_a.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"x")
    srcs = [{"url": "https://a", "path": str(clip)}, {"url": "https://b", "path": "/gone.mp4"}]
    pid = _project(srcs)
    a = {"mirror": True, "reverse": True, "color": "sepia"}
    assert effects.update(pid, [a, {}]) is True
    p = db.get_project(pid)
    assert p["meta"]["effects"] == {"https://a": a}
    assert "Effects changed: Source 1: mirrored, reversed, colour filter sepia" in p["log"]
    assert effects.update(pid, [a, None]) is False  # nothing changed
    view = effects.view(p)
    assert view["allowed"] is True and view["whole_video"] is False and "warm" in view["colors"]
    assert view["sources"] == [{"media": "cache/sources/fx_a.mp4", **a}, {"media": None, **effects.NONE}]
    got = effects.attach(p, [{"url": "https://a", "path": "x"}, {"url": "https://b", "path": "y"}])
    assert got[0]["effects"] == a and got[1]["effects"] is None
    with pytest.raises(ValueError):
        effects.update(pid, [a])  # one entry per source
    with pytest.raises(LookupError):
        effects.update(99999, [])
    assert effects.update(pid, [{}, {}]) is True and db.get_project(pid)["meta"]["effects"] == {}


def test_locked_while_rights_are_unknown():
    pid = _project([{"url": "https://a", "path": "/x.mp4"}], rights="unknown")
    with pytest.raises(ValueError, match="rights"):
        effects.update(pid, [{"mirror": True}])
    assert effects.update(pid, [{}]) is False  # turning everything off is always allowed
    assert effects.view(db.get_project(pid))["allowed"] is False
    # saved while owned, then the rights went back to unknown: the render leaves them out
    db.update_project(pid, meta={"rights": "owned"})
    effects.update(pid, [{"color": "mono"}])
    db.update_project(pid, meta={"rights": "unknown"})
    p = db.get_project(pid)
    assert effects.skipped(p) is True
    assert effects.attach(p, [{"url": "https://a", "path": "x"}])[0]["effects"] is None


def test_ai_video_has_one_setting_for_every_scene():
    pid = _project([], mode="ai", rights=None)
    p = db.get_project(pid)
    assert effects.view(p) == {"allowed": True, "whole_video": True, "colors": list(effects.COLORS),
                               "sources": [{"media": None, **effects.NONE}]}
    assert effects.update(pid, [{"reverse": True, "color": "vivid"}]) is True
    p = db.get_project(pid)
    assert "Effects changed: reversed, colour filter vivid" in p["log"]
    scenes = effects.attach(p, [{"path": "1.png", "url": None}, {"path": "2.png", "url": None}])
    assert [s["effects"] for s in scenes] == [{"mirror": False, "reverse": True, "color": "vivid"}] * 2


def test_no_source_yet():
    pid = _project([])
    assert effects.view(db.get_project(pid)) is None
    with pytest.raises(ValueError):
        effects.update(pid, [])


def test_effect_filter():
    assert render.effect_filter(None) == "" and render.effect_filter(effects.NONE) == ""
    assert render.effect_filter({"mirror": True}) == "hflip"
    assert render.effect_filter({"mirror": True, "color": "mono"}) == "hflip,hue=s=0"
    assert set(render.REVERSED_MOTION) == set(render.MOTIONS)
    assert all(render.REVERSED_MOTION[render.REVERSED_MOTION[m]] == m for m in render.MOTIONS)


ffmpeg = pytest.mark.skipif(not config.find("ffmpeg"), reason="needs ffmpeg")


def _grey(path, at: float) -> float:
    png = path.with_suffix(f".{at}.png")
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-ss", f"{at}", "-i", str(path), "-frames:v", "1", str(png)],
                   check=True)
    return ImageStat.Stat(Image.open(png).convert("L")).mean[0]


def _length(path) -> float:
    r = subprocess.run([config.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


@pytest.fixture
def ramp(tmp_path):
    """4 s from black to white, with a tone: brighter means later."""
    src = tmp_path / "ramp.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=64x64:d=4:r=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-vf", "fade=in:st=0:d=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
    return src


@ffmpeg
def test_reversed_segment_plays_backwards_in_chunks(ramp, tmp_path):
    out = render.reversed_segment(str(ramp), 0.5, 3.0, True, tmp_path)
    assert abs(_length(out) - 3.0) < 0.15
    first, middle, last = _grey(out, 0.1), _grey(out, 1.5), _grey(out, 2.85)
    assert first > middle > last and first - last > 120
    assert render.reversed_segment(str(ramp), 0.5, 3.0, True, tmp_path) == out  # kept for the 16:9 copy
    assert sorted(f.name for f in tmp_path.glob("rev_*.mkv")) == [out.name]  # chunks cleaned up


@pytest.fixture
def overlay(tmp_path):
    png = tmp_path / "overlay.png"
    Image.new("RGBA", (render.VERTICAL.w, render.VERTICAL.h), (0, 0, 0, 0)).save(png)
    return png


def _frame(src, overlay, tmp_path, name: str, piece: render.Piece, at: float = 0.5, **extra) -> Image.Image:
    out = tmp_path / f"{name}.mp4"
    render.render_piece(piece, {"path": str(src), **extra}, overlay, out)
    png = tmp_path / f"{name}.png"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-ss", f"{at}", "-i", str(out), "-frames:v", "1", str(png)],
                   check=True)
    return Image.open(png).convert("RGB")


@ffmpeg
def test_render_piece_mirrors_and_filters(tmp_path, overlay):
    pic = Image.new("RGB", (640, 360), (220, 30, 30))
    pic.paste((30, 30, 220), (320, 0, 640, 360))  # red left, blue right
    pic.save(tmp_path / "halves.png")
    src = tmp_path / "halves.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-loop", "1", "-t", "2", "-i", str(tmp_path / "halves.png"),
                    "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    mid = render.VERTICAL.h // 2
    piece = render.Piece(0, 0.0, 1.0, 0.0)
    plain = _frame(src, overlay, tmp_path, "plain", piece)
    assert plain.getpixel((200, mid))[0] > 150  # red on the left
    flipped = _frame(src, overlay, tmp_path, "flip", piece, effects={"mirror": True})
    r, g, b = flipped.getpixel((200, mid))
    assert b > 150 and r < 100  # blue on the left
    r, g, b = _frame(src, overlay, tmp_path, "mono", piece, effects={"color": "mono"}).getpixel((200, mid))
    assert max(r, g, b) - min(r, g, b) < 12


@ffmpeg
def test_render_piece_reverses_the_source(ramp, tmp_path, overlay):
    piece = render.Piece(0, 0.5, 2.5, 0.0)
    fx = {"reverse": True}
    early = _frame(ramp, overlay, tmp_path, "rev_early", piece, at=0.1, effects=fx, has_audio=True)
    late = _frame(ramp, overlay, tmp_path, "rev_late", piece, at=2.3, effects=fx, has_audio=True)
    mid = (render.VERTICAL.w // 2, render.VERTICAL.h // 2)
    assert early.getpixel(mid)[0] > late.getpixel(mid)[0] + 80  # plays from bright (late) to dark (early)
