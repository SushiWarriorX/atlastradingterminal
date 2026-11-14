"""Whole-crypto-market snapshot from CoinGecko's free public API: total value, 24-hour change and volume, and how the market is split (Bitcoin and Ether share, stablecoin share).
No key. Data provided by CoinGecko; shown with that credit and a link.

Why it is watched: Bitcoin's share of the whole market ("dominance") rises when money prefers the safest crypto and falls when it spreads into smaller coins. The stablecoin share rises
when people sit in cash-like tokens. These describe the market's mood and structure; they are not signals. What it is not: an official statistic. CoinGecko's totals depend on which coins
it lists and how it counts supply, and differ between data providers. Shown with its timestamp; a failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

URL = "https://api.coingecko.com/api/v3/global"
SOURCE = "CoinGecko (free public API; totals depend on which coins it lists and how it counts supply)"
TTL = 900.0
FAIL_TTL = 120.0
OVERDUE_AFTER_SECONDS = 3 * 3600


def parse(payload: dict, now: datetime) -> dict:
    d = payload["data"]
    cap = float(d["total_market_cap"]["usd"])
    vol = float(d["total_volume"]["usd"])
    pct = d["market_cap_percentage"]
    if cap <= 0:
        raise ValueError("the source returned a zero market value")
    upd = datetime.fromtimestamp(int(d["updated_at"]), timezone.utc)
    age = (now - upd).total_seconds()
    stable = [k for k in ("usdt", "usdc") if k in pct]
    return {"available": True, "updated_at": upd.isoformat(), "age_minutes": round(age / 60), "freshness": "CURRENT" if age <= OVERDUE_AFTER_SECONDS else "OVERDUE",
            "total_market_cap_trillions": round(cap / 1e12, 3), "change_24h_pct": round(float(d["market_cap_change_percentage_24h_usd"]), 2), "volume_24h_billions": round(vol / 1e9, 1),
            "volume_to_cap_pct": round(vol / cap * 100, 1), "btc_dominance_pct": round(float(pct["btc"]), 1), "eth_dominance_pct": round(float(pct["eth"]), 1),
            "other_pct": round(100 - float(pct["btc"]) - float(pct["eth"]), 1), "stablecoin_share_pct": round(sum(float(pct[k]) for k in stable), 1) if stable else None,
            "stablecoin_note": "Share held by Tether (USDT) and USD Coin (USDC) only." if stable else None, "coins": int(d["active_cryptocurrencies"]), "markets": int(d["markets"]),
            "top": [{"symbol": k.upper(), "share_pct": round(float(v), 1)} for k, v in sorted(pct.items(), key=lambda kv: -float(kv[1]))[:8]]}


class CoinGeckoGlobal:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "source": SOURCE, "url": "https://www.coingecko.com", "credit": "Data provided by CoinGecko",
                "note": "Describes the crypto market's size and structure right now. Bitcoin's share rises when money prefers the largest coin and falls when it spreads into smaller ones. Descriptive, not a signal."}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: real market data is not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=20)
        try:
            r = await c.get(URL, headers={"User-Agent": "ATLAS research terminal", "Accept": "application/json"})
            if r.status_code != 200:
                raise ValueError("rate limited (HTTP 429), try again in a minute" if r.status_code == 429 else f"HTTP {r.status_code}")
            res = {**base, **parse(r.json(), now)}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"CoinGecko could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
