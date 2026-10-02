"""Engine API (JSON) cho app desktop. Chạy: uv run python -m motio engine --port 0 --token <t>

Xác thực: `Authorization: Bearer <token>`; `?token=` chỉ nhận cho /media và luồng SSE (EventSource,
<video> không gửi được header).
"""
import asyncio
import json
import platform
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import (
    __version__,
    aiclips,
    asr,
    automake,
    channels,
    config,
    creator,
    db,
    delogo,
    dub,
    edit,
    localfile,
    newsnow,
    notify,
    pipeline,
    postiz,
    search,
    settings,
    toolbox,
    topic,
    tts,
    usage,
    watch,
)
from .i18n import tr

CORS_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost", "http://localhost:1420"]
FINAL = ("done", "failed", "review")  # SSE dừng: xong, lỗi, hoặc chờ duyệt
SCHED_TICK = 15.0  # giây giữa hai lần bộ hẹn giờ kiểm tra lịch cập nhật tin
FIRST_DELAY = 60.0  # lần tự cập nhật đầu tiên: 1 phút sau khi engine khởi động
PROJECT_FIELDS = ("id", "trend_id", "mode", "title", "status", "step", "pct", "meta", "created_at", "updated_at")


class ProduceIn(BaseModel):
    links: list[str] = []  # link video dán tay (Douyin, X, …), luôn được dùng
    links_only: bool = False  # chỉ dùng các link này, không tự tìm
    channel: int | None = None  # hồ sơ kênh: None = kênh mặc định (nếu có), 0 = không dùng kênh


class TopicIn(BaseModel):
    topic: str = ""  # chủ đề tự do, mọi ngôn ngữ; bỏ trống = chỉ dùng link
    links: list[str] = []
    links_only: bool = False
    duration: int = 80  # 70 | 80 | 90 giây
    rights: str = "unknown"  # unknown | owned | licensed | cc
    channel: int | None = None  # như ProduceIn


class AiIn(BaseModel):
    topic: str  # chủ đề của video AI (mọi ngôn ngữ)
    duration: int = 80  # 70 | 80 | 90 giây
    channel: int | None = None  # như ProduceIn
    clips: int | None = None  # số cảnh thành clip AI cho video này (0–6); None = theo hồ sơ kênh


class DubIn(BaseModel):
    link: str  # video cần lồng tiếng (Douyin, Bilibili, YouTube…)
    start: float | None = None  # đoạn lồng tiếng (giây); bỏ trống = tự chọn (cả video nếu ≤ 88 s)
    end: float | None = None
    rights: str = "unknown"  # unknown | owned | licensed | cc; chỉ tự gửi Postiz khi không phải unknown
    channel: int | None = None  # như ProduceIn


class ClipDubIn(BaseModel):
    channel: int | None = None


class DubPatch(BaseModel):
    """Chỉ các trường gửi lên mới đổi. blur: [x, y, w, h] theo tỉ lệ khung, null = tắt làm mờ. voices: {nhãn người
    nói: id giọng ElevenLabs}, id rỗng = để Motio tự chọn."""
    start: float | None = None
    end: float | None = None
    blur: list[float] | None = None
    voices: dict[str, str] | None = None


class ProjectPatch(BaseModel):
    rights: str | None = None


class WatchIn(BaseModel):
    target: str  # link kênh / playlist YouTube, không gian Bilibili, hoặc từ khoá tìm
    site: str = "youtube"  # nơi tìm khi `target` là từ khoá: youtube | bilibili
    rights: str = "unknown"


class WatchPatch(BaseModel):
    name: str | None = None
    rights: str | None = None
    enabled: bool | None = None


class ClipPatch(BaseModel):
    status: str  # new | hidden


class ClipProduceIn(BaseModel):
    duration: int = 80
    links_only: bool | None = None  # None = chỉ dùng video này khi nguồn có quyền rõ ràng
    channel: int | None = None  # như ProduceIn


class ScriptIn(BaseModel):
    title_fr: str
    lines: list[dict]  # [{text, clips: [{src, start, end}]}]; clips giữ nguyên từ GET, dòng mới không cần
    description: str = ""
    hashtags: list[str] = []
    style: str = ""  # video AI: phong cách ảnh chung; dòng của video AI có thêm image, motion, seed


class LinksIn(BaseModel):
    links: list[str]


class RetryIn(BaseModel):
    start: str | None = None  # search | download | transcribe | script | voice | render; None = từ bước lỗi


class DelogoFrameIn(BaseModel):
    at: float | None = None  # giây; bỏ trống = 10 % độ dài video


class DelogoRunIn(BaseModel):
    boxes: list[dict]  # [{x, y, w, h}] theo pixel của khung hình
    rights: str | None = None  # optional existing-client declaration: owned | licensed
    scope: str | None = None  # nguồn dự án: used (mặc định); file tải lên: all (mặc định) | range (start–end, giây)
    start: float | None = None
    end: float | None = None


