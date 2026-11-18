"""Euro-area government bond yields from the ECB Data Portal's public API (official, free, no key): the ECB's yield curve for AAA-rated euro-area government bonds, daily.

How to read it: the ECB fits a Svensson curve to the prices of AAA-rated euro-area government bonds every business day and publishes the spot rates read off it (the source's own labels: "Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation"), the six numbers that describe the curve (Beta 0 to 3 and Tau 1 and 2) and the spreads between the 10-year and shorter spot rates. It is a fitted curve, not a market quote. A day arrives one business day later.
Checks, set from the whole real record (5,675 business days, 2004-09-06 to 2026-11-16, fifteen series) before any test was written: every series reports the units the card assumes (percent per annum, multiplier 1); all end on the same day; the days follow each other (the real gaps are 1 day for 4,493 pairs, 2 for 16, 3 for 1,114, 4 for 17, 5 for 33 and 6 for one: weekends and holidays, so more than 8 days is a hole); each spot rate lies between -3% and 10% (the real range is -0.996% to 5.175%) and each spread between -4 and 6 points (real -1.781 to 3.538); each rate and spread moves by no more than a bound set from its real one-day extremes (for example the 10-year rate -0.5 to +0.5 points against a real -0.265 to +0.236, the 3-month rate -1.5 to +0.5 against -0.940 to +0.272); each model parameter on the newest day lies in a wide range (real: Beta 0 -0.34 to 5.56, Beta 1 -5.04 to 3.20, Beta 2 -11.1 to 36.9, Beta 3 -36.5 to 12.4, Tau 1 0.25 to 17.1, Tau 2 0.25 to 16.9). These are plain checks on the real record, not sums.
**Two checks are the ECB's own arithmetic**, which show that the series fetched belong to one release and were not mixed up, not that the figures are right: the published spreads equal the 10-year spot rate minus the shorter one (the real gap is at most 1e-10 on all 5,675 days, so the tolerance of 0.000001 is generous and is applied to each of the last 520 days), and each spot rate equals the Svensson curve evaluated with the published parameters (the real gap is at most 1.5e-10 on 5,670 days). That second identity is checked on the newest day only because it is not exact on five days of the record: four days in May 2007 (up to 6e-5) and 2022-06-23 (0.056 points, a day whose parameters carry 8 decimals instead of 15 and do not reproduce its own rates), so one old inconsistent day would otherwise hide the card for two years.
It describes yields that already happened: it is not a market signal or a forecast. A failure says so and shows nothing. A missing value is left out, never filled in.
"""
from __future__ import annotations

import asyncio
import csv
import io
import math
import re
import statistics
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .failreason import fail_reason

BASE = "https://data-api.ecb.europa.eu/service/data/YC/"
CURVE = "B.U2.EUR.4F.G_N_A.SV_C_YM."
SOURCE = "European Central Bank, euro-area yield curve for AAA-rated government bonds (Svensson model), as published on the ECB Data Portal (official, free public data)"
PAGE = BASE + CURVE + "SR_10Y"
TEN = "SR_10Y"
RATES = ("SR_3M", "SR_1Y", "SR_2Y", "SR_5Y", "SR_10Y", "SR_30Y")
YEARS = {"SR_3M": 0.25, "SR_1Y": 1.0, "SR_2Y": 2.0, "SR_5Y": 5.0, "SR_10Y": 10.0, "SR_30Y": 30.0}
LABELS = {"SR_3M": "3 months", "SR_1Y": "1 year", "SR_2Y": "2 years", "SR_5Y": "5 years", "SR_10Y": "10 years", "SR_30Y": "30 years"}
SPREADS = ("SRS_10Y_3M", "SRS_10Y_1Y", "SRS_10Y_2Y")
SPREAD_OF = {"SRS_10Y_3M": "SR_3M", "SRS_10Y_1Y": "SR_1Y", "SRS_10Y_2Y": "SR_2Y"}
SPREAD_LABELS = {"SRS_10Y_3M": "10 years minus 3 months", "SRS_10Y_1Y": "10 years minus 1 year", "SRS_10Y_2Y": "10 years minus 2 years"}
PARAMS = ("BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2")
NAMES = {"SR_3M": "the 3-month rate", "SR_1Y": "the 1-year rate", "SR_2Y": "the 2-year rate", "SR_5Y": "the 5-year rate", "SR_10Y": "the 10-year rate", "SR_30Y": "the 30-year rate",
         "SRS_10Y_3M": "the spread of the 10-year over the 3-month rate", "SRS_10Y_1Y": "the spread of the 10-year over the 1-year rate", "SRS_10Y_2Y": "the spread of the 10-year over the 2-year rate",
         "BETA0": "model parameter Beta 0", "BETA1": "model parameter Beta 1", "BETA2": "model parameter Beta 2", "BETA3": "model parameter Beta 3", "TAU1": "model parameter Tau 1", "TAU2": "model parameter Tau 2"}
