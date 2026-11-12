"""Read the posting of an offer page from its schema.org JobPosting (JSON-LD); HTML fragments to plain text."""
from __future__ import annotations

import html as htmllib
import json
import re

_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def html_to_text(fragment: str) -> str:
    """Plain text of an HTML fragment: block ends become line breaks, list items "• ", entities unescaped."""
    t = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", fragment or "")
    t = re.sub(r"(?i)<li[^>]*>", "• ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def _walk(node):
    """Every dict in a JSON tree, depth first."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _json(block: str):
    """A JSON-LD block, as written or HTML-escaped; None when it is neither."""
    for text in (block, htmllib.unescape(block)):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return None


def find_jobposting(page_html: str) -> dict | None:
    """The first schema.org JobPosting in the page's JSON-LD blocks, or None."""
    for block in _LD.findall(page_html or ""):
        data = _json(block.strip())
        if data is None:
            continue
        for node in _walk(data):
            t = node.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                return node
    return None


def _joined(value) -> str:
    """A JSON-LD value that may be a list, as one space-separated string."""
    return " ".join(value) if isinstance(value, list) else (value or "")


def _salary(base) -> str:
    """A JSON-LD `baseSalary` as text: "8000-12000 PLN/month"; '' when it has no amount."""
    if not isinstance(base, dict):
        return ""
    cur = base.get("currency", "")
    val = base.get("value", {})
    if isinstance(val, dict):
        lo, hi = val.get("minValue", val.get("value")), val.get("maxValue", val.get("value"))
        unit = (val.get("unitText") or "").lower()
    else:
        lo = hi = val
        unit = ""
    if lo is None:
        return ""
    return f"{lo}-{hi} {cur}/{unit}".strip("/")


def parse_posting(page_html: str) -> dict:
    """{description, company, published, valid_through, salary, remote, employment_type} from the page's JobPosting
    JSON-LD; {} when it has none."""
    jp = find_jobposting(page_html)
    if not jp:
        return {}
    org = jp.get("hiringOrganization")
    return {
        "description": html_to_text(jp.get("description", "")),
        "company": (org.get("name") if isinstance(org, dict) else org) or "",
        "published": (jp.get("datePosted") or "")[:10],
        "valid_through": (jp.get("validThrough") or "")[:10],
        "salary": _salary(jp.get("baseSalary")),
        "remote": "TELECOMMUTE" in _joined(jp.get("jobLocationType")).upper(),
        "employment_type": _joined(jp.get("employmentType")),
    }

