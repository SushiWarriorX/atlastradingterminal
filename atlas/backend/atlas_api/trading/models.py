from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .money import D


class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")   # an unknown field (e.g. a mistyped stop) must be an error, never silently dropped

    instrument_id: str
    side: Literal["buy", "sell"]
    qty: Decimal
    type: Literal["market", "limit", "stop", "stop_limit"] = "market"
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    tif: Literal["DAY", "GTC"] = "GTC"
    planned_stop: Decimal | None = None      # invalidation level used ONLY for risk sizing; it does not create an order
    portfolio_id: int | None = None

    @field_validator("qty", "limit_price", "stop_price", "planned_stop", mode="before")
    @classmethod
    def _dec(cls, v):
        if v is None or v == "":
            return None
        try:
            return D(v)
        except Exception as e:  # noqa: BLE001
            raise ValueError("must be a number") from e

    @model_validator(mode="after")
    def _shape(self):
        if self.qty is None or self.qty <= 0:
            raise ValueError("qty must be positive")
        t = self.type
        if t in ("limit", "stop_limit") and (self.limit_price is None or self.limit_price <= 0):
            raise ValueError(f"{t} orders need a positive limit_price")
        if t in ("stop", "stop_limit") and (self.stop_price is None or self.stop_price <= 0):
            raise ValueError(f"{t} orders need a positive stop_price")
        if t == "market" and (self.limit_price is not None or self.stop_price is not None):
            raise ValueError("market orders take no limit_price/stop_price")
        if t == "limit" and self.stop_price is not None:
            raise ValueError("limit orders take no stop_price")
        if t == "stop" and self.limit_price is not None:
            raise ValueError("stop orders take no limit_price (use stop_limit)")
        if self.planned_stop is not None and self.planned_stop <= 0:
            raise ValueError("planned_stop must be positive")
        return self


class RiskLimits(BaseModel):
    """Configurable limits. Enforced by backend code at order submission, never by a prompt."""
    model_config = ConfigDict(extra="forbid")
    max_risk_per_trade_pct: float = Field(default=0.5, gt=0, le=100)
    max_aggregate_risk_pct: float = Field(default=2.0, gt=0, le=100)
    daily_loss_warning_pct: float = Field(default=2.0, gt=0, le=100)
    max_daily_loss_pct: float = Field(default=3.0, gt=0, le=100)     # blocks NEW risk-increasing orders once breached
    max_position_pct: float = Field(default=10.0, gt=0, le=100)
    max_order_notional: float | None = Field(default=None, gt=0)
    max_spread_bps: dict[str, float] = Field(default_factory=lambda: {"equity": 50.0, "crypto": 20.0})
    require_stop: bool = True            # buys need a planned stop so planned risk can be computed
    allow_fractional_equities: bool = False
    blocked_symbols: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _order(self):
        if self.daily_loss_warning_pct > self.max_daily_loss_pct:
            raise ValueError("daily_loss_warning_pct must not exceed max_daily_loss_pct")
        if self.max_risk_per_trade_pct > self.max_aggregate_risk_pct:
            raise ValueError("max_risk_per_trade_pct must not exceed max_aggregate_risk_pct")
        return self


class SimParams(BaseModel):
    """Paper-fill assumptions. They are assumptions, not measurements of any real venue."""
    model_config = ConfigDict(extra="forbid")
    slippage_bps: dict[str, float] = Field(default_factory=lambda: {"equity": 2.0, "crypto": 2.0})
    assumed_half_spread_bps: dict[str, float] = Field(default_factory=lambda: {"equity": 1.0, "crypto": 1.0})   # used only when the quote has no bid/ask
    crypto_taker_fee_pct: float = Field(default=0.10, ge=0, le=5)      # percent of notional (real tiers vary: check your venue)
    equity_per_share_fee: float = Field(default=0.0, ge=0)
    participation_pct: float = Field(default=1.0, gt=0, le=100)         # max share of REPORTED daily volume filled per evaluation
    conservative_limit_fills: bool = True                               # passive limits fill only when price trades THROUGH the limit
