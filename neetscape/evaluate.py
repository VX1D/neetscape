"""Check offers against each search (hard filters) and rank the ones that pass (soft rules).

`check` is a pure function of a stored offer row and a search. Every condition is evaluated locally,
including those a board already applied server-side; the board having applied them is used only as
evidence for fields the board did not return (e.g. remote mode, keyword relevance).

`evaluate` judges the current state as of a run (`Store.current_offers`: every offer presumed still listed,
from every board, not only those the run crawled) and stores both outcomes under the run: passing offers in
`evals` (score, matched rules, tags) and failing ones in `rejections` (the reasons, `; `-separated), so
`neetscape show` and SQL can tell why an offer is missing without re-running the filters.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from . import country as countries
from . import infer
from .boards import REGISTRY
from .model import Search, canonical_contract, fold, parse_date
from .pay import HOURS_PER_MONTH
from .profile import Profile
from .store import Store

_TEXT_FIELDS = ("title", "company", "category", "skills", "pay_text", "snippet")


def _text(o, fields=_TEXT_FIELDS) -> str:
    return " ".join(str(o[k] or "") for k in fields)


def _posting(o) -> str:
    """The fetched posting text (`details`), "" until it is fetched and when the fetch failed (`ERROR ...`)."""
    text = (o["posting"] if "posting" in o.keys() else "") or ""
    return "" if text.startswith("ERROR") else text


def _filter_text(o) -> str:
    """What `text_exclude` and the blacklist's `text` read: the card fields, locations and the posting."""
    return _text(o, (*_TEXT_FIELDS, "locations")) + " " + _posting(o)


class _Verdict:
    """Collects failing reasons; `unknown` applies the search's policy for a field the offer lacks."""

    def __init__(self, s: Search):
        self.search, self.reasons = s, []

    def fail(self, reason: str) -> None:
        self.reasons.append(reason)

    def unknown(self, what: str) -> None:
        if self.search.unknown == "drop":
            self.fail(f"{what} unknown")


def _city_in(city: str, country: str, hay: str) -> bool:
    try:
        names = countries.get(country).aliases(city)
    except KeyError:
        names = {fold(city)}
    return any(n in hay for n in names)


def _found_in_area(o, s: Search) -> bool:
    """The board itself placed the offer within the search's area: a request with the board's own city and radius
    filter for the same city, at no larger radius, found it (a town 25 km away matches a 30 km search although its
    name differs). Only boards whose radius filter is verified (`Caps.radius`) count: a board with a city filter
    only may answer an unknown town with the whole country (seen live), and LinkedIn ignores the distance. Boards
    that round a radius up to their own steps may include slightly farther offers."""
    areas = (o["areas"] if "areas" in o.keys() else "") or ""
    for area in filter(None, areas.split(",")):
        board, city, radius = (area.split("|") + ["", "", ""])[:3]
        b = REGISTRY.get(board)
        if b and b.caps.radius and _city_in(s.where.city, s.where.country, fold(city)) \
                and float(radius or 0) <= (s.where.radius_km or 0):
            return True
    return False


def _check_where(o, s: Search, v: _Verdict) -> None:
    locations = " ".join(json.loads(o["locations"] or "[]"))
    if s.where.city:
        in_city = _city_in(s.where.city, s.where.country, fold(locations + " " + (o["snippet"] or "")))
        if in_city or _found_in_area(o, s) or (s.where.remote and o["mode"] == "remote"):
            return
        if locations:
            v.fail(f"not in {s.where.city}")
        else:
            v.unknown("location")
    elif s.where.remote:
        if o["mode"] in ("hybrid", "onsite"):
            v.fail(f"mode {o['mode']}")
        elif o["mode"] == "unknown":
            v.unknown("mode")


def _check_remote_proof(o, s: Search, v: _Verdict) -> None:
    """`remote_proof`: the posting itself must describe remote work ("fully remote", or plain remote wording) and
    mention no hybrid model or required presence (client visits, business travel, office days, relocation).
    "Hybrid or 100% remote, your choice" passes (remote is offered); "hybrid, 1 day a week in the office" or "remote
    with client visits" fails. Without a fetched posting the proof is unknown and follows the `unknown` policy."""
    text = _posting(o)
    if not text or text.startswith("ERROR"):
        v.unknown("remote proof")
        return
    languages = countries.languages(s.where.country)
    h = infer.hints(text, languages)
    presence = _required_presence(text, languages) + h["office"]
    if presence:
        v.fail("posting requires presence: " + ", ".join(presence[:2]))
    elif not (h["fully_remote"] or infer.mode_from_text(text, languages) == "remote"):
        v.fail("posting does not mention remote work")


