"""Self-improving research loop for the Strategy Lab (research only: it changes a backtest rule, never places a trade).

One round = stress test -> find where the rule loses money -> pick a fix from a fixed menu -> rerun -> keep it or throw it away.

The rules that stop the loop from fooling itself:
 - Five years of daily BTC-USD. The first 70% is the DESIGN period; the last 30% is the HOLDOUT and is sealed. No decision (diagnosis, choice of fix, keep/discard)
   ever looks at it. It is opened once, at the end, to compare the starting rule with the final rule.
 - The menu of fixes is written down in advance with fixed settings. The loop picks WHICH fix, never tunes a number, so there is little room to fit noise.
 - A fix is kept only if, on the design period, Sharpe improves by a margin that grows with every fix already tried (more tries = more luck = a higher bar),
   the worst drawdown does not get worse, the loss in the worst crashes does not get worse, and at least MIN_TRADES trades remain.
 - If the final rule does not hold up on the sealed holdout, the verdict says so and the starting rule is the recommendation.
Costs (fees, slippage) apply to every run. Data is Coinbase daily candles. Past results do not predict future results.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

import numpy as np
import pandas as pd

from .evaluate import Frame, LabError, _slice, buy_and_hold, costs_for, iso, metrics, run, target_for
from .strategies import S, atr, sma

YEARS = 5
MIN_BARS = 365 * 2
DESIGN_FRACTION = 0.70
MIN_TRADES = 10
HOLDOUT_MIN_TRADES = 3          # a changed rule that made fewer trades than this on the holdout is "inconclusive", not "held up"
BASE_MARGIN = 0.05              # Sharpe improvement needed for the first fix tried; it grows by this much for each further try
DD_TOLERANCE = 1.0              # percentage points the worst drawdown may worsen by
CRASH_DEPTH = 20.0              # a buy-and-hold fall of at least this % counts as a stress window
MAX_ROUNDS = 5
WHIPSAW_BARS = 10
VOL_RATIO = 1.5
MIN_SHARE = 0.20                # a cause must explain at least this share of the losses before a fix is tried for it


# ---------------------------------------------------------------- the menu of fixes (settings are fixed here, never tuned)
def _trend_filter(f: Frame, tgt, costs):
    ma = sma(f.df["c"], 200).to_numpy()
    return np.where(f.c > np.nan_to_num(ma, nan=np.inf), tgt, 0.0), costs


def _calm_only(f: Frame, tgt, costs):
    a = (atr(f.df, 14) / f.df["c"]).to_numpy()
    med = pd.Series(a).rolling(365, min_periods=90).median().to_numpy()
    return np.where(np.nan_to_num(a / med, nan=0.0) > VOL_RATIO, 0.0, tgt), costs


def _confirm_entry(f: Frame, tgt, costs):
    prev = np.r_[0.0, tgt[:-1]]
    return np.where((tgt > 0) & (prev > 0), tgt, 0.0), costs        # enter only on the second consecutive bar of signal; exits stay immediate


def _min_hold(f: Frame, tgt, costs, bars: int = 5):
    out, age, on = np.zeros(len(tgt)), 0, False
    for i, v in enumerate(tgt):
        if on:
            age += 1
            if v <= 0 and age >= bars:
                on = False
        elif v > 0:
            on, age = True, 0
        out[i] = 1.0 if on else 0.0
    return out, costs


def _stop15(f: Frame, tgt, costs):
    return tgt, replace(costs, stop_pct=min(costs.stop_pct, 15.0) if costs.stop_pct else 15.0)


REMEDIES: dict[str, dict] = {
    "trend_filter": {"name": "Only hold when BTC is above its 200-day average", "cause": "bear_market", "fn": _trend_filter},
    "calm_only": {"name": "Stand aside when volatility is 1.5x its one-year norm", "cause": "high_volatility", "fn": _calm_only},
    "confirm_entry": {"name": "Wait for a second day of signal before buying", "cause": "whipsaw", "fn": _confirm_entry},
    "stop15": {"name": "Add a 15% protective stop", "cause": "deep_loss", "fn": _stop15},
    "min_hold": {"name": "Hold at least 5 days once in", "cause": "cost_drag", "fn": _min_hold},
}
CAUSE_TEXT = {
    "bear_market": "bought while BTC was below its 200-day average (a falling market)",
    "high_volatility": "bought when volatility was unusually high",
    "whipsaw": f"bought and was stopped out within {WHIPSAW_BARS} days (false signals)",
    "deep_loss": "held a losing trade down more than 15% (nothing cut it)",
    "cost_drag": "lost mostly to fees and slippage from trading too often",
    "other": "other (no clear pattern)",
}


# ---------------------------------------------------------------- measuring
def _index(f: Frame, t: float) -> int:
    return int(np.searchsorted(f.t, t))


def drawdown_episodes(c, lo: int, hi: int, depth: float = CRASH_DEPTH, top: int = 4) -> list[tuple[int, int, float]]:
    """Peak-to-trough falls of at least `depth` % in c[lo:hi], deepest first, as (peak index, trough index, fall %). Indexes are into c."""
    eps, peak, trough, ptr = [], lo, lo, lo
    for i in range(lo, hi):
        if c[i] >= c[peak]:
            if (c[trough] / c[peak] - 1) * 100 <= -depth:
                eps.append((peak, trough, (c[trough] / c[peak] - 1) * 100))
            peak = trough = i
        elif c[i] < c[trough]:
            trough = i
    if (c[trough] / c[peak] - 1) * 100 <= -depth:
        eps.append((peak, trough, (c[trough] / c[peak] - 1) * 100))
    return sorted(eps, key=lambda e: e[2])[:top]


def stress_windows(f: Frame, curve, a: int, lo: int, hi: int) -> list[dict]:
    """How the rule did through each big fall of BTC itself (indexes lo..hi are absolute bars). curve[k] is the equity before bar a+k."""
    out = []
    for p, tr, depth in drawdown_episodes(f.c, lo, hi):
        s, e = max(p - a, 0), tr - a + 1
        if e <= s or e >= len(curve):
            continue
        out.append({"from": iso(int(f.t[p])), "to": iso(int(f.t[tr])), "btc_fall_pct": depth, "rule_pct": (curve[e] / curve[s] - 1) * 100 if curve[s] > 0 else None})
    return out


def start_date_test(f: Frame, tgt, costs, a: int, b: int, n_starts: int = 10, span: int = 365) -> dict:
    """One-year outcomes if the rule had been switched on at ten different dates. Shows how much of the result is down to when you started."""
    if b - a < span * 2:
        return {"available": False}
    res = []
    for s in np.linspace(a, b - span, n_starts).astype(int):
        r = run(f, tgt, costs, int(s), int(s) + span)
        res.append((r["curve"][-1] - 1) * 100)
    return {"available": True, "worst_pct": float(min(res)), "median_pct": float(np.median(res)), "best_pct": float(max(res)), "starts": n_starts, "span_days": span}


def diagnose(f: Frame, res: dict, costs, a: int, hi: int) -> dict:
    """Why did the losing trades lose? Each losing trade is blamed on one cause (first match in the order below); the result is each cause's share of the total loss."""
    ma = sma(f.df["c"], 200).to_numpy()
    av = (atr(f.df, 14) / f.df["c"]).to_numpy()
    med = pd.Series(av).rolling(365, min_periods=90).median().to_numpy()
    closed = [x for x in res["trades"] if not x.get("open") and _index(f, x["exit_t"]) <= hi]
    losers = [x for x in closed if x["ret_pct"] < 0]
    total = sum(-x["ret_pct"] for x in losers)
    by: dict[str, dict] = {k: {"loss_pct": 0.0, "trades": 0} for k in CAUSE_TEXT}
    for x in losers:
        i = max(_index(f, x["entry_t"]) - 1, 0)          # what was known at the close before entry
        j = _index(f, x["exit_t"])
        if not np.isnan(ma[i]) and f.c[i] < ma[i]:
            cause = "bear_market"
        elif not np.isnan(av[i]) and not np.isnan(med[i]) and med[i] > 0 and av[i] / med[i] > VOL_RATIO:
            cause = "high_volatility"
        elif x["bars"] <= WHIPSAW_BARS:
            cause = "whipsaw"
        elif x["ret_pct"] <= -15:
            cause = "deep_loss"
        else:
            cause = "other"
        by[cause]["loss_pct"] += -x["ret_pct"]
        by[cause]["trades"] += 1
    gross_win = sum(x["ret_pct"] for x in closed if x["ret_pct"] > 0)
    fees = res["fees_paid_pct"]
    if gross_win > 0 and fees / gross_win >= 0.25:
        by["cost_drag"] = {"loss_pct": fees, "trades": len(closed)}
    shares = {k: (v["loss_pct"] / total if total else 0.0) for k, v in by.items() if k != "cost_drag"}
    shares["cost_drag"] = (fees / gross_win) if gross_win else 0.0
    worst = sorted(losers, key=lambda x: x["ret_pct"])[:5]
    return {"closed": len(closed), "losers": len(losers), "total_loss_pct": total, "causes": [{"cause": k, "text": CAUSE_TEXT[k], "share": shares.get(k, 0.0), "loss_pct": by[k]["loss_pct"], "trades": by[k]["trades"]}
                                                                                              for k in sorted(shares, key=lambda k: -shares[k]) if shares[k] > 0],
            "worst_trades": [{"entry": iso(int(x["entry_t"])), "exit": iso(int(x["exit_t"])), "days": x["bars"], "ret_pct": x["ret_pct"], "ended_by": x["reason"]} for x in worst], "fees_paid_pct": fees}


