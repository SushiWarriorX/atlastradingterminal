"""FRED public CSV download (no key). Observation dates are NOT publication times."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from ..instruments import Instrument
from ..models import Candle, OHLCV, Provenance, ProviderUnavailable, Quote
from .http import Http


class FredProvider:
    name = "fred"
    entitlement = "public domain / FRED terms"
    delay_seconds = None
    native_intervals = {"1d"}

    def __init__(self, http: Http | None = None):
        self.http = http or Http("https://fred.stlouisfed.org", "fred", min_interval=0.5)

    async def _series(self, inst: Instrument) -> list[tuple[datetime, float]]:
        r = await self.http.get("/graph/fredgraph.csv", {"id": inst.provider_symbol})
        rows = list(csv.reader(io.StringIO(r.text)))
        pts = []
        for date, val in rows[1:]:
            if val not in (".", ""):  # FRED marks missing observations with "."
                pts.append((datetime.fromisoformat(date).replace(tzinfo=timezone.utc), float(val)))
        if not pts:
            raise ProviderUnavailable(self.name, f"empty series {inst.provider_symbol}")
        return pts

    def _prov(self, inst, ev):
        return Provenance(provider=self.name, instrument_id=inst.id, venue="FRED", event_time=ev,
                          ingested_time=datetime.now(timezone.utc), currency=inst.currency, entitlement=self.entitlement)

    async def quote(self, inst: Instrument) -> Quote:
        pts = await self._series(inst)
        (t1, v1), v0 = pts[-1], pts[-2][1] if len(pts) > 1 else None
        return Quote(instrument_id=inst.id, price=v1, prev_close=v0, prev_close_basis="previous observation",
                     unsupported_fields=["bid", "ask", "volume", "vwap", "open", "high", "low"], prov=self._prov(inst, t1))

    async def ohlcv(self, inst: Instrument, interval: str, limit: int) -> OHLCV:
        pts = (await self._series(inst))[-limit:]
        return OHLCV(instrument_id=inst.id, interval="1d", line_only=True, adjustment="none",
                     candles=[Candle(time=int(t.timestamp()), open=v, high=v, low=v, close=v) for t, v in pts],
                     prov=self._prov(inst, pts[-1][0]))
