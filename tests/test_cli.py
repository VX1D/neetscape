"""The commands end to end on the fake board, in a temporary working directory."""
import io
import json
import os
import signal
import sys

import pytest

from conftest import cards, write_profile
from neetscape import cli, details, log
from neetscape.store import Store


@pytest.fixture(autouse=True)
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def out(capsys):
    return capsys.readouterr().out


def listed(capsys, *args):
    capsys.readouterr()
    cli.main(["list", "--format", "json", *args])
    return json.loads(out(capsys))


def store(cwd):
    return Store(cwd / "runs" / "neetscape.db")


class FakeBrowser:
    started = stopped = 0

    def __init__(self, port):
        pass

    def __enter__(self):
        FakeBrowser.started += 1
        return self

    def __exit__(self, *exc):
        FakeBrowser.stopped += 1


@pytest.fixture
def browser(monkeypatch):
    FakeBrowser.started = FakeBrowser.stopped = 0
    monkeypatch.setattr(cli, "Browser", FakeBrowser)
    return FakeBrowser


class Postings(dict):
    asked: list


@pytest.fixture
def postings(monkeypatch):
    """`details` without a browser: each offer asked gets the posting `postings[url]`, when there is one;
    `postings.asked` lists the ids of every fetch."""
    texts = Postings()
    texts.asked = []

    async def fetch(db, ids, *a, **kw):
        texts.asked.append(list(ids))
        for i in ids:
            row = db.offer(i)
            if row["url"] in texts:
                details._save(db, row, 200, texts[row["url"]], {})
    monkeypatch.setattr(cli, "fetch_details", fetch)
    monkeypatch.setattr(cli, "_details_need_browser", lambda db, ids: False)
    return texts


def test_end_to_end(fake, cwd, capsys):
    fake.pages = {("n8n", 1): [["a", "n8n Automation Specialist", {"pay_text": "b2b:12000-15000/month"}]],
                  ("*", 1): [["b", "Asystent zdalny", {"worktime": "part_time"}], ["c", "Księgowa", {"mode": "onsite"}]]}
    write_profile(cwd, searches=[{"id": "main", "where": "remote", "what": ["n8n"]},
                                 {"id": "side", "where": "remote", "what": "all", "worktime": ["part_time"]}])
    cli.main(["check"])
    cli.main(["run"])
    assert "2 offers pass" in (text := out(capsys)) and "details --pick" in text
    rows = listed(capsys)
    assert {d["title"] for d in rows} == {"n8n Automation Specialist", "Asystent zdalny"}
    assert next(d for d in rows if d["title"].startswith("n8n"))["pay_pln_month"] == "12.0–15.0k"
    cli.main(["sql", "SELECT COUNT(*) AS n FROM offers"])
    assert out(capsys).split() == ["n", "3"]
    cli.main(["show", "3"])
    assert "mode onsite" in out(capsys)


def test_country(fake, cwd, capsys):
    cli.main(["init", "--country", "de", "--preset", "broad", "--preset", "side"])
    data = json.loads((cwd / "profile.json").read_text())
    assert data["country"] == "de" and [s["id"] for s in data["searches"]] == ["remote-all", "side"]
    cli.main(["boards", "--country", "de"])
    assert "bundesagentur" in (text := out(capsys)) and "justjoin" not in text and "country" in text
    fake.pages = {("*", 1): [["a", "Kundenservice (m/w/d)", {"pay_text": "3.000 - 3.500 € monatlich"}]]}
    write_profile(cwd, country="de")
    cli.main(["run"])
    assert listed(capsys)[0]["pay_eur_month"] == "3.0–3.5k"
    write_profile(cwd)                                                   # a Polish profile on the German database
    with pytest.raises(SystemExit, match="separate --out"):
        cli.main(["run"])
    cli.main(["run", "--out", "runs-pl"])                               # another database is fine


def test_probe_save_fixture(fake, cwd, capsys):
    fake.pages = {("*", 1): cards("a", "b")}
    cli.main(["probe", "fake", "--save-fixture", "fx/fake.json"])
    assert "2 offers" in out(capsys)
    assert [k for k, _, _ in json.loads((cwd / "fx" / "fake.json").read_text())] == ["a", "b"]  # raw page, no URL line


def test_read_commands_do_not_create_a_database(fake, cwd):
    write_profile(cwd)
    for cmd in (["show", "1"], ["tracked"], ["list"], ["report"]):
        with pytest.raises(SystemExit, match="no database"):
            cli.main(cmd)
    assert not (cwd / "runs").exists()


def test_run_option_on_read_commands(fake, cwd, capsys):
    write_profile(cwd)
    fake.pages = {("*", 1): cards("a", mode="onsite")}
    cli.main(["run"])
    fake.pages = {("*", 1): cards("a", mode="remote")}
    cli.main(["run"])
    capsys.readouterr()
    cli.main(["show", "1", "--run", "1"])
    assert "all: mode onsite" in out(capsys)                            # the verdict stored for run 1
    cli.main(["show", "1"])
    assert "all: passes" in out(capsys)
    cli.main(["sql", "SELECT COUNT(*) n FROM rejections WHERE run_id = :run", "--run", "1"])
    assert out(capsys).split() == ["n", "1"]
    assert listed(capsys, "--run", "1") == []
    for cmd in (["list"], ["show", "1"], ["report"], ["sql", "SELECT 1"]):
        with pytest.raises(SystemExit, match="no run 9"):
            cli.main(cmd + ["--run", "9"])


