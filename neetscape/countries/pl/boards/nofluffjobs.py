"""nofluffjobs — results ship as Angular transfer state (`serverApp-state`), read with a same-origin fetch.

URLs: remote `/pl/praca-zdalna?criteria=keyword%3D<kw>&page=N`, city `/pl/<city-slug>?...`. Page N holds the
offers of pages 1..N ("load more", 20 per page), so later pages repeat earlier offers (deduplicated by key)
and there is no short-page stop. No sort parameter.
"""
from __future__ import annotations

import json
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, register
from ....boards.pages import LEVEL_WORDS, epoch_or_iso_date, lowest_level, pay_range, script_json, slug
from ....model import Offer

q = urllib.parse.quote
_SHRINK = script_json("serverApp-state", """
const v=Object.values(d).find(x=>x&&Array.isArray(x.postings));if(!v)return '';
return JSON.stringify({total:v.totalCount,pages:v.totalPages,offers:v.postings.map(p=>({url:p.url,title:p.title,company:p.name,
posted:p.posted,renewed:p.renewed,category:p.category,seniority:p.seniority,salary:p.salary,promoted:!!(p.highlighted||p.topInSearch),
remote:!!((p.location||{}).fullyRemote||p.fullyRemote),type:(p.location||{}).type||'',
cities:((p.location||{}).places||[]).map(x=>x.city).filter(Boolean),
skills:((p.tiles||{}).values||[]).filter(x=>x.type==='requirement').map(x=>x.value)}))});""")
CONTRACTS = {"zlecenie": "mandate_contract", "uz": "mandate_contract", "uod": "specific_task_contract"}  # -> infer.contract


@register
class NoFluffJobs(Board):
    name = "nofluffjobs"
    caps = Caps(keywords=True, remote="filter", city=True, max_pages=8,
                transport="browser_fetch", origin="https://nofluffjobs.com/pl")

    def page_url(self, r, page):
        if page > self.caps.max_pages:
            return None
        where = slug(r.params["city"]) if r.params.get("city") else "praca-zdalna"
        crit = f"?criteria=keyword%3D{q(r.keyword)}" if r.keyword else "?"
        return f"https://nofluffjobs.com/pl/{where}{crit}" + (f"&page={page}" if page > 1 else "")

    def fetch_js(self):
        return _SHRINK

    def parse(self, raw, r):
        if not raw:
            raise ValueError("no serverApp-state postings in the page (bot wall or format change)")
        out, seen = [], set()
        for p in json.loads(raw)["offers"]:
            if not p.get("url") or p["url"] in seen:
                continue
            seen.add(p["url"])
            url = f"https://nofluffjobs.com/pl/job/{p['url']}"
            sal = p.get("salary") or {}
            kind = str(sal.get("type") or "").lower()
            pay = (pay_range(kind, sal["from"], sal["to"], sal.get("currency") or "PLN", str(sal.get("period") or "month").lower())
                   if sal.get("from") is not None and sal.get("to") is not None else "")
            ltype = (p.get("type") or "").lower()
            dates = [d for d in (epoch_or_iso_date(p.get("posted")), epoch_or_iso_date(p.get("renewed"))) if d]
            out.append(Offer(
                board=self.name, key=url, url=url, title=(p.get("title") or "").strip(), company=(p.get("company") or "").strip(),
                mode="remote" if p.get("remote") or ltype == "remote" else infer.mode(ltype),
                locations=sorted({c for c in p.get("cities") or [] if c.lower() != "remote"}),
                contracts=[infer.contract(CONTRACTS.get(kind, kind))] if kind else [],
                level=lowest_level(p.get("seniority"), LEVEL_WORDS), category=p.get("category") or "", skills=list(p.get("skills") or []),
                pay_text=pay, published=max(dates) if dates else None, promoted=bool(p.get("promoted")),
                snippet=" ".join(p.get("skills") or [])))
        return out
