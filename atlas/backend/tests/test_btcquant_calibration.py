"""btcquant calibration: the synthetic worlds are what they say they are (valid candles on the stored calendar, reproducible, with and without a trend structure), and the summaries count correctly."""
import json

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
    assert r["world"] == "null_mild" and r["seed"] == 1 and len(r["families"]) == 12 and r["trial_variance"] > 0 and r["trial_variance_excess"] > 0
    f = r["families"]["tsmom"]
    assert set(f) >= {"outcome", "failed", "activity", "train", "val", "ir_train", "ir_val", "dsr", "dsr_excess", "null_p", "val_null_p", "wf_passes", "exposure", "stable", "cost2"}
    assert f["outcome"] in ("admitted", "rejected", "too_thin") and (f["val_null_p"] is None or 0.0 <= f["val_null_p"] <= 1.0)
