"""neetscape — remote/local job offer radar for the job boards of one country (pl, de, ...).

Setup
  neetscape init [--country CC] [--interactive]          write profile.json from questions (default on a terminal)
  neetscape init [--country CC] --preset broad|focused|local|side ...   ... or from presets (they combine)
  neetscape check                                         validate the profile
  neetscape plan                                          show what would be fetched (no network)
  neetscape boards [--country CC]                         board capabilities
  neetscape probe BOARD [--keyword K] [--save-fixture PATH]   fetch one page, show field coverage

Run
  neetscape run [--resume] [--full] [--limit-pages N] [--boards a,b] [--record DIR]
  neetscape crawl | eval | report                         single steps (eval, report: the latest run or --run N)

Review (all read the latest run, or --run N; a run's listing is the current state of every board as of it)
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
from . import infer
from . import planner, report
from . import profile as prof_mod
from .boards import REGISTRY, expand
from .boards.base import Request, country_of, min_intervals
from .boards.fetch import Limiter
from .browser import Browser
from .crawler import crawl
from .details import detail, fetch_details, route
from .log import log
from .model import LEVELS, Search, Where
from .store import MARK_STATUSES, Store

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
    if getattr(a, "boards", None):  # init has no --boards
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


def _open(a, readonly: bool = False) -> tuple[Store, prof_mod.Profile, int]:
    """The store, profile and run id of a command working on one run."""
    store = _store(a, readonly)
    return store, _profile(a), _run_id(store, a)


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
    offers = (store.offer(m["url"]) for m in store.tracked(run_id, include_hidden=False))
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


def cmd_crawl(a) -> None:
    cmd_run(a, crawl_only=True)


def cmd_probe(a) -> None:
    name = a.board
    board = REGISTRY.get(name)
    if not board:
        sys.exit(f"unknown board; available: {', '.join(REGISTRY)}")
    code = country_of(board)
    code = code if code in countries.codes() else (a.country or countries.DEFAULT_COUNTRY)
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
    if a.interactive and a.preset:
        sys.exit("--interactive builds the profile from questions; leave out --preset")
    if a.interactive or (not a.preset and _is_terminal()):
        _init_interactive(a, target)
        return
    names = a.preset or ["focused"]
    try:
        data = prof_mod.combine(names, a.country or countries.DEFAULT_COUNTRY)
    except prof_mod.ProfileError as e:
        sys.exit(str(e))
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {target} ({data['country']}) from preset(s) {', '.join(names)}; edit it, then `neetscape check` and `neetscape plan`")


def _is_terminal() -> bool:
    return bool(sys.stdin and sys.stdin.isatty())


def _ask(question: str, default: str, parse):
    """Ask until `parse` accepts the answer (Enter takes `default`); a ValueError's message is the hint shown."""
    while True:
        try:
            reply = input(f"{question} [{default}]: ").strip()
        except EOFError:
            sys.exit("\ninit cancelled; nothing written")
        try:
            return parse(reply or default)
        except ValueError as e:
            print(f"  {e}")


def _one_of(allowed):
    def parse(reply: str) -> str:
        if reply.lower() not in allowed:
            raise ValueError(f"answer one of: {', '.join(allowed)}")
        return reply.lower()
    return parse


def _some_of(allowed):
    """Comma-separated values from `allowed`; "any" or "none" is []."""
    def parse(reply: str) -> list[str]:
        values = [v.strip().lower() for v in reply.split(",") if v.strip()]
        if values in (["any"], ["none"]):
            return []
        bad = [v for v in values if v not in allowed]
        if bad:
            raise ValueError(f"unknown: {', '.join(bad)}; choose from: {', '.join(allowed)}")
        return list(dict.fromkeys(values))
    return parse


