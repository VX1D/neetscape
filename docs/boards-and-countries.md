# Boards and countries

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Reviewing](review.md) · [Testing](testing.md)

## Boards

`neetscape boards` prints the live capability table: country (`pl`, `de`, `any` for
boards serving every country, `intl`), transport, and
whether the board supports keyword search, a remote filter (`filter`, `always` for remote-only
boards, or `no`), city search, a part-time filter, newest-first sorting, and its page limit.
`neetscape boards --country de` shows only the boards serving Germany (its own plus LinkedIn).

| Board | Country | Source | Notes |
|---|---|---|---|
| justjoin.it, rocketjobs.pl | pl | offers embedded in the result page (browser) | same engine; rocketjobs covers non-IT jobs |
| pracuj.pl | pl | `__NEXT_DATA__` of the result page (browser) | keyword listings are by relevance, so only keyword-less ones stop at known pages |
| nofluffjobs | pl | the site's public search API (HTTP POST) | the remote filter keeps fully remote offers only; postings from its posting API |
| theprotocol.it | pl | `__NEXT_DATA__` of the result page (browser) | keywords supported; throttles hard, so requests are at least 4 s apart |
| bulldogjob | pl | the site's GraphQL API (HTTP POST) | no keyword search; publication dates and work modes from the API |
| solid.jobs | pl | JSON API, one download per division | every division (IT, sales, engineering, marketing, ...), filtered locally |
| Indeed | pl | JSON embedded in the result page (browser) | only the first page (15 offers) is public per request; "Zdalnie" is often hybrid in the posting, so remote+hybrid tags with a place read as hybrid |
| useme | pl | server-rendered result pages (HTTP) | freelance projects, always remote, pay is the project budget; closed projects skipped |
| OLX | pl | listing state embedded in the result page (browser) | the remote filter is server-side; remote with other workplaces reads as hybrid |
| gowork.pl | pl | Nuxt payload of the result page (HTTP) | only gowork's own postings; imported copies of other sites' ads are skipped |
| praca.pl | pl | server-rendered result pages (HTTP) | dates are relative (last refresh) |
| Arbeitnow | de | JSON API | |
| Bundesagentur für Arbeit (Jobsuche) | de | JSON API | no remote filter; remote searches add "Homeoffice" |
| LinkedIn | any | public guest search and posting endpoints (HTTP) | ignores remote, job-type, distance and sort filters |
| remoteok, We Work Remotely | intl, opt-in | JSON / RSS feed | remote only; enable with `"boards": ["pl", "intl"]` |

A board's labels for an offer go into two fields. `category` is the role or job category ("backend",
"Specjalista ds. obsługi klienta", "Finanzbuchhalter/in"): job fields, functions and domains are read from
it when the title says nothing, and `category_include` filters on it. `industry` is the employer's industry
("it i telekomunikacja"): context, shown by `neetscape show` and read by `text_exclude` and the blacklist,
but never a domain, so a salesperson at a telecom is in sales, not in IT. Every board's categories are roles
except rocketjobs' `sales` and `support` categories, whose subcategory is the industry ("sales it i
telekomunikacja" -> category `sales`, industry `it i telekomunikacja`). Each adapter's docstring says which
its labels are.

"Browser" boards are read with a same-origin fetch from a tab of the private browser
(`browser_fetch`), because they do not serve a plain HTTP client; the result is still the board's own
data, not the rendered page.

`neetscape probe BOARD [--keyword K]` fetches one page from a board and shows how well each field
is filled, which is the first thing to check when a board returns nothing; `--save-fixture PATH`
also writes the raw page, ready to be added to `tests/fixtures/<cc>/` (`tests/fixtures/shared/` for LinkedIn and the feeds).

Adapters live in `neetscape/countries/<cc>/boards/` (one module per board) and, for the shared boards
(LinkedIn, international feeds), in `neetscape/boards/`, next to the code all adapters use (`base`, `fetch`,
`pages`). A board declares `Caps`, turns a search into `Request`s,
builds page URLs and parses raw pages into offers with a pure `parse()` function tested on
recorded fixtures. A board may also read the posting body itself (`posting_body()`, e.g. from its embedded
data), point to a posting API, declare a CSS selector for the posting body, and declare a minimum
interval between requests. [CONTRIBUTING.md](../CONTRIBUTING.md) explains how to add or fix one.

