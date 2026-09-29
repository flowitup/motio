"""Phụ đề karaoke tiếng Pháp: mốc từng từ, ngắt dòng ≤ 42 ký tự, chính tả Pháp, xuất SRT / ASS.

Hàm thuần (không gọi FFmpeg, không vẽ): render.py dùng `build_cues` để vẽ từng khung karaoke bằng Pillow.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field

NBSP = " "
MAX_CHARS = 42  # ký tự / dòng (chuẩn phụ đề Pháp)
MAX_LINES = 2


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Cue:
    start: float
    end: float
    lines: list[list[Word]] = field(default_factory=list)

    @property
    def words(self) -> list[Word]:
        return [w for ln in self.lines for w in ln]

    def text(self, sep: str = "\n") -> str:
        return sep.join(" ".join(w.text for w in ln) for ln in self.lines)


# ---------- mốc thời gian từng từ ----------
def word_times(lines: list[str], spans: list[dict], alignment: dict | None = None) -> list[list[Word]]:
    """Mốc từng từ cho mỗi dòng kịch bản.

    ElevenLabs trả mốc từng ký tự cho cả đoạn văn (các dòng nối bằng một dấu cách, như tts._elevenlabs);
    khớp độ dài thì dùng, không thì chia thời gian của dòng theo số ký tự (giọng macOS, dữ liệu lệch).
    """
    text = " ".join(ln.strip() for ln in lines)
    al = alignment or {}
    starts = al.get("character_start_times_seconds") or []
    ends = al.get("character_end_times_seconds") or []
    exact = len(al.get("characters") or []) == len(text) == len(starts) == len(ends)
    out, off = [], 0
    for ln, sp in zip(lines, spans, strict=False):
        ln = ln.strip()
        a, b = float(sp["start"]), float(sp["end"])
        n = max(len(ln), 1)
        words = []
        for m in re.finditer(r"\S+", ln):
            if exact:
                s, e = float(starts[off + m.start()]), float(ends[off + m.end() - 1])
            else:
                s, e = a + (b - a) * m.start() / n, a + (b - a) * m.end() / n
            words.append(Word(m.group(), s, max(e, s)))
        out.append(words)
        off += len(ln) + 1
    return out


# ---------- chính tả Pháp ----------
_CLOSE_ONLY = re.compile(r"^[»!?;:.,…)\]]+$")


def _quotes(words: list[Word]) -> None:
    """Ngoặc kép thẳng / cong → « » (mở khi đang đóng, đóng khi đang mở)."""
    open_ = False
    for w in words:
        chars = []
        for ch in w.text:
            if ch == "“" or (ch == '"' and not open_):
                ch, open_ = "«", True
            elif ch == "”" or (ch == '"' and open_):
                ch, open_ = "»", False
            elif ch == "«":
                open_ = True
            elif ch == "»":
                open_ = False
            chars.append(ch)
        w.text = "".join(chars)


def fr_text(text: str) -> str:
    """Khoảng trắng không ngắt trước : ; ! ? và trong « », dấu nháy ’. Không đụng 12:30 hay https://."""
    text = text.replace("'", "’")
    text = re.sub(r"«[  ]*", "«" + NBSP, text)
    text = re.sub(r"(?<=\S)[  ]*»", NBSP + "»", text)
    text = re.sub(r"(?<=[^\s ])[  ]*([!?;:]+)(?=$|[\s »)\].,…])", NBSP + r"\1", text)
    return text


def fr_typography(text: str) -> str:
    """Áp chính tả Pháp cho cả câu (tiêu đề, phụ đề)."""
    words = [Word(t, 0, 0) for t in text.split()]
    return " ".join(w.text for w in french_words(words))


def french_words(words: list[Word]) -> list[Word]:
    """Gộp dấu câu đứng riêng vào từ bên cạnh (« vào từ sau, ! ? » … vào từ trước) rồi áp chính tả Pháp.

    Sau bước này mỗi Word là một khối không ngắt dòng: « Bonjour », France !, 12:30.
    """
    words = [Word(w.text, w.start, w.end) for w in words]
    _quotes(words)
    out: list[Word] = []
    carry: Word | None = None
    for w in words:
        if carry:
            w = Word(carry.text + w.text, carry.start, w.end)
            carry = None
        if w.text == "«":
            carry = w
        elif out and _CLOSE_ONLY.match(w.text):
            out[-1] = Word(out[-1].text + w.text, out[-1].start, w.end)
        else:
            out.append(w)
    if carry:
        out.append(carry)
    for w in out:
        w.text = fr_text(w.text)
    return out


# ---------- ngắt dòng, chia cue ----------
def _ends_phrase(w: Word) -> bool:
    return w.text.rstrip("»" + NBSP)[-1:] in ",;:.!?…"


def _join(ws: list[Word]) -> str:
    return " ".join(w.text for w in ws)


def split_lines(words: list[Word], fits: Callable[[str], bool], max_lines: int = MAX_LINES) -> list[list[Word]] | None:
    """Xếp các từ vào ≤ max_lines dòng vừa khung; 2 dòng thì cân độ dài. None nếu không xếp được."""
    if fits(_join(words)):
        return [words]
    if max_lines < 2:
        return None
    best = None
    for i in range(1, len(words)):
        a, b = _join(words[:i]), _join(words[i:])
        if fits(a) and fits(b):
            # Ưu tiên cân nhau; dòng trên ngắn hơn một chút đọc dễ hơn
            score = max(len(a), len(b)) + (0.5 if len(a) > len(b) else 0)
            if best is None or score < best[0]:
                best = (score, i)
    if best is None:
        return None
    return [words[:best[1]], words[best[1]:]]


