"""Language packs: vocabularies that map free text onto the model's values.

Each module `<code>.py` (ISO 639-1) defines

    VOCAB = {
        "mode":     {"remote": [regex, ...], "hybrid": [...], "onsite": [...]},
        "worktime": {"part_time": [...], "flexible": [...], "full_time": [...]},
        "contract": {"employment": [...], ...},            # canonical contract names (model.CONTRACTS)
        "level":    {"intern": [...], ...},
        "first":    {"mode": [(value, regex), ...]},     # optional: checked before the merged tables
        "hints":    {"fully_remote": [...], "hybrid": [...], "years": [...], "degree": [...],
                     "languages": [...], "fixed_term": [...],
                     "office": [...]},                  # required presence: client visits, business travel, office days
    }
    EXAMPLES = [(text, field, expected), ...]           # checked by tests/core/test_lang.py

Patterns are case-insensitive. For one field, the patterns of all active languages are merged per value
and values are tried in a fixed order (model order below), so adding a language never reorders another
language's decisions. `first` holds phrases that must win over the order: explicit full remote
("100% zdalnie", "fully remote", "remote or hybrid" as a choice) and phrases a generic word of another
language would misread (German "Homeoffice möglich" is hybrid although it contains "home office").
"""
from __future__ import annotations

import importlib

ORDER = {
    # hybrid before remote: "hybrid, 2 days remote" is hybrid; explicit full-remote phrases sit in `first`
    "mode": ("hybrid", "remote", "onsite"),
    "worktime": ("part_time", "flexible", "full_time"),
    "contract": ("employment", "b2b", "mandate", "specific_task", "internship", "freelance", "mini_job",
                 "working_student", "temp_agency"),
    "level": ("intern", "junior", "senior", "lead", "manager", "mid"),
}
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