class Candidate:
    """A rule = the library strategy plus the fixes accepted so far. Rebuilt from scratch each time so nothing leaks between rounds."""

    def __init__(self, f: Frame, sid: str, req: dict, fixes: list[str]):
        self.f, self.sid, self.fixes = f, sid, list(fixes)
        st = S[sid]
        self.costs = costs_for(f, st, req)
        tgt = target_for(st, f, dict(st.params), False)
        for k in self.fixes:
            tgt, self.costs = REMEDIES[k]["fn"](f, tgt, self.costs)
        self.tgt = np.asarray(tgt, float)

    def sim(self, a: int, b: int) -> dict:
        return run(self.f, self.tgt, self.costs, a, b)


def _summary(f: Frame, cand: Candidate, a: int, k: int, b: int, bh: dict) -> dict:
    """Design-period metrics (never touches the holdout) plus stress windows measured inside the design period."""
    d = cand.sim(a, a + k)
    m = metrics(d["curve"], d["trades"], f.bpy, d["exposure"])
    return {"metrics": m, "stress": stress_windows(f, d["curve"], a, a, a + k), "run": d}


def _score_stress(s: list[dict]) -> float:
    vals = [w["rule_pct"] for w in s if w["rule_pct"] is not None]
    return min(vals) if vals else 0.0


