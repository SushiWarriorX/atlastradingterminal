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
    assert r["world"] == "null_mild" and r["seed"] == 1 and len(r["families"]) == 15 and {"monday", "three_down", "volume_surge"} <= set(r["families"]) and r["trial_variance"] > 0 and r["trial_variance_excess"] > 0       # fifteen families since protocol 1.5
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


# ---- worlds with a planted reversal after a run of lower closes, and the family that is meant to find it (added with protocol 1.4) ----

def run_before(r):
    """For each candle, the number of lower closes in a row that end at the candle BEFORE it (a lower close is a negative return; the first candle has none), by a plain loop."""
    out, run = [], 0
    for i, x in enumerate(r):
        out.append(run)
        run = run + 1 if i > 0 and x < 0 else 0
    return np.array(out)


def test_the_planted_reversal_worlds_pay_their_premium_after_a_run_of_three_lower_closes_and_nowhere_else():
    n = 300_000
    for world, premium in (("planted_reversal_small", 0.003), ("planted_reversal_mid", 0.006), ("planted_reversal_big", 0.010)):
        r = K.daily_returns(world, 1, n=n)
        before = run_before(r)
        after, exactly_two, others = before >= 3, before == 2, before < 2
        se = 0.035 / np.sqrt(after.sum())
        assert 0.10 < after.mean() < 0.14 and r[after].mean() == pytest.approx(0.0004 + premium, abs=4 * se), world            # about one day in eight follows a run of three, and it pays the premium
        assert r[exactly_two].mean() == pytest.approx(0.0004, abs=4 * 0.035 / np.sqrt(exactly_two.sum())) and r[others].mean() == pytest.approx(0.0004, abs=4 * 0.035 / np.sqrt(others.sum())), world      # a run of two pays nothing extra
        assert r.std() == pytest.approx(0.035, rel=0.02)
    assert np.array_equal(K.daily_returns("planted_reversal_mid", 4), K.daily_returns("planted_reversal_mid", 4)) and not np.array_equal(K.daily_returns("planted_reversal_mid", 4), K.daily_returns("planted_reversal_big", 4))
    names = ["planted_reversal_small", "planted_reversal_mid", "planted_reversal_big"]
    assert [K.WORLDS[w]["premium"] for w in names] == [0.003, 0.006, 0.010] and all((K.WORLDS[w]["kind"], K.WORLDS[w]["drift"], K.WORLDS[w]["vol"], K.WORLDS[w]["streak"]) == ("reversal", 0.0004, 0.035, 3) for w in names)       # the numbers CALIBRATION.md quotes
    assert K.synthetic_candles("planted_reversal_big", 2)[0][0] == K.T0


def test_the_family_that_follows_runs_of_lower_closes_trades_in_a_reversal_world_and_leaves_a_compact_record():
    rows = K.run_family_world("planted_reversal_big", [3], "three_down", n_shifts=40)
    json.dumps(rows)
    r = rows[0]
    assert (r["world"], r["seed"], r["family"]) == ("planted_reversal_big", 3, "three_down") and r["chosen"] in ({"streak": 2}, {"streak": 3}, {"streak": 4}) and r["outcome"] in ("admitted", "rejected", "too_thin")
    assert r["activity"] > 40 and 0.001 < r["exposure"] < 0.05                                      # dozens of trades; about a tenth of the account, a tenth of the days
    assert K.run_family_world("planted_reversal_big", [3], "three_down", n_shifts=40) == rows        # reproducible


def test_the_record_of_the_reversal_family_carries_the_outcome_and_the_numbers_of_the_evaluation_it_came_from():
    # reference runs on seeded synthetic data (the random streams of numpy's default generator are stable): a no-skill dataset, and three with a reversal premium of 1.0% where the gates give different answers
    r = K.run_family_world("null_mild", [1], "three_down")[0]
    assert (r["outcome"], r["failed"], r["activity"], r["chosen"], r["stable"]) == ("rejected", ["A2", "A3", "A4", "A5"], 223, {"streak": 2}, False)
    assert r["train"] == pytest.approx(-0.4306, abs=0.001) and r["val"] == pytest.approx(-0.428, abs=0.001) and r["cost2"] == pytest.approx(-0.8352, abs=0.001) and r["val_null_p"] == pytest.approx(0.8905, abs=0.001)
    near = K.run_family_world("planted_reversal_big", [1], "three_down")[0]                                              # everything holds except the timing p-value, 0.217
    assert (near["outcome"], near["failed"], near["activity"], near["chosen"], near["stable"]) == ("rejected", ["A3"], 229, {"streak": 2}, True) and near["val_null_p"] == pytest.approx(0.2173, abs=0.001)
    got = K.run_family_world("planted_reversal_big", [2], "three_down")[0]
    assert (got["outcome"], got["failed"], got["chosen"], got["activity"]) == ("admitted", [], {"streak": 4}, 49) and got["val_null_p"] == pytest.approx(0.0408, abs=0.001)
    assert got["ir_train"] > 1.0 and got["ir_val"] > 1.0 and got["cost2"] == pytest.approx(0.8597, abs=0.001) and got["train"] == pytest.approx(1.0336, abs=0.001)
    two = K.run_family_world("planted_reversal_big", [3], "three_down")[0]
    assert (two["outcome"], two["failed"], two["chosen"], two["activity"]) == ("admitted", [], {"streak": 4}, 47) and two["val_null_p"] == pytest.approx(0.0131, abs=0.001)


