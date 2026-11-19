"""The board chore as a tool (`devtools/board.py`): a row on top of the STATE BOARD, the oldest rows moved unchanged to the archive with one "Moved on" line, nothing else touched, and a refusal, with the reason, for anything that would leave the files in a form the hygiene test (`backend/tests/test_docs_hygiene.py`) would not accept. It replaces a scratch script that was written again every hour (thirteen times in a row, 2026-11-18)."""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

import board as B

ATLAS = Path(__file__).resolve().parents[2]
HEAD = "| When (UTC) | Who | Job | What changed | Next suggestion |"
SEP = "| --- | --- | --- | --- | --- |"
NEW = "| 2026-11-19 00:47 | Claude | improve | the new row | next time |"


def stamp(i: int) -> str:
    return f"2026-11-{18 - i // 24:02d} {23 - i % 24:02d}:00"                      # newest first: i = 0 is the newest


def handoff(n: int = 20) -> str:
    rows = [f"| {stamp(i)} | Claude | job {i} | what changed {i} | next {i} |" for i in range(n)]
    return "\n".join(["# Shared handoff", "", "## Shifts", "| Who | Hours |", "| 2026-01-01 not a board row |", "", "## STATE BOARD (newest first)", HEAD, SEP, *rows, "", "Older rows: HANDOFF_ARCHIVE.md", "",
                      "## Open items", "| 2026-11-01 10:00 | Claude | not | a | board row |", ""])


def archive(n: int = 3) -> str:
    notes = [f"Moved on 2026-11-18 (old job {i}): 1 row, 2026-11-10 0{9 - i}:00." for i in range(2)]
    rows = [f"| 2026-11-10 0{9 - i}:00 | Claude | old {i} | moved {i} | next |" for i in range(n)]
    return "\n".join(["# Hand-off board archive", "", "History only.", "", *notes, "", HEAD, SEP, *rows, ""])


def board_of(text: str) -> list[str]:
    lines = text.split("\n")
    a, b = B.span(lines)
    return lines[a:b + 1]


def refused(fn, text):
    with pytest.raises(B.BoardError) as e:
        fn()
    assert str(e.value) == text


# ---------------------------------------------------------------- the row

def test_a_row_is_its_five_cells_between_pipes():
    assert B.make_row("2026-11-19 00:47", "Claude", "improve", "what changed", "what next") == "| 2026-11-19 00:47 | Claude | improve | what changed | what next |"
    assert B.make_row("2026-11-19 00:47", " Claude ", " improve ", "  what changed  ", " what next\n") == "| 2026-11-19 00:47 | Claude | improve | what changed | what next |"


@pytest.mark.parametrize("when", ["2026-11-19", "2026-11-19 0:47", "19 Nov 2026 00:47", "2026-11-19T00:47", "2026-11-19 00:47:00", "", "2026-1-19 00:47", "26-11-19 00:47", "202-11-19 00:47"])
def test_a_time_that_is_not_a_stamp_is_refused(when):
    refused(lambda: B.make_row(when, "Claude", "improve", "c", "n"), f"the time {when!r} is not like 2026-11-19 00:47")


@pytest.mark.parametrize("cell", ["who", "job", "what changed", "next suggestion"])
def test_an_empty_cell_a_pipe_or_a_line_break_is_refused_and_the_cell_is_named(cell):
    cells = {"who": "Claude", "job": "improve", "what changed": "c", "next suggestion": "n"}

    def make(value):
        return B.make_row("2026-11-19 00:47", *[value if k == cell else v for k, v in cells.items()])

    refused(lambda: make("   "), f"the {cell} cell is empty")
    refused(lambda: make(""), f"the {cell} cell is empty")
    refused(lambda: make("a | b"), f"the {cell} cell has a pipe, which would split the table")
    refused(lambda: make("two\nlines"), f"the {cell} cell has a line break")
    refused(lambda: make("two\rlines"), f"the {cell} cell has a line break")


# ---------------------------------------------------------------- the move

