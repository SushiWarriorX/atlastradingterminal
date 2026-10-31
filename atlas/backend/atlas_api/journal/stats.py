"""Performance analytics over CLOSED trades (pure).

Statistical honesty is built in: every summary carries its sample size, a Wilson interval for the win rate, a deterministic bootstrap
interval for expectancy (only from MIN_SAMPLE trades), and `reliable=False` below MIN_SAMPLE. Group tables repeat that per row so a
"best setup" backed by 4 trades is visibly not a finding. Results describe the past; they do not predict.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np

NY = ZoneInfo("America/New_York")
MIN_SAMPLE = 30
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - m), min(1.0, c + m)


def bootstrap_mean_ci(values: list[float], n_boot: int = 2000, seed: int = 20240601) -> tuple[float, float] | None:
    if len(values) < MIN_SAMPLE:
        return None
    rng = np.random.default_rng(seed)                       # fixed seed: the same data always gives the same interval
    arr = np.asarray(values)
    means = arr[rng.integers(0, len(arr), size=(n_boot, len(arr)))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _streaks(pnls: list[float]) -> tuple[int, int]:
    best_w = best_l = cur_w = cur_l = 0
    for p in pnls:
        if p > 0:
            cur_w, cur_l = cur_w + 1, 0
        elif p < 0:
            cur_l, cur_w = cur_l + 1, 0
        else:
            cur_w = cur_l = 0
        best_w, best_l = max(best_w, cur_w), max(best_l, cur_l)
    return best_w, best_l


def max_drawdown(pnls: list[float]) -> float:
    """Largest peak-to-trough fall of cumulative closed-trade P&L, in currency, starting from 0."""
    cum = peak = dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def summary(trades: list[dict]) -> dict:
    """trades: dicts with net_pnl (number), closed_at (datetime), holding_seconds, fees, funding and optional r_multiple."""
    ts = sorted(trades, key=lambda t: t["closed_at"])
    pnls = [float(t["net_pnl"]) for t in ts]
    n = len(pnls)
    out: dict = {"n": n, "reliable": n >= MIN_SAMPLE, "min_sample": MIN_SAMPLE}
    if n == 0:
        return {**out, "note": "no closed trades"}
    wins, losses = [p for p in pnls if p > 1e-9], [p for p in pnls if p < -1e-9]
    gp, gl = sum(wins), -sum(losses)
    out.update(
        wins=len(wins), losses=len(losses), breakeven=n - len(wins) - len(losses),
        win_rate=len(wins) / n, win_rate_ci95=wilson(len(wins), n),
        avg_win=gp / len(wins) if wins else None, avg_loss=-gl / len(losses) if losses else None,
        payoff_ratio=(gp / len(wins)) / (gl / len(losses)) if wins and losses else None,
        gross_profit=gp, gross_loss=-gl, net_pnl=sum(pnls), profit_factor=gp / gl if gl > 0 else None,
        profit_factor_note=None if gl > 0 else "no losing trades: profit factor undefined",
        expectancy=sum(pnls) / n, expectancy_ci95=bootstrap_mean_ci(pnls),
        best=max(pnls), worst=min(pnls), max_drawdown=max_drawdown(pnls),
        fees=float(sum(float(t.get("fees", 0)) for t in ts)), funding=float(sum(float(t.get("funding", 0)) for t in ts)),
    )
    out["max_win_streak"], out["max_loss_streak"] = _streaks(pnls)
    holds = [t["holding_seconds"] for t in ts if t.get("holding_seconds") is not None]
    out["avg_hold_seconds"] = sum(holds) / len(holds) if holds else None
    out["median_hold_seconds"] = median(holds) if holds else None
    rs = [float(t["r_multiple"]) for t in ts if t.get("r_multiple") is not None]
    out["r"] = {"n": len(rs), "avg_r": sum(rs) / len(rs) if rs else None, "total_r": sum(rs) if rs else None,
                "note": None if rs else "no trades have a planned stop, so R-multiples are unavailable"}
    ci = out["expectancy_ci95"]
    out["expectancy_note"] = None if ci is None else (
        "The 95% interval for expectancy INCLUDES zero: these trades do not show a statistically reliable edge." if ci[0] <= 0 <= ci[1]
        else "The 95% interval for expectancy excludes zero. That is still descriptive: it does not guarantee future results.")
    out["note"] = None if n >= MIN_SAMPLE else f"only {n} trades: treat every figure here as anecdotal (need {MIN_SAMPLE}+ for even rough conclusions)"
    return out


def _hold_bucket(sec: float | None) -> str:
    if sec is None:
        return "n/a"
    return "<1h" if sec < 3600 else "1h-1d" if sec < 86400 else "1d-7d" if sec < 7 * 86400 else ">7d"


def _r_bucket(r) -> str:
    if r is None:
        return "no stop"
    r = float(r)
    return "<-1R" if r < -1 else "-1R..0" if r < 0 else "0..1R" if r < 1 else "1R..2R" if r < 2 else ">=2R"


def _et(t: dict) -> datetime:
    o = t["opened_at"]
    return (o if o.tzinfo else o.replace(tzinfo=timezone.utc)).astimezone(NY)


GROUPS = {
    "setup": lambda t: [t.get("setup") or "(no setup)"],
    "symbol": lambda t: [t["symbol"]],
    "source": lambda t: [t["source"]],
    "side": lambda t: [t["side"]],
    "asset_class": lambda t: [t["asset_class"]],
    "hour_et": lambda t: [f"{_et(t).hour:02d}:00"],
    "weekday_et": lambda t: [WEEKDAYS[_et(t).weekday()]],
    "holding": lambda t: [_hold_bucket(t.get("holding_seconds"))],
    "r_bucket": lambda t: [_r_bucket(t.get("r_multiple"))],
    "tag": lambda t: list(t.get("tags") or []) or ["(untagged)"],
    "liquidation": lambda t: ["liquidated" if t.get("liquidated") else "not liquidated"],
    "exit_reason": lambda t: [t.get("exit_reason") or "n/a"],
    "year": lambda t: [str(_et(t).year)],
}


def group_by(trades: list[dict], name: str) -> list[dict]:
    if name not in GROUPS:
        raise ValueError(f"unknown grouping '{name}'")
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        for k in GROUPS[name](t):
            buckets[k].append(t)
    rows = []
    for k, ts in buckets.items():
        s = summary(ts)
        rows.append({"key": k, "n": s["n"], "reliable": s["reliable"], "win_rate": s.get("win_rate"), "win_rate_ci95": s.get("win_rate_ci95"),
                     "net_pnl": s.get("net_pnl"), "expectancy": s.get("expectancy"), "profit_factor": s.get("profit_factor"),
                     "avg_r": (s.get("r") or {}).get("avg_r")})
    # sort by net P&L, but unreliable rows never rank above reliable ones
    rows.sort(key=lambda r: (not r["reliable"], -(r["net_pnl"] or 0)))
    return rows


def equity_curve(trades: list[dict]) -> list[dict]:
    cum = 0.0
    out = []
    for t in sorted(trades, key=lambda x: x["closed_at"]):
        cum += float(t["net_pnl"])
        out.append({"ts": t["closed_at"].isoformat(), "pnl": float(t["net_pnl"]), "cum": cum})
    return out


def analyze(trades: list[dict], groups: list[str] | None = None) -> dict:
    """trades: CLOSED trades only. Mixed currencies are never added together: the most frequent currency is analysed, the rest reported."""
    by_ccy: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_ccy[t.get("currency", "USD")].append(t)
    if not by_ccy:
        return {"currency": None, "excluded": {}, "summary": summary([]), "groups": {}, "equity_curve": []}
    ccy = max(by_ccy, key=lambda c: len(by_ccy[c]))
    use = by_ccy[ccy]
    return {"currency": ccy, "excluded": {c: len(v) for c, v in by_ccy.items() if c != ccy},
            "summary": summary(use), "equity_curve": equity_curve(use),
            "groups": {g: group_by(use, g) for g in (groups or ["setup", "symbol", "source", "side", "hour_et", "weekday_et", "holding", "r_bucket", "tag"])},
            "caveats": ["Realized P&L only (open trades excluded); FIFO lot matching; fees and funding included where the source provided them.",
                        "Time buckets use the trade's ENTRY time in New York time (24/7 markets included).",
                        f"Groups with fewer than {MIN_SAMPLE} trades are flagged unreliable and sorted below reliable ones.",
                        "Past performance does not predict future results; do not size or change strategy on anecdotal groups."]}
