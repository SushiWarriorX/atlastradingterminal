"""Single-symbol simulation on daily bars (pure). Point-in-time by construction:

- signals are computed from bars up to and including bar i, and fill at the OPEN of bar i+1 (never at the signal close);
- features come from the same code the scanner uses, on a trailing WINDOW of bars (recursive indicators such as RSI and ATR are seeded
  on that window, so values can differ slightly from a full-history scan; the window is long enough for them to converge);
- if a stop and a target are both touched inside one bar the stop is assumed to hit first (conservative: the daily bar has no intrabar order);
- a gap through a stop fills at the open (worse than the stop), never at the stop price;
- market-type fills (entry, stop, time exit, signal exit) pay slippage against the trade; a target is a limit and does not.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone

from ..models import Candle
from ..scanner import features as feat
from .spec import BtSpec

WINDOW = 400
WARMUP = feat.MIN_BARS


def day(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).date().isoformat()


def _features(symbol, candles, i, bench, bench_times):
    lo = max(0, i - WINDOW + 1)
    b = None
    if bench:
        k = bisect_right(bench_times, candles[i].time)
        b = bench[max(0, k - WINDOW):k] or None
    return feat.compute(symbol, candles[lo:i + 1], b)


def _passes(f: dict, filters) -> bool:
    return f["sufficient"] and all(x.passes(f) for x in filters)


def simulate(symbol: str, candles: list[Candle], bench: list[Candle] | None, spec: BtSpec) -> dict:
    n = len(candles)
    d = 1 if spec.side == "long" else -1
    slip = spec.slippage_bps / 10_000
    bench_times = [c.time for c in bench] if bench else []
    start_t = int(datetime(spec.start.year, spec.start.month, spec.start.day, tzinfo=timezone.utc).timestamp()) if spec.start else None
    end_t = int(datetime(spec.end.year, spec.end.month, spec.end.day, 23, 59, 59, tzinfo=timezone.utc).timestamp()) if spec.end else None
    trades: list[dict] = []
    pos: dict | None = None
    pend_entry: dict | None = None
    pend_exit = False
    pending_signal: dict | None = None

    def close_trade(j: int, px: float, reason: str, market: bool):
        nonlocal pos
        fill = px * (1 - d * slip) if market else px
        gross = d * (fill / pos["entry_px"] - 1) * 100
        cost = 2 * spec.commission_bps / 100
        risk = pos["risk_frac"] * 100 if pos["risk_frac"] else None
        net = gross - cost
        trades.append({
            "symbol": symbol, "side": spec.side, "signal_t": pos["signal_t"], "signal_date": day(pos["signal_t"]),
            "entry_t": pos["entry_t"], "entry_date": day(pos["entry_t"]), "entry_px": pos["entry_px"],
            "stop": pos["stop"], "target": pos["target"], "exit_t": candles[j].time, "exit_date": day(candles[j].time), "exit_px": fill,
            "exit_reason": reason, "bars_held": pos["held"], "gross_pct": gross, "cost_pct": cost, "net_pct": net,
            "risk_pct": risk, "r_multiple": net / risk if risk else None, "setup": pos["setup"],
        })
        pos = None

    for j in range(WARMUP - 1, n):
        o, h, l, c = candles[j].open, candles[j].high, candles[j].low, candles[j].close
        if pos is not None and pend_exit:
            close_trade(j, o, "signal", True)
        pend_exit = False
        if pos is None and pend_entry is not None:
            fill = o * (1 + d * slip)
            dist = pend_entry["atr"] * spec.stop_atr if spec.stop_atr else None
            stop = fill - d * dist if dist else None
            target = fill + d * dist * spec.target_r if dist and spec.target_r else None
            pos = {"signal_t": pend_entry["t"], "entry_t": candles[j].time, "entry_px": fill, "stop": stop, "target": target,
                   "risk_frac": dist / fill if dist else None, "held": 0, "setup": pend_entry["setup"]}
        pend_entry = None
        if pos is not None:
            pos["held"] += 1
            stop, target = pos["stop"], pos["target"]
            hit_stop = stop is not None and ((l <= stop) if d == 1 else (h >= stop))
            hit_tgt = target is not None and ((h >= target) if d == 1 else (l <= target))
            if hit_stop:    # also covers "both touched": stop first
                gap = (o <= stop) if d == 1 else (o >= stop)
                close_trade(j, o if gap else stop, "stop", True)
            elif hit_tgt:
                gap = (o >= target) if d == 1 else (o <= target)
                close_trade(j, o if gap else target, "target", False)
            elif pos["held"] >= spec.max_hold_bars:
                close_trade(j, c, "time", True)
        in_window = (start_t is None or candles[j].time >= start_t) and (end_t is None or candles[j].time <= end_t)
        need_entry = pos is None and in_window
        need_exit = pos is not None and bool(spec.exit_filters)
        if need_entry or need_exit:
            f = _features(symbol, candles, j, bench, bench_times)
            if need_exit and _passes(f, spec.exit_filters):
                pend_exit = j < n - 1
            if need_entry and _passes(f, spec.entry) and f["atr_pct"] is not None:
                sig = {"t": candles[j].time, "atr": f["atr_pct"] / 100 * c, "setup": f.get("setup")}
                if j < n - 1:
                    pend_entry = sig
                else:
                    pending_signal = {"symbol": symbol, "date": day(candles[j].time), "close": c, "setup": f.get("setup")}
    open_at_end = None
    if pos is not None:
        last = candles[-1].close
        open_at_end = {"symbol": symbol, "side": spec.side, "entry_date": day(pos["entry_t"]), "entry_px": pos["entry_px"], "last_close": last,
                       "unrealized_pct": d * (last / pos["entry_px"] - 1) * 100, "bars_held": pos["held"], "stop": pos["stop"], "target": pos["target"]}
    return {"trades": trades, "open_at_end": open_at_end, "pending_signal": pending_signal}
