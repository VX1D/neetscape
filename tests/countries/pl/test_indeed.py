"""pl.indeed.com on its recorded jobcards extract tests/fixtures/pl/indeed.json (output of `Indeed.fetch_js`) and offer
page tests/fixtures/pl/indeed_posting.html."""
from pathlib import Path

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request
from neetscape.countries.pl.boards import indeed

FX = Path(__file__).parents[2] / "fixtures" / "pl"
IN = REGISTRY["indeed"]


def offers():
    return {o.key.rsplit("=", 1)[1]: o for o in IN.parse((FX / "indeed.json").read_text(), Request("indeed", "t", None))}


def test_both_remote_tags_with_a_place_are_hybrid():
    by = offers()
    assert by["8dd16953fd4b780d"].mode == "hybrid"  # tags Hybrydowo + Zdalnie, Gdańsk: posting asks for office days
    assert by["265a7108be11400f"].mode == "hybrid"  # REMOTE_HYBRID
    assert indeed.work_mode({"tags": {"remote": ["Hybrydowo", "Zdalnie"]}, "remote_location": True, "mode": "REMOTE_ALWAYS"}) == "remote"


def test_posting_from_embedded_description():
    meta = IN.posting((FX / "indeed_posting.html").read_text())
    assert meta["source"] == "board" and meta["description"].startswith("Kogo szukamy?")
    assert "ochronadanych@knauf.com" in meta["description"] and "cookie" not in meta["description"].lower()
    assert "\\u003C" not in meta["description"] and "<p>" not in meta["description"]
    assert indeed.posting_text("<html>no data</html>") == "" and "description" not in IN.posting("<html></html>")
    assert IN.posting_selector == ".simple-job-description-html"
