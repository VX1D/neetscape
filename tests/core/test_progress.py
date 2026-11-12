"""The progress line of long steps: plain periodic lines when stderr is not a terminal."""
import io

from neetscape import log


class Pipe(io.StringIO):
    def isatty(self):
        return False


def test_progress_writes_plain_lines_off_a_terminal():
    out = Pipe()
    with log.Progress(4, "requests", stream=out, every=3600) as p:
        p.active("pracuj", "p12")
        p.add(pages=3, offers=150)
        p.step(); log.tick()
    lines = out.getvalue().splitlines()
    assert lines[0].endswith("progress [░░░░░░░░░░░░░░░░░░░░] 0/4 requests")      # on start, then quiet until `every`
    assert lines[-1] == "[██████████░░░░░░░░░░] 2/4 requests · 3 pages · 150 offers · now: pracuj p12"
    assert log._progress is None                                                  # no stray bar after the step


def test_tick_without_a_bar_is_a_no_op():
    log.tick()
