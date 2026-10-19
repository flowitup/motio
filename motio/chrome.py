"""A headless Google Chrome for the sites that only answer a real browser.

Douyin's search API answers a signed-out session with `status_code 2483` ("please log in first") and its own search
page is a JavaScript bot check, but the public search site `so.douyin.com` shows the same results to a visitor with no
account (checked 2026-10-19 from the owner's Mac in France: a page, a browser, no login, results with titles, lengths,
views and likes). That page asks `/s/fe/api/aweme/v2/search/msite/general/search/single/` on its own origin, unsigned,
and the answer is the same `aweme_info` cards the app already reads. A plain HTTP client gets the anti-spam answer
(`hit_shark`) and a headless browser that keeps the default "HeadlessChrome" user agent gets Douyin's captcha middle
page, so this runs headless Chrome with the installed Chrome's own version in the user agent and runs the page's own
request in the page context: the page's cookies, fingerprint and session, nothing signed, no login, no captcha solved.
A browser check Douyin still asks for is reported as an error, never worked around.

The engine does not bundle a browser: Google Chrome (or Chromium / Edge, which share this remote-debugging protocol)
must be installed, and `MOTIO_CHROME` can name a different executable. One Chrome starts per call with a throwaway
profile under the data cache and is closed at the end; the session is the one a person would get in a fresh browser.
Tests fake `evaluate`, so no test starts a browser.

`websockets` comes with f2 (its `websockets>=15` dependency; Motio's Douyin download needs f2 anyway).
"""
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import httpx

from . import config

FALLBACK_UA_VERSION = "131.0.0.0"
START_TIMEOUT = 20.0  # how long Chrome has to expose its DevTools port
PAGE_TIMEOUT = 20.0  # how long the page has to say it is complete before the script runs
SETTLE = 4.0  # after the page says it is complete, the page's own scripts (and cookies) get this long
MAX_MESSAGE = 32 << 20  # a search answer with 100 cards is a few MB


class ChromeError(RuntimeError):
    """Chrome is installed but could not be started, or the page/script failed."""


class Missing(ChromeError):
    """No Chrome (or Chromium / Edge) is installed, and MOTIO_CHROME does not name one."""


def _candidates() -> list[Path]:
    """The Chrome-like executables to try, in order: MOTIO_CHROME, then each browser in its usual places."""
    found: list[Path] = []
    override = os.getenv("MOTIO_CHROME")
    if override:
        found.append(Path(override).expanduser())
    system = platform.system()
    if system == "Darwin":
        apps = ("Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser", "Google Chrome Beta")
        for app in apps:
            for root in (Path("/Applications"), Path.home() / "Applications"):
                found.append(root / f"{app}.app" / "Contents/MacOS" / app)
    elif system == "Windows":
        names = {"Google Chrome": Path("Google/Chrome/Application/chrome.exe"),
                 "Chromium": Path("Chromium/Application/chrome.exe"),
                 "Microsoft Edge": Path("Microsoft/Edge/Application/msedge.exe"),
                 "Brave": Path("BraveSoftware/Brave-Browser/Application/brave.exe")}
        for root in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"), os.getenv("LOCALAPPDATA")):
            if not root:
                continue
            for rel in names.values():
                found.append(Path(root) / rel)
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                     "microsoft-edge", "microsoft-edge-stable", "brave-browser"):
            path = shutil.which(name)
            if path:
                found.append(Path(path))
    return found


def find() -> Path | None:
    """The first installed Chrome-like executable, MOTIO_CHROME first; None when there is none."""
    for path in _candidates():
        if path.is_file():
            return path
    return None


def _version(executable: Path) -> str:
    """The browser's own version (for the user agent), or a recent-looking fallback."""
    try:
        out = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return FALLBACK_UA_VERSION
    m = re.search(r"(\d+(?:\.\d+){1,3})", out or "")
    if not m:
        return FALLBACK_UA_VERSION
    version = m[1]
    while version.count(".") < 3:
        version += ".0"
    return version


