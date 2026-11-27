"""The breakage tool (`devtools/breakage.py`): it breaks a module in a COPY one change at a time, names the changes the tests did not notice, refuses a table that cannot be run, never writes the original and cleans up after itself, also when it is told to stop."""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

import breakage as B

DEV = Path(__file__).resolve().parents[1]

MOD = '''LIMIT = 10


def clamp(x):
    if x > LIMIT:
        return LIMIT
    return x


def label(x):
    return "big" if x >= 100 else "small"


def first(items):
    return items[0]
'''
TESTS = '''from mod import LIMIT, clamp, first, label


def test_clamp():
    assert clamp(11) == 10 and clamp(10) == 10 and clamp(3) == 3


def test_label():
    assert label(5) == "small"                  # the edge of 100 is not pinned: a change there survives


def test_limit():
    assert LIMIT == 10


def test_first():
    assert first([4, 5]) == 4
'''
TABLE = '''CHANGES = [("limit lower", "LIMIT = 10", "LIMIT = 9"),
           ("label edge", "x >= 100", "x > 100"),
           ("first item", "items[0]", "items[1]")]
EQUIVALENT = [("clamp edge", "x > LIMIT", "x >= LIMIT")]
'''


@pytest.fixture
def toy(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "mod.py").write_text(MOD)
    (proj / "test_mod.py").write_text(TESTS)
    (proj / "test_unrelated.py").write_text("def test_fails():\n    assert False\n")                    # never named by --tests: a run that picks it up has a failing clean copy
    table = tmp_path / "table.py"
    table.write_text(TABLE)
    return proj, table


def run(proj, table, *extra, capsys):
    rc = B.main(["mod.py", "--cwd", str(proj), "--table", str(table), "--tests", "test_mod.py", *extra])
    return rc, capsys.readouterr().out


def table_of(tmp_path, text):
    p = tmp_path / "other_table.py"
    p.write_text(text)
    return p


def test_a_dry_run_accepts_a_good_table_and_runs_nothing(toy, capsys):
    proj, table = toy
    rc, out = run(proj, table, "--dry", capsys=capsys)
    assert rc == 0 and "3 changes, every pattern found exactly once, each changes the text; nothing was run" in out and "clean copy" not in out


def test_a_run_names_the_survivor_catches_the_rest_and_leaves_the_original_byte_for_byte(toy, capsys):
    proj, table = toy
    before = {p.name: p.read_bytes() for p in proj.iterdir()}
    rc, out = run(proj, table, capsys=capsys)
    assert rc == 1
    assert "clean copy passes first: True" in out and "SURVIVED: label edge" in out
    assert "SURVIVED: limit lower" not in out and "SURVIVED: first item" not in out
    assert "3 changes run, 2 caught, 1 survived, original untouched and copy restored: True" in out
    assert {p.name: p.read_bytes() for p in proj.iterdir()} == before                 # no file written, and no __pycache__ made in the original folder


def test_a_table_with_no_survivor_exits_with_zero(toy, tmp_path, capsys):
    proj, _ = toy
    t = table_of(tmp_path, 'CHANGES = [("limit lower", "LIMIT = 10", "LIMIT = 9"), ("first item", "items[0]", "items[1]")]\n')
    rc, out = run(proj, t, capsys=capsys)
    assert rc == 0 and "2 changes run, 2 caught, 0 survived" in out


def test_the_equivalent_list_must_survive(toy, capsys):
    proj, table = toy
    rc, out = run(proj, table, "--equiv", capsys=capsys)
    assert rc == 0 and "1 changes run, 0 caught, 1 survived" in out and "SURVIVED: clamp edge" in out and "equivalent changes that were caught (so not equivalent): none" in out


def test_an_equivalent_change_that_is_caught_is_reported_and_fails(toy, tmp_path, capsys):
    proj, _ = toy
    t = table_of(tmp_path, 'CHANGES = []\nEQUIVALENT = [("limit lower", "LIMIT = 10", "LIMIT = 9")]\n')
    rc, out = run(proj, t, "--equiv", capsys=capsys)
    assert rc == 1 and "equivalent changes that were caught (so not equivalent): ['limit lower']" in out


def test_only_runs_the_named_changes_and_refuses_an_unknown_name(toy, capsys):
    proj, table = toy
    rc, out = run(proj, table, "--only", "label edge", capsys=capsys)
    assert rc == 1 and "1 changes run, 0 caught, 1 survived" in out
    rc, out = run(proj, table, "--only", "limit lower", "--only", "first item", capsys=capsys)
    assert rc == 0 and "2 changes run, 2 caught, 0 survived" in out
    rc, out = run(proj, table, "--only", "no such change", capsys=capsys)
    assert rc == 2 and "not in the table: ['no such change']" in out and "clean copy" not in out


