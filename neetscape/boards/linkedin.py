"""LinkedIn public (logged-out) job search API. 10 offers per page, at most 1000 per query.

Verified live 2026-11-12: logged out, only `keywords`, `location`/`geoId`, `start` and `f_TPR` change the
results. `f_WT` (remote), `f_JT` (job type), `f_E`, `f_F`, `f_I`, `distance` and `sortBy=DD` are ignored
(identical pages, unsorted dates), also on the public /jobs/search page, so none of them is pushed. A free-text
`location=Kraków` resolves to a village in Łódzkie, so cities are sent as a `geoId` from the GEO typeahead.

Remote searches without phrases ("all"): the whole country's listing is 1000 offers of every kind, mostly on
site (fully remote by the posting: 1 of 10 sampled). Such a search is sent as the searched country's
`REMOTE_PHRASES` instead, words that remote postings contain. Verified 2026-11-12 on pages 1 and 3 (20 postings
per phrase, read with `infer.hints`): Poland "remote" 9 of 20 fully remote, "home office" 8, "zdalnie" 3 (and 10
more mention remote work), "praca zdalna" 4 (and 9); their page-1 results overlap by at most 2 of 10. Germany
(page 1): "remote" 1 fully remote and 6 mentioning it of 10, "home office" 4 and 3; "homeoffice" repeats 7 of
"home office"'s 10, so it is not sent. Each phrase still reaches the cap, and the offers' mode stays unknown
until their posting is read (nothing remote is pushed).

Result cap: `start` stops at 990 (`start=1000` answers HTTP 400) and no total is reported, so `result_cap=1000`
is declared without `total()`: the crawler sees the cap only when a request fetches all 100 pages, then asks
`split()`. Verified 2026-11-12: keyword-less Poland, Mazowieckie and Małopolskie still list cards at start=990,
Opolskie and Warsaw end before it. A region's geoId search also lists the offers placed at country level (card
location "Poland"): without a keyword they come after the region's own (Opolskie: 0 of 30 sampled cards), with
"remote" they come first (Opolskie: 10 of 10, and still cards at start=990). So `split()` narrows a capped
country request into the regions named on its cards, and a capped region into its cities seen on at least
`MIN_CITY` cards, but only while country-level cards are under `MAX_NATIONAL` of the request's (keyword-less
Poland: 1 of 20 sampled; "remote": 15 of 49): otherwise every part repeats them and stays capped. City requests
are not narrowed. The parts overlap in the country-level offers and a region's cities miss its small places, so a
split adds offers beyond the cap rather than partitioning the listing.

Empty pages are flaky: a listing's end is a 26-byte body without cards, and the same body comes back now and
then mid-listing (2 of 12 consecutive pages on 2026-11-12; the next try listed 10). `empty_retries` makes the
crawler fetch an empty page again before taking it as the end.

Serves every country (`country="any"`): the searched country arrives in `params["country"]`; without a city the
search goes to the country's `linkedin_location` ("Poland"), a city is resolved among the typeahead hits ending
with one of the country's `place_names`.
"""
from __future__ import annotations

import datetime as dt
import functools
from collections import Counter
from dataclasses import replace
import html
import json
import re
import urllib.parse

from .. import country
from ..log import log
from ..model import Offer, Search, fold
from .base import Board, Caps, Request, register
from .fetch import _http_get
from ..posting import html_to_text
from .pages import clean_spaces, html_field

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
TYPEAHEAD = "https://www.linkedin.com/jobs-guest/api/typeaheadHits?typeaheadType=GEO&query="

# sent instead of a keyword-less remote search, by searched country (verified live, see above)
REMOTE_PHRASES = {"pl": ("remote", "zdalnie", "praca zdalna", "home office")}
DEFAULT_REMOTE_PHRASES = ("remote", "home office")
MAX_NATIONAL = 0.1  # a capped request splits only while fewer of its cards than this are placed at country level
MIN_CITY = 10       # a capped region splits into its cities seen on at least this many cards


def pick_geo(city: str, hits: list[dict], cc: str = "pl") -> str | None:
    """The place in country `cc` named exactly `city` (first such hit), else the first hit in that country."""
    names = "|".join(map(re.escape, country.get(cc).place_names))
    local = [h for h in hits if re.search(rf"\b(?:{names})$", h.get("displayName") or "")] if names else []
    exact = [h for h in local if fold(h["displayName"].split(",")[0]) == fold(city)]
    best = (exact or local or [None])[0]
    return str(best["id"]) if best else None


@functools.lru_cache(maxsize=64)
def geo_id(city: str, cc: str = "pl") -> str | None:
    status, body = _http_get(TYPEAHEAD + urllib.parse.quote(city), "application/json")
    try:
        found = pick_geo(city, json.loads(body), cc) if status == 200 else None
    except (ValueError, KeyError, TypeError):
        found = None
    if not found:
        log("linkedin", f"no geoId for {city!r} in {cc} (HTTP {status}); sending it as free-text location")
    return found


