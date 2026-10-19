"""The headless Chrome helper (motio/chrome.py): which browser is used and what is said when there is none."""
import platform
import subprocess
from pathlib import Path

import pytest

from motio import chrome


def test_motio_chrome_names_the_browser_and_is_tried_first(monkeypatch, tmp_path):
    exe = tmp_path / "my-chrome"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("MOTIO_CHROME", str(exe))
    assert chrome._candidates()[0] == exe
    assert chrome.find() == exe


def test_find_is_none_when_nothing_is_installed(monkeypatch, tmp_path):
    monkeypatch.delenv("MOTIO_CHROME", raising=False)
    monkeypatch.setattr(chrome, "_candidates", lambda: [tmp_path / "missing"])
    assert chrome.find() is None


def test_evaluate_without_a_browser_raises_missing(monkeypatch):
    monkeypatch.setattr(chrome, "find", lambda: None)
    with pytest.raises(chrome.Missing):
        chrome.evaluate("https://example.com/", "1")
    assert issubclass(chrome.Missing, chrome.ChromeError)


def test_the_user_agent_is_the_installed_chrome_not_headless(monkeypatch):
    monkeypatch.setattr(chrome, "_version", lambda executable: "155.0.8059.84")
    ua = chrome.user_agent(Path("/x/chrome"))
    assert "Chrome/155.0.0.0" in ua and "155.0.8059.84" not in ua and "HeadlessChrome" not in ua
    assert ("Macintosh" in ua) == (platform.system() == "Darwin")


class _Done:
    def __init__(self, stdout=""):
        self.stdout = stdout


def test_the_version_comes_from_the_browser(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Done("Google Chrome 155.0.8059.84\n"))
    assert chrome._version(Path("/x/chrome")) == "155.0.8059.84"


def test_the_version_falls_back_when_the_browser_says_nothing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Done(""))
    assert chrome._version(Path("/x/chrome")) == chrome.FALLBACK_UA_VERSION
