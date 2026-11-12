"""Vocabularies of the Polish general boards (pracuj.pl, gowork.pl, praca.pl), which use the same dictionaries
for contract types and position levels. Not a board: shared by the adapters of this package."""

LANGS = ("pl", "en")  # lang packs for free text on Polish boards

# contract labels, lower-cased (pracuj `typesOfContract`, gowork `contractType`, praca.pl contract tags). "Umowa na
# zastępstwo" is an employment contract; "umowa o pracę tymczasową" is employment through a temp agency
CONTRACTS = {
    "umowa o pracę": "employment", "umowa na zastępstwo": "employment", "umowa o dzieło": "specific_task",
    "umowa zlecenie": "mandate", "kontrakt b2b": "b2b", "umowa agencyjna": "other", "inny": "other",
    "umowa o pracę tymczasową": "temp_agency", "umowa o tymczasową pracę": "temp_agency",
    "umowa o staż / praktyki": "internship", "umowa o staż/praktykę": "internship", "staż/praktyka": "internship",
}

# position-level labels by leading words, lower-cased (pracuj `positionLevels`, gowork `positionLevel.label`);
# "pracownik fizyczny" (manual worker) has no level
LEVELS = {
    "praktykant": "intern", "stażysta": "intern", "asystent": "junior", "młodszy specjalista": "junior",
    "specjalista": "mid", "starszy specjalista": "senior", "ekspert": "senior", "kierownik": "manager",
    "menedżer": "manager", "menadżer": "manager", "dyrektor": "manager", "prezes": "manager",
}

# work-time labels: "część etatu", "praca dodatkowa / tymczasowa" are part time, "pełny etat" full time
PART_TIME, FULL_TIME = r"część|dodatkowa", r"pełny"
