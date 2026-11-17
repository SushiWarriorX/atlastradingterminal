"""btcquant calibration: how the whole research procedure behaves on SYNTHETIC candles where the truth is known.

Why it exists. A pass bar is only worth something if it can be passed when there is an edge and is hard to pass when there is none. The only way to know is to run the same procedure on data we made, with the same
calendar as the real candles: pure random walks (with and without the upward drift Bitcoin has had) where no rule can have skill, and series with a planted trend edge where a trend rule should win. Nothing here
reads the real data files, and no real result was used to choose anything in it.

Worlds (all 2,875 daily candles from 2019-01-01, as in the stored data):
  null_mild        independent daily returns, drift 0.04% a day, volatility 3.5% (no rule has skill; a buy-and-hold Sharpe of about 0.2)
  null_drift       the same with drift 0.15% a day (a buy-and-hold Sharpe of about 0.8: closer to Bitcoin in 2020 to 2024)
  planted_strong   a hidden two-state trend: the daily drift is +0.40% or -0.40% (volatility 2.5%), switching with probability 2% a day (regimes of about 50 days)
  planted_weak     the same with drift +-0.25%
  planted_monday_small (protocol 1.3) no trend and no other skill, but the candle of one weekday (Monday) pays a premium of 0.3% on top of the 0.04% drift: exactly what a weekly round trip costs
  planted_monday_mid   the same with a premium of 0.6% (the cost of a round trip at doubled costs, the level of gate A5)
  planted_monday_big   the same with a premium of 1.0%
  planted_reversal_small (protocol 1.4) no trend and no other skill, but the candle that follows three or more lower closes in a row pays a premium of 0.3% on top of the 0.04% drift
  planted_reversal_mid   the same with a premium of 0.6%
  planted_reversal_big   the same with a premium of 1.0%
  planted_surge_small  (protocol 1.5) no trend and no other skill, but each of the five candles that follow a SURGE DAY (volume at least twice the mean of the 20 days before it, close above the close before) pays a premium of 0.10% on top of the 0.04% drift: 0.5% in all, 1.7 times what a round trip costs
  planted_surge_mid    the same with a premium of 0.20% a candle (1.0% in all)
  planted_surge_big    the same with a premium of 0.40% a candle (2.0% in all)
The weekday, reversal and surge worlds exist only to see whether the machinery can find a calendar, a reversal or a volume effect and how large it must be: a Monday-only holder pays about 0.30% in fees and slippage every week, so a
premium under that cannot pay for itself whatever the data say, and a reversal or surge trade pays the same 0.30% for every trade. They are used with `run_family_world` (one family at a time); the first calibration
of the other worlds is not repeated.

Volume (protocol 1.5). Every world carries a synthetic daily volume series, drawn from a random stream of its own (seed + 2000) so that no price, wick or return of any world changed when it was added; it used to be a constant 100,
which no family read. Log volume is a first-order autoregression (persistence 0.7, innovation 0.4) around 10,000: it surges (volume at least 1.5, 2 and 3 times the mean of the 20 days before) on 17.7%, 7.4% and 1.4% of days against
15.9%, 6.3% and 1.5% in the stored Coinbase series, and its first-order autocorrelation is about 0.7 against 0.65. Those three shares and the autocorrelation were measured once from the stored volumes (no price and no return was
used) to set the two numbers; this module never reads the data files. Volume is unrelated to the returns in every world: the returns are independent, so no rule that reads volume can have skill, except where a premium is planted.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np

from . import backtest as B
from . import strategies as S
from . import validation as V

DAY = 86400
T0 = int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp())
N_CANDLES = 2875                                           # 2019-01-01 to 2026-11-14, as stored
WORLDS = {"null_mild": {"kind": "null", "drift": 0.0004, "vol": 0.035},
          "null_drift": {"kind": "null", "drift": 0.0015, "vol": 0.035},
          "planted_strong": {"kind": "planted", "mu": 0.004, "vol": 0.025, "switch": 0.02},
          "planted_weak": {"kind": "planted", "mu": 0.0025, "vol": 0.025, "switch": 0.02},
          "planted_monday_small": {"kind": "calendar", "drift": 0.0004, "vol": 0.035, "day": 0, "premium": 0.003},
          "planted_monday_mid": {"kind": "calendar", "drift": 0.0004, "vol": 0.035, "day": 0, "premium": 0.006},
          "planted_monday_big": {"kind": "calendar", "drift": 0.0004, "vol": 0.035, "day": 0, "premium": 0.010},
          "planted_reversal_small": {"kind": "reversal", "drift": 0.0004, "vol": 0.035, "streak": 3, "premium": 0.003},
          "planted_reversal_mid": {"kind": "reversal", "drift": 0.0004, "vol": 0.035, "streak": 3, "premium": 0.006},
          "planted_reversal_big": {"kind": "reversal", "drift": 0.0004, "vol": 0.035, "streak": 3, "premium": 0.010},
          "planted_surge_small": {"kind": "surge", "drift": 0.0004, "vol": 0.035, "ratio": 2.0, "hold": 5, "premium": 0.001},
          "planted_surge_mid": {"kind": "surge", "drift": 0.0004, "vol": 0.035, "ratio": 2.0, "hold": 5, "premium": 0.002},
          "planted_surge_big": {"kind": "surge", "drift": 0.0004, "vol": 0.035, "ratio": 2.0, "hold": 5, "premium": 0.004}}
VOLUME_PERSISTENCE, VOLUME_INNOVATION, VOLUME_LEVEL = 0.7, 0.4, 10_000.0                  # log volume: first-order autoregression, innovation standard deviation, and the level it varies around


def volume_series(seed: int, n: int = N_CANDLES) -> np.ndarray:
    """The synthetic daily volume of a seed (protocol 1.5), the same in every world: log volume is an AR(1) with persistence 0.7 and innovation 0.4 around 10,000, started in its stationary distribution. It has a random stream of its own, so adding it moved nothing else."""
    e = np.random.default_rng(seed + 2000).normal(0.0, VOLUME_INNOVATION, n)
    a = np.empty(n)
    a[0] = e[0] / np.sqrt(1.0 - VOLUME_PERSISTENCE ** 2)
    for i in range(1, n):
        a[i] = VOLUME_PERSISTENCE * a[i - 1] + e[i]
    return VOLUME_LEVEL * np.exp(a)


def daily_returns(world: str, seed: int, n: int = N_CANDLES) -> np.ndarray:
    w = WORLDS[world]
    rng = np.random.default_rng(seed)
    if w["kind"] == "null":
        return rng.normal(w["drift"], w["vol"], n)
    if w["kind"] == "calendar":                                                                   # independent returns, plus a premium on every candle of one weekday (0 = Monday, from the candle's UTC open time)
        return rng.normal(w["drift"], w["vol"], n) + w["premium"] * (S.weekday(T0 + np.arange(n) * DAY) == w["day"])
    if w["kind"] == "reversal":                                                                   # independent returns, plus a premium on every candle that follows `streak` or more lower closes in a row
        noise = rng.normal(w["drift"], w["vol"], n)
        out, run = np.empty(n), 0
        for i in range(n):
            out[i] = noise[i] + (w["premium"] if run >= w["streak"] else 0.0)
            run = run + 1 if i > 0 and out[i] < 0 else 0                                          # a lower close is a negative return; the first candle has no close before it
        return out
    if w["kind"] == "surge":                                                                      # independent returns, plus a premium on each of the `hold` candles after a surge day; the volume is the seed's own series
        noise, v = rng.normal(w["drift"], w["vol"], n), volume_series(seed, n)
        base = S.volume_baseline(v)
        with np.errstate(invalid="ignore"):
            heavy = (base > 0) & (v >= w["ratio"] * base)
        out, left = np.empty(n), 0
        for i in range(n):
            out[i] = noise[i] + (w["premium"] if left > 0 else 0.0)
            left = max(left - 1, 0)
            if i > 0 and heavy[i] and out[i] > 0:                                                  # a surge day: a rise on a heavy volume; the next `hold` candles are paid (a new surge day inside the window starts the count again)
                left = w["hold"]
        return out
    state, out = 1, np.empty(n)
    for i in range(n):
        if rng.random() < w["switch"]:
            state = -state
        out[i] = state * w["mu"] + rng.normal(0.0, w["vol"])
    return out


def synthetic_candles(world: str, seed: int, n: int = N_CANDLES, start: float = 20_000.0) -> list:
    """Daily candles built from the world's returns: each opens at the previous close, with wicks beyond the open and close."""
    r = daily_returns(world, seed, n)
    rng = np.random.default_rng(seed + 1000)
    c = start * np.exp(np.cumsum(r))
    o = np.concatenate([[start], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    v = volume_series(seed, n)
    return [(T0 + i * DAY, float(o[i]), float(h[i]), float(l[i]), float(c[i]), float(v[i])) for i in range(n)]


def compact(ev: dict) -> dict:
    """The numbers of one full procedure run that an admission rule can use, per family (small enough to keep for hundreds of datasets)."""
    fams = {}
    for fid, e in ev["families"].items():
        ex = e["excess"]
        fams[fid] = {"outcome": e["outcome"], "failed": e["admission"]["failed"], "activity": e["admission"]["gates"]["A1"]["value"], "train": e["train"]["sharpe"], "val": e["validation"]["sharpe"],
                     "val_return": e["validation"]["total_return"], "stable": bool(e["stability"]["passes"]), "cost2": e["costs"][V.A5_COST_INDEX]["sharpe"], "dsr": e["deflated_sharpe"]["dsr"],
                     "ir_train": ex["train"], "ir_val": ex["validation"], "ir_pooled_daily": ex["pooled"]["sr_daily"], "dsr_excess": None if ex["deflated"] is None else ex["deflated"]["dsr"],
                     "null_p": e["random_timing"]["p"], "val_null_p": e["validation_timing"]["p"], "wf_passes": e["walk_forward"]["passes"] if e["walk_forward"] else None,
                     "exposure": e["train"]["exposure"]}
    return {"trial_variance": ev["trial_variance"], "trial_variance_excess": ev["trial_variance_excess"], "families": fams}


def run_world(world: str, seeds, *, n_shifts: int = V.NULL_SHIFTS) -> list:
    out = []
    for s in seeds:
        ev = V.evaluate_all(B.Prepared(synthetic_candles(world, s)), n_shifts=n_shifts)
        out.append({"world": world, "seed": s, **compact(ev)})
    return out


def compact_family(e: dict) -> dict:
    """The numbers of one family's evaluation that the admission gates use (small enough to keep for hundreds of datasets)."""
    ex = e["excess"]
    return {"outcome": e["outcome"], "failed": e["admission"]["failed"], "activity": e["admission"]["gates"]["A1"]["value"], "train": e["train"]["sharpe"], "val": e["validation"]["sharpe"],
            "stable": bool(e["stability"]["passes"]), "cost2": e["costs"][V.A5_COST_INDEX]["sharpe"], "ir_train": ex["train"], "ir_val": ex["validation"], "val_null_p": e["validation_timing"]["p"],
            "exposure": e["train"]["exposure"], "chosen": e["chosen"]}


def run_family_world(world: str, seeds, family: str, *, n_shifts: int = V.NULL_SHIFTS) -> list:
    """One family alone through selection on TRAIN and the five admission gates, on synthetic datasets: for a family pre-registered after the first calibration (protocol 1.3), whose admission share can be measured
    without repeating the twelve others (about a second a dataset instead of ten). No walk-forward and no deflated Sharpe ratio, which are not admission gates; the trial count passed to the deflated Sharpe is the full 101."""
    out = []
    for s in seeds:
        prep = B.Prepared(synthetic_candles(world, s))
        tr, va = prep.period("TRAIN"), prep.period("VALIDATION")
        runs = {"TRAIN": B.run_all(prep, family, *tr), "VALIDATION": B.run_all(prep, family, *va)}
        ev = V.evaluate_family(prep, family, runs, 1e-4, S.n_configurations(), walk=False, n_shifts=n_shifts)
        out.append({"world": world, "seed": s, "family": family, **compact_family(ev)})
    return out


def admission_summary(rows: list) -> dict:
    """How often the stored outcome 'admitted' happens: the share of datasets with at least one admitted family, and the average number admitted per dataset."""
    n = len(rows)
    counts = [sum(1 for f in r["families"].values() if f["outcome"] == "admitted") for r in rows]
    return {"datasets": n, "any_admitted": sum(1 for c in counts if c > 0), "share": (sum(1 for c in counts if c > 0) / n) if n else None, "mean_admitted": (sum(counts) / n) if n else None}


def main(argv: list) -> int:
    import json
    if len(argv) < 4 or argv[1] not in WORLDS or (len(argv) > 5 and argv[5] not in [f.id for f in S.RESEARCH]):
        print("usage: python -m atlas_api.btcquant.calibration <" + "|".join(WORLDS) + "> <first seed> <end seed> [output.json [family]]")
        return 2
    if len(argv) > 5:
        rows = run_family_world(argv[1], range(int(argv[2]), int(argv[3])), argv[5])
        print(argv[1], argv[5], "admitted", sum(1 for r in rows if r["outcome"] == "admitted"), "of", len(rows))
    else:
        rows = run_world(argv[1], range(int(argv[2]), int(argv[3])))
        print(argv[1], admission_summary(rows))
    if len(argv) > 4:
        with open(argv[4], "w", encoding="utf-8") as fh:
            json.dump(rows, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
