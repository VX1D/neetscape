"""bulldogjob.pl — the GraphQL API the site itself uses (plain HTTP POST, JSON).

    POST https://bulldogjob.pl/graphql      the site's `searchJobs` query, 50 per page (`perPage`)

Verified live 2026-11-12:
- filters: `city: ["Remote"]` (336 offers) or a city (`Kraków`, also `Krakow`: 531, remote offers listed there
  included), `employmentType: ["part_time", "freelance"]` (remote: 6); no keyword filter (`skills` takes technology
  tags only), `locationDistance` changes nothing;
- `order: {field: PUBLISHED, direction: DESC}` (the site's `/order,published,desc`) is strictly newest first; the
  API returns `publishedAt` (the listing pages' own JSON has no dates);
- the last page is short (remote: page 7 has 36). No result cap: the whole board is `totalCount` 870 (18 pages);
  Warszawa (609) ends on page 13 (9), page 14 is empty. `max_pages` (40, twice the board) is a safety stop;
- `workModes` (`full-remote`, `hybrid`, `on-site`, several), `roles` (category), `locations[].location.cityPl`;
  `denominatedSalaryLong.money` is a range without a unit ("20 000 - 24 000", currency apart);
- the URL's query string is ignored by the API: it only makes request records differ per page and search.
- category vs industry: `roles` (`backend`, `project_manager`, `support`) are the role; no industry.
"""
from __future__ import annotations

import json
import re

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import LEVEL_WORDS, clean_spaces, date_of, lowest_level, most_remote_mode, places, with_query
from ....model import Offer

API = "https://bulldogjob.pl/graphql"
QUERY = """query searchJobs($page: Int, $perPage: Int, $filters: JobFilters, $order: JobsSearchOrderBy, $language: LocaleEnum,
$country: String) { searchJobs(page: $page, perPage: $perPage, filters: $filters, order: $order, language: $language,
country: $country) { totalCount nodes { id position publishedAt city remote workModes employmentType experienceLevel roles
technologyTags contractB2b contractEmployment contractOther redirectTo company { name } denominatedSalaryLong { money currency
hidden } environment { remotePossible } locations { location { cityPl } } } } }"""
WORKTIME = {"full_time": "full_time", "part_time": "part_time", "freelance": "flexible"}  # "contractor": unknown


def filters(r: Request) -> dict:
    f = {"city": [r.params["city"] if r.params.get("city") else "Remote"]}
    if r.params.get("part_time"):
        f["employmentType"] = ["part_time", "freelance"]
    return f


def pay_text(salary: dict) -> str:
    """'20 000 - 24 000 PLN'; '' when hidden or absent."""
    if not salary.get("money") or salary.get("hidden"):
        return ""
    return clean_spaces(f"{salary['money']} {salary.get('currency') or ''}")


def work_mode(j: dict) -> str:
    mode = most_remote_mode(j.get("workModes"), "remote", "hybrid", "site")
    if mode == "unknown" and (j.get("remote") or (j.get("environment") or {}).get("remotePossible") == 100):
        return "remote"
    return mode


@register
class BulldogJob(Board):
    name = "bulldogjob"
    caps = Caps(remote="filter", city=True, worktime=True, sort_newest=True, page_size=50, max_pages=40, transport="http")
    accept = "application/json"
    content_type = "application/json"

    def page_url(self, r: Request, page: int) -> str | None:
        f = filters(r)
        return with_query(API, {"city": f["city"][0]} | ({"part_time": 1} if "employmentType" in f else {}) | {"page": page})

    def post_body(self, r: Request, page: int) -> str | None:
        variables = {"page": page, "perPage": self.caps.page_size, "filters": filters(r), "language": "pl", "country": "PL"}
        if r.params.get("sort") == "newest":
            variables["order"] = {"field": "PUBLISHED", "direction": "DESC"}
        return json.dumps({"query": QUERY, "variables": variables}, separators=(",", ":"))

    def parse(self, raw: str, r: Request) -> list[Offer]:
        data = json.loads(raw) if raw else {}
        jobs = ((data.get("data") or {}).get("searchJobs") or {}).get("nodes")
        if jobs is None:
            raise ValueError(f"no searchJobs in the response: {json.dumps(data.get('errors'))[:300]}")
        out = []
        for j in jobs:
            if not re.match(r"\d+-", j.get("id") or ""):
                continue
            url = f"https://bulldogjob.pl/companies/jobs/{j['id']}"
            contracts = [infer.contract(c) for c, on in (("b2b", j.get("contractB2b")), ("permanent", j.get("contractEmployment")),
                                                         ("any", j.get("contractOther"))) if on]
            out.append(Offer(
                board=self.name, key=url, url=url, title=clean_spaces(j.get("position")),
                company=clean_spaces((j.get("company") or {}).get("name")), mode=work_mode(j),
                locations=places((x.get("location") or {}).get("cityPl") for x in j.get("locations") or [])
                or [c.strip() for c in (j.get("city") or "").split(",") if c.strip()],
                worktime=WORKTIME.get(j.get("employmentType") or "", "unknown"), contracts=contracts,
                level=lowest_level([j.get("experienceLevel")], LEVEL_WORDS), skills=list(j.get("technologyTags") or []),
                category=", ".join(j.get("roles") or []), published=date_of(j.get("publishedAt")),
                pay_text=pay_text(j.get("denominatedSalaryLong") or {}), snippet=" ".join(j.get("technologyTags") or [])))
        return out
