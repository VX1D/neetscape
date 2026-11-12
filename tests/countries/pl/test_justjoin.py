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


def test_extract_offers_handles_escapes_and_truncation():
    offers = [{"slug": "a-b", "title": 'Quote " and ] bracket'}, {"slug": "c", "title": "x"}]
    assert extract_offers(_rsc_chunk(offers)) == offers
    assert extract_offers("") == []
    assert extract_offers('{\\"offers\\":[{\\"slug\\":\\"a') is None
    with pytest.raises(ValueError):
        REGISTRY["justjoin"].parse('{\\"offers\\":[{\\"slug\\":\\"a', Request("justjoin", "t", None))


@pytest.mark.parametrize("board", ["justjoin", "rocketjobs"])
def test_capped_listing_splits_by_level_then_category(board):
    b, raw = REGISTRY[board], (FX / f"{board}.txt").read_text()
    assert b.caps.result_cap == 10_000 and b.caps.max_pages == 200  # 200 pages of 50, page 201 is a 404
    r = Request(board, "t", None, {"sort": "newest"})
    assert b.total(raw, r) >= b.caps.result_cap  # the page's count (an upper bound of the results)
    levels = b.split(raw, r)
    assert len(levels) == 6 and all(s.params["sort"] == "newest" and s.params["level"] for s in levels)
    cats = b.split(raw, levels[2])
    assert len(cats) == 24 and {s.params["level"] for s in cats} == {levels[2].params["level"]}
    assert b.split(raw, cats[0]) == []  # level and category set: cannot be narrowed further
    assert b.total(parse_raw_chunk(), r) is None  # an older recording (the offers slice alone) has no count


def parse_raw_chunk():
    return json.dumps({"offers": []}, separators=(",", ":")).replace('"', '\\"')


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
