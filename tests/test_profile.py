"""profile.json: presets, validation errors, countries, and the plan of requests it compiles to."""
import pytest

from neetscape import evaluate as ev
from neetscape import country, infer, planner, profile
from neetscape.model import CONTRACTS, UNKNOWN_DIMENSIONS


def validate(**raw):
    return profile.validate({"version": 2, "searches": [{"id": "a"}], **raw})


def plan(boards, *searches, **raw):
    return planner.plan(profile.validate({"version": 2, "boards": boards, "searches": list(searches), **raw}))


def test_presets_validate_and_combine():
    for name in profile.PRESETS:
        profile.validate(profile.preset(name))
    p = profile.validate(profile.combine(["focused", "side"]))
    assert [s.id for s in p.searches] == ["main", "side"] and p.rules
    assert p.search("side").keywords is None and "part_time" in p.search("side").worktime
    assert profile.combine(["broad"], "de")["country"] == "de"


def one(**search):
    return {"searches": [{"id": "a", **search}]}


@pytest.mark.parametrize("raw,msg", [
    ({"version": 1}, "version"),
    ({"searches": []}, "at least one"),
    ({"boards": ["monster"]}, "unknown boards"),
    ({"reveiw": {}}, "unknown key"),
    ({"defaults": {"max_age": 3}}, "unknown key"),
    ({"rank": {"tags": [{"pattern": "x"}]}}, "rank.tags"),
    ({"review": {"details_top": "many"}}, "details_top"),
    ({"country": "xx"}, "unknown country"),
    ({"blacklist": {"urls": ["("]}}, r"blacklist.urls\[0\]"),
    ({"blacklist": {"companies": ["x"], "action": "dorp"}}, "blacklist.action"),
    ({"searches": [{"id": "a"}, {"id": "a"}]}, "unique"),
    (one(what="x"), "what"),
    (one(title_include=["("]), "invalid regex"),
    (one(worktime=["sometimes"]), "unknown values"),
    (one(where={"remote": True, "country": "xx"}), "unknown country"),
    (one(where={"or_remote": True}), "where"),
    (one(titel_include=["x"]), "unknown key"),
    (one(pay={"min": 10, "max": 20}), "unknown key"),
    (one(where={"city": "Kraków", "radius": 10}), "unknown key"),
    (one(keywords_for={"justjoin": "n8n"}), "keywords_for"),
    (one(pay={"min": "8000"}), "pay.min"),
    (one(max_age_days="30"), "max_age_days"),
    (one(boost="high"), "boost"),
    (one(domains=["artificial_intelligence"]), r"domains: unknown values"),
    (one(functions_exclude=["sales"]), r"functions_exclude: unknown values"),       # a field, not a function
    (one(unknown="maybe"), r"unknown must be 'keep' or 'drop'"),
    (one(unknown={"salary": "drop"}), r"unknown: unknown key"),
    (one(unknown={"pay": "maybe"}), r"unknown.pay must be"),
    (one(unknown=["drop"]), "unknown"),
    ({"defaults": {"unknown": {"domian": "drop"}}}, r"defaults.unknown: unknown key"),
])
def test_profile_errors(raw, msg):
    with pytest.raises(profile.ProfileError, match=msg):
        validate(**raw)


@pytest.mark.parametrize("defaults,own,policy", [
    ("drop", None, {"default": "drop"}),
    ({"domain": "drop"}, None, {"default": "keep", "domain": "drop"}),
    ({"domain": "drop"}, "keep", {"default": "keep", "domain": "drop"}),       # a string sets the search's default
    ("drop", {"pay": "keep"}, {"default": "drop", "pay": "keep"}),
    ({"default": "drop", "pay": "keep"}, {"pay": "drop", "date": "keep"}, {"default": "drop", "pay": "drop", "date": "keep"}),
])
def test_unknown_policies_merge_per_dimension(defaults, own, policy):
    s = validate(defaults={"unknown": defaults}, **one(**({} if own is None else {"unknown": own}))).searches[0]
    assert {d: s.unknown_policy(d) for d in UNKNOWN_DIMENSIONS} == {d: policy.get(d, policy["default"]) for d in UNKNOWN_DIMENSIONS}


def test_contract_aliases_and_country():
    p = validate(**one(contracts=["uop", "b2b"]))
    assert p.searches[0].contracts == {"employment", "b2b"} and p.country.code == "pl" and p.currency == "PLN"
    de = validate(country="de", **one(contracts=["minijob", "employment"]))
    assert de.searches[0].contracts == {"mini_job", "employment"} and de.searches[0].where.country == "de"
    assert validate(blacklist={}).blacklist["action"] == "drop"
    anywhere = validate(**one(where="anywhere")).searches[0].where
    assert not anywhere.remote and not anywhere.city and anywhere.country == "pl"


def test_german_profile_pay_and_city():
    p = validate(country="de", **one(where={"city": "München"}, what="all", pay={"min": 15, "per": "hour"}))
    assert p.currency == "EUR" and p.fx["EUR"] == 1.0 and set(p.boards) == {"linkedin", "arbeitnow", "bundesagentur"}
    row = dict(board="arbeitnow", title="Kellner", company="", category="", skills="", pay_text="", snippet="",
               locations='["Munich"]', mode="onsite", worktime="part_time", contracts="", level="unknown",
               pay_min=2595, pay_max=2595, pay_period="", published=None, keywords="")
    assert ev.check(row, p.searches[0], hours_per_month=173)[0]           # Munich == München; 2595/173 = 15 €/h
    assert not ev.check({**row, "pay_max": 2400}, p.searches[0], hours_per_month=173)[0]


