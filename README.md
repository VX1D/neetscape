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

## Features

- **Composable searches**: remote or a city with a radius, specific phrases or everything, plus
  filters for work time, contract type, level, pay, posting age and title/text patterns.
- **Many boards, one listing**: duplicates across boards are merged; new and removed offers are
  tracked between runs.
- **Countries as plug-ins**: Poland and Germany today, each with its own boards, currency,
  language and presets. Adding a country is adding a directory.
- **Two-pass review**: skim thousands of offers as a listing, then open only the postings worth reading.
- **Local and polite**: your data stays on your machine; public pages only, no logins, rate-limited.

## Quick start

With an agent:

```
git clone https://github.com/VX1D/neetscape && cd neetscape
claude    # or any agent that reads AGENTS.md
> Here is my CV: ~/cv.pdf. Find me remote work; side jobs welcome.
```

By hand (Python 3.10+, a Chromium-family browser, ideally `Xvfb`):

```
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
neetscape init --preset broad      # write profile.json (add --country de for Germany)
neetscape plan                     # what will be fetched from which board
neetscape run --limit-pages 2      # a quick first crawl
neetscape list --group title       # skim the results
neetscape show 12                  # read one offer
```

## Boards

| Country | Boards |
|---|---|
| Poland | justjoin.it, rocketjobs.pl, pracuj.pl, nofluffjobs, theprotocol.it, bulldogjob, solid.jobs, Indeed, useme, OLX |
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
| [How it works](docs/how-it-works.md) | architecture, crawling, de-duplication, the database and SQL recipes |
| [Boards and countries](docs/boards-and-countries.md) | supported boards, country packages, responsible use, limitations |
| [Testing](docs/testing.md) | offline tests, affected-only runs, live checks |
| [AGENTS.md](AGENTS.md) | the workflow a coding agent follows |
| [CONTRIBUTING.md](CONTRIBUTING.md) | adding or fixing a board, adding a country |

## License

MIT, see [LICENSE](LICENSE). Changes are listed in [CHANGELOG.md](CHANGELOG.md).
