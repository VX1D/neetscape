# Changelog

All notable changes to neetscape are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

- LinkedIn's job criteria are structured evidence: the posting reader keeps them as `meta["criteria"]` and
  `Board.posting_facts(meta)` maps them to level, work time and contract (source `posting_struct`, above the
  title, card and posting text, below board facts and the request; evidence "LinkedIn: Employment type
  Full-time"). Entry level → junior, Internship → intern, Director/Executive → manager; Full-time, Part-time;
  Contract and Temporary → flexible work time without a contract type; employment type Internship → contract
  and level intern. Associate, Mid-Senior level, Not Applicable, Volunteer, Other and unlisted labels stay
  unknown. Postings stored earlier are read from their text's criteria lines; `neetscape eval` applies it.

- Every language-specific word now lives in its language pack or country package, so a new language is one
  module (`neetscape/lang/<code>.py`) and a new country one package: pay periods, pay words, the thousand
  suffix and range words (`VOCAB["pay"]`, read by `pay.py`); words offering options (`choice`, for
  `remote_proof`); placeholder employer names (`placeholder_companies`); LinkedIn's remote phrases
  (`Country.linkedin_remote_phrases`); solid.jobs' "staż" level in its adapter; the Polish presets in
  `countries/pl/presets/`, with language-neutral shared presets. Text of an unknown country is read in
  English only (`lang.DEFAULT`). `model.fold` transliterates every letter Unicode does not decompose
  (ø, đ, æ, œ, þ, ß, ł); boards map currency symbols with `pay.CURRENCIES`. On a 32k-offer database every
  derived value, pay range and remote-proof verdict is unchanged.
- Job domains: every offer gets `job_domains`, the set of domains its title (head and qualifier) and the
  board's category name, read in the offer's own languages ("AI Gateway Product Owner": `ai, product`;
  "Sachbearbeiter (m/w/d) Buchhaltung": `finance`); the weak `tech` domain counts only alone. Schema v7 adds
  the column; `neetscape eval` fills it. `job_field`, `job_function` and `job_domain` are unchanged. New search
  filters `domains` (any of the offer's domains), `functions` and `functions_exclude`; a `domains` column in
  listing.tsv / offers.csv after `field`, and among the facts in REPORT.html; `neetscape show` lists each
  domain's source and phrase. A title naming no domain takes the one its function implies (`infer.IMPLIED_DOMAIN`:
  "Automation Engineer" is `ai`, a developer `software`, a tester `software`); a gender pair ("Konsultant /
  Konsultantka", "Kierowca/Kierowczyni") reads as one job name, not as the end of the title's head.
- Vocabularies extended from `tests/infer_audit.py --suggest` (Polish education, logistics, hospitality,
  retail, manufacturing, health; English full stack/backend/frontend, identity, reliability; integrations, Jira,
  Atlassian and system analysts as IT; "network" as IT only in network roles). On a 32k-offer database the
  category's domain is among the title's domains for 81.2% of the offers (78.1% before), and 22.9% of current
  offers have no domain in the title (30.7%).
- `tests/infer_audit.py --agreement` and `--suggest`: vocabulary maintenance from the boards' own categories,
  per language, with the target pack of each suggestion; a pack may declare a `TITLE_TOKENS` hook.
- OLX offers carry the ad's own category ("Sprzedaż - Przedstawiciel handlowy").
- A missing job field, domain or function is unknown, not a failure: an include filter (`fields`, `domains`,
  `functions`) follows the search's `unknown` policy for an offer with field `other`, no domain or no function
  (before, `fields` dropped `other` always); exclude filters never drop it. Set `"unknown": {"field": "drop"}`
  to keep the old behaviour.
- `unknown` per dimension: a search's `unknown` may be a mapping, e.g. `{"default": "keep", "domain": "drop"}`,
  over the dimensions `location`, `mode`, `remote_proof`, `worktime`, `pay`, `date`, `field`, `domain`,
  `function`. `defaults` and a search merge per dimension (a string is `{"default": ...}`).
- Language packs may declare `qualifier` (words that open a title's qualifier: "with", "z", "mit") and
  `gender` (gender markers in words: "all genders"); `infer.py` keeps only punctuation. Bracketed gender
  markers made of letters ("(m/w/d)", "(k/m)", "(f/m/x)") no longer end a title's head in any language.

- Derived fields are re-derived from stored observations: offers keep the adapter's structured values
  (`facts`), the requests that found them and the fetched posting apart from mode, work time, contracts,
  level and job field, which `neetscape eval` derives again (a vocabulary change needs no crawl).
  `neetscape show ID` prints where each value came from (`evidence`: board data, the board's remote
  filter, JSON-LD, title, card text, category, posting). One module, `neetscape/infer.py`; vocabularies are
  checked on real data with `tests/infer_audit.py` instead of per-pattern examples (the Polish snapshot and
  the packs' `EXAMPLES` tables are gone).
- Job fields: every offer gets a `job_field` (26 fields such as `ai_automation`, `it_support`, `qa`, `hr`,
  `finance`, `retail`, or `other`), read as function x domain from the title, then the board's category
  ("Logistics Support Specialist" is logistics, "Technical Support Engineer" IT support, "HR Automation
  Specialist" AI and automation; a qualifier such as "(GenAI)" counts less than the title's head). Columns
  `job_field`, `job_function`, `job_domain`; search filters `fields` and `fields_exclude`; a `field` column
  in listing.tsv; REPORT.html shows the field and groups by it.
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
