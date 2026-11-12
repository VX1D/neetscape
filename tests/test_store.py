"""The database: duplicates across boards, the current state (new, gone, carried offers), marks, migrations."""
import json
import sqlite3

import pytest

from conftest import ALL_REMOTE, cards, crawl, ingest, job
from neetscape import evaluate as ev
from neetscape import profile, report, store
from neetscape.model import Search, Where
from neetscape.store import MIGRATIONS, Store


def clusters(db):
    return {o["key"]: o["cluster_id"] for o in db.q("SELECT key, cluster_id FROM offers")}


@pytest.mark.parametrize("a,b,same", [
    (dict(title="AI Automation Specialist", company="Emoti Group sp. z o.o."),
     dict(title="AI Automation Specialist", snippet="Emoti Group Warszawa"), True),     # the company only in the card text
    (dict(company="Acme"), dict(company="Other"), False),
    (dict(title="Senior Fullstack Developer", company="DCG"),
     dict(title="Senior Fullstack Developer (Java / React)", company="DCG"), True),     # one extra qualifier: the same job
    (dict(title="Magister Farmacji", company="A"), dict(title="Magister Farmacji (k/m)", company="A"), True),
    (dict(title="Tester Manualny", company="A"), dict(title="Tester Manualny (Senior)", company="A"), False),  # a level
    (dict(title="Data Analyst", company="A"), dict(title="Data Analyst - Junior", company="A"), False),
])
def test_duplicates_across_boards_share_a_cluster(db, a, b, same):
    ingest(db, job("justjoin", "1", **a), job("pracuj", "2", **b))
    c = clusters(db)
    assert (c["1"] == c["2"]) is same


def test_a_title_extended_two_ways_is_ambiguous(db):
    ingest(db, job("justjoin", "3", "Data Analyst Junior (SQL)", company="Acme"),
           job("pracuj", "4", "Data Analyst Junior (Python)", company="Acme"), job("olx", "5", "Data Analyst Junior", company="Acme"))
    c = clusters(db)
    assert len({c["3"], c["4"], c["5"]}) == 3              # two qualifiers: two jobs; the bare title matches both: apart


def test_ingest_stores_derived_fields(db):
    ingest(db, job("solidjobs", "1", "T", contracts=["uop"]))
    ingest(db, job("olx", "2", "Technical Support Engineer"), job("olx", "3", "Support Associate"),
           board="olx", params={"category": "obsluga-klienta"})
    assert db.offer("https://solidjobs/1")["contracts"] == "employment"   # canonical contracts
    assert db.offer("https://olx/2")["job_field"] == "it_support"
    assert db.offer("https://olx/3")["job_field"] == "customer_service"  # the title's function, the request category's domain
    assert json.loads(db.offer("https://olx/3")["evidence"])["job_field"][0] == "category"


def test_new_and_gone(fake, db):
    fake.pages = {("*", 1): cards("a", "b", "c"), ("*", 2): cards("d")}
    r1 = crawl(db)
    assert {o["mode"] for o in db.run_offers(r1)} == {"remote"}            # evidence from the pushed filter
    fake.pages[("*", 2)] = cards("e")                                      # d disappeared, e is new
    r2 = crawl(db)                                                         # page 1 fully known: an incremental stop
    assert db.mark_gone(r2) == 0                                           # an incomplete request declares nothing gone
    assert {o["key"] for o in db.current_offers(r2)} == {"a", "b", "c", "d"}   # d lies beyond the stop: still listed
    r3 = crawl(db, incremental=False)                                      # --full
    assert db.mark_gone(r3) == 1 and db.offer("https://fake/d")["gone_at"]
    assert {o["key"] for o in db.current_offers(r3)} == {"a", "b", "c", "e"}
    assert {o["key"] for o in db.current_offers(r2)} == {"a", "b", "c", "d"}   # d was gone only after run 2
    assert {o["key"] for o in db.run_offers(r3) if o["cluster_first_run"] == r3} == {"e"}


def test_gone_counts_only_offers_newly_marked(fake, db):
    kw = Search(id="kw", label="kw", where=Where(remote=True), keywords=("n8n",))
    fake.pages = {("*", 1): cards("a"), ("n8n", 1): cards("b")}
    crawl(db, ALL_REMOTE, kw)
    fake.pages = {("*", 1): cards("c"), ("n8n", 1): cards("a")}               # a moved to the other request
    r2 = crawl(db, ALL_REMOTE, kw)
    assert db.mark_gone(r2) == 1 and db.offer("https://fake/b")["gone_at"] and not db.offer("https://fake/a")["gone_at"]
    assert db.mark_gone(crawl(db, ALL_REMOTE, kw)) == 0                    # b is already gone


def test_partial_and_split_requests_in_the_current_state(db):
    """An incremental (or page-limit) stop says nothing about deeper offers, so it carries what its request saw
    before; an offer only a request no longer made found leaves the state; a split request carries nothing."""
    r1 = ingest(db, job(key="1"), job(key="2"), complete=True)
    ingest(db, job(key="3"), run=r1, keyword="old phrase", complete=True)
    ingest(db, job("olx", "4"), run=r1, board="olx", complete=True)
    r2 = ingest(db, job(key="1"), complete=False, stop="incremental: page already known")
    ingest(db, run=r2, board="olx", complete=False, stop="split into 2 (matches 1000+, the board shows 1000)")
    assert {o["key"] for o in db.current_offers(r2)} == {"1", "2"}


