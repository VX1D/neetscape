"""solid.jobs — JSON API, one document per division (the whole division in one download).

    GET https://solid.jobs/api/offers?division=it&sortOrder=default   Accept: application/vnd.solidjobs.jobofferlist+json

Mode and city are filtered locally.
"""
from __future__ import annotations

import json

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import feed_date
from ....model import Offer

MODES = {"W całości": "remote", "Możliwa w całości": "remote", "Dowolnie": "remote",
         "Hybrydowo": "hybrid", "Możliwa częściowo": "hybrid", "Brak": "onsite"}
CONTRACTS = {"B2B": "b2b", "UoP": "uop", "Umowa o pracę": "uop", "UZ": "mandate", "Umowa zlecenie": "mandate", "UoD": "specific_task"}


@register
class SolidJobs(Board):
    name = "solidjobs"
    caps = Caps(keywords=False, remote="no", page_size=0, max_pages=1, local_all=True, transport="http")
    accept = "application/vnd.solidjobs.jobofferlist+json"
    divisions = ("it",)

    def requests(self, s):
        reqs, warns = super().requests(s)
        return [Request(self.name, s.id, None, {"division": d}, r.pushed) for d in self.divisions for r in reqs[:1]], warns

    def page_url(self, r: Request, page: int) -> str | None:
        return f"https://solid.jobs/api/offers?division={r.params['division']}&sortOrder=default" if page == 1 else None

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out = []
        for o in json.loads(raw):
            url = f"https://solid.jobs/offer/{o['id']}/{o.get('jobOfferUrl', '')}"
            sr = o.get("salaryRange") or {}
            pay = f"{sr.get('lowerBound')}-{sr.get('upperBound')} {sr.get('currency', '')}/{(sr.get('salaryPeriod') or '').lower()}" if sr.get("lowerBound") else ""
            out.append(Offer(board=self.name, key=url, url=url, title=o.get("jobTitle") or "", company=o.get("companyName") or "",
                             mode=MODES.get(o.get("remotePossible") or "", "unknown"), locations=[o["companyCity"]] if o.get("companyCity") else [],
                             worktime="full_time" if (o.get("workload") or "100%") == "100%" else "part_time",
                             contracts=[CONTRACTS.get(sr.get("employmentType", ""), "other")] if sr else [],
                             level=infer.level(o.get("experienceLevel")), category=f"{o.get('mainCategory', '')}/{o.get('subCategory', '')}",
                             skills=[x.get("name", "") for x in o.get("requiredSkills") or []], pay_text=pay,
                             published=feed_date(o.get("validFrom"))))
        return out
