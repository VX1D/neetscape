"""neetscape — remote/local job offer radar for the job boards of one country (pl, de, ...).

Setup
  neetscape init [--country CC] [--preset broad|focused|local|side ...]   write profile.json (presets combine)
  neetscape check                                         validate the profile
  neetscape plan                                          show what would be fetched (no network)
  neetscape boards [--country CC]                         board capabilities
  neetscape probe BOARD [--keyword K] [--save-fixture PATH]   fetch one page, show field coverage

Run
  neetscape run [--resume] [--full] [--limit-pages N] [--boards a,b] [--record DIR]
  neetscape crawl | eval | report                         single steps on the latest run (or --run N)

Review (all read the latest run, or --run N)
  neetscape list [--search ID] [--new] [--group title] [--where SQL] [--limit N] [--format tsv|md|json]
  neetscape details --pick 12,40 | --pick-file F | --top N | --marked
  neetscape show ID                                       offer, why it passes/fails each search, posting text
  neetscape sql "SELECT ... WHERE run_id = :run"          read-only SQL on the database (:run = the run)
  neetscape mark ID|URL STATUS [--note TEXT]              shortlisted applied interview offer rejected ignored
  neetscape tracked
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import signal
import sqlite3
import sys
import threading
from pathlib import Path

from . import country as countries
from . import evaluate as ev
from . import planner, report
from . import profile as prof_mod
from .boards import REGISTRY, expand
from .boards.base import Request, country_of, min_intervals
from .boards.fetch import Limiter
from .browser import Browser
from .crawler import crawl
from .details import detail, fetch_details, route
from .log import log
from .model import Search, Where
from .store import MARK_STATUSES, Store

COMMANDS = ["init", "check", "plan", "boards", "probe", "run", "crawl", "eval", "report",
            "list", "details", "show", "sql", "mark", "tracked"]
_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


# ---------------------------------------------------------------- process lifecycle
@contextlib.contextmanager
def _signals_unwind():
    """Turn SIGTERM/SIGINT/SIGHUP into SystemExit(128 + signal) so every `with` block unwinds (the private
    browser and Xvfb are stopped, the run stays `running` for --resume). Later signals are ignored while
    unwinding."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {s: signal.getsignal(s) for s in _SIGNALS}

    def unwind(signo, _frame):
        for s in _SIGNALS:
            signal.signal(s, signal.SIG_IGN)
        raise SystemExit(128 + signo)

    for s in _SIGNALS:
        signal.signal(s, unwind)
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


class _LazyBrowser:
    """Starts the private browser on the first `ensure()`; stopped with the enclosing ExitStack."""

    def __init__(self, stack: contextlib.ExitStack, port: int):
        self.stack, self.port, self.started = stack, port, False

    def ensure(self, needed: bool = True) -> None:
        if needed and not self.started:
            self.stack.enter_context(Browser(port=self.port))
            self.started = True


def _needs_browser(boards) -> bool:
    return any(REGISTRY[b].caps.transport != "http" for b in boards)


def _details_need_browser(store: Store, ids: list[int]) -> bool:
    """Postings are fetched in the browser unless the source shipped the text, or LinkedIn / a posting API serves them."""
    return any(route(r) == "browser" for r in (store.offer(i) for i in ids) if r)


# ---------------------------------------------------------------- store, profile, run
def _db_path(a) -> Path:
    return Path(a.out) / "neetscape.db"


def _store(a, readonly: bool = False) -> Store:
    db = _db_path(a)
    if readonly and not db.exists():
        sys.exit(f"no database at {db}; run `neetscape run` first")
    return Store(db, readonly=readonly)


def _profile(a) -> prof_mod.Profile:
    try:
        p = prof_mod.load(a.profile)
    except prof_mod.ProfileError as e:
        sys.exit(f"profile error: {e}")
    if a.boards:
        p.boards = expand([b.strip() for b in a.boards.split(",")])
        bad = set(p.boards) - set(REGISTRY)
        if bad:
            sys.exit(f"unknown boards: {sorted(bad)}")
    return p


