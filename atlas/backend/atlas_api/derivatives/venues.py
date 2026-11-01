"""BTC perpetual-swap data from public exchange endpoints (no keys): Hyperliquid, Binance USD-M, Bybit linear, OKX.

Each parser turns one venue's raw JSON into the SAME small record: mark, index, funding rate PER INTERVAL (a fraction), the interval in hours,
open interest in BTC, and the venue's own timestamp. Units are normalised here and nowhere else; compute.py does all arithmetic.

UNVERIFIED AGAINST THE LIVE APIS: the build sandbox had no internet. Endpoint paths and field names are from the public documentation as
remembered. Anything that does not match raises VenueError("shape") and shows up as that venue FAILED, never as a guess.
Funding intervals: OKX reports the next funding time so the interval is measured; Hyperliquid funds hourly; Binance and Bybit are assumed 8 h
(the default for BTC) and say so in `notes`. Some exchanges refuse connections from some countries: HTTP 403/451 is reported as a regional block.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from ..numeric import num

VENUES = ("hyperliquid", "binance", "bybit", "okx")
LABELS = {"hyperliquid": "Hyperliquid", "binance": "Binance (USD-M)", "bybit": "Bybit (linear)", "okx": "OKX (swap)"}


class VenueError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _need(d: dict, key: str, venue: str, positive: bool = False) -> float:
    v = num(d.get(key))
    if v is None or (positive and v <= 0):
        raise VenueError("shape", f"{venue}: missing or invalid '{key}'")
    return v


def _ms(x) -> int:
    v = num(x)
    return int(v) if v else 0


def _rec(venue, mark, index, rate, interval_h, oi_base, ts_ms, notes=None, next_ms=None) -> dict:
    if interval_h is None or interval_h <= 0 or interval_h > 48:
        raise VenueError("shape", f"{venue}: implausible funding interval {interval_h}")
    if oi_base < 0 or mark <= 0:
        raise VenueError("shape", f"{venue}: implausible mark price or open interest")
    return {"venue": venue, "mark": mark, "index": index, "funding_rate": rate, "funding_interval_h": interval_h, "oi_btc": oi_base,
            "ts_ms": ts_ms, "next_funding_ms": next_ms, "notes": notes or []}


def parse_hyperliquid(payload) -> dict:
    try:
        meta, ctxs = payload[0], payload[1]
        i = next(k for k, u in enumerate(meta["universe"]) if u.get("name") == "BTC")
        c = ctxs[i]
    except (TypeError, KeyError, IndexError, StopIteration):
        raise VenueError("shape", "hyperliquid: BTC not found in metaAndAssetCtxs") from None
    now = datetime.now(timezone.utc)
    nxt = now.replace(minute=0, second=0, microsecond=0).timestamp() * 1000 + 3_600_000
    return _rec("hyperliquid", _need(c, "markPx", "hyperliquid", True), num(c.get("oraclePx")), _need(c, "funding", "hyperliquid"), 1.0,
                _need(c, "openInterest", "hyperliquid"), int(now.timestamp() * 1000), ["funding is hourly; no server timestamp in this response (local receive time used)"], int(nxt))


def parse_binance(premium: dict, oi: dict) -> dict:
    if not isinstance(premium, dict) or not isinstance(oi, dict):
        raise VenueError("shape", "binance: unexpected response")
    if "code" in premium and "markPrice" not in premium:
        raise VenueError("api", f"binance: {str(premium.get('msg', premium.get('code')))[:80]}")
    return _rec("binance", _need(premium, "markPrice", "binance", True), num(premium.get("indexPrice")), _need(premium, "lastFundingRate", "binance"), 8.0,
                _need(oi, "openInterest", "binance"), _ms(premium.get("time")) or _ms(oi.get("time")), ["funding interval assumed 8 h (the BTCUSDT default)"],
                _ms(premium.get("nextFundingTime")) or None)


def parse_bybit(tickers: dict) -> dict:
    try:
        if str(tickers.get("retCode")) != "0":
            raise VenueError("api", f"bybit: {str(tickers.get('retMsg'))[:80]}")
        t = tickers["result"]["list"][0]
    except (TypeError, KeyError, IndexError, AttributeError):
        raise VenueError("shape", "bybit: unexpected tickers response") from None
    return _rec("bybit", _need(t, "markPrice", "bybit", True), num(t.get("indexPrice")), _need(t, "fundingRate", "bybit"), 8.0, _need(t, "openInterest", "bybit"),
                _ms(tickers.get("time")), ["funding interval assumed 8 h (the BTCUSDT default)"], _ms(t.get("nextFundingTime")) or None)


def _okx_first(d: dict, what: str) -> dict:
    try:
        if str(d.get("code")) != "0":
            raise VenueError("api", f"okx {what}: {str(d.get('msg'))[:80]}")
        return d["data"][0]
    except (TypeError, KeyError, IndexError, AttributeError):
        raise VenueError("shape", f"okx: unexpected {what} response") from None


def parse_okx(funding: dict, oi: dict, mark: dict, index: dict) -> dict:
    f, o, m, i = _okx_first(funding, "funding-rate"), _okx_first(oi, "open-interest"), _okx_first(mark, "mark-price"), _okx_first(index, "index-tickers")
    t0, t1 = num(f.get("fundingTime")), num(f.get("nextFundingTime"))
    hours = (t1 - t0) / 3_600_000 if t0 and t1 and t1 > t0 else None
    if hours is None:
        raise VenueError("shape", "okx: cannot measure the funding interval")
    return _rec("okx", _need(m, "markPx", "okx", True), num(i.get("idxPx")), _need(f, "fundingRate", "okx"), round(hours, 4), _need(o, "oiCcy", "okx"),
                _ms(o.get("ts")) or _ms(m.get("ts")), ["open interest = the venue's coin-denominated figure (oiCcy)"], int(t1))


class VenueClient:
    """Async fetchers. A failure is a VenueError with a plain reason; the URL is never echoed."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.c = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))

    async def _req(self, method: str, url: str, **kw):
        try:
            r = await self.c.request(method, url, **kw)
        except httpx.TimeoutException:
            raise VenueError("timeout", "timed out") from None
        except httpx.HTTPError as e:
            raise VenueError("network", f"unreachable ({type(e).__name__})") from None
        return self._json(r)

    async def _get(self, url: str, params: dict | None = None):
        return await self._req("GET", url, params=params)

    async def _post(self, url: str, body: dict):
        return await self._req("POST", url, json=body)

    @staticmethod
    def _json(r: httpx.Response):
        if r.status_code in (403, 451):
            raise VenueError("blocked", f"the exchange refused the connection (HTTP {r.status_code}): often a regional or network restriction")
        if r.status_code == 429:
            raise VenueError("rate_limited", "rate limited (HTTP 429)")
        if r.status_code >= 400:
            raise VenueError("http", f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise VenueError("shape", "response was not JSON") from None

    async def hyperliquid(self) -> dict:
        return parse_hyperliquid(await self._post("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"}))

    async def binance(self) -> dict:
        p, o = await asyncio.gather(self._get("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"}),
                                    self._get("https://fapi.binance.com/fapi/v1/openInterest", {"symbol": "BTCUSDT"}))
        return parse_binance(p, o)

    async def bybit(self) -> dict:
        return parse_bybit(await self._get("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"}))

    async def okx(self) -> dict:
        b = "https://www.okx.com/api/v5"
        f, o, m, i = await asyncio.gather(self._get(f"{b}/public/funding-rate", {"instId": "BTC-USDT-SWAP"}),
                                          self._get(f"{b}/public/open-interest", {"instType": "SWAP", "instId": "BTC-USDT-SWAP"}),
                                          self._get(f"{b}/public/mark-price", {"instType": "SWAP", "instId": "BTC-USDT-SWAP"}),
                                          self._get(f"{b}/market/index-tickers", {"instId": "BTC-USDT"}))
        return parse_okx(f, o, m, i)

    async def fetch(self, venue: str) -> dict:
        return await {"hyperliquid": self.hyperliquid, "binance": self.binance, "bybit": self.bybit, "okx": self.okx}[venue]()
