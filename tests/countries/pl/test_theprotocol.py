"""theprotocol.it on its recorded `__NEXT_DATA__` extract tests/fixtures/pl/theprotocol.json (output of `fetch_js`)."""
import json
import re
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request

FX = Path(__file__).parents[2] / "fixtures" / "pl" / "theprotocol.json"
B = REGISTRY["theprotocol"]


def parse(data=None, keyword=None):
    return B.parse(FX.read_text() if data is None else json.dumps(data), Request("theprotocol", "t", keyword))


def test_page_urls():
    r = Request("theprotocol", "t", "scrum master", {"remote": True, "sort": "newest"})
    assert B.page_url(r, 1) == "https://theprotocol.it/filtry/zdalna;rw?kw=scrum+master&sort=date"
    assert B.page_url(r, 2) == "https://theprotocol.it/filtry/zdalna;rw?kw=scrum+master&sort=date&pageNumber=2"
    assert B.page_url(Request("theprotocol", "t", None, {"remote": True}), 2) == "https://theprotocol.it/filtry/zdalna;rw?pageNumber=2"
    assert B.page_url(Request("theprotocol", "t", None, {"city": "Kraków"}), 1) == "https://theprotocol.it/filtry/krakow;wp"
    assert B.page_url(Request("theprotocol", "t", "asystent", {"city": "Kraków"}), 1) == "https://theprotocol.it/filtry/krakow;wp?kw=asystent"
    assert B.page_url(Request("theprotocol", "t", None, {"remote": True}), B.caps.max_pages + 1)  # never None
    assert B.caps.keywords and B.caps.sort_newest


def test_recorded_page_fields():
    offers = parse()
    assert all(o.company and o.mode == "remote" and o.level != "unknown" and o.published and o.locations for o in offers)
    assert sum(1 for o in offers if o.pay_text) >= 5 and all(o.contracts for o in offers if o.pay_text)
    assert all(re.fullmatch(r"https://theprotocol\.it/szczegoly/praca/[^?#]+,oferta,[0-9a-f-]+", o.key) for o in offers)
    assert any("; " in o.pay_text and len(o.contracts) > 1 for o in offers)  # one pay range per contract type
    assert any(" gross" in o.pay_text for o in offers)  # English "gross" kindName in the recorded page
    with pytest.raises(ValueError):
        B.parse("", Request("theprotocol", "t", None))


def test_contracts_and_gross_pay():
    data = json.loads(FX.read_text())
    offer = dict(data["offers"][0], contracts=[
        {"id": 6, "salary": {"from": 30, "to": 35, "currencySymbol": "zł", "timeUnit": {"longForm": "hourly"}, "kindName": "gross"}},
        {"id": 4, "salary": None}, {"id": 5, "salary": None}])
    o = parse(dict(data, offers=[offer]))[0]
    assert o.contracts == ["temp_agency", "employment", "other"]
    assert o.pay_text == "temp_agency:30-35 PLN/hour gross"


def test_offers_older_than_a_later_one_are_promoted():
    data = json.loads(FX.read_text())
    a, b, c = (dict(data["offers"][i]) for i in range(3))
    a["published"], b["published"], c["published"] = "2026-11-12T10:00:00", "2026-10-01T10:00:00", "2026-11-11T10:00:00"
    assert [o.promoted for o in parse(dict(data, offers=[a, b, c]))] == [False, True, False]


def test_throttled_keyword_answer_is_an_error():
    with pytest.raises(ValueError):
        parse({"total": 0, "page": {}, "keywords": [], "offers": []}, keyword="python")
    assert parse({"total": 0, "page": {}, "keywords": ["asystent"], "offers": []}, keyword="asystent") == []
