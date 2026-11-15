"""btcquant calibration: the synthetic worlds are what they say they are (valid candles on the stored calendar, reproducible, with and without a trend structure), and the summaries count correctly."""
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from atlas_api.btcquant import calibration as K


def test_synthetic_candles_are_valid_daily_candles_on_the_stored_calendar():
    for world in K.WORLDS:
        cs = K.synthetic_candles(world, 3)
        assert len(cs) == 2875 and cs[0][0] == K.T0 and all(b[0] - a[0] == 86400 for a, b in zip(cs, cs[1:]))
        for i, (t, o, h, l, c, v) in enumerate(cs):
            assert h >= max(o, c) and l <= min(o, c) and l > 0 and v > 0
            if i:
                assert o == cs[i - 1][4]                                                 # each candle opens at the previous close


def test_the_same_seed_gives_the_same_series_and_different_seeds_or_worlds_do_not():
    a, b = K.synthetic_candles("null_mild", 5), K.synthetic_candles("null_mild", 5)
    assert a == b and a != K.synthetic_candles("null_mild", 6) and a != K.synthetic_candles("null_drift", 5) and a != K.synthetic_candles("planted_strong", 5)
    assert np.array_equal(K.daily_returns("planted_weak", 2), K.daily_returns("planted_weak", 2))


def test_the_null_worlds_have_the_stated_drift_and_volatility_and_no_trend_structure():
    for world, drift in (("null_mild", 0.0004), ("null_drift", 0.0015)):
        r = K.daily_returns(world, 1, n=200_000)
        assert r.mean() == pytest.approx(drift, abs=3 * 0.035 / np.sqrt(200_000)) and r.std() == pytest.approx(0.035, rel=0.01)
        assert abs(trend_edge(r)) < 0.0004                                               # what follows a rising month is no better than what follows a falling one


def trend_edge(r, window=30):
    """Mean return of the days after a positive trailing 30-day sum, less the mean after a negative one."""
    cs = np.concatenate([[0.0], np.cumsum(r)])
    trail = cs[window:-1] - cs[:-window - 1]
    nxt = r[window:]
    return float(nxt[trail > 0].mean() - nxt[trail <= 0].mean())


def test_the_planted_worlds_have_a_trend_edge_that_a_trend_rule_can_use_and_the_stronger_one_has_more():
    strong = K.daily_returns("planted_strong", 1, n=200_000)
    weak = K.daily_returns("planted_weak", 1, n=200_000)
    assert trend_edge(strong) > 0.002 and trend_edge(weak) > 0.0008 and trend_edge(strong) > 1.5 * trend_edge(weak)           # measured: about 0.0028 and 0.0012 a day
    assert strong.mean() == pytest.approx(0.0, abs=0.0006)                                   # the hidden drift is up and down in equal measure: no net drift to ride


def test_the_admission_summary_counts_datasets_with_something_admitted():
    rows = [{"families": {"a": {"outcome": "admitted"}, "b": {"outcome": "rejected"}, "c": {"outcome": "admitted"}}},
            {"families": {"a": {"outcome": "rejected"}, "b": {"outcome": "too_thin"}}},
            {"families": {"a": {"outcome": "admitted"}}}]
    s = K.admission_summary(rows)
    assert s == {"datasets": 3, "any_admitted": 2, "share": pytest.approx(2 / 3), "mean_admitted": pytest.approx(1.0)}
    assert K.admission_summary([])["share"] is None


def test_the_command_line_refuses_an_unknown_world(capsys):
    assert K.main(["calibration", "moon", "1", "2"]) == 2 and "usage" in capsys.readouterr().out


def test_one_dataset_goes_through_the_whole_procedure_and_leaves_a_compact_record():
    rows = K.run_world("null_mild", [1], n_shifts=20)
    json.dumps(rows)
    r = rows[0]
    assert r["world"] == "null_mild" and r["seed"] == 1 and len(r["families"]) == 13 and "monday" in r["families"] and r["trial_variance"] > 0 and r["trial_variance_excess"] > 0       # thirteen families since protocol 1.3
    f = r["families"]["tsmom"]
    assert set(f) >= {"outcome", "failed", "activity", "train", "val", "ir_train", "ir_val", "dsr", "dsr_excess", "null_p", "val_null_p", "wf_passes", "exposure", "stable", "cost2"}
    assert f["outcome"] in ("admitted", "rejected", "too_thin") and (f["val_null_p"] is None or 0.0 <= f["val_null_p"] <= 1.0)


# ---- worlds with a planted weekday premium, and one family run alone (added with protocol 1.3) ----

