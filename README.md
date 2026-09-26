# Motio · hot-news MVP

Motio turns trending Chinese news (NewsNow hot lists) into French 9:16 videos. A Python engine does the work and a
desktop app (macOS, Windows) drives it: it finds source clips on YouTube and Bilibili, transcribes them with Whisper,
has Claude write a French voice-over script and pick the clip segments, voices it with ElevenLabs, and renders it with
FFmpeg (blurred background, captions, optional source labels, AI-voice disclosure). The app UI is in Vietnamese; the
videos are in French.

## Run on a Mac (legacy web dashboard)

```bash
cd ~/Works/motio
uv sync                             # first time only
uv run python -m motio serve        # open http://127.0.0.1:8765
```

1. Click **Cập nhật tin hot** (refresh hot topics): fetches the Douyin, Weibo, Baidu, Bilibili, Toutiao and The Paper
   lists; Claude translates the titles into French and scores them for a French audience.
2. Pick a topic and click **Làm video** (make video). The project page shows progress, the log, the video and the post
   text (title, description, sources, hashtags).

Command line: `uv run python -m motio refresh`, `... trends`, `... produce douyin:2644652`, `... rerender <project>`.

## Desktop app (Tauri)

```bash
cd app && pnpm install
pnpm tauri dev        # opens the app; it starts the engine with uv from the repo root
```

Needs Rust (`rustup`). The app looks for `uv` on PATH, in `~/.local/bin`, `~/.cargo/bin` and Homebrew; set `MOTIO_UV`
if it lives elsewhere. Settings (Cài đặt) → "Engine từ xa" (remote engine) uses an engine on another machine (URL +
token); the app then doesn't start its own engine.

## Packaging, CI and releases

```bash
uv run --group build python tools/build_engine.py   # PyInstaller engine + static ffmpeg → app/src-tauri/resources/
cd app && pnpm tauri build                          # Motio.app + .dmg (macOS) or .msi (Windows)
```

`tauri build` / `tauri dev` need the folder `app/src-tauri/resources/motio-engine/` (it can stay empty for dev: the
debug build still runs the engine with `uv` from the repo). Packaged builds keep their data in
`~/Library/Application Support/Motio` (macOS) or `%APPDATA%\Motio` (Windows). `claude -p` still needs Claude Code
installed on the machine; without it, pick "Anthropic API" in Settings.

- **CI** (`.github/workflows/ci.yml`, on every PR and every push to `master`): the engine runs `ruff check` + `pytest`
  on Ubuntu and Windows; the app runs `pnpm build` (tsc + vite) and `cargo clippy`.
- **Releases** (`.github/workflows/release.yml`): bump `version` in `app/src-tauri/tauri.conf.json` and
  `app/package.json`, then `git tag vX.Y.Z && git push origin vX.Y.Z` (the tag must match that version). CI freezes the
  engine, builds the `.dmg` (macOS Apple Silicon) and the `.msi` / `.exe` (Windows), and creates a draft GitHub Release
  for you to check and Publish.
- The installers are not code-signed: on macOS, open the app the first time via System Settings → Privacy & Security →
  "Open Anyway"; on Windows, click "More info" → "Run anyway". The installers bundle the engine; to use an engine on
  another machine, go to Settings → "Engine từ xa".
- **Auto-update** (Settings → "Cập nhật ứng dụng"): the app checks GitHub Releases on launch and when you click
  "Kiểm tra cập nhật" (check for updates), downloads the new version, verifies its signature and restarts itself. Only
  published releases are offered. The repo is public, so the GitHub token field in that card can stay empty.
- Update signing key, one time: `cd app && pnpm tauri signer generate -w ~/.tauri/motio-updater.key`, then
  `gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/motio-updater.key` and
  `gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD`. The public key (`~/.tauri/motio-updater.key.pub`) goes in
  `plugins.updater.pubkey` in `app/src-tauri/tauri.conf.json`. Without the secret a release tag fails; if the private
  key is lost, installed apps can no longer update themselves (they have to be reinstalled by hand).

## Engine API (for the desktop app)

```bash
uv run python -m motio engine --port 0 --token <t>   # prints {"event":"ready","port":N,...} then serves
```

Every `/api/*` route needs `Authorization: Bearer <t>`; `/media/*` and `/api/projects/{id}/events` (SSE) also accept
`?token=`. `--host 0.0.0.0` (remote use) requires `--token`. `--exit-with-stdin` exits when the parent app closes.

## Running on a server (Hetzner + Postiz)

`deploy/` holds the Docker Compose stack for the engine + [Postiz](https://postiz.com) (automatic posting) behind
Caddy (HTTPS); the "Deploy (Hetzner)" workflow builds the image and updates the server. Steps:
[docs/DEPLOY.md](docs/DEPLOY.md) (in Vietnamese). On the server the engine reads its token from `MOTIO_TOKEN` and
defaults to `LLM_PROVIDER=anthropic`.

## Configuration (.env)

Settings changed in the app are saved to `data/settings.json`, override `.env` and take effect immediately.

| Variable | Meaning |
|---|---|
| `LLM_PROVIDER` | `claude_cli` (Claude Code on the Mac, uses your Claude plan) or `anthropic` (API key, for the server) |
| `LLM_MODEL` | `sonnet` / `opus` with claude_cli; full model ID via `ANTHROPIC_MODEL` with anthropic |
| `ANTHROPIC_API_KEY` | API key for the `anthropic` provider (never passed to `claude -p`) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | French voice; leave the voice empty to let the app pick a French voice from the account |
| `ELEVENLABS_MODEL` | Default `eleven_multilingual_v2` |
| `WHISPER_MODEL` | Default `mlx-community/whisper-large-v3-turbo` |
| `NEWSNOW_URL`, `NEWS_SOURCES` | Self-hosted NewsNow (`http://newsnow:4444`) on the server |
| `MAX_VIDEOS_PER_DAY` | Daily video cap (0 = no limit) |
| `CREDIT_ON_VIDEO`, `CREDIT_IN_POST` | Show source credits on the video / in the post (default off; `sources.txt` is always written) |
| `POSTIZ_URL`, `POSTIZ_API_KEY` | Postiz for posting: API root (`https://postiz.<domain>/api`) + Public API key |
| `MOTIO_FFMPEG`, `MOTIO_FFPROBE`, `MOTIO_CLAUDE` | Binary paths if they are not on PATH |

Data (SQLite, source videos, projects) lives in `data/`.

## Layout

```
motio/newsnow.py   fetch hot topics + translate + score
motio/search.py    yt-dlp search / download of sources (keeps platform, channel, license)
motio/asr.py       Whisper (mlx on the Mac, faster-whisper elsewhere)
motio/llm.py       claude -p or the Claude API
motio/tts.py       ElevenLabs with timestamps (macOS voice when there is no key)
motio/render.py    9:16 render: Pillow draws the text, FFmpeg composes
motio/pipeline.py  the steps of one project
motio/settings.py  data/settings.json over .env
motio/api.py       JSON engine API for the desktop app
motio/postiz.py    send videos to Postiz (draft / scheduled / post now)
motio/web.py       legacy dashboard (to be removed)
```

## Built-in content rules

An original French voice-over with context and analysis; source clips only illustrate it, 3–6 seconds each; the “Voix
de synthèse (IA)” label stays on the video and the post says “Voix off générée par IA.” Every project writes
`sources.txt` with all source links; the on-video “Source : platform / channel” label and the source list in the post
are optional (`CREDIT_ON_VIDEO`, `CREDIT_IN_POST`, default off).
