"""What the Signal app shows of the paper lab: the latest dashboard in plain words, and the last trades as the ledger recorded them on signal. Read-only; simulated accounts only, nothing here can place an order."""
from __future__ import annotations

import bisect
import json
from datetime import datetime, timezone
from pathlib import Path

from . import backtest as B
from . import config as C
from . import data as D
from . import strategies as S

SHOWN_EVENTS = ("order", "fill", "reject", "stop_hit", "breaker", "breaker_reset")       # the trades as they happened; an account opening is not a trade (its day is in the account's opened_after)
PORTFOLIO_LABEL = "Main portfolio ($100,000, champions only)"
BENCHMARK_LABELS = {"buy_hold": "Buy and hold Bitcoin", "cash": "Cash only"}
SHORT = {"sma_cross": "SMA", "donchian": "DON", "ma_atr_trend": "ATR", "tsmom": "TSM", "rsi_momentum": "RSM", "mom_vol": "MOM", "bollinger_mr": "BOL", "rsi_oversold": "RSO", "vol_breakout": "VBO",
         "regime_switch": "REG", "vol_target": "VTG", "sma_filter": "FLT", "buy_hold": "BTC", "cash": "USD", "portfolio": "MP"}      # the letters on a strategy's round logo
OUTCOME_WORDS = {"admitted": "Admitted", "rejected": "Rejected", "too_thin": "Too few trades to judge"}
GATE_WORDS = {"A1": "it made too few trades to judge (at least 10 are needed)",
              "A2": "it did not beat holding the same average amount of Bitcoin, in both 2020-2022 and 2023-2024",
              "A3": "its timing was no better than random timing",
              "A4": "its result was not stable when its settings were nudged",
              "A5": "it stopped working when the costs were doubled"}
CURVE_STEP_DAYS = 7
CURVE_NOTE = ("Each line replays one rule on past prices as one continuous run from 2020-01-01 with $10,000, with the same fees and slippage as the paper accounts. The settings were chosen on this same history, "
              "so a backtest looks better than anything that can be expected from now on. 2025 onward is not a clean test either: earlier experiments in this project already looked at it.")
PARAM_WORDS = {"fast": "fast", "slow": "slow", "N": "N", "L": "L", "m": "ATR multiple", "n": "n", "enter": "enter", "exit": "exit", "cap": "volatility cap", "k": "k", "hold": "hold days", "adx": "ADX", "target": "target", "window": "window"}


def iso(t: int) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def label(account: dict) -> str:
    if account["id"] == "portfolio":
        return PORTFOLIO_LABEL
    if account["id"] in BENCHMARK_LABELS:
        return BENCHMARK_LABELS[account["id"]]
    params = params_text(account)
    return f"{S.FAMILIES[account['family']].name} ({params})" if params else S.FAMILIES[account["family"]].name


def family_name(account: dict) -> str:
    return "Main portfolio" if account["id"] == "portfolio" else S.FAMILIES[account["family"]].name


def params_text(account: dict) -> str:
    return ", ".join(f"{PARAM_WORDS.get(k, k)} {v}" for k, v in account["params"].items())


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


def short(account: dict) -> str:
    return SHORT.get(account["id"]) or SHORT.get(account["family"]) or account["family"][:3].upper()


def _period(m: dict | None) -> dict | None:
    """One period's figures of the research run (TRAIN or VALIDATION), the ones the pre-registered gates were applied to."""
    if not m:
        return None
    return {k: m.get(src) for k, src in (("return", "total_return"), ("hold_return", "hold_return"), ("matched_hold_return", "matched_hold_return"), ("max_drawdown", "max_drawdown"),
                                          ("sharpe", "sharpe"), ("trades", "trades"), ("exposure", "exposure"))}


def verdicts(root: Path, dash: dict) -> dict:
    """What the one-off research run decided about each family, in plain words: {family: {outcome, outcome_text, why, train, validation, timing_p}}. The outcome comes from the dashboard; the reasons and the period figures come
    from the research report when it is there. A missing or damaged report loses only the details."""
    out = {fam: {"outcome": o, "outcome_text": OUTCOME_WORDS.get(o, o), "why": [], "train": None, "validation": None, "timing_p": None} for fam, o in ((dash.get("research") or {}).get("outcomes") or {}).items()}
    path = root / "reports" / f"research_{dash.get('protocol', C.PROTOCOL_VERSION)}.json"
    try:
        fams = json.loads(path.read_text(encoding="utf-8"))["evaluation"]["families"]
    except (OSError, ValueError, KeyError, TypeError):
        return out
    for fam, ev in fams.items():
        if fam not in out:
            continue
        out[fam].update({"why": [GATE_WORDS.get(g, g) for g in ev["admission"]["failed"]], "train": _period(ev.get("train")), "validation": _period(ev.get("validation")),
                         "timing_p": (ev.get("validation_timing") or {}).get("p")})
    return out


def _day(t: int) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d")


_CURVES: dict = {}


