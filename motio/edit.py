"""Sửa và xoá dự án từ app: đọc / lưu kịch bản (script.json) rồi dựng lại, xoá dự án cùng thư mục của nó.
Bản lồng tiếng (dub.py) chỉ sửa được lời từng câu: mỗi câu Pháp gắn với một câu gốc, không thêm / bớt câu."""
import json
import re
import shutil
import time
from pathlib import Path

from . import config, db, dub, pipeline, render, tts
from .i18n import tr, tr_n

BUSY = ("queued", "running")
MIN_LINES = 3  # như pipeline: kịch bản dưới 3 dòng là quá ngắn
MAX_LINES = 40
MAX_TITLE = 100
MAX_LINE_CHARS = 400
MAX_DESC = 1500
MAX_TAGS = 10  # bài đăng chỉ dùng 6 hashtag đầu
MAX_CLIPS = 4
DUB_FIELDS = ("kind", "speaker", "zh", "at", "until", "max_chars")  # trường riêng của mỗi câu lồng tiếng


class Busy(RuntimeError):
    """Dự án đang chạy: chưa sửa / xoá được."""


def _dir(pid: int) -> Path:
    return config.PROJECTS / str(pid)


def _project(pid: int) -> dict:
    p = db.get_project(pid)
    if not p:
        raise LookupError(tr("Project #{id} not found", id=pid))
    return p


def _idle(p: dict) -> None:
    if p["status"] in BUSY:
        raise Busy(tr("Project is running: wait until it finishes, then try again"))


def _read(pid: int) -> dict:
    f = _dir(pid) / "script.json"
    if not f.exists():
        raise FileNotFoundError(tr("Project has no script yet"))
    try:
        plan = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(tr("script.json is corrupt: {error}", error=e)) from e
    if not isinstance(plan, dict) or not isinstance(plan.get("lines"), list):
        raise ValueError(tr("script.json is corrupt: the lines list is missing"))
    return plan


def _write(pid: int, plan: dict) -> None:
    f = _dir(pid) / "script.json"
    f.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


def _words(lines: list[dict]) -> int:
    return sum(len(ln["text"].split()) for ln in lines)


def _one_line(text) -> str:
    """Gộp xuống dòng / khoảng trắng thừa thành một dấu cách; giữ NBSP của kiểu chữ Pháp."""
    return re.sub(r"[ \t\r\n]+", " ", str(text or "")).strip()


def _clips(raw) -> list[dict]:
    """Đoạn hình của một dòng {src, start, end}; bỏ mục sai (render tự lấp hình cho dòng không có đoạn nào)."""
    out = []
    for c in raw if isinstance(raw, list) else []:
        try:
            start = float(c["start"])
            out.append({"src": int(c["src"]), "start": start, "end": float(c.get("end", start + 4))})
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out[:MAX_CLIPS]


def _tags(raw) -> list[str]:
    """Hashtag từ danh sách hoặc chuỗi cách nhau bằng dấu cách / phẩy; thêm #, bỏ trùng."""
    items = [raw] if isinstance(raw, str) else [str(x) for x in raw or []]
    tags, seen = [], set()
    for w in " ".join(items).replace(",", " ").split():
        w = "#" + w.lstrip("#")
        if len(w) > 1 and w.lower() not in seen:
            seen.add(w.lower())
            tags.append(w[:60])
    return tags[:MAX_TAGS]


def _post_fields(raw: dict) -> dict:
    """Tiêu đề, mô tả, hashtag gửi từ app. ValueError nếu không dùng được."""
    title = _one_line(raw.get("title_fr"))
    if not title:
        raise ValueError(tr("Title can't be empty"))
    if len(title) > MAX_TITLE:
        raise ValueError(tr("Title can be at most {n} characters", n=MAX_TITLE))
    desc = str(raw.get("description") or "").strip()
    if len(desc) > MAX_DESC:
        raise ValueError(tr("Description can be at most {n} characters", n=MAX_DESC))
    return {"title_fr": title, "description": desc, "hashtags": _tags(raw.get("hashtags"))}


