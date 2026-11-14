"""Average interest rate the US government pays on its debt, by type of security (US Treasury FiscalData, "Average Interest Rates on U.S. Treasury Securities", free, no key).

How to read it: this is the average rate on ALL debt currently outstanding, month by month. Old low-rate debt stays in the average until it matures, so it moves slowly and lags today's market
yields (for current yields see the yield curve). A rising average means older cheap debt is being replaced by newer, costlier debt. It describes what the Treasury pays on what it already owes:
it is not a market signal or a forecast. Shown with the month it is for; a failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates?sort=-record_date&page%5Bsize%5D=260"
SOURCE = "US Treasury FiscalData, Average Interest Rates on U.S. Treasury Securities (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/average-interest-rates-treasury-securities/average-interest-rates-on-u-s-treasury-securities"
ROWS = [("Treasury Bills", "Bills"), ("Treasury Notes", "Notes"), ("Treasury Bonds", "Bonds"), ("Treasury Inflation-Protected Securities (TIPS)", "Inflation-protected (TIPS)"),
        ("Treasury Floating Rate Notes (FRN)", "Floating-rate notes"), ("Total Marketable", "All marketable debt"), ("Total Interest-bearing Debt", "All interest-bearing debt")]
HEADLINE = "Total Interest-bearing Debt"
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 50


def parse(payload: dict) -> dict[str, dict[date, float]]:
    """{security: {month end date: average rate in percent}} for the securities we show."""
    wanted = {k for k, _ in ROWS}
    out: dict[str, dict[date, float]] = {}
    for r in payload.get("data") or []:
        try:
            name = r["security_desc"]
            if name not in wanted:
                continue
            out.setdefault(name, {})[date.fromisoformat(r["record_date"])] = float(r["avg_interest_rate_amt"])
        except (KeyError, TypeError, ValueError):
            continue
    if len(out.get(HEADLINE, {})) < 3 or len(out) < 4:
        raise ValueError("the source returned too few months or securities to compare")
    return out


def _month_back(d: date, months: int) -> tuple[int, int]:
    i = d.year * 12 + (d.month - 1) - months
    return i // 12, i % 12 + 1


def summarize(data: dict[str, dict[date, float]], today: date) -> dict:
    newest = max(data[HEADLINE])
    rows = []
    for key, label in ROWS:
        s = data.get(key)
        if not s or newest not in s:
            continue
        find = lambda back: next((v for d, v in s.items() if (d.year, d.month) == _month_back(newest, back)), None)
        prev, year = find(1), find(12)
        rows.append({"name": label, "rate": round(s[newest], 3), "change_month": round(s[newest] - prev, 3) if prev is not None else None, "change_year": round(s[newest] - year, 3) if year is not None else None})
    head = data[HEADLINE]
    age = (today - newest).days
    return {"available": True, "date": newest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "rows": rows,
            "history": [{"date": d.isoformat(), "rate": round(v, 3)} for d, v in sorted(head.items())[-16:]],
            "note": "The average rate on all debt now outstanding, by type of security. Old low-rate debt stays in the average until it matures, so it moves slowly and lags current market yields. "
                    "It describes what the Treasury pays on what it already owes: it is not a market signal or a forecast. Percent per year; changes are in percentage points."}


class AvgRates:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real Treasury interest rates are not shown because made-up values would look real."}
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
