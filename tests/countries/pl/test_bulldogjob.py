"""bulldogjob.pl (GraphQL search API) on its recorded response tests/fixtures/pl/bulldogjob.json."""
import json
import re
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request

FX = Path(__file__).parents[2] / "fixtures" / "pl" / "bulldogjob.json"
B = REGISTRY["bulldogjob"]


def parse(raw=None):
    return B.parse(FX.read_text() if raw is None else raw, Request("bulldogjob", "t", None))


def test_post_body_filters_order_and_pages():
    r = Request("bulldogjob", "t", None, {"remote": True, "part_time": True, "sort": "newest"})
    v = json.loads(B.post_body(r, 3))["variables"]
    assert v["filters"] == {"city": ["Remote"], "employmentType": ["part_time", "freelance"]}
    assert v["order"] == {"field": "PUBLISHED", "direction": "DESC"} and v["page"] == 3 and v["perPage"] == 50
    city = json.loads(B.post_body(Request("bulldogjob", "t", None, {"city": "Kraków"}), 1))["variables"]
    assert city["filters"] == {"city": ["Kraków"]} and "order" not in city


def test_page_urls():
    r = Request("bulldogjob", "t", None, {"remote": True, "part_time": True, "sort": "newest"})
    assert B.page_url(r, 2) == "https://bulldogjob.pl/graphql?city=Remote&part_time=1&page=2"
    assert B.page_url(Request("bulldogjob", "t", None, {"remote": True}), 2) == "https://bulldogjob.pl/graphql?city=Remote&page=2"
    assert B.page_url(Request("bulldogjob", "t", "asystent", {"city": "Kraków"}), 1) == "https://bulldogjob.pl/graphql?city=Krak%C3%B3w&page=1"
    assert B.page_url(r, B.caps.max_pages + 1) is None


def test_fields_from_the_api():
    offers = parse()
    assert len(offers) == 15 and all(o.published and o.category and o.mode == "remote" for o in offers)
    assert all(o.company and o.level != "unknown" for o in offers)
    assert all(re.fullmatch(r"https://bulldogjob\.pl/companies/jobs/\d+-[^/?#]+", o.key) for o in offers)
    assert all(o.pay_text.endswith((" PLN", " EUR")) for o in offers if o.pay_text) and sum(bool(o.pay_text) for o in offers) >= 7
    assert all(o.contracts for o in offers if o.pay_text)
    nodes = json.loads(FX.read_text())["data"]["searchJobs"]["nodes"]
    multi = next(n for n in nodes if len(n["locations"]) > 1)
    o = next(o for o in offers if o.key.endswith(multi["id"]))
    assert o.locations == sorted({x["location"]["cityPl"] for x in multi["locations"]})


def test_modes_and_worktime():
    node = json.loads(FX.read_text())["data"]["searchJobs"]["nodes"][0]
    one = lambda **kw: parse(json.dumps({"data": {"searchJobs": {"nodes": [dict(node, **kw)]}}}))[0]
    assert one(workModes=["on-site", "hybrid"], remote=False).mode == "hybrid"
    assert one(workModes=["on-site"], remote=False).mode == "onsite"
    assert one(workModes=["on-site", "full-remote"]).mode == "remote"
    assert one(employmentType="freelance").worktime == "flexible" and one(employmentType="contractor").worktime == "unknown"


def test_errors_raise():
    with pytest.raises(ValueError):
        parse(json.dumps({"errors": [{"message": "x"}]}))
    with pytest.raises(ValueError):
        parse("")
