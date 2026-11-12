"""Logging to stderr, and one progress line for long steps (crawling, fetching postings).

On a terminal the progress line redraws in place below the log lines; when stderr is redirected (a run in
the background writing `run.log`) it is written as a plain `progress ...` line at most every 30 seconds.
"""
from __future__ import annotations

import shutil
import sys
import time

_progress: Progress | None = None


def log(*parts) -> None:
    line = " ".join(str(p) for p in (time.strftime("%H:%M:%S"), *parts))
    if _progress and _progress.tty:
        sys.stderr.write("\r\033[K" + line + "\n")
        _progress.draw(force=True)
    else:
        print(line, file=sys.stderr, flush=True)


def tick(n: int = 1) -> None:
    """Count finished units on the progress line, if one is shown."""
    if _progress:
        _progress.step(n)


class Progress:
    """`total` units (requests, postings); `step()` per finished unit, `active(key, text)` for what is running
    now (e.g. the page a board is on), `add(**counts)` for running totals shown after the bar."""

    def __init__(self, total: int, unit: str, stream=None, every: float = 30.0):
        self.total, self.unit, self.stream, self.every = total, unit, stream or sys.stderr, every
        self.tty = self.stream.isatty()
        self.done, self.counts, self.now = 0, {}, {}
        self.started = self.last = time.monotonic()

    def __enter__(self):
        global _progress
        _progress = self
        self.draw(force=True)
        return self

    def __exit__(self, *exc):
        global _progress
        _progress = None
        if self.tty:
            self.stream.write("\r\033[K")
        self.stream.write(self.line() + "\n")
        self.stream.flush()
        return False

    def step(self, n: int = 1) -> None:
        self.done += n
        self.draw()

    def add(self, **counts: int) -> None:
        for k, v in counts.items():
            self.counts[k] = self.counts.get(k, 0) + v
        self.draw()

    def active(self, key: str, text: str | None) -> None:
        if text is None:
            self.now.pop(key, None)
        else:
            self.now[key] = text
        self.draw()

    def line(self) -> str:
        frac = self.done / self.total if self.total else 1.0
        bar = "█" * round(frac * 20) + "░" * (20 - round(frac * 20))
        parts = [f"[{bar}] {self.done}/{self.total} {self.unit}"] + [f"{v} {k}" for k, v in self.counts.items()]
        if self.now:
            parts.append("now: " + ", ".join(f"{k} {v}" for k, v in sorted(self.now.items())))
        elapsed = time.monotonic() - self.started
        if 0 < self.done < self.total and elapsed > 10:
            left = elapsed / self.done * (self.total - self.done)
            parts.append(f"~{left / 60:.0f} min left" if left >= 90 else f"~{left:.0f} s left")
        return " · ".join(parts)

    def draw(self, force: bool = False) -> None:
        t = time.monotonic()
        if self.tty:
            if force or t - self.last >= 0.2:
                width = shutil.get_terminal_size((120, 20)).columns
                self.stream.write("\r\033[K" + self.line()[:width - 1])
                self.stream.flush()
                self.last = t
        elif force or t - self.last >= self.every:
            self.stream.write(time.strftime("%H:%M:%S") + " progress " + self.line() + "\n")
            self.stream.flush()
            self.last = t
