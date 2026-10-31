from __future__ import annotations

from .models import Candle

SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400}


WEEK = 7 * 86400
MONDAY_OFFSET = 4 * 86400   # 1970-01-01 was a Thursday; the first Monday boundary is 4 days later


def resample(candles: list[Candle], seconds: int, offset: int = 0) -> list[Candle]:
    """Aggregate finer bars into buckets aligned to the UTC epoch (shifted by `offset`).
    Weekly bars use offset=MONDAY_OFFSET so weeks start on Monday, matching equity convention.
    The incomplete trailing bucket is kept."""
    out: list[Candle] = []
    for c in sorted(candles, key=lambda c: c.time):
        b = c.time - (c.time - offset) % seconds
        if out and out[-1].time == b:
            p = out[-1]
            out[-1] = Candle(time=b, open=p.open, high=max(p.high, c.high), low=min(p.low, c.low),
                             close=c.close, volume=p.volume + c.volume)
        else:
            out.append(Candle(time=b, open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume))
    return out
