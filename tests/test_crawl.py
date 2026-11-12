"""The crawl on the fake board: where a request stops, result caps (split, end probe, newest windows), retries,
--resume, and the HTTP transport's own retries and host pauses."""
import asyncio
from dataclasses import replace

import pytest

from conftest import ALL_REMOTE, cards, crawl, page, requests_of
from neetscape import crawler, log
from neetscape.boards import fetch
from neetscape.boards.base import Caps
from neetscape.boards.fetch import FetchError, Http, Limiter
from neetscape.model import Search, Where
from neetscape.store import PAGE_LIMIT_ASKED

REAL_GET, REAL_WAIT = Http.get, Limiter.wait   # before the `http` fixture replaces them
PROBED = Caps(keywords=True, remote="filter", page_size=3, max_pages=10, result_cap=30, transport="http")


def listing(fake, http, sizes, empty=None):
    """Requests keyed `cat@days` (their params); `sizes[key]` offers in all, 3 per page (None: endless); `empty[url]`:
    that many empty answers first. Returns the URLs asked, as "cat@days/page"."""
    fake.page_url = lambda r, n: f"fake://{r.params.get('cat', '')}@{r.params.get('days', '')}/{n}"
    empty, asked = dict(empty or {}), []

    def answer(url):
        tail = url[len("fake://"):]
        asked.append(tail)
        key, n = tail.rsplit("/", 1)
        if empty.get(tail):
            empty[tail] -= 1
            return "[]"
        total, start = sizes[key] if sizes[key] is not None else 10 ** 6, (int(n) - 1) * 3
        return page([[f"{key}{i}", "Job", {}] for i in range(start, min(total, start + 3))])
    http(answer)
    return asked


def split_into(*cats, given):
    """A `split()` turning a request without a category into one per `cats`; records in `given` the cards it got."""
    def split(raw, r, seen=()):
        given[r.params.get("cat", "")] = [o.key for o in seen]
        return [] if r.params.get("cat") else [replace(r, params={**r.params, "cat": c}) for c in cats]
    return split


def newest_windows(r):
    nxt = {None: (7, "7 days"), 7: (1, "24 hours")}.get(r.params.get("days"))
    return (replace(r, params={**r.params, "days": nxt[0]}), nxt[1]) if nxt else None


# where a request stops

@pytest.mark.parametrize("caps,page2,stop", [
    (dict(max_pages=1, whole_listing=True), None, (1, "end")),   # a full single page is the whole listing
    (dict(max_pages=1), None, (0, "page limit")),                # e.g. Indeed's 1 public page: offers beyond it are not gone
    (dict(), FetchError(404), (1, "end")),                       # a 404 after the last page
])
def test_last_page(fake, http, db, caps, page2, stop):
    fake.caps = replace(fake.caps, sort_newest=False, **caps)
    http(lambda url: page2 if url.endswith("/2") else page(cards("a", "b", "c")))
    req = requests_of(db, crawl(db))[""]
    assert (req["complete"], req["stop_reason"], req["error"]) == (*stop, "")


def test_incremental_stop_ignores_known_promoted_offers(fake, db):
    fake.pages = {("*", 1): [["p", "Promo", {"promoted": True}], *cards("a")]}
    crawl(db)
    fake.pages = {("*", 1): [["p", "Promo", {"promoted": True}], *cards("a", "b")], ("*", 2): cards("c")}
    assert {o["key"] for o in db.run_offers(crawl(db))} == {"p", "a", "b", "c"}


def test_incremental_stop_needs_the_same_request_completed_before(fake, db):
    fake.pages = {("x", 1): cards("a", "b", "c")}
    crawl(db, Search(id="kw", label="kw", where=Where(remote=True), keywords=("x",)))   # the phrase search sees a, b, c
    fake.pages = {("*", 1): cards("a", "b", "c"), ("*", 2): cards("d", "e", "f")}
    req = requests_of(db, crawl(db), by=None)[None]                       # "all" was never crawled to its end: no stop
    assert req["pages"] == 3 and req["complete"] and db.offer("https://fake/f")


