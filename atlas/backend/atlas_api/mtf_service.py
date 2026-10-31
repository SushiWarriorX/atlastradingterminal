"""Fetches the five timeframes and runs the pure analysis in mtf.py. Shared by the API route, the AI tool and the AI snapshot."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from . import compare as cmp
from . import mtf
from .instruments import Instrument
from .models import ProviderUnavailable
from .service import BAR_SECONDS, MarketService

TF_LIMIT = {"1w": 120, "1d": 300, "4h": 200, "1h": 300, "15m": 300}


async def run_mtf(svc: MarketService, inst: Instrument, swing_k: int = 3, bench_inst: Instrument | None = None) -> dict:
    now_ts = time.time()
    res = await asyncio.gather(*(svc.ohlcv(inst, tf, TF_LIMIT[tf]) for tf in mtf.TIMEFRAMES), return_exceptions=True)
    tfs, daily = [], None
    for tf, r in zip(mtf.TIMEFRAMES, res):
        if isinstance(r, Exception):
            tfs.append({"interval": tf, "available": False, "reason": str(r)})
            continue
        a = mtf.analyze_tf(r.candles, tf, BAR_SECONDS[tf], now_ts, swing_k, inst.is_equity_like)
        a["data"] = {"status": r.prov.status.value, "provider": r.prov.provider, "derived_from": r.derived_from,
                     "event_time": r.prov.event_time.isoformat() if r.prov.event_time else None}
        if tf == "1d":
            daily = r.candles
        tfs.append(a)
    rs_pp, rs_note = None, "no benchmark selected" if bench_inst is None else None
    if bench_inst is not None and daily:
        try:
            b = await svc.ohlcv(bench_inst, "1d", 300)
            _, al = cmp.align({inst.id: daily, bench_inst.id: b.candles}, "1d", min_common=65)
            a_c, b_c = [c.close for c in al[inst.id]], [c.close for c in al[bench_inst.id]]
            rs_pp = ((a_c[-1] / a_c[-64] - 1) - (b_c[-1] / b_c[-64] - 1)) * 100
            rs_note = f"63 aligned daily observations vs {bench_inst.symbol} ({len(a_c)} shared bars)"
        except (ProviderUnavailable, cmp.NoOverlap) as e:
            rs_note = f"benchmark unavailable: {e}"
    sc = mtf.score(tfs, rs_pp)
    sc["factors"]["relative_strength"]["note"] = rs_note
    return {"instrument_id": inst.id, "symbol": inst.symbol, "swing_k": swing_k, "benchmark": bench_inst.symbol if bench_inst else None,
            "as_of": datetime.now(timezone.utc).isoformat(), "timeframes": tfs, "alignment": mtf.alignment(tfs), "score": sc, "rules": mtf.RULES}


def compact(m: dict) -> dict:
    """A small, model-friendly view of an MTF result (no rule text), plus level candidates with stable ids."""
    tfs, levels = [], []
    for t in m["timeframes"]:
        if not t["available"]:
            tfs.append({"interval": t["interval"], "available": False, "reason": t.get("reason", "")[:120]})
            continue
        st = t["structure"]
        tfs.append({"interval": t["interval"], "available": True, "trend": t["trend"], "structure": st["label"], "event": st["event"],
                    "rsi14": t["rsi14"], "macd_hist": t["macd_hist"], "atr_pct": t["atr_pct"], "rvol": t["rvol"], "last_close": t["last_close"],
                    "data_status": t["data"]["status"]})
        for kind, key in (("support", "nearest_support"), ("resistance", "nearest_resistance")):
            if t.get(key) is not None:
                levels.append({"id": f"mtf-{t['interval']}-{kind}", "kind": f"mtf_{kind}", "price": t[key],
                                "derivation": f"nearest computed {kind} on {t['interval']} (swings, prior-day range, SMA50/200)"})
    sc = m["score"]
    return {"timeframes": tfs, "levels": levels, "alignment": {"verdict": m["alignment"]["verdict"], "text": m["alignment"]["text"]},
            "score": {"score": sc["score"], "label": sc["label"], "tilt": sc["tilt"], "benchmark": m["benchmark"], "unavailable": sc["unavailable"],
                      "factors": {k: {"value": f["value"], "weight": f["effective_weight"]} for k, f in sc["factors"].items()}},
            "swing_k": m["swing_k"]}
