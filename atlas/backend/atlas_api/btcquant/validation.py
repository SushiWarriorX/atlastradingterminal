"""btcquant validation (protocol section 7 and the gates of section 8): how a result is judged, so that a high return alone is never taken as an edge.

Pieces, in the order the protocol runs them:
  select           the configuration of a family that wins on TRAIN, by the mean of its own Sharpe and its grid neighbours' (a stable region beats an isolated peak); a tie goes to lower turnover
  stability        gate A4: how many neighbours keep at least 70% of the chosen configuration's Sharpe
  walk_forward     expanding fits from 2020-01-01 re-choosing the configuration every six months, scored on the next six months; the out-of-sample record is stitched and compared with holding
  deflated_sharpe  Bailey and Lopez de Prado (2014): the probability that the observed Sharpe ratio beats the best Sharpe ratio expected from N unrelated trials, allowing for skew and fat tails
  random_timing    shifts the strategy's own exposure schedule around a circle against the same prices and costs, to separate timing skill from simply being invested at some times; on VALIDATION alone it
                   is the out-of-sample significance test of admission (the configuration was chosen on TRAIN, so VALIDATION is untouched by the choice)
  admission        gates A1 to A5 and the three outcomes: admitted, rejected, too thin to judge. They measure skill against the exposure-matched passive hold, not raw returns, because raw
                   returns mostly measure the market's drift (v1.2: calibrated on synthetic data, see CALIBRATION.md)
Nothing here reads TEST-period results to choose or admit anything: selection and admission use TRAIN and VALIDATION only. The walk-forward windows after 2024-12-31 overlap TEST, as pre-registered, and are reported as such.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from statistics import NormalDist

import numpy as np

from . import backtest as B
from . import config as C
from . import metrics as M
from . import strategies as S

EULER = 0.5772156649015329
_NORMAL = NormalDist()

A1_MIN_TRADES = 10                     # admission floor: something to watch
A3_MAX_NULL_P = 0.05                   # VALIDATION random-timing p-value at most this (out-of-sample significance of timing skill); chosen from CALIBRATION.md: about 14% of no-skill datasets admit something, against 60% with a strong planted edge
A4_NEIGHBOUR_KEEP = 0.7                # a neighbour "keeps" the result if it reaches 70% of the chosen Sharpe ...
A4_NEIGHBOUR_SHARE = (6, 10)           # ... and at least 60% of the neighbours must do so
A5_COST_INDEX = 2                      # the doubled cost setting (0.20% fee, 0.10% slippage) in C.COST_SENSITIVITY
P_MIN_TRADES = 30
P_MIN_DSR = 0.95
P_MAX_NULL_P = 0.05
P_MAX_DRAWDOWN_RATIO = 0.75
P_TEST_SHARPE_MARGIN = 0.10
P_WF_POSITIVE_SHARE = (6, 10)
NULL_SHIFTS = 1000
NULL_MIN_SHIFT = 60
NULL_SEED = 20261115


def _z(x) -> float:
    """An undefined Sharpe ratio (never traded, or flat) counts as zero when ranking configurations."""
    return 0.0 if x is None else float(x)


# ---- selection and stability ----

def select(runs: dict, fam: S.Family) -> dict:
    """runs: {param_key: run with .metrics}. Score = mean of the configuration's own Sharpe and its neighbours' Sharpe; highest score wins; a tie goes to lower turnover, then to the first in grid order."""
    sharpe = {k: _z(r.metrics["sharpe"]) for k, r in runs.items()}
    scores = {}
    for p in S.configs(fam):
        k = B.param_key(p)
        scores[k] = float(np.mean([sharpe[k]] + [sharpe[B.param_key(q)] for q in S.neighbours(fam, p)]))
    best = max(scores, key=lambda k: (round(scores[k], 12), -float(runs[k].metrics["turnover"] or 0.0)))
    ranking = sorted(scores, key=lambda k: (-round(scores[k], 12), float(runs[k].metrics["turnover"] or 0.0)))
    return {"chosen": best, "params": dict(best), "scores": scores, "sharpe": sharpe, "ranking": ranking}


def stability(sharpe: dict, fam: S.Family, params: dict) -> dict:
    """Gate A4. Applies only when the chosen configuration's Sharpe is positive; otherwise gate A2 has already failed. A family with a single configuration has no neighbours (v1.3): see below."""
    own = sharpe[B.param_key(params)]
    nbs = [B.param_key(q) for q in S.neighbours(fam, params)]
    if not nbs:
        # v1.3: a family with a single configuration has no neighbourhood to be stable in and nothing was chosen on TRAIN, so there is no isolated peak to guard against. The gate keeps the part it can ask of
        # one number: the configuration's own TRAIN Sharpe must be above zero. (No family before 1.3 was in this position: every one has neighbours.)
        return {"applicable": False, "passes": bool(own > 0), "neighbours": 0, "reaching": 0, "share": None, "threshold": None, "single": True}
    if own <= 0:
        return {"applicable": False, "passes": False, "neighbours": len(nbs), "reaching": 0, "share": None, "threshold": None}
    thr = A4_NEIGHBOUR_KEEP * own
    reaching = sum(1 for k in nbs if sharpe[k] >= thr)
    need_num, need_den = A4_NEIGHBOUR_SHARE
    return {"applicable": True, "passes": reaching * need_den >= need_num * len(nbs), "neighbours": len(nbs), "reaching": reaching, "share": reaching / len(nbs), "threshold": thr}


