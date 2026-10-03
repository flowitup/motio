# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Motio** — a personal desktop app (macOS + Windows) that turns trending Chinese news (NewsNow hot lists)
into French 9:16 videos: find source clips (yt-dlp) → transcribe (Whisper) → French voice-over script
(Claude) → voice (ElevenLabs) → render (Pillow overlays + FFmpeg) → deliver (later: Google Drive, Slack,
auto-publish). Single owner, not a SaaS. The current implementation plan is `docs/APP_PLAN.md` — treat it
as authoritative for scope and milestones.

## Layout

- `motio/` — Python 3.12 engine (uv, `package = false`).
  - `config.py` env + paths · `db.py` SQLite (trend, project) · `newsnow.py` fetch/translate/score trends
  - `search.py` yt-dlp search/download (cookies: `YTDLP_COOKIES_FILE` per-thread copy, else browser) · `asr.py` mlx-whisper (macOS arm64) / faster-whisper (elsewhere)
  - `douyin.py` public Douyin videos without a login through the `f2` package (it does Douyin's request signing; Motio only
    calls it): `search.download` tries it first for Douyin links and falls back to yt-dlp when f2 cannot
  - `llm.py` `claude -p` or Anthropic API · `tts.py` ElevenLabs (macOS `say` fallback for dev only)
  - `render.py` 9:16 composition (+ 16:9 copy, same cut) · `pipeline.py` project steps (`produce`, `resume`, `rerender`)
  - `captions.py` French karaoke cues + SRT/ASS · `scenes.py` scene cuts (FFmpeg scene filter)
  - `topic.py` topic mode: explainer from any topic or video links (prompts, rights flag, `create`)
  - `creator.py` AI video mode (`mode = "ai"`): Claude writes scenes (spoken line + English picture prompt + camera move),
    one picture per scene, one moving piece per scene (Ken Burns, `render.Piece.motion`); no source footage; pictures
    from a provider that isn't cleared for monetized channels force the video gate (`creator.needs_review`)
  - `shots.py` picture review for AI videos ("Review the pictures first", `meta.ai.review_shots`): after the pictures are made the
    video waits in `meta.review == "shots"`; each shot is approved by the key of its current picture (a new prompt, seed, style or
    provider un-approves it), redone at once (only that picture is made), a picture the provider cannot make is noted instead of
    stopping the step, and "continue" runs the voice and render (`/api/projects/{id}/shots/*`, `ShotsCard` in the app)
  - `images.py` AI pictures behind one adapter: fal `qwen-image-2512` (default) / Modal `qwen21-uc` / placeholder; a
    picture is cached by (provider, size, seed, prompt) in `out/scenes/`, so only a new or edited scene is made again
  - `aiclips.py` AI clips for AI videos: a scene's picture becomes a 5 s clip (fal `minimax/h3-max/image-to-video`, or
    HeyGen Video 1 when `CLIP_PROVIDER=heygen`; first frame = the picture, sound dropped) instead of a camera move;
    `creator.animate` picks scenes (`pick`), makes them after the voice, cached in `out/clips/`; a clip that fails or goes
    over `MONTHLY_BUDGET_USD` leaves the scene as it was; HeyGen clips force the video gate (`REVIEW_PROVIDERS`); CLI
    `clipcheck` makes one paid trial clip to compare providers
  - `series.py` AI video series: a channel's `cast` (`Name: look` lines, fictional characters; the look is kept in
    `plan["cast"]` and put in front of every picture prompt that names the character, `creator.prompt`) and `series` (premise;
    each AI episode is written knowing the recaps of the channel's earlier ones, `meta.ai.episode` / `recap`); same words, not a
    face guarantee
  - `qa.py` quality check after every render (ffprobe + FFmpeg blackdetect / silencedetect / ebur128, saved as `meta.qa`) and
    warnings for a source, title or script used in the last 30 days; a `fail` holds the video at the gate when the channel
    has Postiz (`pipeline._why_held`), a warning is only shown
  - `trending.py` Bilibili's own ranking (16 categories or all), popular and weekly lists as followed sources in `watch.py`
    (`bilibili:ranking:<rid>`, `bilibili:popular`, `bilibili:weekly`), original uploads only
  - `localfile.py` a video file added by hand (`POST /api/uploads`) stored as `cache/sources/File_<id>.mp4` and used as the
    link `file:<id>/<name>` wherever links go (`search.clean_links` / `search.download` understand it)
  - `dub.py` French dub mode: one video → excerpt (62–90 s) → line-by-line translation that fits each original line's
    time (tu/vous, channel glossary, speakers + gender) → one voice per speaker (channel voice + `dub_voices`, or the
    user's pick) placed line by line → original music/sounds kept
    (`separate.py`) → old burned subtitles blurred (auto band or the user's box) → karaoke captions; rights gate
    (`needs_review`)
  - `separate.py` voice / music separation for the dub (UVR MDX-Net Inst_HQ_3 ONNX on onnxruntime, model downloaded once to
    `data/models/`, sha256 checked, CPU)
  - `watch.py` followed YouTube channels/playlists, Bilibili spaces, saved searches → `clip` rows ("New videos")
  - `postiz.py` hand finished videos to a self-hosted Postiz (Public API) for posting
  - `notify.py` Slack alerts: one message to the owner's Incoming Webhook (`SLACK_WEBHOOK_URL`, https://hooks.slack.com only) when a project waits for approval, is done (and whether Postiz took it) or fails; a failure to send is only logged
  - `channels.py` "Channels" profiles (GĐ1): badge, script style, voice, hashtags, script / video approval gates, Postiz
    auto-send after approval (draft / next posting time / now), a 16:9 copy for the Postiz channels ticked for it
    (`final_wide.mp4`, `meta.wide`); projects point to one with `meta.channel`
  - `automake.py` after each scheduled refresh, make videos for new trends at or above a profile's `auto_score`
    (per-profile `auto_daily` cap + `MAX_VIDEOS_PER_DAY`); such projects carry `meta.auto`
  - `i18n.py` engine messages in the UI language (`tr`, `tr_n`, Vietnamese in `VI`, `UI_LANG`)
  - `edit.py` edit a project's script from the app (then re-render from the voice step), delete a project
  - `delogo.py` "Remove logo" tool: remove a static logo from a video the user picks (drawn or auto-found boxes); a
    project source is cleaned only where its final video uses it (`timeline.json`), an upload whole or one part
  - `toolbox.py` Tools page: one-off jobs (download / transcribe / translate subtitles / read text aloud / burn subtitles), each a
    `data/tools/jobs/<id>/` (state.json, in/, out/); a job's output feeds another (`file_job`, `subs_job`); burn draws the
    subtitles with the Pillow overlay (`render.write_caption_track(plain=True)`), never FFmpeg libass
  - `usage.py` Stats page: every successful ElevenLabs call is a `usage` row (characters, estimated USD, project /
    channel / tool job from a ContextVar); price and monthly budget in Settings; over budget pauses `automake` only
  - `inpaint.py` LaMa AI fill for the logo tool (onnxruntime, model downloaded once to `data/models/`, frame by frame)
  - `web.py` + `templates/` legacy Jinja dashboard (to be replaced by the JSON API in M1)
  - `__main__.py` CLI
- `app/` — Tauri 2 + React + TypeScript desktop shell (created in M2).
- `deploy/` + `Dockerfile` — Hetzner server stack (engine + Postiz + Caddy), runbook `docs/DEPLOY.md`.
- `.claude/hooks/office_hook.py` — reports this project's Claude threads to the Flowitup Office (office.flowitup.com); the
  office lives in `github.com/flowitup/office`, which also holds the hook's source and `install-hook.py` to refresh it here.
- `tools/windows/motio-server.ps1` — runs the installed engine 24/7 on a Windows PC at home (Task Scheduler, Tailscale
  only), runbook `docs/WINDOWS_SERVER.md`; the app uses it as a Remote engine and keeps no video on the Mac.
- `tools/` — dev scripts. `docs/` — plans and notes.
- `.claude/skills/motio-dev/` — the dev playbook skill (workflow, gates, ship, release, server rules).
- `data/` — runtime data (SQLite, downloaded sources, rendered projects). Never commit.
- `.env` — secrets. Never read, print, or commit it.

## Commands

```bash
uv sync
uv run python -m motio refresh              # fetch + score hot topics
uv run python -m motio trends               # list scored topics
uv run python -m motio produce <trend_id>   # full pipeline for one topic
uv run python -m motio rerender <project>   # voice + render again from script.json
uv run python -m motio topic "<topic>" [link ...]   # explainer on any topic and/or video links ("" = links only)
uv run python -m motio ai "<topic>" [70|80|90] [ai clips]   # video made only of AI pictures (IMAGE_PROVIDER=placeholder to try it free)
uv run python -m motio dub <link> [start end]      # French dub of one video (times in seconds; none = whole video if short, else Claude picks)
uv run python -m motio watch "<channel link | search words>" [bilibili]   # follow a source and check it now
uv run python -m motio check                # check every followed source · `clips` lists the new videos
uv run python -m motio approve <project> [nosend]  # approve a script / video waiting at a channel's gate
uv run python -m motio automake             # make the trends that meet a channel's auto-make score now
uv run python -m motio retry <project> [step]  # continue from the failed step, or redo from search|download|transcribe|script|voice|render (render keeps the voice)
uv run python -m motio delete <project>     # delete a project and its folder (source cache kept)
uv run python -m motio serve                # legacy dashboard on :8765
# after M1:
uv run python -m motio engine --port 0 --token <t>
# after M2:
cd app && pnpm install && pnpm tauri dev
# release: bump the version (files listed in the dev skill, §9; tests/test_version.py checks them), then
git tag vX.Y.Z && git push origin vX.Y.Z   # CI builds .dmg/.msi into a draft GitHub Release
```

CI (`.github/workflows/ci.yml`) runs ruff + pytest (Ubuntu, Windows), `pnpm build` and `cargo clippy -D warnings`
on every PR; keep them green.

## Conventions

- The UI is English (default) or Vietnamese, picked in Settings → Language (owner, 2026-09-28). Every UI string lives
  in both catalogs of `app/src/i18n.ts` (`vi` is typed as `en`, so a missing string fails `pnpm build`). Engine
  messages the app shows (steps, logs, errors) are written in English inside `tr()` / `tr_n()` from `motio/i18n.py`
  with their Vietnamese in `i18n.VI` (`tests/test_i18n.py` fails when one is missing); the app sets the engine's
  `UI_LANG`. CLI help and the legacy dashboard stay English. Video content is French.
- Code, identifiers and commit messages in English; short comments may be Vietnamese.
- The engine must stay cross-platform: guard OS-specific code with `platform.system()`, use `pathlib`,
  never hardcode `/opt/homebrew` or `C:\` paths outside a lookup helper.
- All LLM calls go through `motio/llm.py`. The `claude_cli` provider strips `ANTHROPIC_API_KEY` from the
  subprocess env so `claude -p` never bills the API account by accident — keep that.
- Source credits are optional (`CREDIT_ON_VIDEO`, `CREDIT_IN_POST`, default off); always write
  `sources.txt` in the project folder.
- AI disclosure (AI Act art. 50): every post keeps "Voix off générée par IA." and the platforms' AI flags (TikTok
  `video_made_with_ai`). The owner removed the on-video "Voix de synthèse (IA)" label on 2026-09-26; don't re-add it
  unless they ask.
- AI video (`motio/creator.py`): every post keeps "Voix off générée par IA." and adds "Images générées par IA." (the
  platforms' AI flags stay on). Only Qwen-Image-2512 on fal (Apache 2.0) is cleared for a monetized channel: a video
  made with the Modal provider (Qwen Research Licence, no safety filter) or the placeholder always stops at the video
  gate (`images.REVIEW_PROVIDERS`), and the pictures are made right before the voice so a script gate stops before any
  picture is paid for. Never make a picture of a real, recognizable person. AI clips (`motio/aiclips.py`, channel profile
  `ai_clips` or a per-video count, off by default) change the post label to "Images et vidéos générées par IA."; they are
  paid per new clip (`AI_CLIP_USD_PER_SEC`, recorded in the `usage` table) and stop when the monthly budget is reached.
- Every video lasts 62–90 s (owner's minimum of 1 min 2 s; Facebook Reels API maximum): `pipeline.MIN_SECONDS` /
  `MAX_SECONDS`, enforced after the voice, not only in the prompt.
- Douyin: `motio/douyin.py` downloads public videos with the `f2` package (Johnserf-Seed/f2, Apache-2.0), added on the
  owner's go of 2026-10-02 (what it does, the test results and how to bump f2: `docs/DOUYIN_F2.md`). f2 is a pinned
  dependency and does Douyin's request signing (`a_bogus`, `msToken`, `ttwid`); never copy that signing code into this
  repo, so a newer f2 brings the new signatures when Douyin changes them. Douyin has to say why a post is gone (removed,
  private, photos) for the download to be final; every other failure (offline, signature out of date, a 403, an answer
  with no post and no reason) falls back to yt-dlp on the plain `douyin.com/video/<id>` link (the id comes from
  `douyin.find_id`, which follows a short link once; `search.download` hands it to f2 and builds the link from it), whose
  extractor needs fresh browser cookies (a guest session is enough), and last to a video file added by hand
  (`localfile.py`). When f2 could not connect at all (`douyin.Unreachable`), yt-dlp still gets its turn, but if it fails
  with its cookie hint the error says "Could not connect to Douyin" instead (yt-dlp asks for cookies even when offline;
  any other yt-dlp error is shown as it is); a link with no id that cannot be fetched without a connection stops there.
  f2 is imported lazily and once, in a background thread that `_f2()` waits for 15 s at most (importing it asks Douyin
  for an `msToken`, and f2 itself retries for ~135 s when packets are dropped; the load goes on and is used by the next
  download if it ends well; a failed import is not started again for two minutes), its logger
  is parked on a `NullHandler` so it makes no `./logs` folder, it gets empty stand-in modules for `browser_cookie3` and
  `execjs` (not installed: LGPL cookie-store reader and a JavaScript runner for livestreams), and tests switch it off
  (`conftest.py`). f2 does not check TLS certificates, so a stream link from its reply is fetched only when it is https to
  a public address, redirects included; keep that check when touching `_save`.
- Logo/watermark removal exists only as the manual "Remove logo" tool (`motio/delogo.py`): the user picks one video and
  starts processing without a rights confirmation form. Preserve previously recorded rights metadata. Never run it
  automatically in the news / topic pipelines or as a batch step, and never add features that evade duplicate /
  Content ID detection.
- A dub (`motio/dub.py`) keeps someone else's pictures and words: it is auto-sent to Postiz only when `meta.rights` is
  owned / licensed / cc, otherwise it stops at the video gate (`dub.needs_review`; `unknown` counts as not owned). The
  subtitle blur covers only the subtitle band, never a logo (logo removal stays the manual tool), and nothing in a dub is
  built to dodge duplicate / Content ID detection.
- Before committing: `uv run ruff check motio` (add ruff as a dev dependency if missing),
  `uv run pytest`, and for render changes `uv run python -m motio rerender 1` + inspect a frame.

## Git

Remote `github.com/flowitup/motio` (private). One branch per milestone (`feat/<name>`), small commits,
open a PR with `gh pr create`. Ask the owner before pushing or opening PRs.
