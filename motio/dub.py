"""Chế độ "Lồng tiếng" (GĐ2): một video (Douyin, Bilibili, YouTube…) → bản tiếng Pháp giữ nhạc nền và tiếng động gốc.

Dùng lại các bước của pipeline:
- tải, Whisper như mọi dự án;
- kịch bản: chọn một đoạn 62–90 s (cả video nếu ngắn, Claude chọn nếu dài, hoặc đoạn người dùng đặt), Claude dịch
  từng câu gốc cho vừa chỗ của nó (tu / vous theo ai nói với ai, bảng thuật ngữ của kênh, ai đang nói);
- giọng: ElevenLabs đọc một lượt, mỗi câu đặt đúng lúc câu gốc bắt đầu (đọc nhanh tối đa 15 % nếu dài hơn chỗ),
  giọng gốc được tách khỏi nhạc nền (separate.py), rồi trộn;
- dựng: hình của đoạn đó, vùng phụ đề cũ làm mờ, phụ đề karaoke tiếng Pháp.

Nguồn ngắn hơn 62 s: thêm câu mở / kết tiếng Pháp trên khung hình đứng yên ở đầu / cuối đoạn (tối đa 24 s).
Bản lồng tiếng giữ hình và lời của người khác: chỉ tự gửi Postiz khi quyền nguồn là owned / licensed / cc
(needs_review), không thì dừng chờ duyệt video.
"""
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from . import channels, config, db, llm, render, search, separate, topic, tts
from .asr import has_audio
from .i18n import tr, tr_n

MODE = "dub"
OK_RIGHTS = ("owned", "licensed", "cc")  # quyền nguồn cho phép tự gửi Postiz
MAX_EXCERPT = 88.0  # giây hình gốc tối đa: video ≤ 90 s kể cả câu cuối đọc lố một chút
AIM = (62, 85)  # Claude chọn đoạn dài trong khoảng này
MAX_PAD = 24.0  # giây mở + kết tối đa khi nguồn ngắn
MIN_PAD = 3.0  # mỗi phần mở / kết dài ít nhất chừng này (đủ cho một câu)
MIN_SEG = 1.2  # câu gốc ngắn hơn thì gộp với câu kế
CHARS_PER_SEC = 14  # tốc độ đọc tiếng Pháp ước lượng (ký tự / giây) để Claude viết vừa chỗ
MAX_RATE = 1.15  # đọc nhanh tối đa khi câu Pháp dài hơn chỗ
GAP = 0.08  # khoảng lặng tối thiểu giữa hai câu Pháp
PIECE = 15.0  # giây mỗi mảnh hình của đoạn gốc (để báo tiến độ dựng)
CAPTION_HOLD = 1.2  # phụ đề Pháp tắt sau từ cuối chừng này giây (giữa hai câu có khoảng lặng)
BG_VOLUME = 0.8  # nhạc nền đã tách giọng
ORIG_VOLUME = 0.12  # không tách được giọng: tiếng gốc nhỏ dưới giọng Pháp
BAND_EDGE = 60  # chênh sáng giữa hai điểm ảnh liền nhau coi là nét chữ (thang 0–255)
BAND_MIN = 0.05  # tỉ lệ điểm nét chữ tối thiểu của một hàng phụ đề
BAND_W = 320  # bề ngang khung hình thu nhỏ để tìm dải phụ đề

EXCERPT_SYSTEM = "Tu choisis un extrait de vidéo à doubler en français. Réponds uniquement en JSON."
EXCERPT_PROMPT = """Vidéo : « {title} » ({duration:.0f} s). Transcription (segments [début–fin] en secondes, texte) :
{segments}

Choisis UN extrait continu de {lo} à {hi} secondes, le plus intéressant pour un public français et compréhensible
seul : il commence au début d'une phrase et finit à la fin d'une phrase (utilise les horodatages des segments).
Évite l'intro et la fin de la vidéo (salutations, appels à s'abonner).
Réponds : {{"start": s, "end": s, "why": "une phrase"}}"""

