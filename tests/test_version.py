"""One release number everywhere: the app, the Rust crate and the engine (Settings → Engine status shows the engine's,
which is how an out-of-date remote engine shows)."""
import json
import re
from pathlib import Path

import motio

ROOT = Path(__file__).resolve().parents[1]


def test_the_engine_reports_the_same_version_as_the_app():
    app = json.loads((ROOT / "app/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))["version"]
    package = json.loads((ROOT / "app/package.json").read_text(encoding="utf-8"))["version"]
    cargo = re.search(r'^version = "([^"]+)"', (ROOT / "app/src-tauri/Cargo.toml").read_text(encoding="utf-8"), re.M)
    assert cargo and {motio.__version__, package, cargo.group(1)} == {app}
