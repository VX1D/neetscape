"""Arbeitnow job board API: the whole board as JSON, newest first (the template example for API boards).

    GET https://www.arbeitnow.com/api/job-board-api?page=N

Verified live 2026-11-12: up to 300 offers per page (the last page is shorter), about 6 pages (one week);
`remote`, `search` and `location` query parameters are ignored, so nothing is pushed: every search is served
by downloading the board and filtering locally. Offers: slug, company_name, title, description (HTML), remote
(bool), url, tags, job_types (free strings in German, English, French), location, created_at (unix time).
Mostly Germany, also Paris, London, Zürich, Amsterdam. No pay. Free API; the terms ask for moderate use and a
link back.
"""
from __future__ import annotations

import datetime as dt
import json

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....model import Offer
from ....posting import html_to_text

LANGS = ("de", "en")

# job_types seen live -> (worktime, contract, level); anything else is read as free text
JOB_TYPES = {
    "full time": ("full_time", None, None), "fulltime permanent": ("full_time", "employment", None),
    "full-time permanent": ("full_time", "employment", None), "fulltime fixed term": ("full_time", "employment", None),
    "part time": ("part_time", None, None), "teilzeit": ("part_time", None, None), "vollzeit": ("full_time", None, None),
    "unbefristeter arbeitsvertrag": (None, "employment", None), "befristeter arbeitsvertrag": (None, "employment", None),
    "permanent employment": (None, "employment", None),
    "permanent employment (unbefristeter arbeitsvertrag)": (None, "employment", None),
    "praktikum": (None, "internship", "intern"), "internship": (None, "internship", "intern"), "intern": (None, "internship", "intern"),
    "werkstudent": ("part_time", "working_student", None), "student college": ("part_time", "working_student", None),
    "hilfstätigkeit / student": ("part_time", "working_student", None),
    "minijob": ("part_time", "mini_job", None), "freelance": ("flexible", "freelance", None),
    "berufseinstieg": (None, None, "junior"), "entry": (None, None, "junior"), "berufserfahren": (None, None, "mid"),
    "experienced": (None, None, "mid"), "professional / experienced": (None, None, "mid"), "mid": (None, None, "mid"),
    "teamleitung": (None, None, "lead"), "manager": (None, None, "manager"),
}


def _types(job_types: list[str]) -> tuple[str, list[str], str]:
    worktime, contracts, level = "unknown", [], "unknown"
    for t in job_types or []:
        w, c, lv = JOB_TYPES.get(t.strip().lower(), (None, None, None))
        if w is None and c is None and lv is None:
            w = infer.worktime_from_text(t, LANGS)
            w = None if w == "unknown" else w
            c = next(iter(infer.contracts_from_text(t, LANGS)), None)
        if w and worktime == "unknown":
            worktime = w
        if c and c not in contracts:
            contracts.append(c)
        if lv and level == "unknown":
            level = lv
    return worktime, contracts, level


@register
class Arbeitnow(Board):
    name = "arbeitnow"
    caps = Caps(keywords=False, remote="no", page_size=0, max_pages=10, local_all=True, sort_newest=True, transport="http")
    accept = "application/json"

    def page_url(self, r: Request, page: int) -> str | None:
        if page > self.caps.max_pages:
            return None
        return "https://www.arbeitnow.com/api/job-board-api" + (f"?page={page}" if page > 1 else "")

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out = []
        for o in json.loads(raw).get("data") or []:
            url = o.get("url") or f"https://www.arbeitnow.com/view/{o.get('slug')}"
            text = html_to_text(o.get("description") or "")
            worktime, contracts, level = _types(o.get("job_types"))
            if o.get("remote"):
                mode = "remote"
            else:  # the board says not remote: hybrid when the text says so, else on site
                mode = "hybrid" if infer.mode_from_text(text[:4000], LANGS) in ("hybrid", "remote") else "onsite"
            created = o.get("created_at")
            out.append(Offer(
                board=self.name, key=url, url=url, title=o.get("title") or "", company=o.get("company_name") or "",
                mode=mode, locations=[o["location"]] if o.get("location") else [], worktime=worktime, contracts=contracts,
                level=level if level != "unknown" else infer.level_from_text(o.get("title") or "", LANGS),
                category=", ".join(o.get("tags") or []), skills=list(o.get("tags") or []),
                published=dt.datetime.fromtimestamp(created, dt.timezone.utc).date() if created else None,
                snippet=", ".join(o.get("job_types") or []), description=text))
        return out
