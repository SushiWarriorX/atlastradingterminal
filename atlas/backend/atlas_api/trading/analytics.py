"""Portfolio risk analytics, scenarios and performance. Statistics are floats (not accounting); money inputs are Decimal.

Method (stated in every response): historical simulation applying TODAY's weights to the aligned history of the holdings.
It describes how this portfolio would have behaved, not what it will do. Cash earns 0. Series from different calendars (BTC 24/7
vs US equities) are aligned to the dates they share, so BTC weekend moves are compressed into Monday's return.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import numpy as np

from .. import compare as cmp
from .. import instruments as I
from ..models import ProviderUnavailable
from ..service import MarketService
from .money import ZERO, D, q, s

MIN_OBS = 60
ANN = 252


def _drawdown(returns: np.ndarray) -> float:
    eq = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1).min())


def risk_stats(port: np.ndarray, equity: float) -> dict:
    n = len(port)
    out: dict = {"observations": n}
    out["volatility_ann_pct"] = float(np.std(port, ddof=1) * np.sqrt(ANN) * 100)
    out["max_drawdown_pct"] = _drawdown(port) * 100
    var95 = -float(np.percentile(port, 5))
    out["var_95_1d"] = {"pct": var95 * 100, "amount": var95 * equity, "method": "historical simulation, 5th percentile of aligned daily returns"}
    tail = port[port <= -var95 + 1e-12]    # tolerance: ties at the boundary must not be dropped by float noise
    out["es_95_1d"] = ({"pct": -float(tail.mean()) * 100, "amount": -float(tail.mean()) * equity, "tail_observations": int(len(tail))}
                       if len(tail) >= 10 else {"available": False, "reason": f"only {len(tail)} tail observations (need 10)"})
    out["var_99_1d"] = ({"pct": -float(np.percentile(port, 1)) * 100, "amount": -float(np.percentile(port, 1)) * equity}
                        if n >= 200 else {"available": False, "reason": f"{n} observations (need 200 for a 1% tail)"})
    out["worst_day_pct"] = float(port.min()) * 100
    return out


async def portfolio_risk(eng, pid: int, benchmark: str = "SPY") -> dict:
    v = await eng.valuation(pid)
    equity = float(v["equity"])
    pos = [p for p in v["positions"] if p["value"] > 0]
    base = {"portfolio_id": v["portfolio"]["id"], "equity": s(v["equity"]), "exposure": _exp_json(v["exposure"]), "valuation_note": v["valuation_note"],
            "assumptions": ["Historical simulation with today's weights applied to aligned daily returns; cash earns 0; fees and slippage ignored.",
                            "Mixed calendars are aligned to shared dates; BTC weekend moves land in Monday's return. Annualised with sqrt(252).",
                            "Not a forecast: the past window may not contain the risks that matter."]}
    if not pos:
        return {**base, "available": False, "reason": "no positions"}
    svc: MarketService = eng.svc
    insts = [I.resolve(p["instrument_id"]) for p in pos]
    bench_inst = I.resolve(benchmark) if benchmark and benchmark.lower() != "none" else None
    fetch = insts + ([bench_inst] if bench_inst else [])
    res = await asyncio.gather(*(svc.ohlcv(i, "1d", 300) for i in fetch), return_exceptions=True)
    missing = [f"{i.symbol}: {r}" for i, r in zip(fetch, res) if isinstance(r, Exception)]
    if missing:
        return {**base, "available": False, "reason": "history unavailable for " + "; ".join(missing)}
    candles = {i.id: r.candles for i, r in zip(fetch, res)}
    try:
        _, al = cmp.align(candles, "1d", min_common=MIN_OBS + 1)
    except cmp.NoOverlap as e:
        return {**base, "available": False, "reason": str(e)}
    closes = {k: [c.close for c in vv] for k, vv in al.items()}
    rets = {k: cmp.returns(vv) for k, vv in closes.items()}
    w = np.array([float(p["value"]) / equity for p in pos])
    port = sum(w[i] * rets[p["instrument_id"]] for i, p in enumerate(pos))
    out = {**base, "available": True, "window": {"observations": len(port), "weights": {p["symbol"]: float(w[i]) for i, p in enumerate(pos)}, "cash_weight": float(1 - w.sum())},
           **risk_stats(np.asarray(port), equity)}
    if bench_inst:
        b = rets[bench_inst.id]
        out["beta"] = {"benchmark": bench_inst.symbol, "value": cmp.beta(np.asarray(port), b), "correlation": cmp.corr(np.asarray(port), b),
                       "by_position": {p["symbol"]: cmp.beta(rets[p["instrument_id"]], b) for p in pos}}
    if len(pos) > 1:
        ids = [p["instrument_id"] for p in pos]
        out["correlation"] = {"symbols": [p["symbol"] for p in pos], "matrix": [[cmp.corr(rets[a], rets[b]) for b in ids] for a in ids]}
        pairs = sorted(((out["correlation"]["matrix"][i][j], pos[i]["symbol"], pos[j]["symbol"]) for i in range(len(ids)) for j in range(i + 1, len(ids))
                        if out["correlation"]["matrix"][i][j] is not None), reverse=True)
        out["most_correlated"] = [{"pair": f"{a}/{b}", "corr": c} for c, a, b in pairs[:3]]
    wsum = sum(float(p["value"]) for p in pos)
    shares = [float(p["value"]) / wsum for p in pos]
    out["concentration"] = {"top_position": max(pos, key=lambda p: p["value"])["symbol"], "top_position_pct_of_equity": max(float(p["weight_pct"] or 0) for p in pos),
                            "hhi_invested": float(sum(x * x for x in shares)), "note": "HHI 1.0 = one position; 1/N = evenly spread."}
    liq = []
    for p, i in zip(pos, insts):
        c = candles[i.id][-20:]
        adv = float(np.mean([x.close * x.volume for x in c])) if c and any(x.volume > 0 for x in c) else None
        val = float(p["value"])
        liq.append({"symbol": p["symbol"], "value": val, "adv_usd_20d": adv, "pct_of_adv": (val / adv * 100) if adv else None,
                    "days_to_exit_at_10pct": (val / (0.1 * adv)) if adv else None})
    out["liquidity"] = {"positions": liq, "note": "Average daily dollar volume over 20 bars; exit time assumes 10% participation. Crypto volume is single-venue."}
    return out


def _exp_json(e: dict) -> dict:
    return {"gross": s(e["gross"]), "gross_pct": float(e["gross_pct"]) if e["gross_pct"] is not None else None, "leverage": float(e["leverage"]) if e["leverage"] is not None else None,
            "largest_position_pct": float(e["largest_position_pct"]) if e["largest_position_pct"] is not None else None,
            "by_asset_class": {k: {"value": s(x["value"]), "pct": float(x["pct"]) if x["pct"] is not None else None} for k, x in e["by_asset_class"].items()},
            "by_sector": {k: {"value": s(x["value"]), "pct": float(x["pct"]) if x["pct"] is not None else None} for k, x in e["by_sector"].items()}}


async def scenario(eng, pid: int, shocks: dict[str, float], benchmark: str | None = None, benchmark_shock: float | None = None) -> dict:
    """Deterministic instantaneous shocks. Explicit per-symbol shocks win; otherwise a benchmark shock is applied through each
    position's estimated beta (labelled as an estimate). No gap, liquidity or second-order effects are modelled."""
    v = await eng.valuation(pid)
    for k, x in shocks.items():
        if not -100 <= x <= 1000:
            raise ValueError(f"shock for {k} must be between -100% and +1000%")
    betas: dict[str, float | None] = {}
    beta_note = None
    if benchmark_shock is not None:
        if benchmark is None:
            raise ValueError("benchmark_shock needs a benchmark symbol")
        if not -100 <= benchmark_shock <= 1000:
            raise ValueError("benchmark_shock must be between -100% and +1000%")
        r = await portfolio_risk(eng, pid, benchmark)
        if r.get("available") and r.get("beta"):
            betas = r["beta"]["by_position"]
        else:
            beta_note = f"betas unavailable ({r.get('reason', 'no benchmark data')}): benchmark shock not applied"
    keyed = {k.upper(): x for k, x in shocks.items()}
    rows, total = [], ZERO
    for p in v["positions"]:
        shock, src = None, "none"
        for key in (p["symbol"].upper(), p["instrument_id"].upper()):
            if key in keyed:
                shock, src = keyed[key], "explicit"
        if shock is None and benchmark_shock is not None and betas.get(p["symbol"]) is not None:
            shock = round(betas[p["symbol"]] * benchmark_shock, 4)     # an estimate: 4 dp keeps float noise out of money values
            src = f"beta-implied (estimated beta {betas[p['symbol']]:.2f} x {benchmark_shock:g}% {benchmark})"
        pnl = p["value"] * D(shock) / 100 if shock is not None else ZERO
        total += pnl
        rows.append({"symbol": p["symbol"], "value": p["value"], "shock_pct": shock, "source": src, "pnl": pnl})
    eq = v["equity"]
    unknown = [k for k in keyed if k not in {p["symbol"].upper() for p in v["positions"]} | {p["instrument_id"].upper() for p in v["positions"]}]
    return {"portfolio_id": pid, "equity_before": s(eq), "equity_after": s(eq + total), "pnl": s(total), "pnl_pct_of_equity": float(total / eq * 100) if eq > 0 else None,
            "positions": [{**r, "value": s(r["value"]), "pnl": s(r["pnl"])} for r in rows], "ignored_shocks": unknown, "note": beta_note,
            "caveats": ["Instantaneous shock on current marks. Gaps, liquidity, margin effects and correlation changes in a real stress are not modelled.",
                        "Beta-implied shocks use historical betas, which are unstable (see /risk)."]}


def performance(eng, pid: int) -> dict:
    pf = eng.portfolio(pid)
    rows = eng.db.q("SELECT ts, equity, cash FROM equity_history WHERE portfolio_id=? ORDER BY ts", (pf["id"],))
    pts = [{"ts": r["ts"], "equity": r["equity"], "cash": r["cash"]} for r in rows]
    out = {"portfolio_id": pf["id"], "points": pts, "starting_cash": pf["starting_cash"],
           "note": "Equity is sampled about once a minute while the server runs; gaps mean the server was off."}
    if len(pts) >= 2:
        e = np.array([float(x["equity"]) for x in pts])
        base = float(pf["starting_cash"]) if pf["kind"] == "paper" else e[0]
        out.update(start_equity=base, latest_equity=float(e[-1]), total_return_pct=(e[-1] / base - 1) * 100 if base else None,
                   max_drawdown_pct=float((e / np.maximum.accumulate(e) - 1).min() * 100), samples=len(pts))
    else:
        out["reason"] = "fewer than 2 equity samples yet"
    return out
