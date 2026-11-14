"""The universe of listed companies for "new to me" discovery, from Nasdaq's public stock screener feed (all NYSE and Nasdaq common stocks; unofficial website feed, delayed prices).

It carries the fields the filters need: sector, industry, market value, country, IPO year and volume. A field the feed leaves blank is UNKNOWN, never zero: a company with an unknown market value
cannot pass a market-value filter, and one with an unknown IPO year cannot pass a listing-age filter (the counts of such exclusions are returned so nothing disappears silently).
Warrants, units, rights, preferred shares, funds and blank-check shells are not operating companies and are excluded; foreign companies listed through depositary receipts are excluded under their own reason, because they file 20-F reports that this research does not read.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

SOURCE = "Nasdaq stock screener (public website feed; unofficial; prices delayed)"
URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true&exchange={exchange}"
SYMBOL_OK = re.compile(r"^[A-Z]{1,5}([-/][A-Z])?$")
NOT_OPERATING = re.compile(r"\b(warrants?|units?|rights?|preferred|etf|etn|fund|notes? due|subordinated|trust units?|acquisition corp|acquisition corporation|acquisition holdings|blank check)\b", re.I)
ADS = re.compile(r"\bamerican depositary (shares|receipts)\b|\bdepositary shares\b", re.I)         # foreign companies listed through receipts; they file 20-F, which this research does not read
SIZE_BUCKETS = [("small", 0.3e9, 2e9), ("mid", 2e9, 10e9), ("large", 10e9, 200e9), ("mega", 200e9, float("inf"))]
DEFAULT_FILTERS = {"sectors": None, "min_market_cap": 300e6, "max_market_cap": 50e9, "min_dollar_volume": 1e6, "countries": None, "exchanges": None, "max_listing_age_years": None, "min_listing_age_years": None}


def _f(x):
    try:
        s = str(x).replace("$", "").replace(",", "").replace("%", "").strip()
        return float(s) if s not in ("", "NA", "N/A", "--") else None
    except (TypeError, ValueError):
        return None


def parse_screener(payload: dict, exchange: str) -> list[dict]:
    """Screener rows -> companies with numbers parsed and unknowns kept as None."""
    out = []
    for r in ((payload or {}).get("data") or {}).get("rows") or []:
        sym, name = (r.get("symbol") or "").strip().upper(), (r.get("name") or "").strip()
        if not sym or not name:
            continue
        price, vol = _f(r.get("lastsale")), _f(r.get("volume"))
        ipo = _f(r.get("ipoyear"))
        out.append({"symbol": sym, "name": name[:120], "exchange": exchange, "price": price, "market_cap": _f(r.get("marketCap")), "volume": int(vol) if vol is not None else None,
                    "dollar_volume": price * vol if price is not None and vol is not None else None, "country": (r.get("country") or "").strip() or None, "ipo_year": int(ipo) if ipo and 1900 < ipo < 2100 else None,
                    "sector": (r.get("sector") or "").strip() or None, "industry": (r.get("industry") or "").strip() or None})
    return out


def operating_company(c: dict) -> bool:
    return bool(SYMBOL_OK.match(c["symbol"])) and not NOT_OPERATING.search(c["name"])


def size_bucket(cap: float | None) -> str | None:
    if cap is None:
        return None
    for name, lo, hi in SIZE_BUCKETS:
        if lo <= cap < hi:
            return name
    return "micro" if cap < SIZE_BUCKETS[0][1] else None


def apply_filters(companies: list[dict], f: dict | None, this_year: int | None = None) -> tuple[list[dict], dict]:
    """Companies that pass every filter, and how many were excluded for each reason (including 'unknown')."""
    f = {**DEFAULT_FILTERS, **{k: v for k, v in (f or {}).items() if k in DEFAULT_FILTERS}}
    this_year = this_year or date.today().year
    why = {"not an operating company": 0, "foreign depositary shares (foreign filers are not covered)": 0, "unknown market value": 0, "market value out of range": 0, "low trading volume or unknown": 0, "sector": 0, "country": 0, "exchange": 0, "listing age": 0, "unknown listing year": 0}
    keep = []
    sectors = {s.lower() for s in f["sectors"]} if f["sectors"] else None
    countries = {s.lower() for s in f["countries"]} if f["countries"] else None
    exchanges = {s.lower() for s in f["exchanges"]} if f["exchanges"] else None
    for c in companies:
        if not operating_company(c):
            why["not an operating company"] += 1
        elif ADS.search(c["name"]):
            why["foreign depositary shares (foreign filers are not covered)"] += 1
        elif c["market_cap"] is None:
            why["unknown market value"] += 1
        elif not (f["min_market_cap"] <= c["market_cap"] <= f["max_market_cap"]):
            why["market value out of range"] += 1
        elif f["min_dollar_volume"] and (c["dollar_volume"] is None or c["dollar_volume"] < f["min_dollar_volume"]):
            why["low trading volume or unknown"] += 1
        elif sectors is not None and (c["sector"] or "").lower() not in sectors:
            why["sector"] += 1
        elif countries is not None and (c["country"] or "").lower() not in countries:
            why["country"] += 1
        elif exchanges is not None and c["exchange"].lower() not in exchanges:
            why["exchange"] += 1
        elif (f["max_listing_age_years"] is not None or f["min_listing_age_years"] is not None) and c["ipo_year"] is None:
            why["unknown listing year"] += 1
        elif f["max_listing_age_years"] is not None and this_year - c["ipo_year"] > f["max_listing_age_years"]:
            why["listing age"] += 1
        elif f["min_listing_age_years"] is not None and this_year - c["ipo_year"] < f["min_listing_age_years"]:
            why["listing age"] += 1
        else:
            keep.append(c)
    return keep, {k: v for k, v in why.items() if v}


def _h(symbol: str, day: str) -> int:
    return int(hashlib.sha256(f"{symbol}|{day}".encode()).hexdigest(), 16)


def sample_for_study(companies: list[dict], day: str, n: int, exclude: set[str] | None = None) -> list[dict]:
    """Which companies to study today: round-robin across sector and size groups in a day-seeded but reproducible order, so the pool is varied instead of the biggest names every day."""
    exclude = {s.upper() for s in (exclude or set())}
    groups: dict[tuple, list[dict]] = {}
    for c in companies:
        if c["symbol"] in exclude:
            continue
        groups.setdefault((c["sector"] or "(unclassified)", size_bucket(c["market_cap"])), []).append(c)
    for g in groups.values():
        g.sort(key=lambda c: _h(c["symbol"], day))
    order = sorted(groups, key=lambda k: _h(f"{k[0]}|{k[1]}", day))
    out: list[dict] = []
    i = 0
    while len(out) < n and any(groups[k] for k in order):
        k = order[i % len(order)]
        if groups[k]:
            out.append(groups[k].pop(0))
        i += 1
    return out