def test_the_row_goes_on_top_and_the_oldest_row_moves_to_the_top_of_the_archive():
    h, a = handoff(20), archive(3)
    new_h, new_a, moved = B.add(h, a, NEW, "00 UTC improve job")
    old_rows, rows = board_of(h), board_of(new_h)
    assert len(rows) == 20 and rows[0] == NEW and rows[1:] == old_rows[:19] and moved == [old_rows[19]]
    hl, nl = h.split("\n"), new_h.split("\n")
    first, last = B.span(hl)
    assert nl[:first] == hl[:first] and nl[last + 1:] == hl[last + 1:]                          # the Shifts table above, the Open items table below and every other line: untouched
    al, nal = a.split("\n"), new_a.split("\n")
    note_at, head_at = next(i for i, l in enumerate(al) if l.startswith("Moved on ")), next(i for i, l in enumerate(al) if l.startswith("| When"))
    assert nal[note_at] == f"Moved on 2026-11-19 (00 UTC improve job): 1 row, {stamp(19)}." and nal[note_at + 1:note_at + 3] == al[note_at:note_at + 2]     # above the earlier notes
    assert nal[head_at + 1:head_at + 3] == al[head_at:head_at + 2] and nal[head_at + 3] == old_rows[19] and nal[head_at + 4:] == al[head_at + 2:]       # directly under the header, above the old rows


def test_a_board_that_is_too_long_loses_the_extra_rows_in_one_move_newest_of_them_first():
    h, a = handoff(22), archive(2)
    new_h, new_a, moved = B.add(h, a, NEW, "03 UTC skills job")
    old_rows = board_of(h)
    assert len(board_of(new_h)) == 20 and moved == old_rows[19:] and len(moved) == 3
    assert f"Moved on 2026-11-19 (03 UTC skills job): 3 rows, from {stamp(19)} back to {stamp(21)}." in new_a
    nal = new_a.split("\n")
    head_at = next(i for i, l in enumerate(nal) if l.startswith("| When"))
    assert nal[head_at + 2:head_at + 5] == old_rows[19:] and nal[head_at + 5].startswith("| 2026-11-10 09:00")


def test_a_board_with_room_takes_the_row_and_moves_nothing():
    h, a = handoff(5), archive(3)
    new_h, new_a, moved = B.add(h, a, NEW, "label")
    assert board_of(new_h) == [NEW] + board_of(h) and moved == [] and new_a == a


def test_the_number_of_rows_kept_can_be_changed():
    new_h, new_a, moved = B.add(handoff(8), archive(1), NEW, "label", keep=5)
    assert len(board_of(new_h)) == 5 and len(moved) == 4 and "4 rows, from" in new_a
    refused(lambda: B.add(handoff(8), archive(1), NEW, "label", keep=0), "--keep must be at least 1")
    new_h, new_a, moved = B.add(handoff(3), archive(1), NEW, "label", keep=1)
    assert board_of(new_h) == [NEW] and len(moved) == 3


def test_a_row_made_in_the_same_minute_as_the_newest_is_accepted_and_an_older_one_is_not():
    same = f"| {stamp(0)} | Claude | improve | same minute | n |"
    assert board_of(B.add(handoff(20), archive(), same, "x")[0])[0] == same
    older = "| 2026-11-01 00:00 | Claude | improve | too old | n |"
    refused(lambda: B.add(handoff(20), archive(), older, "x"), f"the new row (2026-11-01 00:00) is older than the newest row on the board ({stamp(0)})")
    between = "| 2026-11-18 12:00 | Claude | improve | between the oldest and the newest | n |"
    refused(lambda: B.add(handoff(20), archive(), between, "x"), f"the new row (2026-11-18 12:00) is older than the newest row on the board ({stamp(0)})")


def test_the_same_row_twice_is_refused():
    h = handoff(20)
    refused(lambda: B.add(h, archive(), board_of(h)[0], "x"), "this row is already on the board")


