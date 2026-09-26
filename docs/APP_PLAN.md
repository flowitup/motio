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
   - `GET  /api/health` → version, platform, active providers (llm, tts, asr), ffmpeg, JS runtime (deno) and claude CLI found
   - `GET  /api/trends?hours=24&source=` · `POST /api/trends/refresh` (async) · `GET /api/state`
   - `POST /api/trends/{id}/produce` → `{project_id}`
   - `GET  /api/projects` · `GET /api/projects/{id}` · `POST /api/projects/{id}/rerender`
   - `POST /api/projects/{id}/retry` `{start?}` — continue from the failed step, or redo from a given step (added 26/09)
   - `POST /api/projects` `{topic?, links?, links_only, duration, rights}` — explainer on any topic or from video
     links, no trend needed · `PATCH /api/projects/{id}` `{rights}` (added 26/09, see "Beyond hot news")
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
release on launch and from Cài đặt → "Cập nhật ứng dụng", then downloads, verifies the signature and restarts.
`release.yml` signs the update bundles (`TAURI_SIGNING_PRIVATE_KEY` secret) and attaches `latest.json`; the app reads it
from `releases/latest/download/latest.json` and downloads the bundles from the tag's public download links. 0.3.0 needed
a read-only GitHub token while the repo was private; since 0.3.1 (repo public) there is no token, and the app deletes the
old `updater.json` on launch.

## Blueprint GĐ0 additions (added 26/09/2026)

The rest of the blueprint's GĐ0 (news MVP), agreed with the owner on 26/09:

- **Retry a failed step**: `produce` runs as steps (search → download → transcribe → script → voice + render), each
  saving what the next needs, so a failed project continues where it broke (`POST /api/projects/{id}/retry`).
- **French karaoke captions**: word timings from the ElevenLabs alignment, cues of ≤ 2 lines of ≤ 42 characters that
  also fit the frame, French typography (non-breaking space before `: ; ! ?`, « » quotes, ’). Still drawn with Pillow;
  the caption layer is one timed PNG stream overlaid in the final pass. Each project also gets `captions.srt` and
  `captions.ass` (karaoke `\kf` tags).
- **Scene cuts**: FFmpeg's scene filter (`motio/scenes.py`, cached next to each source) instead of PySceneDetect, so
  no OpenCV. Clip pieces start on a cut just after their in-point, stop before a cut just ahead of their out-point,
  and filler clips start at the head of a shot.
- **Douyin and X sources**: yt-dlp has no search for either (X also needs a login), so videos can be pasted as links
  (any site yt-dlp downloads) when producing (`links`, `links_only` on `POST /api/trends/{id}/produce`) or added to a
  project (`POST /api/projects/{id}/links`, then it re-runs from the download step). Pasted links always go in;
  YouTube/Bilibili search fills the remaining slots. `YTDLP_COOKIES_FROM_BROWSER` lets yt-dlp use a local browser
  session for those links.
- **Scheduled refresh + self-hosted NewsNow**: the engine refreshes hot topics every `REFRESH_EVERY_MIN` minutes
  (0 = off, the desktop default; 30 on the server) and `/api/state` reports the next run. `NEWSNOW_URL` is a setting
  read at call time; `deploy/compose.yaml` runs NewsNow (`ghcr.io/ourongxing/newsnow`) next to the engine.
  Auto-produce above a score stays with the rest of M4.

## Beyond hot news: any topic, any video (added 26/09/2026)

The owner wants Motio to remake other people's Douyin, Bilibili, Facebook and YouTube videos on any subject, not
only hot news. Agreed order (brainstorm 26/09): **A** topic mode → **B** channel watchlist → **C** French dub.

- **A · Topic mode** (built): "Tạo video" on the Projects page, `POST /api/projects`, CLI `topic "<chủ đề>" [link …]`.
  A free topic in any language and/or 1–10 video links. Claude turns the topic into a French title, an angle and
  ZH/EN/FR keywords (`motio/topic.py`), YouTube + Bilibili search fills the slots the links leave, and the script is
  an original French explainer (subject-neutral prompts; news projects keep theirs). With links only, search is
  skipped. Length 70 / 80 / 90 s (`meta.duration`). Every project carries a rights flag
  (`unknown` default / `owned` / `licensed` / `cc`), editable on the project page. Tin hot scoring and the news script no longer favour hard
  news: light themes (food, animals, tech, travel, culture, oddities) score as high when they're visual.
- **B · Watchlist** (next, own brainstorm): YouTube channels/playlists, Bilibili user spaces and saved searches feed a
  "Video mới" list via the scheduler. yt-dlp can only download single Douyin/Facebook videos, so those stay links.
- **C · French dub** (after B): the source's pictures with French speech (Demucs, tu/vous, burned captions). Postiz
  only for `owned` / `licensed` / `cc` sources: a dub of someone else's video is reused content on every platform.

## Video length: 62–90 s (added 26/09/2026)

The owner's rule: every video lasts at least 1 min 2 s. The top is 90 s because Facebook Reels published through the
Graph API accept 3–90 s (checked 26/09: YouTube Shorts allow 3 min, Instagram Reels via API 15 min, TikTok per
creator, X 140 s on free accounts). `pipeline.MIN_SECONDS = 62`, `MAX_SECONDS = 90`, default target 80 s; older
30 / 60 s targets are raised to 70.

- Script: word count from the target at 2.5 words/s; a script that can't reach 62 s is lengthened before the voice.
- Voice: if narration + 0.6 s falls outside 62–90 s, Claude rewrites once to the word count the measured speech rate
  needs, and it is read again (rerender does the same, so old projects come out ≥ 62 s).
- Render: still short → the last shot continues with source footage up to 62 s (captions end with the voice);
  still over 90 s → a log line warns that Facebook Reels (API) won't take it.

## Out of scope for now

Motio calling TikTok / Reels / YouTube / X APIs directly (Postiz does it) · auto-sending every finished video to
Postiz (belongs with the M4 scheduler) · AI clips (fal H3 Max) and Qwen images
(Modal) inside the pipeline.
