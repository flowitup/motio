"""Dựng video 9:16 (và bản 16:9 khi kênh cần) bằng FFmpeg + lớp chữ vẽ bằng Pillow.

FFmpeg của Homebrew không có libass / drawtext, nên chữ được vẽ thành PNG trong suốt rồi overlay.
Cách này chạy được với mọi bản FFmpeg.
- Mỗi mảnh clip: nền mờ + clip + lớp tiêu đề và nhãn (tĩnh), mã hoá riêng rồi nối lại.
- Phụ đề karaoke: chuỗi PNG có thời lượng (concat demuxer), overlay một lần ở bước trộn cuối.
- Bản 16:9 dùng lại đúng các mảnh, giọng đọc và phụ đề của bản 9:16, chỉ đổi bố cục (Layout).
"""
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import captions, config, scenes
from .asr import has_audio
from .i18n import tr

W, H, FPS = config.W, config.H, config.FPS
VIDEO_BOTTOM = (H + W * 9 // 16) // 2  # mép dưới của clip 16:9 đặt giữa khung
NARRATION_DELAY = 0.15  # giọng đọc vào trễ 150 ms (adelay ở bước trộn): phụ đề dời theo
TAIL = 0.6  # giây hình sau câu cuối
CAP_TOP = VIDEO_BOTTOM + 100  # dải phụ đề, ngay dưới nhãn nguồn
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
    credit_y: int
    cap_top: int
    cap_size: int
    cap_line: int

    def k(self, v: float) -> int:
        return round(v * self.scale)

    @property
    def cap_h(self) -> int:
        return captions.MAX_LINES * self.cap_line + 40


VERTICAL = Layout(W, H, "", 1.0, 40, 150, 3, W - 140, False, VIDEO_BOTTOM + 18, CAP_TOP, CAP_SIZE, CAP_LINE)
WIDE_W, WIDE_H = 1920, 1080
_WIDE_CAP_LINE = 68
_WIDE_CAP_TOP = WIDE_H - (captions.MAX_LINES * _WIDE_CAP_LINE + 40) - 24  # dải phụ đề sát đáy khung
WIDE = Layout(WIDE_W, WIDE_H, "wide_", 0.8, 48, 40, 2, 1150, True, _WIDE_CAP_TOP - 50, _WIDE_CAP_TOP, 52,
              _WIDE_CAP_LINE)


def _font(cands: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in cands:
        if p and Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = [w for w in text.split(" ") if w], [], ""  # chỉ ngắt ở dấu cách thường, giữ NBSP
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def overlay_png(path: Path, *, title: str, credit: str, badge: str = "", layout: Layout = VERTICAL) -> Path:
    """Lớp tĩnh cỡ khung: băng tiêu đề (nhãn đỏ phía trên nếu có `badge`) và nhãn nguồn (tuỳ chọn).
    Công bố giọng AI nằm trong bài đăng."""
    L, k = layout, layout.k
    img = Image.new("RGBA", (L.w, L.h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Băng tiêu đề phía trên
    f_badge, f_title = _font(FONT_BOLD, k(34)), _font(FONT_BOLD, k(58))
    tl = _wrap(d, title, f_title, L.title_wrap)[:L.title_lines]
    x0, y0, pad, line = L.title_x, L.title_y, k(30), k(70)
    top = k(92) if badge else k(30)  # không có nhãn: tiêu đề lên sát mép trên của băng
    box_h = top + len(tl) * line + k(8)
    bw = d.textlength(badge, font=f_badge) + k(36) if badge else 0
    if L.fit_box:
        x1 = x0 + 2 * pad + max([bw, *(d.textlength(ln, font=f_title) for ln in tl)])
    else:
        x1 = L.w - x0
    d.rounded_rectangle((x0, y0, x1, y0 + box_h), radius=k(22), fill=(12, 16, 22, 205))
    if badge:
        bx = x0 + pad
        d.rounded_rectangle((bx, y0 + k(24), bx + bw, y0 + k(76)), radius=k(10), fill=(222, 45, 38, 255))
        d.text((bx + k(18), y0 + k(30)), badge, font=f_badge, fill="white")
    for i, ln in enumerate(tl):
        d.text((x0 + pad, y0 + top + i * line), ln, font=f_title, fill="white")
    # Nhãn nguồn (tuỳ chọn): 9:16 ngay dưới clip, 16:9 ngay trên phụ đề. Chủ dự án bỏ nhãn "Voix de synthèse (IA)"
    # trên video (26/09/2026).
    if credit:
        f_cr = _font(FONT_CJK, k(30))
        cy, tw = L.credit_y, d.textlength(credit, font=f_cr)
        d.rounded_rectangle((x0, cy, x0 + tw + k(24), cy + k(46)), radius=k(10), fill=(0, 0, 0, 150))
        d.text((x0 + k(12), cy + k(6)), credit, font=f_cr, fill=(235, 235, 235))
    img.save(path)
    return path


def caption_fits() -> Callable[[str], bool]:
    """Một dòng phụ đề vừa khi ≤ 42 ký tự và lọt chiều ngang khung với font phụ đề."""
    f = _font(FONT_BOLD, CAP_SIZE)
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    return lambda text: len(text) <= captions.MAX_CHARS and d.textlength(text, font=f) <= CAP_MAX_W


def caption_png(path: Path, cue: captions.Cue | None, lit: int, layout: Layout = VERTICAL) -> Path:
    """Dải phụ đề cỡ bề ngang khung × cap_h: `lit` từ đầu đã đọc (vàng), phần còn lại trắng. cue None = dải trống."""
    L = layout
    img = Image.new("RGBA", (L.w, L.cap_h), (0, 0, 0, 0))
    if cue:
        d = ImageDraw.Draw(img)
        f = _font(FONT_BOLD, L.cap_size)
        space = d.textlength(" ", font=f)
        n = 0
        for i, ln in enumerate(cue.lines):
            x = (L.w - d.textlength(" ".join(w.text for w in ln), font=f)) / 2
            for w in ln:
                d.text((x, L.k(12) + i * L.cap_line), w.text, font=f, fill=SPOKEN if n < lit else "white",
                       stroke_width=L.k(6), stroke_fill=(0, 0, 0))
                x += d.textlength(w.text, font=f) + space
                n += 1
    img.save(path)
    return path


def write_caption_track(cues: list[captions.Cue], work: Path, layout: Layout = VERTICAL) -> Path:
    """Vẽ mọi khung karaoke và ghi danh sách concat (mỗi PNG kèm thời lượng)."""
    pre = layout.prefix
    frames = captions.karaoke_frames(cues)
    blank = caption_png(work / f"{pre}cap_blank.png", None, 0, layout)
    rows = ["ffconcat version 1.0"]
    for i, (a, b, cue, lit) in enumerate(frames):
        f = caption_png(work / f"{pre}cap_{i:04d}.png", cue, lit, layout) if cue else blank
        rows += [f"file '{f.name}'", f"duration {b - a:.3f}"]
    rows.append(f"file '{blank.name}'")  # concat bỏ qua thời lượng của file cuối
    lst = work / f"{pre}captions.ffconcat"
    lst.write_text("\n".join(rows) + "\n")
    return lst


@dataclass
class Piece:
    src: int
    src_start: float
    dur: float
    t0: float


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


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(tr("ffmpeg failed: {error}", error=r.stderr[-1500:]))


def render_piece(p: Piece, src: dict, overlay: Path, out: Path, layout: Layout = VERTICAL) -> None:
    fw, fh = layout.w, layout.h
    src_path = src["path"]
    audio_in = ["-i", src_path] if src.get("has_audio") else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    a_map = "[0:a]" if src.get("has_audio") else "[2:a]"
    inputs = ["-ss", f"{p.src_start:.3f}", "-t", f"{p.dur + 0.1:.3f}", "-i", src_path,
              "-loop", "1", "-t", f"{p.dur + 0.1:.3f}", "-i", str(overlay)]
    if not src.get("has_audio"):
        inputs += audio_in
    fc = (f"[0:v]split[a][b];"
          f"[a]scale={fw}:{fh}:force_original_aspect_ratio=increase,crop={fw}:{fh},gblur=sigma=36,"
          f"eq=brightness=-0.10:saturation=0.9[bg];"
          f"[b]scale={fw}:{fh}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v1];[v1][1:v]overlay=0:0:shortest=1,fps={FPS},format=yuv420p,"
          f"setsar=1,tpad=stop_mode=clone:stop_duration=3[v];"
          f"{a_map}volume=0.10,aresample=48000,aformat=channel_layouts=stereo,apad[aud]")
    _run([config.ffmpeg(), "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[aud]",
          "-t", f"{p.dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
          "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", str(out)])


def _compose(layout: Layout, pieces: list[Piece], sources: list[dict], cues: list[captions.Cue], narration: dict,
             title: str, badge: str, out_dir: Path, work: Path, tick: Callable[[], None]) -> Path:
    """Dựng một khổ từ các mảnh đã chọn: mảnh clip + lớp chữ, nối lại, trộn giọng đọc và phụ đề."""
    pre = layout.prefix
    cap_list = write_caption_track(cues, work, layout)
    overlays: dict[str, Path] = {}
    files = []
    for j, p in enumerate(pieces):
        src = sources[p.src]
        credit = f"Source : {src['platform']} / {src['uploader']}".strip(" /") if config.flag("CREDIT_ON_VIDEO") else ""
        if credit not in overlays:
            overlays[credit] = overlay_png(work / f"{pre}ov_{len(overlays):03d}.png", title=title, credit=credit,
                                          badge=badge, layout=layout)
        f = work / f"{pre}p_{j:03d}.mp4"
        render_piece(p, src, overlays[credit], f, layout)
        files.append(f)
        tick()
    lst = work / f"{pre}list.txt"
    lst.write_text("".join(f"file '{f.name}'\n" for f in files))
    bg = out_dir / f"{pre}bg.mp4"
    _run([config.ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(bg)])
    final = out_dir / f"final{'_' + pre.rstrip('_') if pre else ''}.mp4"
    _run([config.ffmpeg(), "-y", "-v", "error", "-i", str(bg), "-i", narration["audio"],
          "-f", "concat", "-safe", "0", "-i", str(cap_list), "-filter_complex",
          f"[2:v]format=rgba[cap];[0:v][cap]overlay=0:{layout.cap_top}:eof_action=pass,format=yuv420p[v];"
          f"[1:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(NARRATION_DELAY * 1000)}|"
          f"{int(NARRATION_DELAY * 1000)}[nar];"
          "[0:a][nar]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]",
          "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
          "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(final)])
    return final


def render(plan: dict, sources: list[dict], narration: dict, out_dir: Path, progress=None,
           min_total: float = 0.0, badge: str = "", wide: bool = False) -> dict:
    """plan: {title_fr, lines:[{text, clips}]}; narration: kết quả tts.synthesize. Video dài ít nhất min_total giây.
    badge: nhãn đỏ trên tiêu đề (vd. "ACTU CHINE" cho tin nóng), rỗng = không có.
    wide: dựng thêm bản 16:9 (final_wide.mp4) từ cùng các mảnh, giọng đọc và phụ đề."""
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "pieces"
    work.mkdir(exist_ok=True)
    for s in sources:
        s["has_audio"] = has_audio(Path(s["path"]))
        s["cuts"] = scenes.detect(Path(s["path"]))  # đã có cache nếu pipeline chạy bước cắt cảnh
    lines = [{**ln, **sp} for ln, sp in zip(plan["lines"], narration["lines"], strict=False)]
    total = max(narration["duration"] + TAIL, min_total)  # thiếu thì kéo dài phần cuối bằng hình nguồn

    # Phụ đề karaoke theo mốc từng từ của giọng đọc
    words = captions.word_times([ln["text"] for ln in plan["lines"]], narration["lines"], narration.get("alignment"))
    spoken = narration["duration"] + TAIL  # câu cuối không ở lại suốt phần đuôi kéo dài
    cues = captions.build_cues(words, min(spoken, total), fits=caption_fits(), shift=NARRATION_DELAY)
    (out_dir / "captions.srt").write_text(captions.to_srt(cues), encoding="utf-8")
    (out_dir / "captions.ass").write_text(captions.to_ass(cues), encoding="utf-8")

    pieces = build_timeline(lines, sources, total)
    title = captions.fr_typography(plan["title_fr"])
    layouts = [VERTICAL, WIDE] if wide else [VERTICAL]
    done, steps = 0, len(pieces) * len(layouts)

    def tick() -> None:
        nonlocal done
        done += 1
        if progress:
            progress(done, steps)

    final, *rest = [_compose(lay, pieces, sources, cues, narration, title, badge, out_dir, work, tick)
                    for lay in layouts]
    thumb = out_dir / "thumb.jpg"
    _run([config.ffmpeg(), "-y", "-v", "error", "-ss", "1.2", "-i", str(final), "-frames:v", "1", "-q:v", "3",
          str(thumb)])
    # đoạn nào của nguồn nào (url để Xoá logo biết nguồn chưa đổi): Xoá logo chỉ cần xoá những đoạn này
    (out_dir / "timeline.json").write_text(json.dumps([{**p.__dict__, "url": sources[p.src].get("url")}
                                                       for p in pieces], ensure_ascii=False, indent=1))
    return {"video": str(final), "thumb": str(thumb), "wide": str(rest[0]) if rest else None, "duration": total,
            "pieces": len(pieces), "captions": len(cues)}
