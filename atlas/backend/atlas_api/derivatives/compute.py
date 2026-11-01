"""All derivatives arithmetic (pure). Raw venue records in, comparable figures out. Every formula is stated in `basis` and nothing is estimated.

- funding_8h_pct        = rate per interval x (8 / interval hours) x 100          (what the market usually quotes)
- funding_annual_pct    = rate per interval x (8760 / interval hours) x 100      (simple, not compounded)
- basis_pct             = (mark - index) / index x 100                           (perpetual premium to the index; NOT a dated-futures basis)
- oi_usd                = open interest in BTC x mark price
- aggregate funding     = open-interest-weighted mean of the venues' annualised funding (weights = USD open interest of venues that answered)
Positive funding means longs pay shorts. A venue that failed is listed as failed and left out; coverage is always shown.
"""
from __future__ import annotations

from datetime import datetime, timezone

LIVE_SECONDS = 120
DISPERSION_WARN_PCT = 0.5


def enrich(raw: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    h = raw["funding_interval_h"]
    mark, index = raw["mark"], raw.get("index")
    ts = raw.get("ts_ms") or 0
    age = max(0.0, now.timestamp() - ts / 1000) if ts else None
    notes = list(raw.get("notes", []))
    if ts and now.timestamp() - ts / 1000 < -60:
        notes.append("the venue's timestamp is in the future: clock skew or bad data")
    status = "STALE" if age is None or age > LIVE_SECONDS else "LIVE"
    if age is None:
        notes.append("no venue timestamp: freshness unknown")
    return {"venue": raw["venue"], "ok": True, "status": status, "mark": mark, "index": index,
            "basis_pct": None if not index or index <= 0 else (mark - index) / index * 100,
            "funding_rate": raw["funding_rate"], "funding_interval_h": h,
            "funding_8h_pct": raw["funding_rate"] * (8 / h) * 100, "funding_annual_pct": raw["funding_rate"] * (8760 / h) * 100,
            "next_funding_ms": raw.get("next_funding_ms"), "oi_btc": raw["oi_btc"], "oi_usd": raw["oi_btc"] * mark,
            "age_seconds": age, "ts_ms": ts, "notes": notes}


def aggregate(rows: list[dict], expected: int) -> dict:
    ok = [r for r in rows if r.get("ok")]
    out: dict = {"venues_ok": len(ok), "venues_expected": expected, "venues_failed": [r["venue"] for r in rows if not r.get("ok")], "flags": []}
    if not ok:
        return {**out, "available": False}
    oi_usd = sum(r["oi_usd"] for r in ok)
    out.update(available=True, oi_btc=sum(r["oi_btc"] for r in ok), oi_usd=oi_usd)
    out["funding_annual_pct"] = sum(r["funding_annual_pct"] * r["oi_usd"] for r in ok) / oi_usd if oi_usd > 0 else sum(r["funding_annual_pct"] for r in ok) / len(ok)
    fa = [r["funding_annual_pct"] for r in ok]
    out["funding_spread_annual_pct"] = max(fa) - min(fa)
    marks = [r["mark"] for r in ok]
    mean = sum(marks) / len(marks)
    out["mark_dispersion_pct"] = (max(marks) - min(marks)) / mean * 100
    if out["mark_dispersion_pct"] > DISPERSION_WARN_PCT:
        out["flags"].append(f"venues disagree on the mark price by {out['mark_dispersion_pct']:.2f}%: check for a stale or broken feed before trusting the comparison")
    if any(f > 0 for f in fa) and any(f < 0 for f in fa):
        out["flags"].append("venues disagree on the sign of funding (some longs pay, some shorts pay)")
    if len(ok) < expected:
        out["flags"].append(f"only {len(ok)} of {expected} venues answered: totals cover those venues only")
    if any(r["status"] == "STALE" for r in ok):
        out["flags"].append("at least one venue's data is older than 2 minutes")
    return out


def percentile(history: list[float], value: float, min_points: int = 100) -> dict:
    """Where `value` sits in our own recorded history. Below `min_points` observations no percentile is given."""
    n = len(history)
    if n < min_points:
        return {"available": False, "have": n, "need": min_points}
    return {"available": True, "pctile": sum(1 for x in history if x <= value) / n * 100, "points": n}
