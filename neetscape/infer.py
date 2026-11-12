"""Board vocabularies and free text -> the model's values, each derived field with where it came from.

An offer's observations are stored apart from what is derived from them, so `neetscape eval` derives every
offer again after a vocabulary change, without a crawl (`derive`, called by `Store.rederive`):
- `facts`: what the board's adapter read from structured data;
- a remote filter the board applied in a request that found the offer;
- the title, the card text and the board's category;
- the fetched posting (its JSON-LD and text).

Free text is read with the language packs (`neetscape/lang/<code>.py`): per field and value, `explicit`
phrases (they settle the field: "100% zdalnie") and plain ones ("zdalnie"). A field takes its strongest
match: by source (`SOURCES`), then explicit before plain, then the field's order of values (`ORDER`).
Every function returns "unknown" (or an empty list) rather than guessing.
"""
from __future__ import annotations

import functools
import json
import re

from . import lang
from .model import canonical_contract
from .pay import parse_pay

# --- board vocabularies -------------------------------------------------------
_MODE = {"remote": "remote", "hybrid": "hybrid", "office": "onsite", "onsite": "onsite", "partly_remote": "hybrid"}
_WORKTIME = {"full_time": "full_time", "part_time": "part_time", "freelance": "flexible", "practice_internship": "part_time",
             "contract": "flexible", "temporary": "flexible", "flexible": "flexible"}
_CONTRACT = {"permanent": "employment", "b2b": "b2b", "mandate_contract": "mandate", "specific_task_contract": "specific_task",
             "internship": "internship", "freelance": "freelance", "any": "other", "uop": "employment", "mandate": "mandate"}
_LEVEL = {"intern": "intern", "junior": "junior", "mid": "mid", "regular": "mid", "senior": "senior", "expert": "senior",
          "lead": "lead", "manager": "manager", "c_level": "manager"}


def mode(value: str) -> str:
    return _MODE.get((value or "").lower(), "unknown")


def worktime(value: str) -> str:
    return _WORKTIME.get((value or "").lower(), "unknown")


def contract(value: str, aliases: dict | None = None) -> str:
    """A board's contract word -> canonical contract. `aliases`: the country's `contract_aliases`."""
    v = (value or "").lower()
    found = _CONTRACT.get(v) or (aliases or {}).get(v)
    return canonical_contract(found) if found else "other"


def level(value: str) -> str:
    return _LEVEL.get((value or "").lower(), "unknown")


# --- job fields: function x domain -------------------------------------------
# A title names what the person does (function) and what the work is about (domain). A function-led function
# decides the field ("Sales Engineer" sells, "AI Recruiter" recruits); a domain-led one (None) takes the domain's
# ("Logistics Support Specialist" is logistics, "Technical Support Engineer" IT support).
FUNCTIONS = {
    "assist": "admin_office", "test": "qa", "automate": "ai_automation", "develop": "software_dev",
    "design": "design", "teach": "education", "care": "healthcare", "serve": "customer_service", "sell": "sales",
    "market": "marketing", "people": "hr", "account": "finance", "transport": "logistics", "operate": "manufacturing",
    "build": "engineering", "manage_project": "product_project", "cook_clean": "hospitality", "shop": "retail",
    "law": "legal",
    "support": None, "administer": None, "engineer": None, "analyse": None, "consult": None, "manage": None,
    "specialist": None,
}
# None: the domain only qualifies the functions named in MATRIX ("technical", "system" make an IT administrator)
DOMAINS = {
    "ai": "ai_automation", "security": "security", "erp": "erp_crm", "data": "data", "cloud": "devops_cloud",
    "software": "software_dev", "it": "it_support", "tech": None, "ecommerce": "ecommerce", "industrial": "engineering",
    "construction": "engineering", "manufacturing": "manufacturing", "logistics": "logistics", "hr": "hr",
    "finance": "finance", "legal": "legal", "health": "healthcare", "education": "education",
    "hospitality": "hospitality", "retail": "retail", "customer": "customer_service", "sales": "sales",
    "marketing": "marketing", "office": "admin_office", "design": "design", "product": "product_project",
}
# the domain a function implies when the title and the category name none ("Automation Engineer", "Manual Tester")
IMPLIED_DOMAIN = {"automate": "ai", "develop": "software", "test": "software"}
MATRIX = {
    ("administer", "it"): "it_admin", ("administer", "tech"): "it_admin", ("administer", "cloud"): "it_admin",
    ("engineer", "it"): "it_admin", ("support", "tech"): "it_support",
    ("develop", "ai"): "ai_automation", ("develop", "data"): "data", ("develop", "erp"): "erp_crm",
    ("develop", "security"): "security", ("develop", "cloud"): "devops_cloud",
    ("automate", "industrial"): "engineering", ("automate", "manufacturing"): "engineering",
    ("engineer", "software"): "software_dev",
}

