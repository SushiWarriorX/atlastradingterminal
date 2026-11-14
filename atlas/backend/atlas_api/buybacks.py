"""US Treasury buyback operations (US Treasury FiscalData, "Treasury Buybacks: Buyback Operations", free, no key).

How to read it: since 2024 the Treasury regularly buys back some of its own older, already-issued securities for cash. Each operation has an announced maximum amount the Treasury is willing to buy
("maximum"), the amount dealers offered to sell ("offered"), and the amount the Treasury actually bought ("accepted"). A "liquidity support" buyback aims to keep the market for older securities working
smoothly; a "cash management" buyback smooths the Treasury's cash around tax dates. Buybacks are not a change in how much the government owes in the long run: they are swapped for new issuance.
The amounts are par (face) values in dollars. Operations are not scheduled every day, so a quiet week is normal. This describes what already happened: it is not a market signal or a forecast.
Shown with the operation date; a failure says so and shows nothing; demo mode invents nothing. An operation whose result is missing in the source is counted as "no result reported", never as zero.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import httpx

URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/buybacks_operations?sort=-operation_date&page%5Bsize%5D=1000"
SOURCE = "US Treasury FiscalData, Treasury Buybacks: Buyback Operations (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/furd/buybacks-operations"
PROGRAM_START = date(2024, 5, 1)                     # the current program began in May 2024; earlier rows (2000 to 2002) are a different, closed program
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 45
SECURITY_LABEL = {"Nominal Coupons": "Notes and bonds (nominal)", "TIPS": "Inflation-protected (TIPS)"}
TYPE_LABEL = {"Liquidity Support": "Liquidity support", "Cash Management": "Cash management", "Small Value": "Small value"}


def _num(x):
    try:
        return None if x in (None, "", "null") else float(x)
    except (TypeError, ValueError):
        return None


def parse(payload: dict) -> list[dict]:
    """Operations since the current program began, newest first. Dollars. A row with no usable date is refused; a row with a missing result is kept and marked (accepted is None)."""
    out = []
    for r in payload.get("data") or []:
        try:
            d = date.fromisoformat(r["operation_date"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("a row had no usable operation date")
        if d < PROGRAM_START:
            continue
        out.append({"date": d, "type": r.get("operation_type"), "security": r.get("security_type"), "bucket": r.get("maturity_bucket"),
                    "offered": _num(r.get("total_par_amt_offered")), "accepted": _num(r.get("total_par_amt_accepted")), "maximum": _num(r.get("max_par_amt_redeemed")),
                    "issues": _num(r.get("nbr_issues_accepted"))})
    if len(out) < 2:
        raise ValueError("the response did not contain at least two operations since 2024")
    return sorted(out, key=lambda o: o["date"], reverse=True)


def _b(v):
    return None if v is None else round(v / 1e9, 2)


def _window(ops: list[dict], since: date) -> dict:
    inwin = [o for o in ops if o["date"] > since]
    done = [o for o in inwin if o["accepted"] is not None and o["offered"] is not None]
    acc, off = sum(o["accepted"] for o in done), sum(o["offered"] for o in done)
    return {"operations": len(inwin), "with_result": len(done), "no_result": len(inwin) - len(done), "accepted_billions": _b(acc), "offered_billions": _b(off), "bought_share_pct": round(acc / off * 100, 1) if off else None}


def _group(ops: list[dict], since: date, key, labels=None) -> list[dict]:
    g = defaultdict(lambda: [0, 0.0, 0.0])
    for o in ops:
        if o["date"] > since and o["accepted"] is not None and o["offered"] is not None:
            k = o[key] or "Unlabelled"
            g[k][0] += 1
            g[k][1] += o["accepted"]
            g[k][2] += o["offered"]
    rows = [{"key": k, "label": (labels or {}).get(k, k), "operations": n, "accepted_billions": _b(a), "offered_billions": _b(f)} for k, (n, a, f) in g.items()]
    return sorted(rows, key=lambda r: -r["accepted_billions"])


def summarize(ops: list[dict], today: date) -> dict:
    last = ops[0]
    age = (today - last["date"]).days
    anomalies = sum(1 for o in ops if o["accepted"] is not None and ((o["offered"] is not None and o["accepted"] > o["offered"] + 1) or (o["maximum"] is not None and o["accepted"] > o["maximum"] + 1)))
    share = lambda o: round(o["accepted"] / o["offered"] * 100, 1) if o["accepted"] is not None and o["offered"] else None
    one = lambda o: {"date": o["date"].isoformat(), "type": TYPE_LABEL.get(o["type"], o["type"]), "security": SECURITY_LABEL.get(o["security"], o["security"]), "maturity": o["bucket"],
                     "offered_billions": _b(o["offered"]), "accepted_billions": _b(o["accepted"]), "maximum_billions": _b(o["maximum"]), "bought_share_pct": share(o), "issues_accepted": None if o["issues"] is None else int(o["issues"])}
    since90, since365 = today - timedelta(days=90), today - timedelta(days=365)
    return {"available": True, "date": last["date"].isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE,
            "latest": one(last), "last_90_days": _window(ops, since90), "last_365_days": _window(ops, since365),
            "by_security": _group(ops, since365, "security", SECURITY_LABEL), "by_type": _group(ops, since365, "type", TYPE_LABEL), "by_maturity": _group(ops, since365, "bucket"),
            "recent": [one(o) for o in ops[:8]], "anomalies": anomalies, "program_start": PROGRAM_START.isoformat(),
            "note": "Since May 2024 the Treasury regularly buys back older securities for cash. 'Offered' is what dealers offered to sell, 'bought' is what the Treasury accepted, in par (face) value. "
                    "Liquidity-support buybacks aim to keep the market for older securities working smoothly; cash-management buybacks smooth the Treasury's cash around tax dates. Buybacks are replaced by new issuance, "
                    "so they do not shrink the debt for good. An operation with no result in the source is counted separately, never as zero. This describes what already happened: not a market signal or a forecast."}


class Buybacks:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real buyback figures are not shown because made-up values would look real."}
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
