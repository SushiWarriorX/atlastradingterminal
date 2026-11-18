"""Euro-area GDP from the ECB Data Portal's public API (official, free, no key): Eurostat's quarterly national accounts for the euro area of 21 countries (fixed composition as of 1 January 2026, code `I10`), seasonally and calendar adjusted, as published in the ECB's MNA dataflow.

How to read it: real GDP growth (chain-linked volumes, reference year 2020) on the previous quarter and on the same quarter a year earlier, calculated by the ECB from Eurostat's real GDP level; and, for the newest quarter that has a breakdown, nominal GDP (current prices, millions of euro per quarter, not annualised), nominal domestic demand (`P3T5`: final consumption plus gross capital formation), exports (`P6`) and imports (`P7`), with their contributions to real growth in percentage points (calculated by the ECB). Real GDP growth arrives about 45 days after a quarter ends, the breakdown about 65 days, so the breakdown is usually one quarter behind. Revisions of earlier quarters are normal.
Why `I10` and not another code: the dataflow keeps one series per euro-area composition. The 20-country series (`I9`) stops at 2026-Q1, the 19-country one (`I8`) at 2024-Q1 and the 17 and 18-country ones (`I6`, `I7`) at 2015-Q4, and all of them answer without any error, so a key written from memory (`I9` was the first guess and it worked) would show a quarter that is two quarters old. Only `I10` is current (real GDP to 2026-Q3, the breakdown to 2026-Q2). A freshness check (OVERDUE) is what will notice the day this one stops too.
Checks, set from the whole real record (126 quarters from 1995-Q1 to 2026-Q2 for the nominal and breakdown series, 127 to 2026-Q3 for real GDP, ten series, none missing) before any test was written: every series reports the units the card assumes (levels in millions of euro, `UNIT` EUR and `UNIT_MULT` 6; the growth rates carry the ECB's labels EUR and multiplier 1 although they are percent, which the growth-from-level check below proves; the contributions `EUR_R_B1GQ` and multiplier 0); the real series end on one quarter and the breakdown series on one quarter, and the real ones are the same quarter or the next; each series has every quarter of its last 45 (no real gaps: the quarters follow each other on all 126); each figure lies in a range set around the real one (real GDP growth on the quarter -15 to 15 against a real -11.155 to +11.537, on the year -20 to 20 against -13.833 to +15.270, real GDP 1,000,000 to 6,000,000 against 2,109,034 to 3,373,329, nominal GDP 1,000,000 to 10,000,000 against 1,416,839 to 4,125,843, domestic demand 1,000,000 to 10,000,000 against 1,390,774 to 3,978,043, exports and imports 200,000 to 6,000,000 against 395,727 to 2,086,049 and 369,661 to 1,938,249, the contribution of domestic demand -15 to 15 against -11.348 to +9.873, of exports and of imports -12 to 12 against -9.091 to +6.836 and -5.172 to +9.285); nominal GDP changes by no more than -15% to +15% in a quarter (real -10.151% to +10.393%). These are plain checks on the real record, not sums.
**Three checks are the source's own arithmetic**, which show that the series fetched belong to one release, not that the figures are right. (1) The growth rates are calculated by the ECB from the real level (its metadata says PCT and YTYPCT of the level): they equal 100 times the change of the level (the real gap is 0 on all 126 and 123 quarters; tolerance 2 to the power -30, about 0.000000001); because it is by construction, it proves the unit (percent) and the alignment of the quarters, nothing about the economy. (2) Nominal GDP equals domestic demand plus exports minus imports (the real gap is at most 1.5e-8 millions of euro on all 126 quarters; tolerance 0.015625, which is 2 to the power -6, so that a gap of exactly the tolerance can be tested). (3) The contributions of domestic demand, exports and imports add up to real GDP growth on the quarter (the real gap is at most 1.8e-15 points on all 121 quarters from 1996-Q2; tolerance 2 to the power -20, about 0.000001); the contributions are calculated by the ECB, so this one is partly by construction too. All three hold on the whole record without exception, so each is applied to the whole fetched window (45 quarters).
It describes growth that already happened: it is not a market signal or a forecast. A failure says so and shows nothing. A missing value is left out, never filled in.
"""
from __future__ import annotations

