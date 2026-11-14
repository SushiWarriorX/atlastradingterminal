"""'What if I had bought it?' simulations from a stock's own past daily closes. Research only: it replays history, it predicts nothing and places nothing.

Five views, all computed here from the bars (nothing is invented):
 1. Lump sum: put the amount in on one past date (about 1, 3 and 5 years ago, as far back as the data goes) and hold to today.
 2. Monthly buying (dollar-cost averaging): put the same amount in on the first trading day of every month over the same windows.
 3. Every possible start date: the spread of results for one year (and three years) of holding, whichever day you happened to buy. Shows how much luck of timing matters.
 4. Exit rules: the same purchase with a 20% stop, a 30% profit target, a 20% trailing stop, or just holding. Checked on daily closes only, so a gap through a stop
    fills at that day's close, which can be worse than the stop line.
 5. Bootstrap: 2,000 made-up one-year paths built by reshuffling blocks of this stock's own daily returns. It is a stress picture of "history repeating in a different order".
Prices are split-adjusted closes without dividends and without taxes or fees, so real results would differ. Past results do not predict future results.
"""
from __future__ import annotations

import zlib
from datetime import datetime, timezone

import numpy as np

MIN_BARS = 130
BOOT_PATHS = 2000
BOOT_BLOCK = 21
STOP, TARGET, TRAIL = 0.20, 0.30, 0.20


def _day(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).date().isoformat()


def _stats(v: np.ndarray) -> dict:
    p = np.percentile(v, [10, 50, 90])
    return {"worst_pct": float(v.min()), "p10_pct": float(p[0]), "median_pct": float(p[1]), "p90_pct": float(p[2]), "best_pct": float(v.max()), "share_positive": float((v > 0).mean()), "share_lost_20": float((v <= -20).mean()), "n": int(len(v))}


def _hold(c: np.ndarray, i: int) -> dict:
    """Buy at close i, hold to the end."""
    path = c[i:] / c[i]
    peak = np.maximum.accumulate(path)
    dd = float((path / peak - 1).min() * 100)
    worst_vs_buy = float((path.min() - 1) * 100)
    under = int((path < 1).sum())
    return {"final": float(path[-1]), "max_drawdown_pct": dd, "lowest_vs_cost_pct": worst_vs_buy, "days_below_cost": under, "days": int(len(path) - 1)}


def lump_sum(t, c, amount: float, YEAR: int) -> list[dict]:
    out, n = [], len(c)
    for years in (1, 3, 5):
        i = n - 1 - years * YEAR
        if i < 0:
            continue
        h = _hold(c, i)
        yrs = h["days"] / YEAR
        out.append({"label": f"{years} year{'s' if years > 1 else ''} ago", "buy_date": _day(t[i]), "buy_price": float(c[i]), "invested": amount, "value_now": amount * h["final"], "gain": amount * (h["final"] - 1),
                    "return_pct": (h["final"] - 1) * 100, "per_year_pct": (h["final"] ** (1 / yrs) - 1) * 100 if yrs >= 1 else None,
                    "lowest_vs_cost_pct": h["lowest_vs_cost_pct"], "max_drawdown_pct": h["max_drawdown_pct"], "days_below_cost": h["days_below_cost"], "days": h["days"]})
    return out


