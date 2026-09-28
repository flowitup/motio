# Motio · hot-news MVP

Motio turns trending Chinese news (NewsNow hot lists) into French 9:16 videos. A Python engine does the work and a
desktop app (macOS, Windows) drives it: it finds source clips on YouTube and Bilibili, transcribes them with Whisper,
has Claude write a French voice-over script and pick the clip segments, voices it with ElevenLabs, and renders it with
FFmpeg (blurred background, captions, optional source labels, AI-voice disclosure). The app UI is in English or
Vietnamese (Settings → Language); the videos are in French.

## Run on a Mac (legacy web dashboard)

```bash
cd ~/Works/motio
uv sync                             # first time only
brew install deno                   # yt-dlp needs a JavaScript runtime to download YouTube videos
uv run python -m motio serve        # open http://127.0.0.1:8765
```

1. Click **Refresh**: fetches the Douyin, Weibo, Baidu, Bilibili, Toutiao and The Paper
   lists; Claude translates the titles into French and scores them for a French audience.
2. Pick a topic and click **Make video**. The project page shows progress, the log, the video and the post
   text (title, description, sources, hashtags).

Beyond hot news: in the app, **Projects → New video** takes any topic, in any language, and/or
video links (Douyin, Bilibili, Facebook, YouTube…) and makes a 70 / 80 / 90-second French explainer.
Every video (news or topic) lasts 62–90 s: at least 1 min 2 s, at most the 90 s Facebook Reels takes through its API.

**New videos** follows YouTube channels and playlists, Bilibili user spaces and saved searches on YouTube or
Bilibili. Motio checks them on the `REFRESH_EVERY_MIN` schedule or with "Check now"; a new source shows
its latest 10 videos, then only videos it hasn't seen. Claude gives each one a French title and a score, and
"Make video" makes a French explainer from it. Douyin and Facebook accounts can't be followed (yt-dlp only downloads
single videos there): paste those links into "New video". Bilibili spaces often need the browser-cookie setting.

**Channels** holds one profile per channel you post to: the red badge on the video ("ACTU CHINE", "INSOLITE",
or none), style notes Claude follows when it writes the script, the ElevenLabs voice, the default length for hot-news
videos, hashtags that always go first, and two approval gates. With the script gate on, a project stops at **Awaiting
script approval** until you read it, edit it if needed, and press **Approve and continue**; with the video gate on, a
finished video stops at **Awaiting video approval** until you press **Approve and send**. A profile can also send
the approved video to its Postiz channels by itself, as a draft, at the channel's next free posting time, or right
away (once per project; later re-renders don't post again). Tick **16:9** next to a Postiz channel (a YouTube channel
for regular videos, say) and Motio also renders a 16:9 copy of each video with the same cut, voice and captions, and
sends that copy to those channels. Turn on **Make videos automatically** and, after each scheduled refresh, Motio
makes a video for that channel from every new trending topic at or above the minimum score, up to the videos per day
you set (the daily limit in Settings still applies); these videos stop at the channel's approval gates like any other
and are marked "Made automatically". Pick the channel when you make a video (Trending, New
videos, New video); the default channel is preselected, and videos without a channel run straight through as before.
Without a channel, hot-news videos carry the "ACTU CHINE" badge and topic explainers carry none.

On a project's page you can also edit the script (the title shown on the video, each voice-over line, the post
description and hashtags) and re-voice + re-render from your edit, rerun from any step, or delete the project.

