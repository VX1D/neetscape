"""Shared boards (neetscape/boards/: LinkedIn, the international feeds) on their recorded pages in tests/fixtures/shared/."""
import json
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY, linkedin
from neetscape.boards.base import Request

FX = Path(__file__).parents[1] / "fixtures" / "shared"
FIXTURES = {"linkedin": "linkedin.html", "remoteok": "remoteok.json", "weworkremotely": "weworkremotely.rss"}


@pytest.mark.parametrize("board", sorted(FIXTURES))
def test_board_parses_recorded_page(board):
    offers = REGISTRY[board].parse((FX / FIXTURES[board]).read_text(), Request(board, "t", None, {}, frozenset()))
    assert len(offers) >= 3, board
    for o in offers:
        assert o.board == board and o.key and o.url.startswith("http") and o.title
    assert len({o.key for o in offers}) == len(offers)
    assert REGISTRY[board].caps.country == ("any" if board == "linkedin" else "intl")


def test_linkedin_city_as_geo_id(monkeypatch):
    hits = json.loads((FX / "linkedin_typeahead_krakow.json").read_text())
    assert linkedin.pick_geo("Kraków", hits) == "103263110"           # Małopolskie, not the village in Łódzkie
    assert linkedin.pick_geo("Krakow", hits, "pl") == "103263110"
    assert linkedin.pick_geo("Nowhere", [h for h in hits if "Polska" not in h["displayName"]]) is None
    assert linkedin.pick_geo("Kraków", hits, "de") == "102982500"     # the first German hit (Krakow am See)
    li = REGISTRY["linkedin"]
    monkeypatch.setattr(linkedin, "geo_id", lambda city, cc: "103263110" if cc == "pl" else None)
    url = li.page_url(Request("linkedin", "t", "n8n", {"city": "Kraków", "radius_km": 30, "part_time": True, "country": "pl"}), 2)
    assert url == linkedin.SEARCH + "keywords=n8n&geoId=103263110&start=10"
    assert li.page_url(Request("linkedin", "t", "n8n", {"city": "Köln", "country": "de"}), 1) == (
        linkedin.SEARCH + "keywords=n8n&location=K%C3%B6ln&start=0")


@pytest.mark.parametrize("cc,location", [("pl", "Poland"), ("de", "Germany"), (None, "Poland")])
def test_linkedin_country_location(cc, location):
    params = {"remote": True} | ({"country": cc} if cc else {})
    assert REGISTRY["linkedin"].page_url(Request("linkedin", "t", None, params), 1) == (
        linkedin.SEARCH + f"keywords=&location={location}&start=0")


def test_linkedin_posting_is_the_description_block_only():
    from neetscape.boards.linkedin import LinkedIn
    page = (Path(__file__).parents[1] / "fixtures" / "shared" / "linkedin_posting.html").read_text()
    meta = LinkedIn.posting_fields(page)
    text = meta["description"]
    assert meta["source"] == "api" and text.startswith("Location: Warsaw, Mazowieckie, Poland\nSeniority level: Associate")
    assert "Employment type: Full-time" in text and len(text) > 2000
    assert "Report this job" not in text and "Similar jobs" not in text   # page chrome around the block
    assert LinkedIn.posting_fields("<html>login wall</html>")["description"] == ""


def test_linkedin_remote_all_is_sent_as_remote_phrases():
    from neetscape.model import Search, Where
    li = REGISTRY["linkedin"]
    reqs, warns = li.requests(Search(id="all", label="all", where=Where(remote=True), keywords=None))
    assert [r.keyword for r in reqs] == list(linkedin.REMOTE_PHRASES["pl"])
    assert all(r.params == {"country": "pl"} and r.pushed == {"keyword"} for r in reqs)   # the mode stays unknown
    assert "sent as the phrases remote, zdalnie" in warns[0]
    de, _ = li.requests(Search(id="de", label="de", where=Where(remote=True, country="de"), keywords=None))
    assert [r.keyword for r in de] == list(linkedin.DEFAULT_REMOTE_PHRASES)
    # phrases, a city and "anywhere" are left alone; "city or remote" sends phrases only for its remote part
    assert [r.keyword for r in li.requests(Search(id="kw", label="kw", where=Where(remote=True), keywords=("n8n",)))[0]] == ["n8n"]
    assert [r.keyword for r in li.requests(Search(id="any", label="any", where=Where(), keywords=None))[0]] == [None]
    both, _ = li.requests(Search(id="b", label="b", where=Where(remote=True, city="Kraków"), keywords=None))
    assert [(r.keyword, r.params.get("city")) for r in both] == [(None, "Kraków")] + [(p, None) for p in linkedin.REMOTE_PHRASES["pl"]]


def card(loc, n=[0]):
    from neetscape.model import Offer
    n[0] += 1
    return Offer(board="linkedin", key=f"k{n[0]}", url="u", title="t", locations=[loc] if loc else [])


def test_linkedin_split_by_region_then_city(monkeypatch):
    li = REGISTRY["linkedin"]
    assert li.caps.result_cap == 1000 and li.total("", Request("linkedin", "t", None)) is None
    r = Request("linkedin", "t", None, {"country": "pl"})
    seen = ([card("Warsaw, Mazowieckie, Poland") for _ in range(12)] + [card("Otwock, Mazowieckie, Poland") for _ in range(3)]
            + [card("Opole, Opolskie, Poland"), card("Bydgoszcz Metropolitan Area"), card(""), card("Poland")])
    regions = li.split("", r, seen)
    assert [x.params for x in regions] == [{"country": "pl", "region": "Mazowieckie"}, {"country": "pl", "region": "Opolskie"}]
    cities = li.split("", regions[0], seen)                           # a capped region: its cities seen >= MIN_CITY times
    assert [x.params for x in cities] == [{"country": "pl", "region": "Mazowieckie", "city": "Warsaw"}]
    assert li.split("", cities[0], seen) == []                        # a city is not narrowed
    assert li.split("", r, seen + [card("Poland"), card("Poland")]) == []   # 3 of 21 at country level: parts repeat them
    monkeypatch.setattr(linkedin, "geo_id", lambda place, cc: {"Mazowieckie": "102996679", "Warsaw": "105076658"}.get(place))
    assert li.page_url(regions[0], 1) == linkedin.SEARCH + "keywords=&geoId=102996679&start=0"
    assert li.page_url(cities[0], 3) == linkedin.SEARCH + "keywords=&geoId=105076658&start=20"
    assert li.page_url(regions[1], 1) == linkedin.SEARCH + "keywords=&location=Opolskie&start=0"   # no geoId: free text
