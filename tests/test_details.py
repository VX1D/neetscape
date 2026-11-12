"""Fetching postings (`details`) with fake transports: failures stay per offer, what a posting may change."""
import asyncio

import pytest

from conftest import cards, crawl, ingest, job, save_posting
from neetscape import details
from neetscape.boards import REGISTRY
from neetscape.boards.fetch import FetchError, Limiter
from neetscape.boards.linkedin import LinkedIn

URLS = [f"https://site/{k}" for k in "abcd"]


class FakeFetch:
    """The browser fetch: `pages[url]` is the page, or an exception to raise."""
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
def site(db, monkeypatch):
    """Four pracuj offers (ids 1-4) at URLS, read with the fake browser; pracuj renders `main` when a page has no text."""
    monkeypatch.setattr(REGISTRY["pracuj"], "posting_selector", "main")
    monkeypatch.setattr(details, "BrowserFetch", FakeFetch)
    monkeypatch.setattr(details, "BrowserRender", FakeRender)
    FakeRender.opened = FakeRender.closed = 0
    ingest(db, *(job("pracuj", u[-1], u[-1], url=u) for u in URLS))
    return db


def fetch(db, pages, ids=(1, 2, 3, 4)):
    FakeFetch.pages = pages if isinstance(pages, dict) else {u: pages for u in URLS}
    asyncio.run(details.fetch_details(db, list(ids), 0, Limiter()))
    return {r["offer_id"]: (r["http_status"], r["text"]) for r in db.q("SELECT * FROM details")}


def test_one_failing_offer_does_not_skip_the_rest_of_its_site(site):
    got = fetch(site, dict(zip(URLS, [TimeoutError("slow"), FetchError(404), "<html></html>", FetchError(403)])))
    assert got[1][0] == 0 and got[2] == (404, "") and got[3] == (200, "rendered https://site/c main")
    assert got[4] == (403, "")                                         # a blocked page is not rendered as text
    assert site.offer(2)["gone_at"] and not site.offer(3)["gone_at"]
    assert FakeRender.opened == FakeRender.closed == 1


def test_render_tab_closed_when_saving_fails(site, monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(site, "save_detail", broken)
    fetch(site, "<html></html>")
    assert FakeRender.opened == FakeRender.closed == 1


def test_no_selector_no_rendering(site, monkeypatch):
    monkeypatch.setattr(REGISTRY["pracuj"], "posting_selector", "")
    assert {text for _, text in fetch(site, "<html><nav>Menu</nav></html>").values()} == {""} and FakeRender.opened == 0


def test_posting_fields_fill_the_offer(site):
    fetch(site, '<script type="application/ld+json">{"@type": "JobPosting", "description": "Praca w 100% zdalna.", '
                '"datePosted": "05.01.2025", "hiringOrganization": {"name": "confidential"}}</script>', ids=[1])
    save_posting(site, 2, company="Acme")
    o = site.offer(1)
    assert o["published"] is None                                      # a date that is no ISO date is dropped
    assert o["company"] == "" and site.offer(2)["company"] == "Acme"    # a placeholder company is ignored
    assert o["mode"] == "remote"                                       # the posting is derived into the offer


def test_linkedin_parse_error_does_not_skip_the_other_postings(db, http, monkeypatch):
    ingest(db, *(job("linkedin", k, k, url=f"https://www.linkedin.com/jobs/view/job-{k}") for k in "12"))
    http(lambda url: url)

    def fields(page):
        if page.endswith("1"):
            raise ValueError("markup changed")
        return {"description": "posting 2", "source": "api"}
    monkeypatch.setattr(LinkedIn, "posting_fields", staticmethod(fields))
    asyncio.run(details.fetch_details(db, [1, 2], 0, Limiter()))
    got = {r["offer_id"]: (r["http_status"], r["text"]) for r in db.q("SELECT * FROM details")}
    assert got == {1: (0, "ERROR ValueError: markup changed"), 2: (200, "posting 2")}


def test_first_publication_date_from_the_posting_replaces_a_refresh_date(fake, db):
    """gowork cards carry the refresh date, its postings the first publication (`posting_date_is_first`): the
    earlier posting date wins, and outlives the next sighting of the card."""
    fake.posting_date_is_first = True
    fake.pages = {("*", 1): cards("a", "b", published="2026-11-12")}
    crawl(db)
    save_posting(db, "https://fake/a", published="2026-10-15")
    save_posting(db, "https://fake/b", published="2026-11-20")          # later than the card: ignored
    fake.pages = {("*", 1): cards("a", "b", published="2026-11-14")}
    crawl(db)
    assert [db.offer(f"https://fake/{k}")["published"] for k in "ab"] == ["2026-10-15", "2026-11-14"]
    fake.posting_date_is_first = False                                  # other boards keep the card's date
    save_posting(db, "https://fake/b", published="2026-10-15")
    assert db.offer("https://fake/b")["published"] == "2026-11-14"