def test_a_board_row_in_the_wrong_form_stops_the_chore_before_anything_changes():
    bad = handoff(20).replace("what changed 3 | next 3", "what changed 3 | extra | next 3")
    refused(lambda: B.add(bad, archive(), NEW, "x"), "a row on the board is not in the five-column form: run `check`")
    bad = handoff(20).replace("| 2026-11-18 20:00 ", "| 2026-11-18 ", 1)                                              # a date without a time is not a stamp
    refused(lambda: B.add(bad, archive(), NEW, "x"), "a row on the board is not in the five-column form: run `check`")
    bad = handoff(20).replace("| 2026-11-18 20:00 ", "| 18 Nov 20:00 ", 1)                                            # a row that does not even start with a year is not a board row: it breaks the block
    refused(lambda: B.add(bad, archive(), NEW, "x"), "the rows of the STATE BOARD are not one block")


def test_a_row_that_is_both_on_the_board_and_in_the_archive_stops_the_chore():
    h = handoff(21)
    a = archive(1).replace("| 2026-11-10 09:00 | Claude | old 0 | moved 0 | next |", board_of(h)[0])
    refused(lambda: B.add(h, a, NEW, "x"), "the result would not pass the checks: a row is both on the board and in the archive")


@pytest.mark.parametrize("text,message", [
    (lambda h: h.replace("## STATE BOARD (newest first)", "## Board"), "HANDOFF.md has no line starting with '## STATE BOARD'"),
    (lambda h: "\n".join(l for l in h.split("\n") if not l.startswith("| 2026-11-18 ")), "the STATE BOARD has no rows"),
    (lambda h: h.replace("| 2026-11-18 22:00 |", "\n| 2026-11-18 22:00 |", 1), "the rows of the STATE BOARD are not one block"),
])
def test_a_hand_off_file_without_a_usable_board_is_refused(text, message):
    refused(lambda: B.add(text(handoff(20)), archive(), NEW, "x"), message)


@pytest.mark.parametrize("a,message", [
    (lambda t: t.replace(HEAD, "| the header |"), "HANDOFF_ARCHIVE.md has no table header ('| When (UTC)' and a '| --- ' line under it)"),
    (lambda t: t.replace(SEP, "| rows |"), "HANDOFF_ARCHIVE.md has no table header ('| When (UTC)' and a '| --- ' line under it)"),
    (lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("Moved on")), "HANDOFF_ARCHIVE.md has no 'Moved on ...' lines above its table"),
    (lambda t: "\n".join([*[l for l in t.split("\n") if not l.startswith("Moved on")], "Moved on 2026-11-10 (late): 1 row, x."]), "HANDOFF_ARCHIVE.md has no 'Moved on ...' lines above its table"),
])
def test_an_archive_without_its_header_or_its_notes_is_refused_when_rows_must_move(a, message):
    refused(lambda: B.add(handoff(20), a(archive()), NEW, "x"), message)


def test_a_board_that_is_the_last_section_of_the_file_is_found_too():
    last = "\n".join(l for l in handoff(20).split("\n")[:-4])                                  # the file ends with the board's table: no heading follows it
    assert "## Open items" not in last and len(board_of(last)) == 20
    new_h, new_a, moved = B.add(last, archive(), NEW, "x")
    assert board_of(new_h)[0] == NEW and len(board_of(new_h)) == 20 and len(moved) == 1


def test_an_archive_is_not_needed_when_nothing_moves():
    assert B.add(handoff(3), "", NEW, "x")[2] == []


# ---------------------------------------------------------------- the checks

