"""Shared helpers: a fake board served from memory, a store, offers, crawls and fake HTTP (no network)."""
import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

from neetscape import crawler, details, profile
from neetscape.boards import REGISTRY
from neetscape.boards.base import Board, Caps
from neetscape.boards.fetch import Http, Limiter
from neetscape.model import Offer, Search, Where
from neetscape.pay import DEFAULT_FX
from neetscape.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
ALL_REMOTE = Search(id="all", label="all", where=Where(remote=True), keywords=None)


class Fake(Board):
    """Pages from `pages[(keyword or "*", page)]`: lists of [key, title, extra Offer fields]."""
    name = "fake"
    caps = Caps(keywords=True, remote="filter", sort_newest=True, page_size=3, max_pages=10, transport="http")

    def page_url(self, r, page):
        return f"fake://{r.keyword or '*'}/{page}"

    def parse(self, raw, r):
        return [Offer(board="fake", key=k, url=f"https://fake/{k}", title=t,
                      **{**x, **({"published": dt.date.fromisoformat(x["published"])} if "published" in x else {})})
                for k, t, x in json.loads(raw)]


def cards(*keys, **fields):
    """Fake-board cards titled "Job <key>"."""
    return [[k, f"Job {k}", fields] for k in keys]


def page(cards_):
    return json.dumps(cards_)


@pytest.fixture
def http(monkeypatch):
    """`http(answer)` replaces `Http.get` with `answer(url)`: a body, or an exception to raise. Returns the list of
    URLs asked, in order. Host pauses (`Limiter.wait`) and the crawl's retry pauses are skipped."""
    monkeypatch.setattr(Limiter, "wait", lambda self, url: asyncio.sleep(0))
    monkeypatch.setattr(crawler, "RETRY_PAUSES", (0, 0))
    monkeypatch.setattr(crawler, "EMPTY_PAUSE", 0)

    def install(answer):
        calls = []

        async def get(self, url, *a, **kw):
            calls.append(url)
            out = answer(url)
            if isinstance(out, BaseException):
                raise out
            return out
        monkeypatch.setattr(Http, "get", get)
        return calls
    return install


@pytest.fixture
def fake(monkeypatch, http):
    """The fake board, registered as "fake" and served from `fake.pages`."""
    board = Fake()
    board.pages = {}
    monkeypatch.setitem(REGISTRY, "fake", board)

    def answer(url):
        kw, n = url[len("fake://"):].rsplit("/", 1)
        return page(board.pages.get((kw, int(n)), []))
    board.calls = http(answer)
    return board


@pytest.fixture
def db(tmp_path):
    return Store(tmp_path / "j.db")


def job(board="justjoin", key="1", title="AI Automation Specialist", **kw):
    return Offer(board=board, key=key, url=kw.pop("url", f"https://{board}/{key}"), title=title, **kw)


def ingest(db, *offers, run=None, board="x", keyword=None, params=None, complete=None, stop="last page"):
    """Store `offers` as seen by one request of `run` (a new run when None); `complete` given: finish the request
    with it. Returns the run id."""
    run = run or db.start_run({}, [])
    req = db.start_request(run, board, "all", keyword, params or {}, ())
    db.ingest(list(offers), run, req, 1)
    if complete is not None:
        db.finish_request(req, 1, len(offers), complete, stop)
    return run


def crawl(db, *searches, run=None, **kw):
    """Crawl the fake board for `searches` (default: everything remote) like `neetscape run`: identical requests once.
    Returns the run id."""
    searches = searches or (ALL_REMOTE,)
    reqs = list({r.key: r for s in searches for r in REGISTRY["fake"].requests(s)[0]}.values())
    run = run or db.start_run({}, [])
    asyncio.run(crawler.crawl(reqs, {s.id: s for s in searches}, db, run, port=0, limiter=Limiter(), fx=DEFAULT_FX, **kw))
    return run


def requests_of(db, run, by="cat"):
    """The run's requests by one of their parameters ("" when missing), or by keyword (`by=None`)."""
    rows = db.q("SELECT * FROM requests WHERE run_id=?", run)
    return {(r["keyword"] if by is None else json.loads(r["params_json"]).get(by, "")): r for r in rows}


def save_posting(db, ref, text="text", status=200, **meta):
    """Store a fetched posting of offer `ref` as `details` does, and derive the offer again."""
    details._save(db, db.offer(ref), status, text, meta)


def search(**kw):
    """One validated search of a profile (fields as in profile.json)."""
    return profile.validate({"version": 2, "searches": [{"id": "x", **kw}]}).searches[0]


def write_profile(path, **extra):
    """A profile.json in `path` searching the fake board for everything remote, review mode `listing`."""
    raw = {"version": 2, "boards": ["fake"], "searches": [{"id": "all", "where": "remote", "what": "all"}],
           "review": {"mode": "listing"}, **extra}
    (path / "profile.json").write_text(json.dumps(raw))
