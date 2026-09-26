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
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import __version__, asr, config, db, newsnow, pipeline, postiz, settings, tts

CORS_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost", "http://localhost:1420"]
FINAL = ("done", "failed")
PROJECT_FIELDS = ("id", "trend_id", "mode", "title", "status", "step", "pct", "meta", "created_at", "updated_at")


class RetryIn(BaseModel):
    start: str | None = None  # search | download | transcribe | script | voice; None = từ bước bị lỗi


class PublishIn(BaseModel):
    channels: list[str]
    mode: str = "draft"  # draft | schedule | now
    date: str | None = None  # ISO 8601 có múi giờ, bắt buộc khi mode=schedule


def _log_tail(log: str, n: int = 30) -> list[str]:
    return (log or "").rstrip("\n").split("\n")[-n:] if log else []


def _project_out(p: dict, full: bool = False) -> dict:
    out = {k: p.get(k) for k in PROJECT_FIELDS}
    if full:
        out["log"] = p.get("log") or ""
        out["folder"] = str(config.PROJECTS / str(p["id"]))
        out["trend"] = db.get_trend(p["trend_id"]) if p.get("trend_id") else None
        out["retry"] = {"auto": pipeline.resume_point(p["id"]), "steps": pipeline.available_steps(p["id"])}
    return out


