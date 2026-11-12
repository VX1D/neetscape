"""pl.indeed.com — job cards from the JSON embedded in the result page (transport browser_fetch), 15 per page.

URLs: remote `/jobs?q=K&sc=0kf%3Aattr%28DSQF7%29%3B&sort=date`, city `/jobs?q=K&l=<City>&radius=KM&sort=date`,
anywhere `/jobs?q=K&sort=date` (radius 0/25/50 around Kraków: 48/55/60 results; DSQF7 on "python": 3418 -> 786).
The page embeds its cards as `window.mosaic.providerData["mosaic-provider-jobcards"]`; `fetch_js` cuts them
down in the tab to the fields parsed here. Verified live 2026-11-12:
- only the first page is public: `start=10` answers with a sign-in wall ("Aby zobaczyć więcej niż jedną
  stronę ... zaloguj się", the same-origin fetch fails), so one request is one page of 15;
- an empty query returns the home page, but with a location it lists everything: remote uses `l=Polska`;
- DSQF7 keeps only cards tagged remote; `remoteWorkModel.type` is REMOTE_ALWAYS ("Zdalnie") or REMOTE_HYBRID
  ("Hybrydowo"), absent when the employer set none (left unknown). An employer may tick both (taxonomy
  ["Hybrydowo", "Zdalnie"]); Indeed then shows and filters it as "Zdalnie", but 6 of 7 such postings read
  were hybrid (office days), the 7th had no place ("zdalnie"). So both tags with a place are read as hybrid;
- `createDate` (epoch ms) is the date the card shows ("6 dni temu"); `pubDate` can be years older (reposts);
- `salarySnippet.text` ("90 000-115 000 PLN za rok"), contract and work-time labels in `taxonomyAttributes`.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import clean_spaces, epoch_or_iso_date
from ....model import Offer
from ....posting import html_to_text
from .vocab import LANGS

q = urllib.parse.quote
_BODY = '"sanitizedJobDescription":"'
MODES = {"REMOTE_ALWAYS": "remote", "REMOTE_HYBRID": "hybrid"}

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
    if i < 0:
        return ""
    try:
        body, _ = json.JSONDecoder().raw_decode(page, i + len(_BODY) - 1)
    except ValueError:
        return ""
    return html_to_text(body) if isinstance(body, str) else ""


@register
class Indeed(Board):
    name = "indeed"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, sort_newest=True, page_size=15, max_pages=1,
                transport="browser_fetch", origin="https://pl.indeed.com/")
    posting_selector = ".simple-job-description-html"  # the rendered body (no #jobDescriptionText any more), a fallback

    def page_url(self, r: Request, page: int) -> str | None:
        # page 2+ is behind a sign-in wall and never fetched (max_pages 1), but the listing goes on: never None,
        # so a request stopped at the page limit stays partial and offers beyond page 1 are not marked gone
        if r.params.get("city"):
            where = f"&l={q(r.params['city'])}&radius={r.params.get('radius_km', 0)}"
        else:  # an empty query without a location is the home page
            where = "" if r.keyword else "&l=Polska"
        remote = "&sc=0kf%3Aattr%28DSQF7%29%3B" if r.params.get("remote") else ""
        sort = "&sort=date" if r.params.get("sort") == "newest" else ""
        start = f"&start={10 * (page - 1)}" if page > 1 else ""  # Indeed's own step, though it shows 15
        return f"https://pl.indeed.com/jobs?q={q(r.keyword or '')}{where}{remote}{sort}{start}"

    def fetch_js(self) -> str:
        return FETCH_JS

    def posting(self, page: str) -> dict:
        """The offer page has no JSON-LD; its `window._initialData` (a JS object, not JSON) carries the body as the
        JSON string `"sanitizedJobDescription":"<html>"`."""
        meta = super().posting(page)
        text = posting_text(page)
        if text:
            meta["description"], meta["source"] = text, "board"
        return meta

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out: dict[str, Offer] = {}
        for j in json.loads(raw or "[]"):
            if not j.get("jk") or not j.get("title"):
                continue
            key = f"https://pl.indeed.com/viewjob?jk={j['jk']}"
            tags = j.get("tags") or {}
            contracts, worktime = contracts_and_worktime(tags)
            title = clean_spaces(html.unescape(j["title"]))[:140]
            out[key] = Offer(
                board=self.name, key=key, url=key, title=title,
                company=clean_spaces(j.get("company"))[:80], mode=work_mode(j),
                locations=place(j.get("location") or "", j.get("remote_location")), worktime=worktime, contracts=contracts,
                level=infer.level_from_text(title, LANGS), pay_text=clean_spaces(j.get("salary")),
                published=epoch_or_iso_date(j.get("created")), promoted=bool(j.get("sponsored")),
                snippet=html_to_text(j.get("snippet") or "")[:600])
        return list(out.values())
