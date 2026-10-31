"""Canonical market-data models. Every datum carries provenance (spec section 4.3)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class DataStatus(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    HISTORICAL = "HISTORICAL"
    STALE = "STALE"
    DEMO = "DEMO"
    UNAVAILABLE = "UNAVAILABLE"


class Provenance(BaseModel):
    provider: str
    instrument_id: str
    venue: str | None = None
    event_time: datetime | None = None      # when the market event happened
    provider_time: datetime | None = None   # provider's own timestamp, if distinct
    ingested_time: datetime                 # when we received it
    currency: str = "USD"
    session: str | None = None              # equity session state at ingest, if applicable
    entitlement: str = "unknown"
    delay_seconds: int | None = None        # declared provider delay (0 = real-time)
    status: DataStatus = DataStatus.UNAVAILABLE
    quality: list[str] = Field(default_factory=list)


class Quote(BaseModel):
    instrument_id: str
    price: float
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    prev_close_basis: str = "previous session close"   # crypto: "24h rolling open"
    volume: float | None = None
    vwap: float | None = None
    market_cap: float | None = None
    unsupported_fields: list[str] = Field(default_factory=list)
    prov: Provenance

    @computed_field
    @property
    def change(self) -> float | None:
        return None if self.prev_close is None else self.price - self.prev_close

    @computed_field
    @property
    def change_pct(self) -> float | None:
        return None if not self.prev_close else (self.price - self.prev_close) / self.prev_close * 100

    @computed_field
    @property
    def spread(self) -> float | None:
        return None if self.bid is None or self.ask is None else self.ask - self.bid


class Candle(BaseModel):
    time: int  # epoch seconds, bar open, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class OHLCV(BaseModel):
    instrument_id: str
    interval: str
    candles: list[Candle]
    adjustment: str = "none"
    line_only: bool = False  # macro series: open=high=low=close=value
    derived_from: str | None = None  # set when resampled from a finer interval
    prov: Provenance


class ProviderUnavailable(Exception):
    def __init__(self, provider: str, message: str):
        super().__init__(f"{provider}: {message}")
        self.provider, self.message = provider, message
