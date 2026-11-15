"""btcquant research queue (BUILD_PLAN step 13): the novelty pre-screen.

Protocol section 10 counts a candidate whose position series correlates 0.90 or more with an existing one as a renamed copy of it. The research queue (`btcquant/RESEARCH_QUEUE.md`) applies the same test BEFORE an idea
is written up and pre-registered, so that no hour is spent on a look-alike of something already tested, and so that the multiple-testing count N (every pre-registered configuration adds to it) is not spent on copies.

What is compared: the ON/OFF state of the candidate's default configuration (does the rule want to be long from the next open) against the same series of ALL 100 configurations of the twelve families (stop families:
the state; weight families: the target weight), on the TRAIN and VALIDATION days, the days the registry compares. Pearson correlation; a series that never changes over those days has no correlation and is skipped.
This is a screen on timing only. No return, profit or Sharpe ratio is computed here, nothing is optimised, and every rule below uses only candles up to the close of day i (a test moves the later candles and
checks that nothing at or before i changes). A candidate that passes the screen has still proved nothing: it only has the right to be written up and pre-registered under the protocol.

Run `python -m atlas_api.btcquant.novelty` to screen every queued candidate on the stored candles; the result is written to `btcquant/reports/novelty.json` with the data version it was computed from.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import backtest as B
from . import config as C
from . import data as D
from . import indicators as I
from . import registry as R
from . import strategies as S

DUP_CORRELATION = R.DUP_CORRELATION


weekday = S.weekday                                     # 0 = Monday ... 6 = Sunday from the candle's UTC open time (the one definition lives with the family that uses it)


def _last_any(x: np.ndarray, k: int) -> np.ndarray:
    """True at i when x was True at any of the last k candles, i included."""
    cs = np.cumsum(x.astype(int))
    return (cs - np.concatenate([np.zeros(k, dtype=int), cs])[:len(cs)]) > 0


# ---- the queued candidates: each a pure function of completed candles, with its default configuration ----
def monday(b: S.Bars, day: int = 0) -> np.ndarray:
    """Long during one weekday only (default Monday). The state is ON at the close of the candle BEFORE that day, so the position is held through the day's candle and sold at the next open."""
    return weekday(b.t) == (day - 1) % 7


def volume_surge(b: S.Bars, ratio: float = 2.0, window: int = 20, hold: int = 5) -> np.ndarray:
    """Long for `hold` candles after a day whose volume is at least `ratio` times the mean of the previous `window` days AND whose close is above the previous close."""
    mean_prev = I.prior(I.sma(b.v, window), 1)
    prev_close = I.prior(b.c, 1)
    with np.errstate(invalid="ignore"):                 # a comparison with a warm-up NaN is False: no surge before there is history
        spike = (b.v >= ratio * mean_prev) & (b.c > prev_close)
    return _last_any(spike, hold)


def near_high(b: S.Bars, window: int = 91, frac: float = 0.95) -> np.ndarray:
    """Long while the close is within (1 - frac) of the highest close of the last `window` candles (13 weeks), the current close included."""
    hh = I.rolling_max(b.c, window)
    with np.errstate(invalid="ignore"):
        return b.c >= frac * hh


def _squeezed(width: np.ndarray, lookback: int, pct: float) -> np.ndarray:
    """True at i when the band width at i is at or below the `pct` percentile of the widths of the `lookback` days before i. A missing width, or a window with one, gives NaN and so never a squeeze."""
    out = np.zeros(len(width), dtype=bool)
    for i in range(lookback, len(width)):
        out[i] = bool(width[i] <= np.percentile(width[i - lookback:i], pct))
    return out


def squeeze_break(b: S.Bars, n: int = 20, k: float = 2.0, lookback: int = 180, pct: float = 20.0) -> np.ndarray:
    """Volatility compression, then a break up: enter when the close is above the upper Bollinger band and the band width of the PREVIOUS day was at or below the `pct` percentile of the widths of the `lookback` days before it;
    stay long until the close is below the middle band."""
    lo, mid, up = I.bollinger(b.c, n, k)
    with np.errstate(invalid="ignore", divide="ignore"):
        width = (up - lo) / mid
    squeeze = _squeezed(width, lookback, pct)
    entry = np.zeros(b.n, dtype=bool)
    with np.errstate(invalid="ignore"):
        entry[1:] = (b.c[1:] > up[1:]) & squeeze[:-1]
    state, on = np.zeros(b.n, dtype=bool), False
    for i in range(b.n):
        if on:
            if b.c[i] < mid[i]:                         # below the middle band: out
                on = False
        elif entry[i]:
            on = True
        state[i] = on
    return state


def three_down(b: S.Bars, streak: int = 3) -> np.ndarray:
    """Short-term reversal: enter after `streak` lower closes in a row; stay long until a close that is not lower than the one before."""
    down = np.zeros(b.n, dtype=bool)
    down[1:] = b.c[1:] < b.c[:-1]
    run = np.zeros(b.n, dtype=int)
    for i in range(1, b.n):
        run[i] = run[i - 1] + 1 if down[i] else 0
    state, on = np.zeros(b.n, dtype=bool), False
    for i in range(b.n):
        if on:
            on = bool(down[i])
        elif run[i] >= streak:
            on = True
        state[i] = on
    return state


