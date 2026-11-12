"""Board adapters. Importing this package registers every board in `REGISTRY`: the shared boards in this
directory (LinkedIn, serving any country, and the international feeds) and the boards of every country
package (`neetscape/countries/<cc>/boards/`, one module per board).

Shared code for adapters: `base` (interface, registration), `fetch` (HTTP, politeness), `pages` (parsing
helpers shared by adapters).

Groups usable in a profile's `boards` and in `--boards`: a country code (that country's boards plus the
boards serving any country, e.g. "pl", "de"), "intl" (international remote-only boards, opt-in) and "all".
"""
from . import feeds, linkedin  # registration side effects
from .base import REGISTRY, Board, Caps, Request, country_of, register
from .. import country as _country

__all__ = ["REGISTRY", "Board", "Caps", "Request", "country_of", "register", "groups", "expand",
           "feeds", "linkedin"]  # the board modules are imported to register them

_country.load_boards()


def groups() -> dict[str, list[str]]:
    """Group name -> board names. Computed on demand so that boards registered later are included."""
    out: dict[str, list[str]] = {}
    for code in _country.codes():
        out[code] = [n for n, b in REGISTRY.items() if country_of(b) in (code, "any") and b.caps.country]
    out["intl"] = [n for n, b in REGISTRY.items() if country_of(b) == "intl"]
    out["all"] = list(REGISTRY)
    return out


def expand(names: list[str]) -> list[str]:
    """Expand group names (country codes, "intl", "all") and keep order without duplicates."""
    g = groups()
    out: list[str] = []
    for n in names:
        for b in g.get(n, [n]):
            if b not in out:
                out.append(b)
    return out
