"""Live smoke tests: one page per board against the real site. Never run in CI.

    pytest -m live                    # all boards
    pytest -m live -k pracuj          # one board

They catch markup/API changes that offline fixture tests cannot: a board returning nothing, or a
field that used to be filled dropping to zero.
"""
import asyncio
import tempfile
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import country_of
from neetscape.boards.fetch import Limiter
from neetscape.browser import Browser
from neetscape.crawler import crawl
from neetscape.model import Search, Where
from neetscape.pay import DEFAULT_FX
from neetscape.store import Store

pytestmark = pytest.mark.live
PORT = 9411

# board -> (keyword needed because listing everything is guarded, minimum fill ratio per field)
EXPECT = {
    "justjoin": (None, {"company": 0.9, "mode": 0.9, "published": 0.9}),
    "rocketjobs": (None, {"company": 0.9, "mode": 0.9, "published": 0.9}),
    "solidjobs": (None, {"company": 0.9, "pay_text": 0.9}),
    "linkedin": (None, {"company": 0.9, "published": 0.5}),
    "pracuj": (None, {"company": 0.9, "published": 0.9}),
    "nofluffjobs": (None, {"company": 0.9, "published": 0.9}),
    "indeed": ("asystent", {"company": 0.7, "published": 0.9}),
    "theprotocol": (None, {"company": 0.8}),
    "bulldogjob": (None, {"company": 0.8, "published": 0.9}),
    "useme": ("asystent", {"company": 0.8}),
    "olx": ("asystent", {"published": 0.8}),
    "gowork": (None, {"company": 0.9, "published": 0.9}),
    "pracapl": (None, {"published": 0.9}),
    "remoteok": (None, {"company": 0.9}),
    "weworkremotely": (None, {"company": 0.9}),
    "arbeitnow": (None, {"company": 0.9, "published": 0.9}),
    "bundesagentur": (None, {"company": 0.9, "published": 0.9}),
}


@pytest.fixture(scope="module")
def browser():
    with Browser(port=PORT):
        yield


@pytest.mark.parametrize("board", sorted(EXPECT))
def test_board_live(board, browser):
    keyword, fill = EXPECT[board]
    cc = country_of(REGISTRY[board])
    where = Where(remote=True, country=cc if cc not in ("any", "intl") else "pl")
    s = Search(id="live", label="live", where=where, keywords=(keyword,) if keyword else None)
    reqs, _ = REGISTRY[board].requests(s)
    assert reqs, f"{board} cannot serve a remote search"
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "live.db")
        run = store.start_run({}, ["live"])
        asyncio.run(crawl(reqs[:1], {"live": s}, store, run, port=PORT, limiter=Limiter(), fx=DEFAULT_FX, limit_pages=1))
        err = store.q("SELECT error FROM requests WHERE run_id=?", run)[0]["error"]
        rows = store.run_offers(run)
        store.close()
    assert not err, f"{board}: {err}"
    assert len(rows) >= 5, f"{board}: only {len(rows)} offers"
    assert all(o["title"] for o in rows)
    for field, minimum in fill.items():
        ratio = sum(1 for o in rows if o[field] not in (None, "", "unknown", "[]")) / len(rows)
        assert ratio >= minimum, f"{board}: {field} filled in {ratio:.0%} < {minimum:.0%}"
