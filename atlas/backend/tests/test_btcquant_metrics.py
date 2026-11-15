"""btcquant metrics: every number of protocol section 6 worked by hand (or recomputed with Python's own statistics module), the cases where a ratio is undefined, the regime labels with their
exact-equality boundaries, the exposure-matched hold with and without costs, and a whole-account example."""
import math
import statistics

import numpy as np
import pytest

from atlas_api.btcquant import config as C
from atlas_api.btcquant import metrics as M

SQ = math.sqrt(365)


# ---- returns, Sharpe, Sortino ----

def test_daily_returns_start_from_the_starting_equity():
    assert M.daily_returns([10_100, 10_200], 10_000) == pytest.approx([0.01, 10_200 / 10_100 - 1])
    assert len(M.daily_returns([], 10_000)) == 0


def test_sharpe_is_the_mean_over_the_sample_deviation_times_root_365():
    r = [0.01, -0.01, 0.02, 0.0]                                          # mean 0.005; deviations 0.005, -0.015, 0.015, -0.005; sum of squares 5e-4; ddof 1 -> sd sqrt(5e-4 / 3) = 0.0129099
    assert M.sharpe(r) == pytest.approx(0.005 / statistics.stdev(r) * SQ, rel=1e-12) and M.sharpe(r) == pytest.approx(7.39932429, rel=1e-8)
    assert M.sharpe([-x for x in r]) == pytest.approx(-7.39932429, rel=1e-8)


def test_sortino_divides_by_the_downside_deviation_over_all_days():
    r = [0.01, -0.01, 0.02, 0.0]                                          # only -0.01 is below zero: sqrt((0 + 0.0001 + 0 + 0) / 4) = 0.005, so the ratio is 1 before annualising
    assert M.sortino(r) == pytest.approx(SQ, rel=1e-12)


def test_ratios_with_a_zero_denominator_are_undefined_not_zero_and_not_infinite():
    assert M.sharpe([0.01, 0.01, 0.01]) is None and M.sharpe([0.0, 0.0]) is None and M.sharpe([0.01]) is None and M.sharpe([]) is None
    assert M.sortino([0.01, 0.02, 0.0]) is None and M.sortino([0.01]) is None and M.sortino([-0.01]) is None and M.sortino([]) is None
    assert M.calmar(0.1, 0.0) is None and M.calmar(None, 0.2) is None


# ---- drawdown, CAGR, Calmar, total return ----

def test_max_drawdown_is_measured_from_the_running_peak_and_the_start_counts_as_a_peak():
    assert M.max_drawdown([11_000, 9_900, 10_500, 8_800, 9_500], 10_000) == pytest.approx(0.2)           # 8,800 against the 11,000 peak
    assert M.max_drawdown([9_000, 9_500], 10_000) == pytest.approx(0.1)                                 # below the start from day one: the start is the peak
    assert M.max_drawdown([10_100, 10_200, 10_300], 10_000) == 0.0
    assert M.max_drawdown([10_000, 10_000], 10_000) == 0.0


def test_cagr_compounds_over_days_in_a_365_day_year():
    assert M.cagr(12_100, 10_000, 730) == pytest.approx(0.10, rel=1e-12)
    assert M.cagr(11_000, 10_000, 365) == pytest.approx(0.10, rel=1e-12)
    assert M.cagr(9_000, 10_000, 365) == pytest.approx(-0.10, rel=1e-12)
    assert M.cagr(11_000, 10_000, 0) is None and M.cagr(0.0, 10_000, 365) is None and M.cagr(-5.0, 10_000, 365) is None
    assert M.calmar(0.10, 0.20) == pytest.approx(0.5)
    assert M.total_return(10_300, 10_000) == pytest.approx(0.03)


# ---- trades ----

def trade(pnl, ret, bars):
    return {"net_pnl": pnl, "ret": ret, "bars": bars}


