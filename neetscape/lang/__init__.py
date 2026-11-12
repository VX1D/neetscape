"""Language packs: vocabularies that map free text onto the model's values.

Each module `<code>.py` (ISO 639-1) defines

    VOCAB = {
        "mode":     {"remote": [regex, ...], "hybrid": [...], "onsite": [...]},
        "worktime": {"part_time": [...], "flexible": [...], "full_time": [...]},
        "contract": {"employment": [...], ...},            # canonical contract names (model.CONTRACTS)
        "level":    {"intern": [...], ...},
        "function": {"support": [...], "develop": [...], ...},   # what a job title does (infer.FUNCTIONS)
        "domain":   {"it": [...], "logistics": [...], ...},      # what it is about
        "explicit": {"mode": {"remote": [...]}},          # optional: statements that settle a field
        "hints":    {"fully_remote": [...], "hybrid": [...], "years": [...], "degree": [...],
                     "languages": [...], "fixed_term": [...],
                     "office": [...]},                  # required presence: client visits, business travel, office days
    }

Patterns are case-insensitive. A pack is data, not an order: for one field the patterns of all active
languages are merged per value and strength, decided by the language-neutral rules in `infer.py`, so adding a language never reorders another language's
decisions. `explicit` holds statements that settle a field over plain words: explicit full remote
("100% zdalnie", "fully remote", "remote or hybrid" as a choice) and phrases a generic word of another
language would misread (German "Homeoffice möglich" is hybrid although it contains "home office").
"""
from __future__ import annotations

import importlib

FIELDS = ("mode", "worktime", "contract", "level", "function", "domain")  # read from free text (infer.ORDER)
DEFAULT = ("pl", "en")  # free text of unknown origin (historical: the tool started with Polish boards)
HINTS = ("fully_remote", "hybrid", "years", "degree", "languages", "fixed_term", "office")


def with_english(languages) -> tuple:
    """English is read in every country, after the local languages."""
    langs = tuple(languages)
    return langs + (() if "en" in langs else ("en",))


def pack(code: str):
    return importlib.import_module(f"neetscape.lang.{code}")


def available() -> list[str]:
    import pkgutil
    from neetscape import lang
    return sorted(m.name for m in pkgutil.iter_modules(lang.__path__))
