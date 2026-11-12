# Boards and countries

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Testing](testing.md)

## Boards

`neetscape boards` prints the live capability table: country (`pl`, `de`, `any` for
boards serving every country, `intl`), transport, and
whether the board supports keyword search, a remote filter (`filter`, `always` for remote-only
boards, or `no`), city search, a part-time filter, newest-first sorting, and its page limit.
Poland: justjoin.it, rocketjobs.pl, pracuj.pl, nofluffjobs, Indeed, theprotocol.it, bulldogjob,
solid.jobs, useme and OLX. Germany: Arbeitnow (API) and the Bundesagentur für Arbeit Jobsuche (API).
Both: LinkedIn (public guest search). remoteok and We Work Remotely are international and opt-in
(`"boards": ["pl", "intl"]`). `neetscape boards --country de` shows only the boards serving
Germany (its own plus LinkedIn).

`neetscape probe BOARD [--keyword K]` fetches one page from a board and shows how well each field
is filled, which is the first thing to check when a board returns nothing; `--save-fixture PATH`
also writes the raw page, ready to be added to `tests/fixtures/<cc>/` (`tests/fixtures/shared/` for LinkedIn and the feeds).

Adapters live in `neetscape/countries/<cc>/boards/` (one module per board) and, for the shared boards
(LinkedIn, international feeds), in `neetscape/boards/`, next to the code all adapters use (`base`, `fetch`,
`pages`). A board declares `Caps`, turns a search into `Request`s,
builds page URLs and parses raw pages into offers with a pure `parse()` function tested on
recorded fixtures. [CONTRIBUTING.md](../CONTRIBUTING.md) explains how to add or fix one.

## Countries

A country is a package `neetscape/countries/<cc>/`: `__init__.py` defines a `Country` (currency and
exchange rates, languages, hours per month, LinkedIn location, city aliases such as
München/Munich, legal-form words for de-duplication, contract words, default boards), `boards/`
holds its adapters (registered with that country) and `presets/` its profile presets. Free text
is read with the language packs `neetscape/lang/<code>.py` (vocabularies plus an `EXAMPLES` table
that the tests check); English is always added.

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
  shared by crawling and posting fetches, with growing back-off on errors (longer on HTTP 429). Slow down further with
  `politeness.min_interval_s`.
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
- Posting hints (remote, years, degree, languages) are regex extractions; read the posting.
