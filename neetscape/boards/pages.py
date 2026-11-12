"""Helpers shared by board adapters.

- embedded data: `script_json` (JS for `Board.fetch_js()`: one <script>'s JSON, cut down in the tab),
  `page_script_json` (the same JSON from a page source), `json_at`, `nuxt_data`;
- markup: `html_text`, `html_field`;
- URLs: `with_query`, `slug`, `nearest_radius`;
- values: `clean_spaces`, `snippet`, `present`, `places`, `date_of`, `amount`, `pay_range`, `currency_code`;
- board labels -> vocabulary: `most_remote_mode`, `labelled_contracts`, `worktime_from_labels`, `prefix_level`,
  `lowest`, `lowest_level` (+ `LEVEL_WORDS`).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import urllib.parse
from email.utils import parsedate_to_datetime

from .. import infer
from ..pay import CURRENCIES
from ..model import LEVELS, fold

# embedded data


def script_json(script_id: str, body: str) -> str:
    """JS `(t)=>string` returning '' when the script is missing. `body` sees the parsed JSON as `d` and must
    `return JSON.stringify(...)` of what the parser needs (keep it small: it is sent over CDP)."""
    return ("(t)=>{const m=t.match(/<script id=\"" + script_id + "\"[^>]*>([\\s\\S]*?)<\\/script>/);if(!m)return '';"
            "const d=JSON.parse(m[1]);" + body + "}")


def page_script_json(page: str, script_id: str):
    """The JSON of `<script id=script_id>` in a page source (e.g. Next.js `__NEXT_DATA__`), or None."""
    m = re.search(rf'<script[^>]*\sid="{re.escape(script_id)}"[^>]*>(.*?)</script>', page or "", re.S)
    try:
        return json.loads(m.group(1)) if m else None
    except json.JSONDecodeError:
        return None


def json_at(text: str, start: int):
    """The JSON value starting at `text[start]` (an object, array or string embedded in a script); None when it
    is truncated or malformed."""
    try:
        return json.JSONDecoder().raw_decode(text, start)[0]
    except ValueError:
        return None


_NUXT_WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef"}


def _devalue(table: list, index: int, depth: int = 0):
    """Entry `index` of a devalue table: objects and arrays hold indexes of other entries, ["Reactive", i]-style
    wrappers stand for entry i, ["Set", ...] / ["Date", iso] for those types; negative indexes are special values."""
    if index < 0 or depth > 60:
        return None
    v = table[index]
    if isinstance(v, dict):
        return {k: _devalue(table, i, depth + 1) for k, i in v.items()}
    if isinstance(v, list):
        if v and isinstance(v[0], str):
            if v[0] in _NUXT_WRAPPERS:
                return _devalue(table, v[1], depth + 1)
            if v[0] in ("EmptyRef", "EmptyShallowRef"):
                return None
            if v[0] == "Set":
                return [_devalue(table, i, depth + 1) for i in v[1:]]
            if v[0] == "Date":
                return v[1]
        return [_devalue(table, i, depth + 1) for i in v]
    return v


def nuxt_data(page: str, key: str = "data"):
    """`key` of a Nuxt payload (`<script id="__NUXT_DATA__">`, devalue format: one flat JSON array whose entries
    refer to others by index), decoded. ValueError when the page has no payload."""
    table = page_script_json(page, "__NUXT_DATA__")
    if not table:
        raise ValueError("no __NUXT_DATA__ in the page (bot wall or format change)")
    root = table[0] if isinstance(table[0], dict) else table[table[0][1]]  # ["ShallowReactive", 1]
    return _devalue(table, root[key])


# markup


def clean_spaces(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def html_text(fragment: str | None) -> str:
    """Text of a markup fragment on one line: tags dropped, entities decoded, whitespace collapsed."""
    return clean_spaces(html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")))


def html_field(pattern: str, markup: str) -> str:
    """`html_text` of the first group of `pattern` in `markup` (dot matches newlines); '' when absent."""
    m = re.search(pattern, markup, re.S)
    return html_text(m.group(1)) if m else ""


# URLs


def with_query(url: str, query: dict, **urlencode_args) -> str:
    """`url?<query>`, or `url` alone when the query is empty (`urlencode_args`: e.g. `safe`, `quote_via`)."""
    return url + ("?" + urllib.parse.urlencode(query, **urlencode_args) if query else "")


def slug(text: str) -> str:
    """URL slug of a place or phrase: 'Kraków' -> 'krakow', 'Bielsko-Biała' -> 'bielsko-biala'."""
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")


def nearest_radius(km, radii: tuple) -> int:
    """The smallest of a board's accepted radii (ascending) covering `km`; the largest when `km` is larger."""
    return next((r for r in radii if r >= (km or 0)), radii[-1])


