"""German boards and a German profile end to end (offline)."""
import json
from pathlib import Path

from neetscape import evaluate as ev
from neetscape import planner, profile
from neetscape.boards import REGISTRY
from neetscape.boards.base import Request

FX = Path(__file__).parent.parent / "fixtures" / "de"


def parse(board, name):
    return {o.key: o for o in REGISTRY[board].parse((FX / name).read_text(), Request(board, "t", None))}


def test_bundesagentur_fields():
    offers = parse("bundesagentur", "bundesagentur.json")
    o = offers["17220-WDH3KQ2ZMYSS4JKE-S"]  # Finanzbuchhalter, mini job, home office by arrangement
    assert (o.mode, o.worktime, o.contracts) == ("hybrid", "part_time", ["mini_job"])
    assert o.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/17220-WDH3KQ2ZMYSS4JKE-S"
    paid = [o for o in offers.values() if o.pay_text]
    assert paid and all(p.pay_text.endswith("EUR/Jahr") for p in paid)
    assert any(o.contracts == ["internship"] and o.level == "intern" for o in offers.values())
    assert all(o.published and o.company and o.locations for o in offers.values())


def test_bundesagentur_requests():
    p = profile.validate({"version": 2, "country": "de", "boards": ["bundesagentur"], "searches": [
        {"id": "r", "where": "remote", "what": "all", "max_age_days": 10},
        {"id": "c", "where": {"city": "Köln", "radius_km": 20}, "what": ["Kundenservice"], "worktime": ["part_time"]},
        {"id": "a", "where": "anywhere", "what": "all"}]})
    pl = planner.plan(p)
    by = {r.search_id: r for r in pl.requests}
    b = REGISTRY["bundesagentur"]
    assert "was=Homeoffice" in b.page_url(by["r"], 1) and "veroeffentlichtseit=14" in b.page_url(by["r"], 1)
    url = b.page_url(by["c"], 2)
    assert "wo=K%C3%B6ln" in url and "umkreis=20" in url and "arbeitszeit=tz%3Bmj" in url and "page=2" in url
    assert "Homeoffice" not in url and "a" not in by and any("too large" in w for w in pl.warnings)


def test_arbeitnow_fields():
    offers = list(parse("arbeitnow", "arbeitnow.json").values())
    assert sum(o.mode == "remote" for o in offers) == 5
    assert all(o.description and o.published for o in offers)
    assert any("employment" in o.contracts for o in offers)
    assert REGISTRY["arbeitnow"].page_url(Request("arbeitnow", "t", None), 2).endswith("?page=2")


def test_german_profile_pay_and_city():
    p = profile.validate({"version": 2, "country": "de", "searches": [
        {"id": "m", "where": {"city": "München"}, "what": "all", "pay": {"min": 15, "per": "hour"}}]})
    assert p.currency == "EUR" and p.fx["EUR"] == 1.0 and set(p.boards) == {"linkedin", "arbeitnow", "bundesagentur"}
    s = p.searches[0]
    row = dict(board="arbeitnow", title="Kellner", company="", category="", skills="", pay_text="", snippet="",
               locations=json.dumps(["Munich"]), mode="onsite", worktime="part_time", contracts="", level="unknown",
               pay_min=2595, pay_max=2595, pay_period="", published=None, keywords="")
    assert ev.check(row, s, hours_per_month=173)[0]           # Munich == München; 2595/173 = 15 €/h
    assert not ev.check({**row, "pay_max": 2400}, s, hours_per_month=173)[0]


def test_polish_profile_searching_germany():
    p = profile.validate({"version": 2, "searches": [
        {"id": "pl", "where": "remote", "what": ["python"]},
        {"id": "de", "where": {"remote": True, "country": "de"}, "what": ["python"]}]})
    assert p.currency == "PLN" and "justjoin" in p.boards and "bundesagentur" in p.boards
    reqs = planner.plan(p).requests
    assert {r.board for r in reqs if r.search_id == "de"} == {"linkedin", "arbeitnow", "bundesagentur"}
    assert "bundesagentur" not in {r.board for r in reqs if r.search_id == "pl"}
    assert {r.params["country"] for r in reqs if r.board == "linkedin"} == {"pl", "de"}
