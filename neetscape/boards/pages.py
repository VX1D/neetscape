"""Helpers shared by adapters that read job board result pages.

- `script_json`: JS for `Board.fetch_js()` that cuts a page down to the JSON embedded in one <script>
  (Next.js `__NEXT_DATA__`, Angular `serverApp-state`, ...), so only that travels from the tab.
- `RenderedBoard`: base class for boards read from rendered result cards (transport browser_render).
- small value helpers used by many adapters: `slug`, `epoch_or_iso_date`, `feed_date`, `amount`, `pay_range`,
  `lowest_level` (+ `LEVEL_WORDS`), `most_remote_mode`, `clean_spaces`, `card_title`, `MONEY`.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from email.utils import parsedate_to_datetime

from .. import infer
from ..model import LEVELS, Offer, fold
from .base import Board, Request

# amount + currency + the unit / gross / contract words that belong to it, and nothing after them
MONEY = re.compile(r"\d[\d\s .,]*k?\s*(?:[–-]\s*\d[\d\s .,]*k?\s*)?(?:zł|pln|eur|€|usd|\$)"
                   r"(?:\s*(?:/\s*(?:mies|godz|h|dzień|day|month|hour|rok|year|mo|hr)\b\.?|brutto|netto|gross|net\b|"
                   r"\(?\+\s*VAT\)?|za\s+(?:miesiąc|godzinę|dzień|rok)|"
                   r"\((?:B2B|UoP|UZ|UoD|CoE|zlec\.?|umowa[^)]*|zal\. od umowy)\)))*", re.I)
_CONTRACT_TAG = re.compile(r"\((?:B2B|UoP|UZ|UoD|CoE|zlec\.?|umowa[^)]*)\)", re.I)
_TITLE_NOISE = re.compile(r"\s(?:new|nowa|quick apply|szybka aplikacja|start ASAP|B2B|UoP|UZ|UoD)\b|\s\d[\d\s]*(?:k)?\s?[–-]\s?\d")
_JUNK_TITLES = {"sprawdź!", "apply", "aplikuj", "skip to main content"}


def script_json(script_id: str, body: str) -> str:
    """JS `(t)=>string` returning '' when the script is missing. `body` sees the parsed JSON as `d` and must
    `return JSON.stringify(...)` of what the parser needs (keep it small: it is sent over CDP)."""
    return ("(t)=>{const m=t.match(/<script id=\"" + script_id + "\"[^>]*>([\\s\\S]*?)<\\/script>/);if(!m)return '';"
            "const d=JSON.parse(m[1]);" + body + "}")


def clean_spaces(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def slug(city: str) -> str:
    """URL slug of a place: 'Kraków' -> 'krakow', 'Bielsko-Biała' -> 'bielsko-biala'."""
    return re.sub(r"[^a-z0-9]+", "-", fold(city)).strip("-")


def epoch_or_iso_date(value) -> dt.date | None:
    """A date from epoch milliseconds or an ISO string; None otherwise."""
    if isinstance(value, (int, float)) and value > 0:
        return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).date()
    if isinstance(value, str) and len(value) >= 10:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def feed_date(s: str | None) -> dt.date | None:
    """A date from an ISO string ("2026-11-12T...") or an RFC 2822 one (RSS `pubDate`); None otherwise."""
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        try:
            return parsedate_to_datetime(s).date()
        except (TypeError, ValueError):
            return None


def amount(v) -> str:
    """12000.0 -> '12000', 12.5 -> '12.5'."""
    return str(int(v)) if isinstance(v, (int, float)) and v == int(v) else str(v)


def pay_range(kind: str, lo, hi, currency: str, unit: str, gross: bool = False) -> str:
    """The pay text format all structured adapters produce: 'b2b:12000-18000 PLN/month gross'."""
    return f"{kind}:{amount(lo)}-{amount(hi)} {currency}/{unit}{' gross' if gross else ''}"


# board seniority words that `infer.level` does not know
LEVEL_WORDS = {"trainee": "intern", "assistant": "junior", "medium": "mid", "head": "lead", "executive": "manager"}


def most_remote_mode(modes, remote: str, hybrid: str, onsite: str = r"(?s).") -> str:
    """Work mode of an offer listed with several modes ("zdalna", "hybrydowa"): the most remote one, by regex on
    the lower-cased modes. `onsite` defaults to any text, so a listed mode that is not remote or hybrid is on site."""
    text = " ".join(modes or []).lower()
    return ("remote" if re.search(remote, text) else "hybrid" if re.search(hybrid, text)
            else "onsite" if re.search(onsite, text) else "unknown")


def lowest_level(values, local: dict | None = None) -> str:
    """Offers listed for several levels (mid/senior) keep the lowest, so a level filter does not drop them."""
    local = local or {}
    found = {local.get(str(v).lower()) or infer.level(str(v)) for v in values or []} - {"unknown"}
    return min(found, key=LEVELS.index) if found else "unknown"


def card_title(link_text: str) -> str:
    """Title from a result link: pay, contract tags and badges glued after the title are cut off."""
    return _CONTRACT_TAG.sub("", _TITLE_NOISE.split(clean_spaces(link_text))[0]).strip()[:140]


class RenderedBoard(Board):
    """Boards read from rendered result cards: the browser returns [[href, [link_text, card_text]], ...].

    Subclasses set `link_pattern` and implement `url(r, page)`; `card(link, rest)` may extract company,
    pay and locations from the card text after the link text, `extra(card, url)` may add fields read from the
    whole card or the URL, or board constants.
    """

    def url(self, r: Request, page: int) -> str:
        raise NotImplementedError

    def page_url(self, r: Request, page: int) -> str | None:
        return self.url(r, page) if page <= self.caps.max_pages else None

    def offer_key(self, url: str) -> str:
        return re.sub(r"[?#].*$", "", url)

    def card(self, link: str, rest: str) -> dict:
        """Fields from the card text after the link text. Default: the first amount of money, in the card text
        first (the link text may hold numbers, such as hours or a street, that are not pay)."""
        money = MONEY.search(rest) or MONEY.search(link)
        return {"pay_text": money.group(0).strip() if money else ""}

    def extra(self, card: str, url: str) -> dict:
        return {}

    def parse(self, raw: str, r: Request) -> list[Offer]:
        seen: dict[str, Offer] = {}
        for url, (text, card) in json.loads(raw):
            if not re.search(self.link_pattern, url):
                continue
            title, card = card_title(text), clean_spaces(card)
            if not title or title.lower() in _JUNK_TITLES:
                continue
            link = clean_spaces(text)
            fields = self.card(link, card[len(link):].strip() if card.startswith(link) else card)
            key = self.offer_key(url)
            o = seen.get(key)
            if o is None:
                seen[key] = Offer(board=self.name, key=key, url=key, title=title, snippet=card,
                                  **{"company": "", "pay_text": "", "locations": [], **fields}, **self.extra(card, url))
            else:  # the same offer is linked several times (logo, title): keep the richest values
                if len(title) > len(o.title):
                    o.title = title
                o.company = o.company or fields.get("company", "")
                o.pay_text = o.pay_text or fields.get("pay_text", "")
                o.locations = o.locations or fields.get("locations", [])
                if len(card) > len(o.snippet):
                    o.snippet = card
        return list(seen.values())