def test_age_stop_uses_the_loosest_search_sharing_a_request(fake, db):
    fake.pages = {("*", 1): cards("a", "b", "c", published="2020-01-01"), ("*", 2): cards("d", published="2020-01-01")}
    recent = Search(id="recent", label="recent", where=Where(remote=True), keywords=None, max_age_days=7)
    assert len(db.run_offers(crawl(db, recent, replace(recent, id="any", max_age_days=None)))) == 4


# result caps

def test_request_over_the_result_cap_is_split_recursively(fake, http, db):
    fake.caps = replace(PROBED, result_cap=5)
    totals = {"": 9, "a": 4, "b": 5, "b1": 3, "b2": 2}                 # b reaches the cap (5): split again
    tree = {"": ["a", "b"], "b": ["b1", "b2"]}
    fake.total = lambda raw, r: totals[r.params.get("cat", "")]
    fake.split = lambda raw, r: [replace(r, params={**r.params, "cat": c}) for c in tree.get(r.params.get("cat", ""), [])]
    listing(fake, http, {k + "@": n if k in ("a", "b1", "b2") else 3 for k, n in totals.items()})   # leaves list their own
    reqs = requests_of(db, rid := crawl(db))
    assert set(reqs) == set(totals) and all(reqs[k]["complete"] for k in ("a", "b1", "b2"))
    assert reqs[""]["stop_reason"].startswith("split into 2") and reqs["b"]["stop_reason"].startswith("split into 2")
    assert {o["key"] for o in db.run_offers(rid)} >= {f"{c}@{i}" for c, n in (("a", 4), ("b1", 3), ("b2", 2)) for i in range(n)}


def test_small_cap_is_probed_on_the_page_holding_its_last_results(fake, http, db):
    fake.caps, seen = replace(PROBED, result_cap=6), {}
    fake.split = split_into("a", "b", given=seen)
    listing(fake, http, {"@": None, "a@": 4, "b@": 2})
    reqs = requests_of(db, crawl(db))
    assert reqs[""]["pages"] == 2 and not reqs[""]["complete"]          # cap 6 / 3 per page: page 2 is probed
    assert reqs[""]["stop_reason"] == "split into 2 (matches 6+, the board shows 6)"
    assert seen == {"": ["@0", "@1", "@2", "@3", "@4", "@5"]}            # split() gets page 1 and the probed page
    # "a" (4 offers): its probed page 2 is short, the listing's own end within the cap; "b": page 1 is short
    assert reqs["a"]["complete"] and reqs["b"]["complete"] and reqs["a"]["found"] == 4
    assert (reqs["a"]["pages"], reqs["a"]["stop_reason"]) == (2, "last page")


def test_end_probe_splits_right_after_page_one_when_the_cap_is_reached(fake, http, db):
    fake.caps, seen = PROBED, {}
    fake.split = split_into("a", "b", given=seen)
    asked = listing(fake, http, {"@": None, "a@": 7, "b@": 2})
    reqs = requests_of(db, crawl(db))
    assert asked[:2] == ["@/1", "@/10"]                                 # page 1, then the probe of the last page
    assert (reqs[""]["pages"], reqs[""]["found"], reqs[""]["complete"]) == (2, 6, 0)   # the probe counts as a page
    assert reqs[""]["stop_reason"] == "split into 2 (matches 30+, the board shows 30)"
    assert seen == {"": ["@0", "@1", "@2", "@27", "@28", "@29"]}        # the cards of page 1 and of the probed page
    # the parts: "a" probes page 10 (empty: under the cap), then pages to its end; "b" ends on a short page 1
    assert asked[2:] == ["a@/1", "a@/10", "a@/2", "a@/3", "b@/1"]
    assert (reqs["a"]["pages"], reqs["a"]["found"], reqs["a"]["complete"], reqs["a"]["stop_reason"]) == (4, 7, 1, "last page")
    assert (reqs["b"]["pages"], reqs["b"]["complete"]) == (1, 1)


