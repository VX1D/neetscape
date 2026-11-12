"""Polish boards (neetscape/countries/pl/boards/) on their recorded pages in tests/fixtures/pl/."""
import json
import re
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request
from neetscape.countries.pl.boards import indeed, olx
from neetscape.countries.pl.boards.justjoin import category_from_slug, extract_offers

FX = Path(__file__).parents[2] / "fixtures" / "pl"
FIXTURES = {
    "justjoin": "justjoin.txt", "rocketjobs": "rocketjobs.txt", "solidjobs": "solidjobs.json",
    **{b: f"{b}.json" for b in ("pracuj", "nofluffjobs", "theprotocol", "bulldogjob", "indeed", "useme", "olx")},
}


def parse(board, params=None):
    return REGISTRY[board].parse((FX / FIXTURES[board]).read_text(), Request(board, "t", None, params or {}, frozenset()))


@pytest.mark.parametrize("board", sorted(FIXTURES))
def test_board_parses_recorded_page(board):
    offers = parse(board, {"division": "it"} if board == "solidjobs" else {})
    assert len(offers) >= 3, board
    for o in offers:
        assert o.board == board and o.key and o.url.startswith("http") and o.title
        assert o.title.lower() not in ("sprawdź!", "skip to main content")
    assert len({o.key for o in offers}) == len(offers)


def test_justjoin_and_solidjobs_fill_rich_fields():
    assert all(o.company and o.mode != "unknown" and o.published and o.contracts for o in parse("justjoin"))
    assert all(o.pay_text and o.mode in ("remote", "hybrid", "onsite") for o in parse("solidjobs", {"division": "it"}))


@pytest.mark.parametrize("board", ["nofluffjobs", "theprotocol", "bulldogjob"])
def test_json_boards_fill_rich_fields(board):
    offers = parse(board)
    assert all(o.company and o.mode == "remote" and o.level != "unknown" for o in offers), board
    assert sum(1 for o in offers if o.pay_text) >= 5 and all(o.contracts for o in offers if o.pay_text), board
    if board != "bulldogjob":  # bulldogjob's listing JSON has no dates
        assert all(o.published for o in offers), board
    with pytest.raises(ValueError):
        REGISTRY[board].parse("", Request(board, "t", None))


def test_nofluffjobs_keys_and_pay_units():
    nfj = parse("nofluffjobs")
    assert len({o.pay_text for o in nfj}) > 1  # each offer has its own pay, not the first one of the list
    assert all(o.key.startswith("https://nofluffjobs.com/pl/job/") and "?" not in o.key for o in nfj)
    assert any(o.pay_text.endswith(" PLN/hour") for o in nfj) and all(o.category for o in nfj)
    assert all(re.fullmatch(r"[a-z0-9_]+:\d+-\d+ [A-Z]{3}/(hour|day|month|year)", o.pay_text) for o in nfj if o.pay_text)


def test_theprotocol_keys_and_pay_per_contract():
    tp = parse("theprotocol")
    assert all(re.fullmatch(r"https://theprotocol\.it/szczegoly/praca/[^?#]+,oferta,[0-9a-f-]+", o.key) for o in tp)
    assert any("; " in o.pay_text and len(o.contracts) > 1 for o in tp)  # one pay range per contract type
    assert all(o.locations for o in tp)


def test_bulldogjob_keys_and_pay():
    bd = parse("bulldogjob")
    assert all(re.fullmatch(r"https://bulldogjob\.pl/companies/jobs/\d+-[^/?#]+", o.key) for o in bd)
    assert any(o.pay_text.endswith(" EUR") for o in bd) or any(o.pay_text.endswith(" PLN") for o in bd)


def test_pracuj_structured_results():
    offers = parse("pracuj")
    assert all(o.company and o.published and o.locations and o.mode == "remote" and o.contracts for o in offers)
    assert any(len(o.locations) > 1 for o in offers) and any(o.promoted for o in offers)
    assert sum(1 for o in offers if o.pay_text) >= 3
    with pytest.raises(ValueError):
        REGISTRY["pracuj"].parse("", Request("pracuj", "t", None))


def test_olx_and_indeed_card_quirks():
    card = lambda board, link, rest: REGISTRY[board].card(link, rest)
    # pay stops after its unit; numbers in the title (street, hours) are not pay
    c = card("olx", "Pomoc kuchenna- ZAKOPIAŃSKA 62",
             "Bistro Sp. z o.o. 31,40 - 33 zł / godz. brutto Kraków, Łagiewniki Pełny etat Umowa o pracę")
    assert (c["pay_text"], c["company"], c["locations"]) == ("31,40 - 33 zł / godz. brutto", "Bistro Sp. z o.o.", ["Kraków, Łagiewniki"])
    c = card("olx", "Asystent ds Jakości", "Firma X Kraków, Grzegórzki Pełny etat Umowa o pracę")
    assert (c["pay_text"], c["company"], c["locations"]) == ("", "Firma X", ["Kraków, Grzegórzki"])
    c = card("indeed", "Asystent biura", "HR Project 31-444 Kraków 4 000-6 000 PLN za miesiąc")
    assert (c["company"], c["locations"], c["pay_text"]) == ("HR Project", ["Kraków"], "4 000-6 000 PLN za miesiąc")
    c = card("indeed", "Junior", "Uniwersytet Ekonomiczny Zdalnie Umowa zlecenie")
    assert (c["company"], c["locations"]) == ("Uniwersytet Ekonomiczny", [])
    assert indeed.company_and_place("nothing to see") == {}


