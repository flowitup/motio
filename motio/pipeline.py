"""Pipeline: một tin NewsNow (mode news) hoặc một chủ đề / link video (mode topic) → một video 9:16 tiếng Pháp."""
import json
import time
import traceback
from pathlib import Path

from . import asr, config, db, llm, render, scenes, search, topic, tts

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


class QuotaExceeded(RuntimeError):
    pass


def _today_start() -> float:
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def quota_left(exclude: int | None = None) -> int | None:
    """Số video còn được làm hôm nay theo MAX_VIDEOS_PER_DAY; None = không giới hạn."""
    cap = config.max_videos_per_day()
    if not cap:
        return None
    return max(cap - db.count_projects_since(_today_start(), exclude), 0)


def check_quota(exclude: int | None = None) -> None:
    if quota_left(exclude) == 0:
        raise QuotaExceeded(f"Đã đủ {config.max_videos_per_day()} video hôm nay (MAX_VIDEOS_PER_DAY)")


class Step:
    def __init__(self, pid: int):
        self.pid = pid

    def __call__(self, step: str, pct: int, log: str | None = None, **meta):
        db.update_project(self.pid, status="running", step=step, pct=pct, log=log, meta=meta or None)


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
STEPS = ("search", "download", "transcribe", "script", "voice")
STEP_LABELS = {"search": "Tìm nguồn", "download": "Tải video", "transcribe": "Bóc lời", "script": "Kịch bản",
               "voice": "Giọng đọc"}
STEP_PCT = {"search": 5, "download": 12, "transcribe": 32, "script": 55, "voice": 64}


def _subject(proj: dict) -> dict:
    """Đề tài của dự án cho các prompt: tin hot (news) hoặc chủ đề tự do (topic, đã được Claude diễn giải)."""
    if proj.get("mode") == topic.MODE:
        meta = proj["meta"]
        return {"mode": topic.MODE, "topic": meta.get("topic") or "", **(meta.get("subject") or {})}
    return {"mode": "news", **db.get_trend(proj["trend_id"])}


def _step_search(proj: dict, step, max_sources: int) -> list[dict]:
    """Link dán tay (meta.links) luôn được dùng; tự tìm trên YouTube / Bilibili lấp chỗ còn lại."""
    pid, meta = proj["id"], proj["meta"]
    subj = _subject(proj)
    is_topic = subj["mode"] == topic.MODE
    if is_topic and subj["topic"] and not subj.get("keywords"):
        step("Tìm nguồn", 3, f"Claude diễn giải chủ đề: {subj['topic']}")
        subj.update(topic.expand(subj["topic"]))
        db.update_project(pid, log=f"Chủ đề: {subj['title_fr']} · {subj['angle']}",
                          meta={"subject": {k: subj[k] for k in ("title_fr", "angle", "keywords")}})
    pinned = [search.link_candidate(u) for u in meta.get("links") or []]
    room = max_sources - len(pinned)
    if pinned:
        step("Tìm nguồn", 5, f"{len(pinned)} link dán tay")
    if meta.get("links_only") or room <= 0 or (is_topic and not subj["topic"]):
        if not pinned:
            raise RuntimeError("Chưa có link nguồn nào")
        step("Tìm nguồn", 12, f"Chỉ dùng {len(pinned)} link dán tay", chosen=pinned)
        return pinned
    kw = subj.get("keywords") or {}
    if not kw.get("zh") and not is_topic:
        kw["zh"] = [subj["title_zh"]]
    step("Tìm nguồn", 5, f"Từ khoá: {json.dumps(kw, ensure_ascii=False)}")
    cands = [c for c in search.candidates(kw) if c["url"] not in {p["url"] for p in pinned}]
    if not cands and not pinned:
        raise RuntimeError("Không tìm thấy video nào cho " + ("chủ đề này" if is_topic else "tin này"))
    picked, why = [], "không có kết quả tự tìm"
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
    step("Tìm nguồn", 12, f"{len(cands)} ứng viên, chọn {len(picked)}"
         + (f" + {len(pinned)} link dán tay" if pinned else "") + f": {why}", candidates=len(cands), chosen=chosen)
    return chosen


