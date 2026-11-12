"""Countries and boards: consistent definitions, every parser on its recorded page (`COVERAGE`), the adapters'
shared helpers, and each board's own rules. Exact URLs and per-offer values are not pinned: `neetscape probe BOARD`
checks a board live."""
import datetime as dt
import json

import pytest

from conftest import FIXTURES
from neetscape import country as countries
from neetscape import crawler, lang, profile
from neetscape.boards import REGISTRY, expand, groups, linkedin, pages
from neetscape.boards.base import Board, Caps, Request, country_of, min_intervals, register
from neetscape.countries.pl.boards import gowork, indeed, olx, pracapl
from neetscape.countries.pl.boards.justjoin import extract_offers
from neetscape.model import CONTRACTS, Offer, Search, Where

CODES = countries.codes()


def fixture(board, suffix=""):
    """The recorded page tests/fixtures/<cc>/<board><suffix>.* (shared boards: tests/fixtures/shared/)."""
    cc = country_of(REGISTRY[board])
    found = sorted((FIXTURES / (cc if cc in CODES else "shared")).glob(f"{board}{suffix}.*"))
    return found[0] if found else None


def parse(board, raw=None, keyword=None, **params):
    """The board's offers on `raw` (default: its fixture)."""
    return REGISTRY[board].parse(fixture(board).read_text() if raw is None else raw, Request(board, "t", keyword, params))


def requests(board, where=Where(remote=True), keywords=None, **kw):
    """The board's requests and warnings for one search."""
    return REGISTRY[board].requests(Search(id="s", label="s", where=where, keywords=keywords, **kw))


# countries and the registry

@pytest.mark.parametrize("code", CODES)
def test_country_definition(code):
    c = countries.get(code)
    assert c.code == code and c.fx[c.currency] == 1.0 and c.linkedin_location and c.place_names
    assert set(c.languages) <= set(lang.available())
    assert set(c.contracts) <= set(CONTRACTS) and set(c.contract_aliases.values()) <= set(CONTRACTS)
    boards = expand(list(c.default_boards))
    assert boards and set(boards) <= set(REGISTRY) and any(country_of(REGISTRY[b]) == code for b in boards)
    assert profile.presets(code)
    for name in profile.presets(code):
        assert profile.validate(profile.preset(name, code)).country.code == code


@pytest.mark.parametrize("board", sorted(REGISTRY))
def test_board_has_known_country_and_fixture(board):
    assert country_of(REGISTRY[board]) in CODES + list(countries.PSEUDO)
    assert fixture(board), f"{board}: record a page with `neetscape probe {board} --save-fixture tests/fixtures/<cc>/{board}.json`"


# Every board's parser on its recorded page: the fields it must fill on at least 80% of the offers. A new board
# is one row; a parser change that loses a field fails here (`neetscape probe BOARD` shows the live coverage).
COVERAGE = {
    "arbeitnow": "company published locations contracts level mode category skills",
    "bulldogjob": "company published contracts level mode worktime category skills",
    "bundesagentur": "company published locations contracts mode worktime category skills",
    "gowork": "company published locations contracts mode worktime category",
    "indeed": "company published locations",
    "justjoin": "company published locations contracts level mode worktime category skills",
    "linkedin": "company published locations",
    "nofluffjobs": "company published pay_text contracts level mode category skills",
    "olx": "published locations contracts worktime category",
    "pracapl": "published locations level mode worktime",
    "pracuj": "company published locations contracts level mode worktime",
    "remoteok": "company published mode skills",
    "rocketjobs": "company published locations level mode worktime category skills",
    "solidjobs": "company published locations pay_text contracts level mode worktime category skills",
    "theprotocol": "company published locations contracts level mode",
    "useme": "company contracts mode worktime category",
    "weworkremotely": "company published locations mode worktime category",
}


def test_every_board_has_a_coverage_row():
    assert set(COVERAGE) == set(REGISTRY)


@pytest.mark.parametrize("board", sorted(COVERAGE))
def test_board_parses_its_fixture(board):
    offers = parse(board)
    assert len(offers) >= 3 and len({o.key for o in offers}) == len(offers)
    for o in offers:
        assert o.board == board and o.key and o.url.startswith("http") and o.title
        assert o.mode in ("remote", "hybrid", "onsite", "unknown") and set(o.contracts) <= set(CONTRACTS)
    for f in COVERAGE[board].split():
        filled = sum(bool(getattr(o, f)) and getattr(o, f) != "unknown" for o in offers)
        assert filled >= 0.8 * len(offers), f"{board}: {f} on {filled}/{len(offers)} offers"


