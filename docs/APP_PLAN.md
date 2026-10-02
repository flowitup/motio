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
- **C · French dub** (built in GĐ2, see "GĐ2: French dub"): the source's pictures with French speech (tu/vous, burned captions,
  original music kept). Postiz only for `owned` / `licensed` / `cc` sources: a dub of someone else's video is reused
  content on every platform.

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
- Slack notifications: see "Slack alerts" below (an Incoming Webhook; the interactive Slack app with buttons is still M4).

## GĐ2: French dub (added 28/09/2026)

The owner picked "Motio's own dub" (option B of the 28/09 brainstorm; ElevenLabs Dubbing and a plain voice-over were the
others). Two PRs: (1) one French voice with tu/vous, glossary, background separation, subtitle blur, captions and a
side-by-side compare; (2) one voice per speaker, voices chosen in the channel profile ("Part 2" below).

- **Mode `dub`** (`motio/dub.py`): a new project kind next to news and topic. `POST /api/dubs` `{link, start?, end?,
  rights}` (New video → *French dub*), `POST /api/clips/{id}/dub` (New videos → *Dub in French*), CLI `dub <link>
  [start end]`. It reuses the pipeline steps and the channel profile (badge, style, voice, hashtags, gates, Postiz).
  Only the first link is dubbed. Step labels: download and Whisper as usual, the script step writes the dub script, the
  voice step separates and mixes, the render step composes.
- **Excerpt**: a video up to 88 s is used whole; a longer one gets an excerpt of 62–85 s that Claude picks at sentence
  edges (`pick_excerpt`, snapped to Whisper segment edges), or that the user types (from–to on the project page, which
  reruns from the script step). A source shorter than 62 s gets a French intro and outro on the first / last frame held
  still (`pads`, at most 24 s together, each at least 3 s); the whole dub stays within 62–90 s (`pipeline.MIN_SECONDS` /
  `MAX_SECONDS`).
- **Translation** (`dub.script`, one `llm` call): every Whisper segment of the excerpt (segments under 1.2 s merge with
  the next) becomes one French line with a character budget from its time slot (14 characters a second). The prompt
  carries the channel's style note and glossary (`channels.glossary`, Channels → Glossary), the video's title and
  uploader, and asks for a speaker label and *tu* or *vous* by who talks to whom. `script.json` lines carry `kind`
  (line | intro | outro), `speaker`, `zh` (the original), `at`, `until`, `max_chars`; the script editor shows them (lines
  are edited, not added, moved or deleted), and `edit.clean_dub` keeps the extra fields on save.
- **Voice** (`dub.voice`): one ElevenLabs call for all lines; each line is placed at the start of its original segment
  (`place`: a line that is longer than the room before the next original line is played up to 1.15× faster; a line
  still speaking pushes the next one back, so French lines never overlap), alignment timestamps are shifted to match for the captions (`shift_alignment`).
- **Original sound** (`motio/separate.py`): UVR-MDX-NET-Inst_HQ_3 (MIT, ONNX, 67 MB, sha256 checked, downloaded once to
  `data/models/`) runs on the CPU with onnxruntime, in 5.9 s chunks with 25 % overlap (about 1.2× real time on 4 cores)
  and returns the music and sounds without the voice, which `dub.mix` puts under the French voice at 0.8. If the model
  cannot download or run, the original audio plays at 12 % instead and the log says so.
- **Subtitle blur** (`dub.detect_band`, `find_band`): sample frames at speech times, find horizontal runs of sharp text
  edges present in at least 60 % of them, drop static strokes (logos, more than 80 %), ignore the top 30 % of the frame,
  join small gaps and give up on bands taller than 25 % of the frame. The box is stored normalized (`meta.dub.blur`,
  `blur_auto`), drawn by the user on the project page (Blur old subtitles), or cleared. `render.blur_filter` applies it
  to the source picture only, so it never touches the title, badge or French captions. It is not a logo remover.
