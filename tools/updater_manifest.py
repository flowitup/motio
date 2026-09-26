"""Build latest.json, the Tauri updater manifest, for a draft GitHub release.

Run by .github/workflows/release.yml once the installers are uploaded:

    python3 tools/updater_manifest.py --version 0.3.0 --assets assets.json --sigs sigs > latest.json

`assets.json` is the release's asset list from the GitHub API; `sigs/` holds the `.sig` files `tauri build` wrote next
to each update bundle. Bundle URLs are API asset URLs (…/releases/assets/<id>), not browser download links, because
the repo is private: the app downloads them with its GitHub token (app/src-tauri/src/updater.rs).
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Bundle file suffix → updater targets it serves. The app tries "<os>-<arch>-<installer>" first, then "<os>-<arch>".
TARGETS = {
    ".app.tar.gz": ["darwin-aarch64-app", "darwin-aarch64"],
    ".msi": ["windows-x86_64-msi"],
    "-setup.exe": ["windows-x86_64-nsis", "windows-x86_64"],
}


def build_manifest(version: str, assets: list[dict], sigs: dict[str, str], pub_date: str | None = None) -> dict:
    platforms: dict[str, dict] = {}
    for suffix, targets in TARGETS.items():
        found = [a for a in assets if a["name"].endswith(suffix)]
        if len(found) != 1:
            names = ", ".join(a["name"] for a in found) or "none"
            raise ValueError(f"expected one *{suffix} asset, found {names}")
        asset = found[0]
        sig = sigs.get(asset["name"] + ".sig")
        if not sig:
            raise ValueError(f"no signature for {asset['name']} (is TAURI_SIGNING_PRIVATE_KEY set?)")
        for target in targets:
            platforms[target] = {"signature": sig.strip(), "url": asset["url"]}
    return {
        "version": version.removeprefix("v"),
        "pub_date": pub_date or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": platforms,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--assets", type=Path, required=True, help="GitHub API release assets (JSON array)")
    ap.add_argument("--sigs", type=Path, required=True, help="folder with the .sig files")
    args = ap.parse_args()
    assets = json.loads(args.assets.read_text())
    sigs = {p.name: p.read_text() for p in args.sigs.glob("*.sig")}
    try:
        manifest = build_manifest(args.version, assets, sigs)
    except ValueError as e:
        print(f"updater_manifest: {e}", file=sys.stderr)
        return 1
    json.dump(manifest, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
