"""Quality check of a finished video, run after every render (ffprobe + FFmpeg's own detectors) and a look at what the
channel already posted.

Each finding is {"id", "level": "ok" | "warn" | "fail", "msg"} (msg in the UI language). `fail` means the video is not
fit to post as it is (no sound, outside 62–90 s, a black first frame, almost all silence): the project stops at the
video gate instead of going to Postiz by itself, and the owner can still approve it. `warn` is only shown. The
thresholds are Motio's own, not a platform rule. FFmpeg's detector pass never fails a video when it cannot run: the
check says so and the video goes on. A file ffprobe cannot read at all is a `fail`.
"""
import difflib
import json
import re
import subprocess
import time
import unicodedata
from pathlib import Path

from . import config, db
from .i18n import tr

LEVELS = ("ok", "warn", "fail")
TARGET_LUFS = -14.0  # what render.py normalises to
LUFS_TOLERANCE = 2.0  # loudnorm lands within about 1 LU; further than this something went wrong
PEAK_MAX = -0.5  # dBFS: above this the AAC encode can clip
LENGTH_SLACK = 0.25  # s: container rounding
SILENCE_FROM = 1.2  # s of silence that count as a gap
SILENCE_WARN = 1.5  # a gap this long inside the video is shown
SILENT_SHARE = 0.5  # more than this share of the video silent: the voice is missing
BLACK_FROM = 0.3  # s of black that count as a black picture
BLACK_PIC = 0.90  # share of dark pixels that makes a frame black: the title, badge and captions light 3–5% of a render
BLACK_FIRST = 0.5  # a black start this long makes the cover black
TAIL_SLACK = 0.35  # silence reaching the last 0.35 s is the ending, not a gap
REPEAT_DAYS = 30
REPEAT_LOOKBACK = 600  # projects looked at: 30 days of a busy install (6 a day, failed ones included) fit
TITLE_SAME = 0.85  # title similarity (0–1) that is "almost the same"
SCRIPT_SAME = 0.5  # share of 5-word runs two scripts have in common that is "the same script"
TIMEOUT = 300


def _finding(fid: str, level: str, msg: str) -> dict:
    return {"id": fid, "level": level, "msg": msg}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)


def probe(path: Path) -> dict:
    """ffprobe: {"duration", "video": {...} | None, "audio": {...} | None}. RuntimeError when the file is unreadable."""
    r = _run([config.ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "ffprobe failed").strip()[:200])
    try:
        data = json.loads(r.stdout)
    except ValueError as e:
        raise RuntimeError("ffprobe returned nothing readable") from e
    streams = data.get("streams") or []

    def pick(kind: str) -> dict | None:
        return next((s for s in streams if s.get("codec_type") == kind), None)

    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {"duration": duration, "video": pick("video"), "audio": pick("audio")}


_NUM = r"(-?inf|-?\d+(?:\.\d+)?)"


def _num(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def parse_scan(text: str, duration: float) -> dict:
    """FFmpeg's log → {"black": [(start, end)], "silence": [(start, end)], "lufs", "lra", "peak"} (None = not in the
    log, -inf for a file with no sound at all). A silence still open at the end of the log runs to `duration`."""
    num = r"(\d+(?:\.\d+)?)"
    black = [(float(a), float(b)) for a, b in re.findall(rf"black_start:{num} black_end:{num}", text)]
    silence, start = [], None
    for m in re.finditer(r"silence_start: (-?\d+(?:\.\d+)?)|silence_end: (-?\d+(?:\.\d+)?)", text):
        if m.group(1) is not None:
            start = max(0.0, float(m.group(1)))
        elif start is not None:
            silence.append((start, float(m.group(2))))
            start = None
    if start is not None:
        silence.append((start, duration))
    summary = text.rsplit("Summary:", 1)[-1] if "Summary:" in text else ""

    def last(pattern: str) -> float | None:
        found = re.findall(pattern, summary)
        return _num(found[-1]) if found else None

    return {"black": black, "silence": silence, "lufs": last(rf"\bI:\s+{_NUM} LUFS"),
            "lra": last(rf"\bLRA:\s+{_NUM} LU"), "peak": last(rf"\bPeak:\s+{_NUM} dBFS")}


def scan(path: Path, has_audio: bool, duration: float) -> dict:
    """One FFmpeg pass over the whole file with the black / silence / loudness detectors."""
    cmd = [config.ffmpeg(), "-nostdin", "-hide_banner", "-nostats", "-v", "info", "-i", str(path),
           "-vf", f"blackdetect=d={BLACK_FROM}:pic_th={BLACK_PIC}:pix_th=0.10"]
    if has_audio:
        cmd += ["-af", f"silencedetect=n=-50dB:d={SILENCE_FROM},ebur128=peak=true:framelog=quiet"]
    r = _run(cmd + ["-f", "null", "-"])
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "ffmpeg failed").strip()[-200:])
    return parse_scan(r.stderr, duration)


