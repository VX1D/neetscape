# Search profile

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Testing](testing.md)

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
| `where` | `"remote"` (default), `"anywhere"`, `{"city", "radius_km", "or_remote", "country"}`, or `{"remote": true, "country": "de"}` (search another country's boards; they must be in `boards`) |
| `what` | `"all"` or a list of phrases; `keywords_for` overrides phrases per board |
| `worktime`, `contracts` | allowed values; an offer passes if its work time **or** one of its contracts is allowed. Contracts: `employment` (old name `uop` still accepted), `b2b`, `mandate`, `specific_task`, `internship`, `freelance`, `mini_job`, `working_student`, `temp_agency`, `other`; local words of the profile's country (`minijob`, `werkstudent`) are accepted too |
| `levels_exclude` | `intern junior mid senior lead manager unknown` |
| `pay` | `{"min", "per": "month"\|"hour", "required"}`; amounts are in the profile country's currency (PLN, EUR), compared against the top of the offer's range |
| `max_age_days` | drop offers published earlier |
| `title_include`, `title_exclude`, `text_exclude`, `category_include` | case-insensitive Python regexes |
| `unknown` | `keep` (default) or `drop` offers whose filtered field (mode, pay, work time, date, location) is unknown |
| `boost` | score added to offers passing this search |

Top-level keys: `country` (`pl` default, `de`), `boards` (board names or groups: a country code, `intl`, `all`;
default: the boards of the profile's country and of every country a search targets), `candidate` (free-form notes
for the reviewing agent, ignored by the tool), `rank` (`rules`, `tags`, `sort`), `review` (`mode`
`auto`/`listing`, `details_top`, `min_score`), `politeness` (`min_interval_s` per host, `retries`),
`fx` (units of the country's currency per unit of another currency; the country sets defaults). The full definition is
[`neetscape/profile/schema.json`](../neetscape/profile/schema.json).
