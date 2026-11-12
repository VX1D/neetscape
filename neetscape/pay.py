"""Turn free-form salary text into a monthly range in the database currency (`base`, the profile country's).

Handles the formats seen on Polish, German and international boards, e.g.
  "b2b:12000-18000/month; permanent:9000-12000/month gross"   (justjoin)
  "200–250 zł / godz. (B2B)", "8.3k–14.1k zł / mies.", "35 – 55 PLN brutto godzinowo"
  "PLN 10,000.00/mo - PLN 15,000.00/mo", "€3,000 - €4,000", "1 200 – 1 440 PLN / dzień"
  "45.000–55.000 € brutto/Jahr", "13,50 €/Std.", "3.000 bis 3.500 € monatlich", "4,5-6,5 tys. zł", "1500 zł/tydzień"
Without a unit word, the size of the amount decides hourly / monthly / yearly, with thresholds that depend
on the currency (a German "45.000–55.000 €" is yearly, a Polish "45 000 zł" would be an odd monthly pay).
Gross/net and contract type are ignored: the result is only meant for ranking and thresholds.
"""
from __future__ import annotations

import functools
import re

from . import lang

HOURS_PER_MONTH = 168           # defaults of `Country.hours_per_month` / `days_per_month`
DAYS_PER_MONTH = 21
WEEKS_PER_MONTH = 52 / 12
DEFAULT_FX = {"PLN": 1.0, "EUR": 4.3, "USD": 4.0, "GBP": 5.1, "CHF": 4.6}  # PLN per unit (Poland)

# per currency, applied to the amount as written (before conversion):
#   hourly_below  a bare amount below this is an hourly rate
#   b2b_day_below a board's structured "b2b:lo-hi .../month" below this is a day rate the employer filed as monthly
#                 (solid.jobs: "b2b:800-1100 PLN/month" for a release manager)
#   yearly_above  a bare amount above this is a yearly salary
#   month_min/max the monthly amount must fall in this range, else it is not a salary (dates, ids, counts)
#   single_min    a lone amount without a unit word below this is too ambiguous to read
THRESHOLDS = {
    "PLN": dict(hourly_below=400, yearly_above=60000, month_min=500, month_max=500_000, single_min=1000, b2b_day_below=2000),
    "EUR": dict(hourly_below=100, yearly_above=15000, month_min=120, month_max=120_000, single_min=250, b2b_day_below=500),
    "USD": dict(hourly_below=100, yearly_above=15000, month_min=120, month_max=120_000, single_min=250, b2b_day_below=500),
    "GBP": dict(hourly_below=100, yearly_above=12000, month_min=100, month_max=100_000, single_min=200, b2b_day_below=450),
    "CHF": dict(hourly_below=120, yearly_above=25000, month_min=120, month_max=120_000, single_min=250, b2b_day_below=550),
}

# currency marks (lower case), in the order `_currency` tries them; boards map symbols with it too
CURRENCIES = (("zł", "PLN"), ("pln", "PLN"), ("eur", "EUR"), ("€", "EUR"), ("usd", "USD"), ("$", "USD"),
               ("gbp", "GBP"), ("£", "GBP"), ("chf", "CHF"))
_CUR = "(?:" + "|".join(re.escape(mark) for mark, _ in CURRENCIES) + ")"


@functools.lru_cache(maxsize=1)
def _words() -> dict:
    """Regexes of the pay words of every language pack (`VOCAB["pay"]`): units of time are unambiguous across
    languages, and a board's text mixes them, so all packs are read at once."""
    packs = [lang.pack(code).VOCAB.get("pay", {}) for code in lang.available()]
    alt = lambda key: "|".join(f"(?:{p})" for pk in packs for p in pk.get(key, [])) or "(?!)"  # noqa: E731
    num = rf"\d[\d\s .,]*(?:{alt('thousand')})?"  # 8.3k, "4,5 tys." (thousand)
    rx = {key: re.compile(alt(key), re.I) for key in ("hour", "week", "day", "year", "month", "words")}
    rx["thousand"] = re.compile(rf"(?:{alt('thousand')})$")
    rx["range"] = re.compile(
        rf"(?:{_CUR}\s*)?(?P<lo>{num})\s*(?:{_CUR}\s*)?(?:/\s*\w+\.?\s*)?(?:-|–|—|{alt('range')})\s*(?:{_CUR}\s*)?(?P<hi>{num})\s*"
        rf"(?:{_CUR})?(?P<tail>[^;\n]{{0,40}})", re.I)
    rx["single"] = re.compile(rf"(?:{_CUR}\s*)?(?P<lo>{num})\s*{_CUR}?(?P<tail>[^;\n]{{0,40}})", re.I)
    return rx