def test_groups_and_countries():
    g = groups()
    assert "linkedin" in g["pl"] and "linkedin" in g["de"] and "justjoin" in g["pl"] and "justjoin" not in g["de"]
    assert {"arbeitnow", "bundesagentur"} <= set(g["de"])
    assert g["intl"] == ["remoteok", "weworkremotely"] and set(g["all"]) == set(REGISTRY)
    reqs, warns = requests("justjoin", Where(remote=True, country="de"), ("python",))
    assert not reqs and "for pl" in warns[0]                           # a board of another country skips the search
    assert requests("linkedin", Where(remote=True, country="de"), ("python",))[0][0].params["country"] == "de"
    de = countries.get("de")
    assert {"munchen", "munich"} <= de.aliases("München") and "munchen" in de.aliases("Munich")
    assert "warsaw" in countries.get("pl").aliases("Warszawa")


# the board interface (base.py) and the adapters' helpers (pages.py)

def test_default_posting_is_jsonld_and_empty_without_it():
    page = ('<script type="application/ld+json">{"@type": "JobPosting", "description": "<p>Do things</p>", '
            '"hiringOrganization": {"name": "Acme"}}</script><nav>Menu</nav>')
    assert REGISTRY["justjoin"].posting(page)["description"] == "Do things"     # justjoin: no posting override
    assert REGISTRY["justjoin"].posting("<nav>Menu</nav><main>whole page</main>") == {}


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
    b.caps = Caps(keywords=True, remote="always", huge_unfiltered=True, country="pl")  # e.g. useme: no filter, still huge
    assert b.requests(remote)[0] == []


def test_min_intervals_yield_to_the_profile():
    assert min_intervals()["theprotocol.it"] == REGISTRY["theprotocol"].min_interval["theprotocol.it"]
    assert min_intervals()["linkedin.com"] >= 3
    assert min_intervals({"linkedin.com": 5})["linkedin.com"] == 5


def test_value_helpers():
    assert pages.slug("Bielsko-Biała") == "bielsko-biala" and pages.slug("automatyzacja procesów") == "automatyzacja-procesow"
    assert pages.date_of(1794231934738) == dt.date(2026, 11, 9) and pages.date_of("x") is None
    assert pages.date_of("2026-11-12T10:00:00Z") == pages.date_of("Thu, 12 Nov 2026 10:00:00 +0000") == dt.date(2026, 11, 12)
    assert pages.pay_range("b2b", 12000.0, 18000, "PLN", "month", gross=True) == "b2b:12000-18000 PLN/month gross"
    assert pages.pay_range("b2b", None, 5000, "PLN", "month") == "b2b:5000-5000 PLN/month"  # a missing end takes the other
    assert pages.pay_range("b2b", 31.4, None, "PLN", "hour") == "b2b:31.4-31.4 PLN/hour"
    assert [pages.nearest_radius(km, (5, 10, 30)) for km in (None, 0, 7, 30, 31)] == [5, 5, 10, 30, 30]


# LinkedIn

def test_linkedin_city_as_geo_id(monkeypatch):
    hits = json.loads((FIXTURES / "shared" / "linkedin_typeahead_krakow.json").read_text())
    assert linkedin.pick_geo("Kraków", hits) == linkedin.pick_geo("Krakow", hits, "pl") == "103263110"   # not the Łódzkie village
    assert linkedin.pick_geo("Nowhere", [h for h in hits if "Polska" not in h["displayName"]]) is None
    assert linkedin.pick_geo("Kraków", hits, "de") == "102982500"     # the first German hit (Krakow am See)
    li = REGISTRY["linkedin"]
    monkeypatch.setattr(linkedin, "geo_id", lambda city, cc: "103263110" if cc == "pl" else None)
    url = li.page_url(Request("linkedin", "t", "n8n", {"city": "Kraków", "radius_km": 30, "part_time": True, "country": "pl"}), 2)
    assert "geoId=103263110" in url and "start=10" in url
    assert "location=K%C3%B6ln" in li.page_url(Request("linkedin", "t", "n8n", {"city": "Köln", "country": "de"}), 1)
    for params, location in (({"remote": True, "country": "de"}, "Germany"), ({"remote": True}, "Poland")):
        assert f"location={location}&" in li.page_url(Request("linkedin", "t", None, params), 1)   # the country itself


def test_linkedin_posting_is_the_description_block_only():
    meta = linkedin.LinkedIn.posting_fields(fixture("linkedin", "_posting").read_text())
    text = meta["description"]
    assert meta["source"] == "api" and text.startswith("Location: ") and "Employment type: " in text and len(text) > 2000
    assert "Report this job" not in text and "Similar jobs" not in text   # page chrome around the block
    assert linkedin.LinkedIn.posting_fields("<html>login wall</html>")["description"] == ""


