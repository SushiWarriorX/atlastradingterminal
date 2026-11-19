"""US job openings and labour turnover: how many jobs employers in the United States had open at the end of a month and how many people they hired and lost during it, from the Job Openings and Labor Turnover Survey (JOLTS) of the Bureau of Labor Statistics, with payroll employment (Current Employment Statistics) and the number of unemployed persons (Current Population Survey) for scale, via FRED, the St. Louis Fed (public-domain US government data, citation requested; every series page read on 2026-11-18 names only the Bureau of Labor Statistics as source and carries no third-party notice). Free, no key.

How to read it: job openings (JTSJOL) are the jobs not filled on the last business day of the month for which a specific position exists with work available, which could start within 30 days, with active recruiting; 7,523 means 7.523 million. Hires (JTSHIL) and total separations (JTSTSL) are counted over the whole month; separations split into quits (JTSQUL, the worker's choice), layoffs and discharges (JTSLDL, the employer's) and other separations (JTSOSL: retirements, deaths, transfers). Each of the six has a published rate (JTSJOR, JTSHIR, JTSTSR, JTSQUR, JTSLDR, JTSOSR) in percent. Openings per unemployed person divide openings by the unemployed persons of the household survey (UNEMPLOY), which comes out a month earlier than JOLTS and misses October 2025 (no household survey was taken during the shutdown). Each monthly observation is dated the 1st and means the whole month. The newest month is normally 63 to 95 days old by its date.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18: 141 months of openings and 310 months of everything else in one download).
Checks, set from the whole real record (310 months, December 2000 to September 2026) before any test was written: the twelve JOLTS series end in the same month, cover the same months, are dated the 1st and skip no month, and at least 120 months are there; every level is between 100 and 50,000 thousand (the real range is 237 to 16,275), payroll employment is there for every month and between 100,000 and 250,000 thousand (the real range since 2000 is 129,706 to 159,293) and unemployed persons, in the months both have, between 2,000 and 40,000 thousand (5,634 to 23,084); total separations equal quits plus layoffs plus other separations to within 2 thousand (four values each rounded to a thousand; the real largest gap is 1.0 in all 310 months: 210 exact, 51 at +1, 49 at -1); and each published rate equals its level over payroll employment (job openings over payroll employment plus job openings) to within 0.0625 of a point (half a unit of the published decimal plus the rounding of a level and of payrolls; the real largest gap is 0.0504 over 1,860 comparisons, and payroll employment alone as the denominator for openings would be wrong by up to 0.63). A month missing from one series, or a series that ends in another month, is refused. A missing value ('.') is left out, never filled in.
Not checked, and said so: hires minus separations does not equal the change in payroll employment (it is NOT an identity: the median gap is 33 thousand and the largest 12,967 thousand, April 2020), and no bound on the change from one month to the next (the real record has layoffs rising 564% in March 2020, so any bound loose enough is a unit check, which the ranges already are). A one-decimal slip in a published rate can hide inside the rounding allowance: the check catches a mix-up of series, a shifted month or a unit slip, not every wrong digit. The survey is a sample and its figures carry sampling error that FRED does not show.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .claims import _pct
from .failreason import fail_reason
from .fincond import parse
from .moneysupply import _label, _months_back

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Bureau of Labor Statistics, Job Openings and Labor Turnover Survey, Current Employment Statistics and Current Population Survey, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/JTSJOL"
LEVELS = {"JTSJOL": "job openings", "JTSHIL": "hires", "JTSTSL": "total separations", "JTSQUL": "quits", "JTSLDL": "layoffs and discharges", "JTSOSL": "other separations"}
RATES = {"JTSJOR": "JTSJOL", "JTSHIR": "JTSHIL", "JTSTSR": "JTSTSL", "JTSQUR": "JTSQUL", "JTSLDR": "JTSLDL", "JTSOSR": "JTSOSL"}      # the rate and the level it is a rate of
SERIES = [*LEVELS, *RATES, "PAYEMS", "UNEMPLOY"]
FLOWS = (("hires", "JTSHIL", "JTSHIR"), ("separations", "JTSTSL", "JTSTSR"), ("quits", "JTSQUL", "JTSQUR"), ("layoffs", "JTSLDL", "JTSLDR"), ("other", "JTSOSL", "JTSOSR"))
LEVEL_LIMITS = (100.0, 50_000.0)                 # thousands; the real range is 237 to 16,275 (a slip to millions or to units is caught)
PAYROLL_LIMITS = (100_000.0, 250_000.0)          # thousands of jobs; the real range since 2000 is 129,706 to 159,293
UNEMPLOYED_LIMITS = (2_000.0, 40_000.0)          # thousands of people; the real range since 2000 is 5,634 to 23,084
SEPARATIONS_TOLERANCE = 2.0                      # thousands: four values each rounded to a thousand; the real largest gap is 1.0
RATE_TOLERANCE = 2 ** -4                         # points: 0.05 for the rounding of the published decimal plus under 0.001 for the levels; exact in binary; the real largest gap is 0.0504
MIN_MONTHS = 120
HISTORY_MONTHS = 120
OVERDUE_AFTER_DAYS = 105                         # from the 1st of the observed month: the next month normally arrives 61 to 63 days after its own 1st, so the newest month is up to about 95 days old
TTL = 6 * 3600.0
FAIL_TTL = 120.0
LOOKBACK_DAYS = 4200                             # about 11.5 years: 137 months today, enough for ten years of history


def _name(sid: str) -> str:
    return LEVELS[sid] if sid in LEVELS else f"{LEVELS[RATES[sid]]} rate"


def _num(v: float) -> str:
    s = f"{v:,.1f}"
    return s[:-2] if s.endswith(".0") else s


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    base = data["JTSJOL"]
    if len({max(data[sid]) for sid in (*LEVELS, *RATES)}) != 1:
        raise ValueError("the JOLTS series end in different months")
    for sid in (*LEVELS, *RATES):
        if set(data[sid]) != set(base):
            raise ValueError(f"the {_name(sid)} series covers different months than the job openings series")
    months = sorted(base)
    if any(d.day != 1 for d in months):
        raise ValueError("a JOLTS date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the JOLTS values skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"JOLTS covers {len(months)} months, fewer than the {MIN_MONTHS} expected")
    for sid in LEVELS:
        for d in months:
            v = data[sid][d]
            if not (LEVEL_LIMITS[0] <= v <= LEVEL_LIMITS[1]):
                raise ValueError(f"{_name(sid)} of {_num(v)} thousand in {_label(d)} is outside {_num(LEVEL_LIMITS[0])} to {_num(LEVEL_LIMITS[1])}")
    pay, unemployed = data["PAYEMS"], data["UNEMPLOY"]
    for d in months:
        if d not in pay:
            raise ValueError(f"payroll employment is missing for {_label(d)}")
        if not (PAYROLL_LIMITS[0] <= pay[d] <= PAYROLL_LIMITS[1]):
            raise ValueError(f"payroll employment of {_num(pay[d])} thousand in {_label(d)} is outside {_num(PAYROLL_LIMITS[0])} to {_num(PAYROLL_LIMITS[1])}")
    for d in months:
        if d in unemployed and not (UNEMPLOYED_LIMITS[0] <= unemployed[d] <= UNEMPLOYED_LIMITS[1]):
            raise ValueError(f"unemployed persons of {_num(unemployed[d])} thousand in {_label(d)} is outside {_num(UNEMPLOYED_LIMITS[0])} to {_num(UNEMPLOYED_LIMITS[1])}")
    separations_gap = 0.0
    for d in months:
        gap = abs(data["JTSTSL"][d] - data["JTSQUL"][d] - data["JTSLDL"][d] - data["JTSOSL"][d])
        if gap > SEPARATIONS_TOLERANCE:
            raise ValueError(f"separations differ from quits plus layoffs plus other by {_num(gap)} thousand in {_label(d)}, over {_num(SEPARATIONS_TOLERANCE)}")
        separations_gap = max(separations_gap, gap)
    rate_gap = 0.0
    for rate, level in RATES.items():
        for d in months:
            want = 100.0 * data[level][d] / (pay[d] + data[level][d] if level == "JTSJOL" else pay[d])
            gap = abs(want - data[rate][d])
            if gap > RATE_TOLERANCE:
                raise ValueError(f"the {_name(rate)} is {data[rate][d]:g} in {_label(d)} but {want:.2f} from its level and payrolls, over {RATE_TOLERANCE:g}")
            rate_gap = max(rate_gap, gap)
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]), "largest_separations_gap": round(separations_gap, 3), "largest_rate_gap": round(rate_gap, 4)}


def _range(values: dict[date, float], now: float, first: date) -> dict:
    """Lowest, highest (the earliest month when several are equal) and the share of months strictly lower than `now`, over the months in `values`."""
    lo, hi = min(values, key=values.get), max(values, key=values.get)
    return {"months": len(values), "first": _label(first), "lowest": {"value": round(values[lo], 2), "month": _label(lo)}, "highest": {"value": round(values[hi], 2), "month": _label(hi)},
            "share_lower_pct": round(100 * sum(1 for v in values.values() if v < now) / len(values))}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    window = months[-HISTORY_MONTHS:]
    ago, before = _months_back(last, 12), _months_back(last, 1)
    jol, rate, unemployed = data["JTSJOL"], data["JTSJOR"], data["UNEMPLOY"]
    both = [d for d in window if d in unemployed]
    if not both:
        raise ValueError(f"no month of the last {HISTORY_MONTHS} has both job openings and unemployed persons")
    rm = both[-1]
    ratios = {d: jol[d] / unemployed[d] for d in both}
    rago = _months_back(rm, 12)
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "openings": {"level_thousands": jol[last], "rate_pct": rate[last], "rate_year_ago_pct": rate[ago], "change_1m_thousands": round(jol[last] - jol[before], 1), "change_1y_pct": _pct(jol[last], jol[ago]),
                         "range": _range({d: rate[d] for d in window}, rate[last], window[0])},
            "per_unemployed": {"ratio": round(ratios[rm], 2), "month": _label(rm), "unemployed_thousands": unemployed[rm],
                               "year_ago": round(jol[rago] / unemployed[rago], 2) if rago in unemployed else None, "range": _range(ratios, ratios[rm], window[0])},
            "flows": [{"id": fid, "name": LEVELS[lv], "level_thousands": data[lv][last], "rate_pct": data[rt][last], "rate_year_ago_pct": data[rt][ago], "change_1y_pct": _pct(data[lv][last], data[lv][ago])} for fid, lv, rt in FLOWS],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "separations_add_up_ok": True, "rates_follow_levels_ok": True},
            "note": ("The Job Openings and Labor Turnover Survey (JOLTS) of the US Bureau of Labor Statistics, seasonally adjusted, monthly. "
                     "Job openings are jobs not filled on the last business day of the month: a specific position with work available that could start within 30 days, with active recruiting. "
                     "Openings fall when positions are filled and when they are removed without filling positions. "
                     "Hires and separations are counted over the whole month. Separations are quits (the worker's choice), layoffs and discharges (the employer's) and other (retirements, deaths, transfers). "
                     "Rates divide a count by payroll employment (openings: by payroll employment plus openings). "
                     "Openings per unemployed person divide openings by the unemployed persons of the household survey. "
                     "The newest months are preliminary and are revised later; each figure carries its month. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the rates rebuilt from the levels are in the Check line. "
                     "This describes the labour market that already happened: it is not a market signal or a forecast.")}


class Jolts:
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
            return {**base, "available": False, "reason": "Demo mode: the real US job openings figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US job openings could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
