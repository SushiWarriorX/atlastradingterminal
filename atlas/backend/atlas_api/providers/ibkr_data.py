"""US stock and ETF market data from IBKR (TWS / IB Gateway) through the existing broker connection. READ-ONLY: only market-data calls are made here
(contract lookup, a market-data snapshot, historical bars). It never touches orders, and works on a readonly API connection.

Entitlement honesty: IBKR serves live data only with a market-data subscription. Without one, the quote is requested again as DELAYED data and is
labelled DELAYED (declared ~15 min); with no price at all this provider raises ProviderUnavailable and the service falls back to the default
provider with a visible note. Nothing is ever presented as live that was not.

UNVERIFIED AGAINST A REAL GATEWAY: written from the ib_async API as remembered and tested only against a fake. Known points to check on the first
real run: delayed ticks may arrive in `delayedLast`/`delayedBid` rather than `last`/`bid` (both are read), US stock snapshot `volume` is reported
in round lots of 100 (so volume is NOT reported here until verified), pacing limits on historical requests (error 162), and the SMART/primary-exchange
choice for ambiguous symbols. `IBKR_ENABLED=1` and `ATLAS_IBKR_DATA=1` are both required.
"""
from __future__ import annotations

import asyncio
import math
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from ..instruments import Instrument
from ..models import Candle, OHLCV, Provenance, ProviderUnavailable, Quote

NY = ZoneInfo("America/New_York")
# our interval -> (IBKR barSizeSetting, durationStr). Weekly and the odd intervals are derived by the service from these.
BARS = {"1m": ("1 min", "2 D"), "5m": ("5 mins", "1 W"), "15m": ("15 mins", "1 M"), "30m": ("30 mins", "1 M"), "1h": ("1 hour", "3 M"), "1d": ("1 day", "2 Y")}
DELAYED_SECONDS = 900


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > -1e9 and v < 1e9 else None        # IBKR encodes "unset" as ~1.8e308 or -1


def _pos(x) -> float | None:
    v = _f(x)
    return v if v is not None and v > 0 else None


def ib_symbol(sym: str) -> str:
    return sym.replace(".", " ")          # IBKR writes class shares with a space: BRK B


