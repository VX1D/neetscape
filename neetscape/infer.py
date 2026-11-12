"""Map board vocabularies and free text onto the model's vocabularies.

Every function returns "unknown" (or an empty list) rather than guessing. Free-text functions take the
languages to read (`neetscape/lang/<code>.py`); the default is `lang.DEFAULT` (Polish + English). English is always added.
"""
from __future__ import annotations

import functools
import re

from . import lang
from .model import canonical_contract
from .pay import parse_pay

# --- board vocabularies -------------------------------------------------------
_MODE = {"remote": "remote", "hybrid": "hybrid", "office": "onsite", "onsite": "onsite", "partly_remote": "hybrid"}
_WORKTIME = {"full_time": "full_time", "part_time": "part_time", "freelance": "flexible", "practice_internship": "part_time",
             "contract": "flexible", "temporary": "flexible", "flexible": "flexible"}
_CONTRACT = {"permanent": "employment", "b2b": "b2b", "mandate_contract": "mandate", "specific_task_contract": "specific_task",
             "internship": "internship", "freelance": "freelance", "any": "other", "uop": "employment", "mandate": "mandate"}
_LEVEL = {"intern": "intern", "junior": "junior", "mid": "mid", "regular": "mid", "senior": "senior", "expert": "senior",
          "lead": "lead", "manager": "manager", "c_level": "manager", "staż": "intern"}


def mode(value: str) -> str:
    return _MODE.get((value or "").lower(), "unknown")


def worktime(value: str) -> str:
    return _WORKTIME.get((value or "").lower(), "unknown")


def contract(value: str, aliases: dict | None = None) -> str:
    """A board's contract word -> canonical contract. `aliases`: the country's `contract_aliases`."""
    v = (value or "").lower()
    found = _CONTRACT.get(v) or (aliases or {}).get(v)
    return canonical_contract(found) if found else "other"


def level(value: str) -> str:
    return _LEVEL.get((value or "").lower(), "unknown")


# --- free text ------------------------------------------------------------------
def _langs(languages) -> tuple:
    return lang.with_english(languages or lang.DEFAULT)


@functools.lru_cache(maxsize=32)
def _tables(languages: tuple) -> dict:
    packs = [lang.pack(code).VOCAB for code in languages]
    out: dict = {}
    for fld, order in lang.ORDER.items():
        first = [(v, re.compile(p, re.I)) for pk in packs for v, p in pk.get("first", {}).get(fld, [])]
        merged = []
        for value in order:
            pats = [p for pk in packs for p in pk.get(fld, {}).get(value, [])]
            if pats:
                merged.append((value, re.compile("|".join(pats), re.I)))
        out[fld] = (first, merged)
    out["hints"] = {}
    for key in lang.HINTS:
        pats = [f"(?:{p})" for pk in packs for p in pk.get("hints", {}).get(key, [])]
        out["hints"][key] = re.compile("|".join(pats), re.I) if pats else None
    return out


def _first_match(fld: str, text: str, languages) -> str:
    first, merged = _tables(_langs(languages))[fld]
    for value, rx in first + merged:
        if rx.search(text or ""):
            return value
    return "unknown"


def mode_from_text(text: str, languages=None) -> str:
    return _first_match("mode", text, languages)


def worktime_from_text(text: str, languages=None) -> str:
    return _first_match("worktime", text, languages)


def contracts_from_text(text: str, languages=None) -> list[str]:
    _, merged = _tables(_langs(languages))["contract"]
    return [value for value, rx in merged if rx.search(text or "")]


def level_from_text(title: str, languages=None) -> str:
    return _first_match("level", title, languages)


def hints(text: str, languages=None) -> dict:
    """Signals for the reviewer from a full posting. Not decisions: the posting text is the source of truth."""
    rx = _tables(_langs(languages))["hints"]
    text = text or ""
    found = lambda k: sorted({m.lower() for m in rx[k].findall(text)})[:3] if rx[k] else []
    return {
        "fully_remote": bool(rx["fully_remote"] and rx["fully_remote"].search(text)),
        "hybrid": found("hybrid"),
        "years": sorted(set(rx["years"].findall(text)))[:3] if rx["years"] else [],
        "degree": found("degree"),
        "languages": found("languages"),
        "fixed_term": bool(rx["fixed_term"] and rx["fixed_term"].search(text)),
        "office": found("office"),
    }


def fill_from_text(offer, fx: dict, *, base: str = "PLN", languages=None, assume: str | None = None,
                   hours: int | None = None, days: int | None = None) -> None:
    """Complete unknown fields of an Offer from its own text, then normalise pay. Board data always wins.

    `fx`/`base`: currency of the database (the profile's country); `languages`/`assume`: the board's (or the
    searched) country, i.e. the language of the text and the currency of amounts written without one."""
    text = offer.text()
    offer.contracts = [canonical_contract(c) for c in offer.contracts]
    if offer.mode == "unknown":
        offer.mode = mode_from_text(text, languages)
    if offer.worktime == "unknown":
        offer.worktime = worktime_from_text(text, languages)
    if not offer.contracts:
        offer.contracts = contracts_from_text(text, languages)
    if offer.level == "unknown":
        offer.level = level_from_text(offer.title, languages)
    if offer.pay_min is None and offer.pay_text and offer.pay_period != "project":
        kw = {k: v for k, v in (("hours", hours), ("days", days)) if v}
        pm = parse_pay(offer.pay_text, fx, base=base, assume=assume, **kw)
        if pm:
            offer.pay_min, offer.pay_max = pm
