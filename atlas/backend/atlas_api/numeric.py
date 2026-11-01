"""Shared numeric coercion for untrusted third-party values."""
from __future__ import annotations

import math


def num(x) -> float | None:
    """Finite float or None. Strings such as 'Infinity', 'N/A' and NaN give None; booleans are not numbers."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
