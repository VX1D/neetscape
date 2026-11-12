"""Germany. Boards: Arbeitnow (JSON API), Bundesagentur für Arbeit Jobsuche (REST API); LinkedIn serves it too."""
from ...country import Country

COUNTRY = Country(
    code="de", name="Germany", currency="EUR",
    fx={"EUR": 1.0, "PLN": 0.233, "USD": 0.93, "GBP": 1.19, "CHF": 1.07},
    languages=("de", "en"), hours_per_month=173, days_per_month=21,
    linkedin_location="Germany", place_names=("Deutschland", "Germany"),
    city_aliases={"munchen": ("munich", "muenchen"), "koln": ("cologne", "koeln"), "nurnberg": ("nuremberg", "nuernberg"),
                  "dusseldorf": ("duesseldorf",), "frankfurt am main": ("frankfurt",), "hannover": ("hanover",),
                  "braunschweig": ("brunswick",), "gottingen": ("goettingen",), "lubeck": ("luebeck",),
                  "saarbrucken": ("saarbruecken",), "wurzburg": ("wuerzburg",), "munster": ("muenster",)},
    legal_suffixes=(r"gmbh ?& ?co\.? ?kg(?:aa)?", "gmbh", r"mbh", r"ag", r"kgaa", r"kg", r"ohg", r"ug(?: \(haftungsbeschrankt\))?",
                    r"e\.? ?k\.?", r"e\.? ?v\.?", "se", "deutschland", "germany"),
    contracts=("employment", "mini_job", "working_student", "internship", "freelance", "temp_agency", "other"),
    contract_aliases={"festanstellung": "employment", "unbefristet": "employment", "arbeitsvertrag": "employment",
                      "minijob": "mini_job", "geringfügig": "mini_job", "werkstudent": "working_student",
                      "werkstudentin": "working_student", "praktikum": "internship", "freiberuflich": "freelance",
                      "freelancer": "freelance", "selbstständig": "freelance", "zeitarbeit": "temp_agency",
                      "arbeitnehmerüberlassung": "temp_agency"},
    default_boards=("de",),
)
