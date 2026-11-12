# Testing

[README](../README.md) · [Getting started](getting-started.md) · [Search profile](profile.md) · [How it works](how-it-works.md) · [Boards and countries](boards-and-countries.md) · [Reviewing](review.md) · [Testing](testing.md)

```
pip install -e '.[test]'
pytest -q                   # everything offline (well under a second)
python tests/affected.py    # only the tests affected by your uncommitted changes
pytest tests/countries -k olx  # one board
pytest -m live              # live checks against the real boards (network; never in CI)
```

Tests run offline and are grouped by area: `tests/core` (pay parsing, text inference, JSON-LD), `tests/countries` (every country's
definition, a fixture for every board, country boards' parsers on recorded pages in
`tests/fixtures/<cc>/` and their URL builders, one test file per board, e.g. `tests/countries/pl/test_gowork.py`;
posting readers on recorded offer pages `tests/fixtures/<cc>/<board>_posting.html`),
`tests/boards` (the shared boards, on pages in `tests/fixtures/shared/`) and
`tests/engine` (profile, planner, filters, store, crawler stop rules, CLI end to end with a fake
board). `tests/affected.py` maps changed files to these groups; a board-only change runs just that
board. CI never touches live boards: `pyproject.toml` excludes the `live` marker by default, and
`pytest -m live` (in `tests/live/`) fetches one real page per board (`-k BOARD` for one), so use it sparingly. To record a fresh fixture:
`neetscape probe BOARD --save-fixture tests/fixtures/<cc>/BOARD.json`.

## Vocabularies: check on real data

Language-pack vocabularies are not pinned by unit tests. Check a change on a copy of a real database:

```
cp runs/neetscape.db /tmp/audit.db
python tests/infer_audit.py /tmp/audit.db --dump-stored /tmp/before.json   # before the change
python tests/infer_audit.py /tmp/audit.db --rederive /tmp/before.json      # after: every changed decision, grouped
```
