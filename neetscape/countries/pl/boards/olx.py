"""olx.pl (jobs) — rendered result cards (transport browser_render).

URLs: `/praca/[<city-slug>/][q-<kw>/]?search[dist]=KM&search[order]=created_at:desc&page=N` (dist=30 adds towns
around the city, verified). There is no remote filter: a remote search adds "zdalnie" to the query and keeps
only offers whose card mentions remote work. Card text after the title: "[company] [pay] <city>[, <district>]
<work time> ... <date>".
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from ....boards.base import Caps, Request, register
from ....boards.pages import MONEY, RenderedBoard, slug

REMOTE_TEXT = re.compile(r"zdaln|remote|online|z domu|home office|home-office", re.I)
WORKTIME = r"\s(?:Pełny etat|Niepełny etat|Praca dodatkowa|Praca sezonowa|Praca tymczasowa)\b"
MONTHS = ("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
          "października", "listopada", "grudnia")


def company_and_place(rest: str, money) -> dict:
    """Company and place from the card text after the title; {} when the layout is not recognised."""
    head = re.split(WORKTIME, " " + rest, maxsplit=1)[0].strip()
    if money and money.start() < len(head):
        company, place = rest[:money.start()], rest[money.end():len(head)]
        company = re.sub(r"\s*\b(?:do|od)$", "", company.strip())
    elif re.search(r"\S+,\s", head):  # "<company> <City>, <district>": the city is the word before the comma
        m = re.search(r"(?:^|\s)(\S+,\s.*)$", head)
        company, place = head[:m.start()], m.group(1)
    else:
        return {}
    return {"company": company.strip()[:80], "locations": [place.strip()] if place.strip() else []}


def olx_date(card: str, today: dt.date | None = None) -> dt.date | None:
    """Date at the end of a card ("Dzisiaj o 10:52", "Odświeżono dnia 10 listopada 2026")."""
    if re.search(r"dzisiaj o \d", card, re.I):
        return today or dt.date.today()
    m = re.search(rf"(\d{{1,2}}) ({'|'.join(MONTHS)}) (\d{{4}})\s*$", card)
    return dt.date(int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1))) if m else None


@register
class Olx(RenderedBoard):
    name = "olx"
    caps = Caps(keywords=True, remote="no", city=True, radius=True, sort_newest=True, max_pages=4, huge_unfiltered=True,
                transport="browser_render")
    link_pattern = r"olx\.pl/oferta/praca/"

    def requests(self, s):
        reqs, warns = super().requests(s)
        if s.where.remote and not s.where.city:
            reqs = [Request(r.board, r.search_id, r.keyword, dict(r.params, remote_text=True), r.pushed) for r in reqs]
        return reqs, warns

    def url(self, r, page):
        kw = ((r.keyword or "") + (" zdalnie" if r.params.get("remote_text") else "")).strip()
        path = "praca/" + (slug(r.params["city"]) + "/" if r.params.get("city") else "")
        query = {}
        if r.params.get("city"):
            query["search[dist]"] = r.params.get("radius_km", 0)
        if r.params.get("sort") == "newest":
            query["search[order]"] = "created_at:desc"
        if page > 1:
            query["page"] = page
        return (f"https://www.olx.pl/{path}" + (f"q-{urllib.parse.quote(kw)}/" if kw else "")
                + (f"?{urllib.parse.urlencode(query)}" if query else ""))

    def card(self, link, rest):
        return super().card(link, rest) | company_and_place(rest, MONEY.search(rest))

    def extra(self, card, url):
        return {"published": olx_date(card), "promoted": "promoted" in url}

    def parse(self, raw, r):
        offers = super().parse(raw, r)
        if r.params.get("remote_text"):
            offers = [o for o in offers if REMOTE_TEXT.search(o.title + " " + o.snippet)]
        return offers
