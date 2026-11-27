"""US construction spending: how much construction work was done in the United States in a month, from the Census Bureau (the Construction Spending release, the value of construction put in place), via FRED, the St. Louis Fed.

How to read it: the figures are millions of dollars at a seasonally adjusted ANNUAL rate: 2,186,145 means work was being done at a pace of about $2.19 trillion a year, as if that month's pace went on for twelve months. It is the value of construction work done in the month (an estimate from Census Bureau surveys), not new orders and not buildings finished. The total is split two ways and the splits cross: by who pays (private owners, or federal, state and local governments) and by use (residential or nonresidential), which gives four parts. The newest months are revised later.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2015-01-01 and nothing is sent but the id and the date. No key, no custom User-Agent (FRED stalls and drops connections for an unfamiliar one, seen 2026-11-12), the client's own 25 second timeout, six requests at a time.
Checks, set from the whole real record (141 months, January 2015 to September 2026; none missing in any of the 9 series) before any test was written: the 9 series end in the same month, cover the same months, are dated the 1st and skip no month; every series stays inside a range of about half its lowest to about twice its highest real value (the literals below); and six sums hold: total equals private plus public and equals residential plus nonresidential, private equals private residential plus private nonresidential, public equals public residential plus public nonresidential, residential equals private plus public residential, and nonresidential equals private plus public nonresidential. The Census publishes whole millions, each rounded on its own, so a sum can be one million off: the gaps in the real record are -1, 0 and 1 (29 to 44 of the 141 months per sum, never more than 1). The tolerance of each sum is the arithmetic bound of the rounding of its three figures (0.5 each: 1.5), not the measured gap of 1, so that a revision that moves one figure by a rounding step does not hide the card and a gap of 2 is refused. A month-on-month move is NOT limited: the real moves are large (public residential spending changed by 22% in a month, the total by 43 billion dollars in 2026-08).
The sums are the Census Bureau's own arithmetic: they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: the revisions of older months; which series is wrong when a check fails (the message says only that they disagree); and what the survey does not cover.
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
SOURCE = "U.S. Census Bureau, Construction Spending (value of construction put in place), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/TTLCONS"
START = "2015-01-01"                                   # the first month of the record: 141 months to 2026-09
TOT, PRV, PUB = "TTLCONS", "TLPRVCONS", "TLPBLCONS"
RES, NRS = "TLRESCONS", "TLNRESCONS"
PRR, PRN, PBR, PBN = "PRRESCONS", "PNRESCONS", "PBRESCONS", "PBNRESCONS"
NAMES = {TOT: "total spending", PRV: "private spending", PUB: "public spending", RES: "residential spending", NRS: "nonresidential spending",
         PRR: "private residential spending", PRN: "private nonresidential spending", PBR: "public residential spending", PBN: "public nonresidential spending"}   # short on purpose: fail_reason shows 110 characters
SERIES = list(NAMES)
OWNERS = (("private", "Private", PRV), ("public", "Public", PUB))
USES = (("residential", "Residential", RES), ("nonresidential", "Nonresidential", NRS))
PARTS = (("private_residential", "Private residential", PRR), ("private_nonresidential", "Private nonresidential", PRN),
         ("public_residential", "Public residential", PBR), ("public_nonresidential", "Public nonresidential", PBN))
LIMITS = {TOT: (530000.0, 4550000.0), PRV: (390000.0, 3500000.0), PUB: (140000.0, 1100000.0), RES: (205000.0, 1975000.0), NRS: (325000.0, 2700000.0),
          PRR: (200000.0, 1960000.0), PRN: (185000.0, 1625000.0), PBR: (2800.0, 26500.0), PBN: (135000.0, 1075000.0)}      # millions of dollars at an annual rate; the real ranges are in the log
SUMS = ((TOT, (PRV, PUB), 1.5, "private plus public spending"),                                                           # the tolerance is 0.5 per figure: the whole and its two parts
        (TOT, (RES, NRS), 1.5, "residential plus nonresidential spending"),
        (PRV, (PRR, PRN), 1.5, "private residential plus nonresidential"),
        (PUB, (PBR, PBN), 1.5, "public residential plus nonresidential"),
        (RES, (PRR, PBR), 1.5, "private plus public residential"),
        (NRS, (PRN, PBN), 1.5, "private plus public nonresidential"))
MIN_MONTHS = 132                                       # ten years of year-on-year growth need 120 months with a month a year before each
HISTORY_MONTHS = 120
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 100                               # from the 1st of the observed month: the release comes on the first working day of the second month after it (62 days for September 2026), and the next month about 91 days after it
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
        raise ValueError("the construction spending series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {NAMES[sid]} series covers different months than total spending")
    months = sorted(base)
    if any(d.day != 1 for d in months):
        raise ValueError("a construction spending date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the construction spending months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the construction spending series cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    _check_ranges(data, months)
    gap_max = 0.0
    for whole, parts, tolerance, what in SUMS:
        for d in months:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > tolerance:
                raise ValueError(f"{NAMES[whole]} is {_num(gap)} million off {what} in {_label(d)}, over {tolerance:g}")
            gap_max = max(gap_max, gap)
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_sum_gap": round(gap_max, 4)}


def _diff(now: float, then: float) -> float:
    return round(now - then, 1) + 0.0                  # millions to a tenth; a fall that rounds to nothing is 0.0, not -0.0


def _item(key: str, label: str, s: dict[date, float], tot: dict[date, float], last: date, before: date, ago: date) -> dict:
    return {"key": key, "label": label, "millions": s[last], "share_pct": round(100.0 * s[last] / tot[last], 1),
            "change_month_millions": _diff(s[last], s[before]), "change_month_pct": _change(s[last], s[before]),
            "change_year_millions": _diff(s[last], s[ago]), "change_year_pct": _change(s[last], s[ago])}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    window = months[-HISTORY_MONTHS:]
    ago, before = _months_back(last, 12), _months_back(last, 1)
    tot = data[TOT]
    growth = {d: _change(tot[d], tot[_months_back(d, 12)]) for d in window}
    total = {"millions": tot[last], "change_month_millions": _diff(tot[last], tot[before]), "change_month_pct": _change(tot[last], tot[before]),
             "change_year_millions": _diff(tot[last], tot[ago]), "change_year_pct": growth[last], "growth_range": _range(growth, growth[last], window[0])}
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": total,
            "owners": [_item(key, label, data[sid], tot, last, before, ago) for key, label, sid in OWNERS],
            "uses": [_item(key, label, data[sid], tot, last, before, ago) for key, label, sid in USES],
            "parts": [_item(key, label, data[sid], tot, last, before, ago) for key, label, sid in PARTS],
            "recent": [{"month": _label(d), "millions": tot[d], "change_millions": _diff(tot[d], tot[_months_back(d, 1)])} for d in months[-RECENT_MONTHS:]],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "sums_ok": True},
            "note": ("Construction spending from the Census Bureau (the Construction Spending release, the value of construction put in place), seasonally adjusted, as an annual rate in millions of dollars: "
                     "2,186,145 means work was being done at a pace of about $2.19 trillion a year. It is the value of construction work done in the month, an estimate from Census Bureau surveys, not new orders and not buildings finished. "
                     "Private spending is by owners other than governments, and public spending is by federal, state and local governments; the newest months are revised later. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges and the six sums are in the Check line. "
                     "This describes construction work that already happened: it is not a market signal or a forecast.")}


class UsConstruction:
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
            return {**base, "available": False, "reason": "Demo mode: the real US construction spending figures are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US construction spending could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
