"""Execute planned requests: page loop, stop rules, ingest into the store.

Stop rules, in order:
  complete  - empty page, page without offers new to this request, page shorter than the board's page size
  partial   - page limit (board max or --limit-pages), incremental stop (newest-first listing reached a page
              whose organic offers were all known from earlier runs), age stop (newest-first listing whose organic
              offers are all older than the loosest `max_age_days` of the searches sharing the request)
Only complete requests are used to mark offers as gone. Promoted offers never trigger a partial stop.

Result cap: a request over the board's `result_cap` (seen from page 1's `total()`, or, on boards without a total,
from an end probe of the cap's last page fetched right after page 1) is replaced by the board's `split()`, or when
it cannot be split by its newest window (`newest()`), which never completes (see `_run_request`).
Transient failures (connection errors, timeouts, HTTP 5xx/429, a page that does not parse on a board whose pages
parsed before) are retried after `RETRY_PAUSES` (`retries` of them); only then does the request end with an error.
The transports do not retry on their own during a crawl, so a page gets at most 1 + `retries` attempts.

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
from .log import Progress, log
from .model import Offer, Search
from .store import PAGE_LIMIT, PAGE_LIMIT_ASKED, Store


def transport_for(board, port: int, limiter: Limiter):
    """The board's transport, without retries of its own: the crawl retries pages itself (`_fetch_page`)."""
    caps = board.caps
    if caps.transport == "http":
        headers = {**(getattr(board, "headers", None) or {}),
                   **({"Content-Type": board.content_type} if getattr(board, "content_type", "") else {})}
        return Http(limiter, getattr(board, "accept", "*/*"), 0, headers=headers or None,
                    language=accept_language(board))
    if caps.transport == "browser_fetch":
        return BrowserFetch(port, caps.origin, limiter, board.fetch_js(), 0)
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


MAX_SPLIT_DEPTH = 3
RETRY_PAUSES = (20, 60)  # seconds before the first and the second retry of a page that failed transiently
EMPTY_PAUSE = 5          # seconds before fetching an empty page again (boards with `Caps.empty_retries`)


def retry_pauses(retries: int) -> tuple:
    """Pauses before each of `retries` retries of a page: `RETRY_PAUSES`, its last one repeated beyond it."""
    return tuple(RETRY_PAUSES[min(i, len(RETRY_PAUSES) - 1)] for i in range(retries)) if RETRY_PAUSES else ()


def probe_page(board, total: int | None, max_pages: int) -> int:
    """The page the end probe fetches right after page 1, or 0 for no probe. Only boards with a `result_cap` and
    no total (`total()` is None) probe: the page holding the cap's last results (`max_pages` when the page size is
    unknown or the pages run out first; LinkedIn: page 100, start=990). No probe when the page limit stops short."""
    caps = board.caps
    if not caps.result_cap or total is not None:
        return 0
    last = min(caps.max_pages, math.ceil(caps.result_cap / caps.page_size)) if caps.page_size else caps.max_pages
    return last if 1 < last <= max_pages else 0


def _probe_shows_cap(caps, last: int, listed: int) -> bool:
    """Whether the end probe of page `last`, listing `listed` offers, shows the cap: a full page, or any offers on the
    board's last page (nothing beyond it can be fetched, so the listing may go on: LinkedIn's start=990). A short
    page below the board's last is the listing's own end within the cap."""
    return listed > 0 and (last == caps.max_pages or listed >= (caps.page_size or 1))


def _label(r: Request) -> tuple:
    """How log lines name a request."""
    return r.board, r.search_id, repr(r.keyword or "*")


def _transient(e: Exception, parsed_before: bool) -> bool:
    """Failures worth a retry after a pause: connection errors and timeouts, HTTP 5xx and 429, and a page that
    does not parse although pages of the same request or board parsed before (a bot wall such as pracuj's page
    without `__NEXT_DATA__`, not a format change)."""
    if isinstance(e, FetchError):
        return e.status == 0 or e.status == 429 or e.status >= 500
    if isinstance(e, (OSError, asyncio.TimeoutError)):  # refused, reset, timed out, DNS (urllib's URLError)
        return True
    return isinstance(e, ValueError) and parsed_before


def _short(e: Exception) -> str:
    return str(e) if isinstance(e, FetchError) else f"{type(e).__name__}: {e}"


