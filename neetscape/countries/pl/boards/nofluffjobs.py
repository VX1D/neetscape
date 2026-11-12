"""nofluffjobs — the public search API the site itself uses (plain HTTP POST, JSON); postings from its posting API.

    POST https://nofluffjobs.com/api/search/posting?salaryCurrency=PLN&salaryPeriod=month&...&pageFrom=N&pageTo=N
         {"rawSearch": "remote keyword=python", "page": N}

Verified live 2026-11-12 (2 disjoint pages, short last page, Kraków search, anywhere search, posting details):
- `rawSearch` is the site's search language: `remote` or a city slug (`warszawa`), `keyword=<word>`; a phrase with
  spaces is quoted (`keyword="agent ai"`, exact phrase), unquoted words are split into criteria;
- `pageFrom`/`pageTo` give disjoint pages of 50; the last is short, the next empty (the HTML listing grows by 20 per
  "load more" and repeats offers). No result cap: the anywhere search reports `totalPages` 52 and serves page 52,
  pages 53-54 are empty; `max_pages` (120, twice the board) is a safety stop. Remote is ~19 pages;
- `remote` returns fully remote offers only; there is no sort parameter (`sort`/`sortBy` are ignored);
- anywhere (no `remote`, no city), every posting comes once per place variant (`-remote`, `-krakow`, provinces; same
  `reference`, contiguous, identical fields): kept once per `reference`;
- salaries come converted to PLN per month (`salaryCurrency`, `salaryPeriod`; 168 h, 21 days), for the one contract
  type listed (the others only in the posting);
- `q=` is ignored by the API; it only makes page URLs (request records, `--record` files) differ per search;
- the offer page's JSON-LD holds only the company description; the posting API (`/api/posting/<ref>`) has the
  requirements, daily tasks, languages, every contract type and pay.
"""
from __future__ import annotations

import json

from .... import infer
from ....boards.base import Board, Caps, Request, register
from ....boards.pages import LEVEL_WORDS, amount, date_of, lowest_level, pay_range, places, slug, with_query
from ....model import Offer
from ....posting import html_to_text

API = "https://nofluffjobs.com/api/search/posting"
API_QUERY = {"salaryCurrency": "PLN", "salaryPeriod": "month", "region": "pl", "language": "pl-PL"}
POSTING_API = "https://nofluffjobs.com/api/posting/"
LANGUAGES = {"en": "English", "pl": "Polish", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "nl": "Dutch",
             "sv": "Swedish", "no": "Norwegian", "da": "Danish", "fi": "Finnish", "cs": "Czech", "sk": "Slovak", "uk": "Ukrainian",
             "ru": "Russian", "hu": "Hungarian", "pt": "Portuguese", "ro": "Romanian", "ja": "Japanese", "zh": "Chinese"}
CONTRACTS = {"zlecenie": "mandate_contract", "uz": "mandate_contract", "uod": "specific_task_contract"}  # -> infer.contract


def raw_search(r: Request) -> str:
    """`remote`, a city slug, or nothing (anywhere), then the keyword criterion."""
    where = slug(r.params["city"]) if r.params.get("city") else "remote" if r.params.get("remote") else ""
    if not r.keyword:
        return where
    kw = r.keyword.replace('"', " ").strip()
    return f"{where} keyword=".lstrip() + (f'"{kw}"' if " " in kw else kw)


def pay_text(salary: dict, kind: str) -> str:
    """The listed contract's range; "from 4850" (flexibleUpperBound) has no upper end."""
    if salary.get("from") is None:
        return ""
    return pay_range(kind, salary["from"], salary.get("to"), salary.get("currency") or "PLN",
                     str(salary.get("period") or "month").lower())


