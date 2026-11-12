"""test_report.py"""
from neetscape import evaluate as ev
from neetscape import profile, report
from neetscape.model import Offer
from neetscape.store import Store

PROFILE = profile.validate({"version": 2, "boards": ["justjoin"], "searches": [{"id": "all", "where": "remote", "what": "all"}]})


def _seen(db, run_id, offers):
    req = db.start_request(run_id, "x", "all", None, {}, ())
    db.ingest(offers, run_id, req, 1)


def _job(board, key, title="AI Automation Specialist", company="Acme", mode="remote", **kw):
    return Offer(board=board, key=key, url=f"https://{board}/{key}", title=title, company=company, mode=mode, **kw)


def test_hidden_mark_hides_the_whole_cluster(tmp_path):
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    _seen(db, rid, [_job("justjoin", "1"), _job("pracuj", "2")])
    ev.evaluate(db, PROFILE, rid)
    db.mark("https://pracuj/2", "rejected")
    assert report.listing(db, PROFILE, rid) == []


def test_mark_on_another_board_of_the_cluster_is_shown(tmp_path):
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    _seen(db, rid, [_job("justjoin", "1", pay_text="x", pay_min=1, pay_max=20000), _job("pracuj", "2")])
    ev.evaluate(db, PROFILE, rid)
    db.mark("https://pracuj/2", "applied")
    assert [d["mark"] for d in report.listing(db, PROFILE, rid)] == ["applied"]


def test_boards_of_an_older_run(tmp_path):
    db = Store(tmp_path / "j.db")
    r1 = db.start_run({}, [])
    _seen(db, r1, [_job("justjoin", "1"), _job("pracuj", "2")])
    ev.evaluate(db, PROFILE, r1)
    r2 = db.start_run({}, [])
    _seen(db, r2, [_job("justjoin", "1"), _job("pracuj", "2")])
    assert sorted(report.listing(db, PROFILE, r1)[0]["boards"].split(",")) == ["justjoin", "pracuj"]


def test_group_by_title(tmp_path):
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    _seen(db, rid, [_job("justjoin", "1", title="Customer Support Agent", company="A"),
                    _job("pracuj", "2", title="Customer support agent!", company="B"),
                    _job("pracuj", "3", title="Customer Support Agent", company="A"),   # same job as 1
                    _job("justjoin", "4", title="Accountant", company="C")])
    ev.evaluate(db, PROFILE, rid)
    groups = report.group_by_title(report.listing(db, PROFILE, rid))
    assert [(g["title"], g["offers"], g["companies"], g["boards"]) for g in groups] == [
        ("Customer Support Agent", 2, 2, "justjoin,pracuj"), ("Accountant", 1, 1, "justjoin")]
    out = report.format_groups(groups, "tsv").splitlines()
    assert out[0].split("\t")[:4] == ["title", "offers", "companies", "boards"] and len(out) == 3


def test_rejections_are_stored_with_reasons(tmp_path):
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    _seen(db, rid, [_job("justjoin", "1"), _job("justjoin", "2", title="Senior Accountant", mode="onsite")])
    ev.evaluate(db, PROFILE, rid)
    rows = db.q("SELECT o.key, r.search_id, r.reasons FROM rejections r JOIN offers o ON o.id = r.offer_id WHERE r.run_id=?", rid)
    assert [tuple(r) for r in rows] == [("2", "all", "mode onsite")]
    assert db.verdicts(rid, db.offer("https://justjoin/2")["id"]) == {"all": ["mode onsite"]}
    assert db.verdicts(rid, db.offer("https://justjoin/1")["id"])["all"] == []