def test_the_checks_are_quiet_on_a_good_pair_and_name_each_fault():
    assert B.problems(handoff(20), archive()) == []
    assert B.problems(handoff(21), archive()) == ["the board has 21 rows, more than 20"] and B.problems(handoff(21), archive(), keep=25) == []
    wide = "| 2026-11-18 22:00 | Claude | job 1 | what changed 1 | next 1 | extra |"
    assert B.problems(handoff(3).replace("next 1 |", "next 1 | extra |"), archive()) == [f"a board row has 6 columns, not 5: {wide[:50]}"]
    nostamp = "| 2026-11-18 | Claude | job 1 | what changed 1 | next 1 |"
    assert B.problems(handoff(3).replace("| 2026-11-18 22:00 |", "| 2026-11-18 |"), archive()) == [f"a board row does not start with a stamp like 2026-11-17 18:02: {nostamp[:40]}"]
    rows = board_of(handoff(3))
    swapped = handoff(3).replace(rows[0], "@@").replace(rows[1], rows[0]).replace("@@", rows[1])
    assert B.problems(swapped, archive()) == ["the board is not newest first"]
    assert B.problems(handoff(3), archive().replace("| Claude | old 1 |", "| Claude | old 1 | extra |")) == ["an archive row does not have 5 columns"]
    doubled = archive() + "\n" + archive(1).split("\n")[-2]
    assert B.problems(handoff(3), doubled) == ["a row is in the archive twice"]
    assert B.problems(handoff(3), archive(1).replace("| 2026-11-10 09:00 | Claude | old 0 | moved 0 | next |", board_of(handoff(3))[0])) == ["a row is both on the board and in the archive"]
    assert B.problems("no board here", archive()) == ["HANDOFF.md has no line starting with '## STATE BOARD'"]


def test_the_real_board_and_archive_are_in_the_form_the_tool_expects():
    h, a = (ATLAS / "HANDOFF.md").read_text(encoding="utf-8"), (ATLAS / "HANDOFF_ARCHIVE.md").read_text(encoding="utf-8")
    assert [p for p in B.problems(h, a) if not p.startswith("the board has")] == []          # the count is the hygiene test's business (25 at most); a cycle that has just added a row may stand at 21 for a moment
    assert 1 <= len(board_of(h)) <= 25
    first_note = next(i for i, l in enumerate(a.split("\n")) if l.startswith("Moved on "))
    head = next(i for i, l in enumerate(a.split("\n")) if l.startswith("| When (UTC)"))
    assert first_note < head and a.split("\n")[head + 1].startswith("| --- ")


# ---------------------------------------------------------------- the command line

def files(tmp_path, h=None, a=None, changed="the new row", nxt="next time"):
    (tmp_path / "HANDOFF.md").write_text(h or handoff(20), encoding="utf-8")
    (tmp_path / "HANDOFF_ARCHIVE.md").write_text(a or archive(3), encoding="utf-8")
    (tmp_path / "changed.txt").write_text(changed + "\n", encoding="utf-8")
    (tmp_path / "next.txt").write_text(nxt + "\n", encoding="utf-8")
    return ["--root", str(tmp_path), "add", "--job", "improve", "--changed-file", str(tmp_path / "changed.txt"), "--next-file", str(tmp_path / "next.txt"), "--when", "2026-11-19 00:47"]


def test_the_command_adds_the_row_writes_both_files_and_says_what_it_moved(tmp_path, capsys):
    argv = files(tmp_path)
    assert B.main(argv) == 0
    assert capsys.readouterr().out == f"row of {len(NEW)} characters for 2026-11-19 00:47; moved to the archive: {stamp(19)}\n"
    h, a = (tmp_path / "HANDOFF.md").read_text(encoding="utf-8"), (tmp_path / "HANDOFF_ARCHIVE.md").read_text(encoding="utf-8")
    assert board_of(h)[0] == NEW and len(board_of(h)) == 20 and f"Moved on 2026-11-19 (00 UTC improve job): 1 row, {stamp(19)}." in a
    assert B.main(["--root", str(tmp_path), "check"]) == 0 and capsys.readouterr().out == "board and archive are fine\n"


def test_a_dry_run_writes_nothing(tmp_path, capsys):
    argv = files(tmp_path)
    before = [(tmp_path / n).read_bytes() for n in ("HANDOFF.md", "HANDOFF_ARCHIVE.md")]
    assert B.main([*argv, "--dry-run"]) == 0
    assert capsys.readouterr().out.endswith("(dry run: nothing written)\n")
    assert [(tmp_path / n).read_bytes() for n in ("HANDOFF.md", "HANDOFF_ARCHIVE.md")] == before


