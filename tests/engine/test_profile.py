"""test_profile.py"""
import pytest

from neetscape import profile


def test_presets_validate_and_combine():
    for name in profile.PRESETS:
        profile.validate(profile.preset(name))
    p = profile.validate(profile.combine(["focused", "side"]))
    assert [s.id for s in p.searches] == ["main", "side"] and p.rules
    assert p.search("side").keywords is None and "part_time" in p.search("side").worktime


@pytest.mark.parametrize("patch,msg", [
    ({"version": 1}, "version"),
    ({"searches": []}, "at least one"),
    ({"boards": ["monster"]}, "unknown boards"),
    ({"searches": [{"id": "a", "what": "x"}]}, "what"),
    ({"searches": [{"id": "a", "title_include": ["("]}]}, "invalid regex"),
    ({"searches": [{"id": "a", "worktime": ["sometimes"]}]}, "unknown values"),
    ({"searches": [{"id": "a"}, {"id": "a"}]}, "unique"),
])
def test_profile_errors(patch, msg):
    raw = {**profile.preset("broad"), **patch}
    with pytest.raises(profile.ProfileError, match=msg):
        profile.validate(raw)


def test_contract_aliases_and_country():
    p = profile.validate({"version": 2, "searches": [{"id": "a", "contracts": ["uop", "b2b"]}]})
    assert p.searches[0].contracts == {"employment", "b2b"} and p.country.code == "pl" and p.currency == "PLN"
    de = profile.validate({"version": 2, "country": "de", "searches": [{"id": "a", "contracts": ["minijob", "employment"]}]})
    assert de.searches[0].contracts == {"mini_job", "employment"} and de.searches[0].where.country == "de"
    assert profile.combine(["broad"], "de")["country"] == "de"


@pytest.mark.parametrize("patch,msg", [
    ({"country": "xx"}, "unknown country"),
    ({"searches": [{"id": "a", "where": {"remote": True, "country": "xx"}}]}, "unknown country"),
    ({"searches": [{"id": "a", "where": {"or_remote": True}}]}, "where"),
])
def test_country_errors(patch, msg):
    with pytest.raises(profile.ProfileError, match=msg):
        profile.validate({**profile.preset("broad"), **patch})


@pytest.mark.parametrize("search,msg", [
    ({"titel_include": ["x"]}, "unknown key"),
    ({"pay": {"min": 10, "max": 20}}, "unknown key"),
    ({"where": {"city": "Kraków", "radius": 10}}, "unknown key"),
    ({"keywords_for": {"justjoin": "n8n"}}, "keywords_for"),
    ({"pay": {"min": "8000"}}, "pay.min"),
    ({"max_age_days": "30"}, "max_age_days"),
    ({"boost": "high"}, "boost"),
])
def test_search_field_errors(search, msg):
    with pytest.raises(profile.ProfileError, match=msg):
        profile.validate({"version": 2, "searches": [{"id": "a", **search}]})


@pytest.mark.parametrize("patch,msg", [
    ({"reveiw": {}}, "unknown key"),
    ({"defaults": {"max_age": 3}}, "unknown key"),
    ({"rank": {"tags": [{"pattern": "x"}]}}, "rank.tags"),
    ({"review": {"details_top": "many"}}, "details_top"),
])
def test_profile_field_errors(patch, msg):
    with pytest.raises(profile.ProfileError, match=msg):
        profile.validate({"version": 2, "searches": [{"id": "a"}], **patch})