def test_the_command_line_runs_the_reversal_family_in_a_reversal_world(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert K.main(["calibration", "planted_reversal_mid", "5", "7", str(out), "three_down"]) == 0
    rows = json.loads(out.read_text())
    assert [r["seed"] for r in rows] == [5, 6] and all(r["family"] == "three_down" for r in rows) and "planted_reversal_mid" in capsys.readouterr().out


# ---- a synthetic volume series, and worlds with a planted continuation after a heavy-volume up day (added with protocol 1.5) ----

def surge_reference(v, r, ratio=2.0, n=20):
    """For each candle: is it a surge day (volume at least `ratio` times the mean of the `n` candles before it, and a rise on the day before), by a plain loop written apart from the code under test. Candle 0 has no day before it."""
    out = []
    for i in range(len(v)):
        base = sum(v[i - n:i]) / n if i >= n else None
        out.append(bool(base and base > 0 and i > 0 and v[i] >= ratio * base and r[i] > 0))
    return np.array(out)


def test_every_world_carries_the_same_positive_volume_series_for_a_seed_and_the_prices_are_what_they_were_without_it():
    a, b = K.synthetic_candles("null_mild", 5), K.synthetic_candles("planted_strong", 5)
    va, vb = np.array([c[5] for c in a]), np.array([c[5] for c in b])
    assert np.array_equal(va, vb) and (va > 0).all() and np.array_equal(va, K.volume_series(5)) and not np.array_equal(va, K.volume_series(6))      # the volume depends on the seed and on nothing else
    assert va.std() / va.mean() > 0.3 and len(set(va.tolist())) > 2800                                                                  # it changes from day to day (it used to be a constant 100)
    r = K.daily_returns("null_mild", 5)
    assert np.allclose([c[4] for c in a], 20_000.0 * np.exp(np.cumsum(r)), rtol=1e-12)                                                   # every close is still built from the returns alone
    assert np.array_equal(r, np.random.default_rng(5).normal(0.0004, 0.035, 2875))                                                      # and the returns are the same numbers the generator always drew


def test_the_volume_has_a_random_stream_of_its_own_and_starts_in_its_stationary_distribution():
    seed, n = 5, 2875
    v = K.volume_series(seed)
    a = np.log(v / K.VOLUME_LEVEL)
    e = a[1:] - K.VOLUME_PERSISTENCE * a[:-1]                                                      # the innovations of the autoregression
    for other in (seed, seed + 1000):                                                              # the stream of the returns, and the stream of the wicks (the first draw of the candle builder)
        z = np.random.default_rng(other).normal(0.0, 1.0, n)[1:]
        assert abs(float(np.corrcoef(e, z)[0, 1])) < 0.08, other                                   # unrelated to both: four standard errors
    first = np.array([np.log(K.volume_series(s, n=1)[0] / K.VOLUME_LEVEL) for s in range(3000)])
    assert first.std() == pytest.approx(K.VOLUME_INNOVATION / np.sqrt(1 - K.VOLUME_PERSISTENCE ** 2), rel=0.06) and abs(first.mean()) < 0.05      # the first day is a draw from the long-run spread, not a start at the mean


def test_the_synthetic_volume_surges_about_as_often_and_is_about_as_persistent_as_the_stored_series():
    v = K.volume_series(1, n=200_000)
    base = np.convolve(v, np.ones(20) / 20, "valid")[:-1]                                           # base[j] is the mean of candles j .. j+19: the baseline of candle j+20
    share = {k: float(np.mean(v[20:] >= k * base)) for k in (1.5, 2.0, 3.0)}                         # the shares of days at 1.5, 2 and 3 times the mean of the 20 days before
    assert 0.13 < share[1.5] < 0.22 and 0.045 < share[2.0] < 0.095 and 0.008 < share[3.0] < 0.022   # the stored series has 15.9%, 6.3% and 1.5% (measured once, from volume alone)
    lv = np.log(v) - np.log(v).mean()
    assert 0.62 < float((lv[:-1] * lv[1:]).mean() / (lv * lv).mean()) < 0.78                         # the stored series has a first-order autocorrelation of 0.65


def test_the_planted_surge_worlds_pay_their_premium_on_the_five_candles_after_a_heavy_volume_up_day_and_nowhere_else():
    n = 300_000
    for world, premium in (("planted_surge_small", 0.001), ("planted_surge_mid", 0.002), ("planted_surge_big", 0.004)):
        r, v = K.daily_returns(world, 1, n=n), K.volume_series(1, n=n)
        day = surge_reference(v, r)
        inside = np.zeros(n, dtype=bool)
        for k in range(1, 6):
            inside[k:] |= day[:-k]
        se_in, se_out = 0.035 / np.sqrt(inside.sum()), 0.035 / np.sqrt((~inside).sum())
        assert 0.08 < inside.mean() < 0.20 and r[inside].mean() == pytest.approx(0.0004 + premium, abs=4 * se_in), world                  # about one candle in seven follows a surge day, and it pays the premium
        assert r[~inside].mean() == pytest.approx(0.0004, abs=4 * se_out) and r.std() == pytest.approx(0.035, rel=0.02), world            # nothing is paid anywhere else
    names = ["planted_surge_small", "planted_surge_mid", "planted_surge_big"]
    assert [K.WORLDS[w]["premium"] for w in names] == [0.001, 0.002, 0.004] and all((K.WORLDS[w]["kind"], K.WORLDS[w]["drift"], K.WORLDS[w]["vol"], K.WORLDS[w]["ratio"], K.WORLDS[w]["hold"]) == ("surge", 0.0004, 0.035, 2.0, 5) for w in names)   # the numbers CALIBRATION.md quotes
    assert np.array_equal(K.daily_returns("planted_surge_mid", 4), K.daily_returns("planted_surge_mid", 4)) and not np.array_equal(K.daily_returns("planted_surge_mid", 4), K.daily_returns("planted_surge_big", 4))


def test_the_surge_worlds_events_are_the_default_setting_of_the_family_they_are_meant_for():
    from atlas_api.btcquant import strategies as S
    r, cs = K.daily_returns("planted_surge_big", 2), K.synthetic_candles("planted_surge_big", 2)
    day = surge_reference([c[5] for c in cs], r)
    one = S.signals("volume_surge", cs, {"ratio": 2.0, "hold": 1}).state                         # a hold of one candle shows the surge days themselves
    assert one.tolist() == day.tolist() and day.sum() > 40


def test_the_volume_family_trades_in_a_surge_world_and_leaves_a_compact_record():
    rows = K.run_family_world("planted_surge_big", [3], "volume_surge", n_shifts=40)
    json.dumps(rows)
    r = rows[0]
    assert (r["world"], r["seed"], r["family"]) == ("planted_surge_big", 3, "volume_surge") and r["outcome"] in ("admitted", "rejected", "too_thin")
    assert {(c["ratio"], c["hold"]) for c in [r["chosen"]]} <= {(a, b) for a in (1.5, 2.0, 3.0) for b in (3, 5, 10)} and r["activity"] >= 1 and 0.0 < r["exposure"] < 0.5
    assert K.run_family_world("planted_surge_big", [3], "volume_surge", n_shifts=40) == rows        # reproducible


def test_the_command_line_runs_the_volume_family_in_a_surge_world(tmp_path, capsys):
    out = tmp_path / "rows.json"
    assert K.main(["calibration", "planted_surge_mid", "5", "7", str(out), "volume_surge"]) == 0
    rows = json.loads(out.read_text())
    assert [r["seed"] for r in rows] == [5, 6] and all(r["family"] == "volume_surge" for r in rows) and "planted_surge_mid" in capsys.readouterr().out


def test_the_record_of_the_volume_family_carries_the_outcome_and_the_numbers_of_the_evaluation_it_came_from():
    # reference runs on seeded synthetic data (the random streams of numpy's default generator are stable): a no-skill dataset that fails four gates, one where the chosen setting is in the ratio-3 row and makes too few trades, and one with a surge premium of 0.4% a candle that passes every gate
    r = K.run_family_world("null_mild", [2], "volume_surge")[0]
    assert (r["outcome"], r["failed"], r["activity"], r["chosen"], r["stable"]) == ("rejected", ["A2", "A3", "A4", "A5"], 96, {"hold": 3, "ratio": 1.5}, False)
    assert r["train"] == pytest.approx(-0.0007, abs=0.001) and r["val"] == pytest.approx(-0.0782, abs=0.001) and r["cost2"] == pytest.approx(-0.2119, abs=0.001) and r["val_null_p"] == pytest.approx(0.4493, abs=0.001)
    thin = K.run_family_world("null_mild", [7], "volume_surge")[0]
    assert (thin["outcome"], thin["failed"], thin["activity"], thin["chosen"]) == ("too_thin", ["A1", "A3", "A4"], 8, {"hold": 3, "ratio": 3.0})      # eight trades: fewer than the ten that gate A1 asks for
    got = K.run_family_world("planted_surge_big", [45], "volume_surge")[0]
    assert (got["outcome"], got["failed"], got["chosen"], got["activity"], got["stable"]) == ("admitted", [], {"hold": 10, "ratio": 1.5}, 61, True) and got["val_null_p"] == pytest.approx(0.0065, abs=0.001)
    assert got["ir_train"] == pytest.approx(1.04, abs=0.01) and got["ir_val"] == pytest.approx(1.48, abs=0.01) and got["cost2"] == pytest.approx(1.1406, abs=0.001) and got["train"] == pytest.approx(0.7392, abs=0.001) and got["val"] == pytest.approx(1.8531, abs=0.001)
