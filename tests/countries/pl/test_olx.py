"""olx.pl (jobs) on its recorded listing-state extract tests/fixtures/pl/olx.json (output of `Olx.fetch_js`)."""

from neetscape import profile
from neetscape.boards import REGISTRY
from neetscape.boards.base import Request
from neetscape.countries.pl.boards import olx

OLX = REGISTRY["olx"]



def test_work_mode_company_and_pay():
    assert olx.work_mode(["remote_work_possibility"]) == "remote"
    assert olx.work_mode(["remote_work_possibility", "traveling"]) == "remote"
    assert olx.work_mode(["hybrid", "remote_work_possibility"]) == "hybrid"
    assert olx.work_mode(["on_site", "remote_work_possibility"]) == "hybrid"
    assert olx.work_mode(["on_site"]) == "onsite" and olx.work_mode([]) == "unknown"
    assert olx.company({"company_name": "", "name": "Filip"}) == ""  # a recruiter's first name
    assert olx.company({"company_name": "", "name": "IGS SCHREINER POLSKA SP. Z O.O."}) == "IGS SCHREINER POLSKA SP. Z O.O."
    assert olx.pay_text(None) == "" and olx.pay_text({"from": 0, "to": 0}) == ""


def test_requests_remote_everything_but_not_whole_board():
    p = profile.validate({"version": 2, "boards": ["olx"], "searches": [
        {"id": "all", "where": "remote", "what": "all", "worktime": ["part_time"]},
        {"id": "any", "where": "anywhere", "what": "all"}]})
    by = {s.id: OLX.requests(s) for s in p.searches}
    (req,), _ = by["all"]
    assert req.keyword is None and req.params == {"remote": True, "sort": "newest", "part_time": True}
    assert req.pushed == {"remote", "worktime"}
    assert by["any"][0] == [] and "too large" in by["any"][1][0]


def test_capped_listing_splits_into_the_page_categories():
    import json
    page = json.dumps({"total": 1000, "ads": [], "categories": [
        {"path": "praca", "parent": ""}, {"path": "praca/hr", "parent": "praca"},
        {"path": "praca/informatyka", "parent": "praca"}, {"path": "praca/informatyka/qa", "parent": "praca/informatyka"}]})
    r = Request("olx", "all", None, {"remote": True, "sort": "newest"})
    assert OLX.caps.result_cap == 1000 and OLX.total(page, r) == 1000
    subs = OLX.split(page, r)
    assert [s.params["category"] for s in subs] == ["hr", "informatyka"] and all(s.params["remote"] for s in subs)
    deeper = OLX.split(page, subs[1])                              # a capped subcategory splits again
    assert [s.params["category"] for s in deeper] == ["informatyka/qa"]
    assert OLX.page_url(subs[0], 2).startswith("https://www.olx.pl/praca/hr/?")
    city = OLX.page_url(Request("olx", "c", None, {"city": "Kraków", "radius_km": 30, "category": "hr"}), 1)
    assert city.startswith("https://www.olx.pl/praca/hr/krakow/?")
    assert OLX.parse(json.dumps([]), r) == [] and OLX.total("[]", r) is None   # older shrunk pages: a bare list
