# Changelog

All notable changes to neetscape are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

- Postings as a second stage: listing cards are filtered first and postings are fetched only for
  matches. In `review.mode: "auto"`, `run` fetches the top `details_top` matches whose job has no stored
  posting yet (once per job across runs) and re-evaluates; `details` re-evaluates too and logs how many
  offers no longer pass. New `details --marked`; `--top` skips jobs whose posting is already stored.
- A fetched posting fills unknown work mode (strong signals only: JSON-LD `TELECOMMUTE`, explicit full
  remote, hybrid words), work time and contracts; `text_exclude` and the blacklist also read it.
- Posting text is only the posting body: from a board API (nofluffjobs, LinkedIn guest posting), the
  board's `posting()` (JSON-LD by default, embedded data for pracuj.pl and Indeed) or its
  `posting_selector`, never the whole rendered page. The source is stored. 401/403/429 answers are
  stored as blocked and not rendered.
- Profile `blacklist`: your own `companies` / `urls` / `text` regexes, `action` `drop` (default) or `flag`
  (kept, tagged `!blacklist`). No built-in list.
- `REPORT.html` next to `REPORT.md`: a list / detail review (tabs Review and All) in English, German or
  Polish; the posting formatted for reading with its red flags; grouping, sorting and filters behind one
  View button; keyboard navigation; decisions on the page copied as one block of `neetscape mark` commands.
- Mode inference: hybrid wording beats a generic "remote"; explicit full remote and "remote or hybrid"
  choices read as remote; "hybrid cloud" and similar no longer read as hybrid. More Polish contract words.
- Politeness: boards can declare a minimum interval per host (theprotocol.it: 4 s); the profile's
  `politeness.min_interval_s` overrides it.
- Crawler: single-response listings (`whole_listing`: feeds, solid.jobs) complete their request; a 404
  after the last page ends a request as complete; reaching the page cap never does. HTTP boards can POST
  (`post_body`). A stuck browser navigation is retried once instead of stalling a board.
- Boards (Poland): new **gowork.pl** (own postings only; imported copies of other sites' ads skipped) and
  **praca.pl**; nofluffjobs moved to its public search API (HTTP POST); theprotocol.it supports keywords;
  bulldogjob moved to its GraphQL API (publication dates, work modes); solid.jobs reads every division,
  not only IT; Indeed reads the embedded JSON (one public page; "Zdalnie" with a place read as hybrid);
  useme over plain HTTP, closed projects skipped, budgets parsed; OLX reads the embedded state and uses
  its server-side remote filter. LinkedIn postings read only the description block and job criteria.
- No board reads rendered result cards any more: Indeed, useme and OLX moved from `browser_render` to
  their embedded data or plain HTTP.
- Docs: boards deliberately not supported (praca.gov.pl / CBOP) and the terms check in CONTRIBUTING.

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