UNIT = ("PCPA", "0")                  # the ECB's own labels: percent per annum
RATE_LIMITS = (-3.0, 10.0)            # percent; the real range is -0.996 to 5.175
SPREAD_LIMITS = (-4.0, 6.0)           # points; the real range is -1.781 to 3.538
PARAM_LIMITS = {"BETA0": (-3.0, 10.0), "BETA1": (-10.0, 10.0), "BETA2": (-30.0, 60.0), "BETA3": (-60.0, 30.0), "TAU1": (0.1, 30.0), "TAU2": (0.1, 30.0)}
MOVES = {"SR_3M": (-1.5, 0.5), "SR_1Y": (-0.8, 0.5), "SR_2Y": (-0.8, 0.5), "SR_5Y": (-0.6, 0.5), "SR_10Y": (-0.5, 0.5), "SR_30Y": (-1.0, 0.6),          # points in one day; the real extremes are in the docstring and the log
         "SRS_10Y_3M": (-0.6, 1.5), "SRS_10Y_1Y": (-0.5, 0.5), "SRS_10Y_2Y": (-0.4, 0.6)}
SPREAD_TOLERANCE = 0.000001           # the real gap is at most 1e-10
CURVE_TOLERANCE = 0.000001            # the real gap is at most 1.5e-10 except on five days
MAX_GAP_DAYS = 8                      # the real gaps are 1 to 6 days
TEN_LAST_N = 2700                     # about 10.4 years of business days
RATES_LAST_N = 520                    # about two years: the days on which the other rates and the spreads are checked
PARAMS_LAST_N = 1                     # the identity with the curve is checked on the newest day only
WINDOW_DAYS = 3652
MIN_WINDOW_DAYS = 1300
OVERDUE_AFTER_DAYS = 8                # a day's value comes out on the next business day; after a long holiday weekend the newest can be about 6 days old
TTL = 6 * 3600.0
FAIL_TTL = 120.0
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _day(x) -> date | None:
    """A day written exactly YYYY-MM-DD."""
    if not isinstance(x, str) or not _DAY.fullmatch(x):
        return None
    try:
        return date(int(x[:4]), int(x[5:7]), int(x[8:10]))
    except ValueError:
        return None


