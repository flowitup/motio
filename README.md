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
"Make video" makes a French explainer from it. Bilibili's own trending lists can be followed too (**Trending lists**
on that page: the ranking of each of 17 categories, Popular, and the weekly must-watch): no login, original uploads
only (reposts, "no reprint" and paid videos are left out). Douyin and Facebook accounts can't be followed (yt-dlp only
downloads single videos there): paste those links into "New video". Bilibili spaces often need the browser-cookie setting.

**Douyin**: yt-dlp's Douyin extractor needs a logged-in browser session (`YTDLP_COOKIES_FROM_BROWSER` or
`YTDLP_COOKIES_FILE`), so a pasted Douyin link only works with one of those. Without it, download the video yourself
(for example with [f2](https://github.com/Johnserf-Seed/f2), Apache 2.0, which fetched Douyin videos without logging in
when tried on 2026-10-02) and use **Add a video file** (below).

**Add a video file** (next to every place that takes links: New video, a project's sources, a trending topic's links)
sends a video you already have, from Douyin or anywhere else, to the engine and uses it like a link: dubbed, or used as
a source for a topic explainer. It is kept with the downloaded sources, so Remove logo and re-renders find it. MP4, MOV,
M4V, MKV, WebM, AVI, TS or FLV, up to 2 GB; anything but MP4 is converted. Rights stay *unknown* until you set them.

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

**French dub** (Projects → New video → *French dub*, or **Dub in French** on a video in New videos) turns one video
(Douyin, Bilibili, YouTube…) into a French version that keeps its pictures, music and sound effects. Motio transcribes
it, takes one 62–90 s part (the whole video when it is short enough, otherwise Claude picks a part that starts and ends
on a sentence, or you type from–to), and Claude translates every line so it fits the time of the line it replaces: *tu*
or *vous* depending on who talks to whom, the channel's glossary (Channels → Glossary) for names and terms, and the
speaker and gender of each line. ElevenLabs reads the lines, each one placed where the original line started, with
one French voice per speaker: the channel's voice first, then the extra voices of the channel profile (Channels →
Other voices for dubs, up to 3), matched to the speaker's gender when the voice says which it is; you can pick each
speaker's voice on the project page (**Voices**, then **Save and re-voice**). An AI
model (UVR MDX-Net, MIT, run on the CPU) separates the original voice from the music and sounds, and the music and
sounds stay under the French voice; the first dub downloads this model once (67 MB) into `data/models/`, and if it
cannot run the original sound is kept quietly instead. A video shorter than 62 s gets a French intro and outro on a
still frame. The old subtitles burned into the picture are blurred: Motio finds the subtitle band, and you can draw
the box yourself on a frame of the project page. Only that band is blurred, never a logo (**Remove logo** stays a
separate, manual tool). French karaoke captions go on top as in every video, and the project page plays the original
part next to the dub (**Play both**), lets you change the part and edit each French line. The post keeps "Voix off
générée par IA." and the AI flags. A dub reuses someone else's pictures and words, so it is sent to Postiz by itself
only when the source rights are *owned*, *licensed* or *cc*; otherwise, even if the channel has no video gate, it stops
at **Awaiting video approval** before anything is sent.

**AI video** (Projects → New video → *AI video*) makes a French explainer from a topic with no source footage at all:
Claude writes the voice-over as scenes (the spoken line, an English picture prompt and a slow camera move: zoom in,
zoom out, pan left, pan right), an image model draws one 9:16 picture per scene, and the usual voice and render steps
put each picture under its line with a Ken Burns move, karaoke captions and the channel's badge. The pictures come
from the provider picked in Settings → AI pictures: **fal** (Qwen-Image-2512, Apache 2.0, about $0.04 per picture,
so about $0.40–0.60 per video; needs a fal key and credit) is the default and the only one cleared for a monetized
channel; **Modal** (your own `qwen21-uc` app, about $0.01 per picture) runs under the Qwen Research Licence, so its videos
always stop at **Awaiting video approval**, and it needs the `modal` Python package and a Modal login, so it works from
the dev engine or the server, not the packaged app; **Placeholder** draws gradient cards that show the prompt (free,
no network, to try the flow, also stops at the approval gate). The script gate stops before any picture is paid for.
On the project page each scene shows its picture, prompt and camera move: edit a prompt or a move and only that
scene's picture is made again, press **New picture** to draw the same scene again, then re-render (the voice is kept
when only pictures changed). The post keeps "Voix off générée par IA." and adds "Images générées par IA."; the
estimated cost of the pictures is in the project log and on the project page. Stats does not include it yet.

