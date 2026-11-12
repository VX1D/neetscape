"""pl.indeed.com — rendered result cards (transport browser_render), 15 per page, sortable by date.

URLs: remote `/jobs?q=K&sc=0kf%3Aattr%28DSQF7%29%3B&sort=date&start=10*(N-1)`, city `/jobs?q=K&l=<City>&radius=KM`.
Card text after the title: "[Aplikuj bezpośrednio] <company> [Zdalnie in|Hybrydowo in] <place> [pay] [contract] [+N]".
Only result links count: Indeed also plants bare `/viewjob?jk=<fake id>` copies of real cards.
"""
from __future__ import annotations

import re
import urllib.parse

from ....boards.base import Caps, register
from ....boards.pages import RenderedBoard

q = urllib.parse.quote
VOIVODESHIPS = (r"(?:dolnośląskie|kujawsko-pomorskie|lubelskie|lubuskie|łódzkie|małopolskie|mazowieckie|opolskie|podkarpackie|"
                r"podlaskie|pomorskie|śląskie|świętokrzyskie|warmińsko-mazurskie|wielkopolskie|zachodniopomorskie)")


def company_and_place(rest: str) -> dict:
    """Company and place from the card text after the title; {} when the layout is not recognised."""
    rest = re.sub(r"^Aplikuj bezpośrednio\s+", "", rest)
    m = (re.search(r"^(.+?)\s+(?:Zdalnie|Hybrydowo|Praca zdalna)\b(?:\s+in\s+(.*))?", rest)  # no "in <place>": remote
         or re.search(r"^(.+?)\s+(\d\d-\d{3}\s+\S.*)$", rest)
         or re.search(rf"^(.+?)\s+(\S+,\s{VOIVODESHIPS}\b.*)$", rest))
    if not m:
        return {}
    place = re.match(rf"(?:\d\d-\d{{3}}\s+)?([A-ZŁŚŻŹĆ][\w\-]+(?:,\s{VOIVODESHIPS})?)", m.group(2) or "")
    return {"company": m.group(1).strip()[:80], "locations": [place.group(1)] if place else []}


@register
class Indeed(RenderedBoard):
    name = "indeed"
    # an empty query returns no results (verified live 2026-11-12), so listing everything needs phrases
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, sort_newest=True, page_size=15, max_pages=10,
                huge_unfiltered=True, transport="browser_render")
    link_pattern = r"/(?:rc/clk|pagead/clk)\?.*jk=[0-9a-f]+"

    def url(self, r, page):
        start = f"&start={10 * (page - 1)}" if page > 1 else ""
        sort = "&sort=date" if r.params.get("sort") == "newest" else ""
        if r.params.get("city"):
            return f"https://pl.indeed.com/jobs?q={q(r.keyword or '')}&l={q(r.params['city'])}&radius={r.params.get('radius_km', 0)}{sort}{start}"
        return f"https://pl.indeed.com/jobs?q={q(r.keyword or '')}&sc=0kf%3Aattr%28DSQF7%29%3B{sort}{start}"

    def offer_key(self, url):
        return "https://pl.indeed.com/viewjob?" + re.search(r"jk=[0-9a-f]+", url).group(0)

    def card(self, link, rest):
        return super().card(link, rest) | company_and_place(rest)