# ---- return statistics, deflated Sharpe ----

def return_stats(r) -> dict:
    """Per-day Sharpe (not annualised), the number of days, skewness and kurtosis (not excess; a normal has 3) of a daily return series, population moments."""
    r = np.asarray(r, dtype=float)
    n = len(r)
    if n < 3:
        return {"T": n, "sr_daily": None, "skew": None, "kurt": None, "sharpe": None}
    sd = float(np.std(r, ddof=1))
    s0 = float(np.std(r, ddof=0))
    if sd < 1e-15 or s0 < 1e-15:
        return {"T": n, "sr_daily": None, "skew": None, "kurt": None, "sharpe": None}
    mean = float(np.mean(r))
    d = r - mean
    return {"T": n, "sr_daily": mean / sd, "skew": float(np.mean(d ** 3) / s0 ** 3), "kurt": float(np.mean(d ** 4) / s0 ** 4), "sharpe": mean / sd * math.sqrt(C.DAYS_PER_YEAR)}


def excess_returns(run) -> np.ndarray:
    """A run's daily returns less those of the exposure-matched hold over the same days: what the strategy earned by WHEN it was invested, with the drift of simply being invested taken out."""
    return np.asarray(run.returns) - np.asarray(run.matched_returns)


def expected_max_normal(n_trials: int) -> float:
    """Approximate expected maximum of n standard normal draws (Bailey and Lopez de Prado 2014)."""
    return (1.0 - EULER) * _NORMAL.inv_cdf(1.0 - 1.0 / n_trials) + EULER * _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))


def deflated_sharpe(sr: float | None, T: int, skew: float | None, kurt: float | None, n_trials: int, var_trials: float) -> dict:
    """Probability that the true Sharpe ratio is above what the best of `n_trials` unrelated trials would show by luck. All Sharpe ratios are per day. dsr is None when it cannot be computed."""
    if n_trials < 2:
        raise ValueError("the deflated Sharpe ratio needs at least two trials")
    sr0 = math.sqrt(max(var_trials, 0.0)) * expected_max_normal(n_trials)
    out = {"dsr": None, "sr0": sr0, "z": None, "n_trials": n_trials}
    if sr is None or T < 2 or skew is None or kurt is None:
        return out
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return out
    z = (sr - sr0) * math.sqrt(T - 1) / math.sqrt(denom)
    out.update(dsr=_NORMAL.cdf(z), z=z)
    return out


# ---- random-timing null ----

def timing_sharpe(exposure, btc_returns, cost: float, shift: int) -> float | None:
    """Annualised Sharpe of an exposure schedule shifted `shift` days around a circle against the price path: return = exposure x Bitcoin's day return, less cost x the change in exposure.
    A shift of zero is the real schedule and starts flat; a shifted schedule is treated as circular."""
    e = np.asarray(exposure, dtype=float)
    r = np.asarray(btc_returns, dtype=float)
    held = np.roll(e, shift)
    prev = np.concatenate([[0.0], held[:-1]]) if shift == 0 else np.roll(held, 1)
    return M.sharpe(held * r - np.abs(held - prev) * cost)


