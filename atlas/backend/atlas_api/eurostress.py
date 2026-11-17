"""Euro-area financial stress from the ECB Data Portal's public API (official, free, no key): the ECB's New Composite Indicator of Systemic Stress (the "new CISS"), daily.

How to read it: the ECB builds an index between 0 and 1 of how much stress there is in the euro area's financial markets, from five segments (the bond market, the equity market, financial intermediaries, the foreign exchange market and the money market); a higher value means more stress. The ECB also publishes how much each segment contributes and one more term, the contribution of the correlation between the segments, which is negative on every day: the index is the five segments' contributions plus that term. The area is "Euro area (changing composition)" (the series' own label). A day arrives one business day later. The ECB's older CISS series (keys ending SS_CI) ends on 2 May 2025 and is not used.
Checks, set from the whole real record (the index 12,236 days from 1980-01-03 to 2026-11-16, the six contributions 7,272 days each from 1999-01-01) before any test was written: every series reports the units the card assumes (the ECB's own labels: a pure number, multiplier 1); all end on the same day; the days follow each other (the real gaps are 1 day for 9,789 pairs, 2 for 8, 3 for 2,438: weekends and a few holidays, so more than 5 days is a hole); the index is inside 0 to 1 (the real range is 0.0007 on 2017-11-27 to 0.9409 on 2008-11-20) and moves by no more than 0.25 in a day (the real extremes are +0.1364 on 2010-08-11 and -0.1051 on 1981-10-22; in the ten years the card uses +0.1017 on 2022-09-23 and -0.0627 on 2022-07-04). **Properties that are not the ECB's own sum:** each of the five segments contributes at least 0 and at most 1 (the real ranges: bond market 0.0067 to 0.2569, equity market 0.0032 to 0.1775, financial intermediaries 0.0056 to 0.1942, foreign exchange 0.0005 to 0.1933, money market 0.0024 to 0.1270: never negative in 7,272 days) and the correlation term lies between -1 and 0 (the real range is -0.4103 to -0.0010: never positive in 7,272 days). **One check is the ECB's own arithmetic**, which shows that the seven series fetched belong to one release and were not mixed up, not that the figures are right: the five segments' contributions plus the correlation term add up to the index (the real gap is at most 3.3e-16 over all 7,272 days, so the tolerance of 0.000001 allows for rounding to six decimals but not to the four the ECB displays). A series that ends on another day, a day missing from a contribution, or a hole of more than 5 days is refused. A missing value (the source marks it "M") is left out, never filled in.
It describes stress that has already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
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

BASE = "https://data-api.ecb.europa.eu/service/data/CISS/"
INDEX_KEY = "D.U2.Z0Z.4F.EC.SS_CIN.IDX"
PARTS_KEY = "D.U2.Z0Z.4F.EC.SS_BMN+SS_EMN+SS_FIN+SS_FXN+SS_MMN+SS_CON.CON"
SOURCE = "European Central Bank, New Composite Indicator of Systemic Stress (CISS), as published on the ECB Data Portal (official, free public data)"
PAGE = BASE + INDEX_KEY
INDEX = "SS_CIN"
CORRELATION = "SS_CON"
SEGMENTS = (("SS_BMN", "bond market"), ("SS_EMN", "equity market"), ("SS_FIN", "financial intermediaries"), ("SS_FXN", "foreign exchange market"), ("SS_MMN", "money market"))
PART_IDS = tuple(sid for sid, _ in SEGMENTS) + (CORRELATION,)
NAMES = {INDEX: "the stress index", CORRELATION: "the correlation term", **{sid: f"the contribution of the {name}" for sid, name in SEGMENTS}}
UNIT = ("PURE_NUMB", "0")             # the ECB's own labels: a pure number
INDEX_LIMITS = (0.0, 1.0)             # the index is bounded by its definition; the real range is 0.0007 to 0.9409
INDEX_MOVE = (-0.25, 0.25)            # in one day; the real extremes are -0.1051 and +0.1364
SEGMENT_LIMITS = (0.0, 1.0)           # each segment's contribution; the real range is 0.0005 to 0.2569
CORRELATION_LIMITS = (-1.0, 0.0)      # the real range is -0.4103 to -0.0010
IDENTITY_TOLERANCE = 0.000001         # the real gap is at most 3.3e-16
MAX_GAP_DAYS = 5                      # the real gaps are 1 to 3 days
INDEX_LAST_N = 2700                   # about 10.3 years of business days
PARTS_LAST_N = 520                    # about two years: the days on which the contributions are checked
WINDOW_DAYS = 3652                    # the ten years the card compares with
MIN_WINDOW_DAYS = 1300                # about five years of business days: less than that and no comparison is shown
OVERDUE_AFTER_DAYS = 8                # a day's value comes out on the next business day: after a long holiday weekend the newest can be about 6 days old
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


def parse(text: str, datatype: str, ids: tuple[str, ...]) -> tuple[dict[str, dict[date, float]], dict[str, tuple[str, str]], dict[str, str]]:
    """Values by series id (for example "SS_CIN"), the units each series reports (the ECB's UNIT and UNIT_MULT), and the status of each series' newest value ("A" normal). Rows of any other series, and rows without a day or a number (the source leaves the value empty and marks it "M" when a day has none), are left out; two values for one day are an error."""
    values: dict[str, dict[date, float]] = {i: {} for i in ids}
    wanted = {f"CISS.D.U2.Z0Z.4F.EC.{i}.{datatype}": i for i in ids}
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


def _check(index: dict[date, float], index_unit: dict, parts: dict[str, dict[date, float]], parts_units: dict) -> tuple[list[date], dict]:
    for sid, u in {**index_unit, **parts_units}.items():
        if u != UNIT:
            raise ValueError(f"the ECB reports {NAMES[sid]} in other units than the card assumes")
    if len({max(s) for s in [index] + list(parts.values())}) != 1:
        raise ValueError("the stress series end on different days")
    days = sorted(index)
    for a, b in zip(days, days[1:]):
        if (b - a).days > MAX_GAP_DAYS:
            raise ValueError(f"the stress index skips from {a.isoformat()} to {b.isoformat()}, more than {MAX_GAP_DAYS} days")
    for d in days:
        if not (INDEX_LIMITS[0] <= index[d] <= INDEX_LIMITS[1]):
            raise ValueError(f"the stress index is {index[d]:.4f} on {d.isoformat()}, outside {INDEX_LIMITS[0]:g} to {INDEX_LIMITS[1]:g}")
    worst_move = 0.0
    for a, b in zip(days, days[1:]):
        ch = index[b] - index[a]
        if not (INDEX_MOVE[0] <= ch <= INDEX_MOVE[1]):
            raise ValueError(f"the stress index moved by {ch:+.4f} on {b.isoformat()}, outside {INDEX_MOVE[0]:+.2f} to {INDEX_MOVE[1]:+.2f}")
        worst_move = max(worst_move, abs(ch))
    recent = days[-PARTS_LAST_N:]
    for sid in PART_IDS:
        lo, hi = CORRELATION_LIMITS if sid == CORRELATION else SEGMENT_LIMITS
        for d in recent:
            if d not in parts[sid]:
                raise ValueError(f"{NAMES[sid]} is missing for {d.isoformat()}")
            if not (lo <= parts[sid][d] <= hi):
                raise ValueError(f"{NAMES[sid]} is {parts[sid][d]:+.4f} on {d.isoformat()}, outside {lo:g} to {hi:g}")
    worst_gap = 0.0                                                                                      # the ECB's own arithmetic: shows the series belong together
    for d in recent:
        off = index[d] - sum(parts[sid][d] for sid in PART_IDS)
        if abs(off) > IDENTITY_TOLERANCE:
            raise ValueError(f"the contributions do not add up to the stress index on {d.isoformat()} (off by {off:+.6f})")
        worst_gap = max(worst_gap, abs(off))
    return days, {"days_checked": len(days), "contribution_days_checked": len(recent), "largest_daily_move": round(worst_move, 4), "largest_identity_gap": round(worst_gap, 9)}


def _window(index: dict[date, float], last: date) -> dict | None:
    """The ten years up to `last`, which is the newest day of the index."""
    days = [d for d in sorted(index) if d > last - timedelta(days=WINDOW_DAYS)]
    if len(days) < MIN_WINDOW_DAYS:
        return None
    lo, hi = min(days, key=lambda d: index[d]), max(days, key=lambda d: index[d])
    return {"days": len(days), "from": days[0].isoformat(), "years": 10, "median": round(statistics.median(index[d] for d in days), 4),
            "lowest": {"value": round(index[lo], 4), "date": lo.isoformat()}, "highest": {"value": round(index[hi], 4), "date": hi.isoformat()},
            "share_lower_pct": round(100 * sum(1 for d in days if index[d] < index[last]) / len(days))}


def _before(index: dict[date, float], last: date, days_back: int) -> dict | None:
    """The newest value on or before `days_back` calendar days before the last day, with its date and the change to now."""
    earlier = [d for d in index if d <= last - timedelta(days=days_back)]
    if not earlier:
        return None
    d = max(earlier)
    return {"date": d.isoformat(), "value": round(index[d], 4), "change": round(index[last] - index[d], 4)}


def summarize(index: dict, index_unit: dict, parts: dict, parts_units: dict, status: dict[str, str], today: date) -> dict:
    days, detail = _check(index, index_unit, parts, parts_units)
    last = days[-1]
    age = (today - last).days
    segments = sorted(({"id": sid, "label": name, "contribution": round(parts[sid][last], 4)} for sid, name in SEGMENTS), key=lambda s: -parts[s["id"]][last])
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "provisional": status.get(INDEX, "") not in ("", "A"),
            "index": round(index[last], 4), "week_ago": _before(index, last, 7), "month_ago": _before(index, last, 30), "window": _window(index, last),
            "segments": segments, "segments_total": round(sum(parts[sid][last] for sid, _ in SEGMENTS), 4), "correlation": round(parts[CORRELATION][last], 4),
            "detail": detail,
            "checks": {"units_ok": True, "days_in_a_row": True, "range_ok": True, "daily_move_ok": True, "segments_in_range_ok": True, "correlation_in_range_ok": True, "contributions_add_up_ok": True},
            "note": ("The ECB builds this index between 0 and 1 from five market segments (the bond market, the equity market, financial intermediaries, the foreign exchange market and the money market); a higher value means more stress. "
                     "The ECB also publishes how much each segment contributes and the contribution of the correlation between the segments, which has been negative on every day since 1999: the index is the five contributions plus that term. "
                     "The area is the euro area with its changing composition; a day arrives one business day later; the ECB's older CISS series ends on 2 May 2025 and is not used. "
                     "Checked: the units are the ones assumed, no hole of more than 5 days, the index lies between 0 and 1 and moves by no more than 0.25 in a day, each segment contributes between 0 and 1 and the correlation term lies between -1 and 0 (properties, not the ECB's own sum), "
                     "and one check that is the ECB's own arithmetic (the six contributions add up to the index), which shows the series belong together, not that the figures are right. "
                     "This describes stress that already happened: it is not a market signal or a forecast.")}


class EuroStress:
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
            return {**base, "available": False, "reason": "Demo mode: the real euro-area stress index is not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            index_text, parts_text = await asyncio.gather(self._get(c, INDEX_KEY, INDEX_LAST_N), self._get(c, PARTS_KEY, PARTS_LAST_N))
            index, i_unit, status = parse(index_text, "IDX", (INDEX,))
            parts, p_units, _ = parse(parts_text, "CON", PART_IDS)
            res = {**base, **summarize(index[INDEX], {INDEX: i_unit[INDEX]}, parts, p_units, status, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The euro-area stress index could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