@pytest.mark.parametrize("changes, expected", [
    ('[("many", "x", "y")]', "many: a pattern is found"),
    ('[("missing", "no such text", "y")]', "missing: a pattern is found 0 times, not once"),
    ('[("same", "LIMIT = 10", "LIMIT = 10")]', "same: the change changes nothing"),
    ('[("a", "LIMIT = 10", "LIMIT = 9"), ("a", "items[0]", "items[1]")]', "a: the name is used twice"),
    ('[("lists", ["LIMIT = 10", "items[0]"], ["LIMIT = 9"])]', "lists: lists of edits of two lengths"),
    ('[("gone", ["LIMIT = 10", "LIMIT = 10"], ["x = 1", "LIMIT = 9"])]', "gone: a pattern is found 0 times, not once"),     # the second edit looks in the text the first one left
    ('[("empty", [], [])]', "empty: lists of edits of two lengths"),
])
def test_a_table_that_cannot_be_run_is_refused_before_anything_runs(toy, tmp_path, capsys, changes, expected):
    proj, _ = toy
    rc, out = run(proj, table_of(tmp_path, f"CHANGES = {changes}\n"), capsys=capsys)
    assert rc == 2 and "REFUSED: " + expected in out and "clean copy" not in out


def test_a_pattern_found_twice_is_refused_even_when_a_dry_run_is_asked_for(toy, tmp_path, capsys):
    proj, _ = toy
    rc, out = run(proj, table_of(tmp_path, 'CHANGES = [("many", "x", "y")]\n'), "--dry", capsys=capsys)
    assert rc == 2 and f"REFUSED: many: a pattern is found {MOD.count('x')} times, not once: 'x'" in out and "1 changes; 1 refused" in out


def test_the_refusal_shows_the_first_60_characters_of_the_pattern(toy, tmp_path, capsys):
    proj, _ = toy
    rc, out = run(proj, table_of(tmp_path, 'CHANGES = [("long", "q" * 80, "y")]\n'), "--dry", capsys=capsys)
    assert rc == 2 and f"not once: '{'q' * 60}'" in out and "q" * 61 not in out


def test_a_list_of_edits_is_made_one_after_the_other_and_caught_as_one_change(toy, tmp_path, capsys):
    proj, _ = toy
    t = table_of(tmp_path, 'CHANGES = [("two edits", ["LIMIT = 10", "def first(items):\\n    return items[0]"], ["LIMIT = 11", "def first(items):\\n    return items[-1]"])]\n')
    rc, out = run(proj, t, capsys=capsys)
    assert rc == 0 and "1 changes run, 1 caught, 0 survived" in out
    t = table_of(tmp_path, 'CHANGES = [("moves a line", ["    return items[0]\\n", "LIMIT = 10\\n"], ["", "LIMIT = 10\\n    return items[0]\\n"])]\n')
    assert B.problems(MOD, B.runpy.run_path(str(t))["CHANGES"]) == []                      # the second pattern is found in the text the first edit left


def test_a_failing_clean_copy_stops_the_run(toy, capsys):
    proj, table = toy
    (proj / "test_mod.py").write_text(TESTS + "\n\ndef test_broken():\n    assert False\n")
    rc, out = run(proj, table, capsys=capsys)
    assert rc == 2 and "the CLEAN copy does not pass" in out and "SURVIVED" not in out


def test_a_change_that_hangs_or_that_cannot_be_imported_counts_as_caught(toy, tmp_path, capsys):
    proj, _ = toy
    t = table_of(tmp_path, 'CHANGES = [("hang", "return items[0]", "while True:\\n        pass"), ("syntax", "LIMIT = 10", "LIMIT = = 10")]\n')
    rc, out = run(proj, t, "--timeout", "4", capsys=capsys)
    assert rc == 0 and "2 changes run, 2 caught, 0 survived, original untouched and copy restored: True" in out


