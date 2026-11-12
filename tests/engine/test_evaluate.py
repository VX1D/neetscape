"""test_evaluate.py"""
import datetime as dt

import pytest

from neetscape import evaluate as ev
from neetscape import profile

TODAY = dt.date.today()


def row(**kw):
    base = dict(board="fake", title="AI Automation Specialist", company="Acme", category="", skills="", pay_text="", snippet="",
                locations="[]", mode="remote", worktime="full_time", contracts="b2b", level="mid", pay_min=None, pay_max=None,
                pay_period="", published=TODAY.isoformat(), keywords="")
    base.update(kw)
    return base


class R(dict):  # sqlite3.Row-like
    def keys(self):
        return super().keys()


def s(**kw):
    raw = {"version": 2, "searches": [{"id": "x", **kw}]}
    return profile.validate(raw).searches[0]


@pytest.mark.parametrize("search,offer,ok", [
    (dict(where="remote"), dict(mode="hybrid"), False),
    (dict(where="remote"), dict(mode="unknown"), True),
    (dict(where="remote", unknown="drop"), dict(mode="unknown"), False),
    (dict(where={"city": "Kraków"}), dict(mode="onsite", locations='["Krakow, małopolskie"]'), True),
    (dict(where={"city": "Kraków"}), dict(mode="onsite", locations='["Warszawa"]'), False),
    (dict(where={"city": "Kraków", "or_remote": True}), dict(mode="remote", locations='["Warszawa"]'), True),
    (dict(what=["n8n"]), dict(), False),
    (dict(what=["n8n"]), dict(keywords="n8n"), True),                 # found by the board for this phrase
    (dict(what=["n8n"]), dict(skills="n8n, Python"), True),
    (dict(worktime=["part_time"], contracts=["mandate"]), dict(contracts="mandate"), True),
    (dict(worktime=["part_time"]), dict(worktime="full_time", contracts="uop"), False),
    (dict(levels_exclude=["senior"]), dict(level="senior"), False),
    (dict(pay={"min": 8000}), dict(pay_max=7000), False),
    (dict(pay={"min": 8000}), dict(), True),
    (dict(pay={"min": 8000, "required": True}), dict(), False),
    (dict(pay={"min": 40, "per": "hour"}), dict(pay_max=8400), True),   # 50/h
    (dict(pay={"min": 1000}), dict(pay_max=500, pay_period="project"), True),
    (dict(max_age_days=7), dict(published=(TODAY - dt.timedelta(days=30)).isoformat()), False),
    (dict(title_include=["automat"]), dict(title="Accountant"), False),
    (dict(title_exclude=["senior"]), dict(title="Senior AI"), False),
    (dict(text_exclude=["call center"]), dict(snippet="call center 24/7"), False),
])
def test_check_each_dimension(search, offer, ok):
    assert ev.check(R(row(**offer)), s(**search))[0] is ok


@pytest.mark.parametrize("search,offer", [
    (dict(worktime=["part_time"]), dict(worktime="unknown", contracts="b2b")),   # contracts cannot satisfy a worktime-only search
    (dict(contracts=["b2b"]), dict(worktime="full_time", contracts="")),          # worktime is irrelevant to a contract-only search
    (dict(worktime=["part_time"], contracts=["mandate"]), dict(worktime="full_time", contracts="")),  # a contract may still fit
])
def test_worktime_contract_unknown_follows_policy(search, offer):
    assert ev.check(R(row(**offer)), s(**search))[0] is True
    assert ev.check(R(row(**offer)), s(unknown="drop", **search))[1] == ["work time unknown"]


def test_unknown_location_dropped_once():
    assert ev.check(R(row(mode="onsite")), s(where={"city": "Kraków"}, unknown="drop"))[1] == ["location unknown"]


def test_malformed_published_date_is_unknown():
    assert ev.check(R(row(published="2024-1-5")), s(max_age_days=7)) == (True, [])


