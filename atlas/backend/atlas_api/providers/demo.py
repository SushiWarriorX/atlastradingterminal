"""Synthetic data for UI development and tests. Only enabled with ATLAS_DEMO=1; always labeled DEMO."""
from __future__ import annotations

import math
import random
import time
import zlib
from datetime import datetime, timezone

from ..instruments import Instrument
from ..models import Candle, OHLCV, Provenance, Quote
from ..resample import SECONDS


class DemoProvider:
    name = "demo"
    entitlement = "synthetic"
    delay_seconds = 0
    native_intervals = {"1m", "5m", "15m", "30m", "1h", "1d", "1w", "6h"}

    CRYPTO_BASE = {"BTC": 68000, "ETH": 3400, "SOL": 165, "XRP": 2.4, "ADA": 0.7, "DOGE": 0.18, "AVAX": 38, "LINK": 17, "DOT": 7, "LTC": 90, "BCH": 480, "UNI": 9, "SHIB": 0.000022, "PEPE": 0.000011}

    def _base(self, inst: Instrument) -> float:
        h = zlib.crc32(inst.id.encode())
        if inst.asset_class == "crypto":
            sym = inst.provider_symbol.split("-")[0]
            return float(self.CRYPTO_BASE.get(sym, 60000 + h % 20000 if sym == "BTC" else 0.5 + h % 300))
        return {"macro": 3 + h % 200 / 100, "index": 3000 + h % 15000}.get(inst.asset_class, 40 + h % 400)

    def _prov(self, inst, ev):
        return Provenance(provider="demo", instrument_id=inst.id, venue="DEMO", event_time=ev,
                          ingested_time=datetime.now(timezone.utc), entitlement=self.entitlement, delay_seconds=0)

    def _walk(self, inst, interval, n):
        sec = SECONDS.get(interval, 7 * 86400 if interval == "1w" else 86400)
        rng = random.Random(f"{inst.id}:{interval}")
        now = int(datetime.now(timezone.utc).timestamp())
        t0, px, out = now - now % sec - sec * n, self._base(inst), []
        for i in range(n):
            o = px
            c = o * (1 + rng.gauss(0, 0.004 if sec < 86400 else 0.012))
            out.append(Candle(time=t0 + i * sec, open=o, high=max(o, c) * (1 + abs(rng.gauss(0, 0.002))),
                              low=min(o, c) * (1 - abs(rng.gauss(0, 0.002))), close=c, volume=rng.uniform(1e3, 1e6)))
            px = c
        scale = self._base(inst) / out[-1].close if out and out[-1].close else 1.0      # every interval and every length ends at the same anchor price, so a demo asset is internally consistent
        return [Candle(time=x.time, open=x.open * scale, high=x.high * scale, low=x.low * scale, close=x.close * scale, volume=x.volume) for x in out]

    async def quote(self, inst: Instrument) -> Quote:
        c = self._walk(inst, "1d", 30)
        last = c[-1]
        # gentle +/-1% oscillation (period ~25 s) so alerts and the UI have something to react to; still labelled DEMO
        px = last.close * (1 + 0.01 * math.sin(time.time() / 4))
        return Quote(instrument_id=inst.id, price=px, open=last.open, high=last.high, low=last.low,
                     prev_close=c[-2].close, volume=last.volume, prov=self._prov(inst, datetime.now(timezone.utc)),
                     unsupported_fields=["bid", "ask"])

    async def ohlcv(self, inst: Instrument, interval: str, limit: int) -> OHLCV:
        return OHLCV(instrument_id=inst.id, interval=interval, candles=self._walk(inst, interval, limit),
                     line_only=inst.asset_class == "macro", prov=self._prov(inst, datetime.now(timezone.utc)))
