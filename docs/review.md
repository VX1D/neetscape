# Reviewing a large crawl: cheap and precise

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Reviewing](review.md) · [Testing](testing.md)

A full crawl of one country stores tens of thousands of offers. Reading them with a language model is
the expensive part, and most of them are out of scope for the person anyway. This workflow keeps the
model's work to the end of the funnel: everything that rules can decide is decided by neetscape, for
free, and the agent reads only the postings that survive.

Two principles:

- **Narrow with the profile, not by reading.** `neetscape eval` and `neetscape sql` re-judge every
  stored offer in seconds without crawling. Tighten the profile until the listing is a few hundred
  offers before anyone reads anything.
- **Precision over recall.** The person acts on the shortlist. An offer that wrongly survives (a hybrid
  job in a "remote only" list, an HR role for an IT profile) costs their trust; a borderline offer that is
  dropped costs little. Prefer rules that drop doubtful offers, and say how many were dropped.

## The funnel

| Stage | Who | Cost | Typical size |
|---|---|---|---|
| 0. Profile from the CV | the agent writes `profile.json`, `eval` checks it | free | 20 000 stored → 300–2 000 passing |
| 1. Titles | the agent skims compact rows | small | → 150–300 candidates |
| 2. Postings and rules | `details`, then `eval` | free (network only) | → 50–150 survivors |
| 3. Reading | the agent reads each posting | the main cost | → the shortlist |
| 4. Record | `mark`, `report` | free | REPORT.html |

### 0. Make the profile do the filtering

Write the profile from the CV and the person's answers (AGENTS.md, sections 1–2), then add rules that
remove what they would never apply to. For example, for someone who wants remote IT or AI work:

```json
{"id": "main", "where": "remote", "what": "all", "remote_proof": true,
 "domains": ["ai", "it", "data", "erp", "security", "cloud"],
 "functions_exclude": ["sell", "market", "people", "account", "shop", "cook_clean", "operate", "transport",
                       "care", "teach"],
 "unknown": {"default": "keep", "domain": "drop"},
 "title_exclude": ["senior|\\blead\\b|principal|architect|head of|manager",
                   "java\\b|\\.net\\b|c#|golang|react|angular|php"],
 "text_exclude": ["\\b(german|dutch|french)\\b.{0,40}(c1|b2|fluent|native|required)"],
 "levels_exclude": ["senior", "lead", "manager"], "pay": {"min": 6000, "per": "month"}}
```

- `domains` is what the person's work is about, from the CV, in any role ("AI Gateway Product Owner" has
  `ai`); `functions_exclude` removes the roles they rule out (selling, marketing, recruiting, accounting...).
  `neetscape sql "SELECT job_domains, COUNT(*) FROM offers GROUP BY 1 ORDER BY 2 DESC LIMIT 30"` shows what the
  crawl holds. Generic titles name no domain ("Support Associate", "Asystent"); `"domain": "drop"` leaves them
  out, `keep` (the default) lets them through for reading by title. Use `fields` instead when the person names a
  role rather than a subject (docs/profile.md, "Fields, domains or functions").
- `title_exclude` removes seniority and stacks they rule out; `text_exclude` removes hard blockers that show
  on cards (other languages). Group the listing by field in REPORT.html to see what each field holds.
- `remote_proof: true` (remote searches) requires the fetched posting to describe remote work and to
  mention no hybrid model or required presence (client visits, business trips, office days,
  relocation). Before a posting is fetched it counts as unknown, so stage 1 is not affected.
- Iterate: `neetscape eval` prints the count per search. Look at what is thrown away before tightening
  further:

```
neetscape eval
neetscape sql "SELECT reasons, COUNT(*) n FROM rejections WHERE run_id = :run GROUP BY 1 ORDER BY n DESC LIMIT 15"
neetscape list --group title --limit 60
```

Stop when the listing is a few hundred to two thousand offers and the top of `list --group title` looks
like the person's field. If it is still several thousand, do not start reading: tighten the profile.

### 1. Titles: pick candidates without opening postings

Read the listing in compact rows, never whole:

```
neetscape list --format tsv --limit 100000 > runs/listing-now.tsv
cut -f1,4,5,6,7,10,12 runs/listing-now.tsv | sed -n '2,401p'     # id title company pay mode level boards
```

Pick realistic fits (a few hundred at most) and write their ids, one per line, to `runs/candidates.txt`.
Skip duplicates (same title and company) and titles that already show a blocker.

### 2. Fetch postings, let the rules work

```
neetscape details --pick-file runs/candidates.txt
```

`details` fetches each posting once (cached across runs), then evaluates again. With `remote_proof`,
`text_exclude` and the blacklist, offers whose posting is hybrid, requires presence or names a blocker
drop out here; the log says how many. The posting hints can be queried too:

```
neetscape sql "SELECT o.id, o.title, json_extract(d.hints, '$.years') years, json_extract(d.hints, '$.office') office
              FROM evals e JOIN offers o ON o.id = e.offer_id JOIN details d ON d.offer_id = o.id
              WHERE e.run_id = :run GROUP BY o.id"
```

### 3. Read the survivors

Only offers that still pass and have a posting:

```
neetscape sql "SELECT DISTINCT e.offer_id FROM evals e JOIN details d ON d.offer_id = e.offer_id
              WHERE e.run_id = :run AND d.text != ''"
neetscape show ID
```

Decide each with one rubric and keep the answer short:

1. **Location:** is the whole job remote (or within reach) as the posting states it? If not, reject.
2. **Hard blockers:** degree or student status, years of commercial experience the person lacks,
   languages, citizenship, location.
3. **Fit:** which of the person's strengths it uses, and what is missing.
4. **Pay and contract**, if stated.

Verdict: `apply` (realistic now), `side` (part-time or freelance), `stretch` (good fit, one blocker) or
`reject`, plus a 0–10 score for ordering.

**Subagents.** Use them only for this stage, and only when there are more postings than you can read
yourself (roughly 40 or more). Give each subagent at most 40 ids, the same short candidate summary, the
rubric above and a structured output (id, verdict, score, why, risk). Never hand a subagent a listing of
thousands of rows; stages 0–2 exist so that nobody has to read it. A smaller, cheaper model is enough
for this kind of reading.

### 4. Record the review

```
neetscape mark 12 shortlisted --note "Apply now
✅ n8n + API integrations, fully remote
⚠ asks for 2 years of B2B integrations"
neetscape mark 40 rejected --note "requires German C1"
neetscape report
```

The first line of a note is its category in REPORT.html (Apply now / Side jobs / Stretch); `✅` and `⚠`
lines are coloured. Categories are listed in the order they were first recorded, so mark the best first.

## Later runs

```
neetscape run
neetscape list --new
```

Only new matches go through stages 1–3: postings already fetched are not fetched again, and earlier
decisions stay attached to their offers.