def _step_download(chosen: list[dict], step) -> list[dict]:
    sources = []
    for i, c in enumerate(chosen):
        step("Tải video", 12 + int(20 * i / len(chosen)), f"Tải {c['url']}")
        try:
            sources.append(search.download(c["url"], config.CACHE / "sources", cookies=bool(c.get("pinned"))))
        except Exception as e:
            step("Tải video", 12 + int(20 * i / len(chosen)), f"Bỏ qua (lỗi tải): {str(e)[:160]}")
    if not sources:
        raise RuntimeError("Không tải được video nguồn nào")
    step("Tải video", 32, f"Đã tải {len(sources)} nguồn",
         sources=[{k: s[k] for k in ("path", "url", "id", "platform", "uploader", "uploader_url", "title",
                                     "duration", "license", "upload_date")} for s in sources])
    return sources


def _step_transcribe(sources: list[dict], step) -> list[dict]:
    transcripts, n_cuts = [], []
    for i, s in enumerate(sources):
        step("Bóc lời", 32 + int(20 * i / len(sources)), f"Whisper + cắt cảnh: {Path(s['path']).name}")
        transcripts.append(asr.transcribe(Path(s["path"])))
        n_cuts.append(len(scenes.detect(Path(s["path"]))))
    done = [f"{t.get('language') or '-'}:{len(t['segments'])} đoạn, {n} cảnh"
            for t, n in zip(transcripts, n_cuts, strict=False)]
    step("Bóc lời", 52, "Xong bóc lời: " + " · ".join(done))
    return transcripts


