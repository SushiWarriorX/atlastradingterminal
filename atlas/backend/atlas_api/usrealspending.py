"""US real consumer spending: what households spend with the effect of price changes taken out, from the Bureau of Economic Analysis' monthly Personal Income and Outlays, as FRED, the St. Louis Fed, carries it (public-domain US government data, citation requested; the series pages read on 2026-11-24 name only the Bureau as the source, with no third-party notice). Free, no key.

The four series, all monthly, seasonally adjusted, dated the 1st and meaning the whole month: PCEC96, real consumer spending in billions of chained 2017 dollars at an annual rate (BEA account code DPCERX); PCE, consumer spending in billions of dollars of the day at an annual rate (the series the household card already shows); PCEPI, the PCE price index, 2017 = 100, a chain-type index (DPCERG); and PCEPILFE, the same index without food and energy (DPCCRG). The real series starts in 2007-01, so every request starts there (237 months by 2026-09) and the whole record is checked each time. Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18).
Checks, set from the whole real record before any test was written: the four series end in the same month and cover exactly the same months, each dated the 1st, none skipped, at least 120 of them; every level and index lies inside a range set well outside the real one; no month-on-month move is beyond 25% for the two spending series or 5% for the two indexes (the real extremes are -11.3% and +8.4% in 2020-04 and 2020-05, and -1.2% to +1.2% for the price index since 1959); and real spending times the price index over 100 equals spending in dollars within 2 to the power -10 of spending (0.0977%, exact in binary), on every month. The Bureau chain-weights real spending and the price index, so the identity is approximate, not exact: the real largest gap is 0.0378% of spending (2021-03, 5.9 billion; at most 0.008% in every year except 2020 to 2022), about a third of the tolerance, and rounding explains only about 0.2 billion. A series swapped for the core index is caught (it is 1.0% off in the newest month), and a digit slip that stays inside every range and move is caught by the sum alone.
These figures are the Bureau's own accounting (it derives the price index and the real series from the same prices and quantities): the check shows that the four series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: which of the three series is wrong when the sum fails, any revision of the newest months, and what the price index contains beyond the Bureau's own description. The change over a year in spending in dollars, in real spending and in prices come from three separate series and fit each other: (1 + nominal) = (1 + real) x (1 + prices), the gap being at most 0.03 points in any year since 2008.
It describes what already happened: it is not a market signal or a forecast.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone

import httpx

from .failreason import fail_reason
from .fincond import parse
from .jolts import _num, _range
from .moneysupply import _label, _months_back

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Bureau of Economic Analysis, Personal Income and Outlays (real consumer spending, spending in dollars and the PCE price indexes), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/PCEC96"
START = "2007-01-01"                             # the first month of the real series: every request asks for the whole record
REAL, NOMINAL, PRICE, CORE = "PCEC96", "PCE", "PCEPI", "PCEPILFE"
SERIES = (REAL, NOMINAL, PRICE, CORE)
NAMES = {REAL: "real consumer spending", NOMINAL: "consumer spending in dollars", PRICE: "PCE price index", CORE: "core PCE price index"}
LIMITS = {REAL: (3_000.0, 60_000.0), NOMINAL: (150.0, 80_000.0), PRICE: (5.0, 500.0), CORE: (5.0, 500.0)}       # billions and index points; the real ranges since 2007 are inside (real 11,068.0 to 16,977.6)
MOVE_LIMITS = {REAL: (-25.0, 25.0), NOMINAL: (-25.0, 25.0), PRICE: (-5.0, 5.0), CORE: (-5.0, 5.0)}                # percent in a month; the real extremes are -11.3 and +8.4 for spending, -1.2 and +1.2 for the price index
IDENTITY_TOLERANCE = 2 ** -10                    # of spending in dollars: 0.0977%, about 2.6 times the real largest gap of 0.0378%; exact in binary
MIN_MONTHS = 120
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 100                         # from the 1st of the observed month: a month is released 55 to 61 days after its 1st and stays the newest until the next release (September on 29 October, October on 25 November, when September is 85 days old), so about 91 days is normal; 9 days of slack
TTL = 6 * 3600.0
FAIL_TTL = 120.0


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the real spending series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(data[REAL]):
            raise ValueError(f"the {NAMES[sid]} series covers different months than real consumer spending")
    months = sorted(data[REAL])
    if any(d.day != 1 for d in months):
        raise ValueError("a real spending date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the real spending months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the real spending record covers {len(months)} months, fewer than the {MIN_MONTHS} expected")
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        unit = " billion" if sid in (REAL, NOMINAL) else ""
        for d in months:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"the {NAMES[sid]} of {_num(v)}{unit} in {_label(d)} is outside {_num(lo)} to {_num(hi)}")
    for sid in SERIES:
        lo, hi = MOVE_LIMITS[sid]
        for a, b in zip(months, months[1:]):
            change = round(100.0 * (data[sid][b] / data[sid][a] - 1.0), 4)         # four decimals: a move of exactly 5% is not refused for the last bit of a float
            if not (lo <= change <= hi):
                raise ValueError(f"the {NAMES[sid]} moved {change:+.1f}% in {_label(b)}, outside {lo:g} to {hi:g}")
    largest, where = -1.0, months[0]
    for d in months:
        nominal = data[NOMINAL][d]
        gap = abs(data[REAL][d] * data[PRICE][d] / 100.0 - nominal)
        rel = 100.0 * gap / nominal
        if gap > nominal * IDENTITY_TOLERANCE:
            raise ValueError(f"real spending times prices is {rel:.3f}% off spending in dollars in {_label(d)}, over {100.0 * IDENTITY_TOLERANCE:.3f}%")
        if rel > largest:
            largest, where = rel, d
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]),
                    "largest_identity_gap_pct": round(largest, 4), "largest_identity_gap_month": _label(where)}


def _pct(a: float, b: float) -> float:
    return round(100.0 * (a / b - 1.0), 2) + 0.0                                    # + 0.0 turns a negative zero into zero


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    before, ago = _months_back(last, 1), _months_back(last, 12)
    real, nominal, price, core = (data[sid] for sid in SERIES)
    age = (today - last).days
    growth = {d: 100.0 * (real[d] / real[_months_back(d, 12)] - 1.0) for d in months[12:]}
    n, r, p = nominal[last] / nominal[ago] - 1.0, real[last] / real[ago] - 1.0, price[last] / price[ago] - 1.0
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "real": {"level_billions": real[last], "change_pct": _pct(real[last], real[before]), "change_year_pct": _pct(real[last], real[ago]), "range": _range(growth, growth[last], months[12])},
            "nominal": {"level_billions": nominal[last], "change_pct": _pct(nominal[last], nominal[before]), "change_year_pct": _pct(nominal[last], nominal[ago])},
            "prices": {"index": price[last], "change_pct": _pct(price[last], price[before]), "change_year_pct": _pct(price[last], price[ago]),
                       "core_index": core[last], "core_change_pct": _pct(core[last], core[before]), "core_change_year_pct": _pct(core[last], core[ago])},
            "year": {"nominal_pct": _pct(nominal[last], nominal[ago]), "real_pct": _pct(real[last], real[ago]), "prices_pct": _pct(price[last], price[ago]), "core_prices_pct": _pct(core[last], core[ago]),
                     "gap_points": round(abs(100.0 * ((1.0 + n) / ((1.0 + r) * (1.0 + p)) - 1.0)), 3)},
            "recent": [{"month": _label(m), "real_change_pct": _pct(real[m], real[_months_back(m, 1)]), "prices_change_pct": _pct(price[m], price[_months_back(m, 1)]),
                        "nominal_change_pct": _pct(nominal[m], nominal[_months_back(m, 1)])} for m in (_months_back(last, i) for i in range(RECENT_MONTHS - 1, -1, -1))],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "moves_ok": True, "identity_ok": True},
            "note": ("Real consumer spending is what US households spend with the effect of price changes taken out: the Bureau of Economic Analysis' monthly figure in chained 2017 dollars, at a seasonally adjusted annual rate. "
                     "Spending in dollars of the day is the same spending before that adjustment, and the PCE price index (2017 = 100) is the average price of what households buy, with and without food and energy. "
                     "Over a year, the change in spending in dollars is the change in real spending (more or fewer goods and services bought) combined with the change in prices. "
                     "The newest months are revised in later releases; each figure carries its month. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the monthly moves and the sum of real spending and prices against spending in dollars are in the Check line. "
                     "This describes spending that already happened: it is not a market signal or a forecast.")}


class UsRealSpending:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # One series per request: with several ids a single cosd applies to the first series only. No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast.
        r = await c.get(URL, params={"id": sid, "cosd": START})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real US consumer spending figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US real consumer spending could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
