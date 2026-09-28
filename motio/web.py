"""Web dashboard (FastAPI + Jinja). Chạy: uv run python -m motio serve"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, db, newsnow, pipeline

app = FastAPI(title="Motio")
app.mount("/media", StaticFiles(directory=config.DATA), name="media")
tpl = Jinja2Templates(directory=Path(__file__).parent / "templates")

jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="produce")  # một video mỗi lúc
state = {"refreshing": False, "last_refresh": None, "last_result": None}
_refresh_lock = threading.Lock()


def _refresh():
    if not _refresh_lock.acquire(blocking=False):
        return
    state["refreshing"] = True
    try:
        state["last_result"] = newsnow.refresh()
    except Exception as e:
        state["last_result"] = {"error": str(e)[:300]}
    finally:
        state["refreshing"] = False
        state["last_refresh"] = time.time()
        _refresh_lock.release()


def _fmt_age(ts):
    if not ts:
        return "—"
    m = int((time.time() - ts) / 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago"


tpl.env.filters["age"] = _fmt_age
tpl.env.globals["source_name"] = lambda s: newsnow.SOURCE_NAMES.get(s, s)


@app.get("/")
def home(request: Request):
    return tpl.TemplateResponse(request, "home.html", {
        "trends": db.list_trends(), "projects": db.list_projects(12), "state": state})


@app.post("/trends/refresh")
def refresh():
    threading.Thread(target=_refresh, daemon=True).start()
    return RedirectResponse("/", status_code=303)


@app.post("/trends/{tid}/produce")
def produce(tid: str):
    t = db.get_trend(tid)
    if not t:
        raise HTTPException(404, "Trend not found")
    pid = db.create_project(tid, t["title_fr"] or t["title_zh"])
    jobs.submit(pipeline.produce, pid)
    return RedirectResponse(f"/projects/{pid}", status_code=303)


@app.get("/projects/{pid}")
def project_page(request: Request, pid: int):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return tpl.TemplateResponse(request, "project.html", {"p": p, "trend": db.get_trend(p["trend_id"])})


@app.get("/api/projects/{pid}")
def project_api(pid: int):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404)
    return JSONResponse({k: p[k] for k in ("id", "status", "step", "pct", "log", "meta", "title")})


@app.get("/api/state")
def api_state():
    return {**state, "last_refresh_age": _fmt_age(state["last_refresh"])}
