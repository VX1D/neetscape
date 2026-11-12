"""test_crawler.py: the result cap without a total (end probe, newest windows), and retries of transient failures
(fake board, no network)."""
import json
from dataclasses import replace

import pytest

from neetscape import crawler
from neetscape.boards.base import Caps
from neetscape.boards import fetch as fetch_mod
from neetscape.boards.fetch import FetchError, Http, Limiter
from neetscape.store import Store

from conftest import ALL_REMOTE, run_crawl

REAL_GET, REAL_WAIT = Http.get, Limiter.wait   # before the `fake` fixture replaces them


@pytest.fixture(autouse=True)
def no_pauses(monkeypatch):
    monkeypatch.setattr(crawler, "RETRY_PAUSES", (0, 0))
    monkeypatch.setattr(crawler, "EMPTY_PAUSE", 0)


def requests_by(db, rid, field="cat"):
    return {json.loads(r["params_json"]).get(field, ""): r for r in db.q("SELECT * FROM requests WHERE run_id=?", rid)}


def serve(monkeypatch, fake, sizes: dict, calls: list | None = None):
    """Pages by category: `sizes[cat]` offers in all, 3 per page (`None`: endless)."""
    fake.page_url = lambda r, page: f"fake://{r.params.get('cat', '')}/{page}"

    async def get(self, url):
        cat, page = url[len("fake://"):].rsplit("/", 1)
        if calls is not None:
            calls.append(url)
        n = sizes[cat] if sizes[cat] is not None else 10 ** 6
        start = (int(page) - 1) * 3
        return json.dumps([[f"{cat}{i}", f"Job {cat}{i}", {}] for i in range(start, min(n, start + 3))])

    monkeypatch.setattr(Http, "get", get)


def test_small_cap_is_probed_on_the_page_holding_its_last_results(fake, monkeypatch, tmp_path):
    fake.caps = Caps(keywords=True, remote="filter", page_size=3, max_pages=10, result_cap=6, transport="http")
    got = {}

    def split(raw, r, seen=()):
        got[r.params.get("cat", "")] = [o.key for o in seen]
        return [replace(r, params={**r.params, "cat": c}) for c in ("a", "b")] if not r.params.get("cat") else []

    fake.split = split
    serve(monkeypatch, fake, {"": None, "a": 4, "b": 2})
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    reqs = requests_by(db, rid)
    assert reqs[""]["pages"] == 2 and not reqs[""]["complete"]          # cap 6 / 3 per page: page 2 is probed
    assert reqs[""]["stop_reason"] == "split into 2 (matches 6+, the board shows 6)"
    assert got == {"": ["0", "1", "2", "3", "4", "5"]}                   # split() gets page 1 and the probed page
    # "a" (4 offers): its probed page 2 is short, the listing's own end within the cap; "b": page 1 is short
    assert reqs["a"]["complete"] and reqs["b"]["complete"] and reqs["a"]["found"] == 4
    assert (reqs["a"]["pages"], reqs["a"]["stop_reason"]) == (2, "last page")


def test_cap_without_a_total_is_reached_on_the_boards_last_page(fake, monkeypatch, tmp_path):
    fake.caps = Caps(keywords=True, remote="filter", page_size=3, max_pages=3, result_cap=1000, transport="http")
    fake.split = lambda raw, r, seen=(): []                              # cannot be narrowed: fetched up to the cap
    serve(monkeypatch, fake, {"": None})
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = requests_by(db, rid)[""]
    assert (req["pages"], req["complete"]) == (3, 0)
    assert req["stop_reason"] == "page limit; capped: matches 1000+, the board shows 1000"

    rid = db.start_run({}, [])                                           # --limit-pages below the board's last page
    run_crawl(db, rid, fake, [ALL_REMOTE], limit_pages=2, incremental=False)
    assert requests_by(db, rid)[""]["stop_reason"] == "page limit"


