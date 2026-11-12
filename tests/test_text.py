"""Reading text: pay, the offer's fields from its card and posting (infer, lang packs), JSON-LD postings, hints."""
import json

import pytest

from conftest import FIXTURES
from neetscape import infer
from neetscape.model import Offer
from neetscape.pay import DEFAULT_FX, parse_pay
from neetscape.posting import parse_posting

DE_FX = {"EUR": 1.0, "PLN": 0.233, "USD": 0.93}
DE = dict(fx=DE_FX, base="EUR", hours=173)
EUR = dict(fx=DE_FX, base="EUR")
ASSUME = dict(fx=DE_FX, base="EUR", assume="EUR")


@pytest.mark.parametrize("text,opts,expected", [
    ("b2b:12000-18000/month; permanent:9000-12000/month gross", {}, (12000, 18000)),
    ("b2b:125-145/hour", {}, (21000, 24360)),
    ("200–250 zł / godz. (B2B)", {}, (33600, 42000)),
    ("8.3k–14.1k zł / mies. (UoP)", {}, (8300, 14100)),
    ("35 – 55 PLN brutto godzinowo", {}, (5880, 9240)),
    ("PLN 10,000.00/mo - PLN 15,000.00/mo", {}, (10000, 15000)),
    ("3 000 - 4 000 EUR", {}, (12900, 17200)),
    ("1 200 – 1 440 PLN / dzień", {}, (25200, 30240)),
    ("permanent:272600-344900/year gross", {}, (22717, 28742)),
    ("$80,000 - $100,000", {}, (26667, 33333)),
    ("45.000–55.000 €", {}, (16125, 19708)),                # a German yearly salary in a PLN database
    ("4,5-6,5 tys. zł", {}, (4500, 6500)),                  # "tys." = thousand, not an hourly 4.5
    ("8 tys. zł brutto", {}, (8000, 8000)),
    ("1500-2000 zł/tydzień", {}, (6500, 8667)),             # weekly ("tydzień" contains "dzień"): 52/12 weeks a month
    ("b2b:800-1100 PLN/month", {}, (800 * 21, 1100 * 21)),  # a B2B "monthly" range this low is a day rate
    ("mandate:1700-1700 PLN/month", {}, (1700, 1700)),      # a small part-time mandate stays monthly
    ("Senior Python 2024 tech 5+ years", {}, None),
    ("ok 300 zł", {}, None),
    ("", {}, None),
    ("45.000–55.000 €", DE, (3750, 4583)),                  # bare German yearly salary
    ("45.000 - 55.000 € brutto/Jahr", DE, (3750, 4583)),
    ("3.000 bis 3.500 € monatlich", DE, (3000, 3500)),
    ("13,50 €/Std.", DE, (2336, 2336)),                     # 173 h
    ("15 € pro Stunde", DE, (2595, 2595)),
    ("Jahresgehalt 60000-75000 EUR", DE, (5000, 6250)),
    ("650 € Tagessatz", DE, (13650, 13650)),
    ("65000-110000 EUR/Jahr", DE, (5417, 9167)),
    ("520 €", DE, (520, 520)),                              # mini job
    ("2.800 brutto", DE, None),                             # no currency, nothing assumed
    ("800 € pro Woche", EUR, (3467, 3467)),
    ("2.800 brutto pro Monat", ASSUME, (2800, 2800)),       # an assumed currency only next to pay words
    ("Gründung 1998, 2500 Mitarbeitende", ASSUME, None),
    ("b2b:3000-4000/month", ASSUME, (3000, 4000)),
])
def test_parse_pay(text, opts, expected):
    opts = dict(opts)
    assert parse_pay(text, opts.pop("fx", None), **opts) == expected


def test_lang_packs_are_per_country():
    # "kontrakt"/"B2B" mean b2b for Polish boards only
    assert infer.contracts_from_text("B2B-Vertrieb", ("de", "en")) == []
    assert infer.contracts_from_text("B2B", ("pl", "en")) == ["b2b"]
    assert infer.mode_from_text("Homeoffice möglich", ("de", "en")) == "hybrid"
    assert infer.mode_from_text("Home office", ("pl", "en")) == "remote"


def test_fill_reads_text_where_the_board_says_nothing():
    o = Offer(board="olx", key="k", url="k", title="Junior asystent (praca zdalna)", pay_text="4 800 - 5 800 zł / mies.",
              snippet="Praca dodatkowa Umowa zlecenie", worktime="unknown")
    infer.fill(o, DEFAULT_FX)
    assert (o.mode, o.worktime, o.level, o.pay_min, o.pay_max) == ("remote", "part_time", "junior", 4800, 5800)
    assert "mandate" in o.contracts and o.evidence["mode"][0] == "card"
    board_data = Offer(board="justjoin", key="k", url="k", title="Junior (remote)", mode="hybrid")
    infer.fill(board_data, DEFAULT_FX)
    assert board_data.mode == "hybrid" and board_data.facts == {"mode": "hybrid"}  # board data wins over text
    assert board_data.evidence["mode"] == ["board", "board data"]
    found_remote = Offer(board="pracuj", key="k", url="k", title="Asystent", snippet="hybrydowo")
    infer.fill(found_remote, DEFAULT_FX, request_remote=True)
    assert found_remote.mode == "remote"  # the board's own remote filter beats card words