def clean(raw: dict) -> dict:
    """Kịch bản gửi từ app → {title_fr, lines, description, hashtags}. ValueError nếu không dùng được."""
    post = _post_fields(raw)
    lines = []
    for ln in raw.get("lines") or []:
        ln = ln if isinstance(ln, dict) else {"text": ln}
        text = _one_line(ln.get("text"))
        if not text:  # dòng để trống thì bỏ
            continue
        if len(text) > MAX_LINE_CHARS:
            raise ValueError(tr("Line {line} is longer than {n} characters", line=len(lines) + 1, n=MAX_LINE_CHARS))
        lines.append({"text": text, "clips": _clips(ln.get("clips"))})
    if len(lines) < MIN_LINES:
        raise ValueError(tr("The script needs at least {n} narration lines", n=MIN_LINES))
    if len(lines) > MAX_LINES:
        raise ValueError(tr("The script can have at most {n} lines", n=MAX_LINES))
    return {**post, "lines": lines}


def clean_dub(raw: dict, old: dict) -> dict:
    """Bản lồng tiếng: lời mới của từng câu (cùng số câu; lúc vào, câu gốc… giữ nguyên), tiêu đề, mô tả, hashtag.
    Câu để trống thì không đọc. ValueError nếu không dùng được."""
    post = _post_fields(raw)
    new = raw.get("lines") or []
    if len(new) != len(old["lines"]):
        raise ValueError(tr("A dub keeps one French line per original line: lines can't be added or removed"))
    lines = []
    for i, (o, n) in enumerate(zip(old["lines"], new, strict=True)):
        text = _one_line(n.get("text") if isinstance(n, dict) else n)
        if len(text) > MAX_LINE_CHARS:
            raise ValueError(tr("Line {line} is longer than {n} characters", line=i + 1, n=MAX_LINE_CHARS))
        lines.append({**(o if isinstance(o, dict) else {}), "text": text, "clips": []})
    if not any(ln["text"] for ln in lines):
        raise ValueError(tr("The dub needs at least one French line"))
    return {**post, "lines": lines}


def _narration(pid: int) -> Path | None:
    hits = [p for p in (_dir(pid) / "audio").glob("narration.*") if p.suffix in (".mp3", ".wav")]
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def _measured_rate(pid: int, plan: dict) -> float | None:
    """Tốc độ đọc thật (từ / giây) của lần đọc gần nhất, khi script.json hiện tại chính là bản đã được đọc."""
    audio, script = _narration(pid), _dir(pid) / "script.json"
    if not audio or not script.exists() or audio.stat().st_mtime < script.stat().st_mtime:
        return None
    try:
        sec = tts.probe_duration(audio)
        rate = _words([{"text": _one_line(ln.get("text"))} for ln in plan["lines"]]) / sec
    except Exception:  # không có ffprobe, file hỏng, dòng sai kiểu…: dùng tốc độ đã lưu / mặc định
        return None
    return rate if 1.0 <= rate <= 5.0 else None


