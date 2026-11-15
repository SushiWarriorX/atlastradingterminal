"""The twelve strategy families of the protocol (section 5) plus the two benchmarks, as pure functions of completed daily candles.

A family turns candles and one parameter set into SIGNALS for every candle: at the close of candle i it says
  - state[i]  (stop kinds): True if the strategy wants to be long from the next open;
  - weight[i] (weight kinds): the target fraction of equity in Bitcoin from the next open;
  - stop[i]   (stop kinds): the protective stop level to use if it enters now (and, for trailing stops, the candidate level to ratchet up to).
Every value at index i uses candles 0..i only; a test changes later candles and checks that nothing at or before i moves. Warm-up values are False / 0 / NaN.
Families that "stay ON until stopped" (Donchian and the ATR trend filter) replay their own trailing stop on the candles to know when they were stopped, so the state they report matches what the account engine does with the same stop.
Grids are fixed by the protocol: 100 configurations in all, which is the N used for multiple testing.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import config as C
from . import indicators as I

STOP_K = C.STOP_ATR_MULT


class Bars:
    """Daily candles as numpy arrays plus a small cache of indicators, so the grid does not recompute the same SMA a hundred times."""

    def __init__(self, candles):
        a = np.asarray(candles, dtype=float)
        self.t = a[:, 0].astype(np.int64)
        self.o, self.h, self.l, self.c, self.v = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
        self.n = len(a)
        self._cache: dict = {}

    def ind(self, name: str, *args):
        key = (name, args)
        if key not in self._cache:
            self._cache[key] = {
                "sma": lambda n: I.sma(self.c, n), "atr": lambda n: I.atr(self.h, self.l, self.c, n), "rsi": lambda n: I.rsi(self.c, n), "adx": lambda n: I.adx(self.h, self.l, self.c, n),
                "std0": lambda n: I.rolling_std(self.c, n, ddof=0), "vol": lambda n: I.realized_vol(self.c, n), "change": lambda n: I.change(self.c, n),
                "hhigh_prior": lambda n: I.prior(I.rolling_max(self.h, n), 1), "llow": lambda n: I.rolling_min(self.l, n),
            }[name](*args)
        return self._cache[key]


@dataclass
class Signals:
    state: np.ndarray | None = None
    weight: np.ndarray | None = None
    stop: np.ndarray | None = None


@dataclass(frozen=True)
class Family:
    id: str
    name: str
    category: str
    kind: str                                   # stop | weight | hold | cash
    trail: bool
    grid: dict                                  # parameter name -> ordered values
    build: Callable[[Bars, dict], Signals]
    explain: Callable[[Bars, dict, int], dict]
    valid: Callable[[dict], bool] = lambda p: True


def _fixed_stop(b: Bars) -> np.ndarray:
    return b.c - STOP_K * b.ind("atr", C.ATR_N)


def _f(x) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), 6)


def _nan_false(cond: np.ndarray, *arrays) -> np.ndarray:
    ok = np.ones(len(cond), dtype=bool)
    for a in arrays:
        ok &= np.isfinite(a)
    return cond & ok


# ---- 1. sma_cross ----
def _sma_cross(b, p):
    f, s = b.ind("sma", int(p["fast"])), b.ind("sma", int(p["slow"]))
    with np.errstate(invalid="ignore"):
        st = _nan_false(f > s, f, s)
    return Signals(state=st, stop=_fixed_stop(b))


def _sma_cross_x(b, p, i):
    return {"close": _f(b.c[i]), "sma_fast": _f(b.ind("sma", int(p["fast"]))[i]), "sma_slow": _f(b.ind("sma", int(p["slow"]))[i]), "atr14": _f(b.ind("atr", C.ATR_N)[i])}


# ---- 2. donchian (trailing stop: lowest low of the last N/2 candles) ----
def _donchian(b, p):
    n = int(p["N"])
    high_n = b.ind("hhigh_prior", n)                                # highest high of the previous n candles (not including i)
    cand = b.ind("llow", n // 2)                                    # lowest low of the last n/2 candles including i: the stop candidate
    with np.errstate(invalid="ignore"):
        entry = _nan_false(b.c > high_n, high_n, cand)
    state = np.zeros(b.n, dtype=bool)
    on, stop = False, np.nan
    for i in range(b.n):
        if on:
            if b.l[i] <= stop:                                      # the stop in force since the previous close was touched during candle i: OFF at this close
                on = False
            else:
                stop = max(stop, cand[i])                           # ratchets up only. It can never actually be lowered here: a new low under the window's lowest low would have hit the stop, and
                                                                    # dropping the oldest candle can only raise the lowest low. Kept for clarity; a property test checks it
        elif entry[i]:                                              # a stopped-out state waits at least one candle before it can re-enter (the "armed" rule)
            on, stop = True, cand[i]
        state[i] = on
    return Signals(state=state, stop=cand)


def _donchian_x(b, p, i):
    n = int(p["N"])
    return {"close": _f(b.c[i]), "highest_high_prior_N": _f(b.ind("hhigh_prior", n)[i]), "trailing_stop_candidate": _f(b.ind("llow", n // 2)[i])}


# ---- 3. ma_atr_trend (trailing stop: ratchet of close - m x ATR) ----
def _ma_atr(b, p):
    sma, atr = b.ind("sma", int(p["L"])), b.ind("atr", C.ATR_N)
    m = float(p["m"])
    cand = b.c - m * atr
    state = np.zeros(b.n, dtype=bool)
    on, armed, stop = False, True, np.nan
    for i in range(b.n):
        if not np.isfinite(sma[i]) or not np.isfinite(atr[i]):
            state[i] = False
            continue
        if on:
            if b.l[i] <= stop:
                on = False
            else:
                stop = max(stop, cand[i])
        if b.c[i] <= sma[i]:
            armed = True
        if not on and armed and b.c[i] > sma[i]:
            on, armed, stop = True, False, cand[i]
        state[i] = on
    return Signals(state=state, stop=cand)


def _ma_atr_x(b, p, i):
    return {"close": _f(b.c[i]), "sma": _f(b.ind("sma", int(p["L"]))[i]), "atr14": _f(b.ind("atr", C.ATR_N)[i]), "stop_candidate": _f(b.c[i] - float(p["m"]) * b.ind("atr", C.ATR_N)[i])}


# ---- 4. tsmom ----
def _tsmom(b, p):
    r = b.ind("change", int(p["L"]))
    with np.errstate(invalid="ignore"):
        st = _nan_false(r > 0, r)
    return Signals(state=st, stop=_fixed_stop(b))


def _tsmom_x(b, p, i):
    return {"close": _f(b.c[i]), "return_over_L": _f(b.ind("change", int(p["L"]))[i])}


# ---- 5. rsi_momentum (hysteresis) ----
def _hyst(on_cond: np.ndarray, off_cond: np.ndarray) -> np.ndarray:
    st, on = np.zeros(len(on_cond), dtype=bool), False
    for i in range(len(on_cond)):
        if on and off_cond[i]:
            on = False
        elif not on and on_cond[i]:
            on = True
        st[i] = on
    return st


def _rsi_mom(b, p):
    r = b.ind("rsi", int(p["n"]))
    with np.errstate(invalid="ignore"):
        on, off = _nan_false(r > p["enter"], r), _nan_false(r < p["exit"], r)
    return Signals(state=_hyst(on, off), stop=_fixed_stop(b))


def _rsi_x(b, p, i):
    return {"close": _f(b.c[i]), "rsi": _f(b.ind("rsi", int(p["n"]))[i])}


# ---- 6. mom_vol ----
def _mom_vol(b, p):
    r, v = b.ind("change", int(p["L"])), b.ind("vol", 20)
    with np.errstate(invalid="ignore"):
        st = _nan_false((r > 0) & (v <= p["cap"]), r, v)
    return Signals(state=st, stop=_fixed_stop(b))


def _mom_vol_x(b, p, i):
    return {"close": _f(b.c[i]), "return_over_L": _f(b.ind("change", int(p["L"]))[i]), "realised_vol_20": _f(b.ind("vol", 20)[i])}


# ---- 7. bollinger_mr ----
def _bollinger(b, p):
    n, k = int(p["n"]), float(p["k"])
    mid, sd = b.ind("sma", n), b.ind("std0", n)
    lower = mid - k * sd
    with np.errstate(invalid="ignore"):
        on, off = _nan_false(b.c < lower, lower), _nan_false(b.c >= mid, mid)
    return Signals(state=_hyst(on, off), stop=_fixed_stop(b))


def _bollinger_x(b, p, i):
    n, k = int(p["n"]), float(p["k"])
    mid, sd = b.ind("sma", n)[i], b.ind("std0", n)[i]
    return {"close": _f(b.c[i]), "middle": _f(mid), "lower": _f(mid - k * sd)}


# ---- 8. rsi_oversold ----
def _rsi_os(b, p):
    r = b.ind("rsi", int(p["n"]))
    with np.errstate(invalid="ignore"):
        on, off = _nan_false(r < p["enter"], r), _nan_false(r > p["exit"], r)
    return Signals(state=_hyst(on, off), stop=_fixed_stop(b))


# ---- 9. vol_breakout ----
def _vol_breakout(b, p):
    k, hold = float(p["k"]), int(p["hold"])
    atr = b.ind("atr", C.ATR_N)
    state = np.zeros(b.n, dtype=bool)
    on, age = False, 0
    for i in range(1, b.n):
        if on:
            age += 1
            if age >= hold:
                on = False
        elif np.isfinite(atr[i - 1]) and b.c[i] - b.c[i - 1] > k * atr[i - 1]:
            on, age = True, 0
        state[i] = on
    return Signals(state=state, stop=_fixed_stop(b))


def _vol_breakout_x(b, p, i):
    a = b.ind("atr", C.ATR_N)
    return {"close": _f(b.c[i]), "move": _f(b.c[i] - b.c[i - 1]) if i else None, "k_x_atr14_prev": _f(float(p["k"]) * a[i - 1]) if i else None}


# ---- 10. regime_switch ----
def _regime(b, p):
    adx, s50, s200 = b.ind("adx", 14), b.ind("sma", 50), b.ind("sma", 200)
    mid, sd = b.ind("sma", 20), b.ind("std0", 20)
    with np.errstate(invalid="ignore"):
        trend = adx > p["adx"]
        long_trend = _nan_false(trend & (s50 > s200), adx, s50, s200)
        long_range = _nan_false((~trend) & (b.c < mid - 1.5 * sd), adx, mid, sd)
    return Signals(state=long_trend | long_range, stop=_fixed_stop(b))


def _regime_x(b, p, i):
    return {"close": _f(b.c[i]), "adx14": _f(b.ind("adx", 14)[i]), "sma50": _f(b.ind("sma", 50)[i]), "sma200": _f(b.ind("sma", 200)[i]), "sma20": _f(b.ind("sma", 20)[i]), "sd20": _f(b.ind("std0", 20)[i])}


# ---- 11. vol_target (weight) ----
def _vol_target(b, p):
    v = b.ind("vol", int(p["window"]))
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(np.isfinite(v) & (v > 0), np.minimum(1.0, p["target"] / v), 0.0)
    return Signals(weight=w)


def _vol_target_x(b, p, i):
    v = b.ind("vol", int(p["window"]))[i]
    return {"close": _f(b.c[i]), "realised_vol": _f(v), "target_weight": _f(min(1.0, p["target"] / v)) if np.isfinite(v) and v > 0 else 0.0}


# ---- 12. sma_filter (weight) ----
def _sma_filter(b, p):
    s = b.ind("sma", int(p["L"]))
    with np.errstate(invalid="ignore"):
        w = np.where(np.isfinite(s) & (b.c > s), 1.0, 0.0)
    return Signals(weight=w)


def _sma_filter_x(b, p, i):
    return {"close": _f(b.c[i]), "sma": _f(b.ind("sma", int(p["L"]))[i])}


# ---- benchmarks ----
def _none(b, p):
    return Signals()


FAMILIES: dict[str, Family] = {f.id: f for f in [
    Family("sma_cross", "Moving-average crossover", "trend", "stop", False, {"fast": [10, 20, 30, 50], "slow": [50, 100, 150, 200]}, _sma_cross, _sma_cross_x, lambda p: p["fast"] < p["slow"]),
    Family("donchian", "Donchian breakout", "trend", "stop", True, {"N": [20, 40, 55, 80]}, _donchian, _donchian_x),
    Family("ma_atr_trend", "Moving-average trend filter with ATR exit", "trend", "stop", True, {"L": [100, 150, 200], "m": [2, 3, 4]}, _ma_atr, _ma_atr_x),
    Family("tsmom", "Time-series momentum", "momentum", "stop", False, {"L": [30, 60, 90, 180, 365]}, _tsmom, _tsmom_x),
    Family("rsi_momentum", "RSI momentum", "momentum", "stop", False, {"n": [14, 21], "enter": [55, 60, 65], "exit": [40, 45, 50]}, _rsi_mom, _rsi_x),
    Family("mom_vol", "Momentum with a volatility filter", "momentum", "stop", False, {"L": [30, 60, 90], "cap": [0.6, 0.8, 1.0]}, _mom_vol, _mom_vol_x),
    Family("bollinger_mr", "Bollinger band mean reversion", "mean_reversion", "stop", False, {"n": [20, 30], "k": [1.5, 2.0, 2.5]}, _bollinger, _bollinger_x),
    Family("rsi_oversold", "RSI oversold reversal", "mean_reversion", "stop", False, {"n": [7, 14], "enter": [20, 25, 30], "exit": [50, 55]}, _rsi_os, _rsi_x),
    Family("vol_breakout", "Volatility breakout", "volatility", "stop", False, {"k": [1.0, 1.5, 2.0], "hold": [5, 10, 20]}, _vol_breakout, _vol_breakout_x),
    Family("regime_switch", "Trend versus ranging regime switch", "regime", "stop", False, {"adx": [20, 25, 30]}, _regime, _regime_x),
    Family("vol_target", "Volatility-targeted exposure", "risk_managed", "weight", False, {"target": [0.30, 0.40, 0.50], "window": [20, 40]}, _vol_target, _vol_target_x),
    Family("sma_filter", "Simple trend filter exposure", "risk_managed", "weight", False, {"L": [100, 150, 200, 250]}, _sma_filter, _sma_filter_x),
    Family("buy_hold", "Buy and hold (benchmark)", "benchmark", "hold", False, {}, _none, lambda b, p, i: {}),
    Family("cash", "Cash only (benchmark)", "benchmark", "cash", False, {}, _none, lambda b, p, i: {}),
]}
RESEARCH = [f for f in FAMILIES.values() if f.category != "benchmark"]


def configs(fam: Family) -> list[dict]:
    """Every valid parameter set of a family, in a fixed order."""
    if not fam.grid:
        return [{}]
    names = list(fam.grid)
    out = [dict(zip(names, vals)) for vals in itertools.product(*[fam.grid[n] for n in names])]
    return [p for p in out if fam.valid(p)]


def neighbours(fam: Family, p: dict) -> list[dict]:
    """Parameter sets one step away in exactly one parameter (grid index distance 1), valid ones only."""
    out = []
    for name, values in fam.grid.items():
        i = values.index(p[name])
        for j in (i - 1, i + 1):
            if 0 <= j < len(values):
                q = dict(p)
                q[name] = values[j]
                if fam.valid(q):
                    out.append(q)
    return out


def n_configurations() -> int:
    return sum(len(configs(f)) for f in RESEARCH)


def spec(fam_id: str, params: dict, version: int = 1) -> dict:
    """The canonical specification of a candidate: family, version, sorted parameters, and the protocol constants that change its behaviour. This is what is hashed and what a registry stores."""
    return {"family": fam_id, "version": version, "params": {k: params[k] for k in sorted(params)}, "protocol": C.PROTOCOL_VERSION,
            "fee": C.FEE, "slippage": C.SLIPPAGE, "risk": C.RISK_PER_TRADE, "stop_k": C.STOP_ATR_MULT, "atr_n": C.ATR_N, "breaker": C.CIRCUIT_BREAKER, "cool_off": C.BREAKER_COOL_OFF_DAYS,
            "band": C.REBALANCE_BAND}


def hash_spec(spec_dict: dict) -> str:
    """The short hash of a stored specification (no reading of today's constants, so an old specification keeps its hash)."""
    return hashlib.sha256(json.dumps(spec_dict, sort_keys=True).encode()).hexdigest()[:16]


def spec_hash(fam_id: str, params: dict, version: int = 1) -> str:
    return hash_spec(spec(fam_id, params, version))


def signals(fam_id: str, candles, params: dict) -> Signals:
    return FAMILIES[fam_id].build(Bars(candles) if not isinstance(candles, Bars) else candles, params)
