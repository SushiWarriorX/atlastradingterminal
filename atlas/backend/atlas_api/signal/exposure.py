"""What macro conditions an asset is actually exposed to. A rule table, not a model: each profile lists the macro drivers that usually matter for that
kind of asset and the direction (+1: a RISE in the driver has tended to help, -1: hurt). It frames the Macro agent's reading; it does not predict anything.

Drivers: yields (US 10-year yield rising), usd (broad dollar rising), liquidity (Fed balance sheet growing), inflation (core inflation high), curve (10Y-2Y steeper).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .assets import Asset

GROWTH = {"yields": -1, "usd": -1, "liquidity": 1, "inflation": -1, "curve": 1}
PROFILES: dict[str, tuple[str, dict[str, int], str]] = {
    "crypto": ("Crypto", {"usd": -1, "yields": -1, "liquidity": 1, "inflation": -1, "curve": 1},
               "Crypto has tended to be most sensitive to the US dollar, interest-rate expectations and global liquidity."),
    "growth": ("Growth-oriented stock", GROWTH, "Growth stocks are valued on distant earnings, so they have tended to react to interest rates, the dollar and liquidity."),
    "broad_equity": ("Broad US equities", GROWTH, "Broad equity funds have tended to follow interest rates, the dollar (overseas earnings), liquidity and inflation."),
    "bond_proxy": ("Rate-sensitive stock", {"yields": -1, "inflation": -1}, "Utilities and real-estate stocks are often treated like bonds, so they have tended to move against yields."),
    "defensive": ("Defensive stock", {"yields": -1, "inflation": -1}, "Defensive sectors are less tied to growth, but still react to yields and input-cost inflation."),
    "financials": ("Financial stock", {"curve": 1, "yields": 1}, "Banks and lenders have tended to benefit from a steeper yield curve and higher short-term rates."),
    "cyclical": ("Cyclical stock", {"usd": -1, "curve": 1}, "Energy, industrial and materials companies have tended to follow global demand, the dollar and the growth outlook."),
    "bonds": ("Bond fund", {"yields": -1, "inflation": -1}, "Bond prices fall when yields rise, and inflation is the main driver of rate expectations."),
    "tips": ("Inflation-linked bond fund", {"yields": -1, "inflation": 1}, "Inflation-linked bonds respond to real yields and to inflation itself."),
    "gold": ("Gold / precious metals", {"usd": -1, "yields": -1, "inflation": 1}, "Gold has tended to move against the dollar and real yields, and has been used as an inflation hedge."),
    "dollar": ("US dollar fund", {"usd": 1, "yields": 1}, "A dollar fund moves with the dollar, which has tended to follow US interest-rate differentials."),
    "energy": ("Energy / oil", {"usd": -1}, "Oil is priced in dollars, so a stronger dollar has tended to weigh on it; global demand matters more than US rates."),
    "other": ("Mixed exposure", GROWTH, "No specific profile matched, so the broad equity drivers are used."),
}
SECTOR_PROFILE = {"Technology": "growth", "Communication Services": "growth", "Consumer Discretionary": "growth", "Financials": "financials", "Energy": "cyclical",
                  "Industrials": "cyclical", "Materials": "cyclical", "Utilities": "bond_proxy", "Real Estate": "bond_proxy", "Consumer Staples": "defensive", "Health Care": "defensive"}
ETF_SYMBOLS = {
    "broad_equity": "SPY VOO IVV VTI DIA IWM RSP SPLG ITOT SCHB", "growth": "QQQ QQQM XLK SMH SOXX ARKK VUG IWF XLC XLY",
    "bonds": "TLT IEF IEI SHY GOVT BND AGG LQD HYG JNK VGSH VGIT VGLT SGOV BIL", "tips": "TIP SCHP VTIP", "gold": "GLD IAU SLV GDX GDXJ SGOL GLDM",
    "dollar": "UUP USDU", "energy": "USO XLE XOP OIH UNG", "financials": "XLF KRE KBE VFH", "bond_proxy": "XLU XLRE VNQ VNQI IYR", "defensive": "XLP XLV VDC VHT",
    "crypto": "IBIT FBTC GBTC BITB ARKB BTCO HODL BRRR EZBC BTC ETHA ETHE FETH ETH ETHW CETH BITO BITX",
}
SYMBOL_TO_PROFILE = {s: p for p, syms in ETF_SYMBOLS.items() for s in syms.split()}
NAME_RULES = [(r"bitcoin|ethereum|crypto", "crypto"), (r"treasury|bond|aggregate|income|credit", "bonds"), (r"\bgold\b|silver|precious", "gold"), (r"dollar", "dollar"),
              (r"energy|\boil\b|petroleum", "energy"), (r"utilit|real estate|reit", "bond_proxy")]


def phrase(label: str) -> str:
    """'Broad US equities' -> 'broad US equities' (only the first letter is lowered, so acronyms survive)."""
    return label[:1].lower() + label[1:]


@dataclass(frozen=True)
class Exposure:
    profile: str
    label: str
    drivers: dict[str, int]
    rationale: str


def exposure_for(a: Asset) -> Exposure:
    if a.type == "crypto":
        key = "crypto"
    elif a.type == "etf":
        key = SYMBOL_TO_PROFILE.get(a.symbol) if a.id.split(":")[1] in ("ARCA", "NASDAQ", "NYSE", "BATS", "AMEX") else None
        if key == "crypto" and a.symbol in ("BTC", "ETH") and a.venue == "US (exchange unverified)":
            key = None
        key = key or next((p for rx, p in NAME_RULES if re.search(rx, a.name, re.I)), "broad_equity")
    else:
        key = SECTOR_PROFILE.get(a.sector or "", "growth" if a.sector is None else "other")
    label, drivers, why = PROFILES[key]
    return Exposure(key, label, dict(drivers), why)
