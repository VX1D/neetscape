"""Template for a new board. Copy to neetscape/countries/<cc>/boards/<name>.py, import it in that
package's __init__.py and add it to __all__ there, record a fixture and add a parser test (see CONTRIBUTING.md).

Write here what you verified live and when: the URL format, which query parameters change the
results (and which are ignored), page size, ordering, rate limits, the board's terms.

    GET https://jobs.example.com/api/search?q=K&remote=1&page=N      (verified live YYYY-MM-DD)

Worked examples per shape: a GET JSON API, neetscape/countries/de/boards/arbeitnow.py; a POST search API
(`post_body`), countries/pl/boards/bulldogjob.py; JSON embedded in the result page read in a browser tab
(transport "browser_fetch", `fetch_js`), countries/pl/boards/pracuj.py; server-rendered cards over plain HTTP,
countries/pl/boards/useme.py. Shared parsing helpers are in neetscape/boards/pages.py.
"""
from __future__ import annotations

import json
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import epoch_or_iso_date, pay_range
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
        huge_unfiltered=False,  # listing everything is too large without keywords, a city or the remote filter
        local_all=False,        # the whole board is one cheap download (serves every search)
        whole_listing=False,    # one response is the request's whole listing (feeds): fetching it completes it
        transport="http",       # "http" (GET, or POST with `post_body`) or "browser_fetch" (same-origin fetch
        origin="",              # in a tab opened on `origin`, for boards that wall plain clients)
    )
    accept = "application/json"  # http: Accept header
    headers: dict = {}           # http: extra request headers (e.g. a public API key)
    content_type = ""            # http POST searches: Content-Type of `post_body`
    min_interval: dict = {}      # host -> seconds between requests, for boards that throttle hard
    posting_selector = ""        # CSS selector of the posting body on the rendered offer page, a fallback for
    #                              `details` when `posting()` finds no text; empty: never render

    def page_url(self, r: Request, page: int) -> str | None:
        """URL of one result page; None past the last one. Return a URL past `caps.max_pages` when the listing
        goes on, so a request stopped there stays partial (its unseen offers are not marked gone)."""
        if page > self.caps.max_pages:
            return None
        q = {"q": r.keyword or ""}
        if r.params.get("remote"):
            q["remote"] = 1
        if r.params.get("sort") == "newest":
            q["sort"] = "date"
        q["page"] = page
        return "https://jobs.example.com/api/search?" + urllib.parse.urlencode(q)

    def post_body(self, r: Request, page: int) -> str | None:
        """Only for searches sent as a POST (http transport): the body, sent as `content_type`. Default None (GET)."""
        return None

    def fetch_js(self) -> str | None:
        """Only for browser_fetch: JS `(text)=>string` that cuts the page down in the tab (pages.script_json)."""
        return None

    def parse(self, raw: str, r: Request) -> list[Offer]:
        """Pure function of the raw page: no network, no clock. Unknown stays unknown. Raise ValueError when
        the page is not a result page (bot wall, format change), so the request records an error."""
        out = []
        for o in json.loads(raw).get("jobs") or []:
            url = o["url"]
            sal = o.get("salary") or {}
            out.append(Offer(
                board=self.name, key=url, url=url, title=o.get("title") or "", company=o.get("company") or "",
                mode="remote" if o.get("remote") else "unknown",
                locations=[o["city"]] if o.get("city") else [],
                contracts=[infer.contract(c) for c in o.get("contracts") or []],
                level=infer.level_from_text(o.get("title") or "", LANGS),
                pay_text=pay_range("b2b", sal["min"], sal.get("max"), "EUR", "month") if sal.get("min") else "",
                published=epoch_or_iso_date(o.get("date"))))
        return out

    # def posting(self, page: str) -> dict:
    #     """Override only when the offer page's JSON-LD lacks the posting body: return `parse_posting`'s fields
    #     with `description` read from the page's embedded data (never the whole page) and `source` "board"."""
