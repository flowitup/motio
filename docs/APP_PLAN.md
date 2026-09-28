# Motio — desktop app plan

Goal: one app that runs on **macOS (Apple Silicon)** and **Windows (x64)**. A Python **engine** does the
work (existing code in `motio/`); a **Tauri 2 + React + TypeScript** shell is the UI. The engine can run
next to the app, or headless 24/7 on the Windows box, with the Mac app pointing at it over Tailscale.

```
Motio app (Tauri + React)                    Motio engine (Python, FastAPI)
  macOS .dmg / Windows .msi   ── HTTP ──▶     trends · sources · Whisper · Claude · ElevenLabs
  Trending · Projects · …     127.0.0.1       FFmpeg render · scheduler · (later) Drive + Slack
```

Stack decisions: Tauri 2, React 19 + Vite + TypeScript, Tailwind + shadcn/ui, TanStack Query.
Engine: FastAPI, SQLite, uv. Posting goes only through Postiz (see "Server + Postiz" and "GĐ1"), never the platforms'
APIs directly.

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
   - `DELETE /api/projects/{id}` · `GET/PUT /api/projects/{id}/script` — delete a project, edit its script (added
     26/09, see "Edit and delete projects")
   - `GET  /api/projects/{id}/events` — SSE stream of `{status, step, pct, log_tail}`
  - `GET/POST /api/watches` · `PATCH/DELETE /api/watches/{id}` · `POST /api/watches/check` (async) ·
    `GET /api/clips?status=new|used|hidden&watch_id=` · `PATCH /api/clips/{id}` `{status}` ·
    `POST /api/clips/{id}/produce` `{duration, links_only?}` (added 26/09, see "Beyond hot news")
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
   Setting "Remote engine" (URL + token) skips spawning.
3. **Screens** (English or Vietnamese UI, Settings → Language, since 28/09/2026; sidebar layout, follows OS light/dark):
   - **Trending** — score badge, FR title, ZH title, source, angle; filter by source; "Refresh"; "Make video".
   - **Projects** — list with thumbnails and status chips; detail with progress bar, step, live log (SSE),
     9:16 video player, post text + "Copy", "Re-render", "Open folder".
   - **Settings** — engine local/remote, LLM provider + model, API keys (masked), ElevenLabs voice picker
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
  Since 28/09 there is also a `render` step: it renders again with the voice saved at `audio/narration.json`, offered
  while the script's lines are unchanged since that voice (after a logo clean, a title edit, or a failed render).
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
- **B · Watchlist** (built, `motio/watch.py`): a "Video mới" page follows YouTube channels (videos + Shorts tabs) and
  playlists, Bilibili user spaces / series / favourites, and saved searches (YouTube: videos uploaded this month; Bilibili). yt-dlp
  lists them flat (no upload date, so "new" = not seen before); a new source shows its latest 10 videos per list,
  later checks only unseen ones. Checks run on the `REFRESH_EVERY_MIN` scheduler, when a source is added, or with
  "Kiểm tra ngay"; one low-effort Claude call per 20 new videos gives a French title and a score. "Làm video" makes a
  topic project from the video's link (title as the topic). A source's rights flag carries over when only that video
  is used (the default for owned / licensed / cc sources); adding search footage makes the project `unknown`.
  Bilibili lists give links only, so Motio reads each new video's page for its title; the space API often needs
  `YTDLP_COOKIES_FROM_BROWSER`. yt-dlp can only download single Douyin/Facebook videos, so those stay links.
  The same PR fixes YouTube downloads: yt-dlp needs a JavaScript runtime (Deno, bundled) and `yt-dlp-ejs`.
- **C · French dub** (after B): the source's pictures with French speech (Demucs, tu/vous, burned captions). Postiz
  only for `owned` / `licensed` / `cc` sources: a dub of someone else's video is reused content on every platform.

## Video length: 62–90 s (added 26/09/2026)

The owner's rule: every video lasts at least 1 min 2 s, which also clears TikTok Creator Rewards (it only pays for
videos longer than 1 min). The top is 90 s because Facebook Reels published through the Graph API accept 3–90 s
(checked 26/09: YouTube Shorts allow 3 min and earn at any length, Instagram Reels via API 15 min, TikTok per creator,
X 140 s through the API). `pipeline.MIN_SECONDS = 62`, `MAX_SECONDS = 90`, default target 80 s; older 30 / 60 s
targets are raised to 70, and the 1:30 option aims at 85 s (`TOP_MARGIN`) so a rewrite that runs long still fits.

- Script: word count from the target at 2.5 words/s; a script that can't reach 62 s is lengthened before the voice.
- Voice: if narration + 0.6 s falls outside 62–90 s, Claude rewrites once to the word count the measured speech rate
  needs, and it is read again (rerender does the same, so old projects come out ≥ 62 s).
