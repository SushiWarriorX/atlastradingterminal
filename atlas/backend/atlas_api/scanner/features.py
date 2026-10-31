"""Per-symbol scan features from daily bars. Every value is None when it cannot be computed (never guessed)."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .. import indicators as ind
from ..models import Candle
from ..technical import trend as trend_label

# name -> (type, label, unit)
FIELDS: dict[str, tuple[str, str, str]] = {
    "price": ("number", "Price", "$"), "change_pct": ("number", "Change", "%"), "gap_pct": ("number", "Gap", "%"),
    "volume": ("number", "Volume", ""), "avg_volume_20": ("number", "Avg volume (20d)", ""), "rvol": ("number", "Relative volume", "x"),
    "dollar_volume_avg20": ("number", "Avg dollar volume (20d)", "$"), "atr_pct": ("number", "ATR%", "%"),
    "rsi14": ("number", "RSI(14)", ""), "macd_hist": ("number", "MACD histogram", ""),
    "sma20": ("number", "SMA20", "$"), "sma50": ("number", "SMA50", "$"), "sma200": ("number", "SMA200", "$"),
    "above_sma20": ("bool", "Above SMA20", ""), "above_sma50": ("bool", "Above SMA50", ""), "above_sma200": ("bool", "Above SMA200", ""),
    "dist_sma20_pct": ("number", "Distance from SMA20", "%"), "dist_sma50_pct": ("number", "Distance from SMA50", "%"),
    "dist_52w_high_pct": ("number", "Distance from 52w high", "%"), "dist_52w_low_pct": ("number", "Distance from 52w low", "%"),
    "ret_5d": ("number", "Return 5d", "%"), "ret_21d": ("number", "Return 1m", "%"), "ret_63d": ("number", "Return 3m", "%"), "ret_126d": ("number", "Return 6m", "%"),
    "rs_5d": ("number", "Rel. strength 5d vs benchmark", "pp"), "rs_21d": ("number", "Rel. strength 1m vs benchmark", "pp"),
    "rs_63d": ("number", "Rel. strength 3m vs benchmark", "pp"), "rs_126d": ("number", "Rel. strength 6m vs benchmark", "pp"),
    "breakout_20": ("bool", "Close above prior 20d high", ""), "breakdown_20": ("bool", "Close below prior 20d low", ""),
    "bb_width_pct": ("number", "Bollinger width", "%"), "bb_width_pctile": ("number", "Bollinger width percentile (120d)", ""),
    "atr_ratio_20": ("number", "ATR now / ATR 20 bars ago", "x"), "vol_dryup_3d": ("number", "3d avg volume / 20d avg", "x"),
    "consec_up": ("number", "Consecutive up closes", ""), "consec_down": ("number", "Consecutive down closes", ""),
    "trend": ("string", "Trend (MA alignment)", ""), "setup": ("string", "Setup", ""), "sector": ("string", "Sector", ""),
}
MIN_BARS = 60


def _pct(a: float, b: float) -> float | None:
    return None if not b else (a / b - 1) * 100


def _last(x: np.ndarray) -> float | None:
    return None if len(x) == 0 or np.isnan(x[-1]) else float(x[-1])


def _pctile(window: np.ndarray, v: float) -> float:
    w = window[~np.isnan(window)]
    return float((w <= v).sum() / len(w) * 100)


def _streak(close: np.ndarray, up: bool) -> int:
    n = 0
    for i in range(len(close) - 1, 0, -1):
        if (close[i] > close[i - 1]) if up else (close[i] < close[i - 1]):
            n += 1
        else:
            break
    return n


def compute(symbol: str, candles: list[Candle], bench: list[Candle] | None = None, sector: str | None = None) -> dict:
    n = len(candles)
    f: dict = {k: None for k in FIELDS}
    f.update(symbol=symbol, bars=n, sector=sector, last_bar_date=None, sufficient=n >= MIN_BARS)
    if n < 2:
        return f
    c = np.array([x.close for x in candles]); h = np.array([x.high for x in candles])
    l = np.array([x.low for x in candles]); v = np.array([x.volume for x in candles]); o = np.array([x.open for x in candles])
    px, prev = float(c[-1]), float(c[-2])
    f.update(price=px, change_pct=_pct(px, prev), gap_pct=_pct(float(o[-1]), prev), volume=float(v[-1]),
             last_bar_date=datetime.fromtimestamp(candles[-1].time, timezone.utc).date().isoformat())
    if n < MIN_BARS:
        return f  # too little history for anything else: leave the rest None so filters cannot pass
    avg = float(v[-21:-1].mean())
    f["avg_volume_20"] = avg
    f["rvol"] = float(v[-1] / avg) if avg > 0 else None
    f["dollar_volume_avg20"] = float((c[-21:-1] * v[-21:-1]).mean())
    atr = ind.atr(h, l, c, 14)
    f["atr_pct"] = None if np.isnan(atr[-1]) else float(atr[-1] / px * 100)
    f["atr_ratio_20"] = None if np.isnan(atr[-1]) or np.isnan(atr[-21]) or atr[-21] == 0 else float(atr[-1] / atr[-21])
    f["rsi14"] = _last(ind.rsi(c, 14))
    f["macd_hist"] = _last(ind.macd(c)[2])
    for k in (20, 50, 200):
        s = _last(ind.sma(c, k))
        f[f"sma{k}"] = s
        f[f"above_sma{k}"] = None if s is None else bool(px > s)
        if k < 200:
            f[f"dist_sma{k}_pct"] = None if s is None else _pct(px, s)
    hi52, lo52 = float(h[-252:].max()), float(l[-252:].min())
    f["dist_52w_high_pct"], f["dist_52w_low_pct"] = _pct(px, hi52), _pct(px, lo52)
    bret = {}
    for name, d in (("5d", 5), ("21d", 21), ("63d", 63), ("126d", 126)):
        r = _pct(px, float(c[-1 - d])) if n > d else None
        f[f"ret_{name}"] = r
        if bench and len(bench) > d:
            bret[name] = _pct(bench[-1].close, bench[-1 - d].close)
        f[f"rs_{name}"] = None if r is None or bret.get(name) is None else r - bret[name]
    hi20, lo20 = float(h[-21:-1].max()), float(l[-21:-1].min())
    f["breakout_20"], f["breakdown_20"] = bool(px > hi20), bool(px < lo20)
    lo, mid, up = ind.bollinger(c, 20, 2.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        width = (up - lo) / mid * 100
    if not np.isnan(width[-1]):
        f["bb_width_pct"] = float(width[-1])
        win = width[-120:]
        if (~np.isnan(win)).sum() >= 60:
            f["bb_width_pctile"] = _pctile(win, float(width[-1]))
    f["vol_dryup_3d"] = float(v[-3:].mean() / avg) if avg > 0 else None
    f["consec_up"], f["consec_down"] = _streak(c, True), _streak(c, False)
    f["trend"] = trend_label(candles)["label"]
    f["setup"] = setup(f)
    return f


def setup(f: dict) -> str:
    """Deterministic setup label. These are conditions, not predictions."""
    def g(k, d=None):
        return f.get(k) if f.get(k) is not None else d
    if f.get("breakout_20") and g("rvol", 0) >= 1.5:
        return "Breakout"
    if f.get("breakdown_20") and g("rvol", 0) >= 1.5:
        return "Breakdown"
    if f.get("trend") == "bullish" and g("ret_5d", 0) < 0 and abs(g("dist_sma20_pct", 99)) <= 3:
        return "Pullback"
    if g("bb_width_pctile", 100) <= 20:
        return "Compression"
    if g("rvol", 0) >= 2:
        return "Unusual volume"
    if g("rsi14", 50) <= 30:
        return "Oversold"
    if g("rsi14", 50) >= 70:
        return "Overbought"
    return "—"
