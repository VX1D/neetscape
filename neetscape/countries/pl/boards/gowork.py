"""gowork.pl — results from the Nuxt payload of the result page (`__NUXT_DATA__`), over plain HTTP (the pages are
served to a plain client; robots.txt allows `/praca` and `/oferta/`, disallows `/oferta/*/aplikuj` and
`/click-out/`).

    GET https://www.gowork.pl/praca/[<kw>;st/][<city>;l/][<types>;e/][zdalna;tr/][N;pg/][KM;km]

Verified live 2026-11-12:
- path segments in the order of the board's own `seo.next` links (`krakow;l/2;pg/50;km`,
  `czesc-etatu;e/zdalna;tr/2;pg`);
- keywords: `<slug>;st`, the slug of the typed text ("automatyzacja procesów" -> `automatyzacja-procesow;st`, 4
  offers), searched in position names and titles; a slug close to a known position is redirected (302) to it
  ("python" -> `programista-python;st`, 24 offers). A slug starting with "praca" is a filter alias
  ("praca-zdalna;st" -> `zdalna;tr`, "praca;st" -> `praca;l`), or any other (`praca-dodatkowa;st`,
  `praca-biurowa;st`, `pracadodatkowa;st`, also with `zdalna;tr`, `1;pg` or a radius) gets a 302 to itself on page 1
  (in a browser too: "Failed to fetch") while page 2 is served (`praca-dodatkowa;st/2;pg`: 144 results). So a
  leading word "praca" is dropped ("praca dodatkowa" -> `dodatkowa;st`, 493 results, a broader search; "praca
  biurowa" -> `biurowa;st`) and a phrase with nothing left is skipped with a warning ("automatyzacja" and "helpdesk"
  were served with 200 that day, 0 remote results);
- remote: `zdalna;tr` (464 offers; the `workMode` checkbox "Zdalna") keeps offers listing "Zdalna" among their
  modes, often next to "Stacjonarna"/"Hybrydowa": the mode is the most remote one listed; "Mobilna" (field work) is
  on site;
- city: `<slug>;l` (Kraków 1422 offers with the default 20 km); radius `KM;km` from the select's values 5, 10, 20,
  30, 50, 75, 100 (Kraków +50 km: 1872); without it the board applies 20 km;
- work time: `czesc-etatu,dodatkowa;e` (część etatu, praca dodatkowa): 102 of 464 remote offers;
- 40 offers per page; a page past the last one is served with no results (`zdalna;tr/13;pg`);
- order: by `segment` (6 = paid promotion, `isPromoted` on the offer page; 5 = gowork's own postings; 2 = copies of
  other sites' ads), then roughly, not strictly, by `publishedAt` (a page of segment 5 mixes 11-03 and 11-12): no
  newest-first order, and no sort parameter was found;
- dates: a listing result carries only `publishedAt`, the last refresh, so that is `published`. The offer page's
  JSON-LD `datePosted` is its `createdAt`, the first publication, often weeks older (3 of 3 sampled offers refreshed
  11-11/11-12: datePosted 10-15, 11-10, 10-29);
- the whole board is 26 300 offers (658 pages): about 10 600 own postings (segments 6 and 5, pages 1-265, refreshed
  in the last ~6 weeks; 12 of 15 sampled take the application on gowork, 3 redirect to the employer's ATS), then
  ~14 000 `/oferta-zewnetrzna/` copies of lento.pl / nuzle.pl ads (segment 2, one import date, no work mode, company
  often "Ogłoszenie zewnętrzne"), which are skipped;
- no result cap: page 600 of the whole board is served (copies); Kraków (1423 results) is served to its last page 36
  (23 copies), page 37 is empty; the remote listing (464) ends on page 12 (15 own offers). A listing's own postings
  end on its first page of copies, which parses to no offers and ends the request; `max_pages` (1400, about twice
  the whole board) is only a safety stop;
- pay: `netSalary` / `grossSalary` {min, max, currency "zł" or "€", period m/h/d} in hundredths (900000 = 9000 zł).
"""
from __future__ import annotations

import re

from ....boards.base import Board, Caps, Request, register
from ....boards.pages import (clean_spaces, currency_code, date_of, labelled_contracts, most_remote_mode, nearest_radius,
                              nuxt_data, pay_range, prefix_level, present, slug, snippet, worktime_from_labels)
from ....model import Offer, Search
from .vocab import CONTRACTS, FULL_TIME, LANGS, LEVELS, PART_TIME

