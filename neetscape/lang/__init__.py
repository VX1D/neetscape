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
        "qualifier": [regex, ...],                     # optional: words that open a title's qualifier
        "gender":    [regex, ...],                     # optional: bracketed gender markers written as words
        "choice":    [regex, ...],                     # optional: words offering options ("hybrid or remote")
        "pay":       {"hour": [...], "day": [...], "week": [...], "year": [...], "month": [...],
                      "words": [...], "thousand": [...], "range": [...]},  # optional: pay text (neetscape/pay.py)
        "placeholder_companies": [str, ...],           # optional: names a posting uses to hide its employer
    }

Required keys: `mode`, `worktime`, `contract`, `level`, `function`, `domain` (`lang.FIELDS`; a value with no
words in a language may be left out, and a field may be `{}`) and `hints` (`lang.HINTS`; a missing key matches
nothing). Optional keys:
- `explicit`: per field and value, statements that settle the field over plain words (below);
- `qualifier`: words between spaces after which a job title's head ends and its qualifier begins
  (English "with", "for"; Polish "z", "dla"; German "mit"). Without them only punctuation splits a title:
  " - ", " | ", " / " and an opening bracket. The head names the job; a function or domain read from the
  qualifier ranks below one read from the head;
- `gender`: gender markers in words, matched inside brackets ("all genders", German "gn", "m/w/div").
  Bracketed lists of single letters ("(m/w/d)", "(k/m)", "(f/m/x)") are recognised in every language. A
  gender marker is removed before the split, so it never ends the head ("Sachbearbeiter (m/w/d) Buchhaltung").
- `choice`: words that offer options within a sentence (Polish "lub", English "or", German "oder"); a sentence
  naming hybrid work beside remote work with one of them offers remote (`infer.remote_proof`). " / " counts
  in every language;
- `pay`: how pay text names its period (`hour`, `day`, `week`, `year`; `month` only for words never used for
  another period), pay words next to an amount without a currency (`words`: gross, net, salary), the thousand
  suffix (`thousand`: "k", "tys.") and the word between two amounts (`range`: "to", "do", "bis"). These are
  read from every pack at once: units are unambiguous across languages and a board's text mixes them;
- `placeholder_companies`: company names that hide the employer ("confidential", "poufne"), dropped from a
  posting's company field (lower case, whole name).

A pack may also define `UI`, the labels of REPORT.html in its language (`neetscape/lang/en.py` lists every key):
plain strings with `{name}` placeholders, maps of value labels (`st`, `fd`, `md`, `wt`), and plurals as dicts keyed
by CLDR plural category (`{"one": "{n} oferta", "few": "{n} oferty", "many": "{n} ofert", "other": "{n} oferty"}`,
chosen in the page by `Intl.PluralRules`; `other` is required). The page offers every pack with `UI`; a key a
language leaves out falls back to English.

The keys of `function` and `domain` are language-neutral (`infer.FUNCTIONS`, `infer.DOMAINS`); a new language
maps its words onto them and needs no change outside its own module.

Patterns are case-insensitive. A pack is data, not an order: for one field the patterns of all active
languages are merged per value and strength, decided by the language-neutral rules in `infer.py`, so adding a language never reorders another language's
decisions. `explicit` holds statements that settle a field over plain words: explicit full remote
("100% zdalnie", "fully remote", "remote or hybrid" as a choice) and phrases a generic word of another
language would misread (German "Homeoffice möglich" is hybrid although it contains "home office").
"""
from __future__ import annotations

import importlib

FIELDS = ("mode", "worktime", "contract", "level", "function", "domain")  # read from free text (infer.ORDER)
DEFAULT = ("en",)  # free text whose country is unknown; callers pass the country's languages when they know it
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
