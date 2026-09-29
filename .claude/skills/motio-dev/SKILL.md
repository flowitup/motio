---
name: motio-dev
description: Develop Motio (flowitup/motio), the Python engine plus Tauri/React desktop app that turns Chinese hot news, or any topic or pasted video links, into French 9:16 videos. Use for any feature, bug fix, test, CI, release, updater or Hetzner deploy work in that repo; runs every task as ak:brainstorm → ak:cook → ak:git / review-pr / ship.
---

# Motio development

Motio = a Python 3.12 **engine** (`motio/`, FastAPI + SQLite, uv) that runs the video pipeline, and a
**Tauri 2 + React 19 + TypeScript** desktop shell (`app/`) that talks to it over HTTP. Two project modes:
**news** (a NewsNow hot topic) and **topic** (an explainer on any topic and / or pasted video links). Single owner
(Manh Trung, GitHub `yaiba2307`), macOS Apple Silicon + Windows x64. Not a SaaS.

Repo `github.com/flowitup/motio`, **public** since 2026-09-26 (so the updater needs no token): treat
everything pushed as public. Default branch **`master`** (renamed from `main` on 2026-09-26). Owner's local clone: `~/Works/motio`.

## 0. Sources of truth, in order

1. `CLAUDE.md` (repo root): conventions and non-negotiables. Read it every session.
2. `docs/APP_PLAN.md`: scope and milestones (M1 engine API ✓, M2 desktop app ✓, M3 packaging ✓ (engine in
   the installers), Server + Postiz ✓, In-app updates ✓, Blueprint GĐ0 ✓, "Beyond hot news" A topic mode ✓,
   B watchlist ✓ → C French dub (GĐ2 parts 1 + 2 ✓), Video length 62–90 s ✓, GĐ1 channel profiles + gates + auto-send ✓, GĐ1 16:9 copy +
   auto-make ✓, M4 automation later). Anything not in it is a new ask: confirm scope with the owner before
   building it. The owner builds the rest of the blueprint one phase at a time, each brainstormed first.
3. `docs/DEPLOY.md` for the server, README for release / updater steps.
4. Project memory (feature list with status, publishing rules, infra). It goes stale: re-check the code
   before calling anything done.
5. The 25/09 "Xưởng Video" blueprint is the long-term vision only; APP_PLAN wins where they conflict.

This skill lives in the repo at `.claude/skills/motio-dev/SKILL.md` (source of truth, loaded by every Claude Code
session in the repo, cloud included). When a change makes it stale, update it in the same PR.

Talk to the owner in the language they wrote in (usually Vietnamese). Keep summaries short: what works,
what is left, what they must do.

## 1. ak workflows (how every task runs)

Every Motio task follows the owner's `ak` skills, in this order, the same way as on Folio:

1. **`/ak:brainstorm`** first. Explore the ask against APP_PLAN and the code, weigh the options, and agree
   one approach with the owner before any code is written. Nothing gets built from an unagreed idea.
2. **`/ak:cook`** builds the agreed approach on a `feat/<slug>` branch (§2), following §3–§5 and passing
   the §6 gates. The cook report goes to `plans/reports/cook-YYMMDD-HHMM-<slug>.md` and names what was
   verified and what was not (e.g. "Render smoke not run", "Not tested on Windows").
3. Then the git loop:

| Step | ak skill | Fallback here |
|---|---|---|
| Stage + conventional commit, push, open the PR | `/ak:git` | §7.1–7.3 |
| Review the PR in place, apply findings, merge, watch CI to green | `/ak:review-pr <N>` (`--fix`, `--merge`) | §7.4–7.6 |
| Whole chain: tests → review → commit → push → PR (→ reviewed merge) | `/ak:ship` | §6 + §7 |
| Docs touched by the change (README, APP_PLAN, DEPLOY, CLAUDE.md) | `/ak:docs` | §7.1 checklist |

