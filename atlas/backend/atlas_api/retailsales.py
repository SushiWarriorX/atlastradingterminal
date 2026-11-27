"""US retail and food services sales: what American shops, online stores, restaurants and bars sold, monthly, in billions of dollars, from the Census Bureau's Advance Monthly Retail Trade Survey via FRED, the St. Louis Fed (public-domain US government data, citation requested). Free, no key.

How to read it: the headline is the seasonally adjusted total (RSAFS) and its growth over a year, split into retail trade (RSXFS) and food services and drinking places (RSFSDP). Each monthly observation is dated the 1st and means the whole month. The newest month is an ADVANCE estimate from a sample of firms, published about the middle of the next month, and it is revised in the following release, so the newest month is normally 45 to 78 days old by its date and carries it. The dollars are not adjusted for price changes.
Checks, set from the whole real history (417 months, January 1992 to September 2026) before any test was written: each of the last 24 monthly totals is between 100,000 and 2,000,000 million dollars (the real range is 158,647 to 745,021) and the months follow each other without a gap; no one-month change under -25% or over +30% (the real extremes are -14.18% in April 2020 and +19.42% in May 2020); no year-on-year growth under -30% or over +60% (the real extremes are -19.51% in April 2020 and +51.49% in April 2021, so a real shock is never refused); and for each of the last 24 months retail trade plus food services equals the total to within 1 million dollars (the real difference is exactly 0 in all 417 months), with food services between 5% and 20% of the total (the real range is 7.40% to 12.66%, so swapped parts are caught). A month missing from one series, or a series that ends in another month, is refused. A missing value is left out, never filled in.
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
SOURCE = "U.S. Census Bureau, Advance Monthly Retail Trade Survey, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/RSAFS"
SERIES = {"RSAFS": "retail and food services, total", "RSXFS": "retail trade", "RSFSDP": "food services and drinking places"}
LIMITS = (100_000.0, 2_000_000.0)    # millions of dollars; the real range is 158,647 to 745,021 (a x10 or /10 slip is caught)
CHECK_MONTHS = 24
MONTH_MOVE = (-0.25, 0.30)           # one-month change; the real extremes are -14.18% and +19.42%
YOY_LIMITS = (-0.30, 0.60)           # year-on-year growth; the real extremes are -19.51% and +51.49%
SUM_TOLERANCE = 1.0                  # millions of dollars: retail trade + food services - total; the real difference is exactly 0 in every month
FOOD_SHARE = (0.05, 0.20)            # food services as a share of the total; the real range is 7.40% to 12.66%
HISTORY_MONTHS = 36
OVERDUE_AFTER_DAYS = 90              # from the 1st of the observed month: the next month normally arrives about 75 to 78 days after it
TTL = 6 * 3600.0
FAIL_TTL = 120.0
LOOKBACK_DAYS = 4200                 # about 11.5 years: enough for 120 months of year-on-year growth


def _check(sa: dict[date, float], rx: dict[date, float], fs: dict[date, float]) -> tuple[list[date], dict]:
    if not (max(sa) == max(rx) == max(fs)):
        raise ValueError("the three retail sales series end in different months")
    months = sorted(sa)
    recent = months[-CHECK_MONTHS:]
    if any(d.day != 1 for d in recent):
        raise ValueError("a retail sales date is not the 1st of a month")
    if any(not (LIMITS[0] <= sa[d] <= LIMITS[1]) for d in recent):
        raise ValueError("a retail sales value is outside the plausible range")
    if any(_months_back(b, 1) != a for a, b in zip(recent, recent[1:])):
        raise ValueError(f"the retail sales values skip a month in the last {CHECK_MONTHS}")
    for a, b in zip(recent, recent[1:]):
        ch = sa[b] / sa[a] - 1
        if not (MONTH_MOVE[0] <= ch <= MONTH_MOVE[1]):
            raise ValueError(f"retail sales changed by {ch:.1%} in {_label(b)}, outside {MONTH_MOVE[0]:.0%} to {MONTH_MOVE[1]:+.0%}")
    for d in recent:
        ago = sa.get(_months_back(d, 12))
        if ago is not None and not (YOY_LIMITS[0] <= sa[d] / ago - 1 <= YOY_LIMITS[1]):
            raise ValueError(f"retail sales grew {sa[d] / ago - 1:.1%} over the year to {_label(d)}, outside {YOY_LIMITS[0]:.0%} to {YOY_LIMITS[1]:+.0%}")
    worst = 0.0
    for d in recent:
        if d not in rx or d not in fs:
            raise ValueError(f"retail trade or food services is missing for {_label(d)}")
        diff = rx[d] + fs[d] - sa[d]
        if abs(diff) > SUM_TOLERANCE:
            raise ValueError(f"retail trade plus food services is {diff:+,.1f} million dollars away from the total in {_label(d)}")
        if not (FOOD_SHARE[0] <= fs[d] / sa[d] <= FOOD_SHARE[1]):
            raise ValueError(f"food services are {fs[d] / sa[d]:.1%} of retail sales in {_label(d)}, outside {FOOD_SHARE[0]:.0%} to {FOOD_SHARE[1]:.0%}")
        worst = max(worst, abs(diff))
    last = months[-1]
    return months, {"months_checked": len(recent), "max_difference_millions": round(worst, 3),
                    "newest": {"month": _label(last), "retail_millions": rx[last], "food_millions": fs[last], "total_millions": sa[last], "difference_millions": round(rx[last] + fs[last] - sa[last], 3)}}


def _part(s: dict[date, float], total: dict[date, float], last: date) -> dict:
    v = s[last]
    return {"level_billions": round(v / 1000, 1), "share_pct": round(100 * v / total[last], 1), "change_1m_pct": _pct(v, s.get(_months_back(last, 1))), "change_1y_pct": _pct(v, s.get(_months_back(last, 12)))}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    sa, rx, fs = data["RSAFS"], data["RSXFS"], data["RSFSDP"]
    months, sums = _check(sa, rx, fs)
    last = months[-1]
    v = sa[last]
    age = (today - last).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "level_billions": round(v / 1000, 1), "change_1m_pct": _pct(v, sa.get(_months_back(last, 1))), "change_3m_pct": _pct(v, sa.get(_months_back(last, 3))), "change_1y_pct": _pct(v, sa.get(_months_back(last, 12))),
            "retail": _part(rx, sa, last), "food": _part(fs, sa, last), "growth": _growth(sa, last), "sums": sums,
            "history": [{"date": d.isoformat(), "level": round(sa[d] / 1000, 1)} for d in months[-HISTORY_MONTHS:]],
            "checks": {"range_ok": True, "months_in_a_row": True, "monthly_move_ok": True, "yearly_growth_ok": True, "parts_add_up": True, "food_share_ok": True},
            "note": ("Retail and food services sales are what American shops, online stores, restaurants and bars sold in a month, in billions of dollars, seasonally adjusted. They are NOT adjusted for price changes, so a rise can come from higher prices and not from more goods sold. "
                     "The newest month is an advance estimate from a sample of firms, published about the middle of the next month and revised in the following release; each figure carries its month. "
                     "Checked: every recent monthly total is between $100 billion and $2 trillion with no month missing, no month moved by more than the real record allows, and in each of the last 24 months retail trade plus food services adds up to the total. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class RetailSales:
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
            return {**base, "available": False, "reason": "Demo mode: the real retail sales figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Retail sales could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
