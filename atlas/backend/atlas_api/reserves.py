"""Bank reserves, currency and the monetary base: the balances banks hold at the Federal Reserve (reserve balances), the cash in circulation (currency) and their sum (the monetary base), from the Federal Reserve Board's H.4.1 (weekly) and H.6 (monthly) releases via FRED, the St. Louis Fed (public-domain US government data). Free, no key.

How to read it: the weekly series (week averages, "weekly, ending Wednesday", in MILLIONS of dollars) are the freshest and carry the headline; the monthly series (in BILLIONS, dated the 1st for the whole month) give the official monetary base and its two parts. FRED's note on the base says what it is: "the monetary base equals currency in circulation plus reserve balances", which is an accounting identity the monthly numbers must satisfy. Both are shown in trillions.
Checks, set from the real history before any test was written: the last 52 weekly dates are Wednesdays exactly 7 days apart and the two weekly series cover the same dates; each weekly value is in range (reserves 0.5 to 12 trillion, the real range since 2015 is 1.39 to 4.28; currency 0.5 to 8 trillion, the real range 1.33 to 2.49) and no one-week move is outside -30% to +50% for reserves (the real extremes since 2015 are -8.8% and +15.9%, April 2020) or -5% to +10% for currency (the real extremes -0.6% and +1.8%); the last 24 monthly dates are the 1st, follow each other without a gap, and the three monthly series cover the same months, with the base moving no more than -15% to +40% in a month (the real extremes since 2008 are -8.8% and +26.9%) and currency -5% to +10% (the real extremes -0.3% and +2.9%); a monthly range check was left out on purpose, because the weekly ranges, these moves, the identity and the weekly comparison already cover every way it could fail and none of them could be tested apart; for each of the last 12 months the base equals currency plus reserves to within 0.5 billion (the real largest gap since 2008 is 0.1, rounding); and, for each of the last 6 months with at least four weekly figures (at least 3 such months), the weekly currency plus reserves average within 10% of the monthly base (the real largest difference since 2012 is 4.5%, March 2020, and since 2022 it is 0.77%). A missing value is left out, never filled in.
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
from .moneysupply import _label, _months_back

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "Federal Reserve Board H.4.1 (weekly) and H.6 (monthly) releases, via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/WRESBAL"
SERIES = {"WRESBAL": "weekly reserve balances (millions)", "WCURCIR": "weekly currency in circulation (millions)", "BOGMBASE": "monthly monetary base (billions)",
          "MBCURRCIR": "monthly currency in circulation (billions)", "BOGMBBM": "monthly reserve balances (billions)"}
CHECK_WEEKS = 52
WEEK_RES_LIMITS = (500_000.0, 12_000_000.0)      # millions of dollars; the real range since 2015 is 1.39 to 4.28 million million
WEEK_CUR_LIMITS = (500_000.0, 8_000_000.0)       # millions; the real range since 2015 is 1.33 to 2.49 million million
WEEK_RES_MOVE = (-0.30, 0.50)                    # one week; the real extremes since 2015 are -8.8% and +15.9%
WEEK_CUR_MOVE = (-0.05, 0.10)                    # one week; the real extremes since 2015 are -0.6% and +1.8%
CHECK_MONTHS = 24
BASE_MOVE = (-0.15, 0.40)                        # one month; the real extremes since 2008 are -8.8% and +26.9% (April 2020: +24.8%)
CUR_MOVE = (-0.05, 0.10)                         # one month
IDENTITY_MONTHS = 12
IDENTITY_TOLERANCE = 0.5                         # billions; the real largest gap since 2008 is 0.1 (rounding of three one-decimal figures)
CROSS_MONTHS = 6
MIN_CROSS_MONTHS = 3
CROSS_BAND = 0.10                                # the real largest difference since 2012 is 4.5% (March 2020), since 2022 0.77%
OVERDUE_WEEKLY_DAYS = 14
OVERDUE_MONTHLY_DAYS = 100
TTL = 6 * 3600.0
FAIL_TTL = 120.0
LOOKBACK_DAYS = 800                              # about 26 months: 24 monthly values, a year-ago figure, 52 weeks and a year-ago week


def _in(limits: tuple[float, float], v: float) -> bool:
    return limits[0] <= v <= limits[1]


def _check_weekly(res: dict[date, float], cur: dict[date, float]) -> list[date]:
    weeks = sorted(res)[-CHECK_WEEKS:]
    if any(d.weekday() != 2 for d in weeks):
        raise ValueError("a weekly reserves date is not a Wednesday")
    if any((b - a).days != 7 for a, b in zip(weeks, weeks[1:])):
        raise ValueError(f"the weekly reserves dates are not 7 days apart in the last {CHECK_WEEKS} weeks")
    if any(d not in cur for d in weeks):
        raise ValueError("the weekly currency figures do not cover the same weeks as the weekly reserves")
    if any(not _in(WEEK_RES_LIMITS, res[d]) for d in weeks) or any(not _in(WEEK_CUR_LIMITS, cur[d]) for d in weeks):
        raise ValueError("a weekly value is outside the plausible range")
    for a, b in zip(weeks, weeks[1:]):
        r, c = res[b] / res[a] - 1, cur[b] / cur[a] - 1
        if not _in(WEEK_RES_MOVE, r):
            raise ValueError(f"reserves changed by {r:.1%} in the week of {b.isoformat()}, outside {WEEK_RES_MOVE[0]:.0%} to {WEEK_RES_MOVE[1]:+.0%}")
        if not _in(WEEK_CUR_MOVE, c):
            raise ValueError(f"currency changed by {c:.1%} in the week of {b.isoformat()}, outside {WEEK_CUR_MOVE[0]:.0%} to {WEEK_CUR_MOVE[1]:+.0%}")
    return weeks


def _check_monthly(base: dict[date, float], mcur: dict[date, float], mres: dict[date, float]) -> list[date]:
    months = sorted(base)[-CHECK_MONTHS:]
    if any(d.day != 1 for d in months):
        raise ValueError("a monthly date is not the 1st of a month")
    if any(_months_back(b, 1) != a for a, b in zip(months, months[1:])):
        raise ValueError(f"the monthly values skip a month in the last {CHECK_MONTHS}")
    if any(d not in mcur or d not in mres for d in months):
        raise ValueError("the three monthly series do not cover the same months")
    for a, b in zip(months, months[1:]):
        for name, s, lim in (("the monetary base", base, BASE_MOVE), ("currency", mcur, CUR_MOVE)):
            ch = s[b] / s[a] - 1
            if not _in(lim, ch):
                raise ValueError(f"{name} changed by {ch:.1%} in {_label(b)}, outside {lim[0]:.0%} to {lim[1]:+.0%}")
    for d in months[-IDENTITY_MONTHS:]:
        gap = base[d] - (mcur[d] + mres[d])
        if abs(gap) > IDENTITY_TOLERANCE:
            raise ValueError(f"the monetary base is {gap:+.1f} billion away from currency plus reserve balances in {_label(d)}")
    return months


def _cross_check(base: dict[date, float], res: dict[date, float], cur: dict[date, float]) -> dict:
    by_month: dict[tuple[int, int], list[float]] = defaultdict(list)
    for d in res:
        if d in cur:
            by_month[(d.year, d.month)].append((res[d] + cur[d]) / 1000.0)         # millions to billions
    rows = []
    for d in sorted(base, reverse=True)[: CROSS_MONTHS + 3]:
        vals = by_month.get((d.year, d.month), [])
        if len(vals) < 4:
            continue                                                         # a month has at least four Wednesdays: fewer means the weekly data stop inside it
        avg = sum(vals) / len(vals)
        if abs(avg / base[d] - 1) > CROSS_BAND:
            raise ValueError(f"the weekly figures for {_label(d)} add up to an average of {avg:.0f} billion but the monthly base is {base[d]:.0f}")
        rows.append({"month": _label(d), "weeks": len(vals), "weekly_average_billions": round(avg, 1), "monthly_base_billions": round(base[d], 1), "diff_pct": round((avg / base[d] - 1) * 100, 2)})
        if len(rows) == CROSS_MONTHS:
            break
    if len(rows) < MIN_CROSS_MONTHS:
        raise ValueError(f"fewer than {MIN_CROSS_MONTHS} months can be compared with the weekly figures")
    return {"newest": rows[0], "months_compared": len(rows)}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    res, cur = data["WRESBAL"], data["WCURCIR"]
    base, mcur, mres = data["BOGMBASE"], data["MBCURRCIR"], data["BOGMBBM"]
    weeks = _check_weekly(res, cur)
    months = _check_monthly(base, mcur, mres)
    cross = _cross_check(base, res, cur)
    last, lm = weeks[-1], months[-1]
    year = [d for d in sorted(res) if 0 <= (last - d).days <= 52 * 7]
    yv = [res[d] for d in year]
    rank = round(100 * sum(1 for x in yv if x <= res[last]) / len(yv))
    wage, mage = (today - last).days, (today - lm).days
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "age_days": wage, "freshness": "CURRENT" if wage <= OVERDUE_WEEKLY_DAYS else "OVERDUE",
            "weekly": {"date": last.isoformat(), "reserves_millions": round(res[last], 0), "currency_millions": round(cur[last], 0),
                       "reserves_change_1w_pct": _pct(res[last], res.get(last - timedelta(days=7))), "reserves_change_4w_pct": _pct(res[last], res.get(last - timedelta(days=28))),
                       "reserves_change_1y_pct": _pct(res[last], res.get(last - timedelta(days=364))), "currency_change_1y_pct": _pct(cur[last], cur.get(last - timedelta(days=364))),
                       "reserves_year_low_millions": round(min(yv), 0), "reserves_year_high_millions": round(max(yv), 0), "weeks_in_year": len(yv), "reserves_rank_in_year": rank},
            "monthly": {"month": _label(lm), "age_days": mage, "freshness": "CURRENT" if mage <= OVERDUE_MONTHLY_DAYS else "OVERDUE",
                        "base_billions": round(base[lm], 1), "currency_billions": round(mcur[lm], 1), "reserves_billions": round(mres[lm], 1), "gap_billions": round(base[lm] - mcur[lm] - mres[lm], 1),
                        "base_change_1m_pct": _pct(base[lm], base.get(_months_back(lm, 1))), "base_change_1y_pct": _pct(base[lm], base.get(_months_back(lm, 12)))},
            "crosscheck": cross,
            "history": [{"date": d.isoformat(), "reserves_millions": round(res[d], 0)} for d in year],
            "checks": {"weeks_in_a_row": True, "weekly_in_range": True, "weekly_moves_ok": True, "months_in_a_row": True, "monthly_moves_ok": True, "base_equals_currency_plus_reserves": True, "weekly_matches_monthly": True},
            "note": ("Bank reserves are the balances banks hold in their accounts at the Federal Reserve; currency is the cash in circulation; the monetary base is the two added together (FRED's own note: the monetary base equals currency in circulation plus reserve balances). "
                     "The weekly figures are averages for the week ending Wednesday, in millions of dollars, and the monthly ones are monthly averages in billions; both are shown here in trillions. The weekly figures reach FRED within days and the monthly ones a few weeks after the month ends, and all are revised later, so each carries its date. "
                     "Checked: every recent weekly figure is in a plausible range, no figure moves more than the real record allows, the dates follow each other without a gap, the monthly base equals currency plus reserves to within half a billion in each of the last 12 months, and the weekly figures average out to the monthly base for each of the last months (within 10%). "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class BankReserves:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast. cosd keeps the download to about two years.
        r = await c.get(URL, params={"id": sid, "cosd": (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real bank reserves and currency figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Bank reserves and currency could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