def random_timing(exposure, btc_returns, *, fee: float = C.FEE, slip: float = C.SLIPPAGE, n_shifts: int = NULL_SHIFTS, min_shift: int = NULL_MIN_SHIFT, seed: int = NULL_SEED) -> dict:
    """p = the share of shifted copies (whole days, at least `min_shift` from the real alignment either way) with a Sharpe at least as high as the real schedule's. Small p means the timing matters."""
    e = np.asarray(exposure, dtype=float)
    n = len(e)
    cost = fee + slip
    real = timing_sharpe(e, btc_returns, cost, 0)
    allowed = np.arange(min_shift, n - min_shift + 1)
    if real is None or len(allowed) == 0:
        return {"p": None, "real": real, "shifts": 0, "at_least_as_good": None, "median_shifted": None}
    rng = np.random.default_rng(seed)
    shifts = allowed if len(allowed) <= n_shifts else rng.choice(allowed, size=n_shifts, replace=False)
    vals = np.array([_z(timing_sharpe(e, btc_returns, cost, int(k))) for k in shifts])
    atleast = int(np.sum(vals >= real))
    return {"p": atleast / len(shifts), "real": real, "shifts": int(len(shifts)), "at_least_as_good": atleast, "median_shifted": float(np.median(vals))}


# ---- walk-forward ----

def add_months(d: date, k: int) -> date:
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def month_end(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)


def wf_segments(first_fit_end: date, step_months: int, last_date: date) -> list:
    """[(fit_end, oos_start, oos_end)]: each fit ends where the previous out-of-sample window ended; the last window is whatever remains up to the latest candle."""
    out, fit_end = [], first_fit_end
    while True:
        start = fit_end + timedelta(days=1)
        if start > last_date:
            return out
        end = min(month_end(add_months(fit_end, step_months)), last_date)
        out.append((fit_end, start, end))
        fit_end = end


def wf_passes(stitched_sharpe, hold_sharpe, positive: int, windows: int) -> bool:
    """Gate P4: the stitched out-of-sample Sharpe at least the hold's over the same days, and a positive return in at least 60% of the windows."""
    need_num, need_den = P_WF_POSITIVE_SHARE
    return stitched_sharpe is not None and hold_sharpe is not None and stitched_sharpe >= hold_sharpe and windows > 0 and positive * need_den >= need_num * windows


def walk_forward(prep: B.Prepared, fam_id: str, *, fit_start: date = C.EVAL_START, first_fit_end: date = date(2021, 12, 31), step_months: int = 6,
                 fee: float = C.FEE, slip: float = C.SLIPPAGE) -> dict:
    fam = S.FAMILIES[fam_id]
    last_date = datetime.fromtimestamp(prep.times[-1], timezone.utc).date()
    segs, rows, parts = wf_segments(first_fit_end, step_months, last_date), [], []
    for fit_end, start, end in segs:
        f0, f1 = prep.span(fit_start, fit_end)
        sel = select(B.run_all(prep, fam_id, f0, f1, fee=fee, slip=slip), fam)
        o0, o1 = prep.span(start, end)
        oos = B.run(prep, fam_id, sel["params"], o0, o1, fee=fee, slip=slip)
        rows.append({"fit_end": fit_end.isoformat(), "oos_start": start.isoformat(), "oos_end": end.isoformat(), "days": o1 - o0 + 1, "chosen": sel["params"],
                     "return": oos.metrics["total_return"], "sharpe": oos.metrics["sharpe"], "trades": oos.metrics["trades"], "exposure": oos.metrics["exposure"]})
        parts.append(oos.returns)
    if not rows:
        return {"segments": [], "windows": 0, "stitched_sharpe": None, "stitched_return": None, "hold_sharpe": None, "hold_return": None, "positive_windows": 0, "positive_share": None, "passes": False}
    first0, _ = prep.span(date.fromisoformat(rows[0]["oos_start"]), date.fromisoformat(rows[0]["oos_end"]))
    _, last1 = prep.span(date.fromisoformat(rows[-1]["oos_start"]), date.fromisoformat(rows[-1]["oos_end"]))
    hold = B.run(prep, "buy_hold", {}, first0, last1, fee=fee, slip=slip)
    stitched = np.concatenate(parts)
    s_sharpe, h_sharpe = M.sharpe(stitched), hold.metrics["sharpe"]
    positive = sum(1 for r in rows if r["return"] > 0)
    return {"segments": rows, "windows": len(rows), "stitched_sharpe": s_sharpe, "stitched_return": float(np.prod([1.0 + r["return"] for r in rows]) - 1.0),
            "hold_sharpe": h_sharpe, "hold_return": hold.metrics["total_return"], "positive_windows": positive, "positive_share": positive / len(rows),
            "passes": wf_passes(s_sharpe, h_sharpe, positive, len(rows))}


