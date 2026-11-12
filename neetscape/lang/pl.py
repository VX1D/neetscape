"""Polish."""

VOCAB = {
    "qualifier": [r"z", r"dla"],  # words that open a title's qualifier ("Konsultant z j. niemieckim")
    "explicit": {
        "contract": {
            "internship": [r"rodzaj (?:umowy|zatrudnienia):\s*sta[żz]"],  # a labelled field; free text says "staż"/"internship" for other reasons
        },
        "mode": {
            "remote": [
                r"100\s*% ?zdaln|w pełni zdaln|całkowicie zdaln|wyłącznie zdaln|tylko zdaln",
                r"zdaln\w*\s*(?:/|,|lub|albo)\s*(?:praca\s+)?hybryd|hybryd\w*\s*(?:/|,|lub|albo)\s*(?:praca\s+)?zdaln",  # a choice: remote is offered
                r"miejsce pracy:[^:]{0,80}?praca zdalna",  # OLX lists the offered work places
            ],
        },
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
        # "staż pracy" / "2 lata stażu" is work experience and "dobrych praktyk" good practice, not an internship
        "internship": [r"(?<!lat )(?<!lata )(?<!roku )\bstaż(?:u|em|e|ów|y)?\b(?!\s+(?:pracy|zawodow\w*|w zawodzie|na (?:podobnym|tym|analogicznym)))",
                       r"\bstażyst\w*", r"\bpraktykant\w*", r"\bpraktyk[ai]? (?:studenck|zawodow|letni|wakacyjn)\w*",
                       r"umow\w* o staż"],
    },
    "level": {
        "intern": [r"stażyst", r"praktykant"],
        "junior": [r"młodsz", r"bez doświadczenia"],
        "senior": [r"starsz", r"ekspert"],
        "manager": [r"kierownik", r"dyrektor"],
        "mid": [r"specjalist"],
    },
    "function": {
        "test": [r"tester|testow\w*|\bqa\b"],
        "shop": [r"kasjer|sprzedawc|ekspedient|asystent\w* (?:sprzedaży|kas|sklep)|pracownik sklepu|merchandiser"],
        "assist": [r"asystent|sekretar|recepcj|pracownik\w* biurow|pomoc\w* biurow|wprowadza\w* danych|archiwi"],
        "serve": [r"obsług\w* klient|konsultant\w* (?:telefon|infolini|ds\.? klient|call)|infolini|call ?cent|reklamac|"
                  r"obsług\w* telefoniczn|telefoniczn\w* obsług|biur\w* obsługi"],
        "sell": [r"sprzedaż|handlow|przedstawiciel|akwizyt|doradc\w* (?:klienta|handlow|finansow)"],
        "people": [r"rekrut|kadr|\bpłac|personaln"],
        "teach": [r"nauczyciel|lektor|korepetyt|wykładowc|\btrener|instruktor|wychowaw"],
        "care": [r"pielęgniar|opiekun|lekarz|ratownik|fizjoterap|farmaceut|stomatolog|terapeut|położn"],
        "manage_project": [r"kierownik\w* projekt|koordynator\w* projekt|menedżer\w* projekt|analityk\w* (?:biznesow|systemow)|"
                           r"właściciel produktu"],
        "automate": [r"automatyzac\w*|automatyzow\w*|automatyzuj\w*"],
        "develop": [r"programist|deweloper"],
        "design": [r"grafik|projektant\w* (?:graficz|ux|ui|stron)"],
        "market": [r"marketing|social media|copywrit|reklam|pozycjonow"],
        "account": [r"księgow|ksiegow|kontroler\w* finans|audytor|biegł\w* rewident|fakturzyst"],
        "law": [r"prawnik|radc\w* prawn|adwokat|aplikant|notariusz"],
        "transport": [r"kierowc|kurier|spedytor|magazynier|logistyk|dyspozytor|wózk\w* widłow|kompletuj|komisjon"],
        "cook_clean": [r"kelner|kucharz|barista|barman|pomoc\w* kuchenn|sprząta|pokojow|zmywak|pracownik restauracji"],
        "operate": [r"operator|monter|spawacz|ślusarz|tokarz|frezer|pakowacz|pracownik\w* produkcji|pracownik\w* fizyczn|"
                    r"pracownik\w* linii"],
        "build": [r"elektryk|mechanik|hydraulik|stolarz|murarz|budowlan|instalator|serwisant(?! komputer)|elektromonter|"
                  r"automatyk|technolog|konstruktor"],
        "administer": [r"administrator"],
        "support": [r"wsparci\w*|pomoc\w* techniczn|serwisant komputer"],
        "analyse": [r"analityk"],
        "consult": [r"konsultant|doradc"],
        "engineer": [r"inżynier|\btechnik\b|architekt"],
        "manage": [r"kierownik|menedżer|dyrektor|koordynator|lider"],
        "specialist": [r"specjalist|ekspert|referent"],
    },
    "domain": {
        "ai": [r"sztuczn\w* inteligencj|\bsi\b|uczeni\w* maszynow"],
        "security": [r"cyberbezpiecz|bezpieczeństw\w* (?:it|informac|sieci|system)"],
        "erp": [r"optima|enova|comarch|symfonia|subiekt|wdrożeniow"],
        "data": [r"danych|hurtowni"],
        "cloud": [r"chmur"],
        "software": [r"oprogramowani|aplikacj|stron\w* internetow"],
        "it": [r"integrac\w*|analityk\w* (?:\w+-)?systemow|informaty|wsparci\w* techniczn|pomoc\w* techniczn|sieci komputer|komputer"],
        "tech": [r"techniczn|system\w*|sprzęt\w*|serwer\w*"],
        "ecommerce": [r"allegro|sklep\w* internetow|baselinker"],
        "industrial": [r"utrzymani\w* ruchu|automatyk|przemysł|elektr|mechani"],
        "construction": [r"budow|budowl|konstrukc"],
        "manufacturing": [r"operator\w* maszyn|spawacz\w*|ślusarz|produkc|zakład|fabryk"],
        "logistics": [r"spedytor\w*|kierowc\w*|kierowczyni|wózk\w* widłow|planist\w* transport|logisty|spedyc|transport|magazyn|dostaw|zakup|zaopatrz"],
        "hr": [r"kadr|\bpłac|rekrut|personal"],
        "finance": [r"finans|księg|ksieg|bank|ubezpiecz|podatk|kredyt|rachunk|płatnoś|windyk"],
        "legal": [r"prawn|kancelari|zgodnoś|\brodo\b"],
        "health": [r"lekarz|lekark|pielęgniar|medyczn|zdrow|szpital|klinik|aptek|pacjent|stomatolog|farmac"],
        "education": [r"korepetyt|nauczyciel|lektor\w*|języka (?:angielskiego|polskiego|niemieckiego|hiszpańskiego)|szkoł|edukac|przedszkol|nauczan"],
        "hospitality": [r"kucharz|kucharka|kelner\w*|pomoc\w* kuchenn|hotel|restaurac|gastronom|kuchni|catering"],
        "retail": [r"market\w* spożywcz|biedronk|kas\w* samoobsług|sklep(?!\w* internetow)|salon\w*|drogeri|supermarket|hipermarket"],
        "customer": [r"infolini|klient"],
        "sales": [r"sprzeda|handlow"],
        "marketing": [r"meta ads|google ads|marketing|reklam"],
        "office": [r"biur|administracyjn|sekretariat"],
        "design": [r"graficz"],
        "product": [r"produktu|projektów|projektami"],
    },
    # words that offer options in one sentence ("hybrydowo lub zdalnie"): remote offered beside hybrid
    "choice": [r"\b(?:lub|albo|bądź)\b", r"zdalnie/", r"/hybryd"],
    "placeholder_companies": ["poufne", "anonim", "ogłoszenie zewnętrzne"],  # a posting that hides its employer
    "pay": {
        "hour": [r"godz", r"na godzin"],
        "week": [r"/\s*tydz\w*", r"na tydzie[nń]"],
        "day": [r"(?<!ty)dzie[nń]", r"dniówk"],
        "year": [r"\brok\b", r"rocznie"],
        "words": [r"brutto", r"netto", r"wynagrodzenie"],
        "thousand": [r"tys\.?"],
        "range": [r"do"],
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
