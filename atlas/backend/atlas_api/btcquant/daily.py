"""btcquant daily run (protocol section 9 and 10): `python -m atlas_api.btcquant.daily`, scheduled for 00:15 UTC.

One run, in order: bring the stored Bitcoin candles up to date (complete candles only); open the benchmark accounts and the (empty) main portfolio on the first run, and a paper account for any challenger that
lacks one; step every account through each newly completed candle with the same account code the backtest uses (so every order is written to the ledger the moment its signal is made); then write the day's
report (`reports/YYYY-MM-DD.md`, `reports/latest.md`) and `dashboard.json`. Running it twice in a row changes nothing but the files' timestamps. A failed download is reported and the stored data are used; a
missing candle stops the affected account and says so. Nothing here places an order anywhere.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import backtest as B
from . import config as C
from . import data as D
from . import metrics as M
from . import paper as P
from . import registry as R
from . import research as RS
from . import strategies as S

BENCHMARKS = (("buy_hold", "buy_hold", {}), ("cash", "cash", {}))
PORTFOLIO = "portfolio"


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def expected_last_candle(now: int) -> int:
    """Open time of the newest candle that must be complete at `now`: yesterday's."""
    return now - now % C.DAY - C.DAY


def ensure_accounts(book: P.PaperBook, reg: R.Registry, prep: B.Prepared) -> list:
    """Open what is missing: the two benchmarks, the main portfolio (cash while there is no champion), and a shadow account for every challenger."""
    opened = []
    for aid, fid, params in BENCHMARKS:
        if not book.exists(aid):
            book.open(aid, fid, params, prep, stage="benchmark")
            opened.append(aid)
    if not book.exists(PORTFOLIO):
        book.open(PORTFOLIO, "cash", {}, prep, start_equity=C.START_EQUITY_PORTFOLIO, cool_off_days=None, stage="portfolio")
        opened.append(PORTFOLIO)
    for h, ch in sorted(reg.challengers().items()):
        aid = RS.account_id(ch["family"], ch["params"])
        if not book.exists(aid):
            book.open(aid, ch["family"], ch["params"], prep, stage="challenger", version=ch.get("version", 1))
            opened.append(aid)
    return opened


def account_summary(book: P.PaperBook, prep: B.Prepared, aid: str) -> dict:
    a, meta = book.load(aid)
    curve = a.curve
    eq = a.curve[-1][1] if curve else a.start_equity
    prev = a.curve[-2][1] if len(curve) > 1 else a.start_equity
    peak = max([a.start_equity] + [r[1] for r in curve])
    out = {"id": aid, "family": meta["family"], "params": meta["params"], "stage": meta["stage"], "spec_hash": meta["spec_hash"], "opened_after_candle": meta["opened_after_candle"],
           "last_bar": meta["last_bar_iso"], "days": len(curve), "start_equity": a.start_equity, "equity": eq, "day_pnl": eq - prev, "pnl": eq - a.start_equity, "return": eq / a.start_equity - 1.0,
           "cash": a.cash, "btc": a.qty, "exposure": curve[-1][2] if curve else 0.0, "drawdown": 1.0 - eq / peak if peak else 0.0, "max_drawdown": M.max_drawdown([r[1] for r in curve], a.start_equity) if curve else 0.0,
           "trades": len(a.trades), "fills": a.fills, "fees_paid": a.fees_paid, "slippage_paid": a.slip_paid, "halted": a.halted, "breaker_trips": len(a.breaker_trips),
           "pending": None if a.pending is None else {k: a.pending.get(k) for k in ("id", "kind", "reason", "signal_time", "stop", "weight", "est_qty")}, "in_position": a.qty > 1e-12}
    if curve:
        i1 = int(np.searchsorted(prep.bars.t, curve[-1][0]))
        i0 = int(np.searchsorted(prep.bars.t, curve[0][0]))
        if i0 >= 1:
            out["hold_return"] = B.hold_return(prep, i0, i1)
            marks = M.matched_hold(prep.bars.o[i0:i1 + 1], prep.bars.c[i0:i1 + 1], float(np.mean([r[2] for r in curve])), a.start_equity)
            out["matched_hold_return"] = marks[-1] / a.start_equity - 1.0
    return out


