"""praca.pl (neetscape/countries/pl/boards/pracapl.py) on its recorded result page tests/fixtures/pl/pracapl.html."""
import datetime as dt
import re
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


def test_parses_cards_with_structured_fields():
    got = offers()
    assert len(got) == 13 and len({o.key for o in got}) == 13
    assert all(re.fullmatch(r"\d+", o.key) for o in got)  # the ad id, the same in every listing
    assert all(re.fullmatch(r"https://www\.praca\.pl/[a-z0-9-]+_\d+\.html", o.url) for o in got)  # no #tracking hash
    assert all(o.title and o.mode == "remote" and o.locations and o.published for o in got)
    assert all(o.worktime != "unknown" for o in got) and sum(1 for o in got if o.level != "unknown") >= 12
    assert sum(1 for o in got if o.company) >= 8 and "Klient portalu Praca.pl" not in {o.company for o in got}
    assert sum(1 for o in got if o.contracts) >= 8 and sum(1 for o in got if o.pay_text) >= 3


def test_fields_of_known_offers():
    by_key = {o.key: o for o in offers()}
    week = by_key["7992486"]  # "Oferta tygodnia": paid, above the date order
    assert week.promoted and week.title == "Główna Księgowa / Główny Księgowy" and week.locations == ["Pruszków"]
    assert week.contracts == ["mandate", "b2b"] and week.worktime == "full_time" and week.published == dt.date(2026, 11, 9)
    grouped = by_key["7959811"]  # one ad in many towns: one offer, the lowest offer id as url
    assert len(grouped.locations) > 10 and grouped.url.endswith("_11597182.html")
    assert grouped.pay_text == "60,00 - 160,00 zł brutto/godz." and grouped.worktime == "part_time" and grouped.level == "mid"
    lux = by_key["7965190"]  # highlighted, but in date order: not promoted
    assert not lux.promoted and lux.company == "LUX MED Sp. z o.o." and lux.contracts == ["mandate"]
    assert lux.level == "junior" and lux.published == dt.date(2026, 11, 12) and lux.snippet.startswith(lux.title)
    assert by_key["7972480"].locations == ["Niemcy"]
    assert [o.published for o in offers() if not o.promoted] == sorted((o.published for o in offers() if not o.promoted), reverse=True)


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


def test_urls():
    url = lambda kw, page=1, **p: BOARD.page_url(Request("pracapl", "t", kw, p), page)
    assert url("asystent", remote=True, sort="newest") == "https://www.praca.pl/s-asystent.html?wm=3&sort=date"
    assert url("obsługa klienta", 2, remote=True, part_time=True, sort="newest") == \
        "https://www.praca.pl/s-obsluga,klienta_2.html?wm=3&wt=2-3&sort=date"
    assert url("asystent", city="Zielona Góra", radius_km=25, sort="newest") == \
        "https://www.praca.pl/s-asystent_m-zielona-gora.html?cr=30&sort=date"
    assert url(None, 3, city="Kraków") == "https://www.praca.pl/krakow_3.html"
    assert url(None, remote=True, sort="newest") == "https://www.praca.pl/oferty-pracy.html?wm=3&sort=date"
    assert url("x", 21) is None
    assert pracapl.keyword_slug("Asystent/ka ds. Administracji") == "asystent-ka,ds,administracji"


def test_requests():
    remote_all, _ = BOARD.requests(Search(id="s", label="s", where=Where(remote=True), keywords=None,
                                          worktime=frozenset({"part_time"})))
    assert [(r.keyword, r.params) for r in remote_all] == [(None, {"remote": True, "sort": "newest", "part_time": True})]
    reqs, warns = BOARD.requests(Search(id="s", label="s", where=Where(), keywords=None))
    assert not reqs and warns  # the whole board unfiltered is too large
    city, _ = BOARD.requests(Search(id="s", label="s", where=Where(city="Kraków", radius_km=30), keywords=("asystent",)))
    assert city[0].params == {"city": "Kraków", "radius_km": 30, "sort": "newest"} and "city" in city[0].pushed