def _number(kind=int, none: bool = False):
    """A positive number; with `none`, "none" is None."""
    def parse(reply: str):
        if none and reply.lower() == "none":
            return None
        try:
            value = kind(reply.replace(",", "."))
        except ValueError:
            raise ValueError("a number" + (" or none" if none else "")) from None
        if value <= 0:
            raise ValueError("a number above 0" + (" or none" if none else ""))
        return int(value) if value == int(value) else value
    return parse


def _phrases(reply: str) -> list[str]:
    return [] if reply.lower() == "everything" else [w.strip() for w in reply.split(",") if w.strip()]


def _city(reply: str) -> str:
    if reply == "-":
        raise ValueError("name a city, e.g. Kraków or München")
    return reply


def init_answers(default_country: str) -> dict:
    """Ask `neetscape init`'s questions on the terminal; returns the answers for `profile.from_answers`."""
    print("A few questions build profile.json. Enter accepts the [default]; lists are comma-separated.")
    codes = countries.codes()
    names = ", ".join(f"{c} ({countries.get(c).name})" for c in codes)
    ans: dict = {"country": _ask(f"Country: {names}", default_country, _one_of(codes))}
    home = countries.get(ans["country"])
    ans["where"] = _ask("Where: remote, city, or both (the city or remote)", "remote", _one_of(prof_mod.WHERE_ANSWERS))
    if ans["where"] != "remote":
        ans["city"] = _ask("City", "-", _city)
        ans["radius_km"] = _ask("Distance from the city, km", "30", _number())
    ans["what"] = _ask("What work: phrases sent to the boards, e.g. n8n, helpdesk, data analyst", "everything", _phrases)
    domains, functions = list(infer.DOMAINS), list(infer.FUNCTIONS)
    ans["domains"] = _ask(f"Job domains to keep ({', '.join(domains)})", "any", _some_of(domains))
    ans["functions_exclude"] = _ask(f"Functions to exclude ({', '.join(functions)})", "none", _some_of(functions))
    ans["worktime"] = _ask("Work time: full, part, or any", "any", _one_of(list(prof_mod.WORKTIME_ANSWERS)))
    contracts = [c for c in home.contracts if c != "other"]
    ans["contracts"] = _ask(f"Contract types ({', '.join(contracts)})", "any", _some_of(contracts))
    ans["pay_min"] = _ask(f"Minimum pay in {home.currency}", "none", _number(float, none=True))
    if ans["pay_min"]:
        ans["pay_per"] = _ask("Per month or per hour", "month", _one_of(["month", "hour"]))
    levels = [lv for lv in LEVELS if lv != "unknown"]
    ans["levels_exclude"] = _ask(f"Seniority to exclude ({', '.join(levels)})", "none", _some_of(levels))
    ans["max_age_days"] = _ask("Ignore postings older than, days", "30", _number(none=True))
    return ans


def _init_interactive(a, target: Path) -> None:
    default = a.country or countries.DEFAULT_COUNTRY
    if default not in countries.codes():
        sys.exit(f"unknown country {default!r}; available: {', '.join(countries.codes())}")
    try:
        data = prof_mod.from_answers(init_answers(default))
    except prof_mod.ProfileError as e:
        sys.exit(str(e))
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"\nwrote {target}")
    cmd_check(a)
    print("next: `neetscape plan` (what would be fetched, no network), then `neetscape run --limit-pages 2` for a "
          f"quick trial; edit {target} for anything the questions did not cover")


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
    print(f"{'board':<15}{'country':<8}{'transport':<16}{'keywords':<9}{'remote':<8}{'city':<6}{'part-time':<10}{'newest':<7}pages")
    for n, b in REGISTRY.items():
        if a.country and country_of(b) not in (a.country, "any"):
            continue
        c = b.caps
        print(f"{n:<15}{country_of(b):<8}{c.transport:<16}{_yes(c.keywords):<9}{c.remote:<8}{_yes(c.city):<6}"
              f"{_yes(c.worktime):<10}{_yes(c.sort_newest):<7}{c.max_pages}")


