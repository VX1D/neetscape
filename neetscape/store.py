"""SQLite store: every crawled offer, where and when it was seen, evaluations, details and the user's marks.

One database per output directory (`runs/neetscape.db`), holding one country's searches: pay is stored
per month in that country's currency (use a separate `--out` per country). Schema changes are ordered
migrations (SQL scripts or functions) applied according to `PRAGMA user_version`; existing migrations are
never edited, new ones are appended.

Verdicts of a run: `evals` holds the offers that pass a search (score, matched rules, tags), `rejections`
(v3) the ones that fail it with their reasons joined by `; `, e.g.

    SELECT reasons, COUNT(*) FROM rejections WHERE run_id = (SELECT MAX(id) FROM runs) GROUP BY 1 ORDER BY 2 DESC
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

from .model import Offer, canonical_contract, norm, norm_company


def _rename_contracts(db: sqlite3.Connection) -> None:
    """v2: contract `uop` became `employment` (one vocabulary for every country)."""
    for oid, contracts in db.execute("SELECT id, contracts FROM offers WHERE contracts != ''").fetchall():
        new = ",".join(sorted({canonical_contract(c) for c in contracts.split(",") if c}))
        if new != contracts:
            db.execute("UPDATE offers SET contracts=? WHERE id=?", (new, oid))


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
]

MARK_STATUSES = ("shortlisted", "applied", "interview", "offer", "rejected", "ignored")
HIDDEN = ("rejected", "ignored")
GONE = (404, 410)  # HTTP statuses of a posting that mark its offer gone
_POSTING_OK = "d.http_status = 200 AND d.text != ''"  # a stored posting with text (failures keep status 0 / 4xx)


_EMPTY = (None, "", "unknown", "[]")  # stored values that mean "the board did not say"


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def request_key(board: str, keyword: str | None, params: dict) -> str:
    raw = json.dumps([board, keyword, sorted(params.items())], ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


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
        return self.db.execute(sql, args).fetchall()

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
        return self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()

    def last_run(self, status: str | None = None) -> int | None:
        sql = "SELECT id FROM runs" + (" WHERE status=?" if status else "") + " ORDER BY id DESC LIMIT 1"
        row = self.db.execute(sql, (status,) if status else ()).fetchone()
        return row[0] if row else None

    def run_country(self, run_id: int | None = None) -> str | None:
        """Country of the profile of a run (default: the latest run that has a profile)."""
        sql = "SELECT profile_json FROM runs WHERE profile_json NOT IN ('', '{}')" + (" AND id=?" if run_id else "") + " ORDER BY id DESC LIMIT 1"
        row = self.db.execute(sql, (run_id,) if run_id else ()).fetchone()
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
        return {r[0] for r in self.q("SELECT req_key FROM requests WHERE run_id=? AND status='done'", run_id)}

    # ---------------------------------------------------------------- offers
    def _cluster(self, o: Offer, run_id: int) -> int:
        """Same title and compatible company = same job. An unknown company joins a cluster whose company
        name appears in the offer's card text."""
        t, c = o.title_norm, norm_company(o.company)
        if c:
            key = f"{t}|{c}"
        else:
            hay = norm(o.snippet + " " + o.title)
            cands = self.q("SELECT dedup_key FROM clusters WHERE dedup_key LIKE ?", t + "|%")
            match = next((r[0] for r in cands if r[0].split("|", 1)[1] and r[0].split("|", 1)[1] in hay), None)
            key = match or f"{t}|"
        row = self.db.execute("SELECT id FROM clusters WHERE dedup_key=?", (key,)).fetchone()
        if row:
            return row[0]
        return self.db.execute("INSERT INTO clusters(dedup_key, first_seen_run) VALUES (?,?)", (key, run_id)).lastrowid

    @staticmethod
    def _offer_values(o: Offer) -> dict:
        return dict(url=o.url, title=o.title, title_norm=o.title_norm, company=o.company, mode=o.mode,
                    locations=json.dumps(o.locations, ensure_ascii=False), worktime=o.worktime,
                    contracts=",".join(sorted({canonical_contract(c) for c in o.contracts})), level=o.level,
                    category=o.category, skills=", ".join(o.skills), pay_text=o.pay_text, pay_period=o.pay_period,
                    pay_min=o.pay_min, pay_max=o.pay_max, published=o.published.isoformat() if o.published else None,
                    promoted=int(o.promoted), snippet=o.snippet[:1000], description=o.description)

    def _upsert(self, o: Offer, run_id: int) -> tuple[int, bool]:
        """Insert or update one offer; returns (offer id, known from an earlier run). An update keeps stored
        values the new sighting lacks."""
        values = self._offer_values(o)
        cur = self.db.execute("SELECT * FROM offers WHERE board=? AND key=?", (o.board, o.key)).fetchone()
        if cur:
            merged = {k: (cur[k] if v in _EMPTY else v) for k, v in values.items()}
            self.db.execute(f"UPDATE offers SET {', '.join(f'{k}=?' for k in merged)}, last_seen_run=?, gone_at=NULL WHERE id=?",
                            (*merged.values(), run_id, cur["id"]))
            return cur["id"], cur["first_seen_run"] < run_id
        cols = ", ".join(values)
        offer_id = self.db.execute(
            f"INSERT INTO offers(board, key, {cols}, cluster_id, first_seen_run, last_seen_run) "
            f"VALUES (?,?,{','.join('?' * len(values))},?,?,?)",
            (o.board, o.key, *values.values(), self._cluster(o, run_id), run_id, run_id)).lastrowid
        return offer_id, False

    def ingest(self, offers: list[Offer], run_id: int, request_id: int, page: int) -> tuple[int, set[str]]:
        """Upsert offers and record the sighting. Returns (offers new to this request, keys of the offers
        known from earlier runs)."""
        new_in_request, known = 0, set()
        for o in offers:
            offer_id, seen_before = self._upsert(o, run_id)
            if seen_before:
                known.add(o.key)
            new_in_request += self.db.execute("INSERT OR IGNORE INTO sightings(offer_id, request_id, page) VALUES (?,?,?)",
                                              (offer_id, request_id, page)).rowcount
        self.db.commit()
        return new_in_request, known

    def mark_gone(self, run_id: int) -> int:
        """Offers seen earlier under a request that completed in this run, but not seen by it now."""
        rows = self.q("""
            SELECT DISTINCT s.offer_id FROM sightings s JOIN requests old ON old.id = s.request_id
            JOIN requests cur ON cur.req_key = old.req_key AND cur.run_id = ? AND cur.complete = 1
            WHERE old.run_id < ? AND NOT EXISTS (
                SELECT 1 FROM sightings s2 WHERE s2.offer_id = s.offer_id AND s2.request_id = cur.id)""", run_id, run_id)
        stamp = now()
        gone = sum(self.db.execute("UPDATE offers SET gone_at=? WHERE id=? AND gone_at IS NULL AND last_seen_run < ?",
                                   (stamp, r[0], run_id)).rowcount for r in rows)
        self.db.commit()
        return gone

    def run_offers(self, run_id: int | None, offer_id: int | None = None) -> list[sqlite3.Row]:
        """Offers sighted in a run (any run when `run_id` is None), optionally one offer, with the keywords of
        the requests that found them (`keywords`), their cluster's first run (`cluster_first_run`) and the fetched
        posting text (`posting`, NULL until `details`)."""
        return self.q(f"""
            SELECT o.*, GROUP_CONCAT(DISTINCT r.keyword) AS keywords, c.first_seen_run AS cluster_first_run,
                   (SELECT d.text FROM details d WHERE d.offer_id = o.id) AS posting
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

    @staticmethod
    def _is_id(ref: str | int) -> bool:
        return isinstance(ref, int) or str(ref).isdigit()

    def offer(self, ref: str | int) -> sqlite3.Row | None:
        """An offer by id, URL or board key."""
        if self._is_id(ref):
            return self.db.execute("SELECT * FROM offers WHERE id=?", (int(ref),)).fetchone()
        return self.db.execute("SELECT * FROM offers WHERE url=? OR key=?", (ref, ref)).fetchone()

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
        return self.db.execute("SELECT * FROM tracked WHERE url=?", (url,)).fetchone()

    def tracked(self, run_id: int | None = None, hidden: bool = True) -> list[sqlite3.Row]:
        """Latest mark per URL with the offer's title and company; `listed` says whether it was seen in
        `run_id` ("yes", "gone", "not seen in this run"). `hidden=False` leaves out rejected/ignored marks."""
        return self.q(f"""
            SELECT t.*, o.title, o.company,
                   CASE WHEN o.gone_at IS NOT NULL THEN 'gone' WHEN o.last_seen_run = ? THEN 'yes'
                        ELSE 'not seen in this run' END AS listed
            FROM tracked t LEFT JOIN offers o ON o.url = t.url
            {"" if hidden else f"WHERE t.status NOT IN ({','.join('?' * len(HIDDEN))})"} ORDER BY t.at""",
                      run_id, *(() if hidden else HIDDEN))
