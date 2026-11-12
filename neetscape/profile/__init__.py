"""Search profile (version 2).

A profile is a union of searches. Each search says where to look (remote and/or a city), what to look
for (keywords or "all") and which hard filters apply. `defaults` are merged into every search. Ranking
rules only order results; they never drop anything.

    {
      "version": 2,
      "country": "pl",
      "boards": ["pl"],
      "defaults": {"max_age_days": 30},
      "searches": [{"id": "remote-all", "where": "remote", "what": "all"}],
      "rank": {"rules": [], "sort": ["new", "published"]},
      "review": {"mode": "listing"}
    }

`country` (default "pl") sets the currency of every amount (pay floors, `fx`) and of the database, the
default boards and the language of the text; a search can target another country with
`"where": {"remote": true, "country": "de"}` (its boards must be listed in `boards`).

See profile/schema.json for every field, and countries/<cc>/presets/ then profile/presets/ for ready-made
profiles.
"""
from __future__ import annotations

import copy
import functools
import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .. import country as countries
from ..boards import REGISTRY, expand
from ..country import Country
from ..model import CONTRACT_ALIASES, CONTRACTS, FIELDS, LEVELS, WORKTIMES, Search, Where

PRESETS = ("focused", "broad", "local", "side")  # shared presets; a country may add or override some
SORT_KEYS = ("score", "new", "pay", "published")
_HERE = resources.files(__name__)
_SCHEMA = _HERE / "schema.json"


class ProfileError(ValueError):
    """A profile that does not validate; the message names the offending key."""


@dataclass
class Profile:
    """A validated profile: the searches and settings the tool reads, plus the raw JSON (`raw`)."""

    raw: dict
    searches: list[Search]
    boards: list[str]
    rules: list[dict] = field(default_factory=list)
    tags: list[dict] = field(default_factory=list)
    sort: list[str] = field(default_factory=lambda: ["score", "new", "published"])
    review_mode: str = "auto"
    details_top: int = 60
    min_score: int = 0
    min_interval: dict = field(default_factory=dict)
    retries: int = 2
    blacklist: dict = field(default_factory=dict)   # companies/urls/text: compiled regexes; action: drop|flag
    fx: dict = field(default_factory=lambda: dict(countries.get("pl").fx))
    country: Country = field(default_factory=lambda: countries.get("pl"))

    @property
    def currency(self) -> str:
        return self.country.currency

    def search(self, sid: str) -> Search:
        return next(s for s in self.searches if s.id == sid)


def _rx(where: str, patterns) -> tuple:
    """A pattern or a list of patterns, compiled case-insensitively."""
    if isinstance(patterns, str):
        patterns = [patterns]
    out = []
    for i, p in enumerate(patterns or []):
        try:
            out.append(re.compile(p, re.I))
        except re.error as e:
            raise ProfileError(f"{where}[{i}]: invalid regex {p!r}: {e}") from None
    return tuple(out)


def _choice(where: str, values, allowed, aliases: dict | None = None) -> frozenset:
    """`values` (aliases mapped) as a set, each checked to be one of `allowed`."""
    values = [(aliases or {}).get(v, v) for v in values or []]
    bad = set(values) - set(allowed)
    if bad:
        raise ProfileError(f"{where}: unknown values {sorted(bad)}; allowed: {list(allowed)}")
    return frozenset(values)


def _where(where: str, value, home: str = "pl") -> Where:
    """A search's `where`: "remote", "anywhere", a city object or a remote/country object."""
    if value in ("remote", None):
        return Where(remote=True, country=home)
    if value == "anywhere":
        return Where(country=home)
    if isinstance(value, dict):
        cc = value.get("country", home)
        if cc not in countries.codes():
            raise ProfileError(f"{where}.country: unknown country {cc!r}; available: {countries.codes()}")
        if value.get("city"):
            return Where(remote=bool(value.get("or_remote")), city=value["city"], radius_km=value.get("radius_km"), country=cc)
        if "or_remote" not in value and "radius_km" not in value:
            return Where(remote=bool(value.get("remote", True)), country=cc)
    raise ProfileError(f"{where}: 'where' must be \"remote\", \"anywhere\", {{\"city\": ..., \"radius_km\": ..., "
                       f"\"or_remote\": bool, \"country\": cc}} or {{\"remote\": bool, \"country\": cc}}")