def build_dashboard(book: P.PaperBook, reg: R.Registry, prep: B.Prepared, now: int, data_status: dict, steps: dict, opened: list) -> dict:
    accounts = [account_summary(book, prep, aid) for aid in book.ids()]
    runs = RS.previous_runs(reg)
    return {"generated_at": _iso(now), "protocol": C.PROTOCOL_VERSION, "real_trading": "DISABLED: nothing in this system can place an order", "data": data_status, "accounts": accounts,
            "champions": sorted(reg.champions()), "challengers": sorted(reg.challengers()),
            "portfolio": next((a for a in accounts if a["id"] == PORTFOLIO), None), "frozen_check": reg.check_frozen(), "drift": reg.drift(),
            "research": runs[-1] if runs else None, "steps": steps, "opened_today": opened,
            "status": "no champions: the main portfolio is in cash" if not reg.champions() else f"{len(reg.champions())} champion(s)"}


def _pct(x, k=2) -> str:
    return "n/a" if x is None else f"{100 * x:.{k}f}%"


def _money(x) -> str:
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def build_report(dash: dict, prep: B.Prepared, book: P.PaperBook) -> str:
    d = dash["data"]
    L = [f"# BTC paper trading report, {dash['generated_at'][:10]}\n"]
    L.append(f"Protocol {dash['protocol']}. **Real trading is disabled**: every trade below is a line in a file. Prices are Coinbase BTC-USD daily candles; a candle counts only once it is complete (UTC).\n")
    L.append("## Data\n")
    L.append(f"- Latest complete candle: **{d['last_candle'][:10]}** (close ${d['last_close']:,.2f}); {d['candles']:,} daily candles stored; {d['gaps']} gap(s); hash `{d['sha256'][:16]}`.")
    L.append(f"- Update: {d['update']}." + (" **The data are stale: the newest complete candle is older than yesterday's.**" if d["stale"] else ""))
    if d.get("notes"):
        L.append("- Notes: " + "; ".join(d["notes"]) + ".")
    L.append("")
    L.append("## Accounts\n")
    L.append("| account | stage | equity | today | since start | in Bitcoin | drawdown | trades | breaker | pending order |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for a in dash["accounts"]:
        pend = "none" if a["pending"] is None else f"{a['pending']['kind']} ({a['pending']['reason']}) at the next open"
        L.append(f"| `{a['id']}` | {a['stage']} | {_money(a['equity'])} | {_money(a['day_pnl'])} | {_pct(a['return'])} | {_pct(a['exposure'], 0)} | {_pct(a['drawdown'], 1)} | {a['trades']} | "
                 f"{'HALTED' if a['halted'] else 'ok'}{' (' + str(a['breaker_trips']) + ' trip' + ('s' if a['breaker_trips'] != 1 else '') + ')' if a['breaker_trips'] else ''} | {pend} |")
    L.append("")
    ch = [a for a in dash["accounts"] if a["stage"] == "challenger"]
    L.append("## Challengers against holding\n")
    if not ch:
        L.append("No strategy has been admitted as a challenger, so there is nothing to compare yet. The benchmarks above keep running.\n")
    else:
        L.append("| challenger | days | return | buy and hold | exposure-matched hold | verdict |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        for a in ch:
            verdict = "too early to say anything (under 60 days)" if a["days"] < 60 else "not enough days for promotion (needs 90)" if a["days"] < 90 else "see the promotion gates"
            L.append(f"| `{a['id']}` | {a['days']} | {_pct(a['return'])} | {_pct(a.get('hold_return'))} | {_pct(a.get('matched_hold_return'))} | {verdict} |")
        L.append("")
    L.append("## Champions and the main portfolio\n")
    L.append(f"{dash['status'].capitalize()}. " + (f"The $100,000 portfolio holds {_money(dash['portfolio']['equity'])}, all in cash." if dash["portfolio"] and not dash["champions"] else ""))
    L.append("\nA champion needs a forward paper record of at least 90 days and 5 closed trades, and all the promotion gates in `PROTOCOL.md`; none has been promoted.\n")
    if dash["research"]:
        r = dash["research"]
        L.append("## Research\n")
        L.append(f"The one-off research run of protocol {r['protocol']} (data to {r['data']['last'][:10]}) admitted {len(r['admitted'])} of 12 families as challengers; see `reports/research_{r['protocol']}.md` for what was tested, "
                 "what was admitted and why, and what was not shown.\n")
    if dash["frozen_check"]:
        L.append("## Problems found\n")
        L += [f"- {p}" for p in dash["frozen_check"]]
        L.append("")
    errs = [s for s in dash["steps"].values() if "error" in s]
    if errs:
        L.append("## Accounts that could not be stepped\n")
        L += [f"- {s['error']}" for s in errs]
        L.append("")
    L.append("## What this does not show\n")
    L.append("These are simulations on past and forward prices with assumed fees (0.10%) and slippage (0.05%). A paper profit is not a profit; nothing here is advice, a forecast or a claim that any rule makes money. "
             "Orders were modelled as filled at the 00:00 UTC open although the run happens at 00:15.\n")
    return "\n".join(L)


def run_daily(*, root: Path | None = None, now: int | None = None, update_data: bool = True, downloader: D.Downloader | None = None, candles: list | None = None) -> dict:
    now = int(time.time()) if now is None else now
    root = Path(root) if root is not None else C.ROOT
    data_path = root / "data" / "btcusd_1d.csv"
    update = "not attempted"
    notes = []
    if candles is None:
        if update_data:
            try:
                m = D.update(data_path, C.DAY, now=now, downloader=downloader)
                D.record_manifest("1d", m, root / "data" / "manifest.json")
                update = f"{m['added']} new candle(s) added"
                notes += m["notes"] + m["flags"]
            except D.DataError as e:
                update = f"failed ({e}); the stored data were used"
        candles = D.load(data_path)
    if len(candles) < 300:
        raise D.DataError("not enough stored candles to run")
    rep = D.validate(candles, C.DAY)
    if rep.fatal:
        raise D.DataError("the stored candles failed validation: " + "; ".join(rep.fatal[:3]))
    prep = B.Prepared(candles)
    manifest = D.manifest(candles, C.DAY)
    status = {"last_candle": _iso(int(prep.times[-1])), "last_close": float(prep.candles[-1][4]), "candles": len(candles), "gaps": len(rep.gaps), "sha256": manifest["sha256"],
              "stale": int(prep.times[-1]) < expected_last_candle(now), "update": update, "notes": notes}
    book, reg = P.PaperBook(root / "state"), R.Registry(root / "registry")
    opened = ensure_accounts(book, reg, prep)
    steps = book.catch_up_all(prep)
    dash = build_dashboard(book, reg, prep, now, status, steps, opened)
    report = build_report(dash, prep, book)
    rd = root / "reports"
    rd.mkdir(parents=True, exist_ok=True)
    day = _iso(now)[:10]
    (rd / f"{day}.md").write_text(report, encoding="utf-8")
    (rd / "latest.md").write_text(report, encoding="utf-8")
    (root / "dashboard.json").write_text(json.dumps(dash, sort_keys=True, indent=1, default=float) + "\n", encoding="utf-8")
    return dash


def main(argv: list) -> int:
    try:
        dash = run_daily()
    except D.DataError as e:
        print(f"daily run stopped: {e}")
        return 1
    print(f"{dash['generated_at']}: {dash['status']}; {len(dash['accounts'])} accounts; data to {dash['data']['last_candle'][:10]}; update: {dash['data']['update']}")
    bad = [s["error"] for s in dash["steps"].values() if "error" in s]
    for e in bad:
        print("  ", e)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
