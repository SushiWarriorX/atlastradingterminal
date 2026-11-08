"""The strategy library: a small set of classic, fully specified rules. Nothing here is tuned to history and nothing is padded for count.

Every strategy states its entry, exit, stop and sizing in words and in code. A rule is evaluated at the CLOSE of a bar and acts at the next open
(see engine.py). Lengths are in BARS of the chosen timeframe (a 50-bar average is 50 days on 1d and about 8 days on 4h). Position size is the same for
every strategy: all of the account times the chosen leverage, so strategies are compared on their signals and not on hidden sizing choices.
`conditions()` reports whether each entry rule is true on the latest bar. That is a description of the rule right now, not a forecast.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

SIZING = "All of the account equity times the chosen leverage while in a trade; flat otherwise. One position at a time."


# --- indicators (all causal: the value at bar i uses bars <= i only) -------------------------------------------------------------------------
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["c"].shift(1)
    tr = pd.concat([df["h"] - df["l"], (df["h"] - pc).abs(), (df["l"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def hold(enter: pd.Series, leave: pd.Series, enter_short: pd.Series | None = None, leave_short: pd.Series | None = None) -> pd.Series:
    """Position series from entry/exit events: long from `enter` until `leave`; optionally short from `enter_short` until `leave_short`. Unknown (NaN) signals do nothing."""
    e, x = enter.fillna(False).to_numpy(bool), leave.fillna(False).to_numpy(bool)
    es = enter_short.fillna(False).to_numpy(bool) if enter_short is not None else np.zeros(len(e), bool)
    xs = leave_short.fillna(False).to_numpy(bool) if leave_short is not None else np.zeros(len(e), bool)
    out, p = np.zeros(len(e)), 0
    for i in range(len(e)):
        if p == 1 and x[i]:
            p = 0
        elif p == -1 and xs[i]:
            p = 0
        if p == 0:
            if e[i]:
                p = 1
            elif es[i]:
                p = -1
        out[i] = p
    return pd.Series(out, index=enter.index)


def _val(x) -> str:
    return "not enough history yet" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.2f}"


def _cond(label: str, met, value: str) -> dict:
    return {"rule": label, "met": None if met is None or (isinstance(met, float) and np.isnan(met)) else bool(met), "value": value}


@dataclass
class Strategy:
    id: str
    name: str
    family: str
    summary: str
    entry: str
    exit: str
    stop: str
    params: dict
    grid: dict                       # parameter name -> candidate values for walk-forward and the robustness check (one parameter varied at a time)
    build: Callable                  # (df, p) -> position series in {-1, 0, +1}
    conds: Callable                  # (df, p) -> list of condition dicts about the latest bar
    stop_pct: float | None = None
    symmetric: bool = False          # has a mirror-image short side that perps can use
    requires_funding: bool = False
    sizing: str = SIZING
    notes: list = field(default_factory=list)

    def meta(self) -> dict:
        return {"id": self.id, "name": self.name, "family": self.family, "summary": self.summary, "entry": self.entry, "exit": self.exit, "stop": self.stop, "sizing": self.sizing,
                "params": self.params, "grid": self.grid, "stop_pct": self.stop_pct, "symmetric": self.symmetric, "requires_funding": self.requires_funding, "notes": self.notes}


S: dict[str, Strategy] = {}


def reg(s: Strategy):
    S[s.id] = s


# 1 trend: price vs long average
reg(Strategy("price_above_sma", "Price above long average", "Trend", "Hold BTC while the price is above its long moving average.",
             "Close is above the N-bar simple average.", "Close falls to or below the average.", "No fixed stop; the exit rule is the stop.", {"n": 200}, {"n": [100, 150, 200, 250, 300]},
             lambda d, p: pd.Series(np.where(d["c"] > sma(d["c"], p["n"]), 1.0, np.where(sma(d["c"], p["n"]).isna(), 0.0, -1.0)), index=d.index),
             lambda d, p: [_cond(f"Close above {p['n']}-bar average", d["c"].iloc[-1] > sma(d["c"], p["n"]).iloc[-1] if not np.isnan(sma(d["c"], p["n"]).iloc[-1]) else None, f"close {_val(d['c'].iloc[-1])} vs average {_val(sma(d['c'], p['n']).iloc[-1])}")],
             symmetric=True))


def _cross(fast_f, slow_f, fn_name):
    def build(d, p):
        a, b = fast_f(d["c"], p["fast"]), slow_f(d["c"], p["slow"])
        return pd.Series(np.where(b.isna(), 0.0, np.where(a > b, 1.0, -1.0)), index=d.index)

    def conds(d, p):
        a, b = fast_f(d["c"], p["fast"]).iloc[-1], slow_f(d["c"], p["slow"]).iloc[-1]
        return [_cond(f"{p['fast']}-bar {fn_name} above {p['slow']}-bar {fn_name}", None if np.isnan(a) or np.isnan(b) else a > b, f"fast {_val(a)} vs slow {_val(b)}")]
    return build, conds


_b, _c = _cross(sma, sma, "average")
reg(Strategy("sma_cross", "Moving-average crossover", "Trend", "Hold BTC while a faster average is above a slower one.", "Fast simple average is above the slow simple average.",
             "Fast average falls to or below the slow average.", "No fixed stop; the exit rule is the stop.", {"fast": 50, "slow": 200}, {"fast": [20, 30, 50, 70, 100]}, _b, _c, symmetric=True))
_b, _c = _cross(ema, ema, "EMA")
reg(Strategy("ema_cross", "Exponential-average crossover", "Trend", "Like the crossover above but with exponential averages, which react faster.", "Fast EMA is above the slow EMA.",
             "Fast EMA falls to or below the slow EMA.", "No fixed stop; the exit rule is the stop.", {"fast": 12, "slow": 26}, {"fast": [8, 10, 12, 16, 20]}, _b, _c, symmetric=True))


def _donchian_build(d, p):
    hi, lo = d["h"].shift(1).rolling(p["entry"]).max(), d["l"].shift(1).rolling(p["entry"]).min()
    xl, xh = d["l"].shift(1).rolling(p["exit"]).min(), d["h"].shift(1).rolling(p["exit"]).max()
    return hold(d["c"] > hi, d["c"] < xl, d["c"] < lo, d["c"] > xh)


def _donchian_conds(d, p):
    hi, xl = d["h"].shift(1).rolling(p["entry"]).max().iloc[-1], d["l"].shift(1).rolling(p["exit"]).min().iloc[-1]
    c = d["c"].iloc[-1]
    return [_cond(f"Close above the {p['entry']}-bar high (entry)", None if np.isnan(hi) else c > hi, f"close {_val(c)} vs high {_val(hi)}"),
            _cond(f"Close below the {p['exit']}-bar low (exit)", None if np.isnan(xl) else c < xl, f"close {_val(c)} vs low {_val(xl)}")]


reg(Strategy("donchian_breakout", "Long breakout (55/20)", "Breakout", "Buy new highs, sell when the price breaks a shorter-term low.", "Close is above the highest high of the previous N bars.",
             "Close is below the lowest low of the previous M bars.", "No fixed stop; the exit rule is the stop.", {"entry": 55, "exit": 20}, {"entry": [20, 40, 55, 80, 100]}, _donchian_build, _donchian_conds, symmetric=True))
reg(Strategy("donchian_fast", "Short-term breakout (20/10)", "Breakout", "A faster version of the breakout rule: more trades, smaller swings.", "Close is above the highest high of the previous 20 bars.",
             "Close is below the lowest low of the previous 10 bars.", "No fixed stop; the exit rule is the stop.", {"entry": 20, "exit": 10}, {"entry": [10, 15, 20, 30, 40]}, _donchian_build, _donchian_conds, symmetric=True))


def _rsi_mr_build(d, p):
    r = rsi(d["c"], p["n"])
    return hold(r < p["low"], r > p["exit"])


reg(Strategy("rsi_reversion", "RSI oversold bounce", "Mean reversion", "Buy after a sharp drop (RSI low) and sell when momentum recovers.", "RSI(N) falls below the oversold level.",
             "RSI rises above the exit level.", "Stop 10% below the entry fill.", {"n": 14, "low": 30, "exit": 50}, {"low": [20, 25, 30, 35, 40]}, _rsi_mr_build,
             lambda d, p: [_cond(f"RSI({p['n']}) below {p['low']}", None if np.isnan(rsi(d['c'], p['n']).iloc[-1]) else rsi(d['c'], p['n']).iloc[-1] < p['low'], f"RSI {_val(rsi(d['c'], p['n']).iloc[-1])}")], stop_pct=10.0))


def _rsi2_build(d, p):
    r, trend = rsi(d["c"], 2), sma(d["c"], p["trend"])
    return hold((r < p["low"]) & (d["c"] > trend), r > p["exit"])


reg(Strategy("rsi2_trend", "Short-term dip in an uptrend", "Mean reversion", "Buy brief, sharp dips only while the long-term trend is up.", "RSI(2) is below the dip level and the close is above the long average.",
             "RSI(2) rises above the exit level.", "Stop 10% below the entry fill.", {"low": 10, "exit": 60, "trend": 200}, {"low": [5, 10, 15, 20, 25]}, _rsi2_build,
             lambda d, p: [_cond(f"RSI(2) below {p['low']}", None if np.isnan(rsi(d['c'], 2).iloc[-1]) else rsi(d['c'], 2).iloc[-1] < p['low'], f"RSI(2) {_val(rsi(d['c'], 2).iloc[-1])}"),
                           _cond(f"Close above {p['trend']}-bar average", None if np.isnan(sma(d['c'], p['trend']).iloc[-1]) else d['c'].iloc[-1] > sma(d['c'], p['trend']).iloc[-1], f"close {_val(d['c'].iloc[-1])} vs {_val(sma(d['c'], p['trend']).iloc[-1])}")], stop_pct=10.0))


def _bb(d, p):
    m, sd = sma(d["c"], p["n"]), d["c"].rolling(p["n"], min_periods=p["n"]).std(ddof=0)
    return m, m + p["k"] * sd, m - p["k"] * sd


reg(Strategy("bollinger_reversion", "Bollinger band bounce", "Mean reversion", "Buy when the price drops below its lower band and sell at the middle.", "Close is below the lower Bollinger band (N bars, K standard deviations).",
             "Close is back above the middle band.", "Stop 10% below the entry fill.", {"n": 20, "k": 2.0}, {"k": [1.5, 1.75, 2.0, 2.25, 2.5]},
             lambda d, p: hold(d["c"] < _bb(d, p)[2], d["c"] > _bb(d, p)[0]),
             lambda d, p: [_cond(f"Close below lower band ({p['n']} bars, {p['k']} SD)", None if np.isnan(_bb(d, p)[2].iloc[-1]) else d["c"].iloc[-1] < _bb(d, p)[2].iloc[-1], f"close {_val(d['c'].iloc[-1])} vs band {_val(_bb(d, p)[2].iloc[-1])}")], stop_pct=10.0))
reg(Strategy("bollinger_breakout", "Bollinger band breakout", "Breakout", "Buy when the price closes above its upper band (strong momentum) and sell at the middle.", "Close is above the upper Bollinger band.",
             "Close is back below the middle band.", "No fixed stop; the exit rule is the stop.", {"n": 20, "k": 2.0}, {"k": [1.5, 1.75, 2.0, 2.25, 2.5]},
             lambda d, p: hold(d["c"] > _bb(d, p)[1], d["c"] < _bb(d, p)[0]),
             lambda d, p: [_cond(f"Close above upper band ({p['n']} bars, {p['k']} SD)", None if np.isnan(_bb(d, p)[1].iloc[-1]) else d["c"].iloc[-1] > _bb(d, p)[1].iloc[-1], f"close {_val(d['c'].iloc[-1])} vs band {_val(_bb(d, p)[1].iloc[-1])}")]))


def _macd(d, p):
    line = ema(d["c"], p["fast"]) - ema(d["c"], p["slow"])
    return line, line.ewm(span=p["signal"], adjust=False, min_periods=p["signal"]).mean()


def _macd_build(d, p):
    line, sig = _macd(d, p)
    return pd.Series(np.where(sig.isna(), 0.0, np.where(line > sig, 1.0, -1.0)), index=d.index)


reg(Strategy("macd", "MACD momentum", "Momentum", "Hold BTC while the MACD line is above its signal line.", "MACD line (fast EMA minus slow EMA) is above its signal line.",
             "MACD line falls to or below the signal line.", "No fixed stop; the exit rule is the stop.", {"fast": 12, "slow": 26, "signal": 9}, {"fast": [8, 10, 12, 16, 20]}, _macd_build,
             lambda d, p: [_cond("MACD line above signal line", None if np.isnan(_macd(d, p)[1].iloc[-1]) else _macd(d, p)[0].iloc[-1] > _macd(d, p)[1].iloc[-1], f"MACD {_val(_macd(d, p)[0].iloc[-1])} vs signal {_val(_macd(d, p)[1].iloc[-1])}")], symmetric=True))
reg(Strategy("momentum_roc", "Trailing-return momentum", "Momentum", "Hold BTC while its return over the last N bars is positive.", "The N-bar rate of change is above zero.", "The N-bar rate of change is zero or below.",
             "No fixed stop; the exit rule is the stop.", {"n": 90}, {"n": [30, 60, 90, 120, 180]},
             lambda d, p: pd.Series(np.where(d["c"].pct_change(p["n"]).isna(), 0.0, np.where(d["c"].pct_change(p["n"]) > 0, 1.0, -1.0)), index=d.index),
             lambda d, p: [_cond(f"{p['n']}-bar return above 0", None if np.isnan(d["c"].pct_change(p["n"]).iloc[-1]) else d["c"].pct_change(p["n"]).iloc[-1] > 0, f"return {_val(d['c'].pct_change(p['n']).iloc[-1] * 100)}%")], symmetric=True))
reg(Strategy("momentum_filtered", "Momentum with trend filter", "Momentum", "Needs both positive recent returns and a price above its long average.", "30-bar return above zero and close above the N-bar average.",
             "Either condition stops being true.", "No fixed stop; the exit rule is the stop.", {"roc": 30, "n": 100}, {"n": [50, 75, 100, 150, 200]},
             lambda d, p: ((d["c"].pct_change(p["roc"]) > 0) & (d["c"] > sma(d["c"], p["n"]))).astype(float),
             lambda d, p: [_cond(f"{p['roc']}-bar return above 0", None if np.isnan(d["c"].pct_change(p["roc"]).iloc[-1]) else d["c"].pct_change(p["roc"]).iloc[-1] > 0, f"return {_val(d['c'].pct_change(p['roc']).iloc[-1] * 100)}%"),
                           _cond(f"Close above {p['n']}-bar average", None if np.isnan(sma(d['c'], p['n']).iloc[-1]) else d["c"].iloc[-1] > sma(d["c"], p["n"]).iloc[-1], f"close {_val(d['c'].iloc[-1])} vs {_val(sma(d['c'], p['n']).iloc[-1])}")]))


def _atr_channel(d, p):
    mid = ema(d["c"], p["n"])
    return mid, mid + p["k"] * atr(d, 14)


reg(Strategy("atr_channel", "Volatility channel breakout", "Volatility", "Buy when the price breaks above a channel built from its average range; sell when it falls back to the middle.",
             "Close is above the N-bar EMA plus K times the 14-bar average true range.", "Close is back below the EMA.", "No fixed stop; the exit rule is the stop.", {"n": 20, "k": 2.0}, {"k": [1.0, 1.5, 2.0, 2.5, 3.0]},
             lambda d, p: hold(d["c"] > _atr_channel(d, p)[1], d["c"] < _atr_channel(d, p)[0]),
             lambda d, p: [_cond(f"Close above EMA + {p['k']} x ATR", None if np.isnan(_atr_channel(d, p)[1].iloc[-1]) else d["c"].iloc[-1] > _atr_channel(d, p)[1].iloc[-1], f"close {_val(d['c'].iloc[-1])} vs upper {_val(_atr_channel(d, p)[1].iloc[-1])}")]))
reg(Strategy("ma_ribbon", "Stacked averages", "Trend", "Hold BTC only when short, medium and long averages are stacked in order and the price is above them all.", "Close > 20-bar average > 50-bar average > 100-bar average.",
             "The stack breaks (any of those comparisons stops being true).", "No fixed stop; the exit rule is the stop.", {"a": 20, "b": 50, "c": 100}, {"c": [75, 100, 125, 150, 200]},
             lambda d, p: ((d["c"] > sma(d["c"], p["a"])) & (sma(d["c"], p["a"]) > sma(d["c"], p["b"])) & (sma(d["c"], p["b"]) > sma(d["c"], p["c"]))).astype(float),
             lambda d, p: [_cond("Averages stacked: close > fast > medium > slow", None if np.isnan(sma(d['c'], p['c']).iloc[-1]) else bool(d["c"].iloc[-1] > sma(d["c"], p["a"]).iloc[-1] > sma(d["c"], p["b"]).iloc[-1] > sma(d["c"], p["c"]).iloc[-1]),
                                 f"close {_val(d['c'].iloc[-1])}, {p['a']}/{p['b']}/{p['c']}: {_val(sma(d['c'], p['a']).iloc[-1])}/{_val(sma(d['c'], p['b']).iloc[-1])}/{_val(sma(d['c'], p['c']).iloc[-1])}")]))


def _dip_build(d, p):
    dd = d["c"] / d["c"].rolling(p["look"], min_periods=p["look"]).max() - 1
    return hold(dd <= -p["drop"] / 100, d["c"] > sma(d["c"], 20))


reg(Strategy("dip_buy", "Buy a deep drawdown", "Mean reversion", "Buy after a large fall from the recent high and sell once the price recovers to its 20-bar average.", "Close is at least X% below the highest close of the last 60 bars.",
             "Close is above the 20-bar average.", "Stop 15% below the entry fill.", {"drop": 20, "look": 60}, {"drop": [10, 15, 20, 25, 30]}, _dip_build,
             lambda d, p: [_cond(f"Close at least {p['drop']}% below the {p['look']}-bar high", None if d["c"].rolling(p["look"]).max().isna().iloc[-1] else d["c"].iloc[-1] / d["c"].rolling(p["look"]).max().iloc[-1] - 1 <= -p["drop"] / 100,
                                  f"{_val((d['c'].iloc[-1] / d['c'].rolling(p['look']).max().iloc[-1] - 1) * 100)}% from the high")], stop_pct=15.0))


def _funding_series(d, p):
    f = d["funding_ann"] if "funding_ann" in d else pd.Series(np.nan, index=d.index)
    return f


def _fund_build(d, p):
    f, trend = _funding_series(d, p), sma(d["c"], p["trend"])
    return hold((f < p["low"]) & (d["c"] > trend), f > p["high"])


reg(Strategy("funding_fade", "Fade negative funding", "Derivatives", "Perpetual funding turns negative when traders crowd into shorts. Buy that in an uptrend; sell when funding turns strongly positive (crowded longs).",
             "Funding (annualised, mean over the bar) is below the low level and the close is above the long average.", "Funding is above the high level.", "Stop 10% below the entry fill.",
             {"low": 0.0, "high": 30.0, "trend": 50}, {"low": [-10.0, -5.0, 0.0, 5.0, 10.0]}, _fund_build,
             lambda d, p: [_cond(f"Funding below {p['low']}% a year", None if np.isnan(_funding_series(d, p).iloc[-1]) else _funding_series(d, p).iloc[-1] < p["low"], f"funding {_val(_funding_series(d, p).iloc[-1])}% a year"),
                           _cond(f"Close above {p['trend']}-bar average", None if np.isnan(sma(d['c'], p['trend']).iloc[-1]) else d["c"].iloc[-1] > sma(d["c"], p["trend"]).iloc[-1], f"close {_val(d['c'].iloc[-1])} vs {_val(sma(d['c'], p['trend']).iloc[-1])}")],
             stop_pct=10.0, requires_funding=True, notes=["Needs Hyperliquid funding history, which starts in 2023, so it is tested on a short window."]))



# --- candidates added after the first round of research (see IMPROVEMENT_LOG.md) -------------------------------------------------------------
def _supertrend(d: pd.DataFrame, n: int, mult: float) -> pd.Series:
    """Classic Supertrend: ATR bands that only move in the trend's favour; +1 while the close is above the lower band, -1 below the upper band."""
    a, hl2 = atr(d, n).to_numpy(), ((d["h"] + d["l"]) / 2).to_numpy()
    c = d["c"].to_numpy()
    up, dn = hl2 + mult * a, hl2 - mult * a
    fu, fl, tr = np.full(len(c), np.nan), np.full(len(c), np.nan), np.zeros(len(c))
    for i in range(len(c)):
        if np.isnan(up[i]):
            continue
        if i == 0 or np.isnan(fu[i - 1]):
            fu[i], fl[i], tr[i] = up[i], dn[i], 1.0
            continue
        fu[i] = up[i] if (up[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = dn[i] if (dn[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        tr[i] = 1.0 if c[i] > fu[i - 1] else (-1.0 if c[i] < fl[i - 1] else tr[i - 1])
    return pd.Series(np.where(np.isnan(fu), 0.0, tr), index=d.index)


reg(Strategy("supertrend", "Supertrend", "Trend", "Follows a trailing band built from the average range; flips when the price closes through the band.", "Close breaks above the trailing upper ATR band.",
             "Close breaks below the trailing lower ATR band.", "No fixed stop; the trailing band is the stop.", {"n": 10, "mult": 3.0}, {"mult": [2.0, 2.5, 3.0, 3.5, 4.0]},
             lambda d, p: _supertrend(d, p["n"], p["mult"]),
             lambda d, p: [_cond("Supertrend is up (price above the trailing band)", bool(_supertrend(d, p["n"], p["mult"]).iloc[-1] > 0), f"state {'up' if _supertrend(d, p['n'], p['mult']).iloc[-1] > 0 else 'down'}")], symmetric=True))


def _chandelier(d, p):
    hi = d["h"].shift(1).rolling(p["entry"]).max()
    stop = d["h"].rolling(22).max() - p["mult"] * atr(d, 22)
    return hold(d["c"] > hi, d["c"] < stop)


reg(Strategy("chandelier_breakout", "Breakout with a trailing stop", "Breakout", "Buy a new high, then trail a stop three average-ranges below the recent high so winners run and losers are cut.",
             "Close is above the highest high of the previous N bars.", "Close falls below the 22-bar high minus K times the 22-bar average true range.", "The trailing exit is the stop.", {"entry": 55, "mult": 3.0}, {"mult": [2.0, 2.5, 3.0, 4.0, 5.0]}, _chandelier,
             lambda d, p: [_cond(f"Close above the {p['entry']}-bar high (entry)", None if np.isnan(d["h"].shift(1).rolling(p["entry"]).max().iloc[-1]) else d["c"].iloc[-1] > d["h"].shift(1).rolling(p["entry"]).max().iloc[-1], f"close {_val(d['c'].iloc[-1])}"),
                           _cond("Close below the trailing stop (exit)", None if np.isnan(atr(d, 22).iloc[-1]) else d["c"].iloc[-1] < d["h"].rolling(22).max().iloc[-1] - p["mult"] * atr(d, 22).iloc[-1], f"stop {_val(d['h'].rolling(22).max().iloc[-1] - p['mult'] * atr(d, 22).iloc[-1])}")]))


def _band(d, p):
    m = sma(d["c"], p["n"])
    return hold(d["c"] > m * (1 + p["b"]), d["c"] < m * (1 - p["b"]))


reg(Strategy("sma_band", "Long average with a buffer", "Trend", "Like 'price above the long average' but needs a clear move through a buffer zone, which cuts false signals when the price hugs the average.",
             "Close is more than B% above the N-bar average.", "Close is more than B% below the N-bar average.", "No fixed stop; the exit rule is the stop.", {"n": 200, "b": 0.03}, {"b": [0.0, 0.01, 0.02, 0.03, 0.05]}, _band,
             lambda d, p: [_cond(f"Close more than {p['b'] * 100:.0f}% above the {p['n']}-bar average", None if np.isnan(sma(d['c'], p['n']).iloc[-1]) else d["c"].iloc[-1] > sma(d["c"], p["n"]).iloc[-1] * (1 + p["b"]), f"close {_val(d['c'].iloc[-1])} vs average {_val(sma(d['c'], p['n']).iloc[-1])}")]))
reg(Strategy("rsi_trend", "RSI strength trend", "Momentum", "Hold while momentum is strong: enter when RSI(14) is high, leave when it fades.", "RSI(14) rises above the entry level.", "RSI(14) falls below the exit level.", "No fixed stop; the exit rule is the stop.",
             {"enter": 60, "exit": 45}, {"enter": [50, 55, 60, 65, 70]}, lambda d, p: hold(rsi(d["c"], 14) > p["enter"], rsi(d["c"], 14) < p["exit"]),
             lambda d, p: [_cond(f"RSI(14) above {p['enter']}", None if np.isnan(rsi(d['c'], 14).iloc[-1]) else rsi(d["c"], 14).iloc[-1] > p["enter"], f"RSI {_val(rsi(d['c'], 14).iloc[-1])}")]))


def _volf(d, p):
    r = d["c"].pct_change()
    v = r.rolling(30).std()
    med = v.rolling(365, min_periods=200).median()
    return ((d["c"] > sma(d["c"], p["n"])) & (v < med * p["k"])).astype(float)


reg(Strategy("vol_filtered_trend", "Trend only in calm markets", "Volatility", "Holds the long-average trend only while recent volatility is not unusually high, to sidestep violent swings.", "Close above the N-bar average and 30-bar volatility below K times its one-year median.",
             "Either condition stops being true.", "No fixed stop; the exit rule is the stop.", {"n": 100, "k": 1.2}, {"k": [0.8, 1.0, 1.2, 1.5, 2.0]}, _volf,
             lambda d, p: [_cond(f"Close above {p['n']}-bar average", None if np.isnan(sma(d['c'], p['n']).iloc[-1]) else d["c"].iloc[-1] > sma(d["c"], p["n"]).iloc[-1], f"close {_val(d['c'].iloc[-1])}"),
                           _cond(f"30-bar volatility below {p['k']}x its one-year median", None if np.isnan(d["c"].pct_change().rolling(30).std().rolling(365, min_periods=200).median().iloc[-1]) else bool(d["c"].pct_change().rolling(30).std().iloc[-1] < d["c"].pct_change().rolling(30).std().rolling(365, min_periods=200).median().iloc[-1] * p["k"]), "volatility vs its median")]))

def aroon(d: pd.DataFrame, n: int) -> tuple[pd.Series, pd.Series]:
    """Aroon Up / Down (Tushar Chande, 1995): how recently the highest high and lowest low of the last n bars happened, 0 to 100 (100 = this very bar)."""
    up = d["h"].rolling(n + 1).apply(lambda x: 100.0 * int(np.argmax(x)) / n, raw=True)          # position of the highest high inside the window (n = newest bar)
    dn = d["l"].rolling(n + 1).apply(lambda x: 100.0 * int(np.argmin(x)) / n, raw=True)
    return up, dn


def _aroon_build(d, p):
    up, dn = aroon(d, p["n"])
    return hold((up > 70) & (dn < 30), up < 50)


def _aroon_conds(d, p):
    up, dn = aroon(d, p["n"])
    u, w = up.iloc[-1], dn.iloc[-1]
    return [_cond("Aroon Up above 70 and Aroon Down below 30 (entry)", None if np.isnan(u) or np.isnan(w) else bool(u > 70 and w < 30), f"up {_val(u)}, down {_val(w)}"),
            _cond("Aroon Up below 50 (exit)", None if np.isnan(u) else bool(u < 50), f"up {_val(u)}")]


reg(Strategy("aroon_trend", "Aroon trend", "Trend", "Holds BTC while a fresh high is recent and a fresh low is old: the Aroon indicator's reading of a young uptrend.",
             "Aroon Up is above 70 and Aroon Down is below 30 (the highest high of the last N bars is recent, the lowest low is old).", "Aroon Up falls below 50 (the last high is getting old).",
             "No fixed stop; the exit rule is the stop.", {"n": 25}, {"n": [14, 20, 25, 35, 50]}, _aroon_build, _aroon_conds))


def dmi(d: pd.DataFrame, n: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Welles Wilder's Directional Movement Index (1978): (ADX, +DI, -DI). +DI / -DI measure upward / downward pressure; ADX measures how strong the trend is, whichever way it points."""
    up, down = d["h"].diff(), -d["l"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=d.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=d.index)
    pc = d["c"].shift(1)
    tr = pd.concat([d["h"] - d["l"], (d["h"] - pc).abs(), (d["l"] - pc).abs()], axis=1).max(axis=1)
    sm = lambda x: x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()          # Wilder's smoothing
    atr_ = sm(tr)
    pdi, mdi = 100 * sm(plus_dm) / atr_, 100 * sm(minus_dm) / atr_
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return sm(dx), pdi, mdi


def _adx_build(d, p):
    adx_, pdi, mdi = dmi(d, p["n"])
    return hold((adx_ > p["level"]) & (pdi > mdi), pdi < mdi)


def _adx_conds(d, p):
    adx_, pdi, mdi = dmi(d, p["n"])
    a, u, w = adx_.iloc[-1], pdi.iloc[-1], mdi.iloc[-1]
    bad = np.isnan(a) or np.isnan(u) or np.isnan(w)
    return [_cond(f"ADX above {p['level']} and +DI above -DI (entry)", None if bad else bool(a > p["level"] and u > w), f"ADX {_val(a)}, +DI {_val(u)}, -DI {_val(w)}"),
            _cond("+DI below -DI (exit)", None if bad else bool(u < w), f"+DI {_val(u)} vs -DI {_val(w)}")]


reg(Strategy("adx_trend", "ADX trend (Wilder)", "Trend", "Holds BTC only when the trend is strong (ADX above 25) and pointing up (+DI above -DI): Wilder's Directional Movement system.",
             "ADX is above 25 and +DI is above -DI.", "+DI falls below -DI (sellers are in charge).", "No fixed stop; the exit rule is the stop.", {"n": 14, "level": 25}, {"n": [10, 14, 20, 28, 40]}, _adx_build, _adx_conds))


def psar(d: pd.DataFrame, step: float, max_af: float) -> pd.Series:
    """Welles Wilder's Parabolic SAR (1978): a stop-and-reverse level that trails the trend and accelerates toward price. Each value uses only bars up to and including that bar."""
    h, l, c = d["h"].to_numpy(float), d["l"].to_numpy(float), d["c"].to_numpy(float)
    n = len(c)
    sar = np.full(n, np.nan)
    if n < 3:
        return pd.Series(sar, index=d.index)
    up = c[1] >= c[0]
    sar[0] = l[0] if up else h[0]
    ep = h[0] if up else l[0]
    af = step
    for i in range(1, n):
        s_ = sar[i - 1] + af * (ep - sar[i - 1])
        if up:
            s_ = min(s_, l[i - 1], l[i - 2] if i >= 2 else l[i - 1])         # never above the last two lows
            if l[i] < s_:
                up, s_, ep, af = False, ep, l[i], step                       # price broke the SAR: reverse, SAR jumps to the old extreme
            elif h[i] > ep:
                ep, af = h[i], min(af + step, max_af)
        else:
            s_ = max(s_, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])         # never below the last two highs
            if h[i] > s_:
                up, s_, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(af + step, max_af)
        sar[i] = s_
    return pd.Series(sar, index=d.index)


def _psar_build(d, p):
    sar = psar(d, p["step"], p["max_af"])
    return hold(d["c"] > sar, d["c"] < sar)


def _psar_conds(d, p):
    sar = psar(d, p["step"], p["max_af"]).iloc[-1]
    c = d["c"].iloc[-1]
    return [_cond("Close above the Parabolic SAR (entry)", None if np.isnan(sar) else bool(c > sar), f"close {_val(c)} vs SAR {_val(sar)}"),
            _cond("Close below the Parabolic SAR (exit)", None if np.isnan(sar) else bool(c < sar), f"close {_val(c)} vs SAR {_val(sar)}")]


reg(Strategy("psar_trend", "Parabolic SAR (Wilder)", "Trend", "Holds BTC while the price is above Wilder's trailing stop-and-reverse level, which accelerates toward price as the trend ages.",
             "Close is above the Parabolic SAR (step 0.02, maximum 0.2).", "Close falls below the Parabolic SAR.", "The SAR is itself a trailing stop; there is no other stop.", {"step": 0.02, "max_af": 0.2},
             {"step": [0.01, 0.015, 0.02, 0.03, 0.04]}, _psar_build, _psar_conds))


def ichimoku_cloud(d: pd.DataFrame, tenkan: int, kijun: int, senkou: int) -> tuple[pd.Series, pd.Series]:
    """Ichimoku cloud edges (Hosoda): span A = mean of the conversion and base lines, span B = midpoint of the `senkou`-bar range, both drawn `kijun` bars into the future.
    Shifting forward means the cloud shown at bar i was computed from bars up to i - kijun, so it never uses later data. Returns (upper edge, lower edge)."""
    mid = lambda n: (d["h"].rolling(n, min_periods=n).max() + d["l"].rolling(n, min_periods=n).min()) / 2
    a = ((mid(tenkan) + mid(kijun)) / 2).shift(kijun)
    b = mid(senkou).shift(kijun)
    return pd.concat([a, b], axis=1).max(axis=1, skipna=False), pd.concat([a, b], axis=1).min(axis=1, skipna=False)


def _ichi_build(d, p):
    top, bot = ichimoku_cloud(d, p["tenkan"], p["kijun"], p["senkou"])
    return hold(d["c"] > top, d["c"] < bot)


def _ichi_conds(d, p):
    top, bot = ichimoku_cloud(d, p["tenkan"], p["kijun"], p["senkou"])
    t, b_, c = top.iloc[-1], bot.iloc[-1], d["c"].iloc[-1]
    bad = bool(np.isnan(t) or np.isnan(b_))
    return [_cond("Close above the top of the Ichimoku cloud (entry)", None if bad else bool(c > t), f"close {_val(c)} vs cloud top {_val(t)}"),
            _cond("Close below the bottom of the cloud (exit)", None if bad else bool(c < b_), f"close {_val(c)} vs cloud bottom {_val(b_)}")]


reg(Strategy("ichimoku_cloud", "Ichimoku cloud (9, 26, 52)", "Trend", "Holds BTC while the price is above Hosoda's Ichimoku cloud, and steps aside once it falls below the cloud. Inside the cloud it keeps whatever position it had.",
             "Close is above both cloud edges (cloud built from 9, 26 and 52-bar ranges and drawn 26 bars ahead).", "Close falls below both cloud edges.", "The cloud edge is the stop; there is no other stop.",
             {"tenkan": 9, "kijun": 26, "senkou": 52}, {"kijun": [20, 23, 26, 30, 34]}, _ichi_build, _ichi_conds))


def tsmom(c: pd.Series, lookback: int, skip: int) -> pd.Series:
    """Time-series momentum "12 minus 1" (Moskowitz, Ooi and Pedersen): the return from `lookback` bars ago to `skip` bars ago. The recent `skip` bars are left out on purpose."""
    return c.shift(skip) / c.shift(lookback) - 1


def _tsmom_build(d, p):
    m = tsmom(d["c"], p["lookback"], p["skip"])
    return hold(m > 0, m <= 0)


def _tsmom_conds(d, p):
    m = tsmom(d["c"], p["lookback"], p["skip"]).iloc[-1]
    bad = bool(np.isnan(m))
    return [_cond(f"Return from {p['lookback']} to {p['skip']} bars ago is positive (entry)", None if bad else bool(m > 0), f"return {_val(m * 100)}%"),
            _cond("That return is zero or negative (exit)", None if bad else bool(m <= 0), f"return {_val(m * 100)}%")]


reg(Strategy("tsmom_12_1", "Time-series momentum (12 minus 1)", "Momentum", "Holds BTC while its return over the past year, leaving out the most recent month, is positive: the classic 12-minus-1 momentum measure.",
             "The return from 365 bars ago to 30 bars ago is above zero.", "That return is zero or below.", "No fixed stop; the exit rule is the stop.", {"lookback": 365, "skip": 30},
             {"lookback": [240, 300, 365, 450, 540]}, _tsmom_build, _tsmom_conds))


def keltner(d: pd.DataFrame, n: int, atr_n: int, k: float) -> tuple[pd.Series, pd.Series]:
    """Keltner channel (Chester Keltner, modern form): an EMA of the close and the same line plus `k` times the average true range. Returns (middle, upper); each value uses bars up to that bar."""
    mid = ema(d["c"], n)
    return mid, mid + k * atr(d, atr_n)


def _keltner_build(d, p):
    mid, up = keltner(d, p["n"], p["atr_n"], p["k"])
    return hold(d["c"] > up, d["c"] < mid)


def _keltner_conds(d, p):
    mid, up = keltner(d, p["n"], p["atr_n"], p["k"])
    m, u, c = mid.iloc[-1], up.iloc[-1], d["c"].iloc[-1]
    bad = bool(np.isnan(m) or np.isnan(u))
    return [_cond(f"Close above the Keltner upper band (EMA {p['n']} + {p['k']:g} x ATR {p['atr_n']}) (entry)", None if bad else bool(c > u), f"close {_val(c)} vs upper {_val(u)}"),
            _cond(f"Close below the EMA {p['n']} (exit)", None if bad else bool(c < m), f"close {_val(c)} vs EMA {_val(m)}")]


reg(Strategy("keltner_breakout", "Keltner channel breakout", "Volatility", "Buys a strong close above a channel drawn around a 20-bar average (2 average true ranges up) and steps aside when the price falls back to that average. Close kin of the volatility channel rule, with a 10-bar range.",
             "Close is above EMA(20) plus 2 x ATR(10).", "Close falls below EMA(20).", "No fixed stop; the exit rule is the stop.", {"n": 20, "atr_n": 10, "k": 2.0}, {"k": [1.0, 1.5, 2.0, 2.5, 3.0]}, _keltner_build, _keltner_conds))


def vortex(d: pd.DataFrame, n: int) -> tuple[pd.Series, pd.Series]:
    """Vortex indicator (Botes and Siepman, 2010): VI+ = sum of |high - previous low| over n bars divided by the sum of true ranges, VI- = the same with |low - previous high|.
    Each value uses only bars up to and including that bar."""
    h, l, pc = d["h"], d["l"], d["c"].shift(1)
    vmp, vmm = (h - l.shift(1)).abs(), (l - h.shift(1)).abs()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1, skipna=False)
    s_tr = tr.rolling(n, min_periods=n).sum()
    return vmp.rolling(n, min_periods=n).sum() / s_tr, vmm.rolling(n, min_periods=n).sum() / s_tr


def _vortex_build(d, p):
    vp, vm = vortex(d, p["n"])
    return hold(vp > vm, vp <= vm)


def _vortex_conds(d, p):
    vp, vm = vortex(d, p["n"])
    a, b_ = vp.iloc[-1], vm.iloc[-1]
    bad = bool(np.isnan(a) or np.isnan(b_))
    return [_cond("VI+ above VI- (entry)", None if bad else bool(a > b_), f"VI+ {_val(a)} vs VI- {_val(b_)}"),
            _cond("VI+ at or below VI- (exit)", None if bad else bool(a <= b_), f"VI+ {_val(a)} vs VI- {_val(b_)}")]


reg(Strategy("vortex_cross", "Vortex indicator (14)", "Trend", "Holds BTC while the upward vortex line is above the downward one: it compares how far each bar reaches above the last bar's low against how far it reaches below the last bar's high.",
             "VI+ is above VI- (14 bars).", "VI+ drops to VI- or below.", "No fixed stop; the exit rule is the stop.", {"n": 14}, {"n": [10, 14, 20, 28, 40]}, _vortex_build, _vortex_conds))


def stoch_k(d: pd.DataFrame, n: int, smooth: int) -> pd.Series:
    """Slow stochastic %K (Lane): where the close sits inside the last `n` bars' high-low range (0 = at the low, 100 = at the high), averaged over `smooth` bars.
    Each value uses only bars up to and including that bar."""
    lo, hi = d["l"].rolling(n, min_periods=n).min(), d["h"].rolling(n, min_periods=n).max()
    raw = 100 * (d["c"] - lo) / (hi - lo).replace(0, np.nan)
    return raw.rolling(smooth, min_periods=smooth).mean()


def _stoch_build(d, p):
    k = stoch_k(d, p["n"], p["smooth"])
    cross_up = (k.shift(1) < p["low"]) & (k >= p["low"])                       # %K crosses up through the low level
    return hold(cross_up & (d["c"] > sma(d["c"], p["trend"])), k > p["high"])


def _stoch_conds(d, p):
    k = stoch_k(d, p["n"], p["smooth"])
    trend = sma(d["c"], p["trend"]).iloc[-1]
    k1, k0, c = k.iloc[-2] if len(k) > 1 else np.nan, k.iloc[-1], d["c"].iloc[-1]
    bad = bool(np.isnan(k1) or np.isnan(k0) or np.isnan(trend))
    return [_cond(f"%K crosses up through {p['low']} while the close is above the {p['trend']}-bar average (entry)", None if bad else bool(k1 < p["low"] <= k0 and c > trend), f"%K {_val(k1)} to {_val(k0)}, close {_val(c)} vs average {_val(trend)}"),
            _cond(f"%K above {p['high']} (exit)", None if np.isnan(k0) else bool(k0 > p["high"]), f"%K {_val(k0)}")]


reg(Strategy("stoch_uptrend", "Stochastic pullback in an uptrend", "Mean reversion", "Buys a dip inside an uptrend: when the stochastic oscillator turns up from oversold (crosses up through 20) while the price is above its 200-bar average, and sells once it is stretched (above 80).",
             "%K (14, smoothed over 3) crosses up through 20 while the close is above the 200-bar average.", "%K rises above 80.", "No fixed stop; the exit rule is the stop.", {"n": 14, "smooth": 3, "low": 20, "high": 80, "trend": 200},
             {"low": [10, 15, 20, 25, 30]}, _stoch_build, _stoch_conds))


def mfi(d: pd.DataFrame, n: int) -> pd.Series:
    """Money Flow Index (Quong and Soudack): a volume-weighted RSI. Typical price = (high + low + close) / 3; money flow = typical price x volume, counted as positive when the typical price
    rose from the previous bar and negative when it fell; MFI = 100 x positive / (positive + negative) over `n` bars. Each value uses only bars up to and including that bar."""
    tp = (d["h"] + d["l"] + d["c"]) / 3
    flow = tp * d["v"]
    up, dn = flow.where(tp > tp.shift(1), 0.0), flow.where(tp < tp.shift(1), 0.0)
    valid = tp.shift(1).notna()                                                        # the first bar has no previous bar to compare with
    up, dn = up.where(valid), dn.where(valid)
    pos, neg = up.rolling(n, min_periods=n).sum(), dn.rolling(n, min_periods=n).sum()
    return 100 * pos / (pos + neg).replace(0, np.nan)


def _mfi_build(d, p):
    m = mfi(d, p["n"])
    return hold(m < p["low"], m > p["high"])


def _mfi_conds(d, p):
    m = mfi(d, p["n"]).iloc[-1]
    bad = bool(np.isnan(m))
    return [_cond(f"Money Flow Index below {p['low']} (entry)", None if bad else bool(m < p["low"]), f"MFI {_val(m)}"),
            _cond(f"Money Flow Index above {p['high']} (exit)", None if bad else bool(m > p["high"]), f"MFI {_val(m)}")]


reg(Strategy("mfi_reversion", "Money Flow Index reversion", "Mean reversion", "Buys when volume-weighted selling looks exhausted (Money Flow Index below 20) and sells once buying has recovered (above 70).",
             "The 14-bar Money Flow Index falls below 20.", "The Money Flow Index rises above 70.", "No fixed stop; the exit rule is the stop.", {"n": 14, "low": 20, "high": 70}, {"low": [10, 15, 20, 25, 30]}, _mfi_build, _mfi_conds))


def cci(d: pd.DataFrame, n: int) -> pd.Series:
    """Commodity Channel Index (Lambert, 1980): how far the typical price (high + low + close) / 3 sits from its n-bar average, in units of 0.015 x the mean absolute deviation.
    Each value uses only bars up to and including that bar."""
    tp = (d["h"] + d["l"] + d["c"]) / 3
    ma = tp.rolling(n, min_periods=n).mean()
    mad = tp.rolling(n, min_periods=n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - ma) / (0.015 * mad.replace(0, np.nan))


def _cci_build(d, p):
    x = cci(d, p["n"])
    return hold(x > p["high"], x < p["low"])


def _cci_conds(d, p):
    x = cci(d, p["n"]).iloc[-1]
    bad = bool(np.isnan(x))
    return [_cond(f"CCI above +{p['high']} (entry)", None if bad else bool(x > p["high"]), f"CCI {_val(x)}"),
            _cond(f"CCI below {p['low']} (exit)", None if bad else bool(x < p["low"]), f"CCI {_val(x)}")]


reg(Strategy("cci_trend", "Commodity Channel Index trend", "Momentum", "Holds BTC after the Commodity Channel Index shows an unusually strong push above its average (above +100) and steps aside once it drops back below zero.",
             "The 20-bar CCI rises above +100.", "The CCI falls below 0.", "No fixed stop; the exit rule is the stop.", {"n": 20, "high": 100, "low": 0}, {"high": [60, 80, 100, 120, 150]}, _cci_build, _cci_conds))


def obv(d: pd.DataFrame) -> pd.Series:
    """On-balance volume (Granville): a running total that adds a bar's volume when the close rose and subtracts it when the close fell. The first bar has no previous close and adds nothing.
    Each value uses only bars up to and including that bar."""
    return (np.sign(d["c"].diff()).fillna(0.0) * d["v"]).cumsum()


def _obv_ok(d, p):
    o = obv(d)
    return (o > sma(o, p["n_obv"])) & (d["c"] > sma(d["c"], p["n_price"]))


def _obv_build(d, p):
    ok = _obv_ok(d, p)
    return hold(ok, ~ok)


def _obv_conds(d, p):
    o, c = obv(d), d["c"]
    so, sp = sma(o, p["n_obv"]).iloc[-1], sma(c, p["n_price"]).iloc[-1]
    bad = bool(np.isnan(so) or np.isnan(sp))
    return [_cond(f"On-balance volume above its {p['n_obv']}-bar average (entry, with the next line)", None if bad else bool(o.iloc[-1] > so), f"OBV {_val(o.iloc[-1])} vs average {_val(so)}"),
            _cond(f"Close above its {p['n_price']}-bar average (entry; if either line fails, exit)", None if bad else bool(c.iloc[-1] > sp), f"close {_val(c.iloc[-1])} vs average {_val(sp)}")]


reg(Strategy("obv_trend", "On-balance volume trend", "Trend", "Holds BTC while volume is flowing in with the price: on-balance volume is above its own 50-bar average and the close is above its 50-bar average. Steps aside as soon as either fails.",
             "On-balance volume is above its 50-bar average AND the close is above its 50-bar average.", "Either of those two stops being true.", "No fixed stop; the exit rule is the stop.", {"n_obv": 50, "n_price": 50},
             {"n_obv": [30, 40, 50, 70, 100]}, _obv_build, _obv_conds))


DEFAULT_FIVE = ["price_above_sma", "donchian_breakout", "rsi2_trend", "momentum_roc", "atr_channel"]


# What the research found, dated. These are results on past data, not forecasts; they are re-checked when the library changes.
FINDINGS = {
    "as_of": "2026-11-08",
    "data": "Coinbase BTC-USD daily bars from 2015, hourly and 4-hour bars from late 2023, and Hyperliquid funding from 2023. Fees 5 bps and slippage 5 bps per side.",
    "points": [
        "Daily spot, 2015 to 2026: simply holding returned about +27,000% with an 84% worst drop. Counting the whole library of rules, none cleared the bar for moderate evidence: with 20 or so rules to pick from, the best ones can look good by luck.",
        "What the better daily trend rules did offer was a smaller worst drop (about 35% to 45% for the best ones, against 84% for holding) in exchange for giving up some return. They did not beat holding on return out of sample.",
        "Perpetuals (2023 to 2026) and 4-hour or 1-hour spot: most rules lost money after fees, slippage and funding. Faster timeframes trade more often, so costs eat the edge.",
        "Five more candidates were added and tested (Supertrend, a breakout with a trailing stop, a long average with a buffer, an RSI strength trend, a trend filtered by calm volatility). None became a standout, and they are kept as research candidates, not recommendations.",
    ],
}