**AI clips** turn some scenes of an AI video into short video clips instead of a camera move on the picture. Each clip is
made by fal's **H3 Max** (MiniMax H3, image to video, 768p, 5 s, about $0.40) or, if you pick it in Settings → AI
pictures → *Clip provider*, by **HeyGen Video 1** (image to video, 768p, 5 s, $0.01–0.02 per second, so about $0.05–0.10 a
clip; needs `HEYGEN_API_KEY`): the scene's picture is its first frame, so the look you approved is kept, and the model's
own sound is dropped. HeyGen is newer and its commercial terms aren't confirmed, so a video with HeyGen clips always
stops at **Awaiting video approval**; try it on one clip first with `uv run python -m motio clipcheck <picture> "<scene>"
heygen` (about $0.10, saved in `data/clipcheck/`) and compare with `... fal`. Set how many scenes become clips per channel
(Channels → *AI clips per video*, 0 = off, up to 6) or for one video (New video → AI video → *AI clips*, empty = the
channel's number). The scenes are spread over the video and the first one (the hook) is always included. Clips are made
after the voice, once the script is final, and only new ones are paid for (they are cached, so a re-render costs
nothing); the cost goes into the project log, the project page and the Stats page, at the price per second in
Settings → AI pictures (default $0.08 for fal, $0.02 for HeyGen), and the monthly budget stops new clips. A clip fal can't make, or one that would go over the
budget, leaves its scene with the picture and camera move. The post then says "Images et vidéos générées par IA."; the
platforms' AI flags stay on. Needs the fal key (or the HeyGen key) as well as the one for the pictures.

**Quality check** runs after every render (FFmpeg and ffprobe, nothing is sent anywhere): the length is 62–90 s, the
picture is 1080×1920 H.264, there is a sound track at about -14 LUFS without clipping, no silence longer than 1.5 s
inside the video, and the first picture is not black (the cover would be). The project page shows the result; a
**problem** (no sound or almost only silence, wrong length, a black start, a file that cannot be read) stops the video at **Awaiting video
approval** instead of sending it to Postiz by itself, and you can still approve it. A **warning** is only shown. It
also points out a video whose source, title or script is almost the same as one made in the last 30 days (a warning, to
avoid posting the same thing twice). The thresholds are Motio's own, not a platform rule.

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

**Tools** are one-off jobs that need no project, each run on its own: **Download video** (any link yt-dlp can fetch,
480 / 720 / 1080p, an MP4), **Transcribe** (Whisper → `.srt` + plain text, from a video or audio file), **Translate
subtitles** (Claude, `.srt` or `.vtt` → French, English or Vietnamese, timings kept, optionally with a channel's
glossary and style; French gets French typography), **Read text aloud** (ElevenLabs, up to 5,000 characters, any of
your voices) and **Burn subtitles** (draws an `.srt` / `.vtt` at the bottom of a video with the same Pillow overlay as the
videos Motio makes, so it needs no FFmpeg libass; Chinese / Japanese / Korean subtitles use a CJK font). Each input is
an uploaded file or the result of a finished job, so download → transcribe → translate → burn chains without leaving
the page; every job shows its progress, can be stopped and keeps its files under `data/tools/jobs/<id>/out/` until you
delete it.

**Stats** shows what the videos cost: each successful ElevenLabs call is recorded (characters, an estimated price,
and the project, channel or tool job it belonged to), so the page adds up this month's voice cost and videos, the last
30 days day by day, and every channel's videos, sends, failures and cost per video. Each project also shows its own
voice cost. The price per 1,000 characters (default $0.22, the Creator plan; Flash / Turbo models count half) and an
optional monthly budget are in Settings: at 80% the page warns, at 100% the videos made automatically pause until next
month (videos you start yourself still run). Claude runs on your Claude plan and isn't counted, and views or earnings
per platform aren't tracked (they need each platform's account).

Command line: `uv run python -m motio refresh`, `... trends`, `... produce douyin:2644652`,
`... topic "giant pandas" [link …]`, `... ai "giant pandas" [seconds] [ai clips]` (a video made only of AI pictures, 70 / 80 / 90 s, with some scenes as AI clips), `... dub <link> [start end]` (French dub of one video, times in seconds), `... watch "<channel link | search words>" [bilibili]`, `... check`, `... clips`,
`... rerender <project>`, `... retry <project> [step]` (continue from the failed
step, or redo from `search` / `download` / `transcribe` / `script` / `voice` / `render`), `... approve <project> [nosend]`
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