def _run_id(store: Store, a) -> int:
    """`--run`, checked to exist, else the latest run."""
    if a.run is not None:
        if not store.run(a.run):
            sys.exit(f"no run {a.run} in {store.path}")
        return a.run
    rid = store.last_run()
    if not rid:
        sys.exit("no runs yet; run `neetscape run` first")
    return rid


def _open(a, readonly: bool = False, profile: bool = True) -> tuple[Store, prof_mod.Profile | None, int]:
    """The boilerplate of commands working on one run: store, profile and run id."""
    store = _store(a, readonly)
    return store, _profile(a) if profile else None, _run_id(store, a)


def _report_dir(a, store: Store, run_id: int) -> Path:
    return Path(a.out) / f"{store.run(run_id)['started_at'][:10]}-run{run_id}"


def _money(c: countries.Country) -> dict:
    """Database currency and month of a country, as `crawl` takes them."""
    return {"fx": c.fx, "base": c.currency, "hours": c.hours_per_month, "days": c.days_per_month}


def _ids(a, store: Store, profile, run_id: int) -> list[int]:
    """Offers `details` opens: --pick, --pick-file, --marked, else the top matches (--top or `details_top`)."""
    if a.pick:
        return [int(x) for x in a.pick.split(",") if x.strip()]
    if a.pick_file:
        lines = [line.split() for line in Path(a.pick_file).read_text().splitlines()]
        return [int(w[0]) for w in lines if w and w[0].isdigit()]
    if a.marked:
        return _marked_ids(store, run_id)
    return _top_ids(store, profile, run_id, a.top or profile.details_top)


def _marked_ids(store: Store, run_id: int) -> list[int]:
    """Marked offers (not rejected/ignored), of any run, whose posting is missing (never fetched or failed)."""
    offers = (store.offer(m["url"]) for m in store.tracked(run_id, hidden=False))
    return [o["id"] for o in offers if o and store.needs_posting(o["id"])]


def _top_ids(store: Store, profile, run_id: int, top: int) -> list[int]:
    """The best `top` matches of the run scoring at least `min_score` whose job has no stored posting: postings
    are fetched once per job, so later runs open only new matches."""
    fetched = store.posted_clusters()
    rows = [d for d in report.listing(store, profile, run_id) if d["score"] >= profile.min_score and d["cluster_id"] not in fetched]
    return [d["id"] for d in rows[:top]]


def _fetch_postings(store: Store, profile, ids: list[int], port: int, limiter: Limiter, browser: _LazyBrowser) -> None:
    browser.ensure(_details_need_browser(store, ids))
    asyncio.run(fetch_details(store, ids, port, limiter, profile.retries, profile.country.code))


# ---------------------------------------------------------------- run
def _start_or_resume(a, store: Store, profile) -> tuple[int, set[str]]:
    """Run id and the request keys to skip (those already done when resuming)."""
    running = store.last_run("running") if a.resume else None
    if running:
        skip = store.done_request_keys(running)
        log(f"resuming run {running}: {len(skip)} requests already done")
        return running, skip
    before = store.run_country()
    if before and before != profile.country.code:
        sys.exit(f"{_db_path(a)} holds a {before} profile's offers (pay in {countries.get(before).currency}); "
                 f"this profile is {profile.country.code}. Use a separate --out per country.")
    return store.start_run(profile.raw, sys.argv[1:]), set()