def _step_script(proj: dict, sources: list[dict], transcripts: list[dict], out: Path, step,
                 duration_sec: int) -> dict:
    step("Kịch bản", 55, "Claude viết lời bình tiếng Pháp")
    subj = _subject(proj)
    words = int(duration_sec * 2.5)
    n_min, n_max = topic.lines_for(duration_sec)
    size = {"n_min": n_min, "n_max": n_max, "w_min": words - 20, "w_max": words + 10, "sec": duration_sec,
            "sources": _fmt_sources(sources, transcripts)}
    if subj["mode"] == topic.MODE:
        title = " / ".join(x for x in (subj["topic"], subj.get("title_fr")) if x) or topic.NO_TOPIC
        plan = llm.ask_json(topic.SCRIPT_PROMPT.format(title=title, angle=subj.get("angle") or "", **size),
                            topic.SCRIPT_SYSTEM)
    else:
        plan = llm.ask_json(SCRIPT_PROMPT.format(
            source=subj["source"], date=time.strftime("%d/%m/%Y"), title_zh=subj["title_zh"],
            title_fr=subj["title_fr"], angle=subj.get("angle") or "", **size), SCRIPT_SYSTEM)
    plan["lines"] = [ln for ln in plan.get("lines", []) if (ln.get("text") or "").strip()]
    if len(plan["lines"]) < 3:
        raise RuntimeError("Kịch bản quá ngắn")
    plan["title_fr"] = plan.get("title_fr") or subj.get("title_fr") or proj["title"]
    (out / "script.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    step("Kịch bản", 62, f"{len(plan['lines'])} dòng, {sum(len(l['text'].split()) for l in plan['lines'])} từ",
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
                raise FileNotFoundError(f"Mất file nguồn {s['url']}")
            path = str(hits[0])
        sources.append({**s, "path": path})
    return sources


def _transcript_cached(src: dict) -> bool:
    return Path(src["path"]).with_suffix(".transcript.json").exists()


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
    return steps


def resume_point(pid: int) -> str:
    """Bước sớm nhất còn thiếu kết quả: chỗ một dự án lỗi nên chạy tiếp."""
    steps = available_steps(pid)
    last = steps[-1]
    if last in ("script", "voice"):
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
    if start != "voice":
        (out / "script.json").unlink(missing_ok=True)


def produce(pid: int, duration_sec: int = 60, max_sources: int = 4, start: str = "search") -> None:
    """Chạy pipeline từ bước `start` (mặc định từ đầu) tới khi có video. meta.duration (nếu có) thắng duration_sec."""
    if start not in STEPS:
        raise ValueError(f"Bước không hợp lệ: {start}")
    step = Step(pid)
    duration_sec = db.get_project(pid)["meta"].get("duration") or duration_sec
    out = config.PROJECTS / str(pid)
    out.mkdir(parents=True, exist_ok=True)
    t_begin = time.time()
    at = STEPS.index(start)
    try:
        if at == 0:  # chạy lại từ bước sau không làm thêm video mới trong ngày
            check_quota(exclude=pid)
        else:
            step(STEP_LABELS[start], STEP_PCT[start], f"Chạy lại từ bước {STEP_LABELS[start]}")
        if at <= 1:
            proj = db.get_project(pid)
            chosen = _step_search(proj, step, max_sources) if at == 0 else proj["meta"]["chosen"]
            sources = _step_download(chosen, step)
        else:
            sources = _load_sources(pid)
        if at <= 3:
            transcripts = _step_transcribe(sources, step)
            plan = _step_script(db.get_project(pid), sources, transcripts, out, step, duration_sec)
        else:
            plan = json.loads((out / "script.json").read_text())
        _voice_render_post(pid, plan, sources, out, step, t_begin)
    except Exception as e:
        db.update_project(pid, status="failed", log=f"LỖI: {e}\n{traceback.format_exc()[-1200:]}")
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
    db.update_project(pid, log=f"Thêm {len(links)} link nguồn", meta=update)
    return "download" if chosen else "search"


def resume(pid: int, start: str | None = None) -> None:
    """Chạy lại dự án từ `start`, hoặc từ bước bị lỗi nếu không nói rõ."""
    redo = start is not None
    try:
        start = start or resume_point(pid)
        if start not in available_steps(pid):
            raise ValueError(f"Chưa đủ dữ liệu để chạy lại từ bước {STEP_LABELS.get(start, start)}")
        _invalidate(pid, start, redo)
    except Exception as e:
        db.update_project(pid, status="failed", log=f"LỖI: {e}")
        raise
    produce(pid, start=start)


def _voice_render_post(pid: int, plan: dict, sources: list[dict], out: Path, step, t_begin: float) -> None:
    # 5. Giọng đọc
    step("Giọng đọc", 64, "Tạo giọng đọc tiếng Pháp")
    nar = tts.synthesize([ln["text"] for ln in plan["lines"]], out / "audio")
    step("Giọng đọc", 70, f"{nar['provider']} · {nar['voice']} · {nar['duration']:.1f} s")

    # 6. Dựng
    def prog(done, total):
        step("Dựng", 70 + int(26 * done / total), None)

    res = render.render(plan, sources, nar, out, progress=prog)

    # 7. Mô tả bài đăng
    credits = "\n".join(f"• {s['platform']} · {s['uploader']} — {s['url']}" for s in sources)
    (out / "sources.txt").write_text(credits + "\n")  # luôn lưu nội bộ, không đăng
    desc = plan.get("description", "").strip()
    if config.flag("CREDIT_IN_POST"):
        desc += f"\n\nSources :\n{credits}"
    desc += f"\n\nVoix off générée par IA.\n{' '.join(plan.get('hashtags', [])[:6])}"
    (out / "post.txt").write_text(f"{plan['title_fr']}\n\n{desc}\n")
    db.update_project(pid, status="done", step="Xong", pct=100,
                      log=f"Xong trong {time.time() - t_begin:.0f} s · {res['pieces']} đoạn · "
                          f"{res['duration']:.1f} s video",
                      meta={"video": f"projects/{pid}/final.mp4", "thumb": f"projects/{pid}/thumb.jpg",
                            "title": plan["title_fr"], "description": desc,
                            "hashtags": plan.get("hashtags", []), "tts": nar["provider"],
                            "voice": nar["voice"], "elapsed": round(time.time() - t_begin)})


def rerender(pid: int) -> None:
    """Đọc lại giọng + dựng lại từ script.json đã có (vd. sau khi thêm key ElevenLabs hoặc sửa kịch bản)."""
    produce(pid, start="voice")
