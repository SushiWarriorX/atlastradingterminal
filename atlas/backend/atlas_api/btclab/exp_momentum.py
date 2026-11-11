"""Experiment 2 from EDGE_PLAN.md: cross-sectional crypto momentum on the 28-coin panel, judged by the conditions written down BEFORE the run.

Rule (fixed): every 7th day, rank the eligible coins (a bar on each of the last 91 days) by 90-day return, hold the top 5 equal-weight, long only; cash if fewer than 10 are eligible; 20 bps on every amount traded;
decided at a close, traded at the next open. Sealed split: the last 30% of the panel's days. Comparisons: BTC buy-and-hold, equal-weight of all eligible coins (same schedule), and 200 random 5-coin portfolios.
Pass means ALL of, on the sealed period: (a) Sharpe at least 0.15 above equal-weight-all; (b) Sharpe above BTC; (c) net return at least BTC's; (d) Sharpe above the 95th percentile of the random portfolios.
SURVIVORSHIP IS NOT REMOVED: the coin list is made of coins listed today. Run: python -m atlas_api.btclab.exp_momentum [--db PATH]
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter

import numpy as np

from .evaluate import IS_FRACTION, metrics
from .portfolio import momentum_targets, simulate_portfolio

LOOKBACK, K, EVERY, MIN_ELIGIBLE = 90, 5, 7, 10
FEE, SLIP = 10.0, 10.0
BPY = 365
NULL_RUNS, NULL_SEED = 200, 20261111


def _panel_arrays(rows_by_symbol: dict, days: np.ndarray):
    syms = list(rows_by_symbol)
    idx = {int(t): i for i, t in enumerate(days)}
    o = np.full((len(days), len(syms)), np.nan)
    c = np.full((len(days), len(syms)), np.nan)
    for j, s in enumerate(syms):
        for r in rows_by_symbol[s]:
            i = idx.get(int(r[0]))
            if i is not None:
                o[i, j], c[i, j] = r[1], r[4]
    return syms, o, c


def _run(o, c, targets):
    """Simulate only from the day before the first decision (nothing happens before it), and pad the start with 1.0 so indexes line up with the panel."""
    decided = np.flatnonzero(~np.isnan(targets).all(axis=1))
    if len(decided) == 0:
        return {"curve": [1.0] * (len(c) + 1), "turnover": 0.0, "missing_coin_days": 0, "mean_exposure": 0.0}
    s = int(decided[0])
    res = simulate_portfolio(o[s:], c[s:], targets[s:], FEE, SLIP)
    res["curve"] = [1.0] * s + list(res["curve"])
    return res


def _sliced(curve, a, b):
    base = curve[a]
    return [x / base for x in curve[a:b + 1]]


def _m(curve, a, b) -> dict:
    m = metrics(_sliced(curve, a, b), [], BPY)
    return {k: (None if m[k] is None else round(float(m[k]), 3)) for k in ("net_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe")}


def run(rows_by_symbol: dict, days: np.ndarray) -> dict:
    syms, o, c = _panel_arrays(rows_by_symbol, days)
    n = len(days)
    k = int(n * IS_FRACTION)
    tg_mom = momentum_targets(c, LOOKBACK, K, EVERY, MIN_ELIGIBLE, "momentum")
    tg_all = momentum_targets(c, LOOKBACK, K, EVERY, MIN_ELIGIBLE, "all")
    mom, ew = _run(o, c, tg_mom), _run(o, c, tg_all)
    b = syms.index("BTC")
    tg_btc = np.full_like(c, np.nan)
    tg_btc[0] = 0.0
    tg_btc[0, b] = 1.0
    btc = _run(o, c, tg_btc)
    null_sharpes, null_returns = [], []
    for i in range(NULL_RUNS):
        r = _run(o, c, momentum_targets(c, LOOKBACK, K, EVERY, MIN_ELIGIBLE, "random", seed=NULL_SEED + i))
        m = metrics(_sliced(r["curve"], k, n), [], BPY)
        null_sharpes.append(m["sharpe"] if m["sharpe"] is not None else float("nan"))
        null_returns.append(m["net_return_pct"])
    ns = np.array(null_sharpes, float)
    first = int(np.flatnonzero(~np.isnan(tg_mom).all(axis=1))[0]) if (~np.isnan(tg_mom).all(axis=1)).any() else None
    held = Counter()
    for t in range(n):
        if not np.isnan(tg_mom[t]).all():
            for j in np.flatnonzero(tg_mom[t] > 0):
                held[syms[j]] += 1
    out = {"coins": len(syms), "days": n, "sealed_from_day": k, "first_decision_day": first,
           "params": {"lookback": LOOKBACK, "top_k": K, "rebalance_every_days": EVERY, "min_eligible": MIN_ELIGIBLE, "cost_bps_per_amount_traded": FEE + SLIP},
           "sealed_last_30pct": {"momentum": _m(mom["curve"], k, n), "equal_weight_all": _m(ew["curve"], k, n), "btc_hold": _m(btc["curve"], k, n),
                                 "random_5_coin_null": {"runs": NULL_RUNS, "sharpe_median": round(float(np.nanmedian(ns)), 3), "sharpe_p95": round(float(np.nanpercentile(ns, 95)), 3),
                                                        "return_median_pct": round(float(np.nanmedian(null_returns)), 1)}},
           "whole_history": {"momentum": _m(mom["curve"], first or 0, n), "equal_weight_all": _m(ew["curve"], first or 0, n), "btc_hold": _m(btc["curve"], first or 0, n)},
           "diagnostics": {"turnover_x_account": round(mom["turnover"], 1), "mean_exposure": round(mom["mean_exposure"], 3), "missing_coin_days_while_held": mom["missing_coin_days"],
                           "most_held": held.most_common(6)}}
    s = out["sealed_last_30pct"]
    conds = {"a_sharpe_at_least_0.15_above_equal_weight_all": s["momentum"]["sharpe"] - s["equal_weight_all"]["sharpe"] >= 0.15,
             "b_sharpe_above_btc_hold": s["momentum"]["sharpe"] > s["btc_hold"]["sharpe"],
             "c_return_at_least_btc_hold": s["momentum"]["net_return_pct"] >= s["btc_hold"]["net_return_pct"],
             "d_sharpe_above_random_95th_percentile": s["momentum"]["sharpe"] > s["random_5_coin_null"]["sharpe_p95"]}
    out["conditions"] = {k_: bool(v) for k_, v in conds.items()}
    out["passes"] = bool(all(conds.values()))
    out["caveat"] = "Survivorship is not removed: the coins are the ones Coinbase lists today. A pass would only be a candidate, flattered by survivorship."
    return out


async def _main(db_path: str) -> dict:
    from ..db import DB
    from .coins import DAY, UNIVERSE, CoinData
    cd = CoinData(DB(db_path))
    await cd.refresh_all()
    p = cd.panel()
    days = p["t"]
    rows = {s: cd.stored(s) for s in UNIVERSE if cd.stored(s)}
    return run(rows, days)


if __name__ == "__main__":
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/tmp/atlas_coins.db")
    print(json.dumps(asyncio.run(_main(ap.parse_args().db)), indent=1))