def cmd_run(a, crawl_only: bool = False) -> None:
    """Stage 1: crawl the cards and evaluate them. Stage 2 (`review.mode: auto`): fetch the postings of the best
    matches not opened before and evaluate again with them."""
    profile = _profile(a)
    plan = planner.plan(profile)
    for w in plan.warnings:
        log("plan:", w)
    store = _store(a)
    run_id, skip = _start_or_resume(a, store, profile)
    limiter = Limiter(min_intervals(profile.min_interval))
    with contextlib.ExitStack() as stack:
        browser = _LazyBrowser(stack, a.port)
        browser.ensure(_needs_browser({r.board for r in plan.requests}))
        asyncio.run(crawl(plan.requests, {s.id: s for s in profile.searches}, store, run_id, port=a.port, limiter=limiter,
                          retries=profile.retries, limit_pages=a.limit_pages, incremental=not a.full,
                          record=Path(a.record) if a.record else None, skip_keys=skip,
                          **(_money(profile.country) | {"fx": profile.fx})))
        gone = store.mark_gone(run_id)
        if crawl_only:
            store.finish_run(run_id, "crawled")
            print(f"run {run_id} crawled; {gone} offers no longer listed. Next: neetscape eval")
            return
        counts = ev.evaluate(store, profile, run_id)
        ids = _top_ids(store, profile, run_id, profile.details_top) if profile.review_mode == "auto" else []
        if ids:
            _fetch_postings(store, profile, ids, a.port, limiter, browser)
            counts = ev.evaluate(store, profile, run_id)
    rows = report.listing(store, profile, run_id)
    path = report.write_reports(store, profile, run_id, _report_dir(a, store, run_id), rows)
    store.finish_run(run_id)
    print(f"run {run_id}: {len(rows)} offers pass the profile ({', '.join(f'{k} {v}' for k, v in counts.items())}); {gone} gone")
    print(f"report: {path}")
    if profile.review_mode == "listing":
        print(f"next: read {path.parent / 'listing.tsv'} (or `neetscape list --new`), then `neetscape details --pick ID,ID,...`")


def cmd_probe(a) -> None:
    if not a.args:
        sys.exit("usage: neetscape probe BOARD [--keyword K] [--save-fixture PATH]")
    name = a.args[0]
    board = REGISTRY.get(name)
    if not board:
        sys.exit(f"unknown board; available: {', '.join(REGISTRY)}")
    code = country_of(board)
    code = code if code in countries.codes() else (a.country or "pl")
    s = Search(id="probe", label="probe", where=Where(remote=True, country=code), keywords=(a.keyword,) if a.keyword else None)
    reqs, warns = board.requests(s)
    for w in warns:
        print("warning:", w)
    if not reqs:
        sys.exit("board cannot serve a remote search")
    r: Request = reqs[0]
    path = Path(a.out) / "probe.db"
    store = Store(path)
    try:
        run_id = store.start_run({}, ["probe"])
        with Browser(port=a.port) if board.caps.transport != "http" else contextlib.nullcontext():
            asyncio.run(crawl([r], {"probe": s}, store, run_id, port=a.port, limiter=Limiter(min_intervals()), limit_pages=1,
                              save_fixture=Path(a.save_fixture) if a.save_fixture else None, **_money(countries.get(code))))
        _print_probe(name, board.page_url(r, 1), store.run_offers(run_id), a.save_fixture)
    finally:
        store.close()
        path.unlink(missing_ok=True)


def _print_probe(name: str, url: str, rows, save_fixture: str | None) -> None:
    print(f"{name}: {len(rows)} offers from {url}")
    if save_fixture:
        print(f"raw page saved to {save_fixture}" if Path(save_fixture).exists() else "no page saved (request failed)")
    if not rows:
        return
    for f in ("title", "company", "mode", "locations", "worktime", "contracts", "level", "pay_text", "pay_max", "published", "category"):
        filled = sum(1 for o in rows if o[f] not in (None, "", "unknown", "[]"))
        print(f"  {f:<10} {100 * filled // len(rows):>3}%")
    for o in rows[:5]:
        print(f"  - {o['title'][:60]} | {o['company'][:25]} | {o['mode']} | {o['pay_text'][:30]}")


# ---------------------------------------------------------------- setup commands
def cmd_init(a) -> None:
    target = Path(a.profile)
    if target.exists():
        sys.exit(f"{target} already exists")
    names = a.preset or ["focused"]
    try:
        data = prof_mod.combine(names, a.country or "pl")
    except prof_mod.ProfileError as e:
        sys.exit(str(e))
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {target} ({data['country']}) from preset(s) {', '.join(names)}; edit it, then `neetscape check` and `neetscape plan`")


def cmd_check(a) -> None:
    p = _profile(a)
    searches = ", ".join(f"{s.id}: {s.where.describe()}, " + ("all" if s.keywords is None else f"{len(s.keywords)} phrases")
                         for s in p.searches)
    print(f"profile OK ({p.country.code}, amounts in {p.currency}): {len(p.searches)} search(es) [{searches}], "
          f"{len(p.rules)} rank rules, boards: {', '.join(p.boards)}")