def test_schema_enums_match_the_registry():
    s = profile.schema()
    search = s["properties"]["searches"]["items"]["properties"]
    assert sorted(s["properties"]["country"]["enum"]) == sorted(search["where"]["oneOf"][1]["properties"]["country"]["enum"]) \
        == country.codes()
    assert search["contracts"]["items"]["enum"] == list(CONTRACTS) + ["uop"]
    for key in ("searches", "defaults"):   # both read $defs/search
        node = s["properties"][key]
        props = (node["items"] if key == "searches" else node)["properties"]
        assert props["domains"]["items"]["enum"] == list(infer.DOMAINS)
        assert props["functions"]["items"]["enum"] == props["functions_exclude"]["items"]["enum"] == list(infer.FUNCTIONS)
        assert list(props["unknown"]["oneOf"][1]["properties"]) == ["default", *UNKNOWN_DIMENSIONS]


def test_plan_pushdown_and_warnings():
    p = plan(["justjoin", "linkedin", "bulldogjob", "pracuj", "useme", "solidjobs"],
             {"id": "kw", "where": "remote", "what": ["n8n"]},
             {"id": "all", "where": "remote", "what": "all"},
             {"id": "krk", "where": {"city": "Kraków", "radius_km": 30}, "what": "all"})
    by = {(r.board, r.search_id): r for r in p.requests}
    assert by[("justjoin", "kw")].pushed == {"keyword", "remote"} and by[("justjoin", "kw")].params["sort"] == "newest"
    assert by[("linkedin", "kw")].pushed == {"keyword"}               # its remote filter is ignored by the API: checked locally
    assert by[("bulldogjob", "kw")].keyword is None                   # no keyword support: fetch all, filter locally
    assert ("pracuj", "all") in by and ("useme", "all") in by          # useme: its open projects are ~35 pages
    assert by[("linkedin", "krk")].params["city"] == "Kraków"
    assert ("solidjobs", "krk") in by or ("solidjobs", "kw") in by     # whole-board download serves any search
    assert ("useme", "krk") not in by                                 # remote-only board: no city search
    assert any("no city" in w for w in p.warnings)
    keys = [r.key for r in p.requests]
    assert len(keys) == len(set(keys))                                # identical requests are fetched once


def test_city_or_remote_fetches_both_listings():
    reqs = plan(["justjoin"], {"id": "x", "where": {"city": "Kraków", "radius_km": 20, "or_remote": True}, "what": "all"}).requests
    assert {frozenset(r.pushed) for r in reqs} == {frozenset({"city"}), frozenset({"remote"})}


def test_polish_profile_searching_germany():
    p = profile.validate({"version": 2, "searches": [{"id": "pl", "where": "remote", "what": ["python"]},
                                                     {"id": "de", "where": {"remote": True, "country": "de"}, "what": ["python"]}]})
    assert p.currency == "PLN" and "justjoin" in p.boards and "bundesagentur" in p.boards
    reqs = planner.plan(p).requests
    assert {r.board for r in reqs if r.search_id == "de"} == {"linkedin", "arbeitnow", "bundesagentur"}
    assert "bundesagentur" not in {r.board for r in reqs if r.search_id == "pl"}
    assert {r.params["country"] for r in reqs if r.board == "linkedin"} == {"pl", "de"}


def test_profile_from_init_answers():
    remote_it = profile.from_answers({"country": "pl", "where": "remote", "what": ["n8n", "helpdesk"],
                                      "domains": ["ai", "it"], "functions_exclude": ["sell", "market"],
                                      "worktime": "full", "contracts": ["employment", "b2b"], "pay_min": 9000,
                                      "levels_exclude": ["senior", "lead"], "max_age_days": 21})
    s = profile.validate(remote_it).searches[0]
    assert s.where.remote and not s.where.city and s.keywords == ("n8n", "helpdesk") and s.domains == {"ai", "it"}
    assert s.functions_exclude == {"sell", "market"} and s.worktime == {"full_time"} and s.pay_min == 9000
    assert s.pay_period == "month" and s.levels_exclude == {"senior", "lead"} and s.max_age_days == 21
    assert remote_it["review"]["mode"] == "listing"                    # from the broad preset

    local = profile.validate(profile.from_answers({"country": "de", "where": "city", "city": "München", "radius_km": 20,
                                                   "max_age_days": None}))
    s = local.searches[0]
    assert local.currency == "EUR" and s.where.city == "München" and s.where.radius_km == 20 and not s.where.remote
    assert s.keywords is None and s.max_age_days is None and not s.worktime and not s.contracts and s.pay_min is None

    side = profile.validate(profile.from_answers({"where": "both", "city": "Kraków", "worktime": "part",
                                                  "contracts": ["mandate", "freelance"], "pay_min": 40,
                                                  "pay_per": "hour"}))
    s = side.searches[0]
    assert side.country.code == country.DEFAULT_COUNTRY and s.where.remote and s.where.city == "Kraków"
    assert s.where.radius_km == 30 and s.worktime == {"part_time", "flexible"} and s.pay_period == "hour"
    assert s.max_age_days == 30                                         # the preset's default


@pytest.mark.parametrize("answers,msg", [({"where": "city"}, "needs a city"), ({"where": "moon"}, "where"),
                                         ({"worktime": "nights"}, "worktime"), ({"contracts": ["bogus"]}, "contracts"),
                                         ({"country": "xx"}, "unknown country")])
def test_profile_from_bad_init_answers(answers, msg):
    with pytest.raises(profile.ProfileError, match=msg):
        profile.from_answers(answers)