def test_the_tests_run_in_a_copy_without_caches_and_with_bytecode_off(toy, tmp_path, capsys, monkeypatch):
    proj, _ = toy
    (proj / "test_mod.py").write_text("import os, sys\nfrom pathlib import Path\n\n\ndef test_probe():\n    Path(os.environ['PROBE']).write_text(f'{sys.dont_write_bytecode} {sorted(os.listdir(\".\"))}')\n")
    for name in ("__pycache__", ".pytest_cache", "node_modules", ".git"):
        (proj / name).mkdir()
        (proj / name / "stale.txt").write_text("not for the copy")
    (proj / "stale.pyc").write_bytes(b"not for the copy")
    probe = tmp_path / "probe.txt"
    monkeypatch.setenv("PROBE", str(probe))
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)                                # the tool has to switch it off itself
    rc, out = run(proj, table_of(tmp_path, 'CHANGES = [("limit lower", "LIMIT = 10", "LIMIT = 9")]\n'), capsys=capsys)
    assert rc == 1 and "1 changes run, 0 caught, 1 survived" in out                        # the toy test does not look at the module: the change survives
    assert probe.read_text() == "True ['mod.py', 'test_mod.py', 'test_unrelated.py']"      # bytecode off (a stale .pyc of the same size and second could hide a change); none of the four folders and no .pyc copied
    assert sorted(p.name for p in proj.iterdir()) == [".git", ".pytest_cache", "__pycache__", "mod.py", "node_modules", "stale.pyc", "test_mod.py", "test_unrelated.py"]


def test_a_module_with_non_ascii_text_is_read_and_written_as_utf_8_whatever_the_locale(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "mod.py").write_text('NAME = "caf\u00e9"\n', encoding="utf-8")
    (proj / "test_mod.py").write_text('from mod import NAME\n\n\ndef test_name():\n    assert NAME == "caf\\u00e9"\n', encoding="utf-8")
    table = tmp_path / "t.py"
    table.write_text('CHANGES = [("rename", "NAME = ", "OTHER = ")]\n', encoding="utf-8")                  # the changed text still holds the accent
    env = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}          # a machine whose default text encoding is not UTF-8
    r = subprocess.run([sys.executable, str(DEV / "breakage.py"), "mod.py", "--cwd", str(proj), "--table", str(table), "--tests", "test_mod.py"], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "1 changes run, 1 caught, 0 survived, original untouched and copy restored: True" in r.stdout, r.stderr[-400:]


def test_a_missing_module_is_said_in_one_line(toy, capsys):
    proj, table = toy
    rc = B.main(["nope.py", "--cwd", str(proj), "--table", str(table), "--tests", "test_mod.py"])
    assert rc == 2 and "no such file" in capsys.readouterr().out


def test_the_working_copy_is_removed_after_a_run_and_the_stop_handler_is_put_back(toy, tmp_path, capsys, monkeypatch):
    proj, table = toy
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    known = lambda *_: None                                                       # a handler of our own, so that one left behind by an earlier run cannot be mistaken for the original
    before = signal.signal(signal.SIGTERM, known)
    try:
        run(proj, table, "--only", "limit lower", capsys=capsys)
        assert list(scratch.iterdir()) == [] and signal.getsignal(signal.SIGTERM) is known
        run(proj, table, "--dry", capsys=capsys)
        assert list(scratch.iterdir()) == [] and signal.getsignal(signal.SIGTERM) is known
    finally:
        signal.signal(signal.SIGTERM, before)


def test_a_stop_request_cleans_up_and_leaves_the_original_alone(toy, tmp_path):
    proj, _ = toy
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    t = table_of(tmp_path, 'CHANGES = [("hang", "return items[0]", "while True:\\n        pass")]\n')
    before = (proj / "mod.py").read_bytes()
    p = subprocess.Popen([sys.executable, str(DEV / "breakage.py"), "mod.py", "--cwd", str(proj), "--table", str(t), "--tests", "test_mod.py"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env={**os.environ, "TMPDIR": str(scratch)})
    line = p.stdout.readline()                                  # "clean copy passes first: True": the hanging change is being run now
    assert "clean copy passes first: True" in line
    time.sleep(1.5)
    p.send_signal(signal.SIGTERM)
    out = p.stdout.read()
    p.wait(timeout=30)
    p.stdout.close()
    p.stderr.close()
    assert p.returncode == 130 and "stopped: the working copy is removed and the original was never written" in out
    assert list(scratch.iterdir()) == [] and (proj / "mod.py").read_bytes() == before


def test_the_command_line_runs_as_a_program_and_prints_the_help(toy):
    r = subprocess.run([sys.executable, str(DEV / "breakage.py"), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "--table" in r.stdout and "--equiv" in r.stdout and "--only" in r.stdout
