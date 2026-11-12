# Getting started

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Reviewing](review.md) · [Testing](testing.md)

## With a coding agent

```
git clone https://github.com/VX1D/neetscape && cd neetscape
claude          # or any agent that reads AGENTS.md / CLAUDE.md
> Here is my CV: ~/cv.pdf. Find me remote work; side jobs welcome.
```

The agent follows [AGENTS.md](../AGENTS.md).

## Manual use

Requirements: Python 3.10+, a Chromium-family browser (chromium, google-chrome, brave) and,
preferably, `Xvfb`.

```
python3 -m venv .venv && . .venv/bin/activate && pip install -e .

neetscape init                                  # asks a few questions, writes profile.json
neetscape check                                 # validate
neetscape plan                                  # what goes to which board (no network)
neetscape run                                   # crawl, evaluate, write the report
neetscape list --new --limit 50                 # offers new in this run
neetscape details --pick 12,40                  # fetch full postings for chosen ids, re-evaluate
neetscape show 12                               # offer, per-search verdict, posting text
neetscape mark 12 shortlisted --note "why · risk"  # record your decisions
neetscape report                                # rewrite REPORT.md / REPORT.html with the review
```

Commands at a glance (`neetscape --help` for all flags):

| Group | Commands |
|---|---|
| Setup | `init [--country CC] [--interactive]`, `init [--country CC] --preset P ...`, `check`, `plan`, `boards [--country CC]`, `probe BOARD [--keyword K] [--save-fixture PATH]` |
| Run | `run [--resume] [--full] [--limit-pages N] [--boards a,b] [--record DIR]`; single steps `crawl`, `eval`, `report` |
| Review | `list [--search ID] [--new] [--group title] [--where SQL] [--limit N] [--format tsv\|md\|json]`, `details --pick IDS \| --pick-file F \| --top N \| --marked`, `show ID`, `sql "SELECT ... :run"` |
| Tracking | `mark ID\|URL STATUS [--note TEXT]`, `tracked` |

Common options: `--profile` (default `profile.json`), `--out` (data directory, default `runs`),
`--run` (run id, default latest). Mark statuses: `shortlisted applied interview offer rejected
ignored`; `rejected` and `ignored` offers are hidden from later listings.

Each run writes `runs/<date>-run<N>/` with `REPORT.md`, `REPORT.html` (open it in a browser: your
review on top, then every passing offer in a filterable, sortable table), `listing.tsv` and `offers.csv`.

## Interactive init

On a terminal, `neetscape init` without `--preset` asks what to look for and writes a ready
`profile.json` (`--interactive` forces the questions, e.g. with answers piped in). Enter accepts the
default in brackets; lists are comma-separated; a bad answer is asked again with a hint.

| Question | Default | Becomes |
|---|---|---|
| Country (`de`, `pl`) | `--country`, else `pl` | `country`: currency, boards, language |
| Where: `remote`, `city` or `both`; then the city and a distance in km | `remote`; 30 km | `where` |
| What work: phrases sent to the boards | everything | `what` (phrases, or `"all"`) |
| Job domains to keep (`ai`, `it`, `data`, ...) | any | `domains` |
| Functions to exclude (`sell`, `market`, `people`, ...) | none | `functions_exclude` |
| Work time: `full`, `part` or `any` | any | `worktime` (`part` is part time or flexible) |
| Contract types (the country's own: `b2b`, `mandate`, `mini_job`, ...) | any | `contracts` |
| Minimum pay in the country's currency, then per month or per hour | none; month | `pay` |
| Seniority to exclude (`intern` ... `manager`) | none | `levels_exclude` |
| Ignore postings older than N days | 30 | `defaults.max_age_days` |

The rest (ranking, review mode `listing`) comes from the `broad` preset. The profile is validated
and summarised like `neetscape check`; then run `neetscape plan` and `neetscape run --limit-pages 2`
for a quick trial. The questions build one search: as in every search, work time and contract types
are alternatives (an offer passes with either). For several searches (a main job and side jobs),
title filters or rank rules, edit `profile.json` ([Search profile](profile.md)) or start from presets.

```
$ neetscape init
A few questions build profile.json. Enter accepts the [default]; lists are comma-separated.
Country: de (Germany), pl (Poland) [pl]:
Where: remote, city, or both (the city or remote) [remote]: both
City [-]: Kraków
Distance from the city, km [30]: 20
What work: phrases sent to the boards, e.g. n8n, helpdesk, data analyst [everything]: helpdesk, n8n
...
Minimum pay in PLN [none]: 9000
Per month or per hour [month]:
...
wrote profile.json
profile OK (pl, amounts in PLN): 1 search(es) [local-or-remote: Kraków +20km or remote (pl), 2 phrases], ...
```

## Presets

`neetscape init --preset NAME` writes `profile.json` from one or more presets instead (`--preset` is
repeatable; off a terminal `init` without `--preset` uses `focused`; `--country` defaults to `pl`). With several presets the searches are concatenated; other
settings come from the first preset that sets them. A country's own presets
(`neetscape/countries/<cc>/presets/`) take precedence over the shared ones in
`neetscape/profile/presets/`, which fill the rest. `init` refuses to overwrite an existing `profile.json`.

| Preset | Searches | Review mode | Poland (`pl`) | Germany (`de`) |
|---|---|---|---|---|
| `focused` | one remote search with phrases, title include/exclude, levels excluded, monthly pay floor; rank rules and tags (an example to adapt) | `auto` (opens the top N postings during `run`) | shared (Polish/English phrases, PLN floor) | shared: rewrite phrases and the floor in EUR |
| `broad` | every remote offer, no phrases | `listing` | shared | own |
| `local` | every offer within a radius of a city | `listing` | shared (Kraków, 30 km) | own (Berlin, 25 km) |
| `side` | remote part-time / flexible work or side contracts, hourly pay floor, junk filter, score boost | `listing` | shared (mandate / specific task / freelance, 30 PLN/h) | own (Minijob / Werkstudent / freelance, 15 €/h) |
