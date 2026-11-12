"""justjoin.it and rocketjobs.pl (same engine; rocketjobs covers non-IT jobs).

Result pages embed the full offer objects as escaped JSON (`{"offers":[...]}`, 50 per page).
The tab fetches the page and returns only the slice holding that JSON; `extract_offers` decodes it.

URL: `<base>/<city-slug>|<remote>|<all>?keyword=K&radius=KM&<worktime>=<part>,freelance&sortBy=newest&<page>=N`
(verified live 2026-11-12). Query labels are localised: justjoin `page`, `working-times=part-time`;
rocketjobs `strona`, `wymiar-godzin=niepelny-wymiar`. A city matches the offer's `multilocation` within
`radius` km (default 30, any integer accepted). `sortBy=newest` orders by first publication; the default
order follows re-publications. `categoryId` is always 0; the category is the slug tail after the city
(e.g. `...-krakow-security`, rocketjobs `...-lodz-finanse-ksiegowosc`).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse

from .... import infer
from ....model import Offer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import slug

_SHRINK = r"""(t)=>{const k=t.indexOf('{\\"offers\\":[');return k<0?'':t.slice(k,k+900000)}"""


def extract_offers(chunk: str) -> list[dict] | None:
    """Decode the escaped `{"offers":[...]}` JSON; None when the chunk is truncated or malformed."""
    if not chunk:
        return []
    text = re.sub(r'\\(["\\/])', r"\1", chunk)  # JS string escapes, one left-to-right pass
    start = text.find('{"offers":[')
    if start < 0:
        return []
    i = start + len('{"offers":')
    depth, in_str, esc = 0, False, False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i:j + 1])
                except json.JSONDecodeError:
                    return None
    return None


def category_from_slug(offer_slug: str, city: str) -> str:
    """Board category from an offer slug: the part after the city, without a trailing hash."""
    c = slug(city) if city else ""
    i = offer_slug.rfind(f"-{c}-") if c else -1
    if i < 0:
        return ""
    tail = re.sub(r"-[0-9a-f]{8}$", "", offer_slug[i + len(c) + 2:])
    return tail.replace("-", " ")


class _JustJoinEngine(Board):
    base: str = ""
    offer_base: str = ""
    remote_path: str = ""
    all_path: str = ""
    page_param: str = ""
    worktime_param: str = ""
    part_time_values: str = ""

    def page_url(self, r: Request, page: int) -> str | None:
        if page > self.caps.max_pages:
            return None
        p = r.params
        where = slug(p["city"]) if p.get("city") else (self.remote_path if p.get("remote") else self.all_path)
        q = {"keyword": r.keyword or ""}
        if p.get("city") and p.get("radius_km") is not None:
            q["radius"] = round(p["radius_km"])
        if p.get("part_time"):
            q[self.worktime_param] = self.part_time_values
        if p.get("sort") == "newest":
            q["sortBy"] = "newest"
        if page > 1:
            q[self.page_param] = page
        return f"{self.base}/{where}?{urllib.parse.urlencode(q, safe=',')}"

    def fetch_js(self) -> str:
        return _SHRINK

    def parse(self, raw: str, r: Request) -> list[Offer]:
        offers = extract_offers(raw)
        if offers is None:
            raise ValueError("could not decode the offers JSON (page truncated or format changed)")
        out = []
        for o in offers:
            types = o.get("employmentTypes") or []
            pay = "; ".join(f"{e.get('type')}:{e.get('from')}-{e.get('to')}/{e.get('unit')}{' gross' if e.get('gross') else ''}"
                            for e in types if e.get("currency") == "PLN" and e.get("currencySource") == "original" and e.get("from"))
            published = (o.get("publishedAt") or "")[:10]
            cities = [m.get("city") for m in o.get("multilocation") or [] if m.get("city")] or ([o["city"]] if o.get("city") else [])
            out.append(Offer(
                board=self.name, key=self.offer_base + o["slug"], url=self.offer_base + o["slug"], title=o.get("title") or "",
                company=o.get("companyName") or "", mode=infer.mode(o.get("workplaceType")), locations=sorted(set(cities)),
                worktime=infer.worktime(o.get("workingTime")), contracts=sorted({infer.contract(e.get("type")) for e in types}),
                level=infer.level(o.get("experienceLevel")), category=category_from_slug(o["slug"], o.get("city") or ""),
                skills=list(o.get("requiredSkills") or []), pay_text=pay,
                published=dt.date.fromisoformat(published) if published else None,
                promoted=bool(o.get("isPromoted") or o.get("isSuperOffer"))))
        return out


@register
class JustJoin(_JustJoinEngine):
    name = "justjoin"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=True, page_size=50,
                max_pages=150, transport="browser_fetch", origin="https://justjoin.it/")
    base = "https://justjoin.it/job-offers"
    offer_base = "https://justjoin.it/job-offer/"
    remote_path, all_path, page_param = "remote", "all-locations", "page"
    worktime_param, part_time_values = "working-times", "part-time,freelance"


@register
class RocketJobs(_JustJoinEngine):
    name = "rocketjobs"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=True, page_size=50,
                max_pages=150, transport="browser_fetch", origin="https://rocketjobs.pl/")
    base = "https://rocketjobs.pl/oferty-pracy"
    offer_base = "https://rocketjobs.pl/oferta-pracy/"
    remote_path, all_path, page_param = "praca-zdalna", "wszystkie-lokalizacje", "strona"  # ignores ?page
    worktime_param, part_time_values = "wymiar-godzin", "niepelny-wymiar,freelance"
