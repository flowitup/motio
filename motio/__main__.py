"""CLI: uv run python -m motio [refresh | trends | produce <trend_id> | topic "<chủ đề>" [link ...] | rerender <id> |
retry <id> [step] | serve | engine ...]"""
import argparse
import json
import os
import socket
import sys
import threading
import time

from . import config, db


def _utf8_console() -> None:
    """Console / pipe trên Windows mặc định cp1252: in tiếng Việt sẽ lỗi UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str]) -> None:
    _utf8_console()
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
    elif cmd == "topic":  # topic "<chủ đề>" [link …]; chủ đề "" = chỉ dùng link
        from . import pipeline, topic
        try:
            pid = topic.create(argv[1] if len(argv) > 1 else "", argv[2:])
        except ValueError as e:
            sys.exit(str(e))
        print(f"Dự án #{pid} → {config.PROJECTS / str(pid)}")
        pipeline.produce(pid)
        print(json.dumps(db.get_project(pid)["meta"], ensure_ascii=False, indent=1))
    elif cmd == "rerender":
        from . import pipeline
        pipeline.rerender(int(argv[1]))
        print(json.dumps(db.get_project(int(argv[1]))["meta"], ensure_ascii=False, indent=1))
    elif cmd == "retry":  # chạy tiếp từ bước lỗi, hoặc từ bước chỉ định (search … voice)
        from . import pipeline
        pipeline.resume(int(argv[1]), argv[2] if len(argv) > 2 else None)
        print(json.dumps(db.get_project(int(argv[1]))["meta"], ensure_ascii=False, indent=1))
    elif cmd == "serve":
        import uvicorn
        host = config.env("MOTIO_HOST", "127.0.0.1")
        port = int(config.env("MOTIO_PORT", "8765"))
        print(f"Motio: http://{host}:{port}")
        uvicorn.run("motio.web:app", host=host, port=port, log_level="warning")
    elif cmd == "engine":
        engine(argv[1:])
    else:
        sys.exit(__doc__)


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def engine(argv: list[str]) -> None:
    """Chạy engine API. In đúng một dòng JSON {"event":"ready",...} ra stdout khi đã nhận kết nối."""
    ap = argparse.ArgumentParser(prog="motio engine")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0, help="0 = tự chọn cổng trống")
    ap.add_argument("--token", default=os.getenv("MOTIO_TOKEN", ""),
                    help="bắt buộc khi --host không phải loopback; mặc định lấy từ MOTIO_TOKEN (server, Docker)")
    ap.add_argument("--headless", action="store_true", help="chạy nền 24/7 (máy Windows)")
    ap.add_argument("--exit-with-stdin", action="store_true",
                    help="thoát khi stdin đóng (app cha chết) — dùng khi app desktop khởi chạy engine")
    a = ap.parse_args(argv)
    if a.host not in LOOPBACK and not a.token:
        sys.exit("--host không phải loopback thì bắt buộc có --token")

    import secrets

    import uvicorn

    from . import __version__, api
    token = a.token or secrets.token_urlsafe(24)
    family = socket.AF_INET6 if ":" in a.host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((a.host, a.port))
    port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(api.create_app(token, headless=a.headless), log_level="warning",
                                           access_log=False))
    ready = {"event": "ready", "port": port, "version": __version__}
    if not a.token:
        ready["token"] = token  # tự sinh: người gọi cần biết để dùng

    def announce():
        while not server.started:
            if server.should_exit:
                return
            time.sleep(0.02)
        out = sys.stdout
        sys.stdout = sys.stderr  # sau dòng ready, mọi print lạc đều sang stderr
        out.write(json.dumps(ready) + "\n")
        out.flush()

    def watch_stdin():
        try:
            while sys.stdin.buffer.read(4096):
                pass
        except (OSError, ValueError):
            pass
        server.should_exit = True

    threading.Thread(target=announce, daemon=True).start()
    if a.exit_with_stdin:
        threading.Thread(target=watch_stdin, daemon=True).start()
    server.run(sockets=[sock])


if __name__ == "__main__":
    main(sys.argv[1:])
