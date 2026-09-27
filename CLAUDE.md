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
  - `search.py` yt-dlp search/download · `asr.py` mlx-whisper (macOS arm64) / faster-whisper (elsewhere)
  - `llm.py` `claude -p` or Anthropic API · `tts.py` ElevenLabs (macOS `say` fallback for dev only)
  - `render.py` 9:16 composition · `pipeline.py` project steps (`produce`, `resume`, `rerender`)
  - `captions.py` French karaoke cues + SRT/ASS · `scenes.py` scene cuts (FFmpeg scene filter)
  - `topic.py` topic mode: explainer from any topic or video links (prompts, rights flag, `create`)
  - `watch.py` followed YouTube channels/playlists, Bilibili spaces, saved searches → `clip` rows ("Video mới")
  - `postiz.py` hand finished videos to a self-hosted Postiz (Public API) for posting
  - `edit.py` edit a project's script from the app (then re-render from the voice step), delete a project
  - `delogo.py` "Xoá logo" tool: remove a static logo from a video the user picks (drawn or auto-found boxes)
  - `inpaint.py` LaMa AI fill for the logo tool (onnxruntime, model downloaded once to `data/models/`, frame by frame)
  - `web.py` + `templates/` legacy Jinja dashboard (to be replaced by the JSON API in M1)
  - `__main__.py` CLI
- `app/` — Tauri 2 + React + TypeScript desktop shell (created in M2).
- `deploy/` + `Dockerfile` — Hetzner server stack (engine + Postiz + Caddy), runbook `docs/DEPLOY.md`.
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
uv run python -m motio watch "<channel link | search words>" [bilibili]   # follow a source and check it now
uv run python -m motio check                # check every followed source · `clips` lists the new videos
uv run python -m motio retry <project> [step]  # continue from the failed step, or redo from search|download|transcribe|script|voice
uv run python -m motio delete <project>     # delete a project and its folder (source cache kept)
uv run python -m motio serve                # legacy dashboard on :8765
# after M1:
uv run python -m motio engine --port 0 --token <t>
# after M2:
cd app && pnpm install && pnpm tauri dev
# release: bump version in app/src-tauri/tauri.conf.json, then
git tag vX.Y.Z && git push origin vX.Y.Z   # CI builds .dmg/.msi into a draft GitHub Release
```

CI (`.github/workflows/ci.yml`) runs ruff + pytest (Ubuntu, Windows), `pnpm build` and `cargo clippy -D warnings`
on every PR; keep them green.

## Conventions

- UI text is Vietnamese (keep strings in one dictionary so FR/EN can be added). Video content is French.
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
- Every video lasts 62–90 s (owner's minimum of 1 min 2 s; Facebook Reels API maximum): `pipeline.MIN_SECONDS` /
  `MAX_SECONDS`, enforced after the voice, not only in the prompt.
- Logo/watermark removal exists only as the manual "Xoá logo" tool (`motio/delogo.py`): the user picks one video and
  confirms they own it or hold the rights (`owned` / `licensed`, recorded on the video and the project). Never run it
  automatically in the news / topic pipelines or as a batch step, and never add features that evade duplicate /
  Content ID detection.
- Before committing: `uv run ruff check motio` (add ruff as a dev dependency if missing),
  `uv run pytest`, and for render changes `uv run python -m motio rerender 1` + inspect a frame.

## Git

Remote `github.com/flowitup/motio` (private). One branch per milestone (`feat/<name>`), small commits,
open a PR with `gh pr create`. Ask the owner before pushing or opening PRs.