def test_linkedin_posting_keeps_its_job_criteria_as_meta():
    meta = linkedin.LinkedIn.posting_fields(fixture("linkedin", "_posting").read_text())
    assert meta["criteria"] == {"seniority": "Associate", "employment_type": "Full-time",
                                "industry": "Business Consulting and Services"}
    assert "Seniority level: Associate\nEmployment type: Full-time" in meta["description"]   # the text keeps them


@pytest.mark.parametrize("seniority,employment,want", [
    ("Entry level", "Full-time", {"level": "junior", "worktime": "full_time"}),
    ("Internship", "Internship", {"level": "intern", "contracts": ["internship"]}),
    ("Not Applicable", "Internship", {"level": "intern", "contracts": ["internship"]}),   # the type says intern
    ("Director", "Part-time", {"level": "manager", "worktime": "part_time"}),
    ("Executive", "Contract", {"level": "manager", "worktime": "flexible"}),             # and no contract type
    ("Mid-Senior level", "Temporary", {"worktime": "flexible"}),                         # mid or senior: unknown
    ("Associate", "Volunteer", {}),
    ("Starszy specjalista", "Pełny etat", {}),                                           # unlisted labels stay unknown
])
def test_linkedin_criteria_map_to_canonical_values(seniority, employment, want):
    facts = linkedin.LinkedIn().posting_facts({"criteria": {"seniority": seniority, "employment_type": employment}})
    plain = {k: [x[0] for x in v] if isinstance(v, list) else v[0] for k, v in facts.items()}
    assert plain == want
    if "worktime" in facts:
        assert facts["worktime"][1] == f"LinkedIn: Employment type {employment}"


def test_linkedin_criteria_of_a_posting_stored_without_them_come_from_its_text():
    meta = {"description": "Location: Warsaw\nSeniority level: Entry level\nEmployment type: Part-time\n\n"
                           "Employment type: Full-time later in the body is not read", "source": "api"}
    assert linkedin.LinkedIn().posting_facts(meta) == {
        "level": ("junior", "LinkedIn: Seniority level Entry level"),
        "worktime": ("part_time", "LinkedIn: Employment type Part-time")}
    assert Board.posting_facts(linkedin.LinkedIn(), meta) == {} == linkedin.LinkedIn().posting_facts({})


def test_linkedin_remote_all_is_sent_as_remote_phrases():
    reqs, warns = requests("linkedin")
    assert [r.keyword for r in reqs] == list(countries.get("pl").linkedin_remote_phrases)
    assert all(r.params == {"country": "pl"} and r.pushed == {"keyword"} for r in reqs)   # the mode stays unknown
    assert "sent as the phrases remote, zdalnie" in warns[0]
    assert [r.keyword for r in requests("linkedin", Where(remote=True, country="de"))[0]] == list(countries.get("de").linkedin_remote_phrases)
    # phrases, a city and "anywhere" are left alone; "city or remote" sends phrases only for its remote part
    assert [r.keyword for r in requests("linkedin", keywords=("n8n",))[0]] == ["n8n"]
    assert [r.keyword for r in requests("linkedin", Where())[0]] == [None]
    both, _ = requests("linkedin", Where(remote=True, city="Kraków"))
    assert [(r.keyword, r.params.get("city")) for r in both] == [(None, "Kraków")] + [(p, None) for p in countries.get("pl").linkedin_remote_phrases]


def test_linkedin_split_by_region_then_city(monkeypatch):
    li = REGISTRY["linkedin"]
    assert li.caps.result_cap == 1000 and li.total("", Request("linkedin", "t", None)) is None
    places = ["Warsaw, Mazowieckie, Poland"] * 12 + ["Otwock, Mazowieckie, Poland"] * 3 + [
        "Opole, Opolskie, Poland", "Bydgoszcz Metropolitan Area", "", "Poland"]
    seen = [Offer(board="linkedin", key=f"k{i}", url="u", title="t", locations=[p] if p else []) for i, p in enumerate(places)]
    r = Request("linkedin", "t", None, {"country": "pl"})
    regions = li.split("", r, seen)
    assert [x.params for x in regions] == [{"country": "pl", "region": "Mazowieckie"}, {"country": "pl", "region": "Opolskie"}]
    cities = li.split("", regions[0], seen)                           # a capped region: its cities seen >= MIN_CITY times
    assert [x.params for x in cities] == [{"country": "pl", "region": "Mazowieckie", "city": "Warsaw"}]
    assert li.split("", cities[0], seen) == []                        # a city is not narrowed
    country_level = [Offer(board="linkedin", key=f"p{i}", url="u", title="t", locations=["Poland"]) for i in range(2)]
    assert li.split("", r, seen + country_level) == []                # 3 of 21 at country level: parts repeat them
    monkeypatch.setattr(linkedin, "geo_id", lambda place, cc: {"Mazowieckie": "102996679", "Warsaw": "105076658"}.get(place))
    assert "geoId=102996679" in li.page_url(regions[0], 1) and "geoId=105076658" in li.page_url(cities[0], 3)
    assert "location=Opolskie" in li.page_url(regions[1], 1)          # no geoId: free text


