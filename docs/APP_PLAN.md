# Motio — desktop app plan

Goal: one app that runs on **macOS (Apple Silicon)** and **Windows (x64)**. A Python **engine** does the
work (existing code in `motio/`); a **Tauri 2 + React + TypeScript** shell is the UI. The engine can run
next to the app, or headless 24/7 on the Windows box, with the Mac app pointing at it over Tailscale.

```
Motio app (Tauri + React)                    Motio engine (Python, FastAPI)
  macOS .dmg / Windows .msi   ── HTTP ──▶     trends · sources · Whisper · Claude · ElevenLabs
  Tin hot · Dự án · Cài đặt   127.0.0.1       FFmpeg render · scheduler · (later) Drive + Slack
```

Stack decisions: Tauri 2, React 19 + Vite + TypeScript, Tailwind + shadcn/ui, TanStack Query.
Engine: FastAPI, SQLite, uv. No auto-publishing to social platforms in this plan.

---

## M1 — Engine API (Python only, no Rust needed) · branch `feat/engine-api`

1. **`motio/api.py`** — JSON-only FastAPI app replacing the Jinja dashboard (keep `web.py` until M2 ships).
   Auth: random token, `Authorization: Bearer <token>`; `?token=` accepted only for `/media` and SSE.
   CORS for `tauri://localhost`, `http://tauri.localhost`, `http://localhost:1420`.
   - `GET  /api/health` → version, platform, active providers (llm, tts, asr), ffmpeg found, claude CLI found
   - `GET  /api/trends?hours=24&source=` · `POST /api/trends/refresh` (async) · `GET /api/state`
   - `POST /api/trends/{id}/produce` → `{project_id}`
   - `GET  /api/projects` · `GET /api/projects/{id}` · `POST /api/projects/{id}/rerender`
   - `POST /api/projects/{id}/retry` `{start?}` — continue from the failed step, or redo from a given step (added 26/09)
   - `GET  /api/projects/{id}/events` — SSE stream of `{status, step, pct, log_tail}`
   - `GET  /api/voices` — ElevenLabs voices (id, name, labels) when a key is set
   - `GET/PUT /api/settings` — see 4.
   - `GET  /media/{path}` — files under `data/`
2. **Engine entrypoint** `python -m motio engine --host 127.0.0.1 --port 0 --token <t> [--headless]`:
   binds a free port, prints exactly one JSON line to stdout `{"event":"ready","port":N,"version":"…"}`,
   then serves. `--host 0.0.0.0` (remote mode) requires `--token`.
3. **Jobs**: keep the single worker queue; on startup mark stale `running` projects `failed` with a log line.
4. **Settings** `motio/settings.py`: `data/settings.json` layered over `.env`; read at call time so changes
   apply without restart. Keys: `LLM_PROVIDER`, `LLM_MODEL`, `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`,
   `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`, `WHISPER_MODEL`, `NEWS_SOURCES`, `CREDIT_ON_VIDEO`,
   `CREDIT_IN_POST`, `MAX_VIDEOS_PER_DAY`. Secrets are returned masked (`••••1234`); PUT accepts new values.
5. **Cross-platform fixes**
   - Fonts: lookup helper with macOS, Windows (`C:\Windows\Fonts\arialbd.ttf`, `msyhbd.ttc`), Linux paths.
   - `config.which()`: Windows `.exe`/`.cmd` (`claude.cmd`), `%LOCALAPPDATA%`, env overrides
     `MOTIO_FFMPEG`, `MOTIO_FFPROBE`, `MOTIO_CLAUDE`, and a bundled `bin/` next to the engine.
   - TTS: no ElevenLabs key and not macOS → clear error that the UI can show.
   - ASR: faster-whisper picks `cuda` if available, else `cpu` with `int8`.
   - Enforce `MAX_VIDEOS_PER_DAY` in `produce`.
6. **Tests** (pytest): `caption_chunks`, `build_timeline`, `split_by_captions`, `llm.parse_json`,
   `newsnow.safe_id`, settings masking, API routes with `TestClient` and a mocked pipeline. Add `ruff`.

