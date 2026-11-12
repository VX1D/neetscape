"""useme.com — freelance projects parsed from the server-rendered result page (transport http), 20 cards per page.

URL: `/pl/jobs/?query=K&order_by=-published_on&page=N`. Always remote; pay is the budget per project.
Verified live 2026-11-12:
- a query searches every project ever posted, closed ones included ("python": 1186 results, of which only
  the first 2 were open); closed cards say "Zakończone" (class `job__header-details--closed`) and are dropped
  here, so a page with no open project ends the request. Without a query the listing is mostly open ones;
- newest first (the default order, also `order_by=-published_on`), so open projects come before closed ones;
- cards carry the client's name, the budget ("750,00 PLN", "5000,00 USD" or "Do negocjacji"), the category,
  skills and the expiry ("Znika za 30 dni", projects run 5–90 days), but no posting date: `published` comes
  from the posting's JSON-LD `datePosted` when it is opened (`neetscape details`);
- plain HTTP is served; there is no embedded JSON on the result page.
"""
from __future__ import annotations

import html
import re
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import clean_spaces, html_field, html_text
from ....model import Offer
from .vocab import LANGS

_ARTICLE = re.compile(r'<article class="job[^"]*">(.*?)</article>', re.S)


@register
class Useme(Board):
    name = "useme"
    caps = Caps(keywords=True, remote="always", sort_newest=True, page_size=0, max_pages=5, huge_unfiltered=True)
    accept = "text/html"

    def page_url(self, r: Request, page: int) -> str | None:
        # never None: the listing goes on past `max_pages`, so a request stopped there is partial (no "gone" marks)
        query = {"query": r.keyword or ""} | ({"order_by": "-published_on"} if r.params.get("sort") == "newest" else {})
        return f"https://useme.com/pl/jobs/?{urllib.parse.urlencode(query)}" + (f"&page={page}" if page > 1 else "")

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out: dict[str, Offer] = {}
        for art in _ARTICLE.findall(raw):
            if "job__header-details--closed" in art:
                continue  # closed: no longer takes offers
            link = re.search(r'<a href="(/pl/jobs/[^"?#]+,\d+/)"[^>]*job__title', art)
            title = html_field(r"job__title[^>]*>(.*?)</a>", art)
            if not link or not title:
                continue
            url = "https://useme.com" + link.group(1)
            budget = html_field(r'class="job__budget"[^>]*>(.*?)</div>', art)  # "750,00 PLN" or "Do negocjacji"
            who = re.search(r'<strong aria-label="([^"]*)"', art)
            skills = [html_text(s) for s in re.findall(r'<a class="tag[^>]*>(.*?)</a>', art, re.S)]
            description = html_field(r'class="job__content[^"]*">.*?<p[^>]*>(.*?)</p>', art)
            out[url] = Offer(
                board=self.name, key=url, url=url, title=title[:140], company=html.unescape(who.group(1))[:80] if who else "",
                mode="remote", worktime="flexible", contracts=["freelance"],
                category=html_field(r'class="job__category">(.*?)</div>', art), skills=[s for s in skills if s],
                level=infer.level_from_text(title, LANGS), pay_text=budget if re.search(r"\d", budget) else "",
                pay_period="project", snippet=clean_spaces(f"{title} {description} {budget}")[:1000])
        return list(out.values())

