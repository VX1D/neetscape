"""Polish."""

VOCAB = {
    "mode": {
        "remote": [r"100% ?zdaln", r"w pełni zdaln", r"całkowicie zdaln", r"praca zdalna", r"\bzdalnie\b", r"z domu"],
        "hybrid": [r"hybryd"],
        "onsite": [r"stacjonarn", r"w biurze"],
    },
    "worktime": {
        "part_time": [r"część etatu", r"czesc etatu", r"pół etatu", r"1/2 etatu", r"niepełny etat", r"praca dodatkowa", r"dorywcz"],
        "flexible": [r"elastyczne godziny", r"za zadanie", r"projektow"],
        "full_time": [r"pełny etat", r"pelny etat", r"pełen etat"],
    },
    "contract": {
        "employment": [r"umowa o pracę", r"\buop\b"],
        "b2b": [r"\bb2b\b", r"samozatrudnienie", r"kontrakt"],
        "mandate": [r"umowa zlecenie", r"\bzlec\.?\b", r"\buz\b"],
        "specific_task": [r"umowa o dzieło", r"\buod\b"],
        "internship": [r"staż", r"praktyk"],
    },
    "level": {
        "intern": [r"stażyst", r"praktykant"],
        "junior": [r"młodsz", r"bez doświadczenia"],
        "senior": [r"starsz", r"ekspert"],
        "manager": [r"kierownik", r"dyrektor"],
        "mid": [r"specjalist"],
    },
    "hints": {
        "fully_remote": [r"100% ?zdaln", r"w pełni zdaln", r"całkowicie zdaln", r"cała polska \(praca zdalna\)"],
        "hybrid": [r"hybryd\w*", r"\d+ dni (?:w tygodniu )?w biurze"],
        "years": [r"\d\+?\s*(?:-\s*\d+\s*)?(?:lat[a]?|rok)\s*(?:komercyjn\w* )?doświadczeni\w*"],
        "degree": [r"wykształceni\w* wyższ\w*", r"status\w* studenta"],
        "languages": [r"\b(?:niemieck\w*|francusk\w*|niderlandzk\w*|włosk\w*|hiszpańsk\w*|czesk\w*)\b"],
        "fixed_term": [r"na czas określony", r"na zastępstwo"],
    },
}

EXAMPLES = [
    ("Praca zdalna, pełny etat", "mode", "remote"),
    ("Hybrydowo, 2 dni w biurze", "mode", "hybrid"),
    ("Praca stacjonarna w Krakowie", "mode", "onsite"),
    ("Praca dodatkowa, pół etatu", "worktime", "part_time"),
    ("Umowa o pracę lub B2B", "contract", ["employment", "b2b"]),
    ("Umowa zlecenie", "contract", ["mandate"]),
    ("Umowa o dzieło", "contract", ["specific_task"]),
    ("Młodszy specjalista ds. obsługi klienta", "level", "junior"),
    ("Kierownik sklepu", "level", "manager"),
    ("3 lata doświadczenia komercyjnego", "years", True),
    ("Umowa na czas określony", "fixed_term", True),
]