def _yes(value) -> str:
    return "yes" if value else "-"


# ---------------------------------------------------------------- steps and review commands
def cmd_eval(a) -> None:
    store, profile, rid = _open(a)
    print(ev.evaluate(store, profile, rid, rederive=a.rederive))


def _warn_unevaluated(store: Store, run_id: int) -> None:
    """The listing reads the run's stored verdicts: say so when some current offers have none."""
    n = store.unevaluated(run_id)
    if n:
        log(f"{n} offers of the current state have no verdict of run {run_id} and are left out; "
            f"run `neetscape eval{f' --run {run_id}' if run_id != store.last_run() else ''}` first")


def cmd_report(a) -> None:
    store, profile, rid = _open(a, readonly=True)
    _warn_unevaluated(store, rid)
    print(report.write_reports(store, profile, rid, _report_dir(a, store, rid)))


def cmd_list(a) -> None:
    store, profile, rid = _open(a, readonly=True)
    _warn_unevaluated(store, rid)
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

    def say(reasons: list[str]) -> str:
        return ", ".join(reasons) or "passes"

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
    store, profile, rid = _open(a, readonly=True)
    o = store.offer(a.id)
    if not o:
        sys.exit("no such offer")
    print(json.dumps({k: o[k] for k in o.keys() if k not in ("description", "snippet", "evidence")}, ensure_ascii=False, indent=1))
    evidence = json.loads(o["evidence"] or "{}")
    if evidence:
        print("\nwhy (field: value <- source \"phrase\"):")
        for col, why in sorted(evidence.items()):
            if isinstance(why, dict):  # a set of values (job_domains): value -> [source, phrase]
                print(f"  {col}: {o[col]} <- " + ", ".join(f"{v}: {s} \"{p}\"" for v, (s, p) in why.items()))
            else:
                print(f"  {col}: {o[col]} <- {why[0]} \"{why[1]}\"")
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
    store = _store(a, readonly=True)
    query = " ".join(a.query)
    params = {"run": _run_id(store, a)} if ":run" in query or a.run is not None else {}
    cur = store.db.execute(query, params)
    print("\t".join(c[0] for c in cur.description or []))
    for row in cur.fetchall():
        print("\t".join("" if v is None else str(v) for v in row))


def cmd_mark(a) -> None:
    try:
        m = _store(a).mark(a.ref, a.status, a.note)
    except ValueError as e:
        sys.exit(str(e))
    print(f"{m['status']}: {m['url']}")


def cmd_tracked(a) -> None:
    store = _store(a, readonly=True)
    rid = _run_id(store, a) if store.last_run() else None
    for m in store.tracked(rid):
        print(f"{m['status']:<12} {m['at'][:10]}  {m['title'] or ''} — {m['company'] or ''}  {m['url']}  "
              f"[{m['listed']}]  {m['note'] or ''}")


