# AGENTS.md — how a coding agent runs neetscape for a user

You are helping a person find work. neetscape does the deterministic part: crawling job boards,
storing offers in SQLite, filtering, ranking and fetching postings. You do the judgement: turn
the person's CV and answers into a search profile, run the tool, review what it found and write
a shortlist.

The tool never calls a language model and needs no API keys. Everything that requires
understanding the person lives in `profile.json` (written by you) and in your review.

## 0. Setup (once)

```
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
```

Requirements: Python 3.10+, a Chromium-family browser (chromium, google-chrome, brave), and
preferably `Xvfb`. neetscape starts its own private browser with a separate profile on CDP port
9334 (`--port` to change), on a virtual display or headless. Never use the person's own browser,
browser profile or screen, and never log in to any board.

`profile.json`, the CV and `runs/` are git-ignored. Keep them out of commits.

## 1. Read the CV, ask only what changes the search

Ask for the CV path if it was not given (PDF: `pdftotext -layout cv.pdf -`). Then ask, in one
message, only what the CV does not answer and what changes the search:
- which country's job market (Poland `pl`, Germany `de`), if the CV does not make it obvious;
- main job, side jobs (part-time, freelance, mandate contracts, Minijob, Werkstudent) or both;
- remote only, a city (and how far they would commute), or both;
- minimum pay (per month, or per hour for side jobs);
- acceptable contract types (`employment`, `b2b`, `mandate`, `specific_task`, `freelance`, `internship`,
  `mini_job`, `working_student`, `temp_agency`; `neetscape check` rejects unknown ones);
- hours available (full time, part time, flexible);
- explicit exclusions (fields, roles, companies, technologies).

Do not guess facts that decide eligibility (degree, years of experience, languages, location).
Ask, or record them as open questions in `candidate`.

## 2. Choose presets and write `profile.json`

```
neetscape init --preset focused --preset side      # presets combine: searches are concatenated
neetscape init --country de --preset broad         # a German profile: EUR amounts, German boards
```

The profile's `country` (default `pl`) sets the currency of every amount (pay floors) and of the
database, the default boards and the language used to read postings. A country may ship its own
presets (`neetscape/countries/<cc>/presets/`); the shared `focused` preset is Polish-flavoured
(phrases, PLN floor), so rewrite its phrases and pay for another country. One `--out` directory
holds one country: use `--out runs-de` for a German profile next to a Polish one. To look at
another country from the same profile, give a search `"where": {"remote": true, "country": "de"}`
(and add that country to `boards`, or leave `boards` out).

| Preset | Use when |
|---|---|
| `focused` | the person has a clear target role: phrases, title filters, pay floor, rank rules; review mode `auto` |
| `broad` | "show me everything remote": no phrases, review mode `listing` |
| `local` | everything within a radius of a city (edit the city) |
| `side` | remote part-time / freelance / mandate work with an hourly floor |

`init` refuses to overwrite an existing `profile.json`. After it, rewrite every placeholder for
this person; the `focused` preset's phrases and rules are only an example.

A profile is the **union of searches**. Conditions inside a search are ANDed; an offer passes if
it passes any search. `defaults` are merged into every search. Full schema:
`neetscape/profile/schema.json`.