- Still over 90 s after that → the lines just before the closing line are dropped (by their measured length, keeping
  the hook, the closing line and at least 3 lines) and the script is read again, at most twice.
- Render: still short → the last shot continues with source footage up to 62 s (captions end with the voice).

## Edit and delete projects (added 26/09/2026)

Agreed with the owner on 26/09 (brainstorm: script editor, not a clip-level timeline editor).

- **Delete**: a trash button on each card in Dự án and on the project page, with a confirm dialog. It removes the
  project row and `data/projects/<id>/`, keeps the shared source cache, and puts a news trend back to "new" when no
  other project uses it (a "Video mới" clip too, unless its source was removed). Refused while the project is queued or running. Posts sent to Postiz stay there. CLI
  `delete <id>`.
- **Edit**: a "Kịch bản" card on the project page (`motio/edit.py`, `GET/PUT /api/projects/{id}/script`) edits the
  on-video title, each voice-over line (edit, add, move, remove; lines keep their clips, new lines get filler
  footage), the description and hashtags. It estimates the length against 62–90 s from the speech rate measured on
  the last voice (`meta.speech_rate` once the script changes). Saving a finished project rewrites `post.txt` at once;
  a title or line change marks the video as out of date (`meta.edited_at`) until it is re-rendered.
- **Rerun**: "Lưu và dựng lại" saves and runs the existing voice + render step on the edited script, so the length
  rules still apply (Claude fits once, then lines near the end are dropped if still over 90 s). The redo picker warns
  that starting from "Viết kịch bản" or earlier writes a new script.
- Later, if needed: choosing and trimming each line's clips with a source preview.

## Xoá logo: remove a logo from your own video (added 27/09/2026)

Asked by the owner on 27/09: pick a video and remove its watermark. Design agreed in the thread: a manual tool, no
pipeline step.

- A **Xoá logo** page (`app/src/pages/delogo.tsx`, `motio/delogo.py`, `/api/delogo/*`). The video is a project's
  source clip (`p<id>-<i>`, also linked from each source on the project page) or an uploaded file (`u<hex>`, kept in
  `data/tools/delogo/`).
- Boxes are drawn on a frame (slider to pick the frame) or found by **Tự tìm**: edges that keep the same place and
  direction across ~32 sampled frames while the picture moves; letterbox lines and still videos are rejected.
- Removal (changed 27/09 on the owner's ask, "Replace ffmpeg with LaMa"): the LaMa AI model redraws the boxed area
  on every frame (`motio/inpaint.py`). Model: OpenCV Zoo's ONNX export of LaMa (`inpainting_lama_2025jan.onnx`,
  92 MB, Apache 2.0), downloaded once to `data/models/` and checked by sha256; its fixed 512×512 input is opened to
  any size (6 bytes of the input / output shapes). onnxruntime on the CPU, macOS / Windows / Linux alike.
  Per frame: crop the box plus a margin, shrink to ≤ 256 px, fill, scale back, blend over a thin ring so no box edge
  shows; while the picture around the logo stays the same, the last fill is reused (fast on still shots, no
  flicker). FFmpeg only decodes and re-encodes (H.264 CRF 18, AAC, exact-rounding RGB ↔ YUV so the untouched picture
  keeps its values). Measured in a 4-core cloud container: ~0.07 s per frame on a still shot, ~0.7 s per frame and
  logo on a moving one; the Mac should be faster (not measured yet). Logo jobs run on their own queue so they don't
  hold up video production; the page shows time left and a Stop button. Video inpainters (ProPainter, E2FGVI) stay
  out: non-commercial licenses.
- Where to clean (added 28/09 after a 14-minute news clip with 2 logos showed 235 min left on the Mac; owner: "Chỉ
  xoá logo cho các video final"): a project source is cleaned only in the parts its final video uses (the pieces of
  this source in the last render's `timeline.json`, which now records each piece's source URL, widened 1 s before /
  3 s after and merged when less than 2 s apart); it needs a render first. An upload is cleaned whole (**Cả video**)
  or in one part (**Một đoạn**, from–to). Frames outside are re-encoded untouched, so the clean file keeps the
  source's length and timestamps; the record keeps `ranges`. After each render the
  pipeline logs any piece of a partly cleaned source that falls outside those ranges and the page shows it; it never
  cleans by itself. The model's int8 weights are now unpacked once when it loads, not on every frame (~28 % faster,
  same output).
- The "Tôi sở hữu video này…" tick was removed on the owner's ask (PR #19, app 0.5.1). A rights value sent through
  the API is still stored on the source (`meta.sources[i].delogo`) and, once every source is declared, in
  `meta.rights`.
