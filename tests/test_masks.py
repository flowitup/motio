"""Những gì người dùng vẽ trên từng nguồn: khung làm mờ (có thể phủ logo của mình), vùng giữ lại (phóng to). Kiểm tra,
lưu theo link, đưa vào render, và dựng thật bằng FFmpeg."""
import io
import subprocess

import pytest
from PIL import Image, ImageFilter, ImageStat

from motio import config, db, dub, logos, masks, render


def _project(sources: list[dict], mode: str = "news") -> int:
    pid = db.create_project(None, "x", mode=mode)
    db.update_project(pid, status="done", meta={"sources": sources})
    return pid


def _png(color=(255, 0, 0, 255), size=(200, 100)) -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf


@pytest.fixture
def red_logo():
    for lg in logos.list_all():
        logos.remove(lg["id"])
    return logos.add("My Logo.png", _png())


def test_logo_library(red_logo):
    assert red_logo["name"] == "My Logo" and red_logo["media"] == f"logos/{red_logo['id']}.png"
    assert (red_logo["width"], red_logo["height"]) == (200, 100)
    assert logos.add("again.png", _png())["id"] == red_logo["id"]  # same picture: one logo
    assert [lg["id"] for lg in logos.list_all()] == [red_logo["id"]]
    big = logos.add("big.jpg", _png((0, 0, 255, 255), (3000, 1500)))
    assert (big["width"], big["height"]) == (logos.MAX_SIDE, logos.MAX_SIDE // 2)
    for bad in (io.BytesIO(b"not a picture"), _png((0, 0, 0, 0))):
        with pytest.raises(ValueError):
            logos.add("x.png", bad)
    assert logos.path("../motio") is None and logos.path(None) is None
    logos.remove(big["id"])
    with pytest.raises(LookupError):
        logos.remove(big["id"])


def test_clean(red_logo):
    assert masks.clean(None) == {"boxes": [], "keep": None}
    got = masks.clean({"boxes": [[0.8, 0.02, 0.5, 0.1], None, {"box": [0, 0.85, 1, 0.12], "logo": red_logo["id"]}],
                       "keep": [0.1, 0.0, 0.8, 0.8]})
    assert got == {"boxes": [{"box": [0.8, 0.02, 0.2, 0.1], "logo": None},  # clipped to the frame
                             {"box": [0.0, 0.85, 1.0, 0.12], "logo": red_logo["id"]}],
                   "keep": [0.1, 0.0, 0.8, 0.8]}
    assert masks.clean({"keep": [0, 0, 1, 1]})["keep"] is None  # the whole frame is no zoom
    for bad in ({"boxes": [[0.1, 0.1, 0.01, 0.1]]},  # too small
                {"boxes": [[0.1, 0.1, 0.1, 0.1]] * (masks.MAX_BOXES + 1)},
                {"boxes": [{"box": [0.1, 0.1, 0.2, 0.2], "logo": "0123456789abcdef"}]},  # no such logo
                {"keep": [0.1, 0.1, 0.2, 0.9]},  # keep area too small (more than 4× zoom)
                {"boxes": "box"}, "box"):
        with pytest.raises(ValueError):
            masks.clean(bad)


def test_update_attach_and_view(tmp_path, red_logo):
    clip = config.CACHE / "sources" / "masks_a.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"x")
    srcs = [{"url": "https://a", "path": str(clip), "duration": 12.0}, {"url": "https://b", "path": "/gone.mp4"}]
    pid = _project(srcs)
    a = {"boxes": [[0.8, 0.02, 0.15, 0.08], {"box": [0, 0.85, 1, 0.12], "logo": red_logo["id"]}],
         "keep": [0.1, 0.0, 0.8, 0.8]}
    assert masks.update(pid, [a, {}]) is True
    p = db.get_project(pid)
    saved = p["meta"]["masks"]["https://a"]
    assert list(p["meta"]["masks"]) == ["https://a"] and saved["keep"] == [0.1, 0.0, 0.8, 0.8]
    assert "Source 1: 2 blur boxes, 1 logo, zoomed in" in p["log"]
    assert masks.update(pid, [a, None]) is False  # nothing changed
    view = masks.view(p)
    assert view[0] == {"media": "cache/sources/masks_a.mp4", "duration": 12.0, "boxes": saved["boxes"],
                       "keep": saved["keep"]}
    assert view[1] == {"media": None, "duration": None, "boxes": [], "keep": None}
    assert masks.update(pid, [{}, {}]) is True and db.get_project(pid)["meta"]["masks"] == {}
    with pytest.raises(ValueError):
        masks.update(pid, [{}])  # one entry per source
    with pytest.raises(LookupError):
        masks.update(99999, [])
    ai = _project([], mode="ai")
    assert masks.view(db.get_project(ai)) is None
    with pytest.raises(ValueError):
        masks.update(ai, [])


def test_dub_keeps_subtitle_band_and_user_boxes(monkeypatch):
    monkeypatch.setattr(dub, "timeline", lambda nar: [])
    proj = {"meta": {"dub": {"blur": [0, 0.8, 1, 0.15]}}}
    nar = {"total": 10.0, "lines": [], "duration": 9.0}
    args = dub.render_args(proj, {"lines": []}, [{"path": "a", "blur": [[0.8, 0.02, 0.15, 0.08]]}], nar)
    assert args["sources"][0]["blur"] == [[0, 0.8, 1, 0.15], [0.8, 0.02, 0.15, 0.08]]
    args = dub.render_args({"meta": {}}, {"lines": []}, [{"path": "a", "blur": None}], nar)
    assert args["sources"][0]["blur"] is None


def test_blur_filter_one_or_many_boxes():
    assert render.blur_filter(None) == "" and render.blur_filter([]) == ""
    one = render.blur_filter([0.1, 0.2, 0.3, 0.4])
    assert one == render.blur_filter([[0.1, 0.2, 0.3, 0.4]]) and one.count("gblur") == 1
    two = render.blur_filter([[0.1, 0.2, 0.3, 0.4], [0.5, 0.5, 0.2, 0.2]])
    assert two.count("gblur") == 2 and "[bo1]" in two and "overlay=W*0.5000:H*0.5000" in two


def test_cover_png_fits_each_logo_in_its_box(tmp_path, red_logo):
    boxes = [{"box": [0.5, 0.5, 0.5, 0.5], "logo": red_logo["id"]}, {"box": [0, 0, 0.2, 0.2], "logo": None}]
    out = masks.cover_png(boxes, (400, 200), tmp_path / "cover.png")
    pic = Image.open(out)
    assert pic.size == (400, 200) and pic.getpixel((10, 10))[3] == 0  # a box without a logo stays clear
    # the 2:1 logo fits the 200x100 box exactly
    assert pic.getbbox() == (200, 100, 400, 200) and pic.getpixel((300, 150)) == (255, 0, 0, 255)
    assert masks.cover_png([{"box": [0, 0, 1, 1], "logo": None}], (400, 200), tmp_path / "none.png") is None


ffmpeg = pytest.mark.skipif(not config.find("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture
def board(tmp_path):
    """A 640x360 checkerboard video: sharp edges everywhere, so a blurred area shows."""
    png = tmp_path / "board.png"
    Image.frombytes("L", (640, 360), bytes(255 * ((x // 16 + y // 16) % 2) for y in range(360) for x in range(640))
                    ).save(png)
    src = tmp_path / "src.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-loop", "1", "-t", "2", "-i", str(png), "-r", "25",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    overlay = tmp_path / "overlay.png"
    Image.new("RGBA", (render.VERTICAL.w, render.VERTICAL.h), (0, 0, 0, 0)).save(overlay)

    def frame(name: str, **extra) -> Image.Image:
        out = tmp_path / f"{name}.mp4"
        render.render_piece(render.Piece(0, 0.0, 1.0, 0.0), {"path": str(src), **extra}, overlay, out)
        png = tmp_path / f"{name}.png"
        subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-ss", "0.5", "-i", str(out), "-frames:v", "1",
                        str(png)], check=True)
        return Image.open(png).convert("RGB")

    return frame


def _detail(im: Image.Image, box) -> float:  # sharp edges in the area: a blurred one has almost none
    return ImageStat.Stat(im.convert("L").crop(box).filter(ImageFilter.FIND_EDGES)).mean[0]


# the 640x360 source fills the frame's width (→ 1080x608, centred)
TOP, H = (render.VERTICAL.h - 608) // 2, 608


@ffmpeg
def test_render_piece_blurs_only_the_boxes(board):
    plain, blurred = board("plain"), board("blurred", blur=[[0.0, 0.0, 0.5, 1.0], [0.75, 0.0, 0.25, 0.5]])
    left, right_low = (40, TOP + 40, 500, TOP + H - 40), (840, TOP + H // 2 + 40, 1040, TOP + H - 40)
    assert _detail(blurred, left) < _detail(plain, left) / 3
    assert abs(_detail(blurred, right_low) - _detail(plain, right_low)) < _detail(plain, right_low) / 4  # untouched


@ffmpeg
def test_render_piece_covers_a_box_with_a_logo(board, tmp_path, red_logo):
    boxes = [{"box": [0.0, 0.0, 0.5, 1.0], "logo": red_logo["id"]}]
    cover = masks.cover_png(boxes, (640, 360), tmp_path / "cover.png")
    pic = board("logo", blur=[b["box"] for b in boxes], cover=str(cover))
    r, g, b = pic.getpixel((270, TOP + H // 2))  # middle of the left half: the red logo
    assert r > 200 and g < 60 and b < 60
    r, g, b = pic.getpixel((270, TOP + 40))  # above the 2:1 logo, still inside the box: blurred board, not red
    assert abs(r - g) < 40


@ffmpeg
def test_render_piece_keeps_only_the_area(board):
    plain, zoomed = board("plain"), board("zoomed", keep=[0.25, 0.25, 0.5, 0.5])
    # half the width fills the whole frame width: squares are twice as big, so half as many edges per line
    row = (40, TOP + H // 2 - 20, 1040, TOP + H // 2 + 20)
    assert _detail(zoomed, row) < _detail(plain, row) * 0.7
