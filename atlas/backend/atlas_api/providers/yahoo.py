"""US equities, ETFs and indices via yfinance (unofficial; typically ~15 min delayed; personal use only).

Not a licensed consolidated feed. Replace with Massive/Alpaca/Databento adapters for Tier 2.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ..instruments import Instrument
from ..models import Candle, OHLCV, Provenance, ProviderUnavailable, Quote

_MAP = {  # interval -> (yahoo interval, period)
    "1m": ("1m", "5d"), "5m": ("5m", "1mo"), "15m": ("15m", "1mo"), "30m": ("30m", "1mo"),
    "1h": ("1h", "6mo"), "1d": ("1d", "5y"), "1w": ("1wk", "10y"), "1M": ("1mo", "max"),
}
DELAY = 900


class YahooProvider:
    name = "yahoo"
    entitlement = "unofficial delayed (personal use)"
    delay_seconds = DELAY
    native_intervals = set(_MAP)

    async def quote(self, inst: Instrument) -> Quote:
        return await asyncio.to_thread(self._quote, inst)

    def _quote(self, inst: Instrument) -> Quote:
        import yfinance as yf

        try:
            t = yf.Ticker(inst.provider_symbol)
            bars = t.history(period="5d", interval="1m", prepost=False).dropna()
            if bars.empty:
                raise ProviderUnavailable(self.name, f"no data for {inst.provider_symbol}")
            fi = t.fast_info
            prev = float(fi["previous_close"])
            day = bars[bars.index.date == bars.index[-1].date()]
            tp = (day.High + day.Low + day.Close) / 3
            vol = float(day.Volume.sum())
            ev = bars.index[-1].to_pydatetime().astimezone(timezone.utc)
            try:
                mcap = float(fi["market_cap"])
            except Exception:
                mcap = None
            return Quote(
                instrument_id=inst.id, price=float(bars.Close.iloc[-1]), open=float(day.Open.iloc[0]),
                high=float(day.High.max()), low=float(day.Low.min()), prev_close=prev, volume=vol or None,
                vwap=float((tp * day.Volume).sum() / vol) if vol else None, market_cap=mcap,
                unsupported_fields=["bid", "ask", "bid_size", "ask_size", "float", "halt_status"],
                prov=Provenance(provider=self.name, instrument_id=inst.id, venue=inst.exchange, event_time=ev,
                                ingested_time=datetime.now(timezone.utc), currency=inst.currency,
                                entitlement=self.entitlement, delay_seconds=DELAY),
            )
        except ProviderUnavailable:
            raise
        except Exception as e:
            raise ProviderUnavailable(self.name, f"{type(e).__name__}: {e}") from e

    async def ohlcv(self, inst: Instrument, interval: str, limit: int) -> OHLCV:
        return await asyncio.to_thread(self._ohlcv, inst, interval, limit)

    def _ohlcv(self, inst: Instrument, interval: str, limit: int) -> OHLCV:
        import yfinance as yf

        yi, period = _MAP[interval]
        try:
            df = yf.Ticker(inst.provider_symbol).history(period=period, interval=yi, auto_adjust=False).dropna().tail(limit)
        except Exception as e:
            raise ProviderUnavailable(self.name, f"{type(e).__name__}: {e}") from e
        if df.empty:
            raise ProviderUnavailable(self.name, f"no history for {inst.provider_symbol}")
        candles = [Candle(time=int(ts.timestamp()), open=r.Open, high=r.High, low=r.Low, close=r.Close, volume=r.Volume)
                   for ts, r in df.iterrows()]
        return OHLCV(instrument_id=inst.id, interval=interval, candles=candles,
                     adjustment="split-adjusted, not dividend-adjusted",
                     prov=Provenance(provider=self.name, instrument_id=inst.id, venue=inst.exchange,
                                     event_time=datetime.fromtimestamp(candles[-1].time, timezone.utc),
                                     ingested_time=datetime.now(timezone.utc), currency=inst.currency,
                                     entitlement=self.entitlement, delay_seconds=DELAY))