- **Captions**: the usual karaoke cues, with a `hold` (1.2 s after the last word) so a caption clears in a long
  silence instead of staying until the next line.
- **Compare** (project page): the original part in its own player, *Play both* starts it with the dub, from–to fields
  change the part.
- **Rights gate**: a dub whose `meta.rights` is not owned / licensed / cc (unknown counts as not owned) never auto-sends:
  when its channel would send to Postiz, `_deliver` stops it at the video gate (`meta.review = video`) even if the
  channel has no such gate, with a log line saying why; approving then sends it (sending stays a person's decision). Owned / licensed / cc dubs follow the channel's gates as any project.
- Posts keep "Voix off générée par IA." and the platforms' AI flags. Nothing here removes logos or dodges duplicate /
  Content ID detection.
- Not verified in the build environment: real ElevenLabs / Claude / yt-dlp runs (faked in tests), Mac and Windows.

**Part 2: one voice per speaker** (owner asleep, so the defaults below were chosen without a card).

- Claude's translation now labels each speaker with `who` and `gender` (f | m); `meta.dub.speakers` lists the speakers
  that have lines, in order of appearance (`dub.speaker_list`); older projects with the `{label: text}` shape still load.
- **Voices**: the channel profile gets `dub_voices` (up to 3 extra ElevenLabs voice ids; the profile's `voice_id` stays
  the main voice, which also reads the intro and outro). `dub.assign_voices` gives each speaker, in order of appearance,
  the first unused voice among the main voice and the extra ones whose gender label (from the ElevenLabs voice list,
  best effort) matches the speaker's; when voices run out it reuses the main voice; at most 4 distinct voices. A single
  speaker, or a profile without extra voices, reads in one call exactly as in part 1.
- **Reading**: one ElevenLabs call per distinct voice (the cost per character is unchanged), each line placed as before;
  `dub.mix` takes one audio file per voice and every placed line says which one (`v`); the caption timings of the voices
  are shifted separately and joined in video order (`dub._alignment`), and fall back to even timing when a voice has no
  timings.
- **Override**: on the project page a *Voices* card (shown when there are 2+ speakers) picks a voice per speaker
  (`PUT /api/projects/{id}/dub {voices: {label: voice_id}}` → rerun from the voice step, script untouched;
  `meta.dub.voices`, dropped for labels that a new script no longer has). `meta.dub.assigned` records which voice each
  speaker got so the card can show it.

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

## Tools page (added 29/09/2026)

From the "implement everything on the comparison page" ask; built in auto mode while the owner slept. The pipeline's
building blocks, usable on their own: one page (**Tools**, `app/src/pages/tools.tsx`) with five tools.

- `motio/toolbox.py`: a job is `data/tools/jobs/<id>/` with `state.json` (kind, title, status queued / running / done /
  failed / cancelled, pct, message, error, outputs `[{name, path, kind}]`), `in/` (uploads), `out/` (results). Jobs left
  running when the engine stops are failed at the next start (`recover`). Downloads run on their own executor so they
  don't wait behind a long logo removal; the other tools share the logo tool's single worker.
- API: `GET /api/tools/jobs`, `POST /api/tools/{kind}` (multipart: `url`, `height`, `text`, `voice`, `language`,
  `channel`, `size`, `file_job`, `subs_job`, files `file` / `subs`; 202), `GET` / `DELETE /api/tools/jobs/{id}`,
  `POST /api/tools/jobs/{id}/cancel`. Results are served by `/media/tools/jobs/<id>/out/<name>`.
- Download: `search.download` with a progress hook, the same options as source downloads (`cookies=True`, a pasted
  link). Transcribe: `asr.transcribe`; Whisper segments are cut into ≤ 2-line subtitles. Translate: Claude in batches of
  40 with 3 previous subtitles as context; a batch that comes back with the wrong count is halved and retried; French
  output goes through `captions.fr_typography`. Read aloud: `tts.synthesize` (the voice in Settings unless one is
  picked). Burn: `render.Layout` sized to the video, `render.write_caption_track(..., plain=True)` and an FFmpeg overlay
  (no libass: Homebrew's FFmpeg lacks it), `-progress` gives the percentage; the size (small / medium / large) is
  relative to the shorter side.
- Also in this change: the transcript cache, script.json and the ElevenLabs alignment file are read and written as
  UTF-8 (on Windows the default encoding could not hold Chinese text).
- Not verified: real yt-dlp, Whisper, Claude and ElevenLabs runs from this page, and the page on the Mac / Windows apps.

## Stats page (added 29/09/2026)

Built in auto mode right after the Tools page. It answers "what does a video cost me?" for the one paid API Motio
calls per use.

- `motio/usage.py` + the `usage` table (`db.add_usage`, `usage_sum`, `usage_since`): `tts.synthesize` records one row per
  successful ElevenLabs call (characters actually sent, estimated USD, model, voice). Who it belongs to comes from a
  ContextVar (`usage.context(project_id=…, channel_id=…, ref=…)`): `pipeline._voice_render_post` sets the project (the
  channel is read from its meta), the Tools "Read aloud" job sets `ref="tool:<job>"`. A failed call, or a DB error while
  recording, never fails the work.
- Price: `ELEVENLABS_USD_PER_1K_CHARS` in Settings (default 0.22, Creator plan); `flash` / `turbo` models count half. It
  is an estimate: credits on the owner's real plan may differ. `MONTHLY_BUDGET_USD` (0 = none): `summary()["budget"]`
  is `ok` / `warn` (≥ 80%) / `over` (≥ 100%); `over` makes `automake.picks` return nothing, manual makes are never blocked.
- API: `GET /api/stats` (`price_per_1k`, `month`, `budget`, `total`, `days` × 30, `channels`); a project's detail gets
  `usage: {tts_chars, usd}`. The page is `app/src/pages/stats.tsx` (cards, CSS bar chart, per-channel table).
- Not tracked: Claude (`claude -p` bills the owner's plan, not per call), platform views and earnings (need each
  platform's account and API), other providers' credits. Usage from before this version isn't there.
- Not verified: the estimate against a real ElevenLabs invoice; the page on the Mac / Windows apps.

## Slack alerts (added 30/09/2026)

Next item from the left-over list after v0.7.0 that needs nothing but a webhook link (no token-holding Slack app).

- `motio/notify.py`: one-way messages to a Slack Incoming Webhook (`SLACK_WEBHOOK_URL` in Settings → Slack alerts, stored
  masked like the API keys). Only `https://hooks.slack.com/…` links are accepted (Settings rejects anything else), so
  the engine can't be pointed at another address. It runs in the engine, so it also works while the app is closed
  (engine on the server).
- Events, sent from `pipeline.py` right after the status changes: a script or video waits for approval (`review`), a video
  is done (with "Sent to Postiz (draft / schedule / now)" or "Not sent to Postiz: …" when a channel profile sends it), a
  project failed (first line of the error). The text follows the UI language (`tr()`), shows the project title and the
  channel name, and is escaped (`& < >`) because titles come from outside.
- A failure to send (offline, link revoked) is logged and never fails or delays a video beyond the 10 s timeout. Settings has
  "Send a test message" (`POST /api/notify/test`) that shows the real error.
- Not included: buttons (Approve / Make video; needs the Slack app in Socket Mode, M4), budget alerts (the Stats page still
  shows those), notices for Tools and Remove logo jobs, a per-event switch.
- Not verified: a real delivery to Slack (the build sandbox can't reach hooks.slack.com); tested against a fake transport.

## GĐ3 part 1: AI video (added 30/09/2026)

The owner picked "AI images" on the next-feature card (30/09) and then "continue with AI video". Brainstorm:
`/mnt/project-files/motio/plans/brainstorm-260930-gd3-ai-images.md`. This is the first part of the comparison page's GĐ3
row; AI clips (fal H3 Max), consistent characters (reference images) and the Recap variant (a video link as input) come
later, each as its own change.

- **Mode `ai`** (`motio/creator.py`): a project kind next to news, topic and dub, with no source footage. `POST /api/ai`
  `{topic, duration}` (New video → *AI video*), CLI `ai "<topic>" [seconds]`. Steps shown: script, voice, render
  (`available_steps`); `produce` skips search / download / transcribe; `STEPS` itself is unchanged.
- **Script** (`creator.SCRIPT_PROMPT`, one `llm` call): French narration as scenes `{text, image, motion}` plus one
  plan-level `style` sentence and the usual title / description / hashtags. `image` is an English prompt for one concrete
  scene (no text, logos or recognizable real people); `motion` is `zoom_in`, `zoom_out`, `pan_left` or `pan_right`.
  Voice fitting (`pipeline._fit`, with `FIT_LONGER_AI` when it has to add lines) gets the scenes as they are and returns
  them through `creator.tidy`, which keeps each line's prompt, move and seed and fills in a missing move.
  The script editor shows each scene with its picture, prompt and move (`edit.script_view`, `edit.save_script`).
- **Pictures** (`motio/images.py`, `creator.pictures`): one 1088×1920 picture per scene in `out/scenes/`, cached by
  sha1 of provider | size | seed | prompt, so a retry or an edit makes only the missing or changed scenes (one retry per
  picture, then the step stops with the ones already made kept). They are made right before the voice
  (`pipeline._voice_render_post`), after the script gate, so nothing is paid for before approval. **New picture** on a
  scene bumps its `seed` (`edit.reroll_picture`, `POST /api/projects/{id}/scenes/{index}/redo`); re-rendering from the
  render step keeps the saved voice and makes only the pictures that are missing. The project log and `meta.ai`
  (`provider`, `scenes`, `cost`) record the estimated cost; the Stats page doesn't include it yet.
- **Providers**, one adapter, `IMAGE_PROVIDER` in Settings → AI pictures (the decision card only sets the default):
  `fal` (`fal-ai/qwen-image-2512`, Apache 2.0, about $0.042 per picture, `FAL_KEY` stored masked) is the default and the
  only one cleared for a monetized channel; `modal` (the owner's deployed `qwen21-uc`, `Qwen21UC.generate`, about $0.009;
  Qwen Research Licence, no safety filter, needs the `modal` package and a login, so not in the installers); `placeholder`
  (gradient cards with the prompt, free, no network). `IMAGE_STYLE` is added to every picture prompt.
- **Render**: one `render.Piece` per scene, from where its line starts to where the next one starts, each with
  `motion`. `render.kenburns()` makes the move with `zoompan` on a 2× scaled input (fill when the picture is ≈9:16, fit
  over a blurred background otherwise); credits are skipped for these pieces. Captions, badge, 16:9 copy, gates, Postiz
  and Slack are the existing ones.
- **Rights and disclosure**: pictures from `images.REVIEW_PROVIDERS` (`modal`, `placeholder`) always stop at
  **Awaiting video approval** (`creator.needs_review`, `pipeline._deliver`), even when the channel has no video gate.
  The post text keeps "Voix off générée par IA." and adds "Images générées par IA."; the platforms' AI flags stay on.
- Not included: AI clips, reference images for consistent characters, Recap, a per-channel provider, image cost on the
  Stats page, a check for each picture's content before sending (the owner's look at the video gate is it).
- Not verified: real generation from fal or Modal (the build sandbox has no keys or network for them; tests use a mock
  HTTP transport and the placeholder); the picture quality and prompts from Claude on real topics; the Mac / Windows apps.
  Verified in the sandbox with real FFmpeg: the four camera moves in both layouts, and a full 80 s video through the real
  API, renderer and placeholder provider, including one scene redone and the voice kept.

## GĐ3 part 2: AI clips (added 01/10/2026)

The owner confirmed "continue with AI video" and "ship it" for the AI clips line that GĐ3 part 1 left for later. Agreed
shape (proposed in the thread, accepted): clips on some scenes, switched on per channel with a per-video override,
at most 6 clips of 5 s per video, the post says so.

- **What it is** (`motio/aiclips.py`): fal's H3 Max (`minimax/h3-max/image-to-video`: MiniMax H3 post-trained by fal, 768p,
  5–15 s, about $0.08 a second) turns a scene's picture into a `DURATION` = 5 s clip. The picture is the first frame, so the
  look approved at the script gate is kept; the prompt is the scene's prompt plus the scene's camera move written as a
  motion ("slow push-in", …). The model's sound is dropped with `-an`. Same `FAL_KEY` as the fal pictures; a data URI carries the
  picture, `enable_safety_checker` stays on. Cached in `out/clips/` by (picture bytes, prompt, seed, endpoint, size, length).
- **Which scenes** (`aiclips.pick`): `n` of the scenes, evenly spread, scene 1 (the hook) always in. `n` is the project's own
  `meta.ai.clip_limit` (New video → AI video → *AI clips*, `POST /api/ai {clips}`, CLI `ai "<topic>" [seconds] [clips]`) or,
  when it has none, the channel profile's `ai_clips` (0–6, default 0 = off, `aiclips.limit`). Only AI videos.
- **When** (`creator.animate`, called from `pipeline._voice_render_post`): right after the voice, once the script is final
  (clips are not made before the script gate or the voice, so a gate or a failed voice costs nothing). A missing fal key stops
  the run before any picture is paid for (`check_ready`; the app and the API say so at creation).
- **Render**: a clip scene's `render.Piece` has no `motion` (`creator.timeline(scenes=)`), so `render_piece` plays the clip; a
  scene longer than 5 s holds the clip's last frame (the piece's video is now padded to the scene length, not only 3 s).
- **Never fails a video**: a clip fal can't make is tried twice, then that scene keeps its picture and camera move, with a log
  line. Once `MONTHLY_BUDGET_USD` is reached, scenes that would need a new paid clip are left as they are (clips already made are
  reused); the video is still made.
- **Cost**: each new clip adds a `usage` row (kind `clip`, 0 characters, `5 s × AI_CLIP_USD_PER_SEC` USD, default 0.08).
  That puts clips in the Stats page totals, the per-channel table, the per-video cost and the monthly budget; the project
  page shows the clip count and "Pictures and clips so far". `usage.for_project` adds `clip_usd` so the voice line stays
  voice-only. Stats labels that said "Voice cost" now say "Cost". Pictures are still not in Stats.
- **Disclosure**: with clips the post reads "Voix off générée par IA. Images et vidéos générées par IA." (`write_post(ai_clips=)`,
  kept when the script is edited); without clips nothing changes.
- **Also fixed**: when the voice step rewrote or trimmed the script, the render got the pictures of the old script (one too few
  pictures for an 11-line script). `_voice_render_post` now makes (or reuses) the pictures of the final script right after the voice.
- Not included: clips in news / topic / dub videos (mixed with source footage), choosing which scenes get a clip, a clip
  length other than 5 s or 1080p, reference images for consistent characters, Recap.
- Not verified: a real H3 Max call (no fal key or network in the build environment; tests use a mock transport, and FFmpeg
  really strips the sound and holds the last frame); the endpoint's exact input names are from fal's published schema
  (`prompt`, `image_url` as a data URI, `duration`, `resolution`, `seed`, `enable_safety_checker`, `prompt_expansion_mode`) and
  its price is fal's list price, not checked against an invoice; H3 Max's licence for monetized channels was not checked, so
  clip videos follow the channel's own gates; the app on Mac / Windows.

## Windows PC at home as the server (added 01/10/2026)

The owner asked for the home Windows PC (5 TB) to run the engine and keep every downloaded and produced video, with the Mac
only monitoring. Remote-engine mode already does that (no engine and no data folder on the Mac; `/media` streams with Range;
uploads go to the engine; "Open folder" is hidden); what was missing is running it: option A of the brainstorm (installed
engine in the background + Tailscale), no Docker, no network drive.

- **Runbook and script**: `docs/WINDOWS_SERVER.md` and `tools/windows/motio-server.ps1` (elevated PowerShell): finds
  `motio-engine.exe`, writes a launcher (sets `MOTIO_DATA`, `HF_HOME`, `MOTIO_TOKEN`, keeps logs next to the data), registers
  the Task Scheduler task "Motio engine" (at log on, restarts every minute when the engine stops, e.g. Tailscale not up yet),
  binds the engine to the Tailscale address only, opens the port for `100.64.0.0/10` only, optional `-KeepAwake`; `-Status`,
  `-Uninstall`. The token file and launcher are readable by the current user only.
- **`YTDLP_COOKIES_FILE`** (Settings → Cookie file): a Netscape `cookies.txt` for an engine without a browser. Checked when
  saved (`search.check_cookie_file`, loaded with yt-dlp's own jar). Used for pasted links (any site), and for Bilibili search,
  Bilibili downloads and followed Bilibili spaces; it wins over `YTDLP_COOKIES_FROM_BROWSER`, which behaves as before. yt-dlp
  rewrites the jar when it closes, so every thread gets its own temporary copy (`search._own_cookie_copy`) and the original
  is never touched; `/media` refuses the configured file even inside the data folder.
- **Disk space**: `GET /api/health` has `disk: {free, total}` (bytes, the drive of the data folder); Settings → Engine
  status shows it, and the remote engine card says where the videos live.
- Not included: a script that imports the Mac `data/` folder and rewrites the absolute source paths in `meta` (finished
  videos play after a plain copy; delogo-cleaned sources and the dub compare player lose their link); a hosted ASR provider
  (Groq) if faster-whisper on the PC is too slow; a slim client build without the bundled engine; updating the Windows engine
  from the Mac app.
- Not verified: the script and the whole flow on a real Windows PC (the PowerShell is only parse-checked with `pwsh`);
  the frozen engine's transcription and render on Windows; faster-whisper speed and CUDA (the build does not bundle the CUDA
  libraries); macOS WebView with plain HTTP to the Tailscale address (fallback in the runbook: `tailscale serve` HTTPS).

## AI film studio batch (added 01/10/2026)

The owner wants a studio that dubs or comments on trending Douyin / Bilibili / Chinese film-platform videos and makes AI
films, and to start using it on 02/10. Research and the ranked feature list: `plans/brainstorm-261001-ai-studio.md` in the
project files. Built in this batch:

- **Bilibili trending lists as followed sources** (`motio/trending.py`): `bilibili:ranking:<rid>` (16 categories or all),
  `bilibili:popular`, `bilibili:weekly`. Plain JSON, no login and no signature (the weekly list wants anonymous buvid
  cookies; a short User-Agent gets code -352). Only original uploads (`copyright` 1), nothing "no reprint" or paid, nothing
  under 15 s; rights stay *unknown*. A *Bilibili trending* picker with a *Follow list* button on the New videos page; source kind `trending` in `watch.py`; a first check marks the top 20 as new.
- **HeyGen Video 1 as a second AI clip provider** (`aiclips.py`, `CLIP_PROVIDER`, `HEYGEN_API_KEY`): `POST /v3/models/videos`
  `image_to_video` with the scene picture as the first frame, 5 s, 768p, polled every 3 s up to 420 s, sound dropped. The
  output follows the picture's proportions (HeyGen's reference: any `aspect_ratio` is ignored in this mode), so no ratio is
  sent. The job is paid once it exists: its id is kept in `<clip>.job` until the clip is saved, a failed look (429 / 5xx /
  network, up to 6 in a row) is retried, and a timeout or a retry resumes the same job instead of paying for a second one.
  Default price $0.02/s (HeyGen's page says $0.01/s until the end of October and $0.02/s at 768p with sound, OpenRouter shows
  $0.015 after the discount; sources disagree, so the budget uses the list price). Its commercial terms are not confirmed, so HeyGen clips force the video gate
  (`aiclips.REVIEW_PROVIDERS`). CLI `clipcheck <picture> ["<scene>"] [fal | heygen]` makes one paid trial clip (about $0.10 with heygen, $0.40 with fal).
