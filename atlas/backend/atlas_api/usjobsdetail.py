"""US jobs in detail: how many jobs sit inside seven of the larger industries, from the Bureau of Labor Statistics (the Current Employment Statistics survey of employers, the payroll half of the monthly Employment Situation), via FRED, the St. Louis Fed.

How to read it: thousands of jobs, seasonally adjusted, for the pay period that includes the 12th of the month. A job is a position on a payroll, not a person (someone with two jobs counts twice), only non-farm employers are counted, and government counts civilian employees only. The newest months are revised twice and again every year. All 26 series come from one release and end in the same month (2026-10 on 2026-11-25). The seven parents are the series of the jobs by industry card; the 19 parts are the next level down.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2015-01-01 and nothing is sent but the id and the date. No key, no custom User-Agent (FRED stalls and drops connections for an unfamiliar one, seen 2026-11-12), the client's own 25 second timeout, six requests at a time.
Checks, set from the whole real record before any test was written (the shortest history is 1972 for trade, transportation and utilities, 1990 for the other five private industries and 1955 for government; none missing in any of the 26 series): the 26 series end in the same month and cover the same months, every date is the 1st and no month is skipped; every series stays inside a range of about half its lowest to about twice its highest value of the WHOLE record (the literals below); and seven sums hold, each parent against its parts. The six private parents are whole thousands and their parts have one decimal: the real gap is at most 0.5 in every month (the parent's own rounding; 658 to 442 months each), so the tolerance is 0.75, which is above the arithmetic bound (0.5 for the parent and 0.05 for each part: 0.7 at most) and exact in binary; government and its three parts are all whole thousands and add up exactly (862 months), so its tolerance is the bound of four rounded figures, 2.0. A month-on-month move is NOT limited.
The sums are the Bureau's own arithmetic: they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: the revisions of older months; which series is wrong when a check fails (the message says only that they disagree); who is counted (farm work, the self-employed and military personnel are not); and the industries and detail that are not shown.
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
SOURCE = "U.S. Bureau of Labor Statistics, Current Employment Statistics (the Employment Situation payrolls in detail), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/USTRADE"
START = "2015-01-01"                                   # the first month of the card: 142 months to 2026-10
GROUPS = (("trade", "Trade, transportation and utilities", "USTPU", 0.75,
           (("wholesale", "Wholesale trade", "USWTRADE"), ("retail", "Retail trade", "USTRADE"), ("transport", "Transportation and warehousing", "CES4300000001"), ("utilities", "Utilities", "CES4422000001"))),
          ("construction", "Construction", "USCONS", 0.75,
           (("buildings", "Construction of buildings", "CES2023600001"), ("heavy", "Heavy and civil engineering construction", "CES2023700001"), ("specialty", "Specialty trade contractors", "CES2023800001"))),
          ("financial", "Financial activities", "USFIRE", 0.75,
           (("finance", "Finance and insurance", "CES5552000001"), ("realestate", "Real estate and rental and leasing", "CES5553000001"))),
          ("professional", "Professional and business services", "USPBS", 0.75,
           (("technical", "Professional, scientific and technical services", "CES6054000001"), ("management", "Management of companies and enterprises", "CES6055000001"),
            ("administrative", "Administrative, support and waste services", "CES6056000001"))),
          ("education_health", "Education and health services", "USEHS", 0.75,
           (("education", "Private educational services", "CES6561000001"), ("health", "Health care and social assistance", "CES6562000001"))),
          ("leisure", "Leisure and hospitality", "USLAH", 0.75,
           (("arts", "Arts, entertainment and recreation", "CES7071000001"), ("food", "Accommodation and food services", "CES7072000001"))),
          ("government", "Government", "USGOVT", 2.0,
           (("federal", "Federal government", "CES9091000001"), ("state", "State government", "CES9092000001"), ("local", "Local government", "CES9093000001"))))
SERIES = tuple(sid for g in GROUPS for sid in (g[2], *[c[2] for c in g[4]]))          # each parent, then its parts: 26 in all
NAMES = {"USTPU": "trade, transport and utilities payrolls", "USWTRADE": "wholesale trade payrolls", "USTRADE": "retail trade payrolls", "CES4300000001": "transportation and warehousing payrolls",
         "CES4422000001": "utilities payrolls", "USCONS": "construction payrolls", "CES2023600001": "construction of buildings payrolls", "CES2023700001": "heavy and civil engineering payrolls",
         "CES2023800001": "specialty trade contractors payrolls", "USFIRE": "financial activities payrolls", "CES5552000001": "finance and insurance payrolls", "CES5553000001": "real estate and leasing payrolls",
         "USPBS": "professional and business payrolls", "CES6054000001": "professional and technical payrolls", "CES6055000001": "management of companies payrolls", "CES6056000001": "administrative and waste payrolls",
         "USEHS": "education and health payrolls", "CES6561000001": "private education payrolls", "CES6562000001": "health care and social assistance payrolls", "USLAH": "leisure and hospitality payrolls",
         "CES7071000001": "arts and recreation payrolls", "CES7072000001": "accommodation and food payrolls", "USGOVT": "government payrolls", "CES9091000001": "federal government payrolls",
         "CES9092000001": "state government payrolls", "CES9093000001": "local government payrolls"}          # short on purpose: fail_reason shows 110 characters
LIMITS = {"USTPU": (3300.0, 57800.0), "USWTRADE": (730.0, 12300.0), "USTRADE": (1550.0, 31800.0), "CES4300000001": (1300.0, 13400.0), "CES4422000001": (235.0, 1490.0),
          "USCONS": (520.0, 16800.0), "CES2023600001": (590.0, 3750.0), "CES2023700001": (360.0, 2430.0), "CES2023800001": (885.0, 10600.0),
          "USFIRE": (680.0, 18500.0), "CES5552000001": (2450.0, 13500.0), "CES5553000001": (805.0, 4950.0),
          "USPBS": (970.0, 45800.0), "CES6054000001": (2250.0, 21800.0), "CES6055000001": (815.0, 5270.0), "CES6056000001": (2265.0, 19200.0),
          "USEHS": (690.0, 56200.0), "CES6561000001": (830.0, 8130.0), "CES6562000001": (4550.0, 48100.0),
          "USLAH": (930.0, 34100.0), "CES7071000001": (555.0, 5410.0), "CES7072000001": (3750.0, 28800.0),
          "USGOVT": (2000.0, 48000.0), "CES9091000001": (455.0, 6880.0), "CES9092000001": (575.0, 11100.0), "CES9093000001": (1745.0, 30400.0)}      # thousands of jobs; about half the lowest and twice the highest of the whole record
SUMS = tuple((g[2], tuple(c[2] for c in g[4]), g[3]) for g in GROUPS)                  # the parent, its parts and the tolerance
WORDS = {2: "two", 3: "three", 4: "four"}
MIN_MONTHS = 132                                       # ten years of year-on-year change need 120 months with a month a year before each
OVERDUE_AFTER_DAYS = 70                                # from the 1st of the observed month: the figures come about 35 days after it and the next month's about 30 days later, plus a week
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
    base = SERIES[0]
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the jobs detail series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(data[base]):
            raise ValueError(f"the {NAMES[sid]} series covers different months than the first series")
    months = sorted(data[base])
    if any(d.day != 1 for d in months):
        raise ValueError("a jobs detail date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the jobs detail months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the jobs detail series cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    _check_ranges(data, months)
    sum_gap = 0.0
    for whole, parts, tolerance in SUMS:
        for d in months:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > tolerance:
                raise ValueError(f"{NAMES[whole]} are {_num(gap)} thousand off its {WORDS[len(parts)]} parts in {_label(d)}, over {tolerance:g}")
            sum_gap = max(sum_gap, gap)
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_sum_gap": round(sum_gap, 4)}


def _diff(now: float, then: float) -> float:
    return round(now - then, 1) + 0.0                  # thousands to a tenth; a fall that rounds to nothing is 0.0, not -0.0


def _item(key: str, label: str, s: dict[date, float], last: date, before: date, ago: date, whole: dict[date, float] | None = None) -> dict:
    item = {"key": key, "label": label, "thousands": s[last], "change_month": _diff(s[last], s[before]), "change_month_pct": _change(s[last], s[before]),
            "change_year": _diff(s[last], s[ago]), "change_year_pct": _change(s[last], s[ago])}
    if whole is not None:
        item["share_pct"] = round(100.0 * s[last] / whole[last], 1)
    return item


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    before, ago = _months_back(last, 1), _months_back(last, 12)
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "groups": [{"key": key, "label": label, "parent": _item(key, label, data[pid], last, before, ago),
                        "children": [_item(ckey, clabel, data[cid], last, before, ago, data[pid]) for ckey, clabel, cid in parts]} for key, label, pid, _, parts in GROUPS],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "sums_ok": True},
            "note": ("Payrolls in detail from the Bureau of Labor Statistics (the Current Employment Statistics survey of employers, the payroll half of the monthly Employment Situation), in thousands of jobs, seasonally adjusted, for the pay period that includes the 12th: "
                     "seven of the larger industries and the parts each is made of. "
                     "A job is a position on a payroll, not a person: someone with two jobs counts twice. Only non-farm employers are counted, so farm work and the self-employed are not in it, and government counts civilian employees only. "
                     "The newest months are revised twice and again every year. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges and the seven sums are in the Check line. "
                     "This describes employment that already happened: it is not a market signal or a forecast.")}


class UsJobsDetail:
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
            return {**base, "available": False, "reason": "Demo mode: the real US jobs detail figures are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US jobs detail could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
