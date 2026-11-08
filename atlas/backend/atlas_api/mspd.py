"""What the US national debt is made of: the Monthly Statement of the Public Debt (US Treasury FiscalData, "Summary of Treasury Securities Outstanding", free, no key).

How to read it: total public debt outstanding split by type of security (short-term bills, notes, long-term bonds, inflation-protected, floating-rate, and non-marketable debt such as what the
government owes its own trust funds). Each row shows its size, its share of the total and its change from the previous month. A larger share in short-term bills means more of the debt has to be
refinanced soon. This is the stock of debt, month by month, as an accounting record: it is not a market signal or a forecast. Amounts are face value, in billions of dollars (the source reports millions).
Shown with the month it is for; a failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_1?sort=-record_date&page%5Bsize%5D=140"
       "&fields=record_date,security_type_desc,security_class_desc,debt_held_public_mil_amt,intragov_hold_mil_amt,total_mil_amt,src_line_nbr")
SOURCE = "US Treasury FiscalData, Monthly Statement of the Public Debt, Summary of Treasury Securities Outstanding (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/monthly-statement-public-debt/summary-of-treasury-securities-outstanding"
ROWS = [(("Marketable", "Bills"), "Bills (under a year)"), (("Marketable", "Notes"), "Notes (2 to 10 years)"), (("Marketable", "Bonds"), "Bonds (20 and 30 years)"),
        (("Marketable", "Treasury Inflation-Protected Securities"), "Inflation-protected (TIPS)"), (("Marketable", "Floating Rate Notes"), "Floating-rate notes"),
        (("Total Marketable", "_"), "All marketable debt"), (("Total Nonmarketable", "_"), "All non-marketable debt (mostly owed to government trust funds)"),
        (("Total Public Debt Outstanding", "_"), "Total public debt outstanding")]
TOTAL = ("Total Public Debt Outstanding", "_")
MARKETABLE = ("Total Marketable", "_")
BILLS = ("Marketable", "Bills")
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 50


def parse(payload: dict) -> dict[tuple[str, str], dict[date, dict[str, float]]]:
    """{(type, class): {month end: {public, intragov, total}}} in millions of dollars, for the rows we show."""
    keys = {k for k, _ in ROWS}
    out: dict[tuple[str, str], dict[date, dict[str, float]]] = {}
    for r in payload.get("data") or []:
        try:
            key = (r["security_type_desc"], r["security_class_desc"])
            if key not in keys:
                continue
            out.setdefault(key, {})[date.fromisoformat(r["record_date"])] = {"public": float(r["debt_held_public_mil_amt"]), "intragov": float(r["intragov_hold_mil_amt"]), "total": float(r["total_mil_amt"])}
        except (KeyError, TypeError, ValueError):
            continue
    if len(out.get(TOTAL, {})) < 2 or len(out) < 5:
        raise ValueError("the source returned too few months or security types to compare")
    return out


def summarize(data: dict[tuple[str, str], dict[date, dict[str, float]]], today: date) -> dict:
    newest = max(data[TOTAL])
    dates = sorted(data[TOTAL])
    prev = dates[-2]
    b = lambda m: round(m / 1000, 1)
    tot, mk = data[TOTAL][newest]["total"], data[MARKETABLE][newest]["total"] if newest in data.get(MARKETABLE, {}) else None
    rows = []
    for key, label in ROWS:
        s = data.get(key)
        if not s or newest not in s:
            continue
        v = s[newest]["total"]
        rows.append({"name": label, "billions": b(v), "share_of_total_pct": round(v / tot * 100, 1), "change_month_billions": b(v - s[prev]["total"]) if prev in s else None})
    bills = data.get(BILLS, {}).get(newest)
    first = dates[0]
    t = data[TOTAL]
    age = (today - newest).days
    return {"available": True, "date": newest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "rows": rows,
            "total_billions": b(tot), "held_by_public_billions": b(t[newest]["public"]), "held_by_government_accounts_billions": b(t[newest]["intragov"]),
            "bills_share_of_marketable_pct": round(bills["total"] / mk * 100, 1) if bills and mk else None,
            "change_since_billions": b(tot - t[first]["total"]), "since": first.isoformat(), "months_covered": len(dates),
            "history": [{"date": d.isoformat(), "total_billions": b(t[d]["total"])} for d in dates],
            "note": "Total public debt outstanding by type of security: size, share of the total and change from the previous month. Face value, billions of dollars. A larger share in short-term bills "
                    "means more debt must be refinanced soon. This is a month-end accounting record of what is owed: it is not a market signal or a forecast."}


class Mspd:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real debt breakdown is not shown because made-up values would look real."}
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
