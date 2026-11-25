"""US bank balance sheet: what all US commercial banks held and owed on a Wednesday, from the Board of Governors of the Federal Reserve System's H.8 Assets and Liabilities of Commercial Banks release (public-domain US government data), via FRED, the St. Louis Fed: total assets, bank credit (loans and leases plus securities, the securities split into Treasury and agency securities and other securities), cash assets, and on the other side deposits, total liabilities and the residual (assets less liabilities). Free, no key. The partner of the bank loans card: its loans figure is the same series.

How to read it: every figure is the level on a Wednesday (the release comes on the Friday nine days later), weekly, seasonally adjusted, in billions of dollars, for all commercial banks in the United States. The levels are NOT corrected for breaks (a change in the group of banks counted, a reclassification), so a weekly change can include one. It is a description of what already happened, not a forecast.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2015-01-07, the first Wednesday the bank loans card also starts at (619 weeks to 2026-11-11), and no custom User-Agent is sent (FRED stalls on an unfamiliar one).
Checks, set from the whole real record (619 weeks, none missing in any of the 10 series; the 10 series pages say Public Domain: Citation Requested and their notes hold only contact lines and the suggested citation) before any test was written: the 10 series end in the same week, cover the same weeks, are dated a Wednesday and skip no week; every series stays inside a limit fixed from its real lowest and highest value (about half the lowest and about twice the highest, because levels grow); three sums hold to the rounding of the published figures, which are kept to 0.0001 billion dollars, so each tolerance is the arithmetic bound of its figures each rounded to 0.0001 (0.00005 each): bank credit = loans and leases + securities (the real largest gap is 0.0001, exactly 0 in 384 weeks; tolerance 0.00015, three figures), securities = Treasury and agency securities + other securities (0.0001; 0.00015) and total assets = total liabilities + the residual (0.0001; 0.00015: the residual is the Federal Reserve's own difference, so this one shows that the weeks are lined up and is no independent check); and two orders hold: total assets are never below bank credit plus cash assets (the real smallest margin is 1,608 billion) and total liabilities are never below deposits (2,075 billion). The checks run in this order, the oldest week first: the weeks, the ranges, the three sums in the order above, then the two orders.
The sums are the Federal Reserve's own arithmetic: they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: revisions of older weeks, which series is wrong when a check fails (the message says only that they disagree), breaks in the levels, the borrowings and other liabilities that the release also has (their ids were not found), the other groups of banks and the not seasonally adjusted figures.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .failreason import fail_reason
from .fincond import parse
from .jolts import _num
from .usinventories import _change

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "Board of Governors of the Federal Reserve System, H.8 Assets and Liabilities of Commercial Banks, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/TLAACBW027SBOG"
START = "2015-01-07"                                   # the first Wednesday of the bank loans card too: 619 weeks to 2026-11-11
TA, BC, LL, SEC, TAS = "TLAACBW027SBOG", "TOTBKCR", "TOTLL", "SBCACBW027SBOG", "TASACBW027SBOG"
OSE, CASH, DEP, TLB, RES = "OSEACBW027SBOG", "CASACBW027SBOG", "DPSACBW027SBOG", "TLBACBW027SBOG", "RALACBW027SBOG"
NAMES = {TA: "total assets", BC: "bank credit", LL: "loans and leases", SEC: "securities", TAS: "Treasury and agency", OSE: "other securities", CASH: "cash assets",
         DEP: "deposits", TLB: "total liabilities", RES: "the residual"}           # short on purpose: fail_reason shows 110 characters
SERIES = list(NAMES)
LIMITS = {TA: (7590.0, 52400.0), BC: (5290.0, 40300.0), LL: (3810.0, 28600.0), SEC: (1470.0, 11800.0), TAS: (1020.0, 9710.0), OSE: (410.0, 2350.0), CASH: (790.0, 8400.0),
          DEP: (5250.0, 39800.0), TLB: (6760.0, 47400.0), RES: (810.0, 5110.0)}      # billions of dollars; the real ranges are in the log
SUMS = ((BC, (LL, SEC), 0.00015, "loans plus securities"), (SEC, (TAS, OSE), 0.00015, "Treasury plus other securities"), (TA, (TLB, RES), 0.00015, "liabilities plus the residual"))   # a whole, its parts, the tolerance (0.00005 for each figure) and how the message says the parts
ORDERS = ((TA, (BC, CASH), "bank credit plus cash assets"), (TLB, (DEP,), "deposits"))     # a whole that may not be below its listed parts (the rest of it is not published here)
MIN_WEEKS = 572                                        # ten years of year-on-year growth need 520 weeks with a week 52 weeks before each
HISTORY_WEEKS = 520
RECENT_WEEKS = 6
OVERDUE_AFTER_DAYS = 18                                # from the Wednesday: the figures come on the Friday 9 days later and are replaced 7 days after that, so they are 9 to 15 days old; a missed release shows as overdue at 18 (read from the series pages on 2026-11-25, not verified over a longer time)
TTL = 6 * 3600.0
FAIL_TTL = 120.0
CONCURRENCY = 6
WEEK = timedelta(days=7)
YEAR = timedelta(days=364)                             # 52 weeks


def _check_ranges(data: dict[str, dict[date, float]], weeks: list[date]) -> None:
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in weeks:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"{NAMES[sid]} of {_num(v)} on {d.isoformat()} is outside {_num(lo)} to {_num(hi)}")


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    base = data[TA]
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the bank balance sheet series end in different weeks")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {NAMES[sid]} series covers different weeks than total assets")
    weeks = sorted(base)
    if any(d.weekday() != 2 for d in weeks):
        raise ValueError("a bank balance sheet date is not a Wednesday")
    for a, b in zip(weeks, weeks[1:]):
        if b - a != WEEK:
            raise ValueError(f"the bank balance sheet weeks skip a week after {a.isoformat()}")
    if len(weeks) < MIN_WEEKS:
        raise ValueError(f"the bank balance sheet series cover {len(weeks)} weeks, fewer than the {MIN_WEEKS} expected")
    _check_ranges(data, weeks)
    gap_max = 0.0
    for whole, parts, tolerance, what in SUMS:
        for d in weeks:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > tolerance:
                raise ValueError(f"{NAMES[whole]} is {gap:.4f} billion off {what} on {d.isoformat()}, over {tolerance:g}")
            gap_max = max(gap_max, gap)
    for whole, parts, what in ORDERS:
        for d in weeks:
            held = sum(data[p][d] for p in parts)
            if data[whole][d] < held:
                raise ValueError(f"{NAMES[whole]} of {_num(data[whole][d])} are below {what} of {_num(held)} on {d.isoformat()}")
    return weeks, {"weeks_checked": len(weeks), "first_week": weeks[0].isoformat(), "last_week": weeks[-1].isoformat(), "largest_sum_gap": round(gap_max, 5)}


def _diff(now: float, then: float) -> float:
    return round(now - then, 4) + 0.0                  # billions to 0.0001; a fall that rounds to nothing is 0.0, not -0.0


def _range_weeks(values: dict[date, float], now: float, first: date) -> dict:
    """Lowest, highest (the earliest week when several are equal) and the share of weeks strictly lower than `now`, over the weeks in `values` (oldest first)."""
    lo, hi = min(values, key=values.get), max(values, key=values.get)
    return {"weeks": len(values), "first": first.isoformat(), "lowest": {"value": values[lo], "date": lo.isoformat()}, "highest": {"value": values[hi], "date": hi.isoformat()},
            "share_lower_pct": round(100 * sum(1 for v in values.values() if v < now) / len(values))}


def _item(key: str, label: str, now: float, week: float, year: float, base: float) -> dict:
    return {"key": key, "label": label, "billions": now, "share_pct": round(100.0 * now / base, 1),
            "change_week_billions": _diff(now, week), "change_week_pct": _change(now, week), "change_year_billions": _diff(now, year), "change_year_pct": _change(now, year)}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    weeks, detail = _check(data)
    last = weeks[-1]
    window = weeks[-HISTORY_WEEKS:]
    before, ago = last - WEEK, last - YEAR
    ta, tlb = data[TA], data[TLB]

    def rest_assets(d: date) -> float:                 # total assets less what the card lists: other assets, trading assets, lending to other banks
        return round(ta[d] - data[BC][d] - data[CASH][d], 4) + 0.0

    def other_liabilities(d: date) -> float:           # total liabilities less deposits: borrowings and the rest
        return round(tlb[d] - data[DEP][d], 4) + 0.0

    growth = {d: _change(ta[d], ta[d - YEAR]) for d in window}
    total = {"assets_billions": ta[last], "change_week_billions": _diff(ta[last], ta[before]), "change_week_pct": _change(ta[last], ta[before]),
             "change_year_billions": _diff(ta[last], ta[ago]), "change_year_pct": growth[last], "growth_range": _range_weeks(growth, growth[last], window[0])}
    assets = [_item("loans", "Loans and leases", data[LL][last], data[LL][before], data[LL][ago], ta[last]),
              _item("securities", "Securities", data[SEC][last], data[SEC][before], data[SEC][ago], ta[last]),
              _item("cash", "Cash assets", data[CASH][last], data[CASH][before], data[CASH][ago], ta[last]),
              _item("rest", "Everything else", rest_assets(last), rest_assets(before), rest_assets(ago), ta[last])]
    securities = [{"key": "treasury_agency", "label": "Treasury and agency securities", "billions": data[TAS][last], "share_pct": round(100.0 * data[TAS][last] / data[SEC][last], 1)},
                  {"key": "other", "label": "Other securities", "billions": data[OSE][last], "share_pct": round(100.0 * data[OSE][last] / data[SEC][last], 1)}]
    liabilities = {"total_billions": tlb[last], "change_week_billions": _diff(tlb[last], tlb[before]), "change_week_pct": _change(tlb[last], tlb[before]),
                   "change_year_billions": _diff(tlb[last], tlb[ago]), "change_year_pct": _change(tlb[last], tlb[ago]),
                   "items": [_item("deposits", "Deposits", data[DEP][last], data[DEP][before], data[DEP][ago], tlb[last]),
                             _item("other", "Everything else", other_liabilities(last), other_liabilities(before), other_liabilities(ago), tlb[last])]}
    residual = {"billions": data[RES][last], "share_of_assets_pct": round(100.0 * data[RES][last] / ta[last], 1),
                "change_year_billions": _diff(data[RES][last], data[RES][ago]), "change_year_pct": _change(data[RES][last], data[RES][ago])}
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": total, "assets": assets, "securities": securities, "liabilities": liabilities, "residual": residual,
            "recent": [{"date": d.isoformat(), "total_billions": ta[d], "change_billions": _diff(ta[d], ta[d - WEEK])} for d in weeks[-RECENT_WEEKS:]],
            "detail": detail,
            "checks": {"weeks_in_a_row": True, "range_ok": True, "sums_ok": True, "orders_ok": True},
            "note": ("The H.8 release of the Federal Reserve Board for all commercial banks in the United States: the level on a Wednesday, weekly, seasonally adjusted, in billions of dollars, published on the Friday nine days later. "
                     "Bank credit is loans and leases plus securities, and the securities are Treasury and agency securities plus other securities; \"everything else\" on each side is worked out here as what is left after the parts the Fed publishes. "
                     "The residual is the Fed's own difference between assets and liabilities, roughly what the banks own rather than owe: it says nothing about how safe any one bank is. "
                     "The levels are not corrected for changes in the group of banks counted or for reclassifications, and the newest weeks are revised later. "
                     "Plain checks: the units are the ones assumed and no week is missing; the ranges, the sums and the order checks are in the Check line. "
                     "This describes bank balance sheets that already happened: it is not a market signal or a forecast.")}


class UsBankBalance:
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
            return {**base, "available": False, "reason": "Demo mode: the real US bank balance sheet figures are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US bank balance sheet could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
