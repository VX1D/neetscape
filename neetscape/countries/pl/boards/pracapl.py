"""praca.pl — offers parsed from the server-rendered result page (transport http); the page embeds no offer JSON
(no `__NEXT_DATA__`, its only JSON-LD is a BreadcrumbList; `window.__filtersData` holds facet counts only).

URLs (verified live 2026-11-12; robots.txt allows `/s-*.html` and offer pages, the terms forbid no automated reading):
- keyword `/s-<kw>[_m-<city>][_<page>].html?...`: the phrase folded to ASCII, words joined by "," ("obsługa klienta" ->
  `s-obsluga,klienta`, 3822 offers; an unfolded `s-obsługa,...` is a 404), "/" -> "-"; without a keyword
  `/oferty-pracy[_<page>].html?...` (remote) or `/<city>[_<page>].html?...`; the city is `pages.slug` ("zielona-gora";
  "zielona,gora" is read as two towns);
- `wm=3` remote work model ("zdalna"; 1 stacjonarna, 2 hybrydowa; several joined by "-"): "asystent" 323 -> 39, the whole
  board 891 remote offers; a card lists every mode the offer allows ("Stacjonarna / Hybrydowa / Zdalna"), so the mode is
  the most remote one listed;
- `cr=<km>` radius around the city: Wieliczka 790 -> 1382 offers with `cr=30`; only 5, 10, 15, 20, 30, 40, 50, 75 and
  100 are accepted (others are ignored), so the radius is rounded up to one of them;
- a search without results says "Nie znaleźliśmy ofert" (`al__no-offers-block`) and then lists the board's newest
  offers under "Zobacz najnowsze oferty pracy": such a page parses to no offers;
- `wt=2-3` part-time ("część etatu") and "tymczasowa/dodatkowa": 891 remote -> 213; `et=<id>` contract type (1 umowa o
  pracę, 3 zlecenie, 4 B2B, 7 staż; not used: Caps has no contract filter);
- `sort=date` newest first (the default order is "date" on some listings and "accuracy" on others, so it is always sent);
- 50 cards per page (4 full pages checked; no page-size parameter), so a shorter page is the last; a page past the
  last is an empty listing (HTTP 200, no cards);
- above the cards, on every page, up to 2 "Oferta tygodnia" cards (`listing-v2__item--week`, a paid product, out of
  date order: `promoted`); highlighted cards (`--highlight`, 1-12 per page) keep their place in the date order, so
  they are not promoted. Page 1 of a keyword listing may end with up to 5 "Oferty urzędu pracy" (labour-office offers
  matching the phrase; no tags, so mode/contracts/work time stay unknown); they are kept;
- the result counter counts offers per location, not cards (remote part-time: "213" offers on 44 cards, one page): an
  ad published in 12 towns is one card whose title opens a list of 12 offer links (one id each); the card's
  `data-ad-id` is the same in every listing, so it is the key; the url is the lowest offer id, without the `#<hash>`
  tracking fragment;
- dates are relative ("przed chwilą", "N godzin temu", "wczoraj", "N dni temu") and are the last refresh (an offer
  shown "przed chwilą" had JSON-LD `datePosted` two weeks earlier); the page footer's "Numer wydania: N" is the
  server's day as days since 1970-01-01 (20769 = 2026-11-12), so `published` = that day minus the whole days shown
  (hours count as today: up to one day off around midnight); without the footer `published` stays unknown;
- each card ships title, employer, location (`title` attribute "Polska, <voivodeship>, <town>[, street]"), the work
  modes, contract types, levels, work time, the salary as published ("4 850 - 6 000 zł brutto/mies.") when given,
  and a teaser of the description; no category.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import (clean_spaces, html_field, html_text, labelled_contracts, lowest, most_remote_mode,
                              nearest_radius, slug, worktime_from_labels)
from ....model import Offer, fold
from .vocab import CONTRACTS, LANGS

BASE = "https://www.praca.pl"
ANONYMOUS = "Klient portalu Praca.pl"  # employer hidden by the board
_ITEM = re.compile(r'<li class="listing-v2__item(?P<cls>[^"]*)"\s+data-ad-id="(?P<ad>\d+)"')
_ITEM_END = re.compile(r'<li class="listing-v2__(?:consent|alert)|listing-v2__announcer|id="pagination"')
_OFFER_URL = re.compile(r'href="(https://www\.praca\.pl/[^"#?]+_(\d+)\.html)[^"]*"')
_SECTION = re.compile(r'<h2 class="listing-v2__header">(.*?)</h2>', re.S)
_OWN_SECTIONS = ("Oferty urzędu pracy",)  # other headed sections ("Zobacz najnowsze oferty pracy") do not match the search
RADII = (5, 10, 15, 20, 30, 40, 50, 75, 100)  # the radius values the board accepts (`cr=25` is ignored)
_EDITION = re.compile(r"Numer wydania:\s*(\d{4,6})")

# the board's job levels (filters.jobLevel), as words found in the card's level tag, which joins several with " / "
LEVELS = ((r"praktykant|stażyst", "intern"), (r"asystent|młodsz[ya] specjalist|\(junior\)", "junior"),
          (r"\(mid\)", "mid"), (r"starsz[ya] specjalist|\(senior\)|ekspert", "senior"),
          (r"kierownik|kierowniczk|koordynator", "manager"), (r"menedżer|dyrektor|prezes", "manager"))
_LEVEL_TAG = re.compile(r"praktykant|stażyst|asystent|specjalist|ekspert|kierownik|koordynator|menedżer|dyrektor|prezes|"
                        r"pracownik fizyczny", re.I)


def keyword_slug(kw: str) -> str:
    """'obsługa klienta' -> 'obsluga,klienta', 'Asystent/ka ds. Administracji' -> 'asystent-ka,ds,administracji'."""
    s = re.sub(r"\s*/\s*", "-", fold(kw.strip()))
    return re.sub(r"[^a-z0-9-]+", ",", s).strip(",-")


def level(tag: str) -> str:
    """The lowest of the levels a card's level tag lists ("Specjalista (mid) / starszy specjalista (senior)": mid)."""
    return lowest(lv for rx, lv in LEVELS if re.search(rx, tag, re.I))