# values


def snippet(*parts: str, limit: int = 1000) -> str:
    """Card text for `Offer.snippet`: the parts on one line, cut to `limit` characters."""
    return clean_spaces(" ".join(parts))[:limit]


def present(*values) -> list:
    """The non-empty values, in order: `locations=present(o.get("city"))`."""
    return [v for v in values if v]


def places(values) -> list[str]:
    """Distinct non-empty place names, sorted."""
    return sorted({v for v in values or [] if v})


def date_of(value) -> dt.date | None:
    """A date from epoch milliseconds, an ISO string ("2026-11-12T...") or an RFC 2822 one (RSS `pubDate`);
    None otherwise."""
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).date() if value > 0 else None
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        try:
            return parsedate_to_datetime(value).date()
        except (TypeError, ValueError):
            return None


def amount(v) -> str:
    """12000.0 -> '12000', 12.5 -> '12.5'."""
    return str(int(v)) if isinstance(v, (int, float)) and v == int(v) else str(v)


def pay_range(kind: str, lo, hi, currency: str, unit: str, gross: bool = False) -> str:
    """The pay text format all structured adapters produce: 'b2b:12000-18000 PLN/month gross'. A missing end
    (None) takes the other one: 'from 4850' -> '4850-4850'."""
    lo, hi = lo if lo is not None else hi, hi if hi is not None else lo
    return f"{kind}:{amount(lo)}-{amount(hi)} {currency}/{unit}{' gross' if gross else ''}"


def currency_code(symbol: str) -> str:
    """'zł' -> 'PLN' (the currency marks of `pay.py`); a code or an unknown symbol is upper-cased."""
    return dict(CURRENCIES).get(symbol.strip().lower(), symbol.upper())


# board labels -> vocabulary


def most_remote_mode(modes, remote: str, hybrid: str, onsite: str = r"(?s).") -> str:
    """Work mode of an offer listed with several modes ("zdalna", "hybrydowa"): the most remote one, by regex on
    the lower-cased modes. `onsite` defaults to any text, so a listed mode that is not remote or hybrid is on site."""
    text = " ".join(modes or []).lower()
    return ("remote" if re.search(remote, text) else "hybrid" if re.search(hybrid, text)
            else "onsite" if re.search(onsite, text) else "unknown")


def labelled_contracts(labels, table: dict, languages=None) -> list[str]:
    """Contract types of a board's contract labels, in order without duplicates: the board's own table (lower-cased
    labels), else whatever the label's text says (`infer.contracts_from_text`)."""
    out: list[str] = []
    for label in labels or []:
        key = label.strip().lower()
        for c in [table[key]] if key in table else infer.contracts_from_text(label, languages):
            if c not in out:
                out.append(c)
    return out


def worktime_from_labels(labels, part: str, full: str) -> str:
    """Work time from a board's work-time labels: part time when any matches the regex `part`, else full time when
    any matches `full`, else unknown (regexes on the lower-cased labels)."""
    text = " ".join(labels or []).lower()
    return "part_time" if re.search(part, text) else "full_time" if re.search(full, text) else "unknown"


def prefix_level(label: str | None, table: dict) -> str:
    """Level of a board's level label by its leading words (`table`: lower-cased prefix -> level); the longest
    prefix wins ('starszy specjalista' before 'specjalista'). Unknown when none matches."""
    label = (label or "").strip().lower()
    return next((lv for w, lv in sorted(table.items(), key=lambda x: -len(x[0])) if label.startswith(w)), "unknown")


def lowest(levels) -> str:
    """The lowest known level of several (an offer listed for mid and senior is mid), so a level filter does
    not drop it; unknown when none is known."""
    found = set(levels) - {"unknown"}
    return min(found, key=LEVELS.index) if found else "unknown"


# board seniority words that `infer.level` does not know
LEVEL_WORDS = {"trainee": "intern", "assistant": "junior", "medium": "mid", "head": "lead", "executive": "manager"}


def lowest_level(values, local: dict | None = None) -> str:
    """`lowest` of board level values: `local` words (lower-cased) first, then `infer.level`."""
    local = local or {}
    return lowest(local.get(str(v).lower()) or infer.level(str(v)) for v in values or [])
