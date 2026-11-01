"""Backtest orchestration: bars -> per-symbol simulation -> portfolio -> honest statistics. Deterministic: same bars and spec, same result."""
from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

from ..journal import stats as jstats
from ..scanner.bars import BarSource
from ..scanner.universe import load
from . import engine, portfolio
from .spec import BtSpec


def _stat_rows(trades: list[dict]) -> list[dict]:
    """Adapt backtest trades to the journal's statistics (unit: percent return per trade, net of costs)."""
    out = []
    for t in trades:
        closed = datetime.fromtimestamp(t["exit_t"], timezone.utc)
        out.append({"net_pnl": t["net_pct"], "closed_at": closed, "opened_at": datetime.fromtimestamp(t["entry_t"], timezone.utc),
                    "holding_seconds": t["bars_held"] * 86400, "fees": t["cost_pct"], "r_multiple": t["r_multiple"], "symbol": t["symbol"],
                    "source": "backtest", "side": t["side"], "asset_class": "equity", "setup": t["setup"], "tags": [],
                    "exit_reason": t["exit_reason"], "currency": "%"})
    return out


def summarize(trades: list[dict], rows: list[dict] | None = None) -> dict:
    s = jstats.summary(rows if rows is not None else _stat_rows(trades))
    s.pop("max_drawdown", None)       # drawdown of summed per-trade percentages is not meaningful; the portfolio curve has the real one
    s["unit"] = "percent return per trade, net of costs"
    s["avg_hold_bars"] = (sum(t["bars_held"] for t in trades) / len(trades)) if trades else None
    return s


PARALLEL_MIN = 8      # below this many symbols a process pool costs more than it saves


def _worker(args):
    sym, candles, bench, spec_json = args
    return sym, engine.simulate(sym, candles, bench, BtSpec.model_validate_json(spec_json))


def _simulate_all(spec: BtSpec, bars: dict, used: list[str], bench, progress) -> tuple[dict[str, dict], str]:
    out: dict[str, dict] = {}
    workers = min(os.cpu_count() or 1, 4)
    if workers > 1 and len(used) >= PARALLEL_MIN:
        try:
            sj = spec.model_dump_json()
            with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as pool:
                futs = [pool.submit(_worker, (s, bars[s], bench, sj)) for s in used]
                for k, f in enumerate(as_completed(futs)):
                    sym, r = f.result()
                    out[sym] = r
                    if progress:
                        progress(k + 1, len(used))
            return out, f"parallel x{workers}"
        except Exception:  # noqa: BLE001  a restricted environment may forbid processes: the serial path gives the same result
            out.clear()
    for k, s in enumerate(used):
        out[s] = engine.simulate(s, bars[s], bench, spec)
        if progress:
            progress(k + 1, len(used))
    return out, "serial"


def _rounded(rows: list[dict]) -> list[dict]:
    return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()} for t in rows]


