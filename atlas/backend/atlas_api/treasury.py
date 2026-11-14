"""US Treasury: the full daily par yield curve (1 month to 30 years) and total public debt outstanding. Both are free public data from the US Treasury, no key.

Why: FRED already gives the 2-year and 10-year yields. The full curve adds the short end (what the Fed is doing now) and the long end (what the market expects), and the
usual inversion checks (2s10s, 3m10y). The curve is the Treasury's official end-of-day par yield, published each business day, so it is a day old at best.
Debt is "Debt to the Penny": total public debt outstanding as of the record date.
Everything shown is read from the source or simple arithmetic on it (spreads, changes). A failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import httpx

CURVE_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
DEBT_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny"
SOURCE_CURVE = "US Treasury, Daily Treasury Par Yield Curve Rates (official, free public data)"
SOURCE_DEBT = "US Treasury FiscalData, Debt to the Penny (official, free public data)"
TENORS = [("1M", "BC_1MONTH"), ("2M", "BC_2MONTH"), ("3M", "BC_3MONTH"), ("4M", "BC_4MONTH"), ("6M", "BC_6MONTH"), ("1Y", "BC_1YEAR"), ("2Y", "BC_2YEAR"), ("3Y", "BC_3YEAR"),
          ("5Y", "BC_5YEAR"), ("7Y", "BC_7YEAR"), ("10Y", "BC_10YEAR"), ("20Y", "BC_20YEAR"), ("30Y", "BC_30YEAR")]
TTL = 3600.0
FAIL_TTL = 60.0
STALE_AFTER_DAYS = 5
NS = {"a": "http://www.w3.org/2005/Atom", "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata", "d": "http://schemas.microsoft.com/ado/2007/08/dataservices"}


def parse_curve(text: str) -> list[dict]:
    """Daily curves from the Treasury's XML feed, oldest first. Rejects documents that declare entities or a DOCTYPE (nothing legitimate here does)."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("unexpected document type declaration")
    root = ET.fromstring(text)
    out = []
    for props in root.iter("{%s}properties" % NS["m"]):
        raw = props.findtext("d:NEW_DATE", namespaces=NS)
        if not raw:
            continue
        try:
            d = date.fromisoformat(raw[:10])
        except ValueError:
            continue
        rates = {}
        for label, tag in TENORS:
            v = props.findtext(f"d:{tag}", namespaces=NS)
            try:
                rates[label] = float(v) if v not in (None, "") else None
            except ValueError:
                rates[label] = None
        if any(v is not None for v in rates.values()):
            out.append({"date": d, "rates": rates})
    out.sort(key=lambda x: x["date"])
    if not out:
        raise ValueError("the source returned no readable yield curves")
    return out


def curve_fact(days: list[dict], today: date) -> dict:
    last = days[-1]
    r = last["rates"]
    prev = days[-2] if len(days) >= 2 else None
    month = next((x for x in reversed(days) if (last["date"] - x["date"]).days >= 28), None)

    def spread(a, b, rates):
        return None if rates.get(a) is None or rates.get(b) is None else round((rates[a] - rates[b]) * 100)
    s2s10 = spread("10Y", "2Y", r)
    s3m10 = spread("10Y", "3M", r)
    age = (today - last["date"]).days
    return {"available": True, "date": last["date"].isoformat(), "age_days": age, "freshness": "CURRENT" if age <= STALE_AFTER_DAYS else "OVERDUE", "source": SOURCE_CURVE,
            "points": [{"tenor": t, "rate": r[t], "change_1d_bp": None if prev is None or r[t] is None or prev["rates"].get(t) is None else round((r[t] - prev["rates"][t]) * 100),
                        "change_1m_bp": None if month is None or r[t] is None or month["rates"].get(t) is None else round((r[t] - month["rates"][t]) * 100)} for t, _ in TENORS],
            "spreads": {"2s10s_bp": s2s10, "3m10y_bp": s3m10, "2s10s_inverted": None if s2s10 is None else s2s10 < 0, "3m10y_inverted": None if s3m10 is None else s3m10 < 0},
            "compared_with": {"previous_day": prev["date"].isoformat() if prev else None, "one_month": month["date"].isoformat() if month else None},
            "note": "Par yields on the day's closing market prices. Spreads are in basis points (100 bp = 1 percentage point). A negative spread means the curve is inverted at that point; it has often come before slowdowns, but not on a reliable schedule."}


