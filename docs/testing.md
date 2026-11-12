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

Language-pack vocabularies are not pinned word by word. One gate runs in CI: `tests/test_vocab.py` parses every
board fixture and reads each offer's title against the board's category with the same measure as `--agreement`
(below; both use `reading` and `agreement` in `tests/infer_audit.py`). It fails when the share of offers whose
category's domain is among the title's domains drops below `MIN_COVERAGE`, or the share of fixture titles with no
domain rises above `MAX_NO_DOMAIN`, and lists the titles concerned. Both floors sit a few points below the
fixtures' values; when a vocabulary change improves them (`pytest tests/test_vocab.py -s` prints the values),
raising the floors in the same change is welcome. The fixtures hold under two hundred offers; check a change on a copy
of a real database as well:

```
cp runs/neetscape.db /tmp/audit.db
python tests/infer_audit.py /tmp/audit.db --dump-stored /tmp/before.json   # before the change
python tests/infer_audit.py /tmp/audit.db --rederive /tmp/before.json      # after: every changed decision, grouped
```

Job functions and domains are measured against the boards' own categories. `--agreement` reads, for every offer
with a category, the domain of the title alone and of the category alone (with the same packs and rules as
`infer.derive`) and prints, over offers where both give one, the overall agreement, per-domain precision and
recall of the title against the category, the 20 most frequent confusions with sample titles, the share of
current offers whose title gives no domain, and these numbers per title language: the regression metric for a
vocabulary change. `--suggest [--min 15] [--json FILE]` proposes vocabulary from the data, per field (domain,
function) and per title language, each group naming its pack (`-> neetscape/lang/pl.py`): (a) words and bigrams
of titles the field's patterns do not read whose offers' category reads one value in at least 80% of at least
`--min` offers, with example titles; (b) the most frequent words of current offers neither the title nor the
category reads, the long tail to look at by hand. A title's language is the pack whose vocabulary it matches
most, else the one its words occur in most; still undecided, it is reported as ambiguous (`pl|en`). The tool
holds no word lists: stop words are measured (a word seen with half of a field's values says nothing), words are
split on Unicode letters and lower-cased as `re.I` matches them, and a pack may define
`TITLE_TOKENS(title) -> list[str]` to split its own titles (e.g. German compounds into `lager-` and `-mitarbeiter`).
To work on a language: copy a database of a country that speaks it, run `--agreement` and `--suggest`, curate the
convincing suggestions into `neetscape/lang/<code>.py` (a suggestion is a word to turn into a pattern, not a
pattern), run `--agreement` again to check that the language's agreement rose and no domain's precision fell,
and `--rederive` (above) for the decisions that changed.