_SENTENCES = re.compile(r"(?<=[.!?;])\s+|\n+|\s+[•▪·]\s+")
_CHOICE = re.compile(r"\b(?:lub|albo|bądź|or|either)\b|\s/\s|zdalnie/|/hybryd|remote/|/hybrid", re.I)


def _required_presence(text: str, languages) -> list[str]:
    """Hybrid wording that the posting requires. A sentence offering remote work as one of the options ("hybrid or
    100% remote", "remote for people outside the city, hybrid in Gdańsk or fully remote") is a choice, not a
    requirement, and is left out."""
    found: list[str] = []
    for sentence in _SENTENCES.split(text):
        hybrid = infer.hints(sentence, languages)["hybrid"]
        if not hybrid:
            continue
        offers_remote = infer.hints(sentence, languages)["fully_remote"] or infer.mode_from_text(
            re.sub(r"(?i)hybry\w*|hybrid\w*", "", sentence), languages) == "remote"
        if not (offers_remote and _CHOICE.search(sentence)):
            found += [w for w in hybrid if w not in found]
    return found


def _check_keywords(o, s: Search, v: _Verdict) -> None:
    """Found by the board for one of the search's phrases, or a phrase appears in the offer."""
    kws = s.keywords_on(o["board"])
    if kws is None:
        return
    found_for = set((o["keywords"] or "").split(",")) if "keywords" in o.keys() else set()
    hay = fold(_text(o, (*_TEXT_FIELDS, "locations")))
    if not (found_for & set(kws) or any(fold(k) in hay for k in kws)):
        v.fail("no keyword")


def _check_worktime(o, s: Search, v: _Verdict) -> None:
    """Work time and contract: either one the search names may satisfy it; an unknown one may still."""
    if not (s.worktime or s.contracts):
        return
    contracts = {canonical_contract(c) for c in (o["contracts"] or "").split(",") if c}
    if o["worktime"] in s.worktime or contracts & s.contracts:
        return
    if (s.worktime and o["worktime"] == "unknown") or (s.contracts and not contracts):
        v.unknown("work time")
    else:
        v.fail(f"work time {o['worktime']} / contracts {','.join(sorted(contracts)) or '-'}")


def _check_pay(o, s: Search, v: _Verdict, hours_per_month: int) -> None:
    if not (s.pay_min or s.require_pay):
        return
    top = o["pay_max"]
    if top is None or o["pay_period"] == "project":
        if s.require_pay:
            v.fail("no pay")
        else:
            v.unknown("pay")
    elif s.pay_min:
        value = top / hours_per_month if s.pay_period == "hour" else top
        if value < s.pay_min:
            v.fail(f"pay {value:.0f} < {s.pay_min}/{s.pay_period}")


def _check_age(o, s: Search, v: _Verdict, today: dt.date) -> None:
    if not s.max_age_days:
        return
    published = parse_date(o["published"])
    if published is None:
        v.unknown("date")
    elif (today - published).days > s.max_age_days:
        v.fail(f"{(today - published).days} days old")


def _check_patterns(o, s: Search, v: _Verdict) -> None:
    title = o["title"] or ""
    if s.title_include and not any(rx.search(title) for rx in s.title_include):
        v.fail("title not included")
    if any(rx.search(title) for rx in s.title_exclude):
        v.fail("title excluded")
    if s.text_exclude:
        text = _filter_text(o)
        if any(rx.search(text) for rx in s.text_exclude):
            v.fail("text excluded")
    if s.category_include and not any(rx.search(o["category"] or "") for rx in s.category_include):
        v.fail("category not included")