def at(sec: float) -> str:
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def findings(info: dict, sc: dict | None, lo: float, hi: float) -> list[dict]:
    """The checks of one video. `sc` is None when FFmpeg's pass could not run (only the file facts are judged)."""
    out, dur = [], info["duration"]
    v, a = info["video"], info["audio"]
    if dur < lo - LENGTH_SLACK or dur > hi + LENGTH_SLACK:
        out.append(_finding("length", "fail", tr("Length {seconds} s: it must be {lo} to {hi} s",
                                                  seconds=f"{dur:.1f}", lo=f"{lo:.0f}", hi=f"{hi:.0f}")))
    else:
        out.append(_finding("length", "ok", tr("Length {seconds} s", seconds=f"{dur:.1f}")))
    if not v:
        out.append(_finding("video", "fail", tr("No picture track")))
    else:
        size = f"{v.get('width')}×{v.get('height')}"
        spec_ok = (v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p"
                   and (v.get("width"), v.get("height")) == (config.W, config.H))
        out.append(_finding("video", "ok" if spec_ok else "warn",
                            tr("Picture {size}, H.264" if spec_ok else
                               "Picture is {codec} {size} {pix}: platforms expect H.264 {want} yuv420p",
                               size=size, codec=v.get("codec_name"), pix=v.get("pix_fmt"),
                               want=f"{config.W}×{config.H}")))
    if not a:
        out.append(_finding("audio", "fail", tr("No sound track")))
    else:
        out.append(_finding("audio", "ok" if a.get("codec_name") == "aac" else "warn",
                            tr("Sound track present" if a.get("codec_name") == "aac" else
                               "Sound is {codec}: platforms expect AAC", codec=a.get("codec_name"))))
    if sc is not None:
        if a:
            out += _sound(sc, dur)
        out.append(_black(sc))
    return out


def _sound(sc: dict, dur: float) -> list[dict]:
    res = []
    lufs, peak = sc.get("lufs"), sc.get("peak")
    silent = sum(max(0.0, b - a) for a, b in sc["silence"])
    share = min(1.0, silent / dur) if dur else 1.0
    if share > SILENT_SHARE or lufs == float("-inf"):
        return [_finding("loudness", "fail", tr("The video is almost silent ({share}% silence)",
                                                share=f"{max(share, 1.0 if lufs == float('-inf') else 0) * 100:.0f}"))]
    if lufs is not None and abs(lufs - TARGET_LUFS) > LUFS_TOLERANCE:
        res.append(_finding("loudness", "warn", tr("Loudness {lufs} LUFS: Motio aims for {target}",
                                                    lufs=f"{lufs:.1f}", target=f"{TARGET_LUFS:.0f}")))
    elif peak is not None and peak > PEAK_MAX:
        res.append(_finding("loudness", "warn", tr("Sound peaks at {peak} dBFS: it may clip", peak=f"{peak:.1f}")))
    elif lufs is not None:
        res.append(_finding("loudness", "ok", tr("Loudness {lufs} LUFS", lufs=f"{lufs:.1f}")))
    gaps = [(a, b) for a, b in sc["silence"] if b < dur - TAIL_SLACK and b - a >= SILENCE_WARN]
    if gaps:
        a, b = gaps[0]
        more = tr(" (and {n} more)", n=len(gaps) - 1) if len(gaps) > 1 else ""
        res.append(_finding("silence", "warn",
                            tr("Silence of {seconds} s at {at}", seconds=f"{b - a:.1f}", at=at(a)) + more))
    else:
        res.append(_finding("silence", "ok", tr("No long silence")))
    return res


def _black(sc: dict) -> dict:
    first = next((b - a for a, b in sc["black"] if a < 0.05 and b - a >= BLACK_FIRST), None)
    if first is not None:
        return _finding("black", "fail", tr("The first picture is black for {seconds} s: the cover would be black",
                                            seconds=f"{first:.1f}"))
    mid = [(a, b) for a, b in sc["black"] if b - a >= BLACK_FIRST]
    if mid:
        a, b = mid[0]
        return _finding("black", "warn", tr("Black picture for {seconds} s at {at}", seconds=f"{b - a:.1f}", at=at(a)))
    return _finding("black", "ok", tr("No black picture"))


