"""example.com — what is read and how: a public JSON API (plain HTTP), the JSON embedded in the result page, or
server-rendered cards. Copy to neetscape/countries/<cc>/boards/<name>.py, import it in that package's __init__.py
and add it to __all__ there, record a fixture and add a COVERAGE row (see CONTRIBUTING.md).

    GET https://jobs.example.com/api/search?q=K&remote=1&sort=date&page=N

Verified live YYYY-MM-DD:
- which query parameters change the results, and which are ignored;
- page size, what the page after the last one returns, a result cap (or none, and how that was checked);
- the order (newest first?), which date the board shows (first publication or last refresh);
- rate limits, the board's terms.

Layout: this docstring, imports, constants (URLs, vocabulary tables, `FETCH_JS`), small functions per card field,
then the class with its methods in this order. Use the helpers in boards/pages.py and boards/base.py. Examples: a
GET JSON API, countries/de/boards/arbeitnow.py; a POST API (`post_body`), pl/boards/bulldogjob.py; JSON embedded in
the page, read in a tab (`fetch_js`), pl/boards/pracuj.py; server-rendered cards, pl/boards/useme.py.
"""
from __future__ import annotations

import json

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import date_of, pay_range, present, with_query
from ....model import Offer
from .vocab import LANGS  # lang packs of the country (neetscape/lang/<code>.py)

API = "https://jobs.example.com/api/search"


def pay_text(salary: dict) -> str:
    """'b2b:12000-18000 EUR/month'; '' without a range."""
    return pay_range("b2b", salary["min"], salary.get("max"), "EUR", "month") if salary.get("min") else ""


@register  # the country comes from the package path (neetscape.countries.<cc>...)
class Example(Board):
    name = "example"
    # Be honest: declare only what you verified (defaults left out). Whatever is not pushed is still checked
    # locally, so a missing capability costs crawl time, never results; a wrong one silently loses offers.
    caps = Caps(
        keywords=True,          # the board searches phrases server-side
        remote="filter",        # "filter" (server-side), "always" (remote-only board) or "no"
        sort_newest=True,       # results can be ordered newest first (enables incremental stops)
        page_size=50,           # fixed page size (a shorter page ends the request); 0 if it varies
        max_pages=20,
        transport="http",       # "http" (GET, or POST with `post_body`) or "browser_fetch" (same-origin fetch
    )                           # in a tab opened on `origin`, for boards that wall plain clients)
    # Other Caps: city, radius, worktime (part-time filter), huge_unfiltered (listing everything is too large
    # without keywords, a city or the remote filter), local_all (the whole board is one cheap download),
    # whole_listing (one response is the whole listing), result_cap (+ total()/split()), empty_retries, origin.
    accept = "application/json"  # http: Accept header
    # headers = {...}            # http: extra request headers (e.g. a public API key)
    # content_type = "..."       # http POST searches: Content-Type of `post_body`
    # min_interval = {"jobs.example.com": 4.0}  # seconds between requests, for boards that throttle hard
    # posting_selector = "..."   # CSS selector of the posting body on the rendered offer page, a fallback for
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
        return with_query(API, q | {"page": page})

    # def post_body(self, r: Request, page: int) -> str | None:
    #     """Only for searches sent as a POST (http transport): the body, sent as `content_type`."""

    # def fetch_js(self) -> str | None:
    #     """Only for browser_fetch: JS `(text)=>string` that cuts the page down in the tab (pages.script_json)."""

    def parse(self, raw: str, r: Request) -> list[Offer]:
        """Pure function of the raw page: no network, no clock. Unknown stays unknown. Raise ValueError when
        the page is not a result page (bot wall, format change), so the request records an error."""
        out = []
        for o in json.loads(raw).get("jobs") or []:
            url = o["url"]
            out.append(Offer(
                board=self.name, key=url, url=url, title=o.get("title") or "", company=o.get("company") or "",
                mode="remote" if o.get("remote") else "unknown", locations=present(o.get("city")),
                contracts=[infer.contract(c) for c in o.get("contracts") or []],
                level=infer.level_from_text(o.get("title") or "", LANGS), pay_text=pay_text(o.get("salary") or {}),
                published=date_of(o.get("date"))))
        return out

    # def posting_body(self, page: str) -> str:
    #     """Only when the offer page's JSON-LD lacks the posting body: the body read from the page's embedded
    #     data, as plain text (never the whole page); `posting()` then stores it with `source` "board"."""
