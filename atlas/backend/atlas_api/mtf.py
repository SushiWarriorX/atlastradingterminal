"""Multi-timeframe analysis and the transparent technical score. Pure functions on candle lists.

Every classification is a stated rule over computed values. Nothing here predicts; labels describe current structure.
Rules (also returned to the UI as `rules`):
- trend: MA alignment (close vs SMA50 vs SMA200; SMA50 only when <200 bars)
- structure: last two confirmed fractal swing highs and lows (k bars each side). HH+HL = uptrend, LH+LL = downtrend, else range.
- event: close beyond the latest swing high/low. With the structure: continuation = break of structure (BOS);
         against the structure = change of character (CHoCH).
"""
from __future__ import annotations

import numpy as np

from . import indicators as ind
from . import technical
from .models import Candle

TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"]
TF_WEIGHT = {"1w": 0.30, "1d": 0.30, "4h": 0.20, "1h": 0.10, "15m": 0.10}
LABEL = {"bullish": 1.0, "mixed": 0.0, "bearish": -1.0, "range": 0.0, "uptrend": 1.0, "downtrend": -1.0}
DEFAULT_WEIGHTS = {"trend": 0.25, "structure": 0.20, "momentum": 0.20, "volume": 0.10, "relative_strength": 0.25, "volatility": 0.0}
RULES = {
    "trend": "Per timeframe: bullish if close > SMA50 > SMA200, bearish if close < SMA50 < SMA200, else mixed. Weighted 1w .30, 1d .30, 4h .20, 1h .10, 15m .10.",
    "structure": "Per timeframe: uptrend (HH+HL) +1, downtrend (LH+LL) -1, range 0, same timeframe weights.",
    "momentum": "Mean of: (daily RSI14 - 50) / 25 clipped to [-1, 1]; sign of the daily MACD histogram; sign of the 1h MACD histogram (those available).",
    "volume": "Daily: if RVOL > 1, sign(daily change) * min(RVOL - 1, 1), else 0. Uses the last completed daily bar.",
    "relative_strength": "63-observation return minus the benchmark's over calendar-aligned daily bars, / 20pp, clipped to [-1, 1]. Unavailable without a benchmark.",
    "volatility": "Context only (daily ATR%). Weight 0 by default: volatility has no direction.",
}


def completed(candles: list[Candle], seconds: int, now_ts: float) -> list[Candle]:
    return candles[:-1] if candles and candles[-1].time + seconds > now_ts else candles


def structure(candles: list[Candle], k: int = 3) -> dict:
    hi, lo = technical.swings(candles, k)
    base = {"k": k, "swing_highs": len(hi), "swing_lows": len(lo)}
    if len(hi) < 2 or len(lo) < 2:
        return {**base, "label": "insufficient_data", "event": None}
    h1, h2 = candles[hi[-2]].high, candles[hi[-1]].high
    l1, l2 = candles[lo[-2]].low, candles[lo[-1]].low
    label = "uptrend" if h2 > h1 and l2 > l1 else "downtrend" if h2 < h1 and l2 < l1 else "range"
    close = candles[-1].close
    event = None
    if close > h2:
        event = "BOS bullish" if label == "uptrend" else "CHoCH bullish" if label == "downtrend" else "breakout above range high"
    elif close < l2:
        event = "BOS bearish" if label == "downtrend" else "CHoCH bearish" if label == "uptrend" else "breakdown below range low"
    return {**base, "label": label, "event": event, "last_swing_high": h2, "prior_swing_high": h1, "last_swing_low": l2, "prior_swing_low": l1,
            "derivation": f"swing highs {h1:g}->{h2:g}, swing lows {l1:g}->{l2:g}; swing = bar whose high/low beats {k} bars each side"}


def analyze_tf(candles: list[Candle], interval: str, seconds: int, now_ts: float, k: int = 3, equity_tz: bool = False) -> dict:
    c = completed(candles, seconds, now_ts)
    if len(c) < 30:
        return {"interval": interval, "available": False, "reason": f"only {len(c)} completed bars (need 30)"}
    close = [x.close for x in c]
    t = technical.trend(c)
    rsi = ind.rsi(close, 14)[-1]
    hist = ind.macd(close)[2][-1]
    atr = ind.atr([x.high for x in c], [x.low for x in c], close, 14)[-1]
    rv = ind.rvol([x.volume for x in c], 20)[-1] if any(x.volume > 0 for x in c) else float("nan")
    lv = technical.key_levels(c, interval, equity_tz=equity_tz)
    px = close[-1]
    sup = max((l.price for l in lv if l.price < px), default=None)
    res = min((l.price for l in lv if l.price > px), default=None)
    f = lambda x: None if x is None or np.isnan(x) else float(x)
    return {"interval": interval, "available": True, "bars": len(c), "last_close": px, "last_bar_time": c[-1].time,
            "trend": t["label"], "trend_factors": t["factors"], "structure": structure(c, k),
            "rsi14": f(rsi), "macd_hist": f(hist), "atr_pct": f(atr / px * 100), "rvol": f(rv),
            "change_pct": (px / close[-2] - 1) * 100,
            "nearest_support": sup, "nearest_resistance": res}


