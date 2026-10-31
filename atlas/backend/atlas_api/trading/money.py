"""Decimal helpers. Money, quantities and prices are Decimal end to end and stored as TEXT: no binary floating point in accounting."""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 28
ZERO = Decimal(0)


def D(x) -> Decimal:
    """Float inputs go through str() so 0.1 is exactly 0.1, not 0.1000000000000000055."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def q(x, places: int, rounding=ROUND_HALF_UP) -> Decimal:
    return D(x).quantize(Decimal(1).scaleb(-places), rounding=rounding)


def floor_to(x, places: int) -> Decimal:
    return q(x, places, ROUND_DOWN)


def s(x: Decimal) -> str:
    """Canonical string for storage/JSON: plain notation, no exponent, no trailing zeros (so equal values compare equal as text)."""
    r = format(x.normalize(), "f") if x != 0 else "0"
    return r
