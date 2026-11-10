"""US Treasury borrowing from the markets: new bills, notes and bonds sold and old ones paid off (US Treasury FiscalData, Daily Treasury Statement, "Public Debt Transactions", free, no key).

How to read it: "issues" are new marketable securities (Treasury bills, notes, bonds and inflation-protected securities) sold, "redemptions" are marketable securities paid back when they matured. Net is issues minus
redemptions: how much the amount of marketable debt grew over the period. The table is published each business day with the previous day's numbers, and gives each day's amount plus the month so far and the fiscal
year so far (the fiscal year starts on October 1). Amounts are in millions of dollars in the source and shown here in billions. Two things to know: the inflation adjustment on inflation-protected securities is counted
as an "issue" even though no cash changes hands, and a day can contain small negative corrections. Debt the Treasury owes to its own trust funds (Government Account Series) and savings bonds are left out because
they are one part of the government owing another or are small. This describes what already happened: it is not a market signal or a forecast. Shown with the date; a failure says so and shows nothing; demo mode
invents nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import httpx

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/public_debt_transactions"
FIELDS = "record_date,transaction_type,security_market,security_type,security_type_desc,transaction_today_amt,transaction_mtd_amt,transaction_fytd_amt"
SOURCE = "US Treasury FiscalData, Daily Treasury Statement: Public Debt Transactions (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/public-debt-transactions"
BUCKETS = [("bills", "Treasury bills"), ("notes", "Treasury notes"), ("bonds", "Treasury bonds"), ("tips", "Inflation adjustment on TIPS (no cash changes hands)"), ("other", "Other marketable (Federal Financing Bank)")]
TTL = 3 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 7                      # the table lags by one business day; a long weekend adds a few more
TOLERANCE = 2.0                             # the source rounds each day to millions of dollars


def _num(x):
    try:
        return None if x in (None, "", "null") else float(x)
    except (TypeError, ValueError):
        return None


def bucket(security_type: str) -> str:
    s = (security_type or "")
    if s == "Bills":
        return "bills"
    if s == "Notes":
        return "notes"
    if s == "Bonds":
        return "bonds"
    if "Inflation-Protected" in s:
        return "tips"
    return "other"


def parse(payload: dict) -> dict[date, list[dict]]:
    """Marketable rows by day, amounts in millions of dollars. A marketable row with an unreadable amount refuses the response; nonmarketable rows are not read at all."""
    out: dict[date, list[dict]] = {}
    for r in payload.get("data") or []:
        if r.get("security_market") != "Marketable":
            continue
        try:
            d = date.fromisoformat(r["record_date"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("a row had no usable date")
        t, m, f = _num(r.get("transaction_today_amt")), _num(r.get("transaction_mtd_amt")), _num(r.get("transaction_fytd_amt"))
        if t is None or m is None or f is None or r.get("transaction_type") not in ("Issues", "Redemptions"):
            raise ValueError(f"unreadable row for {d.isoformat()}")
        out.setdefault(d, []).append({"type": r["transaction_type"], "bucket": bucket(r.get("security_type")), "today": t, "mtd": m, "fytd": f})
    return out


def _totals(rows: list[dict], field: str) -> dict:
    iss = {k: 0.0 for k, _ in BUCKETS}
    red = {k: 0.0 for k, _ in BUCKETS}
    for r in rows:
        (iss if r["type"] == "Issues" else red)[r["bucket"]] += r[field]
    return {"issues": iss, "redemptions": red, "issues_total": sum(iss.values()), "redemptions_total": sum(red.values())}


def summarize(latest: dict[date, list[dict]], month: dict[date, list[dict]], year_ago: dict[date, list[dict]], today: date) -> dict:
    if not latest:
        raise ValueError("no marketable rows for the newest day")
    d = max(latest)
    rows = latest[d]
    b = lambda v: round(v / 1000.0, 1)
    net = lambda t: t["issues_total"] - t["redemptions_total"]
    mtd, fytd, day = _totals(rows, "mtd"), _totals(rows, "fytd"), _totals(rows, "today")
    # Own arithmetic against the source: the days of this month must add up to the month so far the source reports for the newest day.
    check = None
    days = [x for x in month if x.year == d.year and x.month == d.month and x <= d]
    if d in month and days and min(days) <= d.replace(day=1) + timedelta(days=6):
        summed = {"Issues": 0.0, "Redemptions": 0.0}
        for x in days:
            for r in month[x]:
                summed[r["type"]] += r["today"]
        ok = abs(summed["Issues"] - mtd["issues_total"]) <= TOLERANCE * len(BUCKETS) and abs(summed["Redemptions"] - mtd["redemptions_total"]) <= TOLERANCE * len(BUCKETS)
        check = {"days": len(days), "issues_billions": b(summed["Issues"]), "redemptions_billions": b(summed["Redemptions"]), "source_issues_billions": b(mtd["issues_total"]), "source_redemptions_billions": b(mtd["redemptions_total"]), "match": bool(ok)}
    # The same day a year earlier (or the business day just before it) for comparison.
    ya_day = None
    target = d - timedelta(days=365)
    cands = [x for x in year_ago if x <= target and (target - x).days <= 5]
    if cands:
        ya_day = max(cands)
    ya = year_ago.get(ya_day) if ya_day else None
    ya_mtd, ya_fytd = (_totals(ya, "mtd"), _totals(ya, "fytd")) if ya else (None, None)
    fy = d.year + 1 if d.month >= 10 else d.year
    by = []
    for k, label in BUCKETS:
        by.append({"key": k, "label": label, "mtd_issues_billions": b(mtd["issues"][k]), "mtd_redemptions_billions": b(mtd["redemptions"][k]), "mtd_net_billions": b(mtd["issues"][k] - mtd["redemptions"][k]),
                   "fytd_net_billions": b(fytd["issues"][k] - fytd["redemptions"][k])})
    age = (today - d).days
    return {"available": True, "date": d.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "fiscal_year": fy,
            "latest_day": {"issues_billions": b(day["issues_total"]), "redemptions_billions": b(day["redemptions_total"]), "net_billions": b(net(day))},
            "month_to_date": {"issues_billions": b(mtd["issues_total"]), "redemptions_billions": b(mtd["redemptions_total"]), "net_billions": b(net(mtd)),
                              "year_ago_net_billions": b(net(ya_mtd)) if ya_mtd else None},
            "fiscal_year_to_date": {"issues_billions": b(fytd["issues_total"]), "redemptions_billions": b(fytd["redemptions_total"]), "net_billions": b(net(fytd)),
                                    "year_ago_net_billions": b(net(ya_fytd)) if ya_fytd else None},
            "year_ago_date": ya_day.isoformat() if ya_day else None, "by_security": by, "mtd_check": check,
            "note": "Issues are new marketable Treasury securities sold, redemptions are ones paid back at maturity, and net is issues minus redemptions: how much the amount of marketable debt grew. Amounts are par values. "
                    "The inflation adjustment on inflation-protected securities counts as an issue although no cash changes hands, and a day can include small corrections. Debt the Treasury owes to its own trust funds and savings "
                    "bonds are left out. The comparison is with the same point a year earlier. This describes what already happened: not a market signal or a forecast."}


class Borrowing:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def _get(self, c: httpx.AsyncClient, query: str) -> dict:
        r = await c.get(f"{BASE}?fields={FIELDS}&sort=-record_date{query}", headers={"User-Agent": "ATLAS research terminal"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        return r.json()

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real Treasury borrowing figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            newest = parse(await self._get(c, "&page%5Bsize%5D=60"))
            if not newest:
                raise ValueError("no marketable rows in the newest response")
            d = max(newest)
            month_payload, ya_payload = await asyncio.gather(
                self._get(c, f"&page%5Bsize%5D=1000&filter=record_date:gte:{d.replace(day=1).isoformat()}"),
                self._get(c, f"&page%5Bsize%5D=80&filter=record_date:lte:{(d - timedelta(days=365)).isoformat()}"))
            res = {**base, **summarize({d: newest[d]}, parse(month_payload), parse(ya_payload), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US Treasury FiscalData could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