def build_search(d: dict, defaults: dict, n: int, home: Country | None = None) -> Search:
    """Search number `n` of a profile (`d` over `defaults`), checked against the vocabularies of `home`."""
    home = home or countries.get("pl")
    s = {**defaults, **d}
    sid = s.get("id") or f"search{n + 1}"
    at = f"searches[{sid}]"
    what = s.get("what", "all")
    if what != "all" and not (isinstance(what, list) and what and all(isinstance(w, str) for w in what)):
        raise ProfileError(f"{at}.what must be \"all\" or a non-empty list of phrases")
    pay = s.get("pay") or {}
    if pay and pay.get("per", "month") not in ("month", "hour"):
        raise ProfileError(f"{at}.pay.per must be 'month' or 'hour'")
    if s.get("unknown", "keep") not in ("keep", "drop"):
        raise ProfileError(f"{at}.unknown must be 'keep' or 'drop'")

    def rx(key: str) -> tuple:
        return _rx(f"{at}.{key}", s.get(key))

    def choice(key: str, allowed, aliases: dict | None = None) -> frozenset:
        return _choice(f"{at}.{key}", s.get(key), allowed, aliases)

    return Search(
        id=sid, label=s.get("label", sid), where=_where(at + ".where", s.get("where", "remote"), home.code),
        keywords=None if what == "all" else tuple(what),
        keywords_for={k: tuple(v) for k, v in (s.get("keywords_for") or {}).items()},
        worktime=choice("worktime", WORKTIMES),
        contracts=choice("contracts", CONTRACTS, {**home.contract_aliases, **CONTRACT_ALIASES}),
        levels_exclude=choice("levels_exclude", LEVELS), fields=choice("fields", FIELDS),
        fields_exclude=choice("fields_exclude", FIELDS),
        pay_min=pay.get("min"), pay_period=pay.get("per", "month"), require_pay=bool(pay.get("required")),
        max_age_days=s.get("max_age_days"), title_include=rx("title_include"), title_exclude=rx("title_exclude"),
        text_exclude=rx("text_exclude"), category_include=rx("category_include"),
        unknown=s.get("unknown", "keep"), boost=int(s.get("boost", 0)), remote_proof=bool(s.get("remote_proof", False)))


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float),
          "null": type(None)}


def _is(value, json_type: str) -> bool:
    if json_type in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES.get(json_type, object))


def _check_shape(value, node: dict, at: str) -> None:
    """Keys, required keys and JSON types against profile/schema.json (value ranges are checked when building)."""
    if "oneOf" in node:
        node = next((n for n in node["oneOf"] if n.get("type") == "object"), {}) if isinstance(value, dict) else {}
    want = node.get("type")
    want = [want] if isinstance(want, str) else want or []
    if want and not any(_is(value, t) for t in want):
        raise ProfileError(f"{at}: must be {' or '.join(want)}, not {json.dumps(value, ensure_ascii=False)}")
    if isinstance(value, dict):
        props, extra = node.get("properties", {}), node.get("additionalProperties", True)
        unknown = sorted(set(value) - set(props)) if extra is False else []
        if unknown:
            raise ProfileError(f"{at}: unknown key(s) {unknown}; allowed: {sorted(props)}")
        missing = [k for k in node.get("required", []) if k not in value]
        if missing:
            raise ProfileError(f"{at}: missing required {missing}")
        for k, v in value.items():
            sub = props.get(k, extra if isinstance(extra, dict) else {})
            _check_shape(v, sub, f"{at}.{k}" if at else k)
    elif isinstance(value, list) and "items" in node:
        for i, v in enumerate(value):
            _check_shape(v, node["items"], f"{at}[{i}]")


def validate(raw: dict) -> Profile:
    """Check a profile's JSON and build the `Profile`; raises `ProfileError`."""
    raw = copy.deepcopy(raw)
    if raw.get("version") != 2:
        raise ProfileError("profile 'version' must be 2 (see `neetscape init`)")
    _check_shape(raw, _schema(), "")
    if not raw.get("searches"):
        raise ProfileError("profile needs at least one entry in 'searches'")
    code = raw.get("country", "pl")
    if code not in countries.codes():
        raise ProfileError(f"unknown country {code!r}; available: {countries.codes()}")
    home = countries.get(code)
    defaults = raw.get("defaults") or {}
    searches = [build_search(d, defaults, i, home) for i, d in enumerate(raw["searches"])]
    ids = [s.id for s in searches]
    if len(set(ids)) != len(ids):
        raise ProfileError(f"search ids must be unique: {ids}")
    targets = [code] + [s.where.country for s in searches if s.where.country != code]
    default_boards = [b for cc in dict.fromkeys(targets) for b in countries.get(cc).default_boards]
    boards = expand(raw.get("boards") or default_boards)
    unknown = set(boards) - set(REGISTRY)
    if unknown:
        raise ProfileError(f"unknown boards {sorted(unknown)}; available: {list(REGISTRY)} or groups "
                           f"{'/'.join(countries.codes())}/intl/all")
    rank = raw.get("rank") or {}
    rules, tags = _rules(rank.get("rules") or []), _tags(rank.get("tags") or [])
    sort = rank.get("sort") or (["score", "new", "published"] if rules else ["new", "published"])
    if set(sort) - set(SORT_KEYS):
        raise ProfileError(f"rank.sort keys must be from {SORT_KEYS}")
    review = raw.get("review") or {}
    if review.get("mode", "auto") not in ("auto", "listing"):
        raise ProfileError("review.mode must be 'auto' or 'listing'")
    pol = raw.get("politeness") or {}
    return Profile(raw=raw, searches=searches, boards=boards, rules=rules, tags=tags, sort=sort,
                   review_mode=review.get("mode", "auto" if rules else "listing"),
                   details_top=int(review.get("details_top", 60)), min_score=int(review.get("min_score", 0)),
                   min_interval=pol.get("min_interval_s") or {}, retries=int(pol.get("retries", 2)),
                   blacklist=_blacklist(raw.get("blacklist") or {}), fx={**home.fx, **(raw.get("fx") or {})}, country=home)


