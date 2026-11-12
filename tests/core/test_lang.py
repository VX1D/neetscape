"""Every lang pack's EXAMPLES table: (text, field, expected), read with that language plus English."""
import pytest

from neetscape import infer, lang

FIELDS = {
    "mode": infer.mode_from_text, "worktime": infer.worktime_from_text, "contract": infer.contracts_from_text,
    "level": infer.level_from_text,
}
CASES = [(code, *ex) for code in lang.available() for ex in lang.pack(code).EXAMPLES]


@pytest.mark.parametrize("code,text,field,expected", CASES, ids=[f"{c[0]}:{c[1][:30]}:{c[2]}" for c in CASES])
def test_examples(code, text, field, expected):
    langs = (code, "en")
    if field in FIELDS:
        assert FIELDS[field](text, langs) == expected
    else:  # a hint
        got = infer.hints(text, langs)[field]
        assert bool(got) is expected if isinstance(expected, bool) else got == expected


def test_pack_shape():
    for code in lang.available():
        vocab = lang.pack(code).VOCAB
        for fld, table in vocab.items():
            if fld == "first":
                assert set(table) <= set(lang.ORDER) and all(v in lang.ORDER[f] for f, rows in table.items() for v, _ in rows)
            elif fld == "hints":
                assert set(table) <= set(lang.HINTS), code
            else:
                assert set(table) <= set(lang.ORDER[fld]), (code, fld)


def test_german_text_is_not_read_with_polish_words():
    # "kontrakt"/"B2B" mean b2b for Polish boards only
    assert infer.contracts_from_text("B2B-Vertrieb", ("de", "en")) == []
    assert infer.contracts_from_text("B2B", ("pl", "en")) == ["b2b"]
    assert infer.mode_from_text("Homeoffice möglich", ("de", "en")) == "hybrid"
    assert infer.mode_from_text("Home office", ("pl", "en")) == "remote"  # unchanged Polish behaviour
