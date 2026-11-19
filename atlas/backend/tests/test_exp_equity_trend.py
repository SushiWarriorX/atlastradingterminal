"""Experiment 7 (Bitcoin held only while the Nasdaq Composite is above its 200-day average): the 200-close signal worked by hand, the one-day lag and the weekend carry-forward, no look-ahead, the pass-bar boundaries (12 switches),
an end-to-end run with a planted relationship and without one, too few switches, and the INVALID paths. No network."""
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from atlas_api.btclab import exp_equity_trend as X
from atlas_api.btclab import exp_hashrate as H

D0 = date(2024, 1, 1)
START = D0 - timedelta(days=400)                                     # series index 0; the latest close a bar on D0 + i can see (dated D0 + i - 1) has index 399 + i


def closes(fn, n=700, start=START):
    return [(start + timedelta(days=j), float(fn(j))) for j in range(n)]


def bars(n):
    return [D0 + timedelta(days=i) for i in range(n)]


def test_a_dip_turns_it_off_the_day_after_and_a_recovery_turns_it_on_again():
    # slowly rising, a 10-day dip to 90 (series days 520 to 529), then a jump to 130
    fn = lambda j: 100 + 0.001 * j if j < 520 else 90.0 if j < 530 else 130.0                   # noqa: E731
    w = X.weights(bars(250), closes(fn))
    # bar i sees closes up to index 399 + i: index 520 first appears on bar 121 (the one-day lag: bar 120 still sees index 519)
    assert list(w[:121]) == [1.0] * 121
    assert list(w[121:131]) == [0.0] * 10                                                           # 90 is under the mean of the last 200 closes (about 100.4)
    # index 530 (130) first appears on bar 131: 130 is above the mean (190 x ~100.4 + 10 x 90 + 130) / 200 = about 100.0
    assert list(w[131:]) == [1.0] * 119


def test_equal_to_the_mean_is_off_and_ramps_follow_their_direction():
    assert list(X.weights(bars(100), closes(lambda j: 100.0))) == [0.0] * 100                       # a flat series: the close equals the mean, and "strictly above" means OFF
    assert list(X.weights(bars(100), closes(lambda j: 100.0 + j))) == [1.0] * 100
    assert list(X.weights(bars(100), closes(lambda j: 1000.0 - j))) == [0.0] * 100


def test_weekends_and_holidays_carry_the_last_close_forward_and_the_lag_is_one_day():
    start = date(2023, 1, 2)                                                                          # a Monday
    rows, d, k = [], start, 0
    friday = date(2024, 1, 5)
    while d <= date(2024, 2, 29):
        if d.weekday() < 5:                                                                           # closes on weekdays only
            rows.append((d, 50.0 if d == friday else 100.0 + 0.01 * k))                              # slowly rising, except one crash close on that Friday
            k += 1
        d += timedelta(days=1)
    w = X.weights([friday, friday + timedelta(days=1), friday + timedelta(days=2), friday + timedelta(days=3), friday + timedelta(days=4)], rows)
    # Friday's bar sees Thursday's close (ON); Saturday, Sunday and Monday bars all see Friday's 50 (OFF); Tuesday's bar sees Monday's normal close (ON)
    assert list(w) == [1.0, 0.0, 0.0, 0.0, 1.0]


def test_no_look_ahead_and_a_missing_warm_up_is_an_error():
    base = closes(lambda j: 100.0 + 0.01 * j)
    w = X.weights(bars(300), base)
    assert list(X.weights(bars(120), base)) == list(w[:120])                                          # a prefix of the bars gives the same decisions
    spike_index = 500                                                                                  # the close dated bar-day 100 (index 500 = 400 + 100)
    spiked = [(d, 1e9 if j == spike_index else v) for j, (d, v) in enumerate(base)]
    w2 = X.weights(bars(300), spiked)
    assert list(w2[:101]) == list(w[:101])                                                             # bars 0 to 100 cannot see it: bar 100 sees up to index 499
    assert w2[101] == 1.0 and list(w2[102:300]) == [0.0] * 198                                         # bar 101 sees it first (far above the mean), then it drags the mean up for the next 200 closes: OFF
    short = closes(lambda j: 100.0 + j, n=250, start=D0 - timedelta(days=150))                         # only 150 closes before the first bar
    with pytest.raises(ValueError, match="fewer than 200"):
        X.weights(bars(10), short)


def test_the_average_is_exactly_200_closes_long():
    """A spike of 400 among closes of 100 and a latest close of 101. The 200-close mean includes the spike only when it is the oldest of the 200."""
    p = 300
    base = [(START + timedelta(days=j), 100.0) for j in range(p + 260)]
    base[p] = (base[p][0], 400.0)

    def weight_when_latest_index_is(i):
        rows = list(base[:i]) + [(base[i][0], 101.0)]
        return X.weights([rows[-1][0] + timedelta(days=1)], rows)[0]
    # latest index p + 199: the window of 200 is p .. p + 199 and holds the spike: mean (400 + 198 x 100 + 101) / 200 = 101.505 > 101, so OFF (a 199-close window would not hold it: mean 100.005, ON)
    assert weight_when_latest_index_is(p + 199) == 0.0
    # latest index p + 200: the window of 200 is p + 1 .. p + 200 and does NOT hold it: mean (199 x 100 + 101) / 200 = 100.005 < 101, so ON (a 201-close window would hold it: mean 101.5, OFF)
    assert weight_when_latest_index_is(p + 200) == 1.0


