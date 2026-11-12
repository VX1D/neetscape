"""pracuj.pl on its recorded `__NEXT_DATA__` extract tests/fixtures/pl/pracuj.json (output of `fetch_js`) and offer
page tests/fixtures/pl/pracuj_posting.html."""
import json
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request
from neetscape.boards.pages import labelled_contracts
from neetscape.countries.pl.boards.pracuj import level
from neetscape.countries.pl.boards.vocab import CONTRACTS
from neetscape.model import Search, Where

FX = Path(__file__).parents[2] / "fixtures" / "pl"
B = REGISTRY["pracuj"]


def offers():
    return B.parse((FX / "pracuj.json").read_text(), Request("pracuj", "t", None))


def test_page_urls():
    r = Request("pracuj", "t", None, {"remote": True, "part_time": True})
    assert B.page_url(r, 1) == "https://www.pracuj.pl/praca/praca%20zdalna;wm,home-office?ws=1%2C2"
    assert B.page_url(r, 3) == "https://www.pracuj.pl/praca/praca%20zdalna;wm,home-office?ws=1%2C2&pn=3"
    city = Request("pracuj", "t", "asystent", {"city": "Kraków", "radius_km": 30, "part_time": True})
    assert B.page_url(city, 2) == "https://www.pracuj.pl/praca/asystent;kw/krakow;wp?rd=30&ws=1%2C2&pn=2"
    assert B.page_url(Request("pracuj", "t", "asystent", {"city": "Kraków", "radius_km": 30}), 1) == (
        "https://www.pracuj.pl/praca/asystent;kw/krakow;wp?rd=30")
    assert B.page_url(r, B.caps.max_pages + 1) is None


def test_only_keyword_free_listings_are_newest_first():
    reqs, _ = B.requests(Search(id="s", label="s", where=Where(remote=True), keywords=("python",)))
    assert reqs and all("sort" not in r.params for r in reqs)  # keyword listings are by relevance
    reqs, _ = B.requests(Search(id="s", label="s", where=Where(remote=True), keywords=None))
    assert [r.params.get("sort") for r in reqs] == ["newest"]
    reqs, _ = B.requests(Search(id="s", label="s", where=Where(remote=True), keywords=None, worktime=frozenset({"part_time"})))
    assert reqs[0].params.get("part_time") and "worktime" in reqs[0].pushed


def test_recorded_page_fields():
    got = offers()
    assert len(got) == 15 and all(o.level != "unknown" for o in got)
    assert all(o.company and o.published and o.locations and o.mode == "remote" and o.contracts for o in got)
    assert any(len(o.locations) > 1 for o in got) and sum(1 for o in got if o.pay_text) >= 3
    assert sum(o.worktime == "unknown" for o in got) == 1  # "Ferryt Tester" lists no work schedule
    assert any(o.worktime == "part_time" for o in got)
    with pytest.raises(ValueError):
        B.parse("", Request("pracuj", "t", None))


def test_board_levels_and_contracts():
    assert level(["Asystent / Asystentka"]) == "junior"
    assert level(["Menedżer / Menedżerka"]) == "manager"
    assert level(["Starszy specjalista / Starsza specjalistka (senior)", "Specjalista / Specjalistka (mid / Regular)"]) == "mid"
    assert level(["Pracownik fizyczny / Pracowniczka fizyczna"]) == "unknown"
    assert labelled_contracts(["Umowa o pracę tymczasową", "Umowa na zastępstwo", "Kontrakt B2B"], CONTRACTS) == \
        ["temp_agency", "employment", "b2b"]


def test_published_is_the_posting_date_and_refreshed_offers_are_promoted():
    raw = json.loads((FX / "pracuj.json").read_text())["offers"]
    parsed = {o.key: o for o in offers()}
    for g in raw:
        o = parsed[sorted(x["url"] for x in g["offers"])[0]]
        assert o.published.isoformat() == g["initialPublicated"][:10]
        assert o.promoted == (g["initialPublicated"][:10] != g["lastPublicated"][:10])
    assert any(o.promoted for o in parsed.values()) and not all(o.promoted for o in parsed.values())


def test_posting_reads_the_sections_not_the_blurb():
    meta = B.posting((FX / "pracuj_posting.html").read_text())
    text = meta["description"]
    assert meta["source"] == "board"
    assert "Twój zakres obowiązków\n• odbieraniem zgłoszeń" in text and "Mile widziane" in text
    assert "Przejdź do treści" not in text
    assert meta["company"]                      # JSON-LD fields are kept
