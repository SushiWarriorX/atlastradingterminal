"""US jobs by industry: how many jobs employers had on their payrolls in each industry, from the Bureau of Labor Statistics (the Current Employment Statistics survey of employers, the payroll half of the monthly Employment Situation), via FRED, the St. Louis Fed.

How to read it: thousands of jobs, seasonally adjusted, for the pay period that includes the 12th of the month. A job is a position on a payroll, not a person (someone with two jobs counts twice), and only non-farm employers are counted. The newest months are revised twice and again every year. All the series come from one release and end in the same month (2026-10 on 2026-11-25).
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18). Every request starts at 2015-01-01 and nothing is sent but the id and the date. No key, no custom User-Agent (FRED stalls and drops connections for an unfamiliar one, seen 2026-11-12), the client's own 25 second timeout, six requests at a time.
Checks, set from the whole real record (1,054 months from 1939-01 to 2026-10, none missing in any of the 17 series; the card asks for 2015-01 on) before any test was written: the 17 series end in the same month and cover the same months, every date is the 1st and no month is skipped; every series stays inside a range of about half its lowest to about twice its highest value of the WHOLE record (the literals below); and six sums hold, each to the thousand: total = private + government, private = goods-producing + private service-providing, goods-producing = mining and logging + construction + manufacturing, manufacturing = durable + nondurable, private service-providing = the seven private service industries, and total = the eleven industries (the real gap is 0 in all 1,054 months for all six). The tolerance of each sum is the arithmetic bound of its rounding (0.5 per figure: 1.5, 1.5, 2.0, 1.5, 4.0 and 6.0), not the measured 0, because the Bureau could publish a total that was rounded on its own. A month-on-month move is NOT limited: the real ones are large (total payrolls fell 20,469 thousand in 2020-04 and rose 4,631 thousand in 2020-06).
The sums are the Bureau's own arithmetic: they show that the series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: the revisions of older months; which series is wrong when a check fails (the message says only that they disagree); who is counted (farm work, the self-employed and unpaid family workers are not); and the detail below the eleven industries.
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
SOURCE = "U.S. Bureau of Labor Statistics, Current Employment Statistics (the Employment Situation payrolls by industry), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/PAYEMS"
START = "2015-01-01"                                   # the first month of the card: 142 months to 2026-10
TOTAL, PRIV, GOV, GOOD, SERV = "PAYEMS", "USPRIV", "USGOVT", "USGOOD", "CES0800000001"
MINE, CONS, MAN, DUR, NDUR = "USMINE", "USCONS", "MANEMP", "DMANEMP", "NDMANEMP"
TPU, INFO, FIN, PBS, EDH, LAH, OTH = "USTPU", "USINFO", "USFIRE", "USPBS", "USEHS", "USLAH", "USSERV"
NAMES = {TOTAL: "total payrolls", PRIV: "private payrolls", GOV: "government payrolls", GOOD: "goods-producing payrolls", SERV: "private service payrolls", MINE: "mining and logging payrolls",
         CONS: "construction payrolls", MAN: "manufacturing payrolls", DUR: "durable manufacturing payrolls", NDUR: "nondurable manufacturing payrolls", TPU: "trade, transport and utilities payrolls",
         INFO: "information payrolls", FIN: "financial activities payrolls", PBS: "professional and business payrolls", EDH: "education and health payrolls", LAH: "leisure and hospitality payrolls",
         OTH: "other services payrolls"}                                # short on purpose: fail_reason shows 110 characters
SERIES = list(NAMES)
LIMITS = {TOTAL: (15000.0, 320000.0), PRIV: (13000.0, 275000.0), GOV: (2000.0, 48000.0), GOOD: (5500.0, 51000.0), SERV: (7400.0, 230000.0), MINE: (270.0, 2500.0), CONS: (520.0, 16800.0),
          MAN: (4500.0, 39200.0), DUR: (2200.0, 24700.0), NDUR: (2100.0, 14500.0), TPU: (3300.0, 57800.0), INFO: (550.0, 7500.0), FIN: (680.0, 18500.0), PBS: (970.0, 45800.0),
          EDH: (690.0, 56200.0), LAH: (930.0, 34100.0), OTH: (270.0, 12100.0)}                  # thousands of jobs; about half the lowest and twice the highest of the whole record since 1939
SUMS = ((TOTAL, (PRIV, GOV), 1.5, "private plus government"),                          # the tolerance is 0.5 per figure: the whole and its parts
        (PRIV, (GOOD, SERV), 1.5, "goods-producing plus private service"),
        (GOOD, (MINE, CONS, MAN), 2.0, "mining, construction and manufacturing"),
        (MAN, (DUR, NDUR), 1.5, "durable plus nondurable manufacturing"),
        (SERV, (TPU, INFO, FIN, PBS, EDH, LAH, OTH), 4.0, "the seven private service industries"),
        (TOTAL, (MINE, CONS, MAN, TPU, INFO, FIN, PBS, EDH, LAH, OTH, GOV), 6.0, "the eleven industries"))
INDUSTRIES = (("mining", "Mining and logging", MINE), ("construction", "Construction", CONS), ("manufacturing", "Manufacturing", MAN), ("trade", "Trade, transportation and utilities", TPU),
              ("information", "Information", INFO), ("financial", "Financial activities", FIN), ("professional", "Professional and business services", PBS),
              ("education_health", "Education and health services", EDH), ("leisure", "Leisure and hospitality", LAH), ("other", "Other services", OTH), ("government", "Government", GOV))
GROUPS = (("goods", "Goods-producing", GOOD), ("services", "Private service-providing", SERV), ("government", "Government", GOV))
MIN_MONTHS = 132                                       # ten years of year-on-year change need 120 months with a month a year before each
RECENT_MONTHS = 6
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
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the payroll series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(data[TOTAL]):
            raise ValueError(f"the {NAMES[sid]} series covers different months than total payrolls")
    months = sorted(data[TOTAL])
    if any(d.day != 1 for d in months):
        raise ValueError("a payroll date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the payroll months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the payroll series cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    _check_ranges(data, months)
    sum_gap = 0.0
    for whole, parts, tolerance, what in SUMS:
        for d in months:
            gap = abs(data[whole][d] - sum(data[p][d] for p in parts))
            if gap > tolerance:
                raise ValueError(f"{NAMES[whole]} are {_num(gap)} thousand off {what} in {_label(d)}, over {tolerance:g}")
            sum_gap = max(sum_gap, gap)
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_sum_gap": round(sum_gap, 4)}


def _diff(now: float, then: float) -> float:
    return round(now - then, 1) + 0.0                  # thousands to a tenth; a fall that rounds to nothing is 0.0, not -0.0


def _item(key: str, label: str, s: dict[date, float], last: date, before: date, ago: date, total: dict[date, float] | None = None) -> dict:
    item = {"key": key, "label": label, "thousands": s[last], "change_month": _diff(s[last], s[before]), "change_month_pct": _change(s[last], s[before]),
            "change_year": _diff(s[last], s[ago]), "change_year_pct": _change(s[last], s[ago])}
    if total is not None:
        item["share_pct"] = round(100.0 * s[last] / total[last], 1)
    return item


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    before, ago = _months_back(last, 1), _months_back(last, 12)
    age = (today - last).days
    pay = data[TOTAL]
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": _item("total", "Total nonfarm payrolls", pay, last, before, ago),
            "groups": [_item(key, label, data[sid], last, before, ago, pay) for key, label, sid in GROUPS],
            "industries": [_item(key, label, data[sid], last, before, ago, pay) for key, label, sid in INDUSTRIES],
            "manufacturing": [_item("durable", "Durable goods manufacturing", data[DUR], last, before, ago, data[MAN]), _item("nondurable", "Nondurable goods manufacturing", data[NDUR], last, before, ago, data[MAN])],
            "recent": [{"month": _label(d), "thousands": pay[d], "change": _diff(pay[d], pay[_months_back(d, 1)])} for d in months[-RECENT_MONTHS:]],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "sums_ok": True},
            "note": ("Payrolls by industry from the Bureau of Labor Statistics (the Current Employment Statistics survey of employers, the payroll half of the monthly Employment Situation), in thousands of jobs, seasonally adjusted, for the pay period that includes the 12th. "
                     "A job is a position on a payroll, not a person: someone with two jobs counts twice. Only non-farm employers are counted, so farm work and the self-employed are not in it, and government counts civilian employees only. The newest months are revised twice and again every year. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges and the six sums are in the Check line. "
                     "This describes employment that already happened: it is not a market signal or a forecast.")}


class UsIndustryJobs:
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
            return {**base, "available": False, "reason": "Demo mode: the real US jobs by industry figures are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"US jobs by industry could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