def money_flow(b: S.Bars, n: int = 20, threshold: float = 0.05) -> np.ndarray:
    """Chaikin money flow: the volume-weighted position of the close within the day's range, averaged over `n` days; long while it is above `threshold`."""
    rng = b.h - b.l
    with np.errstate(invalid="ignore", divide="ignore"):
        clv = np.where(rng > 0, ((b.c - b.l) - (b.h - b.c)) / rng, 0.0)
        cmf = I.sma(clv * b.v, n) / I.sma(b.v, n)
        return cmf > threshold                          # a warm-up NaN compares False


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    fn: Callable[[S.Bars], np.ndarray]


CANDIDATES: dict[str, Candidate] = {c.id: c for c in [
    Candidate("monday", "Monday-only holding (day-of-week effect)", monday),
    Candidate("volume_surge", "Hold after a volume surge on an up day", volume_surge),
    Candidate("near_high", "Hold while within 5% of the 13-week high", near_high),
    Candidate("squeeze_break", "Volatility squeeze, then a break above the upper band", squeeze_break),
    Candidate("three_down", "Buy after three lower closes (short-term reversal)", three_down),
    Candidate("money_flow", "Hold while Chaikin money flow is positive", money_flow),
]}


# ---- the screen ----
def days(prep: B.Prepared) -> np.ndarray:
    """Indices of the TRAIN days followed by the VALIDATION days: the days over which the registry compares position series."""
    (a0, a1), (b0, b1) = prep.period("TRAIN"), prep.period("VALIDATION")
    return np.concatenate([np.arange(a0, a1 + 1), np.arange(b0, b1 + 1)])


SCREENED_AGAINST = "1.2"                               # the screen compares with the twelve families (100 configurations) of protocol 1.2 that every queued candidate was written against; a family added later is not in the comparison,
                                                       # so the recorded screen can be reproduced (and a candidate that has become a family is not compared with itself)


def existing(prep: B.Prepared) -> dict:
    """The series of every configuration of every stop or weight family pre-registered under protocol 1.2: {(family id, param key): float array over all candles}. Stop families give their ON/OFF state, weight families their target weight."""
    out = {}
    for fam in S.FAMILIES.values():
        if fam.kind not in ("stop", "weight") or fam.since != SCREENED_AGAINST:
            continue
        for p in S.configs(fam):
            sig = prep.signals(fam, p)
            out[(fam.id, B.param_key(p))] = sig.state.astype(float) if fam.kind == "stop" else np.nan_to_num(np.asarray(sig.weight, dtype=float))
    return out


def correlations(candidate, series: dict, idx: np.ndarray) -> list:
    """[(Pearson r, key)] of the candidate against each series over the days idx, highest first. A candidate that never changes over those days, or a series that never does, has no correlation: nothing is listed for it."""
    x = np.asarray(candidate, dtype=float)[idx]
    if np.std(x) < 1e-12:
        return []
    rows = []
    for key, s in series.items():
        y = s[idx]
        if np.std(y) >= 1e-12:
            rows.append((float(np.corrcoef(x, y)[0, 1]), key))
    return sorted(rows, key=lambda r: -r[0])


def prescreen(prep: B.Prepared, fn: Callable[[S.Bars], np.ndarray], top: int = 3, series: dict | None = None) -> dict:
    """The candidate's timing against all 100 existing configurations: how often it is ON, its highest correlation, the closest configurations, and whether it is a renamed copy (0.90 or more, as in protocol section 10)."""
    state = np.asarray(fn(prep.bars), dtype=float)
    idx = days(prep)
    rows = correlations(state, existing(prep) if series is None else series, idx)
    best = rows[0][0] if rows else None
    return {"days": int(len(idx)), "share_on": float(state[idx].mean()), "max_correlation": best, "renamed": best is not None and best >= DUP_CORRELATION,
            "closest": [{"family": k[0], "params": dict(k[1]), "correlation": r} for r, k in rows[:top]]}


def prescreen_all(prep: B.Prepared, top: int = 3) -> dict:
    series = existing(prep)
    return {cid: {"name": c.name, **prescreen(prep, c.fn, top, series)} for cid, c in CANDIDATES.items()}


def main(argv: list) -> int:
    from . import research as RS
    candles = D.load(D.daily_path())
    if len(candles) < 2:
        print("no stored daily candles: run `python -m atlas_api.btcquant.data` first")
        return 1
    prep = B.Prepared(candles)
    result = prescreen_all(prep)
    out = {"data": RS.data_version(prep), "protocol": C.PROTOCOL_VERSION, "threshold": DUP_CORRELATION, "candidates": result}
    C.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (C.REPORT_DIR / "novelty.json").write_text(json.dumps(out, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(f"novelty pre-screen on {out['data']['candles']} candles to {out['data']['last'][:10]}, TRAIN and VALIDATION days, renamed at {DUP_CORRELATION:.2f} or more")
    for cid, r in result.items():
        near = r["closest"][0] if r["closest"] else None
        print(f"  {cid:14s} on {r['share_on']:.0%} of days; highest correlation " + (f"{r['max_correlation']:+.2f} with {near['family']} {near['params']}" if near else "n/a") + ("  RENAMED COPY" if r["renamed"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
