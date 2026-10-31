from __future__ import annotations

from .. import instruments as I


def sym(instrument_id: str) -> str:
    i = I.resolve(instrument_id)
    return i.symbol if i else instrument_id


def title(rule) -> str:
    if rule.name:
        return rule.name
    k = rule.kind
    if k == "scan":
        return f"Scan: {rule.preset or (rule.spec or {}).get('name', 'custom')}"
    s = sym(rule.instrument_id)
    return {"price": lambda: f"{s} price {rule.op} {rule.level:g}", "pct_change": lambda: f"{s} change {rule.op} {rule.threshold:+g}%",
            "rsi": lambda: f"{s} RSI({rule.period}) {rule.op} {rule.level:g} [{rule.interval}]",
            "ma": lambda: f"{s} price {rule.op} SMA({rule.length}) [{rule.interval}]",
            "macd": lambda: f"{s} MACD {rule.direction} cross [{rule.interval}]", "rvol": lambda: f"{s} RVOL >= {rule.threshold:g}x"}[k]()
