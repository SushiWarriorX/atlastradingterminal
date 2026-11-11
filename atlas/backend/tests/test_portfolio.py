"""Multi-asset simulator and cross-sectional momentum rule: hand-worked numbers, costs, no-trade rows, missing prices, eligibility, selection, schedule, no look-ahead, and agreement with the
single-asset simulator."""
import numpy as np

from atlas_api.btclab import portfolio as P
from atlas_api.btclab import weights as W

NAN = np.nan


def _gapless(c):
    c = np.asarray(c, float)
    return np.vstack([c[0:1], c[:-1]])                                            # each bar opens at the previous close


def test_two_coins_rebalanced_daily_without_costs_follow_the_hand_calculation():
    c = np.array([[100.0, 100.0], [120.0, 100.0], [132.0, 120.0]])
    tg = np.array([[0.5, 0.5], [0.5, 0.5], [NAN, NAN]])
    r = P.simulate_portfolio(_gapless(c), c, tg, fee_bps=0, slippage_bps=0)
    # bar 1: A +20%, B 0 at 50/50 -> 1.10; bar 2 (rebalanced back to 50/50): A +10%, B +20% -> 1.10 * (1 + 0.05 + 0.10) = 1.265
    assert abs(r["curve"][1] - 1.0) < 1e-12 and abs(r["curve"][2] - 1.10) < 1e-12 and abs(r["curve"][3] - 1.265) < 1e-12


def test_the_first_trade_from_cash_pays_fee_and_slippage_on_the_amount_traded_once():
    c = np.full((5, 2), 100.0)
    tg = np.full((5, 2), NAN)
    tg[0] = [0.5, 0.5]
    r = P.simulate_portfolio(_gapless(c), c, tg, fee_bps=10, slippage_bps=10)
    assert abs(r["curve"][-1] - 0.998) < 1e-12                                     # 20 bps on 100% of the account, and nothing more (flat prices, no later trades)
    assert abs(r["turnover"] - 1.0) < 1e-12


def test_a_nan_row_means_no_trade_and_the_weight_drifts():
    c = np.array([[100.0], [110.0], [121.0], [133.1]])
    tg = np.array([[1.0], [NAN], [NAN], [NAN]])
    r = P.simulate_portfolio(_gapless(c), c, tg, fee_bps=0, slippage_bps=0)
    assert abs(r["curve"][-1] - 1.1 ** 3) < 1e-12 and r["turnover"] == 1.0         # bought once, never touched again


def test_a_held_coin_with_no_price_adds_nothing_and_is_counted():
    c = np.array([[100.0, 100.0], [110.0, 100.0], [NAN, 100.0], [121.0, 100.0]])
    o = _gapless(c)
    o[2, 0] = NAN
    tg = np.array([[1.0, 0.0], [NAN, NAN], [NAN, NAN], [NAN, NAN]])
    r = P.simulate_portfolio(o, c, tg, fee_bps=0, slippage_bps=0)
    assert r["missing_coin_days"] == 2 and np.isfinite(r["curve"]).all()           # no open on day 2 and no previous close on day 3: two coin-days with a zero return, said out loud
    assert abs(r["curve"][-1] - 1.1) < 1e-12                                       # only the +10% of bar 1 was earned; nothing was made up for the missing days


def test_one_coin_agrees_with_the_single_asset_weight_simulator():
    rng = np.random.default_rng(5)
    n = 250
    c = 100 * np.cumprod(1 + rng.normal(0.0005, 0.03, n))
    o = np.concatenate([[100.0], c[:-1]]) * (1 + rng.normal(0, 0.004, n))
    w = np.clip(rng.uniform(0, 1, n), 0, 1)
    a = W.simulate_weights(o, c, w, fee_bps=10, slippage_bps=10)
    b = P.simulate_portfolio(o[:, None], c[:, None], w[:, None], fee_bps=10, slippage_bps=10)
    assert abs(a["curve"][-1] / b["curve"][-1] - 1) < 1e-9


