# Changelog

All notable changes to neetscape are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

- Tests: every board's parser is checked by one table (`COVERAGE` in `tests/countries/test_countries.py`:
  the fields it must fill on its recorded page); per-board files keep only the board's own rules. Exact
  URLs and per-offer values are no longer pinned (`neetscape probe` checks a board live); a few report
  formatting tests and `tests/affected.py` are removed.
- docs/review.md: a cheap, high-precision review workflow for large crawls (narrow with the profile and `eval`,
  pick by title, let posting rules drop what they can, read only the survivors; when to use subagents).
- Search option `remote_proof`: a remote search passes an offer only when its fetched posting describes remote
  work and mentions no hybrid model or required presence; a new posting hint `office` (client visits, business
  trips, office days, relocation). Stronger "fully remote" phrases (Polish "z dowolnego miejsca", "100% pracy
  zdalnej"; English "work from anywhere", "remote only", "work from home"); "remote-first" no longer counts as
  fully remote; Polish "pracę zdalną" / "w trybie zdalnym" read as remote.
- City searches: an offer a board with a verified radius filter found with it (same city, no larger radius) is
  within the area even when its location names another town (e.g. Bielsko-Biała in a 30 km search around
  Andrychów); before, only the city's name counted and such offers were rejected as "not in <city>".
- The listing (`list`, listing.tsv, offers.csv, REPORT.md/html, `details --top`) is the current state of every
  board, not only the offers sighted in the run: offers its board's latest crawl saw, or that a request
  stopped early (incremental, page limit, error) did not reach, not marked gone. `eval` judges that whole
  state, so `run --boards X` keeps the other boards' offers; `new` is still "first seen in this run". After
  upgrading, run `neetscape eval` once (`list` and `report` warn otherwise).
- REPORT.md lists requests stopped at a page limit next to "Capped", labelled `--limit-pages (deliberate)` or
  `the board's max_pages`; REPORT.html shows the number of cut listings.
- justjoin.it, rocketjobs.pl: a listing shows at most 10 000 results (200 pages); a larger request is split by
  experience level, then by category, read from the page.
- pracuj, gowork, praca.pl, theprotocol, nofluffjobs: no result cap; `max_pages` is a safety stop of about twice
  the whole board, and a listing ends on its own last page (pracuj, praca.pl and theprotocol city listings were
  cut short before).
- gowork: a phrase starting with "praca" no longer fails with HTTP 302 (the board redirects page 1 to itself); the
  leading "praca" is dropped and an empty phrase is skipped with a warning. The posting's first publication
  date replaces the listing's refresh date (`Board.posting_date_is_first`).
- useme: a search without phrases lists every open project (~35 pages) instead of being skipped as too large.
- LinkedIn: a keyword-less remote search is sent as the searched country's remote phrases (Poland: remote,
  zdalnie, praca zdalna, home office; others: remote, home office) instead of the whole country's listing,
  which was mostly on-site offers. At least 3 s between requests.
- Result caps without a total (LinkedIn: 1000, start=990 is the last page): right after page 1 the crawler
  probes the cap's last page; offers there mean the cap is reached and the request is split at once (LinkedIn:
  into the regions on its cards, a region into its main cities). A request that cannot be split is narrowed to
  the newest window instead (LinkedIn: last 7 days, then 24 hours); a windowed request is partial by design and
  never marks offers gone.
- Transient failures (connection errors, timeouts, HTTP 5xx/429, a bot-wall page on a board that parsed before)
  are retried after 20 s and 60 s; this is the crawl's only retry policy (at most 1 + `retries` attempts per
  page). A 429 holds the host in the rate limiter. Boards with flaky empty pages (LinkedIn) fetch an empty page
  again before taking it as the end.
- Result caps: a board that shows at most N results per search declares `result_cap`; when a request
  matches more, the crawler splits it into narrower requests built from its first page (recursively) and
  fetches each to its end; requests that cannot be narrowed are listed as "Capped" in `REPORT.md`.
- olx.pl: all 25 result pages (was 4) and listings above its 1000-result cap split by job subcategory,
  read from the page's category tree.
- Progress line for `run`, `crawl` and `details`: a bar with requests (or postings) done, pages, offers, what
  each board is fetching and the time left; redrawn in place on a terminal, a `progress ...` line every 30 s
  when stderr goes to a file.
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