import asyncio
import csv
import io
import math
import re
import statistics
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .failreason import fail_reason

BASE = "https://data-api.ecb.europa.eu/service/data/MNA/"
SOURCE = "European Central Bank, euro-area GDP and its expenditure breakdown (Eurostat quarterly national accounts, ESA 2010, euro area of 21 countries, seasonally and calendar adjusted), as published on the ECB Data Portal (official, free public data)"
GDP = "Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z."
DD = "Q.Y.I10.W0.S1.S1.D.P3T5._Z._Z._Z."
EX = "Q.Y.I10.W1.S1.S1.D.P6._Z._Z._Z."
IM = "Q.Y.I10.W1.S1.S1.C.P7._Z._Z._Z."
PAGE = BASE + GDP + "EUR.LR.G1"
# series id -> (the ECB's series key without "MNA.", the units it reports: UNIT_MEASURE and UNIT_MULT)
LEVEL, GROWTH, CONTRIB = ("EUR", "6"), ("EUR", "1"), ("EUR_R_B1GQ", "0")
SERIES = {
    "gdp_nom": (GDP + "EUR.V.N", LEVEL), "gdp_real": (GDP + "EUR.LR.N", LEVEL), "gdp_q": (GDP + "EUR.LR.G1", GROWTH), "gdp_y": (GDP + "EUR.LR.GY", GROWTH),
    "dd_nom": (DD + "EUR.V.N", LEVEL), "dd_c": (DD + "EUR_R_B1GQ.Y.GO1", CONTRIB),
    "ex_nom": (EX + "EUR.V.N", LEVEL), "ex_c": (EX + "EUR_R_B1GQ.Y.GO1", CONTRIB),
    "im_nom": (IM + "EUR.V.N", LEVEL), "im_c": (IM + "EUR_R_B1GQ.Y.GO1", CONTRIB),
}
REAL = ("gdp_real", "gdp_q", "gdp_y")                                       # end on the newest quarter of real GDP
BREAK = ("gdp_nom", "dd_nom", "ex_nom", "im_nom", "dd_c", "ex_c", "im_c")   # end on the newest quarter with a breakdown
# the four requests: the key (the OR-list `+` must reach the host unencoded) and the series each one returns
REQUESTS = (
    (GDP + "EUR.V+LR.N+G1+GY", ("gdp_nom", "gdp_real", "gdp_q", "gdp_y")),
    (DD + "EUR+EUR_R_B1GQ.V+Y.N+GO1", ("dd_nom", "dd_c")),
    (EX + "EUR+EUR_R_B1GQ.V+Y.N+GO1", ("ex_nom", "ex_c")),
    (IM + "EUR+EUR_R_B1GQ.V+Y.N+GO1", ("im_nom", "im_c")),
)
NAMES = {"gdp_nom": "nominal GDP", "gdp_real": "real GDP", "gdp_q": "real GDP growth on the previous quarter", "gdp_y": "real GDP growth on the same quarter a year earlier",
         "dd_nom": "nominal domestic demand", "dd_c": "the contribution of domestic demand to growth", "ex_nom": "nominal exports", "ex_c": "the contribution of exports to growth",
         "im_nom": "nominal imports", "im_c": "the contribution of imports to growth"}
LIMITS = {"gdp_q": (-15.0, 15.0), "gdp_y": (-20.0, 20.0), "gdp_real": (1000000.0, 6000000.0), "gdp_nom": (1000000.0, 10000000.0), "dd_nom": (1000000.0, 10000000.0),
          "ex_nom": (200000.0, 6000000.0), "im_nom": (200000.0, 6000000.0), "dd_c": (-15.0, 15.0), "ex_c": (-12.0, 12.0), "im_c": (-12.0, 12.0)}
