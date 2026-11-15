"""btcquant calibration: how the whole research procedure behaves on SYNTHETIC candles where the truth is known.

Why it exists. A pass bar is only worth something if it can be passed when there is an edge and is hard to pass when there is none. The only way to know is to run the same procedure on data we made, with the same
calendar as the real candles: pure random walks (with and without the upward drift Bitcoin has had) where no rule can have skill, and series with a planted trend edge where a trend rule should win. Nothing here
reads the real data files, and no real result was used to choose anything in it.

Worlds (all 2,875 daily candles from 2019-01-01, as in the stored data):
  null_mild        independent daily returns, drift 0.04% a day, volatility 3.5% (no rule has skill; a buy-and-hold Sharpe of about 0.2)
  null_drift       the same with drift 0.15% a day (a buy-and-hold Sharpe of about 0.8: closer to Bitcoin in 2020 to 2024)
  planted_strong   a hidden two-state trend: the daily drift is +0.40% or -0.40% (volatility 2.5%), switching with probability 2% a day (regimes of about 50 days)
  planted_weak     the same with drift +-0.25%
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np

from . import backtest as B
from . import validation as V

DAY = 86400
T0 = int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp())
N_CANDLES = 2875                                           # 2019-01-01 to 2026-11-14, as stored
WORLDS = {"null_mild": {"kind": "null", "drift": 0.0004, "vol": 0.035},
          "null_drift": {"kind": "null", "drift": 0.0015, "vol": 0.035},
          "planted_strong": {"kind": "planted", "mu": 0.004, "vol": 0.025, "switch": 0.02},
          "planted_weak": {"kind": "planted", "mu": 0.0025, "vol": 0.025, "switch": 0.02}}


def daily_returns(world: str, seed: int, n: int = N_CANDLES) -> np.ndarray:
    w = WORLDS[world]
    rng = np.random.default_rng(seed)
    if w["kind"] == "null":
        return rng.normal(w["drift"], w["vol"], n)
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
    return [(T0 + i * DAY, float(o[i]), float(h[i]), float(l[i]), float(c[i]), 100.0) for i in range(n)]


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


def admission_summary(rows: list) -> dict:
    """How often the stored outcome 'admitted' happens: the share of datasets with at least one admitted family, and the average number admitted per dataset."""
    n = len(rows)
    counts = [sum(1 for f in r["families"].values() if f["outcome"] == "admitted") for r in rows]
    return {"datasets": n, "any_admitted": sum(1 for c in counts if c > 0), "share": (sum(1 for c in counts if c > 0) / n) if n else None, "mean_admitted": (sum(counts) / n) if n else None}


def main(argv: list) -> int:
    import json
    if len(argv) < 4 or argv[1] not in WORLDS:
        print("usage: python -m atlas_api.btcquant.calibration <" + "|".join(WORLDS) + "> <first seed> <end seed> [output.json]")
        return 2
    rows = run_world(argv[1], range(int(argv[2]), int(argv[3])))
    print(argv[1], admission_summary(rows))
    if len(argv) > 4:
        with open(argv[4], "w", encoding="utf-8") as fh:
            json.dump(rows, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
