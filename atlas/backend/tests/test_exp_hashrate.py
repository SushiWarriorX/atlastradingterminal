"""Experiment 6 (Bitcoin held only while miners are not capitulating): the 30/60-day signal worked by hand, the one-day lag and no look-ahead, the day-shift null's invariants, an end-to-end run with a planted relationship and without one, and the INVALID paths. No network."""
from datetime import date, datetime, timedelta, timezone
from itertools import groupby

import numpy as np
import pytest

from atlas_api.btclab import exp_hashrate as X

D0 = date(2024, 1, 1)
START = D0 - timedelta(days=100)                                     # series index 0; a bar on D0 + i has index 100 + i


def series(fn, n=400):
    return {START + timedelta(days=j): float(fn(j)) for j in range(n)}


def days(n):
    return [D0 + timedelta(days=i) for i in range(n)]


def test_a_step_down_in_hash_rate_turns_the_rule_off_the_day_after_and_back_on_after_sixty_days():
    hist = series(lambda j: 200.0 if j < 150 else 100.0)             # miners switch off 40% of the machines on series day 150 = bar day 50
    w = X.weights(days(130), hist)
    # bar day 50 (index 150) still sees only stamps up to index 149: the one-day lag, so it is still ON
    assert list(w[:51]) == [1.0] * 51
    # bar day 51 sees the first low stamp: M30 = (29 x 200 + 100) / 30 = 196.67 < M60 = (59 x 200 + 100) / 60 = 198.33, so OFF
    assert w[51] == 0.0 and list(w[51:110]) == [0.0] * 59
    # bar day 110 (index 210): the 60 stamps are all 100, M30 = M60 exactly, and "at or above" means ON again
    assert list(w[110:]) == [1.0] * 20


def test_a_step_up_or_a_flat_series_never_turns_it_off_and_a_slow_decline_does():
    assert list(X.weights(days(130), series(lambda j: 100.0 if j < 150 else 200.0))) == [1.0] * 130
    assert list(X.weights(days(60), series(lambda j: 100.0))) == [1.0] * 60                           # equal means count as ON
    assert list(X.weights(days(60), series(lambda j: 1000.0 - j))) == [0.0] * 60                     # falling the whole time: the 30-day mean is under the 60-day mean
    assert list(X.weights(days(60), series(lambda j: 1000.0 + j))) == [1.0] * 60


def test_no_look_ahead_and_a_missing_stamp_is_an_error_not_a_guess():
    hist = series(lambda j: 100.0 + 30.0 * np.sin(j / 9.0))
    full = X.weights(days(200), hist)
    assert list(X.weights(days(80), hist)) == list(full[:80])                                         # a prefix of the bars gives the same decisions
    spiked = dict(hist)
    spiked[D0 + timedelta(days=60)] = 1e9                                                             # a stamp dated bar-day 60 ...
    w2 = X.weights(days(200), spiked)
    assert list(w2[:61]) == list(full[:61])                                                           # ... cannot change anything decided on bar-day 60 or earlier
    assert list(w2[61:91]) == [1.0] * 30                                                              # from bar-day 61 the spike sits in both windows and lifts the 30-day mean more: ON for 30 days
    assert list(w2[91:121]) == [0.0] * 30                                                             # then only in the 60-day window for 30 more days: OFF
    gone = dict(hist)
    del gone[D0 - timedelta(days=30)]
    with pytest.raises(ValueError, match="stamp is missing"):
        X.weights(days(10), gone)


def circular_runs(a):
    a = list(a)
    cut = next((i for i in range(len(a)) if a[i] != a[i - 1]), None)
    if cut is None:
        return [len(a)]
    a = a[cut:] + a[:cut]
    return sorted(len(list(g)) for _, g in groupby(a))


def test_the_day_shift_keeps_exposure_and_every_run_length_and_moves_nothing_else():
    k, length = 20, 300
    n = k + length
    rng = np.random.default_rng(5)
    seq = np.concatenate([np.full(int(r), float(i % 2)) for i, r in enumerate(rng.integers(5, 25, size=80))])[:length]
    w = np.concatenate([np.zeros(k - 1), seq, [1.0]])
    assert len(w) == n and X.switches(w, k) > 8
    for m in (60, 97, 240):
        sh = X.shifted_days(w, k, m)
        assert list(sh[:k - 1]) == list(w[:k - 1]) and sh[n - 1] == w[n - 1]                         # nothing outside the traded sequence moves
        assert sh[k - 1:n - 1].sum() == w[k - 1:n - 1].sum()                                          # exposure exactly the same
        assert circular_runs(sh[k - 1:n - 1]) == circular_runs(seq)                                   # every run length kept (around the circle)
        assert abs(X.switches(sh, k) - X.switches(w, k)) <= 1                                         # the seam can add or remove one switch
        assert not np.array_equal(sh, w)
    assert np.array_equal(X.shifted_days(w, k, 0), w) and np.array_equal(X.shifted_days(w, k, length), w)