@register
class NoFluffJobs(Board):
    name = "nofluffjobs"
    caps = Caps(keywords=True, remote="filter", city=True, page_size=50, max_pages=120, transport="http")
    accept = "application/json"
    content_type = "application/infiniteSearch+json"

    def page_url(self, r: Request, page: int) -> str | None:
        return with_query(API, API_QUERY | {"pageFrom": page, "pageTo": page, "q": raw_search(r)})

    def post_body(self, r: Request, page: int) -> str | None:
        return json.dumps({"rawSearch": raw_search(r), "page": page})

    def parse(self, raw: str, r: Request) -> list[Offer]:
        data = json.loads(raw) if raw else {}
        if "postings" not in data:
            raise ValueError("no postings in the search API response (format change?)")
        out, seen = [], set()
        for p in data["postings"]:  # without a place, one entry per place variant of the same posting (`reference`)
            ref = p.get("reference") or p.get("url")
            if not p.get("url") or ref in seen:
                continue
            seen.add(ref)
            url = f"https://nofluffjobs.com/pl/job/{p['url']}"
            loc = p.get("location") or {}
            sal = p.get("salary") or {}
            kind = str(sal.get("type") or "").lower()
            skills = [t["value"] for t in (p.get("tiles") or {}).get("values") or [] if t.get("type") == "requirement"]
            dates = [d for d in (date_of(p.get("posted")), date_of(p.get("renewed"))) if d]
            out.append(Offer(
                board=self.name, key=url, url=url, title=(p.get("title") or "").strip(), company=(p.get("name") or "").strip(),
                mode="remote" if loc.get("fullyRemote") or p.get("fullyRemote") else infer.mode(str(loc.get("type") or "")),
                locations=places(x.get("city") for x in loc.get("places") or [] if (x.get("city") or "").lower() != "remote"),
                contracts=[infer.contract(CONTRACTS.get(kind, kind))] if kind else [],
                level=lowest_level(p.get("seniority"), LEVEL_WORDS), category=p.get("category") or "", skills=skills,
                pay_text=pay_text(sal, kind), published=max(dates) if dates else None,
                promoted=bool(p.get("highlighted") or p.get("topInSearch")), snippet=" ".join(skills)))
        return out

    @staticmethod
    def posting_url(url: str) -> str | None:
        """`neetscape details`: the posting API URL of an offer page."""
        head, sep, ref = url.partition("/job/")
        return POSTING_API + ref.split("?")[0] if sep and head.startswith("https://nofluffjobs.com") else None

    @staticmethod
    def posting_text(raw: str) -> tuple[str, dict]:
        """(text, {company, published}) of one posting API response."""
        d = json.loads(raw)
        req, specs, loc = d.get("requirements") or {}, d.get("specs") or {}, d.get("location") or {}
        sal = (d.get("essentials") or {}).get("originalSalary") or {}
        parts = [html_to_text((d.get("details") or {}).get("description") or "")]
        if req.get("description"):
            parts += ["Requirements:", html_to_text(req["description"])]
        for label, key in (("Must have", "musts"), ("Nice to have", "nices")):
            if req.get(key):
                parts.append(f"{label}: " + ", ".join(x.get("value", "") for x in req[key]))
        if req.get("languages"):
            parts.append("Languages: " + ", ".join(
                " ".join(filter(None, (LANGUAGES.get(x.get("code"), x.get("code")), x.get("level"))))
                + (" (required)" if x.get("type") == "MUST" else " (nice to have)")
                for x in req["languages"]))
        if specs.get("dailyTasks"):
            parts += ["Daily tasks:"] + [f"• {t}" for t in specs["dailyTasks"]]
        if loc.get("hybridDesc"):
            parts.append(f"Work mode: {loc['hybridDesc']}")
        for kind, t in (sal.get("types") or {}).items():
            rng = t.get("range") or []
            pay = f" {'-'.join(amount(v) for v in rng)} {sal.get('currency', '')}/{str(t.get('period') or '').lower()}" if rng else ""
            parts.append(f"Contract: {kind}{pay}")
        published = date_of(d.get("posted"))
        return "\n".join(p for p in parts if p), {"company": ((d.get("company") or {}).get("name") or "").strip(),
                                                  "published": published.isoformat() if published else ""}
