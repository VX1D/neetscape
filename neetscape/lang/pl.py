"""Polish."""

VOCAB = {
    "first": {
        "mode": [
            ("remote", r"100\s*% ?zdaln|w pełni zdaln|całkowicie zdaln|wyłącznie zdaln|tylko zdaln"),
            ("remote", r"zdaln\w*\s*(?:/|,|lub|albo)\s*(?:praca\s+)?hybryd|hybryd\w*\s*(?:/|,|lub|albo)\s*(?:praca\s+)?zdaln"),  # a choice: remote is offered
            ("remote", r"miejsce pracy:[^:]{0,80}?praca zdalna"),  # OLX lists the offered work places
        ],
    },
    "mode": {
        "remote": [r"praca zdalna", r"\bzdalnie\b", r"z domu", r"\bprac\w* zdaln\w*", r"\btryb\w* zdaln\w*"],
        "hybrid": [r"(?<!chmury )(?<!chmurze )hybryd(?!\w*\s+(?:chmur|aplikac|środowisk|infrastruktur))"],
        "onsite": [r"stacjonarn", r"w biurze"],
    },
    "worktime": {
        "part_time": [r"część etatu", r"czesc etatu", r"pół etatu", r"1/2 etatu", r"niepełny etat", r"praca dodatkowa", r"dorywcz"],
        "flexible": [r"elastyczne godziny", r"za zadanie", r"projektow"],
        "full_time": [r"pełny etat", r"pelny etat", r"pełen etat"],
    },
    "contract": {
        "employment": [r"umowa o pracę", r"\buop\b", r"umowa na okres próbny", r"umowa na czas określony", r"umowa na zastępstwo"],
        "b2b": [r"\bb2b\b", r"samozatrudnienie", r"kontrakt", r"podwykonawstwo"],
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
        "fully_remote": [r"100\s*% ?zdaln", r"100\s*% pracy zdaln", r"w pełni zdaln", r"całkowicie zdaln", r"wyłącznie zdaln",
                         r"z dowolnego miejsca", r"cała polska \(praca zdalna\)"],
        "hybrid": [r"hybryd\w*", r"\d+ dni (?:w tygodniu )?w biurze"],
        "years": [r"\d\+?\s*(?:-\s*\d+\s*)?(?:lat[a]?|rok)\s*(?:komercyjn\w* )?doświadczeni\w*"],
        "degree": [r"wykształceni\w* wyższ\w*", r"status\w* studenta"],
        "languages": [r"\b(?:niemieck\w*|francusk\w*|niderlandzk\w*|włosk\w*|hiszpańsk\w*|czesk\w*)\b"],
        "fixed_term": [r"na czas określony", r"na zastępstwo"],
        "office": [r"wizyt\w* u klient\w*", r"spotkani\w* u klient\w*", r"wyjazd\w* (?:służbow\w*|do klient\w*)", r"delegacj\w*",
                   r"(?:raz|dwa razy|kilka razy) w (?:miesiącu|tygodniu|kwartale) w biurze", r"w biurze (?:raz|dwa razy|kilka razy) w",
                   r"przeprowadzk\w*", r"szkoleni\w* stacjonarn\w*", r"wdrożeni\w* stacjonarn\w*"],
    },
}

EXAMPLES = [
    ("Pracujesz w 100% zdalnie, z dowolnego miejsca w Polsce", "fully_remote", True),
    ("Praca zdalna, spotkania u klientów kilka razy w miesiącu", "office", ["spotkania u klientów"]),
    ("Zdalnie, ale raz w miesiącu w biurze w Poznaniu", "office", ["raz w miesiącu w biurze"]),
    ("Będziesz przeprowadzać testy aplikacji, pracując w trybie zdalnym", "office", []),
    ("Oferujemy pracę zdalną w godzinach 8-16", "mode", "remote"),
    ("Praca zdalna, pełny etat", "mode", "remote"),
    ("Hybrydowo, 2 dni w biurze", "mode", "hybrid"),
    ("Praca hybrydowa, 2 dni zdalnie", "mode", "hybrid"),
    ("Model hybrydowy (praca zdalnie 3 dni w tygodniu)", "mode", "hybrid"),
    ("Praca zdalna lub hybrydowa", "mode", "remote"),
    ("Miejsce pracy: Praca hybrydowa, Praca zdalna", "mode", "remote"),
    ("Miejsce pracy: Praca hybrydowa, W siedzibie firmy, Praca zdalna", "mode", "remote"),
    ("Miejsce pracy: Praca hybrydowa Odświeżono dnia 09 listopada", "mode", "hybrid"),
    ("100% zdalnie, raz w kwartale spotkanie w biurze", "mode", "remote"),
    ("Administrator chmury hybrydowej, praca zdalna", "mode", "remote"),
    ("Praca stacjonarna w Krakowie", "mode", "onsite"),
    ("Praca dodatkowa, pół etatu", "worktime", "part_time"),
    ("Umowa o pracę lub B2B", "contract", ["employment", "b2b"]),
    ("Umowa zlecenie", "contract", ["mandate"]),
    ("Umowa na okres próbny", "contract", ["employment"]),
    ("Umowa na czas określony", "contract", ["employment"]),
    ("Umowa o dzieło", "contract", ["specific_task"]),
    ("Młodszy specjalista ds. obsługi klienta", "level", "junior"),
    ("Kierownik sklepu", "level", "manager"),
    ("3 lata doświadczenia komercyjnego", "years", True),
    ("Umowa na czas określony", "fixed_term", True),
]
