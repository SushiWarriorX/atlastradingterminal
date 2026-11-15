"""btcquant performance metrics (protocol section 6), all after costs, computed from an account's daily equity curve and its closed trades.

Conventions, fixed in advance:
- One equity mark per completed daily candle, at its close. The first daily return is measured from the starting equity.
- Sharpe: mean daily return over the sample standard deviation (ddof 1), times sqrt(365), risk-free rate zero. Sortino: mean daily return over the downside deviation
  (square root of the mean of the squared negative returns, over ALL days), times sqrt(365). A ratio whose denominator is zero is None (undefined), never 0 and never infinite.
- Maximum drawdown is a positive fraction measured from the running peak of the daily equity marks (the starting equity counts as the first peak).
- CAGR compounds over days/365. Calmar = CAGR / maximum drawdown.
- A trade is a position taken from flat back to flat (a stop, a signal exit or the circuit breaker). Profit factor = total profit of winning trades / total loss of losing trades (None when there is no losing trade).
  Average holding period is in days (candles held). Turnover = notional traded on both sides / average daily equity.
- Exposure = the average share of equity held in Bitcoin, over every day of the period (zero on days spent in cash).
- Regimes (from information known at the time): BULL when the close is above SMA_200 and SMA_200 is higher than 20 days earlier, BEAR when the close is below SMA_200 and SMA_200 is lower than 20 days earlier, otherwise RANGE.
  A day's return belongs to the regime in force at the previous close (the position held that day was decided then).
- Exposure-matched hold: a constant share of equity in Bitcoin (the strategy's average exposure), rebalanced every day at the same fee and slippage, bought at the first open. It answers "is this better than simply being invested that much?".
"""
from __future__ import annotations

import math

import numpy as np

from . import config as C

REGIMES = ("BULL", "BEAR", "RANGE")
TINY = 1e-15