def check(o, s: Search, today: dt.date | None = None, hours_per_month: int = HOURS_PER_MONTH) -> tuple[bool, list[str]]:
    """Return (passes, reasons for failing). `o` is a store row (or dict) of an offer. `hours_per_month`
    converts the stored monthly pay back to hourly for `pay.per: hour`; pass the profile country's, the one
    the pay was normalised with."""
    v = _Verdict(s)
    _check_where(o, s, v)
    if s.remote_proof and s.where.remote and not s.where.city:
        _check_remote_proof(o, s, v)
    _check_keywords(o, s, v)
    _check_worktime(o, s, v)
    if o["level"] in s.levels_exclude:
        v.fail(f"level {o['level']}")
    _check_pay(o, s, v, hours_per_month)
    _check_age(o, s, v, today or dt.date.today())
    _check_patterns(o, s, v)
    return not v.reasons, v.reasons


def blacklisted(o, profile: Profile) -> list[str]:
    """Reasons the offer matches the profile's own blacklist (company, URL, or text incl. the fetched posting)."""
    bl = profile.blacklist
    if not bl:
        return []
    reasons = [f"blacklisted company /{rx.pattern}/" for rx in bl["companies"] if rx.search(o["company"] or "")]
    reasons += [f"blacklisted url /{rx.pattern}/" for rx in bl["urls"] if rx.search(o["url"] or "")]
    text = _filter_text(o)
    return reasons + [f"blacklisted text /{rx.pattern}/" for rx in bl["text"] if rx.search(text)]


def _blacklist_verdict(o, profile: Profile) -> tuple[list[str], bool]:
    """(blacklist reasons, whether they drop the offer from every search) under the profile's `action`."""
    black = blacklisted(o, profile)
    return black, bool(black) and profile.blacklist.get("action", "drop") == "drop"


def rank(o, profile: Profile, s: Search) -> tuple[int, list[str], list[str]]:
    """Score (rule weights plus the search's boost), the labels of matched rules, and tag ids."""
    title, text = o["title"] or "", _text(o)
    hits = [r for r in profile.rules if r["rx"].search(title if r["field"] == "title" else text)]
    why = [f"{r['label']} ({r['weight']:+d})" for r in hits] + ([f"search {s.id} ({s.boost:+d})"] if s.boost else [])
    tags = [t["id"] for t in profile.tags if t["rx"].search(title)]
    return sum(r["weight"] for r in hits) + s.boost, why, tags


def evaluate(store: Store, profile: Profile, run_id: int) -> dict[str, int]:
    """Store the verdict of every search on every offer of the current state as of the run (replacing the run's
    earlier verdicts). Returns passed counts per search."""
    passed, rejected, counts = [], [], {s.id: 0 for s in profile.searches}
    hours = profile.country.hours_per_month
    for o in store.current_offers(run_id):
        black, drop = _blacklist_verdict(o, profile)
        for s in profile.searches:
            ok, reasons = check(o, s, hours_per_month=hours)
            if drop:
                ok, reasons = False, black + reasons
            if ok:
                score, why, tags = rank(o, profile, s)
                if black:  # action "flag": kept, but visible
                    why, tags = why + black, tags + ["!blacklist"]
                passed.append((o["id"], s.id, score, json.dumps({"why": why, "tags": tags}, ensure_ascii=False)))
                counts[s.id] += 1
            else:
                rejected.append((o["id"], s.id, "; ".join(reasons)))
    store.save_evals(run_id, passed, rejected)
    return counts


def offer_row(store: Store, offer_id: int, run_id: int | None = None):
    """An offer as `evaluate` reads it for `run_id` (with the keyword evidence of every run when the offer is
    not in that run's current state, or no run is given); None for an offer never sighted."""
    rows = (store.current_offers(run_id, offer_id) if run_id else []) or store.run_offers(None, offer_id)
    return rows[0] if rows else None


def explain(store: Store, profile: Profile, offer_id: int, run_id: int | None = None) -> dict[str, list[str]]:
    """Why an offer passes ([]) or fails each search under the current profile (see `offer_row`); {} for an
    offer never sighted."""
    row = offer_row(store, offer_id, run_id)
    if row is None:
        return {}
    black, drop = _blacklist_verdict(row, profile)
    black = black if drop else []
    return {s.id: black + check(row, s, hours_per_month=profile.country.hours_per_month)[1] for s in profile.searches}


def flagged(store: Store, profile: Profile, offer_id: int, run_id: int | None = None) -> list[str]:
    """Blacklist reasons of an offer the profile keeps (`action: flag`)."""
    row = offer_row(store, offer_id, run_id)
    black, drop = _blacklist_verdict(row, profile) if row is not None else ([], False)
    return [] if drop else black
