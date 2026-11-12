"""praca.pl (neetscape/countries/pl/boards/pracapl.py) on its recorded result page tests/fixtures/pl/pracapl.html."""
import datetime as dt
from pathlib import Path

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request
from neetscape.boards.pages import labelled_contracts
from neetscape.countries.pl.boards import pracapl
from neetscape.countries.pl.boards.vocab import CONTRACTS
from neetscape.model import Search, Where

FX = Path(__file__).parents[2] / "fixtures" / "pl" / "pracapl.html"
BOARD = REGISTRY["pracapl"]


def offers():
    return BOARD.parse(FX.read_text(), Request("pracapl", "t", None, {"remote": True}, frozenset({"remote"})))


def test_relative_dates_and_level_tags():
    today = dt.date(2026, 11, 12)
    assert pracapl.edition_day("Numer wydania: 20769&nbsp;/&nbsp;2026") == today
    assert [pracapl.published(s, today) for s in ("przed chwilą", "23 godzin temu", "1 godzinę temu", "wczoraj", "9 dni temu")] == \
        [today, today, today, today - dt.timedelta(1), today - dt.timedelta(9)]
    assert pracapl.published("wczoraj", None) is None and pracapl.published("03.11.2026", None) == dt.date(2026, 11, 3)
    assert pracapl.level("Praktykant / praktykantka / stażysta / stażystka / asystent / asystentka") == "intern"
    assert pracapl.level("Specjalista / specjalistka (mid) / starszy specjalista / starsza specjalistka (senior)") == "mid"
    assert pracapl.level("Pracownik fizyczny / pracowniczka fizyczna") == "unknown"
    tag = "Umowa o pracę / umowa o dzieło / umowa zlecenie / umowa o staż/praktykę / kontrakt B2B"
    assert labelled_contracts(tag.split(" / "), CONTRACTS) == ["employment", "specific_task", "mandate", "internship", "b2b"]


def test_empty_search_and_other_sections_yield_nothing():
    card = ('<li class="listing-v2__item" data-ad-id="1"><a class="listing-v2__title" '
            'href="https://www.praca.pl/x_11.html">X</a></li>')
    r = Request("pracapl", "t", "zzz")
    assert BOARD.parse('<div class="al__no-offers-block gtm-empty-listing"></div>' + card, r) == []
    assert BOARD.parse('<h2 class="listing-v2__header">Zobacz najnowsze oferty pracy</h2>' + card, r) == []
    assert len(BOARD.parse('<h2 class="listing-v2__header">Oferty urzędu pracy</h2>' + card, r)) == 1


def test_requests():
    remote_all, _ = BOARD.requests(Search(id="s", label="s", where=Where(remote=True), keywords=None,
                                          worktime=frozenset({"part_time"})))
    assert [(r.keyword, r.params) for r in remote_all] == [(None, {"remote": True, "sort": "newest", "part_time": True})]
    reqs, warns = BOARD.requests(Search(id="s", label="s", where=Where(), keywords=None))
    assert not reqs and warns  # the whole board unfiltered is too large
    city, _ = BOARD.requests(Search(id="s", label="s", where=Where(city="Kraków", radius_km=30), keywords=("asystent",)))
    assert city[0].params == {"city": "Kraków", "radius_km": 30, "sort": "newest"} and "city" in city[0].pushed
