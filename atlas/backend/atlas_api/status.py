"""Data-freshness classification. Pure function: no I/O, fully testable."""
from __future__ import annotations

from datetime import datetime

from .models import DataStatus

CRYPTO_STALE_SECONDS = 60
EQUITY_TOLERANCE_SECONDS = 300  # on top of declared provider delay


def classify(*, provider: str, asset_class: str, event_time: datetime | None, now: datetime,
             delay_seconds: int | None, session: str | None) -> tuple[DataStatus, list[str]]:
    if provider == "demo":
        return DataStatus.DEMO, ["synthetic demo data: not market data"]
    if asset_class == "macro":
        return DataStatus.HISTORICAL, ["official series; observation date lags publication"]
    if event_time is None:
        return DataStatus.STALE, ["provider returned no event timestamp"]
    age = (now - event_time).total_seconds()
    if asset_class == "crypto":
        if age > CRYPTO_STALE_SECONDS:
            return DataStatus.STALE, [f"last event {int(age)}s ago"]
        return DataStatus.LIVE, []
    if session in ("CLOSED", "HOLIDAY"):
        return DataStatus.HISTORICAL, ["market closed: showing last session"]
    limit = (delay_seconds or 0) + EQUITY_TOLERANCE_SECONDS
    if age > limit:
        return DataStatus.STALE, [f"last event {int(age)}s ago (allowed {limit}s)"]
    if delay_seconds:
        return DataStatus.DELAYED, [f"provider delay ~{delay_seconds // 60} min (declared, not verified per symbol)"]
    return DataStatus.LIVE, []
