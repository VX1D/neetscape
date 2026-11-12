"""pracuj.pl — the Next.js data of the result page (`__NEXT_DATA__`), same-origin fetch, cut down in the tab.

    GET https://www.pracuj.pl/praca/[<kw>;kw/]praca%20zdalna;wm,home-office?ws=1,2&pn=N    (remote, no city)
        https://www.pracuj.pl/praca/[<kw>;kw/]<city>;wp?rd=KM&ws=1,2&pn=N

Verified live 2026-11-12:
- remote without keyword: 2459 offers, 316 with `ws=1,2` (część etatu, dodatkowa / tymczasowa); Kraków 4233 with
  rd=0, 4982 with rd=30 (city listings also hold offers marked "whole Poland");
- 50 grouped offers per page (`rop`), but the last page is not reliably short. No result cap: the whole board
  (`/praca`, 47 755 offers) ends on page 956 (5 test offers), page 957 is empty; Warszawa +30 km pages 100 and 150
  are full. A listing ends on its empty page; `max_pages` (2000, twice the board) is a safety stop;
- without a keyword the listing is strictly newest first by `lastPublicated` (the date the card shows); with one it
  is by relevance (`sc=0`: by day, by relevance within a day), so keyword requests are not newest first;
- `initialPublicated` is the posting date (JSON-LD `datePosted`), `lastPublicated` the last refresh. ~75% of the
  offers listed today were first published up to 30 days earlier, so `published` is the posting date and refreshed
  offers count as `promoted` (they never decide a newest-first stop). `isSuperOffer` (a paid product on 30-90% of a
  page) keeps its date order: not promoted;
- the offer page's JSON-LD carries only the employer's blurb; the posting is in its Next.js `sections`.
"""
from __future__ import annotations

import json
from dataclasses import replace
from urllib.parse import quote

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import (clean_spaces, date_of, labelled_contracts, lowest, most_remote_mode, page_script_json, places,
                              prefix_level, script_json, with_query, worktime_from_labels)
from ....model import Offer, Search, fold
from .vocab import CONTRACTS, FULL_TIME, LEVELS, PART_TIME

BASE = "https://www.pracuj.pl"
REMOTE = "praca%20zdalna;wm,home-office"

# one entry per grouped offer (an offer published in several cities)
FETCH_JS = script_json("__NEXT_DATA__", """
const qs=((d.props.pageProps||{}).dehydratedState||{}).queries||[];
const r=(qs.find(x=>x.queryKey&&x.queryKey[0]==='jobOffers')||{state:{}}).state.data;if(!r)return '';
const keep=['jobTitle','companyName','lastPublicated','initialPublicated','salaryDisplayText','jobDescription','isSuperOffer','positionLevels',
'typesOfContract','workSchedules','workModes'];
return JSON.stringify({total:r.groupedOffersTotalCount,offers:(r.groupedOffers||[]).map(g=>Object.assign(
Object.fromEntries(keep.map(k=>[k,g[k]])),{offers:(g.offers||[]).map(o=>({url:o.offerAbsoluteUri,place:o.displayWorkplace}))}))});""")


def section_lines(sec: dict) -> list[str]:
    """One section of an offer page (`sections` in its Next.js data): its title, then bullets, paragraphs or
    dictionary items (technologies), then its sub-sections."""
    m = sec.get("model") or {}
    lines = [sec["title"]] if sec.get("title") else []
    for key in ("bullets", "paragraphs", "items", "customItems"):
        for v in m.get(key) or []:
            v = v.get("name", "") if isinstance(v, dict) else v
            lines += [clean_spaces(v)] if v else []
    for sub in sec.get("subSections") or []:
        lines += section_lines(sub)
    return lines


def posting_text(page: str) -> str:
    """The posting body of an offer page: its sections (responsibilities, requirements, nice to have, offer,
    technologies), in page order."""
    data = page_script_json(page, "__NEXT_DATA__") or {}
    queries = ((data.get("props") or {}).get("pageProps") or {}).get("dehydratedState", {}).get("queries") or []
    offer = next((q["state"]["data"] for q in queries if isinstance((q.get("state") or {}).get("data"), dict)
                  and "sections" in q["state"]["data"]), None)
    if not offer:
        return ""
    return "\n\n".join("\n".join(lines) for sec in offer["sections"] if (lines := section_lines(sec)))


def level(values) -> str:
    """The lowest of the board levels an offer lists, by the board's words, else by the label's text."""
    return lowest(lv if (lv := prefix_level(v, LEVELS)) != "unknown" else infer.level_from_text(v.lower())
                  for v in values or [])


@register
class Pracuj(Board):
    name = "pracuj"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=True, max_pages=2000,
                transport="browser_fetch", origin=BASE + "/")

    def requests(self, s: Search) -> tuple[list[Request], list[str]]:
        """Only listings without a keyword are newest first (see the module docstring)."""
        reqs, warnings = super().requests(s)
        return [replace(r, params={k: v for k, v in r.params.items() if k != "sort"}) if r.keyword else r
                for r in reqs], warnings

    def page_url(self, r: Request, page: int) -> str | None:
        kw = f"{quote(r.keyword)};kw/" if r.keyword else ""
        query = ({"rd": r.params.get("radius_km", 0)} if r.params.get("city") else {}) \
            | ({"ws": "1,2"} if r.params.get("part_time") else {}) | ({"pn": page} if page > 1 else {})
        where = f"{quote(fold(r.params['city']))};wp" if r.params.get("city") else REMOTE
        return with_query(f"{BASE}/praca/{kw}{where}", query)

    def fetch_js(self) -> str | None:
        return FETCH_JS

    def parse(self, raw: str, r: Request) -> list[Offer]:
        if not raw:
            raise ValueError("no __NEXT_DATA__ offers in the page (bot wall or format change)")
        out = []
        for g in json.loads(raw)["offers"]:
            urls = sorted(o["url"] for o in g["offers"] if o.get("url"))
            if not urls:
                continue
            published = date_of(g.get("initialPublicated") or g.get("lastPublicated"))
            out.append(Offer(
                board=self.name, key=urls[0], url=urls[0], title=g.get("jobTitle") or "", company=g.get("companyName") or "",
                mode=most_remote_mode(g.get("workModes"), "zdaln", "hybryd"),
                locations=places(o.get("place") for o in g["offers"]),
                worktime=worktime_from_labels(g.get("workSchedules"), PART_TIME, FULL_TIME),
                contracts=labelled_contracts(g.get("typesOfContract"), CONTRACTS), level=level(g.get("positionLevels")),
                pay_text=clean_spaces(g.get("salaryDisplayText")), published=published, snippet=g.get("jobDescription") or "",
                promoted=published != date_of(g.get("lastPublicated"))))
        return out

    def posting_body(self, page: str) -> str:
        return posting_text(page)