def test_the_default_label_comes_from_the_hour_and_the_first_word_of_the_job(tmp_path, capsys):
    argv = files(tmp_path)
    argv[argv.index("improve")] = "strategy (owner mission)"
    argv[argv.index("2026-11-19 00:47")] = "2026-11-19 22:09"
    assert B.main(argv) == 0
    assert f"Moved on 2026-11-19 (22 UTC strategy job): 1 row, {stamp(19)}." in (tmp_path / "HANDOFF_ARCHIVE.md").read_text(encoding="utf-8")
    assert "| strategy (owner mission) |" in (tmp_path / "HANDOFF.md").read_text(encoding="utf-8")


def test_a_label_can_be_given(tmp_path):
    assert B.main([*files(tmp_path), "--label", "my own label"]) == 0
    assert f"Moved on 2026-11-19 (my own label): 1 row, {stamp(19)}." in (tmp_path / "HANDOFF_ARCHIVE.md").read_text(encoding="utf-8")


def test_without_a_time_the_row_is_stamped_with_the_present_minute_in_utc(tmp_path, monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is not None and tz.utcoffset(None).total_seconds() == 0
            return datetime(2026, 11, 20, 3, 7, tzinfo=tz)

    monkeypatch.setattr(B, "datetime", Fixed)
    argv = files(tmp_path)
    del argv[argv.index("--when"):argv.index("--when") + 2]
    assert B.main(argv) == 0
    assert board_of((tmp_path / "HANDOFF.md").read_text(encoding="utf-8"))[0].startswith("| 2026-11-20 03:07 | Claude | improve |")


def test_a_refusal_says_why_exits_1_and_changes_nothing(tmp_path, capsys):
    argv = files(tmp_path, changed="has | a pipe")
    before = [(tmp_path / n).read_bytes() for n in ("HANDOFF.md", "HANDOFF_ARCHIVE.md")]
    assert B.main(argv) == 1
    assert capsys.readouterr().err == "refused: the what changed cell has a pipe, which would split the table\n"
    assert [(tmp_path / n).read_bytes() for n in ("HANDOFF.md", "HANDOFF_ARCHIVE.md")] == before
    argv = files(tmp_path, nxt="")
    assert B.main(argv) == 1 and capsys.readouterr().err == "refused: the next suggestion cell is empty\n"


def test_a_missing_file_is_a_refusal_not_a_crash(tmp_path, capsys):
    argv = files(tmp_path)
    (tmp_path / "changed.txt").unlink()
    assert B.main(argv) == 1
    err = capsys.readouterr().err
    assert err.startswith("refused: ") and "changed.txt" in err
    (tmp_path / "HANDOFF.md").unlink()
    assert B.main(["--root", str(tmp_path), "check"]) == 1


def test_check_reports_each_problem_and_exits_1(tmp_path, capsys):
    files(tmp_path, h=handoff(22))
    assert B.main(["--root", str(tmp_path), "check"]) == 1
    assert capsys.readouterr().out == "the board has 22 rows, more than 20\n"


def test_missing_options_are_a_usage_error():
    with pytest.raises(SystemExit) as e:
        B.main(["add", "--job", "improve"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        B.main([])
    assert e.value.code == 2


def test_it_runs_as_a_script(tmp_path):
    argv = files(tmp_path)
    run = subprocess.run([sys.executable, str(ATLAS / "devtools" / "board.py"), *argv], capture_output=True, text=True)
    assert run.returncode == 0 and run.stdout.startswith("row of ") and board_of((tmp_path / "HANDOFF.md").read_text(encoding="utf-8"))[0] == NEW
    run = subprocess.run([sys.executable, str(ATLAS / "devtools" / "board.py"), "--root", str(tmp_path), "check"], capture_output=True, text=True)
    assert run.returncode == 0 and run.stdout == "board and archive are fine\n"


# ---------------------------------------------------------------- more edges found by the breakage run

def test_a_first_cell_that_is_more_than_a_stamp_is_not_a_stamp():
    row = "| 2026-11-18 22:00 Claude | job 1 | what changed 1 | next 1 | x |"                  # five cells, but the first is a stamp followed by text
    bad = handoff(3).replace(board_of(handoff(3))[1], row)
    assert B.problems(bad, archive()) == [f"a board row does not start with a stamp like 2026-11-17 18:02: {row[:40]}"]


def test_rows_of_a_later_year_are_still_rows():
    later = handoff(20).replace("| 2026-11-", "| 2027-11-")
    assert len(board_of(later)) == 20
    old = archive(2).replace("| 2026-11-10", "| 2027-11-10")
    twice = old + "\n" + [l for l in old.split("\n") if l.startswith("| 2027")][0]
    assert B.problems(later, twice) == ["a row is in the archive twice"]


def test_a_sub_heading_inside_the_board_section_does_not_end_it():
    text = handoff(20).replace("## STATE BOARD (newest first)\n", "## STATE BOARD (newest first)\n### a note about the table\n")
    assert len(board_of(text)) == 20


def test_a_heading_that_only_starts_like_the_board_heading_is_not_the_board():
    text = handoff(20).replace("## Shifts", "## STATE OF PLAY\n\n## Shifts")
    assert len(board_of(text)) == 20 and B.add(text, archive(), NEW, "x")[2] != []


def test_an_empty_board_is_refused_even_when_the_next_section_has_dated_rows():
    text = "\n".join(["# x", "## STATE BOARD", "## Open items", "| 2026-11-01 10:00 | Claude | not | a | board row |", ""])
    refused(lambda: B.span(text.split("\n")), "the STATE BOARD has no rows")


def test_an_archive_that_ends_with_its_header_is_refused_in_words():
    cut = archive().split(HEAD)[0] + HEAD
    refused(lambda: B.add(handoff(20), cut, NEW, "x"), "HANDOFF_ARCHIVE.md has no table header ('| When (UTC)' and a '| --- ' line under it)")


def test_the_note_goes_above_the_first_moved_on_line_and_not_above_other_text_that_starts_with_moved():
    text = archive().replace("History only.", "Moved rows are listed below.")
    lines = B.add(handoff(20), text, NEW, "x")[1].split("\n")
    assert lines[2] == "Moved rows are listed below." and lines[4].startswith("Moved on 2026-11-19 (x): 1 row,")


def test_two_moved_rows_are_counted_and_spanned_like_many():
    new_h, new_a, moved = B.add(handoff(21), archive(), NEW, "x")
    assert len(moved) == 2 and f"Moved on 2026-11-19 (x): 2 rows, from {stamp(19)} back to {stamp(20)}." in new_a


def test_a_larger_keep_is_used_for_the_check_of_the_result_too():
    new_h, new_a, moved = B.add(handoff(24), archive(), NEW, "x", keep=25)
    assert len(board_of(new_h)) == 25 and moved == []


def test_two_problems_in_the_result_are_both_named_in_one_refusal():
    h = handoff(20)
    dup = board_of(h)[3]
    refused(lambda: B.add(h, archive(1) + "\n" + dup + "\n" + dup, NEW, "x"),
            "the result would not pass the checks: a row is in the archive twice; a row is both on the board and in the archive")


def test_the_default_folder_is_the_atlas_folder(tmp_path, monkeypatch, capsys):
    files(tmp_path)
    monkeypatch.setattr(B, "ATLAS", tmp_path)
    assert B.main(["check"]) == 0 and capsys.readouterr().out == "board and archive are fine\n"


def test_the_options_who_and_keep_reach_the_row_and_the_move(tmp_path, capsys):
    argv = files(tmp_path, h=handoff(8))
    assert B.main([*argv, "--who", "ChatGPT", "--keep", "5"]) == 0
    out = capsys.readouterr().out
    h = (tmp_path / "HANDOFF.md").read_text(encoding="utf-8")
    assert board_of(h)[0] == "| 2026-11-19 00:47 | ChatGPT | improve | the new row | next time |" and len(board_of(h)) == 5
    assert out.count(",") == 3 and out.startswith("row of ")                                                      # four rows moved: four stamps, three commas


def test_a_move_of_nothing_says_none(tmp_path, capsys):
    argv = files(tmp_path, h=handoff(3))
    assert B.main(argv) == 0 and capsys.readouterr().out == f"row of {len(NEW)} characters for 2026-11-19 00:47; moved to the archive: none\n"
