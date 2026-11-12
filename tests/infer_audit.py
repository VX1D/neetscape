"""Audit the inference layer on a real database (a developer tool, not a test: no network, no model, seconds).

    python tests/infer_audit.py DB --dump before.json          # decisions of the current code
    python tests/infer_audit.py DB --diff before.json          # what changed since the dump, grouped
    python tests/infer_audit.py DB --coverage                  # unknown share per field and board
    python tests/infer_audit.py DB --dump-stored before.json   # the stored fields, read without migrating
    python tests/infer_audit.py DB --rederive before.json      # derive every offer again, diff the stored fields
    python tests/infer_audit.py DB --agreement                 # domain of the title alone vs the board's category alone
    python tests/infer_audit.py DB --suggest [--min 15]        # vocabulary candidates and the unread long tail

Text inference is read from each stored offer's card text and title, and the posting hints from each stored
posting, exactly as the crawl and `details` read them. Work on a copy of the database: opening it migrates it.
"""
from __future__ import annotations

import argparse
import functools
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neetscape import country as countries, infer, lang  # noqa: E402

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


# --- vocabularies: the title's reading against the board's category ------------------------------------------
# Nothing here is language-specific. A title's language is read with the packs themselves, its words are split on
# Unicode word characters (or by the pack's optional `TITLE_TOKENS(title) -> [word]` hook, e.g. for compounds),
# and stop words are measured: a word seen with many values of a field says nothing about it.
_WORD = re.compile(r"[^\W_]+[+#]*")


@functools.lru_cache(maxsize=None)
def _hook(code: str):
    return getattr(lang.pack(code), "TITLE_TOKENS", None) if code in lang.available() else None


def _words(title: str, code: str) -> list[str]:
    """Words of a title, lower-cased as `re.I` matches them (casefold would turn ß into ss, which the packs'
    patterns do not match); numbers and one-letter words dropped. `code`: a pack, whose `TITLE_TOKENS` is used
    when it has one."""
    title = unicodedata.normalize("NFC", title)
    hook = _hook(code)
    words = hook(title) if hook else _WORD.findall(title)
    return [w for w in (w.lower() for w in words) if len(w) > 1 and not w.isdigit()]


def _tokens(words: list[str], stop: frozenset = frozenset()) -> list[str]:
    """Words not in `stop`, then the bigrams of adjacent kept words."""
    kept = [w for w in words if w not in stop]
    return list(dict.fromkeys(kept + [f"{a} {b}" for a, b in zip(kept, kept[1:])]))


@functools.lru_cache(maxsize=None)
def _pack_hits(title: str, code: str) -> int:
    """How many of a pack's own values of the fields a title names (function, domain, level, mode) it matches."""
    return sum(1 for fld in ("function", "domain", "level", "mode") for _, _, rx in infer._lexicon((code,))[fld] if rx.pattern and rx.search(title))


def assign_languages(recs: list[dict], share: float = 0.7) -> None:
    """`lang` of every offer: the language its title is in, among the offer's languages (its country's packs).
    First the pack whose vocabulary the title matches most; titles no pack wins are read by their words, weighted
    by how often each word occurs in titles of each language decided so; still undecided: "pl|en", ambiguous."""
    for r in recs:
        if len(r["langs"]) == 1:
            r["lang"] = r["langs"][0]
            continue
        hits = sorted(((_pack_hits(r["title"], c), c) for c in r["langs"]), reverse=True)
        r["lang"] = hits[0][1] if hits[0][0] > hits[1][0] else None
    seen: dict = defaultdict(Counter)
    for r in recs:
        if r["lang"]:
            for w in set(_words(r["title"], r["lang"])):
                seen[w][r["lang"]] += 1
    for r in recs:
        if r["lang"]:
            continue
        mass = Counter()
        for w in set(_words(r["title"], "")):
            n = sum(seen[w].values())
            if n >= 5:
                for c in r["langs"]:
                    mass[c] += seen[w][c] / n
        best = mass.most_common(1)
        r["lang"] = best[0][0] if best and best[0][1] >= share * sum(mass.values()) else "|".join(r["langs"])


def target(code: str) -> str:
    return (f"neetscape/lang/{code}.py" if "|" not in code
            else "title language ambiguous: " + " or ".join(f"neetscape/lang/{c}.py" for c in code.split("|")))


def _read(fld: str, title: str, category: str, langs) -> tuple[str, str]:
    """(`fld` read from the title alone, from the category alone), as `infer.derive` reads each."""
    m = infer._QUALIFIER.search(title)
    head, qual = (title[:m.start()], title[m.start():]) if m and m.start() > 0 else (title, "")
    t = infer._decide(fld, infer._scan(fld, head, langs, "title") + infer._scan(fld, qual, langs, "qualifier"))[0]
    c = infer._decide(fld, infer._scan(fld, category.replace("-", " "), langs, "category"))[0]
    return t, c


