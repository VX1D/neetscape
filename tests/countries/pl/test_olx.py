"""olx.pl (jobs) on its recorded listing-state extract tests/fixtures/pl/olx.json (output of `Olx.fetch_js`)."""
from pathlib import Path

from neetscape import profile
from neetscape.boards import REGISTRY
from neetscape.boards.base import Request
from neetscape.countries.pl.boards import olx

FX = Path(__file__).parents[2] / "fixtures" / "pl" / "olx.json"
OLX = REGISTRY["olx"]


def offers():
    return OLX.parse(FX.read_text(), Request("olx", "t", None))


def test_structured_fields():
    got = offers()
    assert len(got) == 14 and all(o.published and o.locations and o.contracts for o in got)
    assert any(o.promoted for o in got) and not all(o.promoted for o in got)
    assert all(o.description and o.snippet.startswith(o.title) for o in got)
    o = next(o for o in got if o.title.startswith("Content Creator – TikTok"))
    assert (o.mode, o.worktime, o.contracts, o.pay_text, o.locations) == (
        "remote", "part_time", ["mandate"], "salary:32-32 PLN/hour", ["Gdańsk, Śródmieście"])
    assert next(o for o in got if o.title.startswith("Asystent Klienta Drogerii")).company == "Rossmann SDP sp. z o.o."
    assert next(o for o in got if o.title.startswith("Osoby ds. obsługi")).pay_text == "salary:35-35 PLN/hour"  # from: 0
    assert OLX.parse("[]", Request("olx", "t", None)) == []


def test_work_mode_company_and_pay():
    assert olx.work_mode(["remote_work_possibility"]) == "remote"
    assert olx.work_mode(["remote_work_possibility", "traveling"]) == "remote"
    assert olx.work_mode(["hybrid", "remote_work_possibility"]) == "hybrid"
    assert olx.work_mode(["on_site", "remote_work_possibility"]) == "hybrid"
    assert olx.work_mode(["on_site"]) == "onsite" and olx.work_mode([]) == "unknown"
    assert olx.company({"company_name": "", "name": "Filip"}) == ""  # a recruiter's first name
    assert olx.company({"company_name": "", "name": "IGS SCHREINER POLSKA SP. Z O.O."}) == "IGS SCHREINER POLSKA SP. Z O.O."
    assert olx.pay_text(None) == "" and olx.pay_text({"from": 0, "to": 0}) == ""


def test_page_urls():
    r = Request("olx", "t", "asystent", {"remote": True, "part_time": True, "sort": "newest"})
    assert OLX.page_url(r, 2) == ("https://www.olx.pl/praca/q-asystent/?search%5Border%5D=created_at%3Adesc"
                                  "&search%5Bfilter_enum_workplace%5D%5B0%5D=remote_work_possibility"
                                  "&search%5Bfilter_enum_type%5D%5B0%5D=parttime&search%5Bfilter_enum_type%5D%5B1%5D=halftime&page=2")
    assert OLX.page_url(Request("olx", "t", "asystent", {"city": "Gdańsk", "radius_km": 0, "sort": "newest"}), 1) == (
        "https://www.olx.pl/praca/gdansk/q-asystent/?search%5Bdist%5D=0&search%5Border%5D=created_at%3Adesc")
    assert OLX.page_url(r, OLX.caps.max_pages + 1)  # never None: a request stopped at max_pages stays partial


def test_requests_remote_everything_but_not_whole_board():
    p = profile.validate({"version": 2, "boards": ["olx"], "searches": [
        {"id": "all", "where": "remote", "what": "all", "worktime": ["part_time"]},
        {"id": "any", "where": "anywhere", "what": "all"}]})
    by = {s.id: OLX.requests(s) for s in p.searches}
    (req,), _ = by["all"]
    assert req.keyword is None and req.params == {"remote": True, "sort": "newest", "part_time": True}
    assert req.pushed == {"remote", "worktime"}
    assert by["any"][0] == [] and "too large" in by["any"][1][0]
