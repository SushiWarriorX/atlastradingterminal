"""Experiment 5 from EDGE_PLAN.md: Bitcoin held only while US net liquidity is expanding, judged by the conditions written down BEFORE the run (commit 76c2805).

Net liquidity L(w) = Fed total assets (FRED WALCL, Wednesday level, millions) - Treasury General Account (WDTGAL, Wednesday level, millions) - overnight reverse repo (RRPONTSYD on that Wednesday, billions; the latest earlier value within 3 days
if that day has none), in billions of dollars. Signal: ON if L(w) - L(w - 91 days) > 0, else OFF (zero is OFF). Decision on each Friday's bar using the Wednesday two days earlier, applied from the next open, held until the next Friday;
weight 1.0 or 0.0, and 0 until the first signal exists. Simulator, timing and costs are the BTC lab's (btclab/weights.py: 5 bps fee + 5 bps slippage, cash earns nothing).
Sealed split: the last 30% of the bars (index int(0.70 x bars) onward). Every comparator is simulated from the first sealed bar, starting flat.

PASS = ALL of: (a) Sharpe >= buy-and-hold + 0.10; (b) Sharpe above the 95th percentile of 1,000 shifted copies of the strategy's own sealed schedule; (c) worst drop >= 10 percentage points shallower than buy-and-hold's;
(d) net return after costs > 0 and >= 10 switches in the sealed period. INVALID (not failed) if the data fail the registered checks.

Clarifications written down BEFORE the first run (they make the registered wording exact; none depends on a result, none can be tuned):
  1. "The Wednesday series used" = the Wednesdays from 98 days before the first Bitcoin bar onward, i.e. what can reach a signal. The reverse-repo series is sparse before late 2013 (a data-only look found two holes in 2013 and nothing
     from 2014 on); those old weeks never feed a signal, so they cannot make the run invalid.
  2. "The strategy's sealed weight sequence" = the n - k weights the simulator really trades (the weight decided at the close of bar k-1 is first used at the open of bar k). The weight decided on the very last bar is never traded.
  3. The shift moves the whole-week part of that sequence by m whole weeks (m uniform from 8 to W - 8, W = whole weeks in it); the last fewer-than-7 days stay where they are. Exposure and the weekday of every switch are kept EXACTLY; the two seams
     (where the moved block's end meets its start, and where it meets the unmoved tail) can add or remove a switch, so the number of switches can differ from the strategy's by up to 2.
  4. A "switch" = a change of weight between consecutive bars of the sealed sequence; the entry from flat at the first sealed bar is not counted.
  5. A Sharpe that cannot be computed (no variation) counts as not passing (a) and (b). The bars must be one per day with no gap, else INVALID.
Run: python -m atlas_api.btclab.exp_liquidity
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np

from .evaluate import IS_FRACTION, metrics
from .weights import simulate_weights

LOOKBACK_DAYS = 91
USED_FROM_DAYS_BEFORE_FIRST_BAR = 98
BPY = 365
NULL_RUNS, NULL_SEED, MIN_SHIFT_WEEKS = 1000, 20261114, 8
L_MIN, L_MAX = 3000.0, 9000.0
MAX_RRP_CARRY_SHARE, RRP_CARRY_DAYS = 0.05, 3
PASS_SHARPE_EDGE, PASS_DROP_EDGE, MIN_SWITCHES = 0.10, 10.0, 10


def net_liquidity(walcl: dict[date, float], wdtgal: dict[date, float], rrp: dict[date, float], start: date | None = None) -> tuple[dict[date, float], dict]:
    """L(w) in billions for each Wednesday (on or after `start`) that both weekly series have and on or after the first day the RRP series has a value. RRP carried forward (up to 3 days) is counted; a Wednesday with no RRP value
    in reach is left out and counted. A weekly date that is not a Wednesday raises ValueError."""
    if not rrp:
        raise ValueError("no reverse repo data")
    first_rrp = min(rrp)
    out, stats = {}, {"wednesdays": 0, "rrp_carried": 0, "dropped_no_rrp": 0}
    for w in sorted(set(walcl) & set(wdtgal)):
        if w < first_rrp or (start is not None and w < start):
            continue
        if w.weekday() != 2:
            raise ValueError(f"{w} is not a Wednesday")
        stats["wednesdays"] += 1
        r = rrp.get(w)
        if r is None:
            for back in range(1, RRP_CARRY_DAYS + 1):
                r = rrp.get(w - timedelta(days=back))
                if r is not None:
                    stats["rrp_carried"] += 1
                    break
        if r is None:
            stats["dropped_no_rrp"] += 1
            continue
        out[w] = walcl[w] / 1000.0 - wdtgal[w] / 1000.0 - r
    return out, stats


def validity(L: dict[date, float], stats: dict) -> str | None:
    """None when the data pass the registered checks, else the reason the run is INVALID."""
    ws = sorted(L)
    if not ws:
        return "no net liquidity values in the period used"
    gaps = [(a, b) for a, b in zip(ws, ws[1:]) if (b - a).days != 7]
    if gaps:
        return f"the Wednesday series has a gap: {gaps[0][0]} to {gaps[0][1]}"
    if stats["dropped_no_rrp"]:
        return f"{stats['dropped_no_rrp']} Wednesdays had no reverse repo value within {RRP_CARRY_DAYS} days"
    bad = [w for w in ws if not (L_MIN <= L[w] <= L_MAX)]
    if bad:
        return f"net liquidity outside {L_MIN:.0f} to {L_MAX:.0f} billion on {bad[0]}"
    if stats["wednesdays"] and stats["rrp_carried"] / stats["wednesdays"] > MAX_RRP_CARRY_SHARE:
        return f"reverse repo carried forward on {stats['rrp_carried']} of {stats['wednesdays']} Wednesdays"
    return None


def signal(L: dict[date, float]) -> dict[date, bool]:
    return {w: (v - L[w - timedelta(days=LOOKBACK_DAYS)]) > 0 for w, v in L.items() if (w - timedelta(days=LOOKBACK_DAYS)) in L}


def weight_sequence(dates: list[date], sig: dict[date, bool]) -> tuple[np.ndarray, dict]:
    """w[i] = the weight decided at the close of bar i. It changes only on Fridays, using the signal of the Wednesday two days earlier; a Friday with no signal keeps the previous state (counted). Starts at 0."""
    w = np.zeros(len(dates))
    state = 0.0
    stats = {"fridays": 0, "from_signal": 0, "kept_previous": 0}
    for i, d in enumerate(dates):
        if d.weekday() == 4:
            stats["fridays"] += 1
            s = sig.get(d - timedelta(days=2))
            if s is None:
                stats["kept_previous"] += 1
            else:
                state = 1.0 if s else 0.0
                stats["from_signal"] += 1
        w[i] = state
    return w, stats


def shifted_weights(w: np.ndarray, k: int, weeks: int) -> np.ndarray:
    """A copy of w in which the traded sealed sequence w[k-1 : n-1] is moved circularly by `weeks` whole weeks (clarifications 2 and 3: only its whole-week part moves, the last <7 days stay). Nothing outside it changes."""
    n = len(w)
    whole = ((n - k) // 7) * 7
    out = np.array(w, float)
    out[k - 1:k - 1 + whole] = np.roll(w[k - 1:k - 1 + whole], 7 * weeks)
    return out


def switches(w: np.ndarray, k: int) -> int:
    """Changes of weight between consecutive bars of the traded sealed sequence (the entry from flat is not counted)."""
    return int(np.sum(np.abs(np.diff(w[k - 1:len(w) - 1])) > 0))


def _sim(o, c, w, k) -> dict:
    s = simulate_weights(o, c, w, start=k)
    m = metrics(s["curve"], [], BPY)
    return {"net_return_pct": m["net_return_pct"], "max_drawdown_pct": m["max_drawdown_pct"], "sharpe": m["sharpe"], "mean_weight": s["mean_weight"]}


def _num(x) -> float:
    return float("-inf") if x is None else float(x)


def run(rows, walcl: dict[date, float], wdtgal: dict[date, float], rrp: dict[date, float]) -> dict:
    t = [datetime.fromtimestamp(r[0], timezone.utc).date() for r in rows]
    if any((b - a).days != 1 for a, b in zip(t, t[1:])):
        return {"valid": False, "reason": "the daily bars have a gap"}
    try:
        L, st = net_liquidity(walcl, wdtgal, rrp, start=t[0] - timedelta(days=USED_FROM_DAYS_BEFORE_FIRST_BAR))
    except ValueError as e:
        return {"valid": False, "reason": str(e)}
    why = validity(L, st)
    if why:
        return {"valid": False, "reason": why, "stats": st}
    o, c = np.array([r[1] for r in rows], float), np.array([r[4] for r in rows], float)
    n = len(c)
    k = int(n * IS_FRACTION)
    w, wst = weight_sequence(t, signal(L))
    strat, hold = _sim(o, c, w, k), _sim(o, c, np.ones(n), k)
    const = _sim(o, c, np.full(n, strat["mean_weight"]), k)
    weeks = ((n - k) // 7)
    if weeks - MIN_SHIFT_WEEKS < MIN_SHIFT_WEEKS:
        return {"valid": False, "reason": "the sealed period is too short for the shifted schedules"}
    rng = np.random.default_rng(NULL_SEED)
    shifts = rng.integers(MIN_SHIFT_WEEKS, weeks - MIN_SHIFT_WEEKS + 1, size=NULL_RUNS)
    null, null_sw = [], []
    for m in shifts:
        w2 = shifted_weights(w, k, int(m))
        null.append(_sim(o, c, w2, k))
        null_sw.append(switches(w2, k))
    ns = np.array([_num(x["sharpe"]) for x in null], float)
    p95 = float(np.percentile(ns, 95))
    sw = switches(w, k)
    r3 = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 3)                                                    # noqa: E731
    pack = lambda d: {key: r3(d[key]) for key in ("net_return_pct", "max_drawdown_pct", "sharpe", "mean_weight")}                      # noqa: E731
    s_sh, h_sh, s_dd, h_dd = strat["sharpe"], hold["sharpe"], strat["max_drawdown_pct"], hold["max_drawdown_pct"]
    conds = {"a_sharpe_at_least_0.10_above_hold": s_sh is not None and h_sh is not None and s_sh - h_sh >= PASS_SHARPE_EDGE,
             "b_sharpe_above_95th_pct_of_shifted_schedules": s_sh is not None and s_sh > p95,
             "c_worst_drop_at_least_10_points_shallower": s_dd is not None and h_dd is not None and s_dd - h_dd >= PASS_DROP_EDGE,
             "d_net_return_positive_and_at_least_10_switches": strat["net_return_pct"] is not None and strat["net_return_pct"] > 0 and sw >= MIN_SWITCHES}
    return {"valid": True, "bars": n, "first_bar": t[0].isoformat(), "last_bar": t[-1].isoformat(), "sealed_from_bar": k, "sealed_from": t[k].isoformat(), "sealed_bars": n - k,
            "liquidity_used_from": min(L).isoformat(), "liquidity_last_wednesday": max(L).isoformat(), "liquidity_stats": st, "weight_stats": wst,
            "sealed": {"strategy": pack(strat), "hold": pack(hold), "constant_exposure": pack(const), "switches": sw, "share_of_time_on": r3(strat["mean_weight"])},
            "null": {"runs": NULL_RUNS, "sharpe_median": r3(np.median(ns)), "sharpe_95th": r3(p95), "share_at_or_above_strategy": r3(float(np.mean(ns >= _num(strat["sharpe"])))),
                     "return_median_pct": r3(np.median([_num(x["net_return_pct"]) for x in null])),
                     "switches_min": min(null_sw), "switches_max": max(null_sw)},
            "whole_history_for_context": {"strategy": pack(_sim(o, c, w, 0)), "hold": pack(_sim(o, c, np.ones(n), 0))},
            "conditions": {key: bool(v) for key, v in conds.items()}, "passed": bool(all(conds.values()))}


# ---- live data (command line only) --------------------------------------------------------------------------------------------------------------------------------------------------
def _fred(series: str) -> dict[date, float]:
    import httpx
    from ..fincond import parse
    # No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast.
    r = httpx.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series, "cosd": "2013-01-01"}, timeout=40)
    r.raise_for_status()
    return parse(r.text, series)


async def _main() -> dict:
    from .track_cli import _rows
    rows = await _rows()
    today = datetime.now(timezone.utc).date()
    rows = [r for r in rows if datetime.fromtimestamp(r[0], timezone.utc).date() < today]                                          # complete days only
    return run(rows, _fred("WALCL"), _fred("WDTGAL"), _fred("RRPONTSYD"))


if __name__ == "__main__":
    print(json.dumps(asyncio.run(_main()), indent=1, default=str))
