"""test_crawler.py: the page loop with a fake fetcher (no network)."""
import asyncio
import datetime as dt

from neetscape import crawler, details
from neetscape.boards import REGISTRY
from neetscape.boards.base import Request
from neetscape.model import Offer, Search, Where
from neetscape.store import Store


class FakeFetcher:
    def __init__(self, pages: dict[int, list[Offer]]):
        self.pages = pages

    async def get(self, url, body=None):
        return url


def run_once(board, store: Store, r: Request, pages: dict[int, list[Offer]], monkeypatch) -> int:
    """One run of one request; page N of the listing parses to `pages[N]` (missing: empty)."""
    monkeypatch.setattr(board, "parse", lambda raw, r: [Offer(**vars(o)) for o in pages.get(_page(raw), [])])
    run_id = store.start_run({}, [])
    search = Search(id=r.search_id, label=r.search_id, where=Where(remote=True), keywords=None)
    asyncio.run(crawler._run_request(board, FakeFetcher(pages), r, search, store, run_id, fx={}, limit_pages=None,
                                     incremental=True, record=None))
    return run_id


def _page(url: str) -> int:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return int(tail.split(";")[0]) if tail.endswith(";pg") else 1


def test_gowork_first_publication_survives_a_later_run(tmp_path, monkeypatch):
    """gowork cards carry the refresh date; the posting's first publication (`details`) must outlive the next
    sighting of the card."""
    board, store = REGISTRY["gowork"], Store(tmp_path / "c.db")
    r = Request("gowork", "s", None, {"remote": True})
    card = Offer(board="gowork", key="g1", url="https://site/g1", title="g1", published=dt.date(2026, 11, 12))
    run_once(board, store, r, {1: [card]}, monkeypatch)
    details._save(store, store.q("SELECT * FROM offers WHERE key='g1'")[0], 200, "text", {"published": "2026-10-15"})
    refreshed = Offer(**{**vars(card), "published": dt.date(2026, 11, 14)})
    run_once(board, store, r, {1: [refreshed]}, monkeypatch)
    assert store.q("SELECT published FROM offers WHERE key='g1'")[0][0] == "2026-10-15"
