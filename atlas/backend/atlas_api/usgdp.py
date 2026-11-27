"""US gross domestic product by component: the quarterly National Income and Product Accounts of the Bureau of Economic Analysis, as FRED, the St. Louis Fed, carries them (public-domain US government data, citation requested; every series page read on 2026-11-18 names only the Bureau as its source, with no third-party notice).

How to read it: GDP (series GDP) is the value of what the country produced, counted by what it was spent on, in billions of dollars at a seasonally adjusted annual rate and in the prices of the time: 33,010.036 means 33.010 trillion dollars a year at the pace of that quarter. The four parts are consumer spending (PCEC, the QUARTERLY series: FRED's PCE is monthly), private investment (GPDI), government spending and investment (GCE) and net exports (NETEXP, exports EXPGS minus imports IMPGS). Real growth (A191RL1Q225SBEA) is the change of real GDP, prices held fixed, from the quarter before at an annual rate, and the four contributions (percentage points at an annual rate) say how much of it each part supplied.
Each series is asked for ALONE, never in a combined request: with several ids and one start date FRED applies the date to the FIRST series only and gives every other series in full, without an error (found 2026-11-18 while reading the JOLTS series).
Checks, set from the whole real record (319 quarters from 1947-Q1, 318 of growth and contributions) before any test was written: all twelve series cover the same quarters and end in the same one, the quarters are dated the 1st of January, April, July or October and follow each other, every level and every rate of growth lies inside a range set well outside the real one, GDP equals the four parts to within 2 to the power -8 billion (the largest real gap is 0.002 and five values each rounded to 0.001 can differ by 0.0025), net exports equal exports minus imports to within 2 to the power -9 (real 0.001, bound 0.0015), and real growth equals the sum of the four contributions to within 9/128 point (real 0.07 = half a unit of the total's decimal plus four halves of the contributions' second decimal). All three tolerances are exact in binary and are checked over every quarter downloaded, because the identities have no exception.
NOT checked, and said so: nominal against real GDP (different price bases), and any bound on a quarter's move (the second and third quarters of 2020 are the real extremes). A failure says so and shows nothing.
It describes what already happened: it is not a market signal or a forecast. The newest quarter is revised in later releases.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .failreason import fail_reason
from .fincond import parse
from .jolts import _num

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE = "U.S. Bureau of Economic Analysis, National Income and Product Accounts (GDP by expenditure and contributions to real growth), via FRED, St. Louis Fed (official, free public data)"
PAGE = "https://fred.stlouisfed.org/series/GDP"
LEVELS = {"GDP": "gross domestic product", "PCEC": "consumer spending", "GPDI": "private investment", "GCE": "government spending", "NETEXP": "net exports", "EXPGS": "exports", "IMPGS": "imports"}
GROWTH = "A191RL1Q225SBEA"
CONTRIBUTIONS = {"DPCERY2Q224SBEA": "consumer spending", "A006RY2Q224SBEA": "private investment", "A822RY2Q224SBEA": "government spending", "A019RY2Q224SBEA": "net exports"}
SERIES = [*LEVELS, GROWTH, *CONTRIBUTIONS]
PARTS = (("consumption", "Consumer spending", "PCEC", "DPCERY2Q224SBEA"), ("investment", "Private investment", "GPDI", "A006RY2Q224SBEA"),
         ("government", "Government spending", "GCE", "A822RY2Q224SBEA"), ("net_exports", "Net exports", "NETEXP", "A019RY2Q224SBEA"))      # a part, its level series and its contribution series
LEVEL_LIMITS = {"GDP": (5_000.0, 60_000.0), "PCEC": (3_000.0, 40_000.0), "GPDI": (1_000.0, 12_000.0), "GCE": (1_000.0, 12_000.0),
                "NETEXP": (-3_000.0, 500.0), "EXPGS": (500.0, 8_000.0), "IMPGS": (700.0, 9_000.0)}      # billions; the real ranges since 2000 are inside (GDP 10,002 to 33,010, net exports -1,217 to -357)
GROWTH_LIMITS = (-40.0, 50.0)                    # percent; the real record runs from -28.0 (2020-Q2) to 34.9 (2020-Q3)
CONTRIBUTION_LIMIT = 40.0                        # points, either sign; the real ones run from -21.62 to 24.95
NOMINAL_TOLERANCE = 2 ** -8                      # billions: five values each rounded to 0.001 differ by at most 0.0025; the real largest gap is 0.002; exact in binary
NETEXP_TOLERANCE = 2 ** -9                       # billions: three values each rounded to 0.001 differ by at most 0.0015; the real largest gap is 0.001; exact in binary
CONTRIBUTION_TOLERANCE = 9 / 128                 # points: 0.05 for the total's decimal plus 4 x 0.005 for the contributions' second decimal = 0.07, the real largest gap; exact in binary
MIN_QUARTERS = 40
HISTORY_QUARTERS = 40
RECENT_QUARTERS = 6
OVERDUE_AFTER_DAYS = 240                         # from the 1st of the observed quarter: the next quarter's first estimate comes about 211 days after it (late January for the third quarter), so 29 days of slack
TTL = 6 * 3600.0
FAIL_TTL = 120.0
LOOKBACK_DAYS = 4200                             # about 11.5 years: 45 quarters today, enough for ten years of history


def _name(sid: str) -> str:
    if sid == GROWTH:
        return "real GDP growth"
    return LEVELS[sid] if sid in LEVELS else f"{CONTRIBUTIONS[sid]} contribution"


def _qlabel(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _quarters_back(d: date, n: int) -> date:
    i = d.year * 4 + (d.month - 1) // 3 - n
    return date(i // 4, (i % 4) * 3 + 1, 1)


def _range(values: dict[date, float], now: float, first: date) -> dict:
    """Lowest, highest (the earliest quarter when several are equal) and the share of quarters strictly lower than `now`, over the quarters in `values`."""
    lo, hi = min(values, key=values.get), max(values, key=values.get)
    return {"quarters": len(values), "first": _qlabel(first), "lowest": {"value": round(values[lo], 2), "quarter": _qlabel(lo)}, "highest": {"value": round(values[hi], 2), "quarter": _qlabel(hi)},
            "share_lower_pct": round(100 * sum(1 for v in values.values() if v < now) / len(values))}


def _check(data: dict[str, dict[date, float]]) -> tuple[list[date], dict]:
    base = data["GDP"]
    if len({max(data[sid]) for sid in SERIES}) != 1:
        raise ValueError("the GDP series end in different quarters")
    for sid in SERIES:
        if set(data[sid]) != set(base):
            raise ValueError(f"the {_name(sid)} series covers different quarters than gross domestic product")
    quarters = sorted(base)
    if any(d.day != 1 or d.month not in (1, 4, 7, 10) for d in quarters):
        raise ValueError("a GDP date is not the 1st of a quarter")
    for a, b in zip(quarters, quarters[1:]):
        if _quarters_back(b, 1) != a:
            raise ValueError(f"the GDP quarters skip a quarter after {_qlabel(a)}")
    if len(quarters) < MIN_QUARTERS:
        raise ValueError(f"GDP covers {len(quarters)} quarters, fewer than the {MIN_QUARTERS} expected")
    for sid, (lo, hi) in LEVEL_LIMITS.items():
        for d in quarters:
            v = data[sid][d]
            if not (lo <= v <= hi):
                raise ValueError(f"the {_name(sid)} of {_num(v)} billion in {_qlabel(d)} is outside {_num(lo)} to {_num(hi)}")
    lo, hi = GROWTH_LIMITS
    for d in quarters:
        v = data[GROWTH][d]
        if not (lo <= v <= hi):
            raise ValueError(f"real GDP growth of {v:g}% in {_qlabel(d)} is outside {lo:g} to {hi:g}")
    for sid in CONTRIBUTIONS:
        for d in quarters:
            v = data[sid][d]
            if abs(v) > CONTRIBUTION_LIMIT:
                raise ValueError(f"the {_name(sid)} of {v:g} points in {_qlabel(d)} is outside -{CONTRIBUTION_LIMIT:g} to {CONTRIBUTION_LIMIT:g}")
    nominal = netexp = contrib = 0.0
    for d in quarters:
        gap = abs(data["GDP"][d] - data["PCEC"][d] - data["GPDI"][d] - data["NETEXP"][d] - data["GCE"][d])
        if gap > NOMINAL_TOLERANCE:
            raise ValueError(f"the four parts differ from GDP by {gap:.3f} billion in {_qlabel(d)}, over {NOMINAL_TOLERANCE:g}")
        nominal = max(nominal, gap)
    for d in quarters:
        gap = abs(data["NETEXP"][d] - (data["EXPGS"][d] - data["IMPGS"][d]))
        if gap > NETEXP_TOLERANCE:
            raise ValueError(f"exports minus imports differ from net exports by {gap:.3f} billion in {_qlabel(d)}, over {NETEXP_TOLERANCE:g}")
        netexp = max(netexp, gap)
    for d in quarters:
        gap = abs(data[GROWTH][d] - sum(data[sid][d] for sid in CONTRIBUTIONS))
        if gap > CONTRIBUTION_TOLERANCE:
            raise ValueError(f"the four contributions differ from real growth by {gap:.3f} points in {_qlabel(d)}, over {CONTRIBUTION_TOLERANCE:g}")
        contrib = max(contrib, gap)
    return quarters, {"quarters_checked": len(quarters), "first_quarter": _qlabel(quarters[0]), "last_quarter": _qlabel(quarters[-1]),
                      "largest_gdp_gap": round(nominal, 4), "largest_net_exports_gap": round(netexp, 4), "largest_contribution_gap": round(contrib, 4)}


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    quarters, detail = _check(data)
    last = quarters[-1]
    window = quarters[-HISTORY_QUARTERS:]
    before, ago = _quarters_back(last, 1), _quarters_back(last, 4)
    gdp, growth = data["GDP"], data[GROWTH]
    age = (today - last).days

    def change(a: float, b: float) -> float:
        return round(100.0 * (a / b - 1.0), 2)

    return {"available": True, "source": SOURCE, "url": PAGE, "date": last.isoformat(), "quarter": _qlabel(last), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "gdp": {"level_billions": gdp[last], "change_billions": round(gdp[last] - gdp[before], 3), "change_pct": change(gdp[last], gdp[before]), "change_year_pct": change(gdp[last], gdp[ago])},
            "growth": {"pct": growth[last], "quarter_before_pct": growth[before], "year_ago_pct": growth[ago], "range": _range({d: growth[d] for d in window}, growth[last], window[0]),
                       "contributions_sum_points": round(sum(data[ct][last] for _, _, _, ct in PARTS), 2)},
            "components": [{"key": key, "label": label, "level_billions": data[lv][last], "share_pct": round(100.0 * data[lv][last] / gdp[last], 1), "contribution_points": data[ct][last]} for key, label, lv, ct in PARTS],
            "trade": {"exports_billions": data["EXPGS"][last], "imports_billions": data["IMPGS"][last]},
            "recent": [{"quarter": _qlabel(q), "growth_pct": growth[q]} for q in quarters[-RECENT_QUARTERS:]],
            "detail": detail,
            "checks": {"quarters_in_a_row": True, "range_ok": True, "parts_add_up_ok": True, "net_exports_ok": True, "contributions_add_up_ok": True},
            "note": ("The quarterly National Income and Product Accounts of the US Bureau of Economic Analysis. "
                     "Gross domestic product (GDP) is the value of what the country produced, counted by what it was spent on: consumer spending, private investment, government spending and investment, "
                     "and net exports (exports minus imports, below zero when the country buys more from abroad than it sells). "
                     "Levels are in billions of dollars at a seasonally adjusted annual rate and in the prices of the time. "
                     "Real growth is the change in GDP with prices held fixed, from the quarter before, at an annual rate; each part's contribution to it is in percentage points. "
                     "The newest quarter is revised in later releases; each figure carries its quarter. "
                     "Plain checks: the units are the ones assumed and no quarter is missing; the ranges, the sums and the contributions rebuilt from the parts are in the Check line. "
                     "This describes the economy that already happened: it is not a market signal or a forecast.")}


class UsGdp:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _fetch(self, c: httpx.AsyncClient, sid: str) -> dict[date, float]:
        # One series per request: with several ids a single cosd applies to the first series only. No custom User-Agent: FRED stalls and drops connections for an unfamiliar one (seen 2026-11-12) and answers the client's default one fast.
        r = await c.get(URL, params={"id": sid, "cosd": (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return parse(r.text, sid)

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real US GDP figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._fetch(c, sid) for sid in SERIES])
            res = {**base, **summarize(dict(zip(SERIES, got)), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US GDP figures could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
