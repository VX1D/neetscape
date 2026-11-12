# neetscape

[![tests](https://github.com/VX1D/neetscape/actions/workflows/test.yml/badge.svg)](https://github.com/VX1D/neetscape/actions/workflows/test.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A job offer radar for the job boards of one country at a time. You describe what you are looking
for as a profile of searches; neetscape crawls the boards, keeps every offer in a local SQLite
database, filters and ranks them, and hands you a listing to review.

It is built to be driven by a coding agent (Claude Code, Codex or similar): the agent reads your
CV, writes the profile, runs the crawl, reads the postings and gives you a shortlist, following
[AGENTS.md](AGENTS.md). neetscape itself makes no LLM calls and needs no API keys.

## Who it is for

Anyone looking for work, in any job: an accountant, a nurse, a warehouse worker, a developer, a
student after a side job. You (or your agent) write a `profile.json` with one search per intent.
The keys are the same in every country; phrases in `what` go to the boards as they are, so write them
in the boards' language. Three examples for Poland, one search each:

A remote IT role:

```json
{"id": "it", "where": "remote", "what": ["it support", "helpdesk"],
 "fields": ["it_support", "it_admin"], "levels_exclude": ["senior", "lead", "manager"]}
```

An on-site job near a city (*księgowa*: accountant):

```json
{"id": "accounting", "where": {"city": "Poznań", "radius_km": 25},
 "what": ["księgowa", "accountant"], "fields": ["finance"], "contracts": ["employment"]}
```

Side jobs, any field:

```json
{"id": "side", "where": "remote", "what": "all", "worktime": ["part_time", "flexible"],
 "contracts": ["mandate", "freelance"], "pay": {"min": 40, "per": "hour"}}
```

`neetscape init --preset focused|broad|local|side` writes a starting profile to edit;
[docs/profile.md](docs/profile.md) has every key.

## Features

- **Composable searches**: remote or a city with a radius, specific phrases or everything, plus
  filters for work time, contract type, level, pay, posting age and title/text patterns.
- **Job fields, domains and functions**: every offer's title (and the board's category) is read as
  what the work is about (`domains`: `finance`, `health`, `logistics`, `it`...) and what the person
  does (`functions`: `account`, `care`, `transport`, `sell`...), combined into one job field (`fields`).
  Filter by a role, or by a subject in any role ("healthcare, but not sales").
- **Unknown is not a failure**: a card without pay or a title nothing is read from is kept or dropped
  per dimension (`"unknown": {"default": "keep", "pay": "drop"}`).
- **Explained values**: `neetscape show ID` prints where each value came from (board data, the
  search, the title, the posting) and the phrase that set it, plus why each search passed or failed.
- **Re-judge without crawling**: after changing the profile or the vocabularies, `neetscape eval`
  derives and filters the stored offers again in seconds.
- **Countries as packages, languages as packs**: Poland and Germany today, each with its boards,
  currency, presets and contract words; titles and postings are read with per-language vocabularies
  (Polish, German, English). Adding a country is adding a directory.
- **Many boards, one listing**: duplicates across boards are merged; new and removed offers are
  tracked between runs.
- **Postings only for matches**: listing cards are filtered first; full postings are fetched only
  for matching offers (once per job), and then settle unknown work mode, hours and contracts.
- **Your own blacklist**: companies, links or phrases to drop or flag.
- **Comfortable review**: `REPORT.html` is a list / detail view: group, sort and filter the list, read the
  selected offer with its red flags (years, degree, languages) and full posting, move with `j`/`k`.
- **Local and polite**: your data stays on your machine; public pages only, no logins, rate-limited
  per host.

## Requirements

Python 3.10+ (`pip install -e .` adds its one dependency, `websockets`) and, for the boards that need
one, a Chromium-family browser.
neetscape starts its own private browser instance with a separate profile; it never uses yours.

- **Linux**: tested. The browser is found on `PATH` (`chromium`, `google-chrome`, `brave`...) or
  set with `NEETSCAPE_BROWSER`. With `Xvfb` installed it runs on a virtual display (fewer bot walls),
  otherwise headless.
- **macOS**: untested. Browsers in `/Applications` are not on `PATH`, so set `NEETSCAPE_BROWSER`, e.g.
  `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`; without Xvfb it runs headless.
- **Windows**: not supported natively (the CLI relies on POSIX signals and process groups). WSL2
  should behave like Linux but is untested.

## Quick start

With an agent:

```
git clone https://github.com/VX1D/neetscape && cd neetscape
claude    # or any agent that reads AGENTS.md
> Here is my CV: ~/cv.pdf. Find me work near Wrocław; part-time is fine.
```

By hand:

```
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
neetscape init --preset focused    # write profile.json, then edit it (add --country de for Germany)
neetscape plan                     # what will be fetched from which board
neetscape run --limit-pages 2      # a quick first crawl
neetscape list --group title       # skim the results
neetscape show 12                  # read one offer
```

## Boards

| Country | Boards |
|---|---|
| Poland | justjoin.it, rocketjobs.pl, pracuj.pl, nofluffjobs, theprotocol.it, bulldogjob, solid.jobs, Indeed, useme, OLX, gowork.pl, praca.pl |
| Germany | Arbeitnow, Bundesagentur für Arbeit (Jobsuche) |
| Any country | LinkedIn (public guest search) |
| International, opt-in | remoteok, We Work Remotely |

`neetscape boards` shows what each board can filter. Missing your country or a board?
See [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

| | |
|---|---|
| [Getting started](docs/getting-started.md) | installation, the full command set, presets |
| [Search profile](docs/profile.md) | how to describe what you are looking for |
| [How it works](docs/how-it-works.md) | architecture, crawling, postings as a second stage, de-duplication, reports, the database and SQL recipes |
| [Boards and countries](docs/boards-and-countries.md) | supported boards, country packages, responsible use, limitations |
| [Reviewing a large crawl](docs/review.md) | the cheap, precise funnel from thousands of offers to a shortlist |
| [Testing](docs/testing.md) | offline tests, live checks |
| [AGENTS.md](AGENTS.md) | the workflow a coding agent follows |
| [CONTRIBUTING.md](CONTRIBUTING.md) | adding or fixing a board, adding a country |

## License

MIT, see [LICENSE](LICENSE). Changes are listed in [CHANGELOG.md](CHANGELOG.md).
