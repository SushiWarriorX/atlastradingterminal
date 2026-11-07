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

DEFAULT_FIVE = ["price_above_sma", "donchian_breakout", "rsi2_trend", "momentum_roc", "atr_channel"]
