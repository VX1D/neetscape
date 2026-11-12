"""test_browser.py: process lifecycle with fake processes (nothing is started)."""
import pytest

from neetscape import browser


class Proc:
    def __init__(self, pid):
        self.pid = pid

    def wait(self, timeout=None):
        return 0


def test_failed_browser_start_stops_xvfb(monkeypatch, tmp_path):
    spawned, killed = [], []

    def popen(args, **kw):
        if args[0] != "Xvfb":
            raise FileNotFoundError(args[0])
        spawned.append(Proc(4242))
        return spawned[-1]
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
