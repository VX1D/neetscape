"""Execute planned requests: page loop, stop rules, ingest into the store.

Stop rules, in order:
  complete  - empty page, page without offers new to this request, page shorter than the board's page size
  partial   - page limit (board max or --limit-pages), incremental stop (newest-first listing reached a page
              whose organic offers were all known from earlier runs), age stop (newest-first listing whose organic
              offers are all older than the loosest `max_age_days` of the searches sharing the request)
Only complete requests are used to mark offers as gone. Promoted offers never trigger a partial stop.

Free text is read in the languages of the board's country (or, for boards serving any country, of the
searched country); amounts without a currency are read in that country's currency; pay is stored per month
in the database currency (`base`, the profile country's).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import math
from collections import defaultdict
from pathlib import Path

from . import country as countries
from . import infer
from .boards import REGISTRY
from .boards.base import Request, accept_language
from .boards.fetch import BrowserFetch, FetchError, Http, Limiter
from .log import log
from .model import Offer, Search
from .store import Store


def transport_for(board, port: int, limiter: Limiter, retries: int):
    caps = board.caps
    if caps.transport == "http":
        headers = {**(getattr(board, "headers", None) or {}),
                   **({"Content-Type": board.content_type} if getattr(board, "content_type", "") else {})}
        return Http(limiter, getattr(board, "accept", "*/*"), retries, headers=headers or None,
                    language=accept_language(board))
    if caps.transport == "browser_fetch":
        return BrowserFetch(port, caps.origin, limiter, board.fetch_js(), retries)
    raise ValueError(f"{board.name}: unknown transport {caps.transport!r}")


def text_country(board, r: Request, search: Search) -> str:
    """Country whose language and currency an offer's text is in: the board's, or the searched one."""
    return countries.text_country(board.caps.country, r.params.get("country") or search.where.country)


def fill_kwargs(code: str) -> dict:
    return {"languages": countries.languages(code), "assume": countries.currency(code)}


def age_limits(requests: list[Request], searches: dict[str, Search]) -> dict[str, float]:
    """Request key -> the largest `max_age_days` among all searches that produce that request (inf = none).
    The planner keeps one request for identical ones, so its own search's limit could be too strict."""
    keys, limits = {r.key for r in requests}, {}
    for name in {r.board for r in requests}:
        for s in searches.values():
            for r in REGISTRY[name].requests(s)[0]:
                if r.key in keys:
                    limits[r.key] = max(limits.get(r.key, 0), s.max_age_days or math.inf)
    return limits


def _partial_stop(organic: list[Offer], known: set[str], incremental: bool, max_age: float) -> str:
    """Reason to stop a newest-first listing early, judged on its organic (not promoted) offers, or ''."""
    if not organic:
        return ""
    if incremental and all(o.key in known for o in organic):
        return "incremental: page already known"
    today = dt.date.today()
    if all(o.published and (today - o.published).days > max_age for o in organic):
        return "older than max_age_days"
    return ""


def _apply_pushed(o: Offer, r: Request) -> None:
    """What the board filtered for us is evidence about the offer."""
    if "remote" in r.pushed and o.mode == "unknown":
        o.mode = "remote"
    if "city" in r.pushed and not o.locations:
        o.locations = [r.params["city"]]


