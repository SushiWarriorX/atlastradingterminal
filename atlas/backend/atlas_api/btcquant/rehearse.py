"""Rehearse the next daily run on a throwaway copy of `atlas/btcquant`. Read-only on the repository: the folder is copied to a temporary one, `daily.run_daily` runs there with a stand-in for the candle that has not closed yet, and the tool says what that run would do; the repository's own files are hashed before and after and the tool says so if one differs.

    python -m atlas_api.btcquant.rehearse [--candle real|fall|rise] [--move PERCENT]

The stand-in is the day's own still-forming Coinbase candle (`real`: one request, taken as if it had closed), a candle 20% lower (`fall`) or 20% higher (`rise`), or any move with `--move` (for example -5). It exercises the code path only: no return from it means anything, and a candle that is still forming is not the one that will close. The run is then repeated on the same input: it must leave every state file, ledger and report byte-identical and may change only the dashboard's run-activity counters (days processed and events, which fall back to 0).

Written after four hand-made versions of this script (2026-11-17 16:24 UTC; 2026-11-18 04:19, 19:21 and 22:23 UTC). What it showed on the real accounts: the fall trips the circuit breaker of the one fully invested account and stops out the small positions, the rise signals entries, exits and rebalances, and a second run changes nothing but the counters. The module is not imported by the daily run.

Exit code 0 = the run behaved, 1 = something did not (the lines say what), 2 = the rehearsal could not be made."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..failreason import fail_reason
from . import config as C
from . import daily as DL
from . import data as D

ACTIVITY = ("processed", "events")               # the dashboard's run-activity counters: what THIS run did, so a second run on the same input shows 0
STRESS = {"fall": -20.0, "rise": 20.0}           # percent, the two stand-ins that are not the real candle
EDGE = 0.005                                     # an invented candle's high and low lie half a percent outside its open and close


class RehearsalError(Exception):
    """The rehearsal could not be made, in plain words."""


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def strip_activity(x):
    """A copy of a dashboard without its run-activity counters at any depth."""
    if isinstance(x, dict):
        return {k: strip_activity(v) for k, v in x.items() if k not in ACTIVITY}
    if isinstance(x, list):
        return [strip_activity(v) for v in x]
    return x


def run_time(day_open: int) -> int:
    """When the run that adds the candle of the day opening at `day_open` takes place: 00:15 UTC on the next day."""
    return day_open + C.DAY + 15 * 60


def stand_in(newest, kind: str, move: float | None = None, fetch: Callable | None = None) -> list:
    """The candle of the day after `newest` (the newest stored one) as [open time, open, high, low, close, volume]."""
    t, _o, _h, _l, close, volume = newest
    day = t + C.DAY
    if move is None and kind == "real":
        try:
            rows = [r for r in (fetch or D.Downloader().fetch)(C.DAY, day, day) if r[0] == day]
        except D.DataError as e:
            raise RehearsalError(f"Coinbase gave no candle ({e})") from e
        if len(rows) != 1:
            raise RehearsalError(f"Coinbase has no candle for {_iso(day)} yet (the day opens at 00:00 UTC): try --candle fall, --candle rise or --move PERCENT")
        return list(rows[0])
    pct = move if move is not None else STRESS[kind]
    new = close * (1 + pct / 100)
    return [day, close, max(close, new) * (1 + EDGE), min(close, new) * (1 - EDGE), new, volume]


def rehearse(root: Path, kind: str = "real", move: float | None = None, fetch: Callable | None = None, run: Callable = DL.run_daily) -> dict:
    """Make the rehearsal and return everything it found; `run` is `daily.run_daily` (a test may put another in its place)."""
    root = Path(root)
    before = snapshot(root)
    try:
        old = json.loads((root / "dashboard.json").read_text(encoding="utf-8"))
        candles = D.load(root / "data" / "btcusd_1d.csv")
    except (OSError, ValueError, D.DataError) as e:
        raise RehearsalError(f"the stored files could not be read ({fail_reason(e)})") from e
    if not candles:
        raise RehearsalError("the stored candle file holds no candle")
    candle = stand_in(candles[-1], kind, move, fetch)
    now, problems = run_time(candle[0]), []
    dash = dash2 = None
    with tempfile.TemporaryDirectory(prefix="btcquant-rehearsal-") as tmp:
        work = Path(tmp) / "btcquant"
        shutil.copytree(root, work)
        try:
            dash = run(root=work, now=now, candles=candles + [candle])
        except Exception as e:                                                          # the run is what is under test: whatever it raises is the finding
            problems.append(f"the run failed: {e!r}")
        after1 = snapshot(work)
        if dash is not None:
            try:
                dash2 = run(root=work, now=now, candles=candles + [candle])
            except Exception as e:
                problems.append(f"the repeat run failed: {e!r}")
        after2 = snapshot(work)
    changed_by_repeat = sorted(k for k in set(after1) | set(after2) if after1.get(k) != after2.get(k) and k != "dashboard.json")
    if changed_by_repeat:
        problems.append("a repeat run on the same input changed " + ", ".join(changed_by_repeat[:5]))
    dashboard_moved = dash is not None and dash2 is not None and strip_activity(dash) != strip_activity(dash2)
    if dashboard_moved:
        problems.append("a repeat run on the same input changed the dashboard beyond its run-activity counters")
    accounts, notes = [], []
    if dash is not None:
        was = {a["id"]: a for a in old.get("accounts", [])}
        now_accounts = {a["id"]: a for a in dash["accounts"]}
        if dash["frozen_check"]:
            problems.append(f"the frozen check is not empty: {dash['frozen_check']}")
        if dash["data"]["stale"]:
            problems.append("the data would be stale")
        if sorted(set(was) - set(now_accounts)):
            problems.append("accounts missing after the run: " + ", ".join(sorted(set(was) - set(now_accounts))))
        for aid, a in now_accounts.items():
            o = was.get(aid)
            step = a["days"] - o["days"] if o else None
            accounts.append({"id": aid, "stage": a["stage"], "days_before": o["days"] if o else None, "days_after": a["days"], "equity_before": o["equity"] if o else None, "equity_after": a["equity"],
                             "exposure": a.get("exposure"), "halted": bool(a["halted"]), "pending": a.get("pending")})
            if o and step < 1:
                problems.append(f"{aid} did not step ({o['days']} days before, {a['days']} after)")
            elif o and step > 1:
                notes.append(f"{aid} caught up {step} days")
    after_repo = snapshot(root)
    moved = sorted(k for k in set(before) | set(after_repo) if before.get(k) != after_repo.get(k))
    if moved:
        problems.append("THE REPOSITORY'S btcquant FOLDER CHANGED during the rehearsal: " + ", ".join(moved[:5]))
    return {"candle": candle, "previous_close": candles[-1][4], "run_time": now, "dashboard": dash, "accounts": accounts, "notes": notes,
            "added": sorted(set(after1) - set(before)), "removed": sorted(set(before) - set(after1)), "changed": sorted(k for k in before if k in after1 and before[k] != after1[k]),
            "repeat_ok": not changed_by_repeat and not dashboard_moved and dash2 is not None, "repo_unchanged": not moved, "problems": problems}


def report(r: dict) -> list[str]:
    c, d = r["candle"], r["dashboard"]
    pct = 100 * (c[4] / r["previous_close"] - 1)
    out = ["Rehearsal of the next daily run on a throwaway copy (nothing in the repository is written)",
           f"Stand-in for {_iso(c[0])}: open {c[1]:,.2f}, high {c[2]:,.2f}, low {c[3]:,.2f}, close {c[4]:,.2f}, volume {c[5]:,.1f} ({pct:+.2f}% on the previous close); it exercises the code path only, no return from it means anything",
           f"Run time used: {datetime.fromtimestamp(r['run_time'], timezone.utc):%Y-%m-%d %H:%M} UTC"]
    if d is not None:
        out += [f"Status: {d['status']} | protocol {d['protocol']} | frozen check {'empty' if not d['frozen_check'] else d['frozen_check']} | data {'STALE' if d['data']['stale'] else 'not stale'}, {d['data']['candles']:,} candles, {d['data']['gaps']} gap(s)",
                f"Opened today: {', '.join(d['opened_today']) if d.get('opened_today') else 'none'}"]
        halted = [a["id"] for a in r["accounts"] if a["halted"]]
        orders = [f"{a['id']}: {a['pending']['kind']} ({a['pending'].get('reason', '')})" for a in r["accounts"] if a["pending"]]
        out += [f"Accounts: {len(r['accounts'])}; halted by the circuit breaker: {', '.join(halted) if halted else 'none'}", "Orders waiting for the next open: " + ("; ".join(orders) if orders else "none")]
        for a in r["accounts"]:
            was = "new" if a["days_before"] is None else f"{a['days_before']} -> {a['days_after']}"
            eq = f"{a['equity_after']:,.2f}" if a["equity_before"] is None else f"{a['equity_before']:,.2f} -> {a['equity_after']:,.2f}"
            out.append(f"  {a['id']:<26} {a['stage']:<10} days {was:<7} equity {eq:<24} in Bitcoin {100 * (a['exposure'] or 0):.1f}%" + ("  HALTED" if a["halted"] else ""))
    out += [f"Files: {len(r['changed'])} changed, {len(r['added'])} added, {len(r['removed'])} removed" + (f" (new: {', '.join(r['added'][:3])})" if r["added"] else "")]
    out += [f"Note: {n}" for n in r["notes"]]
    out += ["Repeat run on the same input: " + ("state, ledgers and reports identical; only the dashboard's run-activity counters differ" if r["repeat_ok"] else "NOT identical (or not made)"),
            "Repository: " + ("unchanged (every file hash equal before and after)" if r["repo_unchanged"] else "CHANGED")]
    out += ["Result: " + ("no problems" if not r["problems"] else "PROBLEMS")] + [f"  - {p}" for p in r["problems"]]
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m atlas_api.btcquant.rehearse", description="Rehearse the next daily run on a throwaway copy (read-only on the repository).")
    p.add_argument("--candle", choices=("real", "fall", "rise"), default="real", help="the stand-in for the candle that has not closed: the day's own forming candle, 20%% lower or 20%% higher")
    p.add_argument("--move", type=float, default=None, help="a move in percent from the previous close (for example -5); overrides --candle")
    ns = p.parse_args(argv)
    try:
        result = rehearse(C.ROOT, ns.candle, ns.move)
    except RehearsalError as e:
        print(f"cannot rehearse: {e}", file=sys.stderr)
        return 2
    print("\n".join(report(result)))
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
