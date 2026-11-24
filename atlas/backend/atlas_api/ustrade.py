"""US international trade in goods and services: what the United States sold to the rest of the world (exports), what it bought (imports) and the difference (the balance), from the Census Bureau and the Bureau of Economic Analysis' monthly "U.S. International Trade in Goods and Services" (balance-of-payments basis), as FRED, the St. Louis Fed, carries it (public-domain US government data, citation requested; the nine series pages read on 2026-11-24 name only those two agencies as the source, with no third-party notice and no "calculated by" remark). Free, no key.

The nine series, all monthly, in millions of dollars, seasonally adjusted, dated the 1st and meaning the whole month, all from Table 1 of that release: BOPTEXP and BOPTIMP, exports and imports of goods and services, and BOPGSTB, their balance; BOPGEXP, BOPGIMP and BOPGTB, the same for goods; BOPSEXP, BOPSIMP and BOPSTB, the same for services. Every series starts in 1992-01, so every request starts there (417 months by 2026-09) and the whole record is checked each time. Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18).
Checks, set from the whole real record before any test was written: the nine series end in the same month and cover exactly the same months, each dated the 1st, none skipped, at least 120 of them; every level and balance lies inside a range set well outside the real one; no month-on-month move of the six level series (exports and imports of the total, of goods and of services) is beyond 50% (the real extremes are -25.4% and +15.0%, both goods exports, in 2020-04 and 2020-06; the balances are not move-checked, they follow from the sums); and six sums hold within 1.5 million dollars on every month: each of the three balances equals its exports minus its imports, total exports and total imports equal goods plus services, and the total balance equals the goods balance plus the services balance. The published figures are each rounded to a million, so a sum of three of them can be 1.5 off at most; the real largest gap is 1 million in all six, on 417 months, and the gaps are integers spread over -1, 0 and +1. A series swapped for another is caught by the sums (the goods balance in place of the total balance is off by the services surplus, about 30 billion).
These figures are the agencies' own accounting, all from Table 1 of one release: the sums show that the nine series belong to one release and are lined up, not that the figures are right. NOT checked, and said so: which of the nine series is wrong when a sum fails, any revision of the newest months (every release revises earlier ones), the advance estimate of the newest month that FRED carries as separate series, and how the balance-of-payments basis differs from the customs basis of the same trade.
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
SOURCE = "U.S. Census Bureau and U.S. Bureau of Economic Analysis, U.S. International Trade in Goods and Services (balance-of-payments basis), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/BOPGSTB"
START = "1992-01-01"                              # the first month of every series: every request asks for the whole record
TEXP, TIMP, TBAL = "BOPTEXP", "BOPTIMP", "BOPGSTB"
GEXP, GIMP, GBAL = "BOPGEXP", "BOPGIMP", "BOPGTB"
SEXP, SIMP, SBAL = "BOPSEXP", "BOPSIMP", "BOPSTB"
SERIES = (TEXP, TIMP, TBAL, GEXP, GIMP, GBAL, SEXP, SIMP, SBAL)
MOVE_SERIES = (TEXP, TIMP, GEXP, GIMP, SEXP, SIMP)
NAMES = {TEXP: "total exports", TIMP: "total imports", TBAL: "total balance", GEXP: "goods exports", GIMP: "goods imports", GBAL: "goods balance",
         SEXP: "services exports", SIMP: "services imports", SBAL: "services balance"}
_LEVEL = (3_000.0, 1_500_000.0)
LIMITS = {TEXP: _LEVEL, TIMP: _LEVEL, TBAL: (-600_000.0, 100_000.0), GEXP: _LEVEL, GIMP: _LEVEL, GBAL: (-700_000.0, 100_000.0),
          SEXP: _LEVEL, SIMP: _LEVEL, SBAL: (-100_000.0, 150_000.0)}      # million dollars; the real ranges since 1992 are inside (levels 9,688 to 426,558; balances -159,453 to +32,455)
MOVE_LIMIT = 50.0                                 # percent in a month, either way, for the six level series; the real extremes are -25.4 and +15.0
IDENTITY_TOLERANCE = 1.5                          # million dollars: three published figures, each rounded to a million, can be 1.5 apart at most; exact in binary; the real largest gap is 1
MIN_MONTHS = 120
RECENT_MONTHS = 6
OVERDUE_AFTER_DAYS = 105                          # from the 1st of the observed month: a month is released about 64 days after its 1st and stays the newest until the next release about 34 days later (September on 4 November, October on 8 December, when September is 98 days old); 7 days of slack
TTL = 6 * 3600.0
FAIL_TTL = 120.0

# (refusal text, the gap of one month): the six sums, checked in this order, series by series, the oldest month first
SUMS = (
    ("the total balance is {gap:g} million off exports minus imports in {month}, over {tol:g}", lambda d, m: d[TBAL][m] - (d[TEXP][m] - d[TIMP][m])),
    ("the goods balance is {gap:g} million off goods exports minus imports in {month}, over {tol:g}", lambda d, m: d[GBAL][m] - (d[GEXP][m] - d[GIMP][m])),
    ("the services balance is {gap:g} million off services exports minus imports in {month}, over {tol:g}", lambda d, m: d[SBAL][m] - (d[SEXP][m] - d[SIMP][m])),
    ("total exports are {gap:g} million off goods plus services in {month}, over {tol:g}", lambda d, m: d[TEXP][m] - (d[GEXP][m] + d[SEXP][m])),
    ("total imports are {gap:g} million off goods plus services in {month}, over {tol:g}", lambda d, m: d[TIMP][m] - (d[GIMP][m] + d[SIMP][m])),
    ("the total balance is {gap:g} million off goods plus services balances in {month}, over {tol:g}", lambda d, m: d[TBAL][m] - (d[GBAL][m] + d[SBAL][m])),
)


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the trade series end in different months")
    for sid in SERIES[1:]:
        if set(data[sid]) != set(data[TEXP]):
            raise ValueError(f"the {NAMES[sid]} series covers different months than total exports")
    months = sorted(data[TEXP])
    if any(d.day != 1 for d in months):
        raise ValueError("a trade date is not the 1st of a month")
    for a, b in zip(months, months[1:]):
        if _months_back(b, 1) != a:
            raise ValueError(f"the trade months skip a month after {_label(a)}")
    if len(months) < MIN_MONTHS:
        raise ValueError(f"the trade record covers {len(months)} months, fewer than the {MIN_MONTHS} expected")
    for sid in SERIES:
        lo, hi = LIMITS[sid]
        for d in months:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"the {NAMES[sid]} of {_num(v)} million in {_label(d)} is outside {_num(lo)} to {_num(hi)}")
    for sid in MOVE_SERIES:
        for a, b in zip(months, months[1:]):
            change = round(100.0 * (data[sid][b] / data[sid][a] - 1.0), 4)         # four decimals: a move of exactly 50% is not refused for the last bit of a float
            if not (-MOVE_LIMIT <= change <= MOVE_LIMIT):
                raise ValueError(f"the {NAMES[sid]} moved {change:+.1f}% in {_label(b)}, outside {-MOVE_LIMIT:g} to {MOVE_LIMIT:g}")
    largest, where = -1.0, months[0]
    for text, gap_of in SUMS:
        for d in months:
            gap = abs(gap_of(data, d))
            if gap > IDENTITY_TOLERANCE:
                raise ValueError(text.format(gap=gap, month=_label(d), tol=IDENTITY_TOLERANCE))
            if gap > largest:
                largest, where = gap, d
    return months, {"months_checked": len(months), "first_month": _label(months[0]), "last_month": _label(months[-1]),
                    "largest_gap_million": round(largest, 3) + 0.0, "largest_gap_month": _label(where)}


def _pct(a: float, b: float) -> float:
    return round(100.0 * (a / b - 1.0), 2) + 0.0                                    # + 0.0 turns a negative zero into zero


def _bn(million: float) -> float:
    return round(million / 1000.0, 3) + 0.0                                         # millions of dollars to billions, three decimals: exact for whole millions


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    months, detail = _check(data)
    last = months[-1]
    before, ago = _months_back(last, 1), _months_back(last, 12)
    age = (today - last).days

    def group(e: str, i: str, b: str) -> dict:
        ex, im, bal = data[e], data[i], data[b]
        return {"exports": _bn(ex[last]), "imports": _bn(im[last]), "balance": _bn(bal[last]), "balance_change": _bn(bal[last] - bal[before]), "balance_year_ago": _bn(bal[ago]),
                "exports_change_year_pct": _pct(ex[last], ex[ago]), "imports_change_year_pct": _pct(im[last], im[ago])}

    total = group(TEXP, TIMP, TBAL)
    total["range"] = _range({d: data[TBAL][d] / 1000.0 for d in months}, data[TBAL][last] / 1000.0, months[0])
    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "month": _label(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "total": total, "goods": group(GEXP, GIMP, GBAL), "services": group(SEXP, SIMP, SBAL),
            "recent": [{"month": _label(m), "exports": _bn(data[TEXP][m]), "imports": _bn(data[TIMP][m]), "balance": _bn(data[TBAL][m])}
                       for m in (_months_back(last, i) for i in range(RECENT_MONTHS - 1, -1, -1))],
            "detail": detail,
            "checks": {"months_in_a_row": True, "range_ok": True, "moves_ok": True, "identity_ok": True},
            "note": ("US trade is what the United States sold to the rest of the world (exports) and bought from it (imports) in the month, from the Census Bureau and the Bureau of Economic Analysis, "
                     "on the balance-of-payments basis named in the series titles, in millions of dollars and seasonally adjusted, shown here in billions. "
                     "The balance is exports minus imports. A negative balance is a deficit and a positive one a surplus. Goods are physical products; services are things such as travel, transport and financial services. "
                     "The newest months are revised in later releases; each figure carries its month. "
                     "Plain checks: the units are the ones assumed and no month is missing; the ranges, the monthly moves and the six sums (each balance against its exports and imports, and the totals against goods plus services) are in the Check line. "
                     "This describes trade that already happened: it is not a market signal or a forecast.")}


class UsTrade:
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
            return {**base, "available": False, "reason": "Demo mode: the real US trade figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US international trade could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