def test_linkedin_newest_window_7_days_then_24_hours():
    li = REGISTRY["linkedin"]
    r = Request("linkedin", "t", "remote", {"country": "pl"})
    week, label = li.newest(r)
    assert (week.params, label) == ({"country": "pl", "posted_days": 7}, "7 days")
    day, label = li.newest(week)
    assert (day.params, label) == ({"country": "pl", "posted_days": 1}, "24 hours")
    assert li.newest(day) is None and week.key != r.key != day.key
    assert "f_TPR=r604800" in li.page_url(week, 1) and "f_TPR=r86400" in li.page_url(day, 1)
    assert crawler.probe_page(li, None, 100) == 100                   # start=990, the last page LinkedIn serves
    assert crawler.probe_page(li, None, 99) == 0                      # --limit-pages below it: no probe


# bulldogjob

def test_bulldogjob_modes_worktime_and_errors():
    node = json.loads(fixture("bulldogjob").read_text())["data"]["searchJobs"]["nodes"][0]

    def one(**kw):
        return parse("bulldogjob", json.dumps({"data": {"searchJobs": {"nodes": [dict(node, **kw)]}}}))[0]
    assert one(workModes=["on-site", "hybrid"], remote=False).mode == "hybrid"
    assert one(workModes=["on-site"], remote=False).mode == "onsite"
    assert one(workModes=["on-site", "full-remote"]).mode == "remote"
    assert one(employmentType="freelance").worktime == "flexible" and one(employmentType="contractor").worktime == "unknown"
    for raw in (json.dumps({"errors": [{"message": "x"}]}), ""):
        with pytest.raises(ValueError):
            parse("bulldogjob", raw)


# gowork

def test_gowork_parses_own_postings_and_skips_copies():
    assert "/oferta-zewnetrzna/" in fixture("gowork").read_text()      # copies of other sites' ads
    assert all(o.key == o.url and o.url.startswith("https://www.gowork.pl/oferta/") for o in parse("gowork"))
    with pytest.raises(ValueError):
        parse("gowork", "<html>blocked</html>")


def test_gowork_requests_and_phrases_starting_with_praca():
    """Page 1 of a `/praca/praca...;st` search redirects to itself: the leading word "praca" is dropped."""
    assert [r.params for r in requests("gowork")[0]] == [{"remote": True}]
    reqs, warns = requests("gowork", Where())
    assert not reqs and warns                                          # 26 000 offers without a keyword or a city
    assert [gowork.keyword_slug(p) for p in ("praca dodatkowa", "Praca  zdalna", "praca praca biurowa", "pracownik biurowy")] \
        == ["dodatkowa", "zdalna", "biurowa", "pracownik-biurowy"]
    assert gowork.keyword_slug("praca") == gowork.keyword_slug("pracadodatkowa") == ""
    assert "/praca/dodatkowa;st" in REGISTRY["gowork"].page_url(Request("gowork", "t", "praca dodatkowa", {"remote": True}), 1)
    reqs, warns = requests("gowork", keywords=("praca dodatkowa", "praca", "helpdesk"))
    assert [r.keyword for r in reqs] == ["praca dodatkowa", "helpdesk"]
    assert len(warns) == 1 and "'praca'" in warns[0] and "skipped for 's'" in warns[0]


# indeed

@pytest.mark.parametrize("card,mode", [
    ({"tags": {"remote": ["Hybrydowo", "Zdalnie"]}, "mode": "REMOTE_ALWAYS"}, "hybrid"),   # both tags with a place
    ({"tags": {"remote": ["Hybrydowo", "Zdalnie"]}, "remote_location": True, "mode": "REMOTE_ALWAYS"}, "remote"),
    ({"mode": "REMOTE_HYBRID"}, "hybrid"),
])
def test_indeed_work_mode(card, mode):
    assert indeed.work_mode(card) == mode


