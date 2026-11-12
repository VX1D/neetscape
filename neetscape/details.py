"""Fetch the full posting text of selected offers: stage 2 of a run (`review.mode: auto`) and `neetscape details`.

Only the posting itself is stored, never page chrome (menus, cookie banners, "similar offers"). Per offer, the
first source that applies (saved as `source` with the posting fields):
- `feed`: the source shipped the full text with the listing;
- `api`: LinkedIn's guest posting endpoint (`LinkedIn.posting_fields`: the description block and job criteria)
  and boards with a JSON posting API (`posting_url`/`posting_text`), over plain HTTP;
- `jsonld` or board data: the offer page fetched in the private browser, one tab per site, read by the board's
  `posting()` (schema.org JobPosting by default; boards whose JSON-LD lacks the body read their embedded data);
- `render`: the board's `posting_selector` on the rendered page, only for boards that declare one.
Otherwise the text stays empty. A 404/410 marks the offer gone; 401/403/429 are saved as blocked, not
rendered; any other failure is saved with HTTP status 0 and an `ERROR ...` text, and never stops the other
offers of the site.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import urllib.parse
from collections import defaultdict

from . import country as countries
from . import infer
from .boards import REGISTRY
from .boards.fetch import BrowserFetch, BrowserRender, FetchError, Http, Limiter
from .boards.linkedin import LinkedIn
from .log import Progress, log, tick
from .model import parse_date
from .posting import parse_posting
from .store import GONE, Store

BLOCKED = (401, 403, 429)  # saved as blocked, never rendered: the page would be a login wall or block page
PLACEHOLDER_COMPANIES = {"confidential", "poufne", "anonymous", "anonim", "ogłoszenie zewnętrzne", "n/a", "-"}


def _languages(board: str, home: str) -> tuple:
    """Languages of a posting: its board's country, else (boards serving any country) the profile's."""
    b = REGISTRY.get(board)
    return countries.languages(countries.text_country(b.caps.country if b else "", home))


def _from_posting(row, text: str, meta: dict, hints: dict, languages) -> dict:
    """Fields the listing card left unknown, read from the posting. The mode only from strong signals (JSON-LD
    TELECOMMUTE, "fully remote" phrases, hybrid words): a long posting mentions "remote" for many reasons."""
    if not text or text.startswith("ERROR"):
        return {}
    mode = "remote" if meta.get("remote") or hints.get("fully_remote") else "hybrid" if hints.get("hybrid") else "unknown"
    found = {"mode": mode, "worktime": infer.worktime_from_text(text, languages)}
    out = {k: v for k, v in found.items() if row[k] == "unknown" and v != "unknown"}
    if not row["contracts"] and (cs := _posting_contracts(row, text, languages)):
        out["contracts"] = ",".join(cs)
    return out


_INTERNSHIP_FIELD = re.compile(r"employment type:\s*internship|rodzaj (?:umowy|zatrudnienia):\s*sta[żz]", re.I)


def _posting_contracts(row, text: str, languages) -> list[str]:
    """Contract types named in the posting. An internship only when the title says so or a labelled field does
    (LinkedIn's "Employment type: Internship"): free text mentions "staż" and "internships" for other reasons
    (a company's 37 years of "stażu", "experience from internships", an internship programme as a benefit)."""
    found = infer.contracts_from_text(text, languages)
    if "internship" in found and not (_INTERNSHIP_FIELD.search(text)
                                      or "internship" in infer.contracts_from_text(row["title"] or "", languages)):
        found.remove("internship")
    return found


def _is_earlier_first_publication(row, meta: dict) -> bool:
    """The posting's date is the first publication (`Board.posting_date_is_first`) and earlier than the stored
    one, which the listing card gave as the last refresh."""
    board, first, stored = REGISTRY.get(row["board"]), parse_date(meta.get("published")), parse_date(row["published"])
    return bool(first and board and board.posting_date_is_first and (not stored or first < stored))


def _save(store: Store, row, status: int, text: str, meta: dict, home: str = "pl") -> None:
    languages = _languages(row["board"], home)
    hints = infer.hints(text, languages)
    store.save_detail(row["id"], status, text, meta, hints)
    tick()
    if (meta.get("company") or "").strip().lower() in PLACEHOLDER_COMPANIES:
        meta = {**meta, "company": ""}
    updates = {k: meta[k] for k in ("company", "published") if meta.get(k) and not row[k]} | _from_posting(row, text, meta, hints, languages)
    if _is_earlier_first_publication(row, meta):
        updates["published"] = meta["published"]
    if updates.get("published") and not parse_date(updates["published"]):
        del updates["published"]
    if updates:
        store.db.execute(f"UPDATE offers SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?", (*updates.values(), row["id"]))
        store.db.commit()


async def _posting(fetch, row, render) -> tuple[int, str, dict]:
    """(status, text, posting fields) of one offer page. The text comes from the board's `posting()` (JSON-LD or
    its embedded data) or, failing that, from the board's `posting_selector` on the rendered page; never from the
    whole page. `meta["source"]` says which. `render()` opens the shared render tab on first use."""
    board = REGISTRY.get(row["board"])
    try:
        page = await fetch.get(row["url"])
        meta = board.posting(page) if board else parse_posting(page)
        status, text = 200, meta.get("description", "")
        meta["source"] = meta.get("source") or ("jsonld" if text else "")
    except FetchError as e:
        status, text, meta = e.status, "", {}
    except Exception as e:
        return 0, _error(e), {}
    selector = board.posting_selector if board else ""
    if not text and selector and status not in GONE + BLOCKED:
        try:
            text = await (await render()).element_text(row["url"], selector)
            meta["source"] = "render" if text else ""
        except Exception as e:
            status, text = 0, _error(e)
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


def _error(e: Exception) -> str:
    return f"ERROR {type(e).__name__}: {e}"


async def _over_http(store: Store, rows, limiter: Limiter, retries: int, home: str, accept: str, read) -> None:
    """Postings served over plain HTTP: `read(http, row)` returns (text, posting fields). A failure is saved for
    its offer and never stops the others."""
    async with Http(limiter, accept, retries) as h:
        for row in rows:
            try:
                text, meta = await read(h, row)
            except FetchError as e:
                _save(store, row, e.status, "", {}, home)
            except Exception as e:
                _save(store, row, 0, _error(e), {}, home)
            else:
                _save(store, row, 200, text, meta, home)


async def _linkedin(h: Http, row) -> tuple[str, dict]:
    """LinkedIn's guest posting endpoint: the description block and job criteria."""
    url = LinkedIn.detail_url(row["url"])
    meta = LinkedIn.posting_fields(await h.get(url)) if url else {}
    return meta.get("description", ""), meta


async def _posting_api(h: Http, row) -> tuple[str, dict]:
    """Boards whose offer pages lack the posting text but have a JSON posting API (`posting_url`, `posting_text`)."""
    board = REGISTRY[row["board"]]
    text, meta = board.posting_text(await h.get(board.posting_url(row["url"])))
    return text, {**meta, "source": "api"}


def route(row) -> str:
    """How a posting is fetched: `text` (shipped by the source), `linkedin`, `api` (posting API) or `browser`."""
    board = REGISTRY.get(row["board"])
    if row["description"]:  # feeds ship the full text
        return "text"
    if row["board"] == "linkedin":
        return "linkedin"
    if getattr(board, "posting_url", None) and board.posting_url(row["url"]):
        return "api"
    return "browser"


async def fetch_details(store: Store, ids: list[int], port: int, limiter: Limiter, retries: int = 2, home: str = "pl") -> int:
    """`home`: the profile's country (language of postings on boards serving any country)."""
    rows = [r for r in (store.offer(i) for i in ids) if r]
    groups: dict[str, list] = defaultdict(list)
    linkedin, api = [], []
    for row in rows:
        how = route(row)
        if how == "text":
            _save(store, row, 200, row["description"], {"source": "feed"}, home)
        elif how == "linkedin":
            linkedin.append(row)
        elif how == "api":
            api.append(row)
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

    with Progress(len(rows), "postings") as progress:
        progress.done = sum(1 for r in rows if route(r) == "text")   # saved above, before the bar existed
        await asyncio.gather(*[guarded(_origin(store, o, rs, port, limiter, retries, home)) for o, rs in groups.items()],
                             guarded(_over_http(store, linkedin, limiter, retries, home, "*/*", _linkedin)),
                             guarded(_over_http(store, api, limiter, retries, home, "application/json", _posting_api)))
    log("details fetched:", len(rows))
    return len(rows)


def detail(store: Store, offer_id: int) -> dict | None:
    row = store.q("SELECT * FROM details WHERE offer_id=?", offer_id)
    if not row:
        return None
    r = row[0]
    return {"status": r["http_status"], "text": r["text"], "hints": json.loads(r["hints"] or "{}"), "fetched_at": r["fetched_at"]}
