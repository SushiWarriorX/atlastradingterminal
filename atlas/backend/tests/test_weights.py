"""Fractional exposure simulator: hand-worked numbers, costs, timing, no look-ahead, and agreement with the whole-position engine when the weight is 1."""
import numpy as np

from atlas_api.btclab import weights as W
from atlas_api.btclab.engine import Costs, simulate


def _alt(r, n=40, start=100.0):
    c = [start]
    for i in range(n):
        c.append(c[-1] * (1 + (r if i % 2 == 0 else -r)))
    return np.array(c)


def test_volatility_weight_matches_a_hand_calculation():
    c = _alt(0.05)                                                       # daily returns +5%, -5%, ...: sample std over 20 of them = 0.05 * sqrt(20/19) = 0.051299
    w = W.vol_target_weights(c, window=20, target_ann=0.40, cap=1.0, bpy=365)
    assert abs(w[20] - 0.40 / (0.051299 * np.sqrt(365))) < 1e-4 and abs(w[20] - 0.40812) < 1e-4       # annual volatility 0.9801, so 0.4 / 0.9801
    calm = W.vol_target_weights(_alt(0.01), window=20, target_ann=0.40, cap=1.0)
    assert calm[20] == 1.0                                               # annual volatility 0.196 would ask for 2.04x: capped at 1x
    assert W.vol_target_weights(np.full(40, 100.0))[25] == 0.0           # no movement at all: no weight rather than a division by zero


def test_no_weight_until_twenty_returns_exist():
    w = W.vol_target_weights(_alt(0.05))
    assert (w[:20] == 0).all() and w[20] > 0                             # twenty returns end with the return into bar 20


def test_a_weight_only_uses_bars_up_to_its_own_close():
    rng = np.random.default_rng(3)
    c = 100 * np.cumprod(1 + rng.normal(0, 0.03, 200))
    assert (W.vol_target_weights(c[:120]) == W.vol_target_weights(c)[:120]).all()


def test_constant_half_weight_without_costs_follows_the_hand_calculation():
    c = np.array([100.0, 110.0, 99.0, 108.9])
    o = np.concatenate([[100.0], c[:-1]])                                # no overnight gaps: each bar opens at the previous close
    r = W.simulate_weights(o, c, np.full(4, 0.5), fee_bps=0, slippage_bps=0)
    assert abs(r["curve"][-1] - 1.05 * 0.95 * 1.05) < 1e-12 and abs(r["curve"][-1] - 1.047375) < 1e-12   # bar 0 is flat; then +10%, -10%, +10% at half weight


def test_the_first_trade_pays_fee_and_slippage_on_the_amount_traded():
    c = np.array([100.0, 110.0, 121.0])
    o = np.concatenate([[100.0], c[:-1]])
    r = W.simulate_weights(o, c, np.ones(3), fee_bps=5, slippage_bps=5)
    assert abs(r["curve"][2] - 0.999 * 1.1) < 1e-12 and abs(r["curve"][3] - 0.999 * 1.1 * 1.1) < 1e-12   # 10 bps once (flat to fully invested), then nothing more to trade


def test_the_weight_decided_at_a_close_is_not_used_on_that_same_bar():
    c = np.array([100.0, 100.0, 200.0, 200.0])
    o = np.array([100.0, 100.0, 100.0, 200.0])
    r = W.simulate_weights(o, c, np.array([0.0, 1.0, 0.0, 0.0]), fee_bps=0, slippage_bps=0)
    assert abs(r["curve"][3] - 2.0) < 1e-12                              # decided at the close of bar 1, held from bar 2's open (100) to its close (200): 2x; not from bar 1


def test_a_weight_of_one_agrees_with_the_whole_position_engine():
    rng = np.random.default_rng(7)
    n = 300
    c = 100 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    o = np.concatenate([[100.0], c[:-1]]) * (1 + rng.normal(0, 0.003, n))
    h, l = np.maximum(o, c) * 1.01, np.minimum(o, c) * 0.99
    t = np.arange(n) * 86400
    eng = simulate(t, o, h, l, c, np.ones(n), Costs(fee_bps=5, slippage_bps=5, leverage=1.0, perp=False), 0, n)
    mine = W.simulate_weights(o, c, np.ones(n), fee_bps=5, slippage_bps=5)
    assert abs(mine["curve"][-1] / eng["curve"][-1] - 1) < 2e-3          # the two simulators price the same fees and fills within 0.2% over 300 bars


def test_experiment_runner_reports_the_pre_registered_conditions_on_a_known_series():
    from atlas_api.btclab import exp_voltarget as X
    rng = np.random.default_rng(11)
    n = 800
    c = 100 * np.cumprod(1 + rng.normal(0.0008, 0.025, n))
    o = np.concatenate([[100.0], c[:-1]])
    rows = [(i * 86400, o[i], max(o[i], c[i]), min(o[i], c[i]), c[i], 1.0) for i in range(n)]
    out = X.run(rows)
    assert out["sealed_from_bar"] == int(n * 0.70) and set(out["conditions"]) == {"a_sharpe_at_least_0.10_above_hold", "b_worst_drop_at_least_10_points_shallower", "c_return_at_least_70pct_of_hold", "d_sharpe_above_constant_exposure"}
    assert out["passes"] == all(out["conditions"].values())                                              # a pass is exactly all four conditions together
    s = out["sealed_last_30pct"]
    assert 0 < s["mean_weight"] <= 1 and s["hold"]["net_return_pct"] is not None and abs(s["vol_target"]["max_drawdown_pct"]) <= abs(s["hold"]["max_drawdown_pct"]) + 1e-9   # scaling down never deepens the drop here
