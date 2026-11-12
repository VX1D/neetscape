"""Behaviour snapshot taken before multi-country support: with default settings (a Polish profile), text
inference, pay parsing and hints must stay exactly as they were. Texts come from the recorded PL fixtures.

`uop` was renamed to `employment`; the snapshot keeps the old name and the test maps it.
"""
import json
from pathlib import Path

import pytest

from neetscape import infer
from neetscape.pay import parse_pay

SNAP = json.loads((Path(__file__).parent / "snapshot_pl.json").read_text())
RENAMED = {"uop": "employment"}


@pytest.mark.parametrize("text,mode,worktime,contracts,level", SNAP["infer"])
def test_infer_unchanged(text, mode, worktime, contracts, level):
    got = (infer.mode_from_text(text), infer.worktime_from_text(text), infer.contracts_from_text(text), infer.level_from_text(text))
    assert got == (mode, worktime, [RENAMED.get(c, c) for c in contracts], level)


@pytest.mark.parametrize("text,expected", SNAP["pay"])
def test_pay_unchanged(text, expected):
    assert parse_pay(text) == (tuple(expected) if expected else None)


@pytest.mark.parametrize("text,expected", SNAP["hints"])
def test_hints_unchanged(text, expected):
    got = infer.hints(text)
    assert {k: got[k] for k in expected} == expected