def test_errors_exit_cleanly(fake, cwd):
    write_profile(cwd)
    cli.main(["run"])
    with pytest.raises(SystemExit, match="readonly"):
        cli.main(["sql", "DELETE FROM offers"])
    with pytest.raises(SystemExit, match="no such column"):
        cli.main(["list", "--where", "o.nope = 1"])
    with pytest.raises(SystemExit, match="no offer"):
        cli.main(["mark", "99", "applied"])


def test_show_flags_a_blacklisted_offer(fake, cwd, capsys):
    write_profile(cwd, blacklist={"companies": ["acme"], "action": "flag"})
    fake.pages = {("*", 1): [["a", "Asystent", {"company": "Acme"}]]}
    cli.main(["run"])
    capsys.readouterr()
    cli.main(["show", "1"])
    assert "blacklist (flag): blacklisted company /acme/" in out(capsys)


def test_browser_not_started_for_feed_details(fake, browser, cwd):
    write_profile(cwd, review={"mode": "auto"})                         # details during run
    fake.pages = {("*", 1): cards("a", description="full text from the feed")}
    cli.main(["run"])
    assert browser.started == 0


def test_sigterm_stops_the_browser(fake, browser, cwd, monkeypatch):
    write_profile(cwd)
    monkeypatch.setattr(cli, "_needs_browser", lambda boards: True)

    async def killed(*a, **kw):
        os.kill(os.getpid(), signal.SIGTERM)
    monkeypatch.setattr(cli, "crawl", killed)
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as e:
        cli.main(["run"])
    assert e.value.code == 128 + signal.SIGTERM and (browser.started, browser.stopped) == (1, 1)
    assert signal.getsignal(signal.SIGTERM) is before
    assert store(cwd).q("SELECT status FROM runs")[0][0] == "running"  # resumable


def test_details_counts_offers_that_drop_although_others_now_pass(fake, postings, cwd, capsys):
    write_profile(cwd, searches=[{"id": "all", "where": "remote", "what": "all", "worktime": ["part_time"], "unknown": "drop",
                                  "text_exclude": ["niemiecki"]}])
    fake.pages = {("*", 1): [["a", "Asystent", {"worktime": "part_time"}], ["b", "Konsultant", {}]]}
    cli.main(["run"])
    capsys.readouterr()
    postings.update({"https://fake/a": "Wymagany język niemiecki.",      # excludes a
                     "https://fake/b": "Praca na pół etatu."})           # settles b's unknown work time
    cli.main(["details", "--pick", "1,2"])
    assert "details: 1 offers no longer pass" in capsys.readouterr().err
    assert [d["title"] for d in listed(capsys)] == ["Konsultant"]


def test_details_picks(fake, postings, cwd):
    write_profile(cwd)
    fake.pages = {("*", 1): cards("a", "b", "c")}
    cli.main(["run"])
    db = store(cwd)
    db.save_detail(1, 200, "posting of a", {}, {})
    cli.main(["details", "--top", "10"])                                # jobs whose posting is stored are skipped
    db.save_detail(2, 0, "ERROR TimeoutError: slow", {}, {})
    db.save_detail(3, 403, "", {}, {})
    for key in "abc":
        db.mark(f"https://fake/{key}", "shortlisted")
    cli.main(["details", "--marked"])                                   # marked offers whose posting failed
    db.save_detail(3, 404, "", {}, {})
    cli.main(["details", "--marked"])                                   # gone: nothing to fetch
    assert postings.asked == [[2, 3], [2, 3], [2]]


def test_resumed_run_labels_page_limits_by_the_limit_that_cut_them(fake, cwd, capsys, monkeypatch):
    """A run started with --limit-pages 2 and resumed without it: the request fetched again stops at the board's
    max_pages, not at the original command's --limit-pages."""
    write_profile(cwd)
    fake.pages = {("*", p): cards(*(f"{p}-{i}" for i in range(3))) for p in range(1, 11)}
    monkeypatch.setattr(sys, "argv", ["neetscape", "run", "--limit-pages", "2"])   # the run stores its command line
    cli.main(sys.argv[1:])
    db = store(cwd)
    db.db.execute("UPDATE runs SET status='running'")
    db.db.execute("UPDATE requests SET status='running'")              # interrupted before the request finished
    db.db.commit()
    monkeypatch.setattr(sys, "argv", ["neetscape", "run", "--resume"])
    cli.main(sys.argv[1:])
    text = next((cwd / "runs").glob("*-run1/REPORT.md")).read_text()
    assert "2 pages, --limit-pages (deliberate)" in text                # the interrupted request
    assert "10 pages, the board's max_pages" in text and "10 pages, --limit-pages" not in text


class Pipe(io.StringIO):
    def isatty(self):
        return False


def test_progress_writes_plain_lines_off_a_terminal():
    stream = Pipe()
    with log.Progress(4, "requests", stream=stream, every=3600) as p:
        p.active("pracuj", "p12")
        p.add(pages=3, offers=150)
        p.step()
        log.tick()
    lines = stream.getvalue().splitlines()
    assert lines[0].endswith("progress [░░░░░░░░░░░░░░░░░░░░] 0/4 requests")      # on start, then quiet until `every`
    assert lines[-1] == "[██████████░░░░░░░░░░] 2/4 requests · 3 pages · 150 offers · now: pracuj p12"
    assert log._progress is None                                                  # no stray bar after the step
    log.tick()                                                                    # no bar: a no-op