NOMINAL_MOVE = (-15.0, 15.0)          # percent change of nominal GDP in one quarter; the real range is -10.151 to +10.393
NOMINAL_TOLERANCE = 2 ** -6           # 0.015625 millions of euro (exact in binary, so a gap of exactly the tolerance can be tested); the real gap is at most 1.5e-8
CONTRIBUTION_TOLERANCE = 2 ** -20     # about 0.000001 points (exact in binary); the real gap is at most 1.8e-15
GROWTH_TOLERANCE = 2 ** -30           # about 0.000000001 points (exact in binary); the ECB calculates growth from the level, the real gap is 0
LAST_N = 45                           # quarters fetched and checked: eleven years, so that the ten-year window and every year-on-year check have their level four quarters earlier
WINDOW_QUARTERS = 40                  # ten years
MIN_WINDOW_QUARTERS = 36
OVERDUE_AFTER_DAYS = 135              # a quarter's real GDP growth comes out about 45 days after it ends, the next quarter's about 121 days after: 135 leaves two weeks for the ECB to publish it
TTL = 6 * 3600.0
FAIL_TTL = 120.0
_QUARTER = re.compile(r"\d{4}-Q[1-4]")
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _quarter(x) -> str | None:
    """A quarter written exactly YYYY-Qn."""
    return x if isinstance(x, str) and _QUARTER.fullmatch(x) else None


def _fmt(x: float) -> str:
    return f"{x:,.4f}"


def _lim(x: float) -> str:
    return f"{x:,.0f}" if x == int(x) and abs(x) >= 1000 else f"{x:g}"


def _idx(q: str) -> int:
    """A running number for a quarter, so that the next quarter is one more."""
    return int(q[:4]) * 4 + int(q[6]) - 1


def _label(i: int) -> str:
    return f"{i // 4}-Q{i % 4 + 1}"


def _end(q: str) -> date:
    month, day = _QUARTER_END[int(q[6])]
    return date(int(q[:4]), month, day)


