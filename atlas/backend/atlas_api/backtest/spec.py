"""Backtest specification. Entry rules reuse the scanner's validated filters, so a backtest tests exactly what a scan shows."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..scanner.rules import Filter


class BtSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "Backtest"
    universe: str = "core"
    benchmark: str = "SPY"
    side: Literal["long", "short"] = "long"
    entry: list[Filter] = Field(min_length=1)                 # evaluated on the CLOSE of a bar; fills at the NEXT bar's open
    exit_filters: list[Filter] = Field(default_factory=list)  # all true at a close -> exit at the next open
    stop_atr: float | None = Field(2.0, gt=0, le=20)          # stop distance in ATR(14) multiples from the entry fill
    target_r: float | None = Field(None, gt=0, le=50)         # profit target in multiples of the stop distance
    max_hold_bars: int = Field(20, ge=1, le=250)
    commission_bps: float = Field(1.0, ge=0, le=100)          # per side, % of notional / 100
    slippage_bps: float = Field(5.0, ge=0, le=500)            # per side, applied against the trade on market-type fills
    initial_capital: float = Field(100_000.0, gt=0)
    risk_pct: float = Field(1.0, gt=0, le=10)                 # % of equity risked per trade (needs a stop)
    max_position_pct: float = Field(20.0, gt=0, le=100)       # cap on one position's notional, % of equity
    max_positions: int = Field(10, ge=1, le=100)
    oos_fraction: float = Field(0.3, ge=0, le=0.8)            # last fraction of the timeline is the held-out period
    start: date | None = None                                 # only signals on/after this date open trades
    end: date | None = None                                   # only signals on/before this date open trades
    max_symbols: int = Field(60, ge=1, le=200)

    @model_validator(mode="after")
    def _check(self):
        if self.target_r is not None and self.stop_atr is None:
            raise ValueError("target_r needs stop_atr (the target is a multiple of the stop distance)")
        if self.start and self.end and self.start > self.end:
            raise ValueError("start is after end")
        return self