## Running on a Windows PC at home

The engine can also run 24/7 on a Windows PC with a big drive, with the Mac (or any desktop app) pointing at it over
Tailscale (Settings → "Remote engine"): downloads, projects and finished videos stay on the Windows PC and the app only
streams what you open. `tools/windows/motio-server.ps1` installs the installed engine as a background Task Scheduler
task bound to the Tailscale address; Settings → "Engine status" shows the disk space left there. Steps:
[docs/WINDOWS_SERVER.md](docs/WINDOWS_SERVER.md) (in Vietnamese).

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
| `YTDLP_COOKIES_FILE` | Path (on the engine's machine) of a `cookies.txt` exported from a browser, for an engine without a browser (server, Windows PC): used for pasted links and for Bilibili (search, downloads, followed spaces); wins over the browser; checked when saved, never served by `/media` |
| `CREDIT_ON_VIDEO`, `CREDIT_IN_POST` | Show source credits on the video / in the post (default off; `sources.txt` is always written) |
| `POSTIZ_URL`, `POSTIZ_API_KEY` | Postiz for posting: API root (`https://postiz.<domain>/api`) + Public API key |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook (`https://hooks.slack.com/…`): a message when a script or video waits for approval, a video is ready (and whether Postiz took it) or one fails; empty = off |
| `AI_CLIP_USD_PER_SEC` | Price of one second of AI clip for the cost estimate and the monthly budget (default 0.08 for fal H3 Max, 0.02 for HeyGen, both 768p; every clip is 5 s) |
| `CLIP_PROVIDER`, `HEYGEN_API_KEY` | Who makes AI clips: `fal` (default, uses `FAL_KEY`) or `heygen` (HeyGen Video 1, uses `HEYGEN_API_KEY`) |
| `IMAGE_PROVIDER`, `FAL_KEY`, `IMAGE_STYLE` | Pictures for AI videos: `fal` (default, needs `FAL_KEY`) / `modal` / `placeholder`; the style sentence added to every picture prompt (default "photorealistic, natural light, …") |
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
motio/creator.py   AI video mode: scenes (line + picture prompt + camera move) from a topic, one moving piece per scene
motio/images.py    AI pictures: fal / Modal / placeholder behind one adapter, cached per scene, cost estimate
motio/aiclips.py   AI clips: fal H3 Max or HeyGen Video 1 image-to-video for some scenes of an AI video, cached per scene, cost estimate
motio/qa.py        quality check after each render (length, picture, loudness, silence, black start) + repeat warnings
motio/trending.py  Bilibili ranking / popular / weekly lists as followed sources
motio/localfile.py a video file added by hand, used as a source like a link
motio/dub.py       French dub: excerpt, translation to fit each line, voice placement, subtitle blur, mix (rights gate)
motio/separate.py  original voice / music separation for the dub (MDX-Net ONNX, onnxruntime, model downloaded on first use)
motio/watch.py     followed channels, playlists and searches → "New videos", French titles + scores
motio/settings.py  data/settings.json over .env
motio/api.py       JSON engine API for the desktop app
motio/postiz.py    send videos to Postiz (draft / scheduled / post now)
motio/channels.py  channel profiles: badge, script style, voice, hashtags, approval gates, Postiz auto-send, posting times
motio/automake.py  make videos by themselves for trends above a channel's score, after each scheduled refresh
motio/delogo.py    "Remove logo": remove a static logo from a video you own (drawn or auto-found boxes)
motio/inpaint.py   LaMa AI fill for "Remove logo" (onnxruntime, frame by frame, model downloaded on first use)
motio/toolbox.py   Tools: download, transcribe, translate subtitles, read text aloud, burn subtitles (jobs chain)
motio/usage.py     Stats: ElevenLabs characters and estimated cost per project / channel / tool, monthly budget
motio/web.py       legacy dashboard (to be removed)
```

## Built-in content rules

An original French voice-over with context and analysis; source clips only illustrate it, 3–6 seconds each. The post
says “Voix off générée par IA.” (there is no AI label on the video itself). Every project writes `sources.txt` with all
source links; the on-video “Source : platform / channel” label and the source list in the post are optional
(`CREDIT_ON_VIDEO`, `CREDIT_IN_POST`, default off).