- **Series and recurring characters** (`motio/series.py`, channel fields `series` / `cast`): the owner picked "AI film
  characters" (option C, 01/10). Chosen design: text first. The cast (one `Name: look` line per fictional character, up to 8)
  is saved in the script (`plan["cast"]`) and `creator.prompt` puts the look of every character a scene names in front of its
  picture prompt, so the same words reach the image model each time (cache keys follow the prompt: an edited look redraws only
  those scenes). The series premise plus a recap per episode (`meta.ai.episode` / `recap`, written by Claude in the script
  JSON) make each AI video the next episode of the channel (last 6 recaps). Not included: reference images / character sheets
  for a true same-face guarantee (next level), a per-video cast, characters in news / topic / dub videos.
- **Quality check after every render** (`motio/qa.py`, `meta.qa`, `QualityCard` on the project page): length 62–90 s,
  H.264 1080×1920 / AAC, loudness near -14 LUFS without clipping, silence over 1.5 s inside the video, a black start (the
  cover) or black stretch; `fail` (no sound, almost silent, wrong length, black start, unreadable file) holds the video at the
  gate when the channel has Postiz. Warnings only for the rest and for a source, title or script used in the last 30 days
  (`qa.repeats`; the owner declined a source ledger, so this is a warning, not a record).
