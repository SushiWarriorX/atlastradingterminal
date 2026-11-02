"""Clearly labelled demo fixtures, used ONLY when the backend runs in demo mode (ATLAS_DEMO=1), where every price is synthetic too.

Everything here is invented for UI development and is marked as such (titles start with [DEMO], sources say 'Demo fixture (synthetic, not real)', findings carry
demo=true). Real mode never imports this module: demo and live data are never mixed.
"""
from __future__ import annotations

import zlib
from datetime import datetime, timedelta, timezone

from .assets import Asset


def _r(*parts) -> int:
    return zlib.crc32(":".join(map(str, parts)).encode())


def news(a: Asset, now: datetime) -> dict:
    sym = a.symbol
    items = [
        ("[DEMO] Example report: {s} draws attention after a large trading session", "reporting", 3, None),
        ("[DEMO] Example: {s} reportedly in talks over a partnership, sources say", "unconfirmed", 9, None),
        ("[DEMO] Opinion: why the {s} debate misses the bigger picture", "opinion", 20, None),
        ("[DEMO] Example: regulator opens review that could affect {s} issuers", "reporting", 40, "regulatory"),
    ]
    out = []
    for i, (t, _, hours, _c) in enumerate(items):
        when = now - timedelta(hours=hours)
        out.append({"id": f"demo-{sym}-{i}", "title": t.format(s=sym), "link": None, "summary": "Synthetic demo story. Not real news.", "feed": "Demo fixture",
                    "published": when.isoformat(), "fetched_at": when.isoformat(), "symbols": [sym], "status": "DEMO",
                    "also": [{"feed": "Demo fixture 2", "title": t.format(s=sym), "link": None, "published": when.isoformat()}] if i == 0 else []})
    return {"items": out, "meta": {"feeds_enabled": 0, "feeds_ok": 0, "as_of": now.isoformat(), "never_fetched": 0}}


def _fact(fid, label, value, obs, changes=None, **extra):
    return {"id": fid, "label": label, "value": value, "obs_date": obs, "status": "DEMO", "changes": changes or [], **extra}


def macro_overview(now: datetime) -> dict:
    d = (now - timedelta(days=1)).date().isoformat()
    m = (now - timedelta(days=50)).date().replace(day=1).isoformat()
    ch = lambda v, unit, label="vs ~1 month earlier": [{"label": label, "ref_date": d, "value": v, "unit": unit}]
    return {"demo": True, "demo_fixture": True, "facts": [
        _fact("us10y", "US 10-year Treasury yield", 4.31, d, ch(32.0, "bps")), _fact("us2y", "US 2-year Treasury yield", 4.12, d, ch(18.0, "bps")),
        _fact("curve", "Yield curve (10Y minus 2Y)", 19.0, d), _fact("core_cpi", "Core CPI", 3.2, m), _fact("cpi", "CPI", 3.0, m),
        _fact("fed", "Fed funds target range", None, d, lower=3.75, upper=4.0), _fact("usd", "Broad dollar index", 121.4, d, ch(2.4, "%"))]}


def fedwatch(now: datetime) -> dict:
    at = (now + timedelta(days=12)).replace(hour=19, minute=0, second=0, microsecond=0)
    return {"upcoming": [{"id": "statement-demo", "type": "statement", "title": "FOMC statement (demo date)", "meeting": "Demo meeting", "at_utc": at.isoformat(), "link": None}],
            "release_schedule": [{"series": "cpi", "label": "CPI", "name": "Demo CPI release", "date": (now + timedelta(days=8)).date().isoformat(), "at_utc": (now + timedelta(days=8)).replace(hour=13, minute=30, second=0, microsecond=0).isoformat()}],
            "balance_sheet": {"id": "balance_sheet", "value": 6.6, "trend": "shrinking", "obs_date": (now - timedelta(days=3)).date().isoformat(), "changes": []}}


def etf_raw(a: Asset) -> dict:
    r = _r(a.id)
    names = ["Demo Holding A", "Demo Holding B", "Demo Holding C", "Demo Holding D", "Demo Holding E", "Demo Holding F", "Demo Holding G", "Demo Holding H", "Demo Holding I", "Demo Holding J"]
    return {"info": {"longName": f"{a.symbol} (synthetic demo fund)", "category": "Demo category", "fundFamily": "Demo Funds", "longBusinessSummary": "Synthetic demo fund description. Not a real fund.",
                     "annualReportExpenseRatio": 0.0003 + (r % 60) / 10000, "totalAssets": 5e9 + (r % 90) * 1e9, "yield": 0.012},
            "top_holdings": [{"symbol": f"DM{i + 1}", "name": n, "weight": (9 - i * 0.6) / 100} for i, n in enumerate(names)], "sector_weights": {"technology": 0.3, "financial_services": 0.15, "healthcare": 0.1}, "asset_classes": None}


def coin_raw(a: Asset) -> dict:
    r = _r(a.id)
    circ = 1e8 + (r % 900) * 1e6
    return {"name": f"{a.name} (demo)", "symbol": a.symbol.lower(), "genesis_date": "2015-01-01", "categories": ["Demo category"], "description": {"en": "Synthetic demo token description. Not real."},
            "links": {"homepage": []}, "developer_data": {"commit_count_4_weeks": 40 + r % 100}, "market_data": {"market_cap_rank": 1 + r % 50, "circulating_supply": circ, "total_supply": circ * 1.1,
            "max_supply": circ * 1.4 if r % 2 else None, "market_cap": {"usd": circ * 10}, "fully_diluted_valuation": {"usd": circ * 14 if r % 2 else None}, "last_updated": datetime.now(timezone.utc).isoformat()}}


def btc_snapshot() -> dict:
    return {"height": 905_000, "hashrate": {"currentHashrate": 9.5e20}, "fees": {"halfHourFee": 4}}
