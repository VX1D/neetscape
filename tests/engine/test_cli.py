"""test_cli.py"""
import json

import pytest


def test_cli_end_to_end(fake, tmp_path, monkeypatch, capsys):
    from neetscape import cli
    fake.pages = {("n8n", 1): [["a", "n8n Automation Specialist", {"pay_text": "b2b:12000-15000/month"}]],
                  ("*", 1): [["b", "Asystent zdalny", {"worktime": "part_time"}], ["c", "Księgowa", {"mode": "onsite"}]]}
    monkeypatch.chdir(tmp_path)
    (tmp_path / "profile.json").write_text(json.dumps({"version": 2, "boards": ["fake"], "searches": [
        {"id": "main", "where": "remote", "what": ["n8n"]},
        {"id": "side", "where": "remote", "what": "all", "worktime": ["part_time"]}], "review": {"mode": "listing"}}))
    cli.main(["check"])
    cli.main(["run"])
    out = capsys.readouterr().out
    assert "2 offers pass" in out and "details --pick" in out
    cli.main(["list", "--format", "json"])
    listed = json.loads(capsys.readouterr().out)
    assert {d["title"] for d in listed} == {"n8n Automation Specialist", "Asystent zdalny"}
    assert next(d for d in listed if d["title"].startswith("n8n"))["pay_pln_month"] == "12.0–15.0k"
    cli.main(["sql", "SELECT COUNT(*) AS n FROM offers"])
    assert capsys.readouterr().out.split() == ["n", "3"]
    cli.main(["show", "3"])
    assert "mode onsite" in capsys.readouterr().out


def test_cli_country(fake, tmp_path, monkeypatch, capsys):
    from neetscape import cli
    monkeypatch.chdir(tmp_path)
    cli.main(["init", "--country", "de", "--preset", "broad", "--preset", "side"])
    data = json.loads((tmp_path / "profile.json").read_text())
    assert data["country"] == "de" and [s["id"] for s in data["searches"]] == ["remote-all", "side"]
    cli.main(["boards", "--country", "de"])
    out = capsys.readouterr().out
    assert "bundesagentur" in out and "justjoin" not in out and "country" in out

    fake.pages = {("*", 1): [["a", "Kundenservice (m/w/d)", {"pay_text": "3.000 - 3.500 € monatlich"}]]}
    (tmp_path / "profile.json").write_text(json.dumps({"version": 2, "country": "de", "boards": ["fake"],
        "searches": [{"id": "all", "where": "remote", "what": "all"}], "review": {"mode": "listing"}}))
    cli.main(["run"])
    capsys.readouterr()
    cli.main(["list", "--format", "json"])
    assert json.loads(capsys.readouterr().out)[0]["pay_eur_month"] == "3.0–3.5k"

    (tmp_path / "profile.json").write_text(json.dumps({"version": 2, "boards": ["fake"],
        "searches": [{"id": "all", "where": "remote", "what": "all"}]}))
    import pytest
    with pytest.raises(SystemExit, match="separate --out"):
        cli.main(["run"])
    cli.main(["run", "--out", "runs-pl"])  # another database is fine


def test_probe_save_fixture(fake, tmp_path, monkeypatch, capsys):
    from neetscape import cli
    monkeypatch.chdir(tmp_path)
    fake.pages = {("*", 1): [["a", "Job A", {}], ["b", "Job B", {}]]}
    cli.main(["probe", "fake", "--save-fixture", "fx/fake.json"])
    assert "2 offers" in capsys.readouterr().out
    assert [k for k, _, _ in json.loads((tmp_path / "fx" / "fake.json").read_text())] == ["a", "b"]  # raw page, no URL line


def _profile(tmp_path, **extra):
    (tmp_path / "profile.json").write_text(json.dumps({"version": 2, "boards": ["fake"], "searches": [
        {"id": "all", "where": "remote", "what": "all"}], "review": {"mode": "listing"}, **extra}))


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
    from neetscape import cli
    FakeBrowser.started = FakeBrowser.stopped = 0
    monkeypatch.setattr(cli, "Browser", FakeBrowser)
    return FakeBrowser


def test_read_commands_do_not_create_a_database(fake, tmp_path, monkeypatch):
    from neetscape import cli
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path)
    for cmd in (["show", "1"], ["tracked"], ["list"], ["report"]):
        with pytest.raises(SystemExit, match="no database"):
            cli.main(cmd)
    assert not (tmp_path / "runs").exists()


