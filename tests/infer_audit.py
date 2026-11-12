"""Audit the inference layer on a real database (a developer tool, not a test: no network, no model, seconds).

    python tests/infer_audit.py DB --dump before.json          # decisions of the current code
    python tests/infer_audit.py DB --diff before.json          # what changed since the dump, grouped
    python tests/infer_audit.py DB --coverage                  # unknown share per field and board
    python tests/infer_audit.py DB --dump-stored before.json   # the stored fields, read without migrating
    python tests/infer_audit.py DB --rederive before.json      # derive every offer again, diff the stored fields

Text inference is read from each stored offer's card text and title, and the posting hints from each stored
posting, exactly as the crawl and `details` read them. Work on a copy of the database: opening it migrates it.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neetscape import country as countries, infer  # noqa: E402

FIELDS = ("mode", "worktime", "contracts", "level")


def _languages(board: str) -> tuple:
    from neetscape.boards import REGISTRY
    b = REGISTRY.get(board)
    return countries.languages(countries.text_country(b.caps.country if b else "", "pl"))


def decisions(db: sqlite3.Connection) -> dict:
    rows = db.execute("SELECT o.id, o.board, o.title, o.company, o.category, o.skills, o.pay_text, o.snippet, o.locations, "
                      "d.text posting FROM offers o LEFT JOIN details d ON d.offer_id = o.id").fetchall()
    out = {}
    for r in rows:
        langs = _languages(r["board"])
        locations = " ".join(json.loads(r["locations"] or "[]"))
        text = " ".join([r["title"] or "", r["company"] or "", r["category"] or "", r["skills"] or "", r["pay_text"] or "",
                         r["snippet"] or "", locations])
        d = {"mode": infer.mode_from_text(text, langs), "worktime": infer.worktime_from_text(text, langs),
             "contracts": ",".join(infer.contracts_from_text(text, langs)), "level": infer.level_from_text(r["title"] or "", langs)}
        posting = r["posting"] or ""
        if posting and not posting.startswith("ERROR"):
            d["hints"] = json.dumps(infer.hints(posting, langs), sort_keys=True)
            d["posting_mode"] = infer.mode_from_text(posting, langs)
            d["posting_worktime"] = infer.worktime_from_text(posting, langs)
            d["posting_contracts"] = ",".join(infer.contracts_from_text(posting, langs))
        out[str(r["id"])] = {"title": r["title"], "board": r["board"], **d}
    return out


def diff(before: dict, after: dict, sample: int = 5) -> int:
    groups: dict = defaultdict(list)
    for oid, b in before.items():
        a = after.get(oid, {})
        for k, v in b.items():
            if k in ("title", "board"):
                continue
            if a.get(k) != v:
                groups[(k, v, a.get(k))].append(b["title"])
    total = sum(len(v) for v in groups.values())
    print(f"changed decisions: {total}")
    for (k, old, new), titles in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(titles):6}  {k}: {old!r} -> {new!r}")
        for t in titles[:sample]:
            print(f"            {t[:80]}")
    return total


def stored(db: sqlite3.Connection) -> dict:
    return {str(r["id"]): {"title": r["title"], "board": r["board"], **{f: r[f] for f in FIELDS}}
            for r in db.execute(f"SELECT id, title, board, {', '.join(FIELDS)} FROM offers")}


def coverage(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT board, mode, worktime, contracts, level FROM offers WHERE gone_at IS NULL").fetchall()
    by: dict = defaultdict(Counter)
    for r in rows:
        c = by[r["board"]]
        c["n"] += 1
        for f in FIELDS:
            c[f] += r[f] in ("unknown", "", None)
    print(f"{'board':14} {'offers':>7} " + " ".join(f"{f:>10}" for f in FIELDS) + "   (unknown %)")
    for board, c in sorted(by.items(), key=lambda kv: -kv[1]["n"]):
        print(f"{board:14} {c['n']:7} " + " ".join(f"{100 * c[f] / c['n']:10.0f}" for f in FIELDS))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dump")
    g.add_argument("--diff")
    g.add_argument("--coverage", action="store_true")
    g.add_argument("--dump-stored")
    g.add_argument("--rederive")
    a = ap.parse_args()
    if a.dump_stored:
        raw = sqlite3.connect(a.db)
        raw.row_factory = sqlite3.Row
        Path(a.dump_stored).write_text(json.dumps(stored(raw), ensure_ascii=False))
        print("dumped", a.dump_stored)
        return
    from neetscape.store import Store
    if a.rederive:
        import time
        store = Store(a.db)
        store.db.row_factory = sqlite3.Row
        t0 = time.time()
        n = store.rederive()
        print(f"rederived: {n} offers changed in {time.time() - t0:.1f}s")
        sys.exit(1 if diff(json.loads(Path(a.rederive).read_text()), stored(store.db)) else 0)
    db = Store(a.db).db
    db.row_factory = sqlite3.Row
    if a.coverage:
        coverage(db)
    elif a.dump:
        Path(a.dump).write_text(json.dumps(decisions(db), ensure_ascii=False))
        print("dumped", a.dump)
    else:
        sys.exit(1 if diff(json.loads(Path(a.diff).read_text()), decisions(db)) else 0)


if __name__ == "__main__":
    main()
