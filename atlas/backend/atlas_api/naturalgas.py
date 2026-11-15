"""Natural gas price: the Henry Hub spot price in dollars per million BTU, daily, from the US Energy Information Administration (public-domain US government data) via FRED, the St. Louis Fed. Free, no key.

How to read it: a spot price is what the gas costs for immediate delivery; Henry Hub, a pipeline hub in Louisiana, is the US benchmark. A BTU is a unit of heat, so the price is per million units of heat. EIA data reach FRED a few days late, so the newest figure is normally 2 to 5 days old and carries its own date. In a cold snap the price can jump several-fold for a day or two (the real largest one-day jump since 1997 was to 4.2 times the day before, on 2024-01-12), so a real spike must never be refused.
Checks: each of the last 60 daily prices is between $0.50 and $60 (the real range since 1997 is 1.21 to 30.72); the last 20 prices are no more than 7 days apart (the real longest gap since 2018 is 5); no one-day move to more than 6 times, or to less than a sixth of, the price before (the real extremes are 4.19 times and 0.25 times, so a x10 or /10 slip is caught and a real spike is not); and, for the last 3 finished months that have both a monthly figure and at least 15 daily prices, the average of the daily prices is within 5 cents of the monthly figure EIA publishes (the real largest difference since 2018 is 0.8 cents, rounding). At least 2 months must be comparable. A missing value is left out, never filled in.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import httpx

from .claims import _pct, reading
from .failreason import fail_reason
from .fincond import parse
from .oil import _on_or_before

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "US Energy Information Administration Henry Hub natural gas spot price, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/DHHNGSP"
SERIES = {"DHHNGSP": "daily", "MHHNGSP": "monthly"}
LIMITS = (0.5, 60.0)                 # dollars per million BTU; the real range since 1997 is 1.21 to 30.72 (a /10 slip of a $3 price gives 0.30 and is caught)
MAX_FACTOR = 6.0                     # one-day move: to more than this many times, or to less than 1/this of, the price before; the real extremes since 1997 are 4.19 up and 0.25 down
MAX_GAP_DAYS = 7                     # between prices, in the last 20 (weekends and holidays only; the real longest since 2018 is 5)
MONTH_TOLERANCE = 0.05               # dollars: the average of a month's daily prices against the monthly figure (the real largest difference since 2018 is 0.0084)
MIN_DAYS_IN_MONTH = 15
MONTHS_CHECKED = 3
MIN_MONTHS_COMPARED = 2
OVERDUE_AFTER_DAYS = 14
TTL = 6 * 3600.0
FAIL_TTL = 120.0


def _compare_months(d: dict[date, float], m: dict[date, float], today: date) -> list[dict]:
    """The latest finished months that have a monthly figure and enough daily prices, each with the average of its daily prices next to the published figure. Raises if too few can be compared or one disagrees."""
    by_month: dict[tuple[int, int], list[float]] = defaultdict(list)
    for x, v in d.items():
        by_month[(x.year, x.month)].append(v)
    rows = []
    for x in sorted(m, reverse=True):
        key = (x.year, x.month)
        if key >= (today.year, today.month):
            continue                                                         # this month is not finished: its average is not final
        vals = by_month.get(key, [])
        if len(vals) < MIN_DAYS_IN_MONTH:
            continue                                                         # a month the daily window only partly covers cannot be compared
        mean = sum(vals) / len(vals)
        if abs(mean - m[x]) > MONTH_TOLERANCE:
            raise ValueError(f"the daily prices for {x.year}-{x.month:02d} average {mean:.2f} but the monthly figure is {m[x]:.2f}")
        rows.append({"month": f"{x.year}-{x.month:02d}", "average_of_daily": round(mean, 2), "published": round(m[x], 2), "days": len(vals)})
        if len(rows) == MONTHS_CHECKED:
            break
    if len(rows) < MIN_MONTHS_COMPARED:
        raise ValueError(f"fewer than {MIN_MONTHS_COMPARED} finished months can be compared with the monthly figure")
    return rows


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    d, m = data["DHHNGSP"], data["MHHNGSP"]
    days = sorted(d)
    recent = days[-60:]
    if any(not (LIMITS[0] <= d[x] <= LIMITS[1]) for x in recent):
        raise ValueError("a daily price is outside the plausible range")
    last20 = days[-20:]
    if any((b - a).days > MAX_GAP_DAYS for a, b in zip(last20, last20[1:])):
        raise ValueError(f"the daily prices have a gap of more than {MAX_GAP_DAYS} days in the last 20 values")
    if any(not (1 / MAX_FACTOR <= d[b] / d[a] <= MAX_FACTOR) for a, b in zip(recent, recent[1:])):
        raise ValueError(f"the price moved by more than a factor of {MAX_FACTOR:g} in a day")
    months = _compare_months(d, m, today)
    last = days[-1]
    v = d[last]
    year = [x for x in days if 0 <= (last - x).days <= 365]
    vals = [d[x] for x in year]
    rank = round(100 * sum(1 for x in vals if x <= v) / len(vals))
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "price": round(v, 2), "change_1d": round(v - d[days[-2]], 2), "change_1m_pct": _pct(v, _on_or_before(d, last - timedelta(days=30))), "change_1y_pct": _pct(v, _on_or_before(d, last - timedelta(days=365))),
            "year_low": round(min(vals), 2), "year_high": round(max(vals), 2), "days_in_year": len(vals), "rank_in_year": rank, "reading": reading(rank),
            "monthly": months[0], "months_checked": months,
            "history": [{"date": x.isoformat(), "price": round(d[x], 2)} for x in recent],
            "checks": {"range_ok": True, "spacing_ok": True, "daily_move_ok": True, "monthly_average_ok": True},
            "note": ("A spot price is what natural gas costs for immediate delivery, in US dollars per million BTU (a BTU is a unit of heat); Henry Hub, a pipeline hub in Louisiana, is the US benchmark. "
                     "The figures come from the US Energy Information Administration and reach FRED a few days late, so the price carries its own date. In a cold snap the price can jump several-fold for a day or two. "
                     "Checked: every recent price is between $0.50 and $60, the last 20 prices are no more than 7 days apart, no one-day move is to more than 6 times or less than a sixth of the price before, and the daily prices average out to the monthly figure the EIA publishes for each of the last 3 finished months (within 5 cents). "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class NaturalGas:
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
            return {**base, "available": False, "reason": "Demo mode: the real natural gas prices are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Natural gas prices could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
