"""solid.jobs (one JSON document per division) on its recorded division tests/fixtures/pl/solidjobs.json."""
import json
from pathlib import Path

from neetscape import planner, profile
from neetscape.boards import REGISTRY
from neetscape.boards.base import Request

FX = Path(__file__).parents[2] / "fixtures" / "pl" / "solidjobs.json"
SJ = REGISTRY["solidjobs"]


def _offer(i, primary, secondary=None, workload="100%", remote="Hybrydowo"):
    return {"id": i, "jobOfferUrl": f"acme-{i}", "jobTitle": "Dev", "companyName": "ACME", "companyCity": "Kraków",
            "remotePossible": remote, "workload": workload, "experienceLevel": "Regular", "mainCategory": "Programista",
            "subCategory": "Python", "validFrom": "2026-10-12T15:52:04+02:00", "requiredSkills": [{"name": "Python"}],
            "salaryRange": primary, "secondarySalaryRange": secondary}


def _range(kind, lo, hi):
    return {"lowerBound": lo, "upperBound": hi, "currency": "PLN", "employmentType": kind, "salaryPeriod": "Month"}


def test_recorded_division_fields():
    offers = SJ.parse(FX.read_text(), Request("solidjobs", "t", None, {"division": "it"}))
    assert all(o.pay_text and o.mode in ("remote", "hybrid", "onsite") for o in offers)


def test_every_division_is_fetched():
    p = planner.plan(profile.validate({"version": 2, "boards": ["solidjobs"], "searches": [{"id": "r", "where": "remote", "what": "all"}]}))
    assert sorted(r.params["division"] for r in p.requests) == sorted(SJ.divisions) and len(SJ.divisions) == 8


def test_both_pay_ranges_and_contracts():
    a, b, c, d = SJ.parse(json.dumps([
        _offer(1, _range("B2B", 28600.0, 35300.0), _range("Umowa o pracę", 20000.0, 26000.0)),
        _offer(2, _range("Umowa o staż", 3000.0, 4000.0), workload="50%", remote="Możliwa częściowo"),
        _offer(3, _range("Umowa o dzieło", 5000.0, 6000.0), workload="Praca projektowa", remote="Stacjonarnie lub zdalnie"),
        _offer(4, _range("Umowa zlecenie", 0, 0), workload="75%", remote="Brak")]), Request("solidjobs", "t", None, {"division": "it"}))
    assert a.pay_text == "b2b:28600-35300 PLN/month; permanent:20000-26000 PLN/month gross" and a.contracts == ["b2b", "employment"]
    assert (a.mode, a.worktime, a.level, str(a.published)) == ("hybrid", "full_time", "mid", "2026-10-12")
    assert (b.contracts, b.worktime, b.mode) == (["internship"], "part_time", "hybrid")
    assert (c.contracts, c.worktime, c.mode) == (["specific_task"], "flexible", "remote")
    assert (d.contracts, d.pay_text, d.worktime, d.mode) == (["mandate"], "", "part_time", "onsite")
