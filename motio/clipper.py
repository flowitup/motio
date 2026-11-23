"""Chế độ "Clip" (cắt highlight): một video dài (VOD, trailer, video phản ứng…) → các video đứng 9:16 giữ tiếng gốc.

Hai cách chạy, cùng một engine:
- Claude tự chọn (`start(..., then=export)`): tải, bóc lời, Claude chọn các khoảnh khắc đáng xem, mỗi cái thành một
  dự án (`export`) chạy như mọi video (cổng duyệt, Postiz theo hồ sơ kênh);
- người dùng tự chọn (màn Clip Studio): cùng bước phân tích cho ra đề xuất, người dùng kéo mốc, kéo khung crop, sửa chữ
  hook rồi mới `export`.

Một dự án clip = một đoạn [start, end] của nguồn: hình cắt 9:16 (khung crop trượt theo `crop.x`, hoặc cả khung hình trên
nền mờ), TIẾNG GỐC giữ nguyên (không giọng đọc), phụ đề từ lời gốc (dịch sang tiếng Pháp nếu nguồn không nói tiếng
Pháp) và một dòng chữ hook ở trên. Mỗi clip 15–90 s (chủ dự án, 2026-11-21); video ở các chế độ khác vẫn 62–90 s.
Clip giữ hình và lời của người khác: như mọi video, nó chỉ tự gửi Postiz qua hồ sơ kênh có kênh Postiz và đã tắt cổng
duyệt video. Không có gì ở đây để tránh bị nhận diện trùng lặp / Content ID.
"""
import dataclasses
import json
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from . import asr, channels, config, db, delogo, facetrack, llm, localfile, render, scenes, search, toolbox, usage
from . import captions as cap
from .asr import has_audio
from .i18n import tr, tr_n

MODE = "clip"
MIN_LEN = 15.0  # giây: clip dài từ 15 s (chủ dự án, 2026-11-21); chỉ chế độ Clip, video khác vẫn 62–90 s
MAX_LEN = 90.0  # giây: trần cứng của Facebook Reels (pipeline.MAX_SECONDS)
MAX_CLIPS = 12  # số clip tối đa một lần phân tích / xuất
DEFAULT_CLIPS = 4
CHUNK = 1500.0  # giây lời thoại Claude đọc một lượt (VOD dài thì đọc từng đoạn rồi gộp)
PER_CHUNK = 5  # số khoảnh khắc xin Claude mỗi lượt
MAX_KEYS = 40  # số mốc khung crop tối đa
MAX_HOOK = 80  # ký tự của chữ hook
KEEP_JOBS = 20
CAPTIONS = ("off", "fr", "source")  # phụ đề: không có / tiếng Pháp (dịch nếu cần) / lời gốc
CAP_BOTTOM = 250  # px từ đáy khung tới đáy dải phụ đề (chừa chỗ cho giao diện TikTok / Reels)
EDGE = 0.05  # giây dư để độ dài sau khi làm tròn không rơi xuống dưới 15 s / vượt 90 s
OVERLAP = 0.3  # hai khoảnh khắc chồng nhau quá chừng này (tỉ lệ độ dài) thì bỏ cái điểm thấp

PICK_SYSTEM = ("Tu es monteur pour une chaîne francophone de clips verticaux (TikTok, Reels, Shorts). "
               "Tu choisis les meilleurs moments d'une vidéo longue. Réponds uniquement en JSON.")
PICK_PROMPT = """Vidéo : « {title} » ({duration:.0f} s), langue parlée : {language}.
Transcription de {a:.0f} à {b:.0f} s (segments [début–fin] en secondes, texte) :
{segments}

Choisis jusqu'à {n} moments à publier en clip vertical. Chaque moment :
- dure entre {lo:.0f} et {hi:.0f} secondes, commence au début d'une phrase et finit à la fin d'une phrase (utilise les
  horodatages des segments) ;
- se comprend seul, sans le reste de la vidéo : une réaction, une révélation, une punchline, un point fort ;
- ne contient ni salutations, ni appel à s'abonner, ni intro / outro ;
- ne recoupe pas un autre moment choisi.
Donne pour chacun : « score » de 1 à 10 (potentiel viral), « why » (une phrase) et « hook », un texte d'accroche en
français de {hook} caractères maximum, percutant, à afficher en haut de la vidéo.

Réponds : {{"clips": [{{"start": s, "end": s, "score": 8, "hook": "...", "why": "..."}}]}}"""

