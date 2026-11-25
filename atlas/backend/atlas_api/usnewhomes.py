"""US new home sales: how many new one-family houses were sold in a month, how many are for sale and what they sold for, from the Census Bureau and the Department of Housing and Urban Development (the New Residential Sales release), via FRED, the St. Louis Fed.

How to read it: sales are THOUSANDS of houses at a seasonally adjusted ANNUAL rate: 676 means sales were running at a pace of 676,000 houses a year, as if that month's pace went on for twelve months. The homes for sale are counted at the end of the month (thousands, seasonally adjusted). The months' supply is the Census Bureau's own ratio of the homes for sale to the sales rate: how many months the homes for sale would last at that pace. Prices are dollars and are NOT seasonally adjusted, so they are compared with a year earlier. These are new houses: sales of existing homes are another measure and are not here. The newest months are revised later.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2015-01-01 and nothing is sent but the id and the date. No key, no custom User-Agent (FRED stalls and drops connections for an unfamiliar one, seen 2026-11-12), the client's own 25 second timeout, six requests at a time.
Checks, set from the whole real record (141 months, January 2015 to September 2026; none missing in any of the 9 series) before any test was written: the 9 series end in the same month, cover the same months, are dated the 1st and skip no month; every series stays inside a range of about half its lowest to about twice its highest real value (the literals below); the four regions add up to the total (sales in thousands, each figure rounded on its own, so the tolerance is the arithmetic bound of 5 figures at 0.5 each, 2.5; the real gap is 0 in all 141 months); the months' supply agrees with 12 times the homes for sale divided by the sales rate to within 0.1 (it is published to a tenth: the real gap is 0.05 at most, in 3 of the 141 months); and the average price is not below the median price (true in all 141 months, by 33,800 to 135,400 dollars). A month-on-month move is NOT limited: the real moves are large (sales fell 20.3% in 2026-01 and rose 27.4% in 2020-06, and a single region more than doubled in 2023-03).
The sum and the ratio are the Census Bureau's own arithmetic: they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: the revisions of older months; which series is wrong when a check fails (the message says only that they disagree); and what the survey does not cover.
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
SOURCE = "U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Sales, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/HSN1F"
START = "2015-01-01"                                   # the first month of the record: 141 months to 2026-09
TOT, NE, MW, SO, WE = "HSN1F", "HSN1FNE", "HSN1FMW", "HSN1FS", "HSN1FW"
INV, SUP, MED, AVG = "HNFSEPUSSA", "MSACSR", "MSPNHSUS", "ASPNHSUS"
NAMES = {TOT: "sales", NE: "Northeast sales", MW: "Midwest sales", SO: "South sales", WE: "West sales",
         INV: "homes for sale", SUP: "months' supply", MED: "median price", AVG: "average price"}        # short on purpose: fail_reason shows 110 characters
SERIES = list(NAMES)
REGIONS = (("northeast", "Northeast", NE), ("midwest", "Midwest", MW), ("south", "South", SO), ("west", "West", WE))
LIMITS = {TOT: (230.0, 2060.0), NE: (6.0, 120.0), MW: (23.0, 245.0), SO: (130.0, 1195.0), WE: (52.0, 590.0),
          INV: (100.0, 1010.0), SUP: (1.6, 20.6), MED: (142000.0, 920000.0), AVG: (163000.0, 1080000.0)}      # thousands of houses (sales at an annual rate, for sale at the month end), months, dollars; the real ranges are in the log
SUM_TOLERANCE = 2.5                                    # the total and its four regions: 5 figures, 0.5 each
SUPPLY_TOLERANCE = 0.1                                 # the months' supply is published to a tenth of a month
MIN_MONTHS = 132                                       # ten years of year-on-year growth need 120 months with a month a year before each
HISTORY_MONTHS = 120
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 95                                # from the 1st of the observed month: the release comes about 56 days after it (2026-10-27 for September) and the next one about 28 days later, plus a week
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
        raise ValueError("the new home sales series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {NAMES[sid]} series covers different months than sales")
    months = sorted(base)
    if any(d.day != 1 for d in months):
        raise ValueError("a new home sales date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the new home sales months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the new home sales series cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    _check_ranges(data, months)
    sum_gap = 0.0
    for d in months:
        gap = abs(data[TOT][d] - sum(data[sid][d] for _, _, sid in REGIONS))
        if gap > SUM_TOLERANCE:
            raise ValueError(f"sales are {_num(gap)} off the sum of the four regions in {_label(d)}, over {SUM_TOLERANCE:g}")
        sum_gap = max(sum_gap, gap)
    supply_gap = 0.0
    for d in months:
        calc = 12.0 * data[INV][d] / data[TOT][d]
        gap = abs(data[SUP][d] - calc)
        if gap > SUPPLY_TOLERANCE:
            raise ValueError(f"the months' supply of {_num(data[SUP][d])} in {_label(d)} is {gap:.2f} off 12 times homes for sale over sales ({calc:.2f}), over {SUPPLY_TOLERANCE:g}")
        supply_gap = max(supply_gap, gap)
    price_gap = min(data[AVG][d] - data[MED][d] for d in months)
    for d in months:
        if data[AVG][d] < data[MED][d]:
            raise ValueError(f"the average price of {_num(data[AVG][d])} is below the median of {_num(data[MED][d])} in {_label(d)}")
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_sum_gap": round(sum_gap, 4),
                    "largest_supply_gap": round(supply_gap, 4), "smallest_price_gap": round(price_gap, 4)}


def _diff(now: float, then: float) -> float:
    return round(now - then, 1) + 0.0                  # to a tenth; a fall that rounds to nothing is 0.0, not -0.0


def _item(key: str, label: str, s: dict[date, float], tot: dict[date, float], last: date, before: date, ago: date) -> dict:
    return {"key": key, "label": label, "thousands": s[last], "share_pct": round(100.0 * s[last] / tot[last], 1),
            "change_month": _diff(s[last], s[before]), "change_month_pct": _change(s[last], s[before]),
            "change_year": _diff(s[last], s[ago]), "change_year_pct": _change(s[last], s[ago])}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    window = months[-HISTORY_MONTHS:]
    ago, before = _months_back(last, 12), _months_back(last, 1)
    tot, inv, sup, med, avg = data[TOT], data[INV], data[SUP], data[MED], data[AVG]
    growth = {d: _change(tot[d], tot[_months_back(d, 12)]) for d in window}
    sales = {"thousands": tot[last], "change_month": _diff(tot[last], tot[before]), "change_month_pct": _change(tot[last], tot[before]),
             "change_year": _diff(tot[last], tot[ago]), "change_year_pct": growth[last], "growth_range": _range(growth, growth[last], window[0])}
    stock = {"for_sale": inv[last], "for_sale_change_month": _diff(inv[last], inv[before]), "for_sale_change_year": _diff(inv[last], inv[ago]),
             "months_supply": sup[last], "supply_change_month": _diff(sup[last], sup[before]), "supply_change_year": _diff(sup[last], sup[ago]),
             "supply_range": _range({d: sup[d] for d in window}, sup[last], window[0])}
    prices = {"median": med[last], "median_change_year": _diff(med[last], med[ago]), "median_change_year_pct": _change(med[last], med[ago]),
              "average": avg[last], "average_change_year": _diff(avg[last], avg[ago]), "average_change_year_pct": _change(avg[last], avg[ago]),
              "median_range": _range({d: med[d] for d in window}, med[last], window[0])}
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "sales": sales, "regions": [_item(key, label, data[sid], tot, last, before, ago) for key, label, sid in REGIONS], "stock": stock, "prices": prices,
            "recent": [{"month": _label(d), "thousands": tot[d], "change": _diff(tot[d], tot[_months_back(d, 1)]), "months_supply": sup[d]} for d in months[-RECENT_MONTHS:]],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "sum_ok": True, "supply_ok": True, "prices_ok": True},
            "note": ("New home sales from the Census Bureau and the Department of Housing and Urban Development (the New Residential Sales release): sales of new one-family houses in thousands at a seasonally adjusted annual rate, "
                     "so 676 means sales were running at a pace of 676,000 houses a year. The homes for sale are counted at the end of the month, and the months' supply is the Census Bureau's own ratio of the homes for sale to the sales rate. "
                     "Prices are not seasonally adjusted, so they are compared with a year earlier. These are new houses: sales of existing homes are another measure and are not here. The newest months are revised later. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sum of the four regions, the months' supply and the order of the two prices are in the Check line. "
                     "This describes sales that already happened: it is not a market signal or a forecast.")}


class UsNewHomes:
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
            return {**base, "available": False, "reason": "Demo mode: the real US new home sales figures are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US new home sales could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
