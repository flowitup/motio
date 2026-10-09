"""CLI: uv run python -m motio [refresh | automake | trends | produce <trend_id> | topic "<topic>" [link ...] |
ai "<topic>" [seconds] [ai clips] | clipcheck <picture> ["<scene>"] [fal | heygen] | dub <link> [start end] |
rerender <id> | retry <id> [step] | approve <id> [nosend] |
delete <id> | watch "<channel link | keywords>" [bilibili] | check | clips | serve | engine ...]

produce / topic / ai / dub use the default channel (if any): with an approval gate, the project waits for `approve`.
ai: a video made only of AI pictures (Settings → Image provider; `IMAGE_PROVIDER=placeholder` to try it for free).
dub: French dub of one video (start / end in seconds; left out = whole video if short, else Claude picks 62–85 s).
automake makes, one after another, the trends that reach a channel's auto-make score (the engine does it by itself
after each scheduled refresh)."""
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
    elif cmd == "automake":
        from . import automake, pipeline
        picks = automake.picks()
        if not picks:
            print("Nothing to make: no new trend reaches a channel's auto-make score (or today's limit is reached)")
        for t, ch in picks:
            pid = automake.start(t, ch)
            print(f"Project #{pid} ({ch['name']}, score {t['score']}): {t['title_fr']}")
            pipeline.produce(pid)
    elif cmd == "trends":
        for t in db.list_trends()[:30]:
            print(f"{t['score']:>3}  {t['id']:<28} {t['title_fr']}")
    elif cmd == "produce":
        from . import channels, pipeline
        t = db.get_trend(argv[1])
        if not t:
            sys.exit(f"Trend not found: {argv[1]}")
        pid = db.create_project(t["id"], t["title_fr"] or t["title_zh"])
        channels.attach(pid, channels.pick(None), news=True)
        print(f"Project #{pid} → {config.PROJECTS / str(pid)}")
        pipeline.produce(pid)
        print(json.dumps(db.get_project(pid)["meta"], ensure_ascii=False, indent=1))
    elif cmd == "topic":  # topic "<chủ đề>" [link …]; chủ đề "" = chỉ dùng link
        from . import channels, pipeline, topic
        try:
            pid = topic.create(argv[1] if len(argv) > 1 else "", argv[2:])
        except ValueError as e:
            sys.exit(str(e))
        channels.attach(pid, channels.pick(None))
        print(f"Project #{pid} → {config.PROJECTS / str(pid)}")
        pipeline.produce(pid)
        print(json.dumps(db.get_project(pid)["meta"], ensure_ascii=False, indent=1))
    elif cmd == "ai":  # ai "<chủ đề>" [giây] [số clip AI] [review]: video toàn ảnh AI (+ vài clip AI)
        from . import channels, creator, pipeline
        rest = [a for a in argv[2:] if a != "review"]  # "review": stop after the pictures (then `approve`)
        try:
            pid = creator.create(argv[1] if len(argv) > 1 else "", int(rest[0]) if rest else 80,
                                 int(rest[1]) if len(rest) > 1 else None, review_shots="review" in argv[2:])
        except ValueError as e:
            sys.exit(str(e))
        channels.attach(pid, channels.pick(None))
        print(f"Project #{pid} → {config.PROJECTS / str(pid)}")
        pipeline.produce(pid)
        print(json.dumps(db.get_project(pid)["meta"], ensure_ascii=False, indent=1))
    elif cmd == "clipcheck":  # clipcheck <ảnh> ["<cảnh>"] [fal | heygen]: thử một clip 5 s (tốn tiền), so nhà cung cấp
        from pathlib import Path

        from . import aiclips
        pic = Path(argv[1]) if len(argv) > 1 else None
        if not pic or not pic.is_file():
            sys.exit('Usage: clipcheck <picture file> ["<what is in the scene>"] [fal | heygen]')
        scene, name = aiclips.trial_args(argv[2:])
        try:
            path, usd = aiclips.trial(pic, aiclips.prompt(scene, "zoom_in"), name, config.DATA / "clipcheck")
        except (ValueError, aiclips.ClipError) as e:
            sys.exit(str(e))
        print(f"{path} · about ${usd:.2f}")
    elif cmd == "dub":  # dub <link> [đầu cuối]: lồng tiếng Pháp một video
        from . import channels, dub, pipeline
        try:
            pid = dub.create(argv[1] if len(argv) > 1 else "", *(argv[2:4]))
        except ValueError as e:
            sys.exit(str(e))
        channels.attach(pid, channels.pick(None))
        print(f"Project #{pid} → {config.PROJECTS / str(pid)}")
        pipeline.produce(pid)
        print(json.dumps(db.get_project(pid)["meta"], ensure_ascii=False, indent=1))
    elif cmd == "watch":  # watch "<link kênh / playlist | từ khoá>" [youtube | bilibili]: thêm nguồn rồi kiểm tra
        from . import watch
        try:
            wid = watch.add(argv[1] if len(argv) > 1 else "", argv[2] if len(argv) > 2 else "youtube")
        except ValueError as e:
            sys.exit(str(e))
        print(json.dumps(watch.check_all([wid]), ensure_ascii=False, indent=1))
        _print_clips(wid)
    elif cmd == "check":  # kiểm tra mọi nguồn theo dõi đang bật
        from . import watch
        print(json.dumps(watch.check_all(), ensure_ascii=False, indent=1))
    elif cmd == "clips":
        _print_clips()
    elif cmd == "rerender":
        from . import pipeline
        pipeline.rerender(int(argv[1]))
        print(json.dumps(db.get_project(int(argv[1]))["meta"], ensure_ascii=False, indent=1))
    elif cmd == "retry":  # chạy tiếp từ bước lỗi, hoặc từ bước chỉ định (search … voice, render = giữ giọng)
        from . import pipeline
        pipeline.resume(int(argv[1]), argv[2] if len(argv) > 2 else None)
        print(json.dumps(db.get_project(int(argv[1]))["meta"], ensure_ascii=False, indent=1))
    elif cmd == "approve":  # duyệt dự án đang chờ: kịch bản → đọc giọng và dựng; video → gửi Postiz (nosend: không gửi)
        from . import pipeline
        pid = int(argv[1])
        review = (db.get_project(pid) or {"meta": {}})["meta"].get("review")
        if review == "script":
            db.update_project(pid, log="Script approved", meta={"review": None})
            pipeline.produce(pid, start="voice")
        elif review == "shots":
            from . import shots
            try:
                shots.approve_all(pid)
                shots.check_continue(pid)
            except (ValueError, shots.NotWaiting) as e:
                sys.exit(str(e))
            db.update_project(pid, log="Pictures approved", meta={"review": None})
            pipeline.produce(pid, start="voice")
        elif review == "video":
            pipeline.approve_video(pid, send=argv[2:3] != ["nosend"])
        else:
            sys.exit(f"Project #{pid} is not awaiting approval")
        p = db.get_project(pid)
        print(f"#{pid}: {p['status']} · {p['step']}")
    elif cmd == "delete":  # xoá dự án + thư mục của nó; giữ cache video nguồn
        from . import edit
        try:
            edit.delete(int(argv[1]))
        except (LookupError, edit.Busy, OSError) as e:
            sys.exit(str(e))
        print(f"Deleted project #{argv[1]}")
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


def _print_clips(watch_id: int | None = None) -> None:
    for c in db.list_clips("new", watch_id, 30):
        score = "" if c["score"] is None else c["score"]
        print(f"{score:>3}  {c['id']:<28} {c['title_fr'] or c['title']}  ({c['watch_name']})")


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def engine(argv: list[str]) -> None:
    """Chạy engine API. In đúng một dòng JSON {"event":"ready",...} ra stdout khi đã nhận kết nối."""
    ap = argparse.ArgumentParser(prog="motio engine")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    ap.add_argument("--token", default=os.getenv("MOTIO_TOKEN", ""),
                    help="required when --host is not loopback; defaults to MOTIO_TOKEN (server, Docker)")
    ap.add_argument("--headless", action="store_true", help="run in the background 24/7 (Windows machine)")
    ap.add_argument("--exit-with-stdin", action="store_true",
                    help="exit when stdin closes (the parent app died); used when the desktop app starts the engine")
    a = ap.parse_args(argv)
    if a.host not in LOOPBACK and not a.token:
        sys.exit("--token is required when --host is not loopback")

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