Use the ak skills whenever they are installed. The fallback in this file is for sessions without them
(cloud sessions: do the brainstorm and cook steps by hand in the same order, then §7 with the GitHub MCP
tools instead of `gh`), or for long unattended runs where the scripts background better.

Motio rules that hold whichever path you take:
- `plans/` (plans, cook reports, screenshots) is local working material: `plans/` is not in Motio's
  `.gitignore`, so stage files explicitly and never commit it unless the owner asks.
- The §6 gates run before any ak step that commits; `/ak:cook` and `/ak:ship` do not replace the render
  smoke for render / tts / pipeline changes.
- **Ask the owner before pushing or opening a PR** (CLAUDE.md), unless they already said to ship. So
  `/ak:git` / `/ak:ship` only run after that go.
- Merge only on the owner's go (`--merge` included). Motio merges with **merge commits**
  ("Merge pull request #N"), not squash: make sure the merge step keeps that.
- PRs target `master`. A release tag, a deploy run, or anything on the server is never part of an ak run
  (§8, §9).

## 2. Start of a session

```bash
cd ~/Works/motio
git fetch -q origin && git status -sb
git switch -c feat/<slug> origin/master      # one branch per milestone / feature
uv sync                                      # engine deps (+ ruff, pytest)
cd app && pnpm install && cd ..              # only if touching the app
```

- Old clones may still have `main`: `git branch -m main master && git branch -u origin/master master &&
  git remote set-head origin -a`.
- Never read, print, or commit `.env` (settings deny `cat .env*`). Use `.env.example` for key names.
- Never commit `data/` (SQLite, downloaded sources, rendered projects).

## 3. Where things live

