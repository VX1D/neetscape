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
- Before the PR run `pytest -q` and `python -m pyflakes neetscape tests` (both must be clean).

## Add a board

0. **Check that it may be added.** The board's terms must allow automated access to its public pages
   (see *Politeness and terms* under [Ground rules](#ground-rules)), and it must not be on the list of
   [boards deliberately not supported](docs/boards-and-countries.md#boards-deliberately-not-supported).
1. **Pick the transport**, in this order of preference:
   1. `transport="http"`: a public JSON API (GET, or POST: return the body from `post_body(r, page)`
      and set `content_type`), an RSS feed, or server-rendered result pages / data embedded in them
      (`__NEXT_DATA__`, a Nuxt payload, JSON-LD), when the board serves a plain HTTP client;
   2. `transport="browser_fetch"`: the same embedded data, fetched with a same-origin request from a
      tab of the private browser, for boards that refuse a plain client. `fetch_js()` can shrink the
      response in the page to the fields you parse (the fixture is then that shrunk output).
   Parse the board's own data, not the visible page text.
2. **Probe it by hand.** Find which query parameters really change the results (keywords, remote,
   city/radius, part-time, newest first), the page size, what the page after the last one returns,
   rate limits. Write what you verified, with the date, in the module docstring.
3. **Write the adapter** from [`docs/board_template.py`](docs/board_template.py) in
   `neetscape/countries/<cc>/boards/<name>.py`, then import it in that package's `__init__.py` and
   add it to `__all__` there (the import registers the board; `__all__` keeps pyflakes quiet). The
   country is taken from the package path. Shared boards live in `neetscape/boards/` (imported and
   listed in `__all__` in `neetscape/boards/__init__.py`) and declare their country in `Caps`:
   `country="any"` for boards serving every country (they receive the searched country in
   `r.params["country"]`, like `linkedin.py`), `country="intl"` for international remote-only boards
   (`feeds.py`). A worked example: [`neetscape/countries/de/boards/arbeitnow.py`](neetscape/countries/de/boards/arbeitnow.py).
   Optional parts, when the board needs them:
   - `Caps(whole_listing=True)`: one response is the request's whole listing (a feed, a whole-category
     download), so fetching it completes the request. Otherwise a request is complete only on an
     empty, short or no-new page or a 404 after the last page; reaching `max_pages` never is;
   - `Caps(result_cap=N)` with `total(raw, r)` and `split(raw, r)`: the board shows at most N results per
     search (olx.pl: 1000). `total()` reads the match count from a request's first page; when it is over
     N, the crawler replaces the request with `split()`'s narrower requests (e.g. one per category the
     page lists) and fetches each to its end. Build the split from the page, not from a hard-coded list;
     see `neetscape/countries/pl/boards/olx.py`. Without `total()` the crawler probes the cap's last page
     (`max_pages`, or `result_cap / page_size`) right after page 1, and `split(raw, r, seen=...)` gets the
     cards of page 1 and of the probe (see `neetscape/boards/linkedin.py`). Optionally `newest(r)` returns
     `(request, label)` narrowed to the newest window, used when `split()` returns []; such requests are
     never complete;
   - `Caps(empty_retries=N)`: for a board that sometimes returns an empty page mid-listing, the crawler
     fetches it again N times before treating it as the end;
   - `min_interval = {"host": seconds}`: a longer minimum gap for a board that throttles (the
     profile's `politeness.min_interval_s` still overrides it);
   - `posting(page)`: posting fields from the source of an offer page; the default reads schema.org
     `JobPosting` JSON-LD. Override it when the JSON-LD lacks the body or is missing, to read the
     board's embedded data. Return only the posting body, never page chrome (menus, cookie banners,
     similar offers);
   - `posting_url(url)` / `posting_text(raw)`: a JSON posting API fetched over plain HTTP instead of
     the offer page;
   - `posting_selector`: a CSS selector of the posting body on the rendered offer page, used only when
     `posting()` finds no text. Leave it empty unless you checked that the selector holds just the posting.
4. **Record fixtures** (public offer data only, at most ~15 offers; trim long descriptions, keep the
   structure):
   ```
   neetscape probe <name> --save-fixture tests/fixtures/<cc>/<name>.json
   ```
   Shared boards use `tests/fixtures/shared/<name>.*`. If the board reads postings itself, add a trimmed
   offer page as `tests/fixtures/<cc>/<name>_posting.html`. `tests/countries/test_countries.py`
   requires a fixture for every board and parses every country board's fixture.
5. **Add the board's row to `COVERAGE`** in `tests/countries/test_countries.py`: the fields its parser
   fills on its fixture. Write a test file in `tests/countries/<cc>/` only for rules of its own (a split,
   a quirk of its markup); URLs and per-offer values are checked live with `neetscape probe`.
6. **Fill in the PR coverage table** from `neetscape probe <name>`:

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
