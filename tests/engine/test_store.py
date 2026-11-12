"""test_store.py"""
import pytest

from neetscape import evaluate as ev
from neetscape import profile, report
from neetscape.model import Offer
from neetscape.store import Store

from conftest import ALL_REMOTE, run_crawl


def test_crawl_stop_rules_new_and_gone(fake, tmp_path):
    db = Store(tmp_path / "j.db")
    fake.pages = {("*", 1): [["a", "Job A", {}], ["b", "Job B", {}], ["c", "Job C", {}]],
                  ("*", 2): [["d", "Job D", {}]]}
    r1 = db.start_run({}, [])
    run_crawl(db, r1, fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests WHERE run_id=?", r1)[0]
    assert (req["pages"], req["found"], req["complete"], req["stop_reason"]) == (2, 4, 1, "last page")
    assert {o["mode"] for o in db.run_offers(r1)} == {"remote"}      # evidence from the pushed filter

    # second run: d disappeared, e is new; newest-first page 1 is fully known -> incremental stop, not complete
    fake.pages = {("*", 1): [["a", "Job A", {}], ["b", "Job B", {}], ["c", "Job C", {}]], ("*", 2): [["e", "Job E", {}]]}
    r2 = db.start_run({}, [])
    run_crawl(db, r2, fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests WHERE run_id=?", r2)[0]
    assert req["stop_reason"].startswith("incremental") and not req["complete"]
    assert db.mark_gone(r2) == 0                                      # incomplete request: nothing is declared gone

    r3 = db.start_run({}, [])
    run_crawl(db, r3, fake, [ALL_REMOTE], incremental=False)          # --full
    assert db.mark_gone(r3) == 1                                      # d
    assert db.offer("https://fake/d")["gone_at"]
    new = {o["key"] for o in db.run_offers(r3) if o["cluster_first_run"] == r3}
    assert new == {"e"}


def test_duplicates_across_boards_share_a_cluster(tmp_path):
    db = Store(tmp_path / "j.db")
    r = db.start_run({}, [])
    req = db.start_request(r, "x", "s", None, {}, ())
    db.ingest([Offer(board="justjoin", key="1", url="u1", title="AI Automation Specialist", company="Emoti Group sp. z o.o.")], r, req, 1)
    db.ingest([Offer(board="pracuj", key="2", url="u2", title="AI Automation Specialist", snippet="Emoti Group Warszawa")], r, req, 1)
    db.ingest([Offer(board="linkedin", key="3", url="u3", title="AI Automation Specialist", company="Other")], r, req, 1)
    clusters = [o["cluster_id"] for o in db.q("SELECT cluster_id FROM offers ORDER BY key")]
    assert clusters[0] == clusters[1] != clusters[2]


def test_marks_hide_and_track(fake, tmp_path):
    db = Store(tmp_path / "j.db")
    fake.pages = {("*", 1): [["a", "AI Automation Specialist", {}], ["b", "AI Consultant", {}]]}
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    prof = profile.validate({"version": 2, "boards": ["fake"], "searches": [{"id": "all", "where": "remote", "what": "all"}]})
    ev.evaluate(db, prof, rid)
    db.mark("https://fake/b", "rejected")
    db.mark(db.offer("https://fake/a")["id"], "applied", "sent CV")
    rows = report.listing(db, prof, rid)
    assert [d["key"] for d in rows] == ["a"] and rows[0]["mark"] == "applied"
    with pytest.raises(ValueError):
        db.mark("https://fake/a", "maybe")
    path = report.write_reports(db, prof, rid, tmp_path / "out")
    text = path.read_text()
    assert "Tracked offers" in text and "sent CV" in text
    assert (tmp_path / "out" / "listing.tsv").read_text().count("\n") == 2


def test_migration_renames_uop(tmp_path):
    import sqlite3
    from neetscape.store import MIGRATIONS
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(MIGRATIONS[0])
    db.execute("PRAGMA user_version=1")
    db.execute("INSERT INTO offers(board, key, contracts) VALUES ('x', '1', 'mandate,uop'), ('x', '2', 'b2b'), ('x', '3', '')")
    db.commit()
    db.close()
    s = Store(path)
    assert [r[0] for r in s.q("SELECT contracts FROM offers ORDER BY key")] == ["employment,mandate", "b2b", ""]
    assert s.q("PRAGMA user_version")[0][0] == len(MIGRATIONS)


def test_ingest_stores_canonical_contracts(tmp_path):
    db = Store(tmp_path / "j.db")
    r = db.start_run({}, [])
    req = db.start_request(r, "x", "s", None, {}, ())
    db.ingest([Offer(board="solidjobs", key="1", url="u1", title="T", contracts=["uop"])], r, req, 1)
    assert db.offer("u1")["contracts"] == "employment"


def test_incremental_stop_ignores_known_promoted_offers(fake, tmp_path):
    db = Store(tmp_path / "j.db")
    fake.pages = {("*", 1): [["p", "Promo", {"promoted": True}], ["a", "Job A", {}]]}
    run_crawl(db, db.start_run({}, []), fake, [ALL_REMOTE])
    # next run: the known promoted offer and a known organic one, plus a new organic one; page 2 exists
    fake.pages = {("*", 1): [["p", "Promo", {"promoted": True}], ["a", "Job A", {}], ["b", "Job B", {}]],
                  ("*", 2): [["c", "Job C", {}]]}
    r2 = db.start_run({}, [])
    run_crawl(db, r2, fake, [ALL_REMOTE])
    assert {o["key"] for o in db.run_offers(r2)} == {"p", "a", "b", "c"}


def test_age_stop_uses_the_loosest_search_sharing_a_request(fake, tmp_path):
    from neetscape.model import Search, Where
    import datetime as dt
    old = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    fake.pages = {("*", 1): [[k, f"Job {k}", {"published": old}] for k in "abc"], ("*", 2): [["d", "Job D", {"published": old}]]}
    fake.parse = lambda raw, r: [Offer(board="fake", key=k, url=f"https://fake/{k}", title=t,
                                       published=dt.date.fromisoformat(x["published"])) for k, t, x in __import__("json").loads(raw)]
    recent = Search(id="recent", label="recent", where=Where(remote=True), keywords=None, max_age_days=7)
    any_age = Search(id="any", label="any", where=Where(remote=True), keywords=None)
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    reqs = fake.requests(recent)[0]                                   # the planner keeps one request for both searches
    import asyncio
    from neetscape.crawler import crawl
    from neetscape.boards.fetch import Limiter
    from neetscape.pay import DEFAULT_FX
    asyncio.run(crawl(reqs, {"recent": recent, "any": any_age}, db, rid, port=0, limiter=Limiter(), fx=DEFAULT_FX))
    assert len(db.run_offers(rid)) == 4


def test_mark_gone_counts_only_offers_marked(fake, tmp_path):
    db = Store(tmp_path / "j.db")
    fake.pages = {("*", 1): [["a", "Job A", {}]], ("n8n", 1): [["b", "Job B", {}]]}
    kw = ALL_REMOTE.__class__(id="kw", label="kw", where=ALL_REMOTE.where, keywords=("n8n",))
    run_crawl(db, db.start_run({}, []), fake, [ALL_REMOTE, kw])
    fake.pages = {("*", 1): [["c", "Job C", {}]], ("n8n", 1): [["a", "Job A", {}]]}   # a moved to the other request
    r2 = db.start_run({}, [])
    run_crawl(db, r2, fake, [ALL_REMOTE, kw])
    assert db.mark_gone(r2) == 1 and db.offer("https://fake/b")["gone_at"] and not db.offer("https://fake/a")["gone_at"]
    r3 = db.start_run({}, [])
    run_crawl(db, r3, fake, [ALL_REMOTE, kw])
    assert db.mark_gone(r3) == 0                                      # b is already gone


def test_mark_unknown_numeric_id_is_an_error(tmp_path):
    db = Store(tmp_path / "j.db")
    with pytest.raises(ValueError, match="no offer"):
        db.mark("99", "applied")
    assert db.mark("https://elsewhere/job", "applied")["url"] == "https://elsewhere/job"  # URLs from outside are fine


def test_readonly_store_sees_the_current_schema(tmp_path):
    import sqlite3
    from neetscape.store import MIGRATIONS
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(MIGRATIONS[0])
    db.execute("PRAGMA user_version=2")
    db.commit()
    db.close()
    s = Store(path, readonly=True)
    assert s.q("SELECT COUNT(*) FROM rejections")[0][0] == 0
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        s.db.execute("DELETE FROM offers")


def test_single_page_board_completes(fake, tmp_path):
    from neetscape.boards.base import Caps
    fake.caps = Caps(keywords=True, remote="filter", page_size=3, max_pages=1, whole_listing=True, transport="http")
    fake.pages = {("*", 1): [["a", "Job A", {}], ["b", "Job B", {}], ["c", "Job C", {}]]}
    db = Store(tmp_path / "j.db")
    run_crawl(db, db.start_run({}, []), fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests")[0]
    assert (req["complete"], req["stop_reason"]) == (1, "end")   # a full single page is the whole listing


def test_page_cap_is_not_the_end_of_the_listing(fake, tmp_path):
    from neetscape.boards.base import Caps
    fake.caps = Caps(keywords=True, remote="filter", page_size=3, max_pages=1, transport="http")  # e.g. Indeed: 1 public page
    fake.page_url = lambda r, page: f"fake://{r.keyword or '*'}/{page}" if page <= 1 else None
    fake.pages = {("*", 1): [["a", "Job A", {}], ["b", "Job B", {}], ["c", "Job C", {}]]}
    db = Store(tmp_path / "j.db")
    run_crawl(db, db.start_run({}, []), fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests")[0]
    assert (req["complete"], req["stop_reason"]) == (0, "page limit")   # offers beyond the cap must not turn "gone"


def test_404_after_the_last_page_ends_the_request(fake, tmp_path, monkeypatch):
    import json as _json
    from neetscape.boards.fetch import FetchError, Http
    fake.pages = {("*", 1): [["a", "Job A", {}], ["b", "Job B", {}], ["c", "Job C", {}]]}

    async def get(self, url):
        if url.endswith("/2"):
            raise FetchError(404)
        return _json.dumps(fake.pages.get(("*", 1)))

    monkeypatch.setattr(Http, "get", get)
    db = Store(tmp_path / "j.db")
    run_crawl(db, db.start_run({}, []), fake, [ALL_REMOTE])
    req = db.q("SELECT * FROM requests")[0]
    assert (req["complete"], req["stop_reason"], req["error"]) == (1, "end", "")


def test_incremental_stop_needs_the_same_request_completed_before(fake, tmp_path):
    from neetscape.model import Search, Where
    kw = Search(id="kw", label="kw", where=Where(remote=True), keywords=("x",))
    db = Store(tmp_path / "j.db")
    fake.pages = {("x", 1): [["a", "Job A", {}], ["b", "Job B", {}], ["c", "Job C", {}]], ("x", 2): []}
    run_crawl(db, db.start_run({}, []), fake, [kw])                     # the phrase search sees a, b, c
    fake.pages = {("*", 1): [["a", "Job A", {}], ["b", "Job B", {}], ["c", "Job C", {}]],
                  ("*", 2): [["d", "Job D", {}], ["e", "Job E", {}], ["f", "Job F", {}]], ("*", 3): []}
    r2 = db.start_run({}, [])
    run_crawl(db, r2, fake, [ALL_REMOTE])                               # "all" was never crawled to its end
    req = db.q("SELECT * FROM requests WHERE run_id=? AND keyword IS NULL", r2)[0]
    assert req["pages"] == 3 and req["complete"] and db.offer("https://fake/f")   # page 1 known from the phrase: no stop


def test_request_over_the_result_cap_is_split_recursively(fake, tmp_path):
    import json as _json
    from dataclasses import replace
    from neetscape.boards.base import Caps
    from neetscape.boards.fetch import Http
    fake.caps = Caps(keywords=True, remote="filter", page_size=3, max_pages=10, result_cap=5, transport="http")
    totals = {"": 9, "a": 4, "b": 5, "b1": 3, "b2": 2}                 # b reaches the cap (5): split again
    tree = {"": ["a", "b"], "b": ["b1", "b2"]}
    fake.total = lambda raw, r: totals[r.params.get("cat", "")]
    fake.split = lambda raw, r: [replace(r, params={**r.params, "cat": c}) for c in tree.get(r.params.get("cat", ""), [])]
    fake.page_url = lambda r, page: f"fake://{r.params.get('cat', '')}/{page}"

    async def get(self, url):
        cat, page = url[len("fake://"):].rsplit("/", 1)
        n = totals[cat] if cat in ("a", "b1", "b2") else 3            # leaves list their own offers
        offers = [[f"{cat}{i}", f"Job {cat}{i}", {}] for i in range(n)][(int(page) - 1) * 3:int(page) * 3]
        return _json.dumps(offers)

    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(Http, "get", get)
    db = Store(tmp_path / "j.db")
    rid = db.start_run({}, [])
    run_crawl(db, rid, fake, [ALL_REMOTE])
    mp.undo()
    reqs = {(_json.loads(r["params_json"]).get("cat", "")): r for r in db.q("SELECT * FROM requests WHERE run_id=?", rid)}
    assert set(reqs) == {"", "a", "b", "b1", "b2"}
    assert reqs[""]["stop_reason"].startswith("split into 2") and not reqs[""]["complete"]
    assert reqs["b"]["stop_reason"].startswith("split into 2") and all(reqs[k]["complete"] for k in ("a", "b1", "b2"))
    assert {o["key"] for o in db.run_offers(rid)} >= {f"{c}{i}" for c, n in (("a", 4), ("b1", 3), ("b2", 2)) for i in range(n)}
