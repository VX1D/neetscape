"""International remote-only boards with machine-readable feeds (country "intl", opt-in): the remoteok API and the We
Work Remotely RSS feed. Each is one download per run (`whole_listing`), filtered locally.

Not part of the 2026-11-12 live audit (which covered the Polish boards): the formats are those of the recorded
fixtures in tests/fixtures/shared/.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from .. import infer
from ..model import Offer
from ..posting import html_to_text
from .base import Board, Caps, Request, register
from .pages import date_of, present

FEED_CAPS = Caps(remote="always", whole_listing=True, country="intl", transport="http")


@register
class RemoteOK(Board):
    name = "remoteok"
    caps = FEED_CAPS

    def page_url(self, r: Request, page: int) -> str | None:
        return "https://remoteok.com/api" if page == 1 else None

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out = []
        for o in json.loads(raw)[1:]:  # the first entry is the API's legal notice
            url = o.get("url") or f"https://remoteok.com/remote-jobs/{o.get('id')}"
            out.append(Offer(
                board=self.name, key=url, url=url, title=o.get("position") or "", company=o.get("company") or "",
                mode="remote", locations=present(o.get("location")), skills=list(o.get("tags") or []),
                pay_text=f"{o['salary_min']}-{o['salary_max']} USD/year" if o.get("salary_min") else "",
                published=date_of(o.get("date")), description=html_to_text(o.get("description", ""))))
        return out


@register
class WeWorkRemotely(Board):
    name = "weworkremotely"
    caps = FEED_CAPS

    def page_url(self, r: Request, page: int) -> str | None:
        return "https://weworkremotely.com/remote-jobs.rss" if page == 1 else None

    def parse(self, raw: str, r: Request) -> list[Offer]:
        out = []
        for item in ET.fromstring(raw.encode()).iter("item"):
            def text(tag: str) -> str:
                return (item.findtext(tag) or "").strip()
            company, _, title = text("title").partition(": ")  # "Company: Title"
            out.append(Offer(
                board=self.name, key=text("link"), url=text("link"), title=title or company, company=company if title else "",
                mode="remote", locations=present(text("region")), category=text("category"),
                worktime=infer.worktime(text("type").lower().replace("-", "_")),
                published=date_of(text("pubDate")), description=html_to_text(text("description"))))
        return out
