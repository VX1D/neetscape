"""Shared test helpers: a fake board that serves pages from memory (no network)."""
import asyncio
import json

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import Board, Caps
from neetscape.boards.fetch import Http, Limiter
from neetscape.crawler import crawl
from neetscape.model import Offer, Search, Where
from neetscape.pay import DEFAULT_FX

class Fake(Board):
    name = "fake"
    caps = Caps(keywords=True, remote="filter", sort_newest=True, page_size=3, max_pages=10, transport="http")
    pages: dict = {}  # (keyword, page) -> list of (key, title, extra fields)

    def page_url(self, r, page):
        return f"fake://{r.keyword or '*'}/{page}"

    def parse(self, raw, r):
        return [Offer(board="fake", key=k, url=f"https://fake/{k}", title=t, **x) for k, t, x in json.loads(raw)]


@pytest.fixture
def fake(monkeypatch):
    board = Fake()
    board.pages = {}
    monkeypatch.setitem(REGISTRY, "fake", board)

    async def get(self, url):
        kw, page = url[len("fake://"):].rsplit("/", 1)
        return json.dumps(board.pages.get((kw, int(page)), []))

    monkeypatch.setattr(Http, "get", get)
    monkeypatch.setattr(Limiter, "wait", lambda self, url: asyncio.sleep(0))
    return board


def run_crawl(store, run_id, board, searches, **kw):
    reqs = [r for s in searches for r in board.requests(s)[0]]
    asyncio.run(crawl(reqs, {s.id: s for s in searches}, store, run_id, port=0, limiter=Limiter(), fx=DEFAULT_FX, **kw))


ALL_REMOTE = Search(id="all", label="all", where=Where(remote=True), keywords=None)