def test_profile_blacklist_drops_or_flags(fake, tmp_path):
    from conftest import ALL_REMOTE, run_crawl
    from neetscape.store import Store
    fake.pages = {("*", 1): [["a", "Asystent biurowy", {"company": "Szybka Kasa"}], ["b", "Helpdesk", {"company": "Acme"}],
                             ["c", "Praca z domu", {"snippet": "brak górnego limitu zarobków"}]]}
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    bl = {"companies": ["szybka kasa"], "text": ["limitu zarobków"]}

    def run(action):
        p = profile.validate({"version": 2, "boards": ["fake"], "searches": [{"id": "all", "what": "all"}],
                              "blacklist": {**bl, "action": action}})
        ev.evaluate(db, p, rid)
        return p

    p = run("drop")
    assert [r["title"] for r in db.run_offers(rid) if db.q("SELECT 1 FROM evals WHERE offer_id=?", r["id"])] == ["Helpdesk"]
    reasons = {r["reasons"] for r in db.q("SELECT reasons FROM rejections WHERE run_id=?", rid)}
    assert reasons == {"blacklisted company /szybka kasa/", "blacklisted text /limitu zarobków/"}
    assert ev.explain(db, p, db.offer("https://fake/a")["id"], rid) == {"all": ["blacklisted company /szybka kasa/"]}

    run("flag")
    flagged = db.q("SELECT e.why FROM evals e JOIN offers o ON o.id = e.offer_id WHERE o.key = 'a'")[0]["why"]
    assert "!blacklist" in flagged and db.q("SELECT COUNT(*) n FROM evals WHERE run_id=?", rid)[0]["n"] == 3


def test_blacklist_regex_errors_name_the_field():
    with pytest.raises(profile.ProfileError, match=r"blacklist.urls\[0\]"):
        profile.validate({"version": 2, "searches": [{"id": "x"}], "blacklist": {"urls": ["("]}})


def test_text_exclude_reads_the_posting_once_fetched():
    search = s(text_exclude=["niemiecki"])
    assert ev.check(R(row()), search)[0]
    assert ev.check(R(row(posting="Wymagany język niemiecki B2")), search)[1] == ["text excluded"]


def test_failed_posting_fetch_is_not_posting_text():
    search = s(text_exclude=["timeout"])
    assert ev.check(R(row(posting="ERROR TimeoutError: page did not load")), search) == (True, [])


def test_blacklist_action_is_checked():
    with pytest.raises(profile.ProfileError, match="blacklist.action"):
        profile.validate({"version": 2, "searches": [{"id": "x"}], "blacklist": {"companies": ["x"], "action": "dorp"}})
    assert profile.validate({"version": 2, "searches": [{"id": "x"}], "blacklist": {}}).blacklist["action"] == "drop"


def test_explain_an_offer_never_sighted(tmp_path):
    from neetscape.store import Store
    db = Store(tmp_path / "j.db")
    db.db.execute("INSERT INTO offers(board, key, url, title) VALUES ('x', '1', 'https://x/1', 'Job')")
    p = profile.validate({"version": 2, "searches": [{"id": "x"}], "blacklist": {"companies": ["x"], "action": "flag"}})
    assert ev.explain(db, p, 1) == {} and ev.flagged(db, p, 1) == []


def test_city_search_trusts_the_boards_radius_filter():
    search = s(where={"city": "Andrychów", "radius_km": 30})
    bielsko = row(mode="onsite", locations='["Bielsko-Biała"]')
    assert ev.check(R(bielsko), search)[1] == ["not in Andrychów"]                     # by name alone: out
    assert ev.check(R({**bielsko, "areas": "olx|Andrychów|30"}), search)[0]            # the board placed it within 30 km
    assert ev.check(R({**bielsko, "areas": "olx|Andrychów|50"}), search)[1] == ["not in Andrychów"]   # a wider radius
    assert ev.check(R({**bielsko, "areas": "olx|Kraków|30"}), search)[1] == ["not in Andrychów"]      # another city
    warsaw = row(mode="onsite", locations='["Warszawa"]', areas="theprotocol|Andrychów|30,linkedin|Andrychów|30")
    assert ev.check(R(warsaw), search)[1] == ["not in Andrychów"]   # boards without a verified radius are no evidence
