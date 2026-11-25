"""US factory orders: what US manufacturers were ordered, shipped, held in stock and still owed in a month, from the Census Bureau (the M3 survey: Manufacturers' Shipments, Inventories, and Orders), via FRED, the St. Louis Fed.

How to read it: millions of dollars, seasonally adjusted. New orders are what customers ordered in the month, shipments what was delivered, inventories what manufacturers held at the END of the month and unfilled orders what was ordered but not yet delivered (the backlog) at the end of the month. The totals and the nondurable goods come from the FULL report of a month; the durable goods series (and the two headline cuts of them: orders excluding transportation and nondefense capital goods excluding aircraft, called here core capital goods) are updated a week or so earlier by the ADVANCE durable goods report, so they can carry one more month than the others (on 2026-11-25 the durable series ended in 2026-10 and the others in 2026-09: their update times on FRED were 2026-11-25 and 2026-11-03). Nondurable goods orders are by definition the same as their shipments, and unfilled orders are counted for durable goods only, so the total is the durable figure (both are in the series notes). The newest months are revised later.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2015-01-01 and nothing is sent but the id and the date. No key, no custom User-Agent (FRED stalls and drops connections for an unfamiliar one, seen 2026-11-12), the client's own 25 second timeout, six requests at a time.
Checks, set from the whole real record (141 months of the full report and 142 of the durable series, January 2015 to September and October 2026; none missing in any of the 13 series) before any test was written: the 7 series of the full report end in the same month and cover the same months; the 6 durable series end in the same month, that month is the full report's or the one after it, and they cover the same months as the full report (plus that one); every date is the 1st and no month is skipped; every series stays inside a range of about half its lowest to about twice its highest real value (the literals below); three sums hold (total orders, total shipments and total inventories each equal their durable plus their nondurable figure: whole millions, each rounded on its own, so the tolerance is the arithmetic bound of three figures at 0.5, 1.5; the real gap is 0 in every month but the newest common one); two published equalities hold (nondurable orders equal nondurable shipments, and total unfilled orders equal the durable ones, tolerance 1.0; the real gap is 0); and the durable orders excluding transportation and the core capital goods orders never exceed durable orders (true in all 142 months). The sums and the unfilled orders equality are NOT tested in the newest month the two groups share, because there the durable figures come from the later advance report and the totals from the earlier full one: on 2026-09 they differ by 270, 83, 516 and 326 million (0.04%, 0.01%, 0.05% and 0.02% of the totals), which is a difference of vintage and not an error; the card shows those gaps instead. A month-on-month move is NOT limited: the real moves are large (durable goods orders fell 19.3% in 2020-04 and rose 16.5% in 2025-05).
The sums and equalities are the Census Bureau's own arithmetic: they show that the series belong to one survey and are lined up, not that the figures are right. NOT checked, and said so: the revisions of older months; which series is wrong when a check fails (the message says only that they disagree); the newest common month's sums; and what the survey does not cover (data for the semiconductor industry are not available).
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone

import httpx

from .failreason import fail_reason
from .fincond import parse
from .jolts import _num
from .moneysupply import _label, _months_back
from .usinventories import _change

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Census Bureau, Manufacturers' Shipments, Inventories, and Orders (M3 survey), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/AMTMNO"
START = "2015-01-01"                                   # the first month of the record: 141 months of the full report to 2026-09
ORD_T, ORD_N, SHP_T, SHP_N, INV_T, INV_N, UNF_T = "AMTMNO", "AMNMNO", "AMTMVS", "AMNMVS", "AMTMTI", "AMNMTI", "AMTMUO"
ORD_D, SHP_D, INV_D, UNF_D, CORE, EXTR = "DGORDER", "AMDMVS", "AMDMTI", "AMDMUO", "NEWORDER", "ADXTNO"
NAMES = {ORD_T: "new orders", ORD_N: "nondurable orders", SHP_T: "shipments", SHP_N: "nondurable shipments", INV_T: "inventories", INV_N: "nondurable inventories", UNF_T: "unfilled orders",
         ORD_D: "durable orders", SHP_D: "durable shipments", INV_D: "durable inventories", UNF_D: "durable unfilled orders", CORE: "core capital orders", EXTR: "orders excluding transport"}   # short on purpose: fail_reason shows 110 characters
FULL = (ORD_T, ORD_N, SHP_T, SHP_N, INV_T, INV_N, UNF_T)          # the series of the full report
DURABLE = (ORD_D, SHP_D, INV_D, UNF_D, CORE, EXTR)                # the series of the advance durable goods report
SERIES = list(FULL) + list(DURABLE)
LIMITS = {ORD_T: (180000.0, 1355000.0), ORD_N: (98000.0, 665000.0), SHP_T: (187000.0, 1340000.0), SHP_N: (98000.0, 665000.0), INV_T: (315000.0, 1955000.0), INV_N: (121000.0, 735000.0),
          UNF_T: (530000.0, 3250000.0), ORD_D: (82000.0, 695000.0), SHP_D: (89000.0, 680000.0), INV_D: (190000.0, 1230000.0), UNF_D: (530000.0, 3280000.0), CORE: (28000.0, 179000.0), EXTR: (67000.0, 455000.0)}      # millions of dollars; the real ranges are in the log
SUMS = ((ORD_T, (ORD_D, ORD_N), 1.5, "durable plus nondurable orders"),                                      # the tolerance is 0.5 per figure: the whole and its two parts
        (SHP_T, (SHP_D, SHP_N), 1.5, "durable plus nondurable shipments"),
        (INV_T, (INV_D, INV_N), 1.5, "durable plus nondurable inventories"))
EQUALS = ((ORD_N, SHP_N, 1.0, "nondurable shipments", False),                                              # published as identical (series notes); the tolerance is 0.5 per figure; the last flag: skip the newest common month
          (UNF_T, UNF_D, 1.0, "durable unfilled orders", True))
PARTS = ((EXTR, ORD_D), (CORE, ORD_D))                            # a part of durable orders may not exceed durable orders
MIN_MONTHS = 132                                       # ten years of year-on-year growth need 120 months with a month a year before each
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 100                               # from the 1st of the observed month: the full report comes about 63 days after it (2026-11-03 for September) and the next about 30 days later, plus a week
TTL = 6 * 3600.0
FAIL_TTL = 120.0
CONCURRENCY = 6


def _check_ranges(data: dict[str, dict[date, float]], months: dict[str, list[date]]) -> None:
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in months[sid]:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"{NAMES[sid]} of {_num(v)} in {_label(d)} is outside {_num(lo)} to {_num(hi)}")


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], list[date], dict]:
    if len({max(data[sid]) for sid in FULL}) != 1:
        raise ValueError("the full report series end in different months")
    if len({max(data[sid]) for sid in DURABLE}) != 1:
        raise ValueError("the durable goods series end in different months")
    if any(d.day != 1 for sid in SERIES for d in data[sid]):          # before the month arithmetic below: "the month after" means nothing for a date that is not the 1st
        raise ValueError("a factory orders date is not the 1st of a month")
    full_end, dur_end = max(data[ORD_T]), max(data[ORD_D])
    if dur_end != full_end and dur_end != _months_back(full_end, -1):
        raise ValueError("the durable goods series end in a month that is neither the full report's nor the one after it")
    for sid in FULL[1:]:
        if set(data[sid]) != set(data[ORD_T]):
            raise ValueError(f"the {NAMES[sid]} series covers different months than new orders")
    for sid in DURABLE[1:]:
        if set(data[sid]) != set(data[ORD_D]):
            raise ValueError(f"the {NAMES[sid]} series covers different months than durable orders")
    if set(data[ORD_D]) != set(data[ORD_T]) | {dur_end}:
        raise ValueError("the durable goods series cover other months than the full report")
    months = sorted(data[ORD_T])
    dmonths = sorted(data[ORD_D])
    for a, b in zip(dmonths, dmonths[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the factory orders months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the factory orders series cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    _check_ranges(data, {sid: (months if sid in FULL else dmonths) for sid in SERIES})
    tested = months[:-1]                                # the newest common month mixes two reports: see the module text
    sum_gap = 0.0
    for whole, parts, tolerance, what in SUMS:
        for d in tested:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > tolerance:
                raise ValueError(f"{NAMES[whole]} are {_num(gap)} million off {what} in {_label(d)}, over {tolerance:g}")
            sum_gap = max(sum_gap, gap)
    equal_gap = 0.0
    for a, b, tolerance, what, skip_newest in EQUALS:
        for d in (tested if skip_newest else months):
            gap = abs(data[a][d] - data[b][d])
            if gap > tolerance:
                raise ValueError(f"{NAMES[a]} are {_num(gap)} million off {what} in {_label(d)}, over {tolerance:g}")
            equal_gap = max(equal_gap, gap)
    for part, whole in PARTS:
        for d in dmonths:
            if data[part][d] > data[whole][d]:
                raise ValueError(f"{NAMES[part]} of {_num(data[part][d])} is above {NAMES[whole]} of {_num(data[whole][d])} in {_label(d)}")
    last = months[-1]
    newest = {"month": _label(last), "orders": _gap(data[ORD_T][last], data[ORD_D][last], data[ORD_N][last]), "shipments": _gap(data[SHP_T][last], data[SHP_D][last], data[SHP_N][last]),
              "inventories": _gap(data[INV_T][last], data[INV_D][last], data[INV_N][last]), "unfilled": _diff(data[UNF_T][last], data[UNF_D][last])}
    return months, dmonths, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(last), "durable_last_month": _label(dmonths[-1]),
                             "largest_sum_gap": round(sum_gap, 4), "largest_equal_gap": round(equal_gap, 4), "newest_common": newest}


def _gap(total: float, durable: float, nondurable: float) -> float:
    return round(total - durable - nondurable, 1) + 0.0     # the total less its two parts, to a tenth


def _diff(now: float, then: float) -> float:
    return round(now - then, 1) + 0.0                  # millions to a tenth; a fall that rounds to nothing is 0.0, not -0.0


def _item(key: str, label: str, s: dict[date, float], last: date, before: date, ago: date, total: dict[date, float] | None = None) -> dict:
    item = {"key": key, "label": label, "millions": s[last], "change_month_millions": _diff(s[last], s[before]), "change_month_pct": _change(s[last], s[before]),
            "change_year_millions": _diff(s[last], s[ago]), "change_year_pct": _change(s[last], s[ago])}
    if total is not None:
        item["share_pct"] = round(100.0 * s[last] / total[last], 1)
    return item


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, dmonths, detail = _check(data)
    last, dlast = months[-1], dmonths[-1]
    ago, before = _months_back(last, 12), _months_back(last, 1)
    dago, dbefore = _months_back(dlast, 12), _months_back(dlast, 1)
    age = (today - last).days
    orders, ships = data[ORD_T], data[SHP_T]
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "durable_month": _label(dlast), "durable_advance": dlast > last,
            "full": [_item(key, label, data[sid], last, before, ago) for key, label, sid in (("orders", "New orders", ORD_T), ("shipments", "Shipments", SHP_T), ("inventories", "Inventories", INV_T), ("unfilled", "Unfilled orders", UNF_T))],
            "nondurable": [_item("orders", "Nondurable goods orders and shipments", data[ORD_N], last, before, ago, orders), _item("inventories", "Nondurable goods inventories", data[INV_N], last, before, ago, data[INV_T])],
            "durable": [_item(key, label, data[sid], dlast, dbefore, dago) for key, label, sid in (("orders", "Durable goods orders", ORD_D), ("ex_transport", "Orders excluding transportation", EXTR), ("core_capital", "Core capital goods orders", CORE),
                                                                                                     ("shipments", "Durable goods shipments", SHP_D), ("inventories", "Durable goods inventories", INV_D), ("unfilled", "Durable goods unfilled orders", UNF_D))],
            "recent": [{"month": _label(d), "orders": orders[d], "orders_change": _diff(orders[d], orders[_months_back(d, 1)]), "shipments": ships[d]} for d in months[-RECENT_MONTHS:]],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "sums_ok": True, "equal_ok": True, "parts_ok": True},
            "note": ("Factory orders from the Census Bureau (the M3 survey of manufacturers' shipments, inventories and orders), in millions of dollars, seasonally adjusted: what customers ordered in the month, what was shipped, what manufacturers held at the month end and what was still owed. "
                     "The totals and the nondurable goods come from the full report of a month; the durable goods figures come from the advance report that comes out about a week before it, so they can run one month ahead of the rest. "
                     "Nondurable goods orders are by definition the same as their shipments, and unfilled orders are counted for durable goods only. The newest months are revised later. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums, the published equalities and the order of the durable parts are in the Check line. "
                     "This describes factory activity that already happened: it is not a market signal or a forecast.")}


class UsFactoryOrders:
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
            return {**base, "available": False, "reason": "Demo mode: the real US factory orders figures are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US factory orders could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
