"""Federal Reserve liquidity operations from the New York Fed: how much cash is parked at the Fed overnight (reverse repo) and how much the Fed lent against Treasuries and other collateral
(standing repo). Free official data, no key.

How to read it: reverse repo take-up is spare cash that money funds and others leave with the Fed instead of lending elsewhere; a big fall means that cash has been put to work or has gone.
Standing repo usage is the opposite direction: banks and dealers borrowing from the Fed. It is normally close to zero, and bursts of use have appeared when short-term funding markets were
tight. Both are descriptions of the plumbing, not market signals or forecasts. Amounts are what the Fed accepted in each operation (all operations on a date are added up); a date with no
operation of a kind shows zero for it. Shown with its date; a failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = "https://markets.newyorkfed.org/api/rp/all/all/results/last/120.json"
SOURCE = "Federal Reserve Bank of New York, repo and reverse repo operations (official, free public data)"
TTL = 1800.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 6
B = 1e9


def parse(payload: dict) -> list[dict]:
    """Per operation date: reverse repo accepted and repo accepted, in dollars, oldest first."""
    ops = (payload.get("repo") or {}).get("operations") or []
    days: dict[date, dict] = {}
    for o in ops:
        try:
            if o.get("auctionStatus") != "Results":
                continue                                           # an operation that has not finished has no result yet
            d = date.fromisoformat(o["operationDate"])
            amt = float(o["totalAmtAccepted"])
            kind = {"Reverse Repo": "reverse_repo", "Repo": "repo"}.get(o["operationType"])
            if kind is None:
                continue
            row = days.setdefault(d, {"date": d, "reverse_repo": 0.0, "repo": 0.0, "repo_ops": 0, "reverse_ops": 0})
            row[kind] += amt
            row["repo_ops" if kind == "repo" else "reverse_ops"] += 1
        except (KeyError, TypeError, ValueError):
            continue
    out = sorted(days.values(), key=lambda r: r["date"])
    if len(out) < 5:
        raise ValueError("the source returned too few operation dates to compare")
    return out


def summarize(days: list[dict], today: date) -> dict:
    last, prev = days[-1], days[-2]
    window = days[-21:]                                           # about a month of business days
    rr = [d["reverse_repo"] for d in window]
    rp = [d["repo"] for d in window]
    age = (today - last["date"]).days
    peak = max(window, key=lambda d: d["reverse_repo"])
    return {"available": True, "date": last["date"].isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE,
            "reverse_repo": {"billions": round(last["reverse_repo"] / B, 3), "previous_day_billions": round(prev["reverse_repo"] / B, 3), "change_billions": round((last["reverse_repo"] - prev["reverse_repo"]) / B, 3),
                             "average_billions": round(sum(rr) / len(rr) / B, 3), "highest_billions": round(peak["reverse_repo"] / B, 3), "highest_date": peak["date"].isoformat(), "dates_in_window": len(window)},
            "repo": {"billions": round(last["repo"] / B, 3), "window_total_billions": round(sum(rp) / B, 3), "days_used": sum(1 for x in rp if x > 0), "highest_billions": round(max(rp) / B, 3), "dates_in_window": len(window)},
            "history": [{"date": d["date"].isoformat(), "reverse_repo_billions": round(d["reverse_repo"] / B, 3), "repo_billions": round(d["repo"] / B, 3)} for d in days[-40:]],
            "note": "Reverse repo is cash parked at the Fed overnight; repo is cash the Fed lent out. Standing repo is normally near zero and use has appeared in bursts when short-term funding was tight. "
                    "These describe the plumbing of the money market: they are not market signals or forecasts. Amounts are what the Fed accepted, in billions of dollars."}


class FedOps:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": "https://www.newyorkfed.org/markets/desk-operations/reverse-repo"}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: real Fed operations are not shown because made-up values would look real."}
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
            res = {**base, "available": False, "reason": f"The New York Fed could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
