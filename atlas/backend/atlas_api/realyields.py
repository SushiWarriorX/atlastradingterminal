"""US Treasury real yields (TIPS) and breakeven inflation: the Treasury's official daily par yield curve for inflation-protected bonds, next to the regular par yield curve, at 5, 7, 10, 20 and 30 years.
Both are free public data from the US Treasury, no key.

Breakeven inflation = regular (nominal) yield minus real yield at the same maturity: the average yearly inflation at which a regular Treasury and an inflation-protected one would pay the same. It also includes
payment for inflation risk and for how easily each bond trades, so it is NOT a forecast of inflation. The real yield is what the market pays above inflation. Everything shown is read from the source or simple
arithmetic on it (the difference, changes against a month and a year earlier). There is no published breakeven figure to compare against, so the checks are: both curves are for the same day, every value sits in a
plausible range, and a maturity missing from either curve is left out, never filled in. It describes what already happened: it is not a market signal or a forecast. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import httpx

URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
SOURCE = "US Treasury, Daily Treasury Par Yield Curve Rates and Par Real Yield Curve Rates (official, free public data)"
PAGE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_real_yield_curve"
TENORS = ["5Y", "7Y", "10Y", "20Y", "30Y"]
NS = {"m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata", "d": "http://schemas.microsoft.com/ado/2007/08/dataservices"}
TTL = 3 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 6
REF_WINDOW_DAYS = 5          # a month-ago or year-ago day may fall on a weekend or holiday: the latest earlier day within five days is used, otherwise that comparison is left out
LO, HI = -3.0, 15.0           # a yield outside this range (in percent) is treated as a bad reading


def parse(text: str, prefix: str) -> dict[date, dict[str, float | None]]:
    """{day: {tenor: percent or None}} from the Treasury's XML feed. prefix is "BC_" for the regular curve and "TC_" for the real curve. Rejects documents with a DOCTYPE or entities."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("unexpected document type declaration")
    root = ET.fromstring(text)
    out: dict[date, dict[str, float | None]] = {}
    for props in root.iter("{%s}properties" % NS["m"]):
        raw = props.findtext("d:NEW_DATE", namespaces=NS)
        if not raw:
            continue
        try:
            d = date.fromisoformat(raw[:10])
        except ValueError:
            continue
        row: dict[str, float | None] = {}
        for t in TENORS:
            v = props.findtext(f"d:{prefix}{t[:-1]}YEAR", namespaces=NS)
            try:
                row[t] = float(v) if v not in (None, "") else None
            except ValueError:
                row[t] = None
        if any(v is not None for v in row.values()):
            out[d] = row
    if not out:
        raise ValueError("the source returned no readable yield curves")
    return out


def _bp(x: float) -> int:
    return int(round(x * 100))


def _ref(days: list[date], target: date) -> date | None:
    """The latest day on or before the target that is within REF_WINDOW_DAYS of it."""
    cands = [d for d in days if d <= target and (target - d).days <= REF_WINDOW_DAYS]
    return max(cands) if cands else None


def _month_back(d: date) -> date:
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


def _year_back(d: date) -> date:
    try:
        return date(d.year - 1, d.month, d.day)
    except ValueError:
        return date(d.year - 1, d.month, 28)


def _be(nom: dict, real: dict, d: date, t: str) -> float | None:
    n, r = nom.get(d, {}).get(t), real.get(d, {}).get(t)
    if n is None or r is None or not (LO <= n <= HI and LO <= r <= HI):
        return None
    return round(n - r, 2)


def summarize(nominal: dict, real: dict, today: date) -> dict:
    common = sorted(set(nominal) & set(real))
    if not common:
        raise ValueError("the regular and the real curve share no day")
    last = common[-1]
    m_day, y_day = _ref(common, _month_back(last)), _ref(common, _year_back(last))
    differ = max(nominal) != max(real)
    rows, skipped = [], []
    for t in TENORS:
        n, r = nominal[last].get(t), real[last].get(t)
        be = _be(nominal, real, last, t)
        if be is None:
            skipped.append(t)
            continue
        def chg(ref_day):
            b0 = _be(nominal, real, ref_day, t) if ref_day else None
            return None if b0 is None else _bp(be - b0)
        r_y = real[y_day].get(t) if y_day else None
        rows.append({"tenor": t, "nominal_pct": n, "real_pct": r, "breakeven_pct": be, "breakeven_change_1m_bp": chg(m_day), "breakeven_change_1y_bp": chg(y_day),
                     "real_change_1y_bp": None if r_y is None else _bp(r - r_y)})
    if not rows:
        raise ValueError("no maturity had both a regular and a real yield on the latest day")
    hist = [{"date": d.isoformat(), "breakeven_10y_pct": _be(nominal, real, d, "10Y")} for d in common[-40:]]
    hist = [h for h in hist if h["breakeven_10y_pct"] is not None]
    age = (today - last).days
    return {"available": True, "date": last.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "url": PAGE,
            "month_ago_date": m_day.isoformat() if m_day else None, "year_ago_date": y_day.isoformat() if y_day else None, "rows": rows, "history": hist,
            "checks": {"same_day": True, "range_ok": True, "latest_dates_differ": differ, "maturities_left_out": skipped},
            "note": ("Breakeven inflation is the regular Treasury yield minus the inflation-protected (TIPS) yield at the same maturity: the average yearly inflation at which the two would pay the same. "
                     "It also contains payment for inflation risk and for how easily each bond trades, so it is not a forecast of inflation. The real yield is what the market pays above inflation. "
                     "Both curves are the Treasury's own end-of-day figures, shown only for days present in both. There is no published breakeven figure to compare against, so the checks are that both curves "
                     "are for the same day and every value is in a plausible range. This describes what already happened: it is not a market signal or a forecast.")}


def _months(today: date) -> list[str]:
    cur = today.strftime("%Y%m")
    prev = _month_back(today.replace(day=1)).strftime("%Y%m")
    yago = _year_back(today.replace(day=1)).strftime("%Y%m")
    return [cur, prev, yago]


class RealYields:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _month(self, c: httpx.AsyncClient, data: str, ym: str, prefix: str, tolerate_empty: bool) -> dict:
        r = await c.get(URL, params={"data": data, "field_tdr_date_value_month": ym}, headers={"User-Agent": "ATLAS research terminal"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        try:
            return parse(r.text, prefix)
        except ValueError:
            if tolerate_empty:
                return {}                          # the first days of a month can have no rows yet
            raise

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real Treasury data is not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            ms = _months(now.date())
            jobs = []
            for i, ym in enumerate(ms):
                jobs.append(self._month(c, "daily_treasury_yield_curve", ym, "BC_", i == 0))
                jobs.append(self._month(c, "daily_treasury_real_yield_curve", ym, "TC_", i == 0))
            got = await asyncio.gather(*jobs)
            nominal, real = {}, {}
            for i in range(len(ms)):
                nominal.update(got[2 * i])
                real.update(got[2 * i + 1])
            res = {**base, **summarize(nominal, real, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, ET.ParseError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US Treasury real yields could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
