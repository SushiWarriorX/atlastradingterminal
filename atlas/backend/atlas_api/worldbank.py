"""The big picture from the World Bank: yearly economic growth, inflation and unemployment for the US and five other large economies. Free official data, no key.

What it is for: context. These are ANNUAL figures that arrive months after the year ends and are revised later, so they say how the economies have been doing, not what will happen next
or what the market is pricing. The newest year differs by country (the screen shows each country's own year). Use the monthly releases in the Macro section for anything current.
Everything shown is read from the source or simple arithmetic on it (change from the previous year). A failure of one indicator leaves the others; demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

BASE = "https://api.worldbank.org/v2/country/USA;CHN;EMU;JPN;GBR;IND/indicator"
SOURCE = "World Bank Open Data (official, free public data; annual figures, revised later)"
COUNTRIES = [("USA", "United States"), ("EMU", "Euro area"), ("CHN", "China"), ("JPN", "Japan"), ("GBR", "United Kingdom"), ("IND", "India")]
INDICATORS = [("NY.GDP.MKTP.KD.ZG", "gdp_growth", "Economic growth", "% a year", "How much the economy grew in the year, after inflation."),
              ("FP.CPI.TOTL.ZG", "inflation", "Inflation", "% a year", "How much consumer prices rose over the year."),
              ("SL.UEM.TOTL.ZS", "unemployment", "Unemployment", "% of workers", "Share of people who want a job and cannot find one (modelled estimate).")]
TTL = 12 * 3600.0
FAIL_TTL = 300.0
YEARS_BACK = 8


def parse(payload: list, name: str) -> dict[str, list[tuple[int, float]]]:
    """Per country, (year, value) pairs oldest first, without the years that have no value yet."""
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        raise ValueError(f"the source returned no readable {name} values")
    out: dict[str, list[tuple[int, float]]] = {}
    for r in payload[1]:
        try:
            if r["value"] is None:
                continue
            out.setdefault(r["countryiso3code"] or r["country"]["id"], []).append((int(r["date"]), float(r["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    for k in out:
        out[k].sort()
    if not out:
        raise ValueError(f"the source returned no readable {name} values")
    return out


def table(series: dict[str, list[tuple[int, float]]], today_year: int) -> list[dict]:
    rows = []
    for iso, name in COUNTRIES:
        pts = series.get(iso)
        if not pts:
            rows.append({"country": name, "iso": iso, "available": False})
            continue
        y, v = pts[-1]
        prev = next((p for p in reversed(pts[:-1]) if p[0] == y - 1), None)
        rows.append({"country": name, "iso": iso, "available": True, "year": y, "value": round(v, 2), "previous_year": prev[0] if prev else None, "previous_value": round(prev[1], 2) if prev else None,
                     "change": round(v - prev[1], 2) if prev else None, "years_old": today_year - y, "history": [{"year": a, "value": round(b, 2)} for a, b in pts[-6:]]})
    return rows


class WorldBank:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "source": SOURCE, "url": "https://data.worldbank.org",
                "note": "Yearly figures that arrive months after the year ends and are revised later. They describe how economies have been doing, not what the market expects. Each country's newest year can differ."}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: real World Bank data is not shown because made-up values would look real.", "indicators": []}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        out = []
        try:
            for code, key, title, unit, what in INDICATORS:
                try:
                    r = await c.get(f"{BASE}/{code}", params={"format": "json", "per_page": 300, "date": f"{now.year - YEARS_BACK}:{now.year}"}, headers={"User-Agent": "ATLAS research terminal"})
                    if r.status_code != 200:
                        raise ValueError(f"HTTP {r.status_code}")
                    out.append({"key": key, "title": title, "unit": unit, "what": what, "available": True, "rows": table(parse(r.json(), title), now.year)})
                except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
                    out.append({"key": key, "title": title, "unit": unit, "what": what, "available": False, "reason": f"World Bank {title.lower()} could not be read right now ({type(e).__name__}: {str(e)[:80]})", "rows": []})
        finally:
            if self._client is None:
                await c.aclose()
        res = {**base, "available": any(i["available"] for i in out), "indicators": out}
        if not res["available"]:
            res["reason"] = "The World Bank could not be read right now."
        self._cache = (time.monotonic() + (TTL if all(i["available"] for i in out) else FAIL_TTL), res)
        return res
