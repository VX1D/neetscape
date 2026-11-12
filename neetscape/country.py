"""Countries: currency, languages, places and contract vocabulary of one job market.

A country is a package `neetscape/countries/<code>/` whose `__init__.py` defines `COUNTRY = Country(...)`
and nothing else (it must not import boards). Its boards live in `neetscape/countries/<code>/boards/`
(or a `boards.py` module) and its profile presets in `presets/`. Adding a country means adding that
directory; nothing central has to change.

Besides real countries, a board may declare the pseudo-countries `any` (serves every country through its
own location handling, e.g. LinkedIn) or `intl` (international, remote-only, opt-in).
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field

from .pay import DAYS_PER_MONTH, HOURS_PER_MONTH

PSEUDO = ("any", "intl")


@dataclass(frozen=True)
class Country:
    code: str                              # ISO 3166-1 alpha-2, lower case: "pl", "de"
    name: str
    currency: str                          # ISO 4217: amounts in a profile and in the database use it
    fx: dict                               # units of `currency` per unit of another currency
    languages: tuple                       # lang packs (neetscape/lang/<code>.py) for free text; English is always added last
    hours_per_month: int = HOURS_PER_MONTH  # converts hourly rates to monthly pay
    days_per_month: int = DAYS_PER_MONTH    # converts daily rates
    linkedin_location: str = ""            # LinkedIn free-text location for the whole country ("Poland", "Germany")
    place_names: tuple = ()                # how the country appears at the end of place names ("Polska", "Poland")
    city_aliases: dict = field(default_factory=dict)  # folded city name -> other folded spellings ("munchen": ("munich",))
    legal_suffixes: tuple = ()             # regex alternatives stripped from company names for de-duplication
    contracts: tuple = ()                  # canonical contract types that exist in this market
    contract_aliases: dict = field(default_factory=dict)  # local word (lower case) -> canonical contract
    default_boards: tuple = ()             # boards (or groups) used when a profile names none

    def aliases(self, city: str) -> set[str]:
        """Folded spellings of a city: itself and its aliases (looked up in both directions)."""
        from .model import fold
        c = fold(city)
        out = {c}
        for k, v in self.city_aliases.items():
            if c == k or c in v:
                out |= {k, *v}
        return out


COUNTRIES: dict[str, Country] = {}
_discovered = False


def register(c: Country) -> Country:
    """Add a country to the registry (`discover` does it for every country package)."""
    COUNTRIES[c.code] = c
    return c


def _packages() -> list[str]:
    """Codes of the country packages under `neetscape/countries/`."""
    from . import countries
    return [m.name for m in pkgutil.iter_modules(countries.__path__) if m.ispkg]


def discover() -> dict[str, Country]:
    """Import every `neetscape.countries.<code>` package (cheap: no boards) and return the registry."""
    global _discovered
    if not _discovered:
        _discovered = True
        for code in _packages():
            mod = importlib.import_module(f"neetscape.countries.{code}")
            c = getattr(mod, "COUNTRY", None)
            if c is not None:
                register(c)
    return COUNTRIES


def load_boards() -> None:
    """Import the boards of every country (registers them). Called by `neetscape.boards` after its own boards."""
    for code in _packages():
        name = f"neetscape.countries.{code}.boards"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as e:
            if e.name != name:
                raise


def get(code: str) -> Country:
    """The country `code`; KeyError naming the available ones when it does not exist."""
    discover()
    try:
        return COUNTRIES[code]
    except KeyError:
        raise KeyError(f"unknown country {code!r}; available: {sorted(COUNTRIES)}") from None


def codes() -> list[str]:
    return sorted(discover())


def text_country(board_country: str, fallback: str) -> str:
    """Country whose language and currency a board's text is in: the board's own, or `fallback` (the
    searched or the profile's country) for boards serving any country."""
    return board_country if board_country not in ("", "any") else fallback


def languages(code: str | None) -> tuple:
    """Lang packs for free text of a board or search in `code` (a country or a pseudo-country)."""
    from . import lang
    if code in (None, "", "any"):
        return lang.DEFAULT  # callers pass the search's country when they know it
    if code == "intl":
        return ("en",)
    return lang.with_english(get(code).languages)


def currency(code: str | None) -> str | None:
    """Currency assumed for amounts without a currency sign, or None when unknown."""
    if code in (None, "", "any", "intl"):
        return None
    return get(code).currency
