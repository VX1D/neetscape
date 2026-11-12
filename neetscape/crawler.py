"""Execute planned requests: page loop, stop rules, ingest into the store.

Stop rules, in order:
  complete  - empty page, page without offers new to this request, page shorter than the board's page size
  partial   - page limit (board max or --limit-pages), incremental stop (newest-first listing reached a page
              whose organic offers were all known from earlier runs), age stop (newest-first listing whose organic
              offers are all older than the loosest `max_age_days` of the searches sharing the request)
Only complete requests are used to mark offers as gone. Promoted offers never trigger a partial stop.

Result cap: a request over the board's `result_cap` is replaced by the board's `split()` (see `_over_cap`).
Transient failures (connection errors, timeouts, HTTP 5xx/429, a page that does not parse on a board whose pages
parsed before) are retried after `RETRY_PAUSES`; only then does the request end with an error.

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


MAX_SPLIT_DEPTH = 3
RETRY_PAUSES = (20, 60)  # seconds before the first and the second retry of a page that failed transiently
EMPTY_PAUSE = 5          # seconds before fetching an empty page again (boards with `Caps.empty_retries`)


def _over_cap(board, raw: str, r: Request, page: int, total: int | None, listed: int,
              seen: list[Offer]) -> tuple[int, list[Request]] | None:
    """(matches, sub-requests) when the request reaches the board's result cap, else None.
    With a total (read from page 1): a total equal to the cap counts, since boards report a capped count (olx.pl's
    `totalElements` never exceeds 1000). Without one, the cap shows only at the end: the request has listed
    `result_cap` offers or fetched the board's last page (`max_pages`); `split()` then also gets the offers seen."""
    cap = board.caps.result_cap
    if not cap:
        return None
    if total is not None:
        return (total, board.split(raw, r)) if page == 1 and total >= cap else None
    if listed >= cap or page == board.caps.max_pages:
        return listed, board.split(raw, r, seen=tuple(seen))
    return None


def _transient(e: Exception, parsed_before: bool) -> bool:
    """Failures worth a retry after a pause: connection errors and timeouts, HTTP 5xx and 429 (after the
    transport's own short retries), and a page that does not parse although pages of the same request or board
    parsed before (a bot wall such as pracuj's page without `__NEXT_DATA__`, not a format change)."""
    if isinstance(e, FetchError):
        return e.status == 0 or e.status == 429 or e.status >= 500
    if isinstance(e, (OSError, asyncio.TimeoutError)):  # refused, reset, timed out, DNS (urllib's URLError)
        return True
    return isinstance(e, ValueError) and parsed_before


def _short(e: Exception) -> str:
    return str(e) if isinstance(e, FetchError) else f"{type(e).__name__}: {e}"


async def _fetch_page(board, fetcher, r: Request, page: int, url: str, parsed_before: bool,
                      keep_raw=None) -> tuple[str, list[Offer]]:
    """Fetch and parse one page, retrying transient failures after `RETRY_PAUSES` and, on boards with
    `empty_retries`, an empty page after `EMPTY_PAUSE`; each retry is logged. `keep_raw(raw)` sees every response."""
    body = board.post_body(r, page)
    label = (r.board, r.search_id, repr(r.keyword or "*"), f"p{page}:")
    empties = 0
    for attempt in range(len(RETRY_PAUSES) + 1):
        try:
            while True:
                raw = await (fetcher.get(url, body) if body is not None else fetcher.get(url))
                if keep_raw:
                    keep_raw(raw)
                offers = board.parse(raw, r)
                if offers or empties >= board.caps.empty_retries:
                    return raw, offers
                empties += 1
                log(*label, f"empty page; fetching it again in {EMPTY_PAUSE}s ({empties}/{board.caps.empty_retries})")
                await asyncio.sleep(EMPTY_PAUSE)
        except Exception as e:
            if attempt == len(RETRY_PAUSES) or not _transient(e, parsed_before or empties > 0):
                raise
            pause = RETRY_PAUSES[attempt]
            log(*label, _short(e), f"- retry {attempt + 1}/{len(RETRY_PAUSES)} in {pause}s")
            await asyncio.sleep(pause)
    raise AssertionError("unreachable")


