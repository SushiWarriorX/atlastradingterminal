"""Stablecoin supply (DefiLlama): how many US-dollar stablecoins exist, and who issues them. Free public data, no key.

Why it is watched: stablecoins are the cash inside crypto. When supply grows, new dollars are being brought into crypto; when it shrinks, dollars are leaving. It is a liquidity gauge,
not a price signal: supply can grow while prices fall, and the biggest issuers (Tether and USD Coin) hold most of it.
What it is not: an official statistic. DefiLlama adds up on-chain supply reported by the issuers' contracts; counting rules differ between trackers. Shown with its date and source;
a failure says so and shows nothing; demo mode invents nothing. Only USD-pegged coins are counted here.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

CHART_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
LIST_URL = "https://stablecoins.llama.fi/stablecoins"
SOURCE = "DefiLlama stablecoin tracker (free public data, adds up on-chain supply; not an official statistic)"
TTL = 2 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 4
TOP = 6


def _day(ts) -> date:
    return datetime.fromtimestamp(int(ts), timezone.utc).date()


def parse_chart(rows: list[dict]) -> list[tuple[date, float]]:
    out = []
    for r in rows:
        try:
            v = float(r["totalCirculating"]["peggedUSD"])
            if v > 0:
                out.append((_day(r["date"]), v))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort()
    if len(out) < 40:
        raise ValueError("the source returned too little history to compare")
    return out


def chart_fact(pts: list[tuple[date, float]], today: date) -> dict:
    d, v = pts[-1]

    def back(days: int):
        ref = next((x for x in reversed(pts) if (d - x[0]).days >= days), None)
        return ref

    changes = []
    for label, days in (("7 days", 7), ("30 days", 30), ("90 days", 90), ("1 year", 365)):
        ref = back(days)
        if ref and (d - ref[0]).days <= days + 5:
            changes.append({"label": label, "ref_date": ref[0].isoformat(), "change_billions": round((v - ref[1]) / 1e9, 1), "change_pct": round((v / ref[1] - 1) * 100, 2)})
    peak = max(pts, key=lambda x: x[1])
    age = (today - d).days
    return {"date": d.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "total_billions": round(v / 1e9, 1), "changes": changes,
            "peak": {"date": peak[0].isoformat(), "total_billions": round(peak[1] / 1e9, 1), "below_peak_pct": round((v / peak[1] - 1) * 100, 1)}, "history": [{"date": x.isoformat(), "total_billions": round(y / 1e9, 1)} for x, y in pts[-90:]]}


def parse_top(payload: dict, total: float) -> list[dict]:
    rows = []
    for a in payload.get("peggedAssets") or []:
        try:
            if a.get("pegType") != "peggedUSD":
                continue
            now = float((a.get("circulating") or {})["peggedUSD"])
            if now <= 0:
                continue
            wk, mo = (a.get("circulatingPrevWeek") or {}).get("peggedUSD"), (a.get("circulatingPrevMonth") or {}).get("peggedUSD")
            rows.append({"name": a["name"], "symbol": a["symbol"], "billions": round(now / 1e9, 2), "share_pct": round(now / total * 100, 1) if total else None,
                         "change_7d_pct": round((now / float(wk) - 1) * 100, 2) if wk else None, "change_30d_pct": round((now / float(mo) - 1) * 100, 2) if mo else None})
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    rows.sort(key=lambda r: -r["billions"])
    if not rows:
        raise ValueError("the source returned no readable stablecoins")
    return rows[:TOP]


class Stablecoins:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real stablecoin supply is not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=40)
        try:
            hdr = {"User-Agent": "ATLAS research terminal"}
            r1 = await c.get(CHART_URL, headers=hdr)
            r2 = await c.get(LIST_URL, params={"includePrices": "false"}, headers=hdr)
            for r in (r1, r2):
                if r.status_code != 200:
                    raise ValueError(f"HTTP {r.status_code}")
            fact = chart_fact(parse_chart(r1.json()), now.date())
            res = {**base, "available": True, "source": SOURCE, "url": "https://defillama.com/stablecoins", **fact, "top": parse_top(r2.json(), fact["total_billions"] * 1e9),
                   "note": "Total supply of US-dollar stablecoins, the cash inside crypto. Growing supply means dollars are entering crypto; shrinking supply means they are leaving. It is a liquidity gauge, "
                           "not a price signal: supply can grow while prices fall. Totals differ slightly between trackers. The two biggest issuers hold most of the supply."}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"DefiLlama could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