# order of values when several match with equal source and strength
ORDER = {
    # an explicit full-remote statement beats an explicit hybrid one ("100% Homeoffice möglich"); among plain words
    # hybrid wins: "hybrid, 2 days remote" is hybrid
    ("mode", True): ("remote", "hybrid", "onsite"),
    ("mode", False): ("hybrid", "remote", "onsite"),
    "worktime": ("part_time", "flexible", "full_time"),
    "level": ("intern", "junior", "senior", "lead", "manager", "mid"),
    "contract": ("employment", "b2b", "mandate", "specific_task", "internship", "freelance", "mini_job",
                 "working_student", "temp_agency"),
    # "Test Automation Engineer" tests, "Customer Support Specialist" serves, "Store Assistant" works in a shop
    "function": ("test", "shop", "assist", "serve", "sell", "people", "teach", "care", "manage_project", "automate",
                 "develop", "design", "market", "account", "law", "transport", "cook_clean", "operate", "build",
                 "administer", "support", "analyse", "consult", "engineer", "manage", "specialist"),
    # technical domains first ("HR Data Reporting Specialist" works with data); `tech` words ("system") last
    "domain": ("ai", "security", "erp", "data", "cloud", "software", "it", "ecommerce", "industrial", "construction",
               "manufacturing", "logistics", "hr", "finance", "legal", "health", "education", "hospitality", "retail",
               "customer", "sales", "marketing", "office", "design", "product", "tech"),
}
SOURCES = ("board", "request", "posting_struct", "title", "qualifier", "card", "category", "posting")  # strongest first
COLUMNS = {"mode": "mode", "worktime": "worktime", "contracts": "contract", "level": "level",
           "job_function": "function", "job_domain": "domain"}  # derived offer column -> lexicon field


# --- reading text ---------------------------------------------------------------
_SENTENCES = re.compile(r"(?<=[.!?;])\s+|\n+|\s+[•▪·]\s+")
_CHOICE_MARKS = r"\s/\s"  # "hybrid / remote": an option in any language; the packs' `choice` words add the rest
# A title's head ends at a qualifier: "Senior .NET Developer (GenAI)", "Data Analyst - Remote", and at the words
# of the active packs' `qualifier` ("Customer Support Specialist with German"). A gender marker says nothing about
# the job and must not end the head ("Sachbearbeiter (m/w/d) Buchhaltung"): a bracketed list of single letters
# ("(m/w/d)", "(k/m)", "(f/m/x)") in any language, and the bracketed words of the packs' `gender` ("(all genders)").
_QUALIFIER_MARKS = r"\s[-–—|/]\s|[(\[]"
_GENDER_LETTERS = r"[^\W\d_](?:\s*[/|,]\s*[^\W\d_]){1,3}"


def _langs(languages) -> tuple:
    return lang.with_english(tuple(languages) if languages else lang.DEFAULT)


@functools.lru_cache(maxsize=32)
def _lexicon(languages: tuple) -> dict:
    """{field: [(value, explicit, regex)]} merged over the packs, {"hints": {key: regex}}, and the title's
    "qualifier" and "gender" regexes (generic punctuation plus the packs' words)."""
    packs = [lang.pack(code).VOCAB for code in languages]
    out: dict = {}
    for fld in lang.FIELDS:
        rows = []
        for explicit, tables in ((True, [pk.get("explicit", {}).get(fld, {}) for pk in packs]),
                                 (False, [pk.get(fld, {}) for pk in packs])):
            for value in dict.fromkeys(v for t in tables for v in t):
                rows.append((value, explicit, re.compile("|".join(f"(?:{p})" for t in tables for p in t.get(value, [])), re.I)))
        out[fld] = rows
    choice = [f"(?:{p})" for pk in packs for p in pk.get("choice", [])]
    out["choice"] = re.compile("|".join([_CHOICE_MARKS, *choice]), re.I)
    words = [f"(?:{p})" for pk in packs for p in pk.get("qualifier", [])]
    out["qualifier"] = re.compile(_QUALIFIER_MARKS + (rf"|\s(?:{'|'.join(words)})\s" if words else ""), re.I)
    genders = [_GENDER_LETTERS] + [f"(?:{p})" for pk in packs for p in pk.get("gender", [])]
    out["gender"] = re.compile(rf"[(\[]\s*(?:{'|'.join(genders)})\s*[)\]]", re.I)
    out["hints"] = {}
    for key in lang.HINTS:
        pats = [f"(?:{p})" for pk in packs for p in pk.get("hints", {}).get(key, [])]
        out["hints"][key] = re.compile("|".join(pats), re.I) if pats else None
    return out


