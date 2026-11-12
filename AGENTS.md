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
| `pay` | `{"min": 9000, "per": "month"}` or `{"min": 45, "per": "hour"}`; in the profile country's currency (PLN, EUR), compared with the top of the offer's range. `"required": true` drops offers without pay |
| `max_age_days` | ignore older postings, e.g. `30` |
| `title_include` | regexes; at least one must match the title: `["support\|helpdesk\|automat"]` |
| `title_exclude` | regexes that drop by title: `["senior\|\\blead\\b\|architect"]` |
| `text_exclude` | regexes on title, company, category, skills, pay text, card text |
| `category_include` | regexes on the board's own category string |
| `unknown` | `keep` (default) or `drop` when a filtered field (mode, pay, work time, date, location) is unknown |
| `boost` | score added to offers passing this search (e.g. favour side jobs or a city) |

Other keys: `country` (`pl` default, `de`), `boards` (the country's boards by default, e.g. `["pl"]`
or `["de"]`; add `"intl"` for remoteok / We Work Remotely, or list board names), `candidate` (your notes: summary, strengths, constraints; ignored by the tool, used in
your review), `rank.rules` (`{pattern, weight, field: title|any, label}`, additive score, never
drops), `rank.tags`, `rank.sort` (`score`, `new`, `pay`, `published`), `review` (`mode`
`auto`/`listing`, `details_top`, `min_score`), `politeness.min_interval_s` (per-host seconds).

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

LinkedIn's public search ignores its remote, job-type, distance and sort filters, so LinkedIn
offers arrive with an unknown work mode: with `unknown: keep` they stay in remote searches until you
open them (`details --pick`) and read the posting; with `unknown: drop` they are left out.

## 3. Run

```
mkdir -p runs && neetscape run > runs/run.log 2>&1
```

Run it in the background; a first full run can take 15–60 minutes depending on searches and
boards. For a quick trial use `--limit-pages 2`. If it is interrupted, `neetscape run --resume`
continues and skips finished requests. `--boards a,b` limits a run to some boards.

When it finishes, `run.log` ends with the counts per search and the report path
(`runs/<date>-run<N>/REPORT.md`). Check the board table at the top of the report, or:

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

## 4. Review (your main job)

The review has two passes: first narrow the listing to candidate ids without opening postings,
then read each candidate's posting and decide. Do not skip pass 2: listing fields come from cards
and are often unknown or wrong.

### Pass 1: the listing

`listing.tsv` in the run directory has one row per job (duplicates across boards merged):
`id new score title company pay_<cur>_month mode worktime contracts level age boards searches tags mark url`
(`pay_pln_month`, `pay_eur_month`: the profile country's currency).
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

In `auto` review mode `run` has already opened the top `details_top` offers; `details --top N`
opens more.

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

Write `runs/shortlist.md` for the person:
- **Apply now**: 5–10 offers, each with link, pay, one line on why it fits and one on the biggest risk;
- **Side jobs**: the same for part-time and freelance work, if they wanted it;
- **Stretch**: good fits with one blocker;
- **Rejected**: notable offers that looked good but fail a hard requirement, with the reason.

Be concrete and honest; do not inflate fit. Mention boards that failed in this run.

### Record decisions

```
neetscape mark 12 shortlisted
neetscape mark 40 rejected --note "requires German"
neetscape mark https://example.com/offer/123 applied --note "sent 2026-11-12"
neetscape tracked
```

Statuses: `shortlisted applied interview offer rejected ignored`. `rejected` and `ignored` offers
disappear from later listings; the rest appear under "Tracked offers" in every report, with
whether they are still listed.

## 5. Later runs

Re-run `neetscape run` with the same profile. Crawling is incremental (newest-first boards stop at
pages already seen), offers are flagged new only when the job was not seen in any earlier run,
and offers are marked gone when a complete request no longer returns them. Review with
`neetscape list --new`. Update the profile when the person's situation changes, and tighten it when
the review keeps rejecting the same kind of offer. Keep runs infrequent (once or twice a week).
