"""International remote-only boards with machine-readable feeds (country "intl", opt-in): remoteok API,
weworkremotely RSS. Each is one download per run, filtered locally."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from .. import infer
from ..model import Offer
from ..posting import html_to_text
from .base import Board, Caps, Request, register
from .pages import feed_date


@register
class RemoteOK(Board):
    name = "remoteok"
    caps = Caps(keywords=False, remote="always", page_size=0, max_pages=1, country="intl", transport="http")

    def page_url(self, r: Request, page: int) -> str | None:
        return "https://remoteok.com/api" if page == 1 else None

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out = []
        for o in json.loads(raw)[1:]:
            url = o.get("url") or f"https://remoteok.com/remote-jobs/{o.get('id')}"
            out.append(Offer(board=self.name, key=url, url=url, title=o.get("position") or "", company=o.get("company") or "",
                             mode="remote", locations=[o["location"]] if o.get("location") else [], skills=list(o.get("tags") or []),
                             pay_text=f"{o['salary_min']}-{o['salary_max']} USD/year" if o.get("salary_min") else "",
                             published=feed_date(o.get("date")), description=html_to_text(o.get("description", ""))))
        return out


@register
class WeWorkRemotely(Board):
    name = "weworkremotely"
    caps = Caps(keywords=False, remote="always", page_size=0, max_pages=1, country="intl", transport="http")

    def page_url(self, r: Request, page: int) -> str | None:
        return "https://weworkremotely.com/remote-jobs.rss" if page == 1 else None

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out = []
        for item in ET.fromstring(raw.encode()).iter("item"):
            g = lambda tag: (item.findtext(tag) or "").strip()
            company, _, title = g("title").partition(": ")
            out.append(Offer(board=self.name, key=g("link"), url=g("link"), title=title or company, company=company if title else "",
                             mode="remote", locations=[g("region")] if g("region") else [], category=g("category"),
                             worktime=infer.worktime(g("type").lower().replace("-", "_")),
                             published=feed_date(g("pubDate")), description=html_to_text(g("description"))))
        return out