BASE = "https://www.gowork.pl"
RADII = (5, 10, 20, 30, 50, 75, 100)  # the radius select's values
PROMOTED_SEGMENT = 6
COPY_SEGMENT = 2
PERIOD = {"m": "month", "h": "hour", "d": "day", "w": "week", "y": "year"}


def listing(raw: str) -> dict:
    """data.jobListingData of a result page; ValueError when the page has no Nuxt payload or listing."""
    jl = (nuxt_data(raw) or {}).get("jobListingData")
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
        cur, unit = currency_code(s.get("currency") or "zł"), PERIOD.get(s.get("period"), "month")
        out.append(f"{pay_range('salary', lo, hi, cur, unit)} {word}")
    return "; ".join(out)


def keyword_slug(phrase: str) -> str:
    """The `;st` slug of a phrase without a leading word "praca" ("praca dodatkowa" -> "dodatkowa"); '' when nothing
    searchable is left or the slug still starts with "praca" ("praca", "pracadodatkowa"): the board answers page 1 of
    every `/praca/praca...;st` search with a redirect to itself."""
    kw = slug(phrase)
    while re.match(r"praca(-|$)", kw):
        kw = kw[len("praca"):].lstrip("-")
    return "" if kw.startswith("praca") else kw


def summary(o: dict) -> str:
    """The card's title and the board's AI summary of the posting."""
    s = o.get("aiSummary") or {}
    return snippet(o.get("title") or "", *(s.get(k) or "" for k in ("responsibilities", "skills", "experience", "benefits")))


@register
class GoWork(Board):
    name = "gowork"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, page_size=40, max_pages=1400,
                huge_unfiltered=True, transport="http")
    accept = "text/html,application/xhtml+xml"
    posting_date_is_first = True  # JSON-LD datePosted = createdAt (first publication); the listing has the refresh date

    def requests(self, s: Search) -> tuple[list[Request], list[str]]:
        """Phrases with nothing searchable once the leading "praca" is dropped are skipped (see `keyword_slug`)."""
        reqs, warnings = super().requests(s)
        bad = sorted({r.keyword for r in reqs if r.keyword and not keyword_slug(r.keyword)})
        warnings += [f"{self.name}: phrase {kw!r} cannot be searched (the board loops on '/praca/praca...' result "
                     f"pages); skipped for '{s.id}'" for kw in bad]
        return [r for r in reqs if r.keyword not in bad], warnings

    def page_url(self, r: Request, page: int) -> str | None:
        p = r.params
        kw = keyword_slug(r.keyword or "")
        parts = [f"{kw};st" if kw else "", f"{slug(p['city'])};l" if p.get("city") else "",
                 "czesc-etatu,dodatkowa;e" if p.get("part_time") else "", "zdalna;tr" if p.get("remote") else "",
                 f"{page};pg" if page > 1 else "",
                 f"{nearest_radius(p['radius_km'], RADII)};km" if p.get("city") and p.get("radius_km") is not None else ""]
        return f"{BASE}/praca" + "".join("/" + x for x in parts if x)

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out: dict[str, Offer] = {}
        for o in listing(raw).get("results") or []:
            loc = o.get("firstLocation") or {}
            path = (loc.get("url") or {}).get("url") or ""
            if o.get("segment") == COPY_SEGMENT or not path.startswith("/oferta/"):
                continue  # copies of other sites' ads (/oferta-zewnetrzna/...)
            url = BASE + path
            key = o.get("id") or url
            if key in out or not o.get("title"):
                continue
            out[key] = Offer(
                board=self.name, key=url, url=url, title=clean_spaces(o["title"])[:140],
                company=clean_spaces((o.get("company") or {}).get("name")),
                mode=most_remote_mode(o.get("workMode"), "zdaln", "hybryd") if o.get("workMode") else "unknown",
                locations=present(loc.get("city")),
                worktime=worktime_from_labels(o.get("employmentType"), PART_TIME, FULL_TIME),
                contracts=labelled_contracts(o.get("contractType"), CONTRACTS, LANGS),
                level=prefix_level((o.get("positionLevel") or {}).get("label"), LEVELS),
                category=clean_spaces(o.get("position")), pay_text=pay_text(o),
                published=date_of(o.get("publishedAt")), promoted=o.get("segment") == PROMOTED_SEGMENT,
                snippet=summary(o))
        return list(out.values())
