"""Template for a new board. Copy to neetscape/countries/<cc>/boards/<name>.py, import it in that
package's __init__.py and add it to __all__ there, record a fixture and add a parser test (see CONTRIBUTING.md).

Write here what you verified live and when: the URL format, which query parameters change the
results (and which are ignored), page size, ordering, rate limits, the board's terms.

    GET https://jobs.example.com/api/search?q=K&remote=1&page=N      (verified live YYYY-MM-DD)

The worked example of this shape is neetscape/countries/de/boards/arbeitnow.py.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....model import Offer

LANGS = ("xx", "en")  # lang packs of the country (neetscape/lang/<code>.py)


@register  # the country comes from the package path (neetscape.countries.<cc>...)
class Example(Board):
    name = "example"
    # Be honest: declare only what you verified. Whatever is not pushed is still checked locally, so a
    # missing capability costs crawl time, never results; a wrong one silently loses offers.
    caps = Caps(
        keywords=True,          # the board searches phrases server-side
        remote="filter",        # "filter" (server-side), "always" (remote-only board) or "no"
        city=False, radius=False,
        worktime=False,         # server-side part-time filter
        sort_newest=True,       # results can be ordered newest first (enables incremental stops)
        page_size=50,           # fixed page size (a shorter page ends the request); 0 if it varies
        max_pages=20,
        huge_unfiltered=False,  # listing everything without keywords or a city is too large
        local_all=False,        # the whole board is one cheap download (serves every search)
        transport="http",       # http > browser_fetch (same-origin JSON) > browser_render (cards)
    )
    accept = "application/json"
    headers: dict = {}          # extra request headers (e.g. a public API key), http transport only

    def page_url(self, r: Request, page: int) -> str | None:
        if page > self.caps.max_pages:
            return None
        q = {"q": r.keyword or ""}
        if r.params.get("remote"):
            q["remote"] = 1
        if r.params.get("sort") == "newest":
            q["sort"] = "date"
        q["page"] = page
        return "https://jobs.example.com/api/search?" + urllib.parse.urlencode(q)

    def parse(self, raw: str, r: Request) -> list[Offer]:
        """Pure function of the raw page: no network, no clock. Unknown stays unknown."""
        out = []
        for o in json.loads(raw).get("jobs") or []:
            url = o["url"]
            out.append(Offer(
                board=self.name, key=url, url=url, title=o.get("title") or "", company=o.get("company") or "",
                mode="remote" if o.get("remote") else "unknown",
                locations=[o["city"]] if o.get("city") else [],
                contracts=[infer.contract(c) for c in o.get("contracts") or []],
                level=infer.level_from_text(o.get("title") or "", LANGS),
                pay_text=o.get("salary") or "",          # as published; normalised later
                published=dt.date.fromisoformat(o["date"][:10]) if o.get("date") else None))
        return out
