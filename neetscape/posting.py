"""Extract structured data from an offer page: schema.org JobPosting (JSON-LD) first, page text as fallback."""
from __future__ import annotations

import html as htmllib
import json
import re

_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def html_to_text(fragment: str) -> str:
    t = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", fragment or "")
    t = re.sub(r"(?i)<li[^>]*>", "• ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def find_jobposting(page_html: str) -> dict | None:
    for block in _LD.findall(page_html or ""):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            try:
                data = json.loads(htmllib.unescape(block.strip()))
            except json.JSONDecodeError:
                continue
        for node in _walk(data):
            t = node.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                return node
    return None


def _salary(base) -> str:
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
    """Return {description, company, published, salary, remote} from JSON-LD; empty values when absent."""
    jp = find_jobposting(page_html)
    if not jp:
        return {}
    org = jp.get("hiringOrganization")
    loc_type = jp.get("jobLocationType")
    loc_type = " ".join(loc_type) if isinstance(loc_type, list) else (loc_type or "")
    return {
        "description": html_to_text(jp.get("description", "")),
        "company": (org.get("name") if isinstance(org, dict) else org) or "",
        "published": (jp.get("datePosted") or "")[:10],
        "valid_through": (jp.get("validThrough") or "")[:10],
        "salary": _salary(jp.get("baseSalary")),
        "remote": "TELECOMMUTE" in loc_type.upper(),
        "employment_type": " ".join(jp["employmentType"]) if isinstance(jp.get("employmentType"), list) else (jp.get("employmentType") or ""),
    }

