"""Natural language -> ScanSpec (rule-based). Shows exactly what was understood; never runs anything itself.

Anything it cannot map is reported in `unsupported` instead of being silently dropped.
"""
from __future__ import annotations

import re

from .features import FIELDS
from .rules import Filter, ScanSpec
from .universe import CORE

SECTORS = {s.lower(): s for s in set(CORE.values())}
SECTOR_ALIASES = {"tech": "Technology", "technology": "Technology", "financial": "Financials", "financials": "Financials", "banks": "Financials",
                  "health": "Health Care", "healthcare": "Health Care", "energy": "Energy", "industrial": "Industrials", "industrials": "Industrials",
                  "utilities": "Utilities", "materials": "Materials", "staples": "Consumer Staples", "discretionary": "Consumer Discretionary",
                  "communication": "Communication Services", "real estate": "Real Estate"}
UNSUPPORTED = {
    "profitable|profit|earnings growth|revenue growth|eps|pe ratio|valuation|dividend": "fundamentals are not available (no financials provider yet)",
    "mid-?cap|small-?cap|large-?cap|market cap": "market capitalization filters need a market-cap source for the whole universe",
    "divergence": "divergence detection is not built (roadmap Phase 2)",
    "news|catalyst|earnings (date|event|season)": "news/earnings catalysts are not built (roadmap Phase 4)",
    "premarket|pre-market|intraday|time of day": "scanner uses daily bars only",
    "options|short interest|float": "that data is not available",
}
NUM = r"(-?\d+(?:\.\d+)?)"


def translate(text: str) -> dict:
    t = text.lower().strip()
    filters: list[Filter] = []
    matched: list[str] = []
    weights: dict[str, float] = {}
    spec_kw: dict = {}

    def add(field, op, value, why):
        filters.append(Filter(field=field, op=op, value=value))
        matched.append(why)

    if m := re.search(r"above (?:their |its |the )?(\d+)[- ]?(?:day )?(?:moving average|ma|sma)", t):
        n = int(m.group(1))
        if n in (20, 50, 200):
            add(f"above_sma{n}", "==", True, m.group(0))
        else:
            matched.append(f"'{m.group(0)}' not supported (only 20/50/200-day averages)")
    if m := re.search(r"below (?:their |its |the )?(\d+)[- ]?(?:day )?(?:moving average|ma|sma)", t):
        n = int(m.group(1))
        if n in (20, 50, 200):
            add(f"above_sma{n}", "==", False, m.group(0))
    if m := re.search(r"(?:break(?:ing|s)? (?:out )?above|new) (?:their |its |the )?20[- ]?day highs?|breaking out of (?:a )?20[- ]?day", t):
        add("breakout_20", "==", True, m.group(0))
    if m := re.search(r"break(?:ing|s)? (?:down )?below (?:their |its |the )?20[- ]?day lows?", t):
        add("breakdown_20", "==", True, m.group(0))
    if m := re.search(r"(?:relative volume|rvol)\s*(?:of |is )?(?:above|over|>|>=|at least|greater than)\s*" + NUM, t):
        add("rvol", ">=", float(m.group(1)), m.group(0))
    elif re.search(r"unusual(?:ly)? (?:high )?volume|abnormal volume|volume spike", t):
        add("rvol", ">=", 2.0, "unusual volume -> RVOL >= 2.0")
    if m := re.search(r"rsi\s*(?:\(\d+\)\s*)?(?:is )?(below|under|<|above|over|>)\s*" + NUM, t):
        add("rsi14", "<" if m.group(1) in ("below", "under", "<") else ">", float(m.group(2)), m.group(0))
    if m := re.search(r"(?:price|trading|priced) (?:is )?(?:above|over) \$?" + NUM, t):
        add("price", ">", float(m.group(1)), m.group(0))
    if m := re.search(r"(?:price|trading|priced) (?:is )?(?:below|under) \$?" + NUM, t):
        add("price", "<", float(m.group(1)), m.group(0))
    if m := re.search(r"outperform\w*\s+(spy|qqq|iwm|dia)(?: over (?:the )?(?:last |past )?(week|month|3 months|quarter|6 months))?|bullish relative strength against (spy|qqq|iwm)", t):
        bench = (m.group(1) or m.group(3)).upper()
        horizon = {"week": "5d", "month": "21d", "3 months": "63d", "quarter": "63d", "6 months": "126d", None: "21d"}[m.group(2)]
        spec_kw["benchmark"] = bench
        add(f"rs_{horizon}", ">", 0.0, f"{m.group(0)} -> {horizon} return minus {bench} > 0")
        weights[f"rs_{horizon}"] = 1.0
    if re.search(r"pull(?:ing|s)? ?back today|down today|red today", t):
        add("change_pct", "<", 0.0, "pulling back today -> change < 0")
    if re.search(r"up today|green today|gaining today", t):
        add("change_pct", ">", 0.0, "up today -> change > 0")
    if re.search(r"\bliquid\b", t):
        add("dollar_volume_avg20", ">=", 20_000_000.0, "liquid -> avg dollar volume >= $20M")
    if re.search(r"oversold", t):
        add("rsi14", "<=", 30.0, "oversold -> RSI <= 30")
    if re.search(r"overbought", t):
        add("rsi14", ">=", 70.0, "overbought -> RSI >= 70")
    if re.search(r"consolidat|compress|squeeze|tight", t):
        add("bb_width_pctile", "<=", 20.0, "consolidation/compression -> Bollinger width <= 20th percentile")
    if re.search(r"uptrend|bullish trend", t):
        add("trend", "==", "bullish", "uptrend -> MA alignment bullish")
    if re.search(r"downtrend|bearish trend", t):
        add("trend", "==", "bearish", "downtrend -> MA alignment bearish")
    sectors = sorted({v for k, v in SECTOR_ALIASES.items() if re.search(rf"\b{re.escape(k)}\b", t)})
    if sectors:
        add("sector", "in", sectors, f"sector in {sectors}")
        spec_kw["universe"] = "core"
    unsupported = [why for pat, why in UNSUPPORTED.items() if re.search(pat, t)]
    if not filters:
        return {"ok": False, "error": "Could not map that to scanner rules. Try e.g. 'technology stocks above their 50-day moving average with relative volume above 2'.",
                "unsupported": unsupported, "matched": [], "spec": None}
    spec = ScanSpec(name="Natural-language scan", filters=filters, score_weights=weights or {"rvol": 1.0, "rs_21d": 1.0}, **spec_kw)
    return {"ok": True, "spec": spec.model_dump(), "matched": matched, "unsupported": unsupported,
            "rules": [f.describe() for f in filters],
            "note": "Review and edit these rules before running. Only the rules above are applied; unsupported parts of your request are ignored."}


assert all(k in FIELDS for k in ("rvol", "breakout_20", "rs_21d"))  # import-time guard against field renames
