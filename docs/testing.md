# Testing

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Reviewing](review.md) · [Testing](testing.md)

```
pip install -e '.[test]'
pytest -q                   # everything offline (well under a second)
pytest tests/countries -k olx  # one board
pytest -m live              # live checks against the real boards (network; never in CI)
```

Tests run offline and are grouped by area: `tests/core` (pay parsing, text inference, JSON-LD),
`tests/countries` (every country's definition; every board's parser on its recorded page in
`tests/fixtures/<cc>/`, with the fields it must fill, one row per board in `COVERAGE` of
`test_countries.py`; per board only its own rules, e.g. OLX's category split, in
`tests/countries/pl/test_olx.py`; posting readers on `tests/fixtures/<cc>/<board>_posting.html`),
`tests/boards` (the shared boards, on pages in `tests/fixtures/shared/`) and
`tests/engine` (profile, planner, filters, store, crawler stop rules, CLI end to end with a fake
board). Exact URLs and per-offer values are not pinned: `neetscape probe BOARD` checks a board live.
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
