"""theprotocol.it — results ship in `__NEXT_DATA__` (offersResponse, 50 per page), read with a same-origin fetch.

URLs (verified live 2026-11-12): remote `/filtry/zdalna;rw?pageNumber=N` (1244 offers), city `/filtry/<city-slug>;wp`.
- keywords: `?kw=<phrase>` (remote: python 293, tester 79, "scrum master" 7, "project manager" 56); the site
  matches titles, technologies and posting text, also related words (tester -> "QA Automation Engineer").
  Path forms (`/filtry/python;kw`) and `searchTerm=` are ignored. A throttled session answers 403 or, sometimes,
  an empty result with the keyword dropped from `filters.keywords`;
- order: `sort=date` orders by the last refresh (`orderby.field: LastRefreshDateUtc`); without a keyword the
  default order is the same. `published` is `publicationDateUtc`, the first publication: a refreshed offer
  sits among newer ones (its refresh date is not in the listing). An offer older than one listed after it on the
  page is such an offer and counts as `promoted`, so it never decides a newest-first stop;
- many offers are pracuj.pl postings shown here too (same ids, dates and texts).
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ....boards.base import Board, Caps, register
from ....boards.pages import LEVEL_WORDS, epoch_or_iso_date, lowest_level, most_remote_mode, pay_range, script_json, slug
from ....model import Offer

_SHRINK = script_json("__NEXT_DATA__", """
const r=(d.props.pageProps||{}).offersResponse;if(!r||!r.offers)return '';
return JSON.stringify({total:r.offersCount,page:r.page,keywords:(r.filters||{}).keywords,offers:r.offers.map(o=>({url:o.offerUrlName,title:o.title,company:o.employer,
published:o.publicationDateUtc,modes:o.workModes,levels:(o.positionLevels||[]).map(x=>x.value),
cities:(o.workplace||[]).map(x=>x.city||x.location).filter(Boolean),skills:o.technologies,
contracts:(o.typesOfContracts||[]).map(c=>({id:c.id,salary:c.salary})),about:((o.aboutProject||[])[0]||'').slice(0,300)}))});""")
# dictionary.contracts ids -> contracts (4: umowa na zastępstwo, an employment contract; 5: umowa agencyjna;
# 6: umowa o pracę tymczasową, through a temp agency)
CONTRACTS = {0: "employment", 1: "specific_task", 2: "mandate", 3: "b2b", 4: "employment", 5: "other", 6: "temp_agency",
             7: "internship"}
CURRENCIES = {"zł": "PLN", "€": "EUR", "$": "USD", "£": "GBP"}


def unit(text: str) -> str:
    text = (text or "").lower()
    return ("hour" if re.search(r"godz|hour|hr", text) else "day" if re.search(r"dzie|day|dai", text)
            else "year" if re.search(r"rok|roczn|year|annual", text) else "month")


@register
class TheProtocol(Board):
    name = "theprotocol"
    min_interval = {"theprotocol.it": 4.0}  # answers 403 after ~10 requests in a few minutes at 1.5 s (2026-11-12)
    caps = Caps(keywords=True, remote="filter", city=True, sort_newest=True, page_size=50, max_pages=40,
                transport="browser_fetch", origin="https://theprotocol.it/")

    def page_url(self, r, page):
        if page > self.caps.max_pages:
            return None
        where = slug(r.params["city"]) + ";wp" if r.params.get("city") else "zdalna;rw"
        query = ({"kw": r.keyword} if r.keyword else {}) | ({"sort": "date"} if r.params.get("sort") == "newest" else {}) \
            | ({"pageNumber": page} if page > 1 else {})
        return f"https://theprotocol.it/filtry/{where}" + (f"?{urllib.parse.urlencode(query)}" if query else "")

    def fetch_js(self):
        return _SHRINK

    def parse(self, raw, r):
        if not raw:
            raise ValueError("no __NEXT_DATA__ offers in the page (bot wall or format change)")
        data, out = json.loads(raw), []
        if r.keyword and not data["offers"] and not data.get("keywords"):
            raise ValueError("the keyword was dropped from the search (throttled session?)")
        for o in data["offers"]:
            if not o.get("url"):
                continue
            url = f"https://theprotocol.it/szczegoly/praca/{o['url']}"
            contracts, pays = [], []
            for c in o.get("contracts") or []:
                code = CONTRACTS.get(c.get("id"), "other")
                if code not in contracts:
                    contracts.append(code)
                sal = c.get("salary") or {}
                if sal.get("from") is not None or sal.get("to") is not None:
                    cur = sal.get("currencySymbol") or "zł"
                    pays.append(pay_range(code, sal.get("from"), sal.get("to"),
                                          CURRENCIES.get(cur, cur.upper()),
                                          unit(" ".join(str(v) for v in (sal.get("timeUnit") or {}).values())),
                                          gross=bool(re.search(r"brutto|gross", sal.get("kindName") or "", re.I))))
            out.append(Offer(
                board=self.name, key=url, url=url, title=(o.get("title") or "").strip(), company=(o.get("company") or "").strip(),
                mode=most_remote_mode(o.get("modes"), r"zdaln|remote|home", "hybr", r"stacjon|office"), locations=sorted(set(o.get("cities") or [])),
                contracts=contracts, level=lowest_level(o.get("levels"), LEVEL_WORDS), skills=list(o.get("skills") or []),
                pay_text="; ".join(pays), published=epoch_or_iso_date(o.get("published")), snippet=o.get("about") or ""))
        newest_after = None  # refreshed offers: older than an offer listed after them
        for o in reversed(out):
            if o.published and newest_after and o.published < newest_after:
                o.promoted = True
            newest_after = max(filter(None, (o.published, newest_after)), default=None)
        return out
