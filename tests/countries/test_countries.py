"""Every country and every board: consistent definitions, a recorded fixture per board, parsers of the
country packages on their fixtures."""
from pathlib import Path

import pytest

from neetscape import country as countries
from neetscape import lang, profile
from neetscape.boards import REGISTRY, expand, groups
from neetscape.boards.base import Request, country_of
from neetscape.model import CONTRACTS, Search, Where

FX = Path(__file__).parent.parent / "fixtures"
CODES = countries.codes()


def fixture_for(board: str) -> Path | None:
    """The recorded result page: tests/fixtures/<cc>/<board>.* for country boards, tests/fixtures/shared/<board>.*
    for shared ones (serving any country, international)."""
    cc = country_of(REGISTRY[board])
    found = sorted((FX / (cc if cc in CODES else "shared")).glob(f"{board}.*"))
    return found[0] if found else None


@pytest.mark.parametrize("code", CODES)
def test_country_definition(code):
    c = countries.get(code)
    assert c.code == code and c.fx[c.currency] == 1.0
    for cc in c.languages:
        assert cc in lang.available(), f"{code}: no lang pack {cc}"
    assert set(c.contracts) <= set(CONTRACTS) and set(c.contract_aliases.values()) <= set(CONTRACTS)
    assert c.default_boards and set(expand(list(c.default_boards))) <= set(REGISTRY)
    assert any(country_of(REGISTRY[b]) == code for b in expand(list(c.default_boards))), f"{code}: no own board"
    assert c.linkedin_location and c.place_names
    assert profile.presets(code)
    for name in profile.presets(code):
        p = profile.validate(profile.preset(name, code))
        assert p.country.code == code


@pytest.mark.parametrize("board", sorted(REGISTRY))
def test_board_has_known_country_and_fixture(board):
    assert country_of(REGISTRY[board]) in CODES + list(countries.PSEUDO)
    assert fixture_for(board), f"{board}: record a page with `neetscape probe {board} --save-fixture tests/fixtures/<cc>/{board}.json`"


COUNTRY_BOARDS = sorted(n for n, b in REGISTRY.items() if type(b).__module__.startswith("neetscape.countries."))


@pytest.mark.parametrize("board", COUNTRY_BOARDS)
def test_country_board_parses_its_fixture(board):
    offers = REGISTRY[board].parse(fixture_for(board).read_text(), Request(board, "t", None))
    assert len(offers) >= 3
    for o in offers:
        assert o.board == board and o.key and o.url.startswith("http") and o.title
        assert o.mode in ("remote", "hybrid", "onsite", "unknown") and set(o.contracts) <= set(CONTRACTS)
    assert len({o.key for o in offers}) == len(offers)


def test_schema_country_enum_matches_registry():
    s = profile.schema()
    assert sorted(s["properties"]["country"]["enum"]) == CODES
    where = s["properties"]["searches"]["items"]["properties"]["where"]["oneOf"][1]["properties"]
    assert sorted(where["country"]["enum"]) == CODES
    contracts = s["properties"]["searches"]["items"]["properties"]["contracts"]["items"]["enum"]
    assert contracts == list(CONTRACTS) + ["uop"]


def test_groups():
    g = groups()
    assert "linkedin" in g["pl"] and "linkedin" in g["de"]
    assert "justjoin" in g["pl"] and "justjoin" not in g["de"]
    assert {"arbeitnow", "bundesagentur"} <= set(g["de"])
    assert g["intl"] == ["remoteok", "weworkremotely"] and set(g["all"]) == set(REGISTRY)


def test_board_of_another_country_skips_the_search():
    s = Search(id="x", label="x", where=Where(remote=True, country="de"), keywords=("python",))
    reqs, warns = REGISTRY["justjoin"].requests(s)
    assert not reqs and "for pl" in warns[0]
    reqs, _ = REGISTRY["linkedin"].requests(s)
    assert reqs[0].params["country"] == "de"


def test_city_aliases():
    de = countries.get("de")
    assert {"munchen", "munich"} <= de.aliases("München") and "munchen" in de.aliases("Munich")
    assert "warsaw" in countries.get("pl").aliases("Warszawa")
