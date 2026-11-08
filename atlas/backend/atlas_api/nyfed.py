"""NY Fed Secured Overnight Financing Rate (SOFR): the overnight rate banks actually pay to borrow cash against Treasuries. Free public JSON from the New York Fed, no key.

Why it sits next to the Fed's target range: it shows where overnight money is really trading inside (or outside) that range, and funding stress shows up here first.
Published each business day for the previous business day, so the newest value is normally one to three days old. Shown with its date; a failure says so and shows nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/10.json"
SOURCE = "NY Fed, Secured Overnight Financing Rate (official, free public API)"
TTL = 1800.0
FAIL_TTL = 60.0
STALE_AFTER_DAYS = 5          # publication is next business day; a long weekend plus a holiday stays under this


def parse(payload: dict, today: date) -> dict:
    rows = []
    for r in payload.get("refRates") or []:
        try:
            if r.get("type") != "SOFR":
                continue
            rows.append((date.fromisoformat(r["effectiveDate"]), float(r["percentRate"]), r))
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        raise ValueError("the source returned no readable SOFR values")
    rows.sort(key=lambda x: x[0])
    d, v, raw = rows[-1]
    age = (today - d).days
    fact = {"id": "sofr", "label": "SOFR (overnight funding rate)", "value": v, "unit": "%", "obs_date": d.isoformat(), "series": "NY Fed SOFR", "changes": [],
            "freshness": {"state": "CURRENT" if age <= STALE_AFTER_DAYS else "OVERDUE", "age_days": age, "limit_days": STALE_AFTER_DAYS, "rule": f"published each business day for the day before; overdue after {STALE_AFTER_DAYS} days"},
            "percentiles": {k: raw.get(f"percentPercentile{k}") for k in ("1", "25", "75", "99")}, "volume_billions": raw.get("volumeInBillions"),
            "note": "The rate banks pay to borrow cash overnight against Treasuries. The date is the day it applies to; it is published the next business day."}
    if len(rows) >= 2:
        pd_, pv, _ = rows[-2]
        fact["changes"].append({"label": f"vs previous business day ({pd_.isoformat()})", "ref_date": pd_.isoformat(), "value": round(v - pv, 4), "unit": "percentage points"})
    return fact


class NyFedSofr:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def fact(self, today: date | None = None) -> dict:
        today = today or datetime.now(timezone.utc).date()
        if self.demo:
            return {"id": "sofr", "label": "SOFR (overnight funding rate)", "error": "Demo mode: the real rate is not shown because a made-up value would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return self._cache[1]
        c = self._client or httpx.AsyncClient(timeout=15)
        try:
            r = await c.get(URL, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            f = parse(r.json(), today)
            self._cache = (time.monotonic() + TTL, f)
            return f
        except (httpx.HTTPError, ValueError, KeyError) as e:
            f = {"id": "sofr", "label": "SOFR (overnight funding rate)", "error": f"NY Fed could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, f)
            return f
        finally:
            if self._client is None:
                await c.aclose()
