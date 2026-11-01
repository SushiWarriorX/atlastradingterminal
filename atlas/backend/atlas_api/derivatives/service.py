"""BTC derivatives snapshots: fetch the four venues concurrently, isolate failures, compute in code, record history for percentiles.

A venue that fails is shown as failed with a plain reason and left out of the aggregate (coverage is always visible). Nothing is estimated:
no history means no percentile and no 24 h change, and the response says how much history exists. DEMO mode serves clearly labelled synthetic
records and records no history.
"""
from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timedelta, timezone

from ..db import DB, now as iso_now
from . import compute
from .venues import LABELS, VENUES, VenueClient, VenueError

CACHE_SECONDS = 30.0
RETENTION_DAYS = 35
PCTILE_DAYS = 30
MIN_HISTORY = 100
RECORD_EVERY = 240.0      # seconds between recorded history points (the background loop runs every 300 s)


class DemoVenueClient:
    """Deterministic synthetic venues for ATLAS_DEMO=1. Not market data."""

    async def fetch(self, venue: str) -> dict:
        k = VENUES.index(venue)
        t = time.time()
        mark = 67_000 + 400 * math.sin(t / 900) + k * 12
        return {"venue": venue, "mark": mark, "index": mark * (1 - 0.0004 * (k + 1)), "funding_rate": 0.0001 * (1 + math.sin(t / 1800 + k)) / (1 if venue != "hyperliquid" else 8),
                "funding_interval_h": 1.0 if venue == "hyperliquid" else 8.0, "oi_btc": 20_000 + 1500 * k + 800 * math.sin(t / 3600), "ts_ms": int(t * 1000),
                "next_funding_ms": None, "notes": ["synthetic demo data: not market data"]}


class DerivativesService:
    def __init__(self, db: DB, client=None, demo: bool = False):
        self.db, self.demo = db, demo
        self.client = DemoVenueClient() if demo else (client or VenueClient())
        self._cache: tuple[float, dict] | None = None
        self._last_rec: float | None = None
        self._lock = asyncio.Lock()

    async def _one(self, venue: str) -> dict:
        def fail(code: str, message: str) -> dict:
            return {"venue": venue, "label": LABELS[venue], "ok": False, "status": "UNAVAILABLE", "error": {"code": code, "message": message}}
        try:
            raw = await asyncio.wait_for(self.client.fetch(venue), 15)
            row = compute.enrich(raw)
            if self.demo:
                row["status"] = "DEMO"
            return {**row, "label": LABELS[venue]}
        except VenueError as e:
            return fail(e.code, e.message)
        except asyncio.TimeoutError:
            return fail("timeout", "timed out")
        except Exception as e:  # noqa: BLE001  one venue's bug must not take down the others
            return fail("internal", type(e).__name__)

    def _record(self, rows: list[dict], agg: dict) -> None:
        """At most one history point per RECORD_EVERY seconds, however often the panel polls: evenly spaced samples keep the percentiles honest."""
        if self._last_rec is not None and time.monotonic() - self._last_rec < RECORD_EVERY:
            return
        self._last_rec = time.monotonic()
        ts = iso_now()
        pts = [(ts, r["venue"], r["mark"], r["funding_annual_pct"], r["oi_btc"], r["oi_usd"], r["basis_pct"]) for r in rows if r.get("ok")]
        if agg.get("available"):
            pts.append((ts, "ALL", None, agg["funding_annual_pct"], agg["oi_btc"], agg["oi_usd"], None))
        with self.db.tx() as c:
            c.executemany("INSERT INTO deriv_history(ts,venue,mark,funding_annual_pct,oi_btc,oi_usd,basis_pct) VALUES(?,?,?,?,?,?,?)", pts)
            c.execute("DELETE FROM deriv_history WHERE ts < ?", ((datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(),))

    def _series(self, venue: str, col: str, days: float) -> list[tuple[str, float]]:
        cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return [(r["ts"], r["v"]) for r in self.db.q(f"SELECT ts, {col} AS v FROM deriv_history WHERE venue=? AND ts>=? AND {col} IS NOT NULL ORDER BY ts", (venue, cut))]

    def _context(self, agg: dict) -> dict:
        if not agg.get("available"):
            return {}
        f = [v for _, v in self._series("ALL", "funding_annual_pct", PCTILE_DAYS)]
        o = [v for _, v in self._series("ALL", "oi_usd", PCTILE_DAYS)]
        ctx = {"funding_percentile_30d": compute.percentile(f, agg["funding_annual_pct"], MIN_HISTORY), "oi_percentile_30d": compute.percentile(o, agg["oi_usd"], MIN_HISTORY)}
        now = datetime.now(timezone.utc)
        old = [(t, v) for t, v in self._series("ALL", "oi_usd", 2) if abs((datetime.fromisoformat(t) - (now - timedelta(hours=24))).total_seconds()) <= 2 * 3600]
        if old and old[0][1] > 0:
            ctx["oi_change_24h_pct"] = {"available": True, "value": (agg["oi_usd"] / old[0][1] - 1) * 100,
                                        "note": "open interest in USD, now versus the closest recorded point to 24 h ago"}
        else:
            ctx["oi_change_24h_pct"] = {"available": False, "reason": "no recorded point near 24 hours ago yet: keep ATLAS running to build history"}
        return ctx

    async def refresh(self) -> dict:
        async with self._lock:
            rows = list(await asyncio.gather(*(self._one(v) for v in VENUES)))
            agg = compute.aggregate(rows, len(VENUES))
            if not self.demo and agg.get("available"):
                self._record(rows, agg)
            snap = {"venues": rows, "aggregate": {**agg, **self._context(agg)}, "as_of": iso_now(), "demo": self.demo,
                    "history_points": self.db.q("SELECT COUNT(*) FROM deriv_history WHERE venue='ALL'")[0][0],
                    "notes": ["Perpetual swaps only. Funding positive = longs pay shorts. Open interest is summed across the venues that answered, not the whole market.",
                              "Liquidations, ETF flows and on-chain data are not included (no reliable free source); they are unavailable, not zero."]}
            self._cache = (time.monotonic(), snap)
            return snap

    async def snapshot(self, fresh: bool = False) -> dict:
        if not fresh and self._cache and time.monotonic() - self._cache[0] < CACHE_SECONDS:
            return self._cache[1]
        return await self.refresh()

    def history(self, hours: float = 48) -> dict:
        days = max(hours, 1) / 24
        f, o = self._series("ALL", "funding_annual_pct", days), self._series("ALL", "oi_usd", days)
        return {"funding_annual_pct": [{"ts": t, "v": v} for t, v in f], "oi_usd": [{"ts": t, "v": v} for t, v in o], "hours": hours}

    async def run_loop(self, seconds: float) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001  the loop must survive anything
                pass
            await asyncio.sleep(seconds)
