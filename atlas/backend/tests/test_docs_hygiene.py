"""The hand-off board is read at the start of every cycle by every contributor, so its size and shape are part of the process (found 2026-11-17: HANDOFF.md had grown to 90 KB and 157 board rows although its own heading said to keep 20; the 15 UTC skills job moved 138 rows to HANDOFF_ARCHIVE.md and nothing stopped it growing again)."""
import re
from pathlib import Path

ATLAS = Path(__file__).resolve().parents[2]
HANDOFF = ATLAS / "HANDOFF.md"
ARCHIVE = ATLAS / "HANDOFF_ARCHIVE.md"
MAX_ROWS = 25                 # the rule on the board is 20: five rows of slack, so one forgotten move does not stop the next cycle
MAX_BYTES = 60_000            # the rule is about 40 KB
STAMP = re.compile(r"\| (\d{4}-\d\d-\d\d \d\d:\d\d) \|")


def board_rows(text: str) -> list[str]:
    """The table rows under the STATE BOARD heading, up to the next heading."""
    lines = text.split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("## STATE BOARD"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [l for l in lines[start:end] if l.startswith("| 20")]


def board_problems(text: str, size: int | None = None) -> list[str]:
    rows = board_rows(text)
    size = len(text.encode("utf-8")) if size is None else size
    problems = []
    if len(rows) > MAX_ROWS:
        problems.append(f"the board has {len(rows)} rows, more than {MAX_ROWS}: move the oldest to HANDOFF_ARCHIVE.md, unchanged")
    if size > MAX_BYTES:
        problems.append(f"HANDOFF.md is {size:,} bytes, more than {MAX_BYTES:,}")
    stamps = []
    for r in rows:
        if r.count("|") != 6:
            problems.append(f"a row has {r.count('|') - 1} columns, not 5 (a pipe inside a cell breaks the table): {r[:50]}")
        m = STAMP.match(r)
        if m:
            stamps.append(m.group(1))
        else:
            problems.append(f"a row does not start with a stamp like 2026-11-17 18:02: {r[:40]}")
    if any(a < b for a, b in zip(stamps, stamps[1:])):
        problems.append("the board is not newest first")
    return problems


def archive_problems(archive_text: str, board_text: str) -> list[str]:
    archive = [l for l in archive_text.split("\n") if l.startswith("| 20")]
    problems = []
    if any(r.count("|") != 6 for r in archive):
        problems.append("an archive row does not have 5 columns")
    if len(set(archive)) != len(archive):
        problems.append("a row is in the archive twice")
    if set(archive) & set(board_rows(board_text)):
        problems.append("a row is both on the board and in the archive")
    return problems


def _board(n: int = 3, bad: dict | None = None) -> str:
    """A small hand-off file with `n` rows, newest first (days 28 down), and a later section whose table rows must not be counted."""
    rows = [f"| 2026-11-{28 - i:02d} 10:00 | Claude | job {i} | what changed {i} | next {i} |" for i in range(n)]
    for pos, text in (bad or {}).items():
        rows[pos] = text
    return "\n".join(["# Shared handoff", "", "## Shifts", "| Who | Hours |", "| 2026-01-01 not a board row |", "", "## STATE BOARD (newest first)", "| When (UTC) | Who | Job | What changed | Next suggestion |", "| --- | --- | --- | --- | --- |", *rows,
                      "", "Older rows: HANDOFF_ARCHIVE.md", "", "## Open items", "| 2026-11-01 10:00 | Claude | not | a | board row |", ""])


def test_the_real_board_is_within_its_budget():
    text = HANDOFF.read_text(encoding="utf-8")
    assert board_problems(text) == []
    assert 1 <= len(board_rows(text)) <= MAX_ROWS


def test_the_checker_counts_only_the_rows_of_the_board():
    assert len(board_rows(_board(3))) == 3                                                                    # not the shift table above it, not the table below it
    assert board_problems(_board(25)) == [] and len(board_rows(_board(25))) == 25


def test_the_checker_notices_a_board_that_is_too_long():
    assert board_problems(_board(26)) == ["the board has 26 rows, more than 25: move the oldest to HANDOFF_ARCHIVE.md, unchanged"]


def test_the_checker_notices_a_file_that_is_too_big():
    assert board_problems(_board(3), size=60_000) == []
    assert board_problems(_board(3), size=60_001) == ["HANDOFF.md is 60,001 bytes, more than 60,000"]
    big = _board(3).replace("what changed 0", "x" * 61_000)
    assert any("bytes, more than 60,000" in p for p in board_problems(big))                                   # measured from the text when no size is given
    wide = _board(3).replace("what changed 0", "\u00e9" * 30_000)                                             # 30,000 two-byte letters: 60,000 bytes plus the rest of the file, but far fewer characters
    assert any("bytes, more than 60,000" in p for p in board_problems(wide))


def test_the_checker_notices_a_row_that_breaks_the_table():
    extra = "| 2026-11-27 10:00 | Claude | job | a | b | c |"
    assert board_problems(_board(3, {1: extra})) == [f"a row has 6 columns, not 5 (a pipe inside a cell breaks the table): {extra[:50]}"]
    short = "| 2026-11-27 10:00 | Claude | job | only four |"
    assert board_problems(_board(3, {1: short})) == [f"a row has 4 columns, not 5 (a pipe inside a cell breaks the table): {short[:50]}"]


def test_the_checker_notices_a_row_without_a_stamp_or_out_of_order():
    undated = "| 2026-11-27 | Claude | job | a | b |"
    assert board_problems(_board(3, {1: undated})) == [f"a row does not start with a stamp like 2026-11-17 18:02: {undated[:40]}"]
    swapped = _board(3, {0: "| 2026-11-20 10:00 | Claude | job | a | b |"})                                    # the newest row is older than the second
    assert board_problems(swapped) == ["the board is not newest first"]
    assert board_problems(_board(3, {1: "| 2026-11-28 10:00 | Claude | job | a | b |"})) == []                      # equal stamps are fine


def test_the_real_archive_is_a_clean_table_and_shares_no_row_with_the_board():
    archive_text, board_text = ARCHIVE.read_text(encoding="utf-8"), HANDOFF.read_text(encoding="utf-8")
    assert len([l for l in archive_text.split("\n") if l.startswith("| 20")]) >= 138
    assert archive_problems(archive_text, board_text) == []


def test_the_archive_checker_notices_a_repeated_row_a_shared_row_and_a_broken_row():
    board = _board(3)
    row = "| 2026-11-10 10:00 | Claude | job | old | next |"
    assert archive_problems(f"| --- |\n{row}\n", board) == []
    assert archive_problems(f"{row}\n{row}\n", board) == ["a row is in the archive twice"]
    assert archive_problems("| 2026-11-28 10:00 | Claude | job 0 | what changed 0 | next 0 |\n", board) == ["a row is both on the board and in the archive"]
    assert archive_problems("| 2026-11-10 10:00 | Claude | job | old |\n", board) == ["an archive row does not have 5 columns"]


def test_the_board_points_to_the_archive_and_the_archive_is_a_table():
    assert "HANDOFF_ARCHIVE.md" in HANDOFF.read_text(encoding="utf-8")
    head = ARCHIVE.read_text(encoding="utf-8").split("\n")
    assert any(l.startswith("| When (UTC) | Who | Job | What changed | Next suggestion |") for l in head) and any(l.startswith("| --- ") for l in head)