async def _run_request(board, fetcher, r: Request, search: Search, store: Store, run_id: int, *, fx: dict,
                       limit_pages: int | None, incremental: bool, record: Path | None, base: str = "PLN",
                       hours: int | None = None, days: int | None = None, save_fixture: Path | None = None,
                       max_age: float = math.inf) -> None:
    req_id = store.start_request(run_id, r.board, r.search_id, r.keyword, r.params, r.pushed)
    pages = found = 0
    complete, reason, error = False, "", ""
    newest_first = r.params.get("sort") == "newest"
    # an incremental stop is sound only for a listing crawled to its end before: offers known from other
    # requests (other phrases, other searches) say nothing about what lies deeper in this one
    incremental = incremental and store.completed_before(r.key, run_id)
    max_pages = min(board.caps.max_pages, limit_pages or board.caps.max_pages)
    text_kw = fill_kwargs(text_country(board, r, search)) | {"base": base, "hours": hours, "days": days}
    try:
        for page in range(1, max_pages + 1):
            url = board.page_url(r, page)
            if url is None:
                complete, reason = True, "end"
                break
            body = board.post_body(r, page)
            raw = await (fetcher.get(url, body) if body is not None else fetcher.get(url))
            if record:
                (record / r.board).mkdir(parents=True, exist_ok=True)
                (record / r.board / f"{hashlib.sha1(url.encode()).hexdigest()[:10]}_p{page}.txt").write_text(url + "\n" + raw)
            if save_fixture and page == 1:  # the raw page only, ready for tests/fixtures/
                save_fixture.parent.mkdir(parents=True, exist_ok=True)
                save_fixture.write_text(raw)
            offers = board.parse(raw, r)
            pages += 1
            for o in offers:
                _apply_pushed(o, r)
                infer.fill_from_text(o, fx, **text_kw)
            new, known = store.ingest(offers, run_id, req_id, page)
            found += new
            if not offers:
                complete, reason = True, "empty page"
                break
            if new == 0:
                complete, reason = True, "no new offers"
                break
            if board.caps.page_size and len(offers) < board.caps.page_size:
                complete, reason = True, "last page"
                break
            if newest_first:
                reason = _partial_stop([o for o in offers if not o.promoted], known, incremental, max_age)
                if reason:
                    break
        else:
            if board.caps.whole_listing:  # the response was the whole listing (feeds, solid.jobs divisions)
                complete, reason = True, "end"
            else:
                reason = "page limit"
    except FetchError as e:
        if e.status == 404 and pages:  # boards answer 404 for the page after the last one
            complete, reason = True, "end"
        else:
            error = str(e)
    except Exception as e:  # a broken parser must not stop the other boards
        error = f"{type(e).__name__}: {e}"
    store.finish_request(req_id, pages, found, complete, reason, error)
    log(r.board, r.search_id, repr(r.keyword or "*"), f"{pages}p +{found}", reason or "", ("ERROR " + error) if error else "")


async def crawl(requests: list[Request], searches: dict[str, Search], store: Store, run_id: int, *, port: int,
                limiter: Limiter, fx: dict, retries: int = 2, limit_pages: int | None = None, incremental: bool = True,
                record: Path | None = None, skip_keys: set[str] = frozenset(), base: str = "PLN",
                hours: int | None = None, days: int | None = None, save_fixture: Path | None = None) -> None:
    """`fx`/`base`/`hours`/`days`: the database currency and the month of the profile's country."""
    by_board: dict[str, list[Request]] = defaultdict(list)
    for r in requests:
        if r.key not in skip_keys:
            by_board[r.board].append(r)
    max_age = age_limits(requests, searches)
    tabs = asyncio.Semaphore(4)  # browser tabs open at once

    async def one_board(name: str, reqs: list[Request]) -> None:
        board = REGISTRY[name]
        uses_browser = board.caps.transport != "http"
        if uses_browser:
            await tabs.acquire()
        try:
            async with transport_for(board, port, limiter, retries) as fetcher:
                for r in reqs:
                    await _run_request(board, fetcher, r, searches[r.search_id], store, run_id, fx=fx,
                                       limit_pages=limit_pages, incremental=incremental, record=record, base=base,
                                       hours=hours, days=days, save_fixture=save_fixture,
                                       max_age=max_age.get(r.key, math.inf))
        except Exception as e:
            log("ERROR", name, f"{type(e).__name__}: {e}")
        finally:
            if uses_browser:
                tabs.release()

    await asyncio.gather(*[one_board(n, rs) for n, rs in by_board.items()])
