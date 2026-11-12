"""The listing (one row per job, marks, the current state of every board), title groups and the written reports."""
import json
import re

import pytest

from conftest import ingest, job
from neetscape import evaluate as ev
from neetscape import profile, report
from neetscape.store import PAGE_LIMIT, PAGE_LIMIT_ASKED

PROFILE = profile.validate({"version": 2, "boards": ["justjoin"], "searches": [{"id": "all", "where": "remote", "what": "all"}]})


def evaluated(db, *offers, **kw):
    rid = ingest(db, *offers, **kw)
    ev.evaluate(db, PROFILE, rid)
    return rid


def html_data(out, block="data"):
    page = (out / "REPORT.html").read_text()
    return page, json.loads(re.search(rf'<script type="application/json" id={block}>(.*?)</script>', page, re.S).group(1))


@pytest.mark.parametrize("status,marks", [("rejected", []), ("applied", ["applied"])])
def test_a_mark_applies_to_the_whole_cluster(db, status, marks):
    rid = evaluated(db, job("justjoin", "1", pay_text="x", pay_min=1, pay_max=20000), job("pracuj", "2"))
    db.mark("https://pracuj/2", status)                                  # marked on the other board of the job
    assert [d["mark"] for d in report.listing(db, PROFILE, rid)] == marks


def test_rejections_are_stored_with_reasons(db):
    rid = evaluated(db, job(key="1"), job(key="2", title="Senior Accountant", mode="onsite"))
    rows = db.q("SELECT o.key, r.search_id, r.reasons FROM rejections r JOIN offers o ON o.id = r.offer_id WHERE r.run_id=?", rid)
    assert [tuple(r) for r in rows] == [("2", "all", "mode onsite")]
    assert db.verdicts(rid, db.offer("https://justjoin/2")["id"]) == {"all": ["mode onsite"]}
    assert db.verdicts(rid, db.offer("https://justjoin/1")["id"])["all"] == []


def test_group_by_title(db):
    rid = evaluated(db, job("justjoin", "1", "Customer Support Agent", company="A"),
                    job("pracuj", "2", "Customer support agent!", company="B"),
                    job("pracuj", "3", "Customer Support Agent", company="A"),   # same job as 1
                    job("justjoin", "4", "Accountant", company="C"))
    groups = report.group_by_title(report.listing(db, PROFILE, rid))
    assert [(g["title"], g["offers"], g["companies"], g["boards"]) for g in groups] == [
        ("Customer Support Agent", 2, 2, "justjoin,pracuj"), ("Accountant", 1, 1, "justjoin")]
    out = report.format_groups(groups, "tsv").splitlines()
    assert out[0].split("\t")[:4] == ["title", "offers", "companies", "boards"] and len(out) == 3


def test_listing_is_the_current_state_of_every_board(db):
    """A run crawling one board keeps the other boards' offers (as of their latest crawl) in its listing."""
    r1 = ingest(db, job("justjoin", "1", "Support A"), board="justjoin", complete=True)
    ingest(db, job("pracuj", "2", "Support B"), job("pracuj", "3", "Support C"), run=r1, board="pracuj", complete=True)
    ev.evaluate(db, PROFILE, r1)
    r2 = db.start_run({}, ["run", "--boards", "pracuj"])
    ingest(db, job("pracuj", "2", "Support B"), job("pracuj", "4", "Support D"), run=r2, board="pracuj", complete=True)
    assert db.mark_gone(r2) == 1                                        # 3: the complete request no longer shows it
    assert db.unevaluated(r2) == 3
    ev.evaluate(db, PROFILE, r2)
    assert db.unevaluated(r2) == 0
    rows = report.listing(db, PROFILE, r2)
    assert {(d["title"], d["is_new"]) for d in rows} == {("Support A", 0), ("Support B", 0), ("Support D", 1)}
    assert [d["title"] for d in report.listing(db, PROFILE, r2, new_only=True)] == ["Support D"]
    assert {d["title"] for d in report.listing(db, PROFILE, r1)} == {"Support A", "Support B", "Support C"}  # run 1's state
    db.mark("https://justjoin/1", "applied")
    db.mark("https://pracuj/3", "applied")
    assert [m["listed"] for m in db.tracked(r2)] == ["yes", "gone"]


def test_boards_of_an_older_run(db):
    r1 = evaluated(db, job("justjoin", "1"), job("pracuj", "2"))
    ingest(db, job("justjoin", "1"), job("pracuj", "2"))
    assert sorted(report.listing(db, PROFILE, r1)[0]["boards"].split(",")) == ["justjoin", "pracuj"]


def test_html_report_data_is_inert(db, tmp_path):
    hostile = "AI <!--<script> x"   # in script data, "<!--<script>" would make the next </script> not close the block
    rid = evaluated(db, job(key="1", title=hostile, mode="remote"), job(key="2", url="javascript:alert(1)", title="Job"))
    db.mark("javascript:alert(1)", "shortlisted")
    report.write_reports(db, PROFILE, rid, tmp_path)
    page, data = html_data(tmp_path)
    block = re.search(r'<script type="application/json" id=data>(.*?)</script>', page, re.S).group(1)
    assert "<" not in block and {d["title"] for d in data} == {hostile, "Job"}
    assert next(d for d in data if d["title"] == "Job")["url"] == "" and 'href="javascript' not in page   # web URLs only


def finished(db, board, keyword, params, pages, found, stop):
    rid = db.start_run({}, [])
    db.finish_request(db.start_request(rid, board, "all", keyword, params, ()), pages, found, False, stop, "")
    return rid


def test_capped_requests_are_listed_in_the_report(db, tmp_path):
    rid = finished(db, "olx", None, {"category": "hr"}, 25, 1000, "page limit; capped: matches 1500, the board shows 1000")
    text = report.write_reports(db, PROFILE, rid, tmp_path).read_text()
    assert "Capped (offers beyond" in text and 'olx * {"category": "hr"}: matches 1500, the board shows 1000' in text
    assert "Page limit" not in text                                     # listed once, as capped


@pytest.mark.parametrize("stop,label,cut", [(PAGE_LIMIT, "the board's max_pages", 1),
                                            (PAGE_LIMIT_ASKED, "--limit-pages (deliberate)", 0)])
def test_page_limited_requests_are_listed_in_the_report(db, tmp_path, stop, label, cut):
    rid = finished(db, "linkedin", "n8n", {"country": "pl"}, 2, 50, stop)
    text = report.write_reports(db, PROFILE, rid, tmp_path).read_text()
    assert "Page limit (the listing may go on" in text and f'linkedin n8n {{"country": "pl"}}: 2 pages, {label}' in text
    assert html_data(tmp_path, "meta")[1]["cut"] == cut
