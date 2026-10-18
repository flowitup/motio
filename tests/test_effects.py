"""Effects the user turns on per source: mirror, colour filter. Checked, saved per link, handed to the render, and
made for real with FFmpeg."""
import subprocess

import pytest
from PIL import Image

from motio import config, db, effects, render


def _project(sources: list[dict], mode: str = "news") -> int:
    pid = db.create_project(None, "x", mode=mode)
    db.update_project(pid, status="done", meta={"sources": sources})
    return pid


def test_clean():
    assert effects.clean(None) == effects.NONE
    got = effects.clean({"mirror": 1, "reverse": True, "color": "warm", "other": 3})  # old / unknown keys dropped
    assert got == {"mirror": True, "color": "warm"}
    assert effects.clean({"color": ""})["color"] is None
    for bad in ({"color": "neon"}, "mirror", [True]):
        with pytest.raises(ValueError):
            effects.clean(bad)
    assert set(effects.COLORS) == {"warm", "cool", "mono", "sepia", "vivid", "faded"}


def test_update_attach_and_view():
    clip = config.CACHE / "sources" / "fx_a.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"x")
    srcs = [{"url": "https://a", "path": str(clip)}, {"url": "https://b", "path": "/gone.mp4"}]
    pid = _project(srcs)
    a = {"mirror": True, "color": "sepia"}
    assert effects.update(pid, [a, {}]) is True
    p = db.get_project(pid)
    assert p["meta"]["effects"] == {"https://a": a}
    assert "Effects changed: Source 1: mirrored, colour filter sepia" in p["log"]
    assert effects.update(pid, [a, None]) is False  # nothing changed
    view = effects.view(p)
    assert view["whole_video"] is False and "warm" in view["colors"]
    assert view["sources"] == [{"media": "cache/sources/fx_a.mp4", **a}, {"media": None, **effects.NONE}]
    got = effects.attach(p, [{"url": "https://a", "path": "x"}, {"url": "https://b", "path": "y"}])
    assert got[0]["effects"] == a and got[1]["effects"] is None
    with pytest.raises(ValueError):
        effects.update(pid, [a])  # one entry per source
    with pytest.raises(LookupError):
        effects.update(99999, [])
    assert effects.update(pid, [{}, {}]) is True and db.get_project(pid)["meta"]["effects"] == {}


def test_any_source_may_use_effects():
    pid = _project([{"url": "https://a", "path": "/x.mp4"}])
    assert effects.update(pid, [{"mirror": True}]) is True
    assert effects.view(db.get_project(pid))["sources"][0]["mirror"] is True
    got = effects.attach(db.get_project(pid), [{"url": "https://a", "path": "x"}])
    assert got[0]["effects"] == {"mirror": True, "color": None}


def test_ai_video_has_one_setting_for_every_scene():
    pid = _project([], mode="ai")
    p = db.get_project(pid)
    assert effects.view(p) == {"whole_video": True, "colors": list(effects.COLORS),
                               "sources": [{"media": None, **effects.NONE}]}
    assert effects.update(pid, [{"mirror": True, "color": "vivid"}]) is True
    p = db.get_project(pid)
    assert "Effects changed: mirrored, colour filter vivid" in p["log"]
    scenes = effects.attach(p, [{"path": "1.png", "url": None}, {"path": "2.png", "url": None}])
    assert [s["effects"] for s in scenes] == [{"mirror": True, "color": "vivid"}] * 2


def test_no_source_yet():
    pid = _project([])
    assert effects.view(db.get_project(pid)) is None
    with pytest.raises(ValueError):
        effects.update(pid, [])


def test_effect_filter():
    assert render.effect_filter(None) == "" and render.effect_filter(effects.NONE) == ""
    assert render.effect_filter({"mirror": True}) == "hflip"
    assert render.effect_filter({"mirror": True, "color": "mono"}) == "hflip,hue=s=0"


ffmpeg = pytest.mark.skipif(not config.find("ffmpeg"), reason="needs ffmpeg")


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