# ---- sensitivity ----

def cost_table(prep: B.Prepared, fam_id: str, params: dict, ranges: list) -> list:
    """The chosen configuration over the given (i0, i1) ranges at each of the four cost settings: pooled Sharpe and the total return in each range."""
    out = []
    for fee, slip in C.COST_SENSITIVITY:
        runs = [B.run(prep, fam_id, params, a, b, fee=fee, slip=slip) for a, b in ranges]
        pooled = np.concatenate([r.returns for r in runs])
        out.append({"fee": fee, "slippage": slip, "sharpe": M.sharpe(pooled), "returns": [r.metrics["total_return"] for r in runs], "fees_paid": sum(r.metrics["fees_paid"] for r in runs)})
    return out


# ---- the gates ----

def admission(n: dict) -> dict:
    """Gates A1 to A5 from plain numbers; returns each gate with its value, the requirement and whether it passed, and the outcome.
    Outcomes: 'too_thin' (A1 failed: not enough trades to say anything), 'rejected' (A1 passed and another gate failed: the evidence says no), 'admitted'.
    The deflated Sharpe ratio is reported beside the gates but is not one: on raw returns it rewards the market's drift, and on excess returns it cannot be passed with the history we have (CALIBRATION.md)."""
    def ok(x):
        return x is not None
    g = {}
    g["A1"] = {"value": n["activity"], "need": f">= {A1_MIN_TRADES} {'position changes' if n['weight_mode'] else 'trades'} on TRAIN + VALIDATION", "passed": n["activity"] >= A1_MIN_TRADES}
    g["A2"] = {"value": {"train_ir": n["train_ir"], "validation_ir": n["validation_ir"]}, "need": "information ratio against the exposure-matched hold > 0 on TRAIN and on VALIDATION",
               "passed": ok(n["train_ir"]) and ok(n["validation_ir"]) and n["train_ir"] > 0 and n["validation_ir"] > 0}
    g["A3"] = {"value": n["validation_null_p"], "need": f"random-timing p-value on VALIDATION <= {A3_MAX_NULL_P}", "passed": ok(n["validation_null_p"]) and n["validation_null_p"] <= A3_MAX_NULL_P}
    g["A4"] = {"value": n["stability"], "need": "at least 60% of the neighbours reach 70% of the chosen Sharpe", "passed": bool(n["stability"]["passes"])}
    g["A5"] = {"value": n["doubled_cost_sharpe"], "need": "Sharpe > 0 on TRAIN + VALIDATION at doubled costs", "passed": ok(n["doubled_cost_sharpe"]) and n["doubled_cost_sharpe"] > 0}
    if not g["A1"]["passed"]:
        outcome = "too_thin"
    elif all(v["passed"] for v in g.values()):
        outcome = "admitted"
    else:
        outcome = "rejected"
    return {"gates": g, "outcome": outcome, "failed": [k for k, v in g.items() if not v["passed"]]}