def _rules(rules: list[dict]) -> list[dict]:
    """`rank.rules` with compiled patterns: {rx, weight, field, label}."""
    out = []
    for i, r in enumerate(rules):
        if "pattern" not in r or "weight" not in r:
            raise ProfileError(f"rank.rules[{i}] needs pattern and weight")
        if r.get("field", "title") not in ("title", "any"):
            raise ProfileError(f"rank.rules[{i}].field must be 'title' or 'any'")
        out.append({"rx": _rx(f"rank.rules[{i}]", r["pattern"])[0], "weight": int(r["weight"]),
                    "field": r.get("field", "title"), "label": r.get("label", r["pattern"][:40])})
    return out


def _tags(tags: list[dict]) -> list[dict]:
    """`rank.tags` with compiled patterns: {id, label, rx}."""
    return [{"id": t["id"], "label": t.get("label", t["id"]), "rx": _rx(f"rank.tags[{t['id']}]", t["pattern"])[0]}
            for t in tags]


def _blacklist(bl: dict) -> dict:
    """The blacklist with compiled patterns per key and its action."""
    action = bl.get("action", "drop")
    if action not in ("drop", "flag"):
        raise ProfileError("blacklist.action must be 'drop' or 'flag'")
    return {k: _rx(f"blacklist.{k}", bl.get(k)) for k in ("companies", "urls", "text")} | {"action": action}


def load(path: str | Path) -> Profile:
    """Read and validate a profile file."""
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise ProfileError(f"{path} not found; create one with `neetscape init [--country CC] --preset <focused|broad|local|side>`") from None
    except json.JSONDecodeError as e:
        raise ProfileError(f"{path}: invalid JSON: {e}") from None
    return validate(raw)


def _preset_dirs(country: str):
    own = resources.files("neetscape.countries").joinpath(country, "presets")
    return [own, _HERE / "presets"]


def presets(country: str = "pl") -> list[str]:
    """Preset names available for a country: its own (countries/<cc>/presets/) and the shared ones."""
    names = []
    for d in _preset_dirs(country):
        if d.is_dir():
            names += [f.name.removesuffix(".json") for f in d.iterdir() if f.name.endswith(".json")]
    return sorted(set(names), key=lambda n: (PRESETS.index(n) if n in PRESETS else len(PRESETS), n))


def preset(name: str, country: str = "pl") -> dict:
    """A preset for `country`: countries/<cc>/presets/<name>.json, else the shared profile/presets/<name>.json."""
    for d in _preset_dirs(country):
        f = d.joinpath(f"{name}.json")
        if f.is_file():
            data = json.loads(f.read_text())
            if country != "pl" or "country" in data:
                data["country"] = country
            return data
    raise ProfileError(f"unknown preset {name!r}; available for {country}: {presets(country)}")


def combine(names: list[str], country: str = "pl") -> dict:
    """Merge presets: searches are concatenated, everything else comes from the first preset that sets it."""
    if country not in countries.codes():
        raise ProfileError(f"unknown country {country!r}; available: {countries.codes()}")
    loaded = [preset(name, country) for name in names]
    out: dict = {"$schema": str(_SCHEMA), "version": 2, "country": country}
    for p in loaded:
        out.setdefault("label", p.get("label"))
        out["searches"] = out.get("searches", []) + p.get("searches", [])
        for k in ("candidate", "boards", "defaults", "rank", "blacklist", "review", "politeness"):
            if k in p:
                out.setdefault(k, p[k])
    if len(names) > 1:
        out["label"] = " + ".join(p.get("label", n) for n, p in zip(names, loaded))
    return out


def _resolve(node, defs: dict):
    """`node` with every `{"$ref": "#/$defs/name", ...}` replaced by that definition (siblings of `$ref` win)."""
    if isinstance(node, list):
        return [_resolve(v, defs) for v in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _resolve(defs[node["$ref"].removeprefix("#/$defs/")] | {k: v for k, v in node.items() if k != "$ref"}, defs)
    return {k: _resolve(v, defs) for k, v in node.items() if k != "$defs"}


@functools.lru_cache(maxsize=1)
def _schema() -> dict:
    raw = json.loads(_SCHEMA.read_text())
    return _resolve(raw, raw.get("$defs", {}))


def schema() -> dict:
    """profile/schema.json with its `$defs` references resolved."""
    return copy.deepcopy(_schema())
