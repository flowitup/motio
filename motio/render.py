"""Dựng video 9:16 bằng FFmpeg + lớp chữ vẽ bằng Pillow.

FFmpeg của Homebrew không có libass / drawtext, nên tiêu đề, phụ đề, nhãn nguồn được vẽ thành
PNG trong suốt 1080×1920 rồi overlay. Cách này chạy được với mọi bản FFmpeg.
"""
import json
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config
from .asr import has_audio

W, H, FPS = config.W, config.H, config.FPS
VIDEO_BOTTOM = (H + W * 9 // 16) // 2  # mép dưới của clip 16:9 đặt giữa khung

FONT_BOLD = [config.env("FONT_BOLD"), "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
             "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
FONT_CJK = [config.env("FONT_CJK"), "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc", "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc"]


def _font(cands: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in cands:
        if p and Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
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


def overlay_png(path: Path, *, title: str, caption: str, credit: str, badge: str = "ACTU CHINE") -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Băng tiêu đề phía trên
    f_badge, f_title = _font(FONT_BOLD, 34), _font(FONT_BOLD, 58)
    tl = _wrap(d, title, f_title, W - 140)[:3]
    y0 = 150
    box_h = 70 + len(tl) * 70 + 30
    d.rounded_rectangle((40, y0, W - 40, y0 + box_h), radius=22, fill=(12, 16, 22, 205))
    bw = d.textlength(badge, font=f_badge) + 36
    d.rounded_rectangle((70, y0 + 24, 70 + bw, y0 + 76), radius=10, fill=(222, 45, 38, 255))
    d.text((88, y0 + 30), badge, font=f_badge, fill="white")
    for i, ln in enumerate(tl):
        d.text((70, y0 + 92 + i * 70), ln, font=f_title, fill="white")
    # Nhãn nguồn + công bố giọng AI, ngay dưới clip
    f_cr = _font(FONT_CJK if credit else FONT_BOLD, 30)  # chỉ cần font chữ Hán khi hiện tên kênh nguồn
    cy = VIDEO_BOTTOM + 18
    for text, x, anchor in ((credit, 40, "la"), ("Voix de synthèse (IA)", W - 40, "ra")):
        if not text:
            continue
        tw = d.textlength(text, font=f_cr)
        x0 = x if anchor == "la" else x - tw - 24
        d.rounded_rectangle((x0, cy, x0 + tw + 24, cy + 46), radius=10, fill=(0, 0, 0, 150))
        d.text((x0 + 12, cy + 6), text, font=f_cr, fill=(235, 235, 235))
    # Phụ đề
    if caption:
        f_cap = _font(FONT_BOLD, 64)
        cl = _wrap(d, caption, f_cap, W - 120)[:3]
        top = VIDEO_BOTTOM + 110
        for i, ln in enumerate(cl):
            tw = d.textlength(ln, font=f_cap)
            d.text(((W - tw) / 2, top + i * 82), ln, font=f_cap, fill="white",
                   stroke_width=6, stroke_fill=(0, 0, 0))
    img.save(path)
    return path


def caption_chunks(text: str, max_chars: int = 58) -> list[str]:
    """Chia câu dài thành các đoạn phụ đề gần bằng nhau, ưu tiên ngắt ở dấu câu gần giữa câu."""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return [text]
    mid = len(text) / 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if not spaces:
        return textwrap.wrap(text, max_chars)

    def cost(i: int) -> float:  # gần giữa câu, ưu tiên sau dấu phẩy / chấm phẩy / hai chấm
        return abs(i - mid) - (12 if text[i - 1] in ",;:" else 0)

    cut = min(spaces, key=cost)
    return caption_chunks(text[:cut], max_chars) + caption_chunks(text[cut + 1:], max_chars)


@dataclass
class Piece:
    src: int
    src_start: float
    dur: float
    t0: float
    caption: str = ""


def build_timeline(lines: list[dict], sources: list[dict], total: float, min_piece: float = 0.8) -> list[Piece]:
    """lines: [{text, start, end, clips:[{src,start,end}]}] → các mảnh video phủ kín [0, total].

    Dùng clip LLM chọn cho từng dòng; thiếu thì lấy đoạn kế tiếp trong các nguồn (xoay vòng),
    mỗi nguồn có con trỏ riêng nên không lặp lại cùng một đoạn.
    """
    def usable(s: int) -> tuple[float, float]:
        """Bỏ intro và end card: 6 giây đầu / 10 giây cuối với nguồn dài, ít hơn với nguồn ngắn."""
        sd = sources[s]["duration"] or 30
        if sd > 40:
            return 6.0, sd - 10.0
        return (3.0, sd - 4.0) if sd > 20 else (0.0, sd - 0.05)

    cursor = {i: max(usable(i)[0], (s["duration"] or 30) * 0.15) for i, s in enumerate(sources)}
    rr = 0

    def filler() -> tuple[int, float, float]:
        nonlocal rr
        s = rr % len(sources)
        rr += 1
        lo, hi = usable(s)
        a = cursor[s] if cursor[s] + 3 < hi else lo
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
            left = need - (t - t_start)
            d = min(b - a, left)
            if left - d < min_piece:  # tránh mảnh quá ngắn ở cuối dòng
                d = left
            pieces.append(Piece(s, a, d, t))
            t += d
    return pieces


def split_by_captions(pieces: list[Piece], events: list[tuple[float, float, str]]) -> list[Piece]:
    out = []
    for p in pieces:
        cuts = sorted({round(e[0], 3) for e in events if p.t0 + 0.25 < e[0] < p.t0 + p.dur - 0.25})
        bounds = [p.t0, *cuts, p.t0 + p.dur]
        for a, b in zip(bounds, bounds[1:], strict=False):
            mid = (a + b) / 2
            cap = next((e[2] for e in events if e[0] <= mid < e[1]), "")
            out.append(Piece(p.src, p.src_start + (a - p.t0), b - a, a, cap))
    return out


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg lỗi: {r.stderr[-1500:]}")


def render_piece(p: Piece, src: dict, overlay: Path, out: Path) -> None:
    src_path = src["path"]
    audio_in = ["-i", src_path] if src.get("has_audio") else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    a_map = "[0:a]" if src.get("has_audio") else "[2:a]"
    inputs = ["-ss", f"{p.src_start:.3f}", "-t", f"{p.dur + 0.1:.3f}", "-i", src_path,
              "-loop", "1", "-t", f"{p.dur + 0.1:.3f}", "-i", str(overlay)]
    if not src.get("has_audio"):
        inputs += audio_in
    fc = (f"[0:v]split[a][b];"
          f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=36,"
          f"eq=brightness=-0.10:saturation=0.9[bg];"
          f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v1];[v1][1:v]overlay=0:0:shortest=1,fps={FPS},format=yuv420p,"
          f"setsar=1,tpad=stop_mode=clone:stop_duration=3[v];"
          f"{a_map}volume=0.10,aresample=48000,aformat=channel_layouts=stereo,apad[aud]")
    _run([config.FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[aud]",
          "-t", f"{p.dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
          "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", str(out)])


def render(plan: dict, sources: list[dict], narration: dict, out_dir: Path, progress=None) -> dict:
    """plan: {title_fr, lines:[{text, clips}]}; narration: kết quả tts.synthesize."""
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "pieces"
    work.mkdir(exist_ok=True)
    for s in sources:
        s["has_audio"] = has_audio(Path(s["path"]))
    lines = [{**ln, **sp} for ln, sp in zip(plan["lines"], narration["lines"], strict=False)]
    total = narration["duration"] + 0.6
    events = []
    for i, ln in enumerate(lines):
        a = 0.0 if i == 0 else ln["start"]
        b = total if i == len(lines) - 1 else lines[i + 1]["start"]
        chunks = caption_chunks(ln["text"])
        n = sum(len(c) for c in chunks) or 1
        t = a
        for c in chunks:
            d = (b - a) * len(c) / n
            events.append((t, t + d, c))
            t += d
    pieces = split_by_captions(build_timeline(lines, sources, total), events)
    overlays: dict[tuple, Path] = {}
    files = []
    for j, p in enumerate(pieces):
        src = sources[p.src]
        credit = f"Source : {src['platform']} / {src['uploader']}".strip(" /") if config.CREDIT_ON_VIDEO else ""
        key = (p.caption, credit)
        if key not in overlays:
            overlays[key] = overlay_png(work / f"ov_{len(overlays):03d}.png", title=plan["title_fr"],
                                        caption=p.caption, credit=credit)
        f = work / f"p_{j:03d}.mp4"
        render_piece(p, src, overlays[key], f)
        files.append(f)
        if progress:
            progress(j + 1, len(pieces))
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{f.name}'\n" for f in files))
    bg = out_dir / "bg.mp4"
    _run([config.FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(bg)])
    final = out_dir / "final.mp4"
    _run([config.FFMPEG, "-y", "-v", "error", "-i", str(bg), "-i", narration["audio"], "-filter_complex",
          "[1:a]aresample=48000,aformat=channel_layouts=stereo,adelay=150|150[nar];"
          "[0:a][nar]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]",
          "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
          str(final)])
    thumb = out_dir / "thumb.jpg"
    _run([config.FFMPEG, "-y", "-v", "error", "-ss", "1.2", "-i", str(final), "-frames:v", "1", "-q:v", "3",
          str(thumb)])
    (out_dir / "timeline.json").write_text(json.dumps([p.__dict__ for p in pieces], ensure_ascii=False, indent=1))
    return {"video": str(final), "thumb": str(thumb), "duration": total, "pieces": len(pieces)}
