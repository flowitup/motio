"""Pick the GitHub Releases to delete so only the newest few stay.

Run by .github/workflows/prune-releases.yml:

    gh api --paginate repos/<repo>/releases > releases.json
    python3 tools/prune_releases.py --releases releases.json --keep 3 --latest-id <id>

The input is the releases list from the GitHub API (one array, or several arrays when --paginate wrote one per page).
The output is a JSON list of {"id", "tag", "draft", "reason"} to delete; nothing is deleted here.

Rules (owner, 2026-11-21: keep only the 3 newest releases, delete the older ones):
- Releases are ordered by the version in the tag (v0.7.10 is newer than v0.7.9), not by date: a draft has no
  publish date, and a tag that does not read as vX.Y.Z is never touched.
- Only published releases count toward the number kept, so a draft in progress never pushes a published one out.
- The newest published releases stay (--keep of them), and so does the one GitHub serves as "latest" (--latest-id):
  the in-app updater reads releases/latest/download/latest.json.
- A draft older than the newest published release is stale (superseded) and goes; a newer draft is a release
  waiting to be published and stays.
- Git tags are not part of this: the workflow deletes only the Release objects (notes + installers).
"""

import argparse
import json
import re
import sys
from pathlib import Path

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def version(tag: str) -> tuple[int, int, int] | None:
    m = TAG.match(tag)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def plan(releases: list[dict], keep: int = 3, latest_id: int | None = None) -> list[dict]:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    known = [r for r in releases if version(r["tag_name"])]
    newest_first = sorted(known, key=lambda r: version(r["tag_name"]), reverse=True)
    published = [r for r in newest_first if not r["draft"]]
    out = []
    for r in published[keep:]:
        if r["id"] == latest_id:
            continue
        why = f"older than the {keep} newest published"
        out.append({"id": r["id"], "tag": r["tag_name"], "draft": False, "reason": why})
    if published:
        newest = version(published[0]["tag_name"])
        for r in newest_first:
            if r["draft"] and version(r["tag_name"]) < newest:
                why = f"draft older than {published[0]['tag_name']}"
                out.append({"id": r["id"], "tag": r["tag_name"], "draft": True, "reason": why})
    # Safety net: never come back with every published release.
    gone = {x["id"] for x in out}
    if published and all(r["id"] in gone for r in published):
        raise RuntimeError("refusing to delete every published release")
    return out


def load(path: Path) -> list[dict]:
    """`gh api --paginate` prints one JSON array per page; read them all."""
    dec = json.JSONDecoder()
    text, i, items = path.read_text(encoding="utf-8"), 0, []
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        chunk, i = dec.raw_decode(text, i)
        items.extend(chunk if isinstance(chunk, list) else [chunk])
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--releases", type=Path, required=True)
    ap.add_argument("--keep", type=int, default=3)
    ap.add_argument("--latest-id", type=int, default=None)
    args = ap.parse_args(argv)
    json.dump(plan(load(args.releases), args.keep, args.latest_id), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
