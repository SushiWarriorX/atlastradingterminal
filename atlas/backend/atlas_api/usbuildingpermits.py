"""US building permits: how many new homes local governments in the United States gave permission to build in a month, from the Census Bureau and the Department of Housing and Urban Development (New Residential Construction, the Building Permits Survey), via FRED, the St. Louis Fed.

How to read it: the figures are thousands of homes at a seasonally adjusted ANNUAL rate: 1,295 means permission was given at a pace of 1.295 million homes a year, as if that month's pace went on for twelve months. A permit is permission to build, not a home started or finished (the housing starts card shows the starts, which follow permits). The total is split two ways and each split is an exact sum: by type (single-family homes, homes in buildings of 2 to 4 units, homes in buildings of 5 or more units) and by Census region (Northeast, Midwest, South, West). The universe is about 20,000 permit-issuing places, and the newest months are revised later.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2015-01-01 and nothing is sent but the id and the date. No key, no custom User-Agent (FRED stalls and drops connections for an unfamiliar one, seen 2026-11-12), the client's own 25 second timeout, six requests at a time.
Checks, set from the whole real record (142 months, January 2015 to October 2026; none missing in any of the 8 series) before any test was written: the 8 series end in the same month, cover the same months, are dated the 1st and skip no month; every series stays inside a range of about half its lowest to about twice its highest real value (the literals below); and two sums hold: total permits equal single-family plus 2-4 unit plus 5+ unit permits, and equal the four regions added up. Both held EXACTLY in all 142 months (the Census publishes whole thousands that add up); the tolerance is still the arithmetic bound of the rounding of the figures (0.5 each: 2.0 for the types, 2.5 for the regions), not the measured gap of 0, so that a revision that moves one figure by a rounding step does not hide the card. A month-on-month move is NOT limited: the real moves are large (the Northeast changed by 76% in a month, the total by 272 thousand in 2020-04).
The sums are the Census Bureau's own arithmetic: they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: the revisions of older months; which series is wrong when a check fails (the message says only that they disagree); the permit-issuing places the survey does not cover; and whether a permit leads to a start.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone

import httpx

from .failreason import fail_reason
from .fincond import parse
from .jolts import _num, _range
from .moneysupply import _label, _months_back
from .usinventories import _change

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Construction (building permits), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/PERMIT"
START = "2015-01-01"                                   # the first month of the record: 142 months to 2026-10
TOT, ONE, TWO, FIVE = "PERMIT", "PERMIT1", "PERMIT24", "PERMIT5"
NE, MW, SO, WE = "PERMITNE", "PERMITMW", "PERMITS", "PERMITW"
NAMES = {TOT: "total permits", ONE: "single-family permits", TWO: "2-4 unit permits", FIVE: "5+ unit permits",
         NE: "Northeast permits", MW: "Midwest permits", SO: "South permits", WE: "West permits"}           # short on purpose: fail_reason shows 110 characters
SERIES = list(NAMES)
TYPES = (("single_family", "Single-family homes", ONE), ("two_to_four", "Homes in buildings of 2 to 4 units", TWO), ("five_or_more", "Homes in buildings of 5 or more units", FIVE))
REGIONS = (("northeast", "Northeast", NE), ("midwest", "Midwest", MW), ("south", "South", SO), ("west", "West", WE))
LIMITS = {TOT: (520.0, 3850.0), ONE: (310.0, 2500.0), TWO: (12.0, 135.0), FIVE: (170.0, 1525.0),
          NE: (30.0, 575.0), MW: (70.0, 545.0), SO: (260.0, 2070.0), WE: (125.0, 960.0)}                   # thousands of homes at an annual rate; the real ranges are in the log
SUMS = ((TOT, (ONE, TWO, FIVE), 2.0, "single-family plus 2-4 unit plus 5+ unit permits"),                    # the tolerance is 0.5 per figure, the whole and its parts
        (TOT, (NE, MW, SO, WE), 2.5, "the four regions together"))
MIN_MONTHS = 132                                       # ten years of year-on-year growth need 120 months with a month a year before each
HISTORY_MONTHS = 120
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 90                                # from the 1st of the observed month, as for housing starts (the same release): the next month normally arrives about 76 to 80 days after it
TTL = 6 * 3600.0
FAIL_TTL = 120.0
CONCURRENCY = 6


def _check_ranges(data: dict[str, dict[date, float]], months: list[date]) -> None:
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in months:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"{NAMES[sid]} of {_num(v)} in {_label(d)} is outside {_num(lo)} to {_num(hi)}")


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    base = data[TOT]
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the building permit series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {NAMES[sid]} series covers different months than total permits")
    months = sorted(base)
    if any(d.day != 1 for d in months):
        raise ValueError("a building permit date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the building permit months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the building permit series cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    _check_ranges(data, months)
    gap_max = 0.0
    for whole, parts, tolerance, what in SUMS:
        for d in months:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > tolerance:
                raise ValueError(f"{NAMES[whole]} is {_num(gap)} thousand off {what} in {_label(d)}, over {tolerance:g}")
            gap_max = max(gap_max, gap)
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_sum_gap": round(gap_max, 4)}


def _diff(now: float, then: float) -> float:
    return round(now - then, 1) + 0.0                  # thousands to a tenth; a fall that rounds to nothing is 0.0, not -0.0


def _item(key: str, label: str, s: dict[date, float], tot: dict[date, float], last: date, before: date, ago: date) -> dict:
    return {"key": key, "label": label, "thousands": s[last], "share_pct": round(100.0 * s[last] / tot[last], 1),
            "change_month_thousands": _diff(s[last], s[before]), "change_month_pct": _change(s[last], s[before]),
            "change_year_thousands": _diff(s[last], s[ago]), "change_year_pct": _change(s[last], s[ago])}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    window = months[-HISTORY_MONTHS:]
    ago, before = _months_back(last, 12), _months_back(last, 1)
    tot = data[TOT]
    growth = {d: _change(tot[d], tot[_months_back(d, 12)]) for d in window}
    total = {"thousands": tot[last], "change_month_thousands": _diff(tot[last], tot[before]), "change_month_pct": _change(tot[last], tot[before]),
             "change_year_thousands": _diff(tot[last], tot[ago]), "change_year_pct": growth[last], "growth_range": _range(growth, growth[last], window[0])}
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": total,
            "types": [_item(key, label, data[sid], tot, last, before, ago) for key, label, sid in TYPES],
            "regions": [_item(key, label, data[sid], tot, last, before, ago) for key, label, sid in REGIONS],
            "recent": [{"month": _label(d), "thousands": tot[d], "change_thousands": _diff(tot[d], tot[_months_back(d, 1)])} for d in months[-RECENT_MONTHS:]],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "sums_ok": True},
            "note": ("Building permits from the Census Bureau and the Department of Housing and Urban Development (the New Residential Construction release), seasonally adjusted, as an annual rate in thousands of homes: "
                     "1,295 means permission was given at a pace of 1.295 million homes a year. A permit is permission to build, not a home built: some permitted homes are never started, and permits usually come before starts. "
                     "The survey covers about 20,000 permit-issuing places, the newest months are revised later, and the regions are the Census regions (Northeast, Midwest, South, West). "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges and the two sums are in the Check line. "
                     "This describes permission to build that already happened: it is not a market signal or a forecast.")}


class UsBuildingPermits:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, gate: asyncio.Semaphore, sid: str) -> dict[date, float]:
        # One series per request: with several ids a single cosd applies to the first series only. No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast.
        async with gate:
            r = await c.get(URL, params={"id": sid, "cosd": START})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real US building permit figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            gate = asyncio.Semaphore(CONCURRENCY)
            got = await asyncio.gather(*[self._fetch(c, gate, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US building permits could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
