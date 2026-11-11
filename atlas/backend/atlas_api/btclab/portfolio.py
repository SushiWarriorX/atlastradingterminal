"""Multi-asset portfolio simulator and the cross-sectional momentum rule for the Strategy Lab (EDGE_PLAN experiment 2).

Timing matches the rest of the lab: target weights are decided at a close (row t of the weights array) and traded at the NEXT open. For each coin a day's return is the overnight move to the open held at the old
(drifted) weight, then the trade at the open, then the open-to-close move at the new weight. Costs are charged on the amount traded: rate * sum(|new weight - drifted weight|). A row of NaN means "do not trade":
the weights simply drift. Cash earns nothing. A held coin with no price on a day contributes a zero return that day (counted and reported, never invented).
"""
from __future__ import annotations

import numpy as np


def simulate_portfolio(o, c, targets, fee_bps: float = 10.0, slippage_bps: float = 10.0) -> dict:
    """o, c: days x coins arrays (NaN = no bar). targets: days x coins; targets[t] is decided at the close of day t and traded at the open of day t+1; an all-NaN row means no trade."""
    o, c, tg = np.asarray(o, float), np.asarray(c, float), np.asarray(targets, float)
    T, N = c.shape
    rate = (fee_bps + slippage_bps) / 1e4
    w = np.zeros(N)                                                   # weights actually held going into the day (fractions of equity; the rest is cash)
    eq, curve, traded, missing = 1.0, [1.0], 0.0, 0
    exposure = []
    for j in range(T):
        gap = np.zeros(N)
        day = np.zeros(N)
        if j > 0:
            ok = ~np.isnan(o[j]) & ~np.isnan(c[j - 1])
            gap[ok] = o[j][ok] / c[j - 1][ok] - 1.0
            missing += int(((w > 0) & ~ok).sum())
        okd = ~np.isnan(o[j]) & ~np.isnan(c[j])
        day[okd] = c[j][okd] / o[j][okd] - 1.0
        growth = 1.0 + float(np.sum(w * gap))
        eq *= growth
        drift = w * (1.0 + gap) / growth if growth > 0 else np.zeros(N)
        want = tg[j - 1] if j > 0 else np.full(N, np.nan)
        if np.isnan(want).all():
            new = drift                                               # no trade today
        else:
            new = np.where(np.isnan(want), 0.0, want)
            new = np.where(np.isnan(o[j]), drift, new)                # a coin with no open today cannot be traded: its weight stays as it was
            cost = float(np.abs(new - drift).sum()) * rate
            eq *= 1.0 - cost
            traded += float(np.abs(new - drift).sum())
        growth2 = 1.0 + float(np.sum(new * day))
        eq *= growth2
        w = new * (1.0 + day) / growth2 if growth2 > 0 else np.zeros(N)
        curve.append(eq)
        exposure.append(float(new.sum()))
    return {"curve": curve, "turnover": traded, "mean_exposure": float(np.mean(exposure)) if exposure else 0.0, "missing_coin_days": missing}


def eligible_mask(c, lookback: int) -> np.ndarray:
    """eligible[t, i] is True when coin i has a bar on every one of the last lookback+1 days up to and including t. Uses bars <= t only."""
    c = np.asarray(c, float)
    T, N = c.shape
    ok = np.zeros((T, N), bool)
    has = ~np.isnan(c)
    for t in range(lookback, T):
        ok[t] = has[t - lookback:t + 1].all(axis=0)
    return ok


def momentum_targets(c, lookback: int = 90, k: int = 5, every: int = 7, min_eligible: int = 10, pick: str = "momentum", seed: int | None = None) -> np.ndarray:
    """Target weights decided at each rebalance close; NaN rows elsewhere. pick: 'momentum' (top k by lookback return), 'random' (k random eligible coins), 'all' (every eligible coin, equal weight).
    Fewer than min_eligible eligible coins means cash (all-zero row). Rebalance days are every `every`-th day counted from the first day with enough eligible coins. Uses bars <= t only."""
    c = np.asarray(c, float)
    T, N = c.shape
    ok = eligible_mask(c, lookback)
    out = np.full((T, N), np.nan)
    rng = np.random.default_rng(seed) if pick == "random" else None
    first = next((t for t in range(T) if ok[t].sum() >= min_eligible), None)
    if first is None:
        return out
    for t in range(first, T, every):
        elig = np.flatnonzero(ok[t])
        row = np.zeros(N)
        if len(elig) >= min_eligible:
            if pick == "all":
                chosen = elig
            elif pick == "random":
                chosen = rng.choice(elig, size=min(k, len(elig)), replace=False)
            else:
                ret = c[t, elig] / c[t - lookback, elig] - 1.0
                chosen = elig[np.argsort(-ret, kind="stable")[:k]]
            row[chosen] = 1.0 / len(chosen)
        out[t] = row
    return out
