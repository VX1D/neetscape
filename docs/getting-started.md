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

neetscape init --preset focused --preset side   # writes profile.json; edit it (--country de for Germany)
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
| Setup | `init [--country CC] [--preset P ...]`, `check`, `plan`, `boards [--country CC]`, `probe BOARD [--keyword K] [--save-fixture PATH]` |
| Run | `run [--resume] [--full] [--limit-pages N] [--boards a,b] [--record DIR]`; single steps `crawl`, `eval`, `report` |
| Review | `list [--search ID] [--new] [--group title] [--where SQL] [--limit N] [--format tsv\|md\|json]`, `details --pick IDS \| --pick-file F \| --top N \| --marked`, `show ID`, `sql "SELECT ... :run"` |
| Tracking | `mark ID\|URL STATUS [--note TEXT]`, `tracked` |

Common options: `--profile` (default `profile.json`), `--out` (data directory, default `runs`),
`--run` (run id, default latest). Mark statuses: `shortlisted applied interview offer rejected
ignored`; `rejected` and `ignored` offers are hidden from later listings.

Each run writes `runs/<date>-run<N>/` with `REPORT.md`, `REPORT.html` (open it in a browser: your
review on top, then every passing offer in a filterable, sortable table), `listing.tsv` and `offers.csv`.

## Presets

`neetscape init` writes `profile.json` from one or more presets (`--preset` is repeatable, default
`focused`; `--country` defaults to `pl`). With several presets the searches are concatenated; other
settings come from the first preset that sets them. A country's own presets
(`neetscape/countries/<cc>/presets/`) take precedence over the shared ones in
`neetscape/profile/presets/`, which fill the rest. `init` refuses to overwrite an existing `profile.json`.

| Preset | Searches | Review mode | Poland (`pl`) | Germany (`de`) |
|---|---|---|---|---|
| `focused` | one remote search with phrases, title include/exclude, levels excluded, monthly pay floor; rank rules and tags (an example to adapt) | `auto` (opens the top N postings during `run`) | shared (Polish/English phrases, PLN floor) | shared: rewrite phrases and the floor in EUR |
| `broad` | every remote offer, no phrases | `listing` | shared | own |
| `local` | every offer within a radius of a city | `listing` | shared (Kraków, 30 km) | own (Berlin, 25 km) |
| `side` | remote part-time / flexible work or side contracts, hourly pay floor, junk filter, score boost | `listing` | shared (mandate / specific task / freelance, 30 PLN/h) | own (Minijob / Werkstudent / freelance, 15 €/h) |
