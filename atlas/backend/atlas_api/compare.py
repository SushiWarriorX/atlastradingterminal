"""Cross-asset comparison on calendar-aligned bars. Pure functions: no I/O.

Calendars differ (BTC trades 24/7, equities only on sessions), so series are aligned to the bars they SHARE before any
return is computed. A return is then measured between consecutive shared bars, which gives both assets the same horizon
(e.g. Friday close to Monday close for both). The number of aligned bars is always reported.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .models import Candle

WINDOWS = (20, 60, 90, 180)
DAILY_LIKE = {"1d", "1w", "1M"}


class NoOverlap(ValueError):
    pass


def key_of(c: Candle, interval: str):
    """Alignment key. Daily/weekly/monthly bars align by UTC calendar date of the bar start (crypto bars start 00:00 UTC; Yahoo
    equity bars are stamped 00:00 New York = 04:00/05:00 UTC, i.e. the same UTC date). Intraday bars align by exact timestamp."""
    return datetime.fromtimestamp(c.time, timezone.utc).date().isoformat() if interval in DAILY_LIKE else c.time


def align(series: dict[str, list[Candle]], interval: str, min_common: int = 10) -> tuple[list[int], dict[str, list[Candle]]]:
    """Keep only bars present in ALL series. Returns (times of the first series' bars, aligned candles per series)."""
    keyed = {k: {key_of(c, interval): c for c in v} for k, v in series.items()}
    common = set.intersection(*(set(m) for m in keyed.values())) if keyed else set()
    if len(common) < min_common:
        hint = ("Intraday bars from different calendars/offsets (e.g. 24/7 crypto vs a US equity session) do not share timestamps: compare on 1d or 1w."
                if interval not in DAILY_LIKE else "The series share too few dates.")
        raise NoOverlap(f"only {len(common)} overlapping bars on {interval}. {hint}")
    order = sorted(common)
    first = next(iter(series))
    out = {k: [m[x] for x in order] for k, m in keyed.items()}
    return [c.time for c in out[first]], out


def rebase(closes: list[float], base: float = 100.0) -> list[float]:
    return [base * c / closes[0] for c in closes]


def returns(closes: list[float]) -> np.ndarray:
    c = np.asarray(closes, dtype=float)
    return c[1:] / c[:-1] - 1


def corr(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def beta(y: np.ndarray, x: np.ndarray) -> float | None:
    """Slope of y on x (sensitivity of y to x) over the window."""
    if len(x) < 3 or np.var(x) == 0:
        return None
    return float(np.cov(y, x, ddof=0)[0, 1] / np.var(x))


def rolling_corr(rx: np.ndarray, ry: np.ndarray, w: int) -> list[float | None]:
    return [corr(rx[i - w + 1:i + 1], ry[i - w + 1:i + 1]) if i >= w - 1 else None for i in range(len(rx))]


def pair_stats(base_closes: list[float], other_closes: list[float], windows=WINDOWS) -> dict:
    """Stats of `other` against `base`. Windows are counts of aligned OBSERVATIONS (returns); a window longer than the
    sample is reported as unavailable with the sample size, never silently shortened."""
    rb, ro = returns(base_closes), returns(other_closes)
    n = len(rb)
    out = {"observations": n, "full_sample_corr": corr(rb, ro), "windows": {}}
    for w in windows:
        if n < w:
            out["windows"][str(w)] = {"available": False, "observations": n}
            continue
        out["windows"][str(w)] = {"available": True, "corr": corr(rb[-w:], ro[-w:]), "beta_of_other_on_base": beta(ro[-w:], rb[-w:])}
    if n >= 60:
        roll = [x for x in rolling_corr(rb, ro, 60) if x is not None]
        if roll:
            out["rolling_60"] = {"latest": roll[-1], "min": min(roll), "max": max(roll), "samples": len(roll),
                                 "note": "Correlations drift; the min/max show how unstable this pair has been. Past correlation does not persist reliably."}
    out["total_return_pct"] = {"base": (base_closes[-1] / base_closes[0] - 1) * 100, "other": (other_closes[-1] / other_closes[0] - 1) * 100}
    return out
