"""Fractional exposure for the Strategy Lab: a simulator for rules that hold a FRACTION of the account in BTC (for example scaled down when volatility is high), which the whole-position engine cannot do.

Timing is the same as everywhere else in the lab: the weight for bar j is decided at the close of bar j-1 (using bars up to that close only) and traded at the OPEN of bar j. A bar's return is therefore
  w_old * (open_j / close_{j-1} - 1)   (the old weight, held overnight)
then the trade to the new weight at the open, which pays fee + slippage on the amount traded, then
  w_new * (close_j / open_j - 1)       (the new weight, held through the day).
Between rebalances the weight drifts with price (a weight of 0.5 becomes slightly more or less than 0.5); the trade at the open is measured from that drifted weight, so keeping a constant weight is not free.
The rest of the account is cash earning nothing (stated, not hidden: it makes every low-exposure result slightly worse than if cash earned a bill rate).
"""
from __future__ import annotations

import numpy as np


def vol_target_weights(close, window: int = 20, target_ann: float = 0.40, cap: float = 1.0, bpy: int = 365) -> np.ndarray:
    """w[i] = min(cap, target / annualised volatility of the last `window` daily returns up to and including bar i). 0 until `window` returns exist or when volatility is zero. Uses bars <= i only."""
    c = np.asarray(close, float)
    n = len(c)
    w = np.zeros(n)
    if n <= window:
        return w
    r = c[1:] / c[:-1] - 1.0
    for i in range(window, n):                                  # returns r[i-window:i] end with the return into bar i
        sd = float(np.std(r[i - window:i], ddof=1))
        vol = sd * np.sqrt(bpy)
        w[i] = min(cap, target_ann / vol) if vol > 0 else 0.0
    return w


def simulate_weights(o, c, weights, fee_bps: float = 5.0, slippage_bps: float = 5.0, start: int = 0, end: int | None = None) -> dict:
    """Equity curve (starting at 1.0 at `start`) for target weights decided at each close and applied from the next open. weights[i] is the weight decided at the close of bar i."""
    o, c, wt = np.asarray(o, float), np.asarray(c, float), np.asarray(weights, float)
    end = len(c) if end is None else end
    rate = (fee_bps + slippage_bps) / 1e4
    eq, w = 1.0, 0.0                                              # w is the weight actually held going into the bar
    curve, held, traded = [1.0], [], 0.0
    for j in range(start, end):
        target = wt[j - 1] if j > 0 else 0.0
        gap = o[j] / c[j - 1] - 1.0 if j > 0 else 0.0
        eq *= 1.0 + w * gap                                       # old weight held overnight up to the open
        w_drift = w * (1.0 + gap) / (1.0 + w * gap) if (1.0 + w * gap) > 0 else 0.0
        cost = abs(target - w_drift) * rate
        eq *= 1.0 - cost
        traded += abs(target - w_drift)
        day = c[j] / o[j] - 1.0
        eq *= 1.0 + target * day
        w = target * (1.0 + day) / (1.0 + target * day) if (1.0 + target * day) > 0 else 0.0
        curve.append(eq)
        held.append(target)
    return {"curve": curve, "mean_weight": float(np.mean(held)) if held else 0.0, "turnover": traded, "bars": end - start}