**Remove logo** cleans a static logo or watermark off one of your own videos: pick a project's source clip
or upload a file, draw a box around the logo on a frame (or press **Auto-detect** to find logos that stay in place), then
press **Remove logo**. The LaMa AI model redraws what was behind the logo on every frame.
The first run downloads the model once (92 MB, [LaMa](https://github.com/advimman/lama) exported by
[OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/inpainting_lama), Apache 2.0) into `data/models/`.
It runs on the CPU: still shots go fast (the fill is reused while the picture behind the logo doesn't change), moving
shots take a few minutes per minute of video. So on a project's clip it cleans only the parts the final video uses
(plus a few seconds either side), which turns hours into minutes on a long news clip; an uploaded file can be cleaned
whole (**Whole video**) or in one part (**One part**, from–to). The page shows the time left and a Stop button. A project
clip is replaced by its clean copy and **Re-render video (keep voice)** renders the video again with the voice it
already has (no new ElevenLabs call); if a later render uses a part that wasn't cleaned, the project log and the page
say so. The original is kept and can be restored. An uploaded file gives you a cleaned copy. It never runs by itself
in the pipelines.

Command line: `uv run python -m motio refresh`, `... trends`, `... produce douyin:2644652`,
`... topic "giant pandas" [link …]`, `... watch "<channel link | search words>" [bilibili]`, `... check`, `... clips`,
`... rerender <project>`, `... retry <project> [step]` (continue from the failed
step, or redo from `search` / `download` / `transcribe` / `script` / `voice`), `... approve <project> [nosend]`
(approve a script or video waiting at a channel's gate), `... automake` (make the trends that meet a channel's
auto-make score now), `... delete <project>`. `produce` and `topic` use the default
channel.

## Desktop app (Tauri)

```bash
cd app && pnpm install
pnpm tauri dev        # opens the app; it starts the engine with uv from the repo root
```

Needs Rust (`rustup`). The app looks for `uv` on PATH, in `~/.local/bin`, `~/.cargo/bin` and Homebrew; set `MOTIO_UV`
if it lives elsewhere. Settings → "Remote engine" uses an engine on another machine (URL +
token); the app then doesn't start its own engine.

## Packaging, CI and releases

```bash
uv run --group build python tools/build_engine.py   # PyInstaller engine + ffmpeg, deno → app/src-tauri/resources/
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
  another machine, go to Settings → "Remote engine".
- **Auto-update** (Settings → "Update app"): the app checks GitHub Releases on launch and when you click
  "Check for updates", downloads the new version, verifies its signature and restarts itself. Only
  published releases are offered. The repo is public, so no GitHub token is needed: the app reads
  `releases/latest/download/latest.json`.
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
defaults to `LLM_PROVIDER=anthropic`. Channel posting times use the server's `TZ` (default `Europe/Paris`).

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
| `NEWSNOW_URL`, `NEWS_SOURCES` | Self-hosted NewsNow (`http://newsnow:4444`, part of the server stack); empty = the public instance |
| `REFRESH_EVERY_MIN` | The engine refreshes hot topics and checks followed sources every N minutes (0 = manual only; 30 on the server) |
| `MAX_VIDEOS_PER_DAY` | Daily video cap (0 = no limit) |
| `UI_LANG` | `en` (default) / `vi`: language of the engine's steps, log lines and errors; the app sets it from Settings → Language |
| `YTDLP_COOKIES_FROM_BROWSER` | `chrome` / `safari` / `firefox` / `edge` / `brave`: download pasted links (Douyin, X…) with that browser's login |
| `CREDIT_ON_VIDEO`, `CREDIT_IN_POST` | Show source credits on the video / in the post (default off; `sources.txt` is always written) |
| `POSTIZ_URL`, `POSTIZ_API_KEY` | Postiz for posting: API root (`https://postiz.<domain>/api`) + Public API key |
| `MOTIO_FFMPEG`, `MOTIO_FFPROBE`, `MOTIO_CLAUDE`, `MOTIO_DENO` | Binary paths if they are not on PATH |

Data (SQLite, source videos, projects) lives in `data/`.

## Layout

```
motio/newsnow.py   fetch hot topics + translate + score
motio/search.py    yt-dlp search (YouTube, Bilibili) / download of sources, pasted links included (keeps platform, channel, license)
motio/asr.py       Whisper (mlx on the Mac, faster-whisper elsewhere)
motio/llm.py       claude -p or the Claude API
motio/tts.py       ElevenLabs with timestamps (macOS voice when there is no key)
motio/render.py    9:16 render (+ 16:9 copy): Pillow draws the text, FFmpeg composes
motio/captions.py  French karaoke captions (≤ 42 characters per line), exports captions.srt / captions.ass
motio/scenes.py    scene cuts with FFmpeg's scene filter
motio/pipeline.py  the steps of one project; a failed project continues from the step that broke
motio/topic.py     topic mode: explainer from any topic or video links, source rights flag
motio/watch.py     followed channels, playlists and searches → "New videos", French titles + scores
motio/settings.py  data/settings.json over .env
motio/api.py       JSON engine API for the desktop app
motio/postiz.py    send videos to Postiz (draft / scheduled / post now)
motio/channels.py  channel profiles: badge, script style, voice, hashtags, approval gates, Postiz auto-send, posting times
motio/automake.py  make videos by themselves for trends above a channel's score, after each scheduled refresh
motio/delogo.py    "Remove logo": remove a static logo from a video you own (drawn or auto-found boxes)
motio/inpaint.py   LaMa AI fill for "Remove logo" (onnxruntime, frame by frame, model downloaded on first use)
motio/web.py       legacy dashboard (to be removed)
```

## Built-in content rules

An original French voice-over with context and analysis; source clips only illustrate it, 3–6 seconds each. The post
says “Voix off générée par IA.” (there is no AI label on the video itself). Every project writes `sources.txt` with all
source links; the on-video “Source : platform / channel” label and the source list in the post are optional
(`CREDIT_ON_VIDEO`, `CREDIT_IN_POST`, default off).
