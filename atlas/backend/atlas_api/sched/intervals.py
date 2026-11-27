"""How often a job really runs, and why that may differ from what the user asked for. Pure function: the same inputs always give the same answer and the same explanation.

Inputs that change the interval (each one adds a plain-English reason):
 - market hours: the market-hours or off-hours preferred interval applies;
 - remaining allowance: when less than half of a limited budget is left, stretch the interval so the rest lasts to the reset; when only the usage reserve is left, defer optional work;
 - observed cost: if the job's average cost times its runs per day would overspend its fair share of the daily budget, stretch it until it fits;
 - data freshness: very stale data on an important job can tighten the interval, but never below half the preferred interval;
 - priority: low-priority jobs give way first (stretched a further 1.5x whenever any budget is under 80%).
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_STRETCH = 8.0
MIN_SHRINK = 0.5


@dataclass
class IntervalInput:
    preferred_s: float                          # the interval the user chose for the current market state
    is_market_open: bool
    priority: int = 3                           # 1 optional .. 5 essential
    budget_fractions: dict[str, float] = field(default_factory=dict)      # bucket -> remaining fraction (0..1) for buckets this job uses; unlimited buckets are left out
    reserve_pct: float = 20.0
    avg_cost: dict[str, float] = field(default_factory=dict)              # bucket -> average amount per run, from past runs
    daily_allowance: dict[str, float] = field(default_factory=dict)       # bucket -> the amount of the day's budget this job may plan on (fair share)
    age_s: float | None = None                  # age of the job's data (seconds since last success)
    scheduled_hours_left: float = 24.0


def effective_interval(i: IntervalInput) -> tuple[float | None, list[str]]:
    """Returns (seconds, reasons). seconds is None when the job should be deferred until a budget resets (reasons say why)."""
    reasons: list[str] = []
    interval = float(i.preferred_s)
    reasons.append(f"preferred {_fmt(i.preferred_s)} ({'market hours' if i.is_market_open else 'outside market hours'})")
    floor = i.reserve_pct / 100.0
    worst = min(i.budget_fractions.values(), default=None)
    if worst is not None and worst <= floor and i.priority < 5:
        b = min(i.budget_fractions, key=i.budget_fractions.get)
        return None, reasons + [f"deferred: only the {i.reserve_pct:g}% usage reserve of '{b}' is left, which is kept for essential jobs"]
    if worst is not None and worst < 0.5:
        stretch = min(MAX_STRETCH, 0.5 / max(worst, 1e-6))
        b = min(i.budget_fractions, key=i.budget_fractions.get)
        interval *= stretch
        reasons.append(f"x{stretch:.1f} slower: only {worst * 100:.0f}% of today's '{b}' allowance is left")
    for b, avg in i.avg_cost.items():
        share = i.daily_allowance.get(b)
        if not share or avg <= 0:
            continue
        per_day = 86400.0 / interval * avg
        if per_day > share:
            stretch = min(MAX_STRETCH, per_day / share)
            interval *= stretch
            reasons.append(f"x{stretch:.1f} slower: at {avg:g} per run this job would use {per_day:g}/day of '{b}', more than its {share:g} share")
    if i.priority <= 2 and worst is not None and worst < 0.8:
        interval *= 1.5
        reasons.append("x1.5 slower: low priority gives way while budgets are under 80%")
    if i.age_s is not None and i.priority >= 4 and i.age_s > 3 * interval and (worst is None or worst > 0.5):
        shrunk = max(interval * MIN_SHRINK, i.preferred_s * MIN_SHRINK)
        if shrunk < interval:
            interval = shrunk
            reasons.append(f"x0.5 faster: the data is {_fmt(i.age_s)} old, over 3 times the interval, and the job is important")
    return interval, reasons


def _fmt(s: float) -> str:
    s = float(s)
    if s < 120:
        return f"{s:.0f}s"
    if s < 7200:
        return f"{s / 60:.0f} min"
    return f"{s / 3600:.1f} h"
