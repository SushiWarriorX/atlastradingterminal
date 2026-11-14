"""Experiment 7 from EDGE_PLAN.md: Bitcoin held only while the US stock market is in an uptrend (Nasdaq Composite above its 200-day average), judged by the conditions written down BEFORE the run (commit edf2c7c).

Signal: at the close of each daily bar d, take the latest Nasdaq Composite close dated on or before d - 1 (one extra day of lag; weekends and holidays carry the last close forward) and the mean of the latest 200 closes ending there.
ON (weight 1.0) if that close is STRICTLY above the 200-close mean, else OFF (0.0), decided at every close and applied from the next open. Simulator, timing and costs are the BTC lab's (btclab/weights.py: 5 bps fee + 5 bps slippage, cash earns nothing),
through the same `_sim` and `switches` as experiments 5 and 6, and the same day-shift null. Sealed split: the last 30% of the complete daily bars (index int(0.70 x bars) onward). Every comparator starts flat at the first sealed bar.

PASS = ALL of: (a) Sharpe >= buy-and-hold + 0.10; (b) Sharpe above the 95th percentile of 1,000 shifted copies of the rule's own sealed schedule; (c) worst drop >= 10 percentage points shallower than buy-and-hold's;
(d) net return after costs > 0 and >= 12 switches. INVALID (not failed) if the index checks fail, fewer than 200 closes exist before a bar, or the daily bars have a gap.
Run: python -m atlas_api.btclab.exp_equity_trend
"""
from __future__ import annotations

import asyncio
import bisect
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np

from .evaluate import IS_FRACTION
from .exp_hashrate import shifted_days
from .exp_liquidity import _sim, switches

SMA_LEN, LAG_DAYS = 200, 1
NULL_RUNS, NULL_SEED, MIN_SHIFT_DAYS = 1000, 20261114, 60
PASS_SHARPE_EDGE, PASS_DROP_EDGE, MIN_SWITCHES = 0.10, 10.0, 12


def weights(dates: list[date], closes: list[tuple[date, float]]) -> np.ndarray:
    """w[i] = the weight decided at the close of bar i: 1.0 if the latest close dated on or before d - 1 is strictly above the mean of the 200 closes ending there, else 0.0. Raises ValueError if fewer than 200 closes exist."""
    days = [d for d, _ in closes]
    vals = np.array([v for _, v in closes], float)
    w = np.zeros(len(dates))
    for k, d in enumerate(dates):
        i = bisect.bisect_right(days, d - timedelta(days=LAG_DAYS)) - 1
        if i < SMA_LEN - 1:
            raise ValueError(f"fewer than {SMA_LEN} index closes before {d}")
        w[k] = 1.0 if vals[i] > vals[i - SMA_LEN + 1:i + 1].mean() else 0.0
    return w


def _num(x) -> float:
    return float("-inf") if x is None else float(x)


def judge(strat: dict, hold: dict, p95: float, switch_count: int) -> dict[str, bool]:
    """The four pre-registered conditions, on the sealed period. A figure that could not be computed (None) fails the conditions that need it."""
    s_sh, h_sh, s_dd, h_dd = strat["sharpe"], hold["sharpe"], strat["max_drawdown_pct"], hold["max_drawdown_pct"]
    ret = strat["net_return_pct"]
    return {"a_sharpe_at_least_0.10_above_hold": s_sh is not None and h_sh is not None and s_sh - h_sh >= PASS_SHARPE_EDGE,
            "b_sharpe_above_95th_pct_of_shifted_schedules": s_sh is not None and s_sh > p95,
            "c_worst_drop_at_least_10_points_shallower": s_dd is not None and h_dd is not None and s_dd - h_dd >= PASS_DROP_EDGE,
            "d_net_return_positive_and_at_least_12_switches": ret is not None and ret > 0 and switch_count >= MIN_SWITCHES}


def run(rows, closes: list[tuple[date, float]]) -> dict:
    t = [datetime.fromtimestamp(r[0], timezone.utc).date() for r in rows]
    if any((b - a).days != 1 for a, b in zip(t, t[1:])):
        return {"valid": False, "reason": "the daily bars have a gap"}
    try:
        w = weights(t, closes)
    except ValueError as e:
        return {"valid": False, "reason": str(e)}
    o, c = np.array([r[1] for r in rows], float), np.array([r[4] for r in rows], float)
    n = len(c)
    k = int(n * IS_FRACTION)
    length = n - k
    if length - 2 * MIN_SHIFT_DAYS < 1:
        return {"valid": False, "reason": "the sealed period is too short for the shifted schedules"}
    strat, hold = _sim(o, c, w, k), _sim(o, c, np.ones(n), k)
    const = _sim(o, c, np.full(n, strat["mean_weight"]), k)
    rng = np.random.default_rng(NULL_SEED)
    shifts = rng.integers(MIN_SHIFT_DAYS, length - MIN_SHIFT_DAYS + 1, size=NULL_RUNS)
    null, null_sw = [], []
    for m in shifts:
        w2 = shifted_days(w, k, int(m))
        null.append(_sim(o, c, w2, k))
        null_sw.append(switches(w2, k))
    ns = np.array([_num(x["sharpe"]) for x in null], float)
    p95 = float(np.percentile(ns, 95))
    sw = switches(w, k)
    conds = judge(strat, hold, p95, sw)
    r3 = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 3)                                                    # noqa: E731
    pack = lambda d: {key: r3(d[key]) for key in ("net_return_pct", "max_drawdown_pct", "sharpe", "mean_weight")}                      # noqa: E731
    return {"valid": True, "bars": n, "first_bar": t[0].isoformat(), "last_bar": t[-1].isoformat(), "sealed_from_bar": k, "sealed_from": t[k].isoformat(), "sealed_bars": length,
            "index_closes": len(closes), "index_first": closes[0][0].isoformat(), "index_last": closes[-1][0].isoformat(),
            "design": {"share_on": r3(float(np.mean(w[:k]))), "state_changes": int(np.sum(np.abs(np.diff(w[:k])) > 0))},
            "sealed": {"strategy": pack(strat), "hold": pack(hold), "constant_exposure": pack(const), "switches": sw, "share_of_time_on": r3(strat["mean_weight"])},
            "null": {"runs": NULL_RUNS, "sharpe_median": r3(np.median(ns)), "sharpe_95th": r3(p95), "share_at_or_above_strategy": r3(float(np.mean(ns >= _num(strat["sharpe"])))),
                     "return_median_pct": r3(np.median([_num(x["net_return_pct"]) for x in null])), "switches_min": min(null_sw), "switches_max": max(null_sw)},
            "whole_history_for_context": {"strategy": pack(_sim(o, c, w, 0)), "hold": pack(_sim(o, c, np.ones(n), 0))},
            "conditions": {key: bool(v) for key, v in conds.items()}, "passed": bool(all(conds.values()))}


# ---- live data (command line only) ----------------------------------------------------------------------------------------------------------------------------------------------
async def _main() -> dict:
    from . import research_data
    from .track_cli import _rows
    ix = research_data.fetch_index("NASDAQCOM")
    if not ix["ok"]:
        return {"valid": False, "reason": "Nasdaq Composite data failed its checks: " + "; ".join(ix["problems"])}
    rows = await _rows()
    today = datetime.now(timezone.utc).date()
    rows = [r for r in rows if datetime.fromtimestamp(r[0], timezone.utc).date() < today]                                          # complete days only
    return run(rows, ix["rows"])


if __name__ == "__main__":
    print(json.dumps(asyncio.run(_main()), indent=1, default=str))
