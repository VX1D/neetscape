"""Filters: one stored offer row against one search (`evaluate.check`), the blacklist, and explanations."""
import datetime as dt

import pytest

from conftest import crawl, search
from neetscape import evaluate as ev
from neetscape import profile

TODAY = dt.date.today()


def row(**kw):
    return dict(board="fake", title="AI Automation Specialist", company="Acme", category="", skills="", pay_text="",
                snippet="", locations="[]", mode="remote", worktime="full_time", contracts="b2b", level="mid", pay_min=None,
                pay_max=None, pay_period="", published=TODAY.isoformat(), keywords="") | kw


def reasons(offer, **s):
    """[] when the offer passes the search, else the rejection reasons."""
    ok, why = ev.check(row(**offer), search(**s))
    return [] if ok else why


@pytest.mark.parametrize("s,offer,ok", [
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
    (dict(max_age_days=7), dict(published="2024-1-5"), True),          # a malformed date is unknown
    (dict(title_include=["automat"]), dict(title="Accountant"), False),
    (dict(title_exclude=["senior"]), dict(title="Senior AI"), False),
    (dict(text_exclude=["call center"]), dict(snippet="call center 24/7"), False),
    (dict(text_exclude=["niemiecki"]), dict(posting="Wymagany język niemiecki B2"), False),   # the fetched posting too
    (dict(text_exclude=["timeout"]), dict(posting="ERROR TimeoutError: page did not load"), True),  # a failed fetch is no text
    (dict(where="remote", remote_proof=True, unknown="drop"), dict(), False),   # no posting yet: remote proof unknown
    (dict(fields=["ai_automation", "it_support"]), dict(job_field="ai_automation"), True),
    (dict(fields=["ai_automation"]), dict(job_field="hr"), False),
    (dict(fields_exclude=["sales", "hr"]), dict(job_field="sales"), False),
    (dict(fields_exclude=["hr"]), dict(), True),                       # no field stored: "other"
])
def test_check_each_dimension(s, offer, ok):
    assert ev.check(row(**offer), search(**s))[0] is ok


@pytest.mark.parametrize("s,offer", [
    (dict(worktime=["part_time"]), dict(worktime="unknown", contracts="b2b")),   # contracts cannot satisfy a worktime-only search
    (dict(contracts=["b2b"]), dict(worktime="full_time", contracts="")),          # worktime is irrelevant to a contract-only search
    (dict(worktime=["part_time"], contracts=["mandate"]), dict(worktime="full_time", contracts="")),  # a contract may still fit
])
def test_worktime_contract_unknown_follows_policy(s, offer):
    assert reasons(offer, **s) == []
    assert reasons(offer, unknown="drop", **s) == ["work time unknown"]


AI_PO = dict(job_field="product_project", job_domains="ai,product", job_function="manage_project")
NOTHING = dict(job_field="other", job_domains="", job_function="unknown")   # the title and category say nothing


@pytest.mark.parametrize("s,offer,why", [
    (dict(domains=["ai", "it"]), AI_PO, []),                                   # any of the offer's domains
    (dict(domains=["it", "data"]), AI_PO, ["domain ai,product"]),
    (dict(functions=["manage_project"]), AI_PO, []),
    (dict(functions=["develop"]), AI_PO, ["function manage_project"]),
    (dict(functions_exclude=["sell", "manage_project"]), AI_PO, ["function manage_project"]),
    (dict(domains=["ai"], functions_exclude=["sell"]), AI_PO | dict(job_function="sell"), ["function sell"]),
    (dict(fields=["ai_automation"]), AI_PO, ["field product_project"]),
    # no value: unknown to an include filter, untouched by an exclude filter
    (dict(domains=["ai"]), NOTHING, []),
    (dict(domains=["ai"], unknown="drop"), NOTHING, ["domain unknown"]),
    (dict(functions=["develop"], unknown="drop"), NOTHING, ["function unknown"]),
    (dict(fields=["ai_automation"]), NOTHING, []),
    (dict(fields=["ai_automation"], unknown="drop"), NOTHING, ["field unknown"]),
    (dict(fields_exclude=["sales"], functions_exclude=["sell"], unknown="drop"), NOTHING, []),
])
def test_job_filters(s, offer, why):
    assert reasons(offer, **s) == why


