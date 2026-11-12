"""A private Chromium-family browser driven over the Chrome DevTools Protocol.

The browser runs with its own profile, on a virtual X display (Xvfb) when available,
otherwise headless. It never touches the user's own browser session.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

CANDIDATES = ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "brave", "brave-browser", "/opt/brave-bin/brave")


def find_browser() -> str:
    explicit = os.environ.get("NEETSCAPE_BROWSER")
    if explicit:
        return explicit
    for name in CANDIDATES:
        path = shutil.which(name) or (name if os.path.isabs(name) and os.access(name, os.X_OK) else None)
        if path:
            return path
    raise SystemExit("No Chromium-family browser found. Install chromium or set NEETSCAPE_BROWSER.")


class Browser:
    def __init__(self, port: int = 9334, display: str | None = None, profile_dir: Path | None = None):
        self.port = port
        # one display and one profile per port, so several instances can run side by side
        self.display = display or os.environ.get("NEETSCAPE_DISPLAY") or f":{90 + port % 100}"
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self.profile_dir = profile_dir or cache / "neetscape" / f"browser-profile-{port}"
        self._procs: list[subprocess.Popen] = []

    def alive(self) -> bool:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=2)
            return True
        except Exception:
            return False

    def start(self) -> None:
        """Start a private browser unless one already answers on the port (then it is reused, not owned).
        Whatever was spawned is stopped again when starting fails."""
        if self.alive():
            return
        try:
            self._launch()
        except BaseException:
            self.stop()
            raise

    def _launch(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        args = [find_browser(), f"--user-data-dir={self.profile_dir}", f"--remote-debugging-port={self.port}",
                "--remote-allow-origins=*", "--no-first-run", "--no-default-browser-check", "--window-size=1920,1080"]
        if shutil.which("Xvfb"):
            # A real (virtual) display is less likely to be served bot walls than headless mode.
            self._spawn(["Xvfb", self.display, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"])
            time.sleep(1)
            env["DISPLAY"] = self.display
            env.pop("WAYLAND_DISPLAY", None)
            args.append("--ozone-platform=x11")
        else:
            args.append("--headless=new")
        self._spawn(args + ["about:blank"], env)
        for _ in range(40):
            if self.alive():
                return
            time.sleep(0.5)
        raise SystemExit(f"Browser did not expose CDP on port {self.port}")

    def _spawn(self, args: list[str], env: dict | None = None) -> None:
        self._procs.append(subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            start_new_session=True))

    def stop(self) -> None:
        """Stop only what this instance started: each process group (browser children included), newest first."""
        for proc in reversed(self._procs):
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
        self._procs.clear()

    def __enter__(self) -> "Browser":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


class Tab:
    """One browser tab. Use as `async with Tab(port) as t:`."""

    def __init__(self, port: int):
        self.port = port

    async def __aenter__(self) -> "Tab":
        import websockets
        ver = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version"))
        async with websockets.connect(ver["webSocketDebuggerUrl"]) as b:
            await b.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": "about:blank"}}))
            self.target = json.loads(await b.recv())["result"]["targetId"]
        self.ws = await websockets.connect(f"ws://127.0.0.1:{self.port}/devtools/page/{self.target}", max_size=500_000_000)
        self._id = 0
        return self

    async def __aexit__(self, *exc) -> None:
        await self.ws.close()
        urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/close/{self.target}")

    async def call(self, method: str, params: dict, timeout: float = 180) -> dict:
        self._id += 1
        msg_id = self._id
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
            if msg.get("id") == msg_id:
                return msg.get("result", {})

    async def goto(self, url: str, settle: float) -> None:
        await self.call("Page.navigate", {"url": url})
        await asyncio.sleep(settle)

    async def evaluate(self, expression: str, timeout: float = 600):
        r = await self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}, timeout)
        return r.get("result", {}).get("value")
