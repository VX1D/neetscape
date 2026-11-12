# Search profile

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Reviewing](review.md) · [Testing](testing.md)

A profile is the union of its searches: conditions inside a search are ANDed, an offer passes the
profile if it passes any search. `defaults` are merged into every search. Rank rules only order
results; they never drop anything.

The keys and values are the same in every country; only the phrases in `what` are sent to the boards
as they are, so write them in the language the boards' postings use. An example for three different
people in Poland, one search each (a real profile usually holds one person's searches):

```json
{
  "version": 2,
  "country": "pl",
  "boards": ["pl"],
  "defaults": {"max_age_days": 30, "unknown": "keep"},
  "searches": [
    {"id": "it-remote", "label": "Remote IT support", "where": "remote",
     "what": ["it support", "helpdesk", "service desk"],
     "fields": ["it_support", "it_admin"], "levels_exclude": ["senior", "lead", "manager"],
     "pay": {"min": 7000, "per": "month"}},
    {"id": "accounting", "label": "Accounting near Poznań", "where": {"city": "Poznań", "radius_km": 25},
     "what": ["księgowa", "księgowy", "accountant"], "fields": ["finance"],
     "contracts": ["employment"], "title_exclude": ["główn|kierownik|manager"]},
    {"id": "side", "label": "Tutoring on the side", "where": "anywhere", "what": ["korepetycje", "tutor"],
     "fields": ["education"], "worktime": ["part_time", "flexible"],
     "contracts": ["mandate", "specific_task", "freelance"], "pay": {"min": 50, "per": "hour"}, "boost": 3}
  ],
  "rank": {"rules": [{"pattern": "junior|młodsz|entry", "weight": 2, "label": "entry level"}],
           "sort": ["score", "new", "pay"]},
  "review": {"mode": "listing"}
}
```

`what` holds Polish phrases (*księgowa*, *korepetycje*: accountant, tutoring) because Polish boards
match them against Polish postings; `fields`, `domains`, `functions`, contract and work-time values are
language-neutral and read from titles in every language the country's language packs cover
("Księgowa", "Accountant" and "Buchhalterin" all have the field `finance`). The `główn|kierownik` pattern
(chief, head) is local too.

Search fields:

| Field | Meaning |
|---|---|
| `where` | `"remote"` (default), `"anywhere"`, `{"city", "radius_km", "or_remote", "country"}`, or `{"remote": true, "country": "de"}` (search another country's boards; they must be in `boards`). A city search passes offers whose location names the city (or an alias), and offers a board with a verified radius filter (`neetscape boards`) found with that filter for the same city at no larger radius (a town 25 km away matches a 30 km search; OLX measures its radius loosely) |
| `what` | `"all"` or a list of phrases; `keywords_for` overrides phrases per board |
| `worktime`, `contracts` | allowed values; an offer passes if its work time **or** one of its contracts is allowed. Contracts: `employment` (old name `uop` still accepted), `b2b`, `mandate`, `specific_task`, `internship`, `freelance`, `mini_job`, `working_student`, `temp_agency`, `other`; local words of the profile's country (`minijob`, `werkstudent`) are accepted too |
| `levels_exclude` | `intern junior mid senior lead manager unknown` |
| `fields`, `fields_exclude` | one job field per offer (`ai_automation security qa devops_cloud data erp_crm it_support it_admin software_dev product_project design ecommerce customer_service sales marketing hr finance legal retail admin_office logistics engineering manufacturing healthcare education hospitality`; `other` when nothing matches), read from the title, then the board's category, as function x domain with the language packs' `function` and `domain` vocabularies ("HR Automation Specialist" is `ai_automation`, "Test Automation Engineer" `qa`, "AI Gateway Product Owner" `product_project`). An offer with field `other` is unknown to `fields` (see `unknown`, dimension `field`) and passes `fields_exclude` |
| `domains` | what the work is about, any of the offer's domains: `ai security erp data cloud software it tech ecommerce industrial construction manufacturing logistics hr finance legal health education hospitality retail customer sales marketing office design product`. An offer has every domain its title (head and qualifier) and the board's category name, in the offer's own languages, not the posting: "AI Gateway Product Owner" `ai, product`, "Sachbearbeiter (m/w/d) Buchhaltung" `finance`, "Specjalista ds. logistyki" `logistics`. `tech` ("System Administrator") counts only when no other domain is named. An offer with no domain is unknown (dimension `domain`) |
| `functions`, `functions_exclude` | what the person does: `assist test automate develop design teach care serve sell market people account transport operate build manage_project cook_clean shop law support administer engineer analyse consult manage specialist`. An offer with no function is unknown to `functions` (dimension `function`) and passes `functions_exclude` |
| `pay` | `{"min", "per": "month"\|"hour", "required"}`; amounts are in the profile country's currency (PLN, EUR), compared against the top of the offer's range |
| `max_age_days` | drop offers published earlier |
| `title_include`, `title_exclude`, `text_exclude`, `category_include` | case-insensitive Python regexes; `text_exclude` reads title, company, category, industry, skills, pay text, card text and, once fetched, the posting; `category_include` the board's category and industry |
| `unknown` | `keep` (default) or `drop` offers whose filtered field is unknown, for every dimension, or a mapping per dimension (below) |
| `boost` | score added to offers passing this search |
| `remote_proof` | remote searches: once the posting is fetched, it must describe remote work and mention no hybrid model or required presence (client visits, business trips, office days, relocation); before that the field is unknown (`unknown`). Precision over recall: "remote or hybrid, your choice" fails |

### Unknown values

A filter needs a field the offer may lack: a card without pay, a title nothing is read from. Such an offer is
neither in nor out, and `unknown` decides per dimension:

| Dimension | Unknown when the search filters on | and the offer has |
|---|---|---|
| `location` | `where` with a city | no location |
| `mode` | `where` remote | work mode `unknown` |
| `remote_proof` | `remote_proof` | no fetched posting |
| `worktime` | `worktime` / `contracts` | neither a matching value nor a known one |
| `pay` | `pay.min` | no pay (a per-project budget counts as none) |
| `date` | `max_age_days` | no publication date |
| `field` | `fields` | field `other` |
| `domain` | `domains` | no domain |
| `function` | `functions` | function `unknown` |

`"unknown": "keep"` (default) or `"drop"` applies to every dimension. A mapping sets them one by one, with
`default` for the rest: `{"default": "keep", "domain": "drop", "remote_proof": "drop"}`. Exclude filters
(`fields_exclude`, `functions_exclude`, `title_exclude`...) never drop an offer for a missing value.

When both `defaults` and a search set `unknown`, they merge dimension by dimension and the search's win; a
string `X` counts as `{"default": X}`. So `defaults: {"unknown": {"domain": "drop"}}` with a search's
`"unknown": "keep"` keeps every unknown except a missing domain; a search's `{"pay": "keep"}` under
`defaults: {"unknown": "drop"}` drops every unknown except pay. Every other key of a search replaces the
same key of `defaults`.

### Fields, domains or functions

`fields` gives each offer one field, so AI work in another role lands elsewhere: "AI Gateway Product Owner" is
`product_project`, "AI Content Creator" `marketing`. When the person's criterion is a subject in any role
("AI or IT, but not sales, HR or marketing"), filter by domain and exclude functions instead:

```json
"defaults": {"domains": ["ai", "it", "data", "erp", "security", "cloud"],
             "functions_exclude": ["sell", "market", "people", "account", "shop"],
             "unknown": {"default": "keep", "domain": "drop"}}
```

The same works outside IT: a nurse who would take any healthcare job except selling medical equipment
(`"Przedstawiciel medyczny"`, a medical sales rep, is `health` and `sell`):

```json
"defaults": {"domains": ["health"], "functions_exclude": ["sell", "market"]}
```

`fields` stays the simpler choice when the person names a role ("IT support", "QA", `healthcare`,
`education`).

Top-level keys: `country` (`pl` default, `de`), `boards` (board names or groups: a country code, `intl`, `all`;
default: the boards of the profile's country and of every country a search targets), `candidate` (free-form notes
for the reviewing agent, ignored by the tool), `rank` (`rules`, `tags`, `sort`), `review` (`mode`
`auto`/`listing`, `details_top`, `min_score`; see below), `politeness` (`min_interval_s` per host, overriding a
board's own minimum; `retries`: how often the crawl refetches a page that failed transiently, after 20 s
then 60 s, default 2), `blacklist` (below),
`fx` (units of the country's currency per unit of another currency; the country sets defaults). The full definition is
[`neetscape/profile/schema.json`](../neetscape/profile/schema.json).

`review` controls the second stage (see [How it works](how-it-works.md#postings-the-second-stage)):
with `mode: "auto"`, `run` fetches the postings of the top `details_top` (default 60) matches scoring at
least `min_score` whose job has no stored posting yet, then evaluates again; with `mode: "listing"` it
fetches none and `neetscape details` does it on demand. The default is `auto` when the profile has rank
rules, `listing` otherwise.

## Blacklist

Your own list of employers, links and phrases to avoid; neetscape ships no built-in list.

```json
"blacklist": {
  "companies": ["example staffing"],
  "urls": ["example-agency\\.pl"],
  "text": ["network marketing|mlm"],
  "action": "drop"
}
```

| Key | Meaning |
|---|---|
| `companies` | regexes on the company name |
| `urls` | regexes on the offer URL (e.g. a domain) |
| `text` | regexes on title, company, card text and the fetched posting |
| `action` | `drop` (default): rejected in every search, reason `blacklisted company /.../` etc.; `flag`: kept, tagged `!blacklist`, the reason shown with the offer and by `neetscape show ID` |

All patterns are case-insensitive. Because `text` also reads postings, an offer can be dropped or
flagged only after its posting has been fetched.
