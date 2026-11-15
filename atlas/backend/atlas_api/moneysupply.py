"""M2 money supply: the broad measure of money the public holds (cash, deposits, small time deposits and retail money market funds), monthly, in billions of dollars, from the Federal Reserve Board's H.6 release via FRED, the St. Louis Fed (public-domain US government data). Free, no key.

How to read it: the headline is the seasonally adjusted monthly level (M2SL) and its growth over a year. Each monthly observation is dated the 1st and means the whole month. The figures reach FRED a few weeks after the month ends and are revised later, so the newest month is normally 45 to 80 days old by its date and carries it. Two other H.6 series are used only to check it: the same money unadjusted for the season (M2NS) and the weekly unadjusted figures (WM2NS, "weekly, ending Monday", dated the Monday).
Checks, set from the real history before any test was written: each of the last 24 monthly values is between 5,000 and 60,000 billion (the real range since 2015 is 11,806 to 23,414) and the months follow each other without a gap; no one-month change under -5% or over +10% (the real extremes since 2015 are -1.45% and +6.42%, April 2020); no year-on-year growth under -10% or over +30% (the real extremes since 1960 are -4.7% in April 2023 and +26.8% in February 2021, so a real shock is never refused); for each of the last 12 months, adjusted and unadjusted M2 differ by no more than 2% (the real range since 2015 is -0.6% to +0.7%); the last 26 weekly dates are 7 days apart; and for each of the last 6 months with all its weekly figures, their average is within 1% of the unadjusted monthly figure (the real largest difference since 2010 is 0.64%, March 2020), with at least 3 such months. A missing value is left out, never filled in.
It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import httpx

from .claims import _pct
from .failreason import fail_reason
from .fincond import parse

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "Federal Reserve Board money stock (H.6 release), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/M2SL"
SERIES = {"M2SL": "monthly, adjusted", "M2NS": "monthly, unadjusted", "WM2NS": "weekly, unadjusted"}
LIMITS = (5_000.0, 60_000.0)         # billions of dollars; the real range since 2015 is 11,806 to 23,414 (a x10 or /10 slip is caught)
CHECK_MONTHS = 24
MONTH_MOVE = (-0.05, 0.10)           # one-month change; the real extremes since 2015 are -1.45% and +6.42%
YOY_LIMITS = (-0.10, 0.30)           # year-on-year growth; the real extremes since 1960 are -4.7% and +26.8%
SEASONAL_MONTHS = 12
SEASONAL_BAND = 0.02                 # |adjusted / unadjusted - 1|; the real range since 2015 is -0.6% to +0.7%
WEEKLY_CHECK_WEEKS = 26
WEEKLY_MONTHS = 6
MIN_WEEKLY_MONTHS = 3
WEEKLY_BAND = 0.01                   # |average of a month's weekly figures / the unadjusted monthly figure - 1|; the real largest since 2010 is 0.643%
HISTORY_MONTHS = 120                 # the ten years the growth is put against
MIN_GROWTH_MONTHS = 60
OVERDUE_AFTER_DAYS = 100             # from the 1st of the observed month: the next month normally arrives about 47 days after its own 1st
TTL = 6 * 3600.0
FAIL_TTL = 120.0
LOOKBACK_DAYS = 4200                 # about 11.5 years: enough for 120 months of year-on-year growth


def _months_back(d: date, n: int) -> date:
    y, m = d.year, d.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def _label(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _check_monthly(m: dict[date, float]) -> list[date]:
    months = sorted(m)
    if any(d.day != 1 for d in months[-CHECK_MONTHS:]):
        raise ValueError("a monthly M2 date is not the 1st of a month")
    recent = months[-CHECK_MONTHS:]
    if any(not (LIMITS[0] <= m[d] <= LIMITS[1]) for d in recent):
        raise ValueError("a monthly M2 value is outside the plausible range")
    if any(_months_back(b, 1) != a for a, b in zip(recent, recent[1:])):
        raise ValueError(f"the monthly M2 values skip a month in the last {CHECK_MONTHS}")
    for a, b in zip(recent, recent[1:]):
        ch = m[b] / m[a] - 1
        if not (MONTH_MOVE[0] <= ch <= MONTH_MOVE[1]):
            raise ValueError(f"M2 changed by {ch:.1%} in {_label(b)}, outside {MONTH_MOVE[0]:.0%} to {MONTH_MOVE[1]:+.0%}")
    for d in recent:
        ago = m.get(_months_back(d, 12))
        if ago is not None and not (YOY_LIMITS[0] <= m[d] / ago - 1 <= YOY_LIMITS[1]):
            raise ValueError(f"M2 grew {m[d] / ago - 1:.1%} over the year to {_label(d)}, outside {YOY_LIMITS[0]:.0%} to {YOY_LIMITS[1]:+.0%}")
    return months


def _check_seasonal(sa: dict[date, float], ns: dict[date, float]) -> dict:
    both = [d for d in sorted(sa) if d in ns][-SEASONAL_MONTHS:]
    if len(both) < SEASONAL_MONTHS // 2:
        raise ValueError("adjusted and unadjusted M2 cannot be compared")
    for d in both:
        if abs(sa[d] / ns[d] - 1) > SEASONAL_BAND:
            raise ValueError(f"adjusted and unadjusted M2 differ by {sa[d] / ns[d] - 1:.1%} in {_label(d)}, more than {SEASONAL_BAND:.0%}")
    d = both[-1]
    return {"month": _label(d), "adjusted": round(sa[d], 1), "unadjusted": round(ns[d], 1), "pct": _pct(sa[d], ns[d])}


def _check_weekly(ns: dict[date, float], wk: dict[date, float]) -> dict:
    weeks = sorted(wk)[-WEEKLY_CHECK_WEEKS:]
    if any((b - a).days != 7 for a, b in zip(weeks, weeks[1:])):
        raise ValueError("the weekly M2 dates are not 7 days apart")
    by_month: dict[tuple[int, int], list[float]] = defaultdict(list)
    for d, v in wk.items():
        by_month[(d.year, d.month)].append(v)
    rows = []
    for d in sorted(ns, reverse=True)[: WEEKLY_MONTHS + 3]:
        vals = by_month.get((d.year, d.month), [])
        if len(vals) < 4:
            continue                                                         # a month has at least four Mondays: fewer means the weekly data stop inside it
        avg = sum(vals) / len(vals)
        if abs(avg / ns[d] - 1) > WEEKLY_BAND:
            raise ValueError(f"the weekly figures for {_label(d)} average {avg:.0f} but the monthly figure is {ns[d]:.0f}")
        rows.append({"month": _label(d), "weeks": len(vals), "average": round(avg, 1), "unadjusted": round(ns[d], 1), "diff_pct": round((avg / ns[d] - 1) * 100, 2)})
        if len(rows) == WEEKLY_MONTHS:
            break
    if len(rows) < MIN_WEEKLY_MONTHS:
        raise ValueError(f"fewer than {MIN_WEEKLY_MONTHS} months can be compared with the weekly figures")
    return {"newest": rows[0], "months_compared": len(rows)}


def _growth(m: dict[date, float], last: date) -> dict | None:
    yoy = {d: m[d] / m[_months_back(d, 12)] - 1 for d in sorted(m) if d <= last and _months_back(d, 12) in m}
    window = sorted(yoy)[-HISTORY_MONTHS:]
    if len(window) < MIN_GROWTH_MONTHS or last not in yoy:
        return None
    vals = [yoy[d] for d in window]
    lo, hi = min(window, key=lambda d: yoy[d]), max(window, key=lambda d: yoy[d])
    return {"months": len(window), "slowest": {"pct": round(yoy[lo] * 100, 1), "month": _label(lo)}, "fastest": {"pct": round(yoy[hi] * 100, 1), "month": _label(hi)},
            "share_slower_pct": round(100 * sum(1 for x in vals if x < yoy[last]) / len(vals))}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    sa, ns, wk = data["M2SL"], data["M2NS"], data["WM2NS"]
    months = _check_monthly(sa)
    seasonal = _check_seasonal(sa, ns)
    weekly = _check_weekly(ns, wk)
    last = months[-1]
    v = sa[last]
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "level_billions": round(v, 1), "change_1m_pct": _pct(v, sa.get(_months_back(last, 1))), "change_3m_pct": _pct(v, sa.get(_months_back(last, 3))), "change_1y_pct": _pct(v, sa.get(_months_back(last, 12))),
            "growth": _growth(sa, last), "seasonal": seasonal, "weekly": weekly,
            "history": [{"date": d.isoformat(), "level": round(sa[d], 1)} for d in months[-36:]],
            "checks": {"range_ok": True, "months_in_a_row": True, "monthly_move_ok": True, "yearly_growth_ok": True, "seasonal_factor_ok": True, "weekly_matches_monthly": True},
            "note": ("M2 is a broad measure of the money the public holds: cash, bank deposits, small time deposits and retail money market funds. The data are in billions of dollars and shown here in trillions for the seasonally adjusted monthly level. "
                     "The figures come from the Federal Reserve Board and reach FRED a few weeks after the month ends, and they are revised later, so each carries its month. "
                     "Checked: every recent monthly value is between $5 trillion and $60 trillion with no month missing, no month moved by more than the real record allows, adjusted and unadjusted M2 agree to within 2%, and the weekly figures average out to the monthly one for each of the last months (within 1%). "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class MoneySupply:
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
            return {**base, "available": False, "reason": "Demo mode: the real money supply figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The money supply could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
