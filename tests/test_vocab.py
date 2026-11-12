"""The job function and domain vocabularies on the recorded board pages: a regression gate for vocabulary edits.

Every board's fixture is parsed; each offer's title is read against the board's own category with the same
measure as `python tests/infer_audit.py DB --agreement` (shared: `infer_audit.reading` and `infer_audit.agreement`).
"""
import pytest

from neetscape import country as countries
from neetscape.boards import REGISTRY
from test_boards import COVERAGE, parse

import infer_audit

# The floors, a few points below the fixtures' values when set (2026-11-12: coverage 59/72 = 81.9%, no domain
# 32/177 = 18.1%). A vocabulary change that lowers a value past its floor fails with the titles it lost. When a
# change improves the values, raise the floors to a few points below the new ones (the failure message and
# `pytest tests/test_vocab.py -s` print them); lower one only for a change that reads the fixtures more correctly.
MIN_COVERAGE = 0.78     # the category's domain among the title's domains, over offers where both give one
MAX_NO_DOMAIN = 0.21    # fixture offers whose title gives no domain


@pytest.fixture(scope="module")
def readings():
    recs = []
    for board in sorted(COVERAGE):
        langs = countries.languages(countries.text_country(REGISTRY[board].caps.country, "pl"))
        recs += [infer_audit.reading(o.title, o.category or "", langs) for o in parse(board)]
    infer_audit.assign_languages(recs)
    return recs


def test_title_domains_agree_with_board_categories(readings):
    a = infer_audit.agreement(readings)
    print(f"\nfixture coverage {a['covered']}/{a['both']} = {100 * a['coverage']:.1f}%")
    assert a["both"] >= 50, f"only {a['both']} fixture offers have a domain in both title and category"
    lines = [f"  {d['title'][:70]!r}: title {', '.join(d['title_domains'])}; category {d['category'][:50]!r} -> "
             f"{d['category_domain']}" for d in a["disagreeing"]]
    assert a["coverage"] >= MIN_COVERAGE, (
        f"category's domain among the title's domains: {a['covered']}/{a['both']} = {100 * a['coverage']:.1f}% "
        f"< {100 * MIN_COVERAGE:.0f}% (MIN_COVERAGE). Disagreeing titles:\n" + "\n".join(lines))


def test_few_fixture_titles_have_no_domain(readings):
    none = [r["title"] for r in readings if r["domain"] == "unknown"]
    share = len(none) / len(readings)
    print(f"\nfixture titles with no domain {len(none)}/{len(readings)} = {100 * share:.1f}%")
    assert share <= MAX_NO_DOMAIN, (
        f"titles with no domain: {len(none)}/{len(readings)} = {100 * share:.1f}% > {100 * MAX_NO_DOMAIN:.0f}% "
        f"(MAX_NO_DOMAIN):\n" + "\n".join(f"  {t[:90]!r}" for t in none))
