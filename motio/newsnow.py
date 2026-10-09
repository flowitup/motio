"""Tin hot từ NewsNow (github.com/ourongxing/newsnow, MIT): lấy, dịch sang Pháp, chấm điểm."""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import config, db, llm

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) motio/0.1"}

SOURCE_NAMES = {
    "douyin": "Douyin", "weibo": "Weibo", "baidu": "Baidu", "bilibili-hot-search": "Bilibili",
    "toutiao": "Toutiao", "thepaper": "The Paper", "zhihu": "Zhihu", "kuaishou": "Kuaishou",
}


def safe_id(source: str, ext: str) -> str:
    """ID dùng được trong URL: giữ nguyên nếu ngắn và an toàn, không thì băm (Baidu, Weibo dùng URL/chữ Hán)."""
    ext = str(ext)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", ext):
        ext = hashlib.md5(ext.encode()).hexdigest()[:12]
    return f"{source}:{ext}"


def fetch(source: str) -> list[dict]:
    r = httpx.get(f"{config.newsnow_url()}/api/s", params={"id": source}, headers=UA, timeout=25)
    r.raise_for_status()
    items = r.json().get("items") or []
    return [{"id": safe_id(source, it["id"]), "source": source, "ext_id": str(it["id"]),
             "title_zh": (it.get("title") or "").strip(), "url": it.get("url"), "rank": i + 1}
            for i, it in enumerate(items) if it.get("title")]


SCORE_SYSTEM = """Tu es rédacteur en chef d'une chaîne francophone (TikTok, Reels, Shorts, X) qui montre au public
français ce qui fait le buzz en Chine, sur tous les thèmes : actualité, mais aussi insolite, tech, cuisine,
voyage, nature, culture, sport, divertissement. Tu réponds uniquement en JSON."""

SCORE_PROMPT = """Voici les sujets tendance des classements chinois (NewsNow). Pour CHAQUE sujet :
- title_fr : titre français court et accrocheur, factuel, sans inventer de détails (max 90 caractères)
- score : 0–100, intérêt pour un public français ET faisabilité vidéo (images probablement disponibles
  en ligne). Un sujet léger (insolite, cuisine, animaux, tech grand public, voyage, culture, sport) vaut
  autant qu'une actualité s'il est visuel et parlant pour un Français. Baisse le score pour les sujets
  purement administratifs, les rumeurs de célébrités locales inconnues en France, ou sans images probables.
- angle : en une phrase, l'angle qui rend le sujet intéressant pour un Français
- reason : 5–12 mots expliquant le score
- keywords : mots-clés de recherche vidéo {{"zh": [2–3], "en": [1–2], "fr": [1–2]}}

Si deux sujets parlent du même événement, garde le même title_fr et donne le score complet
seulement au premier, 0 aux doublons.

Réponds avec une liste JSON d'objets {{"id", "title_fr", "score", "angle", "reason", "keywords"}}.

Sujets :
{items}"""


def refresh(sources: list[str] | None = None, per_source: int = 15) -> dict:
    """Lấy bảng hot, chỉ gửi LLM những tin chưa có trong DB. Trả về số liệu."""
    sources = sources or config.news_sources()
    known = db.known_trend_ids()
    fresh, errors = [], {}
    for s in sources:
        try:
            items = fetch(s)[:per_source]
        except Exception as e:  # nguồn lỗi không làm hỏng cả lượt
            errors[s] = str(e)[:200]
            continue
        for it in items:
            if it["id"] in known:
                db.touch_trend(it["id"], it["rank"])
            else:
                fresh.append(it)

    def score(batch: list[dict]) -> int:
        lines = "\n".join(json.dumps({"id": it["id"], "source": SOURCE_NAMES.get(it["source"], it["source"]),
                                      "rang": it["rank"], "titre": it["title_zh"]}, ensure_ascii=False)
                          for it in batch)
        result = llm.ask_json(SCORE_PROMPT.format(items=lines), SCORE_SYSTEM, effort="low", light=True)
        by_id = {r.get("id"): r for r in result if isinstance(r, dict)}
        for it in batch:
            r = by_id.get(it["id"], {})
            db.upsert_trend({**it, "title_fr": r.get("title_fr") or None, "angle": r.get("angle"),
                             "reason": r.get("reason"), "keywords": r.get("keywords"),
                             "score": int(r.get("score") or 0)})
        return len(batch)

    # Lô 20 tin, chạy song song 4 lô một lúc (mỗi lô là một lần gọi Claude)
    batches = [fresh[i:i + 20] for i in range(0, len(fresh), 20)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        scored = sum(ex.map(score, batches))
    return {"new": len(fresh), "scored": scored, "errors": errors}
