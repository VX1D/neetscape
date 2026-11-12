"""pracuj.pl — results ship in the page's Next.js data (`__NEXT_DATA__`), read with a same-origin fetch.

URLs (verified live 2026-11-12): remote `/praca/<kw>;kw/praca%20zdalna;wm,home-office?pn=N`, city
`/praca/<kw>;kw/<city>;wp?rd=<km>&pn=N` (Kraków: 4233 offers with rd=0, 4982 with rd=30; city listings also
hold offers marked "whole Poland"), no keyword (`/praca/praca%20zdalna;wm,home-office`: 2459 remote offers).
50 grouped offers per page (`rop`), but the last page is not reliably short, so there is no short-page stop.
- part-time: `ws=1,2` (część etatu, dodatkowa / tymczasowa): 316 of 2459 remote offers;
- order: without a keyword the listing is newest first (strictly by `lastPublicated`, the date the card shows).
  With a keyword it is by relevance; `sc=0` sorts by day but by relevance within a day, so a page of known
  offers can hide new ones further down: keyword requests are therefore not treated as newest first;
- dates: `initialPublicated` is the posting date (the posting's JSON-LD `datePosted`); `lastPublicated` is
  the last refresh, the date the listing is sorted by. ~75% of the offers listed today were first published
  up to 30 days earlier, so `published` is the posting date and refreshed offers count as `promoted`: their
  place in the order says nothing about their date, so they never decide a newest-first stop. `isSuperOffer`
  (a paid product on 30-90% of a page) is not promotion: such offers keep their date order.
"""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import replace

from .... import infer
from ....boards.base import Board, Caps, register
from ....boards.pages import (clean_spaces, epoch_or_iso_date, labelled_contracts, lowest, most_remote_mode,
                              page_script_json, prefix_level, script_json, worktime_from_labels)
from ....model import Offer, fold
from .vocab import CONTRACTS, FULL_TIME, LEVELS, PART_TIME

q = urllib.parse.quote
# one entry per grouped offer (an offer published in several cities)
_SHRINK = script_json("__NEXT_DATA__", """
const qs=((d.props.pageProps||{}).dehydratedState||{}).queries||[];
const r=(qs.find(x=>x.queryKey&&x.queryKey[0]==='jobOffers')||{state:{}}).state.data;if(!r)return '';
const keep=['jobTitle','companyName','lastPublicated','initialPublicated','salaryDisplayText','jobDescription','isSuperOffer','positionLevels',
'typesOfContract','workSchedules','workModes'];
return JSON.stringify({total:r.groupedOffersTotalCount,offers:(r.groupedOffers||[]).map(g=>Object.assign(
Object.fromEntries(keep.map(k=>[k,g[k]])),{offers:(g.offers||[]).map(o=>({url:o.offerAbsoluteUri,place:o.displayWorkplace}))}))});""")


def _section_lines(sec: dict) -> list[str]:
    """One section of an offer page (`sections` in its Next.js data): its title, then bullets, paragraphs or
    dictionary items (technologies), then its sub-sections."""
    m = sec.get("model") or {}
    lines = [sec["title"]] if sec.get("title") else []
    for key in ("bullets", "paragraphs", "items", "customItems"):
        for v in m.get(key) or []:
            v = v.get("name", "") if isinstance(v, dict) else v
            lines += [clean_spaces(v)] if v else []
    for sub in sec.get("subSections") or []:
        lines += _section_lines(sub)
    return lines


def posting_text(page: str) -> str:
    """The posting body of an offer page: its sections (responsibilities, requirements, nice to have, offer,
    technologies), in page order. The page's JSON-LD carries only the employer's blurb."""
    data = page_script_json(page, "__NEXT_DATA__") or {}
    queries = ((data.get("props") or {}).get("pageProps") or {}).get("dehydratedState", {}).get("queries") or []
    offer = next((q["state"]["data"] for q in queries if isinstance((q.get("state") or {}).get("data"), dict)
                  and "sections" in q["state"]["data"]), None)
    if not offer:
        return ""
    return "\n\n".join("\n".join(lines) for sec in offer["sections"] if (lines := _section_lines(sec)))


def level(values) -> str:
    """The lowest of the board levels an offer lists, by the board's words, else by the label's text."""
    return lowest(lv if (lv := prefix_level(v, LEVELS)) != "unknown" else infer.level_from_text(v.lower())
                  for v in values or [])


@register
class Pracuj(Board):
    name = "pracuj"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=True, page_size=0,
                max_pages=60, transport="browser_fetch", origin="https://www.pracuj.pl/")

    def requests(self, s):
        """Only listings without a keyword are newest first (see the module docstring)."""
        reqs, warnings = super().requests(s)
        return [replace(r, params={k: v for k, v in r.params.items() if k != "sort"}) if r.keyword else r
                for r in reqs], warnings

    def page_url(self, r, page):
        if page > self.caps.max_pages:
            return None
        kw = f"{q(r.keyword)};kw/" if r.keyword else ""
        query = {"ws": "1,2"} if r.params.get("part_time") else {}
        if page > 1:
            query["pn"] = page
        if r.params.get("city"):
            query = {"rd": r.params.get("radius_km", 0)} | query
            return f"https://www.pracuj.pl/praca/{kw}{q(fold(r.params['city']))};wp?{urllib.parse.urlencode(query)}"
        return f"https://www.pracuj.pl/praca/{kw}praca%20zdalna;wm,home-office" + (f"?{urllib.parse.urlencode(query)}" if query else "")

    def fetch_js(self):
        return _SHRINK

    def posting(self, page):
        meta = super().posting(page)
        body = posting_text(page)
        if body:
            meta["description"], meta["source"] = body, "board"
        return meta

    def parse(self, raw, r):
        if not raw:
            raise ValueError("no __NEXT_DATA__ offers in the page (bot wall or format change)")
        out = []
        for g in json.loads(raw)["offers"]:
            urls = sorted(o["url"] for o in g["offers"] if o.get("url"))
            if not urls:
                continue
            published = epoch_or_iso_date(g.get("initialPublicated") or g.get("lastPublicated"))
            out.append(Offer(
                board=self.name, key=urls[0], url=urls[0], title=g.get("jobTitle") or "", company=g.get("companyName") or "",
                mode=most_remote_mode(g.get("workModes"), "zdaln", "hybryd"),
                locations=sorted({o["place"] for o in g["offers"] if o.get("place")}),
                worktime=worktime_from_labels(g.get("workSchedules"), PART_TIME, FULL_TIME),
                contracts=labelled_contracts(g.get("typesOfContract"), CONTRACTS), level=level(g.get("positionLevels")),
                pay_text=clean_spaces(g.get("salaryDisplayText")), published=published, snippet=g.get("jobDescription") or "",
                promoted=published != epoch_or_iso_date(g.get("lastPublicated"))))
        return out
