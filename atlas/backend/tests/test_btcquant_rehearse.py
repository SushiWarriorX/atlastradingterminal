"""The daily-run rehearsal as a tool (`atlas_api/btcquant/rehearse.py`): the stand-in candle (the day's own forming candle, 20% lower, 20% higher or any move), the time of the run it rehearses, a run of `daily.run_daily` on a throwaway copy, a repeat run that may change only the dashboard's run-activity counters, and a hash of the repository's folder before and after. Most tests put a small fake in the place of `run_daily` on a made-up folder (fast, and every finding is one the fake can be told to produce); two run the real thing on the real folder. It replaces a script that was written by hand four times on 2026-11-18."""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_api.btcquant import config as C
from atlas_api.btcquant import data as D
from atlas_api.btcquant import rehearse as R

DAY = 86400
NEWEST = 1794960000                                        # 2026-11-18 00:00 UTC, the open of the newest stored candle in these tests
STAND_IN_DAY = NEWEST + DAY                                # 2026-11-19
RUN = STAND_IN_DAY + DAY + 15 * 60                         # 2026-11-20 00:15 UTC: the run that would add it
CANDLE = (NEWEST, 100.0, 101.0, 99.0, 100.0, 10.0)         # open 100, close 100: a stand-in opens at the previous CLOSE


def make_root(tmp_path, n=3, accounts=("a", "b")):
    root = tmp_path / "btcquant"
    (root / "data").mkdir(parents=True)
    (root / "state").mkdir()
    D.save(root / "data" / "btcusd_1d.csv", [(NEWEST - (n - 1 - i) * DAY, 100.0, 101.0, 99.0, 100.0, 10.0) for i in range(n)])
    dash = {"status": "fine", "protocol": "1.5", "frozen_check": [], "data": {"stale": False, "candles": 2880, "gaps": 2}, "opened_today": [],
            "accounts": [{"id": a, "days": 3, "equity": 10000.0, "halted": False, "stage": "monitor", "exposure": 0.0, "pending": None, "processed": 0} for a in accounts]}
    (root / "dashboard.json").write_text(json.dumps(dash))
    for a in accounts:
        (root / "state" / f"{a}.json").write_text(json.dumps({"days": 3, "last_t": NEWEST}))
    (root / "reports").mkdir()
    (root / "reports" / "2026-11-19.md").write_text("yesterday's report")                          # a file the copy must carry along
    return root