def test_marks_hide_and_track(fake, db, tmp_path):
    fake.pages = {("*", 1): [["a", "AI Automation Specialist", {}], ["b", "AI Consultant", {}]]}
    rid = crawl(db)
    prof = profile.validate({"version": 2, "boards": ["fake"], "searches": [{"id": "all", "where": "remote", "what": "all"}]})
    ev.evaluate(db, prof, rid)
    db.mark("https://fake/b", "rejected")
    db.mark(db.offer("https://fake/a")["id"], "applied", "sent CV")
    rows = report.listing(db, prof, rid)
    assert [d["key"] for d in rows] == ["a"] and rows[0]["mark"] == "applied"
    with pytest.raises(ValueError):
        db.mark("https://fake/a", "maybe")
    with pytest.raises(ValueError, match="no offer"):
        db.mark("99", "applied")
    assert db.mark("https://elsewhere/job", "applied")["url"] == "https://elsewhere/job"  # URLs from outside are fine
    text = report.write_reports(db, prof, rid, tmp_path / "out").read_text()
    assert "Tracked offers" in text and "sent CV" in text
    assert (tmp_path / "out" / "listing.tsv").read_text().count("\n") == 2


def old_database(path, version, sql=()):
    """A database of schema `version` (the first `version` migrations), with `sql` run on it."""
    db = sqlite3.connect(path)
    for step in MIGRATIONS[:version]:
        step(db) if callable(step) else db.executescript(step)
    for s in sql:
        db.execute(s)
    db.execute(f"PRAGMA user_version={version}")
    db.commit()
    db.close()
    return path


def test_migration_renames_uop(tmp_path):
    s = Store(old_database(tmp_path / "old.db", 1, [
        "INSERT INTO offers(board, key, contracts) VALUES ('x', '1', 'mandate,uop'), ('x', '2', 'b2b'), ('x', '3', '')"]))
    assert [r[0] for r in s.q("SELECT contracts FROM offers ORDER BY key")] == ["employment,mandate", "b2b", ""]
    assert s.q("PRAGMA user_version")[0][0] == len(MIGRATIONS)


def test_migration_merges_existing_qualified_duplicates(tmp_path):
    s = Store(old_database(tmp_path / "old.db", MIGRATIONS.index(store._cluster_columns), [
        "INSERT INTO clusters(id, dedup_key, first_seen_run) VALUES (1, 'seniorfullstackdeveloper|dcg', 1), "
        "(2, 'seniorfullstackdeveloperjavareact|dcg', 1)",
        "INSERT INTO offers(board, key, url, title, company, cluster_id) VALUES ('a','1','u1','x','DCG',1), ('b','2','u2','x','DCG',2)"]))
    assert len({row[0] for row in s.q("SELECT cluster_id FROM offers")}) == 1


def test_migration_adds_job_domains_and_eval_fills_them(tmp_path):
    s = Store(old_database(tmp_path / "old.db", MIGRATIONS.index(store._domains_column), [
        "INSERT INTO offers(board, key, url, title, cluster_id) VALUES ('x', '1', 'u1', 'AI Gateway Product Owner', 1)"]))
    assert s.q("PRAGMA user_version")[0][0] == len(MIGRATIONS) and s.offer("u1")["job_domains"] == ""
    s.rederive()
    assert s.offer("u1")["job_domains"] == "ai,product"


def test_migration_splits_mixed_categories_into_industry(tmp_path):
    s = Store(old_database(tmp_path / "old.db", MIGRATIONS.index(store._industry_column), [
        "INSERT INTO offers(board, key, url, title, category, cluster_id) VALUES "
        "('rocketjobs', '1', 'u1', 'Account Manager', 'sales it i telekomunikacja', 1), "
        "('rocketjobs', '2', 'u2', 'SEO Specialist', 'marketing seo', 2), ('justjoin', '3', 'u3', 'Agent', 'support', 3)"]))
    assert [tuple(r) for r in s.q("SELECT category, industry FROM offers ORDER BY key")] == [
        ("sales", "it i telekomunikacja"), ("marketing seo", ""), ("support", "")]
    s.rederive()
    assert s.offer("u1")["job_domains"] == "sales"  # a salesperson at an IT company is not in IT


def test_industry_is_stored_and_names_no_domain(db):
    ingest(db, job("rocketjobs", "1", "Account Manager", category="sales", industry="it i telekomunikacja"),
           job("rocketjobs", "2", "Account Manager", category="sales it"))
    o = db.offer("https://rocketjobs/1")
    assert o["industry"] == "it i telekomunikacja" and o["job_domains"] == "sales"
    assert db.offer("https://rocketjobs/2")["job_domains"] == "it,sales"  # the same words as a category do


def test_job_domains_are_read_in_each_offers_language(db):
    ingest(db, job("arbeitnow", "1", "Sachbearbeiter (m/w/d) Buchhaltung"),          # a German board
           job("justjoin", "2", "Sachbearbeiter Buchhaltung"),                         # a Polish board: not Polish words
           job("justjoin", "3", "Sachbearbeiter Buchhaltung", country="de"),           # ...unless the text is German
           job("justjoin", "4", "Specjalista ds. logistyki"))
    assert [db.offer(f"https://{b}/{k}")["job_domains"] for b, k in
            (("arbeitnow", "1"), ("justjoin", "2"), ("justjoin", "3"), ("justjoin", "4"))] == ["finance", "", "finance", "logistics"]


def test_readonly_store_sees_the_current_schema(tmp_path):
    s = Store(old_database(tmp_path / "old.db", 2), readonly=True)
    assert s.q("SELECT COUNT(*) FROM rejections")[0][0] == 0
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        s.db.execute("DELETE FROM offers")
