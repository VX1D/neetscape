"""useme.com — freelance projects from rendered result cards (transport browser_render), 20 per page.

URL: `/pl/jobs/?query=K&order_by=-published_on&page=N`. Always remote; pay is per project.
"""
from __future__ import annotations

import urllib.parse

from ....boards.base import Caps, register
from ....boards.pages import RenderedBoard


@register
class Useme(RenderedBoard):
    name = "useme"
    caps = Caps(keywords=True, remote="always", sort_newest=True, page_size=20, max_pages=5, huge_unfiltered=True,
                transport="browser_render")
    link_pattern = r"useme\.com/pl/jobs/[^/?#]+,\d+/"

    def url(self, r, page):
        query = {"query": r.keyword or ""} | ({"order_by": "-published_on"} if r.params.get("sort") == "newest" else {})
        return f"https://useme.com/pl/jobs/?{urllib.parse.urlencode(query)}" + (f"&page={page}" if page > 1 else "")

    def extra(self, card, url):
        return {"mode": "remote", "worktime": "flexible", "contracts": ["freelance"], "pay_period": "project"}
