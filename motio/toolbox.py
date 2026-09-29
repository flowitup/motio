"""Công cụ lẻ, không cần dự án: tải video, bóc lời, dịch phụ đề, đọc văn bản, ghi phụ đề lên video.

Mỗi lần chạy là một job: thư mục data/tools/jobs/<id>/ gồm in/ (file tải lên), out/ (kết quả) và state.json.
Kết quả của job này dùng làm đầu vào của job khác (file_job / subs_job): tải → bóc lời → dịch → ghi lên video.
Việc nặng chạy trên executor của engine (api.py), ở đây chỉ có logic; lỗi ghi vào state.json để app hiện.
"""
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw

from . import asr, captions, channels, config, delogo, llm, render, search, tts
from .i18n import tr, tr_n

JOBS = config.DATA / "tools" / "jobs"
KINDS = ("download", "transcribe", "translate", "speak", "burn")
BUSY = ("queued", "running")
VIDEO_EXT = delogo.VIDEO_EXT
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus")
SUBS_EXT = (".srt", ".vtt")
MAX_MEDIA = delogo.MAX_UPLOAD
MAX_SUBS = 2 * 1024 * 1024
MAX_ENTRIES = 1500  # số câu phụ đề tối đa khi dịch
MAX_TEXT = 5000  # ký tự tối đa cho một lần đọc (một lần gọi ElevenLabs)
HEIGHTS = (480, 720, 1080)
LANGS = {"fr": "French (France)", "en": "English", "vi": "Vietnamese"}
SIZES = {"small": 0.038, "medium": 0.048, "large": 0.058}  # cỡ chữ phụ đề / cạnh ngắn của khung hình
BATCH = 40  # số câu phụ đề gửi Claude một lượt
CJK = re.compile("[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")  # kana, Hán, Hangul
_PUNCT = ",;:.!?…，。！？；、"
_TAGS = re.compile(r"<[^>]+>|\{\\[^}]*\}")
_STAMP = (r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_ARROW = re.compile(_STAMP + r"\s*-->\s*" + _STAMP)

_CANCEL: dict[str, threading.Event] = {}
_LOCK = threading.Lock()


class NotFound(LookupError):
    """Không có job (hoặc file của job) này."""


class Busy(RuntimeError):
    """Job đang chạy: chưa xoá được."""


class Cancelled(RuntimeError):
    """Người dùng dừng job."""


# ---------- trạng thái job ----------
def _dir(job_id: str) -> Path:
    d = JOBS / (job_id if re.fullmatch(r"[0-9a-f]{32}", job_id or "") else "-")
    if not d.is_dir():
        raise NotFound(tr("Job not found"))
    return d


def _state(d: Path) -> dict:
    for attempt in range(5):
        try:
            return json.loads((d / "state.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):  # Windows: đọc đúng lúc job nền đang thay file thì lỗi quyền một chốc
            if attempt == 4:
                return {}
            time.sleep(0.05)
    return {}


def _save(d: Path, **changes) -> dict:
    """Ghi file tạm rồi thay: job nền ghi trong lúc app đang đọc, không để ai thấy state.json dở dang."""
    with _LOCK:
        st = {**_state(d), **changes}
        tmp = d / f"state.{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        for attempt in range(5):
            try:
                tmp.replace(d / "state.json")
                break
            except PermissionError:  # Windows: file đang được đọc thì chưa thay được
                if attempt == 4:
                    raise
                time.sleep(0.05)
    return st


def _rel(path: Path) -> str:
    return path.resolve().relative_to(config.DATA.resolve()).as_posix()


def view(st: dict) -> dict:
    """Job như app thấy (không kèm params). folder: thư mục kết quả trên máy chạy engine (để mở ra)."""
    return {**{k: st.get(k) for k in ("id", "kind", "title", "status", "pct", "message", "error", "outputs",
                                      "created_at", "finished_at")}, "folder": str(JOBS / str(st.get("id")) / "out")}


def get(job_id: str) -> dict:
    return view(_state(_dir(job_id)))


def list_jobs(limit: int = 40) -> list[dict]:
    if not JOBS.is_dir():
        return []
    out = []
    for d in JOBS.iterdir():
        st = _state(d) if re.fullmatch(r"[0-9a-f]{32}", d.name) else {}
        if st.get("id"):
            out.append(view(st))
    return sorted(out, key=lambda j: j.get("created_at") or 0, reverse=True)[:limit]


def recover() -> int:
    """Lúc engine khởi động: job dở dang (engine tắt giữa chừng) được đánh dấu lỗi. Trả số job."""
    n = 0
    for j in list_jobs(1000):
        if j["status"] in BUSY:
            d = JOBS / j["id"]
            _save(d, status="failed", error=tr("Interrupted: the engine was restarted"), finished_at=time.time())
            shutil.rmtree(d / "work", ignore_errors=True)
            n += 1
    return n


def cancel(job_id: str) -> dict:
    d = _dir(job_id)
    st = _state(d)
    if st.get("status") not in BUSY:
        return view(st)
    _CANCEL.setdefault(job_id, threading.Event()).set()
    return get(job_id)


def delete(job_id: str) -> None:
    d = _dir(job_id)
    if _state(d).get("status") in BUSY:
        raise Busy(tr("The job is still running: stop it first"))
    shutil.rmtree(d)


# ---------- tạo job ----------
def _clean_name(name: str, fallback: str) -> str:
    stem = re.sub(r"[^\w.\- ]+", "_", Path(name or "").stem).strip(" ._")[:60]
    return stem or fallback


def _upload(d: Path, field: str, name: str, stream, exts: tuple[str, ...], limit: int) -> tuple[str, str]:
    """Lưu file tải lên (từng khúc) thành in/<field><đuôi>. Trả (đường dẫn tương đối, tên gốc)."""
    base = Path(name or field).name
    ext = Path(base).suffix.lower()
    if ext not in exts:
        raise ValueError(tr("Unsupported file type. Use one of: {types}", types=", ".join(exts)))
    dest = d / "in" / f"{field}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as f:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            if size > limit:
                raise ValueError(tr("File too large (max {n} MB)", n=limit >> 20))
            f.write(chunk)
    if not size:
        raise ValueError(tr("The file is empty"))
    return _rel(dest), base[:200]


def _from_job(job_id: str, kinds: tuple[str, ...], missing: str) -> tuple[str, str]:
    """Đường dẫn (tương đối) và tên của file kết quả đầu tiên thuộc `kinds` của một job đã xong."""
    st = _state(_dir(job_id))
    if st.get("status") != "done":
        raise ValueError(tr("That job has not finished yet"))
    for o in st.get("outputs") or []:
        if o.get("kind") in kinds and (config.DATA / o["path"]).is_file():
            return o["path"], o["name"]
    raise ValueError(missing)


def _sources(kind: str) -> list[tuple]:
    """Đầu vào file của từng công cụ: (ô, khoá job trước, đuôi file, loại kết quả nhận, lời nhắc chưa chọn, lời báo
    job trước không có, dung lượng tối đa)."""
    media = (*VIDEO_EXT, *AUDIO_EXT)
    subs = ("subs", "subs_job", SUBS_EXT, ("subtitles",), tr("Choose a subtitle file first"),
            tr("That job has no subtitles"), MAX_SUBS)
    return {
        "transcribe": [("file", "file_job", media, ("video", "audio"), tr("Choose a video or audio file first"),
                        tr("That job has no video or audio file"), MAX_MEDIA)],
        "translate": [subs],
        "burn": [("file", "file_job", VIDEO_EXT, ("video",), tr("Choose a video first"), tr("That job has no video"),
                  MAX_MEDIA), subs],
    }.get(kind, [])


def _take(d: Path, params: dict, files: dict, spec: tuple) -> None:
    """Điền params[ô] (+ names[ô]) từ file tải lên hoặc từ kết quả của job trước. ValueError nếu thiếu."""
    field, job_key, exts, kinds, need, missing, limit = spec
    if files.get(field):
        name, stream = files[field]
        params[field], params["names"][field] = _upload(d, field, name, stream, exts, limit)
    elif params.get(job_key):
        params[field], params["names"][field] = _from_job(params[job_key], kinds, missing)
    else:
        raise ValueError(need)


def _validate(kind: str, params: dict) -> dict:
    """Kiểm tra và chuẩn hoá phần chữ của yêu cầu, trước khi tạo thư mục hay nhận file."""
    p = {"names": {}}
    if kind == "download":
        links = search.clean_links([params.get("url") or ""])
        if not links:
            raise ValueError(tr("Paste a video link first"))
        height = int(params.get("height") or 720)
        if height not in HEIGHTS:
            raise ValueError(tr("Quality must be one of {choices}", choices=", ".join(str(h) for h in HEIGHTS)))
        p.update(url=links[0], height=height)
    elif kind == "translate":
        lang = params.get("language") or "fr"
        if lang not in LANGS:
            raise ValueError(tr("Language must be one of {choices}", choices=", ".join(LANGS)))
        channel = params.get("channel")
        if channel:
            try:
                channels.pick(int(channel))
            except LookupError as e:
                raise ValueError(str(e)) from e
        p.update(language=lang, channel=int(channel) if channel else None)
    elif kind == "speak":
        text = re.sub(r"[ \t]+", " ", str(params.get("text") or "")).strip()
        if not text:
            raise ValueError(tr("Type or paste the text to read first"))
        if len(text) > MAX_TEXT:
            raise ValueError(tr("The text can have at most {n} characters", n=MAX_TEXT))
        if tts.provider() is None:
            raise tts.TTSUnavailable(tr("No ElevenLabs API key. Go to Settings → enter ELEVENLABS_API_KEY "
                                        "(the macOS voice only works on a Mac)."))
        p.update(text=text, voice=str(params.get("voice") or "")[:100])
    elif kind == "burn":
        size = params.get("size") or "medium"
        if size not in SIZES:
            raise ValueError(tr("Size must be one of {choices}", choices=", ".join(SIZES)))
        p.update(size=size)
    elif kind != "transcribe":
        raise NotFound(tr("Unknown tool: {kind}", kind=kind))
    for k in ("file_job", "subs_job"):
        if params.get(k):
            p[k] = str(params[k])
    return p


def start(kind: str, params: dict, files: dict, submit: Callable) -> dict:
    """Tạo job và giao cho `submit(fn)` chạy nền. files: {"file"|"subs": (tên gốc, stream)}.
    ValueError nếu yêu cầu không dùng được (không để lại thư mục nào)."""
    if kind not in KINDS:
        raise NotFound(tr("Unknown tool: {kind}", kind=kind))
    p = _validate(kind, params)
    job_id = uuid.uuid4().hex
    d = JOBS / job_id
    d.mkdir(parents=True)
    try:
        for spec in _sources(kind):
            _take(d, p, files, spec)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    names = p["names"]
    title = {"download": p.get("url"), "speak": (p.get("text") or "").replace("\n", " ")[:60],
             "translate": f"{names.get('subs', '')} → {p.get('language')}"}.get(kind) or names.get("file", "")
    st = _save(d, id=job_id, kind=kind, title=title, status="queued", pct=0, message=tr("Waiting to start…"),
               error=None, outputs=[], params=p, created_at=time.time(), finished_at=None)
    _CANCEL[job_id] = threading.Event()
    submit(lambda: run(job_id))
    return view(st)


# ---------- chạy job ----------
class Job:
    """Ngữ cảnh của một lần chạy: thư mục, tham số, báo tiến độ và điểm dừng."""

    def __init__(self, d: Path, params: dict, stop: threading.Event):
        self.dir, self.params, self._stop = d, params, stop
        self.out = d / "out"
        self.out.mkdir(exist_ok=True)
        self._last = -1

    def check(self) -> None:
        if self._stop.is_set():
            raise Cancelled(tr("Stopped"))

    def progress(self, pct: float | None = None, message: str | None = None) -> None:
        self.check()
        change = {}
        if pct is not None and int(pct) != self._last:
            self._last = change["pct"] = int(min(max(pct, 0), 99))
        if message is not None:
            change["message"] = message
        if change:
            _save(self.dir, **change)

    def path(self, field: str) -> Path:
        return config.DATA / self.params[field]

    def name(self, field: str) -> str:
        return self.params["names"].get(field, field)

    def output(self, path: Path, kind: str) -> dict:
        return {"name": path.name, "path": _rel(path), "kind": kind}


def run(job_id: str) -> None:
    """Chạy job. Dọn thư mục tạm rồi mới ghi trạng thái cuối, để job đã "xong / lỗi / dừng" xoá được ngay."""
    d = JOBS / job_id
    st = _state(d)
    stop = _CANCEL.setdefault(job_id, threading.Event())
    failure = None
    try:
        if stop.is_set():
            raise Cancelled(tr("Stopped"))
        _save(d, status="running", pct=0, message=tr("Starting…"))
        job = Job(d, st["params"], stop)
        outputs, message = RUNNERS[st["kind"]](job)
        job.check()
        end = {"status": "done", "pct": 100, "message": message, "outputs": outputs}
    except Cancelled:
        end = {"status": "cancelled", "message": tr("Stopped")}
    except Exception as e:
        failure = e
        end = {"status": "failed", "error": str(e)[:800] or type(e).__name__}
    shutil.rmtree(d / "work", ignore_errors=True)
    _CANCEL.pop(job_id, None)
    _save(d, finished_at=time.time(), **end)
    if failure:
        raise failure


def _write(path: Path, text: str) -> None:
    """UTF-8 và xuống dòng \\n trên mọi hệ điều hành (Windows không đổi thành \\r\\n)."""
    path.write_text(text, encoding="utf-8", newline="\n")


# ---------- phụ đề: đọc, ghi, cắt ----------
def _secs(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def parse_subs(text: str) -> list[dict]:
    """SRT hoặc WebVTT → [{start, end, text}]. Bỏ thẻ định dạng; câu rỗng bị bỏ. ValueError nếu không có câu nào."""
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            m = _ARROW.search(ln)
            if not m:
                continue
            g = m.groups()
            body = "\n".join(t for t in (_TAGS.sub("", x).strip() for x in lines[i + 1:]) if t)
            if body:
                out.append({"start": _secs(*g[:4]), "end": _secs(*g[4:]), "text": body})
            break
    if not out:
        raise ValueError(tr("No subtitles found in this file"))
    return sorted(out, key=lambda e: e["start"])


def format_srt(entries: list[dict]) -> str:
    cues = [captions.Cue(e["start"], e["end"],
                         [[captions.Word(t, e["start"], e["end"])] for t in e["text"].split("\n")])
            for e in entries]
    return captions.to_srt(cues)


def _units(text: str) -> tuple[list[str], str]:
    """Tách chữ thành từ (chữ có dấu cách) hoặc từng ký tự (có chữ Trung / Nhật / Hàn), kèm chuỗi nối lại.
    Chỉ tách ở dấu cách thường: khoảng trắng không ngắt của kiểu chữ Pháp giữ nguyên."""
    if CJK.search(text):
        return list(text), ""
    return [u for u in text.split(" ") if u], " "


def _cut(text: str, limit: int) -> list[str]:
    """Cắt câu dài thành các đoạn ≤ limit ký tự: ưu tiên sau dấu câu khi đoạn đã dài chừng 60 %, còn lại ở dấu cách
    (chữ Trung, Nhật, Hàn thì cắt theo ký tự)."""
    units, sep = _units(text)
    out, cur = [], []
    for u in units:
        if cur and len(sep.join([*cur, u])) > limit:
            out.append(sep.join(cur))
            cur = []
        cur.append(u)
        if len(sep.join(cur)) >= limit * 0.6 and u[-1:] in _PUNCT:
            out.append(sep.join(cur))
            cur = []
    if cur:
        out.append(sep.join(cur))
    return [o.strip() for o in out if o.strip()]


def _two_lines(text: str, limit: int) -> str:
    """Đoạn dài hơn một dòng thì ngắt đôi gần giữa (ở dấu cách nếu có)."""
    if len(text) <= limit:
        return text
    mid = len(text) // 2
    spaces = [i for i, c in enumerate(text) if c == " "]
    at = min(spaces, key=lambda i: abs(i - mid)) if spaces else mid
    return f"{text[:at].strip()}\n{text[at:].strip()}"


def segment_entries(segments: list[dict], cjk: bool = False) -> list[dict]:
    """Câu của Whisper (có thể dài cả chục giây) → câu phụ đề ≤ 2 dòng; thời gian chia theo số ký tự."""
    limit = 16 if cjk else captions.MAX_CHARS
    out = []
    for s in segments:
        parts = _cut(" ".join(str(s["text"]).split()), limit * captions.MAX_LINES)
        total = sum(len(p) for p in parts) or 1
        a, span, done = float(s["start"]), max(float(s["end"]) - float(s["start"]), 0.1), 0
        for p in parts:
            start = a + span * done / total
            done += len(p)
            out.append({"start": round(start, 3), "end": round(a + span * done / total, 3),
                        "text": _two_lines(p, limit)})
    return out


# ---------- tải video ----------
def _download(job: Job) -> tuple[list[dict], str]:
    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            pct = 5 + 90 * (d.get("downloaded_bytes") or 0) / total if total else None
            job.progress(pct)

    job.progress(2, tr("Downloading…"))
    info = search.download(job.params["url"], job.out, job.params["height"], cookies=True, hooks=[hook])
    _save(job.dir, title=info.get("title") or job.params["url"])
    path = Path(info["path"])
    where = " · ".join(x for x in (info.get("platform"), info.get("uploader")) if x)
    return [job.output(path, "video")], tr("Downloaded: {info}", info=where or path.name)


# ---------- bóc lời ----------
def _transcribe(job: Job) -> tuple[list[dict], str]:
    src = job.path("file")
    job.progress(5, tr("Transcribing: this can take a few minutes…"))
    res = asr.transcribe(src)
    entries = segment_entries(res.get("segments") or [], cjk=(res.get("language") or "") in ("zh", "ja", "ko"))
    if not entries:
        raise ValueError(tr("No speech found in this file"))
    stem = _clean_name(job.name("file"), "transcript")
    srt, txt = job.out / f"{stem}.srt", job.out / f"{stem}.txt"
    _write(srt, format_srt(entries))
    _write(txt, "\n".join(" ".join(e["text"].split()) for e in entries) + "\n")
    return ([job.output(srt, "subtitles"), job.output(txt, "text")],
            tr("Transcribed ({lang}): {n}", lang=res.get("language") or "?", n=tr_n(len(entries), "subtitle")))


# ---------- dịch phụ đề ----------
def _translate_prompt(items: list[dict], before: list[str]) -> str:
    return json.dumps({"context_before": before, "subtitles": items}, ensure_ascii=False)


def _translate_batch(items: list[dict], before: list[str], system: str) -> list[str]:
    """Dịch một loạt câu; Claude trả sai số câu thì chia đôi loạt và dịch lại từng nửa (một câu vẫn sai thì báo lỗi)."""
    try:
        res = llm.ask_json(_translate_prompt(items, before), system)
        lines = res.get("lines") if isinstance(res, dict) else res
        if isinstance(lines, list) and len(lines) == len(items) and all(isinstance(x, str) for x in lines):
            return [x.strip() for x in lines]
    except llm.LLMError:
        if len(items) == 1:
            raise
    if len(items) == 1:
        raise llm.LLMError(tr("The translation came back in the wrong shape"))
    mid = len(items) // 2
    rest_before = [i["text"] for i in items[max(mid - 3, 0):mid]]
    return _translate_batch(items[:mid], before, system) + _translate_batch(items[mid:], rest_before, system)


def _system(lang: str, channel: dict | None) -> str:
    return (f"You are a professional subtitle translator. Translate every subtitle into {LANGS[lang]}.\n"
            "- Keep the meaning, tone, names and numbers; add nothing and drop nothing.\n"
            "- Keep each translation about as long as the original so it can be read in the time shown.\n"
            "- Return exactly one string per input subtitle, in the same order; never merge or split subtitles. "
            "Use \\n for a line break only when the original has one and it reads naturally.\n"
            "- `context_before` holds the previous subtitles (original language), for context only: "
            "do not translate them.\n"
            'Reply with JSON only: {"lines": ["…", "…"]}' + channels.style_note(channel))


def translate(entries: list[dict], lang: str, channel: dict | None = None,
              progress: Callable[[int, int], None] | None = None) -> list[dict]:
    """Dịch từng loạt ≤ BATCH câu (giữ mốc thời gian). Tiếng Pháp: áp chính tả Pháp (dấu cách không ngắt, « »)."""
    system = _system(lang, channel)
    out: list[dict] = []
    for i in range(0, len(entries), BATCH):
        batch = entries[i:i + BATCH]
        items = [{"n": i + k + 1, "text": e["text"]} for k, e in enumerate(batch)]
        before = [e["text"] for e in entries[max(i - 3, 0):i]]
        for e, t in zip(batch, _translate_batch(items, before, system), strict=True):
            t = t or e["text"]
            if lang == "fr":
                t = "\n".join(captions.fr_typography(ln) for ln in t.split("\n"))
            out.append({"start": e["start"], "end": e["end"], "text": t})
        if progress:
            progress(len(out), len(entries))
    return out


def _translate(job: Job) -> tuple[list[dict], str]:
    src = job.path("subs")
    entries = parse_subs(decode(src.read_bytes()))
    if len(entries) > MAX_ENTRIES:
        raise ValueError(tr("At most {n} subtitles per file", n=MAX_ENTRIES))
    lang = job.params["language"]
    channel = channels.pick(job.params["channel"]) if job.params.get("channel") else None
    job.progress(3, tr("Translating {n}…", n=tr_n(len(entries), "subtitle")))
    done = translate(entries, lang, channel,
                     lambda a, b: job.progress(3 + 95 * a / b, tr("Translated {done} of {total}", done=a, total=b)))
    dest = job.out / f"{_clean_name(job.name('subs'), 'subtitles')}.{lang}.srt"
    _write(dest, format_srt(done))
    return [job.output(dest, "subtitles")], tr("Translated into {lang}: {n}", lang=lang, n=tr_n(len(done), "subtitle"))


# ---------- đọc văn bản ----------
def _speak(job: Job) -> tuple[list[dict], str]:
    job.progress(10, tr("Reading the text…"))
    work = job.dir / "work"
    r = tts.synthesize([job.params["text"]], work, job.params.get("voice") or None)
    dest = job.out / f"speech{Path(r['audio']).suffix}"
    shutil.move(r["audio"], dest)
    return [job.output(dest, "audio")], tr("Read by {voice}", voice=r.get("voice") or r.get("provider") or "?")


# ---------- ghi phụ đề lên video ----------
def _measure(size: int, cjk: bool) -> Callable[[str], float]:
    font = render._font(render.FONT_CJK if cjk else render.FONT_BOLD, size)
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    return lambda text: draw.textlength(text, font=font)


def wrap_px(text: str, measure: Callable[[str], float], max_w: float) -> list[str]:
    """Xuống dòng theo bề ngang thật; chữ Trung, Nhật, Hàn thì xuống dòng theo ký tự."""
    units, sep = _units(text)
    lines, cur = [], ""
    for u in units:
        test = f"{cur}{sep}{u}" if cur else u
        if cur and measure(test) > max_w:
            lines.append(cur.strip())
            cur = u
        else:
            cur = test
    return [*lines, cur.strip()] if cur.strip() else lines


def burn_cues(entries: list[dict], measure: Callable[[str], float], max_w: float, total: float) -> list[captions.Cue]:
    """Câu phụ đề → cue ≤ 2 dòng vừa bề ngang; câu dài chia nhiều cue theo số ký tự. Không chồng lên nhau."""
    cues = []
    for i, e in enumerate(entries):
        lines = [ln for part in e["text"].split("\n") for ln in wrap_px(part, measure, max_w)]
        groups = [lines[k:k + captions.MAX_LINES] for k in range(0, len(lines), captions.MAX_LINES)]
        if not groups:
            continue
        end = min(e["end"], entries[i + 1]["start"] if i + 1 < len(entries) else total, total)
        a, span = e["start"], end - e["start"]
        weight = sum(len("".join(g)) for g in groups) or 1
        done = 0
        for g in groups:
            start = a + span * done / weight
            done += len("".join(g))
            stop = a + span * done / weight
            if stop - start > 0.05:
                cues.append(captions.Cue(start, stop, [[captions.Word(ln, start, stop)] for ln in g]))
    return cues


def burn_layout(width: int, height: int, size: str, cjk: bool) -> render.Layout:
    """Dải phụ đề sát đáy, cỡ chữ theo cạnh ngắn của khung hình; nét viền và lề theo tỉ lệ với cỡ chữ."""
    cap = max(18, round(min(width, height) * SIZES[size]) // 2 * 2)
    base = render.Layout(width, height, "burn_", cap / render.CAP_SIZE, 0, 0, 0, 0, False, 0, 0, cap,
                         round(cap * 1.3), cjk)
    return replace(base, cap_top=height - base.cap_h - round(height * (0.08 if height > width else 0.05)))


def _burn(job: Job) -> tuple[list[dict], str]:
    src = job.path("file")
    info = delogo.probe(src)
    w, h = info["width"] // 2 * 2, info["height"] // 2 * 2
    entries = parse_subs(decode(job.path("subs").read_bytes()))
    cjk = any(CJK.search(e["text"]) for e in entries)
    layout = burn_layout(w, h, job.params["size"], cjk)
    total = info["duration"] or max(e["end"] for e in entries)
    job.progress(3, tr("Drawing the subtitles…"))
    cues = burn_cues(entries, _measure(layout.cap_size, cjk), w - 2 * round(w * 0.06), total)
    if not cues:
        raise ValueError(tr("No subtitles fall inside the video"))
    work = job.dir / "work"
    work.mkdir(exist_ok=True)
    track = render.write_caption_track(cues, work, layout, plain=True)
    dest = job.out / f"{_clean_name(job.name('file'), 'video')}.subtitled.mp4"
    cmd = [config.ffmpeg(), "-y", "-v", "error", "-i", str(src), "-f", "concat", "-safe", "0", "-i", str(track),
           "-filter_complex", f"[0:v]crop={w}:{h}:0:0[v0];[1:v]format=rgba[cap];"
                              f"[v0][cap]overlay=0:{layout.cap_top}:eof_action=pass,format=yuv420p[v]",
           "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
           "-b:a", "160k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(dest)]
    _ffmpeg(job, cmd, total, work / "ffmpeg.log")
    return [job.output(dest, "video")], tr("Subtitles added ({n})", n=tr_n(len(entries), "subtitle"))


def _ffmpeg(job: Job, cmd: list[str], total: float, log: Path) -> None:
    """Chạy FFmpeg, đọc `-progress` để báo tiến độ; dừng job thì dừng FFmpeg."""
    with log.open("wb") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
        try:
            for line in proc.stdout or []:
                if line.startswith(("out_time_us=", "out_time_ms=")) and total > 0:  # cả hai đều là micro giây
                    us = line.split("=", 1)[1].strip()
                    if us.lstrip("-").isdigit():
                        job.progress(5 + 93 * int(us) / 1e6 / total)
        except Cancelled:
            proc.kill()
            raise
        finally:
            proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(tr("ffmpeg failed: {error}", error=log.read_text(encoding="utf-8", errors="replace")[-600:]))


RUNNERS = {"download": _download, "transcribe": _transcribe, "translate": _translate, "speak": _speak, "burn": _burn}
