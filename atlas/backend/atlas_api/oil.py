"""Oil prices: WTI (US) and Brent (Europe) crude, spot, in dollars a barrel, daily, from the US Energy Information Administration (public-domain US government data) via FRED, the St. Louis Fed. Free, no key.

How to read it: a spot price is what a barrel costs for immediate delivery. Brent is usually a few dollars above WTI. EIA data reach FRED a few days late, so the newest figure is normally two to four days old and every figure carries its own date.
Checks: each series' last 60 values are above zero and under $250, its last 20 values are no more than 5 days apart (weekends and holidays only), no one-day move over 40% in the last 60 values, the two series' newest dates are within 7 days of each other, and Brent minus WTI on the newest common day is between -20 and +80 dollars (a unit slip in one series would break it; the real range in the last 18 months is -2.45 to +37.62). A missing value ('.') is left out, never filled in.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .claims import _pct, reading
from .fincond import parse

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "US Energy Information Administration spot prices, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/DCOILWTICO"
SERIES = {"DCOILWTICO": "wti", "DCOILBRENTEU": "brent"}
NAMES = {"wti": "WTI crude (US)", "brent": "Brent crude (Europe)"}
LIMITS = (0.0, 250.0)                # dollars a barrel, above zero. WTI closed at -$37.63 on 2020-04-20; crossing zero is a move of more than 100%, so that day would be refused (and the card would say so) rather than shown on doubt
MAX_GAP_DAYS = 5                     # weekends and holidays only (the real series has gaps of 4 and 5 days, never more)
MAX_MOVE = 0.40                      # the real largest one-day moves in the last 18 months are 16.6% (WTI) and 18.0% (Brent)
MAX_DATE_SKEW_DAYS = 7
SPREAD_LIMITS = (-20.0, 80.0)        # Brent minus WTI: the real range in the last 18 months is -2.45 to +37.62; wide enough for a real dislocation, narrow enough that a x10 or /10 slip (beyond +-100) is caught
OVERDUE_AFTER_DAYS = 14
TTL = 6 * 3600.0
FAIL_TTL = 120.0
LOOKUP_DAYS = 5


def _on_or_before(s: dict[date, float], day: date, within: int = LOOKUP_DAYS) -> float | None:
    """The value on `day` or the latest one before it, if that is no more than `within` days earlier (a holiday has no price)."""
    for back in range(within + 1):
        v = s.get(day - timedelta(days=back))
        if v is not None:
            return v
    return None


def _one(s: dict[date, float], today: date) -> dict:
    ks = sorted(s)
    last = ks[-1]
    v = s[last]
    year = [d for d in ks if 0 <= (last - d).days <= 365]
    vals = [s[d] for d in year]
    rank = round(100 * sum(1 for x in vals if x <= v) / len(vals))
    prev = s[ks[-2]]
    return {"value": round(v, 2), "date": last.isoformat(), "age_days": (today - last).days, "freshness": "CURRENT" if (today - last).days <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "change_1d": round(v - prev, 2), "change_1m_pct": _pct(v, _on_or_before(s, last - timedelta(days=30))), "change_1y_pct": _pct(v, _on_or_before(s, last - timedelta(days=365))),
            "year_low": round(min(vals), 2), "year_high": round(max(vals), 2), "days_in_year": len(vals), "rank_in_year": rank, "reading": reading(rank)}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    w, b = data["DCOILWTICO"], data["DCOILBRENTEU"]
    for sid, s in data.items():
        recent = sorted(s)[-60:]
        if any(not (LIMITS[0] < s[d] <= LIMITS[1]) for d in recent):
            raise ValueError(f"{sid} has a value outside the plausible range")
        last20 = sorted(s)[-20:]
        if any((y - x).days > MAX_GAP_DAYS for x, y in zip(last20, last20[1:])):
            raise ValueError(f"{sid} has a gap of more than {MAX_GAP_DAYS} days in its last 20 values")
        if any(s[x] != 0 and abs(s[y] / s[x] - 1) > MAX_MOVE for x, y in zip(recent, recent[1:])):
            raise ValueError(f"{sid} moved more than {MAX_MOVE:.0%} in a day")
    lw, lb = max(w), max(b)
    if abs((lw - lb).days) > MAX_DATE_SKEW_DAYS:
        raise ValueError("the two series are not up to the same week")
    common = max(set(w) & set(b), default=None)
    if common is None:
        raise ValueError("the two series have no day in common")
    spread = b[common] - w[common]
    if not (SPREAD_LIMITS[0] <= spread <= SPREAD_LIMITS[1]):
        raise ValueError(f"Brent minus WTI is {spread:.2f}, outside {SPREAD_LIMITS[0]:g} to {SPREAD_LIMITS[1]:g}")
    return {"available": True, "source": SOURCE, "url": PAGE, "wti": _one(w, today), "brent": _one(b, today),
            "spread": {"value": round(spread, 2), "date": common.isoformat()},
            "history": [{"date": d.isoformat(), "wti": round(w[d], 2)} for d in sorted(w)[-60:]],
            "checks": {"range_ok": True, "spacing_ok": True, "daily_move_ok": True, "same_week": True, "spread_in_range": True},
            "note": ("A spot price is what a barrel of crude costs for immediate delivery, in US dollars (WTI is the US benchmark, Brent the European one; Brent is usually a few dollars higher). "
                     "The figures come from the US Energy Information Administration and reach FRED a few days late, so each one carries its own date. "
                     "Checked: every recent price is above zero and under $250, the last 20 prices are no more than 5 days apart, no one-day move is over 40%, the two series are up to the same week and Brent minus WTI is in a plausible range. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class OilPrices:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast. cosd keeps the download to about two years.
        r = await c.get(URL, params={"id": sid, "cosd": (date.today() - timedelta(days=800)).isoformat()})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real oil prices are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Oil prices could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