| Change | Files |
|---|---|
| Hot-topic fetch, translate, score | `motio/newsnow.py` |
| Source search / download (yt-dlp), pasted links | `motio/search.py` (`YTDLP_COOKIES_FROM_BROWSER` only for pasted links) |
| Transcription | `motio/asr.py` (mlx-whisper on macOS arm64, faster-whisper elsewhere) |
| Any LLM call | `motio/llm.py` only (`complete`, `ask_json`, `parse_json`) |
| Voice | `motio/tts.py` (ElevenLabs with timestamps; macOS `say` is a dev fallback only) |
| 9:16 render, overlays | `motio/render.py` (Pillow draws text and karaoke frames, FFmpeg composes; `snap_start` / `snap_end`) |
| French karaoke captions, SRT / ASS | `motio/captions.py` (`word_times`, `french_words`, `build_cues`, `to_srt`, `to_ass`) |
| Scene cuts | `motio/scenes.py` (FFmpeg `select='gt(scene,0.3)'`, cached next to each source) |
| Pipeline steps, retry, links, quota, video length | `motio/pipeline.py` (`STEPS`, `produce`, `resume`, `add_links`, `rerender`, `_subject`, `MIN_SECONDS` / `MAX_SECONDS`, `target_seconds`, `_fit`) |
| Topic mode (explainer from any topic or links) | `motio/topic.py` (prompts, `RIGHTS`, `DURATIONS`, `create`); project `mode` column in `motio/db.py` |
| Settings layer | `motio/settings.py` (`KEYS`, `SECRETS`; `data/settings.json` over `.env`, read at call time) |
| Paths, binaries, OS checks | `motio/config.py` (`which()`, `env()`, `flag()`, `IS_MAC`/`IS_WIN`) |
| JSON API, refresh scheduler | `motio/api.py` (`create_app(token, headless)`; `REFRESH_EVERY_MIN`) |
| CLI / engine entrypoint | `motio/__main__.py` |
| Edit a project's script, delete a project | `motio/edit.py` (`script_view`, `save_script`, `delete`), `pipeline.write_post`; `app/src/components/{script-card,delete-project}.tsx` |
| Postiz posting | `motio/postiz.py` (`publish`, `publish_project`, `project_video`: vertical / wide), `app/src/components/publish-card.tsx` |
| 16:9 copy of a video | `motio/render.py` (`Layout`, `VERTICAL` / `WIDE`, `_compose`, `render(..., wide=True)` → `final_wide.mp4`), `pipeline._voice_render_post` / `send_to_postiz`, profile `wide_postiz`; tests `tests/test_render.py` (needs FFmpeg), `tests/test_pipeline.py` |
| Auto-make above a channel's score | `motio/automake.py` (`profiles`, `picks`, `start`), `api._refresh(auto=True)` / `_automake` (scheduled refresh only), `db.count_auto_since`, profile `auto_score` / `auto_daily`, CLI `automake`; tests `tests/test_automake.py` |
| "Channels" profiles: badge, script style, voice, hashtags, gates, auto-send | `motio/channels.py` (`clean`, `pick`, `attach`, `for_project`, `badge_for`, `next_slot`), `channel` table in `motio/db.py`, `pipeline._await_review` / `_deliver` / `send_to_postiz` / `approve_video`, `/api/channels`, `POST /api/projects/{id}/approve`, `app/src/pages/channels.tsx`, `app/src/components/channel-choice.tsx`; tests `tests/test_channels.py` |
| French dub mode (excerpt, translation to fit, voice placement, subtitle blur, compare) | `motio/dub.py` (`create`, `from_clip`, `pick_excerpt`, `script`, `voice`, `assign_voices`, `speaker_list`, `detect_band`, `render_args`, `needs_review`, `view`, `update`), `motio/separate.py` (MDX-Net `ensure_model`, `demix`, `instrumental`), `render.Piece(still=…)` / `blur_filter`, `captions.build_cues(hold=…)`, profile `glossary` / `dub_voices`, `POST /api/dubs`, `POST /api/clips/{id}/dub`, `PUT /api/projects/{id}/dub`, CLI `dub`, `app/src/components/dub-cards.tsx`; tests `tests/test_dub.py`, `tests/test_separate.py` |
| "Remove logo" tool (remove a static logo from a video the user picks) | `motio/delogo.py` (`find_static`, `start` / `run` / `cancel`, targets `p<id>-<i>` / `u<hex>`, scopes via `scope_ranges`: a project source only `used`, an upload `all` / `range`, used parts from the render's `timeline.json` via `pieces` / `merge`, `uncovered` warning after a render), `motio/inpaint.py` (LaMa fill: `ensure_model`, `Patch`, `video(ranges=…)`), `/api/delogo/*`, `app/src/pages/delogo.tsx`; tests `tests/test_delogo.py` |
| Tools page (download, transcribe, translate subtitles, read aloud, burn subtitles; jobs chain) | `motio/toolbox.py` (`start`, `run`, `recover`, `parse_subs`, `segment_entries`, `translate`, `burn_cues`, `burn_layout`, `RUNNERS`), `/api/tools/*`, `render.write_caption_track(plain=True)`, `app/src/pages/tools.tsx`; tests `tests/test_toolbox.py` |
| Stats page (ElevenLabs characters and estimated cost per project / channel / tool, monthly budget) | `motio/usage.py` (`context`, `record_tts`, `cost`, `for_project`, `summary`, `over_budget`), `tts.synthesize` records, `db.usage` table, `GET /api/stats`, `app/src/pages/stats.tsx`; tests `tests/test_usage.py` |
| Legacy Jinja dashboard | `motio/web.py` + `templates/` (to be removed; don't extend) |
| UI API client + types | `app/src/lib/api.ts` |
| Engine connection (local/remote) | `app/src/lib/engine.tsx`, `app/src-tauri/src/engine.rs` |
| In-app updater | `app/src-tauri/src/updater.rs`, `app/src/lib/updater.tsx`, `tools/updater_manifest.py` |
| Engine packaging (installers) | `tools/build_engine.py` (PyInstaller onedir), `tools/engine_entry.py`, `tools/fetch_ffmpeg.py` → `app/src-tauri/resources/motio-engine/` |
| Screens | `app/src/pages/{trends,projects,project-detail,settings}.tsx` |
| UI strings | `app/src/i18n.ts` (the only place for UI text: `en` + `vi` catalogs, `t`, `setLang`, `useLang`) |
| Engine messages the app shows | `motio/i18n.py` (`tr`, `tr_n`, Vietnamese in `VI`; language from `UI_LANG`); `tests/test_i18n.py` |
| UI primitives | `app/src/components/ui/*` (shadcn), Tailwind 4 |
| Tauri permissions / config | `app/src-tauri/capabilities/default.json`, `app/src-tauri/tauri.conf.json` |
| Server stack | `Dockerfile`, `deploy/` (compose, Caddyfile, env.example, bootstrap.sh), `docs/DEPLOY.md` |
| GitHub Actions | `.github/workflows/{ci,release,deploy}.yml` (§8) |

Project output folder `data/projects/<id>/`: `script.json`, `audio/`, `final.mp4`, `thumb.jpg`,
`post.txt`, `sources.txt`, `captions.srt`, `captions.ass`, and `delogo/<i>/clean.mp4` when a source had its logo
removed (`meta.sources[i].path` then points there, `orig_path` keeps the cached original). Uploads for the logo tool
live in `data/tools/delogo/<hex>/`.

## 4. Non-negotiables

- **Cross-platform engine.** Guard OS code with `platform.system()` (via `config.IS_MAC` / `IS_WIN`),
  use `pathlib`, find binaries through `config.which()` (honours `MOTIO_FFMPEG`, `MOTIO_FFPROBE`,
  `MOTIO_CLAUDE`, bundled `bin/`). No `/opt/homebrew` or `C:\` outside that lookup helper.
- **All LLM calls through `motio/llm.py`.** The `claude_cli` provider strips `ANTHROPIC_API_KEY` from the
  `claude -p` subprocess env so it bills the Claude plan, not the API account. Keep that.
- **Language.** The UI is English (default) or Vietnamese, switched in Settings → Language (owner, 2026-09-28).
  Every new UI string goes into **both** catalogs in `app/src/i18n.ts` (`vi: Messages`, so a missing one fails
  `pnpm build`); read `t.…` while rendering, never in a module-level constant, or the switch won't show it. Every new
  engine message the app shows (step label, log line, error) is English inside `tr("… {field}", field=…)` /
  `tr_n(n, "noun")` with its Vietnamese added to `i18n.VI` (`tests/test_i18n.py` fails otherwise; `step("Label", …)`
  translates the label). CLI help and the legacy dashboard stay English. Video content and post text are French. Code, identifiers, commits and the README in English (since PR #10;
  `docs/DEPLOY.md` is still Vietnamese); short comments may be Vietnamese.
- **Content rules.** Keep "Voix off générée par IA." in the post and the platforms' AI flags (AI Act art. 50).
  The owner removed the on-video "Voix de synthèse (IA)" label on 2026-09-26; don't re-add it unless they ask.
  Always write `sources.txt`; on-video / in-post credits stay optional (`CREDIT_ON_VIDEO`, `CREDIT_IN_POST`,
  default off). News videos carry an original French script; source clips only illustrate, in short segments.
- **Logo removal stays manual.** The only watermark / logo removal is the "Remove logo" tool (`motio/delogo.py`,
  owner's ask 2026-09-27): the user picks one video (a project source or an upload) and starts it; the owner removed
  the rights confirmation (PR #19) and the per-source rights field (PR #21). A rights value sent through the API is
  still recorded on the source (`meta.sources[i].delogo`) and, once every source is declared, on `meta.rights`: keep
  that. Never apply it automatically in the pipelines or in batch, and **never build** anything that evades
  duplicate / Content ID detection.
- **French dubs keep other people's pictures and words.** `dub.needs_review(proj)` (mode dub and `meta.rights` not
  owned / licensed / cc; `unknown` counts as not owned) makes `pipeline._deliver` stop at the video gate even when the
  channel has none (when it would send to Postiz), so a dub is never auto-sent without a person. The subtitle blur (`dub.detect_band`, the user's box)
  covers the subtitle band only, never a logo; nothing in the dub is built to evade duplicate / Content ID detection.
  The 67 MB separation model is fetched once and sha256-checked (`separate.ensure_model`); dubs must still land in 62–90 s.
- **Rights flag.** Every project carries `meta.rights` = `unknown` | `owned` | `licensed` | `cc`
  (`topic.RIGHTS`; set on `POST /api/projects`, changed with `PATCH /api/projects/{id}`). New features that
  treat footage differently by rights (watermark handling, longer clips, remakes) must read this flag and
  treat `unknown` as not owned.
- **Video length 62–90 s** (owner rule, 2026-09-26). Every video, news or topic, lasts at least 62 s
  (1 min 2 s) and at most 90 s (Facebook Reels API cap): `pipeline.MIN_SECONDS` / `MAX_SECONDS`,
  `target_seconds()` clamps requests (default 80), `_fit()` has Claude lengthen or shorten the script once,
  and render pads the tail to `MIN_SECONDS`. Don't change these bounds without the owner.
- **Engine protocol.** `python -m motio engine` prints exactly one JSON ready line on stdout
  (`{"event":"ready","port":N,...}`); everything after goes to stderr. Don't `print` to stdout before it.
  `/api/*` needs `Authorization: Bearer`; only `/media/*` and the SSE `/events` route accept `?token=`.
  A non-loopback `--host` requires `--token` (on the server it comes from `MOTIO_TOKEN`).
- **Posting** goes only through Postiz's Public API (`POST /api/projects/{id}/publish`, draft by default).
  Never call TikTok / YouTube / Meta / X APIs directly. Automatic sending happens only for a project whose channel
  profile lists Postiz channels, after its gates (`pipeline._deliver`), once per project; later re-renders don't post
  again. A Postiz failure is logged (`meta.send_error`), never fails the video.
- **Approval gates.** A profile's script gate stops `produce` after the script step with status `review`
  (`meta.review = script`) and frees the worker; the video gate stops after the render (`meta.review = video`).
  `review` is not busy (edit, retry, delete allowed) and ends the SSE stream; `produce` clears a pending review.
  Projects without a profile never stop. The video badge comes from `channels.badge_for` ("ACTU CHINE" only for news
  without a profile).
- **Updater trust.** Never commit the updater private key or any GitHub token, and never compile a token
  into the app. From 0.3.1 (PR #8, repo public) the updater needs no token at all.

## 5. Recipes

**New API route.** Add it inside `create_app` in `motio/api.py` with `dependencies=[Depends(auth)]`;
long work goes on the job queue and returns 202. Add the call + its type to `makeApi` in
`app/src/lib/api.ts`. Test it in `tests/test_api.py` with the `client` fixture (pipeline mocked, no network).

**New setting.** Add the key to `settings.KEYS` (and `SECRETS` if it is a secret, so it is masked as
`••••1234`), read it with `config.env("KEY")` / `config.flag("KEY")` at call time (never at import),
add the control + strings in `settings.tsx` / `i18n.ts`, add the row to the README `.env` table and the
key name to `deploy/env.example` if the server needs it. `.env.example` can't be edited from Claude sessions
(§11), so list new keys in the PR body for the owner to add by hand. Test masking / layering in
`tests/test_settings.py`.

**Pipeline change.** `produce` runs `STEPS` = search → download → transcribe → script → voice (voice +
render + post) for both modes; `_subject(proj)` gives the prompts either the trend (news) or the expanded
topic (topic), and pasted links (`meta.links`) are always used before search fills the rest. Each step saves what the next one needs (`meta.chosen`, `meta.sources`, transcript caches,
`script.json`) so `resume()` can continue from the step that broke, or redo from any step (`POST
/api/projects/{id}/retry {start?}`, CLI `retry <id> [step]`). A new or changed step must keep that true:
update `available_steps` / `resume_point` / `_invalidate` and cover it in `tests/test_pipeline.py`. Keep the
`step(name, pct, log)` progress ranges monotonic. Failures raise; the project is marked `failed`.
Any script or voice change must keep the result inside 62–90 s (§4).

**Topic mode change.** Prompts and `create()` live in `motio/topic.py`; the route is `POST /api/projects`
(`TopicIn`: `topic`, `links`, `links_only`, `duration` in `topic.DURATIONS`, `rights`), the CLI is
`topic "<topic>" [link ...]` (`""` = links only). Cover it in `tests/test_api.py` / `tests/test_pipeline.py`
with the LLM mocked.

**Render / caption change.** Caption logic (`captions.word_times`, `french_words`, `build_cues`, `to_srt`,
`to_ass`) is tested in `tests/test_captions.py`; timeline and snapping (`render.build_timeline`,
`snap_start`, `snap_end`) in `tests/test_pure.py`; scene detection in `tests/test_scenes.py` (real FFmpeg,
skipped without it). Captions keep ≤ 2 lines of ≤ 42 characters that also fit the frame, and French
typography (NBSP before `: ; ! ?`, « », ’). Then do the render smoke (§6, gate 4) on the Mac and look at a
frame: the spoken word is highlighted (no on-video AI label since PR #12).

**UI change.** Strings in `i18n.ts` (English and Vietnamese), shadcn primitives from `components/ui`, TanStack
Query for data. Follows OS light/dark; check both, and look at the screen in Vietnamese too (longer labels).

**Workflow change.** Edit the YAML, then prove it: `release.yml` builds installers (no release) on any PR
that touches it; `deploy.yml` only runs by hand or with `AUTO_DEPLOY`, so review it line by line and say
it was not run. Updater manifest logic lives in `tools/updater_manifest.py` with
`tests/test_updater_manifest.py`.

## 6. Gates (all green before a commit)

```bash
# 1. Engine lint + tests (CI runs these on Ubuntu and Windows)
uv run ruff check motio tests          # add tools/ when you touch it; CI doesn't lint it
uv run pytest                          # 205 passed, 6 skipped without FFmpeg (language switch + 16:9 copy, 28/09)
# 2. UI typecheck + build
cd app && pnpm build && cd ..
# 3. Rust (Linux needs libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf first)
cd app/src-tauri && cargo clippy --locked --all-targets -- -D warnings && cd ../..
# 4. Render smoke, for render/tts/pipeline changes (Mac, needs an existing project #1)
uv run python -m motio rerender 1
ffmpeg -y -loglevel error -ss 5 -i data/projects/1/final.mp4 -frames:v 1 /tmp/motio-frame.png   # then look at it
```

- Tests put data in a temp `MOTIO_DATA` (`tests/conftest.py`); never point them at the real `data/`.
- `ruff format` and `cargo fmt` are not enforced (the code uses a 120-col style); don't reformat files.
- Engine smoke: `uv run python -m motio engine --port 0 --token t` prints the ready line, then
  `curl -sS -H "Authorization: Bearer t" http://127.0.0.1:<port>/api/health`.
- UI in a plain browser (no Tauri, e.g. cloud sessions with Playwright): run the engine as above, then
  `cd app && VITE_ENGINE_URL=http://127.0.0.1:<port> VITE_ENGINE_TOKEN=t pnpm dev` and open
  `http://localhost:1420` (already allowed by the engine's CORS). The updater card needs Tauri.
- Full app: `cd app && pnpm tauri dev` (debug builds spawn the engine with uv from the repo root; `MOTIO_UV` /
  `MOTIO_ROOT` override; release builds run the frozen engine from resources; `MOTIO_ENGINE` overrides both). Installing Rust or other system tools: ask the owner first.
- Say plainly what was not run (e.g. "render smoke not run: no project on this machine").

## 7. Ship fallback: commit → PR → CI → merge

Use this when not using `/ak:git`, `/ak:review-pr`, `/ak:ship` (§1).

1. **Commit.** Small, conventional, English: `feat(api): …`, `feat(app): …`, `feat(engine): …`,
   `fix(render): …`, `test: …`, `docs: …`, `ci: …`, `chore: …`. Docs touched by the change (README tables,
   APP_PLAN, DEPLOY, CLAUDE.md layout) go in the same PR.
2. **Ask the owner** before pushing or opening the PR, unless they already said to ship.
3. **PR** against `master`, no template in the repo. Body: Before / After in plain words, a short How, and a
   Verification list (gates with test counts, what was checked on macOS / Windows / in the app).
   ```bash
   git push -u origin feat/<slug>
   gh pr create --base master --title "<commit title>" --body "<body>"
   ```
   In a cloud session without `gh`, use the GitHub MCP tools (`create_pull_request`, draft).
4. **CI** (§8): wait in the background, then keep working:
   ```bash
   RUN=""; for i in $(seq 1 12); do RUN=$(gh run list --branch feat/<slug> --event pull_request --limit 1 --json databaseId -q '.[0].databaseId'); [ -n "$RUN" ] && break; sleep 10; done
   [ -n "$RUN" ] || { echo "no run"; exit 1; }
   gh run watch "$RUN" --exit-status || gh run view "$RUN" --log-failed | tail -80
   ```
   Red CI is work now: reproduce locally, fix, re-run the gates, push. Never skip or disable a test.
5. **Merge** only on the owner's go, as a merge commit: `gh pr merge <N> --merge --delete-branch`.
6. **After merge:** `git switch master && git pull -q && git branch -d feat/<slug>`. Record any new
   landmine in §11 (propose a skill update) or project memory.

## 8. GitHub Actions workflows

| Workflow | Trigger | Does | Needs |
|---|---|---|---|
| **CI** (`ci.yml`) | every PR, push to `master` | Engine (ubuntu + windows): `uv sync --locked`, ruff, pytest. Desktop app (ubuntu): `pnpm build`, clippy `-D warnings` | nothing |
| **Release** (`release.yml`) | tag `v*`; PRs touching it or `tools/{build_engine,engine_entry,fetch_ffmpeg}.py` (build only); manual | freezes the engine (`uv run --group build python tools/build_engine.py`), `.dmg` + `.app.tar.gz` (macOS arm64), `.msi` + `.exe` (Windows), signed update bundles, draft Release, then `latest.json` from `tools/updater_manifest.py` | secrets `TAURI_SIGNING_PRIVATE_KEY` (+ `_PASSWORD`); tag = app version |
| **Deploy (Hetzner)** (`deploy.yml`) | manual; push to `master` touching engine / `deploy/` only if var `AUTO_DEPLOY=true` | builds `ghcr.io/flowitup/motio-engine:sha-<commit>`, copies `deploy/` files to `/opt/motio`, `docker compose pull && up -d --wait` | secrets `HETZNER_HOST/USER/SSH_KEY/KNOWN_HOSTS`; var `MOTIO_PLATFORM` for ARM |

Watch any run with `gh run list --workflow <file> --limit 3` and `gh run watch <id> --exit-status`.

## 9. Release + in-app updates

1. Bump `version` in `app/src-tauri/tauri.conf.json` **and** `app/package.json` (same number), PR, merge.
2. `git tag vX.Y.Z && git push origin vX.Y.Z` (owner's go). The tag must equal that version; a tag build
   without the signing secret fails on purpose.
3. The workflow leaves a **draft** Release with installers and `latest.json`. Installed apps only see an
   update once the owner **publishes** the draft.
4. Installers are unsigned (Gatekeeper "Open Anyway" / SmartScreen "Run anyway") and **bundle the engine**
   (PyInstaller onedir + static ffmpeg, ~460 MB, since PR #3 / 0.3.1). Settings → "Remote engine" (URL + token)
   points the app at an engine on another machine, such as the Hetzner server.
5. Updater: the app checks the latest published release on launch and from Settings → "Update app".
   From 0.3.1 (PR #8, repo public) it reads `releases/latest/download/latest.json` with no token, and
   `latest.json` points at the tag's public download links. Publish a release only while the repo is public.
   (0.3.0 used a per-machine read-only token and API asset URLs; it still updates without one once public.)
6. Signing key (one time, owner): `cd app && pnpm tauri signer generate -w ~/.tauri/motio-updater.key`,
   `gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/motio-updater.key`, set the password secret; the
   public key sits in `plugins.updater.pubkey`. Losing the private key means installed apps can't update.

## 10. Server (Hetzner + Postiz)

Runbook: `docs/DEPLOY.md`. A dedicated Hetzner server (4 vCPU / 8 GB+) runs Caddy, the engine image and
self-hosted Postiz (+ Postgres, Redis, Temporal, Elasticsearch).

- Creating the server, DNS, `/opt/motio/.env`, GitHub secrets, running **Deploy (Hetzner)**, and anything
  over SSH on the server are production actions: wait for the owner's explicit go each time.
- Server LLM is the Claude API (`LLM_PROVIDER=anthropic`, billed per token); Whisper runs on CPU.
- Health: `curl -H "Authorization: Bearer <MOTIO_TOKEN>" https://motio.<domain>/api/health`.
- TikTok / YouTube developer apps stay private until audited: send Postiz drafts until then.

## 11. Landmines

- `mlx-whisper` only installs on macOS arm64; Linux/Windows use `faster-whisper` (CPU int8, CUDA if present).
- `claude -p` is not available on the server or in CI: tests must mock the LLM, TTS, ASR, yt-dlp and Postiz.
- macOS `say` fallback exists for dev only; without an ElevenLabs key on Windows/Linux, `tts.py` raises
  `TTSUnavailable` with a message the UI shows (in the UI language). Keep it that way, never a silent fallback.
- YouTube often blocks downloads from datacenter IPs ("Sign in to confirm you're not a bot"); Bilibili
  usually works. Expect fewer sources on the server.
- `uv` is not on PATH when the app is launched from Finder / Explorer; `engine.rs` searches common
  locations. Keep that list in sync if you change how uv is found.
- The engine does one video at a time (single worker queue) and enforces `MAX_VIDEOS_PER_DAY` in `produce`. "Remove logo"
  jobs have their own one-at-a-time queue (`tools` in `api.py`) so a long LaMa run doesn't hold up production.
- Stale `running` projects are marked `failed` on engine start; don't rely on resuming them.
- Release asset names feed `tools/updater_manifest.py`: renaming bundles or changing `bundles:` in
  `release.yml` breaks updates unless the manifest targets and its test change too.
- `.claude/settings.json` denies `Read(./.env.*)` and `cat .env*`, which also blocks `.env.example`: Claude
  sessions can't add key names there. Put new keys in the PR body for the owner.
- Homebrew FFmpeg has no libass, so captions are not burned with `subtitles=`: Pillow draws each karaoke
  frame and they go on as one timed PNG stream. `captions.ass` is an export only.
- yt-dlp can't search Douyin or X: those come in as pasted links (`{links, links_only}` on produce,
  `POST /api/projects/{id}/links`), with browser cookies from `YTDLP_COOKIES_FROM_BROWSER`.
- French runs long: shorten the script rather than speed up TTS (and stay within 62–90 s, §4).
- Installers run the engine frozen by PyInstaller, not uv. A new dependency that loads data files or plugins
  at runtime may need `--collect-all` in `tools/build_engine.py`; `motio.web` (legacy dashboard) is excluded
  from the freeze. Touch the packaging tools and the PR builds the installers, which proves it.
- The LaMa model is not in the installers: `inpaint.ensure_model` downloads it on the first logo run from OpenCV Zoo
  (pinned by sha256, then 6 shape bytes are patched at fixed offsets). If OpenCV ever replaces that file, downloads
  fail with a "sai sha256" error: update `MODEL_URL`, both hashes and `_FREE_DIMS` together. Tests never download it
  (they use a fake session). The model's input width must be a multiple of 16 and height of 8.

## 12. Cleanup (last step)

Stop the engine, `pnpm dev` / `tauri dev`, and any background CI watchers you started. Leave `data/`
alone except for test projects you created and said you would delete. `git status` must be clean or
explained.
