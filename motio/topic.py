"""Chế độ "Chủ đề": video giải thích tiếng Pháp về một chủ đề bất kỳ hoặc từ link video, không cần tin hot."""
from urllib.parse import urlparse

from . import db, llm, search

MODE = "topic"
RIGHTS = ("unknown", "owned", "licensed", "cc")  # quyền dùng video nguồn; chưa rõ = unknown
DURATIONS = (30, 60, 90)

SUBJECT_SYSTEM = "Tu prépares une courte vidéo explicative en français. Réponds uniquement en JSON."
SUBJECT_PROMPT = """Sujet proposé (dans n'importe quelle langue) : {topic}

Donne :
- title_fr : titre français court et accrocheur, factuel, sans inventer de détails (max 80 caractères)
- angle : en une phrase, ce qui rend le sujet intéressant pour un public français
- keywords : mots-clés de recherche vidéo {{"zh": [1–2], "en": [1–2], "fr": [1]}} (le chinois sert à chercher
  sur Bilibili, l'anglais et le français sur YouTube)
Réponds : {{"title_fr": "...", "angle": "...", "keywords": {{"zh": [], "en": [], "fr": []}}}}"""

PICK_SYSTEM = "Tu sélectionnes des vidéos sources pour une courte vidéo explicative. Réponds uniquement en JSON."
PICK_PROMPT = """Sujet : {title}
Angle : {angle}

Vidéos trouvées (idx, plateforme, chaîne, durée en s, vues, titre) :
{cands}

Choisis jusqu'à {n} vidéos dont les IMAGES illustrent le mieux ce sujet (vidéos nettes de 30 s à 20 min, avec
de l'action ou des plans variés). Écarte les vidéos hors sujet, les podcasts face caméra et les diaporamas.
Réponds : {{"pick": [idx, ...], "why": "une phrase"}}"""

SCRIPT_SYSTEM = """Tu es créateur de vidéos explicatives pour une chaîne francophone (TikTok, Reels, Shorts), sur
tous les sujets : société, tech, science, cuisine, voyage, nature, culture, sport, insolite… Style : clair,
vivant, précis, phrases courtes, sans sensationnalisme. Tu réponds uniquement en JSON."""

SCRIPT_PROMPT = """Sujet : {title}
Angle : {angle}

Transcriptions des vidéos sources (index, plateforme, chaîne, durée, puis segments [début–fin] texte) :
{sources}

Écris un script de voix off en français de {n_min} à {n_max} lignes, {w_min}–{w_max} mots au total
(≈ {sec} secondes) :
- Ligne 1 : accroche de 14 mots maximum.
- Ne te contente pas de décrire ou de traduire les vidéos : explique ce qu'on voit, donne le contexte qu'un
  Français ne connaît pas, compare, apporte une analyse ou une astuce. C'est ce qui rend la vidéo originale.
- Termine par une question ou une ouverture.
- Chaque ligne fait au plus 20 mots.
- Tu peux ajouter des connaissances générales bien établies, mais n'invente aucun fait précis (chiffre, nom,
  date, citation) absent des transcriptions. Attribue ce qui vient des vidéos (« dans cette vidéo… »).
- Pour chaque ligne, choisis 1 ou 2 extraits vidéo {{"src": index, "start": s, "end": s}} de 3 à 6
  secondes qui illustrent la ligne, en t'appuyant sur les horodatages. Varie les sources et
  n'utilise pas deux fois le même passage. Pour une vidéo sans parole, choisis des plages dans sa durée.

Réponds avec :
{{"title_fr": "titre final (max 80 caractères)",
  "lines": [{{"text": "...", "clips": [{{"src": 0, "start": 12.0, "end": 16.5}}]}}],
  "description": "2 phrases pour la description du post, sans hashtags",
  "hashtags": ["#...", "..."]}}"""

NO_TOPIC = "à déduire des vidéos ci-dessous"


def expand(topic: str) -> dict:
    """Chủ đề tự do → tiêu đề tiếng Pháp, góc nhìn, từ khoá tìm video (ZH cho Bilibili, EN/FR cho YouTube)."""
    r = llm.ask_json(SUBJECT_PROMPT.format(topic=topic), SUBJECT_SYSTEM, effort="low")
    r = r if isinstance(r, dict) else {}
    kw = r.get("keywords") if isinstance(r.get("keywords"), dict) else {}
    kw = {k: [str(q) for q in kw.get(k) or [] if str(q).strip()][:2] for k in ("zh", "en", "fr")}
    if not any(kw.values()):
        kw["en"] = [topic]
    return {"title_fr": str(r.get("title_fr") or topic)[:120], "angle": str(r.get("angle") or ""), "keywords": kw}


def lines_for(duration_sec: int) -> tuple[int, int]:
    """Số dòng kịch bản theo độ dài: 30 s → 4–5, 60 s → 7–11, 90 s → 11–16."""
    return max(4, round(duration_sec / 8.5)), max(5, round(duration_sec / 5.5))


def create(topic: str = "", links: list[str] | None = None, links_only: bool = False, duration: int = 60,
           rights: str = "unknown") -> int:
    """Tạo dự án chủ đề (chưa chạy). Không có chủ đề thì chỉ dùng link. ValueError nếu thiếu / sai dữ liệu."""
    topic = " ".join(topic.split())[:300]
    links = search.clean_links(links or [])
    if not topic and not links:
        raise ValueError("Nhập chủ đề hoặc ít nhất một link video")
    if duration not in DURATIONS:
        raise ValueError(f"Độ dài phải là {', '.join(map(str, DURATIONS))} giây")
    if rights not in RIGHTS:
        raise ValueError(f"Quyền nguồn không hợp lệ: {rights}")
    title = topic
    if not title:
        more = f" (+{len(links) - 1})" if len(links) > 1 else ""
        title = f"Video từ {urlparse(links[0]).hostname or 'link'}{more}"
    pid = db.create_project(None, title, mode=MODE)
    db.update_project(pid, log=f"Chủ đề: {topic or '(chỉ link)'} · {len(links)} link · {duration} s",
                      meta={"topic": topic, "links": links, "links_only": bool(links_only or not topic),
                            "duration": duration, "rights": rights})
    return pid