def alignment(tfs: list[dict]) -> dict:
    """Deterministic verdict from trend labels. Counts include only available timeframes."""
    av = [t for t in tfs if t["available"]]
    lab = {t["interval"]: t["trend"] for t in av}
    n = len(av)
    bull = [i for i, v in lab.items() if v == "bullish"]
    bear = [i for i, v in lab.items() if v == "bearish"]
    if n == 0:
        return {"verdict": "no data", "text": "No timeframe had enough data.", "bullish": [], "bearish": [], "available": 0}
    high, low = [i for i in ("1w", "1d") if i in lab], [i for i in ("4h", "1h", "15m") if i in lab]
    if len(bull) == n and n >= 3:
        v, text = "aligned bullish", "All available timeframes are bullish."
    elif len(bear) == n and n >= 3:
        v, text = "aligned bearish", "All available timeframes are bearish."
    elif high and all(lab[i] == "bullish" for i in high) and low and not all(lab[i] == "bullish" for i in low):
        v, text = "bullish higher timeframes, short-term unconfirmed", "Higher timeframes are bullish but short-term confirmation is incomplete (" + ", ".join(f"{i} {lab[i]}" for i in low) + ")."
    elif high and all(lab[i] == "bearish" for i in high) and low and not all(lab[i] == "bearish" for i in low):
        v, text = "bearish higher timeframes, short-term unconfirmed", "Higher timeframes are bearish but short-term confirmation is incomplete (" + ", ".join(f"{i} {lab[i]}" for i in low) + ")."
    elif bull and bear:
        v, text = "conflicting", f"Timeframes disagree: bullish {', '.join(bull)}; bearish {', '.join(bear)}."
    else:
        v, text = "mixed", "No clear alignment across timeframes."
    return {"verdict": v, "text": text, "bullish": bull, "bearish": bear, "available": n, "of": len(tfs),
            "note": "Describes current trend labels only; it is not a forecast."}


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def score(tfs: list[dict], rs_pp: float | None, weights: dict[str, float] | None = None) -> dict:
    """Transparent tilt in [-1, 1] mapped to 0-100 (50 = neutral). Unavailable factors are EXCLUDED and the remaining weights are
    renormalised (shown), never imputed. A tilt summarises current conditions; it is not a probability of profit."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    by = {t["interval"]: t for t in tfs if t["available"]}
    factors: dict[str, dict] = {}

    def tf_mean(key):
        num = den = 0.0
        for i, wt in TF_WEIGHT.items():
            if i in by:
                lbl = by[i]["trend"] if key == "trend" else by[i]["structure"]["label"]
                if lbl in LABEL:
                    num += wt * LABEL[lbl]
                    den += wt
        return (num / den, {i: (by[i]["trend"] if key == "trend" else by[i]["structure"]["label"]) for i in TF_WEIGHT if i in by}) if den else (None, {})

    for key in ("trend", "structure"):
        v, d = tf_mean(key)
        factors[key] = {"value": v, "inputs": d}
    parts, inputs = [], {}
    d = by.get("1d")
    if d and d["rsi14"] is not None:
        parts.append(_clip((d["rsi14"] - 50) / 25)); inputs["1d RSI14"] = d["rsi14"]
    for i in ("1d", "1h"):
        if i in by and by[i]["macd_hist"] is not None:
            parts.append(1.0 if by[i]["macd_hist"] > 0 else -1.0 if by[i]["macd_hist"] < 0 else 0.0); inputs[f"{i} MACD hist"] = by[i]["macd_hist"]
    factors["momentum"] = {"value": float(np.mean(parts)) if parts else None, "inputs": inputs}
    if d and d["rvol"] is not None:
        factors["volume"] = {"value": (1 if d["change_pct"] > 0 else -1) * min(d["rvol"] - 1, 1.0) if d["rvol"] > 1 else 0.0,
                             "inputs": {"1d RVOL": d["rvol"], "1d change %": d["change_pct"]}}
    else:
        factors["volume"] = {"value": None, "inputs": {}}
    factors["relative_strength"] = {"value": None if rs_pp is None else _clip(rs_pp / 20), "inputs": {} if rs_pp is None else {"63-obs excess return (pp)": rs_pp}}
    factors["volatility"] = {"value": None, "inputs": {"1d ATR %": d["atr_pct"]} if d else {}, "context_only": True}
    used = {k: v for k, v in factors.items() if v["value"] is not None and w.get(k, 0) > 0}
    tw = sum(w[k] for k in used)
    for k, v in factors.items():
        v["weight"] = w.get(k, 0.0)
        v["effective_weight"] = (w[k] / tw) if k in used and tw else 0.0
        v["contribution"] = v["value"] * v["effective_weight"] if k in used else 0.0
        v["available"] = v["value"] is not None
    tilt = sum(f["contribution"] for f in factors.values()) if used else None
    label = None if tilt is None else "bullish tilt" if tilt >= 0.25 else "bearish tilt" if tilt <= -0.25 else "neutral"
    return {"score": None if tilt is None else round(50 + 50 * tilt, 1), "tilt": tilt, "label": label, "factors": factors, "rules": RULES,
            "unavailable": [k for k, v in factors.items() if v["value"] is None and not v.get("context_only")],
            "disclaimer": "An analytical summary of current conditions, not a probability of a profitable trade."}
