"""US industrial production: how much the nation's factories, mines and electric and gas utilities produced in a month, as an index with 2017 = 100, and how much of their capacity was in use, from the Board of Governors of the Federal Reserve System (release G.17) via FRED, the St. Louis Fed (public-domain US government data, citation requested). Free, no key.

How to read it: the headline (INDPRO) is an index of real output, the volume produced and not its value in dollars: 103.95 means output 3.95% above its 2017 average. It is built from three groups, all shown: manufacturing (IPMANSICS, the Board's SIC-based group; the NAICS-based IPMAN is a slightly different series and is not used), mining (IPMINE) and electric and gas utilities (IPUTIL). Capacity utilization (TCU) is output as a percent of the Board's estimate of the most the plants could sustainably produce. All are seasonally adjusted. Each monthly observation is dated the 1st and means the whole month. The newest month is an estimate published in the middle of the next month (September 2026 on 2026-10-16) and revised in later releases, so it is normally 45 to 77 days old by its date and carries it.
Checks, set from the whole real history (1,293 months, January 1919 to September 2026) before any test was written: each of the last 24 monthly levels of the four indexes is between 30 and 300 (the real total ranges from 3.69 to 104.10 and the last 24 months from 99 to 104, so a x10 or /10 slip is caught) and utilization between 40% and 100% (the real range since 1967 is 64.1% to 89.4%); the months follow each other without a gap and every series has all of them; no one-month change of the total under -30% or over +40% (the real extremes are -13.19% in April 2020 and +16.55% in May 1933) and none of a group under -60% or over +100% (the real extremes among them are -41.96% and +31.00%, both mining in 1922; a jump in utilization alone is caught by the capacity check below, so it has no move limit of its own); no year-on-year change of the total under -55% or over +90% (the real extremes are -33.66% in February 1946 and +62.04% in July 1933, so a real shock is never refused); the total's one-month change is never more than 0.02 percentage points outside the range of the changes of its three groups, which an average of them cannot be (the real record has no such month from May 1971 to September 2026, 665 months; the 76 before it, the last in April 1971 and the worst 0.66 points in November 1939, are why the check looks at the last 24 months only, and with the NAICS group in place of the SIC one there are four such months since 1972, by up to 0.059 points, which is how the right series was chosen); and the capacity implied by output and utilization (output divided by utilization) moves by between -0.5% and +1.0% a month (the real record since 1967 has -0.21% to +0.67%, and the last 24 months +0.08% to +0.12%). Utilization is output divided by capacity by definition, so the last check shows that the two series are for the same months and agree, not that either is right. A month missing from one series, or a series that ends in another month, is refused. A missing value is left out, never filled in.
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
from .moneysupply import _growth, _label, _months_back

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "Board of Governors of the Federal Reserve System, Industrial Production and Capacity Utilization (G.17), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/INDPRO"
SERIES = {"INDPRO": "industrial production", "IPMANSICS": "manufacturing", "IPMINE": "mining", "IPUTIL": "electric and gas utilities", "TCU": "capacity utilization"}
INDEXES = ("INDPRO", "IPMANSICS", "IPMINE", "IPUTIL")
GROUPS = ("IPMANSICS", "IPMINE", "IPUTIL")
LIMITS = (30.0, 300.0)                # index, 2017 = 100; the real total has been 3.69 to 104.10 (a x10 or /10 slip is caught)
UTIL_LIMITS = (40.0, 100.0)           # percent of capacity; the real range since 1967 is 64.1 to 89.4
CHECK_MONTHS = 24
MONTH_MOVE = (-0.30, 0.40)            # total, one month; the real extremes are -13.19% and +16.55%
GROUP_MOVE = (-0.60, 1.00)            # each group, one month; the real extremes among them are -41.96% and +31.00%
YOY_LIMITS = (-0.55, 0.90)            # total, over a year; the real extremes are -33.66% and +62.04%
BETWEEN_TOLERANCE = 0.02              # percentage points; the real record has no month outside the groups' range since May 1971
CAPACITY_MOVE = (-0.005, 0.010)       # implied capacity, one month; the real range since 1967 is -0.21% to +0.67%
HISTORY_MONTHS = 36
OVERDUE_AFTER_DAYS = 90               # from the 1st of the observed month: the next month normally arrives 77 days after the 1st at the latest
TTL = 6 * 3600.0
FAIL_TTL = 120.0
LOOKBACK_DAYS = 4200                  # about 11.5 years: enough for 120 months of year-on-year growth


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    if len({max(s) for s in data.values()}) != 1:
        raise ValueError("the industrial production series end in different months")
    tot = data["INDPRO"]
    months = sorted(tot)
    recent = months[-CHECK_MONTHS:]
    if any(d.day != 1 for d in recent):
        raise ValueError("an industrial production date is not the 1st of a month")
    if any(_months_back(b, 1) != a for a, b in zip(recent, recent[1:])):
        raise ValueError(f"the industrial production values skip a month in the last {CHECK_MONTHS}")
    for sid, s in data.items():
        for d in recent:
            if d not in s:
                raise ValueError(f"{SERIES[sid]} is missing for {_label(d)}")
    if any(not (LIMITS[0] <= data[sid][d] <= LIMITS[1]) for sid in INDEXES for d in recent):
        raise ValueError("an industrial production index is outside the plausible range")
    if any(not (UTIL_LIMITS[0] <= data["TCU"][d] <= UTIL_LIMITS[1]) for d in recent):
        raise ValueError("capacity utilization is outside the plausible range")
    pairs = list(zip(recent, recent[1:]))
    for a, b in pairs:
        ch = tot[b] / tot[a] - 1
        if not (MONTH_MOVE[0] <= ch <= MONTH_MOVE[1]):
            raise ValueError(f"industrial production changed by {ch:.1%} in {_label(b)}, outside {MONTH_MOVE[0]:.0%} to {MONTH_MOVE[1]:+.0%}")
    for sid in GROUPS:
        for a, b in pairs:
            ch = data[sid][b] / data[sid][a] - 1
            if not (GROUP_MOVE[0] <= ch <= GROUP_MOVE[1]):
                raise ValueError(f"{SERIES[sid]} changed by {ch:.1%} in {_label(b)}, outside {GROUP_MOVE[0]:.0%} to {GROUP_MOVE[1]:+.0%}")
    for d in recent:
        ago = tot.get(_months_back(d, 12))
        if ago is not None and not (YOY_LIMITS[0] <= tot[d] / ago - 1 <= YOY_LIMITS[1]):
            raise ValueError(f"industrial production changed by {tot[d] / ago - 1:.1%} over the year to {_label(d)}, outside {YOY_LIMITS[0]:.0%} to {YOY_LIMITS[1]:+.0%}")
    worst = 0.0
    for a, b in pairs:
        dt = 100 * (tot[b] / tot[a] - 1)
        dg = [100 * (data[sid][b] / data[sid][a] - 1) for sid in GROUPS]
        miss = max(min(dg) - dt, dt - max(dg))
        if miss > BETWEEN_TOLERANCE:
            raise ValueError(f"industrial production changed by {dt:+.2f}% in {_label(b)} while manufacturing, mining and utilities moved between {min(dg):+.2f}% and {max(dg):+.2f}%")
        worst = max(worst, miss)
    caps = []
    for a, b in pairs:
        ch = (tot[b] / data["TCU"][b]) / (tot[a] / data["TCU"][a]) - 1
        if not (CAPACITY_MOVE[0] <= ch <= CAPACITY_MOVE[1]):
            raise ValueError(f"the capacity implied by output and utilization changed by {ch:.2%} in {_label(b)}, outside {CAPACITY_MOVE[0]:.1%} to {CAPACITY_MOVE[1]:+.1%}")
        caps.append(100 * ch)
    last = months[-1]
    return months, {"months_checked": len(recent), "changes_checked": len(pairs), "largest_miss_points": round(worst, 3),
                    "capacity_change_pct": {"smallest": round(min(caps), 2), "largest": round(max(caps), 2)},
                    "newest": {"month": _label(last), "total_change_pct": round(100 * (tot[last] / tot[_months_back(last, 1)] - 1), 2)}}


def _group(s: dict[date, float], last: date) -> dict:
    v = s[last]
    return {"level": round(v, 2), "change_1m_pct": _pct(v, s.get(_months_back(last, 1))), "change_1y_pct": _pct(v, s.get(_months_back(last, 12)))}


def _points(u: float, then: float | None) -> float | None:
    return None if then is None else round(u - then, 1)


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    tot, util = data["INDPRO"], data["TCU"]
    months, detail = _check(data)
    last = months[-1]
    v, u = tot[last], util[last]
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "level": round(v, 2), "change_1m_pct": _pct(v, tot.get(_months_back(last, 1))), "change_3m_pct": _pct(v, tot.get(_months_back(last, 3))), "change_1y_pct": _pct(v, tot.get(_months_back(last, 12))),
            "manufacturing": _group(data["IPMANSICS"], last), "mining": _group(data["IPMINE"], last), "utilities": _group(data["IPUTIL"], last),
            "capacity": {"utilization_pct": round(u, 1), "change_1m_points": _points(u, util.get(_months_back(last, 1))), "change_1y_points": _points(u, util.get(_months_back(last, 12)))},
            "growth": _growth(tot, last), "detail": detail,
            "history": [{"date": d.isoformat(), "level": round(tot[d], 2)} for d in months[-HISTORY_MONTHS:]],
            "checks": {"range_ok": True, "months_in_a_row": True, "monthly_move_ok": True, "yearly_change_ok": True, "between_groups_ok": True, "capacity_ok": True},
            "note": ("Industrial production is an index of the real output, the volume and not the value, of US factories, mines and electric and gas utilities, with 2017 = 100: 104 means output 4% above its 2017 average. "
                     "Capacity utilization is output as a percent of the Board's estimate of the most the plants could sustainably produce. Both are seasonally adjusted. "
                     "The newest month is an estimate that is revised in later releases; each figure carries its month. "
                     "Checked: every recent index is between 30 and 300 and utilization between 40% and 100% with no month missing, no month moved by more than the real record allows, "
                     "the total's monthly change lies between those of manufacturing, mining and utilities (as an average of them must, and as it has in every month since May 1971), "
                     "and the capacity implied by output and utilization moves slowly, as capacity does. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class IndustrialProduction:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast. cosd keeps the download to about 11 years.
        r = await c.get(URL, params={"id": sid, "cosd": (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real industrial production figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Industrial production could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
