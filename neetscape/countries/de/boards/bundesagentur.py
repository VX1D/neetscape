"""Bundesagentur für Arbeit — the Jobsuche REST API of the federal employment agency's job board.

    GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?was=K&wo=CITY&umkreis=KM
        &arbeitszeit=tz;mj&veroeffentlichtseit=D&size=100&page=N      header X-API-Key: jobboerse-jobsuche

Verified live 2026-11-12:
- v6 works (v4 answers 403); `size` up to 100, `page` from 1; the result list `ergebnisliste` is absent past the
  last page; results are ordered by relevance, not date;
- `arbeitszeit` takes vz/tz/snw/mj joined with ";" (with "," the result is empty); "ho" (home office) is no longer
  accepted; `veroeffentlichtseit` only takes 0, 1, 7, 14 or 28 (other values are ignored);
- no working remote filter (`homeoffice=` rejects every value tried): a remote search adds the word "Homeoffice" to
  `was` (matched in the posting), and the mode comes from each offer: `homeofficeprozent` 100 = remote,
  `homeofficemoeglich` (typically "NACH_VEREINBARUNG", by arrangement) = hybrid, false = on site;
- pay, when given: `verguetungsangabe` STUNDENLOHN/MONATSGEHALT/JAHRESGEHALT with `gehaltsspanneVon`/`Bis`;
- offer page: https://www.arbeitsagentur.de/jobsuche/jobdetail/<referenznummer>.
- category vs industry: `hauptberuf`, the occupation ("Finanzbuchhalter/in"), is the role; no industry.
"""
from __future__ import annotations

import json
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, Request, register, with_params
from ....boards.pages import amount, date_of, places, with_query
from ....model import Offer, Search
from .vocab import LANGS

API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
OFFER = "https://www.arbeitsagentur.de/jobsuche/jobdetail/"
PUBLISHED_SINCE = (0, 1, 7, 14, 28)  # the `veroeffentlichtseit` values accepted
PAY_UNIT = {"STUNDENLOHN": "Std.", "MONATSGEHALT": "Monat", "JAHRESGEHALT": "Jahr"}
KIND = {"PRAKTIKUM_TRAINEE": ("internship", "intern"), "AUSBILDUNG": ("other", "intern"), "SELBSTAENDIGKEIT": ("freelance", None)}
PART_TIME = ("arbeitszeitTeilzeitVormittag", "arbeitszeitTeilzeitNachmittag", "arbeitszeitTeilzeitAbend",
             "arbeitszeitTeilzeitFlexibel")


def work_mode(o: dict) -> str:
    if o.get("homeofficeprozent") == 100:
        return "remote"
    if o.get("homeofficemoeglich"):
        return "hybrid"
    if o.get("homeofficemoeglich") is False:
        return "onsite"
    return "unknown"


def worktime(o: dict) -> str:
    part = any(o.get(k) for k in PART_TIME) or o.get("istGeringfuegigeBeschaeftigung")
    return "part_time" if part else "full_time" if o.get("arbeitszeitVollzeit") else "unknown"


def pay_text(o: dict) -> str:
    """'3000-4000 EUR/Monat'; '' without a range."""
    lo = o.get("gehaltsspanneVon")
    if not lo:
        return ""
    hi = o.get("gehaltsspanneBis") or lo
    return f"{amount(lo)}-{amount(hi)} EUR/{PAY_UNIT.get(o.get('verguetungsangabe'), '')}".rstrip("/")


def contracts(o: dict) -> list[str]:
    if o.get("istGeringfuegigeBeschaeftigung"):
        return ["mini_job"]
    contract = KIND.get(o.get("stellenangebotsart"), (None, None))[0]
    return [contract] if contract else (["employment"] if o.get("vertragsdauer") in ("UNBEFRISTET", "BEFRISTET") else [])


@register
class Bundesagentur(Board):
    name = "bundesagentur"
    caps = Caps(keywords=True, city=True, radius=True, worktime=True, page_size=100, max_pages=20, transport="http")
    accept = "application/json"
    headers = {"X-API-Key": "jobboerse-jobsuche"}  # public key of the agency's own web client

    def requests(self, s: Search) -> tuple[list[Request], list[str]]:
        """Everything in Germany is too large a listing; a remote search asks for "Homeoffice" in the posting; a
        maximum age is sent as the narrowest accepted `veroeffentlichtseit` covering it."""
        if not s.where.city and not s.where.remote and s.keywords_on(self.name) is None:
            return [], [f"{self.name}: listing everything in Germany is too large without keywords, a city or remote; "
                        f"skipped for '{s.id}'"]
        reqs, warnings = super().requests(s)
        since = next((d for d in PUBLISHED_SINCE if s.max_age_days is not None and d >= s.max_age_days), None)
        out = []
        for r in reqs:
            extra = {"since": since} if since is not None else {}
            if s.where.remote and not r.params.get("city"):
                extra["homeoffice_word"] = True  # no remote filter: "Homeoffice" must appear in the posting
            out.append(with_params(r, **extra))
        return out, warnings

    def page_url(self, r: Request, page: int) -> str | None:
        if page > self.caps.max_pages:
            return None
        p = r.params
        what = " ".join(x for x in (r.keyword, "Homeoffice" if p.get("homeoffice_word") else None) if x)
        q = {"was": what} if what else {}
        if p.get("city"):
            q["wo"] = p["city"]
            if p.get("radius_km") is not None:
                q["umkreis"] = p["radius_km"]
        if p.get("part_time"):
            q["arbeitszeit"] = "tz;mj"
        if p.get("since") is not None:
            q["veroeffentlichtseit"] = p["since"]
        return with_query(API, q | {"size": self.caps.page_size, "page": page})

    def parse(self, raw: str, r: Request) -> list[Offer]:
        data = json.loads(raw)
        if "ergebnisliste" not in data and data.get("messages"):
            raise ValueError(f"API error: {data['messages']}")
        out = []
        for o in data.get("ergebnisliste") or []:
            ref = o.get("referenznummer")
            if not ref:
                continue
            title = (o.get("stellenangebotsTitel") or o.get("hauptberuf") or "").replace("\x96", "–").strip()
            out.append(Offer(
                board=self.name, key=ref, url=OFFER + urllib.parse.quote(ref), title=title, company=o.get("firma") or "",
                mode=work_mode(o), locations=places((x.get("adresse") or {}).get("ort") for x in o.get("stellenlokationen") or []),
                worktime=worktime(o), contracts=contracts(o),
                level=KIND.get(o.get("stellenangebotsart"), (None, None))[1] or infer.level_from_text(title, LANGS),
                category=o.get("hauptberuf") or "", skills=list(o.get("alleBerufe") or []), pay_text=pay_text(o),
                published=date_of(o.get("datumErsteVeroeffentlichung") or (o.get("veroeffentlichungszeitraum") or {}).get("von")),
                snippet=" · ".join(x for x in (o.get("vertragsdauer") == "BEFRISTET" and "befristet", o.get("externeURL")) if x)))
        return out
