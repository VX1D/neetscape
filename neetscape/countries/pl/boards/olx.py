"""olx.pl (jobs) — the listing state embedded in the result page (`window.__PRERENDERED_STATE__`), same-origin fetch
(Python's HTTP client gets 403 from CloudFront), cut down in the tab.

    GET https://www.olx.pl/praca/[<category>/][<city-slug>/][q-<kw>/]?search[dist]=KM&search[order]=created_at:desc
        &search[filter_enum_workplace][0]=remote_work_possibility&search[filter_enum_type][0]=parttime&...&page=N

Verified live 2026-11-12:
- the workplace filter `remote_work_possibility` ("Praca zdalna") is server-side ("asystent": 1000+ -> 106). Its
  values are checkboxes: of 44 remote results 20 had only remote, 24 also hybrid and/or on_site, and those postings
  mostly describe partial remote work ("częściowo zdalnej", "80/20", field work), so remote alone is remote, remote
  with hybrid or on_site is hybrid (`work_mode`);
- types `parttime` + `halftime` keep part-time and "Praca dodatkowa" offers; `search[dist]=30` adds towns around;
- each page holds ~40 organic ads plus promoted ones (`isPromoted`, the same ones on every page);
- result cap: at most 25 pages, 1000 ads (`totalElements` capped at 1000; pages 5, 10 and 25 of the remote listing
  hold distinct ads, page 26 redirects): `split()` narrows a capped request into the subcategories of its category,
  from the category tree in the page (`/praca/<subcategory>/`; remote ads per subcategory stay far below the cap,
  e.g. customer service 180, extra work 290); a page past the last redirects to page 1 ("no new offers");
- `created_at:desc` orders by the last refresh (`lastRefreshTime`, "Odświeżono dnia ..." on the card), which is
  `published`; `createdTime` may be a year older for refreshed ads;
- each ad ships salary {from, to, period}, `params` type (work time), agreement (contracts), workplace, location
  {cityName, districtName} and the full description;
- each ad's `category.id` is its own job category; its name and its parent's come from the page's category tree
  (`categories.list`): `category` is "Parent - Name" ("Obsługa klienta i call center - Specjalista ds. obsługi
  klienta"), or the name alone for a top-level category ("Sprzątanie"); 52 of 52 remote ads had one;
- the employer is `user.company_name` when set; other business accounts' company line comes from a later client-side
  request, and `user.name` is often a recruiter's first name: used only with a legal form ("Sp. z o.o.").
- category vs industry: the job category tree names roles ("Obsługa klienta i call center - Specjalista ds.
  obsługi klienta"), also in the request's `category`; no industry.
"""
from __future__ import annotations

import json
import re
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, Request, narrowed, register
from ....boards.pages import clean_spaces, date_of, pay_range, present, slug, snippet, with_query
from ....model import Offer
from ....posting import html_to_text
from .vocab import LANGS

BASE = "https://www.olx.pl"
WORKTIME = {"fulltime": "full_time", "parttime": "part_time", "halftime": "part_time"}
AGREEMENT = {"part": "employment", "contract": "specific_task", "zlecenie": "mandate", "selfemployment": "b2b",
             "practice": "internship", "other": "other"}
PERIOD = {"monthly": "month", "hourly": "hour", "weekly": "week", "daily": "day", "yearly": "year"}
LEGAL_FORM = re.compile(r"\b(?:sp\.? ?z\.? ?o\.? ?o|spółka|s\.a\.|sp\.? ?[kj]\.|ltd|gmbh|inc|llc)", re.I)