### Boards deliberately not supported

Check this list before proposing a board; these are not accepted.

- **praca.gov.pl / CBOP (oferty.praca.gov.pl)**, the public employment services' offer database.
  Its official channel for integrators is a separate WebService, available only after signing its
  terms of access ("Warunki udostępniania": a fixed IP address, a 17:00–07:00 access window, request
  limits). Those terms also require an entity that collects and publishes ePraca offers to be
  registered in KRAZ (Rejestr Agencji Zatrudnienia, the register of employment agencies). Querying
  the site's internal portal API instead would bypass that official channel, so neetscape does not
  ship an adapter for it.

## Countries

A country is a package `neetscape/countries/<cc>/`: `__init__.py` defines a `Country` (currency and
exchange rates, languages, hours per month, LinkedIn location, city aliases such as
München/Munich, legal-form words for de-duplication, contract words, default boards), `boards/`
holds its adapters (registered with that country) and `presets/` its profile presets. Free text
is read with the language packs `neetscape/lang/<code>.py` (vocabularies; `neetscape/infer.py` decides
between their matches); English is always added.

One database holds one country's offers, because pay is stored in that country's currency:
`neetscape run` refuses a profile of another country than the previous runs in the same `--out`.
A profile can still search another country (`"where": {"remote": true, "country": "de"}`); its
pay is converted with `fx`.

German specifics: "Homeoffice möglich", "teilweise Homeoffice" and "mobiles Arbeiten" are read as
hybrid, only "100% Homeoffice", "vollständig/komplett remote" or "deutschlandweit remote" as
remote; "befristet" is a hint, not a contract; bare amounts such as "45.000–55.000 €" are yearly.

## Responsible use

- No logins, no accounts, no CAPTCHA solving: only pages and APIs that are public without signing in.
- Low request rates by default: at least ~1.5 s (with jitter) between requests to the same host,
  shared by crawling and posting fetches, with growing back-off on errors (longer on HTTP 429). Boards
  that throttle harder declare a longer minimum (theprotocol.it: 4 s). Set your own per host with
  `politeness.min_interval_s`, which overrides both.
- Postings are fetched only for offers that already match, once per job.
- A blocked posting (HTTP 401/403/429) is stored as such; the page is not rendered to get around it.
- Respect each board's terms of use and robots policy.
- Run infrequently (e.g. once or twice a week); incremental crawling keeps later runs short.
- Data stays local in `runs/`. `profile.json`, CVs and `runs/` are git-ignored.

## Limitations

- Boards change their markup and URLs; an adapter then returns nothing or errors until updated.
  Check the board table in `REPORT.md` after each run.
- Not every board supports every condition server-side. City searches in particular are served
  only by some boards; `neetscape plan` lists what is skipped.
- Some boards cap results (e.g. LinkedIn around 1000 per query) and may rate-limit; a cut-off
  request is not complete and does not mark offers as gone.
- LinkedIn is read through its public guest API, which ignores the remote, job-type, distance and
  sort filters; its offers have an unknown work mode until the posting is opened
  (`unknown: keep` keeps them in remote searches, `unknown: drop` leaves them out).
- Mode, work time, contract, level and pay are parsed from board data and text; unknown values
  are common. Choose `unknown: keep` or `drop` deliberately.
- Pay is normalised to a monthly amount in the profile country's currency with fixed exchange rates
  and the country's hours / days per month (Poland 168 h, Germany 173 h; 21 days), for thresholds
  and ranking only. Per-project pay is not normalised.
- Indeed serves one public page per request (15 offers); deeper pages need a login and are not read.
- Mode inference from text: hybrid wording wins over a generic "remote" ("hybrid, 2 days remote" is
  hybrid); explicit full remote ("100% zdalnie", "fully remote") and an offered choice ("remote or
  hybrid", "zdalnie lub hybrydowo") read as remote.
- Posting hints (remote, years, degree, languages) are regex extractions; read the posting.
