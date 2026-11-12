"""Bundesagentur für Arbeit, Jobsuche REST API (the federal employment agency's job board).

    GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?was=K&wo=CITY&umkreis=KM
        &arbeitszeit=tz;mj&veroeffentlichtseit=D&size=100&page=N      header X-API-Key: jobboerse-jobsuche

Verified live 2026-11-12: v6 works (v4 answers 403). `size` up to 100, `page` from 1; the result list is
`ergebnisliste` (absent past the last page). `arbeitszeit` takes vz/tz/snw/mj joined with ";" (with ","
the result is empty); "ho" (home office) is no longer accepted. `veroeffentlichtseit` only takes 0, 1, 7,
14 or 28 (other values are ignored). There is no working remote filter (`homeoffice=` rejects every value
tried), so a remote search adds the word "Homeoffice" to `was` (matched in the posting) and the mode comes
from each offer: `homeofficeprozent` 100 = remote, `homeofficemoeglich` (typically "NACH_VEREINBARUNG", by
arrangement) = hybrid, false = on site. Results are ordered by relevance, not date. Pay, when given:
`verguetungsangabe` STUNDENLOHN/MONATSGEHALT/JAHRESGEHALT with `gehaltsspanneVon`/`Bis`.
Offer page: https://www.arbeitsagentur.de/jobsuche/jobdetail/<referenznummer>.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....model import Offer

API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?"
DETAIL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/"
LANGS = ("de", "en")
PUBLISHED_SINCE = (0, 1, 7, 14, 28)
PAY_UNIT = {"STUNDENLOHN": "Std.", "MONATSGEHALT": "Monat", "JAHRESGEHALT": "Jahr"}
KIND = {"PRAKTIKUM_TRAINEE": ("internship", "intern"), "AUSBILDUNG": ("other", "intern"), "SELBSTAENDIGKEIT": ("freelance", None)}


def _num(v) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def _mode(o: dict) -> str:
    if o.get("homeofficeprozent") == 100:
        return "remote"
    if o.get("homeofficemoeglich"):
        return "hybrid"
    if o.get("homeofficemoeglich") is False:
        return "onsite"
    return "unknown"


def _worktime(o: dict) -> str:
    part = any(o.get(k) for k in ("arbeitszeitTeilzeitVormittag", "arbeitszeitTeilzeitNachmittag", "arbeitszeitTeilzeitAbend",
                                  "arbeitszeitTeilzeitFlexibel")) or o.get("istGeringfuegigeBeschaeftigung")
    return "part_time" if part else "full_time" if o.get("arbeitszeitVollzeit") else "unknown"


@register
class Bundesagentur(Board):
    name = "bundesagentur"
    caps = Caps(keywords=True, remote="no", city=True, radius=True, worktime=True, page_size=100, max_pages=20,
                transport="http")
    accept = "application/json"
    headers = {"X-API-Key": "jobboerse-jobsuche"}  # public key of the agency's own web client

    def requests(self, s):
        if not s.where.city and not s.where.remote and s.keywords_on(self.name) is None:
            return [], [f"{self.name}: listing everything in Germany is too large without keywords, a city or remote; "
                        f"skipped for '{s.id}'"]
        reqs, warns = super().requests(s)
        since = next((d for d in PUBLISHED_SINCE if s.max_age_days is not None and d >= s.max_age_days), None)
        out = []
        for r in reqs:
            params = dict(r.params)
            if since is not None:
                params["since"] = since
            if not params.get("city") and s.where.remote:
                params["homeoffice_word"] = True  # no remote filter: "Homeoffice" must appear in the posting
            out.append(Request(r.board, r.search_id, r.keyword, params, r.pushed))
        return out, warns

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
        q |= {"size": self.caps.page_size, "page": page}
        return API + urllib.parse.urlencode(q)

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
            pay = ""
            if o.get("gehaltsspanneVon"):
                hi = o.get("gehaltsspanneBis") or o["gehaltsspanneVon"]
                pay = f"{_num(o['gehaltsspanneVon'])}-{_num(hi)} EUR/{PAY_UNIT.get(o.get('verguetungsangabe'), '')}".rstrip("/")
            contract, level = KIND.get(o.get("stellenangebotsart"), (None, None))
            contracts = [contract] if contract else (["employment"] if o.get("vertragsdauer") in ("UNBEFRISTET", "BEFRISTET") else [])
            if o.get("istGeringfuegigeBeschaeftigung"):
                contracts = ["mini_job"]
            places = [(l.get("adresse") or {}).get("ort") for l in o.get("stellenlokationen") or []]
            published = o.get("datumErsteVeroeffentlichung") or (o.get("veroeffentlichungszeitraum") or {}).get("von") or ""
            out.append(Offer(
                board=self.name, key=ref, url=DETAIL + urllib.parse.quote(ref), title=title, company=o.get("firma") or "",
                mode=_mode(o), locations=sorted({p for p in places if p}), worktime=_worktime(o), contracts=contracts,
                level=level or infer.level_from_text(title, LANGS), category=o.get("hauptberuf") or "",
                skills=list(o.get("alleBerufe") or []), pay_text=pay,
                published=dt.date.fromisoformat(published[:10]) if published else None,
                snippet=" · ".join(x for x in (o.get("vertragsdauer") == "BEFRISTET" and "befristet", o.get("externeURL")) if x)))
        return out
