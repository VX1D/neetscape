"""bulldogjob.pl — results ship in `__NEXT_DATA__` (pageProps.jobs, 50 per page), read with a same-origin fetch.

URLs (verified live 2026-11-12): remote `/companies/jobs/s/city,Remote/page,N`, city `/companies/jobs/s/city,<City>`.
The listing ignores keywords and carries no dates and no pay unit.
"""
from __future__ import annotations

import json
import re
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, register
from ....boards.pages import LEVEL_WORDS, clean_spaces, lowest_level, script_json
from ....model import Offer

_SHRINK = script_json("__NEXT_DATA__", """
const p=d.props.pageProps||{};if(!Array.isArray(p.jobs))return '';
return JSON.stringify({total:p.totalCount,offers:p.jobs.map(j=>({id:j.id,title:j.position,company:(j.company||{}).name,
city:j.city,remote:j.remote,remotePossible:(j.environment||{}).remotePossible,level:j.experienceLevel,worktime:j.employmentType,
salary:j.denominatedSalaryLong,b2b:j.contractB2b,uop:j.contractEmployment,other:j.contractOther,skills:j.technologyTags,
redirect:j.redirectTo}))});""")


@register
class BulldogJob(Board):
    name = "bulldogjob"
    caps = Caps(keywords=False, remote="filter", city=True, page_size=50, max_pages=40,
                transport="browser_fetch", origin="https://bulldogjob.pl/")

    def page_url(self, r, page):
        if page > self.caps.max_pages:
            return None
        city = urllib.parse.quote(r.params["city"]) if r.params.get("city") else "Remote"
        return f"https://bulldogjob.pl/companies/jobs/s/city,{city}" + (f"/page,{page}" if page > 1 else "")

    def fetch_js(self):
        return _SHRINK

    def parse(self, raw, r):
        if not raw:
            raise ValueError("no __NEXT_DATA__ jobs in the page (bot wall or format change)")
        out = []
        for j in json.loads(raw)["offers"]:
            if not re.match(r"\d+-", j.get("id") or ""):
                continue
            url = f"https://bulldogjob.pl/companies/jobs/{j['id']}"
            sal = j.get("salary") or {}
            contracts = [infer.contract(c) for c, on in (("b2b", j.get("b2b")), ("permanent", j.get("uop")), ("any", j.get("other"))) if on]
            out.append(Offer(
                board=self.name, key=url, url=url, title=(j.get("title") or "").strip(), company=(j.get("company") or "").strip(),
                mode="remote" if j.get("remote") or j.get("remotePossible") == 100 else "unknown",
                locations=[c.strip() for c in (j.get("city") or "").split(",") if c.strip()],
                worktime=infer.worktime(j.get("worktime") or ""), contracts=contracts,
                level=lowest_level([j.get("level")], LEVEL_WORDS), skills=list(j.get("skills") or []),
                pay_text=clean_spaces(f"{sal.get('money')} {sal.get('currency') or ''}") if sal.get("money") else "",
                snippet=" ".join(j.get("skills") or [])))
        return out
