"""Daily history for a fixed list of coins (Coinbase public candles, spot, USD, free and keyless) for multi-asset research such as cross-sectional momentum.

Honest limits, stated rather than hidden:
- The list is FIXED in advance and is made of coins Coinbase lists TODAY. Coins that were delisted or died are not in it, so any result on this list is flattered by survivorship. This is the main caveat of
  anything built on it, and every report must say so.
- A coin's history starts when Coinbase listed it; before that there is no bar, and the panel shows a gap (NaN), never a made-up value.
- Gaps inside a coin's history are detected and reported, never filled. The bar for today is still forming, so only COMPLETED days are returned by default.
- Coinbase's candle order is [time, low, high, open, close, volume]; the first bar for each coin is the first day Coinbase serves, which can be later than the listing announcement.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx
import numpy as np

from ..db import DB
from .data import CB, DEFAULT_START, gaps

DAY = 86400
UNIVERSE = ("BTC", "ETH", "LTC", "BCH", "XLM", "LINK", "ADA", "DOGE", "DOT", "SOL", "AVAX", "ATOM", "UNI", "ETC", "ALGO", "FIL", "AAVE", "XTZ", "ZEC", "DASH", "COMP", "SNX", "CRV", "MANA", "SHIB", "NEAR", "SAND", "XRP")
WINDOW_BARS = 300                       # Coinbase returns at most 300 candles per request


def parse_candles(data) -> list[tuple]:
    """Coinbase rows [time, low, high, open, close, volume] -> (t, o, h, l, c, v), oldest first. A malformed row refuses the whole response instead of being skipped."""
    out = []
    for r in data:
        if not isinstance(r, (list, tuple)) or len(r) < 6:
            raise ValueError("a candle row did not have six fields")
        t, low, high, op, close, vol = int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])
        if min(low, high, op, close) <= 0 or high < low:
            raise ValueError(f"an impossible candle at {t}")
        out.append((t, op, high, low, close, vol))
    return sorted(out)


class CoinData:
    def __init__(self, db: DB, client: httpx.AsyncClient | None = None):
        self.db, self._client = db, client

    async def _get(self, c: httpx.AsyncClient, url: str, params: dict):
        for attempt in range(3):
            r = await c.get(url, params=params, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code == 429:
                await asyncio.sleep(1 + attempt)
                continue
            return r
        raise ValueError("rate limited by the data source")

    async def refresh(self, symbol: str, now: int | None = None) -> dict:
        """Fetch what is missing for one coin. Returns its status: ok (with bars added), not_listed (Coinbase has no such product) or error (with the reason). Never raises for one coin's failure."""
        now = int(time.time()) if now is None else now
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            last = self.db.q("SELECT MAX(t) m FROM coin_bars WHERE symbol=?", (symbol,))[0]["m"]
            t = (last if last is not None else int(DEFAULT_START["1d"].timestamp()))
            added, listed = 0, last is not None
            while t < now:
                end = min(t + DAY * WINDOW_BARS, now + DAY)
                r = await self._get(c, f"{CB}/products/{symbol}-USD/candles", {"granularity": DAY, "start": datetime.fromtimestamp(t, timezone.utc).isoformat(), "end": datetime.fromtimestamp(end, timezone.utc).isoformat()})
                if r.status_code == 404:
                    if not listed:
                        self._meta(symbol, "not_listed", note="Coinbase has no USD product for this symbol")
                        return {"symbol": symbol, "status": "not_listed", "added": 0}
                    break
                if r.status_code != 200:
                    raise ValueError(f"HTTP {r.status_code}")
                rows = parse_candles(r.json())
                if rows:
                    listed = True
                    self.db.xmany("INSERT OR REPLACE INTO coin_bars(symbol,t,o,h,l,c,v) VALUES(?,?,?,?,?,?,?)", [(symbol, *x) for x in rows])
                    added += len(rows)
                t = end
                await asyncio.sleep(0.12)                      # well under Coinbase's public rate limit
            if not listed:
                self._meta(symbol, "not_listed", note="Coinbase served no daily bars for this symbol")
                return {"symbol": symbol, "status": "not_listed", "added": 0}
            self._meta(symbol, "ok")
            return {"symbol": symbol, "status": "ok", "added": added}
        except (httpx.HTTPError, ValueError, TypeError) as e:
            self._meta(symbol, "error", note=f"{type(e).__name__}: {str(e)[:80]}")
            return {"symbol": symbol, "status": "error", "added": 0, "reason": f"{type(e).__name__}: {str(e)[:80]}"}
        finally:
            if self._client is None:
                await c.aclose()

    async def refresh_all(self, symbols=UNIVERSE, now: int | None = None) -> list[dict]:
        return [await self.refresh(s, now) for s in symbols]

    def _meta(self, symbol: str, status: str, note: str | None = None) -> None:
        r = self.db.q("SELECT MIN(t) a, MAX(t) b, COUNT(*) n FROM coin_bars WHERE symbol=?", (symbol,))[0]
        self.db.x("INSERT INTO coin_meta(symbol,status,first_t,last_t,bars,fetched_at,note) VALUES(?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET status=excluded.status, first_t=excluded.first_t, "
                  "last_t=excluded.last_t, bars=excluded.bars, fetched_at=excluded.fetched_at, note=excluded.note", (symbol, status, r["a"], r["b"], r["n"], datetime.now(timezone.utc).isoformat(), note))

    def stored(self, symbol: str, completed_only: bool = True, now: int | None = None) -> list[tuple]:
        now = int(time.time()) if now is None else now
        rows = [(r["t"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in self.db.q("SELECT t,o,h,l,c,v FROM coin_bars WHERE symbol=? ORDER BY t", (symbol,))]
        return [x for x in rows if x[0] + DAY <= now] if completed_only else rows

    def gaps_in(self, symbol: str, now: int | None = None) -> list[dict]:
        return gaps(self.stored(symbol, True, now), DAY)

    def status(self) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT symbol,status,first_t,last_t,bars,fetched_at,note FROM coin_meta ORDER BY symbol")]

    def panel(self, symbols=UNIVERSE, now: int | None = None) -> dict:
        """Closes on one shared daily calendar: {'t': days, 'symbols': [...], 'close': 2D array days x symbols, NaN where a coin has no bar that day}. Nothing is filled or interpolated."""
        data = {s: {x[0]: x[4] for x in self.stored(s, True, now)} for s in symbols}
        have = [s for s in symbols if data[s]]
        if not have:
            return {"t": np.array([], int), "symbols": [], "close": np.empty((0, 0))}
        t0, t1 = min(min(d) for d in (data[s] for s in have)), max(max(d) for d in (data[s] for s in have))
        days = np.arange(t0, t1 + DAY, DAY)
        close = np.full((len(days), len(have)), np.nan)
        for j, s in enumerate(have):
            for i, d in enumerate(days):
                v = data[s].get(int(d))
                if v is not None:
                    close[i, j] = v
        return {"t": days, "symbols": have, "close": close}
