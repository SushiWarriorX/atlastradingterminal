"""Scan universes.

- core:      ~100 liquid US large caps with sectors (static seed, labelled as such)
- us_listed: every symbol in the Nasdaq Trader directory (official, free). Needs network; sector is unknown there.
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

_CORE = {
    "Technology": "AAPL MSFT NVDA AVGO ORCL CRM ADBE AMD INTC QCOM TXN MU AMAT LRCX KLAC CSCO IBM NOW PANW CRWD PLTR SNOW NET DDOG SMCI ARM MSTR",
    "Communication Services": "GOOGL META NFLX DIS TMUS VZ T CMCSA",
    "Consumer Discretionary": "AMZN TSLA HD MCD NKE SBUX LOW BKNG ABNB UBER LULU",
    "Consumer Staples": "WMT COST PG KO PEP PM MDLZ",
    "Health Care": "LLY UNH JNJ ABBV MRK PFE TMO ABT AMGN ISRG GILD VRTX",
    "Financials": "JPM BAC WFC GS MS V MA AXP BLK SCHW COIN SOFI HOOD",
    "Energy": "XOM CVX COP SLB OXY",
    "Industrials": "CAT DE GE BA RTX LMT UPS HON",
    "Materials": "LIN FCX NEM",
    "Utilities": "NEE DUK SO",
    "Real Estate": "PLD AMT",
}
CORE: dict[str, str] = {s: sector for sector, syms in _CORE.items() for s in syms.split()}
UNIVERSES = {
    "core": "Core liquid US large caps (~100, static seed list)",
    "us_listed": "All US-listed symbols from the Nasdaq Trader directory (needs network; slow; no sector data)",
}
NASDAQ_URLS = ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
_CACHE = Path("universe_cache.txt")
_TTL = 24 * 3600


class UniverseUnavailable(Exception):
    pass


def parse_directory(nasdaq_txt: str, other_txt: str, include_etfs: bool = False) -> list[str]:
    """Parse the two pipe-delimited Nasdaq Trader files. Drops test issues, ETFs (optional) and odd symbols."""
    out: list[str] = []
    for txt, sym_col in ((nasdaq_txt, "Symbol"), (other_txt, "ACT Symbol")):
        lines = [l for l in txt.splitlines() if l and not l.startswith("File Creation Time")]
        if not lines:
            continue
        head = lines[0].split("|")
        i_sym, i_test, i_etf = head.index(sym_col), head.index("Test Issue"), head.index("ETF")
        i_fin = head.index("Financial Status") if "Financial Status" in head else None
        for row in lines[1:]:
            f = row.split("|")
            if len(f) <= max(i_sym, i_test, i_etf) or f[i_test] == "Y" or (f[i_etf] == "Y" and not include_etfs):
                continue
            if i_fin is not None and f[i_fin] not in ("N", ""):  # deficient/delinquent/bankrupt
                continue
            s = f[i_sym].strip()
            if s and s.replace("-", "").replace(".", "").isalpha() and "$" not in s:
                out.append(s.replace(".", "-"))  # Yahoo uses BRK-B
    return sorted(set(out))


async def load(universe: str, client: httpx.AsyncClient | None = None) -> list[str]:
    if universe == "core":
        return sorted(CORE)
    if universe != "us_listed":
        raise UniverseUnavailable(f"unknown universe '{universe}'")
    if _CACHE.exists() and time.time() - _CACHE.stat().st_mtime < _TTL:
        return _CACHE.read_text().split()
    try:
        async with (client or httpx.AsyncClient(timeout=20, follow_redirects=True)) as c:
            texts = [(await c.get(u)).raise_for_status().text for u in NASDAQ_URLS]
    except (httpx.HTTPError, OSError) as e:
        raise UniverseUnavailable(f"Nasdaq Trader directory unreachable: {e}") from e
    syms = parse_directory(*texts)
    if len(syms) < 1000:
        raise UniverseUnavailable(f"directory parse looks wrong ({len(syms)} symbols)")
    _CACHE.write_text("\n".join(syms))
    return syms