def _synthetic(n_days=1500, seed=1, aligned=True, period=80.0):
    """Daily bars from 2020-01-01 and a hash-rate series that oscillates, so the 30/60 state flips about every 40 days. When `aligned`, price drifts +0.4%/day on days the rule holds and -0.4% otherwise."""
    d0 = date(2020, 1, 1)
    ds = [d0 + timedelta(days=i) for i in range(n_days)]
    hist = {d0 - timedelta(days=100) + timedelta(days=i): 1000.0 * (1 + 0.3 * np.sin(2 * np.pi * i / period)) for i in range(n_days + 101)}
    wt = X.weights(ds, hist)
    noise = np.random.default_rng(seed).normal(0, 0.003, n_days)
    ret = (np.where(np.roll(wt, 1) > 0, 0.004, -0.004) if aligned else 0.0) + noise
    c = 100.0 * np.cumprod(1 + ret)
    o = np.concatenate([[100.0], c[:-1]])
    rows = [(int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()), o[i], max(o[i], c[i]), min(o[i], c[i]), c[i], 1.0) for i, d in enumerate(ds)]
    return rows, hist


def test_end_to_end_a_hash_rate_signal_that_really_leads_price_passes_every_condition():
    rows, hist = _synthetic(aligned=True)
    res = X.run(rows, hist)
    assert res["valid"] and res["sealed_from_bar"] == int(len(rows) * 0.7) and res["sealed_bars"] == len(rows) - res["sealed_from_bar"]
    assert res["sealed"]["switches"] >= 6 and res["null"]["runs"] == 1000
    assert res["conditions"] == {key: True for key in res["conditions"]} and res["passed"] is True
    assert res["sealed"]["strategy"]["sharpe"] > res["null"]["sharpe_95th"] > res["null"]["sharpe_median"]
    assert res["null"]["switches_max"] - res["null"]["switches_min"] <= 2                              # the shifted copies keep the switch count to within the seam
    assert 0.3 < res["design"]["share_on"] < 0.7 and res["design"]["state_changes"] > 6


def test_end_to_end_a_signal_unrelated_to_price_does_not_pass():
    rows, hist = _synthetic(aligned=False, seed=7)
    res = X.run(rows, hist)
    assert res["valid"] and res["passed"] is False
    assert res["conditions"]["b_sharpe_above_95th_pct_of_shifted_schedules"] is False


def test_too_few_switches_fail_condition_d_even_if_the_rest_looks_good():
    rows, hist = _synthetic(aligned=True, period=900.0)                                                # a very slow cycle: only a couple of state changes in the sealed period
    res = X.run(rows, hist)
    assert res["valid"] and res["sealed"]["switches"] < 6
    assert res["conditions"]["d_net_return_positive_and_at_least_6_switches"] is False and res["passed"] is False


def test_end_to_end_is_deterministic_and_invalid_data_is_not_a_fail():
    rows, hist = _synthetic(aligned=True)
    assert X.run(rows, hist) == X.run(rows, hist)
    late = {d: v for d, v in hist.items() if d >= date(2019, 12, 1)}                                   # the series starts only 31 days before the first bar: fewer than 60 stamps
    bad = X.run(rows, late)
    assert bad["valid"] is False and "stamp is missing" in bad["reason"] and "passed" not in bad
    holed = dict(hist)
    del holed[date(2020, 3, 1)]                                                                        # one missing stamp inside the run
    assert X.run(rows, holed)["valid"] is False
    skipped = rows[:100] + rows[101:]                                                                  # a missing daily bar
    assert "gap" in X.run(skipped, hist)["reason"]
    short = X.run(rows[:150], hist)                                                                    # sealed period of 45 days: too short for shifts of 60 days
    assert short["valid"] is False and "too short" in short["reason"]


def test_each_pass_condition_has_its_own_boundary():
    """The four conditions on hand-made numbers (binary fractions, so the arithmetic is exact), one at a time with the rest passing."""
    good = {"sharpe": 1.0, "max_drawdown_pct": -40.0, "net_return_pct": 5.0}
    hold = {"sharpe": 0.875, "max_drawdown_pct": -53.0, "net_return_pct": 100.0}
    ok = X.judge(good, hold, 0.9, 6)
    assert all(ok.values()) and len(ok) == 4
    a, b, c, d = ok
    assert not X.judge({**good, "sharpe": 0.9375}, hold, 0.5, 6)[a]                                  # 0.0625 above holding is not enough ...
    assert X.judge({**good, "sharpe": 1.0}, {**hold, "sharpe": 0.875}, 0.5, 6)[a]                    # ... 0.125 is
    assert not X.judge(good, hold, 1.0, 6)[b] and X.judge(good, hold, 0.9999, 6)[b]                  # strictly above the 95th percentile: equal fails
    assert not X.judge({**good, "max_drawdown_pct": -45.0}, hold, 0.9, 6)[c]                         # 8 points shallower is not enough ...
    assert X.judge({**good, "max_drawdown_pct": -40.0}, hold, 0.9, 6)[c]                             # ... 13 is
    assert not X.judge({**good, "net_return_pct": 0.0}, hold, 0.9, 6)[d]                             # zero return fails
    assert not X.judge(good, hold, 0.9, 5)[d] and X.judge(good, hold, 0.9, 6)[d]                     # 5 switches fail, 6 pass
    none = X.judge({"sharpe": None, "max_drawdown_pct": None, "net_return_pct": None}, hold, 0.9, 10)
    assert not any(none.values())                                                                      # what could not be computed never passes
    one_pass = X.judge({"sharpe": None, "max_drawdown_pct": -40.0, "net_return_pct": 5.0}, hold, 0.9, 6)
    assert one_pass[c] and one_pass[d] and not one_pass[a] and not one_pass[b]

