"""useme.com — freelance projects from the server-rendered result page (plain HTTP, no embedded JSON), 20 cards per
page. Always remote; pay is the budget per project.

    GET https://useme.com/pl/jobs/?query=K&order_by=-published_on&page=N

Verified live 2026-11-12:
- a query searches every project ever posted ("python": 1186 results, only the first 2 open); closed cards
  ("Zakończone", `job__header-details--closed`) are dropped, so a page with no open project ends the request;
- open projects come first, newest first (the default order, also `order_by=-published_on`), then the closed ones:
  without a query pages 1-34 hold 680 open projects (page 32: still 55 days to run, page 34: 20-24 days), page 35
  one open and 19 closed, pages 36, 40, 45, 50 and 100 only closed (of 5104). So listing everything is ~35 pages;
  `max_pages` (100, three times that) is a safety stop. Deep pages may be refused (page 200: HTTP 403);
- cards carry the client's name, the budget ("750,00 PLN", "5000,00 USD" or "Do negocjacji"), the category, skills
  and the expiry ("Znika za 30 dni", projects run 5–90 days), but no date (no refresh date either): `published`
  stays unknown in the listing and comes from the posting's JSON-LD `datePosted` when it is opened (`neetscape
  details`). That is the first publication: the "Opublikowano" date the project page shows; projects are not
  refreshed (their ids grow with that date: 147434 -> 11-12, 144943 -> 09-24, 144097 -> 09-09).
- category vs industry: the project's category ("Video", "Social media", "Strony internetowe") is the kind of
  work, a role; no industry.
"""
from __future__ import annotations

import html
import re

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import html_field, html_text, snippet, with_query
from ....model import Offer
from .vocab import LANGS

BASE = "https://useme.com"
_ARTICLE = re.compile(r'<article class="job[^"]*">(.*?)</article>', re.S)


@register
class Useme(Board):
    name = "useme"
    caps = Caps(keywords=True, remote="always", sort_newest=True, max_pages=100, transport="http")
    accept = "text/html"

    def page_url(self, r: Request, page: int) -> str | None:
        # never None: the listing goes on past `max_pages`, so a request stopped there is partial (no "gone" marks)
        query = {"query": r.keyword or ""} | ({"order_by": "-published_on"} if r.params.get("sort") == "newest" else {}) \
            | ({"page": page} if page > 1 else {})
        return with_query(f"{BASE}/pl/jobs/", query)

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out: dict[str, Offer] = {}
        for card in _ARTICLE.findall(raw):
            if "job__header-details--closed" in card:
                continue  # closed: no longer takes offers
            link = re.search(r'<a href="(/pl/jobs/[^"?#]+,\d+/)"[^>]*job__title', card)
            title = html_field(r"job__title[^>]*>(.*?)</a>", card)
            if not link or not title:
                continue
            url = BASE + link.group(1)
            budget = html_field(r'class="job__budget"[^>]*>(.*?)</div>', card)  # "750,00 PLN" or "Do negocjacji"
            client = re.search(r'<strong aria-label="([^"]*)"', card)
            skills = [html_text(s) for s in re.findall(r'<a class="tag[^>]*>(.*?)</a>', card, re.S)]
            description = html_field(r'class="job__content[^"]*">.*?<p[^>]*>(.*?)</p>', card)
            out[url] = Offer(
                board=self.name, key=url, url=url, title=title[:140],
                company=html.unescape(client.group(1))[:80] if client else "", mode="remote", worktime="flexible",
                contracts=["freelance"], category=html_field(r'class="job__category">(.*?)</div>', card),
                skills=[s for s in skills if s], level=infer.level_from_text(title, LANGS),
                pay_text=budget if re.search(r"\d", budget) else "", pay_period="project",
                snippet=snippet(title, description, budget))
        return list(out.values())
