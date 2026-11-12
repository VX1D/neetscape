# Search profile

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Reviewing](review.md) · [Testing](testing.md)

A profile is the union of its searches: conditions inside a search are ANDed, an offer passes the
profile if it passes any search. `defaults` are merged into every search. Rank rules only order
results; they never drop anything.

```json
{
  "version": 2,
  "country": "pl",
  "boards": ["pl"],
  "defaults": {"max_age_days": 30, "unknown": "keep"},
  "searches": [
    {"id": "main", "where": "remote", "what": ["automation", "n8n", "helpdesk"],
     "keywords_for": {"linkedin": ["AI automation", "IT support"]},
     "title_exclude": ["senior|lead|architect"], "pay": {"min": 8000, "per": "month"}},
    {"id": "krk", "where": {"city": "Kraków", "radius_km": 30, "or_remote": true}, "what": "all",
     "contracts": ["employment", "b2b"]},
    {"id": "side", "where": "remote", "what": "all", "worktime": ["part_time", "flexible"],
     "contracts": ["mandate", "specific_task", "freelance"], "pay": {"min": 40, "per": "hour"}, "boost": 3}
  ],
  "rank": {"rules": [{"pattern": "n8n|zapier", "weight": 3}], "sort": ["score", "new", "pay"]},
  "review": {"mode": "listing"}
}
```

Search fields:

| Field | Meaning |
|---|---|
| `where` | `"remote"` (default), `"anywhere"`, `{"city", "radius_km", "or_remote", "country"}`, or `{"remote": true, "country": "de"}` (search another country's boards; they must be in `boards`). A city search passes offers whose location names the city (or an alias), and offers a board with a verified radius filter (`neetscape boards`) found with that filter for the same city at no larger radius (a town 25 km away matches a 30 km search; OLX measures its radius loosely) |
| `what` | `"all"` or a list of phrases; `keywords_for` overrides phrases per board |
| `worktime`, `contracts` | allowed values; an offer passes if its work time **or** one of its contracts is allowed. Contracts: `employment` (old name `uop` still accepted), `b2b`, `mandate`, `specific_task`, `internship`, `freelance`, `mini_job`, `working_student`, `temp_agency`, `other`; local words of the profile's country (`minijob`, `werkstudent`) are accepted too |
| `levels_exclude` | `intern junior mid senior lead manager unknown` |
| `fields`, `fields_exclude` | job fields (`ai_automation security qa devops_cloud data erp_crm it_support it_admin software_dev product_project design ecommerce customer_service sales marketing hr finance legal retail admin_office logistics engineering manufacturing healthcare education hospitality other`), read from the title, then the board's category, with the language packs' `field` vocabularies (first match in that order wins: "HR Automation Specialist" is `ai_automation`, "Test Automation Engineer" `qa`). `neetscape eval` re-reads them, so a vocabulary change needs no crawl |
| `pay` | `{"min", "per": "month"\|"hour", "required"}`; amounts are in the profile country's currency (PLN, EUR), compared against the top of the offer's range |
| `max_age_days` | drop offers published earlier |
| `title_include`, `title_exclude`, `text_exclude`, `category_include` | case-insensitive Python regexes; `text_exclude` reads title, company, category, skills, pay text, card text and, once fetched, the posting |
| `unknown` | `keep` (default) or `drop` offers whose filtered field (mode, pay, work time, date, location) is unknown |
| `boost` | score added to offers passing this search |
| `remote_proof` | remote searches: once the posting is fetched, it must describe remote work and mention no hybrid model or required presence (client visits, business trips, office days, relocation); before that the field is unknown (`unknown`). Precision over recall: "remote or hybrid, your choice" fails |

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