- **Add a video file** (`motio/localfile.py`, `POST /api/uploads`, `AddVideoFile` in the app): the way to use a Douyin video
  (or any file) yt-dlp cannot fetch. Stored as `cache/sources/File_<id>.mp4` so source lookups keep working; the link
  `file:<id>/<name>` goes wherever links go. A pasted Douyin link that yt-dlp refuses for lack of cookies now says to add the
  file or set a cookies file.
- **Douyin findings (02/10)**: tried by the owner's Mac session, guest only (no login, none of the owner's cookies): **f2**
  (Apache 2.0, https://github.com/Johnserf-Seed/f2) fetched video details and playable mp4 addresses 11 of 11 times through
  Douyin's web API with an anonymous `ttwid`, signing each request with `a_bogus`; `v.douyin.com/<code>` redirects to
  `iesdouyin.com/share/video/<id>/`. yt-dlp, jiji262/douyin-downloader (blocked by Douyin per its README) and the web page
  do not work without a browser session; Evil0ctal v5 (Docker + Postgres + Redis) and TikTokDownloader (GPL-3.0, cookie)
  were not run. Not tested: keyword search, an author's video list. Calling f2's way from the engine needs Douyin's request
  signing and a device-fingerprint token payload inside Motio; the auto-mode safety check refused to add that, so it waits for
  the owner's decision (pinning f2's version and a live test would be needed, Douyin changes the signature often).
- Not verified: a real HeyGen call and the H3 / HeyGen comparison, a Bilibili list through the app on the Mac, the quality
  check on a Mac-rendered video, the file upload of a large video through the Tauri webview.
- Not included: consistent characters across clips and a series with many episodes (chosen by the owner for next), hints for
  Whisper in Chinese and a glossary for dubs, Douyin keyword search or author lists.

## Out of scope for now

Motio calling TikTok / Reels / YouTube / X APIs directly (Postiz does it) · auto-sending videos that have no channel
profile · AI clips mixed into news / topic / dub videos (AI pictures and AI clips are in, for AI videos: GĐ3).
