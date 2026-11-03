"""Data-freshness classification. Pure function: no I/O, fully testable."""
from __future__ import annotations

from datetime import datetime, timedelta

from .models import DataStatus

CRYPTO_STALE_SECONDS = 60
EQUITY_TOLERANCE_SECONDS = 300  # on top of declared provider delay


def classify(*, provider: str, asset_class: str, event_time: datetime | None, now: datetime,
             delay_seconds: int | None, session: str | None, regular_hours_only: bool = False,
             last_open: datetime | None = None) -> tuple[DataStatus, list[str]]:
    """`last_open` is the open of the most recent equity session that has started. While the market is closed or in extended hours a price is only
    "last known" if it comes from that session or later: a price from before it means a whole session is missing, which is stale, not "market closed"."""
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
    if session in ("CLOSED", "HOLIDAY", "PREMARKET", "AFTER_HOURS") and last_open is not None and event_time < last_open - timedelta(seconds=EQUITY_TOLERANCE_SECONDS):
        return DataStatus.STALE, [f"last price is from before the latest session opened ({last_open:%Y-%m-%d %H:%M} UTC): that session is missing"]
    if session in ("CLOSED", "HOLIDAY"):
        return DataStatus.HISTORICAL, ["market closed: showing last session"]
    if regular_hours_only and session in ("PREMARKET", "AFTER_HOURS"):
        # The provider only serves regular-session prices, so an old timestamp here is expected, not a broken feed.
        return DataStatus.HISTORICAL, ["regular-session price; this provider has no pre-market/after-hours prices"]
    limit = (delay_seconds or 0) + EQUITY_TOLERANCE_SECONDS
    if age > limit:
        return DataStatus.STALE, [f"last event {int(age)}s ago (allowed {limit}s)"]
    if delay_seconds:
        return DataStatus.DELAYED, [f"provider delay ~{delay_seconds // 60} min (declared, not verified per symbol)"]
    return DataStatus.LIVE, []