def test_trade_statistics_by_hand():
    t = [trade(100, 0.010, 2), trade(-50, -0.005, 3), trade(200, 0.020, 4), trade(-100, -0.010, 5)]
    s = M.trade_stats(t)
    assert s["trades"] == 4 and s["win_rate"] == 0.5
    assert s["avg_win"] == 150.0 and s["avg_win_pct"] == pytest.approx(0.015)
    assert s["avg_loss"] == 75.0 and s["avg_loss_pct"] == pytest.approx(0.0075)                              # losses are shown as positive magnitudes
    assert s["profit_factor"] == pytest.approx(2.0)                                                          # 300 won, 150 lost
    assert s["expectancy"] == pytest.approx(37.5) and s["expectancy_pct"] == pytest.approx(0.00375)
    assert s["avg_holding_days"] == 3.5
    assert s["best_trade"] == 200.0 and s["profit_without_best"] == pytest.approx(-50.0)                      # 150 in total, 200 of it from one trade: negative without it


def test_a_break_even_trade_is_neither_a_win_nor_a_loss():
    s = M.trade_stats([trade(0.0, 0.0, 1), trade(10.0, 0.01, 1)])
    assert s["win_rate"] == 0.5 and s["avg_loss"] is None and s["profit_factor"] is None and s["avg_win"] == 10.0


def test_trade_statistics_with_no_losers_or_no_trades():
    s = M.trade_stats([trade(10, 0.01, 1), trade(20, 0.02, 1)])
    assert s["win_rate"] == 1.0 and s["profit_factor"] is None and s["avg_loss"] is None and s["avg_loss_pct"] is None
    e = M.trade_stats([])
    assert e["trades"] == 0 and e["win_rate"] is None and e["profit_factor"] is None and e["expectancy"] is None and e["avg_holding_days"] is None
    losers = M.trade_stats([trade(-10, -0.01, 1)])
    assert losers["win_rate"] == 0.0 and losers["profit_factor"] == 0.0 and losers["avg_win"] is None


# ---- regimes ----

def test_regimes_follow_the_close_against_the_average_and_the_average_against_20_days_earlier():
    close = [5, 5, 5, 12, 12, 8, 9, 10]
    sma = [math.nan, math.nan, 10, 10, 11, 9, 9, 9]
    got = M.regime_labels(close, sma, lookback=2)
    # i=2, 3: the average or the one 2 days earlier does not exist yet; i=4: above 11 and 11 > 10: BULL; i=5: below 9 and 9 < 10: BEAR;
    # i=6: 9 is not below 9 (equal): RANGE; i=7: above 9 but the average is not higher than 2 days earlier (9, 9): RANGE
    assert got == [None, None, None, None, "BULL", "BEAR", "RANGE", "RANGE"]


def test_exact_equalities_are_never_bull_or_bear():
    assert M.regime_labels([102.0, 102.0, 102.0, 103.0], [100.0, 101.0, 102.0, 103.0], lookback=2)[2] == "RANGE"      # close equals a rising average
    assert M.regime_labels([101.0] * 4, [103.0, 102.0, 101.0, 100.0], lookback=2)[2] == "RANGE"                       # close equals a falling average
    assert M.regime_labels([90.0] * 4, [100.0] * 4, lookback=2)[2:] == ["RANGE", "RANGE"]                             # below a flat average (not lower than 2 days earlier): not BEAR
    assert M.regime_labels([110.0] * 4, [100.0] * 4, lookback=2)[2:] == ["RANGE", "RANGE"]                            # above a flat average: not BULL
    assert M.regime_labels([110.0] * 4, [90.0, 95.0, 100.0, 105.0], lookback=2)[2:] == ["BULL", "BULL"]
    assert M.regime_labels([80.0] * 4, [110.0, 105.0, 100.0, 95.0], lookback=2)[2:] == ["BEAR", "BEAR"]


