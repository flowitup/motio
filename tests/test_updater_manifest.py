import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.updater_manifest import build_manifest

API = "https://api.github.com/repos/flowitup/motio/releases/assets"
DL = "https://github.com/flowitup/motio/releases/download/v0.3.1"
ASSETS = [
    {"name": "Motio_0.3.1_aarch64.dmg", "url": f"{API}/1"},
    {"name": "Motio.app.tar.gz", "url": f"{API}/2"},
    {"name": "Motio_0.3.1_x64_en-US.msi", "url": f"{API}/3"},
    {"name": "Motio_0.3.1_x64-setup.exe", "url": f"{API}/4"},
]
SIGS = {
    "Motio.app.tar.gz.sig": "sig-mac\n",
    "Motio_0.3.1_x64_en-US.msi.sig": "sig-msi",
    "Motio_0.3.1_x64-setup.exe.sig": "sig-nsis",
}


def test_manifest_points_every_target_at_public_tag_downloads():
    m = build_manifest("v0.3.1", ASSETS, SIGS, notes=" Fixes\n", pub_date="2026-09-26T12:00:00Z")
    assert m["version"] == "0.3.1"
    assert m["pub_date"] == "2026-09-26T12:00:00Z"
    assert m["notes"] == "Fixes"
    p = m["platforms"]
    assert p["darwin-aarch64"] == p["darwin-aarch64-app"] == {"signature": "sig-mac", "url": f"{DL}/Motio.app.tar.gz"}
    assert p["windows-x86_64-msi"] == {"signature": "sig-msi", "url": f"{DL}/Motio_0.3.1_x64_en-US.msi"}
    # Windows without an installer hint gets the NSIS setup, like tauri-action does.
    nsis = {"signature": "sig-nsis", "url": f"{DL}/Motio_0.3.1_x64-setup.exe"}
    assert p["windows-x86_64"] == p["windows-x86_64-nsis"] == nsis
    assert "notes" not in build_manifest("0.3.1", ASSETS, SIGS, notes="  ")


def test_manifest_refuses_unsigned_or_missing_bundles():
    with pytest.raises(ValueError, match="no signature for Motio.app.tar.gz"):
        build_manifest("0.3.1", ASSETS, {k: v for k, v in SIGS.items() if "app" not in k})
    with pytest.raises(ValueError, match=r"expected one \*\.msi asset, found none"):
        build_manifest("0.3.1", [a for a in ASSETS if not a["name"].endswith(".msi")], SIGS)


def test_cli_writes_latest_json(tmp_path: Path):
    (tmp_path / "release.json").write_text(json.dumps({"body": "Notes", "assets": ASSETS}))
    sigs = tmp_path / "sigs"
    sigs.mkdir()
    for name, body in SIGS.items():
        (sigs / name).write_text(body)
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [sys.executable, "tools/updater_manifest.py", "--version", "v0.3.1",
         "--release", str(tmp_path / "release.json"), "--sigs", str(sigs), "--repo", "someone/fork"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    m = json.loads(out)
    assert m["notes"] == "Notes"
    assert m["platforms"]["darwin-aarch64"]["url"] == (
        "https://github.com/someone/fork/releases/download/v0.3.1/Motio.app.tar.gz"
    )
