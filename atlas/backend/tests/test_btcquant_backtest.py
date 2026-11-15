"""btcquant backtest runner: periods on a calendar, buy-and-hold equals the price ratio less costs, cash is flat, a weight strategy worked by hand to the cent, the closed form of the exposure-matched hold,
the full-exposure and cost sensitivities, no look-ahead from the runner's point of view, and the circuit-breaker cool-off passed through to the account."""
from datetime import date, datetime, timezone

import numpy as np
import pytest

from atlas_api.btcquant import backtest as B
from atlas_api.btcquant import config as C
from atlas_api.btcquant import indicators as I
from atlas_api.btcquant import metrics as M
from atlas_api.btcquant import strategies as S

DAY = 86400
T2019 = int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp())


def history(n, seed=1, start=20_000.0, vol=0.03, t0=T2019):
    rng = np.random.default_rng(seed)
    c = start * np.exp(np.cumsum(rng.normal(0.0004, vol, n)))
    o = np.concatenate([[start], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    return [(t0 + i * DAY, float(o[i]), float(h[i]), float(l[i]), float(c[i]), 100.0) for i in range(n)]


def from_closes(closes, t0=T2019):
    o = [closes[0]] + list(closes[:-1])
    return [(t0 + i * DAY, float(o[i]), float(max(o[i], closes[i])), float(min(o[i], closes[i])), float(closes[i]), 1.0) for i in range(len(closes))]


FULL = (date(2026, 11, 14) - date(2019, 1, 1)).days + 1                                  # 2,875 daily candles, as in the stored data


# ---- periods ----

def test_the_protocol_periods_cover_exactly_the_calendar_days_they_name():
    prep = B.Prepared(history(FULL))
    i0, i1 = prep.period("TRAIN")
    assert prep.times[i0] == B.day_ts(date(2020, 1, 1)) and prep.times[i1] == B.day_ts(date(2022, 12, 31)) and i1 - i0 + 1 == 1096
    v0, v1 = prep.period("VALIDATION")
    assert prep.times[v0] == B.day_ts(date(2023, 1, 1)) and prep.times[v1] == B.day_ts(date(2024, 12, 31)) and v1 - v0 + 1 == 731 and v0 == i1 + 1
    t0, t1 = prep.period("TEST")
    assert prep.times[t0] == B.day_ts(date(2025, 1, 1)) and t1 == FULL - 1 and t1 - t0 + 1 == (date(2026, 11, 14) - date(2025, 1, 1)).days + 1 and t0 == v1 + 1


def test_a_period_the_data_do_not_cover_is_refused_not_shortened():
    prep = B.Prepared(history(400))                                                       # 2019-01-01 to 2020-02-04
    with pytest.raises(ValueError, match="end before"):
        prep.span(date(2019, 6, 1), date(2021, 1, 1))
    with pytest.raises(ValueError, match="do not contain the first day"):
        prep.span(date(2018, 1, 1), None)
    with pytest.raises(ValueError, match="do not contain the first day"):
        prep.span(date(2021, 1, 1), None)
    with pytest.raises(ValueError, match="at least one candle before"):
        prep.span(date(2019, 1, 1), date(2019, 3, 1))                                     # the very first candle has no warm-up candle before it
    with pytest.raises(ValueError, match="holds no candle"):
        prep.span(date(2019, 3, 1), date(2019, 2, 1))
    assert prep.span(date(2019, 3, 1), date(2019, 3, 1)) == (59, 59)                      # a one-day period is allowed
    assert prep.span(date(2019, 12, 1), date(2020, 2, 4)) == (334, 399)                   # ending exactly on the last day of the data is allowed (2020-02-04 is candle 399)


# ---- the benchmarks ----

def test_buy_and_hold_equals_the_price_ratio_less_the_costs_of_one_purchase():
    prep = B.Prepared(history(FULL, seed=4))
    i0, i1 = prep.period("TRAIN")
    r = B.run(prep, "buy_hold", {}, i0, i1)
    o0, c_last = prep.candles[i0][1], prep.candles[i1][4]
    expected = c_last / (o0 * (1 + C.SLIPPAGE) * (1 + C.FEE)) - 1
    assert r.metrics["total_return"] == pytest.approx(expected, rel=1e-12)
    assert B.hold_return(prep, i0, i1) == pytest.approx(expected, rel=1e-12) and r.metrics["vs_hold"] == pytest.approx(0.0, abs=1e-12)
    assert r.metrics["fills"] == 1 and r.metrics["trades"] == 0 and r.metrics["open_position_at_end"] is True and r.metrics["breaker_trips"] == 0
    assert r.metrics["fees_paid"] == pytest.approx(C.START_EQUITY_STRATEGY / (1 + C.FEE) * C.FEE, rel=1e-12)


def test_buy_and_hold_never_trips_the_breaker_however_far_the_price_falls():
    prep = B.Prepared(from_closes([100.0] * 10 + [50.0] * 5 + [20.0] * 10))
    r = B.run(prep, "buy_hold", {}, 5, 24)
    assert r.metrics["breaker_trips"] == 0 and r.metrics["exposure"] > 0.99 and r.metrics["total_return"] < -0.7


def test_cash_stays_flat_with_undefined_ratios():
    prep = B.Prepared(history(FULL, seed=4))
    i0, i1 = prep.period("VALIDATION")
    r = B.run(prep, "cash", {}, i0, i1)
    m = r.metrics
    assert m["final_equity"] == C.START_EQUITY_STRATEGY and m["total_return"] == 0.0 and m["trades"] == 0 and m["fills"] == 0 and m["exposure"] == 0.0
    assert m["sharpe"] is None and m["max_drawdown"] == 0.0 and m["vs_hold"] == pytest.approx(-B.hold_return(prep, i0, i1)) and m["matched_hold_return"] == 0.0
    assert not r.exposure.any() and len(r.returns) == i1 - i0 + 1


# ---- a weight strategy to the cent ----

def test_a_weight_strategy_by_hand_without_costs():
    # closes 10, 11, 12, 11, 9, 8, 13; SMA3 weights 0, 0, 1, 0, 0, 0, 1. The period is candles 3 to 6. The order made at the close of candle 2 (weight 1) buys at the open of 3 (= 12);
    # candle 3 closes at 11; the close of 3 asks for weight 0, which sells at the open of 4 (= 11); the rest is cash.
    prep = B.Prepared(from_closes([10, 11, 12, 11, 9, 8, 13]))
    r = B.run(prep, "sma_filter", {"L": 3}, 3, 6, fee=0.0, slip=0.0, keep_account=True)
    m = r.metrics
    qty = 10_000 / 12
    assert [row[1] for row in r.account.curve] == pytest.approx([qty * 11] * 4)                      # 9,166.67 on every day from the first close
    assert m["total_return"] == pytest.approx(11 / 12 - 1) and m["trades"] == 1 and m["fills"] == 2 and m["win_rate"] == 0.0
    assert r.account.trades[0]["net_pnl"] == pytest.approx(qty * 11 - 10_000) and r.account.trades[0]["bars"] == 1
    assert m["exposure"] == pytest.approx(0.25) and list(r.exposure) == pytest.approx([1.0, 0.0, 0.0, 0.0]) and m["open_position_at_end"] is False
    assert m["hold_return"] == pytest.approx(13 / 12 - 1) and m["vs_hold"] == pytest.approx((11 / 12 - 1) - (13 / 12 - 1))
    # a constant 25% in Bitcoin, rebalanced daily without costs, is start x the product of (0.75 + 0.25 x each day's growth); the first day grows from the open (12 to 11)
    matched = 10_000 * (0.75 + 0.25 * 11 / 12) * (0.75 + 0.25 * 9 / 11) * (0.75 + 0.25 * 8 / 9) * (0.75 + 0.25 * 13 / 8)
    assert m["matched_hold_return"] == pytest.approx(matched / 10_000 - 1, rel=1e-12) and m["vs_matched_hold"] == pytest.approx(m["total_return"] - m["matched_hold_return"])
    assert r.returns[0] == pytest.approx(11 / 12 - 1) and np.allclose(r.returns[1:], 0.0)


def test_the_same_run_with_costs_pays_them_and_reports_them():
    prep = B.Prepared(from_closes([10, 11, 12, 11, 9, 8, 13]))
    free = B.run(prep, "sma_filter", {"L": 3}, 3, 6, fee=0.0, slip=0.0)
    paid = B.run(prep, "sma_filter", {"L": 3}, 3, 6)
    assert paid.metrics["final_equity"] < free.metrics["final_equity"] and paid.metrics["fees_paid"] > 0 and paid.metrics["slippage_paid"] > 0
    qty = 10_000 / (12 * 1.0005 * 1.001)
    sell = qty * 11 * (1 - 0.0005) * (1 - 0.001)
    assert paid.metrics["final_equity"] == pytest.approx(sell, rel=1e-12)
    assert paid.metrics["fees_paid"] == pytest.approx(qty * 12 * 1.0005 * 0.001 + qty * 11 * 0.9995 * 0.001, rel=1e-12)
    expensive = B.run(prep, "sma_filter", {"L": 3}, 3, 6, fee=0.003, slip=0.0015)
    assert expensive.metrics["final_equity"] < paid.metrics["final_equity"]
    assert expensive.metrics["hold_return"] == pytest.approx(13 / (12 * 1.0015 * 1.003) - 1, rel=1e-12)       # the benchmark pays the same costs as the strategy
    assert paid.metrics["hold_return"] == pytest.approx(13 / (12 * 1.0005 * 1.001) - 1, rel=1e-12)


# ---- sensitivities ----

def test_the_full_exposure_variant_holds_more_and_leaves_weight_strategies_unchanged():
    prep = B.Prepared(history(FULL, seed=8, vol=0.035))
    i0, i1 = prep.period("TRAIN")
    p = {"fast": 10, "slow": 50}
    risk, full = B.run(prep, "sma_cross", p, i0, i1), B.run(prep, "sma_cross", p, i0, i1, sizing="full")
    assert 0.0 < risk.metrics["exposure"] < 0.30 and full.metrics["exposure"] > 2 * risk.metrics["exposure"] and full.metrics["max_drawdown"] > risk.metrics["max_drawdown"]
    w = {"L": 100}
    a, b = B.run(prep, "sma_filter", w, i0, i1), B.run(prep, "sma_filter", w, i0, i1, sizing="full")
    assert a.metrics["final_equity"] == b.metrics["final_equity"]


def test_a_risk_sized_trade_loses_about_one_percent_of_equity_when_it_is_stopped_out():
    prep = B.Prepared(history(FULL, seed=8, vol=0.035))
    i0, i1 = prep.period("TRAIN")
    r = B.run(prep, "sma_cross", {"fast": 10, "slow": 50}, i0, i1, keep_account=True)
    stopped = [t for t in r.account.trades if t["reason"] == "stop"]
    losses = [-t["net_pnl"] / C.START_EQUITY_STRATEGY for t in stopped]
    assert len(stopped) >= 5 and all(0.0095 < x < 0.0135 for x in losses)               # the planned 1% plus fees, slippage and gaps; never several times that


# ---- the runner cannot look ahead ----

def test_a_period_result_does_not_depend_on_candles_after_it():
    base = history(FULL, seed=5)
    other = history(FULL, seed=77, start=base[1500][4])
    i0, i1 = 365, 1200
    changed = base[:i1 + 1] + [(base[i][0],) + other[i][1:] for i in range(i1 + 1, FULL)]
    a, b = B.Prepared(base), B.Prepared(changed)
    for fid in ("sma_cross", "donchian", "ma_atr_trend", "tsmom", "rsi_momentum", "bollinger_mr", "vol_breakout", "regime_switch", "vol_target", "sma_filter", "buy_hold"):
        p = S.configs(S.FAMILIES[fid])[0]
        ra, rb = B.run(a, fid, p, i0, i1), B.run(b, fid, p, i0, i1)
        for key in ("final_equity", "sharpe", "max_drawdown", "trades", "fills", "exposure", "total_return", "hold_return", "matched_hold_return"):
            assert ra.metrics[key] == rb.metrics[key], (fid, key)
        assert np.array_equal(ra.returns, rb.returns)


# ---- regimes and the circuit breaker ----

def test_the_regime_table_covers_every_day_of_the_period():
    prep = B.Prepared(history(FULL, seed=3))
    i0, i1 = prep.period("VALIDATION")
    r = B.run(prep, "sma_filter", {"L": 100}, i0, i1)
    g = r.metrics["by_regime"]
    assert g["BULL"]["days"] + g["BEAR"]["days"] + g["RANGE"]["days"] + g["unknown"] == i1 - i0 + 1 and g["unknown"] == 0
    assert all(g[k]["days"] > 0 for k in ("BULL", "BEAR", "RANGE"))


def crash_series():
    closes = [100.0 * 1.002 ** i for i in range(300)]
    closes += [closes[-1] * 0.85, closes[-1] * 0.85 * 0.85]
    closes += [closes[-1] * 1.015 ** k for k in range(1, 260)]
    return from_closes(closes)


def test_a_full_exposure_account_trips_the_breaker_and_a_research_account_comes_back_after_the_cool_off():
    prep = B.Prepared(crash_series())
    i0, i1 = 100, len(prep.candles) - 1
    resumed = B.run(prep, "sma_filter", {"L": 50}, i0, i1)
    never = B.run(prep, "sma_filter", {"L": 50}, i0, i1, cool_off_days=None)
    assert resumed.metrics["breaker_trips"] == never.metrics["breaker_trips"] == 1 and len(resumed.trips) == 1
    assert resumed.trips[0]["equity"] <= 0.85 * resumed.trips[0]["peak"]
    assert never.metrics["exposure"] < resumed.metrics["exposure"] and never.exposure[-1] == 0.0 and resumed.exposure[-1] > 0.9           # one buys back into the recovery, the other waits for a human forever
    assert never.metrics["final_equity"] < resumed.metrics["final_equity"]


def test_the_metrics_use_the_exposure_at_the_close_and_the_run_keeps_the_exposure_at_the_open():
    prep = B.Prepared(history(FULL, seed=8, vol=0.035))
    i0, i1 = prep.period("TRAIN")
    r = B.run(prep, "sma_cross", {"fast": 10, "slow": 50}, i0, i1, keep_account=True)
    assert r.metrics["exposure"] == pytest.approx(np.mean([row[2] for row in r.account.curve]), rel=1e-12)
    assert np.array_equal(r.exposure, np.array([row[6] for row in r.account.curve])) and not np.allclose(r.exposure, [row[2] for row in r.account.curve])
    assert prep.btc_returns[5] == pytest.approx(prep.candles[5][4] / prep.candles[4][4] - 1) and np.isnan(prep.btc_returns[0])
    expected = M.matched_hold(prep.bars.o[i0:i1 + 1], prep.bars.c[i0:i1 + 1], r.metrics["exposure"], C.START_EQUITY_STRATEGY, C.FEE, C.SLIPPAGE)[-1] / C.START_EQUITY_STRATEGY - 1
    assert r.metrics["matched_hold_return"] == pytest.approx(expected, rel=1e-12)                 # the matched weight is the average exposure at the close


def test_bitcoin_returns_are_close_to_close_even_when_a_candle_opens_away_from_the_last_close():
    base = history(60, seed=6)
    gapped = []
    for i, (t, o, h, l, c, v) in enumerate(base):
        o2 = base[i - 1][4] * 1.01 if i else o                                           # every candle opens 1% above the previous close
        gapped.append((t, o2, max(h, o2), min(l, o2), c, v))
    prep = B.Prepared(gapped)
    for i in (1, 7, 30):
        assert prep.btc_returns[i] == pytest.approx(gapped[i][4] / gapped[i - 1][4] - 1, rel=1e-12)


def test_the_regime_labels_are_the_close_against_the_200_day_average_with_the_20_day_slope():
    cs = history(400, seed=9)
    prep = B.Prepared(cs)
    closes = [x[4] for x in cs]
    assert prep.regimes == M.regime_labels(closes, I.sma(closes, 200))
    assert prep.regimes[218] is None and prep.regimes[219] is not None                     # the average exists from index 199, and its value 20 days earlier from index 219


def test_the_starting_equity_scales_the_account_and_leaves_the_returns_unchanged():
    prep = B.Prepared(history(FULL, seed=8, vol=0.035))
    i0, i1 = prep.period("TRAIN")
    for fid, p in (("sma_cross", {"fast": 10, "slow": 50}), ("sma_filter", {"L": 100})):
        a = B.run(prep, fid, p, i0, i1)
        b = B.run(prep, fid, p, i0, i1, start_equity=25_000.0)
        assert b.metrics["start_equity"] == 25_000.0 and b.metrics["final_equity"] == pytest.approx(25_000.0 * (1 + a.metrics["total_return"]), rel=1e-9)
        assert b.metrics["total_return"] == pytest.approx(a.metrics["total_return"], rel=1e-9) and b.metrics["sharpe"] == pytest.approx(a.metrics["sharpe"], rel=1e-9)
        assert b.metrics["fees_paid"] == pytest.approx(2.5 * a.metrics["fees_paid"], rel=1e-9)


def test_the_regime_of_a_day_is_the_one_in_force_at_the_previous_close(monkeypatch):
    prep = B.Prepared(history(FULL, seed=3))
    i0, i1 = prep.period("VALIDATION")
    seen = {}
    real = B.M.compute

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)
    monkeypatch.setattr(B.M, "compute", spy)
    B.run(prep, "sma_filter", {"L": 100}, i0, i1)
    assert seen["labels"] == prep.regimes[i0 - 1:i1] and len(seen["labels"]) == i1 - i0 + 1
    assert np.array_equal(seen["btc_returns"], prep.btc_returns[i0:i1 + 1])


def test_a_trailing_stop_family_keeps_its_trailing_stop_in_the_runner():
    # the ten-candle Donchian series: signal at the close of candle 4, entry at the open of 5, the stop ratchets to 12.5 and candle 7's low (12) touches it
    c = [10, 10, 10, 10, 12, 13, 14, 13, 15, 15]
    h = [10.5, 10.5, 10.5, 10.5, 12.5, 13.5, 14.5, 14.0, 15.5, 15.5]
    l = [9.5, 9.5, 9.5, 9.5, 11.0, 12.5, 13.0, 12.0, 14.0, 14.5]
    o = [10] + c[:-1]
    prep = B.Prepared([(T2019 + i * DAY, float(o[i]), h[i], l[i], float(c[i]), 1.0) for i in range(10)])
    r = B.run(prep, "donchian", {"N": 4}, 1, 9, keep_account=True)
    first = r.account.trades[0]
    assert first["reason"] == "stop" and first["entry_t"] == T2019 + 5 * DAY and first["exit_t"] == T2019 + 7 * DAY


def test_run_all_returns_every_configuration_keyed_by_its_parameters():
    prep = B.Prepared(history(FULL, seed=2))
    i0, i1 = prep.period("TRAIN")
    out = B.run_all(prep, "donchian", i0, i1)
    assert sorted(k for k in out) == sorted(B.param_key(p) for p in S.configs(S.FAMILIES["donchian"])) and len(out) == 4
    assert all(r.family == "donchian" and r.i0 == i0 and r.i1 == i1 for r in out.values())
    assert len({r.metrics["final_equity"] for r in out.values()}) > 1 and len({r.metrics["trades"] for r in out.values()}) > 1       # the signal cache must not mix configurations up
    assert B.param_key({"b": 2, "a": 1}) == (("a", 1), ("b", 2))