def promotion_gates(n: dict) -> dict:
    """Gates P1 to P5 from plain numbers (P6, the written record, is made by the registry). Only a challenger that already passed A1 to A6 reaches this, and only when its forward record is long enough.
    n: trades (all periods + forward), profit_without_best, test_sharpe, hold_test_sharpe, test_drawdown, matched_test_drawdown, dsr_excess_all (deflated Sharpe of the returns in excess of the
    exposure-matched hold, TRAIN + VALIDATION + TEST), null_p (random-timing p over the same days), wf_passes, forward {days, trades, trips, return, matched_return}."""
    def ok(x):
        return x is not None
    f = n["forward"]
    g = {}
    g["P1"] = {"value": {"trades": n["trades"], "profit_without_best": n["profit_without_best"]}, "need": f">= {P_MIN_TRADES} trades and positive profit without the best trade",
               "passed": n["trades"] >= P_MIN_TRADES and ok(n["profit_without_best"]) and n["profit_without_best"] > 0}
    g["P2"] = {"value": {"test_sharpe": n["test_sharpe"], "hold_sharpe": n["hold_test_sharpe"], "drawdown": n["test_drawdown"], "matched_drawdown": n["matched_test_drawdown"]},
               "need": f"TEST Sharpe >= hold Sharpe + {P_TEST_SHARPE_MARGIN} and drawdown <= {P_MAX_DRAWDOWN_RATIO:.0%} of the exposure-matched hold's",
               "passed": ok(n["test_sharpe"]) and ok(n["hold_test_sharpe"]) and n["test_sharpe"] >= n["hold_test_sharpe"] + P_TEST_SHARPE_MARGIN
               and n["test_drawdown"] <= P_MAX_DRAWDOWN_RATIO * n["matched_test_drawdown"]}
    g["P3"] = {"value": {"dsr_excess": n["dsr_excess_all"], "null_p": n["null_p"]}, "need": f"deflated Sharpe of the excess returns >= {P_MIN_DSR} and random-timing p <= {P_MAX_NULL_P}",
               "passed": ok(n["dsr_excess_all"]) and ok(n["null_p"]) and n["dsr_excess_all"] >= P_MIN_DSR and n["null_p"] <= P_MAX_NULL_P}
    g["P4"] = {"value": n["wf_passes"], "need": "walk-forward Sharpe >= hold's and positive in >= 60% of windows", "passed": bool(n["wf_passes"])}
    g["P5"] = {"value": f, "need": "forward record >= 90 days and >= 5 closed trades, no breaker trip, return not worse than the exposure-matched hold by more than 5 points",
               "passed": f["days"] >= 90 and f["trades"] >= 5 and f["trips"] == 0 and f["return"] >= f["matched_return"] - 0.05}
    failed = [k for k, v in g.items() if not v["passed"]]
    if f["days"] < 60:
        outcome = "too_early"                                                    # under 60 days of forward record nothing is said beyond this
    elif not failed:
        outcome = "promoted"
    elif f["days"] < 90 and failed == ["P5"] and f["trips"] == 0:
        outcome = "waiting"                                                      # everything else holds; only the 90 days or the 5 trades are missing
    else:
        outcome = "not_promoted"
    return {"gates": g, "outcome": outcome, "failed": failed}


# ---- one family, and all of them ----

def _round(x, k=6):
    return None if x is None else round(float(x), k)


