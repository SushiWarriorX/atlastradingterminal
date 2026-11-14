"""Interest the US government pays on the debt held by the public, by month (US Treasury FiscalData, "Interest Expense on the Public Debt Outstanding", free, no key).

How to read it: this is what the government owes in interest each month on Treasury bills, notes, bonds, inflation-protected securities (TIPS), floating rate notes and savings bonds. It is on an accrual basis,
which means interest is counted as it builds up (including the slow write-off of discounts and premiums and the inflation adjustment on TIPS), not on the day cash is paid. The inflation adjustment
can be negative in a month when prices fall, so a single month can jump around. The fiscal year runs October to September. The comparison is with the same month and the same year-to-date a year earlier.
It describes what already happened. It is not a market signal or a forecast. Rows for interest owed to government trust funds (intragovernmental) are left out on purpose: they are one part of the
government paying another. Shown with the statement month; a failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timezone

import httpx

URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/interest_expense"
       "?sort=-record_date&page%5Bsize%5D=1000&fields=record_date,expense_catg_desc,expense_group_desc,expense_type_desc,month_expense_amt,fytd_expense_amt,record_fiscal_year")
SOURCE = "US Treasury FiscalData, Interest Expense on the Public Debt Outstanding (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/interest-expense-debt-outstanding/interest-expense-on-the-public-debt-outstanding"
PUBLIC = "INTEREST EXPENSE ON PUBLIC ISSUES"
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 50                      # a month ends, and its figures follow within a few weeks
BUCKETS = [("bills", "Treasury bills"), ("notes", "Treasury notes"), ("bonds", "Treasury bonds"), ("tips", "Inflation-protected (TIPS), incl. inflation adjustment"),
           ("frn", "Floating rate notes"), ("savings", "Savings bonds"), ("other", "Other (state and local series, domestic and foreign series, misc.)")]


def _num(x):
    try:
        return None if x in (None, "", "null") else float(x)
    except (TypeError, ValueError):
        return None


def bucket(group: str, kind: str) -> str:
    """Which line of the summary one source row belongs to. Every row lands in exactly one bucket, so the buckets add up to the total."""
    g, k = (group or "").upper(), (kind or "")
    if g == "SAVINGS BONDS":
        return "savings"
    if "Inflation" in k:
        return "tips"
    if k.startswith("Treasury Bills"):
        return "bills"
    if k.startswith("Treasury Notes"):
        return "notes"
    if k.startswith("Treasury Bonds"):
        return "bonds"
    if k.startswith("Treasury Floating"):
        return "frn"
    return "other"


def parse(payload: dict) -> dict[date, dict]:
    """{month end date: {total, fytd, fiscal_year, buckets: {name: dollars}, rows}} for debt held by the public. Dollars. Rows with an unreadable amount are refused, not skipped."""
    rows = payload.get("data") or []
    out: dict[date, dict] = {}
    for r in rows:
        if r.get("expense_catg_desc") != PUBLIC:
            continue
        try:
            d = date.fromisoformat(r["record_date"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("a row had no usable date")
        m, f = _num(r.get("month_expense_amt")), _num(r.get("fytd_expense_amt"))
        if m is None or f is None:
            raise ValueError(f"unreadable amount in a row for {d.isoformat()}")
        e = out.setdefault(d, {"total": 0.0, "fytd": 0.0, "fiscal_year": int(r["record_fiscal_year"]), "buckets": defaultdict(float), "rows": 0})
        e["total"] += m
        e["fytd"] += f
        e["rows"] += 1
        e["buckets"][bucket(r.get("expense_group_desc"), r.get("expense_type_desc"))] += m
    if len(out) < 2:
        raise ValueError("the response did not contain at least two months")
    return out


def _fiscal_months_seen(months: dict[date, dict], fy: int) -> list[date]:
    return sorted(d for d, v in months.items() if v["fiscal_year"] == fy)


def summarize(months: dict[date, dict], today: date) -> dict:
    newest = max(months)
    cur = months[newest]
    b = lambda v: round(v / 1e9, 1)
    year_ago = next((d for d in months if d.year == newest.year - 1 and d.month == newest.month), None)
    prev = months.get(year_ago) if year_ago else None
    fy_months = _fiscal_months_seen(months, cur["fiscal_year"])
    # Own arithmetic against the source's own year-to-date figure. Checkable only when every month of the fiscal year so far is in the response.
    expected = (newest.month - 10) % 12 + 1                                  # October is month 1 of the fiscal year
    check = None
    if len(fy_months) == expected:
        ours = sum(months[d]["total"] for d in fy_months)
        check = {"ours_billions": b(ours), "source_billions": b(cur["fytd"]), "match": abs(ours - cur["fytd"]) < 1000.0}
    breakdown = [{"key": k, "label": label, "billions": b(cur["buckets"].get(k, 0.0)), "share_pct": round(cur["buckets"].get(k, 0.0) / cur["total"] * 100, 1) if cur["total"] else None} for k, label in BUCKETS]
    chg = lambda a, p: round((a / p - 1) * 100, 1) if p and p > 0 else None
    history = [{"date": d.isoformat(), "total_billions": b(months[d]["total"])} for d in sorted(months)][-24:]
    age = (today - newest).days
    return {"available": True, "date": newest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE,
            "fiscal_year": cur["fiscal_year"], "month_total_billions": b(cur["total"]),
            "year_ago_month_total_billions": b(prev["total"]) if prev else None, "month_change_pct": chg(cur["total"], prev["total"]) if prev else None,
            "ytd_months": expected, "ytd_total_billions": b(cur["fytd"]),
            "year_ago_ytd_billions": b(prev["fytd"]) if prev else None, "ytd_change_pct": chg(cur["fytd"], prev["fytd"]) if prev else None,
            "breakdown": breakdown, "ytd_check": check, "history": history,
            "note": "Interest the government owes on debt held by the public, counted as it builds up (accrual basis), so inflation adjustments on TIPS and the write-off of discounts and premiums are included "
                    "and a single month can jump. Interest owed to government trust funds is left out. The fiscal year runs October to September. This describes what already happened: not a market signal or a forecast."}


class InterestExpense:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real interest figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            r = await c.get(URL, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            res = {**base, **summarize(parse(r.json()), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US Treasury FiscalData could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