def test_indeed_posting_from_embedded_description():
    b = REGISTRY["indeed"]
    meta = b.posting(fixture("indeed", "_posting").read_text())
    text = meta["description"]
    assert meta["source"] == "board" and text and "cookie" not in text.lower() and "\\u003C" not in text and "<p>" not in text
    assert indeed.posting_text("<html>no data</html>") == "" and "description" not in b.posting("<html></html>")


# justjoin.it and rocketjobs.pl (one engine)

def offer_json(slug, types, working="full_time"):
    return {"slug": slug, "title": "Dev", "companyName": "ACME", "workplaceType": "remote", "workingTime": working,
            "experienceLevel": "mid", "city": "Kraków", "multilocation": [{"city": "Kraków"}], "requiredSkills": ["Python"],
            "publishedAt": "2026-11-08T06:25:09Z", "lastPublishedAt": "2026-11-12T09:47:04Z", "employmentTypes": types}


def pay_types(kind, lo, hi, currency, unit="month", gross=False):
    original = {"from": lo, "to": hi, "currency": currency, "currencySource": "original", "type": kind, "unit": unit, "gross": gross}
    converted = {**original, "from": lo and lo * 4, "to": hi and hi * 4, "currency": "PLN" if currency != "PLN" else "EUR",
                 "currencySource": "conversion"}
    return [original, converted]


def rsc(offers, tail=""):
    """The offers as the RSC chunk of a justjoin page escapes them."""
    return json.dumps({"offers": offers}, separators=(",", ":")).replace("\\", "\\\\").replace('"', '\\"') + tail


def test_justjoin_extract_offers_handles_escapes_and_truncation():
    offers = [{"slug": "a-b", "title": 'Quote " and ] bracket'}, {"slug": "c", "title": "x"}]
    assert extract_offers(rsc(offers, '\\",\\"other\\":[1,2]')) == offers
    assert extract_offers("") == []
    assert extract_offers('{\\"offers\\":[{\\"slug\\":\\"a') is None
    with pytest.raises(ValueError):
        parse("justjoin", '{\\"offers\\":[{\\"slug\\":\\"a')


@pytest.mark.parametrize("board", ["justjoin", "rocketjobs"])
def test_justjoin_capped_listing_splits_by_level_then_category(board):
    b, raw = REGISTRY[board], fixture(board).read_text()
    assert b.caps.result_cap == 10_000 and b.caps.max_pages == 200  # 200 pages of 50, page 201 is a 404
    r = Request(board, "t", None, {"sort": "newest"})
    assert b.total(raw, r) >= b.caps.result_cap  # the page's count (an upper bound of the results)
    levels = b.split(raw, r)
    assert len(levels) > 1 and all(s.params["sort"] == "newest" and s.params["level"] for s in levels)
    cats = b.split(raw, levels[2])
    assert len(cats) > 1 and {s.params["level"] for s in cats} == {levels[2].params["level"]}
    assert b.split(raw, cats[0]) == []  # level and category set: cannot be narrowed further
    assert b.total(rsc([]), r) is None  # an older recording (the offers slice alone) has no count


def test_justjoin_pay_in_original_currency_per_contract():
    eur, pln, anyc = parse("justjoin", rsc([
        offer_json("acme-dev-krakow-python", pay_types("b2b", 700, 800, "EUR")),
        offer_json("acme-dev2-krakow-python", pay_types("b2b", 130, 170, "PLN", "hour")
                   + pay_types("permanent", 15000, 17500, "PLN", gross=True)),
        offer_json("acme-dev3-krakow-c", pay_types("any", None, None, "PLN"))]))
    assert eur.pay_text == "b2b:700-800 EUR/month" and eur.contracts == ["b2b"]  # the PLN conversion is not the pay
    assert pln.pay_text == "b2b:130-170 PLN/hour; permanent:15000-17500 PLN/month gross"
    assert pln.contracts == ["b2b", "employment"]
    assert anyc.pay_text == "" and anyc.contracts == []  # "Any": no particular contract, not "other"
    assert str(eur.published) == "2026-11-08"  # publishedAt, what the offer page shows


def test_rocketjobs_internship_work_time():
    (o,) = parse("rocketjobs", rsc([offer_json("acme-staz-lodz-finanse", pay_types("internship", 3000, 4000, "PLN"),
                                               working="internship")]))
    assert o.worktime == "part_time" and o.contracts == ["internship"] and o.url.startswith("https://rocketjobs.pl/")


# nofluffjobs