@pytest.mark.parametrize("posting,kw,expected", [
    ("Wsparcie użytkowników zdalnie i na miejscu. Umowa o pracę, pełny etat.", {},
     dict(mode="unknown", worktime="full_time", contracts="employment")),   # "zdalnie" alone does not settle the mode
    ("Praca w 100% zdalna.", {}, dict(mode="remote")),
    ("x", dict(posting_remote=True), dict(mode="remote")),                   # JSON-LD TELECOMMUTE
    ("Praca w 100% zdalna. Pełny etat, UoP", dict(facts={"mode": "onsite", "worktime": "part_time", "contracts": ["b2b"]}),
     dict(mode="onsite", worktime="part_time", contracts="b2b")),          # board data wins
    ("Firma z 37-letnim stażem. Doświadczenie z pracy lub staży mile widziane. Umowa o pracę.", {},
     dict(contracts="employment")),                                         # internship only when named in the title or a field
    ("Seniority level: Internship\nEmployment type: Internship", {}, dict(contracts="internship")),
    ("Oferujemy płatny staż.", dict(title="Stażysta w dziale IT"), dict(contracts="internship")),
])
def test_posting_settles_unknown_fields_from_strong_signals_only(posting, kw, expected):
    kw = {"title": "Junior SAP Consultant", "facts": {}, "posting_remote": False, **kw}
    got = infer.derive(card=kw["title"], posting=posting, languages=("pl", "en"), **kw)
    assert {k: got[k] for k in expected} == expected


def test_jsonld_posting():
    p = parse_posting((FIXTURES / "pl" / "justjoin_offer.html").read_text())
    assert p["company"] and p["published"] and len(p["description"]) > 200
    assert parse_posting("<html>no data</html>") == {}


def test_hints():
    h = infer.hints("Praca w 100% zdalna. Wymagamy 3+ lata doświadczenia, bachelor degree. German C1. hybrid possible")
    assert h["fully_remote"] and h["years"] and "degree" in h["degree"] and h["languages"] == ["german"] and h["hybrid"]


@pytest.mark.parametrize("title,category,languages,domains,function", [
    ("AI Gateway Product Owner", "", ("pl", "en"), {"ai", "product"}, "manage_project"),   # AI in any role
    ("AI Content Creator", "", ("en",), {"ai", "marketing"}, "market"),
    ("Logistics Support Specialist", "", ("pl", "en"), {"logistics"}, "support"),
    ("System Administrator", "", ("en",), {"tech"}, "administer"),             # the weak domain when alone
    ("IT System Administrator", "", ("en",), {"it"}, "administer"),            # ...and not beside another one
    ("Support Specialist", "IT support", ("en",), {"it"}, "support"),          # the board's category
    ("Engineer (AI/ML)", "", ("en",), {"ai"}, "engineer"),                     # the qualifier
    ("Konsultant", "", ("pl", "en"), set(), "consult"),
    ("Sachbearbeiter Buchhaltung", "", ("de", "en"), {"finance"}, "account"),
    ("Sachbearbeiter (m/w/d) Buchhaltung", "", ("de", "en"), {"finance"}, "account"),  # a gender marker is no qualifier
])
def test_job_domains_from_title_and_category(title, category, languages, domains, function):
    got = infer.derive(title=title, category=category, languages=languages)
    assert set(filter(None, got["job_domains"].split(","))) == domains and got["job_function"] == function
    evidence = json.loads(got["evidence"]).get("job_domains", {})
    assert set(evidence) == domains and all(len(why) == 2 for why in evidence.values())


def test_job_domains_ignore_the_posting_and_keep_the_single_field():
    got = infer.derive(title="AI Gateway Product Owner", posting="We build logistics software for retail.", languages=("en",))
    assert got["job_domains"] == "ai,product"
    assert (got["job_function"], got["job_domain"], got["job_field"]) == ("manage_project", "ai", "product_project")


def test_gender_markers_are_generic_and_qualifier_words_come_from_the_packs():
    def domains(title, langs):
        return json.loads(infer.derive(title=title, languages=langs)["evidence"])["job_domains"]
    assert domains("Specjalista (k/m) ds. IT", ("pl",)) == {"it": ["title", "IT"]}          # letters: any language
    assert domains("Data Engineer (all genders)", ("en",)) == {"data": ["title", "Data"]}   # English words
    assert domains("Support Specialist with AI", ("en",)) == {"ai": ["qualifier", "AI"]}   # "with" opens a qualifier
