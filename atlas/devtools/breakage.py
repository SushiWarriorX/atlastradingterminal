"""Break a module one small change at a time and see whether its tests notice (standard library only).

Usage (from the repository root; the table is a Python file that defines CHANGES and, if there are any, EQUIVALENT):

    python3 atlas/devtools/breakage.py atlas_api/mod.py --cwd atlas/backend --table my_table.py --tests tests/test_mod.py

    CHANGES = [("limit lower", "LIMIT = 10", "LIMIT = 9"),
               ("order: b before a", ["    a()\\n", "    b()\\n"], ["", "    b()\\n    a()\\n"])]   # lists: several edits made one after the other
    EQUIVALENT = [("edge", "x > LIMIT", "x >= LIMIT")]   # changes that cannot alter behaviour; --equiv runs them and they must all survive

The folder given by --cwd is COPIED to a temporary folder and every change is made in the copy (pytest runs there with bytecode off), so the original is never written. The clean copy is run first and must pass. A pattern that is found other than once (each edit of a list is looked for in the text left by the one before), a change that changes nothing, a repeated name or a list of edits of two lengths is refused before anything runs.
Exit code: 0 = no survivor (with --equiv: every equivalent survived), 1 = survivors (with --equiv: one was caught, so it is not equivalent), 2 = the table or the clean copy could not be run. --dry only checks the table. --only NAME (repeatable) runs the named changes alone, which is how survivors are run again after a test was added."""
from __future__ import annotations

import argparse
import hashlib
import os
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SKIP = shutil.ignore_patterns("__pycache__", ".pytest_cache", "node_modules", ".git", "*.pyc")


def edits(old, new) -> list[tuple[str, str]]:
    olds, news = ([old] if isinstance(old, str) else list(old)), ([new] if isinstance(new, str) else list(new))
    if len(olds) != len(news) or not olds:
        raise ValueError("lists of edits of two lengths")
    return list(zip(olds, news))


def apply(src: str, old, new) -> str:
    for o, n in edits(old, new):
        src = src.replace(o, n, 1)
    return src


def problems(src: str, table: list) -> list[str]:
    out, seen = [], set()
    for name, old, new in table:
        if name in seen:
            out.append(f"{name}: the name is used twice")
        seen.add(name)
        try:
            cur = src
            for o, n in edits(old, new):
                found = cur.count(o)
                if found != 1:
                    out.append(f"{name}: a pattern is found {found} times, not once: {o[:60]!r}")
                    break
                cur = cur.replace(o, n, 1)
            else:
                if cur == src:
                    out.append(f"{name}: the change changes nothing")
        except ValueError as e:
            out.append(f"{name}: {e}")
    return out


def _stop(*_) -> None:
    raise KeyboardInterrupt                                   # a stop request unwinds through the cleanup in main


def run_tests(root: Path, tests: list[str], timeout: int) -> bool:
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests], cwd=root, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired:
        return False                                          # a change that makes the code hang was noticed by the tests
    return r.returncode == 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Break a module one change at a time and see whether its tests notice.")
    ap.add_argument("module", help="the file to break, relative to --cwd")
    ap.add_argument("--table", required=True, help="a Python file that defines CHANGES and optionally EQUIVALENT")
    ap.add_argument("--tests", nargs="+", required=True, help="the test files to run, relative to --cwd")
    ap.add_argument("--cwd", default=".", help="the folder pytest runs in; it is copied and the original is never written")
    ap.add_argument("--dry", action="store_true", help="only check the table")
    ap.add_argument("--equiv", action="store_true", help="run the EQUIVALENT list: every change should survive")
    ap.add_argument("--only", action="append", default=[], help="run only the named change (repeatable)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds one test run may take before the change counts as caught")
    a = ap.parse_args(argv)
    root = Path(a.cwd).resolve()
    original = root / a.module
    if not original.is_file():
        print(f"no such file: {original}")
        return 2
    ns = runpy.run_path(str(Path(a.table).resolve()))
    table = list(ns.get("EQUIVALENT", []) if a.equiv else ns.get("CHANGES", []))
    if a.only:
        missing = [n for n in a.only if n not in {t[0] for t in table}]
        if missing:
            print("not in the table:", missing)
            return 2
        table = [t for t in table if t[0] in a.only]
    src, before = original.read_text(encoding="utf-8"), hashlib.sha256(original.read_bytes()).hexdigest()
    bad = problems(src, table)
    for line in bad:
        print("REFUSED:", line)
    if bad or a.dry:
        print(f"{len(table)} changes; {len(bad)} refused" if bad else f"{len(table)} changes, every pattern found exactly once, each changes the text; nothing was run")
        return 2 if bad else 0
    tmp = Path(tempfile.mkdtemp(prefix="breakage-"))
    previous = signal.signal(signal.SIGTERM, _stop)
    try:
        work = tmp / "work"
        shutil.copytree(root, work, ignore=SKIP)
        target = work / a.module
        if not run_tests(work, a.tests, a.timeout):
            print("the CLEAN copy does not pass: nothing below would mean anything, stopping")
            return 2
        print("clean copy passes first: True", flush=True)
        caught, survived, t0 = 0, [], time.time()
        for name, old, new in table:
            target.write_text(apply(src, old, new), encoding="utf-8")
            try:
                ok = run_tests(work, a.tests, a.timeout)
            finally:
                target.write_text(src, encoding="utf-8")
            if ok:
                survived.append(name)
                print("SURVIVED:", name, flush=True)
            else:
                caught += 1
        untouched = hashlib.sha256(original.read_bytes()).hexdigest() == before and target.read_text(encoding="utf-8") == src
        print(f"{len(table)} changes run, {caught} caught, {len(survived)} survived, original untouched and copy restored: {untouched}, {time.time() - t0:.0f}s")
        if a.equiv:
            print("equivalent changes that were caught (so not equivalent):", [n for n, *_ in table if n not in survived] or "none")
            return 0 if caught == 0 and untouched else 1
        return 0 if not survived and untouched else 1
    except KeyboardInterrupt:
        print("stopped: the working copy is removed and the original was never written")
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