class ChannelIn(BaseModel):
    name: str
    badge: str = ""  # nhãn đỏ trên tiêu đề video, rỗng = không nhãn
    style: str = ""  # ghi chú giọng văn thêm vào prompt kịch bản
    glossary: str = ""  # bảng thuật ngữ (tên riêng, từ chuyên môn) cho kịch bản và bản dịch lồng tiếng
    voice_id: str = ""  # giọng ElevenLabs, rỗng = theo Cài đặt
    dub_voices: list[str] = []  # giọng thêm cho các người nói khác trong bản lồng tiếng (tối đa 3)
    duration: int = 80  # độ dài mặc định cho video tin nóng
    hashtags: list[str] = []
    gate_script: bool = True  # dừng chờ duyệt kịch bản
    gate_video: bool = True  # dừng chờ duyệt video cuối
    postiz: list[str] = []  # id kênh Postiz để gửi khi video được duyệt
    send_mode: str = "draft"  # draft | schedule | now
    send_times: list[str] = []  # giờ đăng "HH:MM" (giờ máy chạy engine) khi send_mode = schedule
    wide_postiz: list[str] = []  # trong `postiz`: kênh nhận bản 16:9 (có thì dựng thêm bản 16:9)
    auto_score: int = 0  # tự làm video khi tin hot đạt điểm này sau lượt tự cập nhật; 0 = tắt
    auto_daily: int = 2  # tối đa số video tự làm mỗi ngày cho kênh này
    ai_clips: int = 0  # video AI: số cảnh thành clip AI (fal H3 Max) mỗi video; 0 = chỉ ảnh chuyển động
    series: str = ""  # video AI: tiền đề + luật của loạt phim; mỗi tập mới viết tiếp các tập trước của kênh
    cast: str = ""  # video AI: nhân vật cố định, mỗi dòng "Tên: ngoại hình" (tiếng Anh, nhân vật hư cấu)
    default: bool = False


class ApproveIn(BaseModel):
    send: bool = True  # duyệt video: gửi sang Postiz theo kênh; False = chỉ duyệt


class PublishIn(BaseModel):
    channels: list[str]
    mode: str = "draft"  # draft | schedule | now
    date: str | None = None  # ISO 8601 có múi giờ, bắt buộc khi mode=schedule
    version: str = "vertical"  # vertical (9:16) | wide (bản 16:9 nếu kênh đã dựng)


def _log_tail(log: str, n: int = 30) -> list[str]:
    return (log or "").rstrip("\n").split("\n")[-n:] if log else []


def _project_out(p: dict, full: bool = False) -> dict:
    out = {k: p.get(k) for k in PROJECT_FIELDS}
    if full:
        out["log"] = p.get("log") or ""
        out["folder"] = str(config.PROJECTS / str(p["id"]))
        out["trend"] = db.get_trend(p["trend_id"]) if p.get("trend_id") else None
        out["retry"] = {"auto": pipeline.resume_point(p["id"]), "steps": pipeline.available_steps(p["id"])}
        out["has_script"] = (config.PROJECTS / str(p["id"]) / "script.json").exists()
        out["dub"] = dub.view(p)
        out["ai"] = creator.view(p)
        out["usage"] = usage.for_project(p["id"])
    return out


