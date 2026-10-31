"""Fundamentals snapshots: provider fetch -> normalize -> cache with provenance.

Yahoo's company data is UNOFFICIAL (scraped endpoints, shifting field names) and lags filings, so it is labelled DELAYED with the quarter it
describes. A failed refresh serves the last good snapshot labelled STALE; with no snapshot at all the answer is UNAVAILABLE, never invented.
"""
from __future__ import annotations

import asyncio
import json
import zlib
from datetime import date, datetime, timedelta, timezone

from ..db import DB
from ..instruments import Instrument
from ..models import ProviderUnavailable
from .normalize import normalize

TTL = timedelta(hours=6)
SUPPORTED = ("equity", "etf")


class YahooFundamentals:
    name = "yahoo"

    async def fetch(self, inst: Instrument) -> tuple[dict, float | None, dict | None]:
        return await asyncio.to_thread(self._fetch, inst)

    def _fetch(self, inst: Instrument):
        import yfinance as yf

        try:
            t = yf.Ticker(inst.provider_symbol)
            info = t.info
            if not isinstance(info, dict) or not info:
                raise ProviderUnavailable(self.name, f"no company data for {inst.provider_symbol}")
            price = None
            try:
                price = float(t.fast_info["last_price"])
            except Exception:  # noqa: BLE001  the info dict's own price is the fallback inside normalize()
                pass
            cal = None
            try:
                c = t.calendar
                cal = c if isinstance(c, dict) else None
            except Exception:  # noqa: BLE001  earnings date is optional
                pass
            return info, price, cal
        except ProviderUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(self.name, f"{type(e).__name__}: {e}"[:160]) from e


class DemoFundamentals:
    """Deterministic synthetic company data for ATLAS_DEMO=1. Not real."""
    name = "demo"

    async def fetch(self, inst: Instrument):
        r = zlib.crc32(inst.symbol.encode())
        price = 30 + r % 300
        now = datetime.now(timezone.utc)
        info = {"longName": f"{inst.symbol} (synthetic)", "sector": "Demo", "industry": "Synthetic data", "quoteType": "ETF" if inst.asset_class == "etf" else "EQUITY",
                "currentPrice": float(price), "trailingEps": price / (10 + r % 25), "forwardEps": price / (9 + r % 20), "marketCap": price * 1e9 * (1 + r % 9),
                "enterpriseValue": price * 1.1e9 * (1 + r % 9), "totalRevenue": price * 4e8 * (1 + r % 9), "ebitda": price * 1e8 * (1 + r % 9), "bookValue": price / 4,
                "sharesOutstanding": 1e9 * (1 + r % 9), "totalCash": price * 1e8, "totalDebt": price * 1.5e8, "dividendRate": (r % 5) * 0.4, "revenueGrowth": 0.02 + (r % 15) / 100,
                "profitMargins": 0.05 + (r % 20) / 100, "grossMargins": 0.3 + (r % 40) / 100, "operatingMargins": 0.1 + (r % 20) / 100, "returnOnEquity": 0.1 + (r % 25) / 100,
                "fiftyTwoWeekHigh": price * 1.2, "fiftyTwoWeekLow": price * 0.7, "mostRecentQuarter": int((now - timedelta(days=40)).timestamp())}
        return info, float(price), {"Earnings Date": [(now + timedelta(days=20)).date()]}


class FundamentalsService:
    def __init__(self, db: DB, provider, demo: bool = False):
        self.db, self.provider, self.demo = db, provider, demo
        self._locks: dict[str, asyncio.Lock] = {}

    def _cached(self, symbol: str):
        r = self.db.q("SELECT * FROM fundamentals_cache WHERE symbol=?", (symbol,))
        return (datetime.fromisoformat(r[0]["fetched_at"]), json.loads(r[0]["payload"]), r[0]["provider"]) if r else None

    @staticmethod
    def _json_safe(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        raise TypeError(type(o).__name__)

    async def get(self, inst: Instrument, force: bool = False) -> dict:
        if inst.asset_class not in SUPPORTED:
            raise ProviderUnavailable("fundamentals", f"company fundamentals are not available for {inst.asset_class} instruments ({inst.symbol})")
        now = datetime.now(timezone.utc)
        async with self._locks.setdefault(inst.symbol, asyncio.Lock()):      # concurrent requests for one symbol share one fetch
            hit = self._cached(inst.symbol)
            if hit and not force and now - hit[0] < TTL:
                return self._wrap(inst, hit[1], hit[0], hit[2], "cache")
            try:
                info, price, cal = await self.provider.fetch(inst)
                snap = normalize(info, price, cal, now)
            except ProviderUnavailable as e:
                if hit:
                    out = self._wrap(inst, hit[1], hit[0], hit[2], "stale")
                    out["prov"]["status"] = "STALE"
                    out["prov"]["quality"].append(f"refresh failed ({e.message[:100]}): showing the last good snapshot")
                    return out
                raise
            self.db.x("INSERT INTO fundamentals_cache(symbol,fetched_at,provider,payload) VALUES(?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET fetched_at=excluded.fetched_at, "
                      "provider=excluded.provider, payload=excluded.payload", (inst.symbol, now.isoformat(), self.provider.name, json.dumps(snap, default=self._json_safe)))
            return self._wrap(inst, snap, now, self.provider.name, "live")

    def _wrap(self, inst: Instrument, snap: dict, fetched: datetime, provider: str, origin: str) -> dict:
        demo = provider == "demo"
        quality = ["synthetic demo data: not real company data"] if demo else [
            "Yahoo company data is unofficial and lags filings; ratios are computed here from the raw figures"]
        return {"instrument_id": inst.id, "symbol": inst.symbol, **snap,
                "prov": {"provider": provider, "fetched_at": fetched.isoformat(), "origin": origin, "status": "DEMO" if demo else "DELAYED", "quality": quality}}
