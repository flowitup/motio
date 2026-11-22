# Build, CI and releases

## Build

```bash
uv run --group build python tools/build_engine.py   # PyInstaller engine + ffmpeg, deno → app/src-tauri/resources/
cd app && pnpm tauri build                          # Motio.app + .dmg (macOS) or .msi (Windows)
```

`tauri build` and `tauri dev` need the folder `app/src-tauri/resources/motio-engine/`. It can stay empty for dev:
the debug build runs the engine with `uv` from the repo.

## CI

`.github/workflows/ci.yml` runs on every PR and every push to `master`: `ruff check` + `pytest` on Ubuntu and
Windows, `pnpm build` (tsc + vite) and `cargo clippy`.

## Release

1. Bump the version in `app/src-tauri/tauri.conf.json`, `app/package.json` and `motio/__init__.py`
   (`tests/test_version.py` checks them; the full list is in the dev skill, §9).
2. Merge the bump PR to `master`. `tag-release.yml` tags `vX.Y.Z` on the merge commit (skipped if the tag exists)
   and starts `release.yml`. By hand: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. CI freezes the engine, builds the `.dmg` (macOS Apple Silicon) and `.msi` / `.exe` (Windows), and makes a draft
   GitHub Release. Check it, then **Publish**.
4. Publishing runs `prune-releases.yml`: only the 3 newest published releases stay, and older drafts are deleted.
   Git tags are kept. Try it first from Actions → Prune releases → Run workflow (dry run by default).

## Auto-update

Settings → *Update app*: the app checks GitHub Releases on launch and on *Check for updates*, verifies the
signature, installs and restarts. Only published releases are offered. The repo is public, so no token is needed;
the app reads `releases/latest/download/latest.json`.

## Signing key (one time)

```bash
cd app && pnpm tauri signer generate -w ~/.tauri/motio-updater.key
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/motio-updater.key
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD
```

Put the public key (`~/.tauri/motio-updater.key.pub`) in `plugins.updater.pubkey` in `app/src-tauri/tauri.conf.json`.
Without the secret a release tag fails. If the private key is lost, installed apps can no longer update
themselves and must be reinstalled by hand.

The installers are not code-signed (see the README for the first-launch steps).