def test_the_regime_lookback_is_twenty_days_by_default():
    sma = [100.0] * 6 + [110.0] * 30                                                    # the average jumped at index 6
    close = [120.0] * 36                                                                # always above the average
    labels = M.regime_labels(close, sma)
    assert labels[19] is None                                                           # needs the average 20 days earlier
    assert labels[20] == "BULL" and labels[25] == "BULL"                                # 110 against indices 0 to 5 (100): higher
    assert labels[26] == "RANGE"                                                        # 110 against index 6 (110): not higher


def test_regimes_by_return_contain_days_exposure_and_sharpe_only_with_thirty_days():
    labels = ["BULL", "BULL", "BEAR", "RANGE", None]
    sr = [0.10, 0.10, -0.10, 0.0, 0.05]
    br = [0.20, 0.10, -0.20, 0.01, 0.0]
    ex = [0.5, 0.5, 0.5, 0.0, 0.1]
    g = M.by_regime(sr, br, ex, labels)
    assert g["BULL"]["days"] == 2 and g["BULL"]["strategy_return"] == pytest.approx(0.21) and g["BULL"]["btc_return"] == pytest.approx(0.32) and g["BULL"]["exposure"] == 0.5
    assert g["BEAR"]["strategy_return"] == pytest.approx(-0.10) and g["BEAR"]["btc_return"] == pytest.approx(-0.20)
    assert g["RANGE"]["strategy_return"] == 0.0 and g["RANGE"]["exposure"] == 0.0 and g["unknown"] == 1
    assert g["BULL"]["sharpe"] is None
    rng = np.random.default_rng(0)
    r30 = list(rng.normal(0.001, 0.02, 30))
    g30 = M.by_regime(r30, r30, [1.0] * 30, ["BULL"] * 30)
    assert g30["BULL"]["sharpe"] == pytest.approx(M.sharpe(r30))
    g29 = M.by_regime(r30[:29], r30[:29], [1.0] * 29, ["BULL"] * 29)
    assert g29["BULL"]["sharpe"] is None
    empty = M.by_regime([0.1], [0.1], [1.0], ["BULL"])
    assert empty["BEAR"]["days"] == 0 and empty["BEAR"]["strategy_return"] is None and empty["BEAR"]["exposure"] is None


# ---- the exposure-matched hold ----

def test_the_matched_hold_without_costs_by_hand():
    marks = M.matched_hold([100, 0, 0], [100, 110, 99], 0.5, 10_000, fee=0.0, slip=0.0)
    # day 0: buys 5,000 at the open, close = open: 10,000. day 1: +10% on half: 10,500. day 2: rebalanced to half, -10% on half: 10,500 x 0.95
    assert marks == pytest.approx([10_000.0, 10_500.0, 9_975.0])


def test_the_matched_hold_pays_the_same_costs_on_what_it_trades():
    marks = M.matched_hold([100, 0, 0], [100, 110, 99], 0.5, 10_000, fee=0.001, slip=0.0005)
    # day 0 buys 5,000: cost 7.50. day 2 trades (0.5238095 - 0.5) x 10,492.125 = 249.8125: cost 0.374719
    assert marks == pytest.approx([9_992.5, 10_492.125, 9_967.1627671875], rel=1e-12)


def test_the_matched_hold_at_the_extremes():
    assert M.matched_hold([100, 0, 0], [100, 110, 99], 0.0, 10_000) == [10_000.0] * 3                          # nothing held: nothing happens
    full = M.matched_hold([100, 0, 0], [100, 110, 99], 1.0, 10_000, fee=0.0, slip=0.0)
    assert full == pytest.approx([10_000.0, 11_000.0, 9_900.0])                                                # all in, no rebalancing needed after the first day
    paid = M.matched_hold([100, 0, 0], [100, 110, 99], 1.0, 10_000)
    assert paid[0] == pytest.approx(10_000 * (1 - 0.0015))


# ---- everything together ----

def curve(equities, exposures, close=100.0):
    return [(1_700_000_000 + i * 86_400, e, x, e * (1 - x), e * x / close, close) for i, (e, x) in enumerate(zip(equities, exposures))]


