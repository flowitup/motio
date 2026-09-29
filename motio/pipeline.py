"""Pipeline: một tin NewsNow (mode news), một chủ đề / link video (mode topic) hoặc một video cần lồng tiếng (mode dub,
xem dub.py) → một video 9:16 tiếng Pháp."""
import json
import time
import traceback
from pathlib import Path

from . import asr, channels, config, db, delogo, dub, llm, postiz, render, scenes, search, topic, tts
from .i18n import tr, tr_n

PICK_SYSTEM = "Tu sélectionnes des vidéos sources pour un reportage court. Réponds uniquement en JSON."
PICK_PROMPT = """Sujet : {title_zh} / {title_fr}
Angle : {angle}

Vidéos trouvées (idx, plateforme, chaîne, durée en s, vues, titre) :
{cands}

Choisis jusqu'à {n} vidéos qui montrent le plus probablement des IMAGES de cet événement précis
(médias d'info, comptes officiels, vidéos récentes de 30 s à 10 min). Écarte les vidéos hors sujet,
les compilations anciennes, les podcasts face caméra, les vidéos d'une autre actualité.
Réponds : {{"pick": [idx, ...], "why": "une phrase"}}"""

SCRIPT_SYSTEM = """Tu es journaliste vidéo pour une chaîne francophone qui explique au public français ce qui fait
le buzz en Chine, actualité comme sujets plus légers (TikTok, Reels, Shorts). Style : clair, posé, factuel,
phrases courtes, pas de sensationnalisme. Tu réponds uniquement en JSON."""

SCRIPT_PROMPT = """Sujet tendance en Chine ({source}, {date}) : {title_zh}
Titre français proposé : {title_fr}
Angle : {angle}

Transcriptions des vidéos sources (index, plateforme, chaîne, durée, puis segments [début–fin] texte) :
{sources}

Écris un script de voix off en français de {n_min} à {n_max} lignes, {w_min}–{w_max} mots au total
(≈ {sec} secondes) :
- Ligne 1 : accroche de 14 mots maximum.
- Donne le contexte qu'un Français ne connaît pas (qui, quoi, pourquoi ça buzze en Chine),
  puis une courte analyse ou mise en perspective, et termine par une question ou une ouverture.
- Chaque ligne fait au plus 20 mots.
- N'affirme rien qui ne soit pas dans le titre ou les transcriptions. Attribue les informations
  (« selon la télévision publique chinoise… »). Reste neutre sur les sujets politiques.
- Pour chaque ligne, choisis 1 ou 2 extraits vidéo {{"src": index, "start": s, "end": s}} de 3 à 6
  secondes qui illustrent la ligne, en t'appuyant sur les horodatages. Varie les sources et
  n'utilise pas deux fois le même passage. Pour une vidéo sans parole, choisis des plages dans sa durée.

Réponds avec :
{{"title_fr": "titre final (max 80 caractères)",
  "lines": [{{"text": "...", "clips": [{{"src": 0, "start": 12.0, "end": 16.5}}]}}],
  "description": "2 phrases pour la description du post, sans hashtags",
  "hashtags": ["#Chine", "..."]}}"""


# Độ dài video: chủ dự án muốn mọi video dài ít nhất 1 phút 2 giây (TikTok Creator Rewards chỉ trả tiền cho video
# dài hơn 1 phút); Facebook Reels qua API nhận tối đa 90 giây, đây là trần cứng.
MIN_SECONDS = 62
MAX_SECONDS = 90
DEFAULT_SECONDS = 80
TOP_MARGIN = 5  # nhắm thấp hơn MAX_SECONDS: Claude viết dư ~10 từ (~4 s) vẫn không quá 90 s
TRIM_MARGIN = 1.0  # bỏ câu cho dư 1 s, vì đọc lại không dài đúng bằng tổng các câu cũ
WORDS_PER_SEC = 2.5  # ước lượng để đặt số từ cho kịch bản; sau khi có giọng đọc thì đo tốc độ thật

FIT_SYSTEM = "Tu ajustes la longueur d'un script de voix off en français. Tu réponds uniquement en JSON."
FIT_PROMPT = """Voici un script de voix off (JSON) de {now} mots. Il doit faire environ {want} mots au total
({lo}–{hi}) pour que la vidéo dure entre {min_s} et {max_s} secondes.
{how}
Garde le même style, la même accroche, la même structure JSON (title_fr, lines avec leurs clips, description,
hashtags) et des lignes de 20 mots maximum. N'invente aucun fait précis (chiffre, nom, date) absent du script.

Script :
{plan}"""
FIT_LONGER = ("Allonge-le : ajoute du contexte, une explication ou une analyse, ou une ligne de plus avec ses "
              "clips (d'autres plages des mêmes vidéos, sans répéter un passage).")