DUB_SYSTEM = """Tu adaptes en français des vidéos étrangères (surtout chinoises) pour un doublage sur une chaîne
francophone (TikTok, Reels, Shorts). Tu écris ce que les voix françaises vont dire. Tu réponds uniquement en JSON."""
DUB_PROMPT = """Vidéo : « {title} » ({platform}{uploader}), langue parlée : {language}.
Extrait doublé : {start:.1f}–{end:.1f} s de la vidéo.

Répliques d'origine (i · [début–fin] dans la vidéo finale, en secondes · place en caractères · texte) :
{segments}

Pour chaque réplique, écris la réplique française lue à sa place :
- Traduis le sens, naturellement, comme un doubleur : langue parlée, pas de mot à mot.
- Respecte la place : au plus « place » caractères, espaces compris, sinon la voix déborde sur la réplique suivante.
  Raccourcis plutôt que d'allonger. Une réplique inutile (« euh », rire) peut rester vide "".
- Tutoiement ou vouvoiement selon qui parle à qui : amis, famille, enfants → tu ; inconnus, clients, supérieurs → vous ;
  une personne qui parle à la caméra ou au public → vous. Reste cohérent d'une réplique à l'autre.
- Indique qui parle, d'après le contexte : « A », « B »… ou un rôle court (« la mère », « le vendeur »).
- Garde les noms propres ; un nom chinois s'écrit en pinyin.
- N'ajoute aucun fait absent de la vidéo.{pads}

Réponds :
{{"title_fr": "titre français (max 80 caractères)",
  "speakers": {{"A": "qui c'est, en quelques mots"}},
  "register": "tu, vous ou les deux, et pourquoi, en une phrase",
  "lines": [{{"i": 0, "speaker": "A", "text": "..."}}],{pad_keys}
  "description": "2 phrases pour la description du post, sans hashtags",
  "hashtags": ["#...", "..."]}}"""
PADS_RULE = """
- La vidéo dure moins d'une minute : ajoute « intro », une accroche lue AVANT l'extrait sur une image fixe (au plus
  {intro} caractères : ce qu'on va voir et pourquoi c'est intéressant), et « outro », lue APRÈS (au plus {outro}
  caractères : une conclusion ou une question au public)."""
PADS_KEYS = """
  "intro": "...", "outro": "...","""


