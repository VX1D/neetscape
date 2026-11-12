"""Fetch full posting text for selected offers (two-pass review: list first, then details for picks).

Offers whose source shipped the full text are saved without fetching; LinkedIn postings come over plain
HTTP; every other offer is fetched in the private browser, one tab per site: JSON-LD first, the rendered
page text when the page has none. A 404/410 marks the offer gone; any other failure is saved with HTTP
status 0 and an `ERROR ...` text, and never stops the other offers of the site.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import urllib.parse
from collections import defaultdict

from . import country as countries
from . import infer
from .boards import REGISTRY
from .boards.fetch import BrowserFetch, BrowserRender, FetchError, Http, Limiter
from .boards.linkedin import LinkedIn
from .log import log
from .model import parse_date
from .posting import html_to_text, parse_posting
from .store import Store

GONE = (404, 410)


def _languages(board: str, home: str) -> tuple:
    """Languages of a posting: its board's country, else (boards serving any country) the profile's."""
    b = REGISTRY.get(board)
    return countries.languages(countries.text_country(b.caps.country if b else "", home))


def _save(store: Store, row, status: int, text: str, meta: dict, home: str = "pl") -> None:
    store.save_detail(row["id"], status, text, meta, infer.hints(text, _languages(row["board"], home)))
    updates = {k: meta[k] for k in ("company", "published") if meta.get(k) and not row[k]}
    if updates.get("published") and not parse_date(updates["published"]):
        del updates["published"]
    if updates:
        store.db.execute(f"UPDATE offers SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?", (*updates.values(), row["id"]))
        store.db.commit()


async def _posting(fetch, row, render) -> tuple[int, str, dict]:
    """(status, text, JSON-LD fields) of one posting; `render()` opens the shared render tab on first use."""
    try:
        meta = parse_posting(await fetch.get(row["url"]))
        status, text = 200, meta.get("description", "")
    except FetchError as e:
        status, text, meta = e.status, "", {}
    except Exception as e:
        return 0, f"ERROR {type(e).__name__}: {e}", {}
    if not text and status not in GONE:  # no JSON-LD: render and read the page
        try:
            text = await (await render()).page_text(row["url"])
        except Exception as e:
            status, text = 0, f"ERROR {type(e).__name__}: {e}"
    return status, text, meta


async def _origin(store: Store, origin: str, rows, port: int, limiter: Limiter, retries: int, home: str) -> None:
    async with contextlib.AsyncExitStack() as stack:
        fetch = await stack.enter_async_context(BrowserFetch(port, origin, limiter, None, retries))
        tab = None

        async def render():
            nonlocal tab
            tab = tab or await stack.enter_async_context(BrowserRender(port, limiter))
            return tab

        for row in rows:
            _save(store, row, *await _posting(fetch, row, render), home)


async def _linkedin(store: Store, rows, limiter: Limiter, retries: int, home: str) -> None:
    async with Http(limiter, "*/*", retries) as h:
        for row in rows:
            url = LinkedIn.detail_url(row["url"])
            try:
                html = await h.get(url) if url else ""
                _save(store, row, 200, html_to_text(html), {}, home)
            except FetchError as e:
                _save(store, row, e.status, "", {}, home)


async def fetch_details(store: Store, ids: list[int], port: int, limiter: Limiter, retries: int = 2, home: str = "pl") -> int:
    """`home`: the profile's country (language of postings on boards serving any country)."""
    rows = [r for r in (store.offer(i) for i in ids) if r]
    groups: dict[str, list] = defaultdict(list)
    linkedin = []
    for row in rows:
        if row["description"]:  # feeds ship the full text
            _save(store, row, 200, row["description"], {}, home)
        elif row["board"] == "linkedin":
            linkedin.append(row)
        else:
            u = urllib.parse.urlsplit(row["url"])
            groups[f"{u.scheme}://{u.netloc}/"].append(row)
    tabs = asyncio.Semaphore(4)

    async def guarded(coro):
        async with tabs:
            try:
                await coro
            except Exception as e:
                log("details error:", type(e).__name__, e)

    await asyncio.gather(*[guarded(_origin(store, o, rs, port, limiter, retries, home)) for o, rs in groups.items()],
                         guarded(_linkedin(store, linkedin, limiter, retries, home)))
    log("details fetched:", len(rows))
    return len(rows)


def detail(store: Store, offer_id: int) -> dict | None:
    row = store.q("SELECT * FROM details WHERE offer_id=?", offer_id)
    if not row:
        return None
    r = row[0]
    return {"status": r["http_status"], "text": r["text"], "hints": json.loads(r["hints"] or "{}"), "fetched_at": r["fetched_at"]}
