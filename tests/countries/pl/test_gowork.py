"""gowork.pl on its recorded (trimmed) result page tests/fixtures/pl/gowork.html."""
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request
from neetscape.boards.pages import labelled_contracts, nearest_radius, prefix_level, worktime_from_labels
from neetscape.countries.pl.boards import gowork
from neetscape.countries.pl.boards.vocab import CONTRACTS, FULL_TIME, LEVELS, PART_TIME
from neetscape.model import Search, Where
from neetscape.pay import parse_pay

FIXTURE = Path(__file__).parents[2] / "fixtures" / "pl" / "gowork.html"
BOARD = REGISTRY["gowork"]


def offers():
    return BOARD.parse(FIXTURE.read_text(), Request("gowork", "t", None))


def test_parses_own_postings_and_skips_copies():
    got = offers()
    assert len(got) == 13  # 15 recorded, 2 copies of lento.pl ads (/oferta-zewnetrzna/) skipped
    assert len({o.key for o in got}) == len(got)
    for o in got:
        assert o.key == o.url and o.url.startswith("https://www.gowork.pl/oferta/")
        assert o.title and o.company and o.locations and o.published and o.category


def test_fields():
    got = offers()
    assert sum(o.mode == "remote" for o in got) == 7 and {o.mode for o in got} == {"remote", "onsite", "unknown"}
    assert sum(o.promoted for o in got) == 7  # segment 6
    assert {o.worktime for o in got} == {"part_time", "full_time", "unknown"}
    assert all(o.contracts for o in got if o.mode != "unknown")
    assert {o.level for o in got} >= {"junior", "mid", "senior", "unknown"}
    hourly = next(o for o in got if "/hour" in o.pay_text and "PLN" in o.pay_text)
    assert hourly.pay_text.startswith("salary:31.4-31.4 PLN/hour brutto")  # hundredths: 3140 -> 31.4
    assert any("EUR/hour" in o.pay_text for o in got)
    monthly = next(o for o in got if o.pay_text.startswith("salary:4880-8000 PLN/month brutto"))
    assert parse_pay(monthly.pay_text) == (5904, 10000)  # the netto range is the higher one


def test_board_vocabularies():
    assert prefix_level("Młodszy specjalista (Junior)", LEVELS) == "junior"
    assert prefix_level("Starszy specjalista (Senior)", LEVELS) == "senior"
    assert prefix_level("Pracownik fizyczny", LEVELS) == "unknown" and prefix_level(None, LEVELS) == "unknown"
    assert labelled_contracts(["Umowa o pracę", "Kontrakt B2B", "Umowa o tymczasową pracę"], CONTRACTS) == \
        ["employment", "b2b", "temp_agency"]
    assert worktime_from_labels(["Pełny etat", "Dodatkowa"], PART_TIME, FULL_TIME) == "part_time"
    assert worktime_from_labels(["Pełny etat"], PART_TIME, FULL_TIME) == "full_time"
    assert [nearest_radius(km, gowork.RADII) for km in (0, 40, 500)] == [5, 50, 100]


def test_page_urls():
    r = Request("gowork", "t", "automatyzacja procesów", {"city": "Bielsko-Biała", "radius_km": 30, "part_time": True})
    assert BOARD.page_url(r, 1) == "https://www.gowork.pl/praca/automatyzacja-procesow;st/bielsko-biala;l/czesc-etatu,dodatkowa;e/30;km"
    assert BOARD.page_url(r, 2).endswith("/czesc-etatu,dodatkowa;e/2;pg/30;km")
    remote = Request("gowork", "t", None, {"remote": True})
    assert BOARD.page_url(remote, 1) == "https://www.gowork.pl/praca/zdalna;tr"
    assert BOARD.page_url(remote, 3) == "https://www.gowork.pl/praca/zdalna;tr/3;pg"
    assert BOARD.page_url(remote, BOARD.caps.max_pages + 1)  # never None: max_pages is a safety stop


def test_requests_remote_everything_but_not_whole_board():
    reqs, warns = BOARD.requests(Search(id="all", label="all", where=Where(remote=True), keywords=None))
    assert [r.params for r in reqs] == [{"remote": True}] and not warns
    reqs, warns = BOARD.requests(Search(id="any", label="any", where=Where(remote=False), keywords=None))
    assert not reqs and warns  # 26 000 offers without a keyword or a city


def test_phrases_starting_with_praca():
    """Page 1 of a `/praca/praca...;st` search redirects to itself: the leading word "praca" is dropped."""
    assert [gowork.keyword_slug(p) for p in ("praca dodatkowa", "Praca  zdalna", "praca praca biurowa", "pracownik biurowy")] \
        == ["dodatkowa", "zdalna", "biurowa", "pracownik-biurowy"]
    assert gowork.keyword_slug("praca") == gowork.keyword_slug("pracadodatkowa") == ""
    r = Request("gowork", "t", "praca dodatkowa", {"remote": True})
    assert BOARD.page_url(r, 1) == "https://www.gowork.pl/praca/dodatkowa;st/zdalna;tr"
    s = Search(id="side", label="side", where=Where(remote=True), keywords=("praca dodatkowa", "praca", "helpdesk"))
    reqs, warns = BOARD.requests(s)
    assert [r.keyword for r in reqs] == ["praca dodatkowa", "helpdesk"]
    assert len(warns) == 1 and "'praca'" in warns[0] and "skipped for 'side'" in warns[0]


def test_page_without_payload_raises():
    with pytest.raises(ValueError):
        BOARD.parse("<html>blocked</html>", Request("gowork", "t", None))
