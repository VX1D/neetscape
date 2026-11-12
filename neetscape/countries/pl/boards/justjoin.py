"""justjoin.it and rocketjobs.pl (same engine; rocketjobs covers non-IT jobs).

Result pages embed the full offer objects as escaped JSON (`{"offers":[...]}`, 50 per page).
The tab fetches the page and returns only the slice holding that JSON; `extract_offers` decodes it.

URL: `<base>/<city-slug>|<remote>|<all>?keyword=K&radius=KM&<worktime>=<part>,freelance&sortBy=newest&<page>=N`
(verified live 2026-11-12: keyword, remote, city + radius, part-time and sort change the results; pages are
disjoint; the last page is short and the one after it is a 404). Query labels are localised: justjoin `page`,
`working-times=part-time`; rocketjobs `strona` (it ignores `page`), `wymiar-godzin=niepelny-wymiar`. A city
matches the offer's `multilocation` within `radius` km (default 30, any integer accepted). `sortBy=newest`
orders by `lastPublishedAt` (re-publication); the default order is not by date. The offer page
shows `publishedAt` ("Published: ..."), which is what `published` holds.

Result cap (verified live 2026-11-12 on both boards): a listing shows at most 10 000 results, 200 pages of 50; page
200 is full and page 201 a 404 even when more match (justjoin, all locations: 200 full pages, while its experience
levels alone list 393 + 3519 + 6693 + 249 results for junior, mid, senior and c-level; rocketjobs, all locations:
page 200 full, page 201 a 404). The page's offer count (`count`, "N job offers") is not the number of results but
larger (remote 10 908 -> 4934 results, "rust" 1252 -> 619, junior 658 -> 393), so it serves as an upper bound:
`total()` returns it, and a request whose count reaches the cap is split, first by experience level
(`experience-levels=` / `doswiadczenie=`, the levels and their URL values read from the page's facets), then by
category (the `/<where>/<category>` links the page lists). Both partition a listing: the level facets sum to the
count (20 310), and the 24 category counts of the c-level listing sum to its 301. When the count overstates, the
split costs one extra page per sub-request (the remote listing is split by level although it fits). `max_pages` is
the cap's 200 pages: the 404 after page 200 must not end a capped request as complete.
An offer published for several cities is listed once per city (own slug), so it appears as several offers
with the same title and company. `categoryId` is always 0; the category is the slug tail after the city
(e.g. `...-krakow-security`, rocketjobs `...-lodz-finanse-ksiegowosc`).

Pay: one range per contract type in the currency the employer gave (`currencySource: original`, PLN, EUR,
USD...); the board's conversions into other currencies are skipped. Some employers enter an hourly rate with
the unit "month" ("120 - 150 PLN per month"); the board shows it like that and `pay.py` reads it as hourly.
Contract type `any` (shown as "Any") is no particular contract: such offers get no contract type.
"""
from __future__ import annotations

import json
import re
import urllib.parse

from .... import infer
from ....model import Offer
from ....boards.base import Board, Caps, Request, narrowed, register
from ....boards.pages import epoch_or_iso_date, pay_range, slug

WORKTIME_ALIASES = {"internship": "practice_internship"}  # rocketjobs "Praktyka / Staż" -> infer.worktime
# the page shrunk in the tab: the offer count, the experience-level facets with their URL values, the category
# links, and the slice of the page holding the escaped offers JSON (`chunk`, decoded by `extract_offers`)
_SHRINK = r"""(t)=>{const u=s=>JSON.parse(s.replace(/\\"/g,'"'));const k=t.indexOf('{\\"offers\\":[');
const c=t.match(/\\"count\\":(\d+),\\"heading\\"/);
const lv=t.match(/\\"experienceLevels\\":\{\\"label\\":\\"[^\\]+\\",\\"values\\":(\{[^}]*\})/);
const fc=t.match(/\\"experienceLevels\\":(\[\{\\"key[^\]]*\])/);
const cats=[...new Set([...t.matchAll(/offer_list_category_link" href="([^"?#]*)/g)].map(m=>m[1].split('/').pop()))];
let levels=[];try{const v=lv?u(lv[1]):{};levels=(fc?u(fc[1]):[]).filter(x=>x.count>0).map(x=>({value:v[x.key]||x.key,count:x.count}))}catch(e){}
return JSON.stringify({count:c?+c[1]:null,levels,categories:cats,chunk:k<0?'':t.slice(k,k+900000)})}"""
RESULT_CAP = 10_000  # 200 pages of 50