def cmd_plan(a) -> None:
    print(planner.describe(planner.plan(_profile(a))))


def cmd_boards(a) -> None:
    if a.country and a.country not in countries.codes() + ["intl"]:
        sys.exit(f"unknown country {a.country!r}; available: {', '.join(countries.codes())}, intl")
    yn = lambda v: "yes" if v else "-"
    print(f"{'board':<15}{'country':<8}{'transport':<16}{'keywords':<9}{'remote':<8}{'city':<6}{'part-time':<10}{'newest':<7}pages")
    for n, b in REGISTRY.items():
        c = b.caps
        if a.country and country_of(b) not in (a.country, "any"):
            continue
        print(f"{n:<15}{country_of(b):<8}{c.transport:<16}{yn(c.keywords):<9}{c.remote:<8}{yn(c.city):<6}{yn(c.worktime):<10}"
              f"{yn(c.sort_newest):<7}{c.max_pages}")


# ---------------------------------------------------------------- steps and review commands
def cmd_eval(a) -> None:
    store, profile, rid = _open(a)
    print(ev.evaluate(store, profile, rid))


def cmd_report(a) -> None:
    store, profile, rid = _open(a, readonly=True)
    print(report.write_reports(store, profile, rid, _report_dir(a, store, rid)))


def cmd_list(a) -> None:
    store, profile, rid = _open(a, readonly=True)
    rows = report.listing(store, profile, rid, search=a.search, new_only=a.new, where_sql=a.where)
    if a.group == "title":
        groups = report.group_by_title(rows)
        print(report.format_groups(groups[:a.limit] if a.limit else groups, a.format, profile.currency))
    else:
        print(report.format_rows(rows[:a.limit] if a.limit else rows, a.format, profile.currency))


def cmd_details(a) -> None:
    store, profile, rid = _open(a)
    ids = _ids(a, store, profile, rid)
    passing = {d["cluster_id"] for d in report.listing(store, profile, rid)}
    with contextlib.ExitStack() as stack:
        _fetch_postings(store, profile, ids, a.port, Limiter(min_intervals(profile.min_interval)), _LazyBrowser(stack, a.port))
    ev.evaluate(store, profile, rid)  # the postings may settle unknown fields or hit text filters
    rows = report.listing(store, profile, rid)
    dropped = passing - {d["cluster_id"] for d in rows}
    if dropped:
        log(f"details: {len(dropped)} offers no longer pass once their posting is known (see `neetscape show ID`)")
    print(report.write_reports(store, profile, rid, _report_dir(a, store, rid), rows))


def _verdict_lines(store: Store, profile, offer_id: int, run_id: int) -> list[str]:
    """Stored verdict of the run per search, plus the current profile's when it differs."""
    stored = store.verdicts(run_id, offer_id)
    live = ev.explain(store, profile, offer_id, run_id)
    say = lambda reasons: ", ".join(reasons) or "passes"
    if not stored:
        return [f"searches (not evaluated in run {run_id}; current profile):"] + [f"  {sid}: {say(r)}" for sid, r in live.items()]
    lines = [f"searches (run {run_id}):"]
    for sid in dict.fromkeys([*stored, *live]):
        line = f"  {sid}: {say(stored[sid]) if sid in stored else '(not in that run)'}"
        if sid in live and live[sid] != stored.get(sid):
            line += f"   [current profile: {say(live[sid])}]"
        lines.append(line)
    return lines


def cmd_show(a) -> None:
    if not a.args:
        sys.exit("usage: neetscape show ID")
    store, profile, rid = _open(a, readonly=True)
    o = store.offer(a.args[0])
    if not o:
        sys.exit("no such offer")
    print(json.dumps({k: o[k] for k in o.keys() if k not in ("description", "snippet")}, ensure_ascii=False, indent=1))
    print("", *_verdict_lines(store, profile, o["id"], rid), sep="\n")
    flagged = ev.flagged(store, profile, o["id"], rid)
    if flagged:
        print("blacklist (flag): " + ", ".join(flagged))
    d = detail(store, o["id"])
    if d:
        print(f"\nposting: HTTP {d['status']}, hints {json.dumps(d['hints'], ensure_ascii=False)}")
        print(d["text"])
    else:
        print(f"\nposting: (not fetched; run `neetscape details --pick {o['id']}`)")
        if o["snippet"]:
            print("card:", o["snippet"])