def parse(text: str, ids: tuple[str, ...]) -> tuple[dict[str, dict[str, float]], dict[str, tuple[str, str]], dict[str, str]]:
    """Values by series id (for example "gdp_q") and quarter, the units each series reports (the ECB's UNIT_MEASURE and UNIT_MULT) and the status of each series' newest value ("A" normal). Rows of any other series, and rows without a quarter or a number, are left out; two values for one quarter are an error."""
    values: dict[str, dict[str, float]] = {i: {} for i in ids}
    wanted = {"MNA." + SERIES[i][0]: i for i in ids}
    units: dict[str, tuple[str, str]] = {}
    newest: dict[str, tuple[str, str]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        sid, q, v = wanted.get(r.get("KEY") or ""), _quarter(r.get("TIME_PERIOD")), _num(r.get("OBS_VALUE"))
        if sid is None or q is None or v is None:
            continue
        if q in values[sid]:
            raise ValueError(f"{sid} has two values for {q}")
        values[sid][q] = v
        units[sid] = ((r.get("UNIT_MEASURE") or "").strip(), (r.get("UNIT_MULT") or "").strip())
        if sid not in newest or _idx(q) > _idx(newest[sid][0]):
            newest[sid] = (q, (r.get("OBS_STATUS") or "").strip())
    missing = [i for i in ids if not values[i]]
    if missing:
        raise ValueError("the source returned no values for " + ", ".join(missing))
    return values, units, {i: s for i, (q, s) in newest.items()}


def _window(v: dict[str, dict[str, float]], sid: str) -> list[str]:
    """The last LAST_N quarters ending on the newest quarter of the series."""
    end = max(_idx(q) for q in v[sid])
    return [_label(i) for i in range(end - LAST_N + 1, end + 1)]


def _check(v: dict[str, dict[str, float]], units: dict) -> tuple[str, str, dict]:
    for sid, u in units.items():
        if u != SERIES[sid][1]:
            raise ValueError(f"the ECB reports {NAMES[sid]} in other units than the card assumes")
    if len({max(_idx(q) for q in v[s]) for s in REAL}) != 1:
        raise ValueError("the real GDP series end on different quarters")
    if len({max(_idx(q) for q in v[s]) for s in BREAK}) != 1:
        raise ValueError("the GDP breakdown series end on different quarters")
    real_end, break_end = max(_idx(q) for q in v["gdp_q"]), max(_idx(q) for q in v["gdp_nom"])
    if real_end - break_end not in (0, 1):
        raise ValueError("real GDP and its breakdown end more than a quarter apart")
    for sid in REAL + BREAK:
        for q in _window(v, sid):
            if q not in v[sid]:
                raise ValueError(f"{NAMES[sid]} is missing for {q}")
    for sid, (lo, hi) in LIMITS.items():
        for q in _window(v, sid):
            if not (lo <= v[sid][q] <= hi):
                raise ValueError(f"{NAMES[sid]} is {_fmt(v[sid][q])} in {q}, outside {_lim(lo)} to {_lim(hi)}")
    lo, hi = NOMINAL_MOVE
    qs = _window(v, "gdp_nom")
    for a, b in zip(qs, qs[1:]):
        ch = 100 * (v["gdp_nom"][b] / v["gdp_nom"][a] - 1)
        if not (lo <= ch <= hi):
            raise ValueError(f"nominal GDP moved by {ch:+.2f}% in {b}, outside {lo:+g}% to {hi:+g}%")
    worst_growth = 0.0                                                                                   # the ECB's own arithmetic: shows the series belong together
    for sid, back in (("gdp_q", 1), ("gdp_y", 4)):
        for q in _window(v, sid):
            before = _label(_idx(q) - back)
            if before in v["gdp_real"]:
                off = v[sid][q] - 100 * (v["gdp_real"][q] / v["gdp_real"][before] - 1)
                if abs(off) > GROWTH_TOLERANCE:
                    raise ValueError(f"{NAMES[sid]} is not the change of the real GDP level in {q} (off by {off:+.9f})")
                worst_growth = max(worst_growth, abs(off))
    worst_nominal = 0.0
    for q in _window(v, "gdp_nom"):
        off = v["gdp_nom"][q] - (v["dd_nom"][q] + v["ex_nom"][q] - v["im_nom"][q])
        if abs(off) > NOMINAL_TOLERANCE:
            raise ValueError(f"nominal GDP is not domestic demand plus exports minus imports in {q} (off by {off:+.4f} millions of euro)")
        worst_nominal = max(worst_nominal, abs(off))
    worst_contrib, contrib_quarters = 0.0, 0
    for q in _window(v, "dd_c"):
        if q not in v["gdp_q"]:                                                                          # the oldest breakdown quarter is one older than the real window when real GDP is a quarter ahead
            continue
        off = v["dd_c"][q] + v["ex_c"][q] + v["im_c"][q] - v["gdp_q"][q]
        if abs(off) > CONTRIBUTION_TOLERANCE:
            raise ValueError(f"the contributions of domestic demand, exports and imports do not add up to real GDP growth in {q} (off by {off:+.6f} points)")
        worst_contrib = max(worst_contrib, abs(off))
        contrib_quarters += 1
    return _label(real_end), _label(break_end), {"quarters_checked": LAST_N, "contribution_quarters_checked": contrib_quarters, "largest_growth_gap": round(worst_growth, 12),
                                                 "largest_nominal_gap": round(worst_nominal, 9), "largest_contribution_gap": round(worst_contrib, 12)}


def _stats(g1: dict[str, float], last: str) -> dict | None:
    """The ten years up to `last`, which is the newest quarter of the series."""
    qs = [q for q in sorted(g1, key=_idx) if _idx(q) > _idx(last) - WINDOW_QUARTERS]
    if len(qs) < MIN_WINDOW_QUARTERS:
        return None
    lo, hi = min(qs, key=lambda q: g1[q]), max(qs, key=lambda q: g1[q])
    return {"quarters": len(qs), "from": qs[0], "years": 10, "median": round(statistics.median(g1[q] for q in qs), 2),
            "lowest": {"value": round(g1[lo], 2), "quarter": lo}, "highest": {"value": round(g1[hi], 2), "quarter": hi},
            "share_lower_pct": round(100 * sum(1 for q in qs if g1[q] < g1[last]) / len(qs))}


def summarize(v: dict, units: dict, status: dict[str, str], today: date) -> dict:
    real, brk, detail = _check(v, units)
    age = (today - _end(real)).days
    g1, gy, k = v["gdp_q"], v["gdp_y"], brk
    bn = lambda sid: round(v[sid][k] / 1000, 1)                                                          # millions of euro to billions
    recent = [_label(_idx(real) - i) for i in range(6)]
    return {"available": True, "source": SOURCE, "url": PAGE, "quarter": real, "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE",
            "provisional": status.get("gdp_q", "") not in ("", "A"),
            "growth": {"quarter": real, "quarter_on_quarter": round(g1[real], 2), "year_on_year": round(gy[real], 2),
                       "previous_quarter": _label(_idx(real) - 1), "year_earlier": _label(_idx(real) - 4)},
            "recent": [{"quarter": q, "quarter_on_quarter": round(g1[q], 2), "year_on_year": round(gy[q], 2)} for q in recent],
            "window": _stats(g1, real),
            "breakdown": {"quarter": k, "gdp": bn("gdp_nom"), "domestic_demand": bn("dd_nom"), "exports": bn("ex_nom"), "imports": bn("im_nom"),
                          "net_trade": round((v["ex_nom"][k] - v["im_nom"][k]) / 1000, 1), "growth": round(g1[k], 2),
                          "contributions": {"domestic_demand": round(v["dd_c"][k], 2), "exports": round(v["ex_c"][k], 2), "imports": round(v["im_c"][k], 2), "net_trade": round(v["ex_c"][k] + v["im_c"][k], 2)}},
            "detail": detail,
            "checks": {"units_ok": True, "quarters_in_a_row": True, "range_ok": True, "nominal_move_ok": True, "growth_follows_the_level_ok": True, "nominal_identity_ok": True, "contributions_add_up_ok": True},
            "note": ("Eurostat's quarterly national accounts for the euro area of 21 countries (a fixed composition as of 1 January 2026), seasonally and calendar adjusted, published on the ECB Data Portal. "
                     "Real GDP growth (chain-linked volumes) is the ECB's own calculation from Eurostat's real GDP level and comes out about 45 days after a quarter ends; the figures at current prices (billions of euro for the quarter, not annualised) and the contributions to growth come with the full breakdown about 65 days after, so they are usually one quarter behind. "
                     "The ECB keeps a separate series for each composition of the euro area, and the one for 20 countries stopped at Q1 2026, which is why this card reads the 21-country one. Earlier quarters are revised. "
                     "Checked: the units are the ones assumed, no quarter missing, every figure inside its range and nominal GDP moving by no more than 15% in a quarter (plain checks), the growth rates following from the real level (calculated by the ECB), "
                     "and two checks that are the source's own arithmetic (nominal GDP equals domestic demand plus exports minus imports, and the contributions of domestic demand, exports and imports add up to real GDP growth, in each of the last 45 quarters), which show the series belong together, not that the figures are right. "
                     "This describes growth that already happened: it is not a market signal or a forecast.")}


class EuroGdp:
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
            return {**base, "available": False, "reason": "Demo mode: the real euro-area GDP is not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
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
            res = {**base, "available": False, "reason": f"The euro-area GDP could not be read right now ({fail_reason(e)})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
