"""Euro-area consumer prices (HICP) from the ECB Data Portal's public API (official, free, no key): how fast prices are rising in the euro area, and which parts of the basket drive it.

How to read it: HICP is the harmonised index of consumer prices that Eurostat (the statistical office of the European Union) compiles and the ECB publishes. The headline is the annual rate of change of the all-items index, for the euro area as it was in each month (the series' own label is "changing composition"; the history is rebuilt for it). The basket splits into five parts that together make up all of it: processed food (with alcohol and tobacco), unprocessed food, non-energy industrial goods, energy and services; each part has a share of the basket for the year (its weight, in thousandths) and an annual rate. "Core" is the all-items index without energy, food, alcohol and tobacco, that is the goods and the services. The newest month is Eurostat's early (flash) estimate and is replaced by the final figure about two weeks after the month ends; the ECB marks it with the status E.
Checks, set from the whole real record (the headline and the parts from 1997 to 2026-10, 358 months; the parts that start in December 2000 give 311 months) before any test was written: every series reports the units the card assumes (the ECB's own labels: percent change, index points, per mille); all rate and index series end in the same month, every one has each of the last 24 months and the months follow each other; every annual rate is inside a range that catches a slip of the decimal point (the real extremes, all-items -0.7% and +10.6%, processed food +0.3% and +15.8%, unprocessed food -2.7% and +14.7%, non-energy industrial goods -0.5% and +6.8%, energy -14.4% and +44.3%, services +0.4% and +5.6%, core +0.2% and +5.7%); every index is between 20 and 250 (the real ones are 36 to 119, base 2025 = 100) and moves by no more than a bound set from the real one-month changes (all-items -1.55% to +2.43%, processed food -0.43% to +1.60%, unprocessed food -2.55% to +3.46%, non-energy industrial goods -3.89% to +3.81%, energy -6.60% to +12.18%, services -1.28% to +1.44%); the five parts' weights add up to 1000 and the all-items weight is 1000 (in every year since 2001 they do, to within 0.01). **Two checks that are not Eurostat's arithmetic on its own published numbers:** the headline annual rate lies between the lowest and the highest rate of its five parts, and the core rate lies between the rates of the goods and the services (both hold in all 311 real months with no tolerance, and the tolerance of 0.1 is the rounding of the published rates). **Two checks that are Eurostat's own arithmetic**, which show that the series fetched belong to one release and were not mixed up, not that the figures are right: the all-items index equals the December index of the year before times the weighted average of the five parts' indices relative to their own December (the weights are the year's published ones); the real gap is at most 0.021 index points in 310 months since 2001 (0.009 in the last 24) and the tolerance is 0.05; and the published annual rate equals the rate calculated from the published indices (Eurostat calculates one from the other); the real gap is at most 0.050 points in all 2,054 pairs of a month and a series (358 months for four series, 311 for two) and the tolerance is 0.1. Rates are compared as published, indices unrounded. A series that ends in another month, or a month missing from one, is refused. A missing value is left out, never filled in.
"Points of the headline" are the share of the basket times the part's annual rate, summed over the five parts: an approximation (Eurostat's own contributions use the weights of the previous December and the prices since), within 0.1 points of the headline in 292 of the 310 real months and 0.51 at most (March 2022, energy +44%); they are shown only when their sum is within 0.3 points of the headline.
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

BASE = "https://data-api.ecb.europa.eu/service/data/HICP/"
RATE_KEY = "M.U2.N.000000+FOODPR+FOODUN+IGXE00+NRGY00+SERV00+XEF000.4D0.ANR"
INDEX_KEY = "M.U2.N.000000+FOODPR+FOODUN+IGXE00+NRGY00+SERV00.4D0.INX"
WEIGHT_KEY = "A.U2.N.000000+FOODPR+FOODUN+IGXE00+NRGY00+SERV00.4D0.INW"
SOURCE = "Eurostat (the statistical office of the European Union), as published on the European Central Bank's Data Portal (official, free public data)"
PAGE = BASE + "M.U2.N.000000.4D0.ANR"
TOTAL = "000000"
CORE = "XEF000"
PARTS = {"FOODPR": "processed food, alcohol and tobacco", "FOODUN": "unprocessed food", "IGXE00": "non-energy industrial goods", "NRGY00": "energy", "SERV00": "services"}
NAMES = {TOTAL: "all items", CORE: "core (without energy, food, alcohol and tobacco)", **PARTS}
RATE_IDS = (TOTAL, *PARTS, CORE)
INDEX_IDS = (TOTAL, *PARTS)
WEIGHT_IDS = (TOTAL, *PARTS)
RATE_UNIT = ("PCCH", "0")             # the ECB's own labels: percent change
INDEX_UNIT = ("IX", "0")              # index points
WEIGHT_UNIT = ("PM", "0")             # per mille
RATE_LIMITS = {TOTAL: (-3.0, 20.0), "FOODPR": (-3.0, 25.0), "FOODUN": (-10.0, 30.0), "IGXE00": (-3.0, 12.0), "NRGY00": (-30.0, 80.0), "SERV00": (-2.0, 12.0), CORE: (-2.0, 12.0)}   # percent; the real extremes are in the docstring
INDEX_LIMITS = (20.0, 250.0)          # the real indices are 36 to 119 (2025 = 100)
MONTH_MOVE = {TOTAL: (-3.0, 4.0), "FOODPR": (-1.5, 3.0), "FOODUN": (-5.0, 6.0), "IGXE00": (-6.0, 6.0), "NRGY00": (-10.0, 16.0), "SERV00": (-3.0, 3.0)}   # percent change of an index in one month; the real extremes are in the docstring
RATE_TOLERANCE = 0.1                  # points between the published rate and the rate the index gives: the rounding of the published rate; the real maximum is 0.050
BETWEEN_TOLERANCE = 0.1               # points: the rounding of the published rates; the real maximum excess is 0
INDEX_TOLERANCE = 0.05                # index points between the all-items index and what its parts and weights give; the real maximum is 0.021
WEIGHT_TOLERANCE = 0.05               # per mille; the real sums are within 0.01 of 1000
CONTRIBUTION_TOLERANCE = 0.3          # points between the sum of share x rate and the headline, above which the contributions are not shown; the real maximum is 0.51, 305 of 310 months are within 0.3
CHECK_MONTHS = 24
HISTORY_MONTHS = 60                   # five years of the headline rate shown
RANGE_WINDOW = 120                    # ten years of the headline rate for the comparison
RATE_LAST_N = 121
INDEX_LAST_N = 40                     # 24 checked months, 12 more for the rate the index gives, and the December before the oldest checked month
WEIGHT_LAST_N = 4
OVERDUE_AFTER_DAYS = 50               # from the end of the observed month: the flash estimate of the next month normally arrives about 31 to 34 days after it ends
TTL = 6 * 3600.0
FAIL_TTL = 120.0
_MONTH = re.compile(r"\d{4}-\d{2}")
_YEAR = re.compile(r"\d{4}")


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


def _year(x) -> int | None:
    """A year written exactly YYYY."""
    return int(x) if isinstance(x, str) and _YEAR.fullmatch(x) else None


def _when(d) -> str:
    return _label(d) if isinstance(d, date) else str(d)


def parse(text: str, ids: tuple[str, ...], freq: str, suffix: str) -> tuple[dict[str, dict], dict[str, tuple[str, str]], dict[str, str]]:
    """Values by item (months as dates for freq "M", years as integers for freq "A"), the units each item reports (the ECB's UNIT and UNIT_MULT), and the status of each item's newest value ("E" estimate, "A" normal). Rows of any other series, and rows without a period or a number, are left out; two values for one period are an error."""
    period = _month if freq == "M" else _year
    values: dict[str, dict] = {i: {} for i in ids}
    units: dict[str, tuple[str, str]] = {}
    newest: dict[str, tuple] = {}
    for r in csv.DictReader(io.StringIO(text)):
        sid, d, v = r.get("ICP_ITEM") or "", period(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if sid not in values or (r.get("KEY") or "") != f"HICP.{freq}.U2.N.{sid}.4D0.{suffix}" or d is None or v is None:
            continue
        if d in values[sid]:
            raise ValueError(f"{sid} has two values for {_when(d)}")
        values[sid][d] = v
        units[sid] = ((r.get("UNIT") or "").strip(), (r.get("UNIT_MULT") or "").strip())
        if sid not in newest or d > newest[sid][0]:
            newest[sid] = (d, (r.get("OBS_STATUS") or "").strip())
    missing = [i for i in ids if not values[i]]
    if missing:
        raise ValueError("the source returned no values for " + ", ".join(missing))
    return values, units, {i: s for i, (d, s) in newest.items()}


def _check(rates: dict, rate_units: dict, indices: dict, index_units: dict, weights: dict, weight_units: dict) -> tuple[list[date], dict]:
    for kind, units, want in (("annual rate", rate_units, RATE_UNIT), ("index", index_units, INDEX_UNIT), ("weight", weight_units, WEIGHT_UNIT)):
        for sid, u in units.items():
            if u != want:
                raise ValueError(f"the ECB reports the {kind} of {NAMES[sid]} in other units than the card assumes")
    if len({max(s) for s in list(rates.values()) + list(indices.values())}) != 1:
        raise ValueError("the consumer price series end in different months")
    months = sorted(rates[TOTAL])
    recent = months[-CHECK_MONTHS:]
    if any(_months_back(b, 1) != a for a, b in zip(recent, recent[1:])):
        raise ValueError(f"the consumer price values skip a month in the last {CHECK_MONTHS}")
    for sid in RATE_IDS:
        for d in recent:
            if d not in rates[sid]:
                raise ValueError(f"the annual rate of {NAMES[sid]} is missing for {_label(d)}")
        lo, hi = RATE_LIMITS[sid]
        for d in recent:
            if not (lo <= rates[sid][d] <= hi):
                raise ValueError(f"the annual rate of {NAMES[sid]} is {rates[sid][d]:+.1f}% in {_label(d)}, outside {lo:+.0f}% to {hi:+.0f}%")
    need = sorted({m for d in recent for m in (d, _months_back(d, 12), date(d.year - 1, 12, 1))})
    for sid in INDEX_IDS:
        for d in need:
            if d not in indices[sid]:
                raise ValueError(f"the index of {NAMES[sid]} is missing for {_label(d)}")
        if any(not (INDEX_LIMITS[0] <= indices[sid][d] <= INDEX_LIMITS[1]) for d in recent):
            raise ValueError(f"the index of {NAMES[sid]} is outside the plausible range")
        lo, hi = MONTH_MOVE[sid]
        for a, b in zip(recent, recent[1:]):
            ch = 100 * (indices[sid][b] / indices[sid][a] - 1)
            if not (lo <= ch <= hi):
                raise ValueError(f"the index of {NAMES[sid]} changed by {ch:+.1f}% in {_label(b)}, outside {lo:+.1f}% to {hi:+.1f}%")
    for y in sorted({d.year for d in recent}):
        for sid in WEIGHT_IDS:
            if y not in weights[sid]:
                raise ValueError(f"the basket weight of {NAMES[sid]} is missing for {y}")
        parts = sum(weights[sid][y] for sid in PARTS)
        if abs(parts - 1000) > WEIGHT_TOLERANCE or abs(weights[TOTAL][y] - 1000) > WEIGHT_TOLERANCE:
            raise ValueError(f"the basket weights of {y} add up to {parts:.2f} (all items {weights[TOTAL][y]:.2f}) per mille, not 1000")
    for d in recent:                                                                                    # properties that must hold, not the source's own sums
        head, five = rates[TOTAL][d], [rates[sid][d] for sid in PARTS]
        if head < min(five) - BETWEEN_TOLERANCE or head > max(five) + BETWEEN_TOLERANCE:
            raise ValueError(f"the headline rate in {_label(d)} ({head:.1f}%) is outside the range of its five parts ({min(five):.1f}% to {max(five):.1f}%)")
        goods, services = sorted((rates["IGXE00"][d], rates["SERV00"][d]))
        if rates[CORE][d] < goods - BETWEEN_TOLERANCE or rates[CORE][d] > services + BETWEEN_TOLERANCE:
            raise ValueError(f"the core rate in {_label(d)} ({rates[CORE][d]:.1f}%) is outside the range of the goods and the services ({goods:.1f}% to {services:.1f}%)")
    worst_rate, worst_index = 0.0, (0.0, recent[-1])
    for d in recent:                                                                                    # Eurostat's own arithmetic: shows the series belong together
        for sid in INDEX_IDS:
            gap = 100 * (indices[sid][d] / indices[sid][_months_back(d, 12)] - 1) - rates[sid][d]
            if abs(gap) > RATE_TOLERANCE:
                raise ValueError(f"the published annual rate of {NAMES[sid]} in {_label(d)} is {abs(gap):.2f} points away from the rate the index gives, more than {RATE_TOLERANCE:g}")
            worst_rate = max(worst_rate, abs(gap))
        base = date(d.year - 1, 12, 1)
        off = indices[TOTAL][d] - indices[TOTAL][base] * sum(weights[sid][d.year] / 1000 * indices[sid][d] / indices[sid][base] for sid in PARTS)
        if abs(off) > INDEX_TOLERANCE:
            raise ValueError(f"the all-items index in {_label(d)} is {off:+.2f} points from what its five parts and their weights give, more than {INDEX_TOLERANCE:g}")
        if abs(off) > worst_index[0]:
            worst_index = (abs(off), d)
    return months, {"months_checked": len(recent), "largest_rate_gap_points": round(worst_rate, 2), "largest_index_gap": round(worst_index[0], 3), "largest_index_gap_month": _label(worst_index[1]) if round(worst_index[0], 3) else None}


def _range(rate: dict[date, float], last: date) -> dict | None:
    window = sorted(d for d in rate if d <= last)[-RANGE_WINDOW:]
    if len(window) < 60:
        return None
    lo, hi = min(window, key=lambda d: rate[d]), max(window, key=lambda d: rate[d])
    return {"months": len(window), "lowest": {"pct": round(rate[lo], 1), "month": _label(lo)}, "highest": {"pct": round(rate[hi], 1), "month": _label(hi)},
            "share_lower_pct": round(100 * sum(1 for d in window if rate[d] < rate[last]) / len(window))}


def _month_end(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)


def summarize(rates: dict, rate_units: dict, indices: dict, index_units: dict, weights: dict, weight_units: dict, status: dict[str, str], today: date) -> dict:
    months, detail = _check(rates, rate_units, indices, index_units, weights, weight_units)
    last = months[-1]
    total = rates[TOTAL]
    age = (today - _month_end(last)).days
    one, three = total.get(_months_back(last, 1)), total.get(_months_back(last, 3))
    approx = sum(weights[sid][last.year] / 1000 * rates[sid][last] for sid in PARTS)                  # unrounded: compared with the headline before anything is rounded
    gap = approx - total[last]
    agree = abs(gap) <= CONTRIBUTION_TOLERANCE
    parts = [{"id": sid, "label": label, "rate_pct": round(rates[sid][last], 1), "share_pct": round(weights[sid][last.year] / 10, 1),
              "points": round(weights[sid][last.year] / 1000 * rates[sid][last], 2) if agree else None} for sid, label in PARTS.items()]
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "estimate": status.get(TOTAL) in ("E", "P"),
            "headline": {"rate_pct": round(total[last], 1), "change_1m_points": None if one is None else round(total[last] - one, 1), "change_3m_points": None if three is None else round(total[last] - three, 1),
                         "core_rate_pct": round(rates[CORE][last], 1)},
            "parts": parts, "contributions": {"shown": agree, "sum_points": round(approx, 2), "gap_points": round(gap, 2)}, "range": _range(total, last), "detail": detail,
            "history": [{"date": d.isoformat(), "rate_pct": round(total[d], 1)} for d in months[-HISTORY_MONTHS:]],
            "checks": {"units_ok": True, "months_in_a_row": True, "range_ok": True, "monthly_move_ok": True, "weights_ok": True, "headline_between_parts_ok": True, "core_between_ok": True, "index_follows_parts_ok": True, "rate_matches_index_ok": True},
            "note": ("The harmonised index of consumer prices (HICP) is compiled by Eurostat and published on the ECB's Data Portal. The headline is the annual rate of change of the all-items index for the euro area as it was in each month. "
                     "The basket splits into five parts that together make up all of it; each has a share of the basket for the year and an annual rate; core is the all-items index without energy, food, alcohol and tobacco. "
                     "The newest month is Eurostat's early (flash) estimate until the final figure replaces it, about two weeks after the month ends. "
                     "Points of the headline are the share times the rate, an approximation shown only when it agrees with the headline within 0.3 points. "
                     "Checked: the units are the ones assumed, no month is missing, no rate or index is outside what the real record allows, the headline lies between the rates of its five parts and core between the goods and the services, "
                     "and two checks that are Eurostat's own arithmetic (the all-items index follows from the parts' indices and weights, and each published rate matches its index), which show the series belong together, not that the figures are right. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class EuroInflation:
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
            return {**base, "available": False, "reason": "Demo mode: the real euro-area consumer prices are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            rate_text, index_text, weight_text = await asyncio.gather(self._get(c, RATE_KEY, RATE_LAST_N), self._get(c, INDEX_KEY, INDEX_LAST_N), self._get(c, WEIGHT_KEY, WEIGHT_LAST_N))
            rates, r_units, status = parse(rate_text, RATE_IDS, "M", "ANR")
            indices, i_units, _ = parse(index_text, INDEX_IDS, "M", "INX")
            weights, w_units, _ = parse(weight_text, WEIGHT_IDS, "A", "INW")
            res = {**base, **summarize(rates, r_units, indices, i_units, weights, w_units, status, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The euro-area consumer prices could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
