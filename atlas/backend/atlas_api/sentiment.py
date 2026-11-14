"""Crypto Fear & Greed index (alternative.me): a free, keyless daily 0-100 reading of crypto market mood.

What it is: a published composite of volatility, momentum/volume, social activity, surveys, BTC dominance and trends. What it is not: a forecast or a trading signal.
Honest limits: the methodology is the publisher's and only partly disclosed, it updates once a day, and extreme readings have stayed extreme for weeks. Shown with its
date; if the source cannot be reached the answer says so (it is never estimated). Demo mode returns nothing rather than inventing a value.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

URL = "https://api.alternative.me/fng/"
SOURCE = "alternative.me Crypto Fear & Greed Index (free public API, unofficial composite)"
TTL = 1800.0
FAIL_TTL = 60.0
BANDS = [(25, "Extreme fear"), (45, "Fear"), (55, "Neutral"), (75, "Greed"), (101, "Extreme greed")]


def band(v: int) -> str:
    return next(name for top, name in BANDS if v < top)


def parse(payload: dict, now: datetime) -> dict:
    rows = payload.get("data") or []
    pts = []
    for r in rows:
        try:
            v, t = int(r["value"]), int(r["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= v <= 100:
            pts.append((datetime.fromtimestamp(t, timezone.utc).date(), v))
    if not pts:
        raise ValueError("the source returned no readable values")
    pts.sort()
    d, v = pts[-1]
    age = (now.date() - d).days
    out = {"value": v, "label": band(v), "source_label": next((r.get("value_classification") for r in rows if str(r.get("value")) == str(v)), None), "date": d.isoformat(), "age_days": age,
           "freshness": "CURRENT" if age <= 2 else "OVERDUE", "history": [{"date": x.isoformat(), "value": y} for x, y in pts]}
    for days, name in ((1, "yesterday"), (7, "a week ago"), (30, "a month ago")):
        ref = next((y for x, y in reversed(pts) if (d - x).days >= days), None)
        out[name.replace(" ", "_")] = ref
    return out


class FearGreed:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"source": SOURCE, "url": "https://alternative.me/crypto/fear-and-greed-index/", "as_of": now.isoformat(), "demo": self.demo,
                "note": "A published mood gauge, not a forecast or a trading signal. Extreme readings can last for weeks.", "bands": "0-24 extreme fear, 25-44 fear, 45-54 neutral, 55-74 greed, 75-100 extreme greed (this app's wording)"}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real index is not shown because a made-up value would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=15)
        try:
            r = await c.get(URL, params={"limit": 31, "format": "json"}, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            res = {**base, "available": True, **parse(r.json(), now)}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError) as e:
            res = {**base, "available": False, "reason": f"alternative.me could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