def nfj_posting(url, ref, city="Remote", salary=None):
    return {"id": url, "url": url, "reference": ref, "title": " Python Dev ", "name": "ACME", "category": "backend",
            "seniority": ["Mid"], "posted": 1794231934738, "renewed": 1794491134738,
            "location": {"places": [{"city": city, "url": url}], "fullyRemote": city == "Remote",
                         "type": "remote" if city == "Remote" else "hybrid"},
            "salary": salary or {"from": 100.0, "to": 200.0, "type": "b2b", "currency": "PLN", "period": "Month"},
            "tiles": {"values": [{"type": "requirement", "value": "Python"}]}}


def test_nofluffjobs_cards():
    offers = parse("nofluffjobs", json.dumps({"postings": [   # an "anywhere" page lists a job once per place
        nfj_posting("dev-acme-remote", "R1"), nfj_posting("dev-acme-masovian", "R1"),
        nfj_posting("dev-acme-krakow", "R2", city="Kraków"), nfj_posting("dev-acme-warszawa", "R2", city="Warszawa"),
        nfj_posting("a", "A", salary={"from": 4850.0, "type": "permanent", "currency": "PLN", "period": "Month",
                                      "flexibleUpperBound": True}),
        nfj_posting("b", "B", salary={"type": "b2b", "period": "Month", "containsSalary": "NOT_PROVIDED"})]}), "python")
    remote, krakow, a, b = offers                                       # one entry per reference
    assert [o.url.rsplit("/", 1)[1] for o in (remote, krakow)] == ["dev-acme-remote", "dev-acme-krakow"]
    assert remote.mode == "remote" and krakow.mode == "hybrid" and krakow.locations == ["Kraków"]
    assert remote.title == "Python Dev" and remote.level == "mid" and remote.skills == ["Python"]
    assert a.pay_text == "permanent:4850-4850 PLN/month" and a.contracts == ["employment"]   # open-ended: its floor
    assert b.pay_text == "" and b.contracts == ["b2b"]


def test_nofluffjobs_posting_api():
    b = REGISTRY["nofluffjobs"]
    assert b.posting_url("https://nofluffjobs.com/pl/job/dev-acme-krakow").endswith("/dev-acme-krakow")
    assert b.posting_url("https://example.com/job/x") is None
    raw = {"posted": 1794221376916, "company": {"name": "ACME "},
           "details": {"description": "<p>About us</p>"},
           "requirements": {"description": "<ul><li>3 years of Python</li></ul>", "musts": [{"value": "Python"}],
                            "nices": [{"value": "Docker"}], "languages": [{"type": "MUST", "code": "en", "level": "B2"}]},
           "specs": {"dailyTasks": ["Write code"]}, "location": {"hybridDesc": "Hybrid 1 day Office / 4 days Remote"},
           "essentials": {"originalSalary": {"currency": "PLN", "types": {"b2b": {"period": "Day", "range": [1400.0, 1800.0]},
                                                                          "permanent": {"period": "Month", "range": [20000.0, 25000.0]}}}}}
    text, meta = b.posting_text(json.dumps(raw))
    for part in ("About us", "3 years of Python", "Must have: Python", "Nice to have: Docker", "Languages: English B2 (required)",
                 "• Write code", "Work mode: Hybrid 1 day", "Contract: b2b 1400-1800 PLN/day", "Contract: permanent 20000-25000 PLN/month"):
        assert part in text, part
    assert meta == {"company": "ACME", "published": "2026-11-09"}


# olx

def test_olx_work_mode_company_and_pay():
    assert olx.work_mode(["remote_work_possibility"]) == olx.work_mode(["remote_work_possibility", "traveling"]) == "remote"
    assert olx.work_mode(["hybrid", "remote_work_possibility"]) == olx.work_mode(["on_site", "remote_work_possibility"]) == "hybrid"
    assert olx.work_mode(["on_site"]) == "onsite" and olx.work_mode([]) == "unknown"
    assert olx.company({"company_name": "", "name": "Filip"}) == ""  # a recruiter's first name
    assert olx.company({"company_name": "", "name": "IGS SCHREINER POLSKA SP. Z O.O."}) == "IGS SCHREINER POLSKA SP. Z O.O."
    assert olx.pay_text(None) == "" and olx.pay_text({"from": 0, "to": 0}) == ""