def cmd_sql(a) -> None:
    if not a.args:
        sys.exit('usage: neetscape sql "SELECT ..."  (:run is bound to --run or the latest run)')
    store = _store(a, readonly=True)
    query = " ".join(a.args)
    params = {"run": _run_id(store, a)} if ":run" in query or a.run is not None else {}
    cur = store.db.execute(query, params)
    print("\t".join(c[0] for c in cur.description or []))
    for row in cur.fetchall():
        print("\t".join("" if v is None else str(v) for v in row))


def cmd_mark(a) -> None:
    if len(a.args) != 2:
        sys.exit(f"usage: neetscape mark ID|URL STATUS [--note TEXT]; statuses: {', '.join(MARK_STATUSES)}")
    try:
        m = _store(a).mark(a.args[0], a.args[1], a.note)
    except ValueError as e:
        sys.exit(str(e))
    print(f"{m['status']}: {m['url']}")


def cmd_tracked(a) -> None:
    store = _store(a, readonly=True)
    rid = _run_id(store, a) if store.last_run() else None
    for m in store.tracked(rid):
        print(f"{m['status']:<12} {m['at'][:10]}  {m['title'] or ''} — {m['company'] or ''}  {m['url']}  "
              f"[{m['listed']}]  {m['note'] or ''}")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="neetscape", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("args", nargs="*")
    ap.add_argument("--profile", default="profile.json")
    ap.add_argument("--out", default="runs", help="data directory (database and reports), default ./runs")
    ap.add_argument("--preset", action="append", default=[], help="for init: preset name, repeatable")
    ap.add_argument("--country", help="init: the profile's country (default pl); boards: only this country's boards")
    ap.add_argument("--boards", help="comma-separated boards or groups (a country code such as pl or de, intl, all)")
    ap.add_argument("--run", type=int, help="run id for eval, report, list, details, show, sql, tracked (default: latest)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--full", action="store_true", help="disable incremental stops")
    ap.add_argument("--limit-pages", type=int)
    ap.add_argument("--record", help="save raw pages to this directory")
    ap.add_argument("--search", help="list: only this search id")
    ap.add_argument("--new", action="store_true", help="list: only offers new in this run")
    ap.add_argument("--group", choices=["title"], help="list: one row per normalised title, with counts")
    ap.add_argument("--where", help="list: extra SQL condition on offers o, e.g. \"o.pay_max > 10000\"")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--format", default="tsv", choices=["tsv", "md", "json"])
    ap.add_argument("--pick", help="details: offer ids, comma separated")
    ap.add_argument("--pick-file", help="details: file with an offer id at the start of each line")
    ap.add_argument("--top", type=int, help="details: open the best N matches whose job has no stored posting (default review.details_top)")
    ap.add_argument("--marked", action="store_true", help="details: open the marked offers whose posting is missing (never fetched or failed)")
    ap.add_argument("--note", default="")
    ap.add_argument("--keyword", help="probe: search phrase")
    ap.add_argument("--save-fixture", help="probe: write the raw first page to this file (for tests/fixtures/<cc>/)")
    ap.add_argument("--port", type=int, default=9334, help="CDP port of the private browser")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = _parser().parse_args(argv)
    handlers = {"init": cmd_init, "check": cmd_check, "plan": cmd_plan, "boards": cmd_boards, "probe": cmd_probe,
                "run": cmd_run, "crawl": lambda a: cmd_run(a, crawl_only=True), "eval": cmd_eval, "report": cmd_report,
                "list": cmd_list, "details": cmd_details, "show": cmd_show, "sql": cmd_sql, "mark": cmd_mark,
                "tracked": cmd_tracked}
    with _signals_unwind():
        try:
            handlers[a.command](a)
        except sqlite3.Error as e:
            sys.exit(f"database error: {e}")


if __name__ == "__main__":
    main()
