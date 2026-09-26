"""Build latest.json, the Tauri updater manifest, for a draft GitHub release.

Run by .github/workflows/release.yml once the installers are uploaded:

    python3 tools/updater_manifest.py --version v0.3.1 --release release.json --sigs sigs > latest.json

`release.json` is the draft release from the GitHub API (its assets and notes); `sigs/` holds the `.sig` files
`tauri build` wrote next to each update bundle. Bundle URLs are the public download links of the tag
(github.com/<repo>/releases/download/<tag>/<file>), which work once the draft is published.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

# Bundle file suffix → updater targets it serves. The app tries "<os>-<arch>-<installer>" first, then "<os>-<arch>".
TARGETS = {
    ".app.tar.gz": ["darwin-aarch64-app", "darwin-aarch64"],
    ".msi": ["windows-x86_64-msi"],
    "-setup.exe": ["windows-x86_64-nsis", "windows-x86_64"],
}


def build_manifest(
    version: str,
    assets: list[dict],
    sigs: dict[str, str],
    repo: str = "flowitup/motio",
    notes: str | None = None,
    pub_date: str | None = None,
) -> dict:
    version = version.removeprefix("v")
    # A draft's assets live under an "untagged-…" path until it is published, so build the tag URL ourselves.
    base = f"https://github.com/{repo}/releases/download/v{version}"
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
            platforms[target] = {"signature": sig.strip(), "url": f"{base}/{quote(asset['name'])}"}
    manifest = {
        "version": version,
        "pub_date": pub_date or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": platforms,
    }
    if notes and notes.strip():
        manifest["notes"] = notes.strip()
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--release", type=Path, required=True, help="the release from the GitHub API (JSON)")
    ap.add_argument("--sigs", type=Path, required=True, help="folder with the .sig files")
    ap.add_argument("--repo", default="flowitup/motio")
    args = ap.parse_args()
    release = json.loads(args.release.read_text())
    sigs = {p.name: p.read_text() for p in args.sigs.glob("*.sig")}
    try:
        manifest = build_manifest(args.version, release["assets"], sigs, args.repo, release.get("body"))
    except ValueError as e:
        print(f"updater_manifest: {e}", file=sys.stderr)
        return 1
    json.dump(manifest, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
