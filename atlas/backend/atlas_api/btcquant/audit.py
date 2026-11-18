"""Independent audit of the btcquant paper accounts. Read-only: nothing here writes a candle file, an account, a ledger, a report or a state file, and nothing from the engine (`account.py`, `paper.py`) is used: the ledger of every account is replayed here in plain Python and compared with the account file, the stored candles and the dashboard. Run it with `python -m atlas_api.btcquant.audit`; nothing calls it by itself.

What it checks, account by account. The files belong together: the account file and its meta carry the id that is the file's name, and every row of the ledger names that account. The ledger: it begins with exactly one `account_opened`, its rows are numbered 1, 2, 3 ... and its start equity is the one in the account file and in the meta. Every fill: a fill that follows an order executes at the next open (on the day the order says, the day after its signal bar), its reference price is the open of that candle and the order's reference close is the close of its signal bar; a stop-out has no order and fills at the stop (or at the open when the open gaps through it), on a candle whose low reached the stop; the fill price is the reference moved by the slippage (0.05%) against the trade, the fee is 0.10% of the notional and the slippage cost is the quantity times the move. The replay: cash and quantity after every fill equal what the ledger says, the account never holds a negative quantity or negative cash (no short, no leverage), and the totals in the account file (cash, quantity, fees, slippage, volume, number of fills) equal the replay. The curve: its days follow each other, start the day after the candle the account opened after and end on the account's last bar, each day's close is the stored close, its cash and quantity are what the ledger had on that day, and its equity is cash plus quantity times the close and its exposure the Bitcoin's share of that equity. The account is no day behind the newest stored candle, a pending order is in the ledger and has not been filled, and the dashboard shows the equity of the curve's last day.

What it cannot say: that the strategy is any good, that a signal was the right signal, or that the stored candles are right (`crosscheck.py` compares them with a second venue). It shows that the paper record is what its own rules say it is.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config as C

FEE = 0.001                                    # protocol section 3, per side, of the notional (spelled out here; a test pins it to config.py, so an amendment cannot go unnoticed)
SLIPPAGE = 0.0005                              # per side, against the trade
DAY = 86400
TOL = 1e-9                                     # relative: the replay does the engine's own arithmetic in the same order, so more than rounding noise is a difference
TOL_PRICE = 1e-12                              # prices and candle figures are copied, not calculated


class AuditError(Exception):
    """A problem that stops the audit, in plain words."""


def _same(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def _read_json(path: Path, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise AuditError(f"{what} cannot be read: {path}") from None
    except ValueError:
        raise AuditError(f"{what} is not valid JSON: {path}") from None


def _candles(root: Path) -> dict[int, tuple[float, float, float, float]]:
    path = root / "data" / "btcusd_1d.csv"
    try:
        rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
        out = {int(r["t"]): (float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"])) for r in rows}
    except OSError:
        raise AuditError(f"the stored candles cannot be read: {path}") from None
    except (KeyError, ValueError, TypeError):
        raise AuditError(f"the stored candles are not in the expected layout (t, o, h, l, c, v): {path}") from None
    if not out:
        raise AuditError(f"the stored candle file is empty: {path}")
    return out


def _ledger(root: Path, account_id: str) -> list[dict]:
    path = root / "state" / "ledger" / f"{account_id}.jsonl"
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    except OSError:
        raise AuditError(f"the ledger of {account_id} cannot be read: {path}") from None
    except ValueError:
        raise AuditError(f"the ledger of {account_id} is not valid JSON lines: {path}") from None


def _audit_account(file_id: str, doc: dict, ledger: list[dict], candles: dict, newest: int, dash: dict | None, worst: dict) -> tuple[list[str], int, int]:
    """The problems of one account (its files are `<file_id>.json` and `<file_id>.jsonl`), its number of fills and its number of curve days; an account whose ledger cannot be replayed counts none of them."""
    try:
        acc, meta = doc["account"], doc["meta"]
        aid = acc["id"]
    except (KeyError, TypeError):
        return [f"{file_id}: the account file lacks its account, its meta or its id"], 0, 0
    problems: list[str] = []

    def bad(msg: str) -> None:
        problems.append(f"{aid}: {msg}")

    if aid != file_id:
        problems.append(f"{file_id}: the account file says it is {aid}")
    if meta.get("id") != aid:
        bad(f"its meta says it is {meta.get('id')}")
    foreign = [e for e in ledger if e.get("account") != aid]
    if foreign:
        bad(f"{len(foreign)} row(s) of its ledger name another account (the first, row {foreign[0].get('seq')}, names {foreign[0].get('account')})")
    opened = [e for e in ledger if e.get("event") == "account_opened"]
    if len(opened) != 1 or ledger[0].get("event") != "account_opened":
        bad("the ledger does not begin with exactly one account_opened")
        return problems, 0, 0
    if [e.get("seq") for e in ledger] != list(range(1, len(ledger) + 1)):
        bad("the ledger's rows are not numbered 1, 2, 3 ...")
    start = opened[0]["start_equity"]
    if start != acc["start_equity"] or start != meta["start_equity"]:
        bad(f"the start equity differs: ledger {start}, account {acc['start_equity']}, meta {meta['start_equity']}")
    orders = {e["order_id"]: e for e in ledger if e.get("event") == "order"}
    stops = {e["exec_time"]: e for e in ledger if e.get("event") == "stop_hit"}
    fills = [e for e in ledger if e.get("event") == "fill"]
    cash, qty, fees, slips, traded = start, 0.0, 0.0, 0.0, 0.0
    states: list[tuple[int, float, float]] = []                              # (the candle a fill happened on, cash after, quantity after)
    for f in fills:
        n = f.get("order_id")
        t = f["exec_time"]
        candle = candles.get(t)                                                                               # a fill that is not on a stored candle is reported, and still replayed, so that it does not hide the rest
        if candle is None:
            bad(f"the fill at {t} is not on a stored candle")
        if n is not None:
            order = orders.get(n)
            if order is None:
                bad(f"the fill of order {n} has no order in the ledger")
            else:
                if t != order["signal_time"] or order["signal_bar"] != t - DAY:
                    bad(f"order {n} was signalled on {_iso(order['signal_bar'])} for {_iso(order['signal_time'])} and filled on {_iso(t)}, not at the open of the day after its signal bar")
                if order["signal_bar"] in candles and not _same(order["ref_close"], candles[order["signal_bar"]][3], TOL_PRICE):
                    bad(f"order {n}: its reference close {order['ref_close']} is not the close of its signal bar {candles[order['signal_bar']][3]}")
            if candle is not None and not _same(f["ref_price"], candle[0], TOL_PRICE):
                bad(f"the fill of order {n} refers to {f['ref_price']}, not the open {candle[0]} of its candle")
        else:
            hit = stops.get(t)
            if f["side"] != "sell" or f.get("reason") != "stop":
                bad(f"a fill with no order on {_iso(t)} is not a stop-out sale")
            elif hit is None:
                bad(f"the stop-out of {_iso(t)} has no stop_hit row")
            elif candle is not None:
                o, _, l, _ = candle
                want = o if o <= hit["stop"] else hit["stop"]
                if l > hit["stop"]:
                    bad(f"the stop-out of {_iso(t)}: the low {l} of that candle never reached the stop {hit['stop']}")
                if not _same(hit["open"], o, TOL_PRICE) or not _same(hit["low"], l, TOL_PRICE):
                    bad(f"the stop-out of {_iso(t)}: its row has the open {hit['open']} and low {hit['low']}, the candle has {o} and {l}")
                if not _same(f["ref_price"], want, TOL_PRICE):
                    bad(f"the stop-out of {_iso(t)} refers to {f['ref_price']}, but the stop is {hit['stop']} and the open {o}: it should fill at {want}")
        sign = 1 if f["side"] == "buy" else -1
        want_price = f["ref_price"] * (1 + sign * SLIPPAGE)
        worst["price"] = max(worst["price"], abs(want_price - f["price"]))
        if not _same(want_price, f["price"], TOL_PRICE):
            bad(f"the fill on {_iso(t)} is at {f['price']}, not the reference moved by {SLIPPAGE:.2%} against the trade ({want_price})")
        notional = f["qty"] * f["price"]
        worst["fee"] = max(worst["fee"], abs(notional * FEE - f["fee"]))
        if not _same(notional * FEE, f["fee"], TOL):
            bad(f"the fee of the fill on {_iso(t)} is {f['fee']}, not {FEE:.2%} of its notional {notional} ({notional * FEE})")
        if not _same(f["qty"] * abs(f["price"] - f["ref_price"]), f["slippage_cost"], TOL):
            bad(f"the slippage cost of the fill on {_iso(t)} is {f['slippage_cost']}, not the quantity times the price move ({f['qty'] * abs(f['price'] - f['ref_price'])})")
        cash += -(notional + f["fee"]) if sign == 1 else notional - f["fee"]                                  # in the engine's order: a purchase pays the notional and the fee, a sale receives the notional less the fee
        qty += sign * f["qty"]
        fees, slips, traded = fees + f["fee"], slips + f["slippage_cost"], traded + notional
        worst["cash"] = max(worst["cash"], abs(cash - f["cash_after"]))
        worst["qty"] = max(worst["qty"], abs(qty - f["qty_after"]))
        if not _same(cash, f["cash_after"], TOL) or not _same(qty, f["qty_after"], TOL):
            bad(f"after the fill on {_iso(t)} the replay holds {cash} cash and {qty} Bitcoin, the ledger says {f['cash_after']} and {f['qty_after']}")
        if qty < -TOL or cash < -1e-6:
            bad(f"after the fill on {_iso(t)} the account would hold {qty} Bitcoin and {cash} cash (a short or leverage)")
        states.append((t, cash, qty))
    if not _same(cash, acc["cash"], TOL) or not _same(qty, acc["qty"], TOL):
        bad(f"the account file holds {acc['cash']} cash and {acc['qty']} Bitcoin, the ledger replays to {cash} and {qty}")
    if not (_same(fees, acc["fees_paid"], TOL) and _same(slips, acc["slip_paid"], TOL) and _same(traded, acc["traded"], TOL) and acc["fills"] == len(fills)):
        bad(f"fees, slippage, volume or number of fills differ: the file has {acc['fees_paid']}, {acc['slip_paid']}, {acc['traded']} and {acc['fills']}, the ledger replays to {fees}, {slips}, {traded} and {len(fills)}")
    curve = acc["curve"]
    after = int(datetime.strptime(opened[0]["after_candle"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    previous = None
    for t, eq, expo, c_, q_, close_, _ in curve:
        if previous is None and t != after + DAY:
            bad(f"the curve starts on {_iso(t)}, not the day after the candle the account opened after ({_iso(after)})")
        if previous is not None and t != previous + DAY:
            bad(f"the curve jumps from {_iso(previous)} to {_iso(t)}")
        previous = t
        if t not in candles:
            bad(f"the curve day {_iso(t)} is not a stored candle")
            continue
        if not _same(close_, candles[t][3], TOL_PRICE):
            bad(f"curve day {_iso(t)}: the close is {close_}, the stored close {candles[t][3]}")
        done = [s for s in states if s[0] <= t]
        want_cash, want_qty = (done[-1][1], done[-1][2]) if done else (start, 0.0)
        if not _same(c_, want_cash, TOL) or not _same(q_, want_qty, TOL):
            bad(f"curve day {_iso(t)}: it holds {c_} cash and {q_} Bitcoin, the ledger says {want_cash} and {want_qty}")
        want_eq = want_cash + want_qty * candles[t][3]
        worst["equity"] = max(worst["equity"], abs(want_eq - eq))
        if not _same(eq, want_eq, TOL):
            bad(f"curve day {_iso(t)}: the equity is {eq}, not cash plus quantity times the close ({want_eq})")
        if want_eq > 0 and not _same(expo, want_qty * candles[t][3] / want_eq, TOL):
            bad(f"curve day {_iso(t)}: the exposure is {expo}, not the Bitcoin's share of the equity ({want_qty * candles[t][3] / want_eq})")
    if curve:
        if not (curve[-1][0] == acc["last_bar"] == meta["last_bar"]):
            bad(f"the last bar differs: the curve ends on {curve[-1][0]}, the account says {acc['last_bar']} and the meta {meta['last_bar']}")
    elif acc["last_bar"] is not None or meta["last_bar"] != after:
        bad(f"an account with no curve should have no last bar and its meta the candle it opened after ({after}), but has {acc['last_bar']} and {meta['last_bar']}")
    behind = (newest - meta["last_bar"]) // DAY
    if behind > 0:
        bad(f"the account is {behind} day(s) behind the newest stored candle ({_iso(newest)})")
    if acc["pending"]:
        n = acc["pending"].get("id")
        if n not in orders or any(f.get("order_id") == n for f in fills):
            bad(f"the pending order {n} is not in the ledger or has been filled already")
    if dash is None:
        bad("it is not in the dashboard")
    elif curve and not _same(dash["equity"], curve[-1][1], TOL):
        bad(f"the dashboard shows the equity {dash['equity']}, the curve's last day {curve[-1][1]}")
    return problems, len(fills), len(curve)


def audit(root: Path | str | None = None) -> dict:
    """Replay every account under `root` (default: the btcquant folder) and describe what was and was not consistent."""
    root = Path(root) if root is not None else C.ROOT                                                      # an empty path is a path (it is not "no path"): a variable that was never set must not be audited as the default folder
    candles = _candles(root)
    dashboard = _read_json(root / "dashboard.json", "the dashboard")
    try:
        dash = {a["id"]: a for a in dashboard["accounts"]}
    except (KeyError, TypeError):
        raise AuditError("the dashboard has no list of accounts") from None
    files = sorted((root / "state" / "accounts").glob("*.json"))
    if not files:
        raise AuditError(f"there are no account files under {root / 'state' / 'accounts'}")
    newest = max(candles)
    worst = {"cash": 0.0, "qty": 0.0, "equity": 0.0, "price": 0.0, "fee": 0.0}
    problems: list[str] = []
    fills = days = 0
    ids = []
    for path in files:
        doc = _read_json(path, f"the account file {path.name}")
        aid = path.stem
        try:
            p, n_fills, n_days = _audit_account(aid, doc, _ledger(root, aid), candles, newest, dash.get(aid), worst)
        except (KeyError, TypeError, ValueError, AttributeError):
            p, n_fills, n_days = [f"{aid}: its files are not in the layout the audit reads (a field is missing or has the wrong type)"], 0, 0
        problems += p
        fills, days = fills + n_fills, days + n_days
        ids.append(aid)
    for extra in sorted(set(dash) - set(ids)):
        problems.append(f"{extra}: it is in the dashboard but has no account file")
    first = min(candles)
    return {"root": str(root), "accounts": len(files), "fills": fills, "curve_days": days, "candles": len(candles), "first_candle": _iso(first), "last_candle": _iso(newest),
            "worst": worst, "problems": problems}


def describe(r: dict) -> str:
    lines = ["Paper-account audit (read-only: nothing is written)", f"Folder: {r['root']}",
             f"{r['accounts']} accounts, {r['fills']} fills and {r['curve_days']} curve days replayed against {r['candles']:,} stored candles ({r['first_candle']} to {r['last_candle']}).",
             "Largest differences between the replay and the files: " + ", ".join(f"{k} {v:.3g}" for k, v in r["worst"].items()) + "."]
    lines += [f"{len(r['problems'])} problem(s):"] + [f"  - {p}" for p in r["problems"]] if r["problems"] else ["No problems."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay the ledgers of the btcquant paper accounts and compare them with the account files, the stored candles and the dashboard (read-only).")
    p.add_argument("--root", help="the btcquant folder (default: the one in this repository)")
    a = p.parse_args(argv)
    try:
        r = audit(a.root)
    except AuditError as e:
        print(f"The audit could not be made: {e}")
        return 2
    print(describe(r))
    return 1 if r["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