def user_agent(executable: Path) -> str:
    """The user agent the installed browser itself would send (a real Chrome, not "HeadlessChrome").

    Chrome sends a reduced user agent since version 110: only the major version, `Chrome/<major>.0.0.0`. Sending the
    full four-part build number instead (a pre-110 style) makes so.douyin.com hold the search request, so keep it
    reduced.
    """
    major = _version(executable).split(".")[0] or FALLBACK_UA_VERSION.split(".")[0]
    system = platform.system()
    if system == "Darwin":
        platform_part = "Macintosh; Intel Mac OS X 10_15_7"
    elif system == "Windows":
        platform_part = "Windows NT 10.0; Win64; x64"
    else:
        platform_part = "X11; Linux x86_64"
    return (f"Mozilla/5.0 ({platform_part}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _launch(executable: Path, profile: Path, port: int, headless: str) -> subprocess.Popen:
    args = [str(executable), headless, "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            f"--user-agent={user_agent(executable)}", f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}", "about:blank"]
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if platform.system() == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(args, **kwargs)


def _stop(proc: subprocess.Popen) -> None:
    """Close Chrome and the helpers it started, without waiting on a hung one."""
    try:
        if platform.system() == "Windows":
            proc.terminate()
        else:
            os.killpg(proc.pid, 15)  # SIGTERM to the session (Chrome's helpers are in it)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass


def _wait_for_port(port: int) -> None:
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.15)
    raise ChromeError("Chrome did not open its debugging port")


def _page_socket(port: int) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            pages = httpx.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
        except (httpx.HTTPError, ValueError):
            pages = []
        for page in pages:
            if isinstance(page, dict) and page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
                return page["webSocketDebuggerUrl"]
        time.sleep(0.15)
    raise ChromeError("Chrome opened no page")


class _Session:
    """One page of one Chrome, spoken to over the DevTools protocol."""

    def __init__(self, socket_url: str, timeout: float):
        from websockets.sync.client import connect

        self._ws = connect(socket_url, max_size=MAX_MESSAGE, open_timeout=15)
        self._id = 0
        self._timeout = timeout

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass

    def call(self, method: str, **params):
        self._id += 1
        self._ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        deadline = time.monotonic() + self._timeout
        while True:
            left = max(0.1, deadline - time.monotonic())
            if time.monotonic() >= deadline:
                raise ChromeError(f"Chrome did not answer {method}")
            try:
                message = json.loads(self._ws.recv(timeout=left))
            except TimeoutError:
                raise ChromeError(f"Chrome did not answer {method}") from None
            except Exception as e:  # the socket closed, a page crashed: say it once, with its reason
                raise ChromeError(f"Chrome connection failed: {e}") from e
            if message.get("id") == self._id:
                return message

    def evaluate(self, script: str, timeout: float):
        message = self.call("Runtime.evaluate", expression=script, awaitPromise=True, returnByValue=True,
                            timeout=int(timeout * 1000))
        result = message.get("result") or {}
        if result.get("exceptionDetails"):
            error = result["exceptionDetails"]
            text = error.get("exception", {}).get("description") or error.get("text") or "script error"
            raise ChromeError(str(text)[:300])
        return (result.get("result") or {}).get("value")


def _run(executable: Path, profile: Path, url: str, script: str, timeout: float) -> object:
    port = _free_port()
    proc = _launch(executable, profile, port, "--headless=new")
    session = None
    try:
        _wait_for_port(port)
        session = _Session(_page_socket(port), timeout)
        session.call("Page.enable")
        session.call("Runtime.enable")
        session.call("Page.navigate", url=url)
        deadline = time.monotonic() + PAGE_TIMEOUT
        while time.monotonic() < deadline:
            try:  # a page that is still building can be slow to answer; that is not a failure yet
                state = session.evaluate("document.readyState", timeout=5)
            except ChromeError:
                state = None
            if state == "complete":
                break
            time.sleep(0.3)
        time.sleep(SETTLE)  # the page's own scripts, and the cookies they set
        return session.evaluate(script, timeout)
    finally:
        if session:
            session.close()
        _stop(proc)


def evaluate(url: str, script: str, *, timeout: float = 60.0) -> object:
    """Open `url` in a fresh headless Chrome, run the async `script` in the page, return its JSON value.

    `script` must be an expression that evaluates to a Promise of a JSON value (for example an async arrow function
    called at once: `(async () => ({…}))()`). Missing / ChromeError when no browser can be used; the caller words it.
    """
    executable = find()
    if not executable:
        raise Missing("Google Chrome, Chromium or Microsoft Edge is not installed")
    profile = config.CACHE / "chrome" / f"session-{uuid.uuid4().hex}"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        return _run(executable, profile, url, script, timeout)
    except ChromeError:
        raise
    except (OSError, subprocess.SubprocessError) as e:
        raise ChromeError(f"{type(e).__name__}: {e}"[:300]) from e
    finally:
        shutil.rmtree(profile, ignore_errors=True)
