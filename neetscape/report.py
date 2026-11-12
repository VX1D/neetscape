"""Listings and reports, all read from the store.

`listing()` is the single source for `neetscape list`, listing.tsv, offers.csv, REPORT.md, REPORT.html and
`details --top`. The listing of run N is the current state as of run N, judged by the profile:

    every offer presumed still listed after run N (its board's latest crawl up to run N saw it, or repeated
    a request that saw it before without reaching that request's end, and it is not marked gone), from every
    board, not only those run N crawled, that passes at least one search in the verdicts `eval` stored for
    run N; one row per cluster (the same job on several boards), clusters whose latest mark is
    rejected/ignored removed, sorted by the profile's sort keys.

`new` means the cluster was first seen in run N. The rest of a report is about run N itself: its board
table (requests, pages, errors) and its cut listings (capped, or stopped at a page limit). `--run N` shows
that run's stored state; `eval --run N` judges the state as of run N again. Pay is shown per month in the
profile country's currency, in a column named after it (`pay_pln_month`, `pay_eur_month`).
`group_by_title()` folds a listing into one row per normalised title, for triaging thousands of offers.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from collections import Counter
from pathlib import Path

from .details import detail
from .html_report import write_html
from .model import age_label, norm_company, parse_date
from .pay import pay_label
from .profile import Profile
from .store import GONE, HIDDEN, Store, has_verdict

_LISTING_SQL = f"""
    SELECT o.*, e.search_id, e.score, e.why, c.first_seen_run = :run AS is_new,
           (SELECT t.status FROM tracked t JOIN offers o3 ON o3.url = t.url
            WHERE o3.cluster_id = o.cluster_id ORDER BY t.id DESC LIMIT 1) AS mark,
           (SELECT GROUP_CONCAT(DISTINCT o2.board) FROM offers o2
            WHERE o2.cluster_id = o.cluster_id AND {has_verdict('o2.id')}) AS boards
    FROM evals e JOIN offers o ON o.id = e.offer_id JOIN clusters c ON c.id = o.cluster_id
    WHERE e.run_id = :run {{conditions}} ORDER BY o.id"""

_SORT_KEYS = {
    "score": lambda d: -d["score"],
    "new": lambda d: -d["is_new"],
    "pay": lambda d: -(d["pay_max"] or 0),
    "published": lambda d: -(parse_date(d["published"]) or dt.date.min).toordinal(),
}


def listing(store: Store, profile: Profile, run_id: int, *, search: str | None = None, new_only: bool = False,
            where_sql: str | None = None) -> list[dict]:
    """Passing offers of the current state as of a run, one per cluster: the best-scored row, with every search
    the cluster passes and the boards of its current offers. The cluster's mark is the latest mark on any of
    its offers. `new_only`: clusters first seen in the run."""
    conditions = ("AND e.search_id = :search " if search else "") + (f"AND ({where_sql})" if where_sql else "")
    best: dict[int, dict] = {}
    for r in store.db.execute(_LISTING_SQL.format(conditions=conditions), {"run": run_id, "search": search}):
        d = dict(r)
        meta = json.loads(d.pop("why") or "{}")
        d["why"], d["tags"] = meta.get("why", []), meta.get("tags", [])
        if d["mark"] in HIDDEN or (new_only and not d["is_new"]):
            continue
        cur = best.get(d["cluster_id"])
        searches = (cur["searches"] if cur else []) + [d["search_id"]]
        if cur is None or (d["score"], d["pay_max"] or 0) > (cur["score"], cur["pay_max"] or 0):
            best[d["cluster_id"]] = cur = d
        cur["searches"] = sorted(set(searches))
    return sorted(best.values(), key=lambda d: tuple(_SORT_KEYS[k](d) for k in profile.sort))


def group_by_title(rows: list[dict]) -> list[dict]:
    """One row per normalised title of a listing: how many jobs, companies and boards carry it, most first."""
    groups: dict[str, list[dict]] = {}
    for d in rows:
        groups.setdefault(d["title_norm"], []).append(d)
    out = []
    for members in groups.values():
        top_pay = max(members, key=lambda d: d["pay_max"] or 0)
        out.append({
            "title": Counter(d["title"] for d in members).most_common(1)[0][0],
            "offers": len(members),
            "companies": len({norm_company(d["company"]) for d in members if d["company"]}),
            "boards": ",".join(sorted({b for d in members for b in (d["boards"] or d["board"]).split(",")})),
            "new": sum(d["is_new"] for d in members),
            "best_pay": pay_label(top_pay),
            "ids": ",".join(str(d["id"]) for d in members[:10]),
        })
    return sorted(out, key=lambda g: -g["offers"])


def pay_column(currency: str = "PLN") -> str:
    return f"pay_{currency.lower()}_month"


def columns(currency: str = "PLN") -> list[str]:
    return ["id", "new", "score", "title", "company", pay_column(currency), "mode", "worktime", "contracts", "level", "age",
            "boards", "searches", "tags", "mark", "url"]


def _md_columns(currency: str) -> list[str]:
    return ["id", "new", "score", "title", "company", pay_column(currency), "mode", "age", "boards"]


def row_values(d: dict, currency: str = "PLN") -> dict:
    return {"id": d["id"], "new": "🆕" if d["is_new"] else "", "score": d["score"], "title": d["title"], "company": d["company"],
            pay_column(currency): pay_label(d), "mode": d["mode"], "worktime": d["worktime"], "contracts": d["contracts"],
            "level": d["level"], "age": age_label(d["published"]), "boards": d["boards"] or d["board"], "searches": ",".join(d["searches"]),
            "tags": ",".join(d["tags"]), "mark": d["mark"] or "", "url": d["url"]}


def _md_cell(value, width: int = 60) -> str:
    """A markdown table cell: `|` and line breaks would end the cell or the row."""
    return " ".join(str(value if value is not None else "").replace("|", "/").split())[:width]


def _table(vals: list[dict], cols: list[str], fmt: str, md_cols: list[str] | None = None) -> str:
    """Rows as json (every column), md (`md_cols`, cells cut to 60 characters) or tsv."""
    if fmt == "json":
        return json.dumps(vals, ensure_ascii=False, indent=1)
    if fmt == "md":
        cols = md_cols or cols
        out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        return "\n".join(out + ["| " + " | ".join(_md_cell(v[c]) for c in cols) + " |" for v in vals])
    return "\n".join(["\t".join(cols)] + ["\t".join(str(v[c]).replace("\t", " ") for c in cols) for v in vals])


def format_rows(rows: list[dict], fmt: str, currency: str = "PLN") -> str:
    return _table([row_values(d, currency) for d in rows], columns(currency), fmt, _md_columns(currency))


def format_groups(groups: list[dict], fmt: str, currency: str = "PLN") -> str:
    best = f"best_{pay_column(currency)}"
    vals = [{(best if k == "best_pay" else k): v for k, v in g.items()} for g in groups]
    return _table(vals, ["title", "offers", "companies", "boards", "new", best, "ids"], fmt)


def _run_stats(store: Store, run_id: int) -> list[str]:
    rows = store.board_stats(run_id)
    out = ["| Board | Requests | Pages | Offers | Complete | Errors |", "|---|---|---|---|---|---|"]
    out += [f"| {r['board']} | {r['n']} | {r['pages']} | {r['found']} | {r['complete']}/{r['n']} | {r['errors'] or 0} |" for r in rows]
    errs = store.q("SELECT board, keyword, error FROM requests WHERE run_id=? AND error != ''", run_id)
    if errs:
        out += ["", "Errors:"] + [f"- {e['board']} {e['keyword'] or '*'}: {e['error'][:160]}" for e in errs]
    capped = store.capped(run_id)
    if capped:  # the board shows fewer results than the request matches and could not narrow it: offers are missing
        out += ["", "Capped (offers beyond the board's result limit are missing):"] + [
            f"- {c['board']} {c['keyword'] or '*'} {c['params_json']}: {c['stop_reason'].split('capped: ')[-1]}" for c in capped]
    cut = store.page_limited(run_id)
    if cut:  # the request ended at its last allowed page, so the listing may go on: offers beyond it are missing
        out += ["", "Page limit (the listing may go on beyond the last page fetched):"] + [
            f"- {c['board']} {c['keyword'] or '*'} {c['params_json']}: {c['pages']} pages, "
            + ("--limit-pages (deliberate)" if c["deliberate"] else "the board's max_pages") for c in cut]
    return out


def _tracked_section(store: Store, run_id: int) -> list[str]:
    marked = store.tracked(run_id, hidden=False)
    if not marked:
        return []
    out = ["## Tracked offers", "", "| Status | Offer | Since | Still listed | Note |", "|---|---|---|---|---|"]
    out += [f"| {m['status']} | [{_md_cell(m['title'] or m['url'], 50).replace(']', ')')}]({_md_cell(m['url'], 2000)}) | "
            f"{m['at'][:10]} | {m['listed']} | {_md_cell(m['note'])} |" for m in marked]
    return out + [""]


def _opened_offer(d: dict, det: dict, currency: str) -> list[str]:
    h = det["hints"]
    flags = ("🆕" if d["is_new"] else "") + ("🏠" if h.get("fully_remote") else "") + ("⚠️" if h.get("hybrid") else "") \
        + ("❌" if det["status"] in GONE else "")
    listed = lambda key, label: h.get(key) and f"{label}: " + ", ".join(h[key])
    meta = [x for x in (f"pay {pay_label(d)} {currency}/mo" + (f" ({d['pay_text'][:70]})" if d["pay_text"] else ""),
                        f"{d['mode']}, {d['worktime']}, {d['contracts'] or '-'}, level {d['level']}", f"posted {age_label(d['published'])} ago",
                        listed("years", "experience"), listed("degree", "degree"), listed("languages", "languages"),
                        listed("hybrid", "mode hints")) if x]
    return [f"### {flags} #{d['id']} {d['title']} — {d['company'] or '?'} [{d['score']}]" + (f" · {d['mark']}" if d["mark"] else ""),
            f"- {d['url']} (on {d['boards'] or d['board']})", "- " + " · ".join(meta),
            f"- why: {', '.join(d['why']) or '—'} · searches: {', '.join(d['searches'])}",
            f"- text: `neetscape show {d['id']}`", ""]


def _opened_section(store: Store, rows: list[dict], currency: str) -> list[str]:
    opened = [(d, det) for d in rows if (det := detail(store, d["id"]))]
    if not opened:
        return []
    return ["## Opened offers", ""] + [line for d, det in opened for line in _opened_offer(d, det, currency)]


def write_reports(store: Store, profile: Profile, run_id: int, out_dir: Path, rows: list[dict] | None = None) -> Path:
    """Write listing.tsv, offers.csv, REPORT.md and REPORT.html of a run into `out_dir`; returns the REPORT.md path.
    `rows`: the run's `listing()` when the caller has it already."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cur = profile.currency
    rows = listing(store, profile, run_id) if rows is None else rows
    (out_dir / "listing.tsv").write_text(format_rows(rows, "tsv", cur) + "\n")
    with open(out_dir / "offers.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns(cur) + ["pay_text", "why"])
        w.writeheader()
        for d in rows:
            w.writerow(row_values(d, cur) | {"pay_text": d["pay_text"], "why": "; ".join(d["why"])})

    run = store.run(run_id)
    per_search = Counter(s for d in rows for s in d["searches"])
    L = [f"# neetscape report — run {run_id} ({run['started_at'][:16]})", ""]
    if profile.raw.get("label"):
        L += [f"Profile: **{profile.raw['label']}**", ""]
    crawled = ", ".join(r["board"] for r in store.board_stats(run_id)) or "no board"
    L += [f"Run {run_id} crawled {crawled}. The listing is the current state: every offer still listed on any board "
          "as of that board's latest crawl, judged by the profile; new = first seen in this run.", ""]
    L += _run_stats(store, run_id) + [""]
    L += [f"Offers passing the profile: **{len(rows)}** ({sum(d['is_new'] for d in rows)} new in this run). "
          + "Per search: " + ", ".join(f"{s.label} {per_search.get(s.id, 0)}" for s in profile.searches), ""]
    for s in profile.searches:
        top = [d for d in rows if s.id in d["searches"]][:15]
        if top:
            L += [f"## {s.label} — top {len(top)}", "", format_rows(top, "md", cur), ""]
    L += _tracked_section(store, run_id) + _opened_section(store, rows, cur)
    L += ["## All passing offers", "", f"See `listing.tsv` / `offers.csv` ({len(rows)} rows) or `neetscape list`.", ""]
    path = out_dir / "REPORT.md"
    path.write_text("\n".join(L) + "\n")
    write_html(store, profile, run_id, rows, out_dir / "REPORT.html")
    return path
