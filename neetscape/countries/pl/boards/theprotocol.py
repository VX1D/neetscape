"""theprotocol.it — results ship in `__NEXT_DATA__` (offersResponse, 50 per page), read with a same-origin fetch.

URLs (verified live 2026-11-12): remote `/filtry/zdalna;rw?pageNumber=N`, city `/filtry/<city-slug>;wp`.
The listings ignore keywords: everything remote (or in the city) is fetched and filtered locally.
"""
from __future__ import annotations

import json
import re

from .... import infer
from ....boards.base import Board, Caps, register
from ....boards.pages import LEVEL_WORDS, epoch_or_iso_date, lowest_level, most_remote_mode, pay_range, script_json, slug
from ....model import Offer

_SHRINK = script_json("__NEXT_DATA__", """
const r=(d.props.pageProps||{}).offersResponse;if(!r||!r.offers)return '';
return JSON.stringify({total:r.offersCount,page:r.page,offers:r.offers.map(o=>({url:o.offerUrlName,title:o.title,company:o.employer,
published:o.publicationDateUtc,modes:o.workModes,levels:(o.positionLevels||[]).map(x=>x.value),
cities:(o.workplace||[]).map(x=>x.city||x.location).filter(Boolean),skills:o.technologies,
contracts:(o.typesOfContracts||[]).map(c=>({id:c.id,salary:c.salary})),about:((o.aboutProject||[])[0]||'').slice(0,300)}))});""")
CONTRACTS = {0: "permanent", 1: "specific_task_contract", 2: "mandate_contract", 3: "b2b", 7: "internship"}  # dictionary.contracts ids
CURRENCIES = {"zł": "PLN", "€": "EUR", "$": "USD", "£": "GBP"}


def unit(text: str) -> str:
    text = (text or "").lower()
    return ("hour" if re.search(r"godz|hour|hr", text) else "day" if re.search(r"dzie|day|dai", text)
            else "year" if re.search(r"rok|roczn|year|annual", text) else "month")


@register
class TheProtocol(Board):
    name = "theprotocol"
    caps = Caps(keywords=False, remote="filter", city=True, page_size=50, max_pages=40,
                transport="browser_fetch", origin="https://theprotocol.it/")

    def page_url(self, r, page):
        if page > self.caps.max_pages:
            return None
        where = slug(r.params["city"]) + ";wp" if r.params.get("city") else "zdalna;rw"
        return f"https://theprotocol.it/filtry/{where}" + (f"?pageNumber={page}" if page > 1 else "")

    def fetch_js(self):
        return _SHRINK

    def parse(self, raw, r):
        if not raw:
            raise ValueError("no __NEXT_DATA__ offers in the page (bot wall or format change)")
        out = []
        for o in json.loads(raw)["offers"]:
            if not o.get("url"):
                continue
            url = f"https://theprotocol.it/szczegoly/praca/{o['url']}"
            contracts, pays = [], []
            for c in o.get("contracts") or []:
                code = infer.contract(CONTRACTS.get(c.get("id"), "any"))
                if code not in contracts:
                    contracts.append(code)
                sal = c.get("salary") or {}
                if sal.get("from") is not None or sal.get("to") is not None:
                    cur = sal.get("currencySymbol") or "zł"
                    pays.append(pay_range(code, sal.get("from", sal.get("to")), sal.get("to", sal.get("from")),
                                          CURRENCIES.get(cur, cur.upper()),
                                          unit(" ".join(str(v) for v in (sal.get("timeUnit") or {}).values())),
                                          gross="brutto" in (sal.get("kindName") or "").lower()))
            out.append(Offer(
                board=self.name, key=url, url=url, title=(o.get("title") or "").strip(), company=(o.get("company") or "").strip(),
                mode=most_remote_mode(o.get("modes"), r"zdaln|remote|home", "hybr", r"stacjon|office"), locations=sorted(set(o.get("cities") or [])),
                contracts=contracts, level=lowest_level(o.get("levels"), LEVEL_WORDS), skills=list(o.get("skills") or []),
                pay_text="; ".join(pays), published=epoch_or_iso_date(o.get("published")), snippet=o.get("about") or ""))
        return out
