"""test_planner.py"""
from neetscape import planner, profile


def test_planner_pushdown_and_warnings():
    raw = {"version": 2, "boards": ["justjoin", "linkedin", "theprotocol", "pracuj", "useme", "solidjobs"], "searches": [
        {"id": "kw", "where": "remote", "what": ["n8n"]},
        {"id": "all", "where": "remote", "what": "all"},
        {"id": "krk", "where": {"city": "Kraków", "radius_km": 30}, "what": "all"}]}
    p = planner.plan(profile.validate(raw))
    by = {(r.board, r.search_id): r for r in p.requests}
    assert by[("justjoin", "kw")].pushed == {"keyword", "remote"} and by[("justjoin", "kw")].params["sort"] == "newest"
    assert by[("linkedin", "kw")].pushed == {"keyword"}               # its remote filter is ignored by the API: checked locally
    assert by[("theprotocol", "kw")].keyword is None                  # no keyword support: fetch all, filter locally
    assert ("pracuj", "all") in by and ("useme", "all") not in by      # useme: too large without keywords
    assert by[("linkedin", "krk")].params["city"] == "Kraków"
    assert ("solidjobs", "krk") in by or ("solidjobs", "kw") in by     # whole-board download serves any search
    assert ("useme", "krk") not in by                                 # remote-only board: no city search
    assert any("too large" in w for w in p.warnings) and any("no city" in w for w in p.warnings)
    keys = [r.key for r in p.requests]
    assert len(keys) == len(set(keys))                                # identical requests are fetched once


def test_city_or_remote_fetches_both_listings():
    raw = {"version": 2, "boards": ["justjoin"], "searches": [
        {"id": "x", "where": {"city": "Kraków", "radius_km": 20, "or_remote": True}, "what": "all"}]}
    reqs = planner.plan(profile.validate(raw)).requests
    assert {frozenset(r.pushed) for r in reqs} == {frozenset({"city"}), frozenset({"remote"})}
