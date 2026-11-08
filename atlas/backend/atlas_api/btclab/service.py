"""Strategy Lab service: loads cached BTC history, runs the evaluation off the event loop, caches finished runs, and labels where the data came from."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import evaluate as E
from .data import BARS_PER_YEAR, TF_SECONDS, BtcData, DataError, gaps
from .strategies import DEFAULT_FIVE, FINDINGS, S

MAX_STRATEGIES = 8


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategies: list[str] = Field(default_factory=lambda: list(DEFAULT_FIVE), min_length=1, max_length=MAX_STRATEGIES)
    timeframe: Literal["1d", "4h", "1h"] = "1d"
    market: Literal["spot", "perp"] = "spot"
    leverage: float = Field(1.0, ge=1.0, le=3.0)                 # never above 3x
    long_short: bool = False
    fee_bps: float = Field(5.0, ge=0, le=50)
    slippage_bps: float = Field(5.0, ge=0, le=100)

    @field_validator("strategies")
    @classmethod
    def _known(cls, v):
        for i in v:
            if i not in S:
                raise ValueError(f"unknown strategy '{i}'")
        if len(set(v)) != len(v):
            raise ValueError("a strategy was listed twice")
        return v


def demo_rows(tf: str) -> list[tuple]:
    """Deterministic synthetic bars for demo mode. NOT market data."""
    step = TF_SECONDS[tf]
    n = {"1d": 2200, "4h": 5000, "1h": 8000}[tf]
    t0 = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    px, rows = 9000.0, []
    for i in range(n):
        cyc = math.sin(i / (n / 9)) * 0.004 + math.sin(i / 7) * 0.006 + math.sin(i / 2.3 + 1) * 0.004
        o = px
        px = px * math.exp(cyc * (step / 86400) ** 0.5 + 0.0002 * (step / 86400))
        rows.append((t0 + i * step, o, max(o, px) * 1.004, min(o, px) * 0.996, px, 1000.0))
    return rows


def demo_funding(rows: list[tuple]) -> list[tuple[int, float]]:
    t = rows[0][0]
    return [(t + 3600 * i, 0.00001 * (1 + math.sin(i / 400))) for i in range((rows[-1][0] - t) // 3600 + 1)]


class LabService:
    def __init__(self, data: BtcData, demo: bool = False):
        self.data, self.demo = data, demo
        self._cache: dict[str, dict] = {}

    @staticmethod
    def listing() -> list[dict]:
        return [s.meta() for s in S.values()]

    def status(self) -> dict:
        return {"demo": self.demo, "defaults": DEFAULT_FIVE, "findings": FINDINGS, "max_leverage": 3.0, "data": None if self.demo else self.data.status(),
                "sources": {"prices": "Coinbase Exchange public candles, BTC-USD spot (4h is built from 1h)", "funding": "Hyperliquid hourly funding history (from 2023)"}}

    async def refresh(self, tfs: list[str]) -> dict:
        if self.demo:
            return {"demo": True, "added": {}}
        added = {}
        try:
            for tf in tfs:
                added[tf] = await self.data.refresh_bars(tf)
            added["funding"] = await self.data.refresh_funding()
        except DataError as e:
            raise E.LabError(str(e)) from e
        return {"demo": False, "added": added}

    async def run(self, req: RunIn) -> dict:
        r = req.model_dump()
        if r["market"] == "spot":
            r["leverage"], r["long_short"] = 1.0, False
        perp = r["market"] == "perp"
        notes: list[str] = []
        if self.demo:
            rows = demo_rows(r["timeframe"])
            funding = demo_funding(rows) if perp else None
        else:
            notes = await self.data.ensure(r["timeframe"], perp or any(S[i].requires_funding for i in r["strategies"]))
            rows = self.data.stored(r["timeframe"])
            funding = self.data.funding() if perp else None
        if not rows:
            raise E.LabError("No BTC price history is saved yet and it could not be downloaded. " + " ".join(notes))
        key = hashlib.sha256(json.dumps([r, len(rows), rows[-1][0], len(funding or [])], sort_keys=True).encode()).hexdigest()[:20]
        if key in self._cache:
            return self._cache[key]
        out = await asyncio.to_thread(E.run_lab, rows, funding, r)
        out["data"] = {"demo": self.demo, "source": "DEMO: synthetic prices, not market data" if self.demo else "Coinbase Exchange public candles (BTC-USD spot)",
                       "funding_source": None if not perp else ("DEMO: synthetic funding" if self.demo else "Hyperliquid funding history"),
                       "bars": len(rows), "last_bar": datetime.fromtimestamp(rows[-1][0], timezone.utc).isoformat(), "gap_count": len(gaps(rows, TF_SECONDS[r["timeframe"]])),
                       "status": "DEMO" if self.demo else "HISTORICAL", "notes": notes}
        out["findings"] = FINDINGS
        out["run_id"] = key
        if len(self._cache) > 24:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = out
        return out