def _scan(fld: str, text: str, languages, source: str) -> list[tuple]:
    """Matches of `fld` in a text: (field, value, source, explicit, phrase), once per value and strength."""
    if not text:
        return []
    return [(fld, value, source, explicit, m.group(0)) for value, explicit, rx in _lexicon(_langs(languages))[fld]
            if (m := rx.search(text))]


def _rank(m: tuple) -> tuple:
    fld, value, source, explicit, _ = m
    order = ORDER.get((fld, explicit)) or ORDER[fld]
    weak = fld == "domain" and value == "tech"  # any other domain, even from a qualifier, says more
    return weak, SOURCES.index(source), not explicit, order.index(value) if value in order else len(order)


def _decide(fld: str, matches: list[tuple]) -> tuple:
    """(value, source, phrase) of a field; contracts: every value of the strongest source that names any."""
    ms = sorted((m for m in matches if m[0] == fld), key=_rank)
    if not ms:
        return ((), "", "") if fld == "contract" else ("unknown", "", "")
    if fld == "contract":
        group = [m for m in ms if m[2] == ms[0][2]]
        return tuple(dict.fromkeys(m[1] for m in group)), ms[0][2], ", ".join(m[4] for m in group)
    return ms[0][1], ms[0][2], ms[0][4]


def mode_from_text(text: str, languages=None) -> str:
    return _decide("mode", _scan("mode", text, languages, "card"))[0]


def worktime_from_text(text: str, languages=None) -> str:
    return _decide("worktime", _scan("worktime", text, languages, "card"))[0]


def contracts_from_text(text: str, languages=None) -> list[str]:
    return list(_decide("contract", _scan("contract", text, languages, "card"))[0])


def level_from_text(title: str, languages=None) -> str:
    return _decide("level", _scan("level", title, languages, "title"))[0]


def hints(text: str, languages=None) -> dict:
    """Signals for the reviewer from a full posting. Not decisions: the posting text is the source of truth."""
    rx = _lexicon(_langs(languages))["hints"]
    text = text or ""
    found = lambda k: sorted({m.lower() for m in rx[k].findall(text)})[:3] if rx[k] else []
    return {
        "fully_remote": bool(rx["fully_remote"] and rx["fully_remote"].search(text)),
        "hybrid": found("hybrid"),
        "years": sorted(set(rx["years"].findall(text)))[:3] if rx["years"] else [],
        "degree": found("degree"),
        "languages": found("languages"),
        "fixed_term": bool(rx["fixed_term"] and rx["fixed_term"].search(text)),
        "office": found("office"),
    }


def remote_proof(text: str, languages=None) -> str:
    """Why a posting fails to prove a fully remote job, or "" when it proves one: it must describe remote work
    ("fully remote", or plain remote wording) and require no presence: no hybrid wording outside a sentence that
    offers remote as an option ("hybrid or 100% remote" is a choice), no office hints (client visits, business
    trips, office days, relocation)."""
    found = []
    for sentence in (s for s in _SENTENCES.split(text or "") if s.strip()):
        hybrid = hints(sentence, languages)["hybrid"]
        if not hybrid:
            continue
        lexicon = _lexicon(_langs(languages))
        offers_remote = (hints(sentence, languages)["fully_remote"]  # remote beside the hybrid wording?
                         or mode_from_text(lexicon["hints"]["hybrid"].sub("", sentence), languages) == "remote")
        if not (offers_remote and lexicon["choice"].search(sentence)):
            found += [w for w in hybrid if w not in found]
    found += [w for w in hints(text, languages)["office"] if w not in found]
    if found:
        return "posting requires presence: " + ", ".join(found[:2])
    if not (hints(text, languages)["fully_remote"] or mode_from_text(text, languages) == "remote"):
        return "posting does not mention remote work"
    return ""