def weekday_of_candle(i):
    return ((K.T0 // 86400) + i + 3) % 7                                             # the formula the code uses ...


def test_the_weekday_arithmetic_of_the_tests_matches_the_calendar():
    first = datetime.fromtimestamp(K.T0, timezone.utc)
    assert first.weekday() == 1                                                      # 2019-01-01 was a Tuesday
    assert [weekday_of_candle(i) for i in range(30)] == [(first + timedelta(days=i)).weekday() for i in range(30)]     # ... agrees with the calendar's own answer


def test_the_planted_weekday_worlds_pay_their_premium_on_one_weekday_and_nowhere_else():
    n = 1_050_000                                                                    # 150,000 weeks: a premium that is 0.1 of a percentage point out is 11 standard errors away
    wd = weekday_of_candle(np.arange(n))
    se = 0.035 / np.sqrt(n / 7)
    for world, premium in (("planted_monday_small", 0.003), ("planted_monday_mid", 0.006), ("planted_monday_big", 0.010)):
        r = K.daily_returns(world, 1, n=n)
        assert r[wd == 0].mean() == pytest.approx(0.0004 + premium, abs=4 * se)
        for d in range(1, 7):
            assert r[wd == d].mean() == pytest.approx(0.0004, abs=4 * se), (world, d)
        assert r.std() == pytest.approx(0.035, rel=0.01)
    assert np.array_equal(K.daily_returns("planted_monday_mid", 4), K.daily_returns("planted_monday_mid", 4)) and not np.array_equal(K.daily_returns("planted_monday_mid", 4), K.daily_returns("planted_monday_big", 4))


def test_one_family_alone_goes_through_selection_and_the_gates_and_leaves_a_compact_record():
    rows = K.run_family_world("planted_monday_big", [3], "monday", n_shifts=40)
    json.dumps(rows)
    r = rows[0]
    assert (r["world"], r["seed"], r["family"], r["chosen"]) == ("planted_monday_big", 3, "monday", {"day": 0}) and r["outcome"] in ("admitted", "rejected", "too_thin")
    assert set(r) >= {"outcome", "failed", "activity", "train", "val", "stable", "cost2", "ir_train", "ir_val", "val_null_p", "exposure"} and r["activity"] > 200      # about two fills a week for five years
    assert r["val_null_p"] is None or 0.0 <= r["val_null_p"] <= 1.0 and 0.10 < r["exposure"] < 0.20                    # fully invested one day in seven
    assert K.run_family_world("planted_monday_big", [3], "monday", n_shifts=40) == rows                                 # reproducible


def test_the_record_carries_the_outcome_and_the_numbers_of_the_evaluation_it_came_from():
    # reference runs on seeded synthetic data (the random streams of numpy's default generator are stable): a no-skill dataset, and three with a Monday premium of 1.0% where the gates give different answers
    r = K.run_family_world("null_mild", [1], "monday")[0]
    assert (r["outcome"], r["failed"], r["activity"], r["stable"]) == ("rejected", ["A2", "A3", "A4", "A5"], 466, False)
    assert r["train"] == pytest.approx(-0.179, abs=0.001) and r["val"] == pytest.approx(-0.595, abs=0.001) and r["cost2"] == pytest.approx(-1.131, abs=0.001) and r["val_null_p"] == pytest.approx(0.7353, abs=0.001)
    near = K.run_family_world("planted_monday_big", [1], "monday")[0]                                                    # everything holds except the timing p-value, 0.070
    assert (near["outcome"], near["failed"], near["activity"]) == ("rejected", ["A3"], 498) and near["val_null_p"] == pytest.approx(0.0703, abs=0.001) and near["stable"] is True
    got = K.run_family_world("planted_monday_big", [3], "monday")[0]
    assert (got["outcome"], got["failed"], got["val_null_p"]) == ("admitted", [], 0.0) and got["ir_train"] > 0 and got["ir_val"] > 0 and got["cost2"] == pytest.approx(0.987, abs=0.001)
    two = K.run_family_world("planted_monday_big", [5], "monday")[0]
    assert (two["outcome"], two["failed"]) == ("rejected", ["A2", "A3"])


def test_the_family_argument_is_the_family_that_is_run():
    r = K.run_family_world("null_mild", [1], "tsmom", n_shifts=40)[0]
    assert r["family"] == "tsmom" and list(r["chosen"]) == ["L"] and r["activity"] != 466 and r["activity"] > 10               # tsmom, not monday: its own selection and its own trades


def test_the_command_line_runs_one_family_and_refuses_an_unknown_one(tmp_path, capsys):
    out = tmp_path / "m.json"
    assert K.main(["calibration", "planted_monday_mid", "5", "7", str(out), "monday"]) == 0
    rows = json.loads(out.read_text())
    assert [r["seed"] for r in rows] == [5, 6] and all(r["family"] == "monday" for r in rows) and "planted_monday_mid" in capsys.readouterr().out
    assert K.main(["calibration", "planted_monday_mid", "5", "6", str(out), "moon"]) == 2 and "usage" in capsys.readouterr().out
