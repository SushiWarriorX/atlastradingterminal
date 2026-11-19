"""Strategy tracker: every strategy the research loop adds is backtested once, the result is FROZEN in a ledger, and from then on the rule is followed forward on new bars.

Two different things are shown and never mixed:
 - The BACKTEST snapshot: run once on the day the strategy was added, on all history up to that day, with the same evaluation as the rest of the Strategy Lab (fees, slippage,
   70/30 out-of-sample split, walk-forward, neighbouring parameters, doubled costs, the luck check that counts the whole library). It is saved in the ledger file and never
   recomputed, so a strategy cannot be quietly re-tuned after the fact.
 - The FORWARD record: how the same fixed rule has done on bars that arrived AFTER the day it was added. This is the only genuinely out-of-sample evidence, because nobody (including
   the person or loop that picked the rule) had seen those bars. Under 60 days of it says nothing, and the screen says so.
It is calculated from the rule on real prices, not a live account, and places nothing. Research only.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from .evaluate import Frame, LabError, buy_and_hold, costs_for, evaluate, iso, metrics, run, target_for
from .strategies import S

LEDGER = Path(__file__).with_name("tracker_ledger.json")
REQ = {"fee_bps": 5.0, "slippage_bps": 5.0, "leverage": 1.0, "long_short": False, "timeframe": "1d", "market": "spot"}
MIN_FORWARD_DAYS = 60


def load(path: Path = LEDGER) -> dict:
    if not path.exists():
        return {"entries": []}
    return json.loads(path.read_text())


def save(ledger: dict, path: Path = LEDGER) -> None:
    path.write_text(json.dumps(ledger, indent=1, sort_keys=False) + "\n")


def snapshot(sid: str, rows: list[tuple]) -> dict:
    """Run the Strategy Lab evaluation once and keep the parts worth showing. `rows` are Coinbase daily bars (t, o, h, l, c, v), oldest first."""
    if sid not in S or S[sid].requires_funding:
        raise LabError(f"'{sid}' cannot be tracked: it is unknown or needs perpetual funding.")
    f = Frame(rows, "1d", None, False)
    bh = buy_and_hold(f, REQ, f.first, f.last)
    n_compared = sum(1 for x in S.values() if not x.requires_funding)
    r = evaluate(S[sid], f, REQ, bh, n_compared)
    wf = {k: r["walk_forward"].get(k) for k in ("net_return_pct", "sharpe", "max_drawdown_pct", "trades")}
    return {"library_size": n_compared, "data_from": r["curve"]["from"], "data_to": r["curve"]["to"], "bars": f.n, "params": r["params"], "stop_pct": r["stop_pct"],
            "full": r["full"], "in_sample": r["in_sample"], "out_of_sample": r["out_of_sample"], "walk_forward": wf,
            "buy_and_hold": {"full": r["buy_and_hold"]["full"], "out_of_sample": r["buy_and_hold"]["out_of_sample"]},
            "robustness": r["robustness"], "luck_check": {"lower_bound": r["judgement"]["sharpe_lower_bound"], "note": r["judgement"]["luck_check_note"]}, "capture": r["judgement"]["capture"],
            "evidence": r["evidence"], "costs": r["costs"], "curve": r["curve"]}


def forward(sid: str, added: str, rows: list[tuple]) -> dict:
    """The fixed rule followed on bars from the day it was added: return, worst drop, closed trades, today's position, and the same for simply holding."""
    f = Frame(rows, "1d", None, False)
    st = S[sid]
    costs = costs_for(f, st, REQ)
    params = dict(st.params)
    tgt = target_for(st, f, params, False)
    a, b = f.first, f.last
    full = run(f, tgt, costs, a, b)
    bh = buy_and_hold(f, REQ, a, b)
    t0 = datetime.fromisoformat(added).replace(tzinfo=timezone.utc).timestamp()
    i0 = int(np.searchsorted(f.t[a:b], t0)) + a
    k0 = i0 - a
    days = (b - a) - k0
    out = {"added": added, "days": days, "from": iso(int(f.t[i0])) if days > 0 else None, "to": iso(int(f.t[b - 1])), "enough": days >= MIN_FORWARD_DAYS,
           "position_now": "long" if tgt[b - 1] > 0 else "flat", "conditions": st.conds(f.df, params)}
    if days < 2:
        return {**out, "strategy": None, "buy_and_hold": None, "note": "Tracking has only just started: there are no new bars to judge it on yet."}
    base, bbase = full["curve"][k0], bh["curve"][k0]
    seg = [x / base if base > 0 else 0.0 for x in full["curve"][k0:]]
    bseg = [x / bbase for x in bh["curve"][k0:]]
    t_cut = f.t[i0]
    trades = [x for x in full["trades"] if x["exit_t"] >= t_cut and not x.get("open")]
    m, mb = metrics(seg, trades, f.bpy, None), metrics(bseg, [], f.bpy)
    out.update(strategy={"return_pct": m["net_return_pct"], "max_drawdown_pct": m["max_drawdown_pct"], "closed_trades": len(trades), "win_rate_pct": m["win_rate_pct"]},
               buy_and_hold={"return_pct": mb["net_return_pct"], "max_drawdown_pct": mb["max_drawdown_pct"]},
               curve={"strategy": [round(x, 4) for x in seg[:: max(1, len(seg) // 120)]], "buy_and_hold": [round(x, 4) for x in bseg[:: max(1, len(bseg) // 120)]]},
               note=(f"{days} days of new bars since the strategy was added. " + ("" if days >= MIN_FORWARD_DAYS else f"Fewer than {MIN_FORWARD_DAYS} days is too little to say anything; ignore the return for now.")))
    return out


def overview(rows: list[tuple] | None, demo: bool = False, ledger: dict | None = None) -> dict:
    """Everything the tracker screens need: the frozen backtest of each strategy plus its forward record (not computed in demo mode)."""
    led = ledger if ledger is not None else load()
    entries = []
    for e in led.get("entries", []):
        row = {k: e.get(k) for k in ("id", "name", "family", "added_at", "idea", "why", "snapshot")}
        row["rule"] = {k: getattr(S[e["id"]], k) for k in ("summary", "entry", "exit", "stop")} if e["id"] in S else None
        if demo or rows is None:
            row["forward"] = None
        else:
            try:
                row["forward"] = forward(e["id"], e["added_at"], rows)
            except (LabError, KeyError) as ex:
                row["forward"] = {"error": str(ex)[:120]}
        entries.append(row)
    entries.sort(key=lambda x: x["added_at"] or "", reverse=True)
    return {"as_of": datetime.now(timezone.utc).isoformat(), "demo": demo, "entries": entries, "library_size": sum(1 for s in S.values() if not s.requires_funding),
            "min_forward_days": MIN_FORWARD_DAYS,
            "notes": ["The backtest is frozen on the day each strategy was added and is never rerun, so a rule cannot be re-tuned after the fact.",
                      "The forward record is the rule followed on bars after that day. It is the only evidence nobody had seen when the rule was chosen. Under 60 days it says nothing.",
                      "Every strategy added to the library makes the luck check stricter for all of them, because trying more rules makes a lucky one more likely.",
                      "Calculated from the rule on real prices, not a live account. Research only: nothing here places a trade."] + (["Demo mode: forward tracking needs real prices, so only the saved backtests are shown."] if demo else [])}
