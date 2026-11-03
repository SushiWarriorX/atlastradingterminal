"""Crypto fundamentals data: token supply and protocol facts.

- CoinGecko public API (keyless, rate-limited; an optional free key goes in COINGECKO_API_KEY on the SERVER): supply, market cap, fully diluted value, rank,
  categories, description, and GitHub commit activity where provided.
- Bitcoin protocol rules computed in code (block subsidy, supply issued, next halving) from the block height reported by mempool.space.
Not available from any source used here: token unlock schedules, governance details, and on-chain activity for tokens other than Bitcoin. Those are reported as
missing. Both adapters were written from the documented response shapes and have NOT been run against the live services; check each service's terms before
redistributing its data.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import httpx

from ..models import ProviderUnavailable
from .etf import clean

COINGECKO = "https://api.coingecko.com/api/v3"
MEMPOOL = "https://mempool.space/api"
HALVING_INTERVAL = 210_000
INITIAL_SUBSIDY_SATS = 50 * 100_000_000
BLOCKS_PER_DAY = 144
BLOCK_SECONDS = 600


def _n(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class CoinGeckoClient:
    name = "coingecko"

    def __init__(self, client: httpx.AsyncClient | None = None, api_key: str | None = None):
        self.c = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), headers={"User-Agent": "atlas-signal/0.1"})
        self.key = api_key

    async def coin(self, cg_id: str) -> dict:
        try:
            r = await self.c.get(f"{COINGECKO}/coins/{cg_id}", params={"localization": "false", "tickers": "false", "market_data": "true", "community_data": "false",
                                                                          "developer_data": "true", "sparkline": "false"},
                                 headers={"x-cg-demo-api-key": self.key} if self.key else {})
        except httpx.HTTPError as e:
            raise ProviderUnavailable(self.name, f"{type(e).__name__} (unreachable)") from None
        if r.status_code == 429:
            raise ProviderUnavailable(self.name, "rate limited (HTTP 429): try again in a minute")
        if r.status_code != 200:
            raise ProviderUnavailable(self.name, f"HTTP {r.status_code}")
        try:
            d = r.json()
        except ValueError:
            raise ProviderUnavailable(self.name, "response was not JSON") from None
        if not isinstance(d, dict) or "market_data" not in d:
            raise ProviderUnavailable(self.name, "unexpected response shape (no market_data)")
        return d


class MempoolClient:
    name = "mempool.space"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.c = client or httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0), headers={"User-Agent": "atlas-signal/0.1"})

    async def _json(self, path: str):
        try:
            r = await self.c.get(MEMPOOL + path)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderUnavailable(self.name, f"{type(e).__name__}") from None

    async def snapshot(self) -> dict:
        """Tip height (required) plus hashrate and recommended fee (optional)."""
        h = await self._json("/blocks/tip/height")
        out: dict = {"height": int(h)}
        for key, path in (("hashrate", "/v1/mining/hashrate/3d"), ("fees", "/v1/fees/recommended")):
            try:
                out[key] = await self._json(path)
            except ProviderUnavailable:
                out[key] = None
        return out


def normalize_coin(raw: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    md = raw.get("market_data") or {}
    usd = lambda k: _n((md.get(k) or {}).get("usd")) if isinstance(md.get(k), dict) else _n(md.get(k))
    circ, total, mx = _n(md.get("circulating_supply")), _n(md.get("total_supply")), _n(md.get("max_supply"))
    mcap, fdv = usd("market_cap"), usd("fully_diluted_valuation")
    dev = raw.get("developer_data") or {}
    cats = [c for c in (raw.get("categories") or []) if isinstance(c, str)][:4]
    home = next((u for u in (raw.get("links") or {}).get("homepage") or [] if isinstance(u, str) and u.startswith("http")), None)
    missing = []
    for k, v, why in (("circulating_supply", circ, "not reported"), ("max_supply", mx, "no fixed maximum is reported (the supply may be uncapped or unknown)"),
                      ("fdv", fdv, "not reported")):
        if v is None:
            missing.append((k, why))
    return {
        "name": clean(raw.get("name"), 60), "symbol": clean(raw.get("symbol"), 12), "rank": md.get("market_cap_rank") if isinstance(md.get("market_cap_rank"), int) else None,
        "circulating": circ, "total": total, "max": mx, "market_cap": mcap, "fdv": fdv,
        "pct_of_max_circulating": circ / mx * 100 if circ is not None and mx else None,
        "fdv_to_mcap": fdv / mcap if fdv is not None and mcap else None,
        "categories": cats, "genesis_date": clean(raw.get("genesis_date"), 12), "description": clean(raw.get("description", {}).get("en") if isinstance(raw.get("description"), dict) else None, 360),
        "homepage": home, "commits_4w": _n(dev.get("commit_count_4_weeks")), "stars": _n(dev.get("stars")),
        "last_updated": clean(md.get("last_updated"), 40), "missing": missing, "fetched_at": now.isoformat(),
    }


def subsidy_sats(height: int) -> int:
    return INITIAL_SUBSIDY_SATS >> (height // HALVING_INTERVAL) if height // HALVING_INTERVAL < 64 else 0


def btc_supply_sats(height: int) -> int:
    """Total subsidy issued through `height` (blocks 0..height), computed from the protocol's halving schedule."""
    total, h, era = 0, height, 0
    while h >= 0 and era < 64:
        blocks = min(h + 1, HALVING_INTERVAL)
        total += blocks * (INITIAL_SUBSIDY_SATS >> era)
        h -= HALVING_INTERVAL
        era += 1
    return total


def btc_protocol(snap: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    h = int(snap["height"])
    supply = btc_supply_sats(h) / 1e8
    sub = subsidy_sats(h) / 1e8
    nxt = (h // HALVING_INTERVAL + 1) * HALVING_INTERVAL
    remaining = nxt - h
    hr = (snap.get("hashrate") or {}).get("currentHashrate")
    fee = (snap.get("fees") or {}).get("halfHourFee")
    return {"height": h, "subsidy_btc": sub, "supply_btc": supply, "max_btc": 21_000_000.0, "pct_issued": supply / 21_000_000 * 100,
            "annual_issuance_pct": sub * BLOCKS_PER_DAY * 365 / supply * 100, "blocks_to_halving": remaining, "next_halving_height": nxt,
            "halving_estimate": (now + timedelta(seconds=remaining * BLOCK_SECONDS)).date().isoformat(),
            "hashrate_ehs": _n(hr) / 1e18 if _n(hr) is not None else None, "fee_sat_vb": _n(fee), "fetched_at": now.isoformat()}