def _verdict(base: dict, cand: dict, n_tries: int) -> tuple[bool, list[str]]:
    """Keep a fix only if every design-period test passes. Returns (keep, reasons in plain words)."""
    bm, cm = base["metrics"], cand["metrics"]
    need = BASE_MARGIN * n_tries
    why, ok = [], True
    bs, cs = bm["sharpe"] or -9, cm["sharpe"] or -9
    if cs - bs < need:
        ok = False
        why.append(f"Sharpe went from {bs:.2f} to {cs:.2f}; it had to rise by at least {need:.2f} (the bar goes up with every fix tried, because trying more makes a lucky result more likely).")
    else:
        why.append(f"Sharpe rose from {bs:.2f} to {cs:.2f} (needed +{need:.2f}).")
    bd, cd = bm["max_drawdown_pct"] or 0, cm["max_drawdown_pct"] or 0
    if cd < bd - DD_TOLERANCE:
        ok = False
        why.append(f"Worst drawdown got deeper ({bd:.0f}% to {cd:.0f}%).")
    bw, cw = _score_stress(base["stress"]), _score_stress(cand["stress"])
    if cw < bw - 1.0:
        ok = False
        why.append(f"It lost more in the worst BTC fall ({bw:.0f}% to {cw:.0f}%).")
    if cm["trades"] < MIN_TRADES:
        ok = False
        why.append(f"Only {cm['trades']} trades left (needs {MIN_TRADES}): too few to trust.")
    return ok, why


