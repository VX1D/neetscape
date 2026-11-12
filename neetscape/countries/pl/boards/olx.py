"""olx.pl (jobs) — the listing state embedded in the result page (`window.__PRERENDERED_STATE__`), read with a
same-origin fetch (transport browser_fetch) and cut down in the tab by `fetch_js` to the fields parsed here.

URL: `/praca/[<city-slug>/][q-<kw>/]?search[dist]=KM&search[order]=created_at:desc&search[filter_enum_...]...&page=N`.
Verified live 2026-11-12 (Python's HTTP client gets 403 from CloudFront, a browser tab is served):
- `search[filter_enum_workplace][0]=remote_work_possibility` ("Miejsce pracy: Praca zdalna") is a real
  server-side filter ("asystent": 1000+ results -> 106). The workplace values are checkboxes: of 44 remote
  results 20 had only remote, 24 also hybrid and/or on_site, and those postings mostly describe partial remote
  work ("częściowo zdalnej", "80/20", field work), rarely full remote; so remote alone is remote, remote with
  hybrid or on_site is hybrid (see `work_mode`);
- `search[filter_enum_type][0]=parttime&search[filter_enum_type][1]=halftime` keeps part-time and "Praca
  dodatkowa" offers; `search[dist]=30` adds towns around the city;
- each page holds ~40 organic ads plus promoted ones (`isPromoted`, the same ones repeat on every page);
  a page past the last redirects to page 1 (so the request ends with "no new offers");
- `created_at:desc` orders by the last refresh (`lastRefreshTime`, the "Odświeżono dnia ..." date the card
  shows), which is used as `published`; `createdTime` may be a year older for refreshed ads;
- each ad ships its structured fields: salary {from, to, period monthly/hourly}, `params` type (work time),
  agreement (contracts), workplace, location {cityName, districtName}, and the full description;
- the employer's name is `user.company_name` when the account set one; the card's company line for other
  business accounts comes from a later client-side request, and `user.name` is often a recruiter's first name,
  so it is used only when it carries a legal form ("Sp. z o.o.", "S.A.").
"""
from __future__ import annotations

import json
import re
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import clean_spaces, epoch_or_iso_date, pay_range, slug
from ....model import Offer
from ....posting import html_to_text
from .vocab import LANGS

WORKTIME = {"fulltime": "full_time", "parttime": "part_time", "halftime": "part_time"}
AGREEMENT = {"part": "employment", "contract": "specific_task", "zlecenie": "mandate", "selfemployment": "b2b",
             "practice": "internship", "other": "other"}
LEGAL_FORM = re.compile(r"\b(?:sp\.? ?z\.? ?o\.? ?o|spółka|s\.a\.|sp\.? ?[kj]\.|ltd|gmbh|inc|llc)", re.I)
PERIOD = {"monthly": "month", "hourly": "hour", "weekly": "week", "daily": "day", "yearly": "year"}


# the ads of the page, shrunk in the tab ('[]' for a page without the state)
# (the state is one 3-4 MB JSON string literal ending its line: it is cut out by index, not by a regex)
FETCH_JS = r"""(t)=>{const i=t.indexOf('window.__PRERENDERED_STATE__');if(i<0)return '[]';
const lo=t.indexOf('"',i),hi=t.lastIndexOf('"',t.indexOf('\n',lo));
let s;try{s=JSON.parse(JSON.parse(t.slice(lo,hi+1)))}catch(e){return '[]'}
const ads=((s.listing||{}).listing||{}).ads||[];
return JSON.stringify(ads.map(a=>({url:a.url,title:a.title,isPromoted:!!a.isPromoted,lastRefreshTime:a.lastRefreshTime,
 createdTime:a.createdTime,salary:a.salary?{from:a.salary.from,to:a.salary.to,currencyCode:a.salary.currencyCode,
 period:a.salary.period}:null,params:(a.params||[]).map(p=>({key:p.key,normalizedValue:p.normalizedValue})),
 location:{cityName:(a.location||{}).cityName,districtName:(a.location||{}).districtName},
 user:{company_name:(a.user||{}).company_name||'',name:(a.user||{}).name||''},description:(a.description||'').slice(0,12000)})))}"""


