"""SQLite store: every crawled offer, where and when it was seen, evaluations, details and the user's marks.

One database per output directory (`runs/neetscape.db`), holding one country's searches: pay is stored
per month in that country's currency (use a separate `--out` per country). Schema changes are ordered
migrations (SQL scripts or functions) applied according to `PRAGMA user_version`; existing migrations are
never edited, new ones are appended.

Current state as of run N: the offers presumed still listed after run N (`current_offers`). Verdicts of a run
cover that whole state, not only the run's sightings: `evals` holds the offers that pass a search (score,
matched rules, tags), `rejections` (v3) the ones that fail it with their reasons joined by `; `, e.g.

    SELECT reasons, COUNT(*) FROM rejections WHERE run_id = (SELECT MAX(id) FROM runs) GROUP BY 1 ORDER BY 2 DESC
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

from . import country as countries
from . import infer
from .boards import REGISTRY
from .boards.base import request_key
from .model import Offer, canonical_contract, norm, norm_company, parse_date

MARK_STATUSES = ("shortlisted", "applied", "interview", "offer", "rejected", "ignored")
HIDDEN = ("rejected", "ignored")
GONE = (404, 410)  # HTTP statuses of a posting that mark its offer gone
_POSTING_OK = "d.http_status = 200 AND d.text != ''"  # a stored posting with text (failures keep status 0 / 4xx)
_EMPTY = (None, "", "unknown", "[]", "{}")  # stored values that mean "the board did not say"

# Stop reasons of a request that reached its last allowed page: the board's `max_pages`, or a smaller
# `--limit-pages N` given to the command that fetched it (a resumed run may get another limit than it started with).
PAGE_LIMIT = "page limit"
PAGE_LIMIT_ASKED = "page limit (--limit-pages)"
_CAPPED = "stop_reason LIKE '%capped:%'"  # a request over the board's result cap that could not be split


def _rename_contracts(db: sqlite3.Connection) -> None:
    """v2: contract `uop` became `employment` (one vocabulary for every country)."""
    for oid, contracts in db.execute("SELECT id, contracts FROM offers WHERE contracts != ''").fetchall():
        new = ",".join(sorted({canonical_contract(c) for c in contracts.split(",") if c}))
        if new != contracts:
            db.execute("UPDATE offers SET contracts=? WHERE id=?", (new, oid))


MIN_PREFIX = 12  # a normalised title this long that starts another one of the same company names the same job
# a qualifier naming a level makes another job ("Tester Manualny" / "Tester Manualny (Senior)"); titles are normalised
# without spaces, so these are matched as substrings of the qualifier
_LEVEL_QUALIFIER = re.compile(r"senior|junior|mid|regular|lead|principal|staff|expert|ekspert|starsz|mlodsz|intern|staz"
                              r"|trainee|manager|kierownik|head|director|dyrektor")


def same_job_title(a: str, b: str) -> bool:
    """Normalised titles of one company that name the same job: equal, or one extends the other with a qualifier
    ("seniorfullstackdeveloper" / "seniorfullstackdeveloperjavareact") that does not name a level."""
    short, long_ = sorted((a, b), key=len)
    if short == long_:
        return True
    return len(short) >= MIN_PREFIX and long_.startswith(short) and not _LEVEL_QUALIFIER.search(long_[len(short):])


def _cluster_columns(db: sqlite3.Connection) -> None:
    """v5: clusters keep their title and company apart (indexed), and clusters of one company whose titles extend
    one another unambiguously are merged (the same job on two boards, one title carrying a "(Java / React)")."""
    db.execute("ALTER TABLE clusters ADD COLUMN title TEXT")
    db.execute("ALTER TABLE clusters ADD COLUMN company TEXT")
    for cid, key in db.execute("SELECT id, dedup_key FROM clusters").fetchall():
        title, _, company = key.partition("|")
        db.execute("UPDATE clusters SET title=?, company=? WHERE id=?", (title, company, cid))
    db.execute("CREATE INDEX clusters_company ON clusters(company)")
    by_company: dict[str, list] = {}
    for cid, title, company, first in db.execute(
            "SELECT id, title, company, first_seen_run FROM clusters WHERE company != '' ORDER BY id").fetchall():
        by_company.setdefault(company, []).append([cid, title, first])
    for clusters in by_company.values():
        for c in sorted(clusters, key=lambda c: len(c[1])):
            if c not in clusters:
                continue
            partners = [d for d in clusters if d is not c and same_job_title(c[1], d[1])]
            if len(partners) == 1 and len(partners[0][1]) > len(c[1]):  # merge the longer title into the shorter
                d = partners[0]
                db.execute("UPDATE offers SET cluster_id=? WHERE cluster_id=?", (c[0], d[0]))
                db.execute("UPDATE clusters SET first_seen_run=MIN(first_seen_run, ?) WHERE id=?", (d[2], c[0]))
                db.execute("DELETE FROM clusters WHERE id=?", (d[0],))
                clusters.remove(d)


def _observation_columns(db: sqlite3.Connection) -> None:
    """v6: offers keep their observations apart from the derived fields: `facts` (the adapter's structured values),
    `country` (the language of the text; '' = the board's, else the database's) and `evidence` (derived column ->
    [source, phrase]); the job field and its two axes are new derived columns. Offers stored earlier did not separate the two: their stored values become their facts."""
    db.execute("ALTER TABLE offers ADD COLUMN facts TEXT DEFAULT '{}'")
    db.execute("ALTER TABLE offers ADD COLUMN evidence TEXT DEFAULT '{}'")
    db.execute("ALTER TABLE offers ADD COLUMN country TEXT DEFAULT ''")
    for col in ("job_field", "job_function", "job_domain"):  # derived by `rederive` (infer.fields)
        db.execute(f"ALTER TABLE offers ADD COLUMN {col} TEXT DEFAULT '{'other' if col == 'job_field' else 'unknown'}'")
    db.execute("CREATE INDEX offers_field ON offers(job_field)")
    for oid, mode, worktime, contracts, level in db.execute(
            "SELECT id, mode, worktime, contracts, level FROM offers").fetchall():
        facts = {k: v for k, v in (("mode", mode), ("worktime", worktime), ("level", level)) if v not in _EMPTY}
        if contracts:
            facts["contracts"] = contracts.split(",")
        db.execute("UPDATE offers SET facts=? WHERE id=?", (json.dumps(facts, sort_keys=True), oid))


def _domains_column(db: sqlite3.Connection) -> None:
    """v7: `job_domains`, every domain the title and the category name (comma-joined, sorted; derived by
    `rederive`, which `neetscape eval` runs, so offers stored earlier get theirs at the next evaluation)."""
    db.execute("ALTER TABLE offers ADD COLUMN job_domains TEXT DEFAULT ''")


MIGRATIONS = [
    """
    CREATE TABLE runs(id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT,
                      profile_json TEXT, argv TEXT);
    CREATE TABLE requests(id INTEGER PRIMARY KEY, run_id INTEGER, board TEXT, search_id TEXT, req_key TEXT,
                          keyword TEXT, params_json TEXT, pushed TEXT, status TEXT, pages INTEGER DEFAULT 0,
                          found INTEGER DEFAULT 0, complete INTEGER DEFAULT 0, stop_reason TEXT, error TEXT,
                          started_at TEXT, finished_at TEXT);
    CREATE INDEX requests_key ON requests(req_key, run_id);
    CREATE TABLE clusters(id INTEGER PRIMARY KEY, dedup_key TEXT UNIQUE, first_seen_run INTEGER);
    CREATE TABLE offers(id INTEGER PRIMARY KEY, board TEXT, key TEXT, url TEXT, title TEXT, title_norm TEXT,
                        company TEXT, mode TEXT, locations TEXT, worktime TEXT, contracts TEXT, level TEXT,
                        category TEXT, skills TEXT, pay_text TEXT, pay_period TEXT, pay_min INTEGER, pay_max INTEGER,
                        published TEXT, promoted INTEGER, snippet TEXT, description TEXT, cluster_id INTEGER,
                        first_seen_run INTEGER, last_seen_run INTEGER, gone_at TEXT, UNIQUE(board, key));
    CREATE INDEX offers_last_run ON offers(last_seen_run);
    CREATE INDEX offers_cluster ON offers(cluster_id);
    CREATE INDEX offers_title ON offers(title_norm);
    CREATE INDEX offers_pay ON offers(pay_max);
    CREATE TABLE sightings(offer_id INTEGER, request_id INTEGER, page INTEGER, PRIMARY KEY(offer_id, request_id));
    CREATE TABLE details(offer_id INTEGER PRIMARY KEY, fetched_at TEXT, http_status INTEGER, text TEXT,
                         jsonld TEXT, hints TEXT);
    CREATE TABLE evals(run_id INTEGER, offer_id INTEGER, search_id TEXT, score INTEGER, why TEXT,
                       PRIMARY KEY(run_id, offer_id, search_id));
    CREATE TABLE marks(id INTEGER PRIMARY KEY, url TEXT, offer_id INTEGER, status TEXT, note TEXT, at TEXT);
    CREATE VIEW tracked AS
        SELECT m.* FROM marks m JOIN (SELECT url, MAX(id) id FROM marks GROUP BY url) last ON last.id = m.id;
    """,
    _rename_contracts,
    """
    CREATE TABLE rejections(run_id INTEGER, offer_id INTEGER, search_id TEXT, reasons TEXT,
                            PRIMARY KEY(run_id, offer_id, search_id));
    """,
    """
    CREATE INDEX offers_url ON offers(url);  -- marks, reports and `--marked` look offers up by URL or key
    CREATE INDEX offers_key ON offers(key);
    """,
    _cluster_columns,
    _observation_columns,
    _domains_column,
]

# The current state as of run :run, as CTEs ending in `cur(offer_id)`. A board's latest crawl is the latest run
# <= :run with requests to it. An offer is current when it is not marked gone (by the start of the next run)
# and that crawl saw it, or that crawl repeated a request that saw it earlier without reaching the request's end
# (an incremental, age or page-limit stop or an error says nothing about the offers further down). A request
# replaced by its split carries nothing: its narrower requests cover its listing.
_CURRENT_CTE = """
    latest(board, run) AS (SELECT board, MAX(run_id) FROM requests WHERE run_id <= :run GROUP BY board),
    carried(req_key) AS (SELECT r.req_key FROM requests r JOIN latest l ON l.board = r.board AND l.run = r.run_id
                         WHERE r.complete = 0 AND COALESCE(r.stop_reason, '') NOT LIKE 'split into%'),
    seen(offer_id) AS (SELECT DISTINCT s.offer_id FROM sightings s JOIN requests r ON r.id = s.request_id
                       JOIN latest l ON l.board = r.board
                       WHERE r.run_id = l.run OR (r.run_id < l.run AND r.req_key IN (SELECT req_key FROM carried))),
    cur(offer_id) AS (SELECT o.id FROM offers o JOIN seen ON seen.offer_id = o.id
                      WHERE o.gone_at IS NULL OR o.gone_at >= COALESCE((SELECT MIN(started_at) FROM runs WHERE id > :run), '~'))"""


# Columns of `run_offers` / `current_offers` beside the offer's own (offers `o`, clusters `c`).
_CLUSTER_AND_POSTING = ("c.first_seen_run AS cluster_first_run, (SELECT d.text FROM details d WHERE d.offer_id = o.id) AS posting, "
                        # areas: "board|city|radius_km,..." of the requests that found the offer with the board's city filter
                        "(SELECT GROUP_CONCAT(DISTINCT r.board || '|' || json_extract(r.params_json, '$.city') || '|' || "
                        "IFNULL(json_extract(r.params_json, '$.radius_km'), 0)) FROM sightings s2 JOIN requests r ON r.id = s2.request_id "
                        "WHERE s2.offer_id = o.id AND instr(r.pushed, 'city') > 0) AS areas")


def has_verdict(offer: str) -> str:
    """SQL condition: the offer `offer` (an SQL expression of its id) has a verdict of run `:run`, passing
    (`evals`) or failing (`rejections`)."""
    return (f"(EXISTS (SELECT 1 FROM evals ve WHERE ve.run_id = :run AND ve.offer_id = {offer}) OR "
            f"EXISTS (SELECT 1 FROM rejections vj WHERE vj.run_id = :run AND vj.offer_id = {offer}))")


def now() -> str:
    """The local time as stored: ISO 8601 to the second."""
    return dt.datetime.now().isoformat(timespec="seconds")



class Store:
    """`readonly` opens an existing database for reading only; a database of an older schema is migrated
    first (the only write a read-only store makes), so readers always see the current schema."""

    def __init__(self, path: str | Path, readonly: bool = False):
        self.path = Path(path)
        if readonly:
            self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            if self._version() < len(MIGRATIONS):
                self.db.close()
                Store(self.path).close()
                self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path)
            self.db.execute("PRAGMA journal_mode=WAL")
            self._migrate()
        self.db.row_factory = sqlite3.Row

    def _version(self) -> int:
        return self.db.execute("PRAGMA user_version").fetchone()[0]

    def _migrate(self) -> None:
        version = self._version()
        for i, step in enumerate(MIGRATIONS[version:], start=version + 1):
            if callable(step):
                step(self.db)
            else:
                self.db.executescript(step)
            self.db.execute(f"PRAGMA user_version={i}")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def q(self, sql: str, *args) -> list[sqlite3.Row]:
        """All rows of a query with positional parameters."""
        return self.db.execute(sql, args).fetchall()

    def _one(self, sql: str, *args) -> sqlite3.Row | None:
        return self.db.execute(sql, args).fetchone()

    def update_offer(self, offer_id: int, cols: dict) -> None:
        """Set some columns of one offer (not committed)."""
        self.db.execute(f"UPDATE offers SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", (*cols.values(), offer_id))

    # ---------------------------------------------------------------- runs & requests
    def start_run(self, profile: dict, argv: list[str]) -> int:
        cur = self.db.execute("INSERT INTO runs(started_at, status, profile_json, argv) VALUES (?,?,?,?)",
                              (now(), "running", json.dumps(profile, ensure_ascii=False, default=str), json.dumps(argv)))
        self.db.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, status: str = "done") -> None:
        self.db.execute("UPDATE runs SET finished_at=?, status=? WHERE id=?", (now(), status, run_id))
        self.db.commit()

    def run(self, run_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM runs WHERE id=?", run_id)

    def last_run(self, status: str | None = None) -> int | None:
        """The latest run, optionally the latest with `status`."""
        args = (status,) if status else ()
        row = self._one("SELECT id FROM runs" + (" WHERE status=?" if status else "") + " ORDER BY id DESC LIMIT 1", *args)
        return row[0] if row else None

    def run_country(self, run_id: int | None = None) -> str | None:
        """Country of the profile of a run (default: the latest run that has a profile)."""
        args = (run_id,) if run_id else ()
        row = self._one("SELECT profile_json FROM runs WHERE profile_json NOT IN ('', '{}')" + (" AND id=?" if run_id else "")
                        + " ORDER BY id DESC LIMIT 1", *args)
        if not row:
            return None
        return (json.loads(row[0]) or {}).get("country", "pl")

    def start_request(self, run_id: int, board: str, search_id: str, keyword: str | None, params: dict, pushed) -> int:
        cur = self.db.execute(
            "INSERT INTO requests(run_id, board, search_id, req_key, keyword, params_json, pushed, status, started_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, board, search_id, request_key(board, keyword, params), keyword, json.dumps(params, ensure_ascii=False),
             ",".join(sorted(pushed)), "running", now()))
        self.db.commit()
        return cur.lastrowid

    def finish_request(self, req_id: int, pages: int, found: int, complete: bool, stop_reason: str, error: str = "") -> None:
        self.db.execute("UPDATE requests SET status=?, pages=?, found=?, complete=?, stop_reason=?, error=?, finished_at=? WHERE id=?",
                        ("error" if error else "done", pages, found, int(complete), stop_reason, error, now(), req_id))
        self.db.commit()

    def completed_before(self, req_key: str, run_id: int) -> bool:
        """Whether an earlier run fetched this same request (board, phrase, parameters) to its end."""
        return bool(self.q("SELECT 1 FROM requests WHERE req_key=? AND run_id<? AND complete=1 LIMIT 1", req_key, run_id))

    def done_request_keys(self, run_id: int) -> set[str]:
        """Keys of the requests a run finished (`--resume` skips them)."""
        return {r[0] for r in self.q("SELECT req_key FROM requests WHERE run_id=? AND status='done'", run_id)}

    # ---------------------------------------------------------------- offers
    def _cluster(self, o: Offer, run_id: int) -> int:
        """Same title and compatible company = same job. An unknown company joins a cluster whose company
        name appears in the offer's card text."""
        title, company = o.title_norm, norm_company(o.company)
        if company:
            if not self._one("SELECT 1 FROM clusters WHERE dedup_key=?", f"{title}|{company}"):
                partners = [r for r in self.q("SELECT id, title FROM clusters WHERE company=?", company)
                            if same_job_title(title, r["title"])]
                if len(partners) == 1:  # the same job under a longer or shorter title (one unambiguous match)
                    return partners[0]["id"]
        else:
            hay = norm(o.snippet + " " + o.title)
            # the first in key order of this title's companies named in the card; a range on the unique index
            # ("title|" <= key < "title}", "}" follows "|"), not a scan
            keys = self.q("SELECT dedup_key FROM clusters WHERE dedup_key >= ? AND dedup_key < ? ORDER BY dedup_key",
                          title + "|", title + "}")
            company = next((c for c in (r[0].partition("|")[2] for r in keys) if c and c in hay), "")
        key = f"{title}|{company}"
        row = self._one("SELECT id FROM clusters WHERE dedup_key=?", key)
        if row:
            return row[0]
        return self.db.execute("INSERT INTO clusters(dedup_key, first_seen_run, title, company) VALUES (?,?,?,?)",
                               (key, run_id, title, company)).lastrowid

    @staticmethod
    def _offer_values(o: Offer) -> dict:
        """The offer's columns as stored."""
        return dict(url=o.url, title=o.title, title_norm=o.title_norm, company=o.company, mode=o.mode,
                    locations=json.dumps(o.locations, ensure_ascii=False), worktime=o.worktime,
                    contracts=",".join(sorted({canonical_contract(c) for c in o.contracts})), level=o.level,
                    category=o.category, skills=", ".join(o.skills), pay_text=o.pay_text, pay_period=o.pay_period,
                    pay_min=o.pay_min, pay_max=o.pay_max, published=o.published.isoformat() if o.published else None,
                    promoted=int(o.promoted), snippet=o.snippet[:1000], description=o.description,
                    facts=json.dumps(infer.board_facts(o) if o.facts is None else o.facts, ensure_ascii=False, sort_keys=True),
                    country=o.country)

    def _posting_set_published(self, cur: sqlite3.Row, card_published: str | None) -> bool:
        """The stored `published` came from the offer's posting and is earlier than the card's date."""
        stored, card = parse_date(cur["published"]), parse_date(card_published)
        if not (stored and card and stored < card):
            return False
        row = self._one("SELECT jsonld FROM details WHERE offer_id=?", cur["id"])
        return bool(row and row[0]) and json.loads(row[0]).get("published") == cur["published"]

    def _upsert(self, o: Offer, run_id: int, posting_date_is_first: bool = False) -> tuple[int, bool]:
        """Insert or update one offer; returns (offer id, known from an earlier run). An update keeps stored
        values the new sighting lacks and, with `posting_date_is_first` (`Board.posting_date_is_first`), the first
        publication date read from the posting over the card's later refresh date."""
        values = self._offer_values(o)
        cur = self._one("SELECT * FROM offers WHERE board=? AND key=?", o.board, o.key)
        if cur:
            merged = {k: (cur[k] if v in _EMPTY else v) for k, v in values.items()}
            if posting_date_is_first and self._posting_set_published(cur, values["published"]):
                merged["published"] = cur["published"]
            self.db.execute(f"UPDATE offers SET {', '.join(f'{k}=?' for k in merged)}, last_seen_run=?, gone_at=NULL WHERE id=?",
                            (*merged.values(), run_id, cur["id"]))
            return cur["id"], cur["first_seen_run"] < run_id
        cols = ", ".join(values)
        offer_id = self.db.execute(
            f"INSERT INTO offers(board, key, {cols}, cluster_id, first_seen_run, last_seen_run) "
            f"VALUES (?,?,{','.join('?' * len(values))},?,?,?)",
            (o.board, o.key, *values.values(), self._cluster(o, run_id), run_id, run_id)).lastrowid
        return offer_id, False

    def rederive(self, offer_ids=None) -> int:
        """Derive the inferred fields (infer.derive) of some offers, or of all, again from their observations: the
        adapter's facts, the title and card text, the requests that found them and the fetched posting. Returns
        how many offers changed."""
        if offer_ids is not None and not offer_ids:
            return 0
        home = self.run_country() or "pl"
        where = f"WHERE o.id IN ({','.join('?' * len(offer_ids))})" if offer_ids is not None else ""
        rows = self.db.execute(f"""
            SELECT o.*, d.text AS posting, d.jsonld AS posting_meta,
                   (SELECT GROUP_CONCAT(DISTINCT json_extract(r.params_json, '$.category')) FROM sightings s
                    JOIN requests r ON r.id = s.request_id WHERE s.offer_id = o.id) AS request_category,
                   EXISTS (SELECT 1 FROM sightings s JOIN requests r ON r.id = s.request_id
                           WHERE s.offer_id = o.id AND instr(r.pushed, 'remote') > 0) AS request_remote
            FROM offers o LEFT JOIN details d ON d.offer_id = o.id {where}""", tuple(offer_ids or ())).fetchall()
        changed = 0
        for r in rows:
            board = REGISTRY.get(r["board"])
            code = r["country"] or countries.text_country(board.caps.country if board else "", home)
            meta = json.loads(r["posting_meta"] or "{}")
            cols = infer.derive(title=r["title"] or "", card=infer.card_text(r), facts=json.loads(r["facts"] or "{}"),
                                request_remote=bool(r["request_remote"]), posting=r["posting"] or "",
                                posting_remote=bool(meta.get("remote")),
                                posting_facts=board.posting_facts(meta) if board and r["posting"] else None,
                                category=" ".join(filter(None, (r["category"], r["request_category"]))),
                                languages=countries.languages(code))
            if any(r[k] != v for k, v in cols.items()):
                self.update_offer(r["id"], cols)
                changed += 1
        self.db.commit()
        return changed

    def ingest(self, offers: list[Offer], run_id: int, request_id: int, page: int,
               posting_date_is_first: bool = False) -> tuple[int, set[str]]:
        """Upsert offers and record the sighting. Returns (offers new to this request, keys of the offers
        known from earlier runs). `posting_date_is_first`: the board's flag (see `_upsert`)."""
        new_in_request, known, ids = 0, set(), []
        for o in offers:
            offer_id, seen_before = self._upsert(o, run_id, posting_date_is_first)
            if seen_before:
                known.add(o.key)
            new_in_request += self.db.execute("INSERT OR IGNORE INTO sightings(offer_id, request_id, page) VALUES (?,?,?)",
                                              (offer_id, request_id, page)).rowcount
            ids.append(offer_id)
        self.db.commit()
        self.rederive(ids)
        return new_in_request, known

    def mark_gone(self, run_id: int) -> int:
        """Offers seen earlier under a request that completed in this run, but not seen by it now."""
        gone = self.db.execute("""
            UPDATE offers SET gone_at = :now WHERE gone_at IS NULL AND last_seen_run < :run AND id IN (
                SELECT s.offer_id FROM sightings s JOIN requests old ON old.id = s.request_id
                JOIN requests cur ON cur.req_key = old.req_key AND cur.run_id = :run AND cur.complete = 1
                WHERE old.run_id < :run AND NOT EXISTS (
                    SELECT 1 FROM sightings s2 WHERE s2.offer_id = s.offer_id AND s2.request_id = cur.id))""",
                               {"now": now(), "run": run_id}).rowcount
        self.db.commit()
        return gone

    def current_offers(self, run_id: int, offer_id: int | None = None) -> list[sqlite3.Row]:
        """The current state as of `run_id` (see `_CURRENT_CTE`), optionally one offer, in `run_offers`' shape;
        `keywords` are those of every request up to the run that found the offer."""
        return self._with_current(f"""
            SELECT o.*, (SELECT GROUP_CONCAT(DISTINCT r.keyword) FROM sightings s JOIN requests r ON r.id = s.request_id
                         WHERE s.offer_id = o.id AND r.run_id <= :run) AS keywords, {_CLUSTER_AND_POSTING}
            FROM offers o JOIN cur ON cur.offer_id = o.id JOIN clusters c ON c.id = o.cluster_id
            {"WHERE o.id = :offer" if offer_id else ""} ORDER BY o.id""", run_id, offer=offer_id).fetchall()

    def unevaluated(self, run_id: int) -> int:
        """Offers of the current state as of `run_id` with no verdict of that run (stored before they became
        current, or by a neetscape that evaluated only the run's sightings); `neetscape eval` settles them."""
        return self._with_current(f"SELECT COUNT(*) FROM cur WHERE NOT {has_verdict('cur.offer_id')}", run_id).fetchone()[0]

    def _with_current(self, sql: str, run_id: int, **params) -> sqlite3.Cursor:
        """Execute `sql` after the current-state CTEs as of `run_id` (`_CURRENT_CTE`, ending in `cur(offer_id)`);
        `:run` is bound to `run_id`, `params` to their own names."""
        return self.db.execute(f"WITH {_CURRENT_CTE} {sql}", {"run": run_id, **params})

    def run_offers(self, run_id: int | None, offer_id: int | None = None) -> list[sqlite3.Row]:
        """Offers sighted in a run (any run when `run_id` is None), optionally one offer, with the keywords of
        the requests that found them (`keywords`), their cluster's first run (`cluster_first_run`) and the fetched
        posting text (`posting`, NULL until `details`)."""
        return self.q(f"""
            SELECT o.*, GROUP_CONCAT(DISTINCT r.keyword) AS keywords, {_CLUSTER_AND_POSTING}
            FROM offers o JOIN sightings s ON s.offer_id = o.id JOIN requests r ON r.id = s.request_id
            JOIN clusters c ON c.id = o.cluster_id
            WHERE (? IS NULL OR r.run_id = ?) {"AND o.id = ?" if offer_id else ""} GROUP BY o.id""",
                      run_id, run_id, *([offer_id] if offer_id else []))

    # ---------------------------------------------------------------- evals, details, marks
    def save_evals(self, run_id: int, passed: list[tuple[int, str, int, str]], rejected: list[tuple[int, str, str]] = ()) -> None:
        """Replace the run's verdicts: `passed` (offer id, search id, score, why json), `rejected` (offer id,
        search id, reasons)."""
        for table in ("evals", "rejections"):
            self.db.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
        self.db.executemany("INSERT INTO evals(run_id, offer_id, search_id, score, why) VALUES (?,?,?,?,?)",
                            [(run_id, *r) for r in passed])
        self.db.executemany("INSERT INTO rejections(run_id, offer_id, search_id, reasons) VALUES (?,?,?,?)",
                            [(run_id, *r) for r in rejected])
        self.db.commit()

    def verdicts(self, run_id: int, offer_id: int) -> dict[str, list[str]]:
        """Stored verdicts of a run on one offer: search id -> failing reasons ([] = passes)."""
        rows = self.q("""SELECT search_id, '' AS reasons FROM evals WHERE run_id=? AND offer_id=?
                         UNION ALL SELECT search_id, reasons FROM rejections WHERE run_id=? AND offer_id=?""",
                      run_id, offer_id, run_id, offer_id)
        return {r["search_id"]: r["reasons"].split("; ") if r["reasons"] else [] for r in rows}

    def save_detail(self, offer_id: int, status: int, text: str, jsonld: dict, hints: dict) -> None:
        """Store an offer's posting (replacing an earlier one); a 404/410 marks the offer gone."""
        self.db.execute("INSERT OR REPLACE INTO details VALUES (?,?,?,?,?,?)",
                        (offer_id, now(), status, text, json.dumps(jsonld, ensure_ascii=False), json.dumps(hints, ensure_ascii=False)))
        if status in GONE:
            self.db.execute("UPDATE offers SET gone_at=? WHERE id=? AND gone_at IS NULL", (now(), offer_id))
        self.db.commit()

    def posted_clusters(self) -> set[int]:
        """Clusters (jobs) of which some offer has a stored posting with text."""
        return {r[0] for r in self.q(f"SELECT DISTINCT o.cluster_id FROM details d JOIN offers o ON o.id = d.offer_id WHERE {_POSTING_OK}")}

    def needs_posting(self, offer_id: int) -> bool:
        """No posting with text stored yet and the offer page was not found gone; a failed or blocked fetch may
        be retried."""
        return not self.q(f"SELECT 1 FROM details d WHERE d.offer_id = ? AND ({_POSTING_OK} OR d.http_status IN "
                          f"({','.join(map(str, GONE))}))", offer_id)

    def board_stats(self, run_id: int) -> list[sqlite3.Row]:
        """Per board of a run: requests `n`, `pages`, `found`, `complete` and `errors` (requests that failed)."""
        return self.q("""SELECT board, COUNT(*) n, SUM(pages) pages, SUM(found) found, SUM(complete) complete,
                         SUM(error != '') errors FROM requests WHERE run_id=? GROUP BY board""", run_id)

    def page_limited(self, run_id: int) -> list[dict]:
        """Requests of a run that stopped at a page limit, so the board's listing may go on beyond the last page
        fetched (requests also over a board's result cap are left to `capped`). `deliberate`: a `--limit-pages N`
        below the board's `max_pages` was the limit (`PAGE_LIMIT_ASKED`); otherwise the board's `max_pages` was."""
        rows = self.q(f"SELECT board, keyword, params_json, pages, stop_reason LIKE '{PAGE_LIMIT_ASKED}%' AS deliberate "
                      f"FROM requests WHERE run_id=? AND stop_reason LIKE '{PAGE_LIMIT}%' AND NOT {_CAPPED} ORDER BY id", run_id)
        return [dict(r) | {"deliberate": bool(r["deliberate"])} for r in rows]

    def capped(self, run_id: int) -> list[sqlite3.Row]:
        """Requests of a run over the board's result cap that could not be split: offers beyond the cap are missing."""
        return self.q(f"SELECT board, keyword, params_json, stop_reason FROM requests WHERE run_id=? AND {_CAPPED}", run_id)

    @staticmethod
    def _is_id(ref: str | int) -> bool:
        return isinstance(ref, int) or str(ref).isdigit()

    def offer(self, ref: str | int) -> sqlite3.Row | None:
        """An offer by id, URL or board key."""
        if self._is_id(ref):
            return self._one("SELECT * FROM offers WHERE id=?", int(ref))
        return self._one("SELECT * FROM offers WHERE url=? OR key=?", ref, ref)

    def mark(self, ref: str | int, status: str, note: str = "") -> sqlite3.Row:
        """Record a decision on an offer (by id, URL or key) or on any URL found elsewhere."""
        if status not in MARK_STATUSES:
            raise ValueError(f"status must be one of {MARK_STATUSES}")
        o = self.offer(ref)
        if o is None and self._is_id(ref):
            raise ValueError(f"no offer with id {ref}")
        url = o["url"] if o else str(ref)
        self.db.execute("INSERT INTO marks(url, offer_id, status, note, at) VALUES (?,?,?,?,?)",
                        (url, o["id"] if o else None, status, note, now()))
        self.db.commit()
        return self._one("SELECT * FROM tracked WHERE url=?", url)

    def tracked(self, run_id: int | None = None, include_hidden: bool = True) -> list[sqlite3.Row]:
        """Latest mark per URL with the offer's title and company; `listed` says whether it is in the current
        state as of `run_id` ("yes"), marked "gone", or "no longer seen" (its board's latest crawl did not find
        it). `include_hidden=False` leaves out rejected/ignored marks."""
        hide = "" if include_hidden else "WHERE t.status NOT IN (" + ",".join(f"'{s}'" for s in HIDDEN) + ")"
        return self._with_current(f"""
            SELECT t.*, o.title, o.company,
                   CASE WHEN o.id IN (SELECT offer_id FROM cur) THEN 'yes' WHEN o.gone_at IS NOT NULL THEN 'gone'
                        ELSE 'no longer seen' END AS listed
            FROM tracked t LEFT JOIN offers o ON o.url = t.url {hide} ORDER BY t.at""", run_id or 0).fetchall()
