"""Transports used by boards, with per-host politeness.

http            plain HTTP (stdlib), run in a thread
browser_fetch   `fetch()` from a tab opened on the board's origin (passes bot checks, no rendering)
browser_render  navigate + scroll + collect (link, link text, card text) triples
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
from ..log import log

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


class Limiter:
    """Minimum interval (plus jitter) between requests to the same host, shared by crawl and details."""

    def __init__(self, min_interval: dict[str, float] | None = None, default: float = 1.5):
        self.min_interval = min_interval or {}
        self.default = default
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            gap = next((v for k, v in self.min_interval.items() if k in host), self.default)
            delay = self._last.get(host, 0) + gap * random.uniform(0.8, 1.3) - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last[host] = time.monotonic()


class FetchError(Exception):
    def __init__(self, status: int, msg: str = ""):
        super().__init__(f"HTTP {status} {msg}")
        self.status = status


def _http_get(url: str, accept: str, language: str = "en", headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": language, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


class Http:
    def __init__(self, limiter: Limiter, accept: str = "*/*", retries: int = 2, headers: dict | None = None,
                 language: str = "en"):
        """`headers`: extra request headers a board needs (e.g. an API key); `language`: Accept-Language."""
        self.limiter, self.accept, self.retries = limiter, accept, retries
        self.headers, self.language = headers or {}, language

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str) -> str:
        status = 0
        for attempt in range(self.retries + 1):
            await self.limiter.wait(url)
            status, body = await asyncio.to_thread(_http_get, url, self.accept, self.language, self.headers)
            if status == 200:
                return body
            if status in (404, 410):
                raise FetchError(status)
            await asyncio.sleep((15 if status == 429 else 3) * (attempt + 1))
        raise FetchError(status, url)


_FETCH = r"""(async(u,shrink)=>{try{const r=await fetch(u,{credentials:'include'});const t=await r.text();
return JSON.stringify([r.status, shrink?shrink(t):t])}catch(e){return JSON.stringify([0,''])}})"""


class BrowserFetch:
    """Same-origin fetch from a tab: the board sees an ordinary browser session."""

    def __init__(self, port: int, origin: str, limiter: Limiter, shrink_js: str | None = None, retries: int = 2):
        self.port, self.origin, self.limiter, self.shrink, self.retries = port, origin, limiter, shrink_js, retries

    async def __aenter__(self):
        self.tab = await Tab(self.port).__aenter__()
        await self.tab.goto(self.origin, 4)
        return self

    async def __aexit__(self, *exc):
        await self.tab.__aexit__(*exc)
        return False

    async def get(self, url: str) -> str:
        status = 0
        for attempt in range(self.retries + 1):
            await self.limiter.wait(url)
            raw = await self.tab.evaluate(f"{_FETCH}({json.dumps(url)},{self.shrink or 'null'})", 90)
            status, body = json.loads(raw or "[0, \"\"]")
            if status == 200:
                return body
            if status in (404, 410):
                raise FetchError(status)
            await asyncio.sleep(3 * (attempt + 1))
        raise FetchError(status, url)


_GRAB = r"""(async()=>{const L=new Map();
const grab=()=>document.querySelectorAll('a[href]').forEach(a=>{const t=(a.innerText||a.textContent||'').trim().replace(/\s+/g,' ').slice(0,500);
 const card=a.closest('li,article,[data-test],[data-cy],div[class*=offer],div[class*=card],div[class*=job]');const c=card?(card.innerText||'').replace(/\s+/g,' ').slice(0,800):'';
 const o=L.get(a.href);L.set(a.href,o?[t.length>o[0].length?t:o[0],c.length>o[1].length?c:o[1]]:[t,c])});
for(let i=0;i<14;i++){grab();window.scrollBy(0,900);await new Promise(r=>setTimeout(r,300))}grab();return JSON.stringify([...L.entries()])})()"""


class BrowserRender:
    """Render a result page and return JSON [[href, [link_text, card_text]], ...]."""

    def __init__(self, port: int, limiter: Limiter, settle: float = 4.0):
        self.port, self.limiter, self.settle = port, limiter, settle

    async def __aenter__(self):
        self.tab = await Tab(self.port).__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self.tab.__aexit__(*exc)
        return False

    async def get(self, url: str) -> str:
        await self.limiter.wait(url)
        await self.tab.goto(url, self.settle)
        raw = await self.tab.evaluate(_GRAB, 120)
        if raw is None:
            log("render: no result for", url)
        return raw or "[]"

    async def page_text(self, url: str) -> str:
        await self.limiter.wait(url)
        await self.tab.goto(url, self.settle + 2)
        return await self.tab.evaluate("document.body.innerText.slice(0,40000)", 60) or ""