def test_end_probe_is_counted_in_the_progress(fake, http, db, monkeypatch):
    fake.caps, fake.split = PROBED, lambda raw, r, seen=(): []
    counted, real_add = [], log.Progress.add
    monkeypatch.setattr(log.Progress, "add", lambda self, **c: counted.append(c) or real_add(self, **c))
    listing(fake, http, {"@": 25})
    crawl(db)
    assert sum(c.get("pages", 0) for c in counted) == 10                # pages 1-9 and the (empty) probe


PAGES = [f"@/{p}" for p in range(2, 11)]


@pytest.mark.parametrize("size,empty,kw,asked,split,req", [
    # a short listing under a cap of 6: its probed page 2 is its own end, no split
    (5, 0, dict(result_cap=6), ["@/1", "@/2"], [], (2, 5, 1, "last page")),
    # an empty probe means under the cap: the listing ends on a short page 9...
    (25, 0, {}, ["@/1", "@/10"] + PAGES[:-1], [], (10, 25, 1, "last page")),
    # ...or 9 full pages: page 10 is the real end, confirmed by fetching it again
    (27, 0, {}, ["@/1", "@/10"] + PAGES, [], (11, 27, 1, "empty page")),
    # a flaky empty probe contradicted by full pages before it: fetched again at its turn, not taken as the end
    (None, 1, {}, ["@/1", "@/10"] + PAGES, [], (11, 30, 0, "page limit")),
    # a board with empty retries (LinkedIn's flaky empty body, twice): the third try lists cards, so capped
    (None, 2, dict(empty_retries=2), ["@/1"] + ["@/10"] * 3 + PAGES[:-1], [6],
     (10, 30, 0, "page limit; capped: matches 30+, the board shows 30")),
    # --limit-pages below the last page: no probe
    (None, 0, dict(limit_pages=3), ["@/1", "@/2", "@/3"], [], (3, 9, 0, PAGE_LIMIT_ASKED)),
])
def test_end_probe(fake, http, db, size, empty, kw, asked, split, req):
    split_seen, limit = [], kw.pop("limit_pages", None)
    fake.caps, fake.split = replace(PROBED, **kw), lambda raw, r, seen=(): split_seen.append(len(seen)) or []
    got = listing(fake, http, {"@": size}, empty={"@/10": empty})
    r = requests_of(db, crawl(db, limit_pages=limit))[""]
    assert got == asked and split_seen == split and (r["pages"], r["found"], r["complete"], r["stop_reason"]) == req


def test_unsplittable_capped_request_falls_back_to_the_newest_window(fake, http, db):
    fake.caps, fake.newest = PROBED, newest_windows
    fake.split = lambda raw, r, seen=(): []                             # e.g. LinkedIn: country-level cards dominate
    asked = listing(fake, http, {"@": None, "@7": None, "@1": 8})        # 7 days still capped, 24 hours not
    reqs = requests_of(db, crawl(db), by="days")
    assert asked == ["@/1", "@/10", "@7/1", "@7/10", "@1/1", "@1/10", "@1/2", "@1/3"]
    assert reqs[""]["stop_reason"] == "narrowed to the newest 7 days (matches 30+, the board shows 30)"
    assert reqs[7]["stop_reason"] == "newest 7 days (cap 30): narrowed to the newest 24 hours (matches 30+, the board shows 30)"
    assert reqs[1]["stop_reason"] == "newest 24 hours (cap 30): last page" and reqs[1]["found"] == 8
    assert not any(r["complete"] for r in reqs.values())                # a window never completes: nothing turns gone


def test_window_that_stays_capped_is_partial_and_marks_nothing_gone(fake, http, db):
    fake.caps, fake.newest = PROBED, newest_windows
    fake.split = lambda raw, r, seen=(): []
    listing(fake, http, {"@": None, "@7": None, "@1": None})
    last = requests_of(db, crawl(db), by="days")[1]
    assert (last["pages"], last["complete"]) == (10, 0)
    assert last["stop_reason"] == "newest 24 hours (cap 30): page limit; capped: matches 30+, the board shows 30"
    listing(fake, http, {"@": None, "@7": None, "@1": 2})                # next run: the 24-hour window moved on
    assert db.mark_gone(crawl(db)) == 0                                  # offers outside the window are not gone