def parse(text: str, ids: tuple[str, ...]) -> tuple[dict[str, dict[date, float]], dict[str, tuple[str, str]], dict[str, str]]:
    """Values by series id (for example "SR_10Y"), the units each series reports (the ECB's UNIT and UNIT_MULT) and the status of each series' newest value ("A" normal). Rows of any other series, and rows without a day or a number, are left out; two values for one day are an error."""
    values: dict[str, dict[date, float]] = {i: {} for i in ids}
    wanted = {f"YC.{CURVE}{i}": i for i in ids}
    units: dict[str, tuple[str, str]] = {}
    newest: dict[str, tuple[date, str]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        sid, d, v = wanted.get(r.get("KEY") or ""), _day(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if sid is None or d is None or v is None:
            continue
        if d in values[sid]:
            raise ValueError(f"{sid} has two values for {d.isoformat()}")
        values[sid][d] = v
        units[sid] = ((r.get("UNIT") or "").strip(), (r.get("UNIT_MULT") or "").strip())
        if sid not in newest or d > newest[sid][0]:
            newest[sid] = (d, (r.get("OBS_STATUS") or "").strip())
    missing = [i for i in ids if not values[i]]
    if missing:
        raise ValueError("the source returned no values for " + ", ".join(missing))
    return values, units, {i: s for i, (d, s) in newest.items()}


def svensson(p: dict[str, float], years: float) -> float:
    """The spot rate (percent) of the Svensson curve with the ECB's published parameters at a maturity in years."""
    x1, x2 = years / p["TAU1"], years / p["TAU2"]
    g = lambda x: (1 - math.exp(-x)) / x
    return p["BETA0"] + p["BETA1"] * g(x1) + p["BETA2"] * (g(x1) - math.exp(-x1)) + p["BETA3"] * (g(x2) - math.exp(-x2))


def _check(v: dict[str, dict[date, float]], units: dict) -> tuple[list[date], dict]:
    for sid, u in units.items():
        if u != UNIT:
            raise ValueError(f"the ECB reports {NAMES[sid]} in other units than the card assumes")
    if len({max(s) for s in v.values()}) != 1:
        raise ValueError("the yield curve series end on different days")
    days = sorted(v[TEN])
    for a, b in zip(days, days[1:]):
        if (b - a).days > MAX_GAP_DAYS:
            raise ValueError(f"the 10-year rate skips from {a.isoformat()} to {b.isoformat()}, more than {MAX_GAP_DAYS} days")
    recent = days[-RATES_LAST_N:]
    window = lambda sid: days if sid == TEN else recent
    for sid in RATES + SPREADS:
        for d in window(sid):
            if d not in v[sid]:
                raise ValueError(f"{NAMES[sid]} is missing for {d.isoformat()}")
    for sid in RATES + SPREADS:
        lo, hi = RATE_LIMITS if sid in RATES else SPREAD_LIMITS
        for d in window(sid):
            if not (lo <= v[sid][d] <= hi):
                raise ValueError(f"{NAMES[sid]} is {v[sid][d]:.4f} on {d.isoformat()}, outside {lo:g} to {hi:g}")
    for sid in RATES + SPREADS:
        lo, hi = MOVES[sid]
        ds = window(sid)
        for a, b in zip(ds, ds[1:]):
            ch = v[sid][b] - v[sid][a]
            if not (lo <= ch <= hi):
                raise ValueError(f"{NAMES[sid]} moved by {ch:+.4f} points on {b.isoformat()}, outside {lo:+.1f} to {hi:+.1f}")
    last = days[-1]
    for sid in PARAMS:
        lo, hi = PARAM_LIMITS[sid]
        if not (lo <= v[sid][last] <= hi):
            raise ValueError(f"{NAMES[sid]} is {v[sid][last]:.4f} on {last.isoformat()}, outside {lo:g} to {hi:g}")
    worst_spread = 0.0                                                                                   # the ECB's own arithmetic: shows the series belong together
    for sid, other in SPREAD_OF.items():
        for d in recent:
            off = v[sid][d] - (v[TEN][d] - v[other][d])
            if abs(off) > SPREAD_TOLERANCE:
                raise ValueError(f"{NAMES[sid]} is not the difference of the two rates on {d.isoformat()} (off by {off:+.6f})")
            worst_spread = max(worst_spread, abs(off))
    p = {sid: v[sid][last] for sid in PARAMS}
    worst_curve = 0.0
    for sid in RATES:
        gap = abs(v[sid][last] - svensson(p, YEARS[sid]))
        if gap > CURVE_TOLERANCE:
            raise ValueError(f"{NAMES[sid]} on {last.isoformat()} is {gap:.6f} points away from the curve of the published model parameters, more than {CURVE_TOLERANCE:g}")
        worst_curve = max(worst_curve, gap)
    return days, {"days_checked": len(days), "rate_days_checked": len(recent), "largest_spread_gap": round(worst_spread, 9), "largest_curve_gap": round(worst_curve, 9)}


def _window(rate: dict[date, float], last: date) -> dict | None:
    """The ten years up to `last`, which is the newest day of the series."""
    days = [d for d in sorted(rate) if d > last - timedelta(days=WINDOW_DAYS)]
    if len(days) < MIN_WINDOW_DAYS:
        return None
    lo, hi = min(days, key=lambda d: rate[d]), max(days, key=lambda d: rate[d])
    return {"days": len(days), "from": days[0].isoformat(), "years": 10, "median": round(statistics.median(rate[d] for d in days), 2),
            "lowest": {"value": round(rate[lo], 2), "date": lo.isoformat()}, "highest": {"value": round(rate[hi], 2), "date": hi.isoformat()},
            "share_lower_pct": round(100 * sum(1 for d in days if rate[d] < rate[last]) / len(days))}


def _before(rate: dict[date, float], last: date, days_back: int) -> dict | None:
    """The newest value on or before `days_back` calendar days before the last day, with its date and the change to now."""
    earlier = [d for d in rate if d <= last - timedelta(days=days_back)]
    if not earlier:
        return None
    d = max(earlier)
    return {"date": d.isoformat(), "value": round(rate[d], 2), "change": round(rate[last] - rate[d], 2)}


def summarize(v: dict, units: dict, status: dict[str, str], today: date) -> dict:
    days, detail = _check(v, units)
    last = days[-1]
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "provisional": status.get(TEN, "") not in ("", "A"),
            "rates": [{"id": sid, "label": LABELS[sid], "years": YEARS[sid], "rate_pct": round(v[sid][last], 2), "week_ago": _before(v[sid], last, 7), "month_ago": _before(v[sid], last, 30)} for sid in RATES],
            "spreads": [{"id": sid, "label": SPREAD_LABELS[sid], "points": round(v[sid][last], 2)} for sid in SPREADS],
            "window": _window(v[TEN], last), "detail": detail,
            "checks": {"units_ok": True, "days_in_a_row": True, "range_ok": True, "daily_move_ok": True, "parameters_in_range_ok": True, "spreads_are_differences_ok": True, "rates_follow_the_curve_ok": True},
            "note": ("The ECB fits a Svensson curve to the prices of AAA-rated euro-area government bonds every business day and publishes the spot rates read off it (zero-coupon rates, continuous compounding), the six numbers that describe the curve and the spreads between the 10-year and shorter spot rates. "
                     "It is a fitted curve, not a market quote, for the euro area with its changing composition. A day arrives one business day later. "
                     "Plain checks: the units are the ones assumed and no hole is longer than 8 days; the ranges and the ECB's own sums that held are in the Check line. "
                     "This describes yields that already happened: it is not a market signal or a forecast.")}


class EuroYields:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _get(self, c: httpx.AsyncClient, key: str, last_n: int) -> str:
        r = await c.get(BASE + CURVE + key, params={"lastNObservations": last_n, "format": "csvdata"}, headers={"User-Agent": "ATLAS research terminal", "Accept": "text/csv"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return r.text

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real euro-area yield curve is not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            ten_text, other_text, param_text = await asyncio.gather(self._get(c, TEN, TEN_LAST_N), self._get(c, "+".join(s for s in RATES + SPREADS if s != TEN), RATES_LAST_N), self._get(c, "+".join(PARAMS), PARAMS_LAST_N))
            ten, t_units, status = parse(ten_text, (TEN,))
            others, o_units, _ = parse(other_text, tuple(s for s in RATES + SPREADS if s != TEN))
            params, p_units, _ = parse(param_text, PARAMS)
            res = {**base, **summarize({**ten, **others, **params}, {**t_units, **o_units, **p_units}, status, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The euro-area yield curve could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
