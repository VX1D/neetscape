"""German.

Traps: "Homeoffice möglich", "teilweise Homeoffice", "mobiles Arbeiten" and "remote möglich" mean some days at
home (hybrid); only phrases such as "100% Homeoffice", "vollständig/komplett remote" or "deutschlandweit remote"
mean fully remote. "Befristet" (fixed-term) is a hint, not a contract type; "unbefristet" is a permanent
employment contract. "B2B" in German postings is usually a sales segment ("B2B-Vertrieb"), not a contract.
"""

_HO = r"home[- ]?office"

VOCAB = {
    "first": {
        "mode": [
            ("remote", rf"100\s*%\s*(?:{_HO}|remote|mobil\w*)"),
            ("remote", rf"(?:vollständig|komplett|ausschließlich|voll|zu 100\s*%)\s+(?:im\s+)?(?:{_HO}|remote|mobil\w*)"),
            ("remote", r"deutschlandweit\s+remote|remote\s*\(deutschlandweit\)|full[- ]?remote|fully remote"),
            ("hybrid", rf"{_HO}[- ]?(?:möglich|option|anteil\w*)|teilweise\s+(?:im\s+)?(?:{_HO}|remote|mobil\w*)"),
            ("hybrid", rf"mobiles?\s+arbeiten|remote[- ]möglich|\d+\s*(?:tage?|x)\s*(?:pro woche\s*|/\s*woche\s*)?(?:im\s+|vom\s+)?(?:{_HO}|remote|mobil)"),
        ],
    },
    "mode": {
        "remote": [r"heim-?\s?/\s?telearbeit", r"telearbeit"],
        "hybrid": [_HO, r"hybrid"],
        "onsite": [r"\bvor ort\b", r"präsenz", r"im büro"],
    },
    "worktime": {
        "part_time": [r"teilzeit", r"minijob", r"geringfügig", r"werkstudent", r"aushilfe", r"nebenjob"],
        "flexible": [r"freiberuflich", r"flexible arbeitszeit"],
        "full_time": [r"vollzeit"],
    },
    "contract": {
        "employment": [r"festanstellung", r"(?<![a-zäöü])unbefristet", r"sozialversicherungspflichtig", r"fest angestellt"],
        "mini_job": [r"minijob", r"geringfügig\w* beschäftig", r"(?:520|538|556)\s*(?:€|euro)?[- ]?basis"],
        "working_student": [r"werkstudent"],
        "internship": [r"praktikum", r"praktikant"],
        "freelance": [r"freiberuflich", r"freelancer", r"selbstständig\w* tätig"],
        "temp_agency": [r"zeitarbeit", r"arbeitnehmerüberlassung", r"personaldienstleist", r"\baü\b"],
    },
    "level": {
        "intern": [r"praktikant", r"werkstudent"],
        "junior": [r"berufseinsteiger", r"\beinsteiger"],
        "lead": [r"teamleit", r"teamlead"],
        "manager": [r"leiter", r"leitung", r"geschäftsführ"],
        "mid": [r"sachbearbeiter", r"fachkraft", r"referent"],
    },
    "hints": {
        "fully_remote": [rf"100\s*%\s*(?:{_HO}|remote)", rf"(?:vollständig|komplett|ausschließlich)\s+(?:im\s+)?(?:{_HO}|remote)",
                         r"deutschlandweit\s+remote"],
        "hybrid": [rf"{_HO}[- ]möglich", rf"teilweise\s+(?:im\s+)?{_HO}", r"mobiles?\s+arbeiten",
                   r"\d+\s*tage?\s*(?:pro woche\s*)?(?:im büro|vor ort)"],
        "years": [r"\d+\+?\s*(?:-\s*\d+\s*)?jahre?n?\s*(?:\w+\s){0,2}?berufserfahrung", r"mehrjährige\w* berufserfahrung"],
        "degree": [r"hochschulabschluss", r"abgeschlossene\w* (?:\w+)?studium", r"abgeschlossene\w* (?:berufs)?ausbildung"],
        "languages": [r"\bdeutsch(?:kenntniss\w*)?\b", r"fließend\w* deutsch", r"\benglisch(?:kenntniss\w*)?\b",
                      r"\b(?:französisch|polnisch|niederländisch|italienisch|spanisch)\w*\b"],
        "fixed_term": [r"(?<![a-zäöü])befristet", r"zeitlich begrenzt"],
    },
}

EXAMPLES = [
    ("Homeoffice möglich", "mode", "hybrid"),
    ("Teilweise Homeoffice, Standort München", "mode", "hybrid"),
    ("Mobiles Arbeiten nach Absprache", "mode", "hybrid"),
    ("2 Tage pro Woche im Homeoffice", "mode", "hybrid"),
    ("Remote möglich", "mode", "hybrid"),
    ("100% Homeoffice", "mode", "remote"),
    ("Vollständig remote", "mode", "remote"),
    ("Komplett remote aus ganz Deutschland", "mode", "remote"),
    ("Deutschlandweit remote", "mode", "remote"),
    ("Heim-/Telearbeit", "mode", "remote"),
    ("Arbeit vor Ort in Hamburg", "mode", "onsite"),
    ("Teilzeit (20 Std./Woche)", "worktime", "part_time"),
    ("Vollzeit", "worktime", "full_time"),
    ("Vollzeit oder Teilzeit", "worktime", "part_time"),
    ("Werkstudent (m/w/d) Marketing", "worktime", "part_time"),
    ("Minijob auf 538 €-Basis", "contract", ["mini_job"]),
    ("Werkstudent (m/w/d) Marketing", "contract", ["working_student"]),
    ("Praktikum im Vertrieb", "contract", ["internship"]),
    ("Festanstellung, unbefristet", "contract", ["employment"]),
    ("Freiberuflich / Freelancer", "contract", ["freelance"]),
    ("Zeitarbeit / Arbeitnehmerüberlassung", "contract", ["temp_agency"]),
    ("B2B-Vertrieb Außendienst", "contract", []),
    ("Befristet auf 2 Jahre", "contract", []),
    ("Befristet auf 2 Jahre", "fixed_term", True),
    ("Unbefristeter Arbeitsvertrag", "fixed_term", False),
    ("Teamleiter Kundenservice", "level", "lead"),
    ("Abteilungsleiterin Finanzen", "level", "manager"),
    ("Berufseinsteiger Buchhaltung", "level", "junior"),
    ("Sachbearbeiter Personal", "level", "mid"),
    ("100% Homeoffice", "fully_remote", True),
    ("Homeoffice möglich", "fully_remote", False),
    ("mindestens 3 Jahre Berufserfahrung", "years", True),
    ("sehr gute Deutschkenntnisse", "languages", True),
]