def test_a_short_listing_under_the_cap_is_not_split(fake, monkeypatch, tmp_path):
    fake.caps = Caps(keywords=True, remote="filter", page_size=3, max_pages=10, result_cap=6, transport="http")
    fake.split = lambda raw, r, seen=(): pytest.fail("split() asked under the cap")
    serve(monkeypatch, fake, {"": 5})
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = requests_by(db, rid)[""]
    assert (req["pages"], req["complete"], req["stop_reason"]) == (2, 1, "last page")


def flaky(monkeypatch, fake, plan: dict, calls: list):
    """`plan[page]`: list of outcomes per attempt (an exception to raise, or a raw body); then 3 offers, page 3 empty."""
    async def get(self, url):
        page = int(url.rsplit("/", 1)[1])
        calls.append(page)
        todo = plan.get(page)
        if todo:
            out = todo.pop(0)
            if isinstance(out, Exception):
                raise out
            return out
        return json.dumps([] if page >= 3 else [[f"k{page}{i}", f"Job {page}{i}", {}] for i in range(3)])

    monkeypatch.setattr(Http, "get", get)


@pytest.mark.parametrize("failure", [ConnectionResetError("reset by peer"), TimeoutError("timed out"),
                                     FetchError(503), FetchError(429), FetchError(0)])
def test_transient_fetch_failure_is_retried(fake, monkeypatch, tmp_path, capsys, failure):
    calls = []
    flaky(monkeypatch, fake, {2: [failure, failure]}, calls)
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests WHERE run_id=?", rid)[0]
    assert (req["pages"], req["found"], req["complete"], req["error"]) == (3, 6, 1, "")
    assert calls == [1, 2, 2, 2, 3]
    err = capsys.readouterr().err
    assert "p2:" in err and "retry 1/2" in err and "retry 2/2" in err


def test_failure_that_persists_ends_the_request_with_an_error(fake, monkeypatch, tmp_path):
    calls = []
    flaky(monkeypatch, fake, {2: [ConnectionRefusedError("refused")] * 5}, calls)
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests WHERE run_id=?", rid)[0]
    assert calls == [1, 2, 2, 2] and req["pages"] == 1 and "ConnectionRefusedError" in req["error"]


@pytest.mark.parametrize("status", [404, 403])
def test_permanent_http_status_is_not_retried(fake, monkeypatch, tmp_path, status):
    calls = []
    flaky(monkeypatch, fake, {2: [FetchError(status)]}, calls)
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests WHERE run_id=?", rid)[0]
    assert calls == [1, 2]
    assert (req["complete"], req["error"]) == ((1, "") if status == 404 else (0, "HTTP 403 "))


def test_parse_error_is_retried_only_after_a_page_parsed(fake, monkeypatch, tmp_path):
    """A bot wall after good pages is transient; a page that never parses is a format change: no retry."""
    calls = []
    flaky(monkeypatch, fake, {2: ["<html>bot wall</html>"]}, calls)    # json.loads raises ValueError
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests WHERE run_id=?", rid)[0]
    assert calls == [1, 2, 2, 3] and req["complete"] and req["error"] == ""

    calls.clear()
    flaky(monkeypatch, fake, {1: ["<html>changed</html>"]}, calls)
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE], incremental=False)
    req = db.q("SELECT * FROM requests WHERE run_id=?", rid)[0]
    assert calls == [1] and req["error"].startswith("JSONDecodeError")


def test_parse_error_on_page_one_is_retried_when_the_board_parsed_before(fake, monkeypatch, tmp_path):
    from neetscape.model import Search, Where
    calls = []
    flaky(monkeypatch, fake, {}, calls)
    fake.page_url = lambda r, page: f"fake://{r.keyword or '*'}/{page}"
    second = Search(id="kw", label="kw", where=Where(remote=True), keywords=("x",))

    async def get(self, url):
        kw, page = url[len("fake://"):].rsplit("/", 1)
        calls.append((kw, int(page)))
        if kw == "x" and calls.count(("x", 1)) == 1:
            return "<html>bot wall</html>"
        return json.dumps([[f"{kw}{page}{i}", "Job", {}] for i in range(2)])

    monkeypatch.setattr(Http, "get", get)
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE, second])
    reqs = {r["keyword"]: r for r in db.q("SELECT * FROM requests WHERE run_id=?", rid)}
    assert reqs["x"]["error"] == "" and reqs["x"]["found"] == 2 and calls.count(("x", 1)) == 2