def page_data(raw: str) -> dict:
    """The shrunk page {count, levels: [{value, count}], categories: [slug], chunk}. A bare chunk (an older
    recording) holds the offers alone."""
    if raw.startswith('{"'):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "chunk" in data:
            return data
    return {"count": None, "levels": [], "categories": [], "chunk": raw}


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
    level_param: str = ""

    def page_url(self, r: Request, page: int) -> str | None:
        p = r.params
        where = slug(p["city"]) if p.get("city") else (self.remote_path if p.get("remote") else self.all_path)
        if p.get("category"):
            where += "/" + p["category"]
        q = {"keyword": r.keyword or ""}
        if p.get("city") and p.get("radius_km") is not None:
            q["radius"] = round(p["radius_km"])
        if p.get("part_time"):
            q[self.worktime_param] = self.part_time_values
        if p.get("level"):
            q[self.level_param] = p["level"]
        if p.get("sort") == "newest":
            q["sortBy"] = "newest"
        if page > 1:
            q[self.page_param] = page
        return f"{self.base}/{where}?{urllib.parse.urlencode(q, safe=',')}"

    def fetch_js(self) -> str:
        return _SHRINK

    def total(self, raw: str, r: Request) -> int | None:
        return page_data(raw).get("count")

    def split(self, raw: str, r: Request) -> list[Request]:
        """One request per experience level the page lists or, for a request already narrowed to a level, one per
        category the page links to."""
        data = page_data(raw)
        if not r.params.get("level"):
            return narrowed(r, "level", [lv["value"] for lv in data.get("levels") or []])
        if not r.params.get("category"):
            return narrowed(r, "category", data.get("categories") or [])
        return []

    def parse(self, raw: str, r: Request) -> list[Offer]:
        offers = extract_offers(page_data(raw)["chunk"])
        if offers is None:
            raise ValueError("could not decode the offers JSON (page truncated or format changed)")
        out = []
        for o in offers:
            types = o.get("employmentTypes") or []
            # one entry per contract type in the employer's currency ("original"), plus the board's conversions
            pay = "; ".join(pay_range(e.get("type"), e["from"], e.get("to") or e["from"], e.get("currency") or "PLN",
                                      e.get("unit") or "month", bool(e.get("gross")))
                            for e in types if e.get("currencySource") == "original" and e.get("from"))
            cities = [m.get("city") for m in o.get("multilocation") or [] if m.get("city")] or ([o["city"]] if o.get("city") else [])
            out.append(Offer(
                board=self.name, key=self.offer_base + o["slug"], url=self.offer_base + o["slug"], title=o.get("title") or "",
                company=o.get("companyName") or "", mode=infer.mode(o.get("workplaceType")), locations=sorted(set(cities)),
                worktime=infer.worktime(WORKTIME_ALIASES.get(o.get("workingTime"), o.get("workingTime"))),
                contracts=sorted({infer.contract(e.get("type")) for e in types if e.get("type") != "any"}),
                level=infer.level(o.get("experienceLevel")), category=category_from_slug(o["slug"], o.get("city") or ""),
                skills=list(o.get("requiredSkills") or []), pay_text=pay,
                published=epoch_or_iso_date(o.get("publishedAt")),
                promoted=bool(o.get("isPromoted") or o.get("isSuperOffer"))))
        return out


@register
class JustJoin(_JustJoinEngine):
    name = "justjoin"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=True, page_size=50,
                max_pages=RESULT_CAP // 50, result_cap=RESULT_CAP, transport="browser_fetch", origin="https://justjoin.it/")
    base = "https://justjoin.it/job-offers"
    offer_base = "https://justjoin.it/job-offer/"
    remote_path, all_path, page_param = "remote", "all-locations", "page"
    worktime_param, part_time_values, level_param = "working-times", "part-time,freelance", "experience-levels"


@register
class RocketJobs(_JustJoinEngine):
    name = "rocketjobs"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=True, page_size=50,
                max_pages=RESULT_CAP // 50, result_cap=RESULT_CAP, transport="browser_fetch", origin="https://rocketjobs.pl/")
    base = "https://rocketjobs.pl/oferty-pracy"
    offer_base = "https://rocketjobs.pl/oferta-pracy/"
    remote_path, all_path, page_param = "praca-zdalna", "wszystkie-lokalizacje", "strona"  # ignores ?page
    worktime_param, part_time_values, level_param = "wymiar-godzin", "niepelny-wymiar,freelance", "doswiadczenie"
