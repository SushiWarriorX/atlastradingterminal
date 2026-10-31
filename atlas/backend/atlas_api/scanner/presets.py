"""Preset scans. Thresholds are explicit, editable defaults: not tuned or backtested."""
from __future__ import annotations

from .rules import Filter, ScanSpec

LIQ = Filter(field="dollar_volume_avg20", op=">=", value=20_000_000)
F = Filter


def _p(id_, name, desc, filters, weights, **kw):
    return id_, {"id": id_, "name": name, "description": desc,
                 "spec": ScanSpec(name=name, filters=[LIQ, *filters], score_weights=weights, **kw)}


PRESETS: dict[str, dict] = dict([
    _p("momentum_breakout", "Momentum Breakout", "Close above the prior 20-day high on RVOL >= 1.5, above SMA50, outperforming the benchmark over 1m, liquid.",
       [F(field="breakout_20", op="==", value=True), F(field="rvol", op=">=", value=1.5), F(field="above_sma50", op="==", value=True),
        F(field="rs_21d", op=">", value=0)], {"rvol": 1, "rs_21d": 1, "ret_21d": 0.5, "dist_52w_high_pct": 0.5}),
    _p("pullback_uptrend", "Pullback in Uptrend", "Bullish MA alignment, down over 5 days, within 3% of SMA20, 3-day volume drying up.",
       [F(field="trend", op="==", value="bullish"), F(field="ret_5d", op="<", value=0), F(field="dist_sma20_pct", op="between", value=[-3, 3]),
        F(field="vol_dryup_3d", op="<", value=1.0)], {"rs_63d": 1, "ret_63d": 0.5, "rsi14": -0.5}),
    _p("unusual_volume", "Unusual Volume", "RVOL >= 2.5 versus the prior 20-day average.",
       [F(field="rvol", op=">=", value=2.5)], {"rvol": 1, "change_pct": 0.25}),
    _p("rs_leaders", "Relative Strength Leaders", "Outperforming the benchmark over 1m, 3m and 6m, above SMA50 and SMA200.",
       [F(field="rs_21d", op=">", value=0), F(field="rs_63d", op=">", value=0), F(field="rs_126d", op=">", value=0),
        F(field="above_sma50", op="==", value=True), F(field="above_sma200", op="==", value=True)], {"rs_21d": 1, "rs_63d": 1, "rs_126d": 1}),
    _p("potential_reversal", "Potential Reversal (setup, not confirmation)", "Oversold (RSI <= 30) and >= 20% below the 52w high, with 3+ consecutive down closes. Confirmation (e.g. a close above the prior day high) is NOT required: treat as a watch list.",
       [F(field="rsi14", op="<=", value=30), F(field="dist_52w_high_pct", op="<=", value=-20), F(field="consec_down", op=">=", value=3)],
       {"rsi14": -1, "consec_down": 0.5}),
    _p("volatility_compression", "Volatility Compression", "Bollinger width in the lowest 20th percentile of its last 120 days and ATR below its level 20 bars ago.",
       [F(field="bb_width_pctile", op="<=", value=20), F(field="atr_ratio_20", op="<", value=1.0)], {"bb_width_pctile": -1, "atr_ratio_20": -0.5}),
    _p("bearish_breakdown", "Bearish Breakdown", "Close below the prior 20-day low on RVOL >= 1.5 and below SMA50.",
       [F(field="breakdown_20", op="==", value=True), F(field="rvol", op=">=", value=1.5), F(field="above_sma50", op="==", value=False)],
       {"rvol": 1, "rs_21d": -1, "ret_21d": -0.5}),
])
UNAVAILABLE_PRESETS = {
    "news_catalyst": "Headlines exist (NEWS) but are not mapped to a catalyst flag: that would need a rule for what counts as a catalyst, which has not been designed.",
    "earnings_momentum": "Needs verified earnings data (roadmap Phase 4/5).",
    "sector_rotation": "Needs sector classification for a broad universe; only the core seed list has sectors.",
}
ALIASES = {"BREAKOUT": "momentum_breakout", "PULLBACK": "pullback_uptrend", "VOLUME": "unusual_volume", "RVOL": "unusual_volume",
           "RS": "rs_leaders", "LEADERS": "rs_leaders", "REVERSAL": "potential_reversal", "COMPRESSION": "volatility_compression",
           "SQUEEZE": "volatility_compression", "BREAKDOWN": "bearish_breakdown"}