def readings(store) -> list[dict]:
    """Every offer: title, category (the board's and its requests', as `Store.rederive` passes it), whether it
    is current, its languages (`langs`, the country's packs), the language of its title (`lang`), and the function
    and domain of its title and of its category."""
    from neetscape.boards import REGISTRY
    home = store.run_country() or "pl"
    rows = store.db.execute("""
        SELECT o.board, o.country, o.title, o.category, o.gone_at IS NULL AS current,
               (SELECT GROUP_CONCAT(DISTINCT json_extract(r.params_json, '$.category')) FROM sightings s
                JOIN requests r ON r.id = s.request_id WHERE s.offer_id = o.id) AS request_category
        FROM offers o""").fetchall()
    out = []
    for r in rows:
        board = REGISTRY.get(r["board"])
        langs = countries.languages(r["country"] or countries.text_country(board.caps.country if board else "", home))
        title, category = r["title"] or "", " ".join(filter(None, (r["category"], r["request_category"])))
        rec = {"title": title, "category": category, "current": bool(r["current"]), "langs": lang.with_english(langs)}
        for fld in ("function", "domain"):
            rec[fld], rec["cat_" + fld] = _read(fld, title, category, langs)
        out.append(rec)
    assign_languages(out)
    return out


def _examples(titles, k: int = 3) -> list[str]:
    return list(dict.fromkeys(titles))[:k]


def agreement(recs: list[dict]) -> dict:
    both = [r for r in recs if r["domain"] != "unknown" and r["cat_domain"] != "unknown"]
    t, c, tp = Counter(r["domain"] for r in both), Counter(r["cat_domain"] for r in both), Counter()
    pairs: dict = defaultdict(list)
    for r in both:
        if r["domain"] == r["cat_domain"]:
            tp[r["domain"]] += 1
        else:
            pairs[(r["domain"], r["cat_domain"])].append(r["title"])
    agree, current = sum(tp.values()), [r for r in recs if r["current"]]
    return {
        "with_category": sum(bool(r["category"]) for r in recs),
        "category_domain": sum(r["cat_domain"] != "unknown" for r in recs),
        "both": len(both), "agree": agree, "agreement": agree / len(both) if both else 0.0,
        "domains": {d: {"title": t[d], "category": c[d], "agree": tp[d], "precision": tp[d] / t[d] if t[d] else 0.0,
                        "recall": tp[d] / c[d] if c[d] else 0.0} for d in sorted(set(t) | set(c), key=lambda d: -c[d])},
        "confusions": [{"title": a, "category": b, "n": len(v), "examples": _examples(v)}
                       for (a, b), v in sorted(pairs.items(), key=lambda kv: -len(kv[1]))[:20]],
        "current": len(current), "current_no_domain": sum(r["domain"] == "unknown" for r in current),
        "languages": {code: {"both": sum(r["lang"] == code for r in both),
                             "agree": sum(r["lang"] == code and r["domain"] == r["cat_domain"] for r in both),
                             "current": sum(r["lang"] == code for r in current),
                             "current_no_domain": sum(r["lang"] == code and r["domain"] == "unknown" for r in current)}
                      for code, _ in Counter(r["lang"] for r in recs).most_common()},
    }


def print_agreement(a: dict) -> None:
    print(f"offers with a category: {a['with_category']}; the category gives a domain: {a['category_domain']}; "
          f"the title too: {a['both']}")
    print(f"agreement: {a['agree']}/{a['both']} = {100 * a['agreement']:.1f}%")
    print(f"\n{'domain':14} {'title':>6} {'categ':>6} {'agree':>6} {'prec':>6} {'recall':>6}")
    for d, x in a["domains"].items():
        print(f"{d:14} {x['title']:6} {x['category']:6} {x['agree']:6} {100 * x['precision']:5.0f}% {100 * x['recall']:5.0f}%")
    print("\ntop confusions (title -> category)")
    for x in a["confusions"]:
        print(f"  {x['n']:6}  {x['title']} -> {x['category']}")
        for e in x["examples"]:
            print(f"            {e[:90]}")
    pct = lambda n, d: f"{100 * n / d:5.1f}%" if d else "    -"  # noqa: E731
    print(f"\ncurrent offers whose title gives no domain: {a['current_no_domain']}/{a['current']} = "
          f"{pct(a['current_no_domain'], a['current']).strip()}")
    print(f"\nper title language    {'both':>6} {'agree':>6} {'agreem':>6} {'current':>8} {'no domain':>9}")
    for code, x in a["languages"].items():
        print(f"{code:20} {x['both']:6} {x['agree']:6} {pct(x['agree'], x['both'])} {x['current']:8} "
              f"   {pct(x['current_no_domain'], x['current'])}")


