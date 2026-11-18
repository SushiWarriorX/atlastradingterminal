"""Euro-area bank lending from the ECB Data Portal's public API (official, free, no key): the loans that euro-area banks (monetary financial institutions) have granted to non-financial corporations ("firms") and to households, how fast they grow, and what they are made of.

How to read it: the headline is the ECB's own measure, loans ADJUSTED for loan sales and securitisation (a loan a bank sells on or packages into a security stays in the figure, so a sale does not look like a repayment), seasonally and working-day adjusted, for the euro area as it was in each month ("changing composition": the amount jumps when a country joins, and the growth rates are built to ignore that). Amounts are outstanding at the END of the month, in millions of euro; the flow is the month's net new lending (transactions, which leave out write-offs, revaluations and a country joining); the growth rate is the ECB's annual rate, calculated from an index of notional stocks. Households are split by purpose (lending for house purchase, consumer credit, other lending) and firms by how long the loan runs (up to one year, one to five years, over five years). The newest month is provisional and is revised; it comes about four weeks after the month ends.
Checks, set from the whole real record before any test was written (285 months of amounts from January 2003 for the two totals, 273 months of growth from January 2004; the households' parts from December 2014, 142 months; the firms' three maturities from January 2022, 57 months; no month missing in any of the 24 series): every series reports the units the card assumes (the ECB's own labels: euro in millions for the amounts and the flows, percent change for the growth); all 24 series end in the same month and each has all of the last 36 months; each amount lies in a range that catches a x10 or /10 slip (loans to firms 1.5 to 12 million million euro against a real 2.99 to 5.52, to households 1.7 to 15 against 3.43 to 7.28, and the six parts likewise); no amount changes by more than -12.5% or +12.5% in a month (the real extremes are -4.26% for other lending to households in January 2022 and +3.39% for loans to firms of up to one year in August 2022); each growth rate lies in a range set around the real one (firms -10% to +25% against a real -3.50% to +15.04%, households -5% to +15% against -0.35% to +9.87%, and the parts likewise).
**Three checks are the source's own arithmetic**, which show that the series fetched belong to one release and were not mixed up, not that the figures are right. (1) Loans to firms equal the sum of the three maturities and loans to households equal house purchase plus consumer credit plus other lending, for the amounts AND for the flows, to the million euro: the real gap is exactly 0 in all 142 and 141 months of the households' parts and all 57 and 56 months of the firms' (tolerance one million euro for rounding). (2) The published annual growth equals the growth rebuilt from the monthly flows and the amounts (the product over twelve months of one plus each month's flow over the previous month's amount, minus one), which is how the ECB builds its index of notional stocks: the real gap is at most 0.0235 points in all 273, 273, 45, 45, 45, 130, 130 and 130 months (largest for households in April 2021; firms 0.0071 in March 2008; tolerance 0.0625 points, which is 2 to the power -4, so that a gap of exactly the tolerance can be tested), and it is applied to the last 24 months because the whole record holds without exception. Because the ECB calculates (2) itself, it proves the units, the months and the pairing of the series, nothing about the economy.
A series that ends in another month, or a month missing from one, is refused. A missing value is left out, never filled in.
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
SOURCE = "European Central Bank, ECB Data Portal: loans of euro-area monetary financial institutions to non-financial corporations and to households, adjusted for loan sales and securitisation (official, free public data)"
# entity id -> (BS_ITEM, MATURITY_ORIG, counterpart sector, name): every series of the card has the key M.U2.Y.U.<item>.<maturity>.<data type>.U2.<sector>.Z01.<suffix>
ENTITIES = {
    "firms": ("A20T", "A", "2240", "loans to firms"),
    "firms_short": ("A20T", "F", "2240", "loans to firms of up to one year"),
    "firms_mid": ("A20T", "I", "2240", "loans to firms of one to five years"),
    "firms_long": ("A20T", "J", "2240", "loans to firms of over five years"),
    "households": ("A20T", "A", "2250", "loans to households"),
    "house": ("A22T", "A", "2250", "lending to households for house purchase"),
    "consumer": ("A21T", "A", "2250", "consumer credit"),
    "other": ("A23T", "A", "2250", "other lending to households"),
}
STOCK_UNIT = ("EUR", "6")             # the ECB's own labels: euro, in millions
FLOW_UNIT = ("EUR", "6")
GROWTH_UNIT = ("PCCH", "0")           # percent change
# kind -> (DATA_TYPE, BS_SUFFIX, the units it reports, how a name says it)
KINDS = {"stock": ("1", "E", STOCK_UNIT, "amount outstanding"), "flow": ("4", "E", FLOW_UNIT, "monthly flow"), "growth": ("I", "A", GROWTH_UNIT, "annual growth")}


def _key(entity: str, kind: str) -> str:
    item, maturity, sector, _ = ENTITIES[entity]
    return f"M.U2.Y.U.{item}.{maturity}.{KINDS[kind][0]}.U2.{sector}.Z01.{KINDS[kind][1]}"


SERIES = {f"{e}.{k}": (_key(e, k), KINDS[k][2]) for e in ENTITIES for k in KINDS}     # series id -> (key without "BSI.", units)
NAMES = {f"{e}.{k}": f"{ENTITIES[e][3]} ({KINDS[k][3]})" for e in ENTITIES for k in KINDS}
FIRMS = ("firms", "firms_short", "firms_mid", "firms_long")
HOUSEHOLDS = ("households", "house", "consumer", "other")
PAGE = BASE + SERIES["firms.growth"][0]
# the four requests: the key (the OR-list `+` must reach the host unencoded) and the series each one returns
REQUESTS = (
    ("M.U2.Y.U.A20T.A+F+I+J.1+4.U2.2240.Z01.E", tuple(f"{e}.{k}" for e in FIRMS for k in ("stock", "flow"))),
    ("M.U2.Y.U.A20T.A+F+I+J.I.U2.2240.Z01.A", tuple(f"{e}.growth" for e in FIRMS)),
    ("M.U2.Y.U.A20T+A21T+A22T+A23T.A.1+4.U2.2250.Z01.E", tuple(f"{e}.{k}" for e in HOUSEHOLDS for k in ("stock", "flow"))),
    ("M.U2.Y.U.A20T+A21T+A22T+A23T.A.I.U2.2250.Z01.A", tuple(f"{e}.growth" for e in HOUSEHOLDS)),
)
STOCK_LIMITS = {"firms": (1.5e6, 12e6), "firms_short": (0.3e6, 3e6), "firms_mid": (0.4e6, 4e6), "firms_long": (1.2e6, 10e6),
                "households": (1.7e6, 15e6), "house": (1.5e6, 15e6), "consumer": (0.2e6, 2.5e6), "other": (0.25e6, 2.5e6)}      # millions of euro; the real record is in the docstring
GROWTH_LIMITS = {"firms": (-10.0, 25.0), "firms_short": (-30.0, 40.0), "firms_mid": (-20.0, 30.0), "firms_long": (-10.0, 20.0),
                 "households": (-5.0, 15.0), "house": (-10.0, 20.0), "consumer": (-15.0, 25.0), "other": (-15.0, 15.0)}       # published annual growth, percent
MONTH_MOVE = (-0.125, 0.125)          # one-month change of an amount (exact in binary, so a change of exactly the limit can be tested); the real extremes are -4.26% and +3.39%
SUM_TOLERANCE = 1.0                   # millions of euro: the sums hold exactly in the whole real record; one million allows for rounding
GROWTH_TOLERANCE = 2 ** -4            # 0.0625 points (exact in binary, so a gap of exactly the tolerance can be tested); the real gap is at most 0.0235
# totals and their parts: (the total, its parts, how a failure says it for the amounts, and for the flows)
SUMS = (("firms", FIRMS[1:], "loans to firms are not the sum of the loans of up to one year, of one to five years and of over five years",
         "the monthly flow of loans to firms is not the sum of the flows of the three maturities"),
        ("households", HOUSEHOLDS[1:], "loans to households are not the sum of lending for house purchase, consumer credit and other lending",
         "the monthly flow of loans to households is not the sum of the flows of house purchase, consumer credit and other lending"))
CHECK_MONTHS = 24                     # months of growth compared with the flows
DEPTH = 36                            # months every series must have: the 24 checked, and twelve more for the flows of the first one
LAST_N = 125                          # observations asked for: the ten-year window of the totals, and a few more
GROWTH_WINDOW = 120                   # ten years of published growth
MIN_WINDOW = 60
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 75               # from the end of the observed month: the next month normally arrives about 59 days after the previous one ends
TTL = 6 * 3600.0
FAIL_TTL = 120.0
TIMEOUT = 45.0                        # seconds for one request: the ECB portal answered one of these four keys in 23 s once and in under 2 s every other time
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


def parse(text: str, ids: tuple[str, ...]) -> tuple[dict[str, dict[date, float]], dict[str, tuple[str, str]], dict[str, str]]:
    """Values by series id (for example "firms.growth") and month, the units each series reports (the ECB's UNIT and UNIT_MULT) and the status of each series' newest value ("A" normal, "P" provisional). Rows of any other series, and rows without a month or a number, are left out; two values for one month are an error."""
    values: dict[str, dict[date, float]] = {i: {} for i in ids}
    wanted = {"BSI." + SERIES[i][0]: i for i in ids}
    units: dict[str, tuple[str, str]] = {}
    newest: dict[str, tuple[date, str]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        sid, d, v = wanted.get(r.get("KEY") or ""), _month(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if sid is None or d is None or v is None:
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


def _check(v: dict[str, dict[date, float]], units: dict) -> tuple[date, dict]:
    for sid, u in units.items():
        if u != SERIES[sid][1]:
            raise ValueError(f"the ECB reports {NAMES[sid]} in other units than the card assumes")
    ends = {max(s) for s in v.values()}
    if len(ends) != 1:
        raise ValueError("the bank lending series end in different months")
    last = ends.pop()
    window = [_months_back(last, i) for i in range(DEPTH - 1, -1, -1)]               # oldest first
    for sid, s in v.items():
        for d in window:
            if d not in s:
                raise ValueError(f"{NAMES[sid]} is missing for {_label(d)}")
    for e in ENTITIES:
        lo, hi = STOCK_LIMITS[e]
        for d in window:
            x = v[e + ".stock"][d]
            if not (lo <= x <= hi):
                raise ValueError(f"{NAMES[e + '.stock']} is {x:,.0f} million euro in {_label(d)}, outside {lo:,.0f} to {hi:,.0f}")
        lo, hi = GROWTH_LIMITS[e]
        for d in window:
            x = v[e + ".growth"][d]
            if not (lo <= x <= hi):
                raise ValueError(f"{NAMES[e + '.growth']} is {x:+.1f}% in {_label(d)}, outside {lo:+g}% to {hi:+g}%")
        for a, b in zip(window, window[1:]):
            ch = v[e + ".stock"][b] / v[e + ".stock"][a] - 1
            if not (MONTH_MOVE[0] <= ch <= MONTH_MOVE[1]):
                raise ValueError(f"{NAMES[e + '.stock']} changed by {ch:.1%} in {_label(b)}, outside {MONTH_MOVE[0]:.1%} to {MONTH_MOVE[1]:+.1%}")
    for total, parts, stock_text, flow_text in SUMS:                                   # the ECB's own arithmetic: shows the series belong together
        for kind, text in (("stock", stock_text), ("flow", flow_text)):
            for d in window:
                off = v[f"{total}.{kind}"][d] - sum(v[f"{p}.{kind}"][d] for p in parts)
                if abs(off) > SUM_TOLERANCE:
                    raise ValueError(f"{text} in {_label(d)} (off by {off:+,.0f} million euro)")
    worst = {"points": 0.0, "month": last, "series": "firms"}
    for e in ENTITIES:                                                                  # the ECB's own arithmetic too: growth from flows and amounts
        for d in window[-CHECK_MONTHS:]:
            product = 1.0
            for i in range(12):
                m = _months_back(d, i)
                product *= 1 + v[e + ".flow"][m] / v[e + ".stock"][_months_back(m, 1)]
            gap = v[e + ".growth"][d] - 100 * (product - 1)
            if abs(gap) > GROWTH_TOLERANCE:
                raise ValueError(f"the published growth of {ENTITIES[e][3]} in {_label(d)} is {abs(gap):.2f} points away from the growth rebuilt from the monthly flows, more than {GROWTH_TOLERANCE:g}")
            if abs(gap) > abs(worst["points"]):
                worst = {"points": gap, "month": d, "series": e}
    shown = round(worst["points"], 4)                                                   # compared unrounded above, so two equal gaps keep the earlier one
    return last, {"months_checked": DEPTH, "sums_checked": 4 * DEPTH, "growth_months_checked": CHECK_MONTHS, "largest_growth_gap_points": shown,
                  "largest_growth_gap_month": _label(worst["month"]) if shown else None, "largest_growth_gap_series": ENTITIES[worst["series"]][3] if shown else None}


def _entity(v: dict, e: str, last: date) -> dict:
    return {"id": e, "label": ENTITIES[e][3], "amount_millions": round(v[e + ".stock"][last], 0), "flow_millions": round(v[e + ".flow"][last], 0),
            "growth_pct": round(v[e + ".growth"][last], 2), "growth_year_earlier_pct": round(v[e + ".growth"][_months_back(last, 12)], 2)}


def _parts(v: dict, total: str, parts: tuple[str, ...], last: date) -> list[dict]:
    rows = []
    for p in parts:
        row = _entity(v, p, last)
        row["share_pct"] = round(100 * v[p + ".stock"][last] / v[total + ".stock"][last], 1)
        rows.append(row)
    return rows


def _growth_range(g: dict[date, float], last: date) -> dict | None:
    window = sorted(d for d in g if d <= last)[-GROWTH_WINDOW:]
    if len(window) < MIN_WINDOW:
        return None
    lo, hi = min(window, key=lambda d: g[d]), max(window, key=lambda d: g[d])
    return {"months": len(window), "lowest": {"pct": round(g[lo], 1), "month": _label(lo)}, "highest": {"pct": round(g[hi], 1), "month": _label(hi)},
            "share_lower_pct": round(100 * sum(1 for d in window if g[d] < g[last]) / len(window))}


def _month_end(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)


def summarize(v: dict, units: dict, status: dict[str, str], today: date) -> dict:
    last, detail = _check(v, units)
    age = (today - _month_end(last)).days
    recent = [_months_back(last, i) for i in range(RECENT_MONTHS)]
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "provisional": status.get("firms.growth", "") not in ("", "A"),
            "firms": {**_entity(v, "firms", last), "parts": _parts(v, "firms", FIRMS[1:], last), "window": _growth_range(v["firms.growth"], last)},
            "households": {**_entity(v, "households", last), "parts": _parts(v, "households", HOUSEHOLDS[1:], last), "window": _growth_range(v["households.growth"], last)},
            "recent": [{"date": d.isoformat(), "month": _label(d), "firms_growth_pct": round(v["firms.growth"][d], 2), "households_growth_pct": round(v["households.growth"][d], 2)} for d in recent],
            "detail": detail,
            "checks": {"units_ok": True, "months_in_a_row": True, "range_ok": True, "monthly_move_ok": True, "growth_range_ok": True, "sums_ok": True, "growth_follows_the_flows_ok": True},
            "note": ("The ECB's own measure of bank lending: loans of euro-area monetary financial institutions to non-financial corporations (firms) and to households, adjusted for loan sales and securitisation (a loan a bank sells on or packages into a security stays in the figure, so a sale does not look like a repayment), seasonally and working-day adjusted, for the euro area as it was at the time (an amount jumps when a country joins; the growth rates are built to ignore that). "
                     "Amounts are outstanding at the end of the month, in euro; the flow is the month's net new lending (transactions, which leave out write-offs and revaluations); the annual growth is the ECB's own rate, calculated from an index of notional stocks. "
                     "Households are split by purpose and firms by how long the loan runs. The newest month is provisional and is revised later; each figure carries its month. "
                     "Checked: the units are the ones assumed, no month is missing, no amount, monthly change or growth rate is outside what the real record allows (plain checks), and two checks that are the source's own arithmetic held in each of the last 36 months: the parts add up to the totals, for the amounts and for the flows (to the million euro), "
                     "and the published annual growth equals the growth rebuilt from the monthly flows and amounts (to within 0.0625 points, in each of the last 24 months). The ECB builds the totals and its growth rates that way, so these show the series belong together, not that the figures are right. "
                     "This describes what already happened: it is not a market signal or a forecast.")}


class EuroLending:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _get(self, c: httpx.AsyncClient, key: str) -> str:
        r = await c.get(BASE + key, params={"lastNObservations": LAST_N, "format": "csvdata"}, headers={"User-Agent": "ATLAS research terminal", "Accept": "text/csv"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return r.text

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real euro-area bank lending figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            texts = await asyncio.gather(*(self._get(c, key) for key, ids in REQUESTS))
            values: dict = {}
            units: dict = {}
            status: dict = {}
            for text, (key, ids) in zip(texts, REQUESTS):
                vv, uu, ss = parse(text, ids)
                values.update(vv)
                units.update(uu)
                status.update(ss)
            res = {**base, **summarize(values, units, status, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The euro-area bank lending could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