def _a(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def daily_returns(equity, start: float) -> np.ndarray:
    """Return of each daily mark: the first against the starting equity, then against the previous mark."""
    e = _a(equity)
    if len(e) == 0:
        return e
    prev = np.concatenate([[start], e[:-1]])
    return e / prev - 1.0


def sharpe(r, per_year: int = C.DAYS_PER_YEAR) -> float | None:
    r = _a(r)
    if len(r) < 2:
        return None
    sd = float(np.std(r, ddof=1))
    if sd < TINY:
        return None
    return float(np.mean(r) / sd * math.sqrt(per_year))


def sortino(r, per_year: int = C.DAYS_PER_YEAR) -> float | None:
    r = _a(r)
    if len(r) < 2:
        return None
    down = math.sqrt(float(np.mean(np.minimum(r, 0.0) ** 2)))
    if down < TINY:
        return None
    return float(np.mean(r) / down * math.sqrt(per_year))


def max_drawdown(equity, start: float) -> float:
    """Largest fall from a running peak as a positive fraction (0.2 means 20% below the peak). The starting equity is the first peak."""
    e = np.concatenate([[start], _a(equity)])
    peak = np.maximum.accumulate(e)
    return float(np.max(1.0 - e / peak))


def total_return(final: float, start: float) -> float:
    return final / start - 1.0


def cagr(final: float, start: float, days: int, per_year: int = C.DAYS_PER_YEAR) -> float | None:
    if days <= 0 or final <= 0 or start <= 0:
        return None
    return float((final / start) ** (per_year / days) - 1.0)


def calmar(cagr_value: float | None, drawdown: float) -> float | None:
    if cagr_value is None or drawdown < TINY:
        return None
    return float(cagr_value / drawdown)


def trade_stats(trades: list) -> dict:
    """Statistics of closed trades. Each trade carries its net profit in dollars (after fees and slippage), its net return and the candles held."""
    n = len(trades)
    out = {"trades": n, "win_rate": None, "avg_win": None, "avg_loss": None, "avg_win_pct": None, "avg_loss_pct": None, "profit_factor": None,
           "expectancy": None, "expectancy_pct": None, "avg_holding_days": None, "best_trade": None, "profit_without_best": None}
    if n == 0:
        return out
    pnl = np.array([t["net_pnl"] for t in trades], dtype=float)
    ret = np.array([t["ret"] for t in trades], dtype=float)
    win, loss = pnl > 0, pnl < 0
    out["win_rate"] = float(np.mean(win))
    if win.any():
        out["avg_win"], out["avg_win_pct"] = float(pnl[win].mean()), float(ret[win].mean())
    if loss.any():
        out["avg_loss"], out["avg_loss_pct"] = float(-pnl[loss].mean()), float(-ret[loss].mean())           # shown as positive magnitudes
        out["profit_factor"] = float(pnl[win].sum() / -pnl[loss].sum())
    out["expectancy"], out["expectancy_pct"] = float(pnl.mean()), float(ret.mean())
    out["avg_holding_days"] = float(np.mean([t["bars"] for t in trades]))
    out["best_trade"] = float(pnl.max())
    out["profit_without_best"] = float(pnl.sum() - pnl.max())                                              # total net profit if the single best trade had not happened
    return out


def regime_labels(close, sma200, lookback: int = 20) -> list:
    """BULL / BEAR / RANGE for each candle from the close and its 200-day average; None while either the average or the average `lookback` days earlier does not exist yet."""
    c, s = _a(close), _a(sma200)
    out: list = [None] * len(c)
    for i in range(lookback, len(c)):
        if not (math.isfinite(s[i]) and math.isfinite(s[i - lookback])):
            continue
        if c[i] > s[i] and s[i] > s[i - lookback]:
            out[i] = "BULL"
        elif c[i] < s[i] and s[i] < s[i - lookback]:
            out[i] = "BEAR"
        else:
            out[i] = "RANGE"
    return out


def by_regime(strategy_returns, btc_returns, exposure, labels) -> dict:
    """Per regime: days, the strategy's compounded return, Bitcoin's compounded return over the same days, the average exposure and the Sharpe ratio (None under 30 days). `labels[i]` is the regime in force at the previous close."""
    sr, br, ex = _a(strategy_returns), _a(btc_returns), _a(exposure)
    out = {}
    for name in REGIMES:
        m = np.array([lab == name for lab in labels], dtype=bool)
        k = int(m.sum())
        out[name] = {"days": k,
                     "strategy_return": float(np.prod(1.0 + sr[m]) - 1.0) if k else None,
                     "btc_return": float(np.prod(1.0 + br[m]) - 1.0) if k else None,
                     "exposure": float(ex[m].mean()) if k else None,
                     "sharpe": sharpe(sr[m]) if k >= 30 else None}
    out["unknown"] = int(sum(lab is None for lab in labels))
    return out


def matched_hold(opens, closes, weight: float, start: float, fee: float = C.FEE, slip: float = C.SLIPPAGE) -> list:
    """Equity marks of holding a constant `weight` of equity in Bitcoin, bought at the first open and rebalanced after every close at the same fee and slippage. The first day runs from the open to the close."""
    o, c = _a(opens), _a(closes)
    cost = fee + slip
    eq = start
    w_now = 0.0
    marks = []
    for i in range(len(c)):
        buy = abs(weight - w_now) * eq                                  # trade to the target weight at today's open (the first day buys it; later days start from the target again)
        eq -= buy * cost
        base = o[i] if i == 0 else c[i - 1]
        grow = c[i] / base
        eq *= 1.0 - weight + weight * grow
        w_now = weight * grow / (1.0 - weight + weight * grow)         # weight after the day's move, before the next rebalance
        marks.append(eq)
    return marks


def compute(curve, trades, *, start_equity: float, fees_paid: float, slip_paid: float, traded: float, fills: int = 0, breaker_trips: int = 0, open_position: bool = False,
            hold_return: float | None = None, matched_return: float | None = None, labels=None, btc_returns=None) -> dict:
    """All of protocol section 6 for one account over one period. `curve` rows are (t, equity, exposure, cash, qty, close), one per completed daily candle."""
    n = len(curve)
    eq = [row[1] for row in curve]
    final = eq[-1] if n else start_equity
    r = daily_returns(eq, start_equity)
    dd = max_drawdown(eq, start_equity)
    g = cagr(final, start_equity, n)
    avg_eq = float(np.mean(eq)) if n else start_equity
    expo = float(np.mean([row[2] for row in curve])) if n else 0.0
    years = n / C.DAYS_PER_YEAR if n else 0.0
    out = {"days": n, "start_equity": start_equity, "final_equity": final, "total_return": total_return(final, start_equity), "cagr": g, "max_drawdown": dd,
           "sharpe": sharpe(r), "sortino": sortino(r), "calmar": calmar(g, dd),
           "turnover": traded / avg_eq if avg_eq else None, "turnover_per_year": (traded / avg_eq / years) if (avg_eq and years) else None,
           "exposure": expo, "fees_paid": fees_paid, "slippage_paid": slip_paid, "fills": fills, "breaker_trips": breaker_trips, "open_position_at_end": open_position}
    out.update(trade_stats(trades))
    if hold_return is not None:
        out["hold_return"], out["vs_hold"] = hold_return, out["total_return"] - hold_return
    if matched_return is not None:
        out["matched_hold_return"], out["vs_matched_hold"] = matched_return, out["total_return"] - matched_return
    if labels is not None and btc_returns is not None:
        out["by_regime"] = by_regime(r, btc_returns, [row[2] for row in curve], labels)
    return out