| Search field | Meaning and example |
|---|---|
| `id`, `label` | unique id (used by `list --search`) and a readable name |
| `where` | `"remote"` (default), `"anywhere"`, `{"city": "Kraków", "radius_km": 30, "or_remote": true}`, or with a `"country"` key to search another country: `{"remote": true, "country": "de"}`, `{"city": "München", "country": "de"}` |
| `what` | `"all"`, or phrases sent to boards: `["n8n", "automatyzacja", "helpdesk"]` |
| `keywords_for` | phrases per board, e.g. `{"linkedin": ["IT support", "AI automation"]}` (LinkedIn works best in English) |
| `worktime` | allowed: `full_time`, `part_time`, `flexible`, `unknown` |
| `contracts` | allowed: `employment` (`uop` is an old alias), `b2b`, `mandate`, `specific_task`, `internship`, `freelance`, `mini_job`, `working_student`, `temp_agency`, `other`. With `worktime`, either one may match |
| `levels_exclude` | `intern`, `junior`, `mid`, `senior`, `lead`, `manager`, `unknown` |
| `fields`, `fields_exclude` | job fields read from the title (then the board's category): `ai_automation`, `security`, `qa`, `devops_cloud`, `data`, `erp_crm`, `it_support`, `it_admin`, `software_dev`, `product_project`, `design`, `ecommerce`, `customer_service`, `sales`, `marketing`, `hr`, `finance`, `legal`, `retail`, `admin_office`, `logistics`, `engineering`, `manufacturing`, `healthcare`, `education`, `hospitality`, `other`. Prefer these to title regexes for a person's field, e.g. `"fields": ["ai_automation", "it_support", "qa"]` |
| `pay` | `{"min": 9000, "per": "month"}` or `{"min": 45, "per": "hour"}`; in the profile country's currency (PLN, EUR), compared with the top of the offer's range. `"required": true` drops offers without pay |
| `max_age_days` | ignore older postings, e.g. `30` |
| `title_include` | regexes; at least one must match the title: `["support\|helpdesk\|automat"]` |
| `title_exclude` | regexes that drop by title: `["senior\|\\blead\\b\|architect"]` |
| `text_exclude` | regexes on title, company, category, skills, pay text, card text and, once fetched, the posting |
| `category_include` | regexes on the board's own category string |
| `unknown` | `keep` (default) or `drop` when a filtered field (mode, pay, work time, date, location) is unknown |
| `boost` | score added to offers passing this search (e.g. favour side jobs or a city) |

Other keys: `country` (`pl` default, `de`), `boards` (the country's boards by default, e.g. `["pl"]`
or `["de"]`; add `"intl"` for remoteok / We Work Remotely, or list board names), `candidate` (your notes: summary, strengths, constraints; ignored by the tool, used in
your review), `rank.rules` (`{pattern, weight, field: title|any, label}`, additive score, never
drops), `rank.tags`, `rank.sort` (`score`, `new`, `pay`, `published`), `review` (`mode`
`auto`/`listing`, `details_top`, `min_score`), `politeness.min_interval_s` (per-host seconds; overrides
a board's own minimum), `blacklist` (below).

`blacklist` is the person's own list of employers, links and phrases to avoid (agencies, scams,
companies they ruled out); neetscape ships none, so fill it only from what the person tells you:

```json
"blacklist": {"companies": ["acme staffing"], "urls": ["example-agency\\.pl"],
              "text": ["mlm|network marketing"], "action": "drop"}
```

`companies` match the company name, `urls` the offer URL, `text` the title, company, card text and
the fetched posting (case-insensitive regexes). `action: "drop"` (default) rejects a match in every
search with the reason `blacklisted ...`; `"flag"` keeps it, tagged `!blacklist`, with the reason
among the matched rules (also printed by `neetscape show ID`).

Rules of thumb:
- Derive phrases from what the person can do today (tools, tasks, domains), not from job titles
  they would like. Mix the country's language and English; 5–20 phrases is typical.
- Germany: the Bundesagentur board has no remote filter; remote searches add "Homeoffice" to the
  query and most results are hybrid ("Homeoffice nach Vereinbarung"). "Homeoffice möglich" is
  read as hybrid, not remote.
- Use separate searches for separate intents (main remote role, local role, side jobs) rather than
  one search with loose filters.
- Exclude seniority above their level and fields they rule out; this removes most noise.
- For "show me everything", use `what: "all"` with `review.mode: "listing"` (the `broad` preset)
  and narrow with filters (pay, worktime, age), not with phrases.
- `unknown: drop` on a pay filter removes most offers (many boards hide pay); prefer `keep`
  unless the person insists.
- Regexes are case-insensitive Python regexes; escape backslashes in JSON.

Then:

```
neetscape check     # validates; prints searches and boards
neetscape plan      # requests per board, what each board filters, warnings (no network)
```

Read the plan warnings: they say which boards skip a search (e.g. no city search, or a listing
too large without phrases). `or_remote` in a city search crawls both the city listing and the remote listing.
`neetscape boards` shows current capabilities; `neetscape boards --country de` only the boards serving
one country (its own plus LinkedIn).

LinkedIn's public search ignores its remote, job-type, distance and sort filters. A remote search
with `what: "all"` is therefore sent as remote phrases ("remote", "zdalnie", "praca zdalna", "home
office" for Poland). Results lean remote, but the work mode stays unknown until the posting is
fetched: with `unknown: keep` these offers stay in remote searches until stage 2 settles the mode;
with `unknown: drop` they are left out. Each phrase hits LinkedIn's 1000-result cap; such requests
are narrowed to the newest week (or day) and marked "Capped" in the report, so run every few days.

Board quirks worth knowing when reading results: Indeed shows only one public page (15 offers) per
request, and its "Zdalnie" tag is often hybrid in the posting; gowork lists only its own postings
(copies of other sites' ads are skipped); useme is freelance projects with a budget per project
(closed projects skipped; a search without phrases lists every open project); solid.jobs is downloaded whole (every division) and filtered locally. justjoin.it and rocketjobs.pl show at most
10 000 results per search; larger searches are split automatically (by experience level, then category).
gowork drops a leading "praca" from phrases (its page 1 for such phrases redirects to itself), and its
posting gives the first publication date, which replaces the listing's refresh date once fetched.

## 3. Run

```
mkdir -p runs && neetscape run > runs/run.log 2>&1
```

Run it in the background; a first full run can take 15–60 minutes depending on searches and
boards. For a quick trial use `--limit-pages 2`. If it is interrupted, `neetscape run --resume`
continues and skips finished requests. `--boards a,b` limits a run to some boards.

When it finishes, `run.log` ends with the counts per search and the report path
(`runs/<date>-run<N>/REPORT.md`). Check the board table at the top of the report and its "Capped" and
"Page limit" lists (a listing cut there is missing offers), or:

```
neetscape sql "SELECT board, COUNT(*) req, SUM(pages), SUM(found), SUM(error != '') errors
              FROM requests WHERE run_id = :run GROUP BY board"
neetscape sql "SELECT board, keyword, stop_reason, error FROM requests
              WHERE run_id = :run AND error != ''"
```

`neetscape sql` is read-only; `:run` is bound to `--run N` or the latest run.

A board with 0 offers or errors has probably changed its markup or URLs. `neetscape probe BOARD`
fetches one page and shows field coverage. Fix the adapter (`neetscape/countries/<cc>/boards/<name>.py`,
or `neetscape/boards/` for LinkedIn and the international feeds; see CONTRIBUTING.md) only if the
person wants that; otherwise report which boards were missing.

After changing only filters or rank rules, do not crawl again: `neetscape eval` then
`neetscape report` re-evaluate the stored offers.

### Two stages: cards, then postings

A run works in two stages. Stage 1 crawls listing cards and filters them cheaply. Stage 2 fetches
full postings only for offers that already pass:
- in `review.mode: "auto"`, `run` fetches the postings of the top `details_top` matches whose job
  has no stored posting yet and evaluates again. Each job's posting is fetched once across runs,
  so later runs open only new matches;
- in `review.mode: "listing"`, nothing is fetched; you choose with `details` (below).

A posting fills fields the card left unknown (work mode only from strong signals such as "fully
remote", JSON-LD telecommute or hybrid words; work time; contract types), and `text_exclude` and the
blacklist also read it. So offers can drop out after their posting is known; `details` logs how many,
and `show ID` gives the reasons. The posting text is only the posting body (from a board API, the
page's JSON-LD or embedded data, or a declared posting element), never the whole page.

## 4. Review (your main job)

The review has two passes: first narrow the listing to candidate ids without opening postings,
then read each candidate's posting and decide. Do not skip pass 2: listing fields come from cards
and are often unknown or wrong.

With a broad profile or a full crawl (thousands of offers), follow [docs/review.md](docs/review.md):
narrow with the profile and `eval` first (free), pick candidates by title, fetch their postings and
let the rules (`remote_proof`, `text_exclude`, blacklist) drop what they can, and read only the
survivors. Never read, or hand to subagents, a listing of thousands of rows.

### Pass 1: the listing

`listing.tsv` in the run directory has one row per job (duplicates across boards merged):
`id new score title company pay_<cur>_month mode worktime contracts level age boards searches tags mark url`
(`pay_pln_month`, `pay_eur_month`: the profile country's currency).
The listing is the current state: every offer still listed on any board as of that board's latest
crawl, not only what this run crawled; `new` = jobs first seen in this run.
With broad searches it can have thousands of rows. Never load it whole; read it in chunks and
slice it:

```
neetscape list --group title --limit 60                 # one row per title: counts, best pay, ids
neetscape list --new --limit 100                        # only offers new in this run
neetscape list --search side --limit 100                # one search
neetscape list --where "o.pay_max >= 12000" --format md
neetscape list --where "o.title LIKE '%support%' AND o.level != 'senior'"
sed -n '2,201p' runs/<date>-run<N>/listing.tsv          # chunk by chunk
```

`--where` is an SQL condition on the `offers` table aliased `o` (columns: `title`, `company`,
`mode`, `worktime`, `contracts`, `level`, `category`, `skills`, `pay_min`, `pay_max` (per month, profile currency),
`pay_text`, `published`, `board`, `locations`, `snippet`). Use `neetscape sql` with `GROUP BY` to
see the shape before reading rows (`list --group title` is the quick version of the second query):

```
neetscape sql "SELECT o.category, COUNT(*) n FROM evals e JOIN offers o ON o.id = e.offer_id
              WHERE e.run_id = :run GROUP BY 1 ORDER BY n DESC LIMIT 40"
neetscape sql "SELECT o.title_norm, COUNT(*) n FROM evals e JOIN offers o ON o.id = e.offer_id
              WHERE e.run_id = :run GROUP BY 1 ORDER BY n DESC LIMIT 40"
```

Offers that fail every search are not in the listing; their reasons are in `rejections`. Check
them when the listing looks too small or a known offer is missing, and loosen the filter that
removes too much (then `neetscape eval` + `neetscape report`, no new crawl):

```
neetscape sql "SELECT reasons, COUNT(*) n FROM rejections WHERE run_id = :run GROUP BY 1 ORDER BY n DESC LIMIT 20"
```

Pick candidate ids from what the person can do and wants, then fetch their postings:

```
neetscape details --pick 12,40,311          # or --pick-file ids.txt (id at the start of each line)
```

`details` fetches the postings, re-evaluates and rewrites the reports. In `auto` review mode `run`
has already opened the top `details_top` matches; `details --top N` opens the next N matches without
a stored posting, and `details --marked` the marked offers whose posting is missing.

### Pass 2: the postings

```
neetscape show 12      # stored fields, pass/fail reasons per search, full posting text
```

`show` works for any offer id, including rejected ones: under `searches (run N)` it prints, per
search, `passes` or the rejection reasons (e.g. `all: mode onsite, title excluded`). If the
posting has not been fetched yet it says so; run `details --pick ID` first.

`REPORT.md` lists opened offers with hints (fully remote, hybrid words, years, degree, languages).
Hints are regex matches, not decisions. For every candidate verify against the person:
1. Is it really remote (or in reach) for the whole role?
2. Hard blockers: degree or student status, years of commercial experience, languages, location, citizenship.
3. Fit: which of the person's strengths does it use; what is missing.
4. Pay and contract type, if stated.

### Shortlist

Record the review in the database, one mark per decision, with a note of why it fits and the
biggest risk, then rewrite the reports:

```
neetscape mark 12 shortlisted --note "n8n + helpdesk, fully remote · asks for 2 years of B2B"
neetscape mark 40 rejected --note "requires German C1"
neetscape report
```

`REPORT.html` in the run directory then shows the review as a list with the selected offer's facts, the
posting's red flags, your note and the full posting beside it; the person groups, sorts and filters it. Make
the note's first line its category ("Apply now", "Side jobs", "Stretch") and the next lines `✅ why`
and `⚠ risk`: the page groups by that first line and colours the rest. That page is the shortlist the
person reads. Aim for:
- **Apply now** (`shortlisted`): 5–10 offers;
- **Side jobs**: the same for part-time and freelance work, if they wanted it (say so in the note);
- **Stretch**: good fits with one blocker (`shortlisted`, the blocker in the note);
- **Rejected** (`rejected`): notable offers that looked good but fail a hard requirement, with the reason.

Be concrete and honest; do not inflate fit. Tell the person which boards failed in this run. A
written `runs/shortlist.md` with the same groups is optional, e.g. when the person wants a text file.

### Record decisions

```
neetscape mark https://example.com/offer/123 applied --note "sent 2026-11-12"
neetscape tracked
```

Statuses: `shortlisted applied interview offer rejected ignored`. `rejected` and `ignored` offers
disappear from later listings; the rest appear under "Tracked offers" in every report, with
whether they are still listed.

## 5. Later runs

Re-run `neetscape run` with the same profile. Crawling is incremental (newest-first boards stop at
pages already seen), offers are flagged new only when the job was not seen in any earlier run,
offers are marked gone when a complete request no longer returns them, and in `auto` mode only
postings of new matches are fetched. `run --boards a,b` refreshes only those boards; the report still
lists the other boards' offers as of their last crawl. Review with `neetscape list --new`. Update the profile when the person's situation changes, and tighten it when
the review keeps rejecting the same kind of offer. Keep runs infrequent (once or twice a week).
