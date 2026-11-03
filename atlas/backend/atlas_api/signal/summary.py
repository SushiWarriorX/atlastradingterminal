"""Market summaries for the watchlist rows and the asset chart. Prices, changes and bars come from the ATLAS market service, so every number keeps its
provenance (provider, event time, and a LIVE / DELAYED / HISTORICAL / STALE / DEMO label). The one-line 'quick take' is computed here from daily bars."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import numpy as np

from .. import indicators as ind
from .. import technical
from ..models import Candle, ProviderUnavailable
from ..sessions import NY
from ..service import MarketService
from . import fmt
from .assets import Asset
from .cache import SharedCache

SPARK_POINTS = 30
BARS_TTL = 300.0
ROW_TIMEOUT = 12.0
# range -> (interval, bar limit, span in seconds; None = the latest trading session)
RANGES = {"1D": ("5m", 300, None), "1W": ("1h", 220, 7 * 86400), "1M": ("1d", 45, 31 * 86400), "3M": ("1d", 110, 92 * 86400),
          "1Y": ("1d", 300, 366 * 86400), "5Y": ("1w", 280, 5 * 366 * 86400)}
MAX_CHART_POINTS = 240


class SummaryError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def prov_dict(p) -> dict:
    return {"provider": p.provider, "status": p.status.value, "event_time": p.event_time.isoformat() if p.event_time else None, "delay_seconds": p.delay_seconds,
            "session": p.session, "quality": list(p.quality)[:4]}


def quick_take(candles: list[Candle]) -> dict | None:
    """One short line from daily bars: trend label (moving-average rule), 1-month change, RSI zone. Descriptive, not a forecast."""
    if len(candles) < 22:
        return None
    close = np.array([c.close for c in candles])
    parts = []
    t = technical.trend(candles) if len(candles) >= 50 else {"label": "insufficient_data"}
    parts.append({"bullish": "Uptrend", "bearish": "Downtrend", "mixed": "Mixed trend"}.get(t["label"], "Trend unclear (short history)"))
    parts.append(f"{fmt.pct((close[-1] / close[-22] - 1) * 100, signed=True)} in 1M")
    rsi = ind.rsi(close, 14)[-1]
    if not np.isnan(rsi) and (rsi >= 70 or rsi <= 30):
        parts.append("RSI " + ("overbought" if rsi >= 70 else "oversold") + f" ({rsi:.0f})")
    return {"text": " · ".join(parts), "timeframe": "1D", "source": "Technical (daily bars, rules)",
            "as_of": datetime.fromtimestamp(candles[-1].time, timezone.utc).isoformat()}


def _session_cut(candles: list[Candle]) -> list[Candle]:
    last = datetime.fromtimestamp(candles[-1].time, timezone.utc).astimezone(NY).date()
    return [c for c in candles if datetime.fromtimestamp(c.time, timezone.utc).astimezone(NY).date() == last]


def thin(points: list[list[float]], n: int = MAX_CHART_POINTS) -> list[list[float]]:
    if len(points) <= n:
        return points
    step = (len(points) - 1) / (n - 1)
    return [points[round(i * step)] for i in range(n)]


class MarketSummary:
    def __init__(self, svc: MarketService, cache: SharedCache | None = None):
        self.svc = svc
        self._bars: SharedCache = cache or SharedCache()

    async def daily(self, asset: Asset, limit: int = 120):
        key = ("1d", asset.id, limit)
        e = await self._bars.get(key, lambda: self.svc.ohlcv(asset.inst, "1d", limit), lambda _o: BARS_TTL)
        return e.value

    async def row(self, asset: Asset) -> dict:
        out = {"asset": asset.public(), "quote": None, "spark": None, "takeaway": None, "error": None}
        q_res, b_res = await asyncio.gather(self.svc.quote(asset.inst), self.daily(asset), return_exceptions=True)
        if isinstance(q_res, Exception):
            out["error"] = _err(q_res)
        else:
            out["quote"] = {"price": q_res.price, "display": fmt.price(q_res.price), "change": q_res.change, "change_pct": q_res.change_pct, "basis": q_res.prev_close_basis,
                            "prov": prov_dict(q_res.prov)}
        if not isinstance(b_res, Exception) and b_res.candles:
            c = b_res.candles
            out["spark"] = [round(x.close, 8) for x in c[-SPARK_POINTS:]]
            out["takeaway"] = quick_take(c)
            out["bars_prov"] = prov_dict(b_res.prov)
        elif out["error"] is None and isinstance(b_res, Exception):
            out["spark_error"] = _err(b_res)["message"]
        return out

    async def chart(self, asset: Asset, rng: str) -> dict:
        if rng not in RANGES:
            raise SummaryError("INVALID_RANGE", f"range must be one of {', '.join(RANGES)}", 422)
        interval, limit, span = RANGES[rng]
        o = await self.svc.ohlcv(asset.inst, interval, limit)
        c = o.candles
        if not c:
            raise ProviderUnavailable(o.prov.provider, "no bars returned")
        c = _session_cut(c) if span is None and asset.inst.is_equity_like else (c if span is None else [x for x in c if x.time >= c[-1].time - span])
        if span is None and not asset.inst.is_equity_like:
            c = [x for x in c if x.time >= c[-1].time - 86400]                      # crypto trades 24/7: the last 24 hours
        pts = thin([[x.time, x.close] for x in c])
        first, last = pts[0][1], pts[-1][1]
        return {"asset": asset.public(), "range": rng, "interval": interval, "points": pts, "first": first, "last": last, "change": last - first,
                "change_pct": (last / first - 1) * 100 if first else None, "derived_from": o.derived_from, "prov": prov_dict(o.prov),
                "note": "Change is measured from the first to the last close shown." + ("" if span else " 1D = the latest trading session (stocks/ETFs) or the last 24 hours (crypto).")}


def _err(e: Exception) -> dict:
    if isinstance(e, ProviderUnavailable):
        return {"code": "DATA_UNAVAILABLE", "message": f"{e.provider}: {e.message}"[:200]}
    return {"code": "ERROR", "message": type(e).__name__}
