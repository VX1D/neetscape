"""useme.com on its recorded result page tests/fixtures/pl/useme.html; closed projects are dropped."""
from pathlib import Path

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request

FX = Path(__file__).parents[2] / "fixtures" / "pl" / "useme.html"
UM = REGISTRY["useme"]


def test_open_cards_only_with_budget_client_category():
    raw = FX.read_text()
    got = UM.parse(raw, Request("useme", "t", None))
    assert raw.count("<article") == 13 and len(got) == 10  # 3 closed ("Zakończone") are dropped
    assert all(o.company and o.category and o.mode == "remote" and o.pay_period == "project" for o in got)
    by = {o.title: o for o in got}
    assert by["Rolka reklamowa książki UGC"].pay_text == "750,00 PLN"
    assert by["Produkcja spotu AI"].pay_text == "" and "Do negocjacji" in by["Produkcja spotu AI"].snippet
    assert by["Specjalista e-commerce Temu, eMAG, eBAY, Amazon"].skills[:2] == ["Amazon Seller Central", "ebay"]
    assert all(o.url.startswith("https://useme.com/pl/jobs/") and o.url.endswith("/") for o in got)


def test_page_without_open_projects_is_empty():
    closed = '<article class="job"><div class="job__header-details--date job__header-details--closed">Zakończone</div>' \
             '<a href="/pl/jobs/x,1/" class="job__title">X</a></article>'
    assert UM.parse(closed, Request("useme", "t", None)) == []
    assert UM.caps.page_size == 0  # open cards per page vary: only an empty page ends a request


def test_page_urls():
    assert UM.page_url(Request("useme", "t", "asystent", {"sort": "newest"}), 1) == (
        "https://useme.com/pl/jobs/?query=asystent&order_by=-published_on")
