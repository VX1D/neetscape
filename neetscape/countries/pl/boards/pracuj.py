"""pracuj.pl — results ship in the page's Next.js data (`__NEXT_DATA__`), read with a same-origin fetch.

URLs (verified live 2026-11-12): remote `/praca/<kw>;kw/praca%20zdalna;wm,home-office?pn=N`, city
`/praca/<kw>;kw/<city>;wp?rd=<km>&pn=N` (rd=30 adds nearby towns). No sort parameter: the default order is
roughly newest first. Page size varies (promoted offers), so there is no short-page stop.
"""
from __future__ import annotations

import json
import re
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, register
from ....boards.pages import clean_spaces, epoch_or_iso_date, most_remote_mode, script_json
from ....model import Offer, fold

q = urllib.parse.quote
# one entry per grouped offer (an offer published in several cities)
_SHRINK = script_json("__NEXT_DATA__", """
const qs=((d.props.pageProps||{}).dehydratedState||{}).queries||[];
const r=(qs.find(x=>x.queryKey&&x.queryKey[0]==='jobOffers')||{state:{}}).state.data;if(!r)return '';
const keep=['jobTitle','companyName','lastPublicated','salaryDisplayText','jobDescription','isSuperOffer','positionLevels',
'typesOfContract','workSchedules','workModes'];
return JSON.stringify({total:r.groupedOffersTotalCount,offers:(r.groupedOffers||[]).map(g=>Object.assign(
Object.fromEntries(keep.map(k=>[k,g[k]])),{offers:(g.offers||[]).map(o=>({url:o.offerAbsoluteUri,place:o.displayWorkplace}))}))});""")


@register
class Pracuj(Board):
    name = "pracuj"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, page_size=0, max_pages=60,
                transport="browser_fetch", origin="https://www.pracuj.pl/")

    def page_url(self, r, page):
        if page > self.caps.max_pages:
            return None
        kw = f"{q(r.keyword)};kw/" if r.keyword else ""
        if r.params.get("city"):
            query = {"rd": r.params.get("radius_km", 0)} | ({"pn": page} if page > 1 else {})
            return f"https://www.pracuj.pl/praca/{kw}{q(fold(r.params['city']))};wp?{urllib.parse.urlencode(query)}"
        return f"https://www.pracuj.pl/praca/{kw}praca%20zdalna;wm,home-office" + (f"?pn={page}" if page > 1 else "")

    def fetch_js(self):
        return _SHRINK

    def parse(self, raw, r):
        if not raw:
            raise ValueError("no __NEXT_DATA__ offers in the page (bot wall or format change)")
        out = []
        for g in json.loads(raw)["offers"]:
            urls = sorted(o["url"] for o in g["offers"] if o.get("url"))
            if not urls:
                continue
            schedules = " ".join(g.get("workSchedules") or []).lower()
            out.append(Offer(
                board=self.name, key=urls[0], url=urls[0], title=g.get("jobTitle") or "", company=g.get("companyName") or "",
                mode=most_remote_mode(g.get("workModes"), "zdaln", "hybryd"),
                locations=sorted({o["place"] for o in g["offers"] if o.get("place")}),
                worktime="part_time" if re.search(r"część|dodatkowa", schedules) else "full_time" if "pełny" in schedules else "unknown",
                contracts=infer.contracts_from_text(" ".join(g.get("typesOfContract") or [])),
                level=infer.level_from_text(" ".join(g.get("positionLevels") or [])),
                pay_text=clean_spaces(g.get("salaryDisplayText")), published=epoch_or_iso_date(g.get("lastPublicated")),
                promoted=bool(g.get("isSuperOffer")), snippet=g.get("jobDescription") or ""))
        return out