FIT_SHORTER = "Raccourcis-le : coupe ce qui est le moins important."


def target_seconds(duration_sec: int | None) -> int:
    """Độ dài nhắm tới, luôn trong [MIN_SECONDS + 8, MAX_SECONDS - TOP_MARGIN]: dự án cũ 30 / 60 s được kéo lên,
    lựa chọn 1 phút 30 nhắm 85 s cho chừa chỗ."""
    return min(max(int(duration_sec or DEFAULT_SECONDS), MIN_SECONDS + 8), MAX_SECONDS - TOP_MARGIN)


def _words(plan: dict) -> int:
    return sum(len(ln["text"].split()) for ln in plan["lines"])


def _save_script(out: Path, plan: dict) -> None:
    (out / "script.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


def _trim(plan: dict, nar: dict) -> tuple[dict, int]:
    """Bỏ câu gần cuối (giữ câu mở đầu và câu kết, còn ít nhất 3 câu) theo thời lượng từng câu đã đo, tới khi
    giọng + đuôi ≤ MAX_SECONDS. Trả (plan mới, số câu đã bỏ)."""
    lines = list(plan["lines"])
    spans = [s["end"] - s["start"] for s in nar.get("lines") or []]
    if len(spans) != len(lines):  # thiếu mốc thời gian từng câu: chia theo số từ
        total_words = max(_words(plan), 1)
        spans = [nar["duration"] * len(ln["text"].split()) / total_words for ln in lines]
    total, budget = nar["duration"], MAX_SECONDS - render.TAIL - TRIM_MARGIN
    while total > budget and len(lines) > 3:
        total -= spans.pop(-2)
        del lines[-2]
    return {**plan, "lines": lines}, len(plan["lines"]) - len(lines)


def _fit(plan: dict, want: int) -> dict:
    """Claude viết lại kịch bản cho đủ khoảng `want` từ; lỗi hay trả về ít dòng quá thì giữ bản cũ."""
    now = _words(plan)
    new = llm.ask_json(FIT_PROMPT.format(
        now=now, want=want, lo=want - 5, hi=want + 10, min_s=MIN_SECONDS, max_s=MAX_SECONDS,
        how=FIT_LONGER if want > now else FIT_SHORTER, plan=json.dumps(plan, ensure_ascii=False)), FIT_SYSTEM)
    lines = [ln for ln in (new.get("lines") if isinstance(new, dict) else None) or [] if (ln.get("text") or "").strip()]
    if len(lines) < 3:
        return plan
    return {**plan, **{k: new[k] for k in ("title_fr", "description", "hashtags") if new.get(k)}, "lines": lines}


class QuotaExceeded(RuntimeError):
    pass


def today_start() -> float:
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def quota_left(exclude: int | None = None) -> int | None:
    """Số video còn được làm hôm nay theo MAX_VIDEOS_PER_DAY; None = không giới hạn."""
    cap = config.max_videos_per_day()
    if not cap:
        return None
    return max(cap - db.count_projects_since(today_start(), exclude), 0)


def check_quota(exclude: int | None = None) -> None:
    if quota_left(exclude) == 0:
        raise QuotaExceeded(tr("Daily limit reached: {n} videos (MAX_VIDEOS_PER_DAY)", n=config.max_videos_per_day()))


class Step:
    def __init__(self, pid: int):
        self.pid = pid

    def __call__(self, step: str, pct: int, log: str | None = None, **meta):
        """`step` is an English label (STEP_LABELS, "Send to Postiz"), saved in the UI language."""
        db.update_project(self.pid, status="running", step=tr(step), pct=pct, log=log, meta=meta or None)


def _fmt_sources(sources: list[dict], transcripts: list[dict], max_chars: int = 3500) -> str:
    blocks = []
    for i, (s, t) in enumerate(zip(sources, transcripts, strict=False)):
        head = f"[{i}] {s['platform']} · {s['uploader']} · {int(s['duration'] or 0)} s · « {s['title'][:90]} »"
        segs = t.get("segments") or []
        if not segs:
            body = "(pas de parole détectée — images seulement)"
        else:
            body, used = [], 0
            for g in segs:
                line = f"[{g['start']:.1f}–{g['end']:.1f}] {g['text']}"
                used += len(line)
                if used > max_chars:
                    body.append("…")
                    break
                body.append(line)
            body = "\n".join(body)
        blocks.append(f"{head}\nlangue: {t.get('language') or '?'}\n{body}")
    return "\n\n".join(blocks)


# Các bước chạy lại được, theo thứ tự. Mỗi bước chỉ cần dữ liệu các bước trước đã lưu trong meta / thư mục dự án.
# "render": dựng lại hình với giọng đọc đã có (vd. sau khi xoá logo nguồn), không đọc lại.
STEPS = ("search", "download", "transcribe", "script", "voice", "render")
STEP_LABELS = {"search": "Find sources", "download": "Download", "transcribe": "Transcribe", "script": "Script",
               "voice": "Voice", "render": "Render"}
STEP_PCT = {"search": 5, "download": 12, "transcribe": 32, "script": 55, "voice": 64, "render": 70}
NARRATION = "narration.json"  # trong audio/: giọng đọc lần dựng trước + các câu đã đọc
# Cổng duyệt của hồ sơ kênh: dự án dừng ở trạng thái "review" (meta.review = script | video) và nhả hàng đợi.
REVIEW_STEPS = {"script": "Awaiting script approval", "video": "Awaiting video approval"}


def _subject(proj: dict) -> dict:
    """Đề tài của dự án cho các prompt: tin hot (news) hoặc chủ đề tự do (topic, đã được Claude diễn giải)."""
    if proj.get("mode") == topic.MODE:
        meta = proj["meta"]
        return {"mode": topic.MODE, "topic": meta.get("topic") or "", **(meta.get("subject") or {})}
    return {"mode": "news", **db.get_trend(proj["trend_id"])}


def _step_search(proj: dict, step, max_sources: int) -> list[dict]:
    """Link dán tay (meta.links) luôn được dùng; tự tìm trên YouTube / Bilibili lấp chỗ còn lại."""
    pid, meta = proj["id"], proj["meta"]
    if proj.get("mode") == dub.MODE:  # bản lồng tiếng: đúng một video, không tìm thêm
        pinned = [search.link_candidate(u) for u in meta.get("links") or []][:1]
        if not pinned:
            raise RuntimeError(tr("No video link to dub"))
        step("Find sources", 12, tr("Video to dub: {url}", url=pinned[0]["url"]), chosen=pinned)
        return pinned
    subj = _subject(proj)
    is_topic = subj["mode"] == topic.MODE
    if is_topic and subj["topic"] and not subj.get("keywords"):
        step("Find sources", 3, tr("Claude is interpreting the topic: {topic}", topic=subj["topic"]))
        subj.update(topic.expand(subj["topic"]))
        db.update_project(pid, log=tr("Topic: {title} · {angle}", title=subj["title_fr"], angle=subj["angle"]),
                          meta={"subject": {k: subj[k] for k in ("title_fr", "angle", "keywords")}})
    pinned = [search.link_candidate(u) for u in meta.get("links") or []]
    room = max_sources - len(pinned)
    if pinned:
        step("Find sources", 5, tr_n(len(pinned), "pasted link"))
    if meta.get("links_only") or room <= 0 or (is_topic and not subj["topic"]):
        if not pinned:
            raise RuntimeError(tr("No source links yet"))
        step("Find sources", 12, tr("Using only the {links}", links=tr_n(len(pinned), "pasted link")), chosen=pinned)
        return pinned
    kw = subj.get("keywords") or {}
    if not kw.get("zh") and not is_topic:
        kw["zh"] = [subj["title_zh"]]
    step("Find sources", 5, tr("Keywords: {keywords}", keywords=json.dumps(kw, ensure_ascii=False)))
    cands = [c for c in search.candidates(kw) if c["url"] not in {p["url"] for p in pinned}]
    if not cands and not pinned:
        raise RuntimeError(tr("No videos found for this topic") if is_topic else tr("No videos found for this story"))
    picked, why = [], tr("no search results")
    if cands:
        lines = "\n".join(f"{i} · {c['site']} · {c['uploader']} · {int(c['duration'] or 0)} · {c['views']} · "
                          f"{c['title'][:100]}" for i, c in enumerate(cands[:30]))
        if is_topic:
            prompt = topic.PICK_PROMPT.format(title=f"{subj['topic']} / {subj['title_fr']}", angle=subj["angle"],
                                              cands=lines, n=room)
            pick = llm.ask_json(prompt, topic.PICK_SYSTEM)
        else:
            pick = llm.ask_json(PICK_PROMPT.format(title_zh=subj["title_zh"], title_fr=subj["title_fr"],
                                                   angle=subj.get("angle") or "", cands=lines, n=room),
                                PICK_SYSTEM)
        picked = [cands[i] for i in pick.get("pick", []) if isinstance(i, int) and 0 <= i < len(cands)]
        picked = picked[:room] or ([] if pinned else cands[:2])
        why = pick.get("why", "")
    chosen = pinned + picked
    step("Find sources", 12, tr("{candidates}, picked {picked}", candidates=tr_n(len(cands), "candidate"),
                                picked=len(picked))
         + (f" + {tr_n(len(pinned), 'pasted link')}" if pinned else "") + f": {why}", candidates=len(cands),
         chosen=chosen)
    return chosen


def _step_download(chosen: list[dict], step) -> list[dict]:
    sources = []
    for i, c in enumerate(chosen):
        step("Download", 12 + int(20 * i / len(chosen)), tr("Downloading {url}", url=c["url"]))
        try:
            sources.append(search.download(c["url"], config.CACHE / "sources", cookies=bool(c.get("pinned"))))
        except Exception as e:
            step("Download", 12 + int(20 * i / len(chosen)),
                 tr("Skipped (download error): {error}", error=str(e)[:160]))
    if not sources:
        raise RuntimeError(tr("Could not download any source video"))
    step("Download", 32, tr("Downloaded {sources}", sources=tr_n(len(sources), "source")),
         sources=[{k: s[k] for k in ("path", "url", "id", "platform", "uploader", "uploader_url", "title",
                                     "duration", "license", "upload_date")} for s in sources])
    return sources


def _step_transcribe(sources: list[dict], step, cuts: bool = True) -> list[dict]:
    """Whisper cho từng nguồn, kèm mốc cắt cảnh (cuts=False: bản lồng tiếng giữ nguyên đoạn, không cần)."""
    transcripts, n_cuts = [], []
    for i, s in enumerate(sources):
        step("Transcribe", 32 + int(20 * i / len(sources)),
             tr("Whisper + scene cuts: {name}" if cuts else "Whisper: {name}", name=Path(s["path"]).name))
        transcripts.append(asr.transcribe(Path(s["path"])))
        n_cuts.append(len(scenes.detect(Path(s["path"]))) if cuts else None)
    done = [f"{t.get('language') or '-'}: {tr_n(len(t['segments']), 'segment')}"
            + (f", {tr_n(n, 'scene')}" if n is not None else "") for t, n in zip(transcripts, n_cuts, strict=False)]
    step("Transcribe", 52, tr("Transcribed: {done}", done=" · ".join(done)))
    return transcripts


def _step_script(proj: dict, sources: list[dict], transcripts: list[dict], out: Path, step,
                 duration_sec: int) -> dict:
    step("Script", 55, tr("Claude is writing the French narration"))
    subj = _subject(proj)
    ch = channels.for_project(proj)
    note = channels.style_note(ch)  # giọng văn của kênh, nếu có
    words = int(duration_sec * WORDS_PER_SEC)
    n_min, n_max = topic.lines_for(duration_sec)
    size = {"n_min": n_min, "n_max": n_max, "w_min": words - 15, "w_max": words + 10, "sec": duration_sec,
            "sources": _fmt_sources(sources, transcripts)}
    if subj["mode"] == topic.MODE:
        title = " / ".join(x for x in (subj["topic"], subj.get("title_fr")) if x) or topic.NO_TOPIC
        plan = llm.ask_json(topic.SCRIPT_PROMPT.format(title=title, angle=subj.get("angle") or "", **size),
                            topic.SCRIPT_SYSTEM + note)
    else:
        plan = llm.ask_json(SCRIPT_PROMPT.format(
            source=subj["source"], date=time.strftime("%d/%m/%Y"), title_zh=subj["title_zh"],
            title_fr=subj["title_fr"], angle=subj.get("angle") or "", **size), SCRIPT_SYSTEM + note)
    plan["lines"] = [ln for ln in plan.get("lines", []) if (ln.get("text") or "").strip()]
    if len(plan["lines"]) < 3:
        raise RuntimeError(tr("Script too short"))
    if _words(plan) < (MIN_SECONDS - render.TAIL) * WORDS_PER_SEC:  # chắc chắn dưới 62 s: viết dài ra trước khi đọc
        step("Script", 58, tr("Script has {words}, too short for a video ≥ {min} s: making it longer",
                              words=tr_n(_words(plan), "word"), min=MIN_SECONDS))
        plan = _fit(plan, words)
    plan["title_fr"] = plan.get("title_fr") or subj.get("title_fr") or proj["title"]
    if ch:
        plan["hashtags"] = channels.merge_tags(ch, plan.get("hashtags") or [])
    _save_script(out, plan)
    step("Script", 62, f"{tr_n(len(plan['lines']), 'line')}, {tr_n(_words(plan), 'word')}",
         title=plan["title_fr"])
    return plan


def _load_sources(pid: int) -> list[dict]:
    """Nguồn đã tải (meta.sources); file bị dời thì tìm lại trong cache theo id video."""
    sources = []
    for s in db.get_project(pid)["meta"].get("sources") or []:
        path = s.get("path")
        if not path or not Path(path).exists():
            vid = s.get("id") or s["url"].rsplit("=", 1)[-1]
            hits = sorted((config.CACHE / "sources").glob(f"*_{vid}.mp4"))
            if not hits:
                raise FileNotFoundError(tr("Source file missing: {url}", url=s["url"]))
            path = str(hits[0])
        sources.append({**s, "path": path})
    return sources


def _transcript_cached(src: dict) -> bool:
    return Path(src["path"]).with_suffix(".transcript.json").exists()


def saved_narration(pid: int) -> dict | None:
    """Giọng đọc của lần dựng trước, nếu file còn và kịch bản chưa đổi câu nào kể từ đó."""
    out = config.PROJECTS / str(pid)
    try:
        nar = json.loads((out / "audio" / NARRATION).read_text(encoding="utf-8"))
        plan = json.loads((out / "script.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if nar.get("texts") != [ln["text"] for ln in plan.get("lines") or []] or not Path(nar.get("audio", "")).is_file():
        return None
    return nar


def available_steps(pid: int) -> list[str]:
    """Các bước có thể chạy lại từ đó, theo dữ liệu dự án đã lưu."""
    meta = db.get_project(pid)["meta"]
    steps = ["search"]
    if meta.get("chosen"):
        steps.append("download")
    if meta.get("sources"):
        steps += ["transcribe", "script"]
        if (config.PROJECTS / str(pid) / "script.json").exists():
            steps.append("voice")
            if saved_narration(pid):
                steps.append("render")
    return steps


def resume_point(pid: int) -> str:
    """Bước sớm nhất còn thiếu kết quả: chỗ một dự án lỗi nên chạy tiếp."""
    steps = available_steps(pid)
    last = steps[-1]
    if last in ("script", "voice", "render"):
        try:
            sources = _load_sources(pid)
        except FileNotFoundError:  # file nguồn đã bị xoá khỏi cache: tải lại
            return "download" if "download" in steps else "search"
        if last == "script" and not all(_transcript_cached(s) for s in sources):
            return "transcribe"
    return last


def _invalidate(pid: int, start: str, redo: bool) -> None:
    """Chạy lại từ `start`: bỏ kết quả của bước đó và các bước sau để không trộn với lần chạy cũ.

    redo=False (chạy tiếp sau lỗi) giữ bản bóc lời đã xong; redo=True bóc lời lại tất cả.
    """
    out = config.PROJECTS / str(pid)
    drop = {"search": ("chosen", "candidates", "sources"), "download": ("sources",)}.get(start, ())
    if drop:
        db.update_project(pid, meta=dict.fromkeys(drop))
    if start == "transcribe" and redo:
        for s in _load_sources(pid):
            Path(s["path"]).with_suffix(".transcript.json").unlink(missing_ok=True)
    if start not in ("voice", "render"):
        (out / "script.json").unlink(missing_ok=True)


def produce(pid: int, duration_sec: int = DEFAULT_SECONDS, max_sources: int = 4, start: str = "search") -> None:
    """Chạy pipeline từ bước `start` (mặc định từ đầu) tới khi có video. meta.duration (nếu có) thắng duration_sec."""
    if start not in STEPS:
        raise ValueError(tr("Invalid step: {step}", step=start))
    step = Step(pid)
    duration_sec = target_seconds(db.get_project(pid)["meta"].get("duration") or duration_sec)
    out = config.PROJECTS / str(pid)
    out.mkdir(parents=True, exist_ok=True)
    t_begin = time.time()
    at = STEPS.index(start)
    try:
        if db.get_project(pid)["meta"].get("review"):  # chạy lại / làm tiếp: bỏ trạng thái chờ duyệt cũ
            db.update_project(pid, meta={"review": None})
        if at == 0:  # chạy lại từ bước sau không làm thêm video mới trong ngày
            check_quota(exclude=pid)
        else:
            step(STEP_LABELS[start], STEP_PCT[start], tr("Rerun from step {step}", step=tr(STEP_LABELS[start])))
        if at <= 1:
            proj = db.get_project(pid)
            chosen = _step_search(proj, step, max_sources) if at == 0 else proj["meta"]["chosen"]
            sources = _step_download(chosen, step)
        else:
            sources = _load_sources(pid)
        if at <= 3:
            proj = db.get_project(pid)
            if proj.get("mode") == dub.MODE:
                transcripts = _step_transcribe(sources[:1], step, cuts=False)
                plan = dub.script(proj, sources[0], transcripts[0], out, step)
            else:
                transcripts = _step_transcribe(sources, step)
                plan = _step_script(proj, sources, transcripts, out, step, duration_sec)
            ch = channels.for_project(db.get_project(pid))
            if ch and ch["gate_script"]:
                _await_review(pid, "script", tr("Channel {name}: awaiting your script approval before voice and "
                                                "render", name=ch["name"]))
                return
        else:
            plan = json.loads((out / "script.json").read_text(encoding="utf-8"))
        nar = None
        if start == "render" and not (nar := saved_narration(pid)):
            raise RuntimeError(tr("The previous voice is gone or the script has changed: rerun from step Voice"))
        _voice_render_post(pid, plan, sources, out, step, t_begin, duration_sec, nar)
    except Exception as e:
        db.update_project(pid, status="failed",
                          log=tr("ERROR: {error}", error=e) + f"\n{traceback.format_exc()[-1200:]}")
        raise


def add_links(pid: int, links: list[str]) -> str:
    """Thêm link nguồn vào dự án. Trả bước nên chạy lại: tải video (đã có danh sách chọn) hoặc tìm nguồn."""
    meta = db.get_project(pid)["meta"]
    links = [u for u in links if u not in (meta.get("links") or [])]
    chosen = meta.get("chosen")
    update = {"links": [*(meta.get("links") or []), *links]}
    if chosen:
        known = {c["url"] for c in chosen}
        update["chosen"] = [*chosen, *(search.link_candidate(u) for u in links if u not in known)]
    db.update_project(pid, log=tr("Added {links}", links=tr_n(len(links), "source link")), meta=update)
    return "download" if chosen else "search"


def resume(pid: int, start: str | None = None) -> None:
    """Chạy lại dự án từ `start`, hoặc từ bước bị lỗi nếu không nói rõ."""
    redo = start is not None
    try:
        start = start or resume_point(pid)
        if start not in available_steps(pid):
            raise ValueError(tr("Not enough data to rerun from step {step}", step=tr(STEP_LABELS.get(start, start))))
        _invalidate(pid, start, redo)
    except Exception as e:
        db.update_project(pid, status="failed", log=tr("ERROR: {error}", error=e))
        raise
    produce(pid, start=start)


def _voice(plan: dict, out: Path, step, duration_sec: int, voice: str | None = None) -> tuple[dict, dict]:
    """Đọc kịch bản (voice: giọng ElevenLabs của kênh, None = theo Cài đặt). Video (giọng + đuôi) ngoài
    [MIN_SECONDS, MAX_SECONDS] thì Claude chỉnh độ dài một lần, theo tốc độ đọc đo được, rồi đọc lại. Vẫn quá
    MAX_SECONDS thì bỏ câu gần cuối và đọc lại. Trả (plan, narration)."""
    step("Voice", 64, tr("Generating the French voice"))
    nar = tts.synthesize([ln["text"] for ln in plan["lines"]], out / "audio", voice=voice)
    length = nar["duration"] + render.TAIL
    step("Voice", 67, f"{nar['provider']} · {nar['voice']} · {nar['duration']:.1f} s")
    if nar["duration"] <= 0:
        return plan, nar
    if not MIN_SECONDS <= length <= MAX_SECONDS:
        want = round(_words(plan) * (duration_sec - render.TAIL) / nar["duration"])
        step("Voice", 67, tr("Video is {length} s, needs {min}–{max} s: adjusting the script to ~{words} words",
                             length=f"{length:.0f}", min=MIN_SECONDS, max=MAX_SECONDS, words=want))
        fitted = _fit(plan, want)
        if fitted is not plan:
            plan = fitted
            _save_script(out, plan)
            nar = tts.synthesize([ln["text"] for ln in plan["lines"]], out / "audio", voice=voice)
            step("Voice", 68, tr("Re-voiced: {duration} s", duration=f"{nar['duration']:.1f}"), title=plan["title_fr"])
    for _ in range(2):  # trần cứng: Facebook Reels (API) không nhận video quá 90 s
        length = nar["duration"] + render.TAIL
        if length <= MAX_SECONDS:
            break
        cut, n = _trim(plan, nar)
        if not n:
            break
        step("Voice", 69, tr("Video is {length} s, max {max} s: dropping {sentences} near the end and re-voicing",
                             length=f"{length:.0f}", max=MAX_SECONDS, sentences=tr_n(n, "sentence")))
        plan = cut
        _save_script(out, plan)
        nar = tts.synthesize([ln["text"] for ln in plan["lines"]], out / "audio", voice=voice)
        step("Voice", 69, tr("Re-voiced: {duration} s", duration=f"{nar['duration']:.1f}"))
    return plan, nar


def write_post(plan: dict, sources: list[dict], out: Path) -> str:
    """Ghi sources.txt (luôn, nội bộ) và post.txt (UTF-8: tên kênh chữ Hán, emoji). Trả phần mô tả bài đăng
    (kèm nhãn giọng AI và hashtag)."""
    credits = "\n".join(f"• {s['platform']} · {s['uploader']} — {s['url']}" for s in sources)
    (out / "sources.txt").write_text(credits + "\n", encoding="utf-8")  # luôn lưu nội bộ, không đăng
    desc = plan.get("description", "").strip()
    if config.flag("CREDIT_IN_POST"):
        desc += f"\n\nSources :\n{credits}"
    desc += f"\n\nVoix off générée par IA.\n{' '.join(plan.get('hashtags', [])[:6])}"
    (out / "post.txt").write_text(f"{plan['title_fr']}\n\n{desc}\n", encoding="utf-8")
    return desc


def _voice_render_post(pid: int, plan: dict, sources: list[dict], out: Path, step, t_begin: float,
                       duration_sec: int = DEFAULT_SECONDS, nar: dict | None = None) -> None:
    proj = db.get_project(pid)
    ch = channels.for_project(proj)
    is_dub = proj.get("mode") == dub.MODE
    voice = (ch["voice_id"] or None) if ch else None
    # 5. Giọng đọc (đủ độ dài); nar có sẵn = dựng lại với giọng đọc cũ. Bản lồng tiếng: câu đặt theo câu gốc, trộn nền.
    if nar is None:
        if is_dub:
            nar = dub.voice(plan, sources[0], out, step, voice, pool=ch["dub_voices"] if ch else [],
                            picks=(proj["meta"].get("dub") or {}).get("voices"))
            dub.remember_voices(pid, nar)
        else:
            plan, nar = _voice(plan, out, step, duration_sec, voice=voice)
        (out / "audio").mkdir(parents=True, exist_ok=True)
        (out / "audio" / NARRATION).write_text(json.dumps({**nar, "texts": [ln["text"] for ln in plan["lines"]]},
                                                          ensure_ascii=False), encoding="utf-8")
    else:
        step("Render", 70, tr("Keeping the previous voice ({voice})",
                              voice=f"{nar.get('provider')} · {nar.get('voice')} · {nar['duration']:.1f} s"))
    length = nar["duration"] + render.TAIL
    if is_dub:  # độ dài đã định ở bước giọng (dub.voice): đoạn gốc + phần mở / kết
        pass
    elif length < MIN_SECONDS:
        step("Voice", 70, tr("Voice is {length} s: extending the ending with source footage to {min} s",
                             length=f"{length:.1f}", min=MIN_SECONDS))
    elif length > MAX_SECONDS:
        step("Voice", 70, tr("Video is {length} s, still over {max} s: Facebook Reels (API) will reject it",
                             length=f"{length:.0f}", max=MAX_SECONDS))

    # 6. Dựng
    def prog(done, total):
        step("Render", 70 + int(26 * done / total), None)

    wide = bool(ch and ch["wide_postiz"])  # bản 16:9 chỉ khi kênh gửi sang kênh Postiz 16:9
    if is_dub:
        res = render.render(**dub.render_args(proj, plan, sources, nar), narration=nar, out_dir=out, progress=prog,
                            badge=channels.badge_for(proj), wide=wide)
    else:
        res = render.render(plan, sources, nar, out, progress=prog, min_total=MIN_SECONDS,
                            badge=channels.badge_for(proj), wide=wide)
    if not res.get("wide"):
        (out / "final_wide.mp4").unlink(missing_ok=True)  # bản 16:9 cũ không còn khớp video mới
    for i, miss in delogo.uncovered(pid):  # chỉ báo: xoá logo luôn do người dùng tự bấm
        spans = ", ".join(f"{delogo.clock(a)}–{delogo.clock(b)}" for a, b in miss[:4]) + ("…" if len(miss) > 4 else "")
        step("Render", 96, tr("Source #{n}: the new video also uses parts where the logo was not removed ({spans}). "
                              "Open Remove logo, click Remove logo again, then Re-render video", n=i + 1, spans=spans))

    # 7. Mô tả bài đăng
    desc = write_post(plan, sources, out)
    bg = nar.get("background") if is_dub else None
    how = (tr(" · original music and sound kept") if bg == "separated"
           else tr(" · original sound turned down") if bg == "original" else "")
    db.update_project(pid, log=tr("Rendered in {seconds} s · {clips} · {rest}", seconds=f"{time.time() - t_begin:.0f}",
                                  clips=tr_n(res["pieces"], "clip"), rest=f"{res['duration']:.1f} s video")
                      + (tr(" + 16:9 copy") if res.get("wide") else "") + how,
                      meta={"video": f"projects/{pid}/final.mp4", "thumb": f"projects/{pid}/thumb.jpg",
                            "wide": f"projects/{pid}/final_wide.mp4" if res.get("wide") else None,
                            "title": plan["title_fr"], "description": desc,
                            "hashtags": plan.get("hashtags", []), "tts": nar["provider"],
                            "voice": nar["voice"], "elapsed": round(time.time() - t_begin)})
    # 8. Chờ duyệt video, tự gửi Postiz, hoặc xong (theo hồ sơ kênh)
    _deliver(pid, ch)


def _await_review(pid: int, what: str, log: str) -> None:
    db.update_project(pid, status="review", step=tr(REVIEW_STEPS[what]), pct=62 if what == "script" else 100, log=log,
                      meta={"review": what})


def _deliver(pid: int, ch: dict | None) -> None:
    """Video vừa dựng xong. Kênh có cổng duyệt video: dừng chờ duyệt. Không có cổng mà có kênh Postiz: tự gửi. Dự án
    đã gửi Postiz rồi thì lần dựng lại sau chỉ xong (không dừng duyệt, không gửi lại); gửi lại bằng tay từ app.
    Bản lồng tiếng mà quyền nguồn chưa rõ không bao giờ tự gửi: luôn dừng chờ duyệt video."""
    proj = db.get_project(pid)
    sent = bool(proj["meta"].get("postiz"))
    held = bool(ch and ch["postiz"] and dub.needs_review(proj))
    if ch and not sent and (ch["gate_video"] or held):
        why = tr(" (a dub of someone else's video: set the source rights to owned, licensed or CC to send it without "
                 "approval)") if held and not ch["gate_video"] else ""
        _await_review(pid, "video", tr("Channel {name}: awaiting your video approval before sending to Postiz"
                                       if ch["postiz"] else "Channel {name}: awaiting your video approval",
                                       name=ch["name"]) + why)
        return
    if ch and not sent and ch["postiz"]:
        send_to_postiz(pid, ch)
    db.update_project(pid, status="done", step=tr("Done"), pct=100)


def send_to_postiz(pid: int, ch: dict) -> bool:
    """Gửi video sang các kênh Postiz của hồ sơ: nháp, giờ đăng kế tiếp của kênh, hoặc đăng ngay. Kênh Postiz đánh
    dấu 16:9 nhận bản 16:9 (thiếu bản này thì nhận bản 9:16). Lỗi chỉ ghi vào nhật ký (video vẫn xong, gửi lại bằng
    tay được). Trả True nếu mọi kênh đã được gửi."""
    Step(pid)("Send to Postiz", 99, tr("Sending to Postiz ({mode}) for channel {name}", mode=ch["send_mode"],
                                         name=ch["name"]))
    meta = db.get_project(pid)["meta"]
    wide_ids = [i for i in ch["postiz"] if i in ch["wide_postiz"]]
    tall_ids = [i for i in ch["postiz"] if i not in wide_ids]
    if wide_ids and not (meta.get("wide") and (config.DATA / meta["wide"]).is_file()):
        db.update_project(pid, log=tr("16:9 copy missing: sending the 9:16 video to every channel"))
        tall_ids, wide_ids = list(ch["postiz"]), []
    errors: list[str] = []
    try:
        when = channels.next_slot(ch, channels.taken_slots(ch["id"])) if ch["send_mode"] == "schedule" else None
    except Exception as e:  # hết giờ đăng trống…: không gửi gì
        when, errors, tall_ids, wide_ids = None, [str(e)], [], []
    for ids, version in ((tall_ids, "vertical"), (wide_ids, "wide")):
        if not ids:
            continue
        try:
            postiz.publish_project(pid, ids, ch["send_mode"], when, profile=ch["id"], version=version)
        except Exception as e:  # Postiz chưa cấu hình, mất mạng, kênh đã bị gỡ…
            errors.append(str(e))
    if errors:
        err = " · ".join(errors)[:300]
        db.update_project(pid, log=tr("Could not send to Postiz: {error}", error=err), meta={"send_error": err})
        return False
    db.update_project(pid, meta={"send_error": None})
    return True


def approve_video(pid: int, send: bool = True) -> None:
    """Duyệt video đang chờ: gửi sang Postiz theo hồ sơ kênh (send=False: chỉ duyệt, không gửi), rồi xong."""
    p = db.get_project(pid)
    if p["meta"].get("review") != "video":  # API đã đổi trạng thái sang running để khoá dự án trong lúc gửi
        raise ValueError(tr("Project is not awaiting video approval"))
    ch = channels.for_project(p)
    db.update_project(pid, log=tr("Video approved") if send else tr("Video approved, not sent to Postiz"),
                      meta={"review": None, "approved_at": time.time()})
    if send and ch and ch["postiz"]:
        send_to_postiz(pid, ch)
    db.update_project(pid, status="done", step=tr("Done"), pct=100)


def rerender(pid: int) -> None:
    """Đọc lại giọng + dựng lại từ script.json đã có (vd. sau khi thêm key ElevenLabs hoặc sửa kịch bản)."""
    produce(pid, start="voice")