def create_app(token: str, headless: bool = False) -> FastAPI:
    if not token:
        raise ValueError("token is required")
    jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="produce")  # một video mỗi lúc
    state = {"refreshing": False, "last_refresh": None, "last_result": None}
    refresh_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_app):
        stale = db.fail_stale()
        if stale:
            print(f"motio: đánh dấu lỗi các dự án dở dang {stale}", file=sys.stderr)
        yield
        jobs.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Motio engine", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])

    def _check(value: str | None) -> None:
        if not value or not secrets.compare_digest(value.encode(), token.encode()):
            raise HTTPException(401, "Sai hoặc thiếu token")

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
            print(f"motio: dự án #{pid} lỗi: {e}", file=sys.stderr)

    def _refresh() -> None:
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
            "claude_cli": claude,
            "postiz": postiz.configured(),
            "quota_left": pipeline.quota_left(),
            "data_dir": str(config.DATA),
        }

    @app.get("/api/state", dependencies=[Depends(auth)])
    def get_state():
        return {**state, "busy": any(p["status"] in ("queued", "running") for p in db.list_projects(20))}

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

    @app.post("/api/trends/{tid}/produce", status_code=202, dependencies=[Depends(auth)])
    def produce(tid: str):
        t = db.get_trend(tid)
        if not t:
            raise HTTPException(404, "Không có tin này")
        if pipeline.quota_left() == 0:
            raise HTTPException(429, f"Đã đủ {config.max_videos_per_day()} video hôm nay (MAX_VIDEOS_PER_DAY)")
        pid = db.create_project(tid, t["title_fr"] or t["title_zh"])
        jobs.submit(_run_job, pipeline.produce, pid)
        return {"project_id": pid}

    # ---------- dự án ----------
    @app.get("/api/projects", dependencies=[Depends(auth)])
    def projects(limit: int = 50):
        return [_project_out(p) for p in db.list_projects(limit)]

    def _get(pid: int) -> dict:
        p = db.get_project(pid)
        if not p:
            raise HTTPException(404, "Không có dự án này")
        return p

    @app.get("/api/projects/{pid}", dependencies=[Depends(auth)])
    def project(pid: int):
        return _project_out(_get(pid), full=True)

    @app.post("/api/projects/{pid}/rerender", status_code=202, dependencies=[Depends(auth)])
    def rerender(pid: int):
        p = _get(pid)
        if p["status"] in ("queued", "running"):
            raise HTTPException(409, "Dự án đang chạy")
        if not (config.PROJECTS / str(pid) / "script.json").exists():
            raise HTTPException(409, "Dự án chưa có kịch bản (script.json) để dựng lại")
        db.update_project(pid, status="queued", step="Chờ dựng lại", pct=0, log="Xếp hàng dựng lại")
        jobs.submit(_run_job, pipeline.rerender, pid)
        return {"project_id": pid}

    @app.post("/api/projects/{pid}/retry", status_code=202, dependencies=[Depends(auth)])
    def retry(pid: int, body: RetryIn | None = None):
        p = _get(pid)
        if p["status"] in ("queued", "running"):
            raise HTTPException(409, "Dự án đang chạy")
        asked = body.start if body else None  # None = chạy tiếp từ bước bị lỗi, giữ kết quả đã có
        start = asked or pipeline.resume_point(pid)
        if start not in pipeline.STEPS:
            raise HTTPException(400, f"Bước không hợp lệ: {start}")
        if start not in pipeline.available_steps(pid):
            raise HTTPException(409, f"Chưa đủ dữ liệu để chạy lại từ bước {pipeline.STEP_LABELS[start]}")
        label = pipeline.STEP_LABELS[start]
        db.update_project(pid, status="queued", step=f"Chờ chạy lại: {label}", pct=0,
                          log=f"Xếp hàng chạy lại từ {label}")
        jobs.submit(_run_job, lambda i: pipeline.resume(i, asked), pid)
        return {"project_id": pid, "start": start}

    @app.get("/api/projects/{pid}/events", dependencies=[Depends(auth_or_query)])
    async def events(pid: int, request: Request):
        _get(pid)

        async def stream():
            last = None
            while True:
                if await request.is_disconnected():
                    return
                p = db.get_project(pid)
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

    # ---------- đăng bài qua Postiz ----------
    def _need_postiz() -> None:
        if not postiz.configured():
            raise HTTPException(409, "Chưa cấu hình Postiz (POSTIZ_URL, POSTIZ_API_KEY)")

    @app.get("/api/postiz/channels", dependencies=[Depends(auth)])
    def postiz_channels():
        _need_postiz()
        try:
            return postiz.channels()
        except (postiz.PostizError, httpx.HTTPError) as e:
            raise HTTPException(502, f"Postiz lỗi: {str(e)[:300]}") from e

    @app.post("/api/projects/{pid}/publish", dependencies=[Depends(auth)])
    def publish(pid: int, body: PublishIn):
        p = _get(pid)
        meta = p["meta"]
        video = config.DATA / meta["video"] if meta.get("video") else None
        if p["status"] != "done" or not video or not video.is_file():
            raise HTTPException(409, "Dự án chưa có video hoàn chỉnh")
        _need_postiz()
        title = meta.get("title") or p["title"]
        text = f"{title}\n\n{meta['description']}" if meta.get("description") else title
        try:
            res = postiz.publish(video, text, title, meta.get("hashtags") or [], body.channels, body.mode, body.date)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except (postiz.PostizError, httpx.HTTPError) as e:
            raise HTTPException(502, f"Postiz lỗi: {str(e)[:300]}") from e
        entry = {"at": time.time(), **{k: res[k] for k in ("mode", "date", "channels", "posts")}}
        names = ", ".join(c["name"] for c in res["channels"])
        db.update_project(pid, log=f"Postiz ({res['mode']}): {names}",
                          meta={"postiz": [*meta.get("postiz", []), entry]})
        return res

    # ---------- giọng, cài đặt ----------
    @app.get("/api/voices", dependencies=[Depends(auth)])
    def voices():
        if not config.env("ELEVENLABS_API_KEY"):
            raise HTTPException(409, "Chưa có ELEVENLABS_API_KEY")
        try:
            vs = tts.list_voices()
        except Exception as e:
            raise HTTPException(502, f"ElevenLabs lỗi: {str(e)[:200]}") from e
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
        if not f.is_relative_to(root) or not f.is_file() or f.name == settings.path().name:
            raise HTTPException(404, "Không có file")
        return FileResponse(f)

    return app
