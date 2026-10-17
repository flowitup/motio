"""Read what TikTok's own web pages load, the way a person's browser does: open a page in a headless browser installed
on this computer (Chrome, Edge or Chromium) and keep the JSON answers the page asks for.

Owner's go, 2026-10-17: Motio may do this, for sound *ideas* only (`music.py`: nothing read here goes in a video).
TikTok's web API refuses requests that lack the signature its own page computes; Motio never forges or copies it, a real
browser does. The browser runs with a throwaway profile, is closed when done, and shows what TikTok serves to this
computer's connection (so a computer in France gets French videos). TikTok may refuse a browser it does not like or
change its pages at any time, so every failure is a plain message and nothing else depends on this.

The browser is driven over the DevTools protocol with the `websockets` package (already a dependency); no browser
download and no Playwright.
"""
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from websockets.sync.client import connect

from . import config
from .i18n import tr

LOAD_SECONDS = 45


def find_browser() -> str | None:
    """A Chromium-based browser here: `CHROME_PATH`, else Chrome / Edge / Chromium where the OS keeps them."""
    env = config.env("CHROME_PATH")
    if env and Path(env).is_file():
        return env
    system = platform.system()
    if system == "Darwin":
        apps = ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser")
        paths = [f"/Applications/{a}.app/Contents/MacOS/{a}" for a in apps]
    elif system == "Windows":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        rel = ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe")
        paths = [str(Path(r) / x) for r in roots if r for x in rel]
    else:
        paths = []
    for p in paths:
        if Path(p).is_file():
            return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def available() -> bool:
    return find_browser() is not None




class _Browser:
    """A headless browser with a throwaway profile, and one page driven over the DevTools protocol."""

    def __init__(self, exe: str):
        self.dir = tempfile.mkdtemp(prefix="motio-chart-")
        args = [exe, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.dir}", "--no-first-run",
                "--no-default-browser-check", "--disable-gpu", "--disable-extensions"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:  # Chrome refuses to start as root (a container) otherwise
            args.append("--no-sandbox")
        self.proc = subprocess.Popen([*args, "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws = None
        self.pending: list[dict] = []  # events that arrived while a call waited for its answer
        self._id = 0
        try:
            port = self._port()
            info = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=10).json()
            self.version = info.get("Browser", "")
            self._conn = connect(info["webSocketDebuggerUrl"], max_size=None, open_timeout=10)
            self.ws = self._conn.__enter__()  # a connection manager in newer websockets, the connection in older ones
            target = self.call("Target.createTarget", url="about:blank")["targetId"]
            self.session = self.call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        except Exception:
            self.close()
            raise

    def _port(self) -> int:
        f = Path(self.dir) / "DevToolsActivePort"
        end = time.time() + 20
        while time.time() < end:
            if f.is_file() and f.read_text().strip():
                return int(f.read_text().split()[0])
            if self.proc.poll() is not None:
                break
            time.sleep(0.2)
        raise RuntimeError(tr("The browser did not start"))

    def call(self, method: str, **params) -> dict:
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params}
        if method.startswith(("Network.", "Page.", "Runtime.")):
            msg["sessionId"] = self.session
        self.ws.send(json.dumps(msg))
        end = time.time() + 20
        while time.time() < end:
            data = json.loads(self.ws.recv(timeout=20))
            if data.get("id") == self._id:
                if "error" in data:
                    raise RuntimeError(f"{method}: {data['error'].get('message')}")
                return data.get("result", {})
            self.pending.append(data)
        raise RuntimeError(f"{method}: no answer")

    def close(self) -> None:
        try:
            if self.ws:
                self._conn.__exit__(None, None, None)
        except Exception:  # already gone
            pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.dir, ignore_errors=True)



def collect(url: str, match: str, scrolls: int = 4, seconds: int = LOAD_SECONDS) -> list:
    """Open `url`, scroll `scrolls` times, and return the JSON bodies of the answers whose address holds `match`, in
    the order they arrived. Raises RuntimeError with a plain message when there is no browser or the page is refused;
    returns [] when the page loaded but asked for nothing like `match`."""
    exe = find_browser()
    if not exe:
        raise RuntimeError(tr("Chrome, Edge or Chromium must be installed to read TikTok's pages"))
    try:
        b = _Browser(exe)
    except (OSError, RuntimeError) as e:
        raise RuntimeError(tr("Could not start the browser: {error}", error=str(e)[:160])) from e
    status = None
    found: list = []
    wanted: dict[str, str] = {}
    try:
        # the browser says "HeadlessChrome" in its user agent; send the plain Chrome one it would send with a window
        ua = b.version.replace("HeadlessChrome", "Chrome")
        b.call("Network.enable")
        b.call("Page.enable")
        if ua:
            b.call("Network.setUserAgentOverride", userAgent=f"Mozilla/5.0 ({_os_token()}) AppleWebKit/537.36 "
                   f"(KHTML, like Gecko) {ua} Safari/537.36")
        b.call("Page.navigate", url=url)
        start = time.time()
        end = start + seconds
        next_scroll, done = start + 6, 0  # let the first answers arrive, then scroll for more
        while time.time() < end:
            msgs, b.pending = b.pending, []
            try:
                msgs.append(json.loads(b.ws.recv(timeout=1)))
            except TimeoutError:
                pass
            for m in msgs:
                p = m.get("params", {})
                if m.get("method") == "Network.responseReceived":
                    r = p.get("response", {})
                    if p.get("type") == "Document" and status is None:
                        status = r.get("status")
                    if match in r.get("url", ""):
                        wanted[p["requestId"]] = r["url"]
                elif m.get("method") == "Network.loadingFinished" and p.get("requestId") in wanted:
                    try:
                        found.append(json.loads(b.call("Network.getResponseBody", requestId=p["requestId"])["body"]))
                    except (RuntimeError, ValueError, KeyError):
                        continue
            if time.time() >= next_scroll and done < scrolls:
                b.call("Runtime.evaluate", expression="window.scrollTo(0, document.body.scrollHeight)")
                done += 1
                next_scroll = time.time() + 2.5
            if done >= scrolls and time.time() >= next_scroll + 2:
                break
    finally:
        b.close()
    if not found and status and status >= 400:
        raise RuntimeError(tr("TikTok refused the page (error {status}): try again later or from another network",
                              status=status))
    return found


def _os_token() -> str:
    return {"Darwin": "Macintosh; Intel Mac OS X 10_15_7", "Windows": "Windows NT 10.0; Win64; x64"}.get(
        platform.system(), "X11; Linux x86_64")