def test_run_option_on_read_commands(fake, tmp_path, monkeypatch, capsys):
    from neetscape import cli
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path)
    fake.pages = {("*", 1): [["a", "Job A", {"mode": "onsite"}]]}
    cli.main(["run"])
    fake.pages = {("*", 1): [["a", "Job A", {"mode": "remote"}]]}
    cli.main(["run"])
    capsys.readouterr()
    cli.main(["show", "1", "--run", "1"])
    assert "all: mode onsite" in capsys.readouterr().out          # the verdict stored for run 1
    cli.main(["show", "1"])
    assert "all: passes" in capsys.readouterr().out
    cli.main(["sql", "SELECT COUNT(*) n FROM rejections WHERE run_id = :run", "--run", "1"])
    assert capsys.readouterr().out.split() == ["n", "1"]
    cli.main(["list", "--run", "1", "--format", "json"])
    assert json.loads(capsys.readouterr().out) == []
    for cmd in (["list"], ["show", "1"], ["report"], ["sql", "SELECT 1"]):
        with pytest.raises(SystemExit, match="no run 9"):
            cli.main(cmd + ["--run", "9"])


def test_sql_errors_exit_cleanly(fake, tmp_path, monkeypatch, capsys):
    from neetscape import cli
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path)
    cli.main(["run"])
    with pytest.raises(SystemExit, match="readonly"):
        cli.main(["sql", "DELETE FROM offers"])
    with pytest.raises(SystemExit, match="no such column"):
        cli.main(["list", "--where", "o.nope = 1"])
    with pytest.raises(SystemExit, match="no offer"):
        cli.main(["mark", "99", "applied"])


def test_list_group_title(fake, tmp_path, monkeypatch, capsys):
    from neetscape import cli
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path)
    fake.pages = {("*", 1): [["a", "Support Agent", {"company": "A"}], ["b", "Support agent", {"company": "B"}]]}
    cli.main(["run"])
    capsys.readouterr()
    cli.main(["list", "--group", "title", "--format", "json"])
    assert [(g["title"], g["offers"], g["companies"]) for g in json.loads(capsys.readouterr().out)] == [("Support Agent", 2, 2)]


def test_browser_not_started_for_feed_details(fake, browser, tmp_path, monkeypatch):
    from neetscape import cli
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path, review={"mode": "auto"})                         # details during run
    fake.pages = {("*", 1): [["a", "Job A", {"description": "full text from the feed"}]]}
    cli.main(["run"])
    assert browser.started == 0


def test_sigterm_stops_the_browser(fake, browser, tmp_path, monkeypatch):
    import os
    import signal
    from neetscape import cli
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path)
    monkeypatch.setattr(cli, "_needs_browser", lambda boards: True)

    async def killed(*a, **kw):
        os.kill(os.getpid(), signal.SIGTERM)
    monkeypatch.setattr(cli, "crawl", killed)
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as e:
        cli.main(["run"])
    assert e.value.code == 128 + signal.SIGTERM and (browser.started, browser.stopped) == (1, 1)
    assert signal.getsignal(signal.SIGTERM) is before
    from neetscape.store import Store
    assert Store(tmp_path / "runs" / "neetscape.db").q("SELECT status FROM runs")[0][0] == "running"  # resumable


def test_details_counts_offers_that_drop_although_others_now_pass(fake, tmp_path, monkeypatch, capsys):
    from neetscape import cli, details
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path, searches=[{"id": "all", "where": "remote", "what": "all", "worktime": ["part_time"], "unknown": "drop",
                                  "text_exclude": ["niemiecki"]}])
    fake.pages = {("*", 1): [["a", "Asystent", {"worktime": "part_time"}], ["b", "Konsultant", {}]]}
    cli.main(["run"])
    capsys.readouterr()
    postings = {"https://fake/a": "Wymagany język niemiecki.", "https://fake/b": "Praca na pół etatu."}

    async def fetch(store, ids, *a, **kw):   # a's posting excludes it, b's settles its unknown work time
        for i in ids:
            row = store.offer(i)
            details._save(store, row, 200, postings[row["url"]], {})
    monkeypatch.setattr(cli, "fetch_details", fetch)
    monkeypatch.setattr(cli, "_details_need_browser", lambda store, ids: False)
    cli.main(["details", "--pick", "1,2"])
    assert "details: 1 offers no longer pass" in capsys.readouterr().err
    cli.main(["list", "--format", "json"])
    assert [d["title"] for d in json.loads(capsys.readouterr().out)] == ["Konsultant"]


def test_show_flags_a_blacklisted_offer(fake, tmp_path, monkeypatch, capsys):
    from neetscape import cli
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path, blacklist={"companies": ["acme"], "action": "flag"})
    fake.pages = {("*", 1): [["a", "Asystent", {"company": "Acme"}]]}
    cli.main(["run"])
    capsys.readouterr()
    cli.main(["show", "1"])
    assert "blacklist (flag): blacklisted company /acme/" in capsys.readouterr().out
