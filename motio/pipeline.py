"""Pipeline "Tin nóng": một tin NewsNow → một video 9:16 tiếng Pháp."""
import json
import time
import traceback
from pathlib import Path

from . import asr, config, db, llm, render, search, tts

PICK_SYSTEM = "Tu sélectionnes des vidéos sources pour un reportage court. Réponds uniquement en JSON."
PICK_PROMPT = """Sujet : {title_zh} / {title_fr}
Angle : {angle}

Vidéos trouvées (idx, plateforme, chaîne, durée en s, vues, titre) :
{cands}

Choisis jusqu'à {n} vidéos qui montrent le plus probablement des IMAGES de cet événement précis
(médias d'info, comptes officiels, vidéos récentes de 30 s à 10 min). Écarte les vidéos hors sujet,
les compilations anciennes, les podcasts face caméra, les vidéos d'une autre actualité.
Réponds : {{"pick": [idx, ...], "why": "une phrase"}}"""

SCRIPT_SYSTEM = """Tu es journaliste vidéo pour une chaîne francophone qui explique l'actualité chinoise
au public français (TikTok, Reels, Shorts). Style : clair, posé, factuel, phrases courtes, pas de
sensationnalisme. Tu réponds uniquement en JSON."""

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


class Step:
    def __init__(self, pid: int):
        self.pid = pid

    def __call__(self, step: str, pct: int, log: str | None = None, **meta):
        db.update_project(self.pid, status="running", step=step, pct=pct, log=log, meta=meta or None)


def _fmt_sources(sources: list[dict], transcripts: list[dict], max_chars: int = 3500) -> str:
    blocks = []
    for i, (s, t) in enumerate(zip(sources, transcripts)):
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


def produce(pid: int, duration_sec: int = 60, max_sources: int = 4) -> None:
    step = Step(pid)
    proj = db.get_project(pid)
    trend = db.get_trend(proj["trend_id"])
    out = config.PROJECTS / str(pid)
    out.mkdir(parents=True, exist_ok=True)
    t_begin = time.time()
    try:
        # 1. Tìm nguồn
        kw = trend.get("keywords") or {}
        if not kw.get("zh"):
            kw["zh"] = [trend["title_zh"]]
        step("Tìm nguồn", 5, f"Từ khoá: {json.dumps(kw, ensure_ascii=False)}")
        cands = search.candidates(kw)
        if not cands:
            raise RuntimeError("Không tìm thấy video nào cho tin này")
        lines = "\n".join(f"{i} · {c['site']} · {c['uploader']} · {int(c['duration'] or 0)} · {c['views']} · "
                          f"{c['title'][:100]}" for i, c in enumerate(cands[:30]))
        pick = llm.ask_json(PICK_PROMPT.format(title_zh=trend["title_zh"], title_fr=trend["title_fr"],
                                               angle=trend.get("angle") or "", cands=lines, n=max_sources),
                            PICK_SYSTEM)
        chosen = [cands[i] for i in pick.get("pick", []) if isinstance(i, int) and 0 <= i < len(cands)]
        chosen = chosen[:max_sources] or cands[:2]
        step("Tìm nguồn", 12, f"{len(cands)} ứng viên, chọn {len(chosen)}: {pick.get('why', '')}",
             candidates=len(cands))

        # 2. Tải video
        sources = []
        for i, c in enumerate(chosen):
            step("Tải video", 12 + int(20 * i / len(chosen)), f"Tải {c['url']}")
            try:
                sources.append(search.download(c["url"], config.CACHE / "sources"))
            except Exception as e:
                step("Tải video", 12 + int(20 * i / len(chosen)), f"Bỏ qua (lỗi tải): {str(e)[:160]}")
        if not sources:
            raise RuntimeError("Không tải được video nguồn nào")
        step("Tải video", 32, f"Đã tải {len(sources)} nguồn",
             sources=[{k: s[k] for k in ("path", "url", "id", "platform", "uploader", "uploader_url", "title",
                                         "duration", "license", "upload_date")} for s in sources])

        # 3. Bóc lời
        transcripts = []
        for i, s in enumerate(sources):
            step("Bóc lời", 32 + int(20 * i / len(sources)), f"Whisper: {Path(s['path']).name}")
            transcripts.append(asr.transcribe(Path(s["path"])))
        step("Bóc lời", 52, "Xong bóc lời: " + ", ".join(
            f"{t.get('language') or '-'}:{len(t['segments'])} đoạn" for t in transcripts))

        # 4. Kịch bản
        step("Kịch bản", 55, "Claude viết lời bình tiếng Pháp")
        words = int(duration_sec * 2.5)
        plan = llm.ask_json(SCRIPT_PROMPT.format(
            source=trend["source"], date=time.strftime("%d/%m/%Y"), title_zh=trend["title_zh"],
            title_fr=trend["title_fr"], angle=trend.get("angle") or "", sources=_fmt_sources(sources, transcripts),
            n_min=7, n_max=11, w_min=words - 20, w_max=words + 10, sec=duration_sec), SCRIPT_SYSTEM)
        plan["lines"] = [ln for ln in plan.get("lines", []) if (ln.get("text") or "").strip()]
        if len(plan["lines"]) < 3:
            raise RuntimeError("Kịch bản quá ngắn")
        plan.setdefault("title_fr", trend["title_fr"])
        (out / "script.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
        step("Kịch bản", 62, f"{len(plan['lines'])} dòng, {sum(len(l['text'].split()) for l in plan['lines'])} từ",
             title=plan["title_fr"])

        _voice_render_post(pid, plan, sources, out, step, t_begin)
    except Exception as e:
        db.update_project(pid, status="failed", log=f"LỖI: {e}\n{traceback.format_exc()[-1200:]}")
        raise


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
    if config.CREDIT_IN_POST:
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
    step = Step(pid)
    out = config.PROJECTS / str(pid)
    plan = json.loads((out / "script.json").read_text())
    sources = []
    for s in db.get_project(pid)["meta"].get("sources", []):
        path = s.get("path")
        if not path or not Path(path).exists():
            vid = s.get("id") or s["url"].rsplit("=", 1)[-1]
            hits = sorted((config.CACHE / "sources").glob(f"*_{vid}.mp4"))
            if not hits:
                raise FileNotFoundError(f"Mất file nguồn {s['url']}")
            path = str(hits[0])
        sources.append({**s, "path": path})
    try:
        _voice_render_post(pid, plan, sources, out, step, time.time())
    except Exception as e:
        db.update_project(pid, status="failed", log=f"LỖI: {e}\n{traceback.format_exc()[-1200:]}")
        raise
