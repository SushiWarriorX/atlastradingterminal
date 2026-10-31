"""Coinbase Exchange public market data (no key). BTC-USD spot, single venue."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from ..instruments import Instrument
from ..models import Candle, OHLCV, Provenance, Quote
from .http import Http

GRAN = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class CoinbaseProvider:
    name = "coinbase"
    entitlement = "public-market-data (no key)"
    delay_seconds = 0
    native_intervals = set(GRAN)

    def __init__(self, http: Http | None = None):
        self.http = http or Http("https://api.exchange.coinbase.com", "coinbase")

    async def quote(self, inst: Instrument) -> Quote:
        p = inst.provider_symbol
        tk, st = await asyncio.gather(self.http.get(f"/products/{p}/ticker"), self.http.get(f"/products/{p}/stats"))
        t, s = tk.json(), st.json()
        ev = _t(t["time"])
        return Quote(
            instrument_id=inst.id, price=float(t["price"]), bid=float(t["bid"]), ask=float(t["ask"]),
            open=float(s["open"]), high=float(s["high"]), low=float(s["low"]),
            prev_close=float(s["open"]), prev_close_basis="24h rolling open", volume=float(s["volume"]),
            unsupported_fields=["bid_size", "ask_size", "vwap", "market_cap"],
            prov=Provenance(provider=self.name, instrument_id=inst.id, venue="COINBASE", event_time=ev,
                            provider_time=ev, ingested_time=datetime.now(timezone.utc), entitlement=self.entitlement,
                            delay_seconds=0),
        )

    async def ohlcv(self, inst: Instrument, interval: str, limit: int) -> OHLCV:
        g = GRAN[interval]
        end = datetime.now(timezone.utc)
        rows: dict[int, list] = {}
        remaining = limit
        while remaining > 0:  # API returns at most 300 candles per request
            n = min(remaining, 300)
            start = end - timedelta(seconds=g * n)
            r = await self.http.get(f"/products/{inst.provider_symbol}/candles",
                                    {"granularity": g, "start": start.isoformat(), "end": end.isoformat()})
            batch = r.json()
            if not batch:
                break
            for row in batch:
                rows[int(row[0])] = row
            end = start
            remaining -= n
        candles = [Candle(time=t, low=r[1], high=r[2], open=r[3], close=r[4], volume=r[5]) for t, r in sorted(rows.items())]
        last = datetime.fromtimestamp(candles[-1].time, timezone.utc) if candles else None
        return OHLCV(instrument_id=inst.id, interval=interval, candles=candles[-limit:], adjustment="none",
                     prov=Provenance(provider=self.name, instrument_id=inst.id, venue="COINBASE", event_time=last,
                                     ingested_time=datetime.now(timezone.utc), entitlement=self.entitlement, delay_seconds=0))
