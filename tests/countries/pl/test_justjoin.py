"""justjoin.it and rocketjobs.pl (one engine) on their recorded pages tests/fixtures/pl/{justjoin,rocketjobs}.txt."""
import json
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request
from neetscape.countries.pl.boards.justjoin import category_from_slug, extract_offers

FX = Path(__file__).parents[2] / "fixtures" / "pl"


def recorded(board):
    return REGISTRY[board].parse((FX / f"{board}.txt").read_text(), Request(board, "t", None))


def _offer(slug, types, working="full_time"):
    return {"slug": slug, "title": "Dev", "companyName": "ACME", "workplaceType": "remote", "workingTime": working,
            "experienceLevel": "mid", "city": "Kraków", "multilocation": [{"city": "Kraków"}], "requiredSkills": ["Python"],
            "publishedAt": "2026-11-08T06:25:09Z", "lastPublishedAt": "2026-11-12T09:47:04Z", "employmentTypes": types}


def _types(kind, lo, hi, currency, unit="month", gross=False):
    original = {"from": lo, "to": hi, "currency": currency, "currencySource": "original", "type": kind, "unit": unit, "gross": gross}
    converted = {**original, "from": lo and lo * 4, "to": hi and hi * 4, "currency": "PLN" if currency != "PLN" else "EUR", "currencySource": "conversion"}
    return [original, converted]


def parse(board, offers):
    chunk = json.dumps({"offers": offers}, separators=(",", ":")).replace('"', '\\"')
    return REGISTRY[board].parse(chunk, Request(board, "t", None, {}))


def _rsc_chunk(offers):
    js = json.dumps({"offers": offers, "next": 1}, separators=(",", ":"))
    return js.replace("\\", "\\\\").replace('"', '\\"') + '\\",\\"other\\":[1,2]'


def test_recorded_pages_fill_rich_fields():
    assert all(o.company and o.mode != "unknown" and o.published and o.contracts and o.category for o in recorded("justjoin"))
    assert all(o.url.startswith("https://rocketjobs.pl/oferta-pracy/") for o in recorded("rocketjobs"))


def test_extract_offers_handles_escapes_and_truncation():
    offers = [{"slug": "a-b", "title": 'Quote " and ] bracket'}, {"slug": "c", "title": "x"}]
    assert extract_offers(_rsc_chunk(offers)) == offers
    assert extract_offers("") == []
    assert extract_offers('{\\"offers\\":[{\\"slug\\":\\"a') is None
    with pytest.raises(ValueError):
        REGISTRY["justjoin"].parse('{\\"offers\\":[{\\"slug\\":\\"a', Request("justjoin", "t", None))


def test_engine_urls():
    jj, rj = REGISTRY["justjoin"], REGISTRY["rocketjobs"]
    city = Request("x", "t", "python", {"city": "Kraków", "radius_km": 25, "part_time": True, "sort": "newest"})
    assert jj.page_url(city, 2) == ("https://justjoin.it/job-offers/krakow?keyword=python&radius=25"
                                    "&working-times=part-time,freelance&sortBy=newest&page=2")
    assert rj.page_url(city, 2) == ("https://rocketjobs.pl/oferty-pracy/krakow?keyword=python&radius=25"
                                    "&wymiar-godzin=niepelny-wymiar,freelance&sortBy=newest&strona=2")
    assert rj.page_url(Request("x", "t", None, {"remote": True}), 1) == "https://rocketjobs.pl/oferty-pracy/praca-zdalna?keyword="
    assert rj.page_url(Request("x", "t", None), 1) == "https://rocketjobs.pl/oferty-pracy/wszystkie-lokalizacje?keyword="
    assert jj.page_url(Request("x", "t", None), 151) is None


def test_category_from_slug():
    assert category_from_slug("transition-technologies-ms-dwh-analyst-warszawa-data-961e82d7", "Warszawa") == "data"
    assert category_from_slug("cloudatus-finance-controlling-specialist-lodz-finanse-ksiegowosc", "Łódź") == "finanse ksiegowosc"
    assert category_from_slug("x-y", "") == ""


def test_pay_in_original_currency_per_contract():
    eur, pln, anyc = parse("justjoin", [
        _offer("acme-dev-krakow-python", _types("b2b", 700, 800, "EUR")),
        _offer("acme-dev2-krakow-python", _types("b2b", 130, 170, "PLN", "hour") + _types("permanent", 15000, 17500, "PLN", gross=True)),
        _offer("acme-dev3-krakow-c", _types("any", None, None, "PLN"))])
    assert eur.pay_text == "b2b:700-800 EUR/month" and eur.contracts == ["b2b"]  # the PLN conversion is not the pay
    assert pln.pay_text == "b2b:130-170 PLN/hour; permanent:15000-17500 PLN/month gross"
    assert pln.contracts == ["b2b", "employment"]
    assert anyc.pay_text == "" and anyc.contracts == []  # "Any": no particular contract, not "other"
    assert str(eur.published) == "2026-11-08"  # publishedAt, what the offer page shows


def test_rocketjobs_internship_work_time():
    (o,) = parse("rocketjobs", [_offer("acme-staz-lodz-finanse", _types("internship", 3000, 4000, "PLN"), working="internship")])
    assert o.worktime == "part_time" and o.contracts == ["internship"] and o.url.startswith("https://rocketjobs.pl/oferta-pracy/")