def published(shown: str, today: dt.date | None) -> dt.date | None:
    """'przed chwilą' / 'N minut|godzin temu' -> today, 'wczoraj' -> 1 day, 'N dni temu' -> N days, 'DD.MM.YYYY'."""
    s = shown.strip().lower()
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    if today is None:
        return None
    if s in ("przed chwilą", "dzisiaj", "dziś") or re.fullmatch(r"(\d+ )?(minut[ayę]?|godzin[ayę]?)( temu)?", s):
        return today
    if s == "wczoraj":
        return today - dt.timedelta(days=1)
    m = re.fullmatch(r"(\d+) (dni|dzień|tydzień|tygodnie|tygodni) temu", s)
    if m:
        return today - dt.timedelta(days=int(m.group(1)) * (7 if m.group(2).startswith("tyg") else 1))
    return None


def edition_day(raw: str) -> dt.date | None:
    m = _EDITION.search(raw)
    return dt.date(1970, 1, 1) + dt.timedelta(days=int(m.group(1))) if m else None


def _place(body: str) -> list[str]:
    regions = [html_text(x) for x in re.findall(r'listing-v2__region-text">(.*?)</span>', body, re.S)]
    if regions:
        return sorted(set(regions))
    m = re.search(r'<span class="listing-v2__location" title="([^"]*)"', body)
    if not m:
        return []
    # "Polska, <voivodeship>, <town> (pow. ..., gm. ...)[, <street>]", "Polska, <voivodeship>" or a country ("Szwajcaria")
    parts = [p.strip() for p in re.sub(r"\s*\([^)]*\)?", "", html.unescape(m.group(1))).split(",") if p.strip()]
    if parts[:1] == ["Polska"] and len(parts) > 1:
        return [parts[2] if len(parts) > 2 else parts[1]]
    return parts[:1]


