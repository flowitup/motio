"""Dựng video 9:16 (và bản 16:9 khi kênh cần) bằng FFmpeg + lớp chữ vẽ bằng Pillow.

FFmpeg của Homebrew không có libass / drawtext, nên chữ được vẽ thành PNG trong suốt rồi overlay.
Cách này chạy được với mọi bản FFmpeg.
- Mỗi mảnh clip: nền mờ + clip + lớp tiêu đề và nhãn (tĩnh), mã hoá riêng rồi nối lại.
- Phụ đề karaoke: chuỗi PNG có thời lượng (concat demuxer), overlay một lần ở bước trộn cuối.
- Bản 16:9 dùng lại đúng các mảnh, giọng đọc và phụ đề của bản 9:16, chỉ đổi bố cục (Layout).
"""
import dataclasses
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import captions, config, looks, scenes
from .asr import has_audio
from .i18n import tr

W, H, FPS = config.W, config.H, config.FPS
VIDEO_BOTTOM = (H + W * 9 // 16) // 2  # mép dưới của clip 16:9 đặt giữa khung
NARRATION_DELAY = 0.15  # giọng đọc vào trễ 150 ms (adelay ở bước trộn): phụ đề dời theo
TAIL = 0.6  # giây hình sau câu cuối
SRC_VOLUME = 0.10  # âm lượng tiếng của nguồn dưới giọng đọc (0 = im: video không còn giọng gốc)
CAP_TOP = VIDEO_BOTTOM + 100  # dải phụ đề, ngay dưới clip
CAP_SIZE, CAP_LINE = 60, 78
CAP_H = captions.MAX_LINES * CAP_LINE + 40
CAP_MAX_W = W - 120
SPOKEN = (255, 214, 10)  # từ đã đọc (karaoke)

FONT_BOLD = config.font_candidates("bold")
FONT_CJK = config.font_candidates("cjk")


@dataclass(frozen=True)
class Layout:
    """Bố cục một khổ video. Cỡ chữ và khoảng cách của băng tiêu đề nhân với `scale` (9:16 = 1)."""
    w: int
    h: int
    prefix: str  # tiền tố tên file tạm và file kết quả ("" cho 9:16)
    scale: float
    title_x: int  # mép trái băng tiêu đề (và nhãn nguồn)
    title_y: int
    title_lines: int  # số dòng tiêu đề tối đa
    title_wrap: int  # bề ngang tối đa một dòng tiêu đề
    fit_box: bool  # băng tiêu đề ôm vừa chữ (16:9) thay vì trải hết bề ngang (9:16)
    cap_top: int
    cap_size: int
    cap_line: int
    cjk: bool = False  # phụ đề có chữ Trung / Nhật / Hàn: dùng font CJK

    def k(self, v: float) -> int:
        return round(v * self.scale)

    @property
    def cap_h(self) -> int:
        return captions.MAX_LINES * self.cap_line + 40


VERTICAL = Layout(W, H, "", 1.0, 40, 150, 3, W - 140, False, CAP_TOP, CAP_SIZE, CAP_LINE)
WIDE_W, WIDE_H = 1920, 1080
_WIDE_CAP_LINE = 68
_WIDE_CAP_TOP = WIDE_H - (captions.MAX_LINES * _WIDE_CAP_LINE + 40) - 24  # dải phụ đề sát đáy khung
WIDE = Layout(WIDE_W, WIDE_H, "wide_", 0.8, 48, 40, 2, 1150, True, _WIDE_CAP_TOP, 52,
              _WIDE_CAP_LINE)


def _font(cands: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in cands:
        if p and Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def overlay_png(path: Path, *, title: str, badge: str = "", layout: Layout = VERTICAL,
                look: dict | None = None) -> Path:
    """Lớp tĩnh cỡ khung: băng tiêu đề (nhãn đỏ phía trên nếu có `badge`). Công bố giọng AI nằm trong bài đăng.
    look["title"]: màu, font, độ đậm của băng, hoặc ẩn hẳn (looks.py)."""
    L, k = layout, layout.k
    st = looks.clean(look)["title"]
    img = Image.new("RGBA", (L.w, L.h), (0, 0, 0, 0))
    if not st["show"]:
        img.save(path)
        return path
    d = ImageDraw.Draw(img)
    # Băng tiêu đề phía trên (hoặc ở phần dưới khung, theo look)
    f_badge, f_title = _font(looks.font_candidates(st["font"]), k(34)), _font(looks.font_candidates(st["font"]), k(58))
    marked = _marked(title, st["upper"])
    tl = _wrap_marked(d, marked, f_title, L.title_wrap)[:L.title_lines]
    x0, y0, pad, line = L.title_x, L.title_y, k(30), k(70)
    if st["pos"] == "lower":
        y0 = round(L.h * 0.64)
    top = k(92) if badge else k(30)  # không có nhãn: tiêu đề lên sát mép trên của băng
    box_h = top + len(tl) * line + k(8)
    bw = d.textlength(badge, font=f_badge) + k(36) if badge else 0
    widths = [d.textlength(" ".join(w for w, _ in ln), font=f_title) for ln in tl]
    if L.fit_box:
        x1 = x0 + 2 * pad + max([bw, *widths])
    else:
        x1 = L.w - x0
    d.rounded_rectangle((x0, y0, x1, y0 + box_h), radius=k(22), fill=looks.rgb(st["bar"], st["bar_alpha"]))
    if badge:
        bx = x0 + pad
        d.rounded_rectangle((bx, y0 + k(24), bx + bw, y0 + k(76)), radius=k(10), fill=looks.rgb(st["badge"], 1))
        d.text((bx + k(18), y0 + k(30)), badge, font=f_badge, fill="white")
    space = d.textlength(" ", font=f_title)
    for i, (ln, wd) in enumerate(zip(tl, widths, strict=True)):
        x = (x0 + x1 - wd) / 2 if st["align"] == "center" else x0 + pad
        for w, hot in ln:
            fill = st["accent"] if hot and st["accent"] else st["color"]
            d.text((x, y0 + top + i * line), w, font=f_title, fill=fill)
            x += d.textlength(w, font=f_title) + space
    img.save(path)
    return path


def _marked(title: str, upper: bool) -> list[tuple[str, bool]]:
    """The title's words, each with whether it was written between *stars* (the title's accent colour)."""
    out, hot = [], False
    for raw in title.split(" "):
        if not raw:
            continue
        starts, ends = raw.startswith("*"), raw.endswith("*") and len(raw) > 1
        hot = hot or starts
        word = raw.strip("*")
        if word:
            out.append((word.upper() if upper else word, hot))
        if ends:
            hot = False
    return out


def _wrap_marked(draw, words: list[tuple[str, bool]], font, max_w: int) -> list[list[tuple[str, bool]]]:
    """Like _wrap on words that carry a flag: lines of (word, flag), broken only at plain spaces."""
    lines, cur = [], []
    for w, hot in words:
        test = " ".join(x for x, _ in [*cur, (w, hot)])
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur.append((w, hot))
        else:
            lines.append(cur)
            cur = [(w, hot)]
    if cur:
        lines.append(cur)
    return lines


def look_layout(layout: Layout, look: dict | None) -> Layout:
    """The layout with the look's caption size and place: size scales the line height and the strip, `pos` moves it."""
    c = looks.clean(look)["caption"]
    k = c["size"] / looks.DEFAULT["caption"]["size"]
    size, line = round(layout.cap_size * k), round(layout.cap_line * k)
    out = dataclasses.replace(layout, cap_size=size, cap_line=line)
    if c["pos"] == "lower":
        top = round(layout.h * 0.66)
    elif c["pos"] == "middle":
        top = (layout.h - out.cap_h) // 2
    elif c["pos"] == "upper":
        top = round(layout.h * 0.13)
    else:
        top = layout.cap_top
    return dataclasses.replace(out, cap_top=top)


def caption_fits(look: dict | None = None) -> Callable[[str], bool]:
    """Một dòng phụ đề vừa khi ≤ 42 ký tự và lọt chiều ngang khung với font phụ đề (đúng font, cỡ, chữ hoa của look)."""
    c = looks.clean(look)["caption"]
    f = _font(looks.font_candidates(c["font"]), look_layout(VERTICAL, look).cap_size)
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    return lambda text: (len(text) <= captions.MAX_CHARS
                         and d.textlength(text.upper() if c["upper"] else text, font=f) <= CAP_MAX_W)


def _glow(size: tuple[int, int], spots: list[tuple], radius: int) -> Image.Image:
    """Neon: the lit words drawn once more in the glow colour, blurred, under the text."""
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for xy, text, font, color in spots:
        gd.text(xy, text, font=font, fill=color, stroke_width=max(radius // 3, 1), stroke_fill=color)
    return glow.filter(ImageFilter.GaussianBlur(radius))


def caption_png(path: Path, cue: captions.Cue | None, lit: int, layout: Layout = VERTICAL,
                look: dict | None = None) -> Path:
    """Dải phụ đề cỡ bề ngang khung × cap_h: `lit` từ đầu đã đọc (màu `spoken`), phần còn lại `color`. cue None = dải
    trống. `layout` đã chỉnh theo look (look_layout); look thêm: hộp sau dòng / từng từ, hộp màu cho từ đang đọc,
    chữ hoa, từ đang đọc phóng nhẹ (pop), ánh sáng (glow). Look mặc định vẽ đúng như trước khi có template."""
    L = layout
    c = looks.clean(look)["caption"]
    img = Image.new("RGBA", (L.w, L.cap_h), (0, 0, 0, 0))
    if cue:
        d = ImageDraw.Draw(img)
        f = _font(looks.font_candidates(c["font"], L.cjk), L.cap_size)
        big = _font(looks.font_candidates(c["font"], L.cjk), round(L.cap_size * (1 + c["pop"]))) if c["pop"] else f
        space = d.textlength(" ", font=f)
        text_of = (lambda s: s.upper()) if c["upper"] else (lambda s: s)
        ascent = f.getmetrics()[0]
        stroke_w = L.k(c["stroke_w"])
        on, off = looks.rgb(c["spoken"]), looks.rgb(c["color"])
        pad = round(L.cap_size * 0.18)
        boxes, words, glow = [], [], []
        n = 0
        for i, ln in enumerate(cue.lines):
            y = L.k(12) + i * L.cap_line
            widths = [d.textlength(text_of(w.text), font=big) for w in ln]  # room for the popped word: no jitter
            total = sum(widths) + space * (len(ln) - 1)
            x = (L.w - total) / 2
            if c["box"] == "line" and ln:
                boxes.append(((x - pad, y - pad // 2, x + total + pad, y + L.cap_line - pad // 2), c["box_color"],
                              c["box_alpha"]))
            for w, wd in zip(ln, widths, strict=True):
                text, spoken, active = text_of(w.text), n < lit, n == lit - 1
                if c["box"] == "word":
                    boxes.append(((x - pad // 2, y - pad // 3, x + wd + pad // 2, y + L.cap_line - pad // 2),
                                  c["box_color"], c["box_alpha"]))
                if active and c["active_box"]:
                    boxes.append(((x - pad // 2, y - pad // 3, x + wd + pad // 2, y + L.cap_line - pad // 2),
                                  c["active_box"], 1.0))
                now = looks.rgb(c["active"]) if active and c["active"] else on
                solo = 0 if active and c["active_box"] else stroke_w  # a word on its own box needs no outline
                if active and c["pop"]:
                    words.append(((x + wd / 2, y + ascent), text, big, now, "ms", solo))
                elif c["pop"]:  # the slot is as wide as the popped word: centre the others in it
                    words.append(((x + wd / 2, y + ascent), text, f, now if spoken else off, "ms", solo))
                else:
                    words.append(((x, y), text, f, now if spoken else off, "la", solo))
                if spoken and c["glow"]:
                    glow.append(((x, y), text, f, looks.rgb(c["glow"])))
                x += wd + space
                n += 1
        radius = round(L.cap_size * 0.25)
        for xy, color, alpha in boxes:
            d.rounded_rectangle(xy, radius=radius, fill=looks.rgb(color, alpha))
        if glow:
            img = Image.alpha_composite(img, _glow(img.size, glow, L.k(14)))
            d = ImageDraw.Draw(img)
        for xy, text, font, color, anchor, outline in words:
            d.text(xy, text, font=font, fill=color, stroke_width=outline, stroke_fill=looks.rgb(c["stroke"]),
                   anchor=anchor)
    img.save(path)
    return path


def write_caption_track(cues: list[captions.Cue], work: Path, layout: Layout = VERTICAL, plain: bool = False,
                        look: dict | None = None) -> Path:
    """Vẽ mọi khung karaoke và ghi danh sách concat (mỗi PNG kèm thời lượng).
    plain: phụ đề thường, mỗi cue một khung. `layout` đã chỉnh theo look (look_layout)."""
    pre = layout.prefix
    frames = captions.plain_frames(cues) if plain else captions.karaoke_frames(cues)
    blank = caption_png(work / f"{pre}cap_blank.png", None, 0, layout, look)
    rows = ["ffconcat version 1.0"]
    for i, (a, b, cue, lit) in enumerate(frames):
        f = caption_png(work / f"{pre}cap_{i:04d}.png", cue, lit, layout, look) if cue else blank
        rows += [f"file '{f.name}'", f"duration {b - a:.3f}"]
    rows.append(f"file '{blank.name}'")  # concat bỏ qua thời lượng của file cuối
    lst = work / f"{pre}captions.ffconcat"
    lst.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return lst


@dataclass
class Piece:
    src: int
    src_start: float
    dur: float
    t0: float
    still: bool = False  # giữ nguyên khung hình ở src_start suốt dur giây (mở / kết của bản lồng tiếng)
    motion: str = ""  # ảnh tĩnh (video AI) chuyển động chậm kiểu Ken Burns: một trong MOTIONS; rỗng = nguồn là video


MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right")  # chuyển động của một ảnh AI (Piece.motion)
KB_ZOOM = 0.12  # Ken Burns: ảnh phóng thêm chừng này (12 %) trong suốt một cảnh
FILL_TOL = 0.06  # tỉ lệ khung ảnh lệch khung video ít hơn chừng này: phủ kín (cắt vài điểm ảnh), không thì giữa nền mờ

CUT_EDGE = 0.8  # cú cắt cách mép mảnh ít hơn chừng này thì dời mép về cú cắt
CUT_PAD = 0.02  # lệch khỏi cú cắt một chút để không dính khung của cảnh bên kia


def snap_start(a: float, b: float, cuts: list[float], edge: float = CUT_EDGE, min_len: float = 1.5) -> float:
    """Có cú cắt ngay sau điểm vào (≤ edge) thì vào từ cú cắt, để không lộ vài khung của cảnh trước."""
    for c in cuts:
        if a < c <= a + edge and b - c >= min_len:
            return c + CUT_PAD
    return a


def snap_end(a: float, d: float, cuts: list[float], edge: float = CUT_EDGE, min_len: float = 1.0) -> float:
    """Có cú cắt ngay trước điểm ra (≤ edge) thì dừng ở cú cắt, để không lộ vài khung của cảnh sau."""
    for c in reversed(cuts):
        if a + d - edge <= c < a + d and c - a >= min_len:
            return c - CUT_PAD - a
    return d


def build_timeline(lines: list[dict], sources: list[dict], total: float, min_piece: float = 0.8) -> list[Piece]:
    """lines: [{text, start, end, clips:[{src,start,end}]}] → các mảnh video phủ kín [0, total].

    Dùng clip LLM chọn cho từng dòng; thiếu thì lấy đoạn kế tiếp trong các nguồn (xoay vòng),
    mỗi nguồn có con trỏ riêng nên không lặp lại cùng một đoạn. Có mốc cắt cảnh (source["cuts"])
    thì mép mảnh bám theo cú cắt và đoạn lấp bắt đầu ở đầu một cảnh.
    """
    def usable(s: int) -> tuple[float, float]:
        """Bỏ intro và end card: 6 giây đầu / 10 giây cuối với nguồn dài, ít hơn với nguồn ngắn."""
        sd = sources[s]["duration"] or 30
        if sd > 40:
            return 6.0, sd - 10.0
        return (3.0, sd - 4.0) if sd > 20 else (0.0, sd - 0.05)

    cuts = {i: s.get("cuts") or [] for i, s in enumerate(sources)}
    cursor = {i: max(usable(i)[0], (s["duration"] or 30) * 0.15) for i, s in enumerate(sources)}
    rr = 0

    def filler() -> tuple[int, float, float]:
        nonlocal rr
        s = rr % len(sources)
        rr += 1
        lo, hi = usable(s)
        a = cursor[s] if cursor[s] + 3 < hi else lo
        a = next((c + CUT_PAD for c in cuts[s] if a <= c <= a + 2.0 and c + 3 < hi), a)  # vào ở đầu một cảnh
        b = min(a + 5.0, hi)
        cursor[s] = b
        return s, a, b

    pieces: list[Piece] = []
    for i, ln in enumerate(lines):
        t_start = 0.0 if i == 0 else ln["start"]
        t_end = total if i == len(lines) - 1 else lines[i + 1]["start"]
        need = max(t_end - t_start, 0.1)
        queue = []
        for c in ln.get("clips") or []:
            s = int(c.get("src", -1)) if str(c.get("src", "")).lstrip("-").isdigit() else -1
            if 0 <= s < len(sources):
                lo, hi = usable(s)
                a = max(lo, min(float(c.get("start", 0)), hi - 1.0))
                b = min(float(c.get("end", a + 4)), hi)
                if b - a < 2.0:  # đoạn LLM chọn rơi vào intro/outro: kéo về vùng dùng được
                    a, b = max(lo, min(a, hi - 4.0)), min(max(a, lo) + 4.0, hi)
                if b - a >= 0.6:
                    queue.append((s, a, b))
                    cursor[s] = max(cursor[s], b) if cursor[s] < b + 8 else cursor[s]
        t = t_start
        while need - (t - t_start) > 0.05:
            s, a, b = queue.pop(0) if queue else filler()
            a = snap_start(a, b, cuts[s])
            left = need - (t - t_start)
            d = min(b - a, left)
            if left - d < min_piece:  # tránh mảnh quá ngắn ở cuối dòng
                d = left
            ds = snap_end(a, d, cuts[s])
            if ds < d and left - ds >= min_piece:  # phần còn thiếu đủ dài cho một mảnh khác
                d = ds
            pieces.append(Piece(s, a, d, t))
            t += d
    return pieces


RUN_TIMEOUT = 45 * 60  # s: one FFmpeg run; a hung one must not hold the single worker for ever


def _run(cmd: list[str]) -> None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(tr("ffmpeg did not finish in {minutes} min", minutes=RUN_TIMEOUT // 60)) from e
    if r.returncode != 0:
        raise RuntimeError(tr("ffmpeg failed: {error}", error=r.stderr[-1500:]))


def blur_filter(boxes: list | None) -> str:
    """Bộ lọc làm mờ các vùng của hình nguồn (phụ đề in sẵn, watermark đứng yên do người dùng vẽ): mỗi khung
    [x, y, w, h] theo tỉ lệ khung (0..1); nhận một khung hoặc danh sách khung. Rỗng khi không có vùng. Nhận một luồng
    hình, trả một luồng hình."""
    if not boxes:
        return ""
    if not isinstance(boxes[0], (list, tuple)):
        boxes = [boxes]
    parts = []
    for i, box in enumerate(boxes):
        x, y, w, h = (f"{float(v):.4f}" for v in box)
        parts.append(f"split[bo{i}][bc{i}];[bc{i}]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},gblur=sigma=22[bb{i}];"
                     f"[bo{i}][bb{i}]overlay=W*{x}:H*{y}")
    return ",".join(parts)


# Bộ lọc màu người dùng bật tay trên một nguồn (motio/effects.py): tên → bộ lọc FFmpeg, làm trên hình nguồn
COLOR_FILTERS = {
    "warm": "colorbalance=rs=0.08:gs=0.02:bs=-0.08:rm=0.06:bm=-0.06",
    "cool": "colorbalance=rs=-0.08:gs=0.01:bs=0.08:rm=-0.05:bm=0.06",
    "mono": "hue=s=0",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "vivid": "eq=saturation=1.35:contrast=1.08",
    "faded": "eq=saturation=0.7:contrast=0.9:brightness=0.03",
}


def effect_filter(fx: dict | None) -> str:
    """Lật gương rồi bộ lọc màu (effects.attach), nối sau các vùng làm mờ / vùng giữ lại; rỗng = không có gì."""
    fx = fx or {}
    parts = (["hflip"] if fx.get("mirror") else []) + ([COLOR_FILTERS[fx["color"]]] if fx.get("color") else [])
    return ",".join(parts)


def kenburns(motion: str, dur: float, w: int, h: int, zoom: float = KB_ZOOM) -> str:
    """Bộ lọc zoompan: một ảnh tĩnh (đã phóng 2× so với khung ra) trôi chậm trong `dur` giây. Ảnh lớn gấp đôi khung ra
    để bước dịch nhỏ hơn một điểm ảnh, không bị rung."""
    n = max(round(dur * FPS), 1)
    t = f"min(on/{n},1)"
    z = {"zoom_in": f"1+{zoom}*{t}", "zoom_out": f"1+{zoom}-{zoom}*{t}"}.get(motion, f"1+{zoom}")
    mid_x, mid_y = "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"
    x = {"pan_left": f"(iw-iw/zoom)*(1-{t})", "pan_right": f"(iw-iw/zoom)*{t}"}.get(motion, mid_x)
    frames = n + round(0.3 * FPS)  # dư một chút: bước sau cắt đúng độ dài
    return f"zoompan=z='{z}':x='{x}':y='{mid_y}':d={frames}:s={w}x{h}:fps={FPS}"


def camera(pieces: list[Piece], look: dict | None) -> list[Piece]:
    """The look's camera move for an AI video's pictures: `auto` keeps what each scene was given; the others replace it
    (zoom in, zoom out, in and out in turn, left and right in turn, or none: zoom 0 holds the picture still)."""
    mode = looks.clean(look)["motion"]["mode"]
    if mode == "auto":
        return pieces
    seq = {"zoom_in": ["zoom_in"], "zoom_out": ["zoom_out"], "still": ["zoom_in"], "alternate": ["zoom_in", "zoom_out"],
           "pan": ["pan_left", "pan_right"]}[mode]
    out, n = [], 0
    for p in pieces:
        if p.motion:
            p = dataclasses.replace(p, motion=seq[n % len(seq)])
            n += 1
        out.append(p)
    return out


def moving_size(src_path: str, layout: Layout) -> tuple[int, int]:
    """Cỡ ảnh ra của một cảnh ảnh tĩnh: phủ kín khung khi tỉ lệ gần bằng (9:16), không thì vừa khung (16:9: ảnh đứng
    giữa nền mờ). Số chẵn cho libx264."""
    with Image.open(src_path) as im:
        iw, ih = im.size
    if abs((iw / ih) / (layout.w / layout.h) - 1) <= FILL_TOL:
        return layout.w, layout.h
    k = min(layout.w / iw, layout.h / ih)
    return int(iw * k) // 2 * 2, int(ih * k) // 2 * 2


def _backdrop(fr: dict) -> str:
    """The filter chain of the picture behind the source: blurred and dimmed (as always), or one flat colour."""
    if fr["color"]:
        return f"drawbox=x=0:y=0:w=iw:h=ih:color=0x{fr['color'].lstrip('#')}:t=fill"
    blur = f"gblur=sigma={fr['blur']}," if fr["blur"] else ""
    return f"{blur}eq=brightness=-{fr['dim']:.2f}:saturation=0.9"


def render_piece(p: Piece, src: dict, overlay: Path, out: Path, layout: Layout = VERTICAL,
                 volume: float = 0.10, look: dict | None = None) -> None:
    """Một mảnh: nền mờ + hình nguồn + lớp chữ tĩnh. volume: âm lượng tiếng của nguồn (0 = im).
    src["blur"]: các vùng làm mờ trên hình nguồn (phụ đề cũ, watermark), xem blur_filter; src["cover"]: ảnh PNG cỡ
    nguồn có logo của người dùng đặt lên các vùng đó (masks.cover_png); src["keep"]: chỉ giữ vùng [x, y, w, h] của nguồn
    (phóng to để chữ / watermark ngoài vùng ra khỏi khung). Cả ba làm trên hình nguồn, trước nền mờ và khung.
    src["effects"]: lật gương, bộ lọc màu người dùng bật (effects.attach), sau ba thứ trên.
    p.motion: nguồn là một ảnh (video AI), trôi chậm theo kenburns thay vì phát video.
    look["frame"]: độ mờ / tối của nền sau hình nguồn (hoặc một màu đặc); look["motion"]: độ phóng của kenburns."""
    fr, mo = (looks.clean(look)[k] for k in ("frame", "motion"))
    zoom = 0.0 if mo["mode"] == "still" else mo["zoom"]
    fw, fh = layout.w, layout.h
    src_path = src["path"]
    fx = src.get("effects") or {}
    sound = bool(src.get("has_audio")) and not p.still and not p.motion and volume > 0
    span = 0.5 if p.still else p.dur + 0.1
    inputs = (["-i", src_path] if p.motion else ["-ss", f"{p.src_start:.3f}", "-t", f"{span:.3f}", "-i", src_path]) \
        + ["-loop", "1", "-t", f"{p.dur + 0.1:.3f}", "-i", str(overlay)]
    if not sound:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    a_map = "[0:a]" if sound else "[2:a]"
    head = [f"trim=end_frame=1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={p.dur + 0.2:.3f}"] \
        if p.still else []
    if blur := blur_filter(src.get("blur")):
        head.append(blur)
    pre = f"[0:v]{','.join(head) or 'null'}"
    if src.get("cover"):  # logo của người dùng phủ lên các vùng đã làm mờ (ảnh tĩnh: overlay giữ khung cuối)
        pre += f"[mk];[mk][{3 if not sound else 2}:v]overlay=0:0"
        inputs += ["-i", src["cover"]]
    if keep := src.get("keep"):
        x, y, w, h = (f"{float(v):.4f}" for v in keep)
        pre += f",crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}"
    if look := effect_filter(fx):
        pre += f",{look}"
    bg_tail = f",tpad=stop_mode=clone:stop_duration={p.dur + 0.3:.3f}" if p.motion else ""  # ảnh chỉ có một khung
    if p.motion:
        ow, oh = moving_size(src_path, layout)
        fg = (f"[b]scale={2 * ow}:{2 * oh}:force_original_aspect_ratio=increase:flags=lanczos,crop={2 * ow}:{2 * oh},"
              f"{kenburns(p.motion, p.dur, ow, oh, zoom)}[fg];")
    else:
        fg = f"[b]scale={fw}:{fh}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
    fc = (f"{pre},split[a][b];"
          f"[a]scale={fw}:{fh}:force_original_aspect_ratio=increase,crop={fw}:{fh},{_backdrop(fr)}{bg_tail}[bg];"
          f"{fg}"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v1];[v1][1:v]overlay=0:0:shortest=1,fps={FPS},format=yuv420p,"
          f"setsar=1,tpad=stop_mode=clone:stop_duration={max(3.0, p.dur):.3f}[v];"
          f"{a_map}volume={volume if sound else 0:.3f},aresample=48000,aformat=channel_layouts=stereo,apad[aud]")
    _run([config.ffmpeg(), "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[aud]",
          "-t", f"{p.dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
          "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", str(out)])


def _compose(layout: Layout, pieces: list[Piece], sources: list[dict], cues: list[captions.Cue], narration: dict,
             title: str, badge: str, out_dir: Path, work: Path, tick: Callable[[], None], volume: float = 0.10,
             delay: float = NARRATION_DELAY, look: dict | None = None) -> Path:
    """Dựng một khổ từ các mảnh đã chọn: mảnh clip + lớp chữ, nối lại, trộn giọng đọc và phụ đề."""
    pre = layout.prefix
    cap_layout = look_layout(layout, look)
    cap_list = write_caption_track(cues, work, cap_layout, look=look)
    overlay = overlay_png(work / f"{pre}ov_000.png", title=title, badge=badge, layout=layout, look=look)
    files = []
    for j, p in enumerate(pieces):
        f = work / f"{pre}p_{j:03d}.mp4"
        render_piece(p, sources[p.src], overlay, f, layout, volume, look)
        files.append(f)
        tick()
    lst = work / f"{pre}list.txt"
    lst.write_text("".join(f"file '{f.name}'\n" for f in files))
    bg = out_dir / f"{pre}bg.mp4"
    _run([config.ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(bg)])
    final = out_dir / f"final{'_' + pre.rstrip('_') if pre else ''}.mp4"
    _run([config.ffmpeg(), "-y", "-v", "error", "-i", str(bg), "-i", narration["audio"],
          "-f", "concat", "-safe", "0", "-i", str(cap_list), "-filter_complex",
          f"[2:v]format=rgba[cap];[0:v][cap]overlay=0:{cap_layout.cap_top}:eof_action=pass,format=yuv420p[v];"
          f"[1:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(delay * 1000)}|{int(delay * 1000)}[nar];"
          "[0:a][nar]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]",
          "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
          "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(final)])
    return final


def render(plan: dict, sources: list[dict], narration: dict, out_dir: Path, progress=None,
           min_total: float = 0.0, badge: str = "", wide: bool = False, pieces: list[Piece] | None = None,
           total: float | None = None, src_volume: float = SRC_VOLUME, delay: float = NARRATION_DELAY,
           caption_hold: float | None = None, look: dict | None = None) -> dict:
    """plan: {title_fr, lines:[{text, clips}]}; narration: kết quả tts.synthesize. Video dài ít nhất min_total giây.
    badge: nhãn đỏ trên tiêu đề (vd. "ACTU CHINE" cho tin nóng), rỗng = không có.
    wide: dựng thêm bản 16:9 (final_wide.mp4) từ cùng các mảnh, giọng đọc và phụ đề.
    pieces / total: các mảnh và độ dài đã định sẵn (bản lồng tiếng), không thì chọn theo kịch bản.
    src_volume: âm lượng tiếng nguồn dưới giọng đọc; delay: giọng đọc vào trễ bao nhiêu giây;
    caption_hold: phụ đề tắt sau từ cuối chừng này giây (None = giữ tới phụ đề sau).
    look: kiểu phụ đề, băng tiêu đề, nền và chuyển động ảnh (looks.py); None = như trước khi có template."""
    look = None if looks.is_default(look) else looks.clean(look)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "pieces"
    work.mkdir(exist_ok=True)
    for s in sources:
        s["has_audio"] = has_audio(Path(s["path"]))
        if pieces is None:
            s["cuts"] = scenes.detect(Path(s["path"]))  # đã có cache nếu pipeline chạy bước cắt cảnh
    lines = [{**ln, **sp} for ln, sp in zip(plan["lines"], narration["lines"], strict=False)]
    if total is None:
        total = max(narration["duration"] + TAIL, min_total)  # thiếu thì kéo dài phần cuối bằng hình nguồn

    # Phụ đề karaoke theo mốc từng từ của giọng đọc
    words = captions.word_times([ln["text"] for ln in plan["lines"]], narration["lines"], narration.get("alignment"))
    spoken = narration["duration"] + TAIL  # câu cuối không ở lại suốt phần đuôi kéo dài
    cues = captions.build_cues(words, min(spoken, total), fits=caption_fits(look), shift=delay, hold=caption_hold)
    (out_dir / "captions.srt").write_text(captions.to_srt(cues), encoding="utf-8")
    (out_dir / "captions.ass").write_text(captions.to_ass(cues), encoding="utf-8")

    if pieces is None:
        pieces = build_timeline(lines, sources, total)
    pieces = camera(pieces, look)
    title = captions.fr_typography(plan["title_fr"])
    layouts = [VERTICAL, WIDE] if wide else [VERTICAL]
    done, steps = 0, len(pieces) * len(layouts)

    def tick() -> None:
        nonlocal done
        done += 1
        if progress:
            progress(done, steps)

    final, *rest = [_compose(lay, pieces, sources, cues, narration, title, badge, out_dir, work, tick, src_volume,
                             delay, look) for lay in layouts]
    thumb = out_dir / "thumb.jpg"
    _run([config.ffmpeg(), "-y", "-v", "error", "-ss", "1.2", "-i", str(final), "-frames:v", "1", "-q:v", "3",
          str(thumb)])
    # đoạn nào của nguồn nào (url để Xoá logo biết nguồn chưa đổi): Xoá logo chỉ cần xoá những đoạn này. Mảnh giữ
    # nguyên khung hình chỉ dùng một khung.
    (out_dir / "timeline.json").write_text(json.dumps([{**p.__dict__, "dur": 0.2 if p.still else p.dur,
                                                        "url": sources[p.src].get("url")} for p in pieces],
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
    return {"video": str(final), "thumb": str(thumb), "wide": str(rest[0]) if rest else None, "duration": total,
            "pieces": len(pieces), "captions": len(cues)}
