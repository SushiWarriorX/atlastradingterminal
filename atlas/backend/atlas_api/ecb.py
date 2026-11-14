"""Foreign exchange from the European Central Bank's euro reference rates: how the US dollar is doing against the major currencies. Free official data, no key.

The ECB publishes, every business day at about 14:15 Central European Time, the value of one euro in 30-odd currencies. The dollar pairs here are calculated from those
(for example dollars-per-yen = euros-per-dollar-rate divided by yen-per-euro). They are reference rates for information, not tradable quotes, and they come once a day, so they can
differ from live prices by a little or a lot on a busy day. "Dollar vs" is the change in how many units of the other currency one dollar buys: up means the dollar got stronger.
A failure says so and shows nothing; demo mode invents nothing.
"""
from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime, timezone

import httpx

URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD+JPY+GBP+CHF+CNY+CAD+AUD.EUR.SP00.A"
SOURCE = "European Central Bank euro reference rates (official, free public data); dollar pairs are calculated from them"
TTL = 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 5
# (label, currency, how the pair is quoted). "per_usd": units of the currency per 1 USD. "usd_per": USD per 1 unit of the currency. EUR/USD is quoted as USD per euro.
PAIRS = [("EUR/USD", "EUR", "usd_per"), ("USD/JPY", "JPY", "per_usd"), ("GBP/USD", "GBP", "usd_per"), ("USD/CHF", "CHF", "per_usd"), ("USD/CNY", "CNY", "per_usd"), ("USD/CAD", "CAD", "per_usd"), ("AUD/USD", "AUD", "usd_per")]


def parse(text: str) -> dict[str, list[tuple[date, float]]]:
    """Euro-based series by currency, oldest first, from the ECB's CSV."""
    out: dict[str, list[tuple[date, float]]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        try:
            if r["CURRENCY_DENOM"] != "EUR":
                continue
            v = float(r["OBS_VALUE"])
            if v > 0:
                out.setdefault(r["CURRENCY"], []).append((date.fromisoformat(r["TIME_PERIOD"]), v))
        except (KeyError, ValueError):
            continue
    for k in out:
        out[k].sort()
    if "USD" not in out or len(out["USD"]) < 10:
        raise ValueError("the source returned no usable dollar rate")
    return out


def usd_per_unit(series: dict[str, list[tuple[date, float]]], ccy: str) -> dict[date, float]:
    """Dollars per one unit of `ccy` on each day both rates exist. EUR itself is just the USD-per-euro rate."""
    usd = dict(series["USD"])
    if ccy == "EUR":
        return dict(usd)
    other = dict(series.get(ccy) or {})
    return {d: usd[d] / other[d] for d in other if d in usd}


def build(series: dict[str, list[tuple[date, float]]], today: date) -> dict:
    rows, latest = [], None
    for label, ccy, quote in PAIRS:
        up = usd_per_unit(series, ccy)
        days = sorted(up)
        if len(days) < 2:
            continue
        d = days[-1]
        latest = max(latest, d) if latest else d

        def rate(x):                       # the pair as it is conventionally quoted
            return up[x] if quote == "usd_per" else 1.0 / up[x]

        def dollar_strength(a, b):         # change in units of the currency per dollar: up = dollar stronger
            return ((1.0 / up[a]) / (1.0 / up[b]) - 1) * 100
        prev = days[-2]
        month = next((x for x in reversed(days) if (d - x).days >= 28), None)
        rows.append({"pair": label, "currency": ccy, "rate": round(rate(d), 4 if ccy != "JPY" else 2), "date": d.isoformat(), "dollar_vs_1d_pct": round(dollar_strength(d, prev), 2),
                     "dollar_vs_30d_pct": None if month is None else round(dollar_strength(d, month), 2), "compared_with_30d": month.isoformat() if month else None})
    if not rows:
        raise ValueError("no currency pair could be calculated")
    age = (today - latest).days
    up_n = sum(1 for r in rows if r["dollar_vs_30d_pct"] is not None and r["dollar_vs_30d_pct"] > 0)
    n30 = sum(1 for r in rows if r["dollar_vs_30d_pct"] is not None)
    return {"available": True, "date": latest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "pairs": rows,
            "breadth": {"stronger_30d": up_n, "of": n30}, "source": SOURCE, "url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
            "note": "Reference rates published once a day by the ECB, for information, not tradable quotes; live prices can differ. 'Dollar vs' is the change in how much of the other currency one dollar buys: "
                    "positive means the dollar got stronger against it. Dollar pairs are calculated from the ECB's euro rates."}


class EcbFx:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: real exchange rates are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            r = await c.get(URL, params={"lastNObservations": 45, "format": "csvdata"}, headers={"User-Agent": "ATLAS research terminal", "Accept": "text/csv"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            res = {**base, **build(parse(r.text), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, KeyError, ZeroDivisionError) as e:
            res = {**base, "available": False, "reason": f"The ECB could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
