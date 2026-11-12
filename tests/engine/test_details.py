"""test_details.py: posting fetches with fake transports (no browser)."""
import asyncio

import pytest

from neetscape import details
from neetscape.boards.fetch import FetchError, Limiter
from neetscape.model import Offer
from neetscape.store import Store


class FakeFetch:
    pages: dict = {}

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        page = self.pages[url]
        if isinstance(page, BaseException):
            raise page
        return page


class FakeRender(FakeFetch):
    opened = closed = 0

    async def __aenter__(self):
        FakeRender.opened += 1
        return self

    async def __aexit__(self, *exc):
        FakeRender.closed += 1
        return False

    async def element_text(self, url, selector):
        return f"rendered {url} {selector}"


@pytest.fixture
def db(tmp_path, monkeypatch):
    from neetscape.boards import REGISTRY
    monkeypatch.setattr(REGISTRY["pracuj"], "posting_selector", "main")  # a board with a rendered fallback
    monkeypatch.setattr(details, "BrowserFetch", FakeFetch)
    monkeypatch.setattr(details, "BrowserRender", FakeRender)
    FakeRender.opened = FakeRender.closed = 0
    store = Store(tmp_path / "j.db")
    rid = store.start_run({}, [])
    req = store.start_request(rid, "x", "s", None, {}, ())
    store.ingest([Offer(board="pracuj", key=k, url=f"https://site/{k}", title=k) for k in ("a", "b", "c")], rid, req, 1)
    return store


def fetch(store):
    return asyncio.run(details.fetch_details(store, [1, 2, 3], 0, Limiter()))


def test_one_failing_offer_does_not_skip_the_rest_of_its_site(db):
    FakeFetch.pages = {"https://site/a": TimeoutError("slow"), "https://site/b": FetchError(404), "https://site/c": "<html></html>"}
    fetch(db)
    got = {r["offer_id"]: (r["http_status"], r["text"]) for r in db.q("SELECT * FROM details")}
    assert got[2] == (404, "") and got[3] == (200, "rendered https://site/c main") and got[1][0] == 0
    assert db.offer(2)["gone_at"] and not db.offer(3)["gone_at"]
    assert FakeRender.opened == FakeRender.closed == 1