def test_empty_page_is_fetched_again_on_a_flaky_board(fake, monkeypatch, tmp_path, capsys):
    fake.caps = replace(fake.caps, empty_retries=2)
    calls = []
    flaky(monkeypatch, fake, {2: ["[]"]}, calls)                        # one flaky empty body mid-listing
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests WHERE run_id=?", rid)[0]
    assert calls == [1, 2, 2, 3, 3, 3]                                  # the real end (page 3) is tried 3 times
    assert (req["pages"], req["found"], req["complete"], req["stop_reason"]) == (3, 6, 1, "empty page")
    assert "empty page; fetching it again" in capsys.readouterr().err

    fake.caps = replace(fake.caps, empty_retries=0)                     # other boards: an empty page is the end
    calls.clear()
    flaky(monkeypatch, fake, {2: ["[]"]}, calls)
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE], incremental=False)
    assert calls == [1, 2]


def windowed(monkeypatch, fake, sizes: dict, calls: list, empty: dict | None = None):
    """Like `serve`, keyed by category and newest window (`cat@days`); `empty[url]`: that many empty answers first."""
    fake.page_url = lambda r, page: f"fake://{r.params.get('cat', '')}@{r.params.get('days', '')}/{page}"
    empty = dict(empty or {})

    async def get(self, url):
        key, page = url[len("fake://"):].rsplit("/", 1)
        calls.append(f"{key}/{page}")
        if empty.get(f"{key}/{page}"):
            empty[f"{key}/{page}"] -= 1
            return "[]"
        n = sizes[key] if sizes[key] is not None else 10 ** 6
        start = (int(page) - 1) * 3
        return json.dumps([[f"{key}{i}", f"Job {key}{i}", {}] for i in range(start, min(n, start + 3))])

    monkeypatch.setattr(Http, "get", get)


PROBED = Caps(keywords=True, remote="filter", page_size=3, max_pages=10, result_cap=30, transport="http")


def test_end_probe_splits_right_after_page_one_when_the_cap_is_reached(fake, monkeypatch, tmp_path):
    fake.caps = PROBED
    got, calls = {}, []

    def split(raw, r, seen=()):
        got[r.params.get("cat", "")] = [o.key for o in seen]
        return [replace(r, params={**r.params, "cat": c}) for c in ("a", "b")] if not r.params.get("cat") else []

    fake.split = split
    windowed(monkeypatch, fake, {"@": None, "a@": 7, "b@": 2}, calls)
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    reqs = requests_by(db, rid)
    assert calls[:2] == ["@/1", "@/10"]                                 # page 1, then the probe of the last page
    assert (reqs[""]["pages"], reqs[""]["found"], reqs[""]["complete"]) == (2, 6, 0)   # the probe counts as a page
    assert reqs[""]["stop_reason"] == "split into 2 (matches 30+, the board shows 30)"
    assert got == {"": ["@0", "@1", "@2", "@27", "@28", "@29"]}         # the cards of page 1 and of the probed page
    # the parts: "a" probes page 10 (empty: under the cap), then pages to its end; "b" ends on a short page 1
    assert calls[2:] == ["a@/1", "a@/10", "a@/2", "a@/3", "b@/1"]
    assert (reqs["a"]["pages"], reqs["a"]["found"], reqs["a"]["complete"], reqs["a"]["stop_reason"]) == (4, 7, 1, "last page")
    assert (reqs["b"]["pages"], reqs["b"]["complete"]) == (1, 1)


