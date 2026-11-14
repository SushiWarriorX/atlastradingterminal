"""US Treasury General Account (TGA): the government's cash balance at the Federal Reserve, from the Daily Treasury Statement (US Treasury FiscalData, free, no key).

How to read it: when the balance rises, cash moves from the banking system and money markets into the Treasury's account (tax receipts, bond sales); when it falls, the Treasury spends
that cash back into the economy. So it is one of the plumbing measures of dollar liquidity, next to Fed reverse repo. It describes where cash sits; it is not a market signal or a forecast.
Amounts are the closing balance of each business day (the source reports millions of dollars; shown here in billions). Shown with its date; a failure says so and shows nothing;
demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
       "?filter=account_type:eq:Treasury%20General%20Account%20(TGA)%20Closing%20Balance&sort=-record_date&page%5Bsize%5D=260"
       "&fields=record_date,account_type,open_today_bal,close_today_bal")
SOURCE = "US Treasury FiscalData, Daily Treasury Statement, TGA closing balance (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/operating-cash-balance"
TTL = 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 6
MIN_DAYS = 30


def parse(payload: dict) -> list[tuple[date, float]]:
    """(date, balance in millions of dollars), oldest first. The source's balance for the closing-balance row sits in `open_today_bal` (its `close_today_bal` is the string "null")."""
    out: dict[date, float] = {}
    for r in payload.get("data") or []:
        try:
            if r.get("account_type") != "Treasury General Account (TGA) Closing Balance":
                continue
            v = r.get("open_today_bal")
            if v in (None, "null", ""):
                continue
            out[date.fromisoformat(r["record_date"])] = float(v)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    rows = sorted(out.items())
    if len(rows) < MIN_DAYS:
        raise ValueError("the source returned too few days to compare")
    return rows


def summarize(rows: list[tuple[date, float]], today: date) -> dict:
    (d, last), (_, prev) = rows[-1], rows[-2]
    window = rows[-21:]                                           # about a month of business days
    year = rows[-250:]
    b = lambda m: round(m / 1000, 1)                              # millions -> billions
    lo, hi = min(year, key=lambda r: r[1]), max(year, key=lambda r: r[1])
    month_ago = rows[-22][1] if len(rows) >= 22 else None
    age = (today - d).days
    return {"available": True, "date": d.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE,
            "balance_billions": b(last), "change_1d_billions": b(last - prev), "change_month_billions": b(last - month_ago) if month_ago is not None else None,
            "month_average_billions": b(sum(v for _, v in window) / len(window)), "dates_in_window": len(window),
            "year_low_billions": b(lo[1]), "year_low_date": lo[0].isoformat(), "year_high_billions": b(hi[1]), "year_high_date": hi[0].isoformat(), "days_in_year_range": len(year),
            "history": [{"date": x.isoformat(), "balance_billions": b(v)} for x, v in rows[-60:]],
            "note": "The Treasury General Account is the government's cash balance at the Fed. A rising balance pulls cash out of the banking system; a falling one puts it back. "
                    "It describes where cash sits: it is not a market signal or a forecast. Closing balance of each business day, in billions of dollars."}


class Tga:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real Treasury cash balance is not shown because made-up values would look real."}
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