- A cleaned project clip replaces the source for the next render (`path` → `delogo/<i>/clean.mp4`, `orig_path`
  keeps the original; transcript and scene caches are copied), "Dựng lại video (giữ giọng)" reruns the `render` step with the saved voice (the
  voice step when the script's lines changed), and
  "Dùng lại video gốc" restores it. An upload gives a cleaned copy to download.

## GĐ1: channel profiles, approval gates, auto-send (added 28/09/2026)

The owner asked to build the rest of the blueprint in phase order; for GĐ1 they picked channel profiles ("Kênh profiles", brainstorm
28/09) over global switches or YAML files. Shipped in two PRs: (1) profiles, gates, auto-send and the badge fix;
(2) the 16:9 copy and auto-make above a trend score.

- **Channels page** (`motio/channels.py`, `/api/channels`): one profile per channel: name, red badge on the video
  (empty = none), style notes appended to the script prompt, ElevenLabs voice, default length for hot-news videos,
  hashtags that go first, a script gate, a video gate, Postiz channels and a send mode (draft / schedule at the
  channel's next free posting time, `send_times` in the engine's local time / now). One profile can be the default.
- Trending, New videos and New video take a `channel` (none = the default profile, 0 = no profile); the project keeps it
  in `meta.channel`. Without a profile a project runs as before: no gates, no auto-send; the badge is "ACTU CHINE" for
  news and none for topic explainers (before, every video got "ACTU CHINE").
- **Gates**: after the script step, a project with the script gate stops as status `review` (`meta.review = script`)
  and frees the worker; "Approve and continue" (`POST /api/projects/{id}/approve`) runs the voice step. After the render,
  the video gate stops it again (`meta.review = video`); approving sends it to the profile's Postiz channels (or not,
  `send: false`). Retrying or re-rendering clears a pending review.
- **Auto-send**: with the video gate off, a finished video goes to Postiz at once. Each project is sent automatically
  once; later re-renders finish without posting again (sending again stays manual). A Postiz error is logged
  (`meta.send_error`) and the video still finishes.
- **16:9 copy** (PR 2): a profile lists `wide_postiz`, a subset of its Postiz channels. When it has any, the render step
  also composes `final_wide.mp4` (1920×1080) from the same pieces, narration and caption cues: `render.Layout` holds
  each format's sizes (`VERTICAL`, `WIDE`), the wide frame fits the clip inside instead of cropping it, with the title
  top left and the captions low. `meta.wide` points to it (none: a stale copy is deleted). Auto-send posts the 16:9
  copy to `wide_postiz` channels and the 9:16 video to the others (if the copy is missing, 9:16 goes everywhere and the
  log says so); the project page plays either and the Postiz card can send either (`version`: vertical | wide).
- **Auto-make** (PR 2, `motio/automake.py`): a profile with `auto_score` > 0 gets videos made for it after each
  *scheduled* refresh (not the Refresh button): trends still on the board in the last 6 h, first seen in the last 24 h,
  status new, score ≥ `auto_score`, best score first. Each trend goes to the first profile it qualifies for (default
  profile first, then by id) that still has room under its `auto_daily` cap (1–20, counted from local midnight), all
  within `MAX_VIDEOS_PER_DAY`. The project gets `meta.auto`, runs like a click on "Make video" for that channel and
  still stops at its gates. `uv run python -m motio automake` runs the same pick by hand. Profiles saved before PR 2
  read the new fields as their defaults (no 16:9, auto-make off).
- Slack notifications wait for a Slack app from the owner.

## English UI (added 28/09/2026)

The owner asked for the app in English: every string in `app/src/i18n.ts` (one dictionary, so other languages can
be added), the Tauri messages, and the engine text the app shows as is (step labels, log lines, API errors, CLI
output, the legacy dashboard). Video content and post text stay French. Older sections of this plan quote the
Vietnamese labels of their time (Tin hot = Trending, Video mới = New videos, Dự án = Projects, Kênh = Channels,
Xoá logo = Remove logo, Cài đặt = Settings).

## Language switch (added 28/09/2026)

Right after the English UI, the owner asked to switch between English and Vietnamese. Settings → Language
(English / Tiếng Việt) applies at once and is remembered on the machine; English is the default. `app/src/i18n.ts`
holds both catalogs (the Vietnamese one is the pre-English text, restored from git, plus the strings added since).
The app also saves `UI_LANG` in the engine's settings, so new step labels, log lines and errors come in the same
language (`motio/i18n.py`); lines already in a project's log stay as written. Messages from the Tauri shell are
matched to Vietnamese in the app. CLI help, the legacy dashboard, video content and post text are unchanged.

## Out of scope for now

Motio calling TikTok / Reels / YouTube / X APIs directly (Postiz does it) · auto-sending videos that have no channel
profile · AI clips (fal H3 Max) and Qwen images (Modal) inside the pipeline.
