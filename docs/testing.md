# Testing

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Reviewing](review.md) · [Testing](testing.md)

```
pip install -e '.[test]'
pytest -q                   # everything offline (well under a second)
pytest tests/test_boards.py -k olx  # one board
pytest -m live              # live checks against the real boards (network; never in CI)
```

Tests run offline, one file per area of the app; a change to a module means touching its file:

| File | Area |
|---|---|
| `test_boards.py` | countries and the board registry; every board's parser on its recorded page (`COVERAGE`: the fields it must fill, one row per board); the board interface and `boards/pages.py` helpers; then one section per board with only its own rules (e.g. OLX's category split, LinkedIn's region split) |
| `test_crawl.py` | the crawl on a fake board: stop reasons, result caps (split, end probe, newest windows), retries, `--resume`, the HTTP transport |
| `test_store.py` | duplicates across boards, the current state (new, gone, carried offers), marks, migrations |
| `test_details.py` | fetching postings and what a posting may change in its offer |
| `test_evaluate.py` | the filters of a search, the blacklist |
| `test_report.py` | the listing, title groups, `REPORT.md` / `REPORT.html` |
| `test_profile.py` | `profile.json` validation and presets, the planner |
| `test_text.py` | pay parsing, text inference, JSON-LD postings, hints |
| `test_cli.py` | the commands end to end on the fake board |
| `test_browser.py` | the private browser's process lifecycle (fake processes) |

`conftest.py` holds the helpers: the fake board (`fake`, pages from memory), `http` (a fake `Http.get`),
`db` (a fresh store), `job`/`ingest` (offers seen by one request), `crawl` (a fake-board crawl like
`neetscape run`), `requests_of`, `search`, `save_posting` and `write_profile`. Recorded pages live in
`tests/fixtures/<cc>/` (shared boards: `tests/fixtures/shared/`; posting readers on
`<board>_posting.html`). Tests check behaviour through public surfaces; exact URLs and per-offer values
are not pinned: `neetscape probe BOARD` checks a board live.
CI never touches live boards: `pyproject.toml` excludes the `live` marker by default, and
`pytest -m live` (in `tests/live/`) fetches one real page per board (`-k BOARD` for one), so use it sparingly. To record a fresh fixture:
`neetscape probe BOARD --save-fixture tests/fixtures/<cc>/BOARD.json`.

## Vocabularies: check on real data

Language-pack vocabularies are not pinned by unit tests. Check a change on a copy of a real database:

```
cp runs/neetscape.db /tmp/audit.db
python tests/infer_audit.py /tmp/audit.db --dump-stored /tmp/before.json   # before the change
python tests/infer_audit.py /tmp/audit.db --rederive /tmp/before.json      # after: every changed decision, grouped
```
