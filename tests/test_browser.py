"""The private browser: process lifecycle and navigation, with fake processes and a fake tab (nothing is started)."""
import asyncio

import pytest

from neetscape import browser


class Proc:
    def __init__(self, pid):
        self.pid = pid

    def wait(self, timeout=None):
        return 0


def test_failed_browser_start_stops_xvfb(monkeypatch, tmp_path):
    killed = []

    def popen(args, **kw):
        if args[0] != "Xvfb":
            raise FileNotFoundError(args[0])
        return Proc(4242)
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    monkeypatch.setattr(browser.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(browser.os, "killpg", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(browser.time, "sleep", lambda s: None)
    monkeypatch.setenv("NEETSCAPE_BROWSER", "/nonexistent/chromium")
    b = browser.Browser(port=1, profile_dir=tmp_path)
    monkeypatch.setattr(b, "alive", lambda: False)
    with pytest.raises(FileNotFoundError):
        b.start()
    assert killed == [4242]


def test_stuck_navigation_is_retried_once():
    tab, calls = browser.Tab.__new__(browser.Tab), []

    async def call(method, params, timeout=180):
        calls.append(method)
        if method == "Page.navigate" and calls.count("Page.navigate") == 1:
            raise asyncio.TimeoutError
        return {}

    tab.call = call
    asyncio.run(tab.goto("https://x", 0))
    assert calls == ["Page.navigate", "Page.stopLoading", "Page.navigate"]