def monthly_buying(t, c, amount: float, YEAR: int) -> list[dict]:
    out, n = [], len(c)
    months = np.array([datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m") for x in t])
    firsts = [int(i) for i in np.where(np.r_[True, months[1:] != months[:-1]])[0]]
    for years in (1, 3, 5):
        lo = n - 1 - years * YEAR
        if lo < 0:
            continue
        idx = [i for i in firsts if i >= lo]
        if len(idx) < 3:
            continue
        shares = sum(amount / c[i] for i in idx)
        invested = amount * len(idx)
        value = shares * c[-1]
        lump = invested / c[idx[0]] * c[-1]                 # the same total money, all put in on the first of these dates
        out.append({"label": f"Every month for {years} year{'s' if years > 1 else ''}", "from": _day(t[idx[0]]), "buys": len(idx), "invested": invested, "value_now": value, "gain": value - invested,
                    "return_pct": (value / invested - 1) * 100, "average_price": invested / shares, "same_money_lump_sum_value": lump, "same_money_lump_sum_return_pct": (lump / invested - 1) * 100})
    return out


def every_start(t, c, YEAR: int) -> list[dict]:
    out, n = [], len(c)
    for years in (1, 3):
        h = years * YEAR
        if n - h < 30:
            continue
        r = (c[h:] / c[:-h] - 1) * 100
        iw, ib = int(r.argmin()), int(r.argmax())
        out.append({"label": f"Hold {years} year{'s' if years > 1 else ''}", **_stats(r), "worst_buy_date": _day(t[iw]), "best_buy_date": _day(t[ib]),
                    "note": f"Based on {len(r)} overlapping start dates, so they are not {len(r)} independent tries."})
    return out


def _exit(c: np.ndarray, i: int, rule: str) -> dict:
    entry = c[i]
    peak = entry
    for j in range(i + 1, len(c)):
        peak = max(peak, c[j])
        r = c[j] / entry - 1
        if rule == "stop" and r <= -STOP:
            return {"sold": True, "sold_on_idx": j, "result_pct": r * 100, "why": "hit the 20% stop"}
        if rule == "target" and r >= TARGET:
            return {"sold": True, "sold_on_idx": j, "result_pct": r * 100, "why": "hit the 30% target"}
        if rule == "trail" and c[j] <= peak * (1 - TRAIL):
            return {"sold": True, "sold_on_idx": j, "result_pct": r * 100, "why": "fell 20% from its highest close since buying"}
    return {"sold": False, "sold_on_idx": None, "result_pct": (c[-1] / entry - 1) * 100, "why": "never triggered; still held"}


def exit_rules(t, c, YEAR: int) -> list[dict]:
    out, n = [], len(c)
    names = {"hold": "Just hold", "stop": "Sell if down 20%", "target": "Sell if up 30%", "trail": "Sell if 20% below its high since buying"}
    for years in (1, 3, 5):
        i = n - 1 - years * YEAR
        if i < 0:
            continue
        rows = []
        for rule, label in names.items():
            r = {"sold": False, "sold_on_idx": None, "result_pct": (c[-1] / c[i] - 1) * 100, "why": "held to today"} if rule == "hold" else _exit(c, i, rule)
            rows.append({"rule": rule, "label": label, "result_pct": float(r["result_pct"]), "sold": r["sold"], "sold_on": _day(t[r["sold_on_idx"]]) if r["sold_on_idx"] is not None else None, "why": r["why"]})
        out.append({"label": f"Bought {years} year{'s' if years > 1 else ''} ago ({_day(t[i])})", "rules": rows})
    return out


def bootstrap(c, seed: int, YEAR: int) -> dict | None:
    r = np.diff(np.log(c))
    if len(r) < YEAR + BOOT_BLOCK:
        return None
    rng = np.random.default_rng(seed)
    blocks = int(np.ceil(YEAR / BOOT_BLOCK))
    starts = rng.integers(0, len(r) - BOOT_BLOCK + 1, size=(BOOT_PATHS, blocks))
    idx = (starts[:, :, None] + np.arange(BOOT_BLOCK)[None, None, :]).reshape(BOOT_PATHS, -1)[:, :YEAR]
    paths = np.exp(np.cumsum(r[idx], axis=1))
    fin = (paths[:, -1] - 1) * 100
    low = (paths.min(axis=1) - 1) * 100
    p = np.percentile(fin, [5, 25, 50, 75, 95])
    return {"paths": BOOT_PATHS, "block_days": BOOT_BLOCK, "p5_pct": float(p[0]), "p25_pct": float(p[1]), "median_pct": float(p[2]), "p75_pct": float(p[3]), "p95_pct": float(p[4]), "share_positive": float((fin > 0).mean()),
            "share_lost_20": float((fin <= -20).mean()), "typical_worst_dip_pct": float(np.median(low)), "bad_year_dip_pct": float(np.percentile(low, 5)),
            "note": "Made-up years built by reshuffling blocks of this stock's own past daily moves. It assumes the future looks like the past, which can be wrong."}


def simulate(bars: list[tuple[float, float]], amount: float, key: str) -> dict:
    """bars = (unix time, close) oldest first. Returns every simulation; raises ValueError if the history is too short to say anything."""
    bars = [(float(a), float(b)) for a, b in bars if b and b > 0]
    if len(bars) < MIN_BARS:
        raise ValueError(f"Only {len(bars)} daily prices are available; at least {MIN_BARS} (about six months) are needed.")
    t = np.array([x[0] for x in bars])
    c = np.array([x[1] for x in bars])
    years = (t[-1] - t[0]) / (365.25 * 86400)
    YEAR = max(int(round((len(c) - 1) / years)), 1)          # bars per year as the data really has them: about 252 for stocks, 365 for crypto
    notes = []
    if years < 5:
        notes.append(f"Only about {years:.1f} years of prices are available, so the longer windows are left out.")
    return {"bars_per_year": YEAR, "amount": amount, "from": _day(t[0]), "to": _day(t[-1]), "bars": len(c), "years": years, "last_price": float(c[-1]),
            "lump_sum": lump_sum(t, c, amount, YEAR), "monthly": monthly_buying(t, c, amount, YEAR), "every_start": every_start(t, c, YEAR), "exit_rules": exit_rules(t, c, YEAR),
            "bootstrap": bootstrap(c, zlib.crc32(key.encode()), YEAR), "notes": notes,
            "caveats": ["A replay of the past, not a forecast. Past results do not predict future results.", "Prices are split-adjusted closes. Dividends, taxes, fees and slippage are not included.",
                        "Stops and targets are checked on daily closes only; a real gap could fill worse.", "Research only: Signal cannot place trades, and nothing here is financial advice."]}