def level(checks: list[dict]) -> str:
    return max((c["level"] for c in checks), key=LEVELS.index, default="ok")


def run(path: Path, lo: float, hi: float) -> dict:
    """The quality check of one video file: {"level", "checks", "at"}. Never raises."""
    try:
        info = probe(path)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        checks = [_finding("file", "fail", tr("The video file cannot be read: {error}", error=str(e)[:160]))]
        return {"level": "fail", "checks": checks, "at": time.time()}
    sc = None
    try:
        sc = scan(path, bool(info["audio"]), info["duration"])
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        extra = _finding("scan", "warn", tr("Could not check sound and black pictures: {error}", error=str(e)[:160]))
    else:
        extra = None
    checks = findings(info, sc, lo, hi) + ([extra] if extra else [])
    return {"level": level(checks), "checks": checks, "at": time.time()}


# ---------- what the channel already posted ----------
def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def _runs(words: list[str], n: int = 5) -> set[tuple]:
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def _script_words(pid: int) -> list[str]:
    try:
        plan = json.loads((config.PROJECTS / str(pid) / "script.json").read_text(encoding="utf-8"))
        return _norm(" ".join(str(ln.get("text") or "") for ln in plan.get("lines") or [])).split()
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def _earlier(pid: int, now: float) -> list[dict]:
    """The projects made in the last REPEAT_DAYS days (newest first), this one and failed ones left out."""
    return [o for o in db.list_projects(REPEAT_LOOKBACK)
            if o["id"] != pid and o["status"] != "failed" and now - (o.get("created_at") or 0) <= REPEAT_DAYS * 86400]


def repeats(pid: int, now: float | None = None) -> list[dict]:
    """Warnings when this project looks like one already made in the last 30 days: the same source video, an almost
    identical title, or the same script. Only `warn`: the owner decides (a series legitimately reuses a source)."""
    proj = db.get_project(pid)
    if not proj:
        return []
    now = now or time.time()
    meta = proj.get("meta") or {}
    sources = {(s.get("platform"), s.get("id")) for s in meta.get("sources") or [] if s.get("id")}
    title = _norm(meta.get("title") or proj.get("title") or "")
    runs = _runs(_script_words(pid))
    found: dict[str, dict] = {}  # the first (newest) project each warning is about
    for other in _earlier(pid, now):
        om = other.get("meta") or {}
        ref = {"n": other["id"], "days": int((now - (other.get("created_at") or now)) // 86400)}
        if "repeat_source" not in found and sources & {(s.get("platform"), s.get("id"))
                                                       for s in om.get("sources") or [] if s.get("id")}:
            found["repeat_source"] = _finding("repeat_source", "warn", tr(
                "The same source video was already used in project #{n} ({days} d ago)", **ref))
        theirs = _norm(om.get("title") or other.get("title") or "")
        if ("repeat_title" not in found and title and theirs
                and difflib.SequenceMatcher(None, title, theirs).ratio() >= TITLE_SAME):
            found["repeat_title"] = _finding("repeat_title", "warn", tr(
                "The title is almost the same as project #{n} ({days} d ago)", **ref))
        if runs and "repeat_script" not in found:
            theirs_runs = _runs(_script_words(other["id"]))
            if theirs_runs and len(runs & theirs_runs) / min(len(runs), len(theirs_runs)) >= SCRIPT_SAME:
                found["repeat_script"] = _finding("repeat_script", "warn", tr(
                    "The script is very close to project #{n} ({days} d ago)", **ref))
    return list(found.values())


def check_project(pid: int, video: Path, lo: float, hi: float) -> dict:
    """Quality check of the rendered video plus the repeat warnings, saved on the project as `meta.qa`."""
    res = run(video, lo, hi)
    try:
        extra = repeats(pid)
    except Exception as e:  # noqa: BLE001 - a look at old projects must never fail a finished video
        extra = [_finding("repeat", "warn", tr("Could not compare with earlier videos: {error}", error=str(e)[:160]))]
    res["checks"] += extra
    res["level"] = level(res["checks"])
    return res


def failed(proj: dict) -> bool:
    """True when the last quality check found something that makes the video unfit to post as it is."""
    return ((proj.get("meta") or {}).get("qa") or {}).get("level") == "fail"