def test_unknown_policy_per_dimension():
    offer = NOTHING | dict(mode="unknown")
    s = dict(where="remote", domains=["ai"], pay={"min": 8000})
    assert reasons(offer, unknown={"domain": "drop"}, **s) == ["domain unknown"]
    assert reasons(offer, unknown={"default": "drop", "domain": "keep"}, **s) == ["mode unknown", "pay unknown"]
    assert reasons(offer, unknown={"default": "drop", "remote_proof": "keep"}, remote_proof=True, **s) == [
        "mode unknown", "domain unknown", "pay unknown"]                       # no posting: proof kept
    assert reasons(dict(worktime="unknown"), worktime=["part_time"], unknown={"worktime": "drop"}) == ["work time unknown"]


def test_unknown_location_dropped_once():
    assert reasons(dict(mode="onsite"), where={"city": "Kraków"}, unknown="drop") == ["location unknown"]


def test_city_search_trusts_the_boards_radius_filter():
    city = dict(where={"city": "Andrychów", "radius_km": 30})
    bielsko = dict(mode="onsite", locations='["Bielsko-Biała"]')
    assert reasons(bielsko, **city) == ["not in Andrychów"]                              # by name alone: out
    assert reasons(bielsko | {"areas": "olx|Andrychów|30"}, **city) == []                # the board placed it within 30 km
    assert reasons(bielsko | {"areas": "olx|Andrychów|50"}, **city) == ["not in Andrychów"]   # a wider radius
    assert reasons(bielsko | {"areas": "olx|Kraków|30"}, **city) == ["not in Andrychów"]      # another city
    warsaw = dict(mode="onsite", locations='["Warszawa"]', areas="theprotocol|Andrychów|30,linkedin|Andrychów|30")
    assert reasons(warsaw, **city) == ["not in Andrychów"]       # boards without a verified radius are no evidence


@pytest.mark.parametrize("posting,why", [
    (None, []),                                                                  # no posting yet: unknown, kept
    ("Praca w 100% zdalna, z dowolnego miejsca w Polsce.", []),
    ("Pracujesz w trybie zdalnym, w zespole.", []),                              # remote wording, no presence
    ("Biuro w centrum, pakiet medyczny.", ["posting does not mention remote work"]),
    ("Pracujemy w systemie hybrydowym lub w 100% zdalnie.", []),                 # remote is one of the options
    ("Praca zdalna. Praca hybrydowa: 1 dzień w tygodniu w biurze (Warszawa).", ["posting requires presence: hybrydowa"]),
    ("100% zdalnie, spotkania u klientów raz w miesiącu.", ["posting requires presence: spotkania u klient"]),
])
def test_remote_proof_reads_the_posting(posting, why):
    offer = {"posting": posting} if posting else {}
    got = reasons(offer, where="remote", remote_proof=True)
    assert len(got) == len(why) and all(g.startswith(w) for g, w in zip(got, why))
    assert reasons(offer, where="remote") == []                                  # only when asked for


def test_blacklist_drops_or_flags(fake, db):
    fake.pages = {("*", 1): [["a", "Asystent biurowy", {"company": "Szybka Kasa"}], ["b", "Helpdesk", {"company": "Acme"}],
                             ["c", "Praca z domu", {"snippet": "brak górnego limitu zarobków"}]]}
    rid = crawl(db)

    def evaluate(action):
        p = profile.validate({"version": 2, "boards": ["fake"], "searches": [{"id": "all", "what": "all"}],
                              "blacklist": {"companies": ["szybka kasa"], "text": ["limitu zarobków"], "action": action}})
        ev.evaluate(db, p, rid)
        return p

    p = evaluate("drop")
    assert [r["title"] for r in db.q("SELECT o.title FROM evals e JOIN offers o ON o.id = e.offer_id")] == ["Helpdesk"]
    reasons_ = {r["reasons"] for r in db.q("SELECT reasons FROM rejections WHERE run_id=?", rid)}
    assert reasons_ == {"blacklisted company /szybka kasa/", "blacklisted text /limitu zarobków/"}
    assert ev.explain(db, p, db.offer("https://fake/a")["id"], rid) == {"all": ["blacklisted company /szybka kasa/"]}
    evaluate("flag")
    flagged = db.q("SELECT e.why FROM evals e JOIN offers o ON o.id = e.offer_id WHERE o.key = 'a'")[0]["why"]
    assert "!blacklist" in flagged and db.q("SELECT COUNT(*) n FROM evals WHERE run_id=?", rid)[0]["n"] == 3


def test_explain_an_offer_never_sighted(db):
    db.db.execute("INSERT INTO offers(board, key, url, title) VALUES ('x', '1', 'https://x/1', 'Job')")
    p = profile.validate({"version": 2, "searches": [{"id": "x"}], "blacklist": {"companies": ["x"], "action": "flag"}})
    assert ev.explain(db, p, 1) == {} and ev.flagged(db, p, 1) == []
