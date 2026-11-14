"""US weekly jobless claims: INITIAL claims (people filing for unemployment insurance for the first time in the week) and CONTINUING claims (people still receiving it), seasonally adjusted, published every Thursday by the US Department of Labor. Free public data from FRED (the St. Louis Fed), no key.

How to read it: fewer initial claims mean fewer people newly laid off, more mean more. Continuing claims run one week behind. The Department of Labor also publishes a four-week average (FRED IC4WSA), which is used as a cross-check, not as the headline.
Checks: every date is a Saturday (the week's end), the last weeks are spaced one week apart, every value is in a plausible range, our four-week average of the last four weeks matches the Labor Department's own for the latest week (within 1%), and continuing claims are for a recent week. A missing value ('.') is left out, never filled in.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .fincond import parse

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "US Department of Labor weekly unemployment insurance claims, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/ICSA"
SERIES = {"ICSA": "initial", "CCSA": "continuing", "IC4WSA": "four_week_average"}
LIMITS = {"ICSA": (100_000, 7_000_000), "CCSA": (500_000, 30_000_000), "IC4WSA": (100_000, 7_000_000)}      # the record is 6.1 million (March 2020); a value outside is a bad reading
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 14          # published Thursdays for the week that ended the Saturday before, so normally 5 to 11 days old
AVG_TOLERANCE = 0.01
WEEK = 7


def reading(rank: int) -> str:
    """Where the latest week sits among the past year's weeks (rank = percent of those weeks at or below it): plain words, no judgement about good or bad."""
    return "toward the low end of the past year's range" if rank <= 25 else "toward the high end of the past year's range" if rank >= 75 else "in the middle of the past year's range"


def _pct(new: float, old: float | None) -> float | None:
    return None if not old else round(100.0 * (new - old) / old, 1)


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    ic, cc, ma = data["ICSA"], data["CCSA"], data["IC4WSA"]
    for sid, s in data.items():
        if any(d.weekday() != 5 for d in s):
            raise ValueError(f"{sid} has a date that is not a Saturday")
        lo, hi = LIMITS[sid]
        if any(not (lo <= s[d] <= hi) for d in sorted(s)[-60:]):
            raise ValueError(f"{sid} has a value outside the plausible range")
    weeks = sorted(ic)
    last = weeks[-1]
    if any((b - a).days != WEEK for a, b in zip(weeks[-12:], weeks[-11:])):
        raise ValueError("the last weeks are not one week apart")
    if last not in ma:
        raise ValueError("the Labor Department's four-week average is missing for the latest week")
    avg4 = sum(ic[d] for d in weeks[-4:]) / 4
    if abs(avg4 - ma[last]) > AVG_TOLERANCE * ma[last]:
        raise ValueError("our four-week average does not match the Labor Department's")
    last_c = max(cc)
    if not 0 <= (last - last_c).days <= 2 * WEEK:
        raise ValueError("continuing claims are not for a recent week")
    v = ic[last]
    year = [d for d in weeks if 0 <= (last - d).days <= 52 * WEEK]
    vals = [ic[d] for d in year]
    rank = round(100 * sum(1 for x in vals if x <= v) / len(vals))
    prev, yago = ic.get(last - timedelta(days=WEEK)), ic.get(last - timedelta(days=52 * WEEK))
    cprev, cyago = cc.get(last_c - timedelta(days=WEEK)), cc.get(last_c - timedelta(days=52 * WEEK))
    age = (today - last).days
    return {"available": True, "date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "source": SOURCE, "url": PAGE,
            "initial": {"value": int(v), "avg4": round(avg4), "avg4_official": int(ma[last]), "change_1w": None if prev is None else int(v - prev), "change_1y_pct": _pct(v, yago),
                        "year_low": int(min(vals)), "year_high": int(max(vals)), "weeks_in_year": len(vals), "rank_in_year": rank},
            "continuing": {"value": int(cc[last_c]), "date": last_c.isoformat(), "change_1w": None if cprev is None else int(cc[last_c] - cprev), "change_1y_pct": _pct(cc[last_c], cyago)},
            "reading": reading(rank),
            "history": [{"date": d.isoformat(), "initial": int(ic[d])} for d in weeks[-52:]],
            "checks": {"saturdays_ok": True, "weekly_spacing_ok": True, "range_ok": True, "four_week_average_matches_official": True, "continuing_recent": True},
            "note": ("Initial claims count people filing for unemployment insurance for the first time in the week ending on the date shown (seasonally adjusted, published Thursdays by the US Department of Labor): fewer means fewer new layoffs, more means more. "
                     "Continuing claims count people still receiving benefits and run one week behind. "
                     "Checked: every date is a Saturday, the last weeks are one week apart, every value is in a plausible range, our four-week average matches the Labor Department's own, and continuing claims are for a recent week. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class JoblessClaims:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _one(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast. cosd keeps the download to about two years.
        r = await c.get(URL, params={"id": sid, "cosd": (date.today() - timedelta(days=800)).isoformat()})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real jobless claims data is not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._one(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Jobless claims could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
