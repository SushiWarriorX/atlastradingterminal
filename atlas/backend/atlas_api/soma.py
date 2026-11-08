"""What the Federal Reserve holds: the System Open Market Account (SOMA), weekly, from the Federal Reserve Bank of New York (free, no key).

How to read it: the Fed's holdings of US Treasuries and mortgage-backed securities are the largest part of its balance sheet. When the total falls, the Fed is letting securities mature without
replacing them (often called balance-sheet runoff or quantitative tightening); when it rises, the Fed is buying. This shows the size and mix of the holdings and how they have changed. It describes
the Fed's own portfolio: it is not a market signal or a forecast. Amounts are face value (inflation compensation on inflation-protected bonds is left out, as in the source's own total).
Shown with its date; a failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import httpx

URL = "https://markets.newyorkfed.org/api/soma/summary.json"
SOURCE = "Federal Reserve Bank of New York, System Open Market Account holdings (official, free public data)"
PAGE = "https://www.newyorkfed.org/markets/soma-holdings"
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 14                    # published weekly
PARTS = ["bills", "notesbonds", "tips", "frn", "mbs", "cmbs", "agencies"]
HISTORY_WEEKS = 104


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0                                      # the source leaves a part empty ("") when the Fed holds none of it


def parse(payload: dict) -> list[dict]:
    """Weekly rows oldest first: {date, total and each part in dollars}. Rows without a date or a positive total are dropped."""
    rows = []
    for r in (payload.get("soma") or {}).get("summary") or []:
        try:
            d = date.fromisoformat(r["asOfDate"])
            total = float(r["total"])
        except (KeyError, TypeError, ValueError):
            continue
        if total <= 0:
            continue
        rows.append({"date": d, "total": total, **{k: _num(r.get(k)) for k in PARTS}})
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 60:
        raise ValueError("the source returned too few weeks to compare")
    return rows


def _at_or_before(rows: list[dict], target: date) -> dict | None:
    """The latest row on or before `target`, but only if it is within a week of it (otherwise there is nothing to compare with)."""
    cand = [r for r in rows if r["date"] <= target]
    return cand[-1] if cand and (target - cand[-1]["date"]).days <= 7 else None


def summarize(rows: list[dict], today: date) -> dict:
    last = rows[-1]
    b = lambda v: round(v / 1e9, 1)
    changes = []
    for label, days in (("1 week", 7), ("4 weeks", 28), ("13 weeks", 91), ("52 weeks", 364)):
        past = _at_or_before(rows, last["date"] - timedelta(days=days))
        changes.append({"period": label, "since": past["date"].isoformat() if past else None, "change_billions": b(last["total"] - past["total"]) if past else None,
                        "change_pct": round((last["total"] / past["total"] - 1) * 100, 2) if past else None})
    peak = max(rows, key=lambda r: r["total"])
    mix = [("Treasury bills", last["bills"]), ("Treasury notes and bonds", last["notesbonds"]), ("Inflation-protected Treasuries (TIPS)", last["tips"]), ("Floating-rate Treasuries", last["frn"]),
           ("Mortgage-backed securities", last["mbs"] + last["cmbs"]), ("Agency debt", last["agencies"])]
    treasuries = last["bills"] + last["notesbonds"] + last["tips"] + last["frn"]
    age = (today - last["date"]).days
    return {"available": True, "date": last["date"].isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE,
            "total_billions": b(last["total"]), "treasuries_billions": b(treasuries), "mbs_billions": b(last["mbs"] + last["cmbs"]),
            "mix": [{"name": n, "billions": b(v), "share_pct": round(v / last["total"] * 100, 1)} for n, v in mix],
            "changes": changes, "peak_billions": b(peak["total"]), "peak_date": peak["date"].isoformat(),
            "from_peak_billions": b(last["total"] - peak["total"]), "from_peak_pct": round((last["total"] / peak["total"] - 1) * 100, 1),
            "history": [{"date": r["date"].isoformat(), "total_billions": b(r["total"])} for r in rows[-HISTORY_WEEKS:]],
            "note": "The Fed's holdings of Treasuries and mortgage-backed securities, weekly, at face value. A falling total means the Fed is letting securities mature without replacing them; a rising "
                    "one means it is buying. This describes the Fed's own portfolio: it is not a market signal or a forecast."}


class Soma:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real Fed holdings are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=60)
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