# --- deriving an offer's fields -------------------------------------------------
def board_facts(offer) -> dict:
    """The values an adapter set from the board's structured data (before any text is read)."""
    out = {k: getattr(offer, k) for k in ("mode", "worktime", "level") if getattr(offer, k) not in ("", "unknown", None)}
    contracts = sorted({canonical_contract(c) for c in offer.contracts})
    return out | ({"contracts": contracts} if contracts else {})


def card_text(row) -> str:
    """Offer.text() of a stored offer row."""
    locations = " ".join(json.loads(row["locations"] or "[]"))
    return " ".join([row["title"] or "", row["company"] or "", row["category"] or "", row["skills"] or "",
                     row["pay_text"] or "", row["snippet"] or "", locations])


def _job_field(function: tuple, domain: tuple) -> tuple[str, str]:
    f, d = (None if x[0] == "unknown" else x[0] for x in (function, domain))
    if f and d and (f, d) in MATRIX:
        return MATRIX[(f, d)], function[1]
    if f and FUNCTIONS[f]:
        return FUNCTIONS[f], function[1]
    if d and DOMAINS[d]:
        return DOMAINS[d], domain[1]
    return "other", ""


def _domains(matches: list[tuple]) -> dict:
    """Every domain the title (head and qualifier) and the category name: {domain: (source, phrase)}, each from
    its strongest match. The weak `tech` domain ("system") counts only when no other domain is named."""
    out: dict = {}
    for m in sorted((m for m in matches if m[0] == "domain"), key=_rank):
        out.setdefault(m[1], (m[2], m[4]))
    if len(out) > 1:
        out.pop("tech", None)
    return out


# "Konsultant / Konsultantka", "Kierowca/Kierowczyni", "Mitarbeiter/in": one job name in two grammatical genders,
# not the end of the title's head; recognised by the shared start of the two words, in any language. Both words stay:
# "Sales/Salesforce Administrator" still names Salesforce
_GENDER_PAIR = re.compile(r"(\w+)\s*/\s*(\w+)")


def _same_word(a: str, b: str) -> bool:
    a, b = a.casefold(), b.casefold()
    return len(a) >= 4 and b.startswith(a[:5] if len(a) >= 5 else a)


def title_parts(title: str, languages=None) -> tuple[str, str]:
    """(head, qualifiers) of a job title, gender markers removed: "Sachbearbeiter (m/w/d) Buchhaltung" ->
    ("Sachbearbeiter Buchhaltung", ""), "Senior .NET Developer (GenAI)" -> ("Senior .NET Developer ", "(GenAI)")."""
    lexicon = _lexicon(_langs(languages))
    plain = _GENDER_PAIR.sub(lambda m: f"{m[1]} {m[2]}" if _same_word(m[1], m[2]) else m[0], lexicon["gender"].sub(" ", title or ""))
    m = lexicon["qualifier"].search(plain)
    return (plain[:m.start()], plain[m.start():]) if m and m.start() > 0 else (plain, "")


