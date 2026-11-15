"""btcquant backtest runner (protocol sections 2, 3, 4 and 6): run one configuration of one family over one period with the account engine, and describe the result.

How a run works. The family's signals are computed ONCE on the whole candle history (they use only past candles, so a later start cannot change an earlier signal); the account then steps through the candles of
the period one at a time, exactly as the paper engine will: the order a signal creates at one close executes at the next open. Each period starts flat with the full starting equity, with indicator history reaching
back before the period start (the warm-up from 2019). The decision at the close of the candle before the period start is allowed to create the first order, so a rule that is already ON can enter at the first open.
Nothing is filled or interpolated. A position still open at the end of the period stays open (its profit is in the final equity, not in the trade list) and is reported as such.
"""
from __future__ import annotations

import bisect
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import numpy as np

from . import config as C
from . import metrics as M
from . import strategies as S
from .account import Account, Sig, make_account


def day_ts(d: date) -> int:
    """Epoch seconds of 00:00 UTC on a calendar day (the open time of that day's candle)."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def param_key(params: dict) -> tuple:
    return tuple(sorted(params.items()))


class Prepared:
    """The whole candle history plus what every run needs from it: indicator cache, regime labels, close-to-close returns and a cache of signals and of the buy-and-hold result."""

    def __init__(self, candles):
        self.candles = [tuple(c) for c in candles]
        if len(self.candles) < 2:
            raise ValueError("at least two candles are needed")
        self.bars = S.Bars(self.candles)
        self.times = [int(t) for t in self.bars.t]
        self.regimes = M.regime_labels(self.bars.c, self.bars.ind("sma", 200))
        c = self.bars.c
        self.btc_returns = np.concatenate([[np.nan], c[1:] / c[:-1] - 1.0])
        self._signals: dict = {}
        self._hold: dict = {}

    def span(self, start: date, end: date | None) -> tuple[int, int]:
        """Index of the first and the last candle of a period (both inclusive; end None means the latest candle). The period must be fully covered by the data and have a candle before it for the warm-up."""
        i0 = bisect.bisect_left(self.times, day_ts(start))
        if i0 >= len(self.times) or self.times[i0] != day_ts(start):
            raise ValueError(f"the data do not contain the first day of the period ({start.isoformat()})")
        if i0 < 1:
            raise ValueError("the period needs at least one candle before it")
        if end is None:
            return i0, len(self.times) - 1
        if self.times[-1] < day_ts(end):
            raise ValueError(f"the data end before the last day of the period ({end.isoformat()})")
        i1 = bisect.bisect_right(self.times, day_ts(end)) - 1
        if i1 < i0:
            raise ValueError("the period holds no candle")
        return i0, i1

    def period(self, name: str) -> tuple[int, int]:
        start, end = C.PERIODS[name]
        return self.span(start, end)

    def signals(self, fam: S.Family, params: dict) -> S.Signals:
        key = (fam.id, param_key(params))
        if key not in self._signals:
            self._signals[key] = fam.build(self.bars, params)
        return self._signals[key]


@dataclass
class Run:
    family: str
    params: dict
    i0: int
    i1: int
    fee: float
    slip: float
    sizing: str
    metrics: dict
    returns: np.ndarray                                   # daily return of each candle of the period
    exposure: np.ndarray                                  # share of equity in Bitcoin held through each day (at the open, after the day's order)
    trips: list = field(default_factory=list)             # circuit-breaker trips: {"t", "equity", "peak"}
    account: Account | None = None


def _sig(prep: Prepared, fam: S.Family, sig: S.Signals | None, params: dict, i: int, verbose: bool) -> Sig | None:
    if fam.kind == "stop":
        stop = sig.stop[i]
        return Sig(state=bool(sig.state[i]), stop=float(stop) if np.isfinite(stop) else None, info=fam.explain(prep.bars, params, i) if verbose else None)
    if fam.kind == "weight":
        return Sig(weight=float(sig.weight[i]), info=fam.explain(prep.bars, params, i) if verbose else None)
    return None


def _account(prep: Prepared, fam: S.Family, params: dict, i0: int, i1: int, fee: float, slip: float, sizing: str, cool_off_days: int | None, start_equity: float, verbose: bool) -> Account:
    sig = prep.signals(fam, params) if fam.kind in ("stop", "weight") else None
    a = make_account(fam.id, fam.kind, fee=fee, slip=slip, sizing=sizing, trail=fam.trail, cool_off_days=cool_off_days, verbose=verbose, start_equity=start_equity)
    a.begin(prep.candles[i0 - 1], _sig(prep, fam, sig, params, i0 - 1, verbose), C.DAY)
    for i in range(i0, i1 + 1):
        a.step(prep.candles[i], _sig(prep, fam, sig, params, i, verbose), C.DAY)
    return a


def hold_return(prep: Prepared, i0: int, i1: int, fee: float = C.FEE, slip: float = C.SLIPPAGE, start_equity: float = C.START_EQUITY_STRATEGY) -> float:
    """Net return of buying at the first open of the period and holding to the last close (cached)."""
    key = (i0, i1, fee, slip, start_equity)
    if key not in prep._hold:
        a = _account(prep, S.FAMILIES["buy_hold"], {}, i0, i1, fee, slip, "risk", None, start_equity, False)
        prep._hold[key] = a.curve[-1][1] / start_equity - 1.0
    return prep._hold[key]


def run(prep: Prepared, fam_id: str, params: dict, i0: int, i1: int, *, fee: float = C.FEE, slip: float = C.SLIPPAGE, sizing: str = "risk",
        cool_off_days: int | None = C.BREAKER_COOL_OFF_DAYS, start_equity: float = C.START_EQUITY_STRATEGY, verbose: bool = False, keep_account: bool = False) -> Run:
    """One configuration over candles i0..i1 (inclusive). `sizing="full"` is the labelled sensitivity: the same signals at 100% exposure when long, with no 1% cap."""
    fam = S.FAMILIES[fam_id]
    a = _account(prep, fam, params, i0, i1, fee, slip, sizing, cool_off_days, start_equity, verbose)
    avg_exposure = float(np.mean([row[2] for row in a.curve]))
    marks = M.matched_hold(prep.bars.o[i0:i1 + 1], prep.bars.c[i0:i1 + 1], avg_exposure, start_equity, fee, slip)
    m = M.compute(a.curve, a.trades, start_equity=start_equity, fees_paid=a.fees_paid, slip_paid=a.slip_paid, traded=a.traded, fills=a.fills, breaker_trips=len(a.breaker_trips),
                  open_position=a.qty > 1e-12, hold_return=hold_return(prep, i0, i1, fee, slip, start_equity), matched_return=marks[-1] / start_equity - 1.0,
                  labels=prep.regimes[i0 - 1:i1], btc_returns=prep.btc_returns[i0:i1 + 1])
    equity = [row[1] for row in a.curve]
    return Run(family=fam_id, params=dict(params), i0=i0, i1=i1, fee=fee, slip=slip, sizing=sizing, metrics=m, returns=M.daily_returns(equity, start_equity),
               exposure=np.array([row[6] for row in a.curve]), trips=list(a.breaker_trips), account=a if keep_account else None)


def run_all(prep: Prepared, fam_id: str, i0: int, i1: int, **kw) -> dict:
    """Every configuration of a family over one period: {param_key: Run}."""
    fam = S.FAMILIES[fam_id]
    return {param_key(p): run(prep, fam_id, p, i0, i1, **kw) for p in S.configs(fam)}
