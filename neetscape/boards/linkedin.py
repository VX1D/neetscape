"""LinkedIn public (logged-out) job search API. 10 offers per page, about 1000 per query.

Verified live 2026-11-12: logged out, only `keywords`, `location`/`geoId`, `start` and `f_TPR` change the
results. `f_WT` (remote), `f_JT` (job type), `f_E`, `distance` and `sortBy=DD` are ignored (identical
pages, unsorted dates), also on the public /jobs/search page, so none of them is pushed. A free-text
`location=Kraków` resolves to a village in Łódzkie, so cities are sent as a `geoId` from the GEO typeahead.

Serves every country (`country="any"`): the searched country arrives in `params["country"]`; without a city the
search goes to the country's `linkedin_location` ("Poland"), a city is resolved among the typeahead hits ending
with one of the country's `place_names`.
"""
from __future__ import annotations

import datetime as dt
import functools
import html
import json
import re
import urllib.parse

from .. import country
from ..log import log
from ..model import Offer, fold
from .base import Board, Caps, Request, register
from .fetch import _http_get
from ..posting import html_to_text
from .pages import clean_spaces, html_field

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
TYPEAHEAD = "https://www.linkedin.com/jobs-guest/api/typeaheadHits?typeaheadType=GEO&query="


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
    caps = Caps(keywords=True, remote="no", city=True, page_size=10, max_pages=100, transport="http", country="any")

    def page_url(self, r: Request, page: int) -> str | None:
        if page > self.caps.max_pages:
            return None
        city, cc = r.params.get("city"), r.params.get("country") or "pl"
        geo = geo_id(city, cc) if city else None
        q = {"keywords": r.keyword or ""}
        q.update({"geoId": geo} if geo else {"location": city or country.get(cc).linkedin_location})
        q["start"] = (page - 1) * 10
        return SEARCH + urllib.parse.urlencode(q)

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
