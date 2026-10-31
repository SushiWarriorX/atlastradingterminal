"""Portfolio layer: turns per-symbol trades into one account with position sizing, capacity limits and a daily mark-to-market curve (pure).

Sizing: risk `risk_pct` of the previous close's equity per trade when the trade has a stop (shares = risk / stop distance), capped at
`max_position_pct` of equity; trades without a stop take the cap. Shares are whole. No leverage: gross exposure is capped at 100% of equity.
A trade that would breach `max_positions` or the exposure cap is SKIPPED and counted, never silently resized. Several entries on the same
day are taken in alphabetical symbol order (a documented tie-break, not a ranking).
"""
from __future__ import annotations

import math

import numpy as np

from .spec import BtSpec


def metrics(ts: list[int], eq: list[float]) -> dict:
    if len(eq) < 2:
        return {"total_return_pct": 0.0, "cagr_pct": None, "max_drawdown_pct": 0.0, "vol_ann_pct": None, "sharpe": None, "calmar": None, "days": len(eq)}
    a = np.asarray(eq, dtype=float)
    peak = np.maximum.accumulate(a)
    dd = float(((a - peak) / peak).min() * 100)
    r = np.diff(a) / a[:-1]
    years = (ts[-1] - ts[0]) / (365.25 * 86400)
    total = (a[-1] / a[0] - 1) * 100
    cagr = ((a[-1] / a[0]) ** (1 / years) - 1) * 100 if years >= 0.25 and a[-1] > 0 else None   # shorter than ~3 months: annualising misleads
    vol = float(r.std(ddof=1) * math.sqrt(252) * 100) if len(r) > 2 else None
    sharpe = float(r.mean() / r.std(ddof=1) * math.sqrt(252)) if len(r) > 2 and r.std(ddof=1) > 0 else None
    return {"total_return_pct": float(total), "cagr_pct": None if cagr is None else float(cagr), "max_drawdown_pct": dd, "vol_ann_pct": vol,
            "sharpe": sharpe, "calmar": float(cagr / abs(dd)) if cagr is not None and dd < 0 else None, "days": len(eq)}


def run(trades: list[dict], closes: dict[str, dict[int, float]], spec: BtSpec) -> dict:
    if not trades:
        return {"curve": [], "metrics": metrics([], []), "trades": [], "skipped": {}, "exposure_avg_pct": None,
                "note": "no trades: nothing to size"}
    t0 = min(t["entry_t"] for t in trades)
    t1 = max(t["exit_t"] for t in trades)
    syms = {t["symbol"] for t in trades}
    timeline = sorted({d for s in syms for d in closes[s] if t0 <= d <= t1})
    by_entry: dict[int, list[dict]] = {}
    for t in sorted(trades, key=lambda x: (x["entry_t"], x["symbol"])):
        by_entry.setdefault(t["entry_t"], []).append(t)
    cash = spec.initial_capital
    open_: list[dict] = []
    done: list[dict] = []
    skipped = {"max_positions": 0, "gross_exposure": 0, "size_zero": 0}
    curve: list[dict] = []
    last_px: dict[str, float] = {}
    equity = cash
    expo: list[float] = []
    comm = spec.commission_bps / 10_000

    def exit_(p):
        nonlocal cash
        t = p["trade"]
        proceeds = p["qty"] * t["exit_px"]
        cash += proceeds - abs(proceeds) * comm
        pnl = p["qty"] * (t["exit_px"] - t["entry_px"]) - abs(p["qty"] * t["entry_px"]) * comm - abs(proceeds) * comm
        done.append({**t, "qty": p["qty"], "pnl": pnl, "notional": abs(p["qty"] * t["entry_px"])})

    for d in timeline:
        for p in [p for p in open_ if p["trade"]["exit_t"] == d and p["trade"]["entry_t"] < d]:
            exit_(p)
            open_.remove(p)
        for t in by_entry.get(d, []):
            px = t["entry_px"]
            sign = 1 if t["side"] == "long" else -1
            cap = spec.max_position_pct / 100 * equity
            if t["stop"]:
                qty = min(spec.risk_pct / 100 * equity / abs(px - t["stop"]), cap / px)
            else:
                qty = cap / px
            qty = math.floor(qty)
            if qty < 1:
                skipped["size_zero"] += 1
                continue
            if len(open_) >= spec.max_positions:
                skipped["max_positions"] += 1
                continue
            gross = sum(abs(p["qty"]) * last_px.get(p["trade"]["symbol"], p["trade"]["entry_px"]) for p in open_)
            if gross + qty * px > equity:
                skipped["gross_exposure"] += 1
                continue
            cash -= sign * qty * px + qty * px * comm
            open_.append({"trade": t, "qty": sign * qty})
        for p in [p for p in open_ if p["trade"]["exit_t"] == d]:
            exit_(p)
            open_.remove(p)
        gross = 0.0
        value = 0.0
        for p in open_:
            s = p["trade"]["symbol"]
            px = closes[s].get(d, last_px.get(s, p["trade"]["entry_px"]))
            last_px[s] = px
            value += p["qty"] * px
            gross += abs(p["qty"]) * px
        equity = cash + value
        expo.append(gross / equity * 100 if equity > 0 else 0.0)
        curve.append({"t": d, "equity": equity})
    ts = [x["t"] for x in curve]
    return {"curve": curve, "metrics": metrics(ts, [x["equity"] for x in curve]), "trades": done, "skipped": skipped,
            "exposure_avg_pct": float(np.mean(expo)) if expo else None, "final_equity": equity,
            "open_at_end": len(open_)}
