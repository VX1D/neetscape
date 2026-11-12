"""Core data model: a normalised offer, and the searches a profile is made of."""
from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

WORKTIMES = ("full_time", "part_time", "flexible", "unknown")
# one shared vocabulary for every country; local words map onto it (Country.contract_aliases)
CONTRACTS = ("employment", "b2b", "mandate", "specific_task", "internship", "freelance", "mini_job", "working_student",
             "temp_agency", "other")
CONTRACT_ALIASES = {"uop": "employment"}  # old names, accepted forever
LEVELS = ("intern", "junior", "mid", "senior", "lead", "manager", "unknown")
# job fields (lang ORDER["field"]); "other" when none matches
FIELDS = ("ai_automation", "security", "qa", "devops_cloud", "data", "erp_crm", "it_support", "it_admin", "software_dev",
          "product_project", "design", "ecommerce", "customer_service", "sales", "marketing", "hr", "finance", "legal",
          "retail", "admin_office", "logistics", "engineering", "manufacturing", "healthcare", "education", "hospitality")

# what a search's `unknown` policy may name per dimension: the fields a filter needs and an offer may lack
# (location, mode: `where`; remote_proof: no fetched posting; field/domain/function: nothing read from the title or
# category). "default" applies to every dimension not named.
UNKNOWN_DIMENSIONS = ("location", "mode", "remote_proof", "worktime", "pay", "date", "field", "domain", "function")
UNKNOWN_POLICIES = ("keep", "drop")


def canonical_contract(value: str) -> str:
    """The current name of a contract type (`uop` -> `employment`)."""
    return CONTRACT_ALIASES.get(value, value)


def parse_date(value) -> date | None:
    """An ISO date (`YYYY-MM-DD`, optionally followed by a time) as stored in the database, else None."""
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def days_old(value, today: date | None = None) -> int | None:
    """Days since a stored date (see `parse_date`), None when unknown."""
    d = parse_date(value)
    return ((today or date.today()) - d).days if d else None


def age_label(value) -> str:
    """A stored date as reports show it: "12d", "?" when unknown."""
    n = days_old(value)
    return "?" if n is None else f"{n}d"


# letters Unicode does not decompose into a base letter and a mark (NFKD keeps them whole), any language
_UNDECOMPOSED = str.maketrans({"ł": "l", "Ł": "L", "ß": "ss", "ẞ": "SS", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
                               "ħ": "h", "Ħ": "H", "ı": "i", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "þ": "th",
                               "Þ": "Th", "ð": "d", "Ð": "D"})


def fold(s: str) -> str:
    """Lowercase ASCII fold: 'Kraków' -> 'krakow', 'Øresund' -> 'oresund'. Used for city and company matching."""
    s = unicodedata.normalize("NFKD", (s or "").translate(_UNDECOMPOSED))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def norm(s: str) -> str:
    """`fold` without anything but letters and digits: 'Kraków, PL' -> 'krakowpl'."""
    return re.sub(r"[^a-z0-9]", "", fold(s))


_GENERIC_LEGAL = ("ltd", "gmbh", "inc", "llc", "group")


@functools.lru_cache(maxsize=1)
def _legal():
    """Legal-form words of every country (companies appear on boards of several countries)."""
    from .country import discover
    alts = [a for c in discover().values() for a in c.legal_suffixes]
    alts += [a for a in _GENERIC_LEGAL if a not in alts]
    return re.compile(r"\b(" + "|".join(alts) + r")\b")


def norm_company(s: str) -> str:
    """A company name for de-duplication: folded, without legal-form words, at most 16 characters."""
    return norm(_legal().sub("", fold(s)))[:16]