def test_render_tab_closed_when_saving_fails(db, monkeypatch):
    FakeFetch.pages = {u: "<html></html>" for u in ("https://site/a", "https://site/b", "https://site/c")}

    def broken(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(db, "save_detail", broken)
    fetch(db)
    assert FakeRender.opened == FakeRender.closed == 1


def test_published_date_from_posting_must_be_a_date(db):
    FakeFetch.pages = {u: '<script type="application/ld+json">{"@type": "JobPosting", "description": "text", '
                          '"datePosted": "05.01.2025"}</script>' for u in ("https://site/a", "https://site/b", "https://site/c")}
    fetch(db)
    assert db.offer(1)["published"] is None


def test_blocked_posting_is_not_rendered_as_text():
    import asyncio
    from neetscape import details
    from neetscape.boards.fetch import FetchError

    class Blocked:
        async def get(self, url):
            raise FetchError(403)

    async def render():
        raise AssertionError("a blocked page must not be rendered")

    assert asyncio.run(details._posting(Blocked(), {"url": "https://site/x", "board": "pracuj"}, render)) == (403, "", {})


def test_board_min_intervals_yield_to_the_profile(monkeypatch):
    from neetscape.boards import REGISTRY
    from neetscape.boards.base import min_intervals
    assert min_intervals()["theprotocol.it"] == REGISTRY["theprotocol"].min_interval["theprotocol.it"]
    assert min_intervals({"theprotocol.it": 9})["theprotocol.it"] == 9


def test_no_selector_no_rendering(db, monkeypatch):
    from neetscape.boards import REGISTRY
    monkeypatch.setattr(REGISTRY["pracuj"], "posting_selector", "")
    FakeFetch.pages = {u: "<html><nav>Menu</nav></html>" for u in ("https://site/a", "https://site/b", "https://site/c")}
    fetch(db)
    assert {r["text"] for r in db.q("SELECT * FROM details")} == {""} and FakeRender.opened == 0


def test_posting_settles_unknown_fields_from_strong_signals_only():
    from neetscape import infer
    langs = ("pl", "en")
    row = {"mode": "unknown", "worktime": "unknown", "contracts": ""}
    vague = "Wsparcie użytkowników zdalnie i na miejscu. Umowa o pracę, pełny etat."
    got = details._from_posting(row, vague, {}, infer.hints(vague, langs), langs)
    assert got == {"worktime": "full_time", "contracts": "employment"}          # "zdalnie" alone is not a work mode
    full = "Praca w 100% zdalna."
    assert details._from_posting(row, full, {}, infer.hints(full, langs), langs)["mode"] == "remote"
    assert details._from_posting(row, "x", {"remote": True}, {}, langs)["mode"] == "remote"   # JSON-LD TELECOMMUTE
    known = {"mode": "onsite", "worktime": "part_time", "contracts": "b2b"}
    assert details._from_posting(known, full + " Pełny etat, UoP", {}, infer.hints(full, langs), langs) == {}  # cards win


def test_top_picks_skip_jobs_whose_posting_is_stored(db):
    import argparse
    from neetscape import cli, profile
    p = profile.validate({"version": 2, "boards": ["pracuj"], "searches": [{"id": "all", "what": "all"}]})
    from neetscape import evaluate as ev
    ev.evaluate(db, p, 1)
    db.save_detail(1, 200, "posting of a", {}, {})
    ns = argparse.Namespace(pick=None, pick_file=None, top=10, marked=False)
    assert cli._ids(ns, db, p, 1) == [2, 3]


def test_placeholder_company_from_jsonld_is_ignored(db):
    details._save(db, db.offer(1), 200, "text", {"company": "confidential"})
    details._save(db, db.offer(2), 200, "text", {"company": "Acme"})
    assert db.offer(1)["company"] == "" and db.offer(2)["company"] == "Acme"


def test_linkedin_parse_error_does_not_skip_the_other_postings(tmp_path, monkeypatch):
    from neetscape.boards.fetch import Http
    from neetscape.boards.linkedin import LinkedIn
    store = Store(tmp_path / "j.db")
    rid = store.start_run({}, [])
    req = store.start_request(rid, "linkedin", "s", None, {}, ())
    store.ingest([Offer(board="linkedin", key=k, url=f"https://www.linkedin.com/jobs/view/job-{k}", title=k) for k in ("1", "2")],
                 rid, req, 1)

    async def get(self, url):
        return url

    def fields(page):
        if page.endswith("1"):
            raise ValueError("markup changed")
        return {"description": "posting 2", "source": "api"}
    monkeypatch.setattr(Http, "get", get)
    monkeypatch.setattr(LinkedIn, "posting_fields", staticmethod(fields))
    monkeypatch.setattr(Limiter, "wait", lambda self, url: asyncio.sleep(0))
    asyncio.run(details.fetch_details(store, [1, 2], 0, Limiter()))
    got = {r["offer_id"]: (r["http_status"], r["text"]) for r in store.q("SELECT * FROM details")}
    assert got == {1: (0, "ERROR ValueError: markup changed"), 2: (200, "posting 2")}


def test_marked_offers_whose_posting_failed_are_fetched_again(db):
    import argparse
    from neetscape import cli
    db.save_detail(1, 0, "ERROR TimeoutError: slow", {}, {})
    db.save_detail(2, 200, "posting of b", {}, {})
    db.save_detail(3, 403, "", {}, {})
    for key in ("a", "b", "c"):
        db.mark(f"https://site/{key}", "shortlisted")
    ns = argparse.Namespace(pick=None, pick_file=None, top=None, marked=True)
    assert cli._ids(ns, db, None, 1) == [1, 3]
    db.save_detail(3, 404, "", {}, {})
    assert cli._ids(ns, db, None, 1) == [1]                     # gone: nothing to fetch


def test_first_publication_date_from_the_posting_replaces_a_refresh_date(db, monkeypatch):
    from neetscape.boards import REGISTRY
    db.db.execute("UPDATE offers SET published='2026-11-12' WHERE id IN (1, 2)")
    db.db.commit()
    monkeypatch.setattr(REGISTRY["pracuj"], "posting_date_is_first", True)
    details._save(db, db.offer(1), 200, "text", {"published": "2026-10-15"})
    details._save(db, db.offer(2), 200, "text", {"published": "2026-11-20"})        # later than the card: ignored
    assert db.offer(1)["published"] == "2026-10-15" and db.offer(2)["published"] == "2026-11-12"
    monkeypatch.setattr(REGISTRY["pracuj"], "posting_date_is_first", False)
    db.db.execute("UPDATE offers SET published='2026-11-12' WHERE id=1")
    details._save(db, db.offer(1), 200, "text", {"published": "2026-10-15"})
    assert db.offer(1)["published"] == "2026-11-12"                                   # other boards keep the card's date