def test_end_probe_is_counted_in_the_progress(fake, monkeypatch, tmp_path):
    from neetscape import log as logmod
    fake.caps = PROBED
    fake.split = lambda raw, r, seen=(): []
    counted = []
    real_add = logmod.Progress.add
    monkeypatch.setattr(logmod.Progress, "add", lambda self, **c: counted.append(c) or real_add(self, **c))
    windowed(monkeypatch, fake, {"@": 27}, [])
    db = Store(tmp_path / "j.db")
    run_crawl(db, db.start_run({}, []), fake, [ALL_REMOTE])
    assert sum(c.get("pages", 0) for c in counted) == 10                # pages 1-9 and the (empty) probe


def test_end_probe_empty_means_under_the_cap(fake, monkeypatch, tmp_path):
    fake.caps = PROBED
    fake.split = lambda raw, r, seen=(): pytest.fail("split() asked under the cap")
    calls = []
    windowed(monkeypatch, fake, {"@": 27}, calls)                       # 9 full pages: page 10 is the real end
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = requests_by(db, rid)[""]
    assert calls == ["@/1", "@/10"] + [f"@/{p}" for p in range(2, 10)]  # page 10 is not fetched again
    assert (req["pages"], req["found"], req["complete"], req["stop_reason"]) == (10, 27, 1, "empty page")


def test_end_probe_retries_an_empty_answer_before_trusting_it(fake, monkeypatch, tmp_path):
    fake.caps = replace(PROBED, empty_retries=2)
    split_seen = []
    fake.split = lambda raw, r, seen=(): split_seen.append(len(seen)) or []
    calls = []
    windowed(monkeypatch, fake, {"@": None}, calls, empty={"@/10": 2})   # LinkedIn's flaky empty body, twice
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = requests_by(db, rid)[""]
    assert calls[:4] == ["@/1", "@/10", "@/10", "@/10"] and split_seen == [6]   # the third try lists cards: capped
    assert calls[4:] == [f"@/{p}" for p in range(2, 10)]                  # then paged; page 10 is not refetched
    assert (req["pages"], req["complete"]) == (10, 0)
    assert req["stop_reason"] == "page limit; capped: matches 30+, the board shows 30"


def test_no_end_probe_below_the_last_page(fake, monkeypatch, tmp_path):
    fake.caps = PROBED
    fake.split = lambda raw, r, seen=(): pytest.fail("no probe, no split")
    calls = []
    windowed(monkeypatch, fake, {"@": None}, calls)
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE], limit_pages=3)
    assert calls == ["@/1", "@/2", "@/3"] and requests_by(db, rid)[""]["stop_reason"] == "page limit"


def newest_windows(r):
    nxt = {None: (7, "7 days"), 7: (1, "24 hours")}.get(r.params.get("days"))
    return (replace(r, params={**r.params, "days": nxt[0]}), nxt[1]) if nxt else None


def test_unsplittable_capped_request_falls_back_to_the_newest_window(fake, monkeypatch, tmp_path):
    fake.caps = PROBED
    fake.split = lambda raw, r, seen=(): []                            # e.g. LinkedIn: country-level cards dominate
    fake.newest = newest_windows
    calls = []
    windowed(monkeypatch, fake, {"@": None, "@7": None, "@1": 8}, calls)   # 7 days still capped, 24 hours not
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    reqs = requests_by(db, rid, "days")
    assert calls == ["@/1", "@/10", "@7/1", "@7/10", "@1/1", "@1/10", "@1/2", "@1/3"]
    assert reqs[""]["stop_reason"] == "narrowed to the newest 7 days (matches 30+, the board shows 30)"
    assert reqs[7]["stop_reason"] == "newest 7 days (cap 30): narrowed to the newest 24 hours (matches 30+, the board shows 30)"
    assert reqs[1]["stop_reason"] == "newest 24 hours (cap 30): last page" and reqs[1]["found"] == 8
    assert not any(r["complete"] for r in reqs.values())               # a window never completes: nothing turns gone


