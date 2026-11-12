"""Poland. Boards in `neetscape/countries/pl/boards/` (justjoin, rocketjobs, pracuj, ...); LinkedIn serves it too."""
from ...country import Country

COUNTRY = Country(
    code="pl", name="Poland", currency="PLN",
    fx={"PLN": 1.0, "EUR": 4.3, "USD": 4.0, "GBP": 5.1, "CHF": 4.6},
    languages=("pl", "en"), hours_per_month=168, days_per_month=21,
    linkedin_location="Poland", place_names=("Polska", "Poland"),
    city_aliases={"warszawa": ("warsaw",), "krakow": ("cracow",), "wroclaw": ("breslau",), "gdansk": ("danzig",),
                  "poznan": ("posen",), "lodz": ("lodsch",)},
    legal_suffixes=(r"sp\.? ?z\.? ?o\.? ?o\.?", r"spolka z ograniczona odpowiedzialnoscia", r"s\.?a\.?", r"sp\.? ?k\.?",
                    "polska", "poland"),
    contracts=("employment", "b2b", "mandate", "specific_task", "internship", "freelance", "other"),
    contract_aliases={"uop": "employment", "umowa o pracę": "employment", "umowa o prace": "employment", "coe": "employment",
                      "uz": "mandate", "umowa zlecenie": "mandate", "zlecenie": "mandate", "uod": "specific_task",
                      "umowa o dzieło": "specific_task", "staż": "internship", "praktyki": "internship"},
    default_boards=("pl",),
)