def backtest_curves(root: Path, accounts: list) -> dict | None:
    """Every account's rule replayed on the stored daily candles from the first evaluation day to the latest candle (one continuous run, $10,000, protocol costs), sampled every CURVE_STEP_DAYS days:
    {"times", "periods", "curves": {account id: {...}}}. None when the candle file is missing or damaged. Cached per candle file and per set of rules: a run takes a few hundredths of a second."""
    path = root / "data" / "btcusd_1d.csv"
    try:
        st = path.stat()
    except OSError:
        return None
    stamp = (str(path), st.st_mtime_ns, st.st_size, C.PROTOCOL_VERSION, tuple(sorted((a["id"], a["family"], json.dumps(a["params"], sort_keys=True)) for a in accounts if a["id"] != "portfolio")))
    if stamp in _CURVES:
        return _CURVES[stamp]
    try:
        prep = B.Prepared(D.load(path))
        i0, i1 = prep.span(C.EVAL_START, None)
    except (ValueError, IndexError, D.DataError):
        return None
    idx = list(range(i0, i1 + 1, CURVE_STEP_DAYS))
    if idx[-1] != i1:
        idx.append(i1)
    periods = []
    for name, (first, last) in C.PERIODS.items():
        k0 = bisect.bisect_left(idx, bisect.bisect_left(prep.times, B.day_ts(first)))
        k1 = (bisect.bisect_right(idx, bisect.bisect_right(prep.times, B.day_ts(last)) - 1) if last else len(idx)) - 1
        if k0 <= k1:
            periods.append({"name": name, "from": k0, "to": k1})
    curves = {}
    for a in accounts:
        if a["id"] == "portfolio" or a["family"] not in S.FAMILIES:
            continue
        r = B.run(prep, a["family"], a["params"], i0, i1, keep_account=True)
        eq = [row[1] for row in r.account.curve]
        curves[a["id"]] = {"curve": [round(eq[i - i0] / r.account.start_equity, 4) for i in idx], "return": r.metrics["total_return"], "max_drawdown": r.metrics["max_drawdown"],
                           "trades": r.metrics["trades"], "breaker_trips": r.metrics["breaker_trips"], "sharpe": r.metrics["sharpe"]}
    out = {"from": _day(prep.times[i0]), "to": _day(prep.times[i1]), "step_days": CURVE_STEP_DAYS, "times": [_day(prep.times[i]) for i in idx], "periods": periods, "curves": curves}
    _CURVES.clear()                                                    # one entry is enough: a new candle changes the key
    _CURVES[stamp] = out
    return out


def forward_series(root: Path, aid: str, keep: int = 120) -> list:
    """The paper account's equity at each daily close since it was opened, as a ratio of its starting equity (the last `keep` days). Empty on the first day or when the file cannot be read."""
    try:
        acc = json.loads((root / "state" / "accounts" / f"{aid}.json").read_text(encoding="utf-8"))["account"]
        return [round(row[1] / acc["start_equity"], 4) for row in acc["curve"]][-keep:]
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return []


def backtest_block(verdict: dict | None, curve: dict | None) -> dict | None:
    """What the phone shows of one account's backtest: the research run's verdict (absent for the benchmarks and the main portfolio) and its continuous replay (absent when the candle file is not there)."""
    if verdict is None and curve is None:
        return None
    v = verdict or {"outcome": None, "outcome_text": "Benchmark", "why": [], "train": None, "validation": None, "timing_p": None}
    return {**v, "run": None if curve is None else {k: curve[k] for k in ("return", "max_drawdown", "trades", "breaker_trips", "sharpe")}, "curve": None if curve is None else curve["curve"]}


def paper_view(root: Path | None = None, recent: int = 30) -> dict:
    root = Path(root) if root is not None else C.ROOT
    path = root / "dashboard.json"
    if not path.exists():
        return {"available": False, "reason": "The paper lab's daily run has not been made yet."}
    dash = json.loads(path.read_text(encoding="utf-8"))
    verd, bt = verdicts(root, dash), backtest_curves(root, dash["accounts"])
    accounts, rows = [], []
    for a in dash["accounts"]:
        pend = a["pending"]
        pend_text = None
        if pend:
            pend_text = {"enter": "BUY at the next open", "exit": "SELL at the next open", "rebalance": f"move to {(pend.get('weight') or 0):.0%} in Bitcoin at the next open"}.get(pend["kind"], pend["kind"])
        accounts.append({"id": a["id"], "label": label(a), "stage": a["stage"], "family": a["family"], "equity": a["equity"], "start_equity": a["start_equity"], "return": a["return"], "day_pnl": a["day_pnl"],
                         "hold_return": a.get("hold_return"), "matched_hold_return": a.get("matched_hold_return"), "exposure": a["exposure"], "drawdown": a["drawdown"], "trades": a["trades"], "days": a["days"],
                         "halted": a["halted"], "breaker_trips": a["breaker_trips"], "pending": pend_text,
                         "opened_after": a.get("opened_after_candle"), "short": short(a), "name": family_name(a), "params_text": params_text(a), "backtest": backtest_block(verd.get(a["family"]), (bt or {"curves": {}})["curves"].get(a["id"])),
                         "forward": forward_series(root, a["id"])})
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
            "backtest": None if bt is None else {"from": bt["from"], "to": bt["to"], "step_days": bt["step_days"], "times": bt["times"], "periods": bt["periods"], "note": CURVE_NOTE},
            "accounts": accounts, "recent": rows[-recent:][::-1], "problems": dash.get("frozen_check", []),
            "note": "These accounts are simulations. A paper profit is not a profit, and no real order is ever placed. Orders are modelled as filled at the 00:00 UTC open although the daily run happens at 00:15."}