def parse_debt(payload: dict, today: date) -> dict:
    rows = []
    for r in payload.get("data") or []:
        try:
            rows.append((date.fromisoformat(r["record_date"]), float(r["tot_pub_debt_out_amt"]), float(r["debt_held_public_amt"]), float(r["intragov_hold_amt"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        raise ValueError("the source returned no readable debt values")
    rows.sort(key=lambda x: x[0])
    d, total, pub, intra = rows[-1]
    age = (today - d).days
    out = {"available": True, "date": d.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= STALE_AFTER_DAYS else "OVERDUE", "source": SOURCE_DEBT,
           "total_trillions": round(total / 1e12, 3), "held_by_public_trillions": round(pub / 1e12, 3), "intragovernmental_trillions": round(intra / 1e12, 3), "change_vs_previous_day_billions": None, "change_vs_a_year_ago_pct": None,
           "note": "Total public debt outstanding on the record date: money owed to the public plus money the government owes its own accounts (like Social Security)."}
    if len(rows) >= 2:
        out["change_vs_previous_day_billions"] = round((total - rows[-2][1]) / 1e9, 1)
    year = next((x for x in rows if abs((d - x[0]).days - 365) <= 7), None)
    if year:
        out["change_vs_a_year_ago_pct"] = round((total / year[1] - 1) * 100, 2)
    return out


class Treasury:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        today = now.date()
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            msg = "Demo mode: the real Treasury data is not shown because made-up values would look real."
            return {**base, "curve": {"available": False, "reason": msg}, "debt": {"available": False, "reason": msg}}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=20)
        try:
            curve = await self._curve(c, today)
            debt = await self._debt(c, today)
        finally:
            if self._client is None:
                await c.aclose()
        res = {**base, "curve": curve, "debt": debt}
        self._cache = (time.monotonic() + (TTL if curve["available"] and debt["available"] else FAIL_TTL), res)
        return res

    async def _curve(self, c, today: date) -> dict:
        try:
            days: list[dict] = []
            for ym in (today.strftime("%Y%m"), (date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)).strftime("%Y%m")):     # this month and the one before, for 1-month changes
                r = await c.get(CURVE_URL, params={"data": "daily_treasury_yield_curve", "field_tdr_date_value_month": ym}, headers={"User-Agent": "ATLAS research terminal"})
                if r.status_code != 200:
                    raise ValueError(f"HTTP {r.status_code}")
                try:
                    days += parse_curve(r.text)
                except ValueError:
                    if ym == today.strftime("%Y%m"):
                        continue                   # the first day of a month can have no rows yet
                    raise
            days = sorted({x["date"]: x for x in days}.values(), key=lambda x: x["date"])
            if not days:
                raise ValueError("no readable yield curves")
            return curve_fact(days, today)
        except (httpx.HTTPError, ValueError, ET.ParseError) as e:
            return {"available": False, "reason": f"US Treasury yield curve could not be read right now ({type(e).__name__}: {str(e)[:80]})"}

    async def _debt(self, c, today: date) -> dict:
        try:
            r = await c.get(DEBT_URL, params={"sort": "-record_date", "page[size]": 380, "fields": "record_date,debt_held_public_amt,intragov_hold_amt,tot_pub_debt_out_amt"}, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            return parse_debt(r.json(), today)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            return {"available": False, "reason": f"US Treasury debt figure could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
