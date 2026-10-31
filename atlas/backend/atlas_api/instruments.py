"""Canonical instrument IDs and a local metadata catalog (not market data).

IDs: ASSET:VENUE:SYMBOL[:KIND]. Spot and perpetuals are distinct instruments.
The seed catalog is small and static; broad-universe ingestion is tracked in the roadmap (Phase 3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    id: str
    symbol: str
    name: str
    asset_class: str          # equity | etf | index | crypto | macro
    exchange: str
    provider: str             # default data provider
    provider_symbol: str
    currency: str = "USD"
    venue: str | None = None
    sector: str | None = None
    kind: str | None = None   # spot | perp
    note: str | None = None

    @property
    def is_equity_like(self) -> bool:
        return self.asset_class in ("equity", "etf", "index")


def _eq(sym, name, exch, sector, cls="equity"):
    return Instrument(f"{cls.upper()}:{exch}:{sym}", sym, name, cls, exch, "yahoo", sym, sector=sector)


CATALOG: list[Instrument] = [
    Instrument("CRYPTO:COINBASE:BTC-USD:SPOT", "BTC-USD", "Bitcoin / US Dollar (Coinbase spot)", "crypto",
               "COINBASE", "coinbase", "BTC-USD", venue="COINBASE", kind="spot",
               note="Single-venue price; not the global BTC market."),
    _eq("SPY", "SPDR S&P 500 ETF Trust", "ARCA", None, "etf"),
    _eq("QQQ", "Invesco QQQ Trust", "NASDAQ", None, "etf"),
    _eq("IWM", "iShares Russell 2000 ETF", "ARCA", None, "etf"),
    _eq("DIA", "SPDR Dow Jones Industrial Average ETF", "ARCA", None, "etf"),
    _eq("GLD", "SPDR Gold Shares (gold proxy)", "ARCA", None, "etf"),
    _eq("USO", "United States Oil Fund (oil proxy)", "ARCA", None, "etf"),
    _eq("UUP", "Invesco DB US Dollar Index Bullish Fund (dollar proxy)", "ARCA", None, "etf"),
    _eq("AAPL", "Apple Inc.", "NASDAQ", "Technology"),
    _eq("MSFT", "Microsoft Corporation", "NASDAQ", "Technology"),
    _eq("NVDA", "NVIDIA Corporation", "NASDAQ", "Technology"),
    _eq("AMZN", "Amazon.com, Inc.", "NASDAQ", "Consumer Discretionary"),
    _eq("META", "Meta Platforms, Inc.", "NASDAQ", "Communication Services"),
    _eq("GOOGL", "Alphabet Inc. Class A", "NASDAQ", "Communication Services"),
    _eq("TSLA", "Tesla, Inc.", "NASDAQ", "Consumer Discretionary"),
    _eq("AMD", "Advanced Micro Devices, Inc.", "NASDAQ", "Technology"),
    _eq("PLTR", "Palantir Technologies Inc.", "NASDAQ", "Technology"),
    _eq("COIN", "Coinbase Global, Inc.", "NASDAQ", "Financials"),
    _eq("MSTR", "Strategy Inc (MicroStrategy)", "NASDAQ", "Technology"),
    Instrument("INDEX:SPGI:SPX", "SPX", "S&P 500 Index", "index", "SPGI", "yahoo", "^GSPC", currency="pts"),
    Instrument("INDEX:NASDAQ:NDX", "NDX", "Nasdaq-100 Index", "index", "NASDAQ", "yahoo", "^NDX", currency="pts"),
    Instrument("INDEX:DJI:DJI", "DJI", "Dow Jones Industrial Average", "index", "DJI", "yahoo", "^DJI", currency="pts"),
    Instrument("INDEX:RUSSELL:RUT", "RUT", "Russell 2000 Index", "index", "RUSSELL", "yahoo", "^RUT", currency="pts"),
    Instrument("INDEX:CBOE:VIX", "VIX", "CBOE Volatility Index", "index", "CBOE", "yahoo", "^VIX", currency="pts"),
    Instrument("MACRO:FRED:DGS10", "US10Y", "US 10-Year Treasury Yield (FRED DGS10, daily)", "macro", "FRED", "fred", "DGS10", currency="%"),
    Instrument("MACRO:FRED:DGS2", "US2Y", "US 2-Year Treasury Yield (FRED DGS2, daily)", "macro", "FRED", "fred", "DGS2", currency="%"),
]
BY_ID = {i.id: i for i in CATALOG}
_ALIASES = {"BTC": "BTC-USD", "BITCOIN": "BTC-USD", "SP500": "SPX", "S&P": "SPX", "NASDAQ100": "NDX",
            "10Y": "US10Y", "2Y": "US2Y", "GOLD": "GLD", "OIL": "USO", "DXY": "UUP", "USD": "UUP"}
BY_SYMBOL = {i.symbol: i for i in CATALOG}
_TICKER = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def get(instrument_id: str) -> Instrument | None:
    return BY_ID.get(instrument_id)


def by_symbol(token: str) -> Instrument | None:
    t = token.upper()
    t = _ALIASES.get(t, t)
    if t in BY_SYMBOL:
        return BY_SYMBOL[t]
    if t.startswith("^"):
        return next((i for i in CATALOG if i.provider_symbol == t), None)
    return None


def adhoc(token: str) -> Instrument | None:
    """An uncatalogued US ticker. Exchange is unknown, so it is flagged UNVERIFIED."""
    t = token.upper()
    return Instrument(f"EQUITY:US:{t}", t, f"{t} (not in local catalog)", "equity", "UNVERIFIED", "yahoo", t,
                      note="Not in the seed catalog: exchange and asset type unverified.") if _TICKER.match(t) else None


def resolve(instrument_id_or_symbol: str) -> Instrument | None:
    return get(instrument_id_or_symbol) or by_symbol(instrument_id_or_symbol) or (
        adhoc(instrument_id_or_symbol.split(":")[-1]) if instrument_id_or_symbol.startswith("EQUITY:US:") else None)


def search(query: str, limit: int = 10) -> list[Instrument]:
    q = query.strip().upper()
    if not q:
        return []
    scored = []
    for i in CATALOG:
        name = i.name.upper()
        if i.symbol == q or _ALIASES.get(q) == i.symbol:
            s = 100
        elif i.symbol.startswith(q):
            s = 80
        elif any(w.startswith(q) for w in re.split(r"[\s/(),.]+", name)):
            s = 60
        elif q in name:
            s = 40
        else:
            continue
        scored.append((s, i))
    out = [i for _, i in sorted(scored, key=lambda x: (-x[0], x[1].symbol))]
    if not out or (q not in BY_SYMBOL and _TICKER.match(q) and len(out) < limit):
        a = adhoc(q)
        if a and all(a.symbol != i.symbol for i in out):
            out.append(a)
    return out[:limit]
