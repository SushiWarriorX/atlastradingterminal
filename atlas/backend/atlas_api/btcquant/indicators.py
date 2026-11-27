"""Indicators for the btcquant strategies, as plain numpy functions of completed candles. Every value at index i uses candles 0..i only (a test perturbs later candles to prove it).
Warm-up values are NaN, never filled. Conventions are fixed by the protocol (section 5): Wilder smoothing (RMA, alpha 1/n, seeded with the simple average of the first n values) for ATR, RSI and ADX;
population standard deviation (ddof 0) for Bollinger bands; sample standard deviation (ddof 1) times sqrt(365) for realised volatility.
"""
from __future__ import annotations

import numpy as np

from . import config as C


def _a(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def sma(x, n: int) -> np.ndarray:
    x = _a(x)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def rolling_std(x, n: int, ddof: int = 0) -> np.ndarray:
    x = _a(x)
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.std(x[i - n + 1:i + 1], ddof=ddof)
    return out


def rolling_max(x, n: int) -> np.ndarray:
    """Highest of x[i-n+1..i], including the current value."""
    x = _a(x)
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.max(x[i - n + 1:i + 1])
    return out


def rolling_min(x, n: int) -> np.ndarray:
    x = _a(x)
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.min(x[i - n + 1:i + 1])
    return out


def prior(x, k: int = 1) -> np.ndarray:
    """x shifted later by k: value at i is x[i-k] (NaN at the start). Used to exclude the current candle from a channel."""
    x = _a(x)
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[:-k]
    return out


def change(x, n: int) -> np.ndarray:
    """x[i] / x[i-n] - 1."""
    x = _a(x)
    out = np.full(len(x), np.nan)
    if n < len(x):
        out[n:] = x[n:] / x[:-n] - 1.0
    return out


def wilder(x, n: int, first: int = 0) -> np.ndarray:
    """Wilder's moving average: seeded at index first+n-1 with the simple average of x[first..first+n-1], then (previous * (n-1) + x[i]) / n. NaN before the seed."""
    x = _a(x)
    out = np.full(len(x), np.nan)
    if len(x) < first + n:
        return out
    out[first + n - 1] = np.mean(x[first:first + n])
    for i in range(first + n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def true_range(h, l, c) -> np.ndarray:
    h, l, c = _a(h), _a(l), _a(c)
    tr = h - l
    if len(c) > 1:
        tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
    return tr


def atr(h, l, c, n: int = C.ATR_N) -> np.ndarray:
    return wilder(true_range(h, l, c), n)


def rsi(c, n: int) -> np.ndarray:
    """Wilder's RSI. First value at index n. 100 when there were no losses and some gains, 50 when nothing moved."""
    c = _a(c)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    gain, loss = np.maximum(d, 0.0), np.maximum(-d, 0.0)
    ag, al = wilder(gain, n), wilder(loss, n)                     # index j of these is for the change into candle j+1
    for j in range(n - 1, len(d)):
        g, ls = ag[j], al[j]
        out[j + 1] = (100.0 if g > 0 else 50.0) if ls == 0 else 100.0 - 100.0 / (1.0 + g / ls)
    return out


def adx(h, l, c, n: int = 14) -> np.ndarray:
    """Wilder's ADX. +DM, -DM and the true range are smoothed with Wilder's average; DX = 100 |+DI - -DI| / (+DI + -DI); ADX is Wilder's average of DX. First value at index 2n-1."""
    h, l, c = _a(h), _a(l), _a(c)
    m = len(c)
    out = np.full(m, np.nan)
    if m < 2 * n:
        return out
    up, down = h[1:] - h[:-1], l[:-1] - l[1:]
    pdm = np.where((up > down) & (up > 0), up, 0.0)
    mdm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(h, l, c)[1:]
    spdm, smdm, str_ = wilder(pdm, n), wilder(mdm, n), wilder(tr, n)          # index j is for candle j+1
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi, mdi = 100.0 * spdm / str_, 100.0 * smdm / str_
        dx = 100.0 * np.abs(pdi - mdi) / (pdi + mdi)
    dx = np.where(np.isfinite(dx), dx, 0.0)
    dx[:n - 1] = np.nan                                                          # no DX before the first smoothed value
    adx_ = np.full(len(dx), np.nan)
    first = n - 1
    if len(dx) >= first + n:
        adx_[first + n - 1] = np.mean(dx[first:first + n])
        for j in range(first + n, len(dx)):
            adx_[j] = (adx_[j - 1] * (n - 1) + dx[j]) / n
    out[1:] = adx_
    return out


def bollinger(c, n: int, k: float):
    """(lower, middle, upper): the simple average and k population standard deviations around it."""
    mid, sd = sma(c, n), rolling_std(c, n, ddof=0)
    return mid - k * sd, mid, mid + k * sd


def realized_vol(c, window: int, per_year: int = C.DAYS_PER_YEAR) -> np.ndarray:
    """Annualised volatility: sample standard deviation of the last `window` daily returns (the return into candle i is the newest) times sqrt(per_year). First value at index `window`."""
    c = _a(c)
    out = np.full(len(c), np.nan)
    if len(c) <= window:
        return out
    r = c[1:] / c[:-1] - 1.0
    for i in range(window, len(c)):
        out[i] = np.std(r[i - window:i], ddof=1) * np.sqrt(per_year)
    return out