def test_a_coin_is_eligible_only_with_a_bar_on_every_day_of_its_window():
    c = np.array([[100.0, 1], [101, 1], [102, 1], [NAN, 1], [104, 1], [105, 1], [106, 1], [107, 1]])
    ok = P.eligible_mask(c, lookback=2)
    assert not ok[:2].any()                                                         # not enough history yet
    assert ok[2, 0] and not ok[3, 0] and not ok[4, 0] and not ok[5, 0] and ok[6, 0]   # the hole at day 3 keeps the coin out until three clean days follow it
    assert ok[2:, 1].all()


def test_momentum_picks_the_best_lookback_return_among_eligible_coins_only():
    c = np.array([[100.0, 100.0, NAN], [100.0, 100.0, NAN], [120.0, 110.0, 500.0], [130.0, 100.0, 600.0]])
    t = P.momentum_targets(c, lookback=2, k=1, every=1, min_eligible=2)
    assert t[2].tolist() == [1.0, 0.0, 0.0]                                          # A +20%, B +10%; the third coin has no full window so it is not even considered
    assert np.isnan(t[:2]).all()


def test_not_enough_eligible_coins_means_cash_and_the_schedule_is_every_nth_day():
    rng = np.random.default_rng(2)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.02, (60, 12)), axis=0)
    t = P.momentum_targets(c, lookback=5, k=3, every=7, min_eligible=10)
    rebalance = [i for i in range(60) if not np.isnan(t[i]).all()]
    assert rebalance[0] == 5 and all(b - a == 7 for a, b in zip(rebalance, rebalance[1:]))
    assert all(abs(t[i].sum() - 1.0) < 1e-12 and (t[i] > 0).sum() == 3 for i in rebalance)
    c2 = c.copy()
    c2[:, 3:] = NAN                                                                   # only three coins exist: below the minimum of ten
    assert np.isnan(P.momentum_targets(c2, lookback=5, k=3, every=7, min_eligible=10)).all()


def test_all_and_random_picks_use_only_eligible_coins_and_random_is_reproducible():
    rng = np.random.default_rng(9)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.02, (40, 12)), axis=0)
    c[:, 11] = NAN                                                                    # one coin never has data
    ta = P.momentum_targets(c, 5, 5, 7, 10, pick="all")
    r1 = P.momentum_targets(c, 5, 5, 7, 10, pick="random", seed=3)
    r2 = P.momentum_targets(c, 5, 5, 7, 10, pick="random", seed=3)
    r3 = P.momentum_targets(c, 5, 5, 7, 10, pick="random", seed=4)
    row = next(i for i in range(40) if not np.isnan(ta[i]).all())
    assert abs(ta[row, :11] - 1 / 11).max() < 1e-12 and ta[row, 11] == 0              # equal weight over the eleven eligible coins
    assert np.array_equal(r1, r2, equal_nan=True) and not np.array_equal(r1, r3, equal_nan=True)
    assert (r1[~np.isnan(r1)] >= 0).all() and r1[row, 11] == 0


def test_a_decision_only_uses_bars_up_to_its_own_close():
    rng = np.random.default_rng(4)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.03, (150, 12)), axis=0)
    full = P.momentum_targets(c, 20, 5, 7, 10)
    part = P.momentum_targets(c[:90], 20, 5, 7, 10)
    assert np.array_equal(full[:90], part, equal_nan=True)


def test_experiment_runner_reports_the_pre_registered_conditions_on_a_known_panel(monkeypatch):
    from atlas_api.btclab import exp_momentum as X
    rng = np.random.default_rng(21)
    n, coins = 700, 14
    days = np.arange(n) * 86400
    closes = 100 * np.cumprod(1 + rng.normal(0.0005, 0.03, (n, coins)), axis=0)
    syms = ["BTC"] + [f"C{i}" for i in range(coins - 1)]
    rows = {s: [(int(days[t]), closes[max(t - 1, 0), j], closes[t, j] * 1.01, closes[t, j] * 0.99, closes[t, j], 1.0) for t in range(n)] for j, s in enumerate(syms)}
    monkeypatch.setattr(X, "NULL_RUNS", 5)                                                # a small null keeps this test fast; the real run uses 200
    out = X.run(rows, days)
    assert out["sealed_from_day"] == int(n * 0.70) and set(out["conditions"]) == {"a_sharpe_at_least_0.15_above_equal_weight_all", "b_sharpe_above_btc_hold", "c_return_at_least_btc_hold", "d_sharpe_above_random_95th_percentile"}
    assert out["passes"] == all(out["conditions"].values())                              # a pass is exactly all four conditions together
    s = out["sealed_last_30pct"]
    assert s["momentum"]["sharpe"] is not None and s["btc_hold"]["net_return_pct"] is not None and out["first_decision_day"] == 90 and out["coins"] == 14
    assert "Survivorship" in out["caveat"]


