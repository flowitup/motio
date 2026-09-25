"""Đo token thật cho 3 loại lệnh gọi Claude của pipeline tin nóng (dùng dữ liệu dự án #1)."""
import json, subprocess, tempfile, time
from pathlib import Path
from studio import config, db, newsnow, pipeline, search, asr

def run(name, prompt, system, effort=None, model="sonnet"):
    cmd = [config.which("claude"), "-p", "--output-format", "json", "--model", model, "--system-prompt", system,
           "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]
    if effort: cmd += ["--effort", effort]
    t = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900, cwd=tmp)
    d = json.loads(r.stdout); u = d["usage"]
    rec = {"call": name, "model": model, "effort": effort or "default", "sec": round(time.time() - t, 1),
           "input": u["input_tokens"], "cache_write": u.get("cache_creation_input_tokens", 0),
           "cache_read": u.get("cache_read_input_tokens", 0), "output": u["output_tokens"],
           "thinking": (u.get("output_tokens_details") or {}).get("thinking_tokens", 0),
           "reported_usd": d.get("total_cost_usd"), "prompt_chars": len(prompt)}
    print(json.dumps(rec), flush=True)

# 1) Chấm 20 tin
trends = db.list_trends(hours=48, limit=20)
lines = "\n".join(json.dumps({"id": t["id"], "source": t["source"], "rang": t["rank"], "titre": t["title_zh"]},
                             ensure_ascii=False) for t in trends)
run("score_20_titles", newsnow.SCORE_PROMPT.format(items=lines), newsnow.SCORE_SYSTEM, effort="low")

# 2) Chọn nguồn (tìm lại ứng viên thật trên YouTube cho tin FAST)
p = db.get_project(1); trend = db.get_trend(p["trend_id"])
cands = search.candidates({"zh": [], "en": trend["keywords"].get("en", []), "fr": trend["keywords"].get("fr", [])})
cl = "\n".join(f"{i} · {c['site']} · {c['uploader']} · {int(c['duration'] or 0)} · {c['views']} · {c['title'][:100]}"
               for i, c in enumerate(cands[:30]))
run("pick_sources", pipeline.PICK_PROMPT.format(title_zh=trend["title_zh"], title_fr=trend["title_fr"],
    angle=trend.get("angle") or "", cands=cl, n=4), pipeline.PICK_SYSTEM)

# 3) Viết kịch bản (4 nguồn đã bóc lời của dự án #1)
srcs = []
for s in p["meta"]["sources"]:
    vid = s["url"].rsplit("=", 1)[-1]
    path = next((config.CACHE / "sources").glob(f"*_{vid}.mp4"))
    srcs.append({**s, "path": str(path)})
trs = [asr.transcribe(Path(s["path"])) for s in srcs]
run("write_script", pipeline.SCRIPT_PROMPT.format(source=trend["source"], date="25/09/2026",
    title_zh=trend["title_zh"], title_fr=trend["title_fr"], angle=trend.get("angle") or "",
    sources=pipeline._fmt_sources(srcs, trs), n_min=7, n_max=11, w_min=130, w_max=160, sec=60),
    pipeline.SCRIPT_SYSTEM)
