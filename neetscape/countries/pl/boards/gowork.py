"""gowork.pl — results ship in the page's Nuxt payload (`<script id="__NUXT_DATA__">`, devalue format: one flat
JSON array whose objects refer to other entries by index), read over plain HTTP (the pages are served to a
plain client; robots.txt allows `/praca` and `/oferta/`, disallows `/oferta/*/aplikuj` and `/click-out/`).

URLs (verified live 2026-11-12): path segments `/praca/[<kw>;st/][<city>;l/][<types>;e/][zdalna;tr/][N;pg/][KM;km]`,
the order the board's own `seo.next` links use (`krakow;l/2;pg/50;km`, `czesc-etatu;e/zdalna;tr/2;pg`).
- keywords: `<slug>;st` (the search box sends the slug of the typed text: "automatyzacja procesów" ->
  `automatyzacja-procesow;st`, 4 offers). It searches the board's position names and titles; a slug close to a
  known position is redirected (302) to it ("python" -> `programista-python;st`, 24 offers). A slug starting with
  "praca" is an alias of a filter ("praca-zdalna;st" -> `zdalna;tr`, "praca;st" -> `praca;l`); any other
  (`praca-dodatkowa;st`, `praca-biurowa;st`, `pracadodatkowa;st`, also with `zdalna;tr`, `1;pg` or a radius) gets a
  302 to itself on page 1 (in a browser too: "Failed to fetch"), while page 2 is served (`praca-dodatkowa;st/2;pg`:
  144 results). So the word "praca" is dropped from the start of a phrase ("praca dodatkowa" -> `dodatkowa;st`,
  493 results, a broader search; "praca biurowa" -> `biurowa;st`), and a phrase with nothing left is skipped with a
  warning (verified live 2026-11-12; "automatyzacja" and "helpdesk" were served with 200 that day, 0 remote results);
- remote: `zdalna;tr` (464 offers; the `workMode` checkbox "Zdalna"): it keeps offers that list "Zdalna" among
  their modes, often next to "Stacjonarna"/"Hybrydowa"; the mode is the most remote one listed. "Mobilna"
  (field work) is on site;
- city: `<slug>;l` (Kraków 1422 offers with the default 20 km); radius `KM;km` from the select's values 5, 10,
  20, 30, 50, 75, 100 (Kraków +50 km: 1872); without it the board applies 20 km;
- work time: `czesc-etatu,dodatkowa;e` (część etatu, praca dodatkowa): 102 of 464 remote offers;
- 40 offers per page; a page past the last one is served with no results (`zdalna;tr/13;pg`);
- order: by `segment` (6 = paid promotion, `isPromoted` on the offer page; 5 = gowork's own postings; 2 = copies
  of other sites' ads), then roughly by `publishedAt`, not strictly (a page of segment 5 mixes 11-03 and 11-12):
  no newest-first order. `publishedAt` is the last refresh; the posting date (`createdAt`, JSON-LD `datePosted`
  on the offer page) can be weeks older. No sort parameter was found;
- dates (verified live 2026-11-12): a listing result carries only `publishedAt` (no `createdAt` or other date in
  the result page), so `published` is the last refresh. The offer page's JSON-LD `datePosted` is its `createdAt`,
  the first publication (3 of 3 sampled offers refreshed 11-11/11-12: datePosted 10-15, 11-10, 10-29);
- the whole board is 26 300 offers (658 pages): about 10 600 own postings (segments 6 and 5, pages 1-265, refreshed
  in the last ~6 weeks; employers post them on gowork: 12 of 15 sampled offers take the application on gowork,
  3 redirect to the employer's ATS), then ~14 000 `/oferta-zewnetrzna/` copies of lento.pl / nuzle.pl ads (segment 2,
  all with the same import date, no work mode, company often "Ogłoszenie zewnętrzne"). The copies are skipped;
- no result cap (verified live 2026-11-12): page 600 of the whole board is served (copies), Kraków (1423 results)
  is served to its last page 36 (23 copies), page 37 is empty, the remote listing (464) ends on page 12 (15 own
  offers). A listing's own postings end on its first page of copies only, which parses to no offers and ends the
  request; `max_pages` (1400, about twice the whole board's 658 pages) is only a safety stop;
- pay: `netSalary` / `grossSalary` {min, max, currency "zł" or "€", period m/h/d} in hundredths (900000 = 9000 zł).
"""
from __future__ import annotations

import re

from ....boards.base import Board, Caps, Request, register
from ....boards.pages import (clean_spaces, epoch_or_iso_date, labelled_contracts, most_remote_mode, nearest_radius,
                              page_script_json, pay_range, prefix_level, slug, worktime_from_labels)
from ....model import Offer
from .vocab import CONTRACTS, FULL_TIME, LEVELS, PART_TIME

BASE = "https://www.gowork.pl"
RADII = (5, 10, 20, 30, 50, 75, 100)  # the radius select's values
PROMOTED_SEGMENT = 6
COPY_SEGMENT = 2
CURRENCY = {"zł": "PLN", "€": "EUR", "$": "USD"}
PERIOD = {"m": "month", "h": "hour", "d": "day", "w": "week", "y": "year"}
_WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef"}


