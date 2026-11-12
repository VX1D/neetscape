"""Board adapter interface.

A board declares what it can filter server-side (`Caps`), turns a `Search` into `Request`s, builds page
URLs and parses raw pages into `Offer`s. Parsing is a pure function of the raw page so it can be tested
offline on recorded fixtures. Whatever is not pushed to the board is still checked locally by
`evaluate`, so capabilities only affect crawl cost, never results.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import ClassVar

from ..model import Offer, Search, Where
from ..posting import parse_posting



def request_key(board: str, keyword: str | None, params: dict) -> str:
    """Identity of a request across runs: a hash of its board, phrase and parameters."""
    raw = json.dumps([board, keyword, sorted(params.items())], ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]

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
    huge_unfiltered: bool = False  # listing everything is too big: needs keywords, a city or the server-side remote filter
    local_all: bool = False      # the whole board is one cheap download: any search can be served by local filtering
    whole_listing: bool = False  # one response holds the request's whole listing (feeds): fetching it completes the request
    result_cap: int = 0          # most results one query shows (OLX 1000); above it the crawler asks `split()`, then
                                 # `newest()` (0 = none). Without `total()` the crawler probes the cap's last page
                                 # (`max_pages`, or result_cap / page_size) right after page 1: offers there = capped
    empty_retries: int = 0       # fetch an empty page again this many times before taking it as the end (flaky boards)
    country: str = ""            # "pl", "de", ...; "any" (serves every country, gets `params["country"]`); "intl" (opt-in,
                                 # international). Empty: derived on registration from the module (see `register`)
    transport: str = "http"      # "http" (plain HTTP, GET or POST) or "browser_fetch" (same-origin fetch in a tab)
    origin: str = ""             # browser_fetch: page to open before the same-origin fetches


TRANSPORTS = ("http", "browser_fetch")


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


def with_params(r: Request, **params) -> Request:
    """A copy of `r` with `params` added to (or replacing some of) its parameters."""
    return replace(r, params={**r.params, **params})


def narrowed(r: Request, param: str, values) -> list[Request]:
    """One copy of `r` per value, with `params[param]` set to it: the sub-requests of a `Board.split()`."""
    return [with_params(r, **{param: v}) for v in values]


class Board:
    name: ClassVar[str]
    caps: ClassVar[Caps]
    accept: ClassVar[str] = "*/*"             # http: Accept header
    headers: ClassVar[dict] = {}              # http: extra request headers (e.g. a public API key)
    content_type: ClassVar[str] = ""          # http: Content-Type of the `post_body` of a POST search
    min_interval: ClassVar[dict] = {}         # host -> seconds between requests, for boards that throttle hard
    posting_date_is_first: ClassVar[bool] = False  # the posting's date (JSON-LD datePosted) is the first publication,
    #                                               earlier than the listing's refresh date: `details` replaces it
    #                                               and later sightings of the card keep it
    posting_selector: ClassVar[str] = ""      # CSS selector of the posting body on the rendered offer page, used
    #                                           when `posting()` finds no text; empty: never fall back to rendering

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
            if caps.huge_unfiltered and "city" not in pushed and not (caps.remote == "filter" and "remote" in pushed):
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

    def posting(self, page: str) -> dict:
        """Posting fields from the source of an offer page: `description` (plain text) plus whatever JSON-LD
        ships (company, published, salary, ...), schema.org JobPosting. A `posting_body()` replaces the
        description (`source` "board")."""
        meta = parse_posting(page)
        if body := self.posting_body(page):
            meta["description"], meta["source"] = body, "board"
        return meta

    def posting_facts(self, meta: dict) -> dict:
        """Canonical values (`level`, `worktime`, `contracts`) read from the structured fields of a stored posting's
        meta (what `posting()` returned), passed to `infer.derive` as source `posting_struct`. A value may be a
        (value, phrase) pair; the phrase is the evidence `show` prints. Default: none."""
        return {}

    def posting_body(self, page: str) -> str:
        """Boards whose JSON-LD lacks the posting body (or that have none): the body read from the offer page's
        embedded data, as plain text; '' when absent. Never page chrome."""
        return ""

    def total(self, raw: str, r: Request) -> int | None:
        """Boards with a `result_cap`: how many results the request matches, read from its first page. None: the
        board reports no total, and the crawler detects the cap at its end (see `Caps.result_cap`)."""
        return None

    def split(self, raw: str, r: Request, seen: tuple = ()) -> list[Request]:
        """Boards with a `result_cap`: narrower requests that together cover `r` (e.g. one per category listed on
        its first page), each expected to stay under the cap; [] when the request cannot be narrowed. `raw` is the
        first page when `total()` showed the cap; without a total it is page 1 too, and `seen`
        holds the offers of page 1 and of the end probe (boards without `total()` must accept it)."""
        return []

    def newest(self, r: Request) -> tuple[Request, str] | None:
        """Boards with a `result_cap`: `r` limited to the board's newest window, one step narrower than the window `r`
        already has (e.g. the last 7 days, then the last 24 hours), with a label for the stop reason ("7 days"); None
        when there is none. The crawler uses it for a capped request that `split()` cannot narrow, and never counts
        a windowed request as complete (offers outside the window are not gone)."""
        return None

    def post_body(self, r: Request, page: int) -> str | None:
        """http boards whose search is a POST: the request body for this page (sent as `content_type`)."""
        return None


REGISTRY: dict[str, Board] = {}


def min_intervals(profile_intervals: dict | None = None) -> dict:
    """Per-host request gaps: the boards' own minimums, overridden by the profile's `politeness.min_interval_s`."""
    out = {host: s for b in REGISTRY.values() for host, s in b.min_interval.items()}
    return out | (profile_intervals or {})


def module_country(module: str) -> str:
    """Country of a board from where it is defined: neetscape.countries.<cc>.* -> cc; elsewhere ''."""
    parts = module.split(".")
    return parts[2] if parts[:2] == ["neetscape", "countries"] and len(parts) > 2 else ""


def register(cls):
    """Class decorator: add the board to REGISTRY. A board without `caps.country` gets its country from its
    module (`neetscape/countries/<cc>/boards/`); shared boards in `neetscape/boards/` must declare "any" or "intl"."""
    if cls.caps.transport not in TRANSPORTS:
        raise ValueError(f"board {cls.name!r}: unknown transport {cls.caps.transport!r} (one of {TRANSPORTS})")
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