def test_olx_capped_listing_splits_into_the_page_categories():
    b = REGISTRY["olx"]
    page = json.dumps({"total": 1000, "ads": [], "categories": [
        {"path": "praca", "parent": ""}, {"path": "praca/hr", "parent": "praca"},
        {"path": "praca/informatyka", "parent": "praca"}, {"path": "praca/informatyka/qa", "parent": "praca/informatyka"}]})
    r = Request("olx", "all", None, {"remote": True, "sort": "newest"})
    assert b.caps.result_cap == 1000 and b.total(page, r) == 1000
    subs = b.split(page, r)
    assert [s.params["category"] for s in subs] == ["hr", "informatyka"] and all(s.params["remote"] for s in subs)
    assert [s.params["category"] for s in b.split(page, subs[1])] == ["informatyka/qa"]   # a capped subcategory splits again
    assert "/praca/hr/" in b.page_url(subs[0], 2)
    assert "/praca/hr/krakow/" in b.page_url(Request("olx", "c", None, {"city": "Kraków", "radius_km": 30, "category": "hr"}), 1)
    assert parse("olx", "[]", **r.params) == [] and b.total("[]", r) is None   # older shrunk pages: a bare list


# praca.pl

def test_pracapl_relative_dates_and_levels():
    today = dt.date(2026, 11, 12)
    assert pracapl.edition_day("Numer wydania: 20769&nbsp;/&nbsp;2026") == today
    assert [pracapl.published(s, today) for s in ("przed chwilą", "23 godzin temu", "1 godzinę temu", "wczoraj", "9 dni temu")] == \
        [today, today, today, today - dt.timedelta(1), today - dt.timedelta(9)]
    assert pracapl.published("wczoraj", None) is None and pracapl.published("03.11.2026", None) == dt.date(2026, 11, 3)
    assert pracapl.level("Praktykant / praktykantka / stażysta / stażystka / asystent / asystentka") == "intern"
    assert pracapl.level("Specjalista / specjalistka (mid) / starszy specjalista / starsza specjalistka (senior)") == "mid"
    assert pracapl.level("Pracownik fizyczny / pracowniczka fizyczna") == "unknown"


def test_pracapl_empty_search_and_other_sections_yield_nothing():
    card = '<li class="listing-v2__item" data-ad-id="1"><a class="listing-v2__title" href="https://www.praca.pl/x_11.html">X</a></li>'
    assert parse("pracapl", '<div class="al__no-offers-block gtm-empty-listing"></div>' + card, "zzz") == []
    assert parse("pracapl", '<h2 class="listing-v2__header">Zobacz najnowsze oferty pracy</h2>' + card, "zzz") == []
    assert len(parse("pracapl", '<h2 class="listing-v2__header">Oferty urzędu pracy</h2>' + card, "zzz")) == 1


# pracuj.pl

def test_pracuj_only_keyword_free_listings_are_newest_first():
    reqs, _ = requests("pracuj", keywords=("python",))
    assert reqs and all("sort" not in r.params for r in reqs)  # keyword listings are by relevance
    assert [r.params.get("sort") for r in requests("pracuj")[0]] == ["newest"]
    reqs, _ = requests("pracuj", worktime=frozenset({"part_time"}))
    assert reqs[0].params.get("part_time") and "worktime" in reqs[0].pushed


def test_pracuj_published_is_the_posting_date_and_refreshed_offers_are_promoted():
    raw = json.loads(fixture("pracuj").read_text())["offers"]
    parsed = {o.key: o for o in parse("pracuj")}
    for g in raw:
        o = parsed[sorted(x["url"] for x in g["offers"])[0]]
        assert o.published.isoformat() == g["initialPublicated"][:10]
        assert o.promoted == (g["initialPublicated"][:10] != g["lastPublicated"][:10])
    assert any(o.promoted for o in parsed.values()) and not all(o.promoted for o in parsed.values())


def test_pracuj_posting_reads_the_sections_not_the_blurb():
    meta = REGISTRY["pracuj"].posting(fixture("pracuj", "_posting").read_text())
    assert meta["source"] == "board" and meta["company"]                  # JSON-LD fields are kept
    assert "Twój zakres obowiązków\n• " in meta["description"] and "Przejdź do treści" not in meta["description"]


# solid.jobs

def sj_offer(i, primary, secondary=None, workload="100%", remote="Hybrydowo"):
    return {"id": i, "jobOfferUrl": f"acme-{i}", "jobTitle": "Dev", "companyName": "ACME", "companyCity": "Kraków",
            "remotePossible": remote, "workload": workload, "experienceLevel": "Regular", "mainCategory": "Programista",
            "subCategory": "Python", "validFrom": "2026-10-12T15:52:04+02:00", "requiredSkills": [{"name": "Python"}],
            "salaryRange": primary, "secondarySalaryRange": secondary}


def sj_range(kind, lo, hi):
    return {"lowerBound": lo, "upperBound": hi, "currency": "PLN", "employmentType": kind, "salaryPeriod": "Month"}


