# Contributing

Most contributions are one of three things: add a board, add a country, or fix a board that broke.
All of them follow the same rules.

## Ground rules

- **No network in tests.** Parsers are pure functions of a recorded page; tests run offline
  (`pytest -q`, well under a second). Live checks are marked `live` and never run in CI.
- **No new dependencies.** The standard library plus `websockets` (for the browser) is all there is.
- **Politeness and terms.** Only public pages and APIs, no logins, no CAPTCHA solving, no evasion
  of blocks. Keep the default rate limit. A board whose terms forbid automated access is not added.
- **Honest capabilities.** Declare in `Caps` only what you verified live. Whatever a board does not
  filter server-side is still checked locally, so a missing capability costs crawl time; a wrong
  one (e.g. a remote filter the board ignores) silently loses or mislabels offers.
- **No personal data.** Never commit your `profile.json`, CV, `runs/` (the database and reports) or
  anything from `.env`; `.gitignore` covers them and CI rejects a pull request that contains them.
  Fixtures are public job offers only: no pages you saw while logged in, no applicant data, and cut
  them down to what the parser needs (≤15 offers).
- **Unknown stays unknown.** Parsers fill what the board ships and leave the rest `unknown`/empty;
  text inference (`neetscape/infer.py`) fills gaps afterwards.
- Run `python tests/affected.py` while working; before the PR run `pytest -q` and
  `python -m pyflakes neetscape tests` (both must be clean).

## Add a board

1. **Pick the transport**, in this order of preference:
   1. a public JSON API or feed (`transport="http"`);
   2. JSON embedded in the result page (`__NEXT_DATA__`, JSON-LD `JobPosting`) read with a
      same-origin fetch from a tab (`browser_fetch`, optionally shrunk in the page with `fetch_js`);
   3. rendered result pages (`browser_render`), parsed from (link, link text, card text) triples.
2. **Probe it by hand.** Find which query parameters really change the results (keywords, remote,
   city/radius, part-time, newest first), the page size, the last page, rate limits. Write what you
   verified, with the date, in the module docstring.
3. **Write the adapter** from [`docs/board_template.py`](docs/board_template.py) in
   `neetscape/countries/<cc>/boards/<name>.py`, then import it in that package's `__init__.py` and
   add it to `__all__` there (the import registers the board; `__all__` keeps pyflakes quiet). The
   country is taken from the package path. Shared boards live in `neetscape/boards/` (imported and
   listed in `__all__` in `neetscape/boards/__init__.py`) and declare their country in `Caps`:
   `country="any"` for boards serving every country (they receive the searched country in
   `r.params["country"]`, like `linkedin.py`), `country="intl"` for international remote-only boards
   (`feeds.py`). A worked example: [`neetscape/countries/de/boards/arbeitnow.py`](neetscape/countries/de/boards/arbeitnow.py).
4. **Record a fixture** (at most ~15 offers; trim long descriptions, keep the structure):
   ```
   neetscape probe <name> --save-fixture tests/fixtures/<cc>/<name>.json
   ```
   It must hold only public offer data (shared boards: `tests/fixtures/shared/<name>.*`).
   `tests/countries/test_countries.py` requires a fixture for every board and parses every country
   board's fixture; add a test of your own for the fields the board ships (see `tests/countries/test_de.py`
   or `tests/countries/pl/test_pl_boards.py`).
5. **Fill in the PR coverage table** from `neetscape probe <name>`:

   | field | coverage | source |
   |---|---|---|
   | title, company | 100% | API |
   | mode | 40% | `remote` flag; rest from text |
   | pay | 10% | `salary` |
   | published | 100% | `created_at` |

## Add a country

1. Create `neetscape/countries/<cc>/__init__.py` defining `COUNTRY = Country(...)` (see
   `neetscape/country.py` and `neetscape/countries/de/__init__.py`): currency and `fx` (units of the
   currency per unit of others), languages, `hours_per_month`, LinkedIn location and place names,
   city aliases, legal-form words, contract words mapped onto the shared vocabulary
   (`neetscape/model.py: CONTRACTS`; propose a new canonical value only when no existing one fits),
   and `default_boards` (usually `("<cc>",)`, the group of the country's boards plus LinkedIn).
   This module must not import boards.
2. Add a language pack `neetscape/lang/<code>.py` if the language is new: `VOCAB` (mode, work time,
   contracts, level, hints; `first` for phrases another language's generic word would misread)
   and an `EXAMPLES` table. Contributors extend `EXAMPLES` rows rather than writing tests;
   `tests/core/test_lang.py` checks every row.
3. Add the country to the `country` enums in `neetscape/profile/schema.json` (a test compares them).
4. Add at least two boards (see above) under `neetscape/countries/<cc>/boards/` (its `__init__.py`
   imports them and lists them in `__all__`), and presets under
   `neetscape/countries/<cc>/presets/` with amounts in the country's currency.
5. Check the pay thresholds in `neetscape/pay.py` (`THRESHOLDS`) if the currency is new: they decide
   whether a bare amount is hourly, monthly or yearly.
6. Add the country's directories to `.github/CODEOWNERS` with a maintainer.

## Fix a broken board

1. `neetscape probe <name>` shows what is missing; `neetscape run --boards <name> --limit-pages 1 --record DIR`
   keeps the raw pages of a real run.
2. Record a fresh fixture with `--save-fixture` and replace the old one, so the test reproduces the
   failure first; then fix the parser or the URL builder.
3. Update the "verified live" notes in the module docstring.

## Pull requests

- One board or one country per PR; keep unrelated refactors out.
- Include the coverage table and the `neetscape plan` lines for a sample search.
- CI runs `pytest -q` only (offline); `pytest -m live` (one real page per board) is for local checks.