def test_compute_gives_every_number_of_protocol_section_6():
    eq = [10_100, 10_000, 10_300, 10_300]
    cur = curve(eq, [0.5, 0.5, 0.5, 0.0])
    trades = [{"net_pnl": 300.0, "ret": 0.03, "bars": 3}]
    m = M.compute(cur, trades, start_equity=10_000, fees_paid=12.0, slip_paid=6.0, traded=5_000.0, fills=2, breaker_trips=0,
                  hold_return=0.10, matched_return=0.02)
    r = [0.01, 10_000 / 10_100 - 1, 0.03, 0.0]
    assert m["days"] == 4 and m["final_equity"] == 10_300 and m["total_return"] == pytest.approx(0.03)
    assert m["max_drawdown"] == pytest.approx(1 - 10_000 / 10_100)
    assert m["sharpe"] == pytest.approx(statistics.mean(r) / statistics.stdev(r) * SQ, rel=1e-12) and m["sharpe"] == pytest.approx(8.4344179, rel=1e-7)
    assert m["sortino"] == pytest.approx(29.0395593, rel=1e-7)
    assert m["cagr"] == pytest.approx(1.03 ** (365 / 4) - 1, rel=1e-12) and m["calmar"] == pytest.approx(m["cagr"] / m["max_drawdown"])
    assert m["exposure"] == pytest.approx(0.375)
    assert m["turnover"] == pytest.approx(5_000 / 10_175) and m["turnover_per_year"] == pytest.approx(5_000 / 10_175 / (4 / 365))
    assert m["fees_paid"] == 12.0 and m["slippage_paid"] == 6.0 and m["fills"] == 2 and m["breaker_trips"] == 0 and m["open_position_at_end"] is False
    assert m["trades"] == 1 and m["win_rate"] == 1.0 and m["profit_factor"] is None and m["avg_holding_days"] == 3.0
    assert m["hold_return"] == 0.10 and m["vs_hold"] == pytest.approx(-0.07) and m["matched_hold_return"] == 0.02 and m["vs_matched_hold"] == pytest.approx(0.01)
    assert "by_regime" not in m


def test_compute_adds_the_regime_table_when_labels_are_given_and_handles_an_empty_period():
    cur = curve([10_100, 10_200], [0.5, 0.5])
    m = M.compute(cur, [], start_equity=10_000, fees_paid=0.0, slip_paid=0.0, traded=0.0, labels=["BULL", "BEAR"], btc_returns=[0.01, -0.01])
    assert m["by_regime"]["BULL"]["days"] == 1 and m["by_regime"]["BEAR"]["days"] == 1 and m["trades"] == 0 and m["win_rate"] is None
    e = M.compute([], [], start_equity=10_000, fees_paid=0.0, slip_paid=0.0, traded=0.0)
    assert e["days"] == 0 and e["total_return"] == 0.0 and e["cagr"] is None and e["sharpe"] is None and e["exposure"] == 0.0 and e["max_drawdown"] == 0.0


def test_drawdown_in_compute_counts_the_starting_equity_as_the_first_peak():
    m = M.compute(curve([9_900, 9_800, 9_900], [1.0, 1.0, 1.0]), [], start_equity=10_000, fees_paid=0.0, slip_paid=0.0, traded=0.0)
    assert m["max_drawdown"] == pytest.approx(0.02) and m["total_return"] == pytest.approx(-0.01)


def test_the_cash_benchmark_has_flat_numbers_and_undefined_ratios():
    m = M.compute(curve([10_000.0] * 5, [0.0] * 5), [], start_equity=10_000, fees_paid=0.0, slip_paid=0.0, traded=0.0)
    assert m["total_return"] == 0.0 and m["max_drawdown"] == 0.0 and m["sharpe"] is None and m["sortino"] is None and m["calmar"] is None and m["exposure"] == 0.0 and m["turnover"] == 0.0
