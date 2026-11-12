"""nofluffjobs (search and posting APIs) on its recorded response tests/fixtures/pl/nofluffjobs.json."""
import json
import re
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request

FX = Path(__file__).parents[2] / "fixtures" / "pl" / "nofluffjobs.json"
NFJ = REGISTRY["nofluffjobs"]


def _posting(url, ref, city="Remote", salary=None, **kw):
    return {"id": url, "url": url, "reference": ref, "title": " Python Dev ", "name": "ACME", "category": "backend",
            "seniority": ["Mid"], "posted": 1794231934738, "renewed": 1794491134738,
            "location": {"places": [{"city": city, "url": url}], "fullyRemote": city == "Remote", "type": "remote" if city == "Remote" else "hybrid"},
            "salary": salary or {"from": 100.0, "to": 200.0, "type": "b2b", "currency": "PLN", "period": "Month"},
            "tiles": {"values": [{"type": "requirement", "value": "Python"}]}, **kw}


def raw_search(kw, params):
    return json.loads(NFJ.post_body(Request("nofluffjobs", "t", kw, params), 3))["rawSearch"]


def test_post_body_raw_search():
    assert json.loads(NFJ.post_body(Request("nofluffjobs", "t", None, {"remote": True}), 3)) == {"rawSearch": "remote", "page": 3}
    assert raw_search("python", {"remote": True}) == "remote keyword=python"
    assert raw_search("agent ai", {"remote": True}) == 'remote keyword="agent ai"'  # a phrase stays one criterion
    assert raw_search("python", {}) == "keyword=python"  # anywhere: no place criterion, not "remote"
    assert raw_search(None, {}) == ""
    assert raw_search("asystent", {"city": "Kraków"}) == "krakow keyword=asystent"
    assert raw_search("agent ai", {"city": "Kraków"}) == 'krakow keyword="agent ai"'


def test_page_urls():
    url = NFJ.page_url(Request("nofluffjobs", "t", None, {"remote": True}), 2)
    assert "pageFrom=2&pageTo=2" in url and url.startswith("https://nofluffjobs.com/api/search/posting?")
    assert NFJ.page_url(Request("nofluffjobs", "t", None), NFJ.caps.max_pages + 1) is None


def test_recorded_page_fields():
    offers = NFJ.parse(FX.read_text(), Request("nofluffjobs", "t", None))
    assert all(o.company and o.mode == "remote" and o.level != "unknown" and o.published and o.category for o in offers)
    assert sum(1 for o in offers if o.pay_text) >= 5 and all(o.contracts for o in offers if o.pay_text)
    assert len({o.pay_text for o in offers}) > 1  # each offer has its own pay, not the first one of the list
    assert all(o.key.startswith("https://nofluffjobs.com/pl/job/") and "?" not in o.key for o in offers)
    assert all(o.pay_text.endswith(" PLN/month") for o in offers if o.pay_text)  # API: salaryPeriod=month
    assert all(re.fullmatch(r"[a-z0-9_]+:\d+-\d+ [A-Z]{3}/(hour|day|month|year)", o.pay_text) for o in offers if o.pay_text)
    with pytest.raises(ValueError):
        NFJ.parse("", Request("nofluffjobs", "t", None))


def test_anywhere_page_keeps_one_entry_per_reference():
    page = {"postings": [_posting("dev-acme-remote", "R1"), _posting("dev-acme-masovian", "R1"),
                         _posting("dev-acme-krakow", "R2", city="Kraków"), _posting("dev-acme-warszawa", "R2", city="Warszawa")]}
    offers = NFJ.parse(json.dumps(page), Request("nofluffjobs", "t", "python", {}))
    assert [o.url for o in offers] == ["https://nofluffjobs.com/pl/job/dev-acme-remote", "https://nofluffjobs.com/pl/job/dev-acme-krakow"]
    assert offers[0].mode == "remote" and offers[1].mode == "hybrid" and offers[1].locations == ["Kraków"]
    assert offers[0].title == "Python Dev" and offers[0].level == "mid" and offers[0].skills == ["Python"]


def test_open_ended_salary_keeps_its_floor():
    page = {"postings": [_posting("a", "A", salary={"from": 4850.0, "type": "permanent", "currency": "PLN", "period": "Month",
                                                    "flexibleUpperBound": True}),
                         _posting("b", "B", salary={"type": "b2b", "period": "Month", "containsSalary": "NOT_PROVIDED"})]}
    a, b = NFJ.parse(json.dumps(page), Request("nofluffjobs", "t", None, {"remote": True}))
    assert a.pay_text == "permanent:4850-4850 PLN/month" and a.contracts == ["employment"]
    assert b.pay_text == "" and b.contracts == ["b2b"]


def test_posting_api_details():
    assert NFJ.posting_url("https://nofluffjobs.com/pl/job/dev-acme-krakow") == "https://nofluffjobs.com/api/posting/dev-acme-krakow"
    assert NFJ.posting_url("https://example.com/job/x") is None
    raw = {"posted": 1794221376916, "company": {"name": "ACME "},
           "details": {"description": "<p>About us</p>"},
           "requirements": {"description": "<ul><li>3 years of Python</li></ul>", "musts": [{"value": "Python"}],
                            "nices": [{"value": "Docker"}], "languages": [{"type": "MUST", "code": "en", "level": "B2"}]},
           "specs": {"dailyTasks": ["Write code"]}, "location": {"hybridDesc": "Hybrid 1 day Office / 4 days Remote"},
           "essentials": {"originalSalary": {"currency": "PLN", "types": {"b2b": {"period": "Day", "range": [1400.0, 1800.0]},
                                                                          "permanent": {"period": "Month", "range": [20000.0, 25000.0]}}}}}
    text, meta = NFJ.posting_text(json.dumps(raw))
    for part in ("About us", "3 years of Python", "Must have: Python", "Nice to have: Docker", "Languages: English B2 (required)",
                 "• Write code", "Work mode: Hybrid 1 day", "Contract: b2b 1400-1800 PLN/day", "Contract: permanent 20000-25000 PLN/month"):
        assert part in text, part
    assert meta == {"company": "ACME", "published": "2026-11-09"}
