"""Transports used by boards, with per-host politeness.

http            plain HTTP (stdlib), GET or POST, run in a thread
browser_fetch   `fetch()` from a tab opened on the board's origin (passes bot checks, no rendering)

`BrowserRender` is not a board transport: `details` uses it to read a board's `posting_selector` from a rendered
offer page.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

from ..browser import Tab

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


class Limiter:
    """Minimum interval (plus jitter) between requests to the same host, shared by crawl and details."""

    def __init__(self, min_interval: dict[str, float] | None = None, default: float = 1.5):
        self.min_interval = min_interval or {}
        self.default = default
        self._last: dict[str, float] = {}
        self._until: dict[str, float] = {}   # host -> no request before this time (a 429 back-off)
        self._locks: dict[str, asyncio.Lock] = {}

    def pause(self, url: str, seconds: float) -> None:
        """Hold every request to the URL's host for `seconds` from now (the host answered 429)."""
        host = urllib.parse.urlsplit(url).netloc
        self._until[host] = max(self._until.get(host, 0), time.monotonic() + seconds)

    async def wait(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            gap = next((v for k, v in self.min_interval.items() if k in host), self.default)
            delay = max(self._last.get(host, 0) + gap * random.uniform(0.8, 1.3), self._until.get(host, 0)) - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last[host] = time.monotonic()


class FetchError(Exception):
    """A request that did not answer 200 (`status` 0: the browser fetch itself failed)."""

    def __init__(self, status: int, msg: str = ""):
        super().__init__(f"HTTP {status} {msg}")
        self.status = status


def _http_get(url: str, accept: str, language: str = "en", headers: dict | None = None,
              body: str | None = None) -> tuple[int, str]:
    """GET, or POST when `body` is given (its Content-Type comes from `headers`)."""
    req = urllib.request.Request(url, data=body.encode() if body is not None else None,
                                 headers={"User-Agent": UA, "Accept": accept, "Accept-Language": language, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


BACKOFF_429 = 15  # seconds a host is held after answering 429 (times the attempt number)


class Http:
    """Plain HTTP (stdlib), run in a thread."""

    def __init__(self, limiter: Limiter, accept: str = "*/*", retries: int = 2, headers: dict | None = None,
                 language: str = "en"):
        """`headers`: extra request headers a board needs (e.g. an API key); `language`: Accept-Language.
        `retries`: short retries of a non-200 answer (3 s, 6 s, ...) for callers without their own (`details`); the
        crawl passes 0 and retries pages itself. A 429 holds the host in the limiter (`BACKOFF_429`) either way,
        404/410 raise at once, and no pause follows the last attempt."""
        self.limiter, self.accept, self.retries = limiter, accept, retries
        self.headers, self.language = headers or {}, language

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, body: str | None = None) -> str:
        return await _get(self.limiter, url, self.retries,
                          lambda: asyncio.to_thread(_http_get, url, self.accept, self.language, self.headers, body))


async def _get(limiter: Limiter, url: str, retries: int, attempt) -> str:
    """The body of the first attempt answering 200; `attempt()` is awaited as `(status, body)` after the limiter's
    wait. 404/410 raise at once. After another failure a 429 holds the host in the limiter (the next `wait`
    sleeps), anything else pauses 3 s times the attempt number before the next retry; nothing after the last."""
    status = 0
    for n in range(retries + 1):
        await limiter.wait(url)
        status, body = await attempt()
        if status == 200:
            return body
        if status in (404, 410):
            raise FetchError(status)
        if status == 429:
            limiter.pause(url, BACKOFF_429 * (n + 1))
        elif n < retries:
            await asyncio.sleep(3 * (n + 1))
    raise FetchError(status, url)


_FETCH = r"""(async(u,shrink)=>{try{const r=await fetch(u,{credentials:'include'});const t=await r.text();
return JSON.stringify([r.status, shrink?shrink(t):t])}catch(e){return JSON.stringify([0,''])}})"""


class _InTab:
    """A context manager owning one tab of the private browser on `self.port`."""
    port: int

    async def __aenter__(self):
        self.tab = await Tab(self.port).__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self.tab.__aexit__(*exc)
        return False


class BrowserFetch(_InTab):
    """Same-origin fetch from a tab: the board sees an ordinary browser session."""

    def __init__(self, port: int, origin: str, limiter: Limiter, shrink_js: str | None = None, retries: int = 2):
        """`retries`: as for `Http` (the crawl passes 0)."""
        self.port, self.origin, self.limiter, self.shrink, self.retries = port, origin, limiter, shrink_js, retries

    async def __aenter__(self):
        await super().__aenter__()
        await self.tab.goto(self.origin, 4)
        return self

    async def get(self, url: str) -> str:
        return await _get(self.limiter, url, self.retries, lambda: self._fetch_once(url))

    async def _fetch_once(self, url: str) -> tuple[int, str]:
        raw = await self.tab.evaluate(f"{_FETCH}({json.dumps(url)},{self.shrink or 'null'})", 90)
        status, body = json.loads(raw or '[0, ""]')
        return status, body


class BrowserRender(_InTab):
    """A tab that renders pages (navigate, let the page settle) to read one element's text."""

    def __init__(self, port: int, limiter: Limiter, settle: float = 4.0):
        self.port, self.limiter, self.settle = port, limiter, settle

    async def element_text(self, url: str, selector: str) -> str:
        """innerText of the first element matching `selector` on the rendered page ("" when absent)."""
        await self.limiter.wait(url)
        await self.tab.goto(url, self.settle + 2)
        js = f"(document.querySelector({json.dumps(selector)})||{{}}).innerText?.slice(0,40000)||''"
        return await self.tab.evaluate(js, 60) or ""
