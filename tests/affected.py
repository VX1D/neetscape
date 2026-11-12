#!/usr/bin/env python3
"""Run only the tests affected by your changes.

    python tests/affected.py            # changes vs HEAD (staged, unstaged, untracked)
    python tests/affected.py main       # changes vs another ref
    python tests/affected.py --dry-run  # print the pytest command only

A change to one board's parser runs that board's tests; core modules run the areas that use them;
anything unmapped (or a change to this file / conftest) runs the whole suite.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BOARD_TESTS = ["tests/boards", "tests/countries"]  # every board's tests (parsers on fixtures, URLs, country consistency)
ENGINE = "tests/engine"
RULES: list[tuple[str, list[str]]] = [  # path regex -> test paths (first match wins)
    (r"^neetscape/pay\.py$", ["tests/core", *BOARD_TESTS, "tests/engine/test_evaluate.py"]),
    (r"^neetscape/(infer|posting)\.py$", ["tests/core", *BOARD_TESTS]),
    (r"^neetscape/boards/pages\.py$", BOARD_TESTS),
    (r"^neetscape/boards/(base|fetch|__init__)\.py$", [*BOARD_TESTS, "tests/engine/test_planner.py", "tests/engine/test_store.py",
                                                     "tests/engine/test_cli.py"]),
    (r"^neetscape/countries/\w+/boards/__init__\.py$", ["tests/countries"]),  # which boards a country registers
    (r"^neetscape/country\.py$", ["tests/core", ENGINE, "tests/countries"]),
    (r"^neetscape/countries/(__init__\.py$|\w+/__init__\.py$|\w+/presets/)", ["tests/countries", "tests/engine/test_profile.py"]),
    (r"^neetscape/lang/", ["tests/core", "tests/countries"]),
    (r"^neetscape/(model|store)\.py$", [ENGINE]),
    (r"^neetscape/profile/", ["tests/engine/test_profile.py", "tests/engine/test_planner.py", "tests/engine/test_evaluate.py"]),
    (r"^neetscape/planner\.py$", ["tests/engine/test_planner.py", "tests/engine/test_cli.py"]),
    (r"^neetscape/evaluate\.py$", ["tests/engine/test_evaluate.py", "tests/engine/test_store.py", "tests/engine/test_cli.py"]),
    (r"^neetscape/crawler\.py$", ["tests/engine/test_store.py", "tests/engine/test_cli.py"]),
    (r"^neetscape/(report|details|cli)\.py$", ["tests/engine/test_store.py", "tests/engine/test_cli.py"]),
    (r"^neetscape/browser\.py$", ["tests/engine/test_browser.py"]),
    (r"^neetscape/(log|__init__|__main__)\.py$", []),
    (r"^(README|AGENTS|CLAUDE|CONTRIBUTING)\.md$|^docs/|^LICENSE$|^\.github/", []),
    (r"^tests/(core|boards|engine|countries)/(\w+/)*test_\w+\.py$", ["{path}"]),
    (r"^tests/live/", []),  # live tests run only on demand: pytest -m live
]


def board_names(path: str) -> list[str]:
    """Boards defined in a board module (its `name = "..."` lines; none for a helper module such as `vocab.py`);
    the file name when it is gone."""
    f = ROOT / path
    return re.findall(r'^\s+name = "(\w+)"', f.read_text(), re.M) if f.exists() else [Path(path).stem]


def board_tests(cc: str | None) -> list[str]:
    """Tests of one country's boards (cc) or of the shared boards (None)."""
    if cc is None:
        return ["tests/boards", "tests/countries/test_countries.py"]
    own = [p for p in (f"tests/countries/{cc}", f"tests/countries/test_{cc}.py") if (ROOT / p).exists()]
    return own + ["tests/countries/test_countries.py"]


def board_change(p: str) -> tuple[list[str], list[str]] | None:
    """(tests, board names) when `p` belongs to one board: its module or one of its recorded fixtures. A helper
    module of a country's boards (no board names) gives that country's board tests, not narrowed."""
    m = re.match(r"^neetscape/countries/(\w+)/boards/(\w+)\.py$", p)
    if m and m.group(2) != "__init__":
        return board_tests(m.group(1)), board_names(p)
    m = re.match(r"^neetscape/boards/(linkedin|feeds)\.py$", p)
    if m:
        return board_tests(None), board_names(p)
    m = re.match(r"^tests/fixtures/(\w+)/([a-z0-9]+)[._]", p)
    if m:
        cc = None if m.group(1) == "shared" else m.group(1)
        return board_tests(cc), [m.group(2)]
    return None


def changed(ref: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", ref], cwd=ROOT, capture_output=True, text=True).stdout.split()
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return sorted(set(out + untracked))


def select(paths: list[str]) -> tuple[list[str], list[str]] | None:
    """(test paths, -k board names) or None for the full suite. Board names are given only when every change
    belongs to a board (then the selected tests can be narrowed to those boards)."""
    tests: set[str] = set()
    boards: set[str] = set()
    only_boards = True
    for p in paths:
        hit = board_change(p)
        if hit:
            tests.update(hit[0])
            boards.update(hit[1])
            only_boards = only_boards and bool(hit[1])
            # a fixture read by name outside the board tests (e.g. a posting page in tests/core) runs those tests whole
            if p.startswith("tests/fixtures/"):
                users = [str(t.relative_to(ROOT)) for t in (ROOT / "tests").rglob("test_*.py")
                         if Path(p).name in t.read_text() and not str(t.relative_to(ROOT)).startswith(tuple(hit[0]))]
                if users:
                    tests.update(users)
                    only_boards = False
            continue
        for rx, targets in RULES:
            if re.search(rx, p):
                tests.update(t.format(path=p) for t in targets)
                only_boards = only_boards and not targets
                break
        else:
            return None  # unknown file (conftest, pyproject, this script, ...): run everything
    return sorted(tests), sorted(boards) if only_boards else []


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    paths = changed(args[0] if args else "HEAD")
    sel = select(paths)
    if sel is None:
        cmd = [sys.executable, "-m", "pytest", "-q"]
    else:
        tests, boards = sel
        if not tests:
            print("no tests affected by:", ", ".join(paths) or "(no changes)")
            return 0
        cmd = [sys.executable, "-m", "pytest", "-q", *tests]
        if boards:  # board-only change: narrow the selected tests to those boards
            cmd += ["-k", " or ".join(boards)]
    print("$", " ".join(cmd))
    if "--dry-run" in sys.argv:
        return 0
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
