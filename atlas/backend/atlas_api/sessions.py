"""US equity session state from the official NYSE calendar (exchange_calendars XNYS)."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

NY = ZoneInfo("America/New_York")
PRE_OPEN, AFTER_CLOSE = time(4, 0), time(20, 0)  # extended-hours bounds (NYSE Arca / Nasdaq typical)


@lru_cache(maxsize=1)
def _cal():
    import exchange_calendars as xcals

    return xcals.get_calendar("XNYS")


def session_state(now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ny = now.astimezone(NY)
    d = pd.Timestamp(ny.date())
    cal = _cal()
    info = {"ny_time": ny.isoformat(), "early_close": False, "holiday_reason": None}
    if not cal.is_session(d):
        info["state"] = "CLOSED" if ny.weekday() >= 5 else "HOLIDAY"
        info["holiday_reason"] = "weekend" if ny.weekday() >= 5 else "NYSE holiday"
    else:
        o = cal.session_open(d).to_pydatetime()
        c = cal.session_close(d).to_pydatetime()
        info["early_close"] = c.astimezone(NY).time() < time(16, 0)
        pre = datetime.combine(ny.date(), PRE_OPEN, NY)
        post_end = datetime.combine(ny.date(), AFTER_CLOSE, NY)
        if o <= now < c:
            info["state"] = "REGULAR"
        elif pre <= now < o:
            info["state"] = "PREMARKET"
        elif c <= now < post_end:
            info["state"] = "AFTER_HOURS"
        else:
            info["state"] = "CLOSED"
        info["session_open"], info["session_close"] = o.isoformat(), c.isoformat()
    info["next_open"] = _next_open(now).isoformat()
    return info


def _next_open(now: datetime) -> datetime:
    cal = _cal()
    ts = pd.Timestamp(now)
    return cal.next_open(ts - pd.Timedelta(seconds=1)).to_pydatetime() if cal.is_open_on_minute(ts, ignore_breaks=True) is False else cal.next_open(ts).to_pydatetime()


def next_session_close(now: datetime) -> datetime:
    """The close of the regular session that a DAY order placed at `now` is valid for: today's if it has not closed, else the next session's."""
    cal = _cal()
    ts = pd.Timestamp(now.astimezone(timezone.utc))
    return cal.next_close(ts).to_pydatetime()