def _number(s: str) -> float | None:
    """An amount as written: "8.3k", "4,5 tys.", "10,000.00", "10.000,00", "1 200"; None when unreadable."""
    s = s.strip().lower()
    mult = 1000 if _words()["thousand"].search(s) else 1
    s = re.sub(r"\s", "", _words()["thousand"].sub("", s))
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):  # 10,000.00
        s = s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):  # 10.000,00
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s) * mult
    except ValueError:
        return None


def _currency(*parts: str | None) -> str | None:
    """Currency code of the first part that names one, else None."""
    for p in filter(None, parts):
        p = p.lower()
        for mark, code in CURRENCIES:
            if mark in p:
                return code
    return None


def _has_unit(text: str) -> bool:
    return any(rx.search(text) for rx in (_words()[k] for k in ("hour", "week", "day", "year", "month")))


def _factor(text: str, lo: float, t: dict, hours: float, days: float) -> float:
    """Multiplier from the amount's unit to a month: the unit word in `text`, else the size of `lo` (`t`: THRESHOLDS)."""
    if _words()["hour"].search(text):
        return hours
    if _words()["week"].search(text):
        return WEEKS_PER_MONTH
    if _words()["day"].search(text):
        return days
    if _words()["year"].search(text):
        return 1 / 12
    if _words()["month"].search(text):
        return 1.0
    if lo < t["hourly_below"]:  # bare small numbers are hourly rates in practice
        return hours
    if lo > t["yearly_above"]:  # bare large numbers are yearly
        return 1 / 12
    return 1.0


def parse_pay(text: str, fx: dict | None = None, base: str = "PLN", assume: str | None = None,
              hours: float = HOURS_PER_MONTH, days: float = DAYS_PER_MONTH) -> tuple[int, int] | None:
    """Best monthly range in `base` found in `text` (highest upper bound across segments), or None.

    `fx`: units of `base` per unit of each currency (default: PLN rates). `assume`: currency of amounts that
    carry no currency sign but are clearly pay (a unit or gross/net word next to them); structured
    `type:lo-hi/unit` fields without a currency are read in `assume`, or PLN when it is not given."""
    if not text:
        return None
    fx = fx or DEFAULT_FX
    best = None
    for seg in re.split(r";|\n", text):
        structured = re.match(r"\s*[a-z0-9_]+:\s*\d", seg)  # justjoin/rocketjobs field
        m = _words()["range"].search(seg)
        single = m is None
        if single:
            m = _words()["single"].search(seg)
        if not m:
            continue
        lo = _number(m.group("lo"))
        hi = lo if single else _number(m.group("hi"))
        if lo and hi and not single and _words()["thousand"].search(m.group("hi").strip().lower()) and lo * 1000 <= hi * 1.01:
            lo *= 1000  # "4,5-6,5 tys.": the multiplier is written once, after the range
        if not lo or not hi or lo > hi * 1.01:
            continue
        cur = _currency(seg)
        if cur is None:
            if structured:
                cur = assume or "PLN"
            elif assume and (_has_unit(seg) or _words()["words"].search(seg)):
                cur = assume
        if cur is None or cur not in fx:
            continue
        t = THRESHOLDS.get(cur, THRESHOLDS["EUR"])
        if single and lo < t["single_min"] and not _has_unit(seg):
            continue  # a lone small number without a unit is too ambiguous
        f = _factor(seg, lo, t, hours, days)
        if structured and f == 1.0 and seg.strip().lower().startswith("b2b") and hi < t["b2b_day_below"]:
            f = days  # no B2B contract pays under ~2000 PLN a month full time: it is a day rate
        lo_src, hi_src = lo * f, hi * f
        if hi_src < t["month_min"] or hi_src > t["month_max"]:  # not a salary (dates, ids, counts)
            continue
        lo_m, hi_m = round(lo_src * fx[cur]), round(hi_src * fx[cur])
        if best is None or hi_m > best[1]:
            best = (lo_m, hi_m)
    return best


def pay_label(d) -> str:
    """A stored offer's pay as reports show it: "9.0–12.0k" per month, the text of a project budget, "—" if none."""
    if d.get("pay_period") == "project":
        return (d.get("pay_text") or "project")[:24]
    lo, hi = d.get("pay_min"), d.get("pay_max")
    if hi is None:
        return "—"
    return f"{lo / 1000:.1f}–{hi / 1000:.1f}k" if lo != hi else f"{hi / 1000:.1f}k"
