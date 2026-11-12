"""test_text.py"""
from pathlib import Path

from neetscape.infer import fill_from_text, hints
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


def test_fill_from_text_infers_unknown_fields_only():
    o = Offer(board="olx", key="k", url="k", title="Junior asystent (praca zdalna)", pay_text="4 800 - 5 800 zł / mies.",
              snippet="Praca dodatkowa Umowa zlecenie", worktime="unknown")
    fill_from_text(o, DEFAULT_FX)
    assert (o.mode, o.worktime, o.level, o.pay_min, o.pay_max) == ("remote", "part_time", "junior", 4800, 5800)
    assert "mandate" in o.contracts
    board_data = Offer(board="justjoin", key="k", url="k", title="Junior (remote)", mode="hybrid")
    fill_from_text(board_data, DEFAULT_FX)
    assert board_data.mode == "hybrid"  # board data wins over text
