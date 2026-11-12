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


def _html_data(page):
    import json
    import re
    return json.loads(re.search(r'<script type="application/json" id=data>(.*?)</script>', page, re.S).group(1))


def test_html_report_embeds_data_and_review(tmp_path):
    import json
    import re
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    _seen(db, rid, [_job("justjoin", "1", title="AI </script><b>x</b>"), _job("justjoin", "2", title="Helpdesk", company="Beta")])
    ev.evaluate(db, PROFILE, rid)
    db.mark("https://justjoin/2", "shortlisted", note="why: <fits>\nrisk: none")
    report.write_reports(db, PROFILE, rid, tmp_path / "out")
    page = (tmp_path / "out" / "REPORT.html").read_text()
    data = json.loads(re.search(r'<script type="application/json" id=data>(.*?)</script>', page, re.S).group(1))
    assert {d["title"] for d in data} == {"AI </script><b>x</b>", "Helpdesk"}    # JSON survives a hostile title
    review = [d for d in data if d["mark"]]
    assert [(d["title"], d["mark"], d["note"], d["category"]) for d in review] == [
        ("Helpdesk", "shortlisted", "why: <fits>\nrisk: none", "why: <fits>")]  # first line of a multi-line note
    assert "<span data-t=review></span><span class=n>1</span>" in page and page.count("<script") == 3


def test_html_report_data_cannot_reshape_its_script_block(tmp_path):
    import json
    import re
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    hostile = "AI <!--<script> x"   # in script data, "<!--<script>" would make the next </script> not close the block
    _seen(db, rid, [_job("justjoin", "1", title=hostile)])
    ev.evaluate(db, PROFILE, rid)
    report.write_reports(db, PROFILE, rid, tmp_path / "out")
    page = (tmp_path / "out" / "REPORT.html").read_text()
    block = re.search(r'<script type="application/json" id=data>(.*?)</script>', page, re.S).group(1)
    assert "<" not in block and json.loads(block)[0]["title"] == hostile


def test_html_review_says_why_a_marked_posting_is_missing(tmp_path):
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    _seen(db, rid, [_job("justjoin", k, title=f"Job {k}", company=k) for k in "1234"])
    ev.evaluate(db, PROFILE, rid)
    db.save_detail(2, 200, "", {}, {})
    db.save_detail(3, 0, "ERROR TimeoutError: slow", {}, {})
    db.save_detail(4, 410, "", {}, {})
    for k in "1234":
        db.mark(f"https://justjoin/{k}", "shortlisted", note='a & b "quoted" <tag>')
    db.mark("https://elsewhere.example/job?a=1&b=2", "applied")
    report.write_reports(db, PROFILE, rid, tmp_path / "out")
    page = (tmp_path / "out" / "REPORT.html").read_text()
    data = {d["title"]: d for d in _html_data(page)}
    assert [data[f"Job {k}"]["posting_state"] for k in "1234"] == ["not fetched", "empty", "failed", "gone (HTTP 410)"]
    assert data["Job 1"]["note"] == 'a & b "quoted" <tag>'
    elsewhere = data["https://elsewhere.example/job?a=1&b=2"]                 # marked outside the listing: still reviewed
    assert elsewhere["mark"] == "applied" and not elsewhere["listed"] and elsewhere["url"] == "https://elsewhere.example/job?a=1&b=2"


def test_markdown_tables_survive_pipes_and_line_breaks(tmp_path):
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    _seen(db, rid, [_job("justjoin", "1", title="Support | Helpdesk")])
    ev.evaluate(db, PROFILE, rid)
    db.mark("https://justjoin/1", "shortlisted", note="fits | n8n\nrisk: German")
    text = report.write_reports(db, PROFILE, rid, tmp_path / "out").read_text()
    tracked = text[text.index("## Tracked offers"):].splitlines()[4]
    assert tracked.count(" | ") == 4 and tracked.endswith("fits / n8n risk: German |")


def test_html_report_links_only_web_urls(tmp_path):
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    _seen(db, rid, [Offer(board="justjoin", key="1", url="javascript:alert(1)", title="Job", mode="remote")])
    ev.evaluate(db, PROFILE, rid)
    db.mark("javascript:alert(1)", "shortlisted")
    report.write_reports(db, PROFILE, rid, tmp_path / "out")
    page = (tmp_path / "out" / "REPORT.html").read_text()
    data = _html_data(page)
    assert data[0]["url"] == "" and 'href="javascript' not in page


def test_html_review_keeps_rejected_offers_and_postings(tmp_path):
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    _seen(db, rid, [_job("justjoin", "1", title="Kept"), _job("justjoin", "2", title="Dropped", company="Other")])
    ev.evaluate(db, PROFILE, rid)
    db.save_detail(1, 200, "Requirements: n8n", {}, {"years": ["2 years of experience"]})
    db.mark("https://justjoin/1", "shortlisted", note="Main job\n✅ n8n\n⚠ English")
    db.mark("https://justjoin/2", "rejected", note="needs German")
    report.write_reports(db, PROFILE, rid, tmp_path / "out")
    data = {d["title"]: d for d in _html_data((tmp_path / "out" / "REPORT.html").read_text())}
    assert data["Kept"]["posting"] == "Requirements: n8n" and data["Kept"]["hints"]["years"] == ["2 years of experience"]
    assert data["Kept"]["category"] == "Main job" and data["Kept"]["listed"]
    assert data["Dropped"]["mark"] == "rejected" and not data["Dropped"]["listed"]   # hidden from the listing, kept in the review