def test_indeed_skips_planted_links_and_reads_company():
    offers = parse("indeed")
    assert not any("fedcba9876543210" in o.key for o in offers)  # bare /viewjob copy with a fake id
    assert all(o.company for o in offers) and sum(1 for o in offers if o.locations) >= 3


def test_olx_dates_promoted_and_remote_text():
    offers = parse("olx")
    assert all(o.published and o.locations for o in offers) and any(o.promoted for o in offers)
    assert not all(o.promoted for o in offers)
    remote = parse("olx", {"remote_text": True})
    assert remote and len(remote) < len(offers) and all(olx.REMOTE_TEXT.search(o.title + " " + o.snippet) for o in remote)


def _rsc_chunk(offers):
    js = json.dumps({"offers": offers, "next": 1}, separators=(",", ":"))
    return js.replace("\\", "\\\\").replace('"', '\\"') + '\\",\\"other\\":[1,2]'


def test_justjoin_extract_offers_handles_escapes_and_truncation():
    offers = [{"slug": "a-b", "title": 'Quote " and ] bracket'}, {"slug": "c", "title": "x"}]
    assert extract_offers(_rsc_chunk(offers)) == offers
    assert extract_offers("") == []
    assert extract_offers('{\\"offers\\":[{\\"slug\\":\\"a') is None


def test_justjoin_engine_urls():
    jj, rj = REGISTRY["justjoin"], REGISTRY["rocketjobs"]
    city = Request("x", "t", "python", {"city": "Kraków", "radius_km": 25, "part_time": True, "sort": "newest"})
    assert jj.page_url(city, 2) == ("https://justjoin.it/job-offers/krakow?keyword=python&radius=25"
                                    "&working-times=part-time,freelance&sortBy=newest&page=2")
    assert rj.page_url(city, 2) == ("https://rocketjobs.pl/oferty-pracy/krakow?keyword=python&radius=25"
                                    "&wymiar-godzin=niepelny-wymiar,freelance&sortBy=newest&strona=2")
    assert rj.page_url(Request("x", "t", None, {"remote": True}), 1) == "https://rocketjobs.pl/oferty-pracy/praca-zdalna?keyword="
    assert rj.page_url(Request("x", "t", None), 1) == "https://rocketjobs.pl/oferty-pracy/wszystkie-lokalizacje?keyword="
    assert jj.page_url(Request("x", "t", None), 151) is None


def test_justjoin_category_from_slug():
    assert category_from_slug("transition-technologies-ms-dwh-analyst-warszawa-data-961e82d7", "Warszawa") == "data"
    assert category_from_slug("cloudatus-finance-controlling-specialist-lodz-finanse-ksiegowosc", "Łódź") == "finanse ksiegowosc"
    assert category_from_slug("x-y", "") == ""
    assert all(o.category for o in parse("justjoin"))


@pytest.mark.parametrize("board,page,url", [
    ("nofluffjobs", 2, "https://nofluffjobs.com/pl/praca-zdalna?&page=2"),
    ("theprotocol", 2, "https://theprotocol.it/filtry/zdalna;rw?pageNumber=2"),
    ("bulldogjob", 2, "https://bulldogjob.pl/companies/jobs/s/city,Remote/page,2"),
])
def test_remote_listing_pages(board, page, url):
    assert REGISTRY[board].page_url(Request(board, "t", None, {"remote": True}), page) == url
    assert REGISTRY[board].page_url(Request(board, "t", None, {"remote": True}), REGISTRY[board].caps.max_pages + 1) is None


@pytest.mark.parametrize("board,params,url", [
    ("pracuj", {"city": "Kraków", "radius_km": 30}, "https://www.pracuj.pl/praca/asystent;kw/krakow;wp?rd=30"),
    ("indeed", {"city": "Gdańsk", "radius_km": 0, "sort": "newest"},
     "https://pl.indeed.com/jobs?q=asystent&l=Gda%C5%84sk&radius=0&sort=date"),
    ("olx", {"city": "Gdańsk", "radius_km": 0, "sort": "newest"},
     "https://www.olx.pl/praca/gdansk/q-asystent/?search%5Bdist%5D=0&search%5Border%5D=created_at%3Adesc"),
    ("nofluffjobs", {"city": "Warszawa"}, "https://nofluffjobs.com/pl/warszawa?criteria=keyword%3Dasystent"),
    ("bulldogjob", {"city": "Kraków"}, "https://bulldogjob.pl/companies/jobs/s/city,Krak%C3%B3w"),
    ("theprotocol", {"city": "Kraków"}, "https://theprotocol.it/filtry/krakow;wp"),
    ("useme", {"sort": "newest"}, "https://useme.com/pl/jobs/?query=asystent&order_by=-published_on"),
])
def test_city_and_sort_urls(board, params, url):
    assert REGISTRY[board].page_url(Request(board, "t", "asystent", params), 1) == url