def test_split_parts_stop_incrementally_once_crawled_to_their_end(fake, http, db):
    """A capped request is split again every run, so it never completes itself; its parts are listings of their
    own and get incremental stops once an earlier run fetched them to their end."""
    fake.caps = replace(PROBED, sort_newest=True, result_cap=10)
    fake.total = lambda raw, r: 5 if r.params.get("cat") else 100
    fake.split = lambda raw, r, seen=(): [replace(r, params={**r.params, "cat": c}) for c in ("a", "b")]
    listing(fake, http, {"@": None, "a@": 9, "b@": 2})
    assert requests_of(db, crawl(db))["a"]["complete"]
    a = requests_of(db, crawl(db))["a"]
    assert (a["pages"], a["stop_reason"]) == (1, "incremental: page already known")


def test_resume_finishes_the_parts_of_a_split_request(fake, http, db):
    """A split parent is done only after its parts: an interrupted run resumes the parts not fetched yet."""
    fake.caps = replace(PROBED, result_cap=5)
    fake.total = lambda raw, r: 2 if r.params.get("cat") else 9
    fake.split = lambda raw, r, seen=(): [replace(r, params={**r.params, "cat": c}) for c in ("a", "b")]
    fake.page_url = lambda r, n: f"fake://{r.params.get('cat', '')}/{n}"
    asked, stop = [], ["b"]

    def answer(url):
        asked.append(url)
        cat = url[len("fake://"):].split("/")[0]
        return KeyboardInterrupt() if cat in stop else page(cards(*(f"{cat}{i}" for i in range(2 if cat else 3))))
    http(answer)
    rid = db.start_run({}, [])
    with pytest.raises(KeyboardInterrupt):                               # the run is interrupted in part b
        crawl(db, run=rid)
    reqs = requests_of(db, rid)
    assert set(reqs) == {"", "a", "b"} and db.done_request_keys(rid) == {reqs["a"]["req_key"]}
    stop[:], asked[:] = [], []
    crawl(db, run=rid, skip_keys=db.done_request_keys(rid))             # --resume
    assert asked == ["fake:///1", "fake://b/1"]                         # page 1 again, part a skipped, part b fetched
    assert len(db.q("SELECT 1 FROM requests WHERE run_id=? AND status='done'", rid)) == 3


# retries

def flaky(http, plan):
    """Pages 1-2 list 3 offers, page 3 is empty; `plan[page]`: answers given first (bodies or exceptions).
    Returns the pages asked."""
    asked = []

    def answer(url):
        n = int(url.rsplit("/", 1)[1])
        asked.append(n)
        if plan.get(n):
            return plan[n].pop(0)
        return page([] if n >= 3 else cards(*(f"k{n}{i}" for i in range(3))))
    http(answer)
    return asked


@pytest.mark.parametrize("plan,asked,complete,error", [
    *[({2: [e, e]}, [1, 2, 2, 2, 3], 1, "") for e in (ConnectionResetError("reset by peer"), TimeoutError("timed out"),
                                                       FetchError(503), FetchError(429), FetchError(0))],
    ({2: [ConnectionRefusedError("refused")] * 5}, [1, 2, 2, 2], 0, "ConnectionRefusedError"),   # persists: an error
    ({2: [FetchError(404)]}, [1, 2], 1, ""),                                                     # permanent: no retry
    ({2: [FetchError(403)]}, [1, 2], 0, "HTTP 403"),
    ({2: ["<html>bot wall</html>"]}, [1, 2, 2, 3], 1, ""),        # a page that does not parse after good pages: transient
    ({1: ["<html>changed</html>"]}, [1], 0, "JSONDecodeError"),   # a page that never parses is a format change
])
def test_failed_page_retries(fake, http, db, plan, asked, complete, error):
    got = flaky(http, plan)
    req = requests_of(db, crawl(db))[""]
    assert got == asked and req["complete"] == complete and req["error"].startswith(error) and bool(req["error"]) == bool(error)


