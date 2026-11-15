"""What the Signal app shows of the paper lab: the latest dashboard in plain words, and the last trades as the ledger recorded them on signal. Read-only; simulated accounts only, nothing here can place an order."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config as C
from . import strategies as S

SHOWN_EVENTS = ("order", "fill", "reject", "stop_hit", "breaker", "breaker_reset", "account_opened")
PORTFOLIO_LABEL = "Main portfolio ($100,000, champions only)"
BENCHMARK_LABELS = {"buy_hold": "Buy and hold Bitcoin", "cash": "Cash only"}
PARAM_WORDS = {"fast": "fast", "slow": "slow", "N": "N", "L": "L", "m": "ATR multiple", "n": "n", "enter": "enter", "exit": "exit", "cap": "volatility cap", "k": "k", "hold": "hold days", "adx": "ADX", "target": "target", "window": "window"}


def iso(t: int) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def label(account: dict) -> str:
    if account["id"] == "portfolio":
        return PORTFOLIO_LABEL
    if account["id"] in BENCHMARK_LABELS:
        return BENCHMARK_LABELS[account["id"]]
    fam = S.FAMILIES[account["family"]]
    params = ", ".join(f"{PARAM_WORDS.get(k, k)} {v}" for k, v in account["params"].items())
    return f"{fam.name} ({params})" if params else fam.name


def money(x) -> str:
    return "n/a" if x is None else (f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}")


def describe(row: dict) -> tuple:
    """(time, text) of one ledger row in plain words; time is when the thing happened (a signal is made at a candle's close, a fill happens at the next open)."""
    ev = row["event"]
    if ev == "order":
        when = iso(row["signal_time"])
        if row["kind"] == "enter":
            est = f", about {row['est_qty']:.4f} BTC" if row.get("est_qty") else ""
            return when, f"BUY signal at the close (${row['ref_close']:,.2f}); protective stop {money(row.get('stop'))}{est}, to be filled at the next open"
        if row["kind"] == "exit":
            why = {"signal": "the rule turned off", "circuit_breaker": "the 15% circuit breaker"}.get(row["reason"], row["reason"])
            return when, f"SELL signal ({why}); to be filled at the next open"
        return when, f"Change to {row['weight']:.0%} in Bitcoin at the next open ({'buy and hold' if row['reason'] == 'benchmark' else 'the rule changed its target'})"
    if ev == "fill":
        when = iso(row["exec_time"])
        side = "BOUGHT" if row["side"] == "buy" else "SOLD"
        how = {"stop": " (stopped out)", "circuit_breaker": " (circuit breaker)"}.get(row.get("reason"), "")
        return when, f"{side} {row['qty']:.4f} BTC at {money(row['price'])}{how}; fee {money(row['fee'])}, slippage cost {money(row['slippage_cost'])}"
    if ev == "reject":
        return iso(row["exec_time"]) if row.get("exec_time") else iso(row["signal_bar"] + C.DAY), f"Order rejected: {row['reason']}"
    if ev == "stop_hit":
        return iso(row["exec_time"]), f"STOP hit at {money(row['stop'])}" + (" (the price gapped through it)" if row.get("gap") else "")
    if ev == "breaker":
        return iso(row["signal_bar"] + C.DAY), f"CIRCUIT BREAKER: equity {abs(row['drawdown']):.1%} below its peak; everything is sold at the next open and trading halts"
    if ev == "breaker_reset":
        return "", f"Trading resumed ({'30-day cool-off' if row.get('how') == 'cool_off' else 'reset by a person'})"
    return "", f"Account opened with {money(row.get('start_equity'))}"


def headline(dash: dict) -> str:
    n_ch, n_mon, n_champ = len(dash.get("challengers", [])), len(dash.get("monitors", [])), len(dash.get("champions", []))
    r = dash.get("research")
    if n_champ:
        return f"{n_champ} champion(s) are in the main portfolio. That is a paper result, not a promise."
    if n_ch:
        return f"{n_ch} strategy(ies) passed the admission bar and are being watched in paper trading. None has earned a place in the main portfolio, which stays in cash."
    if r:
        return (f"None of the {len(r.get('outcomes', {})) or 12} strategies passed the admission bar in the research run of {r['ran_at'][:10]}, so no strategy has earned a place in the main portfolio, which stays in cash. "
                f"All {n_mon} are paper-traded anyway so their trades are recorded and the forward record can show whether rejecting them was right.")
    return "The research run has not been made yet; only the benchmarks are being paper-traded."


def paper_view(root: Path | None = None, recent: int = 30) -> dict:
    root = Path(root) if root is not None else C.ROOT
    path = root / "dashboard.json"
    if not path.exists():
        return {"available": False, "reason": "The paper lab's daily run has not been made yet."}
    dash = json.loads(path.read_text(encoding="utf-8"))
    accounts, rows = [], []
    for a in dash["accounts"]:
        pend = a["pending"]
        pend_text = None
        if pend:
            pend_text = {"enter": "BUY at the next open", "exit": "SELL at the next open", "rebalance": f"move to {(pend.get('weight') or 0):.0%} in Bitcoin at the next open"}.get(pend["kind"], pend["kind"])
        accounts.append({"id": a["id"], "label": label(a), "stage": a["stage"], "family": a["family"], "equity": a["equity"], "start_equity": a["start_equity"], "return": a["return"], "day_pnl": a["day_pnl"],
                         "hold_return": a.get("hold_return"), "matched_hold_return": a.get("matched_hold_return"), "exposure": a["exposure"], "drawdown": a["drawdown"], "trades": a["trades"], "days": a["days"],
                         "halted": a["halted"], "breaker_trips": a["breaker_trips"], "pending": pend_text})
        lp = root / "state" / "ledger" / f"{a['id']}.jsonl"
        if lp.exists():
            for line in lp.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                if r["event"] in SHOWN_EVENTS:
                    when, text = describe(r)
                    rows.append({"when": when or r["recorded_at"], "recorded_at": r["recorded_at"], "seq": r["seq"], "account": a["id"], "label": label(a), "kind": r["event"], "text": text})
    rows.sort(key=lambda r: (r["when"], r["recorded_at"], r["seq"]))
    research = dash.get("research")
    return {"available": True, "generated_at": dash["generated_at"], "protocol": dash["protocol"], "real_trading": dash["real_trading"], "status": dash["status"], "headline": headline(dash),
            "data": {"last_candle": dash["data"]["last_candle"], "last_close": dash["data"]["last_close"], "stale": dash["data"]["stale"], "update": dash["data"]["update"]},
            "counts": {"champions": len(dash["champions"]), "challengers": len(dash["challengers"]), "monitors": len(dash.get("monitors", [])),
                       "research_admitted": len(research["admitted"]) if research else None, "research_ran_at": research["ran_at"] if research else None},
            "accounts": accounts, "recent": rows[-recent:][::-1], "problems": dash.get("frozen_check", []),
            "note": "These accounts are simulations. A paper profit is not a profit, and no real order is ever placed. Orders are modelled as filled at the 00:00 UTC open although the daily run happens at 00:15."}
