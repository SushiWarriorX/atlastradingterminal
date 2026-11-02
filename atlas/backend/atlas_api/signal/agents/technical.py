"""Technical Analysis agent: reads backend-calculated price, trend, momentum, volume, volatility and levels across timeframes (the ATLAS MTF engine and
indicator library) and states the setup, the conflicts, and what would invalidate it. Every conclusion names its timeframe. No targets, no forecasts."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import numpy as np

from ... import indicators as ind
from ...models import Candle, ProviderUnavailable
from ...mtf_service import run_mtf
from .. import fmt
from ..assets import Asset
from ..models import Finding, Interpretation, Level, Missing, Point, Source
from .common import Ctx, iso, mk_fact, provider_source, unavailable

TF_NAME = {"1w": "Weekly", "1d": "Daily", "4h": "4-hour", "1h": "1-hour", "15m": "15-minute"}
TF_SHORT = {"1w": "1W", "1d": "1D", "4h": "4H", "1h": "1H", "15m": "15m"}
TREND_WORD = {"bullish": "up", "bearish": "down", "mixed": "mixed"}
TREND_LONG = {"bullish": "Uptrend (price above its 50- and 200-bar averages)", "bearish": "Downtrend (price below its 50- and 200-bar averages)", "mixed": "Mixed (averages not aligned)"}
STANCE_RULE = "Transparent score from trend, structure, momentum, volume and relative strength across timeframes: 62.5 or higher reads supportive, 37.5 or lower cautious, otherwise mixed."
SOURCE_CAVEAT = "Describes current price action only. It is not a forecast, a price target or advice."


def benchmark_for(a: Asset):
    from .. import assets as A
    from ... import instruments as I
    if a.type == "crypto":
        return None if a.symbol == "BTC" else I.get("CRYPTO:COINBASE:BTC-USD:SPOT")
    return I.get("ETF:ARCA:SPY") if a.id != "ETF:ARCA:SPY" else None


def _ret(close: np.ndarray, n: int) -> float | None:
    return None if len(close) <= n or close[-1 - n] == 0 else float((close[-1] / close[-1 - n] - 1) * 100)


def _label_from_tilt(tilt: float | None, verdict: str) -> str:
    if tilt is None:
        return "insufficient"
    if verdict == "conflicting":
        return "mixed"
    return "supportive" if tilt >= 0.25 else "cautious" if tilt <= -0.25 else "mixed"


class TechnicalAgent:
    name = "technical"

    async def run(self, ctx: Ctx) -> Finding:
        a, inst = ctx.asset, ctx.asset.inst
        bench = benchmark_for(a)
        m, daily = await asyncio.gather(run_mtf(ctx.svc, inst, bench_inst=bench), ctx.svc.ohlcv(inst, "1d", 300), return_exceptions=True)
        if isinstance(daily, Exception):
            reason = f"{daily.provider}: {daily.message}" if isinstance(daily, ProviderUnavailable) else type(daily).__name__
            return unavailable("technical", f"Price history unavailable ({reason[:120]})", ctx.demo)
        if isinstance(m, Exception):
            return unavailable("technical", f"Multi-timeframe analysis failed ({type(m).__name__})", ctx.demo)
        candles: list[Candle] = daily.candles
        if len(candles) < 30:
            return unavailable("technical", f"Only {len(candles)} daily bars are available (30 needed).", ctx.demo, status="partial")
        close = np.array([c.close for c in candles])
        hi = np.array([c.high for c in candles])
        lo = np.array([c.low for c in candles])
        vol = np.array([c.volume for c in candles])
        px = float(close[-1])
        src = provider_source(daily.prov)
        asof = iso(daily.prov.event_time)
        S = src.name
        tfs = {t["interval"]: t for t in m["timeframes"] if t["available"]}
        d = tfs.get("1d")
        sc, al = m["score"], m["alignment"]

        facts = []

        def F(key, label, value, display, tf="1D", unit=None):
            facts.append(mk_fact(key, label, value, display, S, unit=unit, as_of=asof, timeframe=tf))
        r1, r5, r21, r63 = _ret(close, 1), _ret(close, 5), _ret(close, 21), _ret(close, 63)
        for key, label, v in (("ret_1d_pct", "Change, latest daily bar", r1), ("ret_5d_pct", "Change, 5 daily bars", r5), ("ret_1m_pct", "Change, about 1 month", r21), ("ret_3m_pct", "Change, about 3 months", r63)):
            if v is not None:
                F(key, label, round(v, 2), fmt.pct(v, signed=True), unit="%")
        sma = {n: float(ind.sma(close, n)[-1]) if len(close) >= n and not np.isnan(ind.sma(close, n)[-1]) else None for n in (20, 50, 200)}
        for n in (50, 200):
            if sma[n]:
                dist = (px / sma[n] - 1) * 100
                F(f"sma{n}_dist_pct", f"Price vs {n}-day average", round(dist, 2), fmt.pct(dist, signed=True) + (" above" if dist >= 0 else " below"), unit="%")
        rsi = ind.rsi(close, 14)[-1]
        macd_h = ind.macd(close)[2][-1]
        atr = ind.atr(hi, lo, close, 14)[-1]
        rv = ind.rvol(vol, 20)[-1] if (vol > 0).any() else float("nan")
        rsi_v = None if np.isnan(rsi) else float(rsi)
        atr_pct = None if np.isnan(atr) else float(atr / px * 100)
        rv_v = None if np.isnan(rv) else float(rv)
        if rsi_v is not None:
            F("rsi14_1d", "RSI (14), daily", round(rsi_v, 1), f"{rsi_v:.0f}")
        if not np.isnan(macd_h):
            F("macd_hist_1d", "MACD histogram, daily", round(float(macd_h), 6), "positive" if macd_h > 0 else "negative" if macd_h < 0 else "flat")
        if atr_pct is not None:
            F("atr_pct_1d", "Typical daily range (ATR 14)", round(atr_pct, 2), fmt.pct(atr_pct, digits=1) + " of price", unit="%")
        if rv_v is not None:
            F("rvol_1d", "Volume vs 20-day average", round(rv_v, 2), fmt.times(rv_v, 1))
        if len(close) >= 100:
            h52, l52 = float(hi[-252:].max()), float(lo[-252:].min())
            F("dist_52w_high_pct", "Below 52-week high", round((px / h52 - 1) * 100, 2), fmt.pct((px / h52 - 1) * 100, signed=True), unit="%")
            F("dist_52w_low_pct", "Above 52-week low", round((px / l52 - 1) * 100, 2), fmt.pct((px / l52 - 1) * 100, signed=True), unit="%")
        for tf in ("1w", "1d", "4h", "1h", "15m"):
            if tf in tfs:
                t = tfs[tf]
                facts.append(mk_fact(f"trend_{tf}", f"Trend, {TF_NAME[tf].lower()}", t["trend"], TREND_LONG.get(t["trend"], t["trend"]), PROVIDER_FOR_TF(t, S),
                                     as_of=t["data"].get("event_time"), timeframe=TF_SHORT[tf]))
        if sc["score"] is not None:
            facts.append(mk_fact("mtf_score", "Multi-timeframe score (0-100, 50 = neutral)", sc["score"], f"{sc['score']:.0f} / 100", "ATLAS multi-timeframe model (calculated)", as_of=asof, timeframe="all"))
        rs = sc["factors"]["relative_strength"]["inputs"].get("63-obs excess return (pp)")
        if rs is not None:
            facts.append(mk_fact("rel_strength_63d_pp", f"Return vs {m['benchmark']}, 63 daily bars", round(rs, 2), fmt.num(rs, 1) + " pp", S, as_of=asof, timeframe="1D", unit="pp"))

        # levels: nearest support and resistance on the weekly, daily and hourly charts
        levels: list[Level] = []
        for tf in ("1w", "1d", "1h"):
            t = tfs.get(tf)
            if not t:
                continue
            for kind, key in (("support", "nearest_support"), ("resistance", "nearest_resistance")):
                p = t.get(key)
                if p:
                    levels.append(Level(id=f"{tf}-{kind}", kind=kind, price=float(p), display=fmt.price(p), timeframe=TF_SHORT[tf], distance_pct=round((p / t["last_close"] - 1) * 100, 2),
                                        derivation=f"Nearest {kind} on the {TF_NAME[tf].lower()} chart: confirmed swing points, prior-day range, or the 50/200-bar averages."))
        d_sup = next((l for l in levels if l.id == "1d-support"), None)
        d_res = next((l for l in levels if l.id == "1d-resistance"), None)

        # interpretations: each tied to facts and a timeframe
        interp: list[Interpretation] = []
        trend_keys = [f"trend_{tf}" for tf in ("1w", "1d", "4h", "1h", "15m") if tf in tfs]
        interp.append(Interpretation(text=al["text"], based_on=trend_keys, caveat=SOURCE_CAVEAT, timeframe="1W, 1D, 1H"))
        if rsi_v is not None:
            zone = ("in the overbought zone (70 or higher). Strong trends can stay overbought, but it often marks stretched short-term conditions" if rsi_v >= 70 else
                    "in the oversold zone (30 or lower). Weak trends can stay oversold, but it often marks stretched selling" if rsi_v <= 30 else
                    "above the neutral 50 line, which fits positive momentum" if rsi_v > 55 else "below the neutral 50 line, which fits soft momentum" if rsi_v < 45 else "near the neutral 50 line")
            mh = "" if np.isnan(macd_h) else (" The MACD histogram is positive (short-term momentum above its trend)." if macd_h > 0 else " The MACD histogram is negative (short-term momentum below its trend).")
            interp.append(Interpretation(text=f"Daily RSI is {rsi_v:.0f}, {zone}.{mh}", based_on=["rsi14_1d", "macd_hist_1d"], timeframe="1D"))
        if atr_pct is not None:
            interp.append(Interpretation(text=f"A typical daily move is about {atr_pct:.1f}% of price, so a move of that size is normal for this asset.", based_on=["atr_pct_1d"], timeframe="1D"))
        if rv_v is not None and rv_v >= 1.5:
            interp.append(Interpretation(text=f"Volume is {rv_v:.1f}× its 20-day average, so the latest move is happening on unusually heavy trading.", based_on=["rvol_1d"], timeframe="1D"))
        conflicts = _conflicts(tfs, d, rsi_v, macd_h)
        for c in conflicts:
            interp.append(Interpretation(text=c, based_on=trend_keys + ["rsi14_1d"], timeframe="1D"))
        invalid = None
        if d and d["trend"] == "bullish" and d_sup:
            invalid = f"A daily close below {d_sup.display} (the nearest daily support) would weaken this setup."
        elif d and d["trend"] == "bearish" and d_res:
            invalid = f"A daily close above {d_res.display} (the nearest daily resistance) would weaken this downtrend."
        if invalid:
            interp.append(Interpretation(text=invalid, based_on=["trend_1d", "1d-support" if "below" in invalid else "1d-resistance"], caveat="A reference level from the chart's own history, not a stop-loss or price target.", timeframe="1D"))

        stance = _label_from_tilt(sc["tilt"], al["verdict"])
        takeaway = _takeaway(tfs, d_sup, d_res, invalid, al)
        pts = _points(a, tfs, d, closes=close, highs=hi, lows=lo, r1=r1, r21=r21, rsi_v=rsi_v, macd_h=None if np.isnan(macd_h) else float(macd_h), atr_pct=atr_pct, rv_v=rv_v,
                      sma=sma, px=px, d_sup=d_sup, d_res=d_res, al=al, invalid=invalid, conflicts=conflicts)
        missing = [Missing(what=f"{TF_NAME[t['interval']]} chart", why=t.get("reason", "not enough data")[:120]) for t in m["timeframes"] if not t["available"]]
        if sc["unavailable"]:
            missing.append(Missing(what="Score inputs: " + ", ".join(sc["unavailable"]), why="not enough data for those factors; the score uses the rest (weights re-normalised)"))
        sources = [src]
        if bench is not None and rs is not None:
            sources.append(Source(name=f"{bench.symbol} daily bars (benchmark)", kind="data", note="used for relative strength"))
        limits = [SOURCE_CAVEAT, "Levels are computed from past swings and averages; price can pass through any level."]
        if daily.prov.provider == "yahoo":
            limits.append("Yahoo Finance data is unofficial and about 15 minutes delayed; intraday timeframes use delayed bars.")
        return Finding(agent="technical", status="ok" if not missing else "partial", stance=stance, stance_rule=STANCE_RULE, takeaway=takeaway, facts=facts, interpretations=interp,
                       levels=levels, missing=missing, sources=sources, limitations=limits, points=pts, data_as_of=asof, demo=ctx.demo)


def PROVIDER_FOR_TF(t: dict, default: str) -> str:
    from .common import PROVIDER_LABEL
    return PROVIDER_LABEL.get(t["data"].get("provider"), default)


def _conflicts(tfs: dict, d: dict | None, rsi_v, macd_h) -> list[str]:
    out = []
    if d:
        if d["trend"] == "bullish" and ((rsi_v is not None and rsi_v < 45) or (not np.isnan(macd_h) and macd_h < 0)):
            out.append("Conflict: the daily trend is up, but daily momentum has cooled (RSI or MACD is weakening).")
        if d["trend"] == "bearish" and ((rsi_v is not None and rsi_v > 55) or (not np.isnan(macd_h) and macd_h > 0)):
            out.append("Conflict: the daily trend is down, but daily momentum is improving.")
        s = d["structure"]
        if s.get("event") and "CHoCH" in s["event"]:
            out.append(f"Conflict: the daily chart shows a change of character ({s['event']}), which goes against the prior swing structure.")
    w, h = tfs.get("1w"), tfs.get("1h")
    if w and d and w["trend"] != d["trend"] and "mixed" not in (w["trend"], d["trend"]):
        out.append(f"Conflict: the weekly trend is {TREND_WORD[w['trend']]} but the daily trend is {TREND_WORD[d['trend']]}.")
    if d and h and h["trend"] != d["trend"] and "mixed" not in (h["trend"], d["trend"]):
        out.append(f"Conflict: the 1-hour trend is {TREND_WORD[h['trend']]} while the daily trend is {TREND_WORD[d['trend']]}.")
    return out


def _takeaway(tfs: dict, sup: Level | None, res: Level | None, invalid: str | None, al: dict) -> str:
    hi = [(tf, tfs[tf]["trend"]) for tf in ("1w", "1d") if tf in tfs]
    if not hi:
        return "Not enough weekly or daily history to read the trend."
    if len(hi) == 2 and hi[0][1] == hi[1][1]:
        first = f"Weekly and daily trends are {TREND_WORD[hi[0][1]]}"
    elif len(hi) == 2:
        first = f"The weekly trend is {TREND_WORD[hi[0][1]]} and the daily is {TREND_WORD[hi[1][1]]}"
    else:
        first = f"The {TF_NAME[hi[0][0]].lower()} trend is {TREND_WORD[hi[0][1]]}"
    h = tfs.get("1h")
    if h:
        first += f"; the 1-hour is {TREND_WORD[h['trend']]}"
    tail = invalid or (f"Nearest daily support {sup.display}, resistance {res.display}." if sup and res else "")
    return (first + ". " + tail).strip()


def _points(a: Asset, tfs, d, *, closes, highs, lows, r1, r21, rsi_v, macd_h, atr_pct, rv_v, sma, px, d_sup, d_res, al, invalid, conflicts) -> list[Point]:
    P: list[Point] = []
    sym = a.symbol
    add = lambda kind, text, prio, keys, dk=None: P.append(Point(kind=kind, text=text, agent="technical", fact_keys=keys, priority=prio, dedupe_key=dk))
    if r1 is not None and atr_pct and abs(r1) >= 1.5 * atr_pct and abs(r1) >= 1.0:
        add("changed", f"{sym} moved {fmt.pct(r1, signed=True)} on the latest daily bar, larger than its typical daily range (about {atr_pct:.1f}%).", 72, ["ret_1d_pct", "atr_pct_1d"], "move-1d")
    if r21 is not None and abs(r21) >= 5:
        add("changed", f"{sym} is {'up' if r21 > 0 else 'down'} {fmt.pct(abs(r21))} over about a month (daily closes).", 55, ["ret_1m_pct"], "move-1m")
    if len(closes) > 21:
        if closes[-1] > highs[-21:-1].max():
            add("changed", f"{sym} closed above its 20-day high (daily).", 75, ["ret_1d_pct"], "breakout")
        elif closes[-1] < lows[-21:-1].min():
            add("changed", f"{sym} closed below its 20-day low (daily).", 75, ["ret_1d_pct"], "breakdown")
    ev = d["structure"].get("event") if d else None
    if ev:
        add("changed", f"Daily chart structure event: {ev}.", 60, ["trend_1d"], "structure-event")
    if d and d["trend"] == "bullish":
        add("supports", "The daily trend is up (price above its 50- and 200-day averages).", 80, ["trend_1d", "sma50_dist_pct", "sma200_dist_pct"], "trend-up")
    if al["verdict"].startswith("aligned bullish"):
        add("supports", "All available timeframes are in an uptrend.", 85, [f"trend_{tf}" for tf in tfs], "tf-aligned")
    if rsi_v is not None and macd_h is not None and 50 < rsi_v < 70 and macd_h > 0:
        add("supports", f"Daily momentum is positive without being stretched (RSI {rsi_v:.0f}, MACD above its signal).", 55, ["rsi14_1d", "macd_hist_1d"], "momentum-ok")
    if rv_v is not None and rv_v >= 1.5 and r1 is not None and r1 > 0:
        add("supports", f"The latest rise came on {rv_v:.1f}× average volume.", 50, ["rvol_1d"], "volume-confirm")
    if d and d["trend"] == "bearish":
        add("risk", "The daily trend is down (price below its 50- and 200-day averages).", 80, ["trend_1d"], "trend-down")
    if rsi_v is not None and rsi_v >= 70:
        add("risk", f"Daily RSI is {rsi_v:.0f} (overbought zone): moves can stall or reverse after stretched runs.", 70, ["rsi14_1d"], "overbought")
    if rsi_v is not None and rsi_v <= 30:
        add("risk", f"Daily RSI is {rsi_v:.0f} (oversold zone): selling is stretched but can continue.", 60, ["rsi14_1d"], "oversold")
    for c in conflicts[:2]:
        add("risk", c.replace("Conflict: ", "Mixed signals: "), 66, ["rsi14_1d", "trend_1d"], "conflict-" + c[10:30])
    if atr_pct is not None and atr_pct >= 5:
        add("risk", f"Large typical daily swings (about {atr_pct:.1f}% of price): expect big moves in both directions.", 52, ["atr_pct_1d"], "volatile")
    if d_sup and d_sup.distance_pct is not None and abs(d_sup.distance_pct) <= (atr_pct or 3):
        add("risk", f"Price is within about one typical daily move of daily support ({d_sup.display}).", 64, ["1d-support"], "near-support")
    if d_sup and d_res:
        add("watch", f"Daily support {d_sup.display} and resistance {d_res.display}.", 85, ["1d-support", "1d-resistance"], "levels")
    elif d_sup or d_res:
        l = d_sup or d_res
        add("watch", f"Daily {l.kind} near {l.display}.", 80, [l.id], "levels")
    if invalid:
        add("watch", invalid, 78, ["trend_1d"], "invalidation")
    return P
