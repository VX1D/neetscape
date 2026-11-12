# Changelog

All notable changes to neetscape are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## 0.1.0 — first release

- `neetscape` CLI: `init` (presets, `--country`), `check`, `plan` (no network), `boards [--country CC]`,
  `probe`, `run` (`--resume`, `--full`, `--limit-pages`, `--boards`, `--record`), the single steps
  `crawl`, `eval`, `report`, and the review commands `list`, `details`, `show`, `sql`, `mark`, `tracked`.
- JSON search profile (schema in `neetscape/profile/schema.json`): a union of searches with
  `where`, `what`, work time, contracts, levels, pay floor, age, regex filters, `unknown` keep/drop and
  `boost`, plus rank rules, tags and review settings. Presets `focused`, `broad`, `local`, `side`.
- Countries as packages (`neetscape/countries/<cc>/`): Poland (justjoin.it, rocketjobs.pl, pracuj.pl,
  nofluffjobs, Indeed, theprotocol.it, bulldogjob, solid.jobs, useme, OLX) and Germany (Arbeitnow,
  Bundesagentur für Arbeit Jobsuche) with their own currency, languages, contract words and presets;
  LinkedIn (public guest API) for every country; remoteok and We Work Remotely as opt-in international feeds.
- Language packs for Polish, German and English to read mode, work time, contracts, level and pay
  from free text.
- Planner that pushes only the conditions a board supports and deduplicates identical requests;
  crawler with three transports (`http`, `browser_fetch`, `browser_render`), a private Chromium on
  Xvfb or headless, and a per-host rate limiter with back-off.
- SQLite store (`runs/neetscape.db`) with versioned migrations: every fetched offer, cross-board
  clusters, requests and sightings, per-run `evals` and `rejections` (with reasons), postings and marks;
  incremental crawling and gone detection.
- Per-run `REPORT.md`, `listing.tsv` and `offers.csv`; `list --group title`; read-only `sql` with
  the `:run` parameter.
- `AGENTS.md` workflow for coding agents: profile from a CV, run, two-pass review, shortlist, marks.
- Offline test suite on recorded fixtures, `tests/affected.py` for changed files, `pytest -m live`
  smoke tests against the real boards.