def default_fits(text: str) -> bool:
    return len(text) <= MAX_CHARS


def _rebalance_tail(groups: list[list[Word]], fits, max_lines: int, min_tail: int) -> list[list[Word]]:
    """Cue cuối quá ngắn (vd. "soir ?"): gộp vào cue trước nếu vừa, không thì chia lại hai cue cho cân."""
    if len(groups) < 2 or len(_join(groups[-1])) >= min_tail:
        return groups
    both = groups[-2] + groups[-1]
    if split_lines(both, fits, max_lines):
        return groups[:-2] + [both]
    best = None
    for i in range(1, len(both)):
        if split_lines(both[:i], fits, max_lines) and split_lines(both[i:], fits, max_lines):
            score = abs(len(_join(both[:i])) - len(_join(both[i:])))
            if best is None or score < best[0]:
                best = (score, i)
    return groups[:-2] + [both[:best[1]], both[best[1]:]] if best else groups


def build_cues(line_words: list[list[Word]], total: float, fits: Callable[[str], bool] = default_fits,
               max_lines: int = MAX_LINES, min_phrase: int = 28, shift: float = 0.0,
               hold: float | None = None) -> list[Cue]:
    """Chia từng dòng kịch bản thành các cue ≤ max_lines dòng. Mỗi cue kéo tới lúc cue sau bắt đầu (liền mạch);
    `hold` (giây): cue tắt sau từ cuối chừng này nếu cue sau còn xa (bản lồng tiếng có khoảng lặng giữa các câu).

    Ngắt ưu tiên sau dấu câu khi cue đã đủ dài (min_phrase ký tự); cue cuối quá ngắn được gộp hoặc chia lại.
    `shift` dời mọi mốc (giọng đọc được chèn trễ trong bản dựng).
    """
    groups: list[list[Word]] = []
    for words in line_words:
        words = french_words(words)
        line_groups: list[list[Word]] = []
        cur: list[Word] = []
        for w in words:
            if cur and split_lines(cur + [w], fits, max_lines) is None:
                line_groups.append(cur)
                cur = []
            cur.append(w)
            if _ends_phrase(w) and len(_join(cur)) >= min_phrase:
                line_groups.append(cur)
                cur = []
        if cur:
            line_groups.append(cur)
        groups += _rebalance_tail(line_groups, fits, max_lines, min_phrase // 2)
    cues = []
    for i, g in enumerate(groups):
        start = g[0].start + shift
        end = groups[i + 1][0].start + shift if i + 1 < len(groups) else total
        if hold is not None:
            end = min(end, g[-1].end + shift + hold)
        lines = split_lines(g, fits, max_lines) or [g]
        cues.append(Cue(start, max(end, start + 0.05),
                        [[Word(w.text, w.start + shift, w.end + shift) for w in ln] for ln in lines]))
    return cues


def karaoke_frames(cues: list[Cue]) -> list[tuple[float, float, Cue | None, int]]:
    """Các khung liên tiếp phủ [0, cuối]: (bắt đầu, kết thúc, cue, số từ đã đọc). cue None = không có chữ."""
    frames = []
    t = 0.0
    for c in cues:
        if c.start > t + 0.01:
            frames.append((t, c.start, None, 0))
        ws = c.words
        for k, w in enumerate(ws):
            a = c.start if k == 0 else max(w.start, c.start)
            b = ws[k + 1].start if k + 1 < len(ws) else c.end
            b = min(max(b, a), c.end)
            if b - a > 0.001:
                frames.append((a, b, c, k + 1))
        t = c.end
    return frames


def plain_frames(cues: list[Cue]) -> list[tuple[float, float, Cue | None, int]]:
    """Như karaoke_frames nhưng mỗi cue một khung, chữ trắng cả cue (phụ đề thường, không tô từng từ)."""
    frames = []
    t = 0.0
    for c in cues:
        if c.start > t + 0.01:
            frames.append((t, c.start, None, 0))
        if c.end - c.start > 0.001:
            frames.append((c.start, c.end, c, 0))
        t = max(t, c.end)
    return frames


# ---------- xuất file ----------
def _ts(t: float, sep: str = ",") -> str:
    ms = max(int(round(t * 1000)), 0)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    return "\n".join(f"{i}\n{_ts(c.start)} --> {_ts(c.end)}\n{c.text()}\n" for i, c in enumerate(cues, 1))


def _ass_ts(t: float) -> str:
    cs = max(int(round(t * 100)), 0)
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def to_ass(cues: list[Cue], width: int = 1080, height: int = 1920, font: str = "Arial", size: int = 60,
           margin_v: int = 380) -> str:
    """ASS có thẻ karaoke \\kf (từ chuyển trắng → vàng khi được đọc), để sửa trong Aegisub / CapCut."""
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Karaoke,{font},{size},&H000AD6FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,0,"
        f"2,60,60,{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    rows = []
    for c in cues:
        parts, t = [], c.start
        for li, ln in enumerate(c.lines):
            for wi, w in enumerate(ln):
                nxt = ln[wi + 1].start if wi + 1 < len(ln) else (
                    c.lines[li + 1][0].start if li + 1 < len(c.lines) else c.end)
                dur = max(int(round((nxt - t) * 100)), 1)
                t = nxt
                sep = " " if wi + 1 < len(ln) else ""
                parts.append(f"{{\\kf{dur}}}{w.text}{sep}")
            if li + 1 < len(c.lines):
                parts.append("\\N")
        rows.append(f"Dialogue: 0,{_ass_ts(c.start)},{_ass_ts(c.end)},Karaoke,,0,0,0,,{''.join(parts)}")
    return head + "\n".join(rows) + "\n"