def create_app(token: str, headless: bool = False) -> FastAPI:
    if not token:
        raise ValueError("token is required")
    jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="produce")  # một video mỗi lúc
    tools = ThreadPoolExecutor(max_workers=1, thread_name_prefix="delogo")  # xoá logo (lâu) không chặn việc làm video
    fetch = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fetch")  # tải video lẻ: không chờ việc nặng
    state = {"refreshing": False, "last_refresh": None, "last_result": None,
             "watching": False, "last_watch": None, "last_watch_result": None, "last_auto": None}
    refresh_lock = threading.Lock()
    watch_lock = threading.Lock()
    started = time.time()
    stop = threading.Event()

    def next_refresh() -> float | None:
        every = config.refresh_every_min()
        if not every:
            return None
        return state["last_refresh"] + every * 60 if state["last_refresh"] else started + FIRST_DELAY

    def next_watch() -> float | None:
        """Nguồn theo dõi được kiểm tra cùng nhịp REFRESH_EVERY_MIN với tin hot."""
        every = config.refresh_every_min()
        if not every:
            return None
        return state["last_watch"] + every * 60 if state["last_watch"] else started + FIRST_DELAY

    def scheduler() -> None:
        """REFRESH_EVERY_MIN > 0: tự cập nhật tin và nguồn theo dõi theo lịch. Đổi cài đặt là có hiệu lực ngay."""
        while not stop.wait(SCHED_TICK):
            due = next_refresh()
            if due is not None and time.time() >= due and not state["refreshing"]:
                _refresh(auto=True)
            due = next_watch()
            if due is not None and time.time() >= due and not state["watching"]:
                _check_watches()

    @asynccontextmanager
    async def lifespan(_app):
        stale = db.fail_stale()
        if stale:
            print(f"motio: marked unfinished projects as failed {stale}", file=sys.stderr)
        toolbox.recover()
        threading.Thread(target=scheduler, name="refresh-scheduler", daemon=True).start()
        yield
        stop.set()
        jobs.shutdown(wait=False, cancel_futures=True)
        delogo.stop_all()  # FFmpeg + mô hình dừng ở khung hình kế tiếp, engine thoát được ngay
        tools.shutdown(wait=False, cancel_futures=True)
        fetch.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Motio engine", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])

    def _check(value: str | None) -> None:
        if not value or not secrets.compare_digest(value.encode(), token.encode()):
            raise HTTPException(401, tr("Missing or invalid token"))

    def auth(request: Request) -> None:
        h = request.headers.get("authorization", "")
        _check(h[7:] if h.lower().startswith("bearer ") else None)

    def auth_or_query(request: Request, token_q: str | None = Query(None, alias="token")) -> None:
        h = request.headers.get("authorization", "")
        _check(h[7:] if h.lower().startswith("bearer ") else token_q)

    def _run_job(fn, pid: int) -> None:
        try:
            fn(pid)
        except Exception as e:  # pipeline đã ghi lỗi vào dự án; chỉ log ra stderr
            print(f"motio: project #{pid} failed: {e}", file=sys.stderr)

    def _refresh(auto: bool = False) -> None:
        """Cập nhật tin. auto (lượt theo lịch): xong thì tự làm các tin đạt điểm của hồ sơ kênh."""
        if not refresh_lock.acquire(blocking=False):
            return
        state["refreshing"] = True
        try:
            state["last_result"] = newsnow.refresh()
        except Exception as e:
            state["last_result"] = {"error": str(e)[:300]}
        finally:
            state["refreshing"] = False
            state["last_refresh"] = time.time()
            refresh_lock.release()
        if auto:
            _automake()

    def _automake() -> None:
        try:
            made = []
            for t, ch in automake.picks():
                pid = automake.start(t, ch)
                jobs.submit(_run_job, pipeline.produce, pid)
                made.append(pid)
            if made:
                state["last_auto"] = {"at": time.time(), "projects": made}
        except Exception as e:  # không để lỗi tự làm dừng bộ hẹn giờ
            print(f"motio: auto-make failed: {e}", file=sys.stderr)

    def _check_watches(ids: list[int] | None = None) -> None:
        """Kiểm tra nguồn theo dõi (tất cả, hoặc `ids` vừa thêm). Lượt sau chờ lượt trước xong."""
        with watch_lock:
            state["watching"] = True
            try:
                state["last_watch_result"] = watch.check_all(ids)
            except Exception as e:
                state["last_watch_result"] = {"error": str(e)[:300]}
            finally:
                state["watching"] = False
                if ids is None:
                    state["last_watch"] = time.time()

    # ---------- hệ thống ----------
    @app.get("/api/health", dependencies=[Depends(auth)])
    def health():
        claude = config.find("claude")
        return {
            "version": __version__,
            "platform": {"system": platform.system(), "machine": platform.machine(),
                         "python": platform.python_version()},
            "headless": headless,
            "providers": {
                "llm": {"provider": config.env("LLM_PROVIDER", "claude_cli"),
                        "model": config.env("LLM_MODEL", "sonnet")},
                "tts": tts.provider(),
                "asr": {"engine": asr.engine_name(), "model": asr.model_name()},
            },
            "ffmpeg": config.find("ffmpeg"),
            "ffprobe": config.find("ffprobe"),
            "js_runtime": next(iter(config.js_runtimes().values()), {}).get("path"),
            "claude_cli": claude,
            "postiz": postiz.configured(),
            "quota_left": pipeline.quota_left(),
            "data_dir": str(config.DATA),
            "disk": config.disk(),
        }

    @app.get("/api/stats", dependencies=[Depends(auth)])
    def stats():
        """Trang Stats: chi phí ElevenLabs ước lượng (tháng này, 30 ngày, theo kênh), số video, ngân sách."""
        return usage.summary()

    @app.get("/api/state", dependencies=[Depends(auth)])
    def get_state():
        return {**state, "busy": any(p["status"] in ("queued", "running") for p in db.list_projects(20)),
                "refresh_every_min": config.refresh_every_min(), "next_refresh": next_refresh(),
                "next_watch": next_watch()}

    # ---------- tin hot ----------
    @app.get("/api/trends", dependencies=[Depends(auth)])
    def trends(hours: float = 24, source: str | None = None, limit: int = 100):
        return [{**t, "source_name": newsnow.SOURCE_NAMES.get(t["source"], t["source"])}
                for t in db.list_trends(hours=hours, limit=limit, source=source or None)]

    @app.post("/api/trends/refresh", status_code=202, dependencies=[Depends(auth)])
    def refresh():
        started = not state["refreshing"]
        if started:
            threading.Thread(target=_refresh, daemon=True).start()
        return {"started": started}

    def _links(raw: list[str]) -> list[str]:
        try:
            return search.clean_links(raw)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    def _channel_for(channel: int | None) -> dict | None:
        try:
            return channels.pick(channel)
        except LookupError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/trends/{tid}/produce", status_code=202, dependencies=[Depends(auth)])
    def produce(tid: str, body: ProduceIn | None = None):
        t = db.get_trend(tid)
        if not t:
            raise HTTPException(404, tr("Trend not found"))
        links = _links(body.links) if body else []
        if body and body.links_only and not links:
            raise HTTPException(400, tr("“Use only these links” needs at least one link"))
        ch = _channel_for(body.channel if body else None)
        if pipeline.quota_left() == 0:
            raise HTTPException(429, tr("Daily limit reached: {n} videos (MAX_VIDEOS_PER_DAY)",
                                        n=config.max_videos_per_day()))
        pid = db.create_project(tid, t["title_fr"] or t["title_zh"])
        channels.attach(pid, ch, news=True)
        if links:
            db.update_project(pid, log=tr("Pasted source links: {n}", n=len(links)),
                              meta={"links": links, "links_only": bool(body.links_only)})
        jobs.submit(_run_job, pipeline.produce, pid)
        return {"project_id": pid}

    # ---------- nguồn theo dõi, video mới ----------
    def _watch(wid: int) -> dict:
        w = db.get_watch(wid)
        if not w:
            raise HTTPException(404, tr("Source not found"))
        return w

    @app.get("/api/watches", dependencies=[Depends(auth)])
    def watches():
        return db.list_watches()

    @app.post("/api/watches", status_code=201, dependencies=[Depends(auth)])
    def add_watch(body: WatchIn):
        """Thêm nguồn rồi kiểm tra ngay trong nền: lần đầu hiện 10 video mới nhất (danh sách trending Bilibili: 20)."""
        try:
            wid = watch.add(body.target, body.site, body.rights)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        threading.Thread(target=_check_watches, args=([wid],), daemon=True).start()
        return _watch(wid)

    @app.patch("/api/watches/{wid}", dependencies=[Depends(auth)])
    def patch_watch(wid: int, body: WatchPatch):
        _watch(wid)
        if body.rights is not None and body.rights not in topic.RIGHTS:
            raise HTTPException(400, tr("Invalid source rights: {rights}", rights=body.rights))
        name = " ".join((body.name or "").split())[:200]
        db.update_watch(wid, **{k: v for k, v in (("name", name), ("rights", body.rights),
                                                  ("enabled", body.enabled)) if v not in (None, "")})
        return _watch(wid)

    @app.delete("/api/watches/{wid}", dependencies=[Depends(auth)])
    def delete_watch(wid: int):
        _watch(wid)
        db.delete_watch(wid)
        return {"deleted": wid}

    @app.post("/api/watches/check", status_code=202, dependencies=[Depends(auth)])
    def check_watches():
        started = not state["watching"]
        if started:
            state["watching"] = True  # để lần gọi kế tiếp thấy ngay, trước khi luồng chạy
            threading.Thread(target=_check_watches, daemon=True).start()
        return {"started": started}

    @app.get("/api/clips", dependencies=[Depends(auth)])
    def clips(status: str = "new", watch_id: int | None = None, limit: int = 200):
        return db.list_clips(status, watch_id, limit)

    def _clip(cid: str) -> dict:
        c = db.get_clip(cid)
        if not c:
            raise HTTPException(404, tr("Video not found"))
        return c

    @app.patch("/api/clips/{cid}", dependencies=[Depends(auth)])
    def patch_clip(cid: str, body: ClipPatch):
        c = _clip(cid)
        if body.status not in ("new", "hidden") or c["status"] == "used":
            raise HTTPException(400, tr("Only videos not made yet can be hidden or shown again"))
        db.set_clip_status(cid, body.status)
        return _clip(cid)

    @app.post("/api/clips/{cid}/produce", status_code=202, dependencies=[Depends(auth)])
    def produce_clip(cid: str, body: ClipProduceIn | None = None):
        """Video giải thích từ một video mới (dự án chủ đề: link của video + tiêu đề làm chủ đề)."""
        _clip(cid)
        body = body or ClipProduceIn()
        ch = _channel_for(body.channel)
        if pipeline.quota_left() == 0:
            raise HTTPException(429, tr("Daily limit reached: {n} videos (MAX_VIDEOS_PER_DAY)",
                                        n=config.max_videos_per_day()))
        try:
            pid = watch.produce(cid, body.duration, body.links_only)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        channels.attach(pid, ch)
        jobs.submit(_run_job, pipeline.produce, pid)
        return {"project_id": pid}

    @app.post("/api/clips/{cid}/dub", status_code=202, dependencies=[Depends(auth)])
    def dub_clip(cid: str, body: ClipDubIn | None = None):
        """Bản lồng tiếng Pháp của một video mới (quyền nguồn theo nguồn theo dõi)."""
        _clip(cid)
        ch = _channel_for(body.channel if body else None)
        if pipeline.quota_left() == 0:
            raise HTTPException(429, tr("Daily limit reached: {n} videos (MAX_VIDEOS_PER_DAY)",
                                        n=config.max_videos_per_day()))
        try:
            pid = dub.from_clip(cid)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        channels.attach(pid, ch)
        jobs.submit(_run_job, pipeline.produce, pid)
        return {"project_id": pid}

    # ---------- dự án ----------
    @app.get("/api/projects", dependencies=[Depends(auth)])
    def projects(limit: int = 50):
        return [_project_out(p) for p in db.list_projects(limit)]

    def _get(pid: int) -> dict:
        p = db.get_project(pid)
        if not p:
            raise HTTPException(404, tr("Project not found"))
        return p

    @app.get("/api/projects/{pid}", dependencies=[Depends(auth)])
    def project(pid: int):
        return _project_out(_get(pid), full=True)

    @app.post("/api/projects", status_code=202, dependencies=[Depends(auth)])
    def create_topic(body: TopicIn):
        """Video giải thích từ một chủ đề tự do và / hoặc link video (Douyin, Bilibili, Facebook, YouTube…)."""
        ch = _channel_for(body.channel)
        if pipeline.quota_left() == 0:
            raise HTTPException(429, tr("Daily limit reached: {n} videos (MAX_VIDEOS_PER_DAY)",
                                        n=config.max_videos_per_day()))
        try:
            pid = topic.create(body.topic, body.links, body.links_only, body.duration, body.rights)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        channels.attach(pid, ch)
        jobs.submit(_run_job, pipeline.produce, pid)
        return {"project_id": pid}

    @app.post("/api/ai", status_code=202, dependencies=[Depends(auth)])
    def create_ai(body: AiIn):
        """Video làm hoàn toàn bằng ảnh AI từ một chủ đề: Claude viết lời và prompt từng cảnh, nhà cung cấp ảnh
        (Cài đặt) làm ảnh, rồi đọc và dựng với chuyển động chậm."""
        ch = _channel_for(body.channel)
        if pipeline.quota_left() == 0:
            raise HTTPException(429, tr("Daily limit reached: {n} videos (MAX_VIDEOS_PER_DAY)",
                                        n=config.max_videos_per_day()))
        try:
            if body.clips is None and aiclips.limit({"meta": {}}, ch):
                aiclips.check_ready()  # the channel's clips need the key too: say so before the project exists
            pid = creator.create(body.topic, body.duration, body.clips)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        channels.attach(pid, ch)
        jobs.submit(_run_job, pipeline.produce, pid)
        return {"project_id": pid}

    @app.post("/api/dubs", status_code=202, dependencies=[Depends(auth)])
    def create_dub(body: DubIn):
        """Lồng tiếng Pháp cho một video: dịch từng câu, giữ nhạc nền gốc, làm mờ phụ đề cũ."""
        ch = _channel_for(body.channel)
        if pipeline.quota_left() == 0:
            raise HTTPException(429, tr("Daily limit reached: {n} videos (MAX_VIDEOS_PER_DAY)",
                                        n=config.max_videos_per_day()))
        try:
            pid = dub.create(body.link, body.start, body.end, body.rights)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        channels.attach(pid, ch)
        jobs.submit(_run_job, pipeline.produce, pid)
        return {"project_id": pid}

    @app.put("/api/projects/{pid}/dub", dependencies=[Depends(auth)])
    def put_dub(pid: int, body: DubPatch):
        """Đổi đoạn lồng tiếng / giọng từng người nói / khung làm mờ. Trả rerun: bước nên chạy lại (script, voice,
        render) hoặc null, app gọi /retry với bước đó."""
        p = _get(pid)
        if p["status"] in ("queued", "running"):
            raise HTTPException(409, tr("Project is running"))
        try:
            rerun = dub.update(pid, body.model_dump(exclude_unset=True))
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if rerun and rerun not in pipeline.available_steps(pid):
            rerun = pipeline.resume_point(pid)
        return {"project": _project_out(_get(pid), full=True), "rerun": rerun}

    @app.patch("/api/projects/{pid}", dependencies=[Depends(auth)])
    def patch_project(pid: int, body: ProjectPatch):
        _get(pid)
        if body.rights is not None:
            if body.rights not in topic.RIGHTS:
                raise HTTPException(400, tr("Invalid source rights: {rights}", rights=body.rights))
            db.update_project(pid, log=tr("Source rights: {rights}", rights=body.rights), meta={"rights": body.rights})
        return _project_out(_get(pid), full=True)

    @app.delete("/api/projects/{pid}", dependencies=[Depends(auth)])
    def delete_project(pid: int):
        """Xoá dự án và thư mục của nó (video, giọng, phụ đề, bài đăng). Bài đã gửi Postiz vẫn ở Postiz."""
        _get(pid)
        try:
            edit.delete(pid)
        except (edit.Busy, OSError) as e:
            raise HTTPException(409, str(e)) from e
        return {"deleted": pid}

    @app.get("/api/projects/{pid}/script", dependencies=[Depends(auth)])
    def get_script(pid: int):
        _get(pid)
        try:
            return edit.script_view(pid)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @app.put("/api/projects/{pid}/script", dependencies=[Depends(auth)])
    def put_script(pid: int, body: ScriptIn):
        """Lưu kịch bản đã sửa; dựng lại bằng POST /retry {"start": "voice"}."""
        _get(pid)
        try:
            return edit.save_script(pid, body.model_dump())
        except edit.Busy as e:
            raise HTTPException(409, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/projects/{pid}/scenes/{index}/redo", dependencies=[Depends(auth)])
    def redo_scene(pid: int, index: int):
        """Video AI: xin ảnh mới cho một cảnh; dựng lại bằng POST /retry {"start": "render"} để làm ảnh đó."""
        _get(pid)
        try:
            return edit.reroll_picture(pid, index)
        except edit.Busy as e:
            raise HTTPException(409, str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/projects/{pid}/rerender", status_code=202, dependencies=[Depends(auth)])
    def rerender(pid: int):
        p = _get(pid)
        if p["status"] in ("queued", "running"):
            raise HTTPException(409, tr("Project is running"))
        if not (config.PROJECTS / str(pid) / "script.json").exists():
            raise HTTPException(409, tr("Project has no script (script.json) to re-render"))
        db.update_project(pid, status="queued", step=tr("Queued for re-render"), pct=0, log=tr("Queued for re-render"))
        jobs.submit(_run_job, pipeline.rerender, pid)
        return {"project_id": pid}

    @app.post("/api/projects/{pid}/retry", status_code=202, dependencies=[Depends(auth)])
    def retry(pid: int, body: RetryIn | None = None):
        p = _get(pid)
        if p["status"] in ("queued", "running"):
            raise HTTPException(409, tr("Project is running"))
        asked = body.start if body else None  # None = chạy tiếp từ bước bị lỗi, giữ kết quả đã có
        start = asked or pipeline.resume_point(pid)
        if start not in pipeline.STEPS:
            raise HTTPException(400, tr("Invalid step: {step}", step=start))
        label = tr(pipeline.STEP_LABELS[start])
        if start not in pipeline.available_steps(pid):
            raise HTTPException(409, tr("Not enough data to rerun from step {step}", step=label))
        db.update_project(pid, status="queued", step=tr("Queued to rerun: {step}", step=label), pct=0,
                          log=tr("Queued to rerun from step {step}", step=label))
        jobs.submit(_run_job, lambda i: pipeline.resume(i, asked), pid)
        return {"project_id": pid, "start": start}

    @app.post("/api/uploads", status_code=201, dependencies=[Depends(auth)])
    def upload_video(file: UploadFile):
        """A video file the user already has, kept as a source: answers the `file:` link to paste where links go."""
        try:
            return localfile.save(file.filename or "", file.file)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except (RuntimeError, OSError) as e:
            raise HTTPException(500, str(e)[:500]) from e

    @app.post("/api/projects/{pid}/links", status_code=202, dependencies=[Depends(auth)])
    def add_links(pid: int, body: LinksIn):
        """Thêm link nguồn rồi chạy lại từ bước tải video (hoặc tìm nguồn nếu dự án chưa tới đó)."""
        p = _get(pid)
        if p["status"] in ("queued", "running"):
            raise HTTPException(409, tr("Project is running"))
        links = _links(body.links)
        if not links:
            raise HTTPException(400, tr("No links given"))
        start = pipeline.add_links(pid, links)
        label = tr(pipeline.STEP_LABELS[start])
        db.update_project(pid, status="queued", step=tr("Queued to rerun: {step}", step=label), pct=0,
                          log=tr("Queued to rerun from step {step}", step=label))
        jobs.submit(_run_job, lambda i: pipeline.resume(i, start), pid)
        return {"project_id": pid, "start": start}

    @app.post("/api/projects/{pid}/approve", status_code=202, dependencies=[Depends(auth)])
    def approve(pid: int, body: ApproveIn | None = None):
        """Duyệt dự án đang chờ: kịch bản → đọc giọng và dựng; video → gửi Postiz theo kênh (send=False: không gửi)."""
        p = _get(pid)
        review = p["meta"].get("review")
        if p["status"] != "review" or review not in pipeline.REVIEW_STEPS:
            raise HTTPException(409, tr("Project is not awaiting approval"))
        if review == "script":
            db.update_project(pid, status="queued", step=tr("Queued for voice and render"), pct=0,
                              log=tr("Script approved"),
                              meta={"review": None})
            jobs.submit(_run_job, lambda i: pipeline.produce(i, start="voice"), pid)
        else:
            send = body.send if body else True
            db.update_project(pid, status="running", step=tr("Send to Postiz") if send else tr("Done"), pct=100)
            threading.Thread(target=_run_job, args=(lambda i: pipeline.approve_video(i, send), pid),
                             daemon=True).start()  # tải video lên Postiz không chờ hàng đợi làm video
        return {"project_id": pid, "review": review}

    @app.get("/api/projects/{pid}/events", dependencies=[Depends(auth_or_query)])
    async def events(pid: int, request: Request):
        _get(pid)

        async def stream():
            last = None
            while True:
                if await request.is_disconnected():
                    return
                p = db.get_project(pid)
                if not p:  # dự án vừa bị xoá
                    return
                snap = {"status": p["status"], "step": p["step"], "pct": p["pct"],
                        "log_tail": _log_tail(p["log"]), "updated_at": p["updated_at"]}
                if snap != last:
                    last = snap
                    yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                    if p["status"] in FINAL:
                        yield "event: end\ndata: {}\n\n"
                        return
                else:
                    yield ": ping\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------- kênh (hồ sơ đăng) ----------
    def _channel_data(body: ChannelIn) -> dict:
        return body.model_dump(exclude={"default"})

    @app.get("/api/channels", dependencies=[Depends(auth)])
    def list_channels():
        return channels.listing()

    @app.post("/api/channels", status_code=201, dependencies=[Depends(auth)])
    def create_channel(body: ChannelIn):
        try:
            return channels.create(_channel_data(body), body.default)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.put("/api/channels/{cid}", dependencies=[Depends(auth)])
    def update_channel(cid: int, body: ChannelIn):
        try:
            return channels.update(cid, _channel_data(body), body.default)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.delete("/api/channels/{cid}", dependencies=[Depends(auth)])
    def delete_channel(cid: int):
        """Xoá hồ sơ; dự án đã gắn với nó chạy tiếp như không có kênh."""
        if not db.get_channel(cid):
            raise HTTPException(404, tr("Channel not found"))
        db.delete_channel(cid)
        return {"deleted": cid}

    # ---------- đăng bài qua Postiz ----------
    def _need_postiz() -> None:
        if not postiz.configured():
            raise HTTPException(409, tr("Postiz is not configured (POSTIZ_URL, POSTIZ_API_KEY)"))

    @app.get("/api/postiz/channels", dependencies=[Depends(auth)])
    def postiz_channels():
        _need_postiz()
        try:
            return postiz.channels()
        except (postiz.PostizError, httpx.HTTPError) as e:
            raise HTTPException(502, tr("Postiz error: {error}", error=str(e)[:300])) from e

    @app.post("/api/projects/{pid}/publish", dependencies=[Depends(auth)])
    def publish(pid: int, body: PublishIn):
        p = _get(pid)
        if body.version not in postiz.VERSIONS:
            raise HTTPException(400, tr("version must be one of {choices}", choices=", ".join(postiz.VERSIONS)))
        if p["status"] != "done" or not postiz.project_video(p["meta"], body.version):
            raise HTTPException(409, tr("Project has no 16:9 copy yet") if body.version == "wide"
                                else tr("Project has no finished video yet"))
        _need_postiz()
        try:
            return postiz.publish_project(pid, body.channels, body.mode, body.date, version=body.version)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except (postiz.PostizError, httpx.HTTPError) as e:
            raise HTTPException(502, tr("Postiz error: {error}", error=str(e)[:300])) from e

    # ---------- thông báo Slack ----------
    @app.post("/api/notify/test", dependencies=[Depends(auth)])
    def notify_test():
        """Gửi một tin thử tới webhook Slack đã lưu, để Cài đặt biết link có dùng được không."""
        try:
            notify.send(tr("Motio test message: Slack alerts are working."))
        except notify.NotifyError as e:
            raise HTTPException(400, str(e)) from e
        return {"sent": True}

    # ---------- xoá logo (video người dùng chọn) ----------
    def _dl(fn, *args):
        try:
            return fn(*args)
        except delogo.NotFound as e:
            raise HTTPException(404, str(e)) from e
        except delogo.Busy as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except (RuntimeError, OSError) as e:
            raise HTTPException(500, str(e)[:500]) from e

    def _bg(fn) -> None:
        try:
            fn()
        except Exception as e:  # lỗi đã ghi vào trạng thái job
            print(f"motio: logo removal failed: {e}", file=sys.stderr)

    @app.get("/api/delogo/uploads", dependencies=[Depends(auth)])
    def delogo_uploads():
        return delogo.list_uploads()

    @app.post("/api/delogo/uploads", status_code=201, dependencies=[Depends(auth)])
    def delogo_upload(file: UploadFile):
        key = _dl(delogo.save_upload, file.filename or "", file.file)
        return _dl(delogo.frame, key)

    @app.get("/api/delogo/targets/{key}", dependencies=[Depends(auth)])
    def delogo_view(key: str):
        return _dl(delogo.view, key)

    @app.post("/api/delogo/targets/{key}/frame", dependencies=[Depends(auth)])
    def delogo_frame(key: str, body: DelogoFrameIn | None = None):
        return _dl(delogo.frame, key, body.at if body else None)

    @app.post("/api/delogo/targets/{key}/detect", dependencies=[Depends(auth)])
    def delogo_detect(key: str):
        return _dl(delogo.detect, key)

    @app.post("/api/delogo/targets/{key}/run", status_code=202, dependencies=[Depends(auth)])
    def delogo_run(key: str, body: DelogoRunIn):
        span = (body.start or 0.0, body.end or 0.0) if body.scope == "range" else None
        return _dl(delogo.start, key, body.boxes, body.rights, lambda fn: tools.submit(_bg, fn), body.scope, span)

    @app.post("/api/delogo/targets/{key}/cancel", dependencies=[Depends(auth)])
    def delogo_cancel(key: str):
        return _dl(delogo.cancel, key)

    @app.delete("/api/delogo/targets/{key}/result", dependencies=[Depends(auth)])
    def delogo_restore(key: str):
        return _dl(delogo.restore, key)

    @app.delete("/api/delogo/targets/{key}", dependencies=[Depends(auth)])
    def delogo_delete(key: str):
        _dl(delogo.delete_upload, key)
        return {"deleted": key}

    # ---------- công cụ lẻ: tải, bóc lời, dịch phụ đề, đọc, ghi phụ đề ----------
    def _tb(fn, *args):
        try:
            return fn(*args)
        except toolbox.NotFound as e:
            raise HTTPException(404, str(e)) from e
        except (toolbox.Busy, tts.TTSUnavailable) as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except (RuntimeError, OSError) as e:
            raise HTTPException(500, str(e)[:500]) from e

    def _tool_bg(fn) -> None:
        try:
            fn()
        except Exception as e:  # lỗi đã ghi vào job
            print(f"motio: tool job failed: {e}", file=sys.stderr)

    @app.get("/api/tools/jobs", dependencies=[Depends(auth)])
    def tool_jobs():
        return toolbox.list_jobs()

    @app.get("/api/tools/jobs/{job_id}", dependencies=[Depends(auth)])
    def tool_job(job_id: str):
        return _tb(toolbox.get, job_id)

    @app.post("/api/tools/jobs/{job_id}/cancel", dependencies=[Depends(auth)])
    def tool_cancel(job_id: str):
        return _tb(toolbox.cancel, job_id)

    @app.delete("/api/tools/jobs/{job_id}", dependencies=[Depends(auth)])
    def tool_delete(job_id: str):
        _tb(toolbox.delete, job_id)
        return {"deleted": job_id}

    @app.post("/api/tools/{kind}", status_code=202, dependencies=[Depends(auth)])
    def tool_start(kind: str, url: str = Form(""), text: str = Form(""), voice: str = Form(""),
                   language: str = Form(""), height: int = Form(0), size: str = Form(""),
                   channel: int | None = Form(None), file_job: str = Form(""), subs_job: str = Form(""),
                   file: UploadFile | None = None, subs: UploadFile | None = None):
        """Multipart: các ô chữ tuỳ công cụ, file tải lên (`file`: video / âm thanh, `subs`: .srt / .vtt) hoặc
        `file_job` / `subs_job` = kết quả của một job đã xong."""
        pool = fetch if kind == "download" else tools
        params = {"url": url, "text": text, "voice": voice, "language": language, "height": height,
                  "size": size, "channel": channel, "file_job": file_job, "subs_job": subs_job}
        files = {k: (f.filename or "", f.file) for k, f in (("file", file), ("subs", subs)) if f and f.filename}
        return _tb(toolbox.start, kind, params, files, lambda fn: pool.submit(_tool_bg, fn))

    # ---------- giọng, cài đặt ----------
    @app.get("/api/voices", dependencies=[Depends(auth)])
    def voices():
        if not config.env("ELEVENLABS_API_KEY"):
            raise HTTPException(409, tr("ELEVENLABS_API_KEY is not set"))
        try:
            vs = tts.list_voices()
        except Exception as e:
            raise HTTPException(502, tr("ElevenLabs error: {error}", error=str(e)[:200])) from e
        return [{"id": v["voice_id"], "name": v.get("name", v["voice_id"]), "labels": v.get("labels") or {},
                 "preview_url": v.get("preview_url")} for v in vs]

    @app.get("/api/settings", dependencies=[Depends(auth)])
    def get_settings():
        return settings.public()

    @app.put("/api/settings", dependencies=[Depends(auth)])
    def put_settings(changes: dict):
        try:
            return settings.update(changes)
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e).strip("'")) from e

    # ---------- file ----------
    @app.get("/media/{path:path}", dependencies=[Depends(auth_or_query)])
    def media(path: str):
        root = config.DATA.resolve()
        f = (root / path).resolve()
        cookies = search.cookie_file()  # cookie đăng nhập: không phục vụ dù đặt trong thư mục dữ liệu
        if (not f.is_relative_to(root) or not f.is_file() or f.name == settings.path().name
                or (cookies and f == cookies.resolve())):
            raise HTTPException(404, tr("File not found"))
        return FileResponse(f)

    return app