async def _fetch_page(board, fetcher, r: Request, page: int, url: str, parsed_before: bool,
                      keep_raw, pauses: tuple) -> tuple[str, list[Offer]]:
    """Fetch and parse one page, retrying transient failures after each of `pauses` and,
    on boards with `empty_retries`, an empty page after `EMPTY_PAUSE`; each retry is logged. The crawl's transport
    has no retries of its own (`transport_for`), so a failing page gets 1 + len(pauses) attempts. `keep_raw(raw)` sees
    every response."""
    body = board.post_body(r, page)
    label = (*_label(r), f"p{page}:")
    empties = 0
    for attempt in range(len(pauses) + 1):
        try:
            while True:
                raw = await (fetcher.get(url, body) if body is not None else fetcher.get(url))
                keep_raw(raw)
                offers = board.parse(raw, r)
                if offers or empties >= board.caps.empty_retries:
                    return raw, offers
                empties += 1
                log(*label, f"empty page; fetching it again in {EMPTY_PAUSE}s ({empties}/{board.caps.empty_retries})")
                await asyncio.sleep(EMPTY_PAUSE)
        except Exception as e:
            if attempt == len(pauses) or not _transient(e, parsed_before or empties > 0):
                raise
            log(*label, _short(e), f"- retry {attempt + 1}/{len(pauses)} in {pauses[attempt]}s")
            await asyncio.sleep(pauses[attempt])
    raise AssertionError("unreachable")


async def _run_request(board, fetcher, r: Request, search: Search, store: Store, run_id: int, *, fx: dict,
                       limit_pages: int | None, incremental: bool, record: Path | None, base: str = "PLN",
                       hours: int | None = None, days: int | None = None, save_fixture: Path | None = None,
                       max_age: float = math.inf, progress: Progress | None = None, depth: int = 0,
                       parsed: set, pauses: tuple, window: str = "") -> None:
    """Fetch one request page by page.

    Result cap: a request reaches the board's `result_cap` when page 1's `total()` says so or, on a board without a
    total, when the end probe (`probe_page`, fetched right after page 1) still lists offers. The board's `split()`
    then replaces it with narrower requests, fetched recursively, each to its own end. A request that cannot be split
    is replaced by `newest()`, the board's newest window (LinkedIn: 7 days, then 24 hours); a windowed request is
    never complete (offers outside the window are not gone) and its stop reason names the window. A capped request
    with neither is fetched up to the cap and logged as capped.

    `parsed`: names of boards with a page parsed in this crawl (a later parse error there is taken as transient and
    retried); `pauses`: the transient retries' pauses; `window`: the label of the newest window `r` is limited to."""
    children: list[Request] = []
    child_window = ""
    capped = 0
    req_id = store.start_request(run_id, r.board, r.search_id, r.keyword, r.params, r.pushed)
    pages = found = 0
    total: int | None = None
    probed, probe_listed = 0, 0  # the end probe's page, once fetched, and how many offers it listed
    complete, reason, error = False, "", ""
    newest_first = r.params.get("sort") == "newest"
    cap = board.caps.result_cap
    # an incremental stop is sound only for a listing crawled to its end before: offers known from other
    # requests (other phrases, other searches) say nothing about what lies deeper in this one
    incremental = incremental and store.completed_before(r.key, run_id)
    max_pages = min(board.caps.max_pages, limit_pages or board.caps.max_pages)
    text_kw = fill_kwargs(text_country(board, r, search)) | {"base": base, "hours": hours, "days": days}

    async def fetch(page: int, url: str) -> tuple[str, list[Offer], int, set]:
        nonlocal pages, found

        def keep_raw(raw: str) -> None:
            if record:
                (record / r.board).mkdir(parents=True, exist_ok=True)
                (record / r.board / f"{hashlib.sha1(url.encode()).hexdigest()[:10]}_p{page}.txt").write_text(url + "\n" + raw)
            if save_fixture and page == 1:  # the raw page only, ready for tests/fixtures/
                save_fixture.parent.mkdir(parents=True, exist_ok=True)
                save_fixture.write_text(raw)

        raw, offers = await _fetch_page(board, fetcher, r, page, url, pages > 0 or board.name in parsed, keep_raw, pauses)
        parsed.add(board.name)
        pages += 1
        if progress:
            progress.active(r.board, f"p{page}")
        for o in offers:
            _apply_pushed(o, r)
            infer.fill_from_text(o, fx, **text_kw)
        new, known = store.ingest(offers, run_id, req_id, page, board.posting_date_is_first)
        found += new
        if progress:
            progress.add(pages=1, offers=new)
        return raw, offers, new, known

    def narrow(raw: str, seen: tuple | None, matches: int) -> str:
        """Replace the capped request by its split, else by its newest window: the stop reason, or '' (neither)."""
        nonlocal children, child_window
        subs = [] if window or depth >= MAX_SPLIT_DEPTH else (
            board.split(raw, r) if seen is None else board.split(raw, r, seen=seen))
        if subs:
            children = subs
            return f"split into {len(subs)} (matches {matches}+, the board shows {cap})"
        if nxt := board.newest(r):
            children, child_window = [nxt[0]], nxt[1]
            return f"narrowed to the newest {nxt[1]} (matches {matches}+, the board shows {cap})"
        return ""

    try:
        for page in range(1, max_pages + 1):
            if page == probed and probe_listed:  # fetched by the end probe already: its stop rule applies now
                if _probe_shows_cap(board.caps, page, probe_listed):
                    reason = "page limit"
                else:
                    complete, reason = True, "last page"
                break
            # an empty probe reached here is contradicted by the full pages before it (LinkedIn's flaky empty
            # body): the page is fetched again like any other
            url = board.page_url(r, page)
            if url is None:
                complete, reason = True, "end"
                break
            raw, offers, new, known = await fetch(page, url)
            if cap and page == 1 and offers:
                total = board.total(raw, r)
                if total is not None and total >= cap:  # boards report a capped count (olx.pl's never exceeds 1000)
                    if reason := narrow(raw, None, total):
                        break
                    capped = total
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
            if page == 1 and (last := probe_page(board, total, max_pages)) and (end := board.page_url(r, last)):
                # the end probe: a board without a total shows its cap by offers on the cap's last page
                _, end_offers, _, _ = await fetch(last, end)
                probed, probe_listed = last, len(end_offers)
                if _probe_shows_cap(board.caps, last, probe_listed):
                    if reason := narrow(raw, tuple(offers) + tuple(end_offers), cap):
                        break
                    capped = cap
        else:
            if board.caps.whole_listing:  # the response was the whole listing (feeds, solid.jobs divisions)
                complete, reason = True, "end"
            else:
                reason = PAGE_LIMIT_ASKED if max_pages < board.caps.max_pages else PAGE_LIMIT
    except FetchError as e:
        if e.status == 404 and pages:  # boards answer 404 for the page after the last one
            complete, reason = True, "end"
        else:
            error = str(e)
    except Exception as e:  # a broken parser must not stop the other boards
        error = f"{type(e).__name__}: {e}"
    if capped and not complete:
        reason = f"{reason}; capped: matches {capped}+, the board shows {cap}"
    if window:  # offers outside the window may still be listed: never complete, so none is marked gone
        complete, reason = False, f"newest {window} (cap {cap})" + (f": {reason}" if reason else "")
    store.finish_request(req_id, pages, found, complete, reason, error)
    log(*_label(r), f"{pages}p +{found}", reason or "", ("ERROR " + error) if error else "")
    if children:
        if progress:
            progress.total += len(children)
        for child in children:
            await _run_request(board, fetcher, child, search, store, run_id, fx=fx, limit_pages=limit_pages,
                               incremental=incremental, record=record, base=base, hours=hours, days=days,
                               max_age=max_age, progress=progress, depth=depth + 1, parsed=parsed, pauses=pauses,
                               window=child_window)
            if progress:
                progress.step()


