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

    async def page_text(self, url):
        return "rendered " + url


@pytest.fixture
def db(tmp_path, monkeypatch):
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
    assert got[2] == (404, "") and got[3] == (200, "rendered https://site/c") and got[1][0] == 0
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
