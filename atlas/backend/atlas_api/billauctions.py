"""US Treasury bill auction results (US Treasury FiscalData "Treasury Securities Auctions Data", free, no key).

What an auction result says: the rate the Treasury had to pay to borrow for a few weeks or months (the "investment rate" is the bill's yield on the same basis as a bond), and how many times the amount
offered was bid for (bid-to-cover). Bills are the Treasury's short-term borrowing, auctioned every week for 4, 6, 8, 13, 17 and 26 weeks and every four weeks for 52 weeks, so they are where most of the
day-to-day funding happens. A rising rate from one auction of a term to the next means buyers wanted more for the same term; a falling bid-to-cover means weaker demand than usual. The split of who bought
(primary dealers, direct bidders, indirect bidders such as foreign buyers and funds) is shown as a share of competitive awards. These describe funding auctions that already happened: they are not
market signals or forecasts. Cash management bills (irregular, short, one-off) are left out. Auctions whose date has passed but whose results are not yet in the source are listed as pending, not guessed.
Shown with dates; a failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

FIELDS = ("record_date,cusip,security_type,security_term,auction_date,issue_date,offering_amt,total_tendered,total_accepted,high_discnt_rate,high_investment_rate,bid_to_cover_ratio,reopening,"
          "cash_management_bill_cmb,comp_accepted,primary_dealer_accepted,direct_bidder_accepted,indirect_bidder_accepted")
URL = f"https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?sort=-auction_date&page%5Bsize%5D=400&filter=security_type:eq:Bill&fields={FIELDS}"
SOURCE = "US Treasury FiscalData, Treasury Securities Auctions Data (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/treasury-securities-auctions-data/treasury-securities-auctions-data"
TERMS = ["4-Week", "6-Week", "8-Week", "13-Week", "17-Week", "26-Week", "52-Week"]
TTL = 3 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 10                       # bills auction every week


def _num(x):
    try:
        return None if x in (None, "", "null") else float(x)
    except (TypeError, ValueError):
        return None


def parse(payload: dict) -> tuple[list[dict], list[dict]]:
    """(completed auctions, pending auctions), newest first. Only the standard bill terms; cash management bills are skipped. Rates are percent, amounts are dollars.
    An auction with an offering but no result yet is pending; a result with a missing rate or bid-to-cover is refused rather than skipped."""
    done, pending = [], []
    for r in payload.get("data") or []:
        if r.get("security_type") != "Bill" or r.get("security_term") not in TERMS or r.get("cash_management_bill_cmb") == "Yes":
            continue
        try:
            d = date.fromisoformat(r["auction_date"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("a row had no usable auction date")
        acc = _num(r.get("total_accepted"))
        if acc is None:
            pending.append({"term": r["security_term"], "auction_date": d, "offering": _num(r.get("offering_amt"))})
            continue
        inv, disc, btc = _num(r.get("high_investment_rate")), _num(r.get("high_discnt_rate")), _num(r.get("bid_to_cover_ratio"))
        if inv is None or disc is None or btc is None:
            raise ValueError(f"a completed {r['security_term']} auction on {d.isoformat()} had no usable rate or bid-to-cover")
        comp = _num(r.get("comp_accepted"))
        parts = [_num(r.get(k)) for k in ("primary_dealer_accepted", "direct_bidder_accepted", "indirect_bidder_accepted")]
        mix = None
        if comp and all(p is not None for p in parts):
            mix = {"dealers_pct": round(parts[0] / comp * 100, 1), "direct_pct": round(parts[1] / comp * 100, 1), "indirect_pct": round(parts[2] / comp * 100, 1), "sum_ok": abs(sum(parts) - comp) <= 1000.0}
        done.append({"term": r["security_term"], "auction_date": d, "issue_date": r.get("issue_date"), "reopening": r.get("reopening") == "Yes", "investment_rate": inv, "discount_rate": disc,
                     "btc": btc, "offering": _num(r.get("offering_amt")), "accepted": acc, "tendered": _num(r.get("total_tendered")), "mix": mix})
    if not done:
        raise ValueError("no completed bill auctions in the response")
    done.sort(key=lambda x: x["auction_date"], reverse=True)
    pending.sort(key=lambda x: x["auction_date"], reverse=True)
    return done, pending


def summarize(done: list[dict], pending: list[dict], today: date) -> dict:
    terms = []
    for t in TERMS:
        rows = [r for r in done if r["term"] == t]
        if not rows:
            continue
        cur, prev, before = rows[0], (rows[1] if len(rows) > 1 else None), rows[1:5]
        b = lambda v: None if v is None else round(v / 1e9, 1)
        terms.append({"term": t, "auction_date": cur["auction_date"].isoformat(), "reopening": cur["reopening"], "age_days": (today - cur["auction_date"]).days,
                      "investment_rate": round(cur["investment_rate"], 3), "discount_rate": round(cur["discount_rate"], 3),
                      "previous_rate": round(prev["investment_rate"], 3) if prev else None, "rate_change_bps": round((cur["investment_rate"] - prev["investment_rate"]) * 100, 1) if prev else None,
                      "bid_to_cover": round(cur["btc"], 2), "average_bid_to_cover": round(sum(r["btc"] for r in before) / len(before), 2) if before else None, "compared_with": len(before),
                      "offering_billions": b(cur["offering"]), "accepted_billions": b(cur["accepted"]), "mix": cur["mix"]})
    newest = max(r["auction_date"] for r in done)
    age = (today - newest).days
    late = [r for r in pending if r["auction_date"] <= today and (today - r["auction_date"]).days <= 30]
    return {"available": True, "date": newest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "terms": terms,
            "pending_results": [{"term": r["term"], "auction_date": r["auction_date"].isoformat(), "offering_billions": None if r["offering"] is None else round(r["offering"] / 1e9, 1)} for r in late],
            "note": "The investment rate is the bill's yield on the same basis as a bond; it is what the Treasury paid to borrow for that term. Bid-to-cover is how many times the amount offered was bid for. "
                    "Each term is compared with the previous auction of the same term and the average of the four before it. Who bought is the share of competitive awards won by primary dealers, direct bidders "
                    "and indirect bidders (foreign buyers and funds, among others). Cash management bills are left out. These describe auctions that already happened: they are not market signals or forecasts."}


class BillAuctions:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: real Treasury bill auction results are not shown because made-up values would look real."}
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
