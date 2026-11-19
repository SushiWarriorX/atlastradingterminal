"""Experiment 1 from EDGE_PLAN.md: volatility-targeted holding of BTC, judged by the conditions written down BEFORE the run.

Rule (fixed, not to be changed after the result): weight = min(1, 40% / annualised 20-day realised volatility), decided at each close, applied from the next open; fee 5 bps + slippage 5 bps on the amount traded.
Pass means ALL of, on the sealed last 30% of the history: (a) Sharpe at least 0.10 above holding, (b) worst drop at least 10 points shallower than holding, (c) net return at least 70% of holding's,
(d) Sharpe above a constant-exposure hold with the same average weight. Run it with: python -m atlas_api.btclab.exp_voltarget
"""
from __future__ import annotations

import asyncio

import numpy as np

from .evaluate import IS_FRACTION, metrics
from .weights import simulate_weights, vol_target_weights

WINDOW, TARGET, CAP = 20, 0.40, 1.0
BPY = 365


def _sliced(curve, k0, k1) -> list[float]:
    base = curve[k0]
    return [x / base for x in curve[k0:k1 + 1]]


def run(rows) -> dict:
    t = np.array([r[0] for r in rows], float)
    o, c = np.array([r[1] for r in rows], float), np.array([r[4] for r in rows], float)
    n = len(c)
    k = int(n * IS_FRACTION)
    w = vol_target_weights(c, WINDOW, TARGET, CAP, BPY)
    vt = simulate_weights(o, c, w)
    hold = simulate_weights(o, c, np.ones(n))
    out = {"bars": n, "sealed_from_bar": k, "params": {"window": WINDOW, "target_annual_vol": TARGET, "cap": CAP}}
    for name, a, b in (("full", 0, n), ("sealed_last_30pct", k, n)):
        mean_w = float(np.mean(w[a:b]))
        const = simulate_weights(o, c, np.full(n, mean_w))
        m = {key: metrics(_sliced(cur["curve"], a, b), [], BPY) for key, cur in (("vol_target", vt), ("hold", hold), ("constant_exposure", const))}
        out[name] = {"mean_weight": round(mean_w, 3), **{key: {x: (None if v[x] is None else round(float(v[x]), 3)) for x in ("net_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe")} for key, v in m.items()}}
    s = out["sealed_last_30pct"]
    v, h, cst = s["vol_target"], s["hold"], s["constant_exposure"]
    conds = {"a_sharpe_at_least_0.10_above_hold": v["sharpe"] - h["sharpe"] >= 0.10,
             "b_worst_drop_at_least_10_points_shallower": v["max_drawdown_pct"] - h["max_drawdown_pct"] >= 10.0,
             "c_return_at_least_70pct_of_hold": v["net_return_pct"] >= 0.70 * h["net_return_pct"],
             "d_sharpe_above_constant_exposure": v["sharpe"] > cst["sharpe"]}
    out["conditions"] = {k_: bool(x) for k_, x in conds.items()}
    out["passes"] = bool(all(conds.values()))
    out["turnover_full_period"] = round(float(vt["turnover"]), 1)
    return out


async def _main() -> dict:
    from .track_cli import _rows
    return run(await _rows())


if __name__ == "__main__":
    import json
    print(json.dumps(asyncio.run(_main()), indent=1))