@register
class PracaPl(Board):
    name = "pracapl"
    caps = Caps(keywords=True, remote="filter", city=True, radius=True, worktime=True, sort_newest=True, page_size=50,
                max_pages=20, huge_unfiltered=True, transport="http")
    accept = "text/html"

    def page_url(self, r: Request, page: int) -> str | None:
        if page > self.caps.max_pages:
            return None
        kw = keyword_slug(r.keyword or "")
        city = slug(r.params["city"]) if r.params.get("city") else ""
        path = (f"s-{kw}" + (f"_m-{city}" if city else "")) if kw else (city or "oferty-pracy")
        query = {}
        if city and r.params.get("radius_km"):  # the smallest accepted radius covering the requested one
            query["cr"] = nearest_radius(r.params["radius_km"], RADII)
        if r.params.get("remote"):
            query["wm"] = 3
        if r.params.get("part_time"):
            query["wt"] = "2-3"
        if r.params.get("sort") == "newest":
            query["sort"] = "date"
        return f"{BASE}/{path}" + (f"_{page}" if page > 1 else "") + ".html" + (f"?{urllib.parse.urlencode(query)}" if query else "")

    def parse(self, raw: str, r: Request) -> list[Offer]:
        if 'class="al__no-offers-block' in raw:  # nothing matched: the cards below are the newest offers of the whole board
            return []
        today = edition_day(raw)
        sections = [(h.start(), html_text(h.group(1))) for h in _SECTION.finditer(raw)]
        out: dict[str, Offer] = {}
        starts = list(_ITEM.finditer(raw))
        for m, nxt in zip(starts, starts[1:] + [None]):
            section = next((name for pos, name in reversed(sections) if pos < m.start()), None)
            if section is not None and section not in _OWN_SECTIONS:
                continue
            body = raw[m.end():nxt.start() if nxt else len(raw)]
            end = _ITEM_END.search(body)
            body, ad = body[:end.start()] if end else body, m.group("ad")
            urls = sorted({(int(i), u) for u, i in _OFFER_URL.findall(body)})
            title = html_field(r'class="listing-v2__title[^"]*"[^>]*>(.*?)</(?:a|button)>', body)
            if not urls or not title or ad in out:
                continue
            company = html_field(r'class="listing-v2__employer"[^>]*>(.*?)</(?:a|span)>', body)
            company = "" if company == ANONYMOUS else company
            mode_tag = html_field(r'listing-v2__tag--mode">(.*?)</li>', body)
            tags = [html_text(t) for t in re.findall(r'listing-v2__tag--neutral">(.*?)</li>', body, re.S)]
            contract_tag = next((t for t in tags if re.search(r"\bumowa\b|kontrakt", t, re.I)), "")
            level_tag = next((t for t in tags if _LEVEL_TAG.search(t) and t != contract_tag), "")
            time_tag = next((t for t in tags if re.search(r"etat|tymczasowa|dodatkowa", t, re.I) and t != contract_tag), "")
            pay = html_field(r'listing-v2__tag--salary">(.*?)</li>', body)
            shown = html_field(r'listing-v2__published">(.*?)</span>', body)
            teaser = html_field(r'listing-v2__teaser-text">(.*?)</p>', body)
            modes = [x.strip() for x in mode_tag.split("/") if x.strip()]
            lv = level(level_tag)
            out[ad] = Offer(
                board=self.name, key=ad, url=urls[0][1], title=title[:140], company=company[:80],
                mode=most_remote_mode(modes, "zdaln", "hybryd") if modes else "unknown", locations=_place(body),
                worktime=worktime_from_labels([time_tag], r"część etatu|dodatkowa|tymczasowa", r"pełny etat"),
                contracts=labelled_contracts(contract_tag.split(" / "), CONTRACTS, LANGS),
                level=lv if lv != "unknown" else infer.level_from_text(title, LANGS), pay_text=pay,
                published=published(shown, today), promoted="--week" in m.group("cls"),
                snippet=clean_spaces(f"{title} {teaser}")[:1000])
        return list(out.values())
