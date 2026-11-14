"""BTC history for the Strategy Lab: Coinbase public candles (spot, USD) and Hyperliquid hourly funding. Cached in SQLite; refreshed incrementally.

Honest limits, stated to the user: Coinbase BTC-USD daily goes back to 2015 and 1h as far as we choose to fetch (default 3 years); 4h is built from 1h;
Hyperliquid funding exists only from 2023, so perpetual backtests cannot start earlier. Gaps in the bars are detected and reported, never filled.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx

from ..db import DB

CB = "https://api.exchange.coinbase.com"
HL = "https://api.hyperliquid.xyz/info"
GRAN = {"1d": 86400, "1h": 3600}
TF_SECONDS = {"1d": 86400, "4h": 14400, "1h": 3600}
BARS_PER_YEAR = {"1d": 365, "4h": 2190, "1h": 8760}
DEFAULT_START = {"1d": datetime(2015, 7, 20, tzinfo=timezone.utc), "1h": None}      # 1h start is relative (years back)
HOURLY_YEARS = 3
MAX_AGE = {"1d": 2 * 86400, "1h": 6 * 3600}


class DataError(Exception):
    pass


def resample_4h(rows: list[tuple]) -> list[tuple]:
    """1h bars (t,o,h,l,c,v) -> 4h bars aligned to 00/04/08/12/16/20 UTC. A 4h bar is built only from its four complete hours."""
    out, cur, key = [], [], None
    for r in rows:
        k = r[0] - r[0] % 14400
        if key is not None and k != key:
            if len(cur) == 4:
                out.append((key, cur[0][1], max(x[2] for x in cur), min(x[3] for x in cur), cur[-1][4], sum(x[5] for x in cur)))
            cur = []
        key = k
        cur.append(r)
    if key is not None and len(cur) == 4:
        out.append((key, cur[0][1], max(x[2] for x in cur), min(x[3] for x in cur), cur[-1][4], sum(x[5] for x in cur)))
    return out


def gaps(rows: list[tuple], step: int) -> list[dict]:
    g = []
    for a, b in zip(rows, rows[1:]):
        if b[0] - a[0] > step:
            g.append({"from": datetime.fromtimestamp(a[0], timezone.utc).isoformat(), "to": datetime.fromtimestamp(b[0], timezone.utc).isoformat(), "missing_bars": (b[0] - a[0]) // step - 1})
    return g


class BtcData:
    def __init__(self, db: DB, client: httpx.AsyncClient | None = None):
        self.db, self._client = db, client
        self._lock = asyncio.Lock()

    async def _http(self):
        return self._client or httpx.AsyncClient(timeout=30)

    async def _get_json(self, method, url, **kw):
        c = await self._http()
        try:
            for attempt in range(3):
                r = await c.request(method, url, **kw)
                if r.status_code == 429:
                    await asyncio.sleep(1 + attempt)
                    continue
                if r.status_code != 200:
                    raise DataError(f"{url.split('//')[1].split('/')[0]} returned HTTP {r.status_code}")
                return r.json()
            raise DataError("rate limited by the data source")
        except httpx.HTTPError as e:
            raise DataError(f"data source unreachable ({type(e).__name__})") from e
        finally:
            if self._client is None:
                await c.aclose()

    # --- storage ---
    def stored(self, tf: str) -> list[tuple]:
        base = "1h" if tf == "4h" else tf
        rows = [(r["t"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in self.db.q("SELECT t,o,h,l,c,v FROM btc_bars WHERE tf=? ORDER BY t", (base,))]
        return resample_4h(rows) if tf == "4h" else rows

    def funding(self) -> list[tuple[int, float]]:
        return [(r["t"], r["rate"]) for r in self.db.q("SELECT t,rate FROM btc_funding ORDER BY t")]

    def _meta(self, key, default=None):
        r = self.db.q("SELECT value FROM btc_meta WHERE key=?", (key,))
        return r[0]["value"] if r else default

    def _set_meta(self, key, value):
        self.db.x("INSERT INTO btc_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # --- fetching ---
    async def refresh_bars(self, tf: str) -> int:
        base = "1h" if tf == "4h" else tf
        g = GRAN[base]
        now = int(time.time())
        last = self.db.q("SELECT MAX(t) m FROM btc_bars WHERE tf=?", (base,))[0]["m"]
        if last is not None:
            start = last
        elif base == "1d":
            start = int(DEFAULT_START["1d"].timestamp())
        else:
            start = now - HOURLY_YEARS * 365 * 86400
        added = 0
        t = start
        while t < now:
            end = min(t + g * 300, now + g)
            data = await self._get_json("GET", f"{CB}/products/BTC-USD/candles", params={"granularity": g, "start": datetime.fromtimestamp(t, timezone.utc).isoformat(), "end": datetime.fromtimestamp(end, timezone.utc).isoformat()})
            rows = [(int(r[0]), float(r[3]), float(r[2]), float(r[1]), float(r[4]), float(r[5])) for r in data if len(r) >= 6]
            if rows:
                self.db.xmany("INSERT OR REPLACE INTO btc_bars(tf,t,o,h,l,c,v) VALUES(?,?,?,?,?,?,?)", [(base, *r) for r in rows])
                added += len(rows)
            t = end
            await asyncio.sleep(0.12)            # well under Coinbase's public rate limit
        self._set_meta(f"bars_fetched:{base}", datetime.now(timezone.utc).isoformat())
        return added

    async def refresh_funding(self) -> int:
        last = self.db.q("SELECT MAX(t) m FROM btc_funding")[0]["m"]
        start_ms = (last * 1000 + 1) if last else int(datetime(2023, 5, 1, tzinfo=timezone.utc).timestamp() * 1000)
        added = 0
        while True:
            data = await self._get_json("POST", HL, json={"type": "fundingHistory", "coin": "BTC", "startTime": start_ms})
            if not data:
                break
            rows = [(int(x["time"] // 1000), float(x["fundingRate"])) for x in data]
            self.db.xmany("INSERT OR REPLACE INTO btc_funding(t,rate) VALUES(?,?)", rows)
            added += len(rows)
            nxt = int(data[-1]["time"]) + 1
            if len(data) < 500 or nxt <= start_ms:
                break
            start_ms = nxt
            await asyncio.sleep(0.05)
        self._set_meta("funding_fetched", datetime.now(timezone.utc).isoformat())
        return added

    async def ensure(self, tf: str, need_funding: bool) -> list[str]:
        """Refresh what is stale. Returns notes about anything that could not be refreshed (the cached copy is then used and labelled)."""
        notes = []
        async with self._lock:
            base = "1h" if tf == "4h" else tf
            fetched = self._meta(f"bars_fetched:{base}")
            if not fetched or time.time() - datetime.fromisoformat(fetched).timestamp() > MAX_AGE[base] / 6:
                try:
                    await self.refresh_bars(tf)
                except DataError as e:
                    notes.append(f"Could not refresh {base} prices ({e}); using the saved copy.")
            if need_funding:
                ff = self._meta("funding_fetched")
                if not ff or time.time() - datetime.fromisoformat(ff).timestamp() > 3600:
                    try:
                        await self.refresh_funding()
                    except DataError as e:
                        notes.append(f"Could not refresh funding ({e}); using the saved copy.")
        return notes

    def status(self) -> dict:
        out = {}
        for tf in ("1d", "4h", "1h"):
            rows = self.stored(tf)
            out[tf] = {"bars": len(rows), "from": datetime.fromtimestamp(rows[0][0], timezone.utc).date().isoformat() if rows else None,
                       "to": datetime.fromtimestamp(rows[-1][0], timezone.utc).date().isoformat() if rows else None, "gaps": gaps(rows, TF_SECONDS[tf])[:5], "gap_count": len(gaps(rows, TF_SECONDS[tf]))}
        f = self.funding()
        out["funding"] = {"points": len(f), "from": datetime.fromtimestamp(f[0][0], timezone.utc).date().isoformat() if f else None, "to": datetime.fromtimestamp(f[-1][0], timezone.utc).date().isoformat() if f else None}
        return out