def test_each_pass_condition_has_its_own_boundary():
    good = {"sharpe": 1.0, "max_drawdown_pct": -40.0, "net_return_pct": 5.0}
    hold = {"sharpe": 0.875, "max_drawdown_pct": -53.0, "net_return_pct": 100.0}
    ok = X.judge(good, hold, 0.9, 12)
    assert all(ok.values()) and len(ok) == 4
    a, b, c, d = ok
    assert "12_switches" in d
    assert not X.judge({**good, "sharpe": 0.9375}, hold, 0.5, 12)[a] and X.judge({**good, "sharpe": 1.0}, hold, 0.5, 12)[a]                  # 0.0625 above holding is not enough, 0.125 is
    assert not X.judge(good, hold, 1.0, 12)[b] and X.judge(good, hold, 0.9999, 12)[b]                                                    # strictly above the 95th percentile
    assert not X.judge({**good, "max_drawdown_pct": -45.0}, hold, 0.9, 12)[c] and X.judge(good, hold, 0.9, 12)[c]                       # 8 points shallower is not enough, 13 is
    assert not X.judge({**good, "net_return_pct": 0.0}, hold, 0.9, 12)[d]
    assert not X.judge(good, hold, 0.9, 11)[d] and X.judge(good, hold, 0.9, 12)[d] and X.judge(good, hold, 0.9, 13)[d]                  # 11 switches fail, 12 pass
    none = X.judge({"sharpe": None, "max_drawdown_pct": None, "net_return_pct": None}, hold, 0.9, 99)
    assert not any(none.values())


def test_the_day_shift_null_is_the_one_from_experiment_6():
    assert X.shifted_days is H.shifted_days
    k, n = 20, 320
    w = np.concatenate([np.zeros(k - 1), np.tile([1.0] * 7 + [0.0] * 5, 25)[:n - k], [1.0]])
    sh = X.shifted_days(w, k, 60)
    assert sh[k - 1:n - 1].sum() == w[k - 1:n - 1].sum() and list(sh[:k - 1]) == list(w[:k - 1]) and sh[n - 1] == w[n - 1]


def _synthetic(n_days=1500, seed=1, aligned=True, period=60.0):
    """Daily bars from 2020-01-01 and a Nasdaq-like series that oscillates around a flat level, so the close crosses its 200-close mean about every 30 days. When `aligned`, price drifts +0.4%/day on days the rule holds and -0.4% otherwise."""
    d0 = date(2020, 1, 1)
    ds = [d0 + timedelta(days=i) for i in range(n_days)]
    idx = [(d0 - timedelta(days=400) + timedelta(days=j), 1000.0 * (1 + 0.15 * np.sin(2 * np.pi * j / period))) for j in range(n_days + 401)]
    wt = X.weights(ds, idx)
    noise = np.random.default_rng(seed).normal(0, 0.003, n_days)
    ret = (np.where(np.roll(wt, 1) > 0, 0.004, -0.004) if aligned else 0.0) + noise
    c = 100.0 * np.cumprod(1 + ret)
    o = np.concatenate([[100.0], c[:-1]])
    rows = [(int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()), o[i], max(o[i], c[i]), min(o[i], c[i]), c[i], 1.0) for i, d in enumerate(ds)]
    return rows, idx


def test_end_to_end_a_stock_signal_that_really_leads_bitcoin_passes_every_condition():
    rows, idx = _synthetic(aligned=True)
    res = X.run(rows, idx)
    assert res["valid"] and res["sealed_from_bar"] == int(len(rows) * 0.7) and res["sealed_bars"] == len(rows) - res["sealed_from_bar"]
    assert res["sealed"]["switches"] >= 12 and res["null"]["runs"] == 1000
    assert res["conditions"] == {key: True for key in res["conditions"]} and res["passed"] is True
    assert res["sealed"]["strategy"]["sharpe"] > res["null"]["sharpe_95th"] > res["null"]["sharpe_median"]
    assert res["null"]["switches_max"] - res["null"]["switches_min"] <= 2
    assert res["index_closes"] == len(idx) and res["design"]["state_changes"] > 12


def test_end_to_end_a_signal_unrelated_to_bitcoin_does_not_pass():
    rows, idx = _synthetic(aligned=False, seed=7)
    res = X.run(rows, idx)
    assert res["valid"] and res["passed"] is False
    assert res["conditions"]["b_sharpe_above_95th_pct_of_shifted_schedules"] is False


def test_too_few_switches_fail_condition_d_even_if_the_rest_looks_good():
    rows, idx = _synthetic(aligned=True, period=900.0)
    res = X.run(rows, idx)
    assert res["valid"] and res["sealed"]["switches"] < 12
    assert res["conditions"]["d_net_return_positive_and_at_least_12_switches"] is False and res["passed"] is False


def test_end_to_end_is_deterministic_and_invalid_data_is_not_a_fail():
    rows, idx = _synthetic(aligned=True)
    assert X.run(rows, idx) == X.run(rows, idx)
    late = [(d, v) for d, v in idx if d >= date(2019, 8, 1)]                                         # the closes start only 153 days before the first bar: fewer than 200
    bad = X.run(rows, late)
    assert bad["valid"] is False and "fewer than 200" in bad["reason"] and "passed" not in bad
    skipped = rows[:100] + rows[101:]
    assert "gap" in X.run(skipped, idx)["reason"]
    short = X.run(rows[:150], idx)
    assert short["valid"] is False and "too short" in short["reason"]