def _paths(defaults: bool) -> argparse.ArgumentParser:
    """--profile and --out, accepted before and after the command; after it, SUPPRESS keeps a value given before."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--profile", default="profile.json" if defaults else argparse.SUPPRESS,
                   help="the search profile, default ./profile.json")
    p.add_argument("--out", default="runs" if defaults else argparse.SUPPRESS,
                   help="data directory (database and reports), default ./runs")
    return p


def _option(*args, **kwargs) -> argparse.ArgumentParser:
    """A parent parser with one option several commands share."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(*args, **kwargs)
    return p


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="neetscape", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 parents=[_paths(defaults=True)])
    paths = _paths(defaults=False)
    boards = _option("--boards", help="comma-separated boards or groups (a country code such as pl or de, intl, all)")
    run = _option("--run", type=int, help="run id (default: the latest)")
    port = _option("--port", type=int, default=9334, help="CDP port of the private browser")
    sub = ap.add_subparsers(dest="command", required=True, metavar="command")

    def command(name: str, handler, summary: str, *parents) -> argparse.ArgumentParser:
        p = sub.add_parser(name, parents=[paths, *parents], help=summary, description=summary)
        p.set_defaults(handler=handler)
        return p

    p = command("init", cmd_init, "write profile.json from questions, or from presets (they combine)")
    p.add_argument("--preset", action="append", default=[],
                   help="preset name, repeatable (without it, on a terminal, init asks questions instead)")
    p.add_argument("--interactive", action="store_true", help="build the profile from questions (the default on a terminal)")
    p.add_argument("--country", help=f"the profile's country (default {countries.DEFAULT_COUNTRY})")
    command("check", cmd_check, "validate the profile", boards)
    command("plan", cmd_plan, "show what would be fetched (no network)", boards)
    command("boards", cmd_boards, "board capabilities").add_argument("--country", help="only this country's boards")

    p = command("probe", cmd_probe, "fetch one page of a board, show field coverage", port)
    p.add_argument("board")
    p.add_argument("--keyword", help="search phrase")
    p.add_argument("--save-fixture", help="write the raw first page to this file (for tests/fixtures/<cc>/)")
    p.add_argument("--country", help=f"the country searched on a board serving several (default {countries.DEFAULT_COUNTRY})")

    for name, handler, summary in (("run", cmd_run, "crawl, evaluate, fetch the best postings, write the reports"),
                                   ("crawl", cmd_crawl, "only crawl (a run's first step)")):
        p = command(name, handler, summary, boards, port)
        p.add_argument("--resume", action="store_true", help="continue the last interrupted run")
        p.add_argument("--full", action="store_true", help="disable incremental stops")
        p.add_argument("--limit-pages", type=int, help="at most this many pages per request")
        p.add_argument("--record", help="save raw pages to this directory")

    command("eval", cmd_eval, "judge the stored offers again", boards, run).add_argument(
        "--rederive", action="store_true",
        help="derive every offer's fields again even when the derivation (infer.py, lang packs) is unchanged")
    command("report", cmd_report, "write the reports again", boards, run)

    p = command("list", cmd_list, "the passing offers", boards, run)
    p.add_argument("--search", help="only this search id")
    p.add_argument("--new", action="store_true", help="only jobs first seen in this run")
    p.add_argument("--group", choices=["title"], help="one row per normalised title, with counts")
    p.add_argument("--where", help="extra SQL condition on offers o, e.g. \"o.pay_max > 10000\"")
    p.add_argument("--limit", type=int)
    p.add_argument("--format", default="tsv", choices=["tsv", "md", "json"])

    p = command("details", cmd_details, "fetch postings, evaluate again, rewrite the reports", boards, run, port)
    p.add_argument("--pick", help="offer ids, comma separated")
    p.add_argument("--pick-file", help="file with an offer id at the start of each line")
    p.add_argument("--top", type=int, help="open the best N matches whose job has no stored posting (default review.details_top)")
    p.add_argument("--marked", action="store_true", help="open the marked offers whose posting is missing (never fetched or failed)")

    command("show", cmd_show, "an offer, why it passes or fails each search, its posting", boards, run).add_argument("id")
    command("sql", cmd_sql, "read-only SQL on the database (:run is bound to the run)", run).add_argument("query", nargs="+")
    p = command("mark", cmd_mark, f"record a decision: {' '.join(MARK_STATUSES)}")
    p.add_argument("ref", metavar="ID|URL")
    p.add_argument("status")
    p.add_argument("--note", default="")
    command("tracked", cmd_tracked, "marked offers and whether they are still listed", run)
    return ap


def main(argv: list[str] | None = None) -> None:
    a = _parser().parse_args(argv)
    with _signals_unwind():
        try:
            a.handler(a)
        except sqlite3.Error as e:
            sys.exit(f"database error: {e}")


if __name__ == "__main__":
    main()
