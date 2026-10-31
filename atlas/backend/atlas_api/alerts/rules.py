"""Alert rule models and the pure edge/cooldown decision. No I/O here."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from ..resample import SECONDS

INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
Severity = Literal["info", "warning", "critical"]


class Base(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    cooldown_seconds: int = Field(default=3600, ge=60, le=7 * 86400)
    severity: Severity = "info"
    telegram: bool = True       # also send to Telegram when it is configured (per-alert opt-out)


class Instrumented(Base):
    instrument_id: str


class PriceRule(Instrumented):
    kind: Literal["price"] = "price"
    op: Literal["above", "below"]
    level: float = Field(gt=0)


class PctChangeRule(Instrumented):
    kind: Literal["pct_change"] = "pct_change"
    op: Literal["above", "below"]
    threshold: float            # percent vs previous close (24h rolling open for BTC)


class RsiRule(Instrumented):
    kind: Literal["rsi"] = "rsi"
    op: Literal["above", "below"]
    level: float = Field(ge=0, le=100)
    period: int = Field(default=14, ge=2, le=100)
    interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"] = "1d"
    on_close: bool = True       # evaluate the last COMPLETED candle (avoids repainting on the forming bar)


class MaRule(Instrumented):
    kind: Literal["ma"] = "ma"
    op: Literal["above", "below"]      # price crosses above/below the SMA
    length: int = Field(default=50, ge=2, le=400)
    interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"] = "1d"
    on_close: bool = True


class MacdRule(Instrumented):
    kind: Literal["macd"] = "macd"
    direction: Literal["bullish", "bearish"]   # histogram turns positive / negative
    interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"] = "1d"
    on_close: bool = True


class RvolRule(Instrumented):
    kind: Literal["rvol"] = "rvol"
    threshold: float = Field(gt=0)
    # Daily bars only. During the session today's volume is partial, so this under-reports until the close.


class ScanRule(Base):
    kind: Literal["scan"] = "scan"
    preset: str | None = None
    spec: dict | None = None            # a full ScanSpec, validated by the scanner module
    interval_seconds: int = Field(default=900, ge=300, le=86400)
    max_symbols: int = Field(default=10, ge=1, le=50)
    cooldown_seconds: int = Field(default=86400, ge=60, le=7 * 86400)   # per-symbol re-alert cooldown


AlertRule = Annotated[PriceRule | PctChangeRule | RsiRule | MaRule | MacdRule | RvolRule | ScanRule, Field(discriminator="kind")]
RULE = TypeAdapter(AlertRule)
INSTRUMENT_KINDS = {"price", "pct_change", "rsi", "ma", "macd", "rvol"}


def parse_rule(data: dict):
    r = RULE.validate_python(data)
    if isinstance(r, ScanRule) and bool(r.preset) == bool(r.spec):
        raise ValueError("scan alert needs exactly one of preset or spec")
    return r


def interval_seconds(i: str) -> int:
    return SECONDS[i]


def decide(prev: bool | None, now_state: bool, last_fired_at: float | None, now_ts: float, cooldown: int) -> str:
    """Edge-triggered decision.

    baseline  : first observation (prev unknown); establishes state, never fires
    fire      : false -> true and the cooldown has elapsed
    suppressed: false -> true but still inside the cooldown (logged, not notified)
    none      : no edge
    """
    if prev is None:
        return "baseline"
    if prev or not now_state:
        return "none"
    if last_fired_at is not None and now_ts - last_fired_at < cooldown:
        return "suppressed"
    return "fire"
