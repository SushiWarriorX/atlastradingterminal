"""The Fed's policy rate and the overnight rates around it, from the Federal Reserve Bank of New York reference-rate API (official, free, no key).

What is shown: the effective federal funds rate (EFFR, the rate banks pay each other overnight, which the Fed steers with its target range), the target range itself, where EFFR sits inside it, the
other overnight reference rates (bank funding, two Treasury repo rates and SOFR), and when the target range last changed (found by comparing each day's published range, not typed in).
The rates are published for the previous business day. This describes where overnight money costs now: it is not a market signal or a forecast, and nothing here says what the Fed will do.
Shown with its date; a failure says so and shows nothing; if only the history is missing the rates are still shown and the history is said to be unavailable; demo mode invents nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

LATEST_URL = "https://markets.newyorkfed.org/api/rates/all/latest.json"
HISTORY_URL = "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/260.json"
SOURCE = "Federal Reserve Bank of New York, reference rates (official, free public data)"
PAGE = "https://www.newyorkfed.org/markets/reference-rates/effr"
NAMES = {"EFFR": "Effective federal funds rate (EFFR)", "OBFR": "Overnight bank funding rate (OBFR)", "TGCR": "Tri-party repo rate (TGCR)", "BGCR": "Broad general collateral rate (BGCR)",
         "SOFR": "Secured overnight financing rate (SOFR)"}
TTL = 1800.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 5


def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def parse_latest(payload: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in payload.get("refRates") or []:
        try:
            t = r["type"]
            if t not in NAMES:
                continue
            out[t] = {"date": date.fromisoformat(r["effectiveDate"]), "rate": float(r["percentRate"]), "p1": _f(r.get("percentPercentile1")), "p99": _f(r.get("percentPercentile99")),
                      "volume": _f(r.get("volumeInBillions")), "target_from": _f(r.get("targetRateFrom")), "target_to": _f(r.get("targetRateTo"))}
        except (KeyError, TypeError, ValueError):
            continue
    e = out.get("EFFR")
    if not e or e["target_from"] is None or e["target_to"] is None or len(out) < 3:
        raise ValueError("the source did not return the effective federal funds rate with its target range")
    return out


def parse_history(payload: dict) -> list[dict]:
    rows = []
    for r in payload.get("refRates") or []:
        try:
            if r.get("type") != "EFFR":
                continue
            rows.append({"date": date.fromisoformat(r["effectiveDate"]), "rate": float(r["percentRate"]), "target_from": _f(r.get("targetRateFrom")), "target_to": _f(r.get("targetRateTo"))})
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 20:
        raise ValueError("the source returned too few days of history")
    return rows


def last_target_change(hist: list[dict], today: date) -> dict | None:
    """When the target range last moved: the first day of the current range and the range before it. None if the range did not change in the window."""
    cur = (hist[-1]["target_from"], hist[-1]["target_to"])
    if None in cur:
        return None
    i = len(hist) - 1
    while i > 0 and (hist[i - 1]["target_from"], hist[i - 1]["target_to"]) == cur:
        i -= 1
    if i == 0:
        return None
    prev = (hist[i - 1]["target_from"], hist[i - 1]["target_to"])
    if None in prev:
        return None
    return {"date": hist[i]["date"].isoformat(), "days_ago": (today - hist[i]["date"]).days, "from_range": [prev[0], prev[1]], "to_range": [cur[0], cur[1]],
            "change_pp": round(cur[1] - prev[1], 2), "window_days": (hist[-1]["date"] - hist[0]["date"]).days}


def summarize(latest: dict[str, dict], hist: list[dict] | None, today: date) -> dict:
    e = latest["EFFR"]
    lo, hi = e["target_from"], e["target_to"]
    rates = []
    for k in ("EFFR", "OBFR", "TGCR", "BGCR", "SOFR"):
        r = latest.get(k)
        if r:
            rates.append({"code": k, "name": NAMES[k], "rate": r["rate"], "date": r["date"].isoformat(), "p1": r["p1"], "p99": r["p99"], "volume_billions": r["volume"]})
    prev = hist[-2] if hist and len(hist) > 1 else None
    newest = max(r["date"] for r in latest.values())
    age = (today - newest).days
    sofr = latest.get("SOFR")
    where = "inside" if lo <= e["rate"] <= hi else ("below" if e["rate"] < lo else "above")
    out = {"available": True, "date": e["date"].isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE,
           "effr": e["rate"], "effr_change_pp": round(e["rate"] - prev["rate"], 3) if prev else None, "target_low": lo, "target_high": hi, "effr_position": where,
           "effr_above_bottom_pp": round(e["rate"] - lo, 3), "sofr_minus_effr_pp": round(sofr["rate"] - e["rate"], 3) if sofr else None, "rates": rates,
           "history_available": hist is not None,
           "last_change": last_target_change(hist, today) if hist else None,
           "history": [{"date": r["date"].isoformat(), "rate": r["rate"]} for r in (hist or [])[-60:]],
           "note": "EFFR is the rate banks pay each other overnight; the Fed steers it with a target range. The other rates are overnight borrowing costs in related markets. They describe where overnight "
                   "money costs now and are published for the previous business day: not market signals or forecasts, and nothing here says what the Fed will do next."}
    if hist is None:
        out["history_reason"] = "The history needed to show when the target last changed could not be read right now."
    return out


class FedRates:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo, "url": PAGE}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real Fed rates are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            r = await c.get(LATEST_URL, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            latest = parse_latest(r.json())
            hist = None
            try:
                h = await c.get(HISTORY_URL, headers={"User-Agent": "ATLAS research terminal"})
                if h.status_code == 200:
                    hist = parse_history(h.json())
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                hist = None                                  # the rates are still worth showing; the history is said to be missing
            res = {**base, **summarize(latest, hist, now.date())}
            self._cache = (time.monotonic() + (TTL if hist is not None else FAIL_TTL), res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"The New York Fed could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