@dataclass
class Offer:
    """One offer as found on one board. `key` is stable per board (canonical URL or board id)."""
    board: str
    key: str
    url: str
    title: str
    company: str = ""
    mode: str = "unknown"
    locations: list[str] = field(default_factory=list)
    worktime: str = "unknown"
    contracts: list[str] = field(default_factory=list)
    level: str = "unknown"
    category: str = ""            # the board's own role or job category, verbatim
    industry: str = ""            # the employer's industry as the board names it, verbatim: context, never a domain
    skills: list[str] = field(default_factory=list)
    pay_text: str = ""            # as published
    pay_period: str = ""          # "project" when the amount is per project (not normalised)
    pay_min: int | None = None    # per month in the database currency (the profile country's), from the pay text
    pay_max: int | None = None
    published: date | None = None
    promoted: bool = False        # sponsored listings float above newer ones; ignored by incremental stops
    snippet: str = ""             # card text from the result page
    description: str = ""         # full text when the source ships it (feeds)
    facts: dict | None = None     # the adapter's structured values (infer.board_facts); None: its current values
    evidence: dict = field(default_factory=dict)  # derived column -> [source, phrase]; job_domains -> {domain: [...]}
    country: str = ""             # the country the offer's text is in (its language)

    @property
    def title_norm(self) -> str:
        return norm(self.title)[:60]

    def text(self) -> str:
        """Everything a filter may look at besides the title."""
        return " ".join([self.title, self.company, self.category, self.industry, " ".join(self.skills), self.pay_text,
                         self.snippet, " ".join(self.locations)])


@dataclass(frozen=True)
class Where:
    remote: bool = False
    city: str | None = None
    radius_km: int | None = None
    country: str = "pl"           # the job market searched (a country code); boards of other countries skip the search

    def describe(self) -> str:
        """'Kraków +30km or remote (pl)', 'remote (pl)', 'anywhere (de)'."""
        if not self.city:
            return f"{'remote' if self.remote else 'anywhere'} ({self.country})"
        radius = f" +{self.radius_km}km" if self.radius_km else ""
        return f"{self.city}{radius}{' or remote' if self.remote else ''} ({self.country})"


@dataclass(frozen=True)
class Search:
    """One search of a profile. Conditions inside a search are ANDed; a profile is the union of its searches."""
    id: str
    label: str
    where: Where
    keywords: tuple[str, ...] | None            # None = everything ("what": "all")
    keywords_for: dict = field(default_factory=dict, hash=False, compare=False)  # board -> keywords override
    worktime: frozenset = frozenset()           # allowed worktimes; empty = any
    contracts: frozenset = frozenset()          # allowed contracts; empty = any (matches if worktime OR contract fits)
    levels_exclude: frozenset = frozenset()
    fields: frozenset = frozenset()             # allowed job fields (FIELDS); empty = any
    fields_exclude: frozenset = frozenset()
    domains: frozenset = frozenset()            # job domains (infer.DOMAINS); passes when any of the offer's matches
    functions: frozenset = frozenset()          # allowed job functions (infer.FUNCTIONS); empty = any
    functions_exclude: frozenset = frozenset()
    pay_min: int | None = None                  # profile currency, in `pay_period` units
    pay_period: str = "month"                   # "month" or "hour"
    require_pay: bool = False
    max_age_days: int | None = None
    title_include: tuple = ()                   # compiled regexes; at least one must match when given
    title_exclude: tuple = ()
    text_exclude: tuple = ()
    category_include: tuple = ()
    unknown: str = "keep"                       # keep or drop offers whose filtered field is unknown (the default)
    unknown_for: tuple = ()                     # ((dimension, policy), ...): UNKNOWN_DIMENSIONS overriding `unknown`
    boost: int = 0
    remote_proof: bool = False                  # the fetched posting must state fully remote work, with no hybrid or required presence

    def unknown_policy(self, dimension: str) -> str:
        """"keep" or "drop" for an offer lacking the field of `dimension` (UNKNOWN_DIMENSIONS)."""
        return dict(self.unknown_for).get(dimension, self.unknown)

    def keywords_on(self, board: str) -> tuple[str, ...] | None:
        """The phrases sent to `board` (its `keywords_for` override, else `keywords`); None = everything."""
        if self.keywords is None:
            return None
        return tuple(self.keywords_for.get(board, self.keywords))
