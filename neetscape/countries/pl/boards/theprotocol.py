"""theprotocol.it — `__NEXT_DATA__` of the result page (offersResponse, 50 per page), same-origin fetch.

    GET https://theprotocol.it/filtry/zdalna;rw|<city-slug>;wp?kw=K&sort=date&pageNumber=N    (remote: 1244 offers)

Verified live 2026-11-12:
- `kw=<phrase>` (remote: python 293, tester 79, "scrum master" 7, "project manager" 56) matches titles, technologies
  and posting text, also related words (tester -> "QA Automation Engineer"); path forms (`/filtry/python;kw`) and
  `searchTerm=` are ignored. A throttled session answers 403 or, sometimes, an empty result with the keyword dropped
  from `filters.keywords`;
- `sort=date` (and the default order without a keyword) is by the last refresh (`LastRefreshDateUtc`), but
  `published` is `publicationDateUtc`, the first publication: an offer older than one listed after it was refreshed
  and counts as `promoted`, so it never decides a newest-first stop;
- many offers are pracuj.pl postings shown here too (same ids, dates and texts);
- no result cap: the whole board (`/praca`, 4321 offers, `page.count` 87) ends on its short page 87 (21 offers),
  page 88 is empty; Warszawa (2608) ends on page 53 (8). `max_pages` (200, twice the board) is a safety stop;
- no category per offer (2026-11-12, remote page 1, all 50 offers): the offer objects carry no category or
  specialisation field, only `technologies` (read as skills), levels, contracts and work modes.
"""
from __future__ import annotations

import json
import re

from ....boards.base import Board, Caps, Request, register
from ....boards.pages import (LEVEL_WORDS, currency_code, date_of, lowest_level, most_remote_mode, pay_range, script_json,
                              slug, with_query)
from ....model import Offer

BASE = "https://theprotocol.it"
# dictionary.contracts ids -> contracts (4: umowa na zastępstwo, an employment contract; 5: umowa agencyjna;
# 6: umowa o pracę tymczasową, through a temp agency)
CONTRACTS = {0: "employment", 1: "specific_task", 2: "mandate", 3: "b2b", 4: "employment", 5: "other", 6: "temp_agency",
             7: "internship"}

FETCH_JS = script_json("__NEXT_DATA__", """
const r=(d.props.pageProps||{}).offersResponse;if(!r||!r.offers)return '';
return JSON.stringify({total:r.offersCount,page:r.page,keywords:(r.filters||{}).keywords,offers:r.offers.map(o=>({url:o.offerUrlName,title:o.title,company:o.employer,
published:o.publicationDateUtc,modes:o.workModes,levels:(o.positionLevels||[]).map(x=>x.value),
cities:(o.workplace||[]).map(x=>x.city||x.location).filter(Boolean),skills:o.technologies,
contracts:(o.typesOfContracts||[]).map(c=>({id:c.id,salary:c.salary})),about:((o.aboutProject||[])[0]||'').slice(0,300)}))});""")


def unit(text: str) -> str:
    """Pay period of a salary's `timeUnit` labels; month when none is named."""
    text = (text or "").lower()
    return ("hour" if re.search(r"godz|hour|hr", text) else "day" if re.search(r"dzie|day|dai", text)
            else "year" if re.search(r"rok|roczn|year|annual", text) else "month")


def contracts_and_pay(contracts: list[dict]) -> tuple[list[str], str]:
    """The offer's contract types, and one pay range per contract type that states a salary."""
    out, pays = [], []
    for c in contracts or []:
        code = CONTRACTS.get(c.get("id"), "other")
        if code not in out:
            out.append(code)
        sal = c.get("salary") or {}
        if sal.get("from") is not None or sal.get("to") is not None:
            pays.append(pay_range(code, sal.get("from"), sal.get("to"), currency_code(sal.get("currencySymbol") or "zł"),
                                  unit(" ".join(str(v) for v in (sal.get("timeUnit") or {}).values())),
                                  gross=bool(re.search(r"brutto|gross", sal.get("kindName") or "", re.I))))
    return out, "; ".join(pays)


def mark_refreshed(offers: list[Offer]) -> None:
    """Refreshed offers sit among newer ones: an offer older than one listed after it is `promoted`."""
    newest_after = None
    for o in reversed(offers):
        if o.published and newest_after and o.published < newest_after:
            o.promoted = True
        newest_after = max(filter(None, (o.published, newest_after)), default=None)


@register
class TheProtocol(Board):
    name = "theprotocol"
    caps = Caps(keywords=True, remote="filter", city=True, sort_newest=True, page_size=50, max_pages=200,
                transport="browser_fetch", origin=BASE + "/")
    min_interval = {"theprotocol.it": 4.0}  # answers 403 after ~10 requests in a few minutes at 1.5 s (2026-11-12)

    def page_url(self, r: Request, page: int) -> str | None:
        where = slug(r.params["city"]) + ";wp" if r.params.get("city") else "zdalna;rw"
        query = ({"kw": r.keyword} if r.keyword else {}) | ({"sort": "date"} if r.params.get("sort") == "newest" else {}) \
            | ({"pageNumber": page} if page > 1 else {})
        return with_query(f"{BASE}/filtry/{where}", query)

    def fetch_js(self) -> str | None:
        return FETCH_JS

    def parse(self, raw: str, r: Request) -> list[Offer]:
        if not raw:
            raise ValueError("no __NEXT_DATA__ offers in the page (bot wall or format change)")
        data, out = json.loads(raw), []
        if r.keyword and not data["offers"] and not data.get("keywords"):
            raise ValueError("the keyword was dropped from the search (throttled session?)")
        for o in data["offers"]:
            if not o.get("url"):
                continue
            url = f"{BASE}/szczegoly/praca/{o['url']}"
            contracts, pay = contracts_and_pay(o.get("contracts"))
            out.append(Offer(
                board=self.name, key=url, url=url, title=(o.get("title") or "").strip(), company=(o.get("company") or "").strip(),
                mode=most_remote_mode(o.get("modes"), r"zdaln|remote|home", "hybr", r"stacjon|office"),
                locations=sorted(set(o.get("cities") or [])), contracts=contracts,
                level=lowest_level(o.get("levels"), LEVEL_WORDS), skills=list(o.get("skills") or []), pay_text=pay,
                published=date_of(o.get("published")), snippet=o.get("about") or ""))
        mark_refreshed(out)
        return out
