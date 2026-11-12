"""test_pay.py"""
import pytest

from neetscape.pay import parse_pay


@pytest.mark.parametrize("text,expected", [
    ("b2b:12000-18000/month; permanent:9000-12000/month gross", (12000, 18000)),
    ("b2b:125-145/hour", (21000, 24360)),
    ("200–250 zł / godz. (B2B)", (33600, 42000)),
    ("8.3k–14.1k zł / mies. (UoP)", (8300, 14100)),
    ("35 – 55 PLN brutto godzinowo", (5880, 9240)),
    ("PLN 10,000.00/mo - PLN 15,000.00/mo", (10000, 15000)),
    ("3 000 - 4 000 EUR", (12900, 17200)),
    ("1 200 – 1 440 PLN / dzień", (25200, 30240)),
    ("permanent:272600-344900/year gross", (22717, 28742)),
    ("$80,000 - $100,000", (26667, 33333)),
    ("Senior Python 2024 tech 5+ years", None),
    ("ok 300 zł", None),
    ("", None),
])
def test_parse_pay(text, expected):
    assert parse_pay(text) == expected


DE_FX = {"EUR": 1.0, "PLN": 0.233, "USD": 0.93}


@pytest.mark.parametrize("text,expected", [
    ("45.000–55.000 €", (3750, 4583)),                 # bare German yearly salary
    ("45.000 - 55.000 € brutto/Jahr", (3750, 4583)),
    ("3.000 bis 3.500 € monatlich", (3000, 3500)),
    ("13,50 €/Std.", (2336, 2336)),                    # 173 h
    ("15 € pro Stunde", (2595, 2595)),
    ("Jahresgehalt 60000-75000 EUR", (5000, 6250)),
    ("650 € Tagessatz", (13650, 13650)),
    ("65000-110000 EUR/Jahr", (5417, 9167)),
    ("520 €", (520, 520)),                              # mini job
    ("2.800 brutto", None),                             # no currency, nothing assumed
])
def test_parse_pay_euro(text, expected):
    assert parse_pay(text, DE_FX, base="EUR", hours=173) == expected


def test_assumed_currency_only_next_to_pay_words():
    assert parse_pay("2.800 brutto pro Monat", DE_FX, base="EUR", assume="EUR") == (2800, 2800)
    assert parse_pay("Gründung 1998, 2500 Mitarbeitende", DE_FX, base="EUR", assume="EUR") is None
    assert parse_pay("b2b:3000-4000/month", DE_FX, base="EUR", assume="EUR") == (3000, 4000)


def test_euro_in_pln_database():
    # a Polish profile reading a German yearly salary: yearly by the EUR thresholds, converted to PLN
    assert parse_pay("45.000–55.000 €") == (16125, 19708)


@pytest.mark.parametrize("text,expected", [
    ("4,5-6,5 tys. zł", (4500, 6500)),                 # "tys." = thousand, not an hourly 4.5
    ("8 tys. zł brutto", (8000, 8000)),
    ("1500-2000 zł/tydzień", (6500, 8667)),            # weekly ("tydzień" contains "dzień"): 52/12 weeks a month
    ("800 € pro Woche", (3467, 3467)),
])
def test_thousands_words_and_weekly_rates(text, expected):
    fx, base = ({"EUR": 1.0}, "EUR") if "€" in text else (None, "PLN")
    assert parse_pay(text, fx, base=base) == expected