def derive(*, title: str = "", card: str = "", facts: dict | None = None, request_remote: bool = False,
           posting: str = "", posting_remote: bool = False, posting_facts: dict | None = None, category: str = "",
           languages=None) -> dict:
    """Derived offer columns (mode, worktime, contracts, level, job_function, job_domain, job_field, job_domains)
    and `evidence` (json: column -> [source, phrase]; `job_domains` -> {domain: [source, phrase]}).

    `job_domains`: the set of every domain the title and the category name (comma-joined, sorted), so an offer
    has AI as a domain whatever its function ("AI Gateway Product Owner": ai, product); `job_domain` is the
    leading one and `job_field` the single field read from the function and the leading domain.

    `card`: Offer.text(); `request_remote`: a request that found the offer had the board's remote filter;
    `posting_remote`: the posting's JSON-LD says TELECOMMUTE; `posting_facts`: column -> value (or list) the board
    read from the posting's structured fields (`Board.posting_facts`), a value optionally a (value, phrase) pair;
    `category`: the board's category and the categories of the requests that found the offer. A long posting mentions "remote" and "staż" for many
    reasons: its mode counts only from full-remote statements and hybrid words, an internship only from an
    explicit statement ("Employment type: Internship")."""
    ms = [(COLUMNS[k], value, "board", True, "board data")
          for k, v in (facts or {}).items() for value in (v if isinstance(v, list) else [v])]
    if request_remote:
        ms.append(("mode", "remote", "request", True, "board's remote filter"))
    if posting_remote:
        ms.append(("mode", "remote", "posting_struct", True, "JSON-LD TELECOMMUTE"))
    for k, v in (posting_facts or {}).items():
        for item in (v if isinstance(v, list) else [v]):
            value, phrase = item if isinstance(item, tuple) else (item, "posting data")
            ms.append((COLUMNS[k], value, "posting_struct", True, phrase))
    ms += _scan("level", title, languages, "title")
    head, qualifiers = title_parts(title, languages)
    for fld in ("function", "domain"):
        ms += (_scan(fld, head, languages, "title") + _scan(fld, qualifiers, languages, "qualifier")
               + _scan(fld, category.replace("-", " "), languages, "category"))
    for fld in ("mode", "worktime", "contract"):
        ms += _scan(fld, card, languages, "card")
    if posting and not posting.startswith("ERROR"):
        rx = _lexicon(_langs(languages))["hints"]
        if rx["fully_remote"] and (hit := rx["fully_remote"].search(posting)):
            ms.append(("mode", "remote", "posting", True, hit.group(0)))
        if rx["hybrid"] and (hit := rx["hybrid"].search(posting)):
            ms.append(("mode", "hybrid", "posting", False, hit.group(0)))
        ms += _scan("worktime", posting, languages, "posting")
        ms += [x for x in _scan("contract", posting, languages, "posting") if x[1] != "internship" or x[3]]

    decided = {col: _decide(fld, ms) for col, fld in COLUMNS.items()}
    out = {col: (",".join(sorted(v)) if col == "contracts" else v) for col, (v, _, _) in decided.items()}
    evidence = {col: [src, phrase] for col, (_, src, phrase) in decided.items() if src}

    # job field: the title's reading; else the category's (its own function when that leads, otherwise the
    # title's function in the category's domain: "Support Specialist" in "IT support")
    in_title = [x for x in ms if x[2] in ("title", "qualifier")]
    in_category = [x for x in ms if x[2] == "category"]
    tf, td = _decide("function", in_title), _decide("domain", in_title)
    cf, cd = _decide("function", in_category), _decide("domain", in_category)
    field, source = _job_field(tf, td)
    if field == "other":
        leads = cf[0] != "unknown" and FUNCTIONS[cf[0]]
        field, source = _job_field(cf if leads or tf[0] == "unknown" else tf, cd)
    out["job_field"] = field
    if source:
        evidence["job_field"] = [source, " + ".join(x[2] for x in (tf, td, cf, cd) if x[2])]
    domains = _domains(in_title + in_category)
    function = decided["job_function"]
    if not domains and function[0] in IMPLIED_DOMAIN:  # "Automation Engineer": the function says what it is about
        domains = {IMPLIED_DOMAIN[function[0]]: (function[1], function[2])}
    out["job_domains"] = ",".join(sorted(domains))
    if domains:
        evidence["job_domains"] = {d: [src, phrase] for d, (src, phrase) in sorted(domains.items())}
    out["evidence"] = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    return out


def job_field_of(title: str, category: str = "", languages=None) -> str:
    return derive(title=title, category=category, languages=languages)["job_field"]


def fill(offer, fx: dict, *, request_remote: bool = False, base: str = "PLN", country: str = "", languages=None,
         assume: str | None = None, hours: int | None = None, days: int | None = None) -> None:
    """Derive an Offer's fields at ingest (its adapter's values become its `facts`), then normalise pay.
    `fx`/`base`: the database currency; `languages`/`assume`/`country`: the country the text is in."""
    offer.facts, offer.country = board_facts(offer), country
    cols = derive(title=offer.title, card=offer.text(), facts=offer.facts, request_remote=request_remote,
                  category=offer.category, languages=languages)
    offer.mode, offer.worktime, offer.level = cols["mode"], cols["worktime"], cols["level"]
    offer.contracts = [c for c in cols["contracts"].split(",") if c]
    offer.evidence = json.loads(cols["evidence"])
    if offer.pay_min is None and offer.pay_text and offer.pay_period != "project":
        kw = {k: v for k, v in (("hours", hours), ("days", days)) if v}
        pm = parse_pay(offer.pay_text, fx, base=base, assume=assume, **kw)
        if pm:
            offer.pay_min, offer.pay_max = pm
