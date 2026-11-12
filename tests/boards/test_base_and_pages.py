"""The board interface (neetscape/boards/base.py) and the adapters' shared helpers (neetscape/boards/pages.py)."""
import datetime as dt

import pytest

from neetscape.boards import REGISTRY, pages
from neetscape.boards.base import Board, Caps, register
from neetscape.model import Search, Where


def test_default_posting_is_jsonld_and_empty_without_it():
    board = REGISTRY["justjoin"]  # no posting override
    page = ('<script type="application/ld+json">{"@type": "JobPosting", "description": "<p>Do things</p>", '
            '"hiringOrganization": {"name": "Acme"}}</script><nav>Menu</nav>')
    assert board.posting(page)["description"] == "Do things"
    assert board.posting("<nav>Menu</nav><main>whole page</main>") == {}


def test_unknown_transport_is_refused():
    class Rendered(Board):
        name = "rendered"
        caps = Caps(country="any", transport="browser_render")
    with pytest.raises(ValueError, match="unknown transport"):
        register(Rendered)
    assert "rendered" not in REGISTRY


def test_huge_listing_is_served_with_the_remote_filter_only():
    class Huge(Board):
        name = "huge"
        caps = Caps(keywords=True, remote="filter", city=True, worktime=True, sort_newest=True, huge_unfiltered=True, country="pl")
    b = Huge()
    remote = Search(id="r", label="r", where=Where(remote=True), keywords=None, worktime=frozenset({"part_time"}))
    (req,), warns = b.requests(remote)
    assert req.params == {"remote": True, "part_time": True, "sort": "newest"} and req.pushed == {"remote", "worktime"} and not warns
    reqs, warns = b.requests(Search(id="a", label="a", where=Where(), keywords=None))
    assert not reqs and "too large" in warns[0]
    always = Huge()
    always.caps = Caps(keywords=True, remote="always", huge_unfiltered=True, country="pl")  # e.g. useme: no filter, still huge
    assert always.requests(remote)[0] == []


def test_markup_helpers():
    assert pages.html_text(" <b>Kraków</b>&nbsp;&amp;\n Wieliczka ") == "Kraków & Wieliczka"
    assert pages.html_field(r'class="t">(.*?)</a>', '<a class="t">\n A <i>B</i></a>') == "A B"
    assert pages.html_field(r'class="x">(.*?)</a>', "<a>") == ""
    page = '<script type="application/json" id="__NEXT_DATA__">{"a": 1}</script><script data-id="X">{}</script>'
    assert pages.page_script_json(page, "__NEXT_DATA__") == {"a": 1}
    assert pages.page_script_json(page, "X") is None and pages.page_script_json(None, "X") is None


def test_value_helpers():
    assert pages.slug("Bielsko-Biała") == "bielsko-biala" and pages.slug("automatyzacja procesów") == "automatyzacja-procesow"
    assert pages.epoch_or_iso_date(1794231934738) == dt.date(2026, 11, 9)
    assert pages.epoch_or_iso_date("2026-11-12T10:00:00Z") == dt.date(2026, 11, 12) and pages.epoch_or_iso_date("x") is None
    assert pages.feed_date("Thu, 12 Nov 2026 10:00:00 +0000") == dt.date(2026, 11, 12)
    assert pages.pay_range("b2b", 12000.0, 18000, "PLN", "month", gross=True) == "b2b:12000-18000 PLN/month gross"
    assert pages.pay_range("b2b", None, 5000, "PLN", "month") == "b2b:5000-5000 PLN/month"  # a missing end takes the other
    assert pages.pay_range("b2b", 31.4, None, "PLN", "hour") == "b2b:31.4-31.4 PLN/hour"
    assert [pages.nearest_radius(km, (5, 10, 30)) for km in (None, 0, 7, 30, 31)] == [5, 5, 10, 30, 30]


def test_vocabulary_helpers():
    table = {"umowa o pracę": "employment", "kontrakt b2b": "b2b"}
    assert pages.labelled_contracts(["Kontrakt B2B", "Umowa o pracę", "kontrakt b2b", "Umowa zlecenie"], table) == \
        ["b2b", "employment", "mandate"]  # unknown labels by their text, no duplicates
    assert pages.worktime_from_labels(["Pełny etat", "Część etatu"], r"część", r"pełny") == "part_time"
    assert pages.worktime_from_labels([], r"część", r"pełny") == "unknown"
    levels = {"specjalista": "mid", "starszy specjalista": "senior"}
    assert pages.prefix_level("Starszy specjalista (Senior)", levels) == "senior" and pages.prefix_level("x", levels) == "unknown"
    assert pages.lowest(["senior", "unknown", "mid"]) == "mid" and pages.lowest([]) == "unknown"
    assert pages.lowest_level(["Senior", "trainee"], pages.LEVEL_WORDS) == "intern"
    assert pages.most_remote_mode(["Stacjonarna", "Zdalna"], "zdaln", "hybryd") == "remote"
    assert pages.most_remote_mode(["Mobilna"], "zdaln", "hybryd") == "onsite" and pages.most_remote_mode([], "a", "b") == "unknown"
