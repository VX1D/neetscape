"""pl.indeed.com — the job cards embedded in the result page (`window.mosaic.providerData["mosaic-provider-
jobcards"]`), same-origin fetch, 15 cards per page.

    GET https://pl.indeed.com/jobs?q=K[&l=<City>&radius=KM][&sc=0kf%3Aattr%28DSQF7%29%3B]&sort=date

Verified live 2026-11-12:
- remote `sc=...DSQF7` ("python": 3418 -> 786); radius 0/25/50 around Kraków: 48/55/60 results;
- only the first page is public: `start=10` answers with a sign-in wall ("Aby zobaczyć więcej niż jedną stronę ...
  zaloguj się", the fetch fails), so one request is one page of 15;
- an empty query returns the home page, but with a location it lists everything: remote uses `l=Polska`;
- DSQF7 keeps only cards tagged remote; `remoteWorkModel.type` is REMOTE_ALWAYS ("Zdalnie") or REMOTE_HYBRID
  ("Hybrydowo"), absent when the employer set none (unknown). An employer may tick both; Indeed then shows and
  filters it as "Zdalnie", but 6 of 7 such postings read were hybrid (office days), the 7th had no place
  ("zdalnie"): both tags with a place read as hybrid;
- `createDate` (epoch ms) is the date the card shows ("6 dni temu"); `pubDate` can be years older (reposts);
  `salarySnippet.text` ("90 000-115 000 PLN za rok"); contract and work-time labels in `taxonomyAttributes`;
- the offer page (/viewjob) has no JSON-LD; its `window._initialData` (JS, not JSON) holds the body as the JSON
  string `"sanitizedJobDescription":"<html>"`;
- no category per card (2026-11-12, remote page 1, all 15 cards): `taxonomyAttributes` holds only job-types,
  job-types-cc, shifts, schedules, remote and benefits; `taxoAttributes`, `jobTypes` and `translatedAttributes`
  are empty, and `normTitle` is a normalised title, not a category.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import quote

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import clean_spaces, date_of, json_at, with_query
from ....model import Offer
from ....posting import html_to_text
from .vocab import LANGS

BASE = "https://pl.indeed.com"
REMOTE = "0kf:attr(DSQF7);"
MODES = {"REMOTE_ALWAYS": "remote", "REMOTE_HYBRID": "hybrid"}
_BODY = '"sanitizedJobDescription":"'

# the cards of the page, shrunk in the tab to what `parse` reads ('[]' for a page without cards)
FETCH_JS = r"""(t)=>{const m=t.match(/window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{[\s\S]*?\});\s*window\.mosaic/);
if(!m)return '[]';let d;try{d=JSON.parse(m[1])}catch(e){return '[]'}
const r=((d.metaData||{}).mosaicProviderJobCardsModel||{}).results||[];
return JSON.stringify(r.map(j=>({jk:j.jobkey,title:j.displayTitle||j.title,company:j.company||j.truncatedCompany||'',
 location:j.formattedLocation||'',remote_location:!!j.remoteLocation,mode:(j.remoteWorkModel||{}).type||'',
 created:j.createDate||0,salary:(j.salarySnippet||{}).text||'',sponsored:!!j.sponsored,snippet:(j.snippet||'').slice(0,600),
 tags:Object.fromEntries((j.taxonomyAttributes||[]).filter(a=>a.attributes&&a.attributes.length)
   .map(a=>[a.label,a.attributes.map(x=>x.label)]))})))}"""


def place(location: str, remote_location: bool) -> list[str]:
    """'31-864 Kraków' -> ['Kraków']; 'Kraków, małopolskie' stays; 'zdalnie' (no place) -> []."""
    if remote_location or not location or location.lower() in ("zdalnie", "polska"):
        return []
    return [re.sub(r"^\d\d-\d{3}\s+", "", location).strip()]


def work_mode(card: dict) -> str:
    """Both remote tags on a card with a place read as hybrid (see the module docstring)."""
    tags = set((card.get("tags") or {}).get("remote", []))
    if "Hybrydowo" in tags and not card.get("remote_location"):
        return "hybrid"
    return MODES.get(card.get("mode") or "", "unknown")


def contracts_and_worktime(tags: dict) -> tuple[list[str], str]:
    labels = [*tags.get("job-types-cc", []), *tags.get("job-types", [])]
    contracts = set(infer.contracts_from_text("; ".join(labels), LANGS))
    worktimes = {infer.worktime_from_text(x, LANGS) for x in labels} - {"unknown"}
    worktime = worktimes.pop() if len(worktimes) == 1 else "unknown"  # "Pełny etat" and "Część etatu": either
    return sorted(contracts), worktime


def posting_text(page: str) -> str:
    """The posting body of a /viewjob page, from its embedded `sanitizedJobDescription` ('' when absent)."""
    i = (page or "").find(_BODY)
    body = json_at(page, i + len(_BODY) - 1) if i >= 0 else None  # from the opening quote
    return html_to_text(body) if isinstance(body, str) else ""


@register
class Indeed(Board):
    name = "indeed"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, sort_newest=True, page_size=15, max_pages=1,
                transport="browser_fetch", origin=BASE + "/")
    posting_selector = ".simple-job-description-html"  # the rendered body (no #jobDescriptionText any more), a fallback

    def page_url(self, r: Request, page: int) -> str | None:
        # page 2+ is behind a sign-in wall and never fetched (max_pages 1), but the listing goes on: never None,
        # so a request stopped at the page limit stays partial and offers beyond page 1 are not marked gone
        q = {"q": r.keyword or ""}
        if r.params.get("city"):
            q |= {"l": r.params["city"], "radius": r.params.get("radius_km", 0)}
        elif not r.keyword:  # an empty query without a location is the home page
            q["l"] = "Polska"
        if r.params.get("remote"):
            q["sc"] = REMOTE
        if r.params.get("sort") == "newest":
            q["sort"] = "date"
        if page > 1:
            q["start"] = 10 * (page - 1)  # Indeed's own step, though it shows 15
        return with_query(f"{BASE}/jobs", q, safe="/", quote_via=quote)

    def fetch_js(self) -> str | None:
        return FETCH_JS

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out: dict[str, Offer] = {}
        for j in json.loads(raw or "[]"):
            if not j.get("jk") or not j.get("title"):
                continue
            url = f"{BASE}/viewjob?jk={j['jk']}"
            contracts, worktime = contracts_and_worktime(j.get("tags") or {})
            title = clean_spaces(html.unescape(j["title"]))[:140]
            out[url] = Offer(
                board=self.name, key=url, url=url, title=title, company=clean_spaces(j.get("company"))[:80],
                mode=work_mode(j), locations=place(j.get("location") or "", j.get("remote_location")),
                worktime=worktime, contracts=contracts,
                pay_text=clean_spaces(j.get("salary")), published=date_of(j.get("created")),
                promoted=bool(j.get("sponsored")), snippet=html_to_text(j.get("snippet") or "")[:600])
        return list(out.values())

    def posting_body(self, page: str) -> str:
        return posting_text(page)
