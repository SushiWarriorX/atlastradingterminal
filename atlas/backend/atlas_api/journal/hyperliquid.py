"""Hyperliquid fills and funding -> journal executions and cash flows.

READ-ONLY and keyless: Hyperliquid's public `info` endpoint returns an account's history from its public wallet ADDRESS. No private key,
API-wallet secret or signature is ever needed, requested, accepted or stored. Anything shaped like a key is rejected.

UNVERIFIED AGAINST THE LIVE API: the response field names below (coin, px, sz, side B/A, time ms, fee, feeToken, tid, dir, startPosition,
closedPnl, liquidation; funding rows with delta.usdc) are from the public documentation as remembered while building; the build sandbox
could not reach api.hyperliquid.xyz. Every row that does not parse is COUNTED with a reason (never dropped silently), and the sync result
shows reported-vs-derived totals so a mismatch is visible on the first real sync.

Limits of the source: the API serves only an account's most recent fills (about 10,000), so a long history can be truncated. When the
oldest fill we have starts from a non-flat position (`startPosition` != 0) the earlier opening fills are missing, and that is reported as a
warning because FIFO matching would otherwise treat the first fill as a fresh open.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

from ..trading.money import ZERO
from .importers import ParseResult
from .matching import Exec, Flow

ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
STABLES = {"USDC", "USDT0", "USDH", "USDT"}
PAGE = 2000
MAX_PAGES = 5            # 10,000 fills: the API's own history limit


def valid_address(a: str) -> str:
    a = (a or "").strip()
    if re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", a):
        raise ValueError("that looks like a PRIVATE KEY, not a wallet address. Never paste a private key anywhere: only the public 0x address (42 characters) is needed")
    if not ADDRESS.match(a):
        raise ValueError("a Hyperliquid address is 0x followed by 40 hex characters")
    return a.lower()


def source_name(address: str) -> str:
    return f"hyperliquid:{address[:6]}…{address[-4:]}"


def _dec(v) -> Decimal | None:
    try:
        d = Decimal(str(v))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _ts(ms) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc)


def _symbol(coin: str, perp: bool) -> str:
    return f"{coin.upper()}-PERP" if perp else coin.upper()


def parse_fills(rows: list[dict], address: str) -> ParseResult:
    res = ParseResult(kind="trades", headers=[], mapping={"api": "hyperliquid userFillsByTime"}, options={"address": address}, rows_total=len(rows))
    seen: set[str] = set()
    notes: Counter = Counter()
    reported_pnl = ZERO
    for r in rows:
        try:
            coin, side, px, sz, t = r["coin"], r["side"], _dec(r["px"]), _dec(r["sz"]), r["time"]
            if not coin or side not in ("B", "A") or px is None or sz is None or px <= 0 or sz <= 0:
                res.skipped["unusable price/size/side"] += 1
                continue
            d = str(r.get("dir") or "")
            perp = d not in ("Buy", "Sell")                # spot fills carry dir "Buy"/"Sell"; perps carry "Open Long", "Close Short", ...
            ext = str(r.get("tid") or "") or f"{r.get('hash')}-{r.get('oid')}-{t}-{r['px']}-{r['sz']}"
            if ext in seen:
                res.skipped["duplicate in response"] += 1
                continue
            seen.add(ext)
            fee = _dec(r.get("fee", "0")) or ZERO
            token = str(r.get("feeToken") or "USDC").upper()
            if token not in STABLES:
                if token == coin.upper():
                    fee = fee * px                           # fee paid in the base token: convert at the fill price
                else:
                    notes[f"fee paid in {token} not converted (counted as 0)"] += 1
                    fee = ZERO
            fee += _dec(r.get("builderFee", "0")) or ZERO
            liq = r.get("liquidation")
            liquidated = isinstance(liq, dict) and str(liq.get("liquidatedUser", "")).lower() == address.lower()
            res.executions.append(Exec(source=source_name(address), ext_id=ext, ts=_ts(t), symbol=_symbol(coin, perp), asset_class="crypto",
                                       side="buy" if side == "B" else "sell", qty=sz, price=px, fee=fee, kind="liquidation" if liquidated else "trade",
                                       currency="USD"))
            res.kinds["liquidation" if liquidated else "trade"] += 1
            reported_pnl += _dec(r.get("closedPnl", "0")) or ZERO
        except (KeyError, TypeError, ValueError, OverflowError, OSError) as e:
            res.skipped[f"unparseable row ({type(e).__name__})"] += 1
    res.warnings.extend(f"{n} fill(s): {k}" for k, n in notes.items())
    res.options["reported_closed_pnl"] = str(reported_pnl)
    res.options["start_position_warnings"] = _history_gaps(rows)
    res.warnings.extend(res.options["start_position_warnings"])
    return res


def _history_gaps(rows: list[dict]) -> list[str]:
    """The oldest fill per coin should start from a flat position. If not, earlier fills are missing (the API's history window)."""
    first: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: (int(x.get("time", 0)), str(x.get("tid", "")))):
        c = r.get("coin")
        if c and c not in first:
            first[c] = r
    out = []
    for c, r in first.items():
        sp = _dec(r.get("startPosition", "0"))
        if sp is not None and sp != 0 and str(r.get("dir", "")) not in ("Buy", "Sell"):
            out.append(f"{c}: the oldest fill we have starts from an existing position of {sp}, so earlier opening fills are missing; "
                       "the first trade there is incomplete and its P&L is unreliable")
    return out


def parse_funding(rows: list[dict], address: str) -> list[Flow]:
    out: list[Flow] = []
    for r in rows:
        try:
            d = r["delta"]
            if d.get("type") != "funding":
                continue
            amt = _dec(d["usdc"])
            if amt is None:
                continue
            out.append(Flow(source=source_name(address), ext_id=f"{r.get('hash')}-{d['coin']}-{r['time']}", ts=_ts(r["time"]), symbol=_symbol(d["coin"], True),
                            kind="funding", amount=amt, currency="USD"))
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
    return out


class HyperliquidError(Exception):
    pass


class HyperliquidClient:
    """Thin async client for the public info endpoint. `base` is overridable for tests and self-hosted proxies."""

    def __init__(self, base: str = "https://api.hyperliquid.xyz", client: httpx.AsyncClient | None = None):
        self.base = base.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=15)

    async def _post(self, body: dict) -> list[dict]:
        try:
            r = await self.client.post(f"{self.base}/info", json=body)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise HyperliquidError(f"Hyperliquid API unavailable: {type(e).__name__}") from e
        if not isinstance(data, list):
            raise HyperliquidError("unexpected response shape from Hyperliquid (expected a list)")
        return data

    async def _paged(self, kind: str, address: str) -> list[dict]:
        """Time-paged fetch. The next page starts AT the last timestamp seen (not +1) so fills sharing that millisecond are not skipped;
        the overlap is removed by the caller's dedupe on the fill id. A page that cannot advance ends the loop instead of spinning."""
        out: list[dict] = []
        start = 0
        for _ in range(MAX_PAGES):
            page = await self._post({"type": kind, "user": address, "startTime": start})
            out += page
            if len(page) < PAGE:
                break
            last = max(int(x["time"]) for x in page)
            if last <= start:
                break
            start = last
        return out

    async def fills(self, address: str) -> list[dict]:
        return await self._paged("userFillsByTime", address)

    async def funding(self, address: str) -> list[dict]:
        return await self._paged("userFunding", address)
