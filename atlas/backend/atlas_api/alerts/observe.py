"""Turn a rule into an observation: (condition_now, value, detail, provenance). Async data access lives here."""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import indicators as ind
from .. import instruments as I
from ..models import DataStatus, Provenance, ProviderUnavailable
from ..service import MarketService
from .rules import interval_seconds

SKIP_STATUSES = {DataStatus.STALE, DataStatus.UNAVAILABLE}


@dataclass
class Observation:
    cond: bool | None                       # None = could not evaluate
    value: float | None = None
    detail: str = ""
    prov: Provenance | None = None
    skip_reason: str | None = None
    notes: list[str] = field(default_factory=list)


def _skip(prov: Provenance | None, why: str) -> Observation:
    return Observation(None, None, "", prov, skip_reason=why)


def completed(candles, interval: str, now_ts: float, on_close: bool):
    """Drop the still-forming final candle when on_close is requested."""
    if on_close and candles and candles[-1].time + interval_seconds(interval) > now_ts:
        return candles[:-1]
    return candles


async def observe(rule, svc: MarketService, now_ts: float) -> Observation:
    inst = I.resolve(rule.instrument_id)
    if inst is None:
        return _skip(None, f"unknown instrument {rule.instrument_id}")
    try:
        if rule.kind in ("price", "pct_change"):
            q = await svc.quote(inst)
            if q.prov.status in SKIP_STATUSES:
                return _skip(q.prov, f"data {q.prov.status.value}: {'; '.join(q.prov.quality)}")
            if rule.kind == "price":
                return Observation(q.price >= rule.level if rule.op == "above" else q.price <= rule.level, q.price,
                                   f"last {q.price:,.4f}", q.prov)
            if q.change_pct is None:
                return _skip(q.prov, "no previous close to compute change")
            return Observation(q.change_pct >= rule.threshold if rule.op == "above" else q.change_pct <= rule.threshold,
                               q.change_pct, f"change {q.change_pct:+.2f}% ({q.prev_close_basis})", q.prov)
        interval = "1d" if rule.kind == "rvol" else rule.interval
        o = await svc.ohlcv(inst, interval, 300)
        if o.prov.status in SKIP_STATUSES:
            return _skip(o.prov, f"data {o.prov.status.value}: {'; '.join(o.prov.quality)}")
        candles = o.candles if rule.kind == "rvol" else completed(o.candles, interval, now_ts, rule.on_close)
        notes = [f"derived from {o.derived_from} bars"] if o.derived_from else []
        if rule.kind == "rvol":
            if o.prov.session == "REGULAR":
                notes.append("today's volume is partial while the market is open")
            r = ind.rvol([c.volume for c in candles], 20)
            if len(candles) < 22 or r[-1] != r[-1]:
                return _skip(o.prov, "not enough history for RVOL(20)")
            return Observation(bool(r[-1] >= rule.threshold), float(r[-1]), f"RVOL {r[-1]:.2f}x", o.prov, notes=notes)
        close = [c.close for c in candles]
        if rule.kind == "rsi":
            v = ind.rsi(close, rule.period)
            if len(close) <= rule.period or v[-1] != v[-1]:
                return _skip(o.prov, f"not enough history for RSI({rule.period})")
            return Observation(bool(v[-1] >= rule.level) if rule.op == "above" else bool(v[-1] <= rule.level), float(v[-1]),
                               f"RSI({rule.period}) {v[-1]:.1f} on {interval}", o.prov, notes=notes)
        if rule.kind == "ma":
            v = ind.sma(close, rule.length)
            if len(close) < rule.length:
                return _skip(o.prov, f"not enough history for SMA({rule.length})")
            c, m = close[-1], float(v[-1])
            return Observation(c > m if rule.op == "above" else c < m, c, f"close {c:,.4f} vs SMA({rule.length}) {m:,.4f} on {interval}", o.prov, notes=notes)
        if rule.kind == "macd":
            hist = ind.macd(close)[2]
            if len(close) < 36 or hist[-1] != hist[-1]:
                return _skip(o.prov, "not enough history for MACD")
            h = float(hist[-1])
            return Observation(h > 0 if rule.direction == "bullish" else h < 0, h, f"MACD histogram {h:+.4f} on {interval}", o.prov, notes=notes)
    except ProviderUnavailable as e:
        return _skip(None, f"provider unavailable: {e.message}")
    return _skip(None, f"unsupported rule kind {rule.kind}")
