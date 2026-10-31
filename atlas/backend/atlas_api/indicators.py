"""Deterministic technical indicators (numpy). Warm-up values are NaN, never guessed.

Conventions (match common charting platforms):
- EMA seeded with the SMA of the first `n` values.
- RSI/ATR use Wilder smoothing seeded with a simple average.
- Bollinger uses population standard deviation (ddof=0).
- VWAP is cumulative per UTC day from typical price (H+L+C)/3.
"""
from __future__ import annotations

import numpy as np

from .models import Candle

NaN = np.nan


def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def sma(x, n: int) -> np.ndarray:
    x = _arr(x)
    out = np.full(len(x), NaN)
    if n <= 0 or len(x) < n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def ema(x, n: int) -> np.ndarray:
    x = _arr(x)
    out = np.full(len(x), NaN)
    if n <= 0 or len(x) < n:
        return out
    k = 2 / (n + 1)
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def _wilder(x: np.ndarray, n: int, start: int) -> np.ndarray:
    """Wilder smoothing of x[start:], seeded with mean of the first n values from `start`."""
    out = np.full(len(x), NaN)
    if len(x) < start + n:
        return out
    out[start + n - 1] = x[start:start + n].mean()
    for i in range(start + n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def rsi(close, n: int = 14) -> np.ndarray:
    c = _arr(close)
    out = np.full(len(c), NaN)
    if len(c) <= n:
        return out
    d = np.diff(c, prepend=NaN)
    gain, loss = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    ag, al = _wilder(gain, n, 1), _wilder(loss, n, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
        out = np.where(al == 0, 100.0, 100 - 100 / (1 + rs))
    out[: n] = NaN
    return out


def true_range(high, low, close) -> np.ndarray:
    h, l, c = _arr(high), _arr(low), _arr(close)
    pc = np.insert(c[:-1], 0, NaN)
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    tr[0] = h[0] - l[0]
    return tr


def atr(high, low, close, n: int = 14) -> np.ndarray:
    return _wilder(true_range(high, low, close), n, 0)


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    c = _arr(close)
    line = ema(c, fast) - ema(c, slow)
    sig = np.full(len(c), NaN)
    valid = ~np.isnan(line)
    if valid.sum() >= signal:
        first = int(np.argmax(valid))
        sig[first:] = ema(line[first:], signal)
    return line, sig, line - sig


def bollinger(close, n: int = 20, k: float = 2.0):
    c = _arr(close)
    mid = sma(c, n)
    sd = np.full(len(c), NaN)
    if len(c) >= n:
        sd[n - 1:] = np.lib.stride_tricks.sliding_window_view(c, n).std(axis=1)   # population std per window, same values as a loop
    return mid - k * sd, mid, mid + k * sd


def vwap(candles: list[Candle]) -> np.ndarray:
    out = np.full(len(candles), NaN)
    pv = v = 0.0
    day = None
    for i, c in enumerate(candles):
        d = c.time // 86400
        if d != day:
            day, pv, v = d, 0.0, 0.0
        pv += (c.high + c.low + c.close) / 3 * c.volume
        v += c.volume
        out[i] = pv / v if v > 0 else NaN
    return out


def rvol(volume, n: int = 20) -> np.ndarray:
    """Volume relative to the mean of the previous n bars (excludes the current bar)."""
    v = _arr(volume)
    base = np.insert(sma(v, n)[:-1], 0, NaN)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(base > 0, v / base, NaN)


def compute(candles: list[Candle], specs: list[str]) -> dict[str, list[float | None]]:
    """specs like 'sma:20', 'ema:21', 'rsi:14', 'atr:14', 'macd', 'bb:20:2', 'vwap', 'rvol:20'."""
    close = [c.close for c in candles]
    out: dict[str, np.ndarray] = {}
    for spec in specs:
        name, *args = spec.lower().split(":")
        a = [float(x) for x in args]
        if name == "sma":
            out[spec] = sma(close, int(a[0]))
        elif name == "ema":
            out[spec] = ema(close, int(a[0]))
        elif name == "rsi":
            out[spec] = rsi(close, int(a[0]) if a else 14)
        elif name == "atr":
            out[spec] = atr([c.high for c in candles], [c.low for c in candles], close, int(a[0]) if a else 14)
        elif name == "macd":
            l, s, h = macd(close, *(int(x) for x in a)) if a else macd(close)
            out[f"{spec}:line"], out[f"{spec}:signal"], out[f"{spec}:hist"] = l, s, h
        elif name == "bb":
            lo, mid, up = bollinger(close, int(a[0]) if a else 20, a[1] if len(a) > 1 else 2.0)
            out[f"{spec}:lower"], out[f"{spec}:mid"], out[f"{spec}:upper"] = lo, mid, up
        elif name == "vwap":
            out[spec] = vwap(candles)
        elif name == "rvol":
            out[spec] = rvol([c.volume for c in candles], int(a[0]) if a else 20)
        else:
            raise ValueError(f"unknown indicator: {spec}")
    return {k: [None if np.isnan(x) else float(x) for x in v] for k, v in out.items()}