def test_parse_error_on_page_one_is_retried_when_the_board_parsed_before(fake, http, db):
    asked = []

    def answer(url):
        kw, n = url[len("fake://"):].rsplit("/", 1)
        asked.append((kw, n))
        if kw == "x" and asked.count(("x", "1")) == 1:
            return "<html>bot wall</html>"
        return page(cards(f"{kw}{n}0", f"{kw}{n}1"))
    http(answer)
    req = requests_of(db, crawl(db, ALL_REMOTE, Search(id="kw", label="kw", where=Where(remote=True), keywords=("x",))),
                      by=None)["x"]
    assert req["error"] == "" and req["found"] == 2 and asked.count(("x", "1")) == 2


@pytest.mark.parametrize("retries,asked", [(2, [1, 2, 2, 3, 3, 3]), (0, [1, 2])])
def test_empty_page_is_fetched_again_on_a_flaky_board(fake, http, db, capsys, retries, asked):
    fake.caps = replace(fake.caps, empty_retries=retries)
    got = flaky(http, {2: ["[]"]})                                       # one flaky empty body mid-listing
    req = requests_of(db, crawl(db))[""]
    assert got == asked                                                  # with retries the real end is tried 3 times
    if retries:
        assert (req["pages"], req["found"], req["complete"], req["stop_reason"]) == (3, 6, 1, "empty page")
        assert "empty page; fetching it again" in capsys.readouterr().err


def test_crawl_tries_a_failing_page_at_most_three_times(fake, db, monkeypatch):
    """The crawler's retries are the only ones: the transport gets none, so 1 + `retries` attempts per page."""
    monkeypatch.setattr(crawler, "RETRY_PAUSES", (1, 2))
    monkeypatch.setattr(Http, "get", REAL_GET)
    got, sleeps = [], []
    monkeypatch.setattr(fetch, "_http_get", lambda url, *a: got.append(url) or (503, ""))

    async def no_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(fetch.asyncio, "sleep", no_sleep)
    req = requests_of(db, crawl(db))[""]
    assert len(got) == 3 and req["error"].startswith("HTTP 503")
    assert [s for s in sleeps if s] == [1, 2]                           # only the crawler's pauses
    assert crawler.retry_pauses(1) == (1,) and crawler.retry_pauses(4) == (1, 2, 2, 2)   # the last pause repeats


@pytest.mark.parametrize("status,calls,sleeps,held", [(503, 3, [3, 6], []), (429, 3, [], [15, 30, 45]), (404, 1, [], [])])
def test_http_short_retries_for_details(monkeypatch, status, calls, sleeps, held):
    """`details` keeps the transport's own short retries (no pause after the last); a 429 holds the host in the
    limiter instead of sleeping in place; 404 raises at once."""
    got, slept, paused = [], [], []
    monkeypatch.setattr(fetch, "_http_get", lambda url, *a: got.append(url) or (status, ""))

    async def no_sleep(s):
        slept.append(s)
    monkeypatch.setattr(fetch.asyncio, "sleep", no_sleep)
    lim = Limiter()
    monkeypatch.setattr(Limiter, "wait", lambda self, url: no_sleep(None))
    monkeypatch.setattr(lim, "pause", lambda url, s: paused.append(s))
    with pytest.raises(FetchError) as e:
        asyncio.run(Http(lim, retries=2).get("https://host/x"))
    assert e.value.status == status and len(got) == calls
    assert [s for s in slept if s is not None] == sleeps and paused == held


def test_limiter_pause_holds_the_host(monkeypatch):
    slept = []
    monkeypatch.setattr(fetch.time, "monotonic", lambda: 100.0)

    async def sleep(s):
        slept.append(round(s, 3))
    monkeypatch.setattr(fetch.asyncio, "sleep", sleep)
    lim = Limiter(default=0)
    lim.pause("https://www.linkedin.com/a", 15)
    asyncio.run(REAL_WAIT(lim, "https://www.linkedin.com/b"))
    asyncio.run(REAL_WAIT(lim, "https://other.example/b"))
    assert slept == [15.0]                                              # the paused host only
