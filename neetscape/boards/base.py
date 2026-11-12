"""Board adapter interface.

A board declares what it can filter server-side (`Caps`), turns a `Search` into `Request`s, builds page
URLs and parses raw pages into `Offer`s. Parsing is a pure function of the raw page so it can be tested
offline on recorded fixtures. Whatever is not pushed to the board is still checked locally by
`evaluate`, so capabilities only affect crawl cost, never results.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import ClassVar

from ..model import Offer, Search, Where
from ..store import request_key


@dataclass(frozen=True)
class Caps:
    keywords: bool = False       # server-side keyword search
    all: bool = True             # can list everything (no keyword)
    remote: str = "no"           # "filter" (server-side), "always" (board is remote-only), "no"
    city: bool = False
    radius: bool = False
    worktime: bool = False       # server-side part-time filter
    sort_newest: bool = False    # results can be ordered newest first (enables incremental stops)
    page_size: int = 0           # 0 = unknown / variable
    max_pages: int = 1
    huge_unfiltered: bool = False  # listing everything without a filter is too big: needs keywords or a city
    local_all: bool = False      # the whole board is one cheap download: any search can be served by local filtering
    country: str = ""            # "pl", "de", ...; "any" (serves every country, gets `params["country"]`); "intl" (opt-in,
                                 # international). Empty: derived on registration from the module (see `register`)
    transport: str = "http"     # "http", "browser_fetch" (same-origin fetch in a tab), "browser_render" (rendered cards)
    origin: str = ""             # page to open before same-origin fetches


@dataclass(frozen=True)
class Request:
    board: str
    search_id: str
    keyword: str | None
    params: dict = field(default_factory=dict, hash=False)   # what is actually sent (besides the keyword)
    pushed: frozenset = frozenset()                          # conditions the board applies: remote, city, worktime

    @property
    def key(self) -> str:
        return request_key(self.board, self.keyword, self.params)


class Board:
    name: ClassVar[str]
    caps: ClassVar[Caps]
    link_pattern: ClassVar[str] = ""          # browser_render boards: which links are offers

    def requests(self, s: Search) -> tuple[list[Request], list[str]]:
        """Requests serving this search, plus warnings about what cannot be served. Default implementation
        pushes remote/city/worktime when supported and fans out over keywords. Boards of another country than
        the searched one serve nothing; boards serving any country get the searched country in `params`."""
        target = s.where.country
        if self.caps.country not in ("", "any", "intl", target):
            return [], [f"{self.name}: a board for {self.caps.country}; skipped for '{s.id}' (searches {target})"]
        if s.where.city and s.where.remote:  # "city or remote": both listings
            city_reqs, w1 = self.requests(replace(s, where=replace(s.where, remote=False)))
            remote_reqs, w2 = self.requests(replace(s, where=Where(remote=True, country=target)))
            return city_reqs + remote_reqs, w1 + w2
        caps, warnings, params, pushed = self.caps, [], {}, set()
        if caps.country == "any":  # e.g. LinkedIn: the board resolves the country's location itself
            params["country"] = target
        if s.where.city:
            if caps.local_all:
                return [Request(self.name, s.id, None, {}, frozenset())], []
            if not caps.city:
                return [], [f"{self.name}: no city search; skipped for '{s.id}'"]
            params["city"] = s.where.city
            pushed.add("city")
            if s.where.radius_km and caps.radius:
                params["radius_km"] = s.where.radius_km
        elif s.where.remote:
            if caps.remote == "filter":
                params["remote"] = True
                pushed.add("remote")
            elif caps.remote == "always":
                pushed.add("remote")
        if s.worktime and caps.worktime and s.worktime <= {"part_time", "flexible"}:
            params["part_time"] = True
            pushed.add("worktime")
        if caps.sort_newest:
            params["sort"] = "newest"
        kws = s.keywords_on(self.name)
        if kws is None or not caps.keywords:  # one unfiltered-by-keyword listing
            if caps.huge_unfiltered and "city" not in pushed:
                return [], [f"{self.name}: listing everything is too large without keywords or a city; skipped for '{s.id}'"]
            if kws is not None:
                warnings.append(f"{self.name}: no keyword search; fetching all and filtering locally for '{s.id}'")
            return [Request(self.name, s.id, None, params, frozenset(pushed))], warnings
        return [Request(self.name, s.id, kw, params, frozenset(pushed | {"keyword"})) for kw in kws], warnings

    def page_url(self, r: Request, page: int) -> str | None:
        raise NotImplementedError

    def parse(self, raw: str, r: Request) -> list[Offer]:
        raise NotImplementedError

    def fetch_js(self) -> str | None:
        """browser_fetch boards: optional JS `(text)=>string` applied in the page to shrink the response."""
        return None


REGISTRY: dict[str, Board] = {}


def module_country(module: str) -> str:
    """Country of a board from where it is defined: neetscape.countries.<cc>.* -> cc; elsewhere ''."""
    parts = module.split(".")
    return parts[2] if parts[:2] == ["neetscape", "countries"] and len(parts) > 2 else ""


def register(cls):
    """Class decorator: add the board to REGISTRY. A board without `caps.country` gets its country from its
    module (`neetscape/countries/<cc>/boards/`); shared boards in `neetscape/boards/` must declare "any" or "intl"."""
    if not cls.caps.country:
        code = module_country(cls.__module__)
        if not code:
            raise ValueError(f"board {cls.name!r} in {cls.__module__}: set caps.country (\"any\" or \"intl\") or define it "
                             "in neetscape/countries/<cc>/boards/")
        cls.caps = replace(cls.caps, country=code)
    REGISTRY[cls.name] = cls()
    return cls


def country_of(board) -> str:
    """The board's country; "any" for boards that declare none (test doubles)."""
    return board.caps.country or "any"


def accept_language(board) -> str:
    """Accept-Language for a board's own country ("de,en"); English for boards serving any country, whose
    markup may depend on it (LinkedIn's), and for international ones."""
    from ..country import languages
    code = board.caps.country
    return ",".join(languages(code)) if code not in ("", "any", "intl") else "en"
