"""Euro-area unemployment from the ECB Data Portal's public API (official, free, no key): how many people in the euro area are looking for work and cannot find it, by sex and by age.

How to read it: the figures come from the European Labour Force Survey and are compiled by Eurostat (the statistical office of the European Union); the ECB Data Portal republishes them. The unemployment rate is the share of the labour force (people who work or look for work) that is unemployed. Everything is for the euro area of 20 countries with a fixed composition (the series' own label: "Euro area 20 (fixed composition) as of 1 January 2023", so countries that joined later are not in it), seasonally adjusted, ages 15 to 74 unless the card says otherwise. Persons are in thousands. A month arrives about a month after it ends.
Checks, set from the whole real record (321 months, January 2000 to September 2026, nine series of rates and nine of persons: all ages, under 25 and 25 to 74, each for everybody, women and men) before any test was written: every series reports the units the card assumes (the ECB's own labels: percent for rates, persons with a multiplier of a thousand); all end in the same month, every one has each of the last 24 months and the months follow each other; every rate is inside a range that catches a slip of the decimal point (the real ranges are everybody 6.2% to 12.2%, women 6.5% to 12.4%, men 6.0% to 12.2%, under 25 14.1% to 25.5%, 25 to 74 5.4% to 10.9%) and moves by no more than a bound set from the real one-month changes (everybody -0.2 to +0.4 points, women -0.4 to +0.5, men -0.2 to +0.5, under 25 -0.9 to +1.1, 25 to 74 -0.2 to +0.4); every number of unemployed persons is inside a range (the real ones, in thousands: everybody 10,714 to 19,751, women 5,209 to 9,230, men 5,500 to 10,600, under 25 2,159 to 3,930, 25 to 74 8,417 to 15,897) and moves by no more than a bound set from the real changes (-5.42% in March 2020 and +7.59% in July 2020, both for women: the extremes of the five series). **Two checks that are not Eurostat's sums:** the rate for everybody lies between the rates of women and men, and between the rates of the under 25 and the 25 to 74 (both hold in all 321 real months with no tolerance; the tolerance of 0.1 is the rounding of the published one-decimal rates). **Three checks that are Eurostat's own arithmetic**, which show that the series fetched belong to one release and were not mixed up, not that the figures are right: the persons of women and men add up to everybody's and the under 25 and the 25 to 74 add up to everybody's (they do to within 0.1 thousand, the rounding, in all 321 months, so the tolerance is 0.2 thousand), and the labour force implied by each group's persons and rate (persons divided by the rate) of the parts agrees with the one implied for everybody (within 1.37% in all months for the sexes and 1.38% for the ages, the rounding of a one-decimal rate; the tolerance is 2.5%). A series that ends in another month, or a month missing from one, is refused. A missing value is left out, never filled in.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import csv
import io
import math
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .failreason import fail_reason
from .moneysupply import _label, _months_back

BASE = "https://data-api.ecb.europa.eu/service/data/LFSI/"
RATE_KEY = "M.I9.S.UNEHRT.TOTAL0.15_74+15_24+25_74.T+F+M"
LEVEL_KEY = "M.I9.S.UNEMPL.TOTAL0.15_74+15_24+25_74.T+F+M"
SOURCE = "Eurostat (European Labour Force Survey), as published on the European Central Bank's Data Portal (official, free public data)"
PAGE = BASE + "M.I9.S.UNEHRT.TOTAL0.15_74.T"
TOTAL, WOMEN, MEN, YOUTH, ADULTS = "15_74.T", "15_74.F", "15_74.M", "15_24.T", "25_74.T"
NAMES = {TOTAL: "everybody aged 15 to 74", WOMEN: "women", MEN: "men", YOUTH: "people under 25", ADULTS: "people aged 25 to 74"}
IDS = (TOTAL, WOMEN, MEN, YOUTH, ADULTS)
PAIRS = ((WOMEN, MEN, "women and men"), (YOUTH, ADULTS, "people under 25 and people aged 25 to 74"))      # the two ways the total is split
RATE_UNIT = ("PC", "0")               # the ECB's own labels: percent
LEVEL_UNIT = ("PERS", "3")            # persons, in thousands
RATE_LIMITS = {TOTAL: (3.0, 20.0), WOMEN: (3.0, 20.0), MEN: (3.0, 20.0), YOUTH: (5.0, 45.0), ADULTS: (3.0, 20.0)}              # percent; the real ranges are in the docstring
RATE_MOVE = {TOTAL: (-1.0, 1.0), WOMEN: (-1.5, 1.5), MEN: (-1.5, 1.5), YOUTH: (-3.0, 3.0), ADULTS: (-1.0, 1.0)}                  # points in one month; the real extremes are in the docstring
LEVEL_LIMITS = {TOTAL: (5_000.0, 40_000.0), WOMEN: (2_500.0, 20_000.0), MEN: (2_500.0, 20_000.0), YOUTH: (1_000.0, 10_000.0), ADULTS: (4_000.0, 30_000.0)}   # thousands of persons
LEVEL_MOVE = (-10.0, 15.0)            # percent in one month; the real extremes are -5.42 and +7.59
BETWEEN_TOLERANCE = 0.1               # points: the rounding of the published rates; the real maximum excess is 0
SUM_TOLERANCE = 0.2                   # thousand persons: the real sums are within 0.1
LABOUR_FORCE_TOLERANCE = 2.5          # percent between the labour force of the parts and of everybody; the real maxima are 1.37 and 1.38
CHECK_MONTHS = 24
HISTORY_MONTHS = 60
RANGE_WINDOW = 120
RATE_LAST_N = 121
LEVEL_LAST_N = 40                     # 24 checked months and 12 more for the change over a year, with room to spare
OVERDUE_AFTER_DAYS = 75               # from the end of the observed month: the next month normally arrives about 61 to 64 days after the previous one ends
TTL = 6 * 3600.0
FAIL_TTL = 120.0
_MONTH = re.compile(r"\d{4}-\d{2}")


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _month(x) -> date | None:
    """A month written exactly YYYY-MM, as the first of that month."""
    if not isinstance(x, str) or not _MONTH.fullmatch(x):
        return None
    try:
        return date(int(x[:4]), int(x[5:7]), 1)
    except ValueError:
        return None


def parse(text: str, indicator: str, ids: tuple[str, ...]) -> tuple[dict[str, dict[date, float]], dict[str, tuple[str, str]], dict[str, str]]:
    """Values by series id ("age.sex", for example "15_74.F"), the units each series reports (the ECB's UNIT and UNIT_MULT), and the status of each series' newest value ("A" normal). Rows of any other series, and rows without a month or a number, are left out; two values for one month are an error."""
    values: dict[str, dict[date, float]] = {i: {} for i in ids}
    units: dict[str, tuple[str, str]] = {}
    newest: dict[str, tuple[date, str]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        age, sex = r.get("AGE_BREAKDOWN") or "", r.get("GENDER") or ""
        sid, d, v = f"{age}.{sex}", _month(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if sid not in values or (r.get("KEY") or "") != f"LFSI.M.I9.S.{indicator}.TOTAL0.{age}.{sex}" or d is None or v is None:
            continue
        if d in values[sid]:
            raise ValueError(f"{sid} has two values for {_label(d)}")
        values[sid][d] = v
        units[sid] = ((r.get("UNIT") or "").strip(), (r.get("UNIT_MULT") or "").strip())
        if sid not in newest or d > newest[sid][0]:
            newest[sid] = (d, (r.get("OBS_STATUS") or "").strip())
    missing = [i for i in ids if not values[i]]
    if missing:
        raise ValueError("the source returned no values for " + ", ".join(missing))
    return values, units, {i: s for i, (d, s) in newest.items()}


def _check(rates: dict, rate_units: dict, levels: dict, level_units: dict) -> tuple[list[date], dict]:
    for kind, units, want in (("rate", rate_units, RATE_UNIT), ("number of unemployed", level_units, LEVEL_UNIT)):
        for sid, u in units.items():
            if u != want:
                raise ValueError(f"the ECB reports the {kind} of {NAMES[sid]} in other units than the card assumes")
    if len({max(s) for s in list(rates.values()) + list(levels.values())}) != 1:
        raise ValueError("the unemployment series end in different months")
    months = sorted(rates[TOTAL])
    recent = months[-CHECK_MONTHS:]
    if any(_months_back(b, 1) != a for a, b in zip(recent, recent[1:])):
        raise ValueError(f"the unemployment values skip a month in the last {CHECK_MONTHS}")
    for sid in IDS:
        for d in recent:
            if d not in rates[sid]:
                raise ValueError(f"the unemployment rate of {NAMES[sid]} is missing for {_label(d)}")
            if d not in levels[sid]:
                raise ValueError(f"the number of unemployed {NAMES[sid]} is missing for {_label(d)}")
        lo, hi = RATE_LIMITS[sid]
        for d in recent:
            if not (lo <= rates[sid][d] <= hi):
                raise ValueError(f"the unemployment rate of {NAMES[sid]} is {rates[sid][d]:.1f}% in {_label(d)}, outside {lo:.0f}% to {hi:.0f}%")
        lo, hi = LEVEL_LIMITS[sid]
        for d in recent:
            if not (lo <= levels[sid][d] <= hi):
                raise ValueError(f"the number of unemployed {NAMES[sid]} is outside the plausible range in {_label(d)}")
        lo, hi = RATE_MOVE[sid]
        for a, b in zip(recent, recent[1:]):
            ch = rates[sid][b] - rates[sid][a]
            if not (lo <= ch <= hi):
                raise ValueError(f"the unemployment rate of {NAMES[sid]} moved by {ch:+.1f} points in {_label(b)}, outside {lo:+.1f} to {hi:+.1f}")
        for a, b in zip(recent, recent[1:]):
            ch = 100 * (levels[sid][b] / levels[sid][a] - 1)
            if not (LEVEL_MOVE[0] <= ch <= LEVEL_MOVE[1]):
                raise ValueError(f"the number of unemployed {NAMES[sid]} changed by {ch:+.1f}% in {_label(b)}, outside {LEVEL_MOVE[0]:+.0f}% to {LEVEL_MOVE[1]:+.0f}%")
    for d in recent:                                                                                    # properties that must hold, not the source's own sums
        for x, y, what in PAIRS:
            lo, hi = sorted((rates[x][d], rates[y][d]))
            if rates[TOTAL][d] < lo - BETWEEN_TOLERANCE or rates[TOTAL][d] > hi + BETWEEN_TOLERANCE:
                raise ValueError(f"the rate for everybody in {_label(d)} ({rates[TOTAL][d]:.1f}%) is outside the range of the rates of {what} ({lo:.1f}% to {hi:.1f}%)")
    worst_sum, worst_force = 0.0, (0.0, recent[-1])
    for d in recent:                                                                                    # Eurostat's own arithmetic: shows the series belong together
        for x, y, what in PAIRS:
            off = levels[x][d] + levels[y][d] - levels[TOTAL][d]
            if abs(off) > SUM_TOLERANCE:
                raise ValueError(f"the numbers of unemployed {what} do not add up to the total in {_label(d)} (off by {off:+.1f} thousand)")
            worst_sum = max(worst_sum, abs(off))
            force = levels[TOTAL][d] / (rates[TOTAL][d] / 100)
            gap = 100 * ((levels[x][d] / (rates[x][d] / 100) + levels[y][d] / (rates[y][d] / 100)) / force - 1)
            if abs(gap) > LABOUR_FORCE_TOLERANCE:
                raise ValueError(f"the labour force implied for {what} in {_label(d)} is {abs(gap):.2f}% away from the one implied for everybody, more than {LABOUR_FORCE_TOLERANCE:g}%")
            if abs(gap) > worst_force[0]:
                worst_force = (abs(gap), d)
    return months, {"months_checked": len(recent), "largest_sum_gap_thousands": round(worst_sum, 1), "largest_labour_force_gap_pct": round(worst_force[0], 2),
                    "largest_labour_force_gap_month": _label(worst_force[1]) if round(worst_force[0], 2) else None}


def _range(rate: dict[date, float], last: date) -> dict | None:
    window = sorted(d for d in rate if d <= last)[-RANGE_WINDOW:]
    if len(window) < 60:
        return None
    lo, hi = min(window, key=lambda d: rate[d]), max(window, key=lambda d: rate[d])
    return {"months": len(window), "lowest": {"pct": round(rate[lo], 1), "month": _label(lo)}, "highest": {"pct": round(rate[hi], 1), "month": _label(hi)},
            "share_lower_pct": round(100 * sum(1 for d in window if rate[d] < rate[last]) / len(window))}


def _month_end(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)


def summarize(rates: dict, rate_units: dict, levels: dict, level_units: dict, status: dict[str, str], today: date) -> dict:
    months, detail = _check(rates, rate_units, levels, level_units)
    last = months[-1]
    total = rates[TOTAL]
    age = (today - _month_end(last)).days
    one, three, twelve = (total.get(_months_back(last, n)) for n in (1, 3, 12))
    year_ago = levels[TOTAL].get(_months_back(last, 12))
    persons = levels[TOTAL][last]
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "provisional": status.get(TOTAL, "") not in ("", "A"),
            "headline": {"rate_pct": round(total[last], 1), "change_1m_points": None if one is None else round(total[last] - one, 1), "change_3m_points": None if three is None else round(total[last] - three, 1),
                         "change_12m_points": None if twelve is None else round(total[last] - twelve, 1)},
            "persons": {"total_thousands": round(persons, 1), "change_12m_thousands": None if year_ago is None else round(persons - year_ago, 1),
                        "women_thousands": round(levels[WOMEN][last], 1), "men_thousands": round(levels[MEN][last], 1), "youth_thousands": round(levels[YOUTH][last], 1), "adults_thousands": round(levels[ADULTS][last], 1),
                        "women_share_pct": round(100 * levels[WOMEN][last] / persons), "youth_share_pct": round(100 * levels[YOUTH][last] / persons)},
            "groups": [{"id": sid, "label": NAMES[sid], "rate_pct": round(rates[sid][last], 1)} for sid in (WOMEN, MEN, YOUTH, ADULTS)],
            "range": _range(total, last), "detail": detail,
            "history": [{"date": d.isoformat(), "rate_pct": round(total[d], 1)} for d in months[-HISTORY_MONTHS:]],
            "checks": {"units_ok": True, "months_in_a_row": True, "range_ok": True, "monthly_move_ok": True, "total_between_sexes_ok": True, "total_between_ages_ok": True, "persons_add_up_ok": True, "labour_force_agrees_ok": True},
            "note": ("The figures come from the European Labour Force Survey and are compiled by Eurostat; the ECB Data Portal republishes them. The rate is the share of the labour force (people who work or look for work) that is unemployed. "
                     "They are for the euro area of 20 countries with a fixed composition (countries that joined later are not in it), seasonally adjusted, ages 15 to 74 unless the card says otherwise; persons are in thousands. "
                     "Plain checks: the units are the ones assumed, no month is missing and no rate or number is outside what the real record allows; the properties and Eurostat's own sums that held are in the Check line. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class EuroUnemployment:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _get(self, c: httpx.AsyncClient, key: str, last_n: int) -> str:
        r = await c.get(BASE + key, params={"lastNObservations": last_n, "format": "csvdata"}, headers={"User-Agent": "ATLAS research terminal", "Accept": "text/csv"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return r.text

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real euro-area unemployment figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            rate_text, level_text = await asyncio.gather(self._get(c, RATE_KEY, RATE_LAST_N), self._get(c, LEVEL_KEY, LEVEL_LAST_N))
            rates, r_units, status = parse(rate_text, "UNEHRT", IDS)
            levels, l_units, _ = parse(level_text, "UNEMPL", IDS)
            res = {**base, **summarize(rates, r_units, levels, l_units, status, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The euro-area unemployment could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
