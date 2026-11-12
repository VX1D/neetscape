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


def test_fields_from_cards():
    by = offers()
    assert "fedcba9876543210" not in by  # bare /viewjob copy with a fake id
    assert all(o.company and o.published and o.url.startswith("https://pl.indeed.com/viewjob?jk=") for o in by.values())
    assert sum(1 for o in by.values() if o.locations) >= 3
    o = by["91eef789f7a700aa"]  # salary, a place, remote only
    assert (o.company, o.mode, o.locations, o.pay_text) == ("Urban Outfitters", "remote", ["Kraków, małopolskie"],
                                                           "90 000-115 000 PLN za rok")
    assert str(o.published) == "2026-10-21"  # createDate, the date shown; pubDate is 2026-10-20
    assert by["20d9da3be7136033"].published.isoformat() == "2026-10-28"  # reposted: pubDate 2024-12-20
    assert by["9b52b6af002b41dc"].locations == ["Warszawa"]  # "00-640 Warszawa": postcode dropped
    assert by["109a9c722f1b96f1"].locations == [] and by["109a9c722f1b96f1"].mode == "remote"  # "zdalnie", no place
    assert by["f75c35aed0ad0d18"].contracts == ["b2b", "employment", "mandate"]
    assert by["04115fd8f03dfb1e"].contracts == ["employment"] and by["04115fd8f03dfb1e"].promoted  # "Umowa na okres próbny"
    assert by["dcce62fc2354081c"].worktime == "full_time" and by["dcce62fc2354081c"].mode == "unknown"


def test_both_remote_tags_with_a_place_are_hybrid():
    by = offers()
    assert by["8dd16953fd4b780d"].mode == "hybrid"  # tags Hybrydowo + Zdalnie, Gdańsk: posting asks for office days
    assert by["265a7108be11400f"].mode == "hybrid"  # REMOTE_HYBRID
    assert indeed.work_mode({"tags": {"remote": ["Hybrydowo", "Zdalnie"]}, "remote_location": True, "mode": "REMOTE_ALWAYS"}) == "remote"


def test_one_public_page_and_urls():
    assert IN.caps.max_pages == 1 and IN.page_url(Request("indeed", "t", "x", {"remote": True}), 2).endswith("&start=10")
    assert IN.page_url(Request("indeed", "t", None, {"remote": True, "sort": "newest"}), 1) == (
        "https://pl.indeed.com/jobs?q=&l=Polska&sc=0kf%3Aattr%28DSQF7%29%3B&sort=date")
    assert IN.page_url(Request("indeed", "t", "python", {"remote": True}), 1) == (
        "https://pl.indeed.com/jobs?q=python&sc=0kf%3Aattr%28DSQF7%29%3B")
    assert IN.page_url(Request("indeed", "t", "python", {}), 1) == "https://pl.indeed.com/jobs?q=python"  # anywhere
    assert IN.page_url(Request("indeed", "t", "asystent", {"city": "Gdańsk", "radius_km": 0, "sort": "newest"}), 1) == (
        "https://pl.indeed.com/jobs?q=asystent&l=Gda%C5%84sk&radius=0&sort=date")
    assert IN.parse("[]", Request("indeed", "t", None)) == []


def test_posting_from_embedded_description():
    meta = IN.posting((FX / "indeed_posting.html").read_text())
    assert meta["source"] == "board" and meta["description"].startswith("Kogo szukamy?")
    assert "ochronadanych@knauf.com" in meta["description"] and "cookie" not in meta["description"].lower()
    assert "\\u003C" not in meta["description"] and "<p>" not in meta["description"]
    assert indeed.posting_text("<html>no data</html>") == "" and "description" not in IN.posting("<html></html>")
    assert IN.posting_selector == ".simple-job-description-html"
