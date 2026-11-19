"""The chore every cycle ends with: add a row to the STATE BOARD in HANDOFF.md and move the oldest rows, unchanged, to HANDOFF_ARCHIVE.md (found 2026-11-18: it had been written as a new scratch script each hour, thirteen times in a row, and once a shell heredoc ate the values of one).

    python3 atlas/devtools/board.py add --job data --changed-file CHANGED.txt --next-file NEXT.txt [--who Claude] [--when "2026-11-19 00:47"] [--label "00 UTC improve job"] [--keep 20] [--dry-run]
    python3 atlas/devtools/board.py check

The two texts are read from files, not from the command line, so that no shell can touch backticks or dollar signs in them (write the files with an editor tool). A cell may not contain a pipe, a line break or nothing. The row goes to the top of the table that follows the line starting with "## STATE BOARD"; when the board then holds more than `--keep` rows (20) the oldest go directly under the archive's table header, newest first, with one "Moved on ..." line above the earlier ones. Nothing is written unless the result passes the same checks `check` runs (five columns, newest first, no row both on the board and in the archive, none twice in the archive) and `backend/tests/test_docs_hygiene.py` agrees. `--dry-run` says what would change and writes nothing. Exit 0 = done, 1 = refused (the reason is printed), 2 = bad usage."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ATLAS = Path(__file__).resolve().parent.parent
KEEP = 20
STAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
ROW = re.compile(r"^\| (\d{4}-\d\d-\d\d \d\d:\d\d) \|")


class BoardError(Exception):
    """Something the chore cannot do safely; the message says what to fix."""


def span(lines: list[str]) -> tuple[int, int]:
    """(first, last) line of the board's rows: the lines starting `| 20` between the STATE BOARD heading and the next heading."""
    start = next((i for i, l in enumerate(lines) if l.startswith("## STATE BOARD")), None)
    if start is None:
        raise BoardError("HANDOFF.md has no line starting with '## STATE BOARD'")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    idx = [i for i in range(start, end) if lines[i].startswith("| 20")]
    if not idx:
        raise BoardError("the STATE BOARD has no rows")
    if idx != list(range(idx[0], idx[-1] + 1)):
        raise BoardError("the rows of the STATE BOARD are not one block")
    return idx[0], idx[-1]


def make_row(when: str, who: str, job: str, changed: str, nxt: str) -> str:
    if not STAMP.match(when):
        raise BoardError(f"the time {when!r} is not like 2026-11-19 00:47")
    cells = []
    for name, value in (("who", who), ("job", job), ("what changed", changed), ("next suggestion", nxt)):
        text = value.strip()
        if not text:
            raise BoardError(f"the {name} cell is empty")
        if "\n" in text or "\r" in text:
            raise BoardError(f"the {name} cell has a line break")
        if "|" in text:
            raise BoardError(f"the {name} cell has a pipe, which would split the table")
        cells.append(text)
    return f"| {when} | {' | '.join(cells)} |"


def problems(handoff: str, archive: str, keep: int = KEEP) -> list[str]:
    """What is wrong with the board and the archive as they stand (empty = fine)."""
    out: list[str] = []
    try:
        a, b = span(handoff.split("\n"))
    except BoardError as e:
        return [str(e)]
    rows = handoff.split("\n")[a:b + 1]
    if len(rows) > keep:
        out.append(f"the board has {len(rows)} rows, more than {keep}")
    stamps = []
    for r in rows:
        if r.count("|") != 6:
            out.append(f"a board row has {r.count('|') - 1} columns, not 5: {r[:50]}")
        m = ROW.match(r)
        if m:
            stamps.append(m.group(1))
        else:
            out.append(f"a board row does not start with a stamp like 2026-11-17 18:02: {r[:40]}")
    if any(x < y for x, y in zip(stamps, stamps[1:])):
        out.append("the board is not newest first")
    old = [l for l in archive.split("\n") if l.startswith("| 20")]
    if any(r.count("|") != 6 for r in old):
        out.append("an archive row does not have 5 columns")
    if len(set(old)) != len(old):
        out.append("a row is in the archive twice")
    if set(old) & set(rows):
        out.append("a row is both on the board and in the archive")
    return out


