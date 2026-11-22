# Motio

A personal desktop app (macOS, Windows) that turns trending Chinese videos and news, or any topic or video link,
into French 9:16 videos. A Python engine does the work; the app drives it.

**Pipeline:** find a source (yt-dlp, Douyin through f2) → transcribe (Whisper) → French script (Claude) → voice
(ElevenLabs) → render (Pillow overlays + FFmpeg) → optional approval gates → send to [Postiz](https://postiz.com).

The app UI is English or Vietnamese (Settings → Language). The videos are always French.

## Quick start

**Desktop app (dev):**

```bash
uv sync                       # engine deps, first time only
brew install deno             # yt-dlp needs a JavaScript runtime for YouTube
cd app && pnpm install
pnpm tauri dev                # needs Rust; the app starts the engine with uv
```

The app finds `uv` on PATH, `~/.local/bin`, `~/.cargo/bin` and Homebrew (`MOTIO_UV` overrides). Settings → *Remote
engine* points the app at an engine on another machine (URL + token).

**Installed app:** download the `.dmg` / `.msi` from GitHub Releases. Enter your `ANTHROPIC_API_KEY` (and ElevenLabs
key) in Settings. The installers are not code-signed: on macOS use System Settings → Privacy & Security → *Open
Anyway*; on Windows, *More info* → *Run anyway*. The app updates itself from published releases.

**Legacy web dashboard:** `uv run python -m motio serve`, then open http://127.0.0.1:8765.

## What it makes

Every video lasts 62–90 s. A few modes have another length (noted below).

| Mode | Where | What you get |
|---|---|---|
| Explainer | Projects → New video, or *Make video* on a Trending / Followed video | A French explainer from a topic and/or video links (70 / 80 / 90 s) |
| French dub | New video → *French dub* | One video dubbed in French; pictures, music and sounds kept. *Whole video* keeps the full length |
| AI video | New video → *AI video* | Scenes drawn by an image model (no source footage); any length 30 s–30 min |
| Clip | New video → *Clip*, or Clip Studio | The best moments of a long video as vertical clips with the original sound (15–90 s) |
| News | News topics (off by default, `NEWS_TOPICS`) | A French video from a NewsNow hot topic |

Around them:

- **Trending / Followed / Scan**: find videos by category, tag, account or keyword on Bilibili, Douyin, Kuaishou,
  Weibo, AcFun, Pear Video and YouTube; follow channels and searches.
- **Channels**: one profile per channel you post to (badge, script style, voice, hashtags, approval gates, Postiz
  auto-send, automatic making).
- **Project page**: edit the script, hide burned-in text or a watermark, mirror / colour filter, original sound
  level, re-render, delete.
- **Tools**: download, transcribe, translate subtitles, read aloud, burn subtitles, remove a logo.
- **Stats** and **Slack alerts**: costs per project / channel against a monthly budget; a message when a video
  waits, is done or fails.
- **Google Drive** as main storage for finished projects and idle sources.

Details of every feature: [docs/FEATURES.md](docs/FEATURES.md).

## Command line

```bash
uv run python -m motio refresh | trends | check | clips | automake
uv run python -m motio produce <trend_id>
uv run python -m motio topic "<topic>" [link ...]
uv run python -m motio ai "<topic>" [seconds] [ai clips]
uv run python -m motio dub <link> [start end | whole]
uv run python -m motio clip <link> [count]
uv run python -m motio watch "<channel link | search words>" [bilibili]
uv run python -m motio rerender <project>
uv run python -m motio retry <project> [step]       # step: search|download|transcribe|script|voice|render
uv run python -m motio approve <project> [nosend]
uv run python -m motio delete <project>
```

## Configuration

Settings changed in the app go to `data/settings.json` and override `.env`; they apply at once. The main ones:

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key (required; every script, translation and score is an API call) |
| `LLM_MODEL` / `LLM_MODEL_FAST` | Main model (default `claude-opus-5-5`) / fast model for scoring (default `claude-haiku-5-5`) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | French voice; leave the voice empty to pick one from the account |
| `WHISPER_MODEL` | Default `mlx-community/whisper-large-v3-turbo` |
| `REFRESH_EVERY_MIN` | Refresh trends and check followed sources every N minutes (0 = manual; 30 on the server) |
| `UI_LANG` | `en` (default) / `vi`: language of the engine's messages |
| `YTDLP_COOKIES_FILE` / `YTDLP_COOKIES_FROM_BROWSER` | Cookies for sites that need them: a `cookies.txt` (for an engine without a browser) or `chrome` / `safari` / `firefox` / `edge` / `brave` |
| `POSTIZ_URL`, `POSTIZ_API_KEY` | Postiz API root + key, for posting |
| `IMAGE_PROVIDER`, `FAL_KEY`, `FAL_IMAGE_MODEL`, `IMAGE_STYLE` | Pictures for AI videos: `fal` (default) / `modal` / `placeholder` |
| `CLIP_PROVIDER`, `HEYGEN_API_KEY`, `AI_CLIP_USD_PER_SEC` | AI clips: `fal` (default) or `heygen`; price used for the cost estimate |
| `DRIVE_ON`, `DRIVE_CLIENT_ID`, `DRIVE_CLIENT_SECRET`, `DRIVE_FOLDER`, `DRIVE_KEEP_LOCAL` | Google Drive storage ([docs/GOOGLE_DRIVE.md](docs/GOOGLE_DRIVE.md)) |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook for alerts; empty = off |
| `NEWSNOW_URL`, `NEWS_TOPICS` | Self-hosted NewsNow; `true` brings back hot news next to Trending (default off) |
| `MOTIO_FFMPEG`, `MOTIO_FFPROBE`, `MOTIO_DENO`, `MOTIO_CHROME` | Binary paths if not on PATH |

Data (SQLite, sources, projects) lives in `data/`; packaged builds use `~/Library/Application Support/Motio`
(macOS) or `%APPDATA%\Motio` (Windows).

## Engine API

```bash
uv run python -m motio engine --port 0 --token <t>   # prints {"event":"ready","port":N,...}, then serves
```

Every `/api/*` route needs `Authorization: Bearer <t>`; `/media/*` and the SSE route also accept `?token=`.
`--host 0.0.0.0` requires `--token`. `--exit-with-stdin` exits when the parent app closes.

## More docs

| Doc | Topic |
|---|---|
| [docs/FEATURES.md](docs/FEATURES.md) | What each feature does and how to use it |
| [docs/RELEASING.md](docs/RELEASING.md) | Build, CI, releases, auto-update, signing key |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Hetzner server with Postiz (Vietnamese) |
| [docs/WINDOWS_SERVER.md](docs/WINDOWS_SERVER.md) | Engine on a Windows PC at home (Vietnamese) |
| [docs/GOOGLE_DRIVE.md](docs/GOOGLE_DRIVE.md) | Google Drive storage |
| [docs/CN_PLATFORMS.md](docs/CN_PLATFORMS.md), [docs/DOUYIN_F2.md](docs/DOUYIN_F2.md) | Chinese platforms, Douyin through f2 |
| [docs/APP_PLAN.md](docs/APP_PLAN.md), [docs/DESIGN.md](docs/DESIGN.md) | Plan and milestones, UI look |

## Content rules

An original French voice-over with context; source clips only illustrate it. The post says "Voix off générée par
IA." (AI videos add "Images générées par IA."), and the platforms' AI flags stay on. There is no AI label on the
video itself. Every project writes `sources.txt`; sources are not shown on the video or in the post.