class IBKRData:
    name = "ibkr"
    entitlement = "IBKR market data (live if subscribed, otherwise delayed)"
    delay_seconds = None          # depends on the subscription per symbol; each quote carries its own declared delay
    native_intervals = set(BARS)

    def __init__(self, broker, timeout: float = 4.0, bars_timeout: float = 20.0):
        self.broker, self.timeout, self.bars_timeout = broker, timeout, bars_timeout
        self._contracts: dict[str, object] = {}
        self._mdtype: int | None = None
        self._lock = asyncio.Lock()          # one market-data request at a time keeps snapshot/type switching simple and well inside IBKR's rate limits

    @property
    def available(self) -> bool:
        return bool(getattr(self.broker, "connected", False))

    @staticmethod
    def handles(inst: Instrument) -> bool:
        return inst.asset_class in ("equity", "etf") and inst.currency == "USD"

    async def _contract(self, inst: Instrument):
        c = self._contracts.get(inst.id)
        if c is not None:
            return c
        from ib_async import Stock

        raw = Stock(ib_symbol(inst.symbol), "SMART", "USD")
        try:
            got = await asyncio.wait_for(self.broker.ib.qualifyContractsAsync(raw), self.timeout)
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(self.name, f"contract lookup failed ({type(e).__name__})") from e
        if not got or got[0] is None:
            raise ProviderUnavailable(self.name, f"IBKR could not identify {inst.symbol} as a unique US stock")
        self._contracts[inst.id] = got[0]
        return got[0]

    def _set_type(self, t: int) -> None:
        if self._mdtype != t:
            self.broker.ib.reqMarketDataType(t)
            self._mdtype = t

    async def _snapshot(self, contract, delayed: bool):
        ib = self.broker.ib
        self._set_type(3 if delayed else 1)
        t = ib.reqMktData(contract, "", True, False)
        try:
            end = time.monotonic() + self.timeout
            while time.monotonic() < end:
                if self._price(t, delayed) is not None:
                    break
                await asyncio.sleep(0.15)
            return t
        finally:
            try:
                ib.cancelMktData(contract)
            except Exception:  # noqa: BLE001  cancelling is best effort
                pass

    @staticmethod
    def _field(t, name: str, delayed: bool):
        v = _pos(getattr(t, name, None))
        if v is None and delayed:
            v = _pos(getattr(t, "delayed" + name[0].upper() + name[1:], None))
        return v

    def _price(self, t, delayed: bool) -> float | None:
        last = self._field(t, "last", delayed)
        if last is not None:
            return last
        bid, ask = self._field(t, "bid", delayed), self._field(t, "ask", delayed)
        return (bid + ask) / 2 if bid is not None and ask is not None and ask >= bid else None      # a midpoint is labelled as such below

    def _require(self) -> None:
        if not self.available:
            raise ProviderUnavailable(self.name, "IBKR is not connected")

    async def quote(self, inst: Instrument) -> Quote:
        self._require()
        async with self._lock:
            contract = await self._contract(inst)
            delayed = False
            t = await self._snapshot(contract, False)
            if self._price(t, False) is None:
                delayed = True
                t = await self._snapshot(contract, True)
            price = self._price(t, delayed)
        if price is None:
            raise ProviderUnavailable(self.name, f"no price for {inst.symbol} (no market-data subscription, or the market is closed with no last trade)")
        last = self._field(t, "last", delayed)
        bid, ask = self._field(t, "bid", delayed), self._field(t, "ask", delayed)
        ev = getattr(t, "time", None)
        ev = (ev if ev.tzinfo else ev.replace(tzinfo=timezone.utc)).astimezone(timezone.utc) if isinstance(ev, datetime) else datetime.now(timezone.utc)
        quality = ["market-data type: DELAYED (no live subscription for this symbol)"] if delayed else []
        if last is None:
            quality.append("no last trade: price is the bid/ask midpoint")
        return Quote(
            instrument_id=inst.id, price=price, bid=bid, ask=ask, bid_size=self._field(t, "bidSize", delayed), ask_size=self._field(t, "askSize", delayed),
            open=self._field(t, "open", delayed), high=self._field(t, "high", delayed), low=self._field(t, "low", delayed), prev_close=self._field(t, "close", delayed),
            unsupported_fields=["volume (IBKR reports US stock volume in round lots: not used until verified)", "vwap", "market_cap", "float", "halt_status"],
            prov=Provenance(provider=self.name, instrument_id=inst.id, venue="SMART", event_time=ev, ingested_time=datetime.now(timezone.utc), currency=inst.currency,
                            entitlement=self.entitlement + (" [delayed]" if delayed else " [live]"), delay_seconds=DELAYED_SECONDS if delayed else 0, quality=quality))

    async def ohlcv(self, inst: Instrument, interval: str, limit: int) -> OHLCV:
        self._require()
        size, dur = BARS[interval]
        async with self._lock:
            contract = await self._contract(inst)
            try:
                bars = await asyncio.wait_for(self.broker.ib.reqHistoricalDataAsync(
                    contract, endDateTime="", durationStr=dur, barSizeSetting=size, whatToShow="TRADES", useRTH=True, formatDate=2, keepUpToDate=False), self.bars_timeout)
            except Exception as e:  # noqa: BLE001
                raise ProviderUnavailable(self.name, f"historical request failed ({type(e).__name__}: {str(e)[:80]})") from e
        candles: list[Candle] = []
        for b in bars or []:
            o, h, l, c = _pos(b.open), _pos(b.high), _pos(b.low), _pos(b.close)
            if None in (o, h, l, c):
                continue                                   # unusable bar: dropped, never repaired
            d = b.date
            if isinstance(d, datetime):
                ts = int((d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp())
            elif isinstance(d, date):
                ts = int(datetime(d.year, d.month, d.day, tzinfo=NY).timestamp())          # daily bars: New York midnight, the same convention as the Yahoo provider
            else:
                continue
            v = _f(getattr(b, "volume", 0)) or 0.0
            candles.append(Candle(time=ts, open=o, high=h, low=l, close=c, volume=max(v, 0.0)))
        candles.sort(key=lambda x: x.time)
        if not candles:
            raise ProviderUnavailable(self.name, f"no history for {inst.symbol}")
        return OHLCV(instrument_id=inst.id, interval=interval, candles=candles[-limit:], adjustment="as reported by IBKR (split-adjusted; dividends not adjusted)",
                     prov=Provenance(provider=self.name, instrument_id=inst.id, venue="SMART", event_time=datetime.fromtimestamp(candles[-1].time, timezone.utc),
                                     ingested_time=datetime.now(timezone.utc), currency=inst.currency, entitlement=self.entitlement, delay_seconds=0,
                                     quality=["regular trading hours only; volume units as reported by IBKR (unverified)"]))