def suggest(recs: list[dict], min_support: int = 15, min_precision: float = 0.8, top: int = 60) -> dict:
    """Per field (domain, function) and title language (the pack a suggestion goes to): (a) `candidates`, tokens of
    titles the field's patterns do not read, with the category's value they predict; (b) `frequent`, the tokens
    of current offers neither title nor category reads."""
    out = {}
    words = [_words(r["title"], r["lang"]) for r in recs]
    for fld in ("domain", "function"):
        cat = "cat_" + fld
        spread: dict = defaultdict(set)  # word -> the field's values in titles that read one
        for r, ws in zip(recs, words):
            if r[fld] != "unknown":
                for w in ws:
                    spread[w].add(r[fld])
        n_values = len({r[fld] for r in recs} - {"unknown"})
        stop = frozenset(w for w, vs in spread.items() if len(vs) >= max(3, n_values / 2))
        by_tok: dict = defaultdict(Counter)  # (lang, token) -> category values
        ex: dict = defaultdict(list)
        freq, ex_b, unread = Counter(), defaultdict(list), Counter()
        for r, ws in zip(recs, words):
            if r[fld] != "unknown":
                continue
            if r[cat] != "unknown":
                for tok in _tokens(ws, stop):
                    by_tok[(r["lang"], tok)][r[cat]] += 1
                    ex[(r["lang"], tok, r[cat])].append(r["title"])
            elif r["current"]:
                unread[r["lang"]] += 1
                for tok in _tokens(ws, stop):
                    freq[(r["lang"], tok)] += 1
                    ex_b[(r["lang"], tok)].append(r["title"])
        cands: dict = defaultdict(lambda: defaultdict(list))  # lang -> value -> tokens
        for (code, tok), cnt in by_tok.items():
            n, (value, hits) = sum(cnt.values()), cnt.most_common(1)[0]
            if n >= min_support and hits / n >= min_precision:
                e = ex[(code, tok, value)]
                cands[code][value].append({"token": tok, "support": n, "precision": hits / n, "titles": len(set(e)),
                                           "examples": _examples(e)})
        res = {}
        for code in sorted(set(cands) | set(unread), key=lambda c: -unread[c] - sum(map(len, cands[c].values()))):
            vals = {v: sorted(ts, key=lambda x: (-x["support"], x["token"])) for v, ts in cands[code].items()}
            res[code] = {
                "pack": target(code),
                "candidates": dict(sorted(vals.items(), key=lambda kv: -sum(x["support"] for x in kv[1]))),
                "unread": unread[code],
                "frequent": [{"token": t, "n": n, "examples": _examples(ex_b[(c, t)])}
                             for (c, t), n in freq.most_common() if c == code][:top]}
        out[fld] = {"stop_words": len(stop), "languages": res}
    return out


def print_suggest(s: dict, min_support: int) -> None:
    for fld, x in s.items():
        print(f"##### {fld}  ({x['stop_words']} words measured as stop words: seen with half of the {fld} values)")
        for code, y in x["languages"].items():
            n = sum(len(v) for v in y["candidates"].values())
            print(f"\n=== {fld} [{code}] -> {y['pack']}")
            print(f"--- (a) {n} candidates: tokens of titles with no {fld}; support >= {min_support} offers whose category "
                  f"gives one, precision >= 80%   (token, support, precision, distinct titles, examples)")
            for value, toks in y["candidates"].items():
                print(f"[{value}]")
                for t in toks:
                    print(f"  {t['token']:30} {t['support']:5} {100 * t['precision']:4.0f}% {t['titles']:5}  | "
                          + " | ".join(e[:50] for e in t["examples"]))
            print(f"--- (b) {y['unread']} current offers with no {fld} in the title or the category; most frequent tokens")
            for t in y["frequent"]:
                print(f"  {t['n']:6}  {t['token']:30} | " + " | ".join(e[:50] for e in t["examples"]))
        print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dump")
    g.add_argument("--diff")
    g.add_argument("--coverage", action="store_true")
    g.add_argument("--dump-stored")
    g.add_argument("--rederive")
    g.add_argument("--agreement", action="store_true")
    g.add_argument("--suggest", action="store_true")
    ap.add_argument("--min", type=int, default=15, help="--suggest: least support of a candidate token")
    ap.add_argument("--json", help="--agreement/--suggest: also write the result as JSON")
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
    store = Store(a.db)
    db = store.db
    db.row_factory = sqlite3.Row
    if a.agreement or a.suggest:
        recs = readings(store)
        res = agreement(recs) if a.agreement else suggest(recs, a.min)
        (print_agreement(res) if a.agreement else print_suggest(res, a.min))
        if a.json:
            Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1))
        return
    if a.coverage:
        coverage(db)
    elif a.dump:
        Path(a.dump).write_text(json.dumps(decisions(db), ensure_ascii=False))
        print("dumped", a.dump)
    else:
        sys.exit(1 if diff(json.loads(Path(a.diff).read_text()), decisions(db)) else 0)


if __name__ == "__main__":
    main()
