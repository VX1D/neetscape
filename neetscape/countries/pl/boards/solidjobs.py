"""solid.jobs — the site's JSON API, one document per division (the whole division in one download).

    GET https://solid.jobs/api/offers?division=it&sortOrder=default   Accept: application/vnd.solidjobs.jobofferlist+json

Verified live 2026-11-12: eight divisions (the site's /offers/<division>): it 1460 offers, sales 820, engineering
311, marketing 292, logistics 249, finances 237, other 207, hr 123; each offer in one only; an unknown division is a
400. Every offer has a PLN-per-month range (hourly rates converted, "przeliczone z 170 – 210 PLN/h"), some a second
for another contract (`secondarySalaryRange`). `validFrom` is the page's "Dodane N dni temu".
"""
from __future__ import annotations

import json

from ....boards.base import Board, Caps, Request, register
from ....boards.pages import date_of, lowest_level, pay_range, present
from ....model import Offer, Search

API = "https://solid.jobs/api/offers"
MODES = {"W całości": "remote", "Możliwa w całości": "remote", "Dowolnie": "remote", "Stacjonarnie lub zdalnie": "remote",
         "Hybrydowo": "hybrid", "Możliwa częściowo": "hybrid", "Brak": "onsite"}
CONTRACTS = {"B2B": "b2b", "UoP": "employment", "Umowa o pracę": "employment", "UZ": "mandate", "Umowa zlecenie": "mandate",
             "UoD": "specific_task", "Umowa o dzieło": "specific_task", "Umowa o staż": "internship"}
PAY_KIND = {"b2b": "b2b", "employment": "permanent", "mandate": "mandate", "specific_task": "specific_task",
            "internship": "internship"}


def worktime(workload: str | None) -> str:
    """'100%' full time, '50%' / '75%' / '25%' part time, 'praca projektowa' (project work) flexible."""
    w = (workload or "100%").strip().lower()
    return "full_time" if w == "100%" else "part_time" if w.endswith("%") else "flexible" if "projekt" in w else "unknown"


def pay_text(ranges: list[dict]) -> str:
    """One range per contract type; employment contracts are gross."""
    out = []
    for sr in ranges:
        if not sr.get("lowerBound"):
            continue
        contract = CONTRACTS.get(sr.get("employmentType", ""))
        out.append(pay_range(PAY_KIND.get(contract or "", "other"), sr["lowerBound"], sr.get("upperBound") or sr["lowerBound"],
                             sr.get("currency") or "PLN", (sr.get("salaryPeriod") or "month").lower(), contract == "employment"))
    return "; ".join(out)


LEVELS = {"staż": "intern"}  # solid.jobs' own level words beside the shared ones (infer.level)


@register
class SolidJobs(Board):
    name = "solidjobs"
    caps = Caps(whole_listing=True, local_all=True, transport="http")
    accept = "application/vnd.solidjobs.jobofferlist+json"
    divisions = ("it", "sales", "engineering", "marketing", "logistics", "finances", "hr", "other")

    def requests(self, s: Search) -> tuple[list[Request], list[str]]:
        """One download per division, whatever the search (everything is filtered locally)."""
        reqs, warnings = super().requests(s)
        return [Request(self.name, s.id, None, {"division": d}, r.pushed) for d in self.divisions for r in reqs[:1]], warnings

    def page_url(self, r: Request, page: int) -> str | None:
        return f"{API}?division={r.params['division']}&sortOrder=default" if page == 1 else None

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out = []
        for o in json.loads(raw):
            url = f"https://solid.jobs/offer/{o['id']}/{o.get('jobOfferUrl', '')}"
            ranges = [sr for sr in (o.get("salaryRange"), o.get("secondarySalaryRange")) if sr]
            out.append(Offer(
                board=self.name, key=url, url=url, title=o.get("jobTitle") or "", company=o.get("companyName") or "",
                mode=MODES.get(o.get("remotePossible") or "", "unknown"), locations=present(o.get("companyCity")),
                worktime=worktime(o.get("workload")),
                contracts=list(dict.fromkeys(CONTRACTS.get(sr.get("employmentType", ""), "other") for sr in ranges)),
                level=lowest_level([o.get("experienceLevel")], LEVELS), category=f"{o.get('mainCategory', '')}/{o.get('subCategory', '')}",
                skills=[x.get("name", "") for x in o.get("requiredSkills") or []], pay_text=pay_text(ranges),
                published=date_of(o.get("validFrom"))))
        return out