def add(handoff: str, archive: str, row: str, label: str, keep: int = KEEP) -> tuple[str, str, list[str]]:
    """(new HANDOFF.md text, new archive text, the rows moved) after adding `row` on top of the board."""
    if keep < 1:
        raise BoardError("--keep must be at least 1")
    hl, al = handoff.split("\n"), archive.split("\n")
    first, last = span(hl)
    rows = hl[first:last + 1]
    if any(r.count("|") != 6 or not ROW.match(r) for r in rows):
        raise BoardError("a row on the board is not in the five-column form: run `check`")
    stamp = ROW.match(row).group(1)
    if stamp < ROW.match(rows[0]).group(1):
        raise BoardError(f"the new row ({stamp}) is older than the newest row on the board ({ROW.match(rows[0]).group(1)})")
    if row in rows:
        raise BoardError("this row is already on the board")
    new = [row] + rows
    board, moved = new[:keep], new[keep:]
    hl[first:last + 1] = board
    if moved:
        head = next((i for i, l in enumerate(al) if l.startswith("| When (UTC)")), None)
        if head is None or head + 1 >= len(al) or not al[head + 1].startswith("| --- "):
            raise BoardError("HANDOFF_ARCHIVE.md has no table header ('| When (UTC)' and a '| --- ' line under it)")
        first_note = next((i for i, l in enumerate(al) if l.startswith("Moved on ")), None)
        if first_note is None or first_note > head:
            raise BoardError("HANDOFF_ARCHIVE.md has no 'Moved on ...' lines above its table")
        newest, oldest = ROW.match(moved[0]).group(1), ROW.match(moved[-1]).group(1)
        count = "1 row" if len(moved) == 1 else f"{len(moved)} rows"
        span_text = newest if len(moved) == 1 else f"from {newest} back to {oldest}"
        al[head + 2:head + 2] = moved                                                  # the rows first (the later position), then the line above the earlier ones
        al.insert(first_note, f"Moved on {stamp[:10]} ({label}): {count}, {span_text}.")
    out_h, out_a = "\n".join(hl), "\n".join(al)
    found = problems(out_h, out_a, keep)
    if found:
        raise BoardError("the result would not pass the checks: " + "; ".join(found))
    return out_h, out_a, moved


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="board.py", description="Add a STATE BOARD row and move the oldest rows to the archive.")
    p.add_argument("--root", default=str(ATLAS), help="the folder holding HANDOFF.md and HANDOFF_ARCHIVE.md (default: atlas/)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--job", required=True, help="the Job cell, e.g. data, improve, 'strategy (owner mission)', skills")
    a.add_argument("--who", default="Claude")
    a.add_argument("--changed-file", required=True, help="a file holding the 'What changed' cell (one line, no pipes)")
    a.add_argument("--next-file", required=True, help="a file holding the 'Next suggestion' cell (one line, no pipes)")
    a.add_argument("--when", default=None, help="UTC time like 2026-11-19 00:47 (default: now)")
    a.add_argument("--label", default=None, help="what the archive line calls this cycle (default: '00 UTC improve job' from the time and the job)")
    a.add_argument("--keep", type=int, default=KEEP)
    a.add_argument("--dry-run", action="store_true")
    sub.add_parser("check")
    ns = p.parse_args(argv)
    root = Path(ns.root)
    try:
        handoff = (root / "HANDOFF.md").read_text(encoding="utf-8")
        archive = (root / "HANDOFF_ARCHIVE.md").read_text(encoding="utf-8")
        if ns.cmd == "check":
            found = problems(handoff, archive)
            print("\n".join(found) if found else "board and archive are fine")
            return 1 if found else 0
        when = ns.when or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        changed = (Path(ns.changed_file)).read_text(encoding="utf-8").strip()
        nxt = (Path(ns.next_file)).read_text(encoding="utf-8").strip()
        row = make_row(when, ns.who, ns.job, changed, nxt)
        label = ns.label or f"{when[11:13]} UTC {ns.job.split()[0]} job"
        new_h, new_a, moved = add(handoff, archive, row, label, ns.keep)
    except (BoardError, OSError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    stamps = ", ".join(ROW.match(m).group(1) for m in moved) or "none"
    print(f"row of {len(row)} characters for {when}; moved to the archive: {stamps}" + (" (dry run: nothing written)" if ns.dry_run else ""))
    if not ns.dry_run:
        (root / "HANDOFF.md").write_text(new_h, encoding="utf-8")
        (root / "HANDOFF_ARCHIVE.md").write_text(new_a, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
