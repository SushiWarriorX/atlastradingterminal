"""US federal budget: monthly receipts, outlays and the deficit, from the Monthly Treasury Statement (US Treasury FiscalData, Table 1, free, no key).

How to read it: receipts are what the government collected (mostly taxes), outlays are what it spent, and the deficit is outlays minus receipts (a negative number would be a surplus). The fiscal year runs
from October to September, so "year to date" starts each October. The comparison is with the same months of the previous fiscal year. A statement for a month is published about a week after the month ends.
These are accounting totals that describe what already happened: they are not market signals or forecasts. Shown with the statement month; a failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_1?sort=-record_date&page%5Bsize%5D=60"
SOURCE = "US Treasury FiscalData, Monthly Treasury Statement Table 1 (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/summary-of-receipts-outlays-and-the-deficit-surplus-of-the-u-s-government"
FISCAL_MONTHS = ["October", "November", "December", "January", "February", "March", "April", "May", "June", "July", "August", "September"]
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 50                      # a month ends, and its statement follows about a week later


def _num(x):
    try:
        return None if x in (None, "", "null") else float(x)
    except (TypeError, ValueError):
        return None


def parse(payload: dict) -> tuple[date, dict[int, dict[str, dict]]]:
    """(statement date, {fiscal year: {month name: {receipts, outlays}}}) for the newest statement in the response. Dollars."""
    rows = payload.get("data") or []
    try:
        newest = max(date.fromisoformat(r["record_date"]) for r in rows)
    except (KeyError, TypeError, ValueError):
        raise ValueError("no usable statement date in the response")
    rows = [r for r in rows if r.get("record_date") == newest.isoformat()]
    heads = {r["classification_id"]: int(r["classification_desc"][3:]) for r in rows if str(r.get("classification_desc", "")).startswith("FY ") and r.get("parent_id") in (None, "null")}
    out: dict[int, dict[str, dict]] = {}
    for r in rows:
        fy, name = heads.get(r.get("parent_id")), r.get("classification_desc")
        if fy is None or name not in FISCAL_MONTHS:
            continue
        rc, ou = _num(r.get("current_month_gross_rcpt_amt")), _num(r.get("current_month_gross_outly_amt"))
        if rc is None or ou is None:
            continue
        out.setdefault(fy, {})[name] = {"receipts": rc, "outlays": ou, "source_deficit": _num(r.get("current_month_dfct_sur_amt"))}
    if len(out) < 2 or not any(len(v) >= 1 for v in out.values()):
        raise ValueError("the statement did not contain two fiscal years of months")
    return newest, out


def summarize(newest: date, years: dict[int, dict[str, dict]], today: date) -> dict:
    fy = max(years)
    have = [m for m in FISCAL_MONTHS if m in years[fy]]
    if not have:
        raise ValueError("no months in the latest fiscal year")
    last = have[-1]
    idx = FISCAL_MONTHS.index(last)
    through = FISCAL_MONTHS[: idx + 1]
    b = lambda v: round(v / 1e9, 1)
    cur, prior = years[fy], years.get(fy - 1, {})
    ytd = lambda ys: (sum(ys[m]["receipts"] for m in through if m in ys), sum(ys[m]["outlays"] for m in through if m in ys), sum(1 for m in through if m in ys))
    cr, co, cn = ytd(cur)
    pr, po, pn = ytd(prior)
    comparable = pn == len(through) and cn == len(through)
    m = cur[last]
    series = []
    for y in (fy - 1, fy):
        for name in FISCAL_MONTHS:
            if name in years.get(y, {}):
                v = years[y][name]
                series.append({"fiscal_year": y, "month": name, "receipts_billions": b(v["receipts"]), "outlays_billions": b(v["outlays"]), "deficit_billions": b(v["outlays"] - v["receipts"])})
    age = (today - newest).days
    return {"available": True, "date": newest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE,
            "fiscal_year": fy, "month": last,
            "month_receipts_billions": b(m["receipts"]), "month_outlays_billions": b(m["outlays"]), "month_deficit_billions": b(m["outlays"] - m["receipts"]),
            "ytd_months": len(through), "ytd_receipts_billions": b(cr), "ytd_outlays_billions": b(co), "ytd_deficit_billions": b(co - cr),
            "prior_ytd_receipts_billions": b(pr) if comparable else None, "prior_ytd_outlays_billions": b(po) if comparable else None, "prior_ytd_deficit_billions": b(po - pr) if comparable else None,
            "history": series[-24:],
            "note": "Receipts are what the government collected, outlays what it spent; the deficit is outlays minus receipts (negative would be a surplus). The fiscal year runs October to September and the "
                    "comparison is with the same months of the year before. These are accounting totals that describe what already happened: not market signals or forecasts."}


class Mts:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real federal budget figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            r = await c.get(URL, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            newest, years = parse(r.json())
            res = {**base, **summarize(newest, years, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US Treasury FiscalData could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