async def _run_request(board, fetcher, r: Request, search: Search, store: Store, run_id: int, *, fx: dict,
                       limit_pages: int | None, incremental: bool, record: Path | None, base: str = "PLN",
                       hours: int | None = None, days: int | None = None, save_fixture: Path | None = None,
                       max_age: float = math.inf, progress: Progress | None = None, depth: int = 0,
                       parsed: set | None = None) -> None:
    """Fetch one request page by page. When the request matches more results than the board's `result_cap` (seen
    on page 1 from `total()`, or, for boards without a total, on reaching the cap), the board's `split()` replaces
    it with narrower requests (fetched recursively, each to its own end); a request that cannot be split is
    fetched up to the cap and logged as capped. `parsed`: names of boards with a page parsed in this crawl (a
    later parse error there is taken as transient and retried)."""
    children: list[Request] = []
    capped = 0
    parsed = set() if parsed is None else parsed
    req_id = store.start_request(run_id, r.board, r.search_id, r.keyword, r.params, r.pushed)
    pages = found = listed = 0
    total: int | None = None
    seen: list[Offer] = []
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

            def keep_raw(raw: str, url: str = url, page: int = page) -> None:
                if record:
                    (record / r.board).mkdir(parents=True, exist_ok=True)
                    (record / r.board / f"{hashlib.sha1(url.encode()).hexdigest()[:10]}_p{page}.txt").write_text(url + "\n" + raw)
                if save_fixture and page == 1:  # the raw page only, ready for tests/fixtures/
                    save_fixture.parent.mkdir(parents=True, exist_ok=True)
                    save_fixture.write_text(raw)

            raw, offers = await _fetch_page(board, fetcher, r, page, url, pages > 0 or board.name in parsed, keep_raw)
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
            listed += len(offers)
            if board.caps.result_cap:
                if page == 1:
                    total = board.total(raw, r)
                if total is None:
                    seen += offers
                if offers and not capped and (over := _over_cap(board, raw, r, page, total, listed, seen)):
                    matches, subs = over
                    if subs and depth < MAX_SPLIT_DEPTH:
                        children, reason = subs, f"split into {len(subs)} (matches {matches}+, the board shows {board.caps.result_cap})"
                        break
                    capped = matches
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
                reason = PAGE_LIMIT_ASKED if max_pages < board.caps.max_pages else PAGE_LIMIT
    except FetchError as e:
        if e.status == 404 and pages:  # boards answer 404 for the page after the last one
            complete, reason = True, "end"
        else:
            error = str(e)
    except Exception as e:  # a broken parser must not stop the other boards
        error = f"{type(e).__name__}: {e}"
    if capped and not complete:
        reason = f"{reason}; capped: matches {capped}+, the board shows {board.caps.result_cap}"
    store.finish_request(req_id, pages, found, complete, reason, error)
    log(r.board, r.search_id, repr(r.keyword or "*"), f"{pages}p +{found}", reason or "", ("ERROR " + error) if error else "")
    if children:
        if progress:
            progress.total += len(children)
        for child in children:
            await _run_request(board, fetcher, child, search, store, run_id, fx=fx, limit_pages=limit_pages,
                               incremental=incremental, record=record, base=base, hours=hours, days=days,
                               max_age=max_age, progress=progress, depth=depth + 1, parsed=parsed)
            if progress:
                progress.step()


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
    parsed: set[str] = set()     # boards with a page parsed in this crawl

    async def one_board(name: str, reqs: list[Request], progress: Progress) -> None:
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
                                       max_age=max_age.get(r.key, math.inf), progress=progress, parsed=parsed)
                    progress.step()
        except Exception as e:
            log("ERROR", name, f"{type(e).__name__}: {e}")
        finally:
            progress.active(name, None)
            if uses_browser:
                tabs.release()

    with Progress(sum(len(rs) for rs in by_board.values()), "requests") as progress:
        await asyncio.gather(*[one_board(n, rs, progress) for n, rs in by_board.items()])
