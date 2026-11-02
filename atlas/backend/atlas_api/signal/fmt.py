"""Display formatting for facts. The server formats numbers once, so every client shows the same text."""
from __future__ import annotations

import math


def _ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def price(v: float | None) -> str:
    if not _ok(v):
        return "n/a"
    a = abs(v)
    if a >= 1:
        return f"${v:,.2f}"
    if a >= 0.01:
        return f"${v:.4f}"
    return f"${v:.6f}".rstrip("0").rstrip(".") if a else "$0.00"


def pct(v: float | None, signed: bool = False, digits: int = 1) -> str:
    if not _ok(v):
        return "n/a"
    return f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%"


def big(v: float | None, prefix: str = "$") -> str:
    """$1.2B, $340M, $12.5K."""
    if not _ok(v):
        return "n/a"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{'-' if v < 0 else ''}{prefix}{a / div:.2f}{suf}"
    return f"{'-' if v < 0 else ''}{prefix}{a:,.0f}"


def num(v: float | None, digits: int = 2, unit: str = "") -> str:
    if not _ok(v):
        return "n/a"
    return f"{v:,.{digits}f}{unit}"


def times(v: float | None, digits: int = 1) -> str:
    return "n/a" if not _ok(v) else f"{v:.{digits}f}×"


def bps(v: float | None, signed: bool = True) -> str:
    if not _ok(v):
        return "n/a"
    return f"{v:+.0f} bps" if signed else f"{v:.0f} bps"