def script_view(pid: int) -> dict:
    """Kịch bản cho trình sửa trong app, kèm số liệu để ước lượng độ dài video (62–90 s)."""
    p = _project(pid)
    plan = _read(pid)
    is_dub = p.get("mode") == dub.MODE
    rate = _measured_rate(pid, plan) or p["meta"].get("speech_rate") or pipeline.WORDS_PER_SEC
    final = _dir(pid) / "final.mp4"
    edited = p["meta"].get("edited_at")
    return {
        "script": {
            "title_fr": str(plan.get("title_fr") or ""),
            "lines": [{"text": str(ln.get("text") or "") if isinstance(ln, dict) else str(ln),
                       "clips": _clips(ln.get("clips")) if isinstance(ln, dict) else [],
                       **({k: ln.get(k) for k in DUB_FIELDS} if is_dub and isinstance(ln, dict) else {})}
                      for ln in plan["lines"]],
            "description": str(plan.get("description") or ""),
            "hashtags": _tags(plan.get("hashtags")),
        },
        "edited_at": edited,
        # video dựng trước lần sửa (lệch 1 s vì đồng hồ mtime của hệ thống file thô hơn time.time())
        "stale": bool(edited and final.exists() and edited > final.stat().st_mtime + 1),
        "words_per_sec": round(rate, 3),
        "min_seconds": pipeline.MIN_SECONDS,
        "max_seconds": pipeline.MAX_SECONDS,
        "tail": render.TAIL,
        "version": (_dir(pid) / "script.json").stat().st_mtime,
        # bản lồng tiếng: ai nói, tu / vous; mỗi dòng kèm câu gốc (zh), lúc vào / hạn (giây) và số ký tự vừa chỗ
        "dub": {k: (plan.get("dub") or {}).get(k) for k in ("register", "speakers", "language")} if is_dub else None,
    }


def save_script(pid: int, raw: dict) -> dict:
    """Lưu kịch bản đã sửa. Đổi tiêu đề / lời bình thì video cần dựng lại (bước Giọng đọc và dựng);
    đổi mô tả / hashtag của video đã xong thì post.txt cập nhật ngay, không cần dựng."""
    p = _project(pid)
    _idle(p)
    old = _read(pid)
    new = clean_dub(raw, old) if p.get("mode") == dub.MODE else clean(raw)
    old_lines = [ln if isinstance(ln, dict) else {"text": ln} for ln in old["lines"]]
    parts = []
    if new["title_fr"] != _one_line(old.get("title_fr")):
        parts.append(tr("title"))
    if [ln["text"] for ln in new["lines"]] != [_one_line(ln.get("text")) for ln in old_lines]:
        parts.append(tr("narration ({lines}, {words})", lines=tr_n(len(new["lines"]), "line"),
                        words=tr_n(_words(new["lines"]), "word")))
    elif [ln["clips"] for ln in new["lines"]] != [_clips(ln.get("clips")) for ln in old_lines]:
        parts.append(tr("clips"))
    on_video = bool(parts)
    if new["description"] != str(old.get("description") or "").strip():
        parts.append(tr("description"))
    if new["hashtags"] != _tags(old.get("hashtags")):
        parts.append(tr("hashtags"))
    if not parts:
        return script_view(pid)  # không đổi gì

    meta = {"title": new["title_fr"]}
    rate = _measured_rate(pid, old)  # đo trước khi ghi đè: bản cũ là bản đã được đọc
    if rate:
        meta["speech_rate"] = round(rate, 3)
    if on_video:
        meta["edited_at"] = time.time()
    _write(pid, {**old, **new})
    if p["status"] == "done":
        meta["description"] = pipeline.write_post(new, p["meta"].get("sources") or [], _dir(pid))
        meta["hashtags"] = new["hashtags"]
    stale = on_video and p["status"] == "done"
    db.update_project(pid, log=tr("Script edited: {parts} · re-render to update the video" if stale
                                  else "Script edited: {parts}", parts=", ".join(parts)), meta=meta)
    return script_view(pid)


def delete(pid: int) -> None:
    """Xoá dự án: thư mục data/projects/<id>/ rồi dòng trong SQLite. Giữ cache video nguồn (dự án khác có thể dùng).

    Không xoá được thư mục (file đang mở…) thì giữ dự án để thử lại.
    """
    p = _project(pid)
    _idle(p)
    folder = _dir(pid)
    if folder.exists():
        try:
            shutil.rmtree(folder)
        except OSError as e:
            raise OSError(tr("Could not delete the project folder ({error}). Close any open files and try again.",
                             error=e.strerror or e)) from e
    if not db.delete_project(pid):
        raise Busy(tr("The project was just restarted: wait until it finishes, then try again"))