def test_solidjobs_both_pay_ranges_and_contracts():
    a, b, c, d = parse("solidjobs", json.dumps([
        sj_offer(1, sj_range("B2B", 28600.0, 35300.0), sj_range("Umowa o pracę", 20000.0, 26000.0)),
        sj_offer(2, sj_range("Umowa o staż", 3000.0, 4000.0), workload="50%", remote="Możliwa częściowo"),
        sj_offer(3, sj_range("Umowa o dzieło", 5000.0, 6000.0), workload="Praca projektowa", remote="Stacjonarnie lub zdalnie"),
        sj_offer(4, sj_range("Umowa zlecenie", 0, 0), workload="75%", remote="Brak")]), division="it")
    assert a.pay_text == "b2b:28600-35300 PLN/month; permanent:20000-26000 PLN/month gross" and a.contracts == ["b2b", "employment"]
    assert (a.mode, a.worktime, a.level, str(a.published)) == ("hybrid", "full_time", "mid", "2026-10-12")
    assert (b.contracts, b.worktime, b.mode) == (["internship"], "part_time", "hybrid")
    assert (c.contracts, c.worktime, c.mode) == (["specific_task"], "flexible", "remote")
    assert (d.contracts, d.pay_text, d.worktime, d.mode) == (["mandate"], "", "part_time", "onsite")
    assert sorted(r.params["division"] for r in requests("solidjobs")[0]) == sorted(REGISTRY["solidjobs"].divisions)


# theprotocol.it

def test_theprotocol_cards():
    data = json.loads(fixture("theprotocol").read_text())
    first = dict(data["offers"][0], contracts=[
        {"id": 6, "salary": {"from": 30, "to": 35, "currencySymbol": "zł", "timeUnit": {"longForm": "hourly"}, "kindName": "gross"}},
        {"id": 4, "salary": None}, {"id": 5, "salary": None}])
    offers = [dict(o, published=p) for o, p in zip([first] + data["offers"][1:3],
                                                  ("2026-11-12T10:00:00", "2026-10-01T10:00:00", "2026-11-11T10:00:00"))]
    got = parse("theprotocol", json.dumps(dict(data, offers=offers)))
    assert got[0].contracts == ["temp_agency", "employment", "other"] and got[0].pay_text == "temp_agency:30-35 PLN/hour gross"
    assert [o.promoted for o in got] == [False, True, False]            # older than a later one: promoted
    with pytest.raises(ValueError):                                     # a throttled keyword answer is an error
        parse("theprotocol", json.dumps({"total": 0, "page": {}, "keywords": [], "offers": []}), "python")
    assert parse("theprotocol", json.dumps({"total": 0, "page": {}, "keywords": ["asystent"], "offers": []}), "asystent") == []


# useme.com

def test_useme_open_projects_and_requests():
    raw, got = fixture("useme").read_text(), parse("useme")
    assert len(got) == raw.count("<article") - raw.count("Zakończone")             # closed projects are dropped
    assert all(o.company and o.category and o.mode == "remote" and o.pay_period == "project" for o in got)
    assert any(o.pay_text.endswith("PLN") for o in got) and any(not o.pay_text and "Do negocjacji" in o.snippet for o in got)
    reqs, warns = requests("useme")                                            # everything without a phrase
    assert [(r.keyword, r.params) for r in reqs] == [(None, {"sort": "newest"})] and not warns
    caps = REGISTRY["useme"].caps   # open cards per page vary: only an empty page ends a request; ~35 pages (2026-11-12)
    assert caps.page_size == 0 and caps.max_pages >= 35 * 2
    assert REGISTRY["useme"].page_url(reqs[0], caps.max_pages + 1)   # never None: a request stopped there is partial


# bundesagentur

def test_bundesagentur_requests():
    b, de = REGISTRY["bundesagentur"], dict(remote=True, country="de")
    (remote,), _ = requests("bundesagentur", Where(**de), max_age_days=10)
    assert "was=Homeoffice" in b.page_url(remote, 1) and "veroeffentlichtseit=14" in b.page_url(remote, 1)   # no remote filter
    (city,), _ = requests("bundesagentur", Where(city="Köln", radius_km=20, country="de"), ("Kundenservice",),
                          worktime=frozenset({"part_time"}))
    url = b.page_url(city, 2)
    assert "wo=K%C3%B6ln" in url and "umkreis=20" in url and "arbeitszeit=tz%3Bmj" in url and "page=2" in url
    assert "Homeoffice" not in url
    reqs, warns = requests("bundesagentur", Where(country="de"))
    assert not reqs and "too large" in warns[0]