async def crawl(requests: list[Request], searches: dict[str, Search], store: Store, run_id: int, *, port: int,
                limiter: Limiter, fx: dict, retries: int = 2, limit_pages: int | None = None, incremental: bool = True,
                record: Path | None = None, skip_keys: set[str] = frozenset(), base: str = "PLN",
                hours: int | None = None, days: int | None = None, save_fixture: Path | None = None) -> None:
    """`fx`/`base`/`hours`/`days`: the database currency and the month of the profile's country. `retries`: how
    often a page that failed transiently is fetched again, after `retry_pauses()`; the transports get no retries
    of their own, so this is the only retry policy of the crawl (at most 1 + `retries` attempts per page)."""
    pauses = retry_pauses(retries)
    by_board: dict[str, list[Request]] = defaultdict(list)
    for r in requests:
        if r.key not in skip_keys:
            by_board[r.board].append(r)
    max_age = age_limits(requests, searches)
    tabs = asyncio.Semaphore(4)  # browser tabs open at once
    parsed: set[str] = set()     # boards with a page parsed in this crawl

    async def one_board(name: str, reqs: list[Request], progress: Progress) -> None:
        board = REGISTRY[name]
        uses_browser = board.caps.transport != "http"
        if uses_browser:
            await tabs.acquire()
        try:
            async with transport_for(board, port, limiter) as fetcher:
                for r in reqs:
                    await _run_request(board, fetcher, r, searches[r.search_id], store, run_id, fx=fx,
                                       limit_pages=limit_pages, incremental=incremental, record=record, base=base,
                                       hours=hours, days=days, save_fixture=save_fixture,
                                       max_age=max_age.get(r.key, math.inf), progress=progress, parsed=parsed,
                                       pauses=pauses)
                    progress.step()
        except Exception as e:
            log("ERROR", name, f"{type(e).__name__}: {e}")
        finally:
            progress.active(name, None)
            if uses_browser:
                tabs.release()

    with Progress(sum(len(rs) for rs in by_board.values()), "requests") as progress:
        await asyncio.gather(*[one_board(n, rs, progress) for n, rs in by_board.items()])