def nuxt_value(table: list, index: int, _depth: int = 0):
    """Value at `index` of a devalue table (Nuxt payload): objects and arrays hold indexes of other entries,
    ["Reactive", i]-style wrappers stand for entry i, ["Set", ...] / ["Date", iso] for those types."""
    if index < 0 or _depth > 60:  # -1 undefined, -2 hole, ... (special values)
        return None
    v = table[index]
    if isinstance(v, dict):
        return {k: nuxt_value(table, i, _depth + 1) for k, i in v.items()}
    if isinstance(v, list):
        if v and isinstance(v[0], str):
            if v[0] in _WRAPPERS:
                return nuxt_value(table, v[1], _depth + 1)
            if v[0] in ("EmptyRef", "EmptyShallowRef"):
                return None
            if v[0] == "Set":
                return [nuxt_value(table, i, _depth + 1) for i in v[1:]]
            if v[0] == "Date":
                return v[1]
        return [nuxt_value(table, i, _depth + 1) for i in v]
    return v


def listing(raw: str) -> dict:
    """data.jobListingData of a result page; ValueError when the page has no Nuxt payload or listing."""
    table = page_script_json(raw, "__NUXT_DATA__")
    if not table:
        raise ValueError("no __NUXT_DATA__ in the page (bot wall or format change)")
    root = table[0] if isinstance(table[0], dict) else table[table[0][1]]  # ["ShallowReactive", 1]
    data = nuxt_value(table, root["data"]) or {}
    jl = data.get("jobListingData")
    if not isinstance(jl, dict):
        raise ValueError("no jobListingData in the Nuxt payload (not a result page)")
    return jl


def pay_text(o: dict) -> str:
    """'salary:9000-33000 PLN/month netto; salary:31.4-31.4 PLN/hour brutto' (amounts come in hundredths)."""
    out = []
    for key, word in (("grossSalary", "brutto"), ("netSalary", "netto")):
        s = o.get(key) or {}
        lo, hi = (round(v / 100, 2) if isinstance(v, (int, float)) else None for v in (s.get("min"), s.get("max")))
        if lo is None and hi is None:
            continue
        cur = CURRENCY.get(s.get("currency") or "zł", s.get("currency") or "PLN")
        out.append(f"{pay_range('salary', lo, hi, cur, PERIOD.get(s.get('period'), 'month'))} {word}")
    return "; ".join(out)


def keyword_slug(phrase: str) -> str:
    """The `;st` slug of a phrase without a leading word "praca" ("praca dodatkowa" -> "dodatkowa"); '' when nothing
    searchable is left or the slug still starts with "praca" ("praca", "pracadodatkowa"): the board answers page 1 of
    every `/praca/praca...;st` search with a redirect to itself."""
    kw = slug(phrase)
    while re.match(r"praca(-|$)", kw):
        kw = kw[len("praca"):].lstrip("-")
    return "" if kw.startswith("praca") else kw


def snippet(o: dict) -> str:
    s = o.get("aiSummary") or {}
    parts = [o.get("title") or ""] + [s.get(k) or "" for k in ("responsibilities", "skills", "experience", "benefits")]
    return clean_spaces(" ".join(parts))[:1000]


@register
class GoWork(Board):
    name = "gowork"
    posting_date_is_first = True  # JSON-LD datePosted = createdAt (first publication); the listing has the refresh date
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=False, page_size=40,
                max_pages=1400, huge_unfiltered=True, transport="http")
    accept = "text/html,application/xhtml+xml"

    def requests(self, s):
        """Phrases with nothing searchable once the leading "praca" is dropped are skipped (see `keyword_slug`)."""
        reqs, warnings = super().requests(s)
        bad = sorted({r.keyword for r in reqs if r.keyword and not keyword_slug(r.keyword)})
        warnings += [f"{self.name}: phrase {kw!r} cannot be searched (the board loops on '/praca/praca...' result "
                     f"pages); skipped for '{s.id}'" for kw in bad]
        return [r for r in reqs if r.keyword not in bad], warnings

    def page_url(self, r: Request, page: int) -> str | None:
        parts = []
        kw = keyword_slug(r.keyword or "")
        if kw:
            parts.append(f"{kw};st")
        if r.params.get("city"):
            parts.append(f"{slug(r.params['city'])};l")
        if r.params.get("part_time"):
            parts.append("czesc-etatu,dodatkowa;e")
        if r.params.get("remote"):
            parts.append("zdalna;tr")
        if page > 1:
            parts.append(f"{page};pg")
        if r.params.get("city") and r.params.get("radius_km") is not None:
            parts.append(f"{nearest_radius(r.params['radius_km'], RADII)};km")
        return f"{BASE}/praca" + "".join("/" + p for p in parts)

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out: dict[str, Offer] = {}
        for o in listing(raw).get("results") or []:
            loc = o.get("firstLocation") or {}
            path = ((loc.get("url") or {}).get("url") or "")
            if o.get("segment") == COPY_SEGMENT or not path.startswith("/oferta/"):
                continue  # copies of other sites' ads (/oferta-zewnetrzna/...)
            url = BASE + path
            key = o.get("id") or url
            if key in out or not o.get("title"):
                continue
            title = clean_spaces(o["title"])[:140]
            out[key] = Offer(
                board=self.name, key=url, url=url, title=title, company=clean_spaces((o.get("company") or {}).get("name")),
                mode=most_remote_mode(o.get("workMode"), "zdaln", "hybryd") if o.get("workMode") else "unknown",
                locations=[loc["city"]] if loc.get("city") else [],
                worktime=worktime_from_labels(o.get("employmentType"), PART_TIME, FULL_TIME),
                contracts=labelled_contracts(o.get("contractType"), CONTRACTS),
                level=prefix_level((o.get("positionLevel") or {}).get("label"), LEVELS),
                category=clean_spaces(o.get("position")), pay_text=pay_text(o),
                published=epoch_or_iso_date(o.get("publishedAt")), promoted=o.get("segment") == PROMOTED_SEGMENT,
                snippet=snippet(o))
        return list(out.values())
