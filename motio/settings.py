"""Cài đặt người dùng: data/settings.json đè lên .env / biến môi trường.

Đọc lúc gọi (theo mtime) nên đổi trong app có hiệu lực ngay, không cần khởi động lại engine.
"""
import json
import os
import threading
from pathlib import Path

KEYS = ("LLM_PROVIDER", "LLM_MODEL", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID",
        "ELEVENLABS_MODEL", "WHISPER_MODEL", "NEWSNOW_URL", "NEWS_SOURCES", "REFRESH_EVERY_MIN", "CREDIT_ON_VIDEO",
        "CREDIT_IN_POST",
        "MAX_VIDEOS_PER_DAY", "POSTIZ_URL", "POSTIZ_API_KEY", "YTDLP_COOKIES_FROM_BROWSER", "YTDLP_COOKIES_FILE",
        "UI_LANG",
        "ELEVENLABS_USD_PER_1K_CHARS", "MONTHLY_BUDGET_USD", "SLACK_WEBHOOK_URL", "IMAGE_PROVIDER", "FAL_KEY",
        "IMAGE_STYLE", "AI_CLIP_USD_PER_SEC", "CLIP_PROVIDER", "HEYGEN_API_KEY")
SECRETS = ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "POSTIZ_API_KEY", "SLACK_WEBHOOK_URL", "FAL_KEY",
           "HEYGEN_API_KEY")
MASK = "••••"

_lock = threading.Lock()
_cache: dict = {"mtime": None, "data": {}}


def path() -> Path:
    from .config import DATA
    return DATA / "settings.json"


def load() -> dict[str, str]:
    p = path()
    try:
        mtime = p.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            _cache.update(mtime=mtime, data={k: str(v) for k, v in data.items() if k in KEYS})
        return dict(_cache["data"])


def get(key: str) -> str | None:
    """Giá trị trong settings.json nếu có, không thì biến môi trường (.env). None nếu cả hai trống."""
    val = load().get(key) if key in KEYS else None
    if val is None:
        val = os.getenv(key)
    return val


def mask(value: str) -> str:
    if not value:
        return ""
    return MASK + value[-4:] if len(value) >= 8 else MASK


def _source(key: str, overrides: dict) -> str:
    if key in overrides:
        return "settings"
    return "env" if os.getenv(key) else "default"


def public() -> dict[str, dict]:
    """Cho API: bí mật bị che, kèm nguồn của từng giá trị."""
    overrides = load()
    out = {}
    for k in KEYS:
        v = (get(k) or "").strip()
        out[k] = {"value": mask(v) if k in SECRETS else v, "secret": k in SECRETS,
                  "source": _source(k, overrides)}
    return out


def _normalize(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip()


def update(changes: dict) -> dict[str, dict]:
    """Ghi các khoá mới. Giá trị đã che (bắt đầu bằng ••••) bị bỏ qua; None xoá ghi đè (quay về .env)."""
    from .aiclips import PROVIDERS as CLIP_PROVIDERS
    from .i18n import LANGS, tr  # i18n, notify và images đọc settings: nhập muộn cho khỏi vòng lặp import
    from .images import PROVIDERS
    from .notify import valid

    unknown = [k for k in changes if k not in KEYS]
    if unknown:
        raise KeyError(tr("Unknown settings: {keys}", keys=", ".join(unknown)))
    if changes.get("UI_LANG") not in (None, "", *LANGS):
        raise ValueError(tr("UI_LANG must be one of {choices}", choices=", ".join(LANGS)))
    if changes.get("IMAGE_PROVIDER") not in (None, "", *PROVIDERS):
        raise ValueError(tr("IMAGE_PROVIDER must be one of {choices}", choices=", ".join(PROVIDERS)))
    if changes.get("CLIP_PROVIDER") not in (None, "", *CLIP_PROVIDERS):
        raise ValueError(tr("CLIP_PROVIDER must be one of {choices}", choices=", ".join(CLIP_PROVIDERS)))
    cookies = _normalize(changes.get("YTDLP_COOKIES_FILE"))
    if cookies:
        from .search import check_cookie_file
        check_cookie_file(cookies)
    hook = _normalize(changes.get("SLACK_WEBHOOK_URL"))
    if hook and not hook.startswith(MASK) and not valid(hook):
        raise ValueError(tr("SLACK_WEBHOOK_URL must be a https://hooks.slack.com/… link"))
    for k in ("MAX_VIDEOS_PER_DAY", "REFRESH_EVERY_MIN"):
        if k in changes and changes[k] not in (None, ""):
            try:
                if int(changes[k]) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError(tr("{key} must be an integer ≥ 0", key=k)) from None
    for k in ("ELEVENLABS_USD_PER_1K_CHARS", "MONTHLY_BUDGET_USD", "AI_CLIP_USD_PER_SEC"):
        if k in changes and changes[k] not in (None, ""):
            try:
                if float(changes[k]) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError(tr("{key} must be a number ≥ 0", key=k)) from None
    data = load()
    for k, v in changes.items():
        v = _normalize(v)
        if v is not None and v.startswith(MASK):
            continue
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    p = path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    with _lock:
        _cache["mtime"] = None
    return public()