# the page shrunk in the tab: the match count, the category tree and the ads ('{"ads":[]}' without the state;
# the state is one 3-4 MB JSON string literal ending its line: it is cut out by index, not by a regex)
FETCH_JS = r"""(t)=>{const i=t.indexOf('window.__PRERENDERED_STATE__');if(i<0)return '{"ads":[]}';
const lo=t.indexOf('"',i),hi=t.lastIndexOf('"',t.indexOf('\n',lo));
let s;try{s=JSON.parse(JSON.parse(t.slice(lo,hi+1)))}catch(e){return '{"ads":[]}'}
const L=(s.listing||{}).listing||{},ads=L.ads||[],cl=((s.categories||{}).list)||{};
const tree=Object.values(cl).filter(c=>c&&c.path&&(c.path==='praca'||c.path.startsWith('praca/')))
 .map(c=>({path:c.path,parent:(cl[c.parentId]||{}).path||''}));
const cat=a=>{const c=cl[(a.category||{}).id]||{},p=cl[c.parentId]||{};
 return c.name?(p.name&&p.path!=='praca'&&p.level>1?p.name+' - ':'')+c.name:''};
return JSON.stringify({total:L.totalElements??null,categories:tree,ads:ads.map(a=>({url:a.url,title:a.title,category:cat(a),isPromoted:!!a.isPromoted,lastRefreshTime:a.lastRefreshTime,
 createdTime:a.createdTime,salary:a.salary?{from:a.salary.from,to:a.salary.to,currencyCode:a.salary.currencyCode,
 period:a.salary.period}:null,params:(a.params||[]).map(p=>({key:p.key,normalizedValue:p.normalizedValue})),
 location:{cityName:(a.location||{}).cityName,districtName:(a.location||{}).districtName},
 user:{company_name:(a.user||{}).company_name||'',name:(a.user||{}).name||''},description:(a.description||'').slice(0,12000)}))})}"""


def page_data(raw: str) -> dict:
    """The shrunk page {"total": matches, "categories": [{"path", "parent"}], "ads": [...]}; a bare list (an older
    recording) holds the ads alone."""
    data = json.loads(raw or "{}")
    return {"ads": data} if isinstance(data, list) else {"ads": [], **data}


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


def as_list(v) -> list:
    """A param's value: OLX ships one value bare and several as a list."""
    return v if isinstance(v, list) else [v] if v else []


@register
class Olx(Board):
    name = "olx"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=True, max_pages=25,
                result_cap=1000, huge_unfiltered=True, transport="browser_fetch", origin=BASE + "/praca/")

    def page_url(self, r: Request, page: int) -> str | None:
        # never None: the listing goes on past `max_pages`, so a request stopped there is partial (no "gone" marks)
        p, kw = r.params, (r.keyword or "").strip()
        path = "".join(x + "/" for x in ("praca", p.get("category"), slug(p["city"]) if p.get("city") else None) if x)
        query = {}
        if p.get("city"):
            query["search[dist]"] = p.get("radius_km", 0)
        if p.get("sort") == "newest":
            query["search[order]"] = "created_at:desc"
        if p.get("remote"):
            query["search[filter_enum_workplace][0]"] = "remote_work_possibility"
        if p.get("part_time"):
            query["search[filter_enum_type][0]"] = "parttime"
            query["search[filter_enum_type][1]"] = "halftime"
        if page > 1:
            query["page"] = page
        return with_query(f"{BASE}/{path}" + (f"q-{urllib.parse.quote(kw)}/" if kw else ""), query)

    def fetch_js(self) -> str | None:
        return FETCH_JS

    def total(self, raw: str, r: Request) -> int | None:
        return page_data(raw).get("total")

    def split(self, raw: str, r: Request, seen: tuple = ()) -> list[Request]:
        """One request per subcategory of the request's category, read from the page's category tree."""
        here = "praca" + ("/" + r.params["category"] if r.params.get("category") else "")
        subs = [c["path"].removeprefix("praca/") for c in page_data(raw).get("categories") or [] if c.get("parent") == here]
        return narrowed(r, "category", sorted(subs))

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out: dict[str, Offer] = {}
        for ad in page_data(raw)["ads"]:
            url = re.sub(r"[?#].*$", "", ad.get("url") or "")
            if not url or not ad.get("title"):
                continue
            params = {p.get("key"): p.get("normalizedValue") for p in ad.get("params") or []}
            contracts = sorted({AGREEMENT[a] for a in as_list(params.get("agreement")) if a in AGREEMENT}
                               | ({"b2b"} if params.get("type") == "b2b" else set()))
            loc = ad.get("location") or {}
            city = ", ".join(present(loc.get("cityName"), loc.get("districtName")))
            title = clean_spaces(ad["title"])[:140]
            description = html_to_text(ad.get("description") or "")
            out[url] = Offer(
                board=self.name, key=url, url=url, title=title, company=company(ad.get("user") or {}),
                mode=work_mode(as_list(params.get("workplace"))), locations=present(city),
                worktime=WORKTIME.get(params.get("type"), "unknown"), contracts=contracts,
                level=infer.level_from_text(title, LANGS), pay_text=pay_text(ad.get("salary")),
                category=clean_spaces(ad.get("category")),
                published=date_of(ad.get("lastRefreshTime") or ad.get("createdTime")), promoted=bool(ad.get("isPromoted")),
                snippet=snippet(title, description), description=description)
        return list(out.values())
