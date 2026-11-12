"""test_text.py"""
from pathlib import Path

from neetscape.infer import fill, hints
from neetscape.model import Offer
from neetscape.pay import DEFAULT_FX
from neetscape.posting import parse_posting

FX = Path(__file__).parent.parent / "fixtures" / "pl"


def test_jsonld_posting_from_recorded_offer_page():
    p = parse_posting((FX / "justjoin_offer.html").read_text())
    assert p["company"] and p["published"] and len(p["description"]) > 200
    assert parse_posting("<html>no data</html>") == {}


def test_hints():
    h = hints("Praca w 100% zdalna. Wymagamy 3+ lata doświadczenia, bachelor degree. German C1. hybrid possible")
    assert h["fully_remote"] and h["years"] and "degree" in h["degree"] and h["languages"] == ["german"] and h["hybrid"]


def test_fill_reads_text_where_the_board_says_nothing():
    o = Offer(board="olx", key="k", url="k", title="Junior asystent (praca zdalna)", pay_text="4 800 - 5 800 zł / mies.",
              snippet="Praca dodatkowa Umowa zlecenie", worktime="unknown")
    fill(o, DEFAULT_FX)
    assert (o.mode, o.worktime, o.level, o.pay_min, o.pay_max) == ("remote", "part_time", "junior", 4800, 5800)
    assert "mandate" in o.contracts
    board_data = Offer(board="justjoin", key="k", url="k", title="Junior (remote)", mode="hybrid")
    fill(board_data, DEFAULT_FX)
    assert board_data.mode == "hybrid" and board_data.facts == {"mode": "hybrid"}  # board data wins over text
    assert board_data.evidence["mode"] == ["board", "board data"] and o.evidence["mode"][0] == "card"
    found_remote = Offer(board="pracuj", key="k", url="k", title="Asystent", snippet="hybrydowo")
    fill(found_remote, DEFAULT_FX, request_remote=True)
    assert found_remote.mode == "remote"  # the board's own remote filter beats card words
