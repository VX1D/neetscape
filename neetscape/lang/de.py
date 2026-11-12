"""German.

Traps: "Homeoffice möglich", "teilweise Homeoffice", "mobiles Arbeiten" and "remote möglich" mean some days at
home (hybrid); only phrases such as "100% Homeoffice", "vollständig/komplett remote" or "deutschlandweit remote"
mean fully remote. "Befristet" (fixed-term) is a hint, not a contract type; "unbefristet" is a permanent
employment contract. "B2B" in German postings is usually a sales segment ("B2B-Vertrieb"), not a contract.
"""

_HO = r"home[- ]?office"

VOCAB = {
    "qualifier": [r"mit"],  # words that open a title's qualifier ("Sachbearbeiter mit Englisch")
    "gender": [r"gn", r"[a-z](?:\s*/\s*[a-z])*\s*/\s*div(?:ers[ea]?)?"],  # "(gn)", "(m/w/div)"
    "explicit": {
        "mode": {
            "remote": [
                rf"100\s*%\s*(?:{_HO}|remote|mobil\w*)",
                rf"(?:vollständig|komplett|ausschließlich|voll|zu 100\s*%)\s+(?:im\s+)?(?:{_HO}|remote|mobil\w*)",
                r"deutschlandweit\s+remote|remote\s*\(deutschlandweit\)|full[- ]?remote|fully remote",
            ],
            "hybrid": [
                rf"{_HO}[- ]?(?:möglich|option|anteil\w*)|teilweise\s+(?:im\s+)?(?:{_HO}|remote|mobil\w*)",
                rf"mobiles?\s+arbeiten|remote[- ]möglich|\d+\s*(?:tage?|x)\s*(?:pro woche\s*|/\s*woche\s*)?(?:im\s+|vom\s+)?(?:{_HO}|remote|mobil)",
            ],
        },
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
    "function": {
        "shop": [r"verkäufer|kassierer"],
        "serve": [r"kundenservice|kundenbetreuung|kundendienst"],
        "sell": [r"vertrieb|außendienst"],
        "people": [r"personalreferent|personalsachbearbeit|lohnbuchhalt|recruiter"],
        "teach": [r"lehrer|erzieher|dozent|ausbilder"],
        "care": [r"pflege|ärzt|arzt|apotheker|therapeut"],
        "develop": [r"entwickler|programmierer"],
        "account": [r"buchhalt|steuerfach|bilanz"],
        "transport": [r"fahrer|lagerist|kommissionier|lagermitarbeiter|staplerfahrer"],
        "cook_clean": [r"\bkoch\b|köchin|kellner|reinigung|servicekraft"],
        "operate": [r"helfer|produktionsmitarbeiter|maschinenbediener|monteur"],
        "build": [r"elektriker|mechatroniker|mechaniker|anlagenmechaniker|installateur"],
        "administer": [r"systemadministrator|netzwerkadministrator"],
        "engineer": [r"ingenieur|techniker"],
        "consult": [r"berater"],
        "manage": [r"leiter|leitung"],
        "specialist": [r"sachbearbeit|referent|fachkraft"],
        "assist": [r"assistenz|sekretär|bürokraft|empfang"],
    },
    "domain": {
        "it": [r"informatik|\bedv\b"],
        "hr": [r"personal"],
        "finance": [r"finanz|buchhaltung|steuer|controlling|versicherung"],
        "logistics": [r"logistik|\blager|spedition"],
        "health": [r"gesundheit|pflege|medizin|klinik|praxis"],
        "office": [r"büro|verwaltung"],
        "manufacturing": [r"produktion|fertigung"],
        "construction": [r"\bbau"],
        "hospitality": [r"gastronomie|hotel"],
        "sales": [r"vertrieb|verkauf"],
    },
    "choice": [r"\boder\b", r"remote/", r"/hybrid"],
    "pay": {
        "hour": [r"/\s*std\b", r"pro stunde", r"stundenlohn", r"je stunde", r"stündlich"],
        "week": [r"pro woche", r"/\s*woche\b", r"wöchentlich"],
        "day": [r"tagessatz", r"pro tag\b", r"/\s*tag\b"],
        "year": [r"/\s*jahr\b", r"pro jahr", r"jährlich", r"\bp\.\s?a\.", r"jahresgehalt", r"jahresbrutto"],
        "month": [r"pro monat", r"monatlich", r"/\s*monat\b", r"\bmtl\."],
        "words": [r"brutto", r"netto", r"gehalt", r"vergütung"],
        "thousand": [r"tsd\.?"],
        "range": [r"bis"],
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
        "office": [r"kundenbesuch\w*", r"vor ort beim kunden", r"dienstreise\w*", r"reisebereitschaft", r"umzug"],
    },
}

# Interface of REPORT.html (see neetscape/lang/en.py: UI).
UI = {
    "name": "Deutsch",
    "review": "Auswahl", "all": "Alle", "search": "Suchen  /",
    "g_auto": "Gruppe: automatisch", "g_category": "Gruppe: Notiz-Kategorie", "g_status": "Gruppe: Status",
    "g_tag": "Gruppe: Tag", "g_search": "Gruppe: Suche", "g_board": "Gruppe: Börse", "g_field": "Gruppe: Berufsfeld",
    "g_mode": "Gruppe: Arbeitsort", "g_none": "Keine Gruppen",
    "s_score": "Sortierung: Punkte", "s_pay": "Sortierung: Gehalt", "s_newest": "Sortierung: neueste",
    "s_company": "Sortierung: Firma",
    "filters": "Filter", "any_mode": "Jeder Arbeitsort", "any_board": "Jede Börse", "f_new": "Neu in diesem Lauf",
    "f_posted": "Mit Anzeigentext", "f_unreviewed": "Nicht entschieden", "f_hide": "Entschiedene ausblenden",
    "remote_only": "Nur remote",
    "keys": "j/k bewegen · o öffnen · s/a/r/i entscheiden · u rückgängig · n Notiz · / suchen",
    "empty": "Nichts gefunden. Filter zurücksetzen.",
    "empty_review": "Noch keine Auswahl: in „Alle“ entscheiden oder mit neetscape mark festhalten.",
    "select": "Angebot auswählen.",
    "pay": "Gehalt / Monat", "mode": "Arbeitsort", "time": "Umfang", "contract": "Vertrag", "level": "Level",
    "posted": "veröffentlicht", "on": "auf", "score": "Punkte", "ago": "her", "fully_remote": "voll remote", "dm": "Bereiche",
    "open": "Angebot öffnen ↗", "back": "← Liste", "note_ph": "Notiz: warum · Risiko (wird mit der Entscheidung gespeichert)",
    "clear": "Leeren",
    "copy": {"one": "{n} Befehl kopieren", "other": "{n} Befehle kopieren"},
    "copied": {"one": "{n} Befehl kopiert: im Terminal einfügen", "other": "{n} Befehle kopiert: im Terminal einfügen"},
    "confirm_clear": "Die Entscheidungen auf dieser Seite verwerfen?",
    "decided": "{a} / {b} entschieden", "more": "Mehr zeigen ({n} übrig)", "shown": "{a} von {b}",
    "offers": {"one": "{n} Angebot", "other": "{n} Angebote"}, "new": "{n} neu", "errors": "{n} Börsenfehler",
    "cut": {"one": "{n} abgeschnittene Liste", "other": "{n} abgeschnittene Listen"},
    "p_none": "Anzeigentext nicht geladen", "p_empty": "Anzeigentext leer", "p_failed": "Laden des Anzeigentexts fehlgeschlagen",
    "p_gone": "Angebot entfernt", "p_http": "Anzeigentext nicht verfügbar",
    "other": "sonstige", "no_tag": "ohne Tag", "not_reviewed": "nicht geprüft",
    "view": "Ansicht", "prev": "Zurück (k)", "next": "Weiter (j)", "lang": "Sprache",
    "st": {"shortlisted": "vorgemerkt", "applied": "beworben", "interview": "Gespräch", "offer": "Zusage",
           "rejected": "abgelehnt", "ignored": "ignoriert"},
    "fd": {"ai_automation": "KI & Automatisierung", "security": "Sicherheit", "qa": "QA & Test", "devops_cloud": "DevOps & Cloud",
           "data": "Daten & Analyse", "it_support": "IT-Support", "it_admin": "IT-Administration", "erp_crm": "ERP & CRM",
           "software_dev": "Softwareentwicklung", "product_project": "Produkt & Projekt", "design": "Design",
           "ecommerce": "E-Commerce", "customer_service": "Kundenservice", "sales": "Vertrieb", "marketing": "Marketing",
           "hr": "Personal & Lohn", "finance": "Finanzen & Buchhaltung", "legal": "Recht", "admin_office": "Büro & Verwaltung",
           "logistics": "Logistik", "engineering": "Ingenieurwesen", "manufacturing": "Produktion", "healthcare": "Gesundheit",
           "education": "Bildung", "hospitality": "Gastgewerbe", "retail": "Einzelhandel", "other": "Sonstige"},
    "md": {"remote": "remote", "hybrid": "hybrid", "onsite": "vor Ort", "unknown": "unbekannt"},
    "wt": {"full_time": "Vollzeit", "part_time": "Teilzeit", "flexible": "flexibel"},
}