def test_window_that_stays_capped_is_partial_and_marks_nothing_gone(fake, monkeypatch, tmp_path):
    fake.caps = PROBED
    fake.split = lambda raw, r, seen=(): []
    fake.newest = newest_windows
    windowed(monkeypatch, fake, {"@": None, "@7": None, "@1": None}, [])
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    last = requests_by(db, rid, "days")[1]
    assert (last["pages"], last["complete"]) == (10, 0)
    assert last["stop_reason"] == "newest 24 hours (cap 30): page limit; capped: matches 30+, the board shows 30"

    windowed(monkeypatch, fake, {"@": None, "@7": None, "@1": 2}, [])  # next run: the 24-hour window moved on
    rid2 = db.start_run({}, [])
    run_crawl(db, rid2, fake, [ALL_REMOTE])
    assert db.mark_gone(rid2) == 0                                      # offers outside the window are not gone


def test_crawl_tries_a_failing_page_at_most_three_times(fake, monkeypatch, tmp_path):
    """The crawler's retries are the only ones: the transport gets none, so 1 + `retries` attempts per page."""
    monkeypatch.setattr(crawler, "RETRY_PAUSES", (1, 2))
    monkeypatch.setattr(Http, "get", REAL_GET)
    got, sleeps = [], []
    monkeypatch.setattr(fetch_mod, "_http_get", lambda url, *a: got.append(url) or (503, ""))

    async def no_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(fetch_mod.asyncio, "sleep", no_sleep)
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests WHERE run_id=?", rid)[0]
    assert len(got) == 3 and req["error"].startswith("HTTP 503")
    assert [s for s in sleeps if s] == [1, 2]                           # only the crawler's pauses


def test_retry_pauses_follow_the_retries_setting(monkeypatch):
    monkeypatch.setattr(crawler, "RETRY_PAUSES", (20, 60))
    assert crawler.retry_pauses(2) == (20, 60) and crawler.retry_pauses(1) == (20,) and crawler.retry_pauses(0) == ()
    assert crawler.retry_pauses(4) == (20, 60, 60, 60)


@pytest.mark.parametrize("status,calls,sleeps,held", [(503, 3, [3, 6], []), (429, 3, [], [15, 30, 45]), (404, 1, [], [])])
def test_http_short_retries_for_details(monkeypatch, status, calls, sleeps, held):
    """`details` keeps the transport's own short retries (no pause after the last); a 429 holds the host in the
    limiter instead of sleeping in place; 404 raises at once."""
    import asyncio
    got, slept, paused = [], [], []
    monkeypatch.setattr(fetch_mod, "_http_get", lambda url, *a: got.append(url) or (status, ""))

    async def no_sleep(s):
        slept.append(s)
    monkeypatch.setattr(fetch_mod.asyncio, "sleep", no_sleep)
    lim = Limiter()
    monkeypatch.setattr(Limiter, "wait", lambda self, url: no_sleep(None))
    monkeypatch.setattr(lim, "pause", lambda url, s: paused.append(s))
    with pytest.raises(FetchError) as e:
        asyncio.run(Http(lim, retries=2).get("https://host/x"))
    assert e.value.status == status and len(got) == calls
    assert [s for s in slept if s is not None] == sleeps and paused == held


def test_limiter_pause_holds_the_host(monkeypatch):
    import asyncio
    slept = []
    monkeypatch.setattr(fetch_mod.time, "monotonic", lambda: 100.0)

    async def sleep(s):
        slept.append(round(s, 3))
    monkeypatch.setattr(fetch_mod.asyncio, "sleep", sleep)
    lim = Limiter(default=0)
    lim.pause("https://www.linkedin.com/a", 15)
    asyncio.run(REAL_WAIT(lim, "https://www.linkedin.com/b"))
    asyncio.run(REAL_WAIT(lim, "https://other.example/b"))
    assert slept == [15.0]                                              # the paused host only
