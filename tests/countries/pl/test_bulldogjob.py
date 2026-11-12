"""bulldogjob.pl (GraphQL search API) on its recorded response tests/fixtures/pl/bulldogjob.json."""
import json
from pathlib import Path

import pytest

from neetscape.boards import REGISTRY
from neetscape.boards.base import Request

FX = Path(__file__).parents[2] / "fixtures" / "pl" / "bulldogjob.json"
B = REGISTRY["bulldogjob"]


def parse(raw=None):
    return B.parse(FX.read_text() if raw is None else raw, Request("bulldogjob", "t", None))


def test_modes_and_worktime():
    node = json.loads(FX.read_text())["data"]["searchJobs"]["nodes"][0]
    one = lambda **kw: parse(json.dumps({"data": {"searchJobs": {"nodes": [dict(node, **kw)]}}}))[0]
    assert one(workModes=["on-site", "hybrid"], remote=False).mode == "hybrid"
    assert one(workModes=["on-site"], remote=False).mode == "onsite"
    assert one(workModes=["on-site", "full-remote"]).mode == "remote"
    assert one(employmentType="freelance").worktime == "flexible" and one(employmentType="contractor").worktime == "unknown"


def test_errors_raise():
    with pytest.raises(ValueError):
        parse(json.dumps({"errors": [{"message": "x"}]}))
    with pytest.raises(ValueError):
        parse("")