class Fake:
    """Stands in for `daily.run_daily` on the made-up folder: steps every account by one day per new candle (`steps` changes that), writes its state, a report and the dashboard, and on a repeat with the same candles changes nothing but the counters. The flags make it misbehave in one way each."""

    def __init__(self, **flags):
        self.flags, self.calls, self.seen = flags, 0, []

    def __call__(self, *, root, now, candles):
        self.calls += 1
        self.seen.append((Path(root), now, list(candles)))
        if self.calls == 1:
            self.files_seen = sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file())
        f = self.flags
        if f.get("raises") and self.calls == 1:
            raise RuntimeError("boom")
        if f.get("second_raises") and self.calls == 2:
            raise RuntimeError("again")
        dash = json.loads((root / "dashboard.json").read_text())
        for a in dash["accounts"]:
            sf = root / "state" / f"{a['id']}.json"
            if not sf.exists():                                                         # an account the run opened itself: it has no state in this made-up folder
                continue
            st = json.loads(sf.read_text())
            a["processed"] = 0
            if candles[-1][0] > st["last_t"]:
                st, a["processed"] = {"days": st["days"] + f.get("steps", 1), "last_t": candles[-1][0]}, 1
            if f.get("repeat_writes") and self.calls == 2:
                st["again"] = True
            sf.write_text(json.dumps(st))
            a["days"] = 3 if f.get("no_step") == a["id"] else st["days"]
            a["equity"] = 10000.0 - 10 * st["days"]
            a["halted"] = f.get("halt") == a["id"]
            a["pending"] = {"kind": "enter", "reason": "signal"} if a["id"] in f.get("order", ()) else None
            a["exposure"] = 0.5 if a["id"] in f.get("order", ()) else 0.0
            if f.get("no_exposure") == a["id"]:                                         # a dashboard row without the field
                del a["exposure"]
        if f.get("back"):                                                               # an account whose day count falls instead of rising
            for a in dash["accounts"]:
                if a["id"] == f["back"]:
                    a["days"] = 2
        if f.get("remove"):
            dash["accounts"] = [a for a in dash["accounts"] if a["id"] not in f["remove"]]
        if f.get("new_account") and not any(a["id"] == "c" for a in dash["accounts"]):
            dash["accounts"].append({"id": "c", "days": 1, "equity": 10000.0, "halted": False, "stage": "monitor", "exposure": 0.0, "pending": None, "processed": 1})
        dash["frozen_check"] = ["x"] if f.get("frozen") else []
        dash["data"]["stale"] = bool(f.get("stale"))
        dash["opened_today"] = list(f.get("opened", ()))
        for i in range(f.get("many_reports", 0)):                                         # files the run adds besides its report
            (root / "reports").mkdir(exist_ok=True)
            (root / "reports" / f"extra{i}.md").write_text("more")
        if f.get("repeat_dashboard") and self.calls == 2:
            dash["status"] = "changed on the repeat"
        (root / "dashboard.json").write_text(json.dumps(dash))
        (root / "reports").mkdir(exist_ok=True)
        (root / "reports" / (datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d") + ".md")).write_text("report")
        if self.calls == 2 and f.get("repeat_adds"):                                    # a file that only the second run writes
            (root / "state" / "extra.json").write_text("{}")
        if self.calls == 2 and f.get("repeat_removes"):                                 # a file that only the first run wrote
            (root / "reports" / (datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d") + ".md")).unlink()
        if self.calls == 2 and f.get("repeat_many"):
            for i in range(f["repeat_many"]):
                (root / "state" / f"f{i}.json").write_text("{}")
        if f.get("writes_repo"):
            for i in range(f.get("stray", 1)):
                (f["writes_repo"] / "state" / ("stray.json" if f.get("stray", 1) == 1 else f"stray{i}.json")).write_text("{}")
        return dash


def rehearse(tmp_path, kind="fall", move=None, fetch=None, accounts=("a", "b"), **flags):
    root = make_root(tmp_path, accounts=accounts)
    fake = Fake(**{k: (root if v == "ROOT" else v) for k, v in flags.items()})
    return R.rehearse(root, kind, move, fetch, run=fake), fake, root


# ---------------------------------------------------------------- the stand-in candle

def test_a_fall_and_a_rise_open_at_the_previous_close_and_move_it_by_20_percent():
    fall = R.stand_in(CANDLE, "fall")
    assert fall[0] == STAND_IN_DAY and fall[1] == 100.0 and fall[4] == pytest.approx(80.0, rel=1e-12) and fall[5] == 10.0
    assert fall[2] == pytest.approx(100.5, rel=1e-12) and fall[3] == pytest.approx(79.6, rel=1e-12)                          # high: half a percent above the open, low: half a percent below the close
    rise = R.stand_in(CANDLE, "rise")
    assert rise[0] == STAND_IN_DAY and rise[1] == 100.0 and rise[4] == pytest.approx(120.0, rel=1e-12) and rise[5] == 10.0
    assert rise[2] == pytest.approx(120.6, rel=1e-12) and rise[3] == pytest.approx(99.5, rel=1e-12)                          # high: half a percent above the close, low: half a percent below the open


def test_a_given_move_is_used_instead_of_the_kind_and_the_open_is_the_previous_close_not_the_previous_open():
    newest = (NEWEST, 90.0, 120.0, 80.0, 100.0, 7.0)
    c = R.stand_in(newest, "fall", -5.0)
    assert c[1] == 100.0 and c[4] == pytest.approx(95.0, rel=1e-12) and c[2] == pytest.approx(100.5, rel=1e-12) and c[3] == pytest.approx(94.525, rel=1e-12) and c[5] == 7.0
    up = R.stand_in(newest, "fall", 5.0)
    assert up[4] == pytest.approx(105.0, rel=1e-12) and up[2] == pytest.approx(105.525, rel=1e-12) and up[3] == pytest.approx(99.5, rel=1e-12)
    assert R.STRESS == {"fall": -20.0, "rise": 20.0} and R.EDGE == 0.005


def test_a_stand_in_is_always_a_possible_candle():
    for pct in (-20.0, -5.0, 0.0, 3.0, 20.0):
        t, o, h, l, c, v = R.stand_in(CANDLE, "fall", pct)
        assert l <= min(o, c) and h >= max(o, c)


def test_the_real_candle_is_the_one_the_day_gave_and_nothing_else_is_asked_for():
    calls = []
    real = [STAND_IN_DAY, 100.0, 103.0, 98.0, 99.0, 5.5]

    def fetch(interval, start, end):
        calls.append((interval, start, end))
        return [[NEWEST, 1, 1, 1, 1, 1], real]                                  # a neighbour that must be ignored

    got = R.stand_in(CANDLE, "real", None, fetch)
    assert got == real and got is not real and calls == [(DAY, STAND_IN_DAY, STAND_IN_DAY)]
    R.stand_in(CANDLE, "real", -5.0, fetch)                                      # a move wins over `real`: nothing is fetched
    assert len(calls) == 1


@pytest.mark.parametrize("rows", [[], [[NEWEST, 1, 1, 1, 1, 1]], [[STAND_IN_DAY, 1, 1, 1, 1, 1], [STAND_IN_DAY, 2, 2, 2, 2, 2]]])
def test_without_exactly_one_candle_of_that_day_the_real_stand_in_is_refused_in_words(rows):
    with pytest.raises(R.RehearsalError) as e:
        R.stand_in(CANDLE, "real", None, lambda *a: rows)
    assert str(e.value) == "Coinbase has no candle for 2026-11-19 yet (the day opens at 00:00 UTC): try --candle fall, --candle rise or --move PERCENT"


def test_a_failed_request_for_the_real_candle_is_refused_in_words():
    def fetch(*a):
        raise D.DataError("the candle provider could not be reached")

    with pytest.raises(R.RehearsalError) as e:
        R.stand_in(CANDLE, "real", None, fetch)
    assert str(e.value) == "Coinbase gave no candle (the candle provider could not be reached)" and isinstance(e.value.__cause__, D.DataError)      # the cause is kept


def test_an_error_that_is_not_a_data_error_is_not_dressed_up_as_a_missing_candle():
    def fetch(*a):
        raise RuntimeError("a bug")

    with pytest.raises(RuntimeError):
        R.stand_in(CANDLE, "real", None, fetch)


def test_a_move_of_zero_is_a_move_and_not_the_absence_of_one():
    flat = R.stand_in(CANDLE, "fall", 0.0)
    assert flat[1] == flat[4] == 100.0 and flat[2] == pytest.approx(100.5, rel=1e-12) and flat[3] == pytest.approx(99.5, rel=1e-12)
    never = lambda *a: pytest.fail("a move was given, so nothing is fetched")
    assert R.stand_in(CANDLE, "real", 0.0, never)[4] == 100.0


def test_the_run_it_rehearses_is_at_a_quarter_past_midnight_on_the_day_after_the_stand_in():
    assert R.run_time(STAND_IN_DAY) == RUN == 1795133700
    assert datetime.fromtimestamp(RUN, timezone.utc).strftime("%Y-%m-%d %H:%M") == "2026-11-20 00:15"


# ---------------------------------------------------------------- the pieces

def test_the_run_activity_counters_are_taken_out_at_every_depth_and_nothing_else():
    dash = {"processed": 1, "steps": {"a": {"events": 2, "kept": "processed"}}, "accounts": [{"id": "x", "processed": 1, "events": 0, "days": 4}], "events": [1, 2]}
    assert R.strip_activity(dash) == {"steps": {"a": {"kept": "processed"}}, "accounts": [{"id": "x", "days": 4}]}
    assert R.ACTIVITY == ("processed", "events") and R.strip_activity([1, "events", None]) == [1, "events", None]
    assert dash["processed"] == 1                                                # the original is not touched


def test_the_snapshot_notices_a_changed_an_added_and_a_removed_file_and_ignores_folders(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "a.txt").write_text("1")
    (tmp_path / "b.txt").write_text("2")
    (tmp_path / "empty").mkdir()
    s = R.snapshot(tmp_path)
    assert sorted(s) == ["b.txt", "x/a.txt"] and all(len(v) == 64 for v in s.values())
    (tmp_path / "b.txt").write_text("3")
    (tmp_path / "c.txt").write_text("4")
    (tmp_path / "x" / "a.txt").unlink()
    t = R.snapshot(tmp_path)
    assert sorted(t) == ["b.txt", "c.txt"] and t["b.txt"] != s["b.txt"]


# ---------------------------------------------------------------- the rehearsal with a fake run

def test_a_good_run_is_rehearsed_on_a_copy_twice_and_the_repository_is_left_as_it_was(tmp_path):
    root = make_root(tmp_path)
    before = R.snapshot(root)
    fake = Fake()
    r = R.rehearse(root, "fall", None, None, run=fake)
    assert r["problems"] == [] and r["repo_unchanged"] is True and r["repeat_ok"] is True and R.snapshot(root) == before
    assert fake.calls == 2
    assert fake.files_seen == sorted(before) and "reports/2026-11-19.md" in fake.files_seen and "data/btcusd_1d.csv" in fake.files_seen          # the copy carries every file
    (work1, now1, candles1), (work2, now2, candles2) = fake.seen
    assert work1 == work2 and work1 != root and work1.name == "btcquant" and not work1.exists()                              # a copy, the same one twice, gone afterwards
    assert now1 == now2 == RUN and candles1 == candles2 and len(candles1) == 4 and candles1[-1] == r["candle"] and candles1[:3] == D.load(root / "data" / "btcusd_1d.csv")
    assert r["candle"][0] == STAND_IN_DAY and r["previous_close"] == 100.0 and r["run_time"] == RUN
    assert [(a["id"], a["days_before"], a["days_after"], a["equity_before"], a["equity_after"], a["halted"]) for a in r["accounts"]] == [("a", 3, 4, 10000.0, 9960.0, False), ("b", 3, 4, 10000.0, 9960.0, False)]
    assert r["changed"] == ["dashboard.json", "state/a.json", "state/b.json"] and r["added"] == ["reports/2026-11-20.md"] and r["removed"] == [] and r["notes"] == []


def test_the_run_that_fails_is_the_finding_and_no_repeat_is_made(tmp_path):
    r, fake, _ = rehearse(tmp_path, raises=True)
    assert r["problems"] == ["the run failed: RuntimeError('boom')"] and fake.calls == 1 and r["accounts"] == [] and r["dashboard"] is None and r["repeat_ok"] is False


def test_a_repeat_run_that_fails_is_a_finding(tmp_path):
    r, fake, _ = rehearse(tmp_path, second_raises=True)
    assert r["problems"] == ["the repeat run failed: RuntimeError('again')"] and fake.calls == 2 and r["repeat_ok"] is False


@pytest.mark.parametrize("flags,problems", [
    ({"remove": ("b",)}, ["accounts missing after the run: b"]),
    ({"remove": ("a", "b")}, ["accounts missing after the run: a, b"]),
    ({"no_step": "a"}, ["a did not step (3 days before, 3 after)"]),
    ({"back": "a"}, ["a did not step (3 days before, 2 after)"]),
    ({"frozen": True}, ["the frozen check is not empty: ['x']"]),
    ({"stale": True}, ["the data would be stale"]),
    ({"repeat_writes": True}, ["a repeat run on the same input changed state/a.json, state/b.json"]),
    ({"repeat_adds": True}, ["a repeat run on the same input changed state/extra.json"]),                                    # a file only the repeat wrote
    ({"repeat_removes": True}, ["a repeat run on the same input changed reports/2026-11-20.md"]),                         # a file only the first run wrote
    ({"repeat_many": 7}, ["a repeat run on the same input changed state/f0.json, state/f1.json, state/f2.json, state/f3.json, state/f4.json"]),     # sorted, and no more than five named
    ({"repeat_dashboard": True}, ["a repeat run on the same input changed the dashboard beyond its run-activity counters"]),
])
def test_each_way_a_run_can_misbehave_is_found_and_named(tmp_path, flags, problems):
    r, fake, _ = rehearse(tmp_path, **flags)
    assert r["problems"] == problems
    assert r["repeat_ok"] is (not any(k.startswith("repeat_") for k in flags))                # the repeat is called identical only when it was


def test_a_run_that_writes_into_the_repository_instead_of_its_copy_is_caught(tmp_path):
    root = make_root(tmp_path)
    r = R.rehearse(root, "fall", None, None, run=Fake(writes_repo=root))
    assert r["problems"] == ["THE REPOSITORY'S btcquant FOLDER CHANGED during the rehearsal: state/stray.json"] and r["repo_unchanged"] is False


def test_a_run_that_writes_many_files_into_the_repository_names_the_first_five_in_order(tmp_path):
    root = make_root(tmp_path)
    r = R.rehearse(root, "fall", None, None, run=Fake(writes_repo=root, stray=7))
    assert r["problems"] == ["THE REPOSITORY'S btcquant FOLDER CHANGED during the rehearsal: state/stray0.json, state/stray1.json, state/stray2.json, state/stray3.json, state/stray4.json"]


def test_the_folder_may_be_given_as_text_and_a_move_and_a_fetch_reach_the_stand_in(tmp_path):
    root = make_root(tmp_path)
    r = R.rehearse(str(root), "fall", run=Fake())
    assert r["problems"] == [] and r["repo_unchanged"] is True and r["candle"][4] == pytest.approx(80.0, rel=1e-12)
    r, _, _ = rehearse(tmp_path / "x", kind="fall", move=-5.0)                                    # the move wins over the kind
    assert r["candle"][4] == pytest.approx(95.0, rel=1e-12)
    real = [STAND_IN_DAY, 100.0, 103.0, 98.0, 99.0, 5.5]
    r, _, _ = rehearse(tmp_path / "y", kind="real", fetch=lambda *a: [real])                      # the fetch is the one given
    assert r["candle"] == real and r["previous_close"] == 100.0


def test_an_account_that_catches_up_more_than_a_day_is_a_note_not_a_problem(tmp_path):
    r, _, _ = rehearse(tmp_path, steps=2)
    assert r["problems"] == [] and r["notes"] == ["a caught up 2 days", "b caught up 2 days"]


def test_an_account_that_is_new_has_no_before_and_is_no_problem(tmp_path):
    r, _, _ = rehearse(tmp_path, new_account=True)
    c = [a for a in r["accounts"] if a["id"] == "c"][0]
    assert r["problems"] == [] and c["days_before"] is None and c["equity_before"] is None and c["days_after"] == 1


def test_a_halted_account_and_a_waiting_order_are_carried_into_the_result(tmp_path):
    r, _, _ = rehearse(tmp_path, halt="a", order="b")
    assert [a["halted"] for a in r["accounts"]] == [True, False] and r["accounts"][1]["pending"] == {"kind": "enter", "reason": "signal"} and r["accounts"][1]["exposure"] == 0.5


@pytest.mark.parametrize("setup,message", [
    (lambda root: (root / "dashboard.json").unlink(), "the stored files could not be read ("),
    (lambda root: (root / "data" / "btcusd_1d.csv").unlink(), "the stored candle file holds no candle"),                  # a missing file reads as an empty one
    (lambda root: (root / "dashboard.json").write_text("{not json"), "the stored files could not be read ("),
    (lambda root: D.save(root / "data" / "btcusd_1d.csv", []), "the stored candle file holds no candle"),
])
def test_a_folder_that_cannot_be_read_is_refused_in_words(tmp_path, setup, message):
    root = make_root(tmp_path)
    setup(root)
    with pytest.raises(R.RehearsalError) as e:
        R.rehearse(root, "fall", run=Fake())
    assert str(e.value).startswith(message)


def test_a_stored_file_that_cannot_be_read_is_worded_by_fail_reason_and_the_cause_is_kept(tmp_path):
    root = make_root(tmp_path)
    (root / "dashboard.json").write_text("{not json")
    with pytest.raises(R.RehearsalError) as e:
        R.rehearse(root, "fall", run=Fake())
    assert str(e.value) == "the stored files could not be read (the answer was not valid JSON)" and isinstance(e.value.__cause__, ValueError)
    (root / "dashboard.json").unlink()
    with pytest.raises(R.RehearsalError) as e:
        R.rehearse(root, "fall", run=Fake())
    assert str(e.value).startswith("the stored files could not be read (an unexpected error, FileNotFoundError") and isinstance(e.value.__cause__, FileNotFoundError)


# ---------------------------------------------------------------- the words

def test_the_report_says_what_was_found_in_plain_lines(tmp_path):
    r, _, _ = rehearse(tmp_path, halt="a", order="b")
    lines = R.report(r)
    assert lines[0] == "Rehearsal of the next daily run on a throwaway copy (nothing in the repository is written)"
    assert lines[1].startswith("Stand-in for 2026-11-19: open 100.00, high 100.50, low 79.60, close 80.00, volume 10.0 (-20.00% on the previous close); it exercises the code path only")
    assert lines[2] == "Run time used: 2026-11-20 00:15 UTC"
    assert lines[3] == "Status: fine | protocol 1.5 | frozen check empty | data not stale, 2,880 candles, 2 gap(s)"
    assert lines[4:7] == ["Opened today: none", "Accounts: 2; halted by the circuit breaker: a", "Orders waiting for the next open: b: enter (signal)"]
    assert lines[7] == "  a                          monitor    days 3 -> 4  equity 10,000.00 -> 9,960.00    in Bitcoin 0.0%  HALTED"
    assert lines[8] == "  b                          monitor    days 3 -> 4  equity 10,000.00 -> 9,960.00    in Bitcoin 50.0%"
    assert lines[9:] == ["Files: 3 changed, 1 added, 0 removed (new: reports/2026-11-20.md)", "Repeat run on the same input: state, ledgers and reports identical; only the dashboard's run-activity counters differ",
                         "Repository: unchanged (every file hash equal before and after)", "Result: no problems"]


def test_the_report_names_a_new_account_a_note_a_stale_run_and_every_problem(tmp_path):
    r, _, _ = rehearse(tmp_path, new_account=True, steps=2, frozen=True, stale=True, repeat_writes=True)
    text = "\n".join(R.report(r))
    assert "  c                          monitor    days new     equity 10,000.00" in text and "Note: a caught up 2 days" in text and "frozen check ['x']" in text and "data STALE" in text
    assert "Repeat run on the same input: NOT identical (or not made)" in text and "Result: PROBLEMS" in text
    assert "  - the frozen check is not empty: ['x']" in text and "  - the data would be stale" in text and "  - a repeat run on the same input changed state/a.json, state/b.json" in text


def test_the_report_of_a_failed_run_has_no_accounts_and_says_so(tmp_path):
    r, _, _ = rehearse(tmp_path, raises=True)
    lines = R.report(r)
    assert lines[3:5] == ["Files: 0 changed, 0 added, 0 removed", "Repeat run on the same input: NOT identical (or not made)"] and lines[-1] == "  - the run failed: RuntimeError('boom')" and not any("Accounts:" in l for l in lines)


def test_the_report_says_none_when_nothing_is_halted_nothing_is_waiting_and_nothing_opened(tmp_path):
    r, _, _ = rehearse(tmp_path)
    lines = R.report(r)
    assert lines[4:7] == ["Opened today: none", "Accounts: 2; halted by the circuit breaker: none", "Orders waiting for the next open: none"]
    assert lines[7].endswith("in Bitcoin 0.0%") and "HALTED" not in "\n".join(lines)


def test_the_report_lists_every_opened_account_every_halted_account_and_every_waiting_order(tmp_path):
    r, _, _ = rehearse(tmp_path, order=("a", "b"), opened=("c", "d"), halt="b")
    lines = R.report(r)
    assert lines[4:7] == ["Opened today: c, d", "Accounts: 2; halted by the circuit breaker: b", "Orders waiting for the next open: a: enter (signal); b: enter (signal)"]


def test_the_report_writes_a_missing_share_in_bitcoin_as_zero(tmp_path):
    r, _, _ = rehearse(tmp_path, no_exposure="a")
    assert r["accounts"][0]["exposure"] is None and R.report(r)[7].endswith("in Bitcoin 0.0%")


def test_the_report_names_at_most_three_new_files_in_order(tmp_path):
    r, _, _ = rehearse(tmp_path, many_reports=5)
    assert r["added"] == ["reports/2026-11-20.md", "reports/extra0.md", "reports/extra1.md", "reports/extra2.md", "reports/extra3.md", "reports/extra4.md"]
    assert R.report(r)[9] == "Files: 3 changed, 6 added, 0 removed (new: reports/2026-11-20.md, reports/extra0.md, reports/extra1.md)"


def test_the_percent_in_the_report_is_on_the_previous_close_and_not_on_the_open_of_the_candle(tmp_path):
    day = [STAND_IN_DAY, 90.0, 103.0, 88.0, 99.0, 5.5]                                      # a real candle opens away from the previous close
    r, _, _ = rehearse(tmp_path, kind="real", fetch=lambda *a: [day])
    assert "open 90.00, high 103.00, low 88.00, close 99.00, volume 5.5 (-1.00% on the previous close)" in R.report(r)[1]


def test_every_time_in_the_report_is_in_utc_whatever_the_time_zone_of_the_machine(tmp_path):
    r, _, _ = rehearse(tmp_path)
    old = os.environ.get("TZ")
    os.environ["TZ"] = "EST5"                                                               # five hours behind UTC: local midnight is a different day
    time.tzset()
    try:
        lines = R.report(r)
        assert lines[1].startswith("Stand-in for 2026-11-19:") and lines[2] == "Run time used: 2026-11-20 00:15 UTC"
        assert R._iso(STAND_IN_DAY) == "2026-11-19"
    finally:
        if old is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_the_report_says_when_the_repository_changed(tmp_path):
    root = make_root(tmp_path)
    r = R.rehearse(root, "fall", run=Fake(writes_repo=root))
    assert "Repository: CHANGED" in R.report(r)


# ---------------------------------------------------------------- the command

def test_the_command_passes_its_options_prints_the_report_and_exits_by_the_result(monkeypatch, capsys):
    seen = {}

    def fake(root, kind, move):
        seen.update(root=root, kind=kind, move=move)
        return {"problems": [], "marker": True}

    monkeypatch.setattr(R, "rehearse", fake)
    monkeypatch.setattr(R, "report", lambda r: ["line one", f"marker {r['marker']}"])
    assert R.main([]) == 0 and capsys.readouterr().out == "line one\nmarker True\n" and seen == {"root": C.ROOT, "kind": "real", "move": None}
    assert R.main(["--candle", "rise"]) == 0 and seen["kind"] == "rise" and seen["move"] is None
    assert R.main(["--candle", "fall", "--move", "-5"]) == 0 and seen["kind"] == "fall" and seen["move"] == -5.0
    assert R.main(["--move", "2.5"]) == 0 and seen["kind"] == "real" and seen["move"] == 2.5                       # a fraction of a percent is a move too
    monkeypatch.setattr(R, "rehearse", lambda root, kind, move: {"problems": ["x"], "marker": False})
    assert R.main([]) == 1


def test_a_rehearsal_that_cannot_be_made_is_exit_2_with_the_reason_on_the_error_stream(monkeypatch, capsys):
    def fake(root, kind, move):
        raise R.RehearsalError("Coinbase has no candle")

    monkeypatch.setattr(R, "rehearse", fake)
    assert R.main([]) == 2
    out = capsys.readouterr()
    assert out.out == "" and out.err == "cannot rehearse: Coinbase has no candle\n"


def test_the_help_names_the_command_and_the_three_kinds_of_stand_in(capsys):
    with pytest.raises(SystemExit) as e:
        R.main(["--help"])
    out = capsys.readouterr().out
    assert e.value.code == 0 and out.startswith("usage: python -m atlas_api.btcquant.rehearse ") and "{real,fall,rise}" in out and "--move MOVE" in out


def test_an_unknown_candle_kind_is_a_usage_error():
    with pytest.raises(SystemExit) as e:
        R.main(["--candle", "sideways"])
    assert e.value.code == 2


# ---------------------------------------------------------------- the real thing, on the real folder (slow: kept last)

def test_the_real_daily_run_is_rehearsed_on_the_real_folder_with_a_fall_and_nothing_is_written_there():
    before = R.snapshot(C.ROOT)
    r = R.rehearse(C.ROOT, "fall")
    assert R.snapshot(C.ROOT) == before
    assert r["problems"] == [] and r["repo_unchanged"] and r["repeat_ok"] and len(r["accounts"]) >= 18 and r["candle"][4] == pytest.approx(r["previous_close"] * 0.8, rel=1e-12)
    assert any(a["id"] == "buy_hold" and a["equity_after"] < a["equity_before"] for a in r["accounts"])                      # the benchmark that holds Bitcoin loses a fifth of it


def test_the_command_rehearses_a_real_candle_that_a_test_supplies_and_exits_0(monkeypatch, capsys):
    before = R.snapshot(C.ROOT)
    newest = D.load(C.ROOT / "data" / "btcusd_1d.csv")[-1]
    day = newest[0] + DAY
    monkeypatch.setattr(D.Downloader, "fetch", lambda self, interval, start, end: [[day, newest[4], newest[4] * 1.01, newest[4] * 0.99, newest[4], newest[5]]])
    assert R.main(["--candle", "real"]) == 0
    out = capsys.readouterr().out
    assert "(+0.00% on the previous close)" in out and out.rstrip().endswith("Result: no problems") and R.snapshot(C.ROOT) == before