def compute(spec: BtSpec, bars: dict[str, list], symbols: list[str], bench: list | None, progress=None) -> dict:
    trades: list[dict] = []
    open_at_end: list[dict] = []
    pending: list[dict] = []
    used = [s for s in symbols if s in bars and len(bars[s]) > engine.WARMUP]
    sims, mode = _simulate_all(spec, bars, used, bench, progress)
    for s in used:                # fixed symbol order: the result never depends on which worker finished first
        r = sims[s]
        trades += r["trades"]
        if r["open_at_end"]:
            open_at_end.append(r["open_at_end"])
        if r["pending_signal"]:
            pending.append(r["pending_signal"])
    trades.sort(key=lambda t: (t["entry_t"], t["symbol"]))
    timeline = sorted({c.time for s in used for c in bars[s][engine.WARMUP:]})
    cutoff = timeline[int(len(timeline) * (1 - spec.oos_fraction))] if spec.oos_fraction > 0 and len(timeline) > 10 else None
    rows = _stat_rows(trades)
    in_sample = [i for i, t in enumerate(trades) if cutoff is None or t["signal_t"] < cutoff]
    held_out = [i for i, t in enumerate(trades) if cutoff is not None and t["signal_t"] >= cutoff]
    closes = {s: {c.time: c.close for c in bars[s]} for s in {t["symbol"] for t in trades}}
    port = portfolio.run(trades, closes, spec)
    bench_stats = None
    if bench and port["curve"]:
        t0, t1 = port["curve"][0]["t"], port["curve"][-1]["t"]
        bs = [c for c in bench if t0 <= c.time <= t1]
        if len(bs) > 2:
            m = portfolio.metrics([c.time for c in bs], [c.close for c in bs])
            bench_stats = {"symbol": spec.benchmark, **m, "curve": [{"t": c.time, "equity": spec.initial_capital * c.close / bs[0].close} for c in bs]}
    return {
        "summary": summarize(trades, rows), "in_sample": summarize([trades[i] for i in in_sample], [rows[i] for i in in_sample]),
        "out_of_sample": summarize([trades[i] for i in held_out], [rows[i] for i in held_out]),
        "split": {"oos_fraction": spec.oos_fraction, "cutoff_date": engine.day(cutoff) if cutoff else None,
                  "note": "Chronological hold-out: nothing was fitted on either part, so this is a stability check, not parameter validation."},
        "groups": {g: jstats.group_by(rows, g) for g in ("year", "exit_reason", "symbol", "r_bucket")},
        "portfolio": {k: v for k, v in port.items() if k != "trades"},
        "portfolio_trades": _rounded(port.get("trades", [])),
        "benchmark": bench_stats,
        "trades": _rounded(trades),
        "open_at_end": open_at_end, "pending_signals": sorted(pending, key=lambda x: x["symbol"]),
        "symbols_traded": len({t["symbol"] for t in trades}), "symbols_tested": len(used), "compute_mode": mode,
    }


CAVEATS = [
    "Backtests describe the past. They do not predict, and a good one is a reason to test further, not to trade.",
    "The universe is today's list, so symbols that failed or were removed are missing (survivorship bias flatters long strategies).",
    "Prices are unadjusted for dividends. Daily bars cannot show intrabar order: a stop and a target in the same bar resolve to the stop.",
    "Costs are flat assumptions (commission and slippage in bps per side), not measured from your broker.",
    "Preset thresholds were chosen by hand and are not optimised here. Trying many variants on the same history and keeping the best one will overfit.",
    "Same-day entries beyond the position limit are skipped in alphabetical order; no ranking is used.",
]


async def run(spec: BtSpec, source: BarSource, symbols: list[str] | None = None, progress=None) -> dict:
    t0 = time.monotonic()
    syms = symbols if symbols is not None else await load(spec.universe)
    truncated = len(syms) > spec.max_symbols
    syms = syms[: spec.max_symbols]
    batch = await source.fetch(sorted(set(syms) | {spec.benchmark}), None)
    bench = batch.bars.get(spec.benchmark)
    notes = list(batch.notes)
    if truncated:
        notes.append(f"universe limited to the first {spec.max_symbols} symbols (max_symbols)")
    if bench is None:
        notes.append(f"benchmark {spec.benchmark} unavailable: relative-strength rules cannot pass and no buy-and-hold comparison is shown")
    res = await asyncio.to_thread(compute, spec, batch.bars, syms, bench, progress)
    spans = [(b[0].time, b[-1].time) for s in syms if (b := batch.bars.get(s))]          # bars are ascending: first and last are enough
    res["meta"] = {
        "spec": spec.model_dump(mode="json"), "universe": spec.universe, "universe_size": len(syms), "with_data": len([s for s in syms if s in batch.bars]),
        "failed": len(batch.failed), "failed_sample": dict(list(batch.failed.items())[:5]),
        "provider": batch.provider, "status": batch.status.value, "data_as_of": batch.as_of.isoformat() if batch.as_of else None,
        "bars_from": engine.day(min(a for a, _ in spans)) if spans else None, "bars_to": engine.day(max(b for _, b in spans)) if spans else None,
        "ran_at": datetime.now(timezone.utc).isoformat(), "duration_ms": int((time.monotonic() - t0) * 1000), "notes": notes, "caveats": CAVEATS,
    }
    return res