def _one(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clock(sec: float) -> str:
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


# ---------- tạo dự án ----------
def clean_excerpt(start, end) -> tuple[float | None, float | None]:
    """Đoạn người dùng đặt (giây, có thể bỏ trống). ValueError nếu sai."""
    a = None if start in (None, "") else round(float(start), 2)
    b = None if end in (None, "") else round(float(end), 2)
    if (a is not None and a < 0) or (b is not None and b <= 0):
        raise ValueError(tr("The part to dub must start at 0 s or later"))
    if a is not None and b is not None:
        from . import pipeline
        if b - a > MAX_EXCERPT:
            raise ValueError(tr("The part to dub can be at most {max} s (videos last up to {video_max} s)",
                                max=f"{MAX_EXCERPT:.0f}", video_max=pipeline.MAX_SECONDS))
        if b - a < pipeline.MIN_SECONDS - MAX_PAD:
            raise ValueError(tr("The part to dub must be at least {min} s",
                                min=f"{pipeline.MIN_SECONDS - MAX_PAD:.0f}"))
    return a, b


def create(link: str, start=None, end=None, rights: str = "unknown", title: str = "") -> int:
    """Tạo dự án lồng tiếng (chưa chạy). ValueError nếu thiếu / sai dữ liệu."""
    links = search.clean_links([link])
    if len(links) != 1:
        raise ValueError(tr("Enter the link of the video to dub"))
    if rights not in topic.RIGHTS:
        raise ValueError(tr("Invalid source rights: {rights}", rights=rights))
    a, b = clean_excerpt(start, end)
    title = _one(title)[:200] or tr("Dub: {site}", site=urlparse(links[0]).hostname or "video")
    pid = db.create_project(None, title, mode=MODE)
    part = (tr(" · part {a}–{b}", a=clock(a or 0), b=clock(b) if b is not None else tr("end"))
            if a is not None or b is not None else "")
    db.update_project(pid, log=tr("Dub in French: {url}{part}", url=links[0], part=part),
                      meta={"links": links, "links_only": True, "rights": rights, "dub": {"start": a, "end": b}})
    return pid


def from_clip(cid: str) -> int:
    """Dự án lồng tiếng từ một video mới (New videos), giữ quyền của nguồn theo dõi. LookupError nếu không có."""
    c = db.get_clip(cid)
    if not c:
        raise LookupError(tr("Video not found"))
    pid = create(c["url"], rights=c.get("rights") or "unknown", title=c.get("title_fr") or c.get("title") or "")
    db.set_clip_status(cid, "used", pid)
    db.update_project(pid, log=tr("From New videos: {source} · {url}", source=c.get("watch_name") or c["site"],
                                  url=c["url"]), meta={"clip": cid})
    return pid


def needs_review(proj: dict) -> bool:
    """Bản lồng tiếng mà quyền nguồn chưa rõ: không tự gửi Postiz, dừng chờ duyệt video."""
    return proj.get("mode") == MODE and (proj.get("meta") or {}).get("rights") not in OK_RIGHTS


# ---------- kịch bản: chọn đoạn, dịch ----------
def _fmt_segments(segs: list[dict], max_chars: int = 12000) -> str:
    rows, used = [], 0
    for g in segs:
        row = f"[{g['start']:.1f}–{g['end']:.1f}] {g['text']}"
        used += len(row)
        if used > max_chars:
            rows.append("…")
            break
        rows.append(row)
    return "\n".join(rows)


def _snap(t: float, marks: list[float], within: float = 2.0) -> float:
    best = min(marks, key=lambda m: abs(m - t)) if marks else t
    return best if abs(best - t) <= within else t


def pick_excerpt(opts: dict, duration: float, segs: list[dict], title: str) -> tuple[float, float, str]:
    """(đầu, cuối, lý do) của đoạn lồng tiếng: đoạn người dùng đặt, cả video nếu ≤ MAX_EXCERPT, không thì Claude chọn
    một đoạn AIM giây bắt đầu / kết thúc ở ranh giới câu. ValueError nếu đoạn quá ngắn / dài."""
    from . import pipeline
    starts, ends = [g["start"] for g in segs], [g["end"] for g in segs]
    a0, b0 = opts.get("start"), opts.get("end")
    if a0 is not None or b0 is not None:
        a = min(max(a0 or 0.0, 0.0), duration)
        b = min(b0 if b0 is not None else a + AIM[1], duration)
        if b0 is None:  # chỉ đặt điểm bắt đầu: dừng ở cuối câu gần nhất
            b = max([e for e in ends if a + AIM[0] <= e <= b] or [b])
        why = tr("your choice")
    elif duration <= MAX_EXCERPT:
        a, b, why = 0.0, duration, tr("whole video")
    else:
        r = llm.ask_json(EXCERPT_PROMPT.format(title=title, duration=duration, segments=_fmt_segments(segs),
                                               lo=AIM[0], hi=AIM[1]), EXCERPT_SYSTEM, effort="low")
        try:
            a, b = float(r["start"]), float(r["end"])
            why = _one(r.get("why"))[:160] or tr("picked by Claude")
        except (KeyError, TypeError, ValueError):
            a, b, why = -1.0, -1.0, ""
        a, b = _snap(a, starts), _snap(b, ends)
        if not (0 <= a < b <= duration) or not AIM[0] - 2 <= b - a <= MAX_EXCERPT:
            a = starts[0] if starts[0] + AIM[0] <= duration else 0.0
            b = min(a + AIM[1] - 5, duration)
            b = max([e for e in ends if a + AIM[0] <= e <= b] or [b])
            why = tr("the start of the video (Claude's pick was unusable)")
        a = max(0.0, a - 0.15)  # vào sớm một chút để không mất âm đầu câu
        b = min(duration, b + 0.3)
    a, b = round(a, 2), round(b, 2)
    if b - a > MAX_EXCERPT:
        raise ValueError(tr("The part to dub is {n} s: at most {max} s", n=f"{b - a:.0f}", max=f"{MAX_EXCERPT:.0f}"))
    if b - a < pipeline.MIN_SECONDS - MAX_PAD:
        raise ValueError(tr("The part to dub is only {n} s: a dub needs at least {min} s of video (videos last "
                            "{lo}–{hi} s)", n=f"{b - a:.0f}", min=f"{pipeline.MIN_SECONDS - MAX_PAD:.0f}",
                            lo=pipeline.MIN_SECONDS, hi=pipeline.MAX_SECONDS))
    return a, b, why


def pads(length: float) -> tuple[float, float]:
    """Giây mở / kết để video đủ MIN_SECONDS."""
    from . import pipeline
    pad = pipeline.MIN_SECONDS + 0.5 - length
    if pad <= 0:
        return 0.0, 0.0
    half = round(max(MIN_PAD, pad / 2), 2)
    return half, half


def in_excerpt(segs: list[dict], a: float, b: float) -> list[dict]:
    """Các câu gốc có điểm giữa nằm trong [a, b], cắt mép vào trong đoạn."""
    out = []
    for g in segs:
        mid = (g["start"] + g["end"]) / 2
        if a <= mid <= b and _one(g["text"]):
            out.append({"start": max(g["start"], a), "end": min(g["end"], b), "text": _one(g["text"])})
    return out


def merge_short(segs: list[dict], min_len: float = MIN_SEG, max_gap: float = 0.4) -> list[dict]:
    """Gộp câu gốc quá ngắn với câu kế (hoặc câu trước, với câu cuối) để câu Pháp có đủ chỗ."""
    out: list[dict] = []
    for g in segs:
        if out and out[-1]["end"] - out[-1]["start"] < min_len and g["start"] - out[-1]["end"] <= max_gap:
            out[-1] = {"start": out[-1]["start"], "end": g["end"], "text": f"{out[-1]['text']} {g['text']}"}
        else:
            out.append(dict(g))
    if len(out) > 1 and out[-1]["end"] - out[-1]["start"] < min_len and out[-1]["start"] - out[-2]["end"] <= max_gap:
        last = out.pop()
        out[-1] = {"start": out[-1]["start"], "end": last["end"], "text": f"{out[-1]['text']} {last['text']}"}
    return out


def _budget(seconds: float) -> int:
    return max(6, int(seconds * CHARS_PER_SEC))


def script(proj: dict, src: dict, transcript: dict, out: Path, step) -> dict:
    """Bước kịch bản của bản lồng tiếng: chọn đoạn, tìm dải phụ đề cũ, Claude dịch. Ghi script.json, trả plan."""
    pid, meta = proj["id"], proj["meta"]
    opts = dict(meta.get("dub") or {})
    segs = [g for g in transcript.get("segments") or [] if _one(g.get("text"))]
    if not segs:
        raise RuntimeError(tr("No speech found in this video: there is nothing to dub"))
    duration = float(src.get("duration") or 0) or tts.probe_duration(Path(src["path"]))
    step("Script", 55, tr("Choosing the part to dub"))
    a, b, why = pick_excerpt(opts, duration, segs, src.get("title") or proj["title"])
    length = b - a
    pad_in, pad_out = pads(length)
    parts = merge_short(in_excerpt(segs, a, b))
    if not parts:
        raise RuntimeError(tr("No speech between {a} and {b}: pick another part to dub", a=clock(a), b=clock(b)))
    fields = {"a": clock(a), "b": clock(b), "length": f"{length:.0f}", "why": why}
    step("Script", 56, tr("Part {a}–{b} ({length} s, {why}) + {pad} s of French intro and outro",
                          pad=f"{pad_in + pad_out:.0f}", **fields) if pad_in
         else tr("Part {a}–{b} ({length} s, {why})", **fields))
    if "blur" not in opts:  # lần đầu: tìm dải phụ đề cũ; người dùng sửa / tắt trên trang dự án
        box = detect_band(Path(src["path"]), [(g["start"] + g["end"]) / 2 for g in parts])
        opts.update(blur=box, blur_auto=True)
        step("Script", 57, tr("Old subtitles found: blurring them (move or turn off the box on the project page)")
             if box else tr("No burned-in subtitles found (add a blur box on the project page if there are some)"))
    opts.update(excerpt=[a, b], pad=[pad_in, pad_out])
    db.update_project(pid, meta={"dub": opts})

    rows, slots = [], []
    for k, g in enumerate(parts):
        at = pad_in + g["start"] - a
        until = pad_in + (parts[k + 1]["start"] - a if k + 1 < len(parts) else length)
        slots.append((round(at, 2), round(until, 2), _budget(until - at)))
        rows.append(f"{k} · [{at:.1f}–{until:.1f}] · {_budget(until - at)} · {g['text']}")
    ch = channels.for_project(proj)
    b_in, b_out = _budget(pad_in - 0.5), _budget(pad_out - 0.6)
    step("Script", 58, tr("Claude is translating {lines} into French", lines=tr_n(len(parts), "line")))
    res = llm.ask_json(DUB_PROMPT.format(
        title=src.get("title") or proj["title"], platform=src.get("platform") or "video",
        uploader=f" · {src['uploader']}" if src.get("uploader") else "", language=transcript.get("language") or "?",
        start=a, end=b, segments="\n".join(rows),
        pads=PADS_RULE.format(intro=b_in, outro=b_out) if pad_in else "",
        pad_keys=PADS_KEYS if pad_in else ""), DUB_SYSTEM + channels.style_note(ch))
    res = res if isinstance(res, dict) else {}
    got: dict[int, dict] = {}
    for ln in res.get("lines") or []:
        try:
            got[int(ln["i"])] = ln
        except (KeyError, TypeError, ValueError):
            continue
    total = pad_in + length + pad_out
    lines = []
    if pad_in:
        lines.append({"kind": "intro", "text": _one(res.get("intro")), "speaker": "", "zh": "", "at": 0.25,
                      "until": round(pad_in, 2), "max_chars": b_in, "clips": []})
    for k, (g, (at, until, budget)) in enumerate(zip(parts, slots, strict=True)):
        r = got.get(k) or {}
        lines.append({"kind": "dub", "text": _one(r.get("text")), "speaker": _one(r.get("speaker"))[:40],
                      "zh": g["text"], "at": at, "until": until, "max_chars": budget, "clips": []})
    if pad_out:
        lines.append({"kind": "outro", "text": _one(res.get("outro")), "speaker": "", "zh": "",
                      "at": round(pad_in + length + 0.3, 2), "until": round(total, 2), "max_chars": b_out,
                      "clips": []})
    if not spoken(lines):
        raise RuntimeError(tr("Claude returned no French lines"))
    speakers = res.get("speakers") if isinstance(res.get("speakers"), dict) else {}
    plan = {"title_fr": _one(res.get("title_fr"))[:120] or src.get("title") or proj["title"], "lines": lines,
            "description": _one(res.get("description")),
            "hashtags": channels.merge_tags(ch, [str(t) for t in res.get("hashtags") or []]),
            "dub": {"start": a, "end": b, "pad_in": pad_in, "pad_out": pad_out, "why": why,
                    "language": transcript.get("language"), "register": _one(res.get("register"))[:200],
                    "speakers": {_one(k)[:40]: _one(v)[:120] for k, v in speakers.items()}}}
    # JSON thuần ASCII (\uXXXX): dòng gốc tiếng Trung không ghi được bằng mã hoá mặc định của Windows (cp1252)
    (out / "script.json").write_text(json.dumps(plan, ensure_ascii=True, indent=1))
    empty = sum(1 for ln in lines if not ln["text"])
    step("Script", 62, tr_n(len(spoken(lines)), "French line") + (tr(" ({n} left silent)", n=empty) if empty else "")
         + (f" · {plan['dub']['register']}" if plan["dub"]["register"] else ""), title=plan["title_fr"])
    return plan


def spoken(lines: list[dict]) -> list[dict]:
    return [ln for ln in lines if _one(ln.get("text"))]


# ---------- dải phụ đề cũ ----------
def _gray_frame(src: Path, at: float, w: int, h: int) -> np.ndarray | None:
    r = subprocess.run([config.ffmpeg(), "-v", "error", "-nostdin", "-ss", f"{at:.3f}", "-i", str(src),
                        "-frames:v", "1", "-an", "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    if r.returncode != 0 or len(r.stdout) != w * h:
        return None
    return np.frombuffer(r.stdout, np.uint8).reshape(h, w)


def find_band(frames: np.ndarray) -> list[float] | None:
    """Dải phụ đề in sẵn trên các khung hình xám [n, h, w] lấy lúc có người nói: các hàng có nhiều nét chữ sắc ở phần
    lớn các khung, bỏ những nét đứng yên suốt (logo, khung giao diện). Trả [x, y, w, h] theo tỉ lệ khung, hoặc None."""
    n, h, w = frames.shape
    if n < 3:
        return None
    strong = np.abs(np.diff(frames.astype(np.int16), axis=2)) > BAND_EDGE
    strong &= ~(strong.mean(axis=0) > 0.8)  # nét đứng yên ở hầu hết các khung: logo, không phải lời thoại
    score = np.percentile(strong.mean(axis=2), 40, axis=0)  # hàng có chữ ở ≥ 60 % số khung
    k = max(1, h // 80)
    score = np.convolve(score, np.ones(k) / k, mode="same")
    top = int(h * 0.3)  # phụ đề không nằm ở phần trên khung
    score[:top] = 0
    r = int(np.argmax(score))
    peak = float(score[r])
    if peak < BAND_MIN:
        return None
    y0 = y1 = r
    gap_max = max(3, h // 40)
    for direction in (-1, 1):  # nới lên / xuống qua các hàng đủ nét chữ, bỏ qua khe hẹp giữa hai dòng phụ đề
        y, gap = r, 0
        while top <= y + direction < h and gap <= gap_max:
            y += direction
            if score[y] > peak * 0.35:
                gap = 0
                y0, y1 = min(y0, y), max(y1, y)
            else:
                gap += 1
    band = y1 - y0 + 1
    if band > h * 0.25:  # cả mảng lớn đầy chi tiết: cảnh vật, không phải một dòng chữ
        return None
    m = max(2, round(band * 0.35))
    y0, y1 = max(0, y0 - m), min(h, y1 + 1 + m)
    return [0.03, round(y0 / h, 4), 0.94, round((y1 - y0) / h, 4)]


def detect_band(src: Path, times: list[float], n: int = 10) -> list[float] | None:
    """Tìm dải phụ đề trên n khung hình lúc có người nói. Lỗi / không thấy → None."""
    try:
        from .delogo import probe

        info = probe(src)
        w = BAND_W
        h = max(2, round(info["height"] * w / info["width"] / 2) * 2)
        picks = times if len(times) <= n else [times[round(i * (len(times) - 1) / (n - 1))] for i in range(n)]
        frames = [f for f in (_gray_frame(src, t, w, h) for t in picks) if f is not None]
        return find_band(np.stack(frames)) if len(frames) >= 3 else None
    except Exception:  # không tìm được thì không làm mờ: người dùng tự đặt khung
        return None


def clean_blur(box) -> list[float] | None:
    """Khung làm mờ từ app: [x, y, w, h] theo tỉ lệ khung, None / [] = tắt. ValueError nếu sai."""
    if not box:
        return None
    try:
        x, y, w, h = (float(v) for v in box)
    except (TypeError, ValueError):
        raise ValueError(tr("The blur box needs x, y, width and height")) from None
    x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    w, h = min(w, 1.0 - x), min(h, 1.0 - y)
    if w < 0.02 or h < 0.02:
        raise ValueError(tr("The blur box is too small"))
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


# ---------- giọng: đặt từng câu vào chỗ, tách nền, trộn ----------
def tight_spans(texts: list[str], raw: dict) -> list[tuple[float, float]]:
    """Đầu – cuối lời của từng câu trong file giọng (theo mốc từng ký tự nếu có), không kèm khoảng lặng giữa câu."""
    al = raw.get("alignment") or {}
    text = " ".join(t.strip() for t in texts)
    starts = al.get("character_start_times_seconds") or []
    ends = al.get("character_end_times_seconds") or []
    exact = len(al.get("characters") or []) == len(text) == len(starts) == len(ends)
    bare, off = [], 0
    for t, sp in zip(texts, raw["lines"], strict=True):
        n = len(t.strip())
        if exact and n:
            bare.append((float(starts[off]), float(ends[off + n - 1])))
        else:
            bare.append((float(sp["start"]), float(sp["end"])))
        off += n + 1
    out = []
    for i, (s, e) in enumerate(bare):
        lo = bare[i - 1][1] + 0.01 if i else 0.0
        hi = bare[i + 1][0] - 0.01 if i + 1 < len(bare) else float(raw["duration"])
        out.append((round(max(lo, s - 0.03, 0.0), 3), round(max(min(hi, e + 0.12), s + 0.05), 3)))
    return out


def place(slots: list[tuple[float, float]], spans: list[tuple[float, float]]) -> list[dict]:
    """Đặt từng câu: vào lúc câu gốc bắt đầu (hoặc ngay sau câu Pháp trước nếu câu đó còn đang đọc), đọc nhanh tối đa
    MAX_RATE khi dài hơn chỗ tới câu kế. slots: (lúc vào, hạn) theo giây của video; spans: (đầu, cuối) trong file
    giọng."""
    out, prev = [], -GAP
    for (at, limit), (s, e) in zip(slots, spans, strict=True):
        d = max(e - s, 0.05)
        p = max(at, prev + GAP)
        room = limit - GAP - p
        rate = min(max(d / room, 1.0), MAX_RATE) if room > 0 else MAX_RATE
        end = p + d / rate
        out.append({"at": round(p, 3), "end": round(end, 3), "rate": round(rate, 4), "src_start": s, "src_end": e})
        prev = end
    return out


def shift_alignment(texts: list[str], al: dict | None, placed: list[dict]) -> dict | None:
    """Mốc từng ký tự của file giọng → mốc trên video sau khi đặt từng câu (dời và nén theo tốc độ đọc)."""
    al = al or {}
    text = " ".join(t.strip() for t in texts)
    chars = al.get("characters") or []
    starts = al.get("character_start_times_seconds") or []
    ends = al.get("character_end_times_seconds") or []
    if not (len(chars) == len(text) == len(starts) == len(ends)) or not text:
        return None
    ns, ne, off = list(map(float, starts)), list(map(float, ends)), 0
    for t, p in zip(texts, placed, strict=True):
        n = len(t.strip())
        for j in range(off, min(off + n + 1, len(text))):  # kèm dấu cách sau câu
            ns[j] = round(p["at"] + max(float(starts[j]) - p["src_start"], 0.0) / p["rate"], 3)
            ne[j] = round(p["at"] + max(float(ends[j]) - p["src_start"], 0.0) / p["rate"], 3)
        off += n + 1
    return {"characters": chars, "character_start_times_seconds": ns, "character_end_times_seconds": ne}


def background(src: dict, out: Path, a: float, length: float, step) -> tuple[Path | None, str]:
    """Nền gốc không giọng nói của đoạn [a, a + length] (lưu lại cho lần đọc sau). Trả (file, cách):
    separated = đã tách giọng; original = không tách được, dùng tiếng gốc nhỏ; none = nguồn không có tiếng."""
    f = out / "audio" / f"background_{a:.2f}_{a + length:.2f}.wav"
    if f.is_file():
        return f, "separated"
    if not has_audio(Path(src["path"])):
        return None, "none"
    try:
        if not separate.model_ready():
            step("Voice", 66, tr("Downloading the voice separation AI model (67 MB, first dub only)"))
            separate.ensure_model()
        step("Voice", 67, tr("Separating the original voices from the music and sound effects"))
        f.parent.mkdir(parents=True, exist_ok=True)
        for old in f.parent.glob("background_*.wav"):
            old.unlink(missing_ok=True)
        part = f.with_name(f.stem + ".part.wav")
        separate.instrumental(Path(src["path"]), part, a, length)
        part.replace(f)
        return f, "separated"
    except Exception as e:
        step("Voice", 69, tr("Could not separate the original voices ({error}): keeping the original sound quietly "
                             "under the French voice", error=str(e)[:160]))
        return None, "original"


def mix(voice_audio: str, placed: list[dict], bg: Path | None, how: str, src: str, a: float, length: float,
        pad_in: float, total: float, dst: Path) -> Path:
    """Trộn các câu Pháp (đặt đúng chỗ, nén khi cần) với nền gốc (bắt đầu sau phần mở) → WAV dài đúng total."""
    n = len(placed)
    inputs = ["-i", voice_audio]
    fc = [f"[0:a]aresample=44100,aformat=channel_layouts=stereo,asplit={n}" + "".join(f"[s{k}]" for k in range(n))]
    for k, p in enumerate(placed):
        ms = round(p["at"] * 1000)
        tempo = f",atempo={p['rate']:.4f}" if p["rate"] > 1.001 else ""
        fc.append(f"[s{k}]atrim=start={p['src_start']:.3f}:end={p['src_end']:.3f},asetpts=PTS-STARTPTS{tempo},"
                  f"adelay={ms}|{ms}[v{k}]")
    fc.append("".join(f"[v{k}]" for k in range(n)) + f"amix=inputs={n}:duration=longest:normalize=0[voice]")
    if bg is not None or how == "original":
        if bg is not None:
            inputs += ["-i", str(bg)]
            vol = BG_VOLUME
        else:
            inputs += ["-ss", f"{a:.3f}", "-t", f"{length:.3f}", "-i", src]
            vol = ORIG_VOLUME
        ms = round(pad_in * 1000)
        fc.append(f"[1:a]aresample=44100,aformat=channel_layouts=stereo,volume={vol},adelay={ms}|{ms}[bg]")
        fc.append("[voice][bg]amix=inputs=2:duration=longest:normalize=0,apad[out]")
    else:
        fc.append("[voice]apad[out]")
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-nostdin", *inputs, "-filter_complex", ";".join(fc),
                        "-map", "[out]", "-t", f"{total:.3f}", "-c:a", "pcm_s16le", "-ar", "44100", str(dst)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(tr("ffmpeg could not mix the dub: {error}", error=r.stderr[-800:]))
    return dst


def voice(plan: dict, src: dict, out: Path, step, voice_id: str | None = None) -> dict:
    """Đọc các câu Pháp, đặt vào chỗ, trộn với nền gốc. Trả narration cho render (audio = bản trộn), kèm độ dài video
    (total), đoạn gốc (excerpt) và phần mở / kết (pad). RuntimeError nếu video vượt MAX_SECONDS."""
    from . import pipeline
    d = plan["dub"]
    a, b = float(d["start"]), float(d["end"])
    pad_in, pad_out = float(d.get("pad_in") or 0), float(d.get("pad_out") or 0)
    length = b - a
    lines = spoken(plan["lines"])
    if not lines:
        raise RuntimeError(tr("The dub has no French line to read"))
    texts = [_one(ln["text"]) for ln in lines]
    step("Voice", 64, tr("Generating the French voice ({lines})", lines=tr_n(len(texts), "line")))
    raw = tts.synthesize(texts, out / "audio", voice=voice_id)
    total = pad_in + length + pad_out
    slots = [(float(ln["at"]), float(lines[i + 1]["at"]) if i + 1 < len(lines) else total)
             for i, ln in enumerate(lines)]
    placed = place(slots, tight_spans(texts, raw))
    end = placed[-1]["end"] + 0.4
    if end > total:  # câu cuối đọc lố: giữ khung hình cuối thêm một chút
        pad_out, total = round(pad_out + end - total, 2), end
    if total < pipeline.MIN_SECONDS:
        pad_out, total = round(pad_out + pipeline.MIN_SECONDS - total, 2), float(pipeline.MIN_SECONDS)
    if total > pipeline.MAX_SECONDS:
        raise RuntimeError(tr("The dub would last {n} s, over {max} s: shorten the French lines or pick a shorter "
                              "part", n=f"{total:.0f}", max=pipeline.MAX_SECONDS))
    fast = sum(1 for p in placed if p["rate"] > 1.001)
    late = sum(1 for p, (at, _) in zip(placed, slots, strict=True) if p["at"] > at + 0.3)
    step("Voice", 65, tr("{voice} · {lines} placed", voice=f"{raw['provider']} · {raw['voice']}",
                         lines=tr_n(len(placed), "line"))
         + (tr(", {n} read up to {pct} % faster", n=fast, pct=round((MAX_RATE - 1) * 100)) if fast else "")
         + (tr(", {n} start late (French longer than the original)", n=late) if late else ""))
    bg, how = background(src, out, a, length, step)
    audio = mix(raw["audio"], placed, bg, how, src["path"], a, length, pad_in, total, out / "audio" / "dub_mix.wav")
    return {"audio": str(audio), "duration": placed[-1]["end"],
            "lines": [{"start": p["at"], "end": p["end"]} for p in placed],
            "alignment": shift_alignment(texts, raw.get("alignment"), placed), "provider": raw["provider"],
            "voice": raw["voice"], "model": raw.get("model"), "total": round(total, 3), "excerpt": [a, b],
            "pad": [pad_in, pad_out], "background": how}


# ---------- dựng ----------
def timeline(nar: dict) -> list[render.Piece]:
    """Các mảnh hình: khung đứng yên đầu đoạn (phần mở), đoạn gốc chia mảnh PIECE giây, khung đứng yên cuối đoạn."""
    a, b = nar["excerpt"]
    pad_in, pad_out = nar["pad"]
    length = b - a
    pieces = []
    if pad_in > 0.05:
        pieces.append(render.Piece(0, a, pad_in, 0.0, still=True))
    t, x = pad_in, 0.0
    while length - x > 0.05:
        d = min(PIECE, length - x)
        if length - x - d < 3:
            d = length - x
        pieces.append(render.Piece(0, round(a + x, 3), round(d, 3), round(t, 3)))
        t, x = t + d, x + d
    if pad_out > 0.05:
        pieces.append(render.Piece(0, max(a, b - 0.2), pad_out, round(t, 3), still=True))
    return pieces


def render_args(proj: dict, plan: dict, sources: list[dict], nar: dict) -> dict:
    """Tham số render.render cho bản lồng tiếng: các câu đã đọc, nguồn kèm vùng làm mờ, mảnh hình và độ dài định sẵn,
    tiếng nguồn tắt (nền đã nằm trong bản trộn), giọng không vào trễ, phụ đề tắt khi hết câu."""
    blur = ((proj.get("meta") or {}).get("dub") or {}).get("blur")
    return {"plan": {**plan, "lines": spoken(plan["lines"])}, "sources": [{**sources[0], "blur": blur or None}],
            "pieces": timeline(nar), "total": nar["total"], "src_volume": 0.0, "delay": 0.0,
            "caption_hold": CAPTION_HOLD}


def view(proj: dict) -> dict | None:
    """Thông tin cho trang dự án: video gốc (đường dẫn /media), đoạn đã lồng, phần mở, khung làm mờ."""
    if proj.get("mode") != MODE:
        return None
    meta = proj.get("meta") or {}
    opts = meta.get("dub") or {}
    src = (meta.get("sources") or [None])[0]
    media = None
    if src and src.get("path"):
        try:
            media = Path(src["path"]).resolve().relative_to(config.DATA.resolve()).as_posix()
        except ValueError:
            media = None
    return {"start": opts.get("start"), "end": opts.get("end"), "excerpt": opts.get("excerpt"),
            "pad": opts.get("pad"), "blur": opts.get("blur"), "blur_auto": bool(opts.get("blur_auto")),
            "source": media, "needs_review": needs_review(proj)}


def update(pid: int, data: dict) -> str | None:
    """Đổi đoạn lồng tiếng hoặc khung làm mờ từ app. Trả bước nên chạy lại (script / render) hoặc None nếu không đổi.
    ValueError nếu sai."""
    p = db.get_project(pid)
    if not p or p.get("mode") != MODE:
        raise LookupError(tr("Dub project not found"))
    opts = dict(p["meta"].get("dub") or {})
    logs, rerun = [], None
    if "blur" in data:
        box = clean_blur(data["blur"])
        if box != opts.get("blur"):
            opts.update(blur=box, blur_auto=False)
            logs.append(tr("Blur box set at {a}–{b} % of the height", a=round(box[1] * 100),
                           b=round((box[1] + box[3]) * 100)) if box else tr("Blur box turned off"))
            rerun = "render"
    if "start" in data or "end" in data:
        a, b = clean_excerpt(data.get("start", opts.get("start")), data.get("end", opts.get("end")))
        if (a, b) != (opts.get("start"), opts.get("end")):
            opts.update(start=a, end=b)
            logs.append(tr("Part to dub: {a}–{b}", a=clock(a or 0), b=clock(b) if b is not None else tr("auto"))
                        if a is not None or b is not None else tr("Part to dub: automatic"))
            rerun = "script"
    if logs:
        db.update_project(pid, log=" · ".join(logs), meta={"dub": opts})
    return rerun
