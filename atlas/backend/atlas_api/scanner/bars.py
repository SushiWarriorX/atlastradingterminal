"""Daily-bar sources for the scanner."""
from __future__ import annotations

import asyncio
import random
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

from ..models import Candle, DataStatus
from ..sessions import session_state

Progress = Callable[[int, int], None]


@dataclass
class BarBatch:
    bars: dict[str, list[Candle]]
    failed: dict[str, str] = field(default_factory=dict)
    provider: str = ""
    status: DataStatus = DataStatus.HISTORICAL
    as_of: datetime | None = None
    notes: list[str] = field(default_factory=list)


class BarSource(Protocol):
    name: str

    async def fetch(self, symbols: list[str], progress: Progress | None = None) -> BarBatch: ...


class YahooBars:
    """Batched yf.download of ~1y of daily bars with an in-memory TTL cache. Unofficial and delayed."""
    name = "yahoo"

    def __init__(self, chunk: int = 150, ttl: float = 900.0, period: str = "1y"):
        self.chunk, self.ttl, self.period = chunk, ttl, period
        self._cache: dict[str, tuple[float, list[Candle]]] = {}

    def _download(self, chunk: list[str]) -> dict[str, list[Candle]]:
        import pandas as pd
        import yfinance as yf

        df = yf.download(" ".join(chunk), period=self.period, interval="1d", group_by="ticker", auto_adjust=False,
                         threads=True, progress=False)
        out: dict[str, list[Candle]] = {}
        if df is None or df.empty:
            return out
        multi = isinstance(df.columns, pd.MultiIndex)
        for s in chunk:
            try:
                d = (df[s] if multi else df).dropna(subset=["Close"])
            except KeyError:
                continue
            if d.empty:
                continue
            out[s] = [Candle(time=int(ts.timestamp()), open=float(r.Open), high=float(r.High), low=float(r.Low),
                             close=float(r.Close), volume=float(r.Volume) if r.Volume == r.Volume else 0.0)
                      for ts, r in d.iterrows()]
        return out

    async def fetch(self, symbols: list[str], progress: Progress | None = None) -> BarBatch:
        now = time.monotonic()
        bars = {s: self._cache[s][1] for s in symbols if s in self._cache and self._cache[s][0] > now}
        todo = [s for s in symbols if s not in bars]
        failed: dict[str, str] = {}
        done = len(bars)
        for i in range(0, len(todo), self.chunk):
            chunk = todo[i:i + self.chunk]
            try:
                got = await asyncio.to_thread(self._download, chunk)
            except Exception as e:  # noqa: BLE001  network/parse failure affects only this chunk
                got = {}
                failed.update({s: f"{type(e).__name__}: {e}"[:120] for s in chunk})
            for s in chunk:
                if s in got:
                    bars[s] = got[s]
                    self._cache[s] = (time.monotonic() + self.ttl, got[s])
                elif s not in failed:
                    failed[s] = "no data returned"
            done += len(chunk)
            if progress:
                progress(min(done, len(symbols)), len(symbols))
        sess = session_state()["state"]
        last = max((c[-1].time for c in bars.values()), default=None)
        notes = ["Yahoo data is unofficial and typically delayed ~15 min"]
        if sess == "REGULAR":
            notes.append("Market is open: today's daily bar is partial, so RVOL and % change are intraday-in-progress")
        return BarBatch(bars, failed, "yahoo", DataStatus.DELAYED if sess == "REGULAR" else DataStatus.HISTORICAL,
                        datetime.fromtimestamp(last, timezone.utc) if last else None, notes)


class DemoBars:
    """Deterministic synthetic daily bars (ATLAS_DEMO=1). Not market data."""
    name = "demo"

    def __init__(self, days: int = 260):
        self.days = days

    async def fetch(self, symbols: list[str], progress: Progress | None = None) -> BarBatch:
        now = int(datetime.now(timezone.utc).timestamp())
        day0 = now - now % 86400
        bars = {}
        for s in symbols:
            rng = random.Random(zlib.crc32(s.encode()))
            px, drift, out = 30 + zlib.crc32(s.encode()) % 300, rng.uniform(-0.0006, 0.0014), []
            for i in range(self.days):
                o = px
                c = o * (1 + rng.gauss(drift, 0.016))
                v = rng.uniform(2e6, 2e7) * (3 if i == self.days - 1 and rng.random() < 0.15 else 1)
                out.append(Candle(time=day0 - (self.days - 1 - i) * 86400, open=o, high=max(o, c) * 1.006, low=min(o, c) * 0.994, close=c, volume=v))
                px = c
            bars[s] = out
        if progress:
            progress(len(symbols), len(symbols))
        return BarBatch(bars, {}, "demo", DataStatus.DEMO, datetime.fromtimestamp(day0, timezone.utc), ["synthetic demo bars: not market data"])