def evaluate_family(prep: B.Prepared, fam_id: str, runs: dict, trial_var: float, n_trials: int, *, trial_var_excess: float | None = None, walk: bool = True, n_shifts: int = NULL_SHIFTS,
                    wf_kwargs: dict | None = None) -> dict:
    """The protocol's procedure for one family (section 7), on TRAIN and VALIDATION only for selection and admission. `runs` = {"TRAIN": run_all(...), "VALIDATION": run_all(...)} for all its configurations."""
    fam = S.FAMILIES[fam_id]
    train, val = runs["TRAIN"], runs["VALIDATION"]
    sel = select(train, fam)
    ck, params = sel["chosen"], sel["params"]
    ct, cv = train[ck], val[ck]
    ranges = [(ct.i0, ct.i1), (cv.i0, cv.i1)]
    stats = return_stats(np.concatenate([ct.returns, cv.returns]))
    dsr = deflated_sharpe(stats["sr_daily"], stats["T"], stats["skew"], stats["kurt"], n_trials, trial_var)
    stab = stability(sel["sharpe"], fam, params)
    costs = cost_table(prep, fam_id, params, ranges)
    full = {"TRAIN": B.run(prep, fam_id, params, *ranges[0], sizing="full").metrics, "VALIDATION": B.run(prep, fam_id, params, *ranges[1], sizing="full").metrics} if fam.kind == "stop" else None
    null = random_timing(np.concatenate([ct.exposure, cv.exposure]), np.concatenate([prep.btc_returns[ct.i0:ct.i1 + 1], prep.btc_returns[cv.i0:cv.i1 + 1]]), n_shifts=n_shifts)
    weight_mode = fam.kind == "weight"
    activity = (ct.metrics["fills"] + cv.metrics["fills"]) if weight_mode else (ct.metrics["trades"] + cv.metrics["trades"])
    ex_t, ex_v = excess_returns(ct), excess_returns(cv)
    ex_stats = return_stats(np.concatenate([ex_t, ex_v]))
    excess = {"train": M.sharpe(ex_t), "validation": M.sharpe(ex_v), "pooled": {k: _round(v) if isinstance(v, float) else v for k, v in ex_stats.items()},
              "deflated": deflated_sharpe(ex_stats["sr_daily"], ex_stats["T"], ex_stats["skew"], ex_stats["kurt"], n_trials, trial_var_excess) if trial_var_excess is not None else None}
    val_null = random_timing(cv.exposure, prep.btc_returns[cv.i0:cv.i1 + 1], n_shifts=n_shifts)
    numbers = {"activity": activity, "weight_mode": weight_mode, "train_ir": excess["train"], "validation_ir": excess["validation"], "validation_null_p": val_null["p"],
               "stability": stab, "doubled_cost_sharpe": costs[A5_COST_INDEX]["sharpe"]}
    adm = admission(numbers)
    neighbours = []
    for q in S.neighbours(fam, params):
        k = B.param_key(q)
        neighbours.append({"params": q, "train_sharpe": train[k].metrics["sharpe"], "validation_sharpe": val[k].metrics["sharpe"], "validation_return": val[k].metrics["total_return"]})
    table = [{"params": dict(k), "train_sharpe": train[k].metrics["sharpe"], "score": _round(sel["scores"][k]), "trades": train[k].metrics["trades"], "turnover": _round(train[k].metrics["turnover"]),
              "train_return": _round(train[k].metrics["total_return"]), "validation_sharpe": val[k].metrics["sharpe"], "validation_return": _round(val[k].metrics["total_return"])} for k in train]
    return {"family": fam_id, "protocol": C.PROTOCOL_VERSION, "chosen": params, "spec_hash": S.spec_hash(fam_id, params), "configurations": len(train), "table": table,
            "train": ct.metrics, "validation": cv.metrics, "neighbours": neighbours, "stability": stab, "costs": costs, "full_exposure": full,
            "pooled": {**{k: _round(v) if isinstance(v, float) else v for k, v in stats.items()}}, "deflated_sharpe": dsr, "random_timing": null,
            "walk_forward": walk_forward(prep, fam_id, **(wf_kwargs or {})) if walk else None, "trips": {"TRAIN": ct.trips, "VALIDATION": cv.trips},
            "excess": excess, "validation_timing": val_null, "admission": adm, "outcome": adm["outcome"]}


def evaluate_all(prep: B.Prepared, families: list | None = None, *, walk: bool = True, n_shifts: int = NULL_SHIFTS, wf_kwargs: dict | None = None) -> dict:
    """The whole research procedure. All 100 configurations always run on TRAIN and VALIDATION, because the number of trials (N = 100) and the spread of their Sharpe ratios feed the deflated Sharpe ratio of every family."""
    tr, va = prep.period("TRAIN"), prep.period("VALIDATION")
    runs = {f.id: {"TRAIN": B.run_all(prep, f.id, *tr), "VALIDATION": B.run_all(prep, f.id, *va)} for f in S.RESEARCH}
    trial_sr = []
    for f in S.RESEARCH:
        for k in runs[f.id]["TRAIN"]:
            trial_sr.append(_z(return_stats(np.concatenate([runs[f.id]["TRAIN"][k].returns, runs[f.id]["VALIDATION"][k].returns]))["sr_daily"]))
    var = float(np.var(trial_sr, ddof=1))
    trial_ex = []
    for f in S.RESEARCH:
        for k in runs[f.id]["TRAIN"]:
            trial_ex.append(_z(return_stats(np.concatenate([excess_returns(runs[f.id]["TRAIN"][k]), excess_returns(runs[f.id]["VALIDATION"][k])]))["sr_daily"]))
    var_ex = float(np.var(trial_ex, ddof=1))
    out = {}
    for f in S.RESEARCH:
        if families is None or f.id in families:
            out[f.id] = evaluate_family(prep, f.id, runs[f.id], var, len(trial_sr), trial_var_excess=var_ex, walk=walk, n_shifts=n_shifts, wf_kwargs=wf_kwargs)
    return {"protocol": C.PROTOCOL_VERSION, "n_trials": len(trial_sr), "trial_variance": var, "trial_variance_excess": var_ex, "families": out}