**Done when**: `uv run pytest` passes; `uv run python -m motio engine --port 0 --token t` prints the ready
line; with the token, `/api/trends` lists topics and `/api/trends/{id}/produce` renders a video end to end on macOS.

## M2 — Desktop app · branch `feat/desktop-app`

Prerequisite: Rust toolchain (`brew install rustup && rustup-init -y`). **Ask the owner before installing.**

1. Scaffold `app/` (Tauri 2, React TS, Vite, pnpm), Tailwind + shadcn/ui, TanStack Query, react-router.
2. **Engine lifecycle** (`src-tauri/src/engine.rs`): on launch spawn the engine — dev: `uv run python -m motio
   engine --port 0 --token <random>` from the repo root; prod (M3): sidecar `motio-engine`. Read stdout until the
   ready line, keep port + token in state, expose `engine_info()` command, kill the child on exit.
   Setting "Engine từ xa" (URL + token) skips spawning.
3. **Screens** (Vietnamese UI, sidebar layout, follows OS light/dark):
   - **Tin hot** — score badge, FR title, ZH title, source, angle; filter by source; "Cập nhật tin"; "Làm video".
   - **Dự án** — list with thumbnails and status chips; detail with progress bar, step, live log (SSE),
     9:16 video player, post text + "Copy", "Dựng lại", "Mở thư mục".
   - **Cài đặt** — engine local/remote, LLM provider + model, API keys (masked), ElevenLabs voice picker
     (`/api/voices`), Whisper model, credit toggles, max videos/day, engine health panel.
4. Native notification when a project finishes or fails (`tauri-plugin-notification`).

**Done when**: `pnpm tauri dev` on macOS opens the app, the engine starts by itself, and you can refresh topics,
produce a video, follow progress and play the result.

## M3 — Packaging & CI · branch `feat/packaging`

- Freeze the engine with PyInstaller (onedir) as a Tauri sidecar (`externalBin`), per OS; ship ffmpeg/ffprobe
  in `bin/`. macOS build includes mlx-whisper; Windows build includes faster-whisper.
- GitHub Actions matrix (`macos-14`, `windows-latest`): build engine → `pnpm tauri build` → upload `.dmg` and
  `.msi` on tags `v*`. No code signing yet.

**Done when**: CI produces both installers; the Windows build produces a video with ElevenLabs + faster-whisper (CPU).

## M4 — Automation (later)

Scheduler (refresh every 60 min, optional auto-produce above a score, daily cap), Google Drive delivery (rclone),
Slack app in Socket Mode with buttons [Làm video] [Duyệt] [Làm lại], `--headless` mode for the always-on Windows PC.

## Server + Postiz (added 26/09/2026)

Engine in Docker on a Hetzner server next to a self-hosted Postiz, behind Caddy (`deploy/`, `docs/DEPLOY.md`).
The desktop app uses it as a remote engine. Posting goes through Postiz's Public API only: a finished project can be
sent as a draft, scheduled or posted now (`POST /api/projects/{id}/publish`). Postiz owns OAuth, calendars and the
platform APIs.

## In-app updates (added 26/09/2026)

The desktop app updates itself from GitHub Releases with Tauri's updater plugin: it checks the latest published
release on launch and from Cài đặt → "Cập nhật ứng dụng", then downloads, verifies the signature and restarts. The repo
is private, so each install keeps a read-only GitHub token (fine-grained, Contents: Read) in its config dir; nothing is
compiled into the app. `release.yml` signs the update bundles (`TAURI_SIGNING_PRIVATE_KEY` secret) and attaches
`latest.json`, whose bundle URLs are GitHub API asset URLs.

## Out of scope for now

Motio calling TikTok / Reels / YouTube / X APIs directly (Postiz does it) · auto-sending every finished video to
Postiz (belongs with the M4 scheduler) · channel-scan "Pháp hoá" mode · AI clips (fal H3 Max) and Qwen images
(Modal) inside the pipeline.