META_SYSTEM = ("Tu écris le titre et la description d'un clip vertical pour une chaîne francophone. "
               "Réponds uniquement en JSON.")
META_PROMPT = """Clip tiré de la vidéo « {title} » ({platform}{uploader}), de {a:.0f} à {b:.0f} s.
Paroles du clip (en français, sinon la langue d'origine) :
{lines}

Écris le titre (80 caractères max), la description du post (2 phrases, sans hashtags), des hashtags
{hook_note}N'ajoute aucun fait absent de la vidéo.
Réponds : {{"title_fr": "...", "description": "...", "hashtags": ["#...", "..."]{hook_key}}}"""


def _one(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clock(sec: float) -> str:
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def is_clip(proj: dict) -> bool:
    return (proj or {}).get("mode") == MODE


# ---------- choisir les khoảnh khắc ----------
def _snap(t: float, marks: list[float], within: float = 2.0) -> float:
    best = min(marks, key=lambda m: abs(m - t)) if marks else t
    return best if abs(best - t) <= within else t


def tidy(raw, duration: float, segs: list[dict], lo: float, hi: float, n: int) -> list[dict]:
    """Câu trả lời của Claude → các khoảnh khắc dùng được, điểm cao trước: mốc bám ranh giới câu, độ dài trong [lo, hi],
    nằm trong video, không chồng nhau. Bỏ cái nào không sửa được."""
    starts, ends = [g["start"] for g in segs], [g["end"] for g in segs]
    rows = raw.get("clips") if isinstance(raw, dict) else raw
    found: list[dict] = []
    for r in rows if isinstance(rows, list) else []:
        try:
            a, b = _snap(float(r["start"]), starts), _snap(float(r["end"]), ends)
            score = min(max(int(float(r.get("score", 5))), 1), 10)
        except (KeyError, TypeError, ValueError):
            continue
        a, b = max(0.0, a - 0.15), min(duration, b + 0.3)  # vào sớm một chút để không mất âm đầu câu
        if b - a > hi:  # dài quá: dừng ở cuối câu gần nhất trong giới hạn
            b = max([e for e in ends if a + lo + EDGE <= e <= a + hi - EDGE] or [a + hi - EDGE])
        if b - a < lo + EDGE:
            b = min(duration, a + lo + EDGE)
        a, b = round(a, 2), round(b, 2)
        if not (0 <= a < b <= duration) or b - a < lo or b - a > hi:
            continue
        found.append({"start": a, "end": b, "score": score,
                      "hook": _one(r.get("hook"))[:MAX_HOOK], "why": _one(r.get("why"))[:200]})
    found.sort(key=lambda c: (-c["score"], c["start"]))
    kept: list[dict] = []
    for c in found:
        if all(min(c["end"], k["end"]) - max(c["start"], k["start"]) <= OVERLAP * min(c["end"] - c["start"],
                                                                                    k["end"] - k["start"])
               for k in kept):
            kept.append(c)
        if len(kept) >= n:
            break
    return kept


def _fmt(segs: list[dict]) -> str:
    return "\n".join(f"[{g['start']:.1f}–{g['end']:.1f}] {g['text']}" for g in segs)


def rms_per_second(src: Path) -> list[float]:
    """Mức âm (dB RMS) từng giây của video; [] khi không đọc được. Dùng khi video không có lời để chọn khoảnh khắc."""
    r = subprocess.run([config.ffmpeg(), "-v", "error", "-i", str(src), "-vn", "-af",
                        "aresample=16000,asetnsamples=n=16000:p=0,astats=metadata=1:reset=1,"
                        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=30 * 60)
    out = []
    for m in re.finditer(r"RMS_level=(-?[0-9.]+|-?inf)", r.stdout):
        out.append(-90.0 if "inf" in m.group(1) else max(float(m.group(1)), -90.0))
    return out


def loud_moments(levels: list[float], duration: float, lo: float, hi: float, n: int) -> list[dict]:
    """Video không có lời: các đoạn dài (lo+hi)/2 giây to nhất (không chồng nhau)."""
    length = int(min((lo + hi) / 2, duration))
    if length < lo - 0.01 or len(levels) < length:
        return []
    mean = [sum(levels[i:i + length]) / length for i in range(len(levels) - length + 1)]
    order = sorted(range(len(mean)), key=lambda i: -mean[i])
    kept: list[int] = []
    for i in order:
        if all(abs(i - k) >= length for k in kept):
            kept.append(i)
        if len(kept) >= n:
            break
    return [{"start": float(i), "end": float(min(i + length, duration)), "score": 5, "hook": "",
             "why": tr("the loudest part of the video")} for i in sorted(kept)]


def moments(src: dict, transcript: dict, lo: float, hi: float, n: int, step=None) -> list[dict]:
    """Các khoảnh khắc Claude đề xuất cho một nguồn đã bóc lời (chia VOD dài thành lượt CHUNK giây)."""
    duration = float(src.get("duration") or 0)
    segs = [g for g in transcript.get("segments") or [] if _one(g.get("text"))]
    if not segs:  # không có lời: chọn theo mức âm
        return loud_moments(rms_per_second(Path(src["path"])), duration, lo, hi, n)
    language = transcript.get("language") or "?"
    rows: list[dict] = []
    t, i = 0.0, 0
    chunks = max(int(duration // CHUNK) + 1, 1)
    while t < max(duration, segs[-1]["end"]):
        part = [g for g in segs if t <= g["start"] < t + CHUNK]
        if part and (part[-1]["end"] - part[0]["start"]) >= lo:
            if step:
                step("Script", 55 + int(8 * i / chunks), tr("Claude is reading part {i} of {n}", i=i + 1, n=chunks))
            raw = llm.ask_json(PICK_PROMPT.format(title=src.get("title") or "", duration=duration, language=language,
                                                  a=t, b=min(t + CHUNK, duration), segments=_fmt(part),
                                                  n=min(PER_CHUNK, n), lo=lo, hi=hi, hook=MAX_HOOK), PICK_SYSTEM,
                               effort="low")
            rows += tidy(raw, duration, segs, lo, hi, PER_CHUNK)
        t, i = t + CHUNK, i + 1
    return tidy(rows, duration, segs, lo, hi, n)


# ---------- phân tích nền (Clip Studio / tự chọn) ----------
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _media(path: str | None) -> str | None:
    try:
        return Path(path).resolve().relative_to(config.DATA.resolve()).as_posix() if path else None
    except ValueError:
        return None


def _set(job_id: str, **fields) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def clean_params(link: str, count=DEFAULT_CLIPS) -> tuple[str, int]:
    links = search.clean_links([link])
    if len(links) != 1:
        raise ValueError(tr("Enter the link of the video to clip"))
    try:
        n = int(count)
    except (TypeError, ValueError) as e:
        raise ValueError(tr("The number of clips must be between 1 and {max}", max=MAX_CLIPS)) from e
    if not 1 <= n <= MAX_CLIPS:
        raise ValueError(tr("The number of clips must be between 1 and {max}", max=MAX_CLIPS))
    return links[0], n


def _analyze(job_id: str, link: str, n: int, then) -> None:
    try:
        lo = MIN_LEN
        _set(job_id, message=tr("Downloading {url}", url=link), pct=5)
        src = search.download(link, config.CACHE / "sources", cookies=True)
        _set(job_id, _path=str(src["path"]), message=tr("Whisper: {name}", name=Path(src["path"]).name), pct=25,
             source={"path": _media(src["path"]), "title": src.get("title") or "", "duration": src.get("duration"),
                     "platform": src.get("platform") or "", "uploader": src.get("uploader") or ""})
        transcript = asr.transcribe(Path(src["path"]))
        info = delogo.probe(Path(src["path"]))
        duration = float(src.get("duration") or info.get("duration") or 0)
        if duration < lo - 0.01:
            raise ValueError(tr("This video lasts {n} s: shorter than the {lo} s a clip needs",
                                n=f"{duration:.0f}", lo=f"{lo:.0f}"))
        src = {**src, "duration": duration}
        _set(job_id, message=tr("Claude is choosing the best moments"), pct=55,
             source={"path": _media(src["path"]), "title": src.get("title") or "", "duration": duration,
                     "platform": src.get("platform") or "", "uploader": src.get("uploader") or "",
                     "width": info.get("width"), "height": info.get("height")})
        with usage.context(project_id=None, channel_id=None):
            found = moments(src, transcript, lo, MAX_LEN, n)
        cuts = scenes.detect(Path(src["path"]))
        if found:
            _set(job_id, message=tr("Following the faces"), pct=80)
        clips = [{**c, "crop": follow_face(Path(src["path"]), c["start"], c["end"])} for c in found]
        _set(job_id, pct=95, language=transcript.get("language"), cuts=cuts, speech=bool(transcript.get("segments")),
             clips=clips)
        if not found:
            raise ValueError(tr("No moment worth clipping was found in this video"))
        made: list[int] = []
        if then:
            made = then(link, clips)
        _set(job_id, status="done", pct=100, message=None, finished_at=time.time(), projects=made)
    except Exception as e:  # shown in the app; the job ends, the engine goes on
        _set(job_id, status="failed", message=None, error=str(e)[:400], finished_at=time.time())


def start(link: str, count=DEFAULT_CLIPS, then=None) -> dict:
    """Phân tích một video dài ở nền: tải, bóc lời, Claude đề xuất các khoảnh khắc. `then(link, clips)` (cách
    Claude tự chọn) chạy khi xong và trả các id dự án đã tạo. ValueError nếu dữ liệu sai."""
    link, n = clean_params(link, count)
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        for old in sorted(_jobs.values(), key=lambda j: j["created_at"])[:-(KEEP_JOBS - 1)]:
            if old["status"] != "running":
                _jobs.pop(old["id"], None)
        _jobs[job_id] = {"id": job_id, "link": link, "count": n, "auto": then is not None,
                         "status": "running", "message": tr("Starting…"), "pct": 0, "source": None, "clips": [],
                         "cuts": [], "language": None, "speech": None, "projects": [], "error": None,
                         "created_at": time.time(), "finished_at": None}
    threading.Thread(target=_analyze, args=(job_id, link, n, then), daemon=True, name="motio-clipper").start()
    return job_view(job_id)


def job_view(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        return {**{k: v for k, v in job.items() if not k.startswith("_")},
                "clips": [dict(c) for c in job["clips"]], "cuts": list(job["cuts"]), "projects": list(job["projects"])}


# ---------- khung crop ----------
def default_crop() -> dict:
    """Khung 9:16 giữa hình, cắt kín khung (fit = cả khung hình đặt trên nền mờ)."""
    return {"fit": False, "x": [[0.0, 0.5]]}


def find_face_crop(path: Path, start: float, end: float) -> dict | None:
    """Khung crop bám mặt của đoạn [start, end] (facetrack), None khi không thấy mặt, nguồn đã đứng hoặc bám lỗi."""
    try:
        return facetrack.crop_for(path, start, end)
    except Exception:  # bám mặt chỉ là gợi ý: lỗi thì không bám, clip vẫn làm được
        return None


def follow_face(path: Path, start: float, end: float) -> dict:
    return find_face_crop(path, start, end) or default_crop()


def _range(start, end) -> tuple[float, float]:
    try:
        a, b = float(start), float(end)
    except (TypeError, ValueError) as e:
        raise ValueError(tr("A clip needs a start and an end in seconds")) from e
    if a < 0 or b <= a or b - a > MAX_LEN + 0.01:
        raise ValueError(tr("The clip must lie inside the video"))
    return a, b


def track_job(job_id: str, start, end) -> dict:
    """Bám mặt cho một đoạn của video đã phân tích (Clip Studio). {crop, found}. KeyError nếu không có phân tích đó."""
    with _lock:
        path = Path(_jobs[job_id].get("_path") or "")
    if not path.is_file():
        raise ValueError(tr("The video is not downloaded yet"))
    a, b = _range(start, end)
    crop = find_face_crop(path, a, b)
    return {"crop": crop or default_crop(), "found": crop is not None}


def track_project(pid: int, start=None, end=None) -> dict:
    """Bám mặt cho đoạn hiện tại (hoặc [start, end] chưa lưu) của một dự án clip đã tải nguồn. {crop, found}."""
    p = db.get_project(pid)
    if not p or not is_clip(p):
        raise LookupError(tr("Clip project not found"))
    opts = p["meta"].get("clip") or {}
    src = (p["meta"].get("sources") or [None])[0]
    if not src or not src.get("path") or not Path(src["path"]).exists():
        raise ValueError(tr("The video is not downloaded yet"))
    a, b = _range(opts.get("start") if start is None else start, opts.get("end") if end is None else end)
    crop = find_face_crop(Path(src["path"]), a, b)
    return {"crop": crop or default_crop(), "found": crop is not None}


def clean_crop(raw, dur: float | None = None) -> dict:
    """{fit, x: [[giây trong clip, tâm 0..1], …]} đã sửa: mốc tăng dần, tối đa MAX_KEYS. ValueError nếu sai kiểu."""
    if raw is None:
        return default_crop()
    if not isinstance(raw, dict):
        raise ValueError(tr("The crop must be an object with fit and x"))
    pts = raw.get("x", 0.5)
    if isinstance(pts, (int, float)):
        pts = [[0.0, pts]]
    if not isinstance(pts, list) or not pts or len(pts) > MAX_KEYS:
        raise ValueError(tr("The crop needs between 1 and {max} positions", max=MAX_KEYS))
    keys: list[list[float]] = []
    try:
        for p in pts:
            t, x = (p if isinstance(p, (list, tuple)) else (0.0, p))
            t = max(float(t), 0.0)
            if dur is not None:
                t = min(t, dur)
            keys.append([round(t, 2), round(min(max(float(x), 0.0), 1.0), 4)])
    except (TypeError, ValueError) as e:
        raise ValueError(tr("The crop positions must be numbers")) from e
    keys.sort(key=lambda k: k[0])
    return {"fit": bool(raw.get("fit")), "x": keys}


def clean_clip(raw: dict, duration: float | None) -> dict:
    """Một clip người dùng / Claude đặt → {start, end, hook, crop, captions}. ValueError nếu sai hoặc ngoài độ dài."""
    try:
        a, b = round(float(raw["start"]), 2), round(float(raw["end"]), 2)
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(tr("A clip needs a start and an end in seconds")) from e
    lo = MIN_LEN
    if a < 0 or b <= a or (duration and b > duration + 0.5):
        raise ValueError(tr("The clip must lie inside the video"))
    if b - a > MAX_LEN + 0.01:
        raise ValueError(tr("A clip lasts at most {max} s (the Facebook Reels limit)", max=f"{MAX_LEN:.0f}"))
    if b - a < lo - 0.01:
        raise ValueError(tr("A clip lasts at least {min} s", min=f"{lo:.0f}"))
    caps = raw.get("captions") or "fr"
    if caps not in CAPTIONS:
        raise ValueError(tr("Captions must be one of: {options}", options=", ".join(CAPTIONS)))
    hook = raw.get("hook")
    return {"start": a, "end": b, "hook": None if hook is None else _one(hook)[:MAX_HOOK],
            "crop": clean_crop(raw.get("crop"), b - a), "captions": caps}


# ---------- tạo dự án ----------
def create(link: str, clip: dict, duration: float | None = None, title: str = "") -> int:
    """Dự án clip (chưa chạy) cho một đoạn của video. ValueError nếu thiếu / sai dữ liệu."""
    links = search.clean_links([link])
    if len(links) != 1:
        raise ValueError(tr("Enter the link of the video to clip"))
    c = clean_clip(clip, duration)
    site = localfile.title(links[0]) if localfile.parse(links[0]) else urlparse(links[0]).hostname or "video"
    title = _one(title or c["hook"])[:200] or tr("Clip: {site} {a}–{b}", site=site, a=clock(c["start"]),
                                                 b=clock(c["end"]))
    pid = db.create_project(None, title, mode=MODE)
    db.update_project(pid, log=tr("Clip: {url} · part {a}–{b}", url=links[0], a=clock(c["start"]), b=clock(c["end"])),
                      meta={"links": links, "links_only": True, "clip": c})
    return pid


def export(link: str, clips: list[dict], duration: float | None = None) -> list[int]:
    """Một dự án cho mỗi clip. Sai một clip thì không tạo cái nào (ValueError)."""
    if not clips:
        raise ValueError(tr("Pick at least one moment to clip"))
    if len(clips) > MAX_CLIPS:
        raise ValueError(tr("At most {max} clips at a time", max=MAX_CLIPS))
    for c in clips:
        clean_clip(c, duration)
    return [create(link, c, duration) for c in clips]


# ---------- kịch bản: phụ đề + tiêu đề ----------
def _cjk(language: str | None) -> bool:
    return (language or "")[:2] in ("zh", "ja", "ko")


def script(proj: dict, src: dict, transcript: dict, out: Path, step) -> dict:
    """Kịch bản của một clip: phụ đề theo lời gốc (dịch sang tiếng Pháp khi cần), tiêu đề + mô tả + hashtag, chữ hook.
    Ghi script.json."""
    pid, opts = proj["id"], (proj["meta"].get("clip") or {})
    a, b = float(opts["start"]), float(opts["end"])
    ch = channels.for_project(proj)
    language = transcript.get("language")
    step("Script", 55, tr("Captions and title for {a}–{b}", a=clock(a), b=clock(b)))
    segs = [{"start": max(g["start"], a) - a, "end": min(g["end"], b) - a, "text": _one(g["text"])}
            for g in transcript.get("segments") or [] if _one(g["text"]) and a <= (g["start"] + g["end"]) / 2 <= b]
    entries = toolbox.segment_entries(segs, cjk=_cjk(language))
    mode = opts.get("captions") or "fr"
    french = (language or "fr")[:2] == "fr"
    with usage.context(project_id=pid, channel_id=ch["id"] if ch else None):
        if mode == "fr" and entries and not french:
            step("Script", 58, tr("Claude is translating {n} into French", n=tr_n(len(entries), "subtitle")))
            entries = toolbox.translate(entries, "fr", ch)
        elif mode != "off" and french:
            entries = [{**e, "text": "\n".join(cap.fr_typography(x) for x in e["text"].split("\n"))}
                       for e in entries]
        speech = " ".join(e["text"].replace("\n", " ") for e in entries)[:3000]
        want_hook = opts.get("hook") is None
        meta = llm.ask_json(META_PROMPT.format(
            title=src.get("title") or "", platform=src.get("platform") or "video",
            uploader=f" · {src['uploader']}" if src.get("uploader") else "", a=a, b=b,
            lines=speech or tr("(no speech)"), hook_key=', "hook": "..."' if want_hook else "",
            hook_note=(f"et un texte d'accroche en français ({MAX_HOOK} caractères max) à afficher en haut. "
                       if want_hook else ". ")), META_SYSTEM + channels.style_note(ch), light=True)
    hook = _one(meta.get("hook"))[:MAX_HOOK] if want_hook else opts.get("hook") or ""
    if want_hook:
        db.update_project(pid, meta={"clip": {**opts, "hook_auto": hook}})
    plan = {"title_fr": _one(meta.get("title_fr"))[:80] or proj.get("title") or "Clip", "hook": hook,
            "description": _one(meta.get("description")), "hashtags": [h for h in meta.get("hashtags") or []
                                                                         if isinstance(h, str)][:8],
            "captions": entries if mode != "off" else [], "caption_mode": mode,
            "lines": [{"text": e["text"].replace("\n", " ")} for e in entries]}
    (out / "script.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    step("Script", 62, tr("{n} · hook: {hook}", n=tr_n(len(entries), "caption"), hook=hook or tr("none")))
    return plan


# ---------- dựng ----------
def _x_expr(keys: list[list[float]]) -> str:
    """Tâm khung crop (0..1) theo thời gian `t` của clip: tuyến tính giữa các mốc, giữ nguyên ngoài đầu / cuối."""
    if len(keys) == 1:
        return f"{keys[0][1]:.4f}"
    e = f"{keys[-1][1]:.4f}"
    for (t0, x0), (t1, x1) in zip(reversed(keys[:-1]), reversed(keys[1:]), strict=True):
        span = max(t1 - t0, 0.01)
        e = f"if(lt(t,{t1:.2f}),{x0:.4f}+({x1 - x0:.4f})*max(t-{t0:.2f},0)/{span:.2f},{e})"
    return e


def video_filter(crop: dict, w: int, h: int) -> str:
    """Hình nguồn (w×h) → khung đứng W×H, ra luồng [v0]."""
    W, H = config.W, config.H
    if crop.get("fit"):
        return (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=36,"
                f"eq=brightness=-0.10:saturation=0.9[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease:"
                f"flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v0]")
    if w / h <= W / H * 1.02:  # nguồn đã đứng: phủ kín khung
        return f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1[v0]"
    x = _x_expr(crop["x"])
    return (f"[0:v]crop=w='trunc(ih*{W}/{H}/2)*2':h=ih:x='max(0,min(iw-ow,({x})*iw-ow/2))':y=0,"
            f"scale={W}:{H}:flags=lanczos,setsar=1[v0]")


def layout() -> render.Layout:
    base = render.VERTICAL
    return dataclasses.replace(base, cap_top=config.H - base.cap_h - CAP_BOTTOM)


def render_clip(plan: dict, src: dict, opts: dict, out_dir: Path, progress=None, look: dict | None = None) -> dict:
    """Dựng clip: cắt [start, end] của nguồn, khung 9:16, tiếng gốc chuẩn hoá, hook ở trên, phụ đề ở dưới. Trả dict như
    render.render ({video, thumb, wide, duration, pieces, captions}). look: only the hook band takes the template's
    title style (the captions are the source's own words, drawn plain)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "pieces"
    work.mkdir(exist_ok=True)
    a, b = float(opts["start"]), float(opts["end"])
    dur = round(b - a, 3)
    path = Path(src["path"])
    info = delogo.probe(path)
    crop = clean_crop(opts.get("crop"), dur)
    lay = layout()
    cjk = bool(plan.get("captions")) and any(toolbox.CJK.search(e["text"]) for e in plan["captions"])
    lay = dataclasses.replace(lay, cjk=cjk)
    cues = (toolbox.burn_cues(plan["captions"], toolbox._measure(lay.cap_size, cjk), render.CAP_MAX_W, dur)
            if plan.get("captions") else [])
    (out_dir / "captions.srt").write_text(cap.to_srt(cues), encoding="utf-8")
    (out_dir / "captions.ass").write_text(cap.to_ass(cues), encoding="utf-8")
    hook = _one(opts.get("hook") if opts.get("hook") is not None else plan.get("hook"))
    sound = has_audio(path)
    inputs = ["-ss", f"{a:.3f}", "-t", f"{dur:.3f}", "-i", str(path)]
    fc, nxt, last = video_filter(crop, info["width"], info["height"]), 1, "v0"
    if hook:
        inputs += ["-loop", "1", "-t", f"{dur + 0.1:.3f}", "-i",
                   str(render.overlay_png(work / "hook.png", title=cap.fr_typography(hook), look=look))]
        fc += f";[{last}][{nxt}:v]overlay=0:0:shortest=1[v1]"
        nxt, last = nxt + 1, "v1"
    if cues:
        track = render.write_caption_track(cues, work, lay, plain=True)
        inputs += ["-f", "concat", "-safe", "0", "-i", str(track)]
        fc += f";[{nxt}:v]format=rgba[cap];[{last}][cap]overlay=0:{lay.cap_top}:eof_action=pass[v2]"
        nxt, last = nxt + 1, "v2"
    fc += f";[{last}]fps={config.FPS},format=yuv420p[v]"
    if sound:
        fc += (";[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,aformat=channel_layouts=stereo,apad[aud]")
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        fc += f";[{nxt}:a]aresample=48000,aformat=channel_layouts=stereo[aud]"
    final = out_dir / "final.mp4"
    render._run([config.ffmpeg(), "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[aud]",
                 "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(config.FPS),
                 "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(final)])
    if progress:
        progress(1, 1)
    thumb = out_dir / "thumb.jpg"
    render._run([config.ffmpeg(), "-y", "-v", "error", "-ss", f"{min(1.2, dur / 2):.2f}", "-i", str(final),
                 "-frames:v", "1", "-q:v", "3", str(thumb)])
    (out_dir / "timeline.json").write_text(json.dumps(
        [{"src": 0, "src_start": a, "dur": dur, "t0": 0.0, "still": False, "motion": "", "url": src.get("url")}],
        ensure_ascii=False, indent=1), encoding="utf-8")
    return {"video": str(final), "thumb": str(thumb), "wide": None, "duration": dur, "pieces": 1,
            "captions": len(cues)}


# ---------- trang dự án ----------
def view(proj: dict) -> dict | None:
    """Thông tin cho trang dự án clip: nguồn (đường dẫn /media), đoạn, hook, khung crop, kiểu phụ đề."""
    if not is_clip(proj):
        return None
    meta = proj.get("meta") or {}
    opts = meta.get("clip") or {}
    src = (meta.get("sources") or [None])[0]
    hook = opts.get("hook")
    return {"start": opts.get("start"), "end": opts.get("end"),
            "hook": hook if hook is not None else opts.get("hook_auto"), "hook_auto": hook is None,
            "crop": clean_crop(opts.get("crop")), "captions": opts.get("captions") or "fr",
            "source": _media(src.get("path")) if src else None,
            "duration": src.get("duration") if src else None}


def update(pid: int, data: dict) -> str | None:
    """Đổi đoạn, hook, khung crop hoặc kiểu phụ đề của một dự án clip. Trả bước nên chạy lại (script khi đổi đoạn /
    phụ đề, voice = dựng lại khi chỉ đổi hook / crop) hoặc None nếu không đổi. ValueError nếu sai."""
    p = db.get_project(pid)
    if not p or not is_clip(p):
        raise LookupError(tr("Clip project not found"))
    opts = dict(p["meta"].get("clip") or {})
    new = {**opts, **{k: v for k, v in data.items() if k in ("start", "end", "hook", "crop", "captions")}}
    src = (p["meta"].get("sources") or [None])[0]
    clean = clean_clip(new, (src or {}).get("duration"))
    new.update(clean)
    if "hook" not in data:
        new["hook"] = opts.get("hook")
    rerun = None
    if (new["start"], new["end"], new["captions"]) != (opts.get("start"), opts.get("end"), opts.get("captions")):
        rerun = "script"
    elif new["hook"] != opts.get("hook") or new["crop"] != opts.get("crop"):
        rerun = "voice"
    if rerun:
        db.update_project(pid, log=tr("Clip changed: {a}–{b}", a=clock(new["start"]), b=clock(new["end"])),
                          meta={"clip": new})
    return rerun
