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