@register
class LinkedIn(Board):
    name = "linkedin"
    caps = Caps(keywords=True, remote="no", city=True, page_size=10, max_pages=100, result_cap=1000,
                empty_retries=2, transport="http", country="any")

    def requests(self, s: Search) -> tuple[list[Request], list[str]]:
        """A keyword-less remote request becomes one request per remote phrase of the searched country: there is
        no remote filter, and the whole country's listing is mostly on-site offers."""
        reqs, warnings = super().requests(s)
        out = []
        for r in reqs:
            if r.keyword is None and s.where.remote and not r.params.get("city"):
                phrases = REMOTE_PHRASES.get(r.params.get("country") or "pl", DEFAULT_REMOTE_PHRASES)
                out += [Request(r.board, r.search_id, p, r.params, r.pushed | {"keyword"}) for p in phrases]
                warnings.append(f"{self.name}: no remote filter; '{s.id}' is sent as the phrases {', '.join(phrases)}")
            else:
                out.append(r)
        return out, warnings

    def page_url(self, r: Request, page: int) -> str | None:
        if page > self.caps.max_pages:
            return None
        cc = r.params.get("country") or "pl"
        place = r.params.get("city") or r.params.get("region")
        geo = geo_id(place, cc) if place else None
        q = {"keywords": r.keyword or ""}
        q.update({"geoId": geo} if geo else {"location": place or country.get(cc).linkedin_location})
        q["start"] = (page - 1) * 10
        return SEARCH + urllib.parse.urlencode(q)

    def split(self, raw: str, r: Request, seen: tuple = ()) -> list[Request]:
        """A capped request without a city: one request per region named on its cards (a country request), or
        per city seen on at least `MIN_CITY` cards (a region request); [] for a city request, or when country-level
        cards are common (every part would repeat them and stay capped)."""
        if r.params.get("city") or not seen:
            return []
        names = {fold(n) for n in country.get(r.params.get("country") or "pl").place_names}
        places = [[p.strip() for p in o.locations[0].split(",")] for o in seen if o.locations]
        national = sum(len(p) == 1 and fold(p[0]) in names for p in places)
        if national >= MAX_NATIONAL * len(seen):
            log(self.name, f"{r.keyword or '*'}: {national} of {len(seen)} cards placed at country level; not split")
            return []
        here = [p for p in places if len(p) >= 3 and fold(p[-1]) in names]  # City, Region, Country
        if region := r.params.get("region"):
            counts = Counter(p[0] for p in here if fold(p[-2]) == fold(region))
            return [replace(r, params={**r.params, "city": c}) for c in sorted(c for c, n in counts.items() if n >= MIN_CITY)]
        return [replace(r, params={**r.params, "region": g}) for g in sorted({p[-2] for p in here})]

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out = []
        for card in re.findall(r"<li>(.*?)</li>", raw, re.S):
            m = re.search(r'href="(https://[a-z]+\.linkedin\.com/jobs/view/[^"?]+)', card)
            if not m:
                continue
            published = (re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', card) or [None, ""])[1]
            loc = html_field(r"job-search-card__location[^>]*>(.*?)<", card)
            out.append(Offer(board=self.name, key=m.group(1), url=m.group(1),
                             title=html_field(r"base-search-card__title[^>]*>(.*?)<", card),
                             company=html_field(r"base-search-card__subtitle[^>]*>.*?>(.*?)<", card),
                             locations=[loc] if loc else [], pay_text=html_field(r"job-search-card__salary-info[^>]*>(.*?)</span", card),
                             published=dt.date.fromisoformat(published) if published else None,
                             promoted="promoted" in card.lower()))
        return out

    @staticmethod
    def posting_fields(page: str) -> dict:
        """The guest posting page: only its description block, plus the job criteria (seniority, employment
        type, ...) and the location line, which the search cards lack."""
        i = page.find("show-more-less-html__markup")
        body = page[page.find(">", i) + 1:page.find("</div>", i)] if i >= 0 else ""
        criteria = [f"{html.unescape(k)}: {clean_spaces(html.unescape(v))}" for k, v in re.findall(
            r'description__job-criteria-subheader[^>]*>\s*([^<]+?)\s*</h3>\s*<span[^>]*>\s*([^<]+?)\s*</span>', page)]
        place = re.search(r'topcard__flavor--bullet[^>]*>\s*([^<]+?)\s*<', page)
        head = ([f"Location: {clean_spaces(html.unescape(place.group(1)))}"] if place else []) + criteria
        text = html_to_text(body)
        return {"description": ("\n".join(head) + "\n\n" + text).strip() if text else "", "source": "api"}

    @staticmethod
    def detail_url(url: str) -> str | None:
        m = re.search(r"-(\d+)/?$", url)
        return POSTING + m.group(1) if m else None
