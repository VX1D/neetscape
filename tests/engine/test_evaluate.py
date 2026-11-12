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
