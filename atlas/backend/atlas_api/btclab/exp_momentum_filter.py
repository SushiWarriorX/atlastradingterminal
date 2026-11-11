"""Experiment 3 from EDGE_PLAN.md: experiment 2's cross-sectional momentum with ONE gate, judged by the conditions written down BEFORE the run (commit 71d9396).

Rule (fixed): exactly experiment 2 (28 coins, every 7th day rank eligible coins by 90-day return, hold the top 5 equal-weight, long only, cash if fewer than 10 are eligible, 20 bps on every amount traded, decided at a close
and traded at the next open) PLUS: at each weekly decision hold the portfolio only if BTC's close is above its 200-day simple average, else cash until the next weekly decision.
Sealed split: the last 30% of the panel's days. Comparisons: BTC buy-and-hold; equal-weight of all eligible coins with the same gate; 200 random 5-coin portfolios with the same gate; experiment 2's unfiltered momentum for reference.
Pass means ALL of, on the sealed period: (a) Sharpe at least 0.15 above the gated equal-weight-all; (b) Sharpe above BTC buy-and-hold; (c) worst drop shallower than BTC's; (d) Sharpe above the 95th percentile of the gated random
portfolios; (e) net return above zero; and at least 30 portfolio changes in the sealed period. SURVIVORSHIP IS NOT REMOVED. A pass would be "candidate, survivorship-flattered, second look at one idea".
Run: python -m atlas_api.btclab.exp_momentum_filter [--db PATH]
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter

import numpy as np

from .evaluate import IS_FRACTION, metrics
from .exp_momentum import BPY, EVERY, K, LOOKBACK, MIN_ELIGIBLE, NULL_RUNS, NULL_SEED, _m, _panel_arrays, _run, _sliced
from .portfolio import momentum_targets, trend_gate

GATE_WINDOW = 200
MIN_CHANGES = 30


def _changes(targets: np.ndarray, start: int) -> int:
    """Portfolio changes from day `start` on: decision rows whose target differs from the previous decision row (going to or from cash counts)."""
    rows = [i for i in range(len(targets)) if not np.isnan(targets[i]).all()]
    n = 0
    for a, b in zip(rows, rows[1:]):
        if b >= start and not np.array_equal(targets[a], targets[b]):
            n += 1
    return n


def run(rows_by_symbol: dict, days: np.ndarray) -> dict:
    syms, o, c = _panel_arrays(rows_by_symbol, days)
    n = len(days)
    k = int(n * IS_FRACTION)
    b = syms.index("BTC")
    gate = trend_gate(c[:, b], GATE_WINDOW)
    tg_mom = momentum_targets(c, LOOKBACK, K, EVERY, MIN_ELIGIBLE, "momentum", gate=gate)
    tg_all = momentum_targets(c, LOOKBACK, K, EVERY, MIN_ELIGIBLE, "all", gate=gate)
    tg_plain = momentum_targets(c, LOOKBACK, K, EVERY, MIN_ELIGIBLE, "momentum")
    mom, ew, plain = _run(o, c, tg_mom), _run(o, c, tg_all), _run(o, c, tg_plain)
    tg_btc = np.full_like(c, np.nan)
    tg_btc[0] = 0.0
    tg_btc[0, b] = 1.0
    btc = _run(o, c, tg_btc)
    null_sharpes, null_returns = [], []
    for i in range(NULL_RUNS):
        r = _run(o, c, momentum_targets(c, LOOKBACK, K, EVERY, MIN_ELIGIBLE, "random", seed=NULL_SEED + i, gate=gate))
        m = metrics(_sliced(r["curve"], k, n), [], BPY)
        null_sharpes.append(m["sharpe"] if m["sharpe"] is not None else float("nan"))
        null_returns.append(m["net_return_pct"])
    ns = np.array(null_sharpes, float)
    decided = ~np.isnan(tg_mom).all(axis=1)
    first = int(np.flatnonzero(decided)[0]) if decided.any() else None
    weeks = [t for t in np.flatnonzero(decided) if t >= k]
    in_market = [t for t in weeks if tg_mom[t].sum() > 0]
    held = Counter()
    for t in in_market:
        for j in np.flatnonzero(tg_mom[t] > 0):
            held[syms[j]] += 1
    out = {"coins": len(syms), "days": n, "sealed_from_day": k, "first_decision_day": first,
           "params": {"lookback": LOOKBACK, "top_k": K, "rebalance_every_days": EVERY, "min_eligible": MIN_ELIGIBLE, "cost_bps_per_amount_traded": 20, "gate": f"BTC close above its {GATE_WINDOW}-day simple average"},
           "sealed_last_30pct": {"momentum_gated": _m(mom["curve"], k, n), "equal_weight_all_gated": _m(ew["curve"], k, n), "btc_hold": _m(btc["curve"], k, n), "momentum_ungated_reference": _m(plain["curve"], k, n),
                                 "random_5_coin_null_gated": {"runs": NULL_RUNS, "sharpe_median": round(float(np.nanmedian(ns)), 3), "sharpe_p95": round(float(np.nanpercentile(ns, 95)), 3),
                                                              "return_median_pct": round(float(np.nanmedian(null_returns)), 1)}},
           "whole_history": {"momentum_gated": _m(mom["curve"], first or 0, n), "btc_hold": _m(btc["curve"], first or 0, n), "momentum_ungated_reference": _m(plain["curve"], first or 0, n)},
           "diagnostics": {"weekly_decisions_in_sealed_period": len(weeks), "weeks_in_market": len(in_market), "weeks_in_cash": len(weeks) - len(in_market), "portfolio_changes_in_sealed_period": _changes(tg_mom, k),
                           "turnover_x_account": round(mom["turnover"], 1), "missing_coin_days_while_held": mom["missing_coin_days"], "most_held_in_sealed_period": held.most_common(6)}}
    s = out["sealed_last_30pct"]
    m_, e_, b_ = s["momentum_gated"], s["equal_weight_all_gated"], s["btc_hold"]
    conds = {"a_sharpe_at_least_0.15_above_gated_equal_weight_all": m_["sharpe"] - e_["sharpe"] >= 0.15,
             "b_sharpe_above_btc_hold": m_["sharpe"] > b_["sharpe"],
             "c_worst_drop_shallower_than_btc_hold": m_["max_drawdown_pct"] > b_["max_drawdown_pct"],
             "d_sharpe_above_gated_random_95th_percentile": m_["sharpe"] > s["random_5_coin_null_gated"]["sharpe_p95"],
             "e_net_return_above_zero": m_["net_return_pct"] > 0,
             "f_at_least_30_portfolio_changes": out["diagnostics"]["portfolio_changes_in_sealed_period"] >= MIN_CHANGES}
    out["conditions"] = {k_: bool(v) for k_, v in conds.items()}
    out["passes"] = bool(all(conds.values()))
    out["caveat"] = "Survivorship is not removed: the coins are the ones Coinbase lists today. A pass would only be a candidate, flattered by survivorship, and a second look at one idea."
    return out


async def _main(db_path: str) -> dict:
    from ..db import DB
    from .coins import UNIVERSE, CoinData
    cd = CoinData(DB(db_path))
    await cd.refresh_all()
    p = cd.panel()
    return run({s: cd.stored(s) for s in UNIVERSE if cd.stored(s)}, p["t"])


if __name__ == "__main__":
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/tmp/atlas_coins.db")
    print(json.dumps(asyncio.run(_main(ap.parse_args().db)), indent=1))