def test_trend_gate_is_true_only_above_the_average_of_the_last_window_by_hand():
    c = np.array([1.0, 2.0, 3.0, 2.0, 1.0, 5.0])
    g = P.trend_gate(c, window=3)
    # windows: t=2 [1,2,3] mean 2 -> 3>2 True; t=3 [2,3,2] mean 2.333 -> 2 False; t=4 [3,2,1] mean 2 -> 1 False; t=5 [2,1,5] mean 2.667 -> 5 True
    assert g.tolist() == [False, False, True, False, False, True]


def test_trend_gate_needs_a_full_clean_window_and_uses_only_the_past():
    c = np.array([1.0, 2.0, NAN, 4.0, 5.0, 6.0])
    assert P.trend_gate(c, window=3).tolist() == [False, False, False, False, False, True]          # the hole at index 2 blocks windows that contain it
    rng = np.random.default_rng(1)
    x = 100 * np.cumprod(1 + rng.normal(0, 0.02, 80))
    assert np.array_equal(P.trend_gate(x, 10)[:50], P.trend_gate(x[:50], 10))                        # truncating the future changes nothing before it


def test_a_closed_gate_turns_the_rebalance_into_cash_and_an_open_gate_changes_nothing():
    rng = np.random.default_rng(6)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.02, (60, 12)), axis=0)
    base = P.momentum_targets(c, 5, 3, 7, 10)
    open_ = P.momentum_targets(c, 5, 3, 7, 10, gate=np.ones(60, bool))
    assert np.array_equal(base, open_, equal_nan=True)
    gate = np.ones(60, bool)
    rebal = [i for i in range(60) if not np.isnan(base[i]).all()]
    gate[rebal[2]] = False
    g = P.momentum_targets(c, 5, 3, 7, 10, gate=gate)
    assert (g[rebal[2]] == 0).all() and not np.isnan(g[rebal[2]]).any()                              # a closed gate is an all-cash row, not a missing row
    assert np.array_equal(g[rebal[0]], base[rebal[0]]) and np.array_equal(g[rebal[3]], base[rebal[3]])  # other weeks are untouched


def test_experiment_3_runner_reports_the_pre_registered_conditions_on_a_known_panel(monkeypatch):
    from atlas_api.btclab import exp_momentum as X0
    from atlas_api.btclab import exp_momentum_filter as X
    rng = np.random.default_rng(33)
    n, coins = 900, 14
    days = np.arange(n) * 86400
    closes = 100 * np.cumprod(1 + rng.normal(0.0006, 0.03, (n, coins)), axis=0)
    syms = ["BTC"] + [f"C{i}" for i in range(coins - 1)]
    rows = {s: [(int(days[t]), closes[max(t - 1, 0), j], closes[t, j] * 1.01, closes[t, j] * 0.99, closes[t, j], 1.0) for t in range(n)] for j, s in enumerate(syms)}
    monkeypatch.setattr(X, "NULL_RUNS", 5)
    out = X.run(rows, days)
    assert set(out["conditions"]) == {"a_sharpe_at_least_0.15_above_gated_equal_weight_all", "b_sharpe_above_btc_hold", "c_worst_drop_shallower_than_btc_hold", "d_sharpe_above_gated_random_95th_percentile",
                                      "e_net_return_above_zero", "f_at_least_30_portfolio_changes"}
    assert out["passes"] == all(out["conditions"].values())                                       # a pass is exactly all conditions together
    d = out["diagnostics"]
    assert d["weeks_in_market"] + d["weeks_in_cash"] == d["weekly_decisions_in_sealed_period"] and out["sealed_from_day"] == int(n * 0.70)
    assert "Survivorship" in out["caveat"] and out["params"]["gate"].startswith("BTC close above its 200-day")
