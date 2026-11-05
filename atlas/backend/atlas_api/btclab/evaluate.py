"""Strategy evaluation that refuses to flatter: out-of-sample first, walk-forward second, robustness third, and an evidence label that is often "none".

Method, in the order the numbers are produced:
 1. Default parameters, fixed in advance (never tuned), run over the whole history. The first 70% of bars is "in-sample" and the last 30% "out-of-sample".
    Because nothing was fitted on either part, the out-of-sample part is a fair test of the rule on data it was not designed around.
 2. Walk-forward: from 40% of the history onward, in expanding windows, pick the best of five parameter values on the past only (by Sharpe), then trade the next
    window with it, starting flat. The stitched result is what a trader re-tuning as they went would have got.
 3. Robustness: the same rule with each of five nearby parameter values, out-of-sample; and the default again with fees and slippage doubled.
 4. Evidence label: "none", "weak" or "moderate". Never "strong": BTC has only a handful of market cycles, so no backtest here can be called conclusive.
Net figures are after fees, slippage and (for perpetuals) funding. Sharpe uses per-bar equity returns with a 0% risk-free rate.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .data import BARS_PER_YEAR, TF_SECONDS
from .engine import Costs, simulate
from .strategies import S, Strategy

MIN_TRADES = 15           # fewer out-of-sample trades than this and the numbers say little
IS_FRACTION = 0.70
WF_START = 0.40
WF_TEST = 0.15
ROBUST_SHARE = 0.60
EVIDENCE_RANK = {"moderate": 2, "weak": 1, "none": 0}


class LabError(Exception):
    pass


def iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).date().isoformat()


def metrics(curve: list[float], trades: list[dict], bpy: int, exposure: float | None = None) -> dict:
    cv = np.asarray(curve, float)
    n = len(cv) - 1
    out = {"bars": n, "net_return_pct": None, "cagr_pct": None, "max_drawdown_pct": None, "sharpe": None, "win_rate_pct": None, "profit_factor": None, "trades": 0, "avg_trade_pct": None, "exposure_pct": None if exposure is None else exposure * 100}
    if n < 2 or cv[0] <= 0:
        return out
    out["net_return_pct"] = (cv[-1] / cv[0] - 1) * 100
    years = n / bpy
    if years >= 1 and cv[-1] > 0:
        out["cagr_pct"] = ((cv[-1] / cv[0]) ** (1 / years) - 1) * 100
    peak = np.maximum.accumulate(cv)
    out["max_drawdown_pct"] = float(((cv / np.where(peak > 0, peak, np.nan)) - 1).min() * 100)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(cv) / np.where(cv[:-1] > 0, cv[:-1], np.nan)
    r = r[np.isfinite(r)]
    if len(r) > 2 and r.std() > 0:
        out["sharpe"] = float(r.mean() / r.std() * math.sqrt(bpy))
    closed = [x for x in trades if not x.get("open")]
    out["trades"] = len(closed)
    if closed:
        wins, losses = [x["ret_pct"] for x in closed if x["ret_pct"] > 0], [x["ret_pct"] for x in closed if x["ret_pct"] <= 0]
        out["win_rate_pct"] = len(wins) / len(closed) * 100
        out["avg_trade_pct"] = sum(x["ret_pct"] for x in closed) / len(closed)
        out["profit_factor"] = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None
        out["no_losing_trades"] = not losses
    return out


class Frame:
    """Bars as arrays plus the per-bar funding, ready for the engine."""

    def __init__(self, rows: list[tuple], tf: str, funding: list[tuple[int, float]] | None, perp: bool):
        if len(rows) < 250:
            raise LabError(f"Only {len(rows)} {tf} bars are available; at least 250 are needed for any test.")
        self.tf, self.perp, self.bpy = tf, perp, BARS_PER_YEAR[tf]
        step = TF_SECONDS[tf]
        self.df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v"]).set_index("t", drop=False)
        self.notes: list[str] = []
        self.first, self.last = 0, len(rows)
        self.fund = None
        if perp:
            if not funding:
                raise LabError("No funding history is saved yet for perpetuals. Refresh the data first.")
            ft = [x[0] for x in funding]
            cum = np.concatenate([[0.0], np.cumsum([x[1] for x in funding])])
            ts = self.df["t"].to_numpy()
            lo = np.array([bisect_left(ft, int(t)) for t in ts])
            hi = np.array([bisect_left(ft, int(t) + step) for t in ts])
            self.fund = (cum[hi] - cum[lo])
            hours = np.maximum(hi - lo, 1)
            self.df["funding_ann"] = np.where(hi > lo, (self.fund / hours) * 8760 * 100, np.nan)
            self.first = int(np.argmax(ts >= ft[0]))
            self.last = int(np.searchsorted(ts, ft[-1] - step, side="right"))
            if self.last - self.first < 250:
                raise LabError("Funding history overlaps fewer than 250 bars of this timeframe; perpetual tests need more.")
            self.notes.append(f"Perpetual tests use funding from {iso(ft[0])} onward (Hyperliquid), so they cover {iso(int(ts[self.first]))} to {iso(int(ts[self.last - 1]))} only.")
        self.t, self.o, self.h, self.l, self.c = (self.df[k].to_numpy(float) for k in ("t", "o", "h", "l", "c"))

    @property
    def n(self) -> int:
        return self.last - self.first


def costs_for(f: Frame, strat: Strategy, req: dict, mult: float = 1.0) -> Costs:
    return Costs(fee_bps=req["fee_bps"] * mult, slippage_bps=req["slippage_bps"] * mult, leverage=req["leverage"] if f.perp else 1.0, perp=f.perp, stop_pct=strat.stop_pct)


def target_for(strat: Strategy, f: Frame, params: dict, long_short: bool) -> np.ndarray:
    tgt = strat.build(f.df, params).to_numpy(float)
    tgt = np.nan_to_num(tgt)
    if not (f.perp and long_short and strat.symmetric):
        tgt = np.clip(tgt, 0, 1)
    return tgt


def run(f: Frame, tgt, costs: Costs, a: int, b: int) -> dict:
    return simulate(f.t, f.o, f.h, f.l, f.c, tgt, costs, a, b, funding=f.fund)


def _slice(res: dict, k0: int, k1: int, f: Frame, a: int) -> tuple[list[float], list[dict]]:
    """Equity curve points k0..k1 (inclusive, indexes into res['curve']) re-based to start at 1.0, and the trades that closed inside."""
    base = res["curve"][k0]
    cv = [x / base if base > 0 else 0.0 for x in res["curve"][k0:k1 + 1]]
    t0, t1 = f.t[a + k0 - 1] if k0 > 0 else f.t[a], f.t[a + k1 - 1]
    return cv, [x for x in res["trades"] if t0 <= x["exit_t"] <= t1]


def down(curve: list[float], m: int = 240) -> list[float]:
    if len(curve) <= m:
        return [round(x, 5) for x in curve]
    idx = np.linspace(0, len(curve) - 1, m).astype(int)
    return [round(curve[i], 5) for i in idx]


def drawdown(curve: list[float]) -> list[float]:
    cv = np.asarray(curve, float)
    pk = np.maximum.accumulate(cv)
    return (np.where(pk > 0, cv / np.where(pk > 0, pk, 1) - 1, -1) * 100).tolist()


def buy_and_hold(f: Frame, req: dict, a: int, b: int) -> dict:
    res = run(f, np.ones(len(f.t)), Costs(fee_bps=req["fee_bps"], slippage_bps=req["slippage_bps"], leverage=1.0, perp=False), a, b)
    return res


def evaluate(strat: Strategy, f: Frame, req: dict, bh: dict) -> dict:
    a, b = f.first, f.last
    ls = bool(req.get("long_short"))
    costs = costs_for(f, strat, req)
    params = dict(strat.params)
    tgt = target_for(strat, f, params, ls)
    full = run(f, tgt, costs, a, b)
    n = b - a
    k = int(n * IS_FRACTION)
    ins_c, ins_t = _slice(full, 0, k, f, a)
    oos_c, oos_t = _slice(full, k, n, f, a)
    m_full, m_is, m_oos = metrics(full["curve"], full["trades"], f.bpy, full["exposure"]), metrics(ins_c, ins_t, f.bpy), metrics(oos_c, oos_t, f.bpy)
    bh_is, bh_oos = _slice(bh, 0, k, f, a), _slice(bh, k, n, f, a)
    m_bh_full, m_bh_oos = metrics(bh["curve"], [], f.bpy), metrics(bh_oos[0], [], f.bpy)

    # walk-forward
    pname = next(iter(strat.grid))
    wf_curve, wf_trades, folds = [1.0], [], []
    start = int(n * WF_START)
    step = max(int(n * WF_TEST), 30)
    while start + 30 <= n:
        end = min(start + step, n)
        best, best_s = None, -1e9
        for v in strat.grid[pname]:
            p = {**params, pname: v}
            tr = run(f, target_for(strat, f, p, ls), costs, a, a + start)
            mm = metrics(tr["curve"], tr["trades"], f.bpy)
            s = mm["sharpe"] if mm["sharpe"] is not None and mm["trades"] >= 3 else -1e8
            if s > best_s:
                best, best_s = v, s
        p = {**params, pname: best if best is not None else params[pname]}
        te = run(f, target_for(strat, f, p, ls), costs, a + start, a + end)
        base = wf_curve[-1]
        wf_curve += [base * x for x in te["curve"][1:]]
        wf_trades += te["trades"]
        folds.append({"from": iso(int(f.t[a + start])), "to": iso(int(f.t[a + end - 1])), "chosen": {pname: p[pname]}, "train_sharpe": None if best_s < -1e7 else round(best_s, 2), "test_return_pct": (te["curve"][-1] - 1) * 100})
        start = end
    m_wf = metrics(wf_curve, wf_trades, f.bpy)
    wf_eff = (m_wf["sharpe"] / m_is["sharpe"]) if m_wf["sharpe"] is not None and m_is["sharpe"] not in (None, 0) and m_is["sharpe"] > 0 else None

    # robustness: neighbours out of sample, and doubled costs
    nb = []
    for v in strat.grid[pname]:
        r = run(f, target_for(strat, f, {**params, pname: v}, ls), costs, a + k, b)
        nb.append({pname: v, "oos_return_pct": (r["curve"][-1] - 1) * 100})
    share = sum(1 for x in nb if x["oos_return_pct"] > 0) / len(nb)
    stress = run(f, tgt, costs_for(f, strat, req, 2.0), a + k, b)
    stress_ret = (stress["curve"][-1] - 1) * 100

    # evidence
    reasons: list[str] = []
    oos_ret, wf_ret = m_oos["net_return_pct"] or 0.0, m_wf["net_return_pct"] or 0.0
    if full["liquidated"]:
        reasons.append("The account was liquidated at some point in the history.")
    if m_oos["trades"] < MIN_TRADES:
        reasons.append(f"Only {m_oos['trades']} trade{'' if m_oos['trades'] == 1 else 's'} out of sample (fewer than {MIN_TRADES}): too few to tell skill from luck.")
    if oos_ret <= 0:
        reasons.append("Lost money out of sample, on data the rule was not designed around.")
    if wf_ret <= 0:
        reasons.append("Re-tuning as you go (walk-forward) did not make money.")
    level = "none"
    if not full["liquidated"] and m_oos["trades"] >= MIN_TRADES and oos_ret > 0 and wf_ret > 0:
        level = "weak"
        if share < ROBUST_SHARE:
            reasons.append(f"Fragile: only {share * 100:.0f}% of nearby parameter values made money out of sample.")
        if stress_ret <= 0:
            reasons.append("Stopped making money when fees and slippage were doubled.")
        beats = (m_oos["sharpe"] or -9) >= (m_bh_oos["sharpe"] or 9)
        if not beats:
            reasons.append("Risk-adjusted (Sharpe) it did not beat simply holding BTC over the same out-of-sample period.")
        if share >= ROBUST_SHARE and stress_ret > 0 and beats:
            level = "moderate"
            reasons.append("Held up out of sample, in walk-forward, across nearby parameters and with doubled costs. That is still limited evidence: BTC has had only a few market cycles.")
    elif not reasons:
        reasons.append("No reliable evidence.")

    conds = strat.conds(f.df, params)
    now_t = tgt[b - 1]
    return {
        "id": strat.id, "name": strat.name, "family": strat.family, "params": params, "stop_pct": strat.stop_pct,
        "full": m_full, "in_sample": m_is, "out_of_sample": m_oos, "walk_forward": {**m_wf, "folds": folds, "efficiency": wf_eff},
        "buy_and_hold": {"full": m_bh_full, "out_of_sample": m_bh_oos},
        "robustness": {"param": pname, "neighbours": nb, "share_positive": share, "doubled_costs_oos_return_pct": stress_ret},
        "evidence": {"level": level, "reasons": reasons, "min_trades": MIN_TRADES},
        "costs": {"fees_paid_pct": full["fees_paid_pct"], "funding_paid_pct": full["funding_paid_pct"], "liquidated": full["liquidated"]},
        "now": {"rule_position": "long" if now_t > 0 else "short" if now_t < 0 else "flat", "conditions": conds, "as_of": iso(int(f.t[b - 1])),
                "note": "This says whether the rule's conditions are true on the latest bar. It is a description of the rule, not a prediction."},
        "curve": {"strategy": down(full["curve"]), "buy_and_hold": down(bh["curve"]), "drawdown": down(drawdown(full["curve"])), "oos_starts_at": k / n, "from": iso(int(f.t[a])), "to": iso(int(f.t[b - 1]))},
        "trades": {"total": m_full["trades"], "recent": [{**x, "entry": iso(int(x["entry_t"])), "exit": iso(int(x["exit_t"]))} for x in full["trades"][-40:]]},
    }


def rank_key(r: dict):
    wf = r["walk_forward"]["sharpe"]
    return (EVIDENCE_RANK[r["evidence"]["level"]], wf if wf is not None else -99)


def run_lab(rows, funding, req: dict) -> dict:
    ids = req["strategies"]
    unknown = [i for i in ids if i not in S]
    if unknown:
        raise LabError(f"Unknown strategy: {unknown[0]}")
    perp = req["market"] == "perp"
    ls = bool(req.get("long_short")) and perp
    req = {**req, "long_short": ls}
    f = Frame(rows, req["timeframe"], funding, perp)
    a, b = f.first, f.last
    bh = buy_and_hold(f, req, a, b)
    results, skipped = [], []
    for sid in ids:
        st = S[sid]
        if st.requires_funding and not perp:
            skipped.append({"id": sid, "reason": "This strategy uses perpetual funding, so it only runs on the perpetual market."})
            continue
        results.append(evaluate(st, f, req, bh))
    results.sort(key=rank_key, reverse=True)
    notes = list(f.notes)
    if req["timeframe"] != "1d":
        notes.append("Intraday history is shorter than daily, so there are fewer market regimes in the test. Treat these results with extra caution.")
    if ls:
        notes.append("Long/short applies only to strategies with a mirror-image short side; the others stay long-only.")
    return {"settings": {k: req[k] for k in ("timeframe", "market", "leverage", "long_short", "fee_bps", "slippage_bps")}, "period": {"from": iso(int(f.t[a])), "to": iso(int(f.t[b - 1])), "bars": b - a},
            "results": results, "skipped": skipped, "buy_and_hold": {"metrics": metrics(bh["curve"], [], f.bpy), "note": "Buying at the start and holding to the end, after one round of fees and slippage."},
            "notes": notes, "method": __doc__.strip().split("\n\n")[0] if __doc__ else "",
            "caveats": ["Past results do not predict future results. Rules were fixed in advance and are not tuned to this history.", "BTC history covers only a few market cycles, so even a good result is limited evidence.",
                        "Liquidation is approximated and exchange rules differ.", "This is research only: nothing here places a trade."]}
