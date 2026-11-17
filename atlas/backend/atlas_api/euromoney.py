"""Euro-area money supply (M1, M2 and M3) from the ECB Data Portal's public API (official, free, no key): how much money the euro area's households and firms hold, and how fast that amount is growing.

How to read it: M3, the broad money supply, is what the ECB counts as money: M2 plus repurchase agreements, money market fund shares and debt securities of up to two years. M2 is M1 plus deposits with an agreed maturity of up to two years and deposits redeemable at notice of up to three months. M1 is currency in circulation plus overnight deposits. Amounts are outstanding at the END of the month, in millions of euro, adjusted for working days and the season, for the euro area as it was in each month ("changing composition": the amount jumps when a country joins, and the history has been rebuilt as if the members of today had always been in). The growth rates are the ECB's own annual rates, calculated from an index of notional stocks (the series' own description), so they can differ a little from the growth of the amounts shown. The newest month is provisional (the ECB marks it so) and revised; it comes about four weeks after the month ends.
Checks, set from the whole real history (561 months, January 1980 to September 2026 for M1, M2 and M3; 349 months from September 1997 for the parts) before any test was written: every series reports the units the card assumes (the ECB's own labels: euro in millions for the amounts, percent change for the growth rates); all series end in the same month, every one has each of the last 24 months and the months follow each other; M1, M2 and M3 are each within a range that catches a x10 or /10 slip (the real lows since 1999 are 1.79, 3.91 and 4.44 trillion euro; now 11.3, 16.5 and 17.7); no one-month change of an amount under -5% or over +10% (the real extremes are -1.57% in June 2010 and +6.62% in June 2005, M1); no published growth rate under -15% or over +25% for M1 and under -5% or over +20% for M2 and M3 (the real extremes are -10.38% and +16.56% for M1, -2.36% and +12.26% for M2, -1.27% and +12.56% for M3); **four sums that hold to the million euro in all 561 months (349 for the last three)**: M1 = currency + overnight deposits, M2 = M1 + deposits with agreed maturity + deposits redeemable at notice, the marketable instruments (M3 - M2) = repurchase agreements + money market fund shares + debt securities, and M3 = M2 + those instruments, with a tolerance of one million for rounding. The ECB builds the aggregates from these parts, so the sums hold by its own arithmetic: they show that the series fetched belong to one release and were not mixed up, not that the ECB's figures are right. The last check is independent of them: the published annual growth must be within 4 points (M3), 4.5 (M2) or 7 points (M1) of the growth of the amounts over twelve months; the real gaps are at most 3.76, 4.10 and 6.41 points since 1980 (3.17 for M3 since 1999) and in the last 24 months -0.24 to +0.78 for M3, mostly in the years when countries joined the euro area (2001, 2011, 2014, 2015), so it is loose by necessity and catches a swapped or wrongly scaled series, not a small error. A series that ends in another month, or a month missing from one, is refused. A missing value is left out, never filled in.
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

BASE = "https://data-api.ecb.europa.eu/service/data/BSI/"
STOCK_KEY = "M.U2.Y.V.L10+L21+L22+L23+L24A+L30+L40+LT3+M10+M20+M30..1.U2.2300.Z01.E"
GROWTH_KEY = "M.U2.Y.V.M10+M20+M30.X.I.U2.2300.Z01.A"
SOURCE = "European Central Bank, ECB Data Portal: monetary aggregates from the balance sheets of euro-area monetary financial institutions (official, free public data)"
PAGE = BASE + "M.U2.Y.V.M30.X.1.U2.2300.Z01.E"
STOCKS = {"M10": "M1", "M20": "M2", "M30": "M3"}
PARTS = {"L10": "currency in circulation", "L21": "overnight deposits", "L22": "deposits with an agreed maturity of up to two years", "L23": "deposits redeemable at notice of up to three months",
         "L24A": "repurchase agreements", "L30": "money market fund shares", "L40": "debt securities of up to two years", "LT3": "marketable instruments"}
STOCK_IDS = tuple(STOCKS) + tuple(PARTS)
STOCK_UNIT = ("EUR", "6")             # the ECB's own labels: euro, in millions
GROWTH_UNIT = ("PCCH", "0")           # percent change
LIMITS = {"M10": (1.5e6, 4e7), "M20": (3.0e6, 4e7), "M30": (3.5e6, 4e7)}          # millions of euro; the real lows since 1999 are 1.79, 3.91 and 4.44 million million
MONTH_MOVE = (-0.05, 0.10)            # one-month change of an amount; the real extremes are -1.57% and +6.62%
GROWTH_LIMITS = {"M10": (-15.0, 25.0), "M20": (-5.0, 20.0), "M30": (-5.0, 20.0)}  # published annual growth, percent; the real extremes are in the docstring
GAP_TOLERANCE = {"M10": 7.0, "M20": 4.5, "M30": 4.0}                              # points between published growth and the growth of the amounts; the real maxima are 6.41, 4.10 and 3.76
SUM_TOLERANCE = 1.0                   # millions of euro: the sums hold exactly in the whole real history; one million allows for rounding
CHECK_MONTHS = 24
HISTORY_MONTHS = 36
GROWTH_WINDOW = 120                   # ten years of published growth
STOCK_LAST_N = 48                     # observations asked for: 24 checked months, 12 more for the growth of the amounts, and the 36 shown
GROWTH_LAST_N = 121
OVERDUE_AFTER_DAYS = 75               # from the end of the observed month: the next month normally arrives about 59 days after the previous one ends
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


def parse(text: str, ids: tuple[str, ...], key_prefix: str) -> tuple[dict[str, dict[date, float]], dict[str, tuple[str, str]], dict[str, str]]:
    """Values by id, the units each id reports (the ECB's UNIT and UNIT_MULT), and the status of each id's newest value ("P" provisional, "A" normal). Rows of any other series, and rows without a month or a number, are left out; two values for one month are an error."""
    values: dict[str, dict[date, float]] = {i: {} for i in ids}
    units: dict[str, tuple[str, str]] = {}
    newest: dict[str, tuple[date, str]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        sid, d, v = r.get("BS_ITEM") or "", _month(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if sid not in values or not (r.get("KEY") or "").startswith(key_prefix) or d is None or v is None:
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


def _check(stocks: dict[str, dict[date, float]], growth: dict[str, dict[date, float]], stock_units: dict, growth_units: dict) -> tuple[list[date], dict]:
    for sid, u in stock_units.items():
        if u != STOCK_UNIT:
            raise ValueError(f"the ECB reports {sid} in other units than millions of euro")
    for sid, u in growth_units.items():
        if u != GROWTH_UNIT:
            raise ValueError(f"the ECB reports the growth of {STOCKS[sid]} in other units than percent")
    every = list(stocks.values()) + list(growth.values())
    if len({max(s) for s in every}) != 1:
        raise ValueError("the money supply series end in different months")
    m3 = stocks["M30"]
    months = sorted(m3)
    recent = months[-CHECK_MONTHS:]
    if any(_months_back(b, 1) != a for a, b in zip(recent, recent[1:])):
        raise ValueError(f"the money supply values skip a month in the last {CHECK_MONTHS}")
    for sid, s in list(stocks.items()) + list(growth.items()):
        for d in recent:
            if d not in s:
                raise ValueError(f"{sid} is missing for {_label(d)}")
    for sid, (lo, hi) in LIMITS.items():
        if any(not (lo <= stocks[sid][d] <= hi) for d in recent):
            raise ValueError(f"{STOCKS[sid]} is outside the plausible range")
    pairs = list(zip(recent, recent[1:]))
    for sid in STOCKS:
        for a, b in pairs:
            ch = stocks[sid][b] / stocks[sid][a] - 1
            if not (MONTH_MOVE[0] <= ch <= MONTH_MOVE[1]):
                raise ValueError(f"{STOCKS[sid]} changed by {ch:.1%} in {_label(b)}, outside {MONTH_MOVE[0]:.0%} to {MONTH_MOVE[1]:+.0%}")
    for sid, (lo, hi) in GROWTH_LIMITS.items():
        for d in recent:
            if not (lo <= growth[sid][d] <= hi):
                raise ValueError(f"the growth of {STOCKS[sid]} is {growth[sid][d]:+.1f}% in {_label(d)}, outside {lo:+.0f}% to {hi:+.0f}%")
    sums = (("M1 is not currency plus overnight deposits", lambda d: stocks["M10"][d] - stocks["L10"][d] - stocks["L21"][d]),
            ("M2 is not M1 plus the deposits with an agreed maturity and the deposits redeemable at notice", lambda d: stocks["M20"][d] - stocks["M10"][d] - stocks["L22"][d] - stocks["L23"][d]),
            ("the marketable instruments are not the repurchase agreements, money market fund shares and debt securities", lambda d: stocks["LT3"][d] - stocks["L24A"][d] - stocks["L30"][d] - stocks["L40"][d]),
            ("M3 is not M2 plus the marketable instruments", lambda d: stocks["M30"][d] - stocks["M20"][d] - stocks["LT3"][d]))
    for text, diff in sums:
        for d in recent:
            off = diff(d)
            if abs(off) > SUM_TOLERANCE:
                raise ValueError(f"{text} in {_label(d)} (off by {off:+,.0f} million euro)")
    worst = {"points": 0.0, "month": recent[-1]}
    for sid, tol in GAP_TOLERANCE.items():
        for d in recent:
            ago = stocks[sid].get(_months_back(d, 12))
            if ago is None:
                continue
            gap = 100 * (stocks[sid][d] / ago - 1) - growth[sid][d]
            if abs(gap) > tol:
                raise ValueError(f"the published growth of {STOCKS[sid]} in {_label(d)} is {abs(gap):.1f} points away from the growth of the amounts, more than {tol:g}")
            if sid == "M30" and abs(gap) > abs(worst["points"]):
                worst = {"points": gap, "month": d}
    shown = round(worst["points"], 2)                                                  # compared unrounded above, so two equal gaps keep the earlier month
    return months, {"months_checked": len(recent), "sums_checked": 4 * len(recent), "largest_gap_points": shown, "largest_gap_month": _label(worst["month"]) if shown else None}


def _aggregate(stocks: dict[str, dict[date, float]], growth: dict[str, dict[date, float]], sid: str, last: date) -> dict:
    s = stocks[sid]
    v = s[last]
    one, three = s.get(_months_back(last, 1)), s.get(_months_back(last, 3))
    return {"level_millions": round(v, 0), "growth_pct": round(growth[sid][last], 1),
            "change_1m_pct": None if not one else round(100 * (v / one - 1), 2), "change_3m_pct": None if not three else round(100 * (v / three - 1), 2)}


def _growth_range(g: dict[date, float], last: date) -> dict | None:
    window = sorted(d for d in g if d <= last)[-GROWTH_WINDOW:]
    if len(window) < 60:
        return None
    lo, hi = min(window, key=lambda d: g[d]), max(window, key=lambda d: g[d])
    return {"months": len(window), "lowest": {"pct": round(g[lo], 1), "month": _label(lo)}, "highest": {"pct": round(g[hi], 1), "month": _label(hi)},
            "share_lower_pct": round(100 * sum(1 for d in window if g[d] < g[last]) / len(window))}


def _month_end(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)


def summarize(stocks: dict[str, dict[date, float]], growth: dict[str, dict[date, float]], stock_units: dict, growth_units: dict, status: dict[str, str], today: date) -> dict:
    months, detail = _check(stocks, growth, stock_units, growth_units)
    last = months[-1]
    m3 = stocks["M30"][last]
    age = (today - _month_end(last)).days
    makeup = [{"id": "M1", "label": "currency and overnight deposits", "level_millions": round(stocks["M10"][last], 0)},
              {"id": "term", "label": PARTS["L22"], "level_millions": round(stocks["L22"][last], 0)},
              {"id": "notice", "label": PARTS["L23"], "level_millions": round(stocks["L23"][last], 0)},
              {"id": "marketable", "label": "repurchase agreements, money market fund shares and debt securities of up to two years", "level_millions": round(stocks["LT3"][last], 0)}]
    for row in makeup:
        row["share_pct"] = round(100 * row["level_millions"] / m3, 1)
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "provisional": status.get("M30") == "P", "m3": _aggregate(stocks, growth, "M30", last), "m2": _aggregate(stocks, growth, "M20", last), "m1": _aggregate(stocks, growth, "M10", last),
            "makeup": makeup, "growth_range": _growth_range(growth["M30"], last), "detail": detail,
            "history": [{"date": d.isoformat(), "level_millions": round(stocks["M30"][d], 0)} for d in months[-HISTORY_MONTHS:]],
            "checks": {"units_ok": True, "months_in_a_row": True, "range_ok": True, "monthly_move_ok": True, "growth_range_ok": True, "sums_ok": True, "growth_agrees_ok": True},
            "note": ("M3 is what the ECB counts as money: M2 plus repurchase agreements, money market fund shares and debt securities of up to two years; M2 is M1 plus deposits with an agreed maturity of up to two years and deposits redeemable at notice of up to three months; M1 is currency in circulation plus overnight deposits. "
                     "Amounts are outstanding at the end of the month, in euro, adjusted for working days and the season, for the euro area as it was at the time (an amount jumps when a country joins). "
                     "The growth rates are the ECB's own annual rates, calculated from an index of notional stocks, so they can differ a little from the growth of the amounts shown. "
                     "The newest month is provisional and is revised later; each figure carries its month. "
                     "Checked: the units are the ones assumed, no month is missing, no amount or growth rate is outside what the real record allows, M1, M2 and M3 equal the sums of their parts to the million euro (the ECB builds them that way, so this shows the series belong together, not that they are right), and the published growth stays within 4 points of the growth of the amounts. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class EuroMoneySupply:
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
            return {**base, "available": False, "reason": "Demo mode: the real euro-area money supply figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            stock_text, growth_text = await asyncio.gather(self._get(c, STOCK_KEY, STOCK_LAST_N), self._get(c, GROWTH_KEY, GROWTH_LAST_N))
            stocks, s_units, status = parse(stock_text, STOCK_IDS, "BSI.M.U2.Y.V.")
            growth, g_units, _ = parse(growth_text, tuple(STOCKS), "BSI.M.U2.Y.V.")
            res = {**base, **summarize(stocks, growth, s_units, g_units, status, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The euro-area money supply could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
