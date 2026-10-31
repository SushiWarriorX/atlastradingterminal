"""Deterministic technical features and key levels. The LLM interprets these; it never computes them."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

from . import indicators as ind
from .models import Candle

NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Level:
    id: str
    kind: str          # swing_high | swing_low | prev_day_high | prev_day_low | sma
    price: float
    derivation: str    # exact rule so the user can audit it
    time: int | None = None


def swings(candles: list[Candle], k: int = 5) -> tuple[list[int], list[int]]:
    """Fractal swings: bar i is a swing high if its high is strictly greater than the k bars on each side
    (swing low analogously). The last k bars cannot be confirmed yet and are never returned."""
    hi, lo = [], []
    for i in range(k, len(candles) - k):
        h, l = candles[i].high, candles[i].low
        if all(h > candles[j].high for j in range(i - k, i + k + 1) if j != i):
            hi.append(i)
        if all(l < candles[j].low for j in range(i - k, i + k + 1) if j != i):
            lo.append(i)
    return hi, lo


def key_levels(candles: list[Candle], interval: str, *, k: int = 5, n_each: int = 3, equity_tz: bool = False) -> list[Level]:
    levels: list[Level] = []
    hi, lo = swings(candles, k)
    for kind, idxs, attr in (("swing_high", hi[-n_each:], "high"), ("swing_low", lo[-n_each:], "low")):
        for i in idxs:
            levels.append(Level(f"L{len(levels) + 1}", kind, getattr(candles[i], attr),
                                f"{kind.replace('_', ' ')}: {attr} higher/lower than {k} bars each side ({interval})", candles[i].time))
    if interval not in ("1d", "1w", "1M") and candles:
        tz = NY if equity_tz else timezone.utc
        day = lambda c: datetime.fromtimestamp(c.time, tz).date()
        today = day(candles[-1])
        prev = [c for c in candles if day(c) < today]
        if prev:
            pd_ = day(prev[-1])
            bars = [c for c in prev if day(c) == pd_]
            label = "ET" if equity_tz else "UTC"
            levels.append(Level(f"L{len(levels) + 1}", "prev_day_high", max(c.high for c in bars), f"previous {label} day ({pd_}) high from {interval} bars"))
            levels.append(Level(f"L{len(levels) + 1}", "prev_day_low", min(c.low for c in bars), f"previous {label} day ({pd_}) low from {interval} bars"))
    close = [c.close for c in candles]
    for n in (50, 200):
        v = ind.sma(close, n)
        if len(v) and not np.isnan(v[-1]):
            levels.append(Level(f"L{len(levels) + 1}", "sma", float(v[-1]), f"SMA({n}) of close on {interval}, latest bar"))
    return levels


def trend(candles: list[Candle]) -> dict:
    """Moving-average alignment classification with the factors shown, or insufficient_data."""
    close = [c.close for c in candles]
    s20, s50, s200 = (ind.sma(close, n)[-1] if len(close) >= n else np.nan for n in (20, 50, 200))
    if np.isnan(s50):
        return {"label": "insufficient_data", "factors": {"bars": len(close), "needed": 50}}
    px = close[-1]
    f = {"close": px, "sma20": _f(s20), "sma50": float(s50), "sma200": _f(s200),
         "close_above_sma50": bool(px > s50), "sma50_above_sma200": None if np.isnan(s200) else bool(s50 > s200)}
    if np.isnan(s200):
        label = "bullish" if px > s50 else "bearish"
        f["note"] = "fewer than 200 bars: classified on SMA50 only"
    elif px > s50 > s200:
        label = "bullish"
    elif px < s50 < s200:
        label = "bearish"
    else:
        label = "mixed"
    return {"label": label, "factors": f}


def _f(x):
    return None if np.isnan(x) else float(x)


def features(candles: list[Candle], interval: str, equity_tz: bool = False) -> dict:
    if len(candles) < 2:
        return {"interval": interval, "bars": len(candles), "insufficient": True}
    specs = ["rsi:14", "atr:14", "macd", "bb:20:2", "rvol:20", "ema:21", "sma:20"]
    ind_all = ind.compute(candles, specs)
    last = {k: v[-1] for k, v in ind_all.items()}
    atr_v = last.get("atr:14")
    last["atr_pct"] = None if atr_v is None else atr_v / candles[-1].close * 100
    return {"interval": interval, "bars": len(candles), "last_bar_time": candles[-1].time, "last_close": candles[-1].close,
            "indicators": last, "trend": trend(candles), "levels": [asdict(l) for l in key_levels(candles, interval, equity_tz=equity_tz)]}