def _holdout_block(f: Frame, cand: Candidate, a: int, k: int, b: int, bh: dict) -> dict:
    full = cand.sim(a, b)
    n = b - a
    oc, ot = _slice(full, k, n, f, a)
    hc, _ = _slice(bh, k, n, f, a)
    m = metrics(oc, ot, f.bpy)
    return {"metrics": m, "buy_and_hold": metrics(hc, [], f.bpy), "stress": stress_windows(f, full["curve"], a, a + k, b), "full_period": metrics(full["curve"], full["trades"], f.bpy, full["exposure"]), "run": full}


def _public(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "run"}


def improve(rows: list[tuple], req: dict, sid: str, rounds: int = MAX_ROUNDS) -> dict:
    """Run the whole loop for one strategy on the last five years of daily bars."""
    if sid not in S or S[sid].requires_funding:
        raise LabError(f"'{sid}' cannot be used: it is unknown or needs perpetual funding, which does not cover five years.")
    rows = rows[-YEARS * 365 - 1:]
    if len(rows) < MIN_BARS:
        raise LabError(f"Only {len(rows)} daily bars are available; the loop needs at least {MIN_BARS} (two years) and is designed for five.")
    req = {**req, "leverage": 1.0, "long_short": False, "timeframe": "1d", "market": "spot"}
    f = Frame(rows, "1d", None, False)
    a, b = f.first, f.last
    k = int((b - a) * DESIGN_FRACTION)
    bh = buy_and_hold(f, req, a, b)
    rounds = max(1, min(rounds, MAX_ROUNDS))

    fixes: list[str] = []
    cur = Candidate(f, sid, req, fixes)
    start = _summary(f, cur, a, k, b, bh)
    log, tried, tries = [], set(), 0
    first_diag = None
    for r in range(1, rounds + 1):
        d = diagnose(f, start["run"], cur.costs, a, a + k)
        if first_diag is None:
            first_diag = d
        options = [c for c in d["causes"] if c["cause"] != "other" and c["share"] >= MIN_SHARE]
        pick = next(((c, kk) for c in options for kk, v in REMEDIES.items() if v["cause"] == c["cause"] and kk not in fixes and kk not in tried), None)
        if pick is None:
            log.append({"round": r, "stopped": True, "note": "No remaining cause explains enough of the losses with an untried fix. The loop stops here rather than invent a change.", "diagnosis": d})
            break
        cause, key = pick
        tried.add(key)
        tries += 1
        trial = Candidate(f, sid, req, fixes + [key])
        after = _summary(f, trial, a, k, b, bh)
        keep, why = _verdict(start, after, tries)
        log.append({"round": r, "diagnosis": d, "cause": cause["cause"], "cause_text": cause["text"], "cause_share": cause["share"], "fix": key, "fix_name": REMEDIES[key]["name"], "kept": keep, "why": why,
                    "before": _public(start), "after": _public(after)})
        if keep:
            fixes.append(key)
            cur, start = trial, after
    base_c = Candidate(f, sid, req, [])
    base_h, final_h = _holdout_block(f, base_c, a, k, b, bh), _holdout_block(f, cur, a, k, b, bh)
    bm, fm = base_h["metrics"], final_h["metrics"]
    holds = bool(fixes) and (fm["sharpe"] or -9) >= (bm["sharpe"] or -9) and (fm["max_drawdown_pct"] or 0) >= (bm["max_drawdown_pct"] or 0) - DD_TOLERANCE
    thin = fm["trades"] < HOLDOUT_MIN_TRADES
    if not fixes:
        verdict, plain = "no_change", "No fix passed the design-period tests, so the rule is unchanged. That is a result: nothing on the menu reliably helped."
    elif holds and thin:
        verdict, plain = "inconclusive", (f"The changed rule looked better on the sealed holdout, but it made only {fm['trades']} trade{'' if fm['trades'] == 1 else 's'} there (needs {HOLDOUT_MIN_TRADES}), "
                                          "so that could easily be luck. The starting rule stays the recommendation until there is more data.")
    elif holds:
        verdict, plain = "held_up", ("On the sealed holdout (data the loop never used) the changed rule was at least as good as the starting rule. That is encouraging but limited: one holdout, one asset, a few market cycles.")
    else:
        verdict, plain = "did_not_hold_up", "The changes looked good on the design period but not on the sealed holdout, so they are probably fitted to the past. The starting rule is the recommendation."
    full_start = start_date_test(f, base_c.tgt, base_c.costs, a, b)
    full_final = start_date_test(f, cur.tgt, cur.costs, a, b)
    shock = {}
    for mult in (1, 3):
        for name, c in (("start", base_c), ("final", cur)):
            cc = replace(c.costs, fee_bps=c.costs.fee_bps * mult, slippage_bps=c.costs.slippage_bps * mult)
            shock[f"{name}_x{mult}"] = (run(f, c.tgt, cc, a, b)["curve"][-1] - 1) * 100
    return {
        "strategy": {"id": sid, "name": S[sid].name, "family": S[sid].family}, "period": {"from": iso(int(f.t[a])), "to": iso(int(f.t[b - 1])), "bars": b - a,
                                                                                         "design_to": iso(int(f.t[a + k - 1])), "holdout_from": iso(int(f.t[a + k])), "holdout_bars": b - a - k},
        "first_diagnosis": first_diag, "rounds": log, "fixes_kept": [{"id": x, "name": REMEDIES[x]["name"]} for x in fixes], "fixes_tried": tries,
        "holdout": {"start": _public(base_h), "final": _public(final_h)}, "verdict": verdict, "plain": plain,
        "recommended": "final" if verdict == "held_up" else "start",
        "stress": {"costs_x1_start_pct": shock["start_x1"], "costs_x1_final_pct": shock["final_x1"], "costs_x3_start_pct": shock["start_x3"], "costs_x3_final_pct": shock["final_x3"], "start_date_start": full_start, "start_date_final": full_final,
                   "buy_and_hold_pct": (bh["curve"][-1] - 1) * 100},
        "caveats": ["Research only: this changes a backtest rule and never places a trade.", "Past results do not predict future results.", "Five years of BTC is a small sample of market cycles; a rule that 'held up' has passed one test, not been proven.",
                    f"The holdout is the same last {int((1 - DESIGN_FRACTION) * 100)}% of the five years every time, so repeated runs gradually learn from it. Treat a long streak of reruns as weaker evidence, not stronger."],
    }


def improve_many(rows, req: dict, ids: list[str], rounds: int = MAX_ROUNDS) -> dict:
    results, skipped = [], []
    for sid in ids:
        try:
            results.append(improve(rows, req, sid, rounds))
        except LabError as e:
            skipped.append({"id": sid, "reason": str(e)})
    return {"results": results, "skipped": skipped}
