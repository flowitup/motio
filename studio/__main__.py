"""CLI: uv run python -m studio [refresh | trends | produce <trend_id> | serve]"""
import json
import sys

from . import config, db


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else "serve"
    if cmd == "refresh":
        from . import newsnow
        print(json.dumps(newsnow.refresh(), ensure_ascii=False, indent=1))
    elif cmd == "trends":
        for t in db.list_trends()[:30]:
            print(f"{t['score']:>3}  {t['id']:<28} {t['title_fr']}")
    elif cmd == "produce":
        from . import pipeline
        t = db.get_trend(argv[1])
        if not t:
            sys.exit(f"Không có tin {argv[1]}")
        pid = db.create_project(t["id"], t["title_fr"] or t["title_zh"])
        print(f"Dự án #{pid} → {config.PROJECTS / str(pid)}")
        pipeline.produce(pid)
        print(json.dumps(db.get_project(pid)["meta"], ensure_ascii=False, indent=1))
    elif cmd == "rerender":
        from . import pipeline
        pipeline.rerender(int(argv[1]))
        print(json.dumps(db.get_project(int(argv[1]))["meta"], ensure_ascii=False, indent=1))
    elif cmd == "serve":
        import uvicorn
        host = config.env("STUDIO_HOST", "127.0.0.1")
        port = int(config.env("STUDIO_PORT", "8765"))
        print(f"Studio: http://{host}:{port}")
        uvicorn.run("studio.web:app", host=host, port=port, log_level="warning")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