def work_mode(workplace: list) -> str:
    """OLX "Miejsce pracy" checkboxes -> mode: remote only when remote is the only place (field work aside)."""
    places = set(workplace) - {"traveling"}
    if "hybrid" in places or ("remote_work_possibility" in places and "on_site" in places):
        return "hybrid"
    if "remote_work_possibility" in places:
        return "remote"
    return "onsite" if workplace else "unknown"


def company(user: dict) -> str:
    name = clean_spaces(user.get("company_name"))
    if not name and LEGAL_FORM.search(user.get("name") or ""):
        name = clean_spaces(user.get("name"))
    return name[:80]


def pay_text(salary: dict | None) -> str:
    lo, hi = (salary or {}).get("from") or None, (salary or {}).get("to") or None  # "from": 0 means "up to"
    if not lo and not hi:
        return ""
    return pay_range("salary", lo, hi, salary.get("currencyCode") or "PLN", PERIOD.get(salary.get("period"), "month"))


@register
class Olx(Board):
    name = "olx"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=True, page_size=0,
                max_pages=4, huge_unfiltered=True, transport="browser_fetch", origin="https://www.olx.pl/praca/")

    def page_url(self, r: Request, page: int) -> str | None:
        # never None: the listing goes on past `max_pages`, so a request stopped there is partial (no "gone" marks)
        kw = (r.keyword or "").strip()
        path = "praca/" + (slug(r.params["city"]) + "/" if r.params.get("city") else "")
        query = {}
        if r.params.get("city"):
            query["search[dist]"] = r.params.get("radius_km", 0)
        if r.params.get("sort") == "newest":
            query["search[order]"] = "created_at:desc"
        if r.params.get("remote"):
            query["search[filter_enum_workplace][0]"] = "remote_work_possibility"
        if r.params.get("part_time"):
            query["search[filter_enum_type][0]"] = "parttime"
            query["search[filter_enum_type][1]"] = "halftime"
        if page > 1:
            query["page"] = page
        return (f"https://www.olx.pl/{path}" + (f"q-{urllib.parse.quote(kw)}/" if kw else "")
                + (f"?{urllib.parse.urlencode(query)}" if query else ""))

    def fetch_js(self) -> str:
        return FETCH_JS

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out: dict[str, Offer] = {}
        for ad in json.loads(raw or "[]"):
            url = re.sub(r"[?#].*$", "", ad.get("url") or "")
            if not url or not ad.get("title"):
                continue
            params = {p.get("key"): p.get("normalizedValue") for p in ad.get("params") or []}
            as_list = lambda v: v if isinstance(v, list) else [v] if v else []
            contracts = sorted({AGREEMENT[a] for a in as_list(params.get("agreement")) if a in AGREEMENT}
                               | ({"b2b"} if params.get("type") == "b2b" else set()))
            workplace = as_list(params.get("workplace"))
            loc = ad.get("location") or {}
            city = ", ".join(x for x in (loc.get("cityName"), loc.get("districtName")) if x)
            title = clean_spaces(ad["title"])[:140]
            description = html_to_text(ad.get("description") or "")
            out[url] = Offer(
                board=self.name, key=url, url=url, title=title, company=company(ad.get("user") or {}),
                mode=work_mode(workplace),
                locations=[city] if city else [], worktime=WORKTIME.get(params.get("type"), "unknown"), contracts=contracts,
                level=infer.level_from_text(title, LANGS), pay_text=pay_text(ad.get("salary")),
                published=epoch_or_iso_date(ad.get("lastRefreshTime") or ad.get("createdTime")), promoted=bool(ad.get("isPromoted")),
                snippet=clean_spaces(f"{title} {description}")[:1000], description=description)
        return list(out.values())
