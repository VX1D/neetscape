"""bulldogjob.pl — the GraphQL API the site itself uses (plain HTTP POST, JSON).

POST `https://bulldogjob.pl/graphql` with the site's `searchJobs` query (verified live 2026-11-12):
- filters: `city: ["Remote"]` (336 offers) or a city (`Kraków`, also `Krakow`: 531, remote offers listed there
  included), `employmentType: ["part_time", "freelance"]` (remote: 6). There is no keyword filter (`skills`
  takes technology tags only) and `locationDistance` changes nothing: no keywords, no radius;
- `order: {field: PUBLISHED, direction: DESC}` gives a strictly newest-first listing (the site's
  `/order,published,desc`); the listing pages' own JSON has no dates, the API returns `publishedAt`;
- 50 per page (`perPage`), the last page is short (remote: page 7 has 36);
- no result cap (verified live 2026-11-12): the whole board (no city filter) is `totalCount` 870 (18 pages), the
  largest city, Warszawa (609), ends on page 13 (9 offers), page 14 is empty. `max_pages` (40, twice the whole
  board) is only a safety stop;
- `workModes` (`full-remote`, `hybrid`, `on-site`, several per offer), `roles` (the category),
  `locations[].location.cityPl` (Polish city names; `city` is the employer's free text);
- `denominatedSalaryLong.money` is a range without a unit ("20 000 - 24 000", currency apart);
- the URL's query string is ignored by the API: it only makes request records differ per page and search.
"""
from __future__ import annotations

import json
import re
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, register
from ....boards.pages import LEVEL_WORDS, clean_spaces, epoch_or_iso_date, lowest_level, most_remote_mode
from ....model import Offer

API = "https://bulldogjob.pl/graphql"
QUERY = """query searchJobs($page: Int, $perPage: Int, $filters: JobFilters, $order: JobsSearchOrderBy, $language: LocaleEnum,
$country: String) { searchJobs(page: $page, perPage: $perPage, filters: $filters, order: $order, language: $language,
country: $country) { totalCount nodes { id position publishedAt city remote workModes employmentType experienceLevel roles
technologyTags contractB2b contractEmployment contractOther redirectTo company { name } denominatedSalaryLong { money currency
hidden } environment { remotePossible } locations { location { cityPl } } } } }"""
WORKTIME = {"full_time": "full_time", "part_time": "part_time", "freelance": "flexible"}  # "contractor": unknown


def filters(r) -> dict:
    f = {"city": [r.params["city"] if r.params.get("city") else "Remote"]}
    if r.params.get("part_time"):
        f["employmentType"] = ["part_time", "freelance"]
    return f


@register
class BulldogJob(Board):
    name = "bulldogjob"
    caps = Caps(keywords=False, remote="filter", city=True, worktime=True, sort_newest=True, page_size=50, max_pages=40,
                transport="http")
    accept = "application/json"
    content_type = "application/json"

    def page_url(self, r, page):
        f = filters(r)
        query = {"city": f["city"][0]} | ({"part_time": 1} if "employmentType" in f else {}) | {"page": page}
        return f"{API}?{urllib.parse.urlencode(query)}"

    def post_body(self, r, page):
        variables = {"page": page, "perPage": self.caps.page_size, "filters": filters(r), "language": "pl", "country": "PL"}
        if r.params.get("sort") == "newest":
            variables["order"] = {"field": "PUBLISHED", "direction": "DESC"}
        return json.dumps({"query": QUERY, "variables": variables}, separators=(",", ":"))

    def parse(self, raw, r):
        data = json.loads(raw) if raw else {}
        jobs = ((data.get("data") or {}).get("searchJobs") or {}).get("nodes")
        if jobs is None:
            raise ValueError(f"no searchJobs in the response: {json.dumps(data.get('errors'))[:300]}")
        out = []
        for j in jobs:
            if not re.match(r"\d+-", j.get("id") or ""):
                continue
            url = f"https://bulldogjob.pl/companies/jobs/{j['id']}"
            sal = j.get("denominatedSalaryLong") or {}
            contracts = [infer.contract(c) for c, on in (("b2b", j.get("contractB2b")), ("permanent", j.get("contractEmployment")),
                                                         ("any", j.get("contractOther"))) if on]
            cities = [(x.get("location") or {}).get("cityPl") for x in j.get("locations") or []]
            mode = most_remote_mode(j.get("workModes"), "remote", "hybrid", "site")
            if mode == "unknown" and (j.get("remote") or (j.get("environment") or {}).get("remotePossible") == 100):
                mode = "remote"
            out.append(Offer(
                board=self.name, key=url, url=url, title=clean_spaces(j.get("position")),
                company=clean_spaces((j.get("company") or {}).get("name")), mode=mode,
                locations=sorted({c for c in cities if c}) or [c.strip() for c in (j.get("city") or "").split(",") if c.strip()],
                worktime=WORKTIME.get(j.get("employmentType") or "", "unknown"), contracts=contracts,
                level=lowest_level([j.get("experienceLevel")], LEVEL_WORDS), skills=list(j.get("technologyTags") or []),
                category=", ".join(j.get("roles") or []), published=epoch_or_iso_date(j.get("publishedAt")),
                pay_text=clean_spaces(f"{sal['money']} {sal.get('currency') or ''}") if sal.get("money") and not sal.get("hidden") else "",
                snippet=" ".join(j.get("technologyTags") or [])))
        return out
