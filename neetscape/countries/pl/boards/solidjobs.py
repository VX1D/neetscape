"""solid.jobs — JSON API, one document per division (the whole division in one download).

    GET https://solid.jobs/api/offers?division=it&sortOrder=default   Accept: application/vnd.solidjobs.jobofferlist+json

Verified live 2026-11-12: eight divisions (the site's /offers/<division> pages): it 1460 offers, sales 820,
engineering 311, marketing 292, logistics 249, finances 237, other 207, hr 123; every offer is in one division
only. An unknown division is a 400. Every offer has a pay range in PLN per month (hourly rates come converted,
"przeliczone z 170 – 210 PLN/h" on the page) and some a second one for another contract type
(`secondarySalaryRange`, the page shows "B2B / Umowa o pracę" and both ranges). `validFrom` is the date the
page shows as "Dodane N dni temu". Mode and city are filtered locally.
"""
from __future__ import annotations

import json

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import feed_date, pay_range
from ....model import Offer

MODES = {"W całości": "remote", "Możliwa w całości": "remote", "Dowolnie": "remote", "Stacjonarnie lub zdalnie": "remote",
         "Hybrydowo": "hybrid", "Możliwa częściowo": "hybrid", "Brak": "onsite"}
CONTRACTS = {"B2B": "b2b", "UoP": "employment", "Umowa o pracę": "employment", "UZ": "mandate", "Umowa zlecenie": "mandate",
             "UoD": "specific_task", "Umowa o dzieło": "specific_task", "Umowa o staż": "internship"}
_PAY_KIND = {"b2b": "b2b", "employment": "permanent", "mandate": "mandate", "specific_task": "specific_task",
             "internship": "internship"}


def worktime(workload: str | None) -> str:
    """'100%' full time, '50%' / '75%' / '25%' part time, 'praca projektowa' (project work) flexible."""
    w = (workload or "100%").strip().lower()
    return "full_time" if w == "100%" else "part_time" if w.endswith("%") else "flexible" if "projekt" in w else "unknown"


@register
class SolidJobs(Board):
    name = "solidjobs"
    caps = Caps(keywords=False, remote="no", page_size=0, max_pages=1, whole_listing=True, local_all=True, transport="http")
    accept = "application/vnd.solidjobs.jobofferlist+json"
    divisions = ("it", "sales", "engineering", "marketing", "logistics", "finances", "hr", "other")

    def requests(self, s):
        reqs, warns = super().requests(s)
        return [Request(self.name, s.id, None, {"division": d}, r.pushed) for d in self.divisions for r in reqs[:1]], warns

    def page_url(self, r: Request, page: int) -> str | None:
        return f"https://solid.jobs/api/offers?division={r.params['division']}&sortOrder=default" if page == 1 else None

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out = []
        for o in json.loads(raw):
            url = f"https://solid.jobs/offer/{o['id']}/{o.get('jobOfferUrl', '')}"
            ranges = [sr for sr in (o.get("salaryRange"), o.get("secondarySalaryRange")) if sr]
            contracts = list(dict.fromkeys(CONTRACTS.get(sr.get("employmentType", ""), "other") for sr in ranges))
            pay = "; ".join(
                pay_range(_PAY_KIND.get(CONTRACTS.get(sr.get("employmentType", ""), ""), "other"), sr["lowerBound"],
                          sr.get("upperBound") or sr["lowerBound"], sr.get("currency") or "PLN",
                          (sr.get("salaryPeriod") or "month").lower(), CONTRACTS.get(sr.get("employmentType", "")) == "employment")
                for sr in ranges if sr.get("lowerBound"))
            out.append(Offer(board=self.name, key=url, url=url, title=o.get("jobTitle") or "", company=o.get("companyName") or "",
                             mode=MODES.get(o.get("remotePossible") or "", "unknown"),
                             locations=[o["companyCity"]] if o.get("companyCity") else [],
                             worktime=worktime(o.get("workload")), contracts=contracts,
                             level=infer.level(o.get("experienceLevel")),
                             category=f"{o.get('mainCategory', '')}/{o.get('subCategory', '')}",
                             skills=[x.get("name", "") for x in o.get("requiredSkills") or []], pay_text=pay,
                             published=feed_date(o.get("validFrom"))))
        return out
