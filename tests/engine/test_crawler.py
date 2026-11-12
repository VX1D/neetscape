"""test_crawler.py: the result cap without a total, and retries of transient failures (fake board, no network)."""
import json
from dataclasses import replace

import pytest

from neetscape import crawler
from neetscape.boards.base import Caps
from neetscape.boards.fetch import FetchError, Http
from neetscape.store import Store

from conftest import ALL_REMOTE, run_crawl


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


def test_cap_without_a_total_splits_when_the_request_lists_the_cap(fake, monkeypatch, tmp_path):
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
    assert reqs[""]["pages"] == 2 and not reqs[""]["complete"]          # 6 offers listed: the cap, seen on page 2
    assert reqs[""]["stop_reason"] == "split into 2 (matches 6+, the board shows 6)"
    assert got == {"": ["0", "1", "2", "3", "4", "5"]}                   # split() gets every offer the request listed
    assert reqs["a"]["complete"] and reqs["b"]["complete"] and reqs["a"]["found"] == 4


def test_cap_without_a_total_is_reached_on_the_boards_last_page(fake, monkeypatch, tmp_path):
    fake.caps = Caps(keywords=True, remote="filter", page_size=3, max_pages=3, result_cap=1000, transport="http")
    fake.split = lambda raw, r, seen=(): []                              # cannot be narrowed: fetched up to the cap
    serve(monkeypatch, fake, {"": None})
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    req = requests_by(db, rid)[""]
    assert (req["pages"], req["complete"]) == (3, 0)
    assert req["stop_reason"] == "page limit; capped: matches 9+, the board shows 1000"

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
