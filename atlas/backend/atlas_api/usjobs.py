"""The US jobs report: the monthly Employment Situation of the Bureau of Labor Statistics, as FRED, the St. Louis Fed, carries it (public-domain US government data, citation requested; every series page read on 2026-11-18 names only the Bureau of Labor Statistics as source and carries no third-party notice). Free, no key.

How to read it: payrolls (PAYEMS, with USPRIV for private employers and USGOVT for civilian government) count jobs at employers, from the Current Employment Statistics survey of establishments, in thousands: 159,293 means 159.293 million jobs, and the change from the month before is the headline "jobs added". The household figures come from a different survey, the Current Population Survey of households, in thousands of people aged 16 and over: the labour force (CLF16OV) is the employed (CE16OV) plus the unemployed (UNEMPLOY), the unemployment rate (UNRATE) is the unemployed as a share of the labour force, the participation rate (CIVPART) is the labour force as a share of the civilian non-institutional population (CNP16OV, a population, not seasonally adjusted) and the employment-population ratio (EMRATIO) is the employed as a share of it. A person without a job who is not looking is not unemployed. Each monthly observation is dated the 1st and means the whole month. The household survey has no figure for October 2025 (a real hole in all seven of its series inside the window); the newest month is normally 31 to 64 days old by its date.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18 while reading JOLTS).
Checks, set from the whole real record (payrolls 1,054 months from January 1939, household 945 months from January 1948) before any test was written: the three payroll series end in the same month, cover the same months and skip no month, at least 120 months are there and dated the 1st; the seven household series end in that same month and cover the same months as one another, every household month has payrolls and at most 3 months of the newest 120 lack household figures (the real record has 1); each level is inside a range set around the real one (payrolls 100,000 to 250,000 thousand against a real 129,706 to 159,293 since 2000, private 80,000 to 200,000, government 10,000 to 40,000, the labour force and the employed 100,000 to 250,000, the unemployed 2,000 to 40,000, the population 150,000 to 400,000); total nonfarm payrolls equal private plus government payrolls to within 1.5 thousand (the real gap is 0 in all 1,054 months: BLS publishes the total as the sum, so this shows the series belong together); the labour force equals the employed plus the unemployed to within 1.5 thousand (three values each rounded to a thousand; the real gap is 0 in 855 of 945 months, +1 in 48 and -1 in 42); and each of the three published rates equals its own numerator over its own denominator to within 0.0625 of a point (half a unit of the published decimal plus rounding; the real largest gap is 0.04998 over 945 months, none above 0.05). A month missing from one series, or a series that ends in another month, is refused. A missing value ('.') is left out, never filled in.
NOT checked, and said so: payroll employment against household employment (two different surveys that do not agree month to month), and no bound on a month's move (payrolls fell 20,469 thousand in April 2020, so any bound loose enough is a unit check, which the ranges already are). A one-decimal slip in a published rate can hide inside the rounding allowance: the check catches a mix-up of series, a shifted month or a unit slip, not every wrong digit. The surveys are samples and their figures carry sampling error that FRED does not show.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .failreason import fail_reason
from .fincond import parse
from .jolts import _num, _range
from .moneysupply import _label, _months_back

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Bureau of Labor Statistics, Employment Situation (Current Employment Statistics and Current Population Survey), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/PAYEMS"
PAYROLLS = {"PAYEMS": "total nonfarm payrolls", "USPRIV": "private payrolls", "USGOVT": "government payrolls"}
HOUSEHOLD = {"CLF16OV": "labour force", "CE16OV": "employed people", "UNEMPLOY": "unemployed people", "CNP16OV": "population"}
RATES = {"UNRATE": "unemployment rate", "CIVPART": "participation rate", "EMRATIO": "employment-population ratio"}
SERIES = [*PAYROLLS, *HOUSEHOLD, *RATES]
RELATIONS = (("UNRATE", "UNEMPLOY", "CLF16OV"), ("CIVPART", "CLF16OV", "CNP16OV"), ("EMRATIO", "CE16OV", "CNP16OV"))      # the rate, its numerator and its denominator
LEVEL_LIMITS = {"PAYEMS": (100_000.0, 250_000.0), "USPRIV": (80_000.0, 200_000.0), "USGOVT": (10_000.0, 40_000.0), "CLF16OV": (100_000.0, 250_000.0), "CE16OV": (100_000.0, 250_000.0),
                "UNEMPLOY": (2_000.0, 40_000.0), "CNP16OV": (150_000.0, 400_000.0)}      # thousands; the real ranges since 2000 are inside (payrolls 129,706 to 159,293, the unemployed 5,481 to 23,084, the population 211,410 to 275,682)
SUM_TOLERANCE = 1.5                              # thousands: three values each rounded to a thousand; the real largest gaps are 0 (payrolls) and 1 (household)
RATE_TOLERANCE = 2 ** -4                         # points: 0.05 for the rounding of the published decimal plus rounding of the levels; exact in binary; the real largest gap is 0.04998
MIN_MONTHS = 120
HISTORY_MONTHS = 120
MAX_HOUSEHOLD_HOLES = 3                          # months of the newest 120 that may have payrolls and no household figures; the real record has 1 (October 2025)
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 75                          # from the 1st of the observed month: the next month comes 63 to 64 days after it (4 December for October), so the newest month is up to about 64 days old
TTL = 6 * 3600.0
FAIL_TTL = 120.0
LOOKBACK_DAYS = 4200                             # about 11.5 years: 138 months today, enough for ten years of history


def _name(sid: str) -> str:
    return {**PAYROLLS, **HOUSEHOLD, **RATES}[sid]


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], list[date], dict]:
    household = [*HOUSEHOLD, *RATES]
    if len({max(data[sid]) for sid in PAYROLLS}) != 1:
        raise ValueError("the payroll series end in different months")
    if len({max(data[sid]) for sid in household}) != 1:
        raise ValueError("the household series end in different months")
    if max(data["PAYEMS"]) != max(data["CLF16OV"]):
        raise ValueError(f"payrolls end in {_label(max(data['PAYEMS']))} but the household survey in {_label(max(data['CLF16OV']))}")
    for sid in list(PAYROLLS)[1:]:
        if set(data[sid]) != set(data["PAYEMS"]):
            raise ValueError(f"the {_name(sid)} series covers different months than total nonfarm payrolls")
    for sid in household:
        if sid != "CLF16OV" and set(data[sid]) != set(data["CLF16OV"]):
            raise ValueError(f"the {_name(sid)} series covers different months than the labour force")
    months, hmonths = sorted(data["PAYEMS"]), sorted(data["CLF16OV"])
    if any(d.day != 1 for d in months):
        raise ValueError("a jobs report date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the payroll months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"payrolls cover {len(months)} months, fewer than the {MIN_MONTHS} expected")
    for d in hmonths:
        if d not in data["PAYEMS"]:
            raise ValueError(f"payroll figures are missing for {_label(d)}")
    holes = [d for d in months[-HISTORY_MONTHS:] if d not in data["CLF16OV"]]
    if len(holes) > MAX_HOUSEHOLD_HOLES:
        raise ValueError(f"household figures are missing for {len(holes)} of the last {HISTORY_MONTHS} months")
    for sid, (lo, hi) in LEVEL_LIMITS.items():
        for d in sorted(data[sid]):
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"the {_name(sid)} of {_num(v)} thousand in {_label(d)} is outside {_num(lo)} to {_num(hi)}")
    payroll_gap = 0.0
    for d in months:
        gap = abs(data["PAYEMS"][d] - data["USPRIV"][d] - data["USGOVT"][d])
        if gap > SUM_TOLERANCE:
            raise ValueError(f"private plus government payrolls differ from total nonfarm by {_num(gap)} thousand in {_label(d)}, over {_num(SUM_TOLERANCE)}")
        payroll_gap = max(payroll_gap, gap)
    force_gap = 0.0
    for d in hmonths:
        gap = abs(data["CLF16OV"][d] - data["CE16OV"][d] - data["UNEMPLOY"][d])
        if gap > SUM_TOLERANCE:
            raise ValueError(f"employed plus unemployed people differ from the labour force by {_num(gap)} thousand in {_label(d)}, over {_num(SUM_TOLERANCE)}")
        force_gap = max(force_gap, gap)
    rate_gap = 0.0
    for rate, num, den in RELATIONS:
        for d in hmonths:
            want = 100.0 * data[num][d] / data[den][d]
            gap = abs(want - data[rate][d])
            if gap > RATE_TOLERANCE:
                raise ValueError(f"the {_name(rate)} is {data[rate][d]:g} in {_label(d)} but {want:.2f} from the levels, over {RATE_TOLERANCE:g}")
            rate_gap = max(rate_gap, gap)
    return months, hmonths, {"months_checked": len(months), "household_months_checked": len(hmonths), "first_month": _label(months[0]), "last_month": _label(months[-1]),
                             "largest_payroll_gap": round(payroll_gap, 3), "largest_labour_force_gap": round(force_gap, 3), "largest_rate_gap": round(rate_gap, 4)}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, hmonths, detail = _check(data)
    last = months[-1]
    window = months[-HISTORY_MONTHS:]
    before, ago = _months_back(last, 1), _months_back(last, 12)
    pay = data["PAYEMS"]

    def part(sid: str) -> dict:
        v = data[sid]
        return {"level_thousands": v[last], "change_thousands": round(v[last] - v[before], 1), "change_year_thousands": round(v[last] - v[ago], 1)}

    def rate(sid: str) -> dict:
        v = data[sid]
        return {"pct": v[last], "month_before_pct": v.get(before), "year_ago_pct": v.get(ago)}

    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "payrolls": {**part("PAYEMS"), "private": part("USPRIV"), "government": part("USGOVT"),
                         "recent": [{"month": _label(m), "change_thousands": round(pay[m] - pay[_months_back(m, 1)], 1)} for m in (_months_back(last, i) for i in range(RECENT_MONTHS - 1, -1, -1))]},
            "household": {"unemployment_rate": rate("UNRATE"), "participation_rate": rate("CIVPART"), "employment_ratio": rate("EMRATIO"),
                          "labour_force_thousands": data["CLF16OV"][last], "employed_thousands": data["CE16OV"][last], "unemployed_thousands": data["UNEMPLOY"][last],
                          "range": _range({d: data["UNRATE"][d] for d in window if d in data["UNRATE"]}, data["UNRATE"][last], window[0])},
            "household_gaps": [_label(d) for d in window if d not in data["CLF16OV"]],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "payroll_parts_add_up_ok": True, "labour_force_adds_up_ok": True, "rates_follow_levels_ok": True},
            "note": ("The Employment Situation of the US Bureau of Labor Statistics, monthly, seasonally adjusted. "
                     "Payrolls count jobs at employers (a survey of establishments): total nonfarm, private and government (civilians only). "
                     "The household figures come from a survey of households: the labour force is the employed plus the unemployed, the unemployment rate is the unemployed as a share of the labour force, "
                     "participation is the labour force as a share of the population aged 16 and over, and the employment-population ratio is the employed as a share of that population. "
                     "A person without a job who is not looking is not unemployed. "
                     "The two surveys count different things and do not agree month to month. "
                     "The newest months are revised in later releases; each figure carries its month. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the rates rebuilt from the levels are in the Check line. "
                     "This describes the labour market that already happened: it is not a market signal or a forecast.")}


class UsJobs:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # One series per request: with several ids a single cosd applies to the first series only. No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast.
        r = await c.get(URL, params={"id": sid, "cosd": (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real US jobs figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US jobs figures could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
