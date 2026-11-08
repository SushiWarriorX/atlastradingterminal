"""US Treasury note and bond auction results (US Treasury FiscalData "Treasury Securities Auctions Data", free, no key).

What an auction result says: the yield the Treasury had to pay to sell the debt (high yield) and how many times the amount offered was bid for (bid-to-cover). A rising yield from one auction of
a term to the next means buyers wanted more for the same maturity; a falling bid-to-cover means weaker demand than usual. These describe a funding auction that already happened. They are not
market signals or forecasts, and nothing here says whether to buy or sell anything.

Scope: fixed-rate notes and bonds only (2, 3, 5, 7, 10, 20 and 30 years). Reopenings of an older issue (a "9-Year 10-Month" note is a reopened 10-year) are grouped with the original term.
Inflation-protected (TIPS) and floating-rate notes are left out because their yields are not comparable; bills are left out because they auction every week. Auctions whose date has passed but
whose results are not yet in the source are listed as pending, not guessed. Shown with dates; a failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timezone

import httpx

URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?sort=-auction_date&page%5Bsize%5D=150"
       "&fields=record_date,cusip,security_type,security_term,auction_date,issue_date,high_yield,bid_to_cover_ratio,offering_amt,total_accepted,reopening,inflation_index_security,floating_rate")
SOURCE = "US Treasury FiscalData, Treasury Securities Auctions Data (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/treasury-securities-auctions-data/treasury-securities-auctions-data"
TENORS = [2, 3, 5, 7, 10, 20, 30]
TTL = 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 45                       # coupon auctions come in monthly cycles, so about a month between them is normal


def tenor_of(term: str) -> int | None:
    """'9-Year 10-Month' is a reopened 10-year; '29-Year 11-Month' a reopened 30-year; '19-Year 10-Month' a reopened 20-year."""
    m = re.match(r"(\d+)-Year", term or "")
    if not m:
        return None
    years = int(m.group(1))
    if years in (9, 10):
        return 10
    if years in (19, 20):
        return 20
    if years in (29, 30):
        return 30
    return years if years in (2, 3, 5, 7) else None


def _num(x):
    try:
        return None if x in (None, "", "null") else float(x)
    except (TypeError, ValueError):
        return None


def parse(payload: dict) -> tuple[list[dict], list[dict]]:
    """(finished fixed-rate note and bond auctions, auctions with no result yet), each newest first."""
    done, pending = [], []
    for r in payload.get("data") or []:
        try:
            if r.get("security_type") not in ("Note", "Bond") or r.get("inflation_index_security") != "No" or r.get("floating_rate") != "No":
                continue
            t = tenor_of(r["security_term"])
            if t is None:
                continue
            row = {"tenor": t, "term": r["security_term"], "auction_date": date.fromisoformat(r["auction_date"]), "cusip": r.get("cusip"), "reopening": r.get("reopening") == "Yes",
                   "offering": _num(r.get("offering_amt")), "yield": _num(r.get("high_yield")), "btc": _num(r.get("bid_to_cover_ratio"))}
            (done if row["yield"] is not None and row["btc"] is not None else pending).append(row)
        except (KeyError, TypeError, ValueError):
            continue
    done.sort(key=lambda r: r["auction_date"], reverse=True)
    pending.sort(key=lambda r: r["auction_date"], reverse=True)
    if len(done) < 7:
        raise ValueError("the source returned too few finished auctions to compare")
    return done, pending


def summarize(done: list[dict], pending: list[dict], today: date) -> dict:
    tenors = []
    for t in TENORS:
        rows = [r for r in done if r["tenor"] == t]
        if not rows:
            continue
        cur, prev, before = rows[0], (rows[1] if len(rows) > 1 else None), rows[1:5]
        tenors.append({"tenor": f"{t}-year", "term": cur["term"], "auction_date": cur["auction_date"].isoformat(), "reopening": cur["reopening"], "age_days": (today - cur["auction_date"]).days,
                       "high_yield": round(cur["yield"], 3), "previous_yield": round(prev["yield"], 3) if prev else None,
                       "yield_change": round(cur["yield"] - prev["yield"], 3) if prev else None,
                       "bid_to_cover": round(cur["btc"], 2), "average_bid_to_cover": round(sum(r["btc"] for r in before) / len(before), 2) if before else None, "compared_with": len(before),
                       "offering_billions": round(cur["offering"] / 1e9, 1) if cur["offering"] else None})
    newest = max(r["auction_date"] for r in done)
    age = (today - newest).days
    late = [r for r in pending if r["auction_date"] <= today and (today - r["auction_date"]).days <= 30]
    return {"available": True, "date": newest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "tenors": tenors,
            "pending_results": [{"tenor": f"{r['tenor']}-year", "auction_date": r["auction_date"].isoformat()} for r in late],
            "note": "High yield is what the Treasury paid to sell the debt; bid-to-cover is how many times the amount offered was bid for. Compared with the previous auction of the same term and the average of the "
                    "four before it. Fixed-rate notes and bonds only. These describe auctions that already happened: they are not market signals or forecasts."}


class Auctions:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: real Treasury auction results are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            r = await c.get(URL, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            done, pending = parse(r.json())
            res = {**base, **summarize(done, pending, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"US Treasury FiscalData could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
