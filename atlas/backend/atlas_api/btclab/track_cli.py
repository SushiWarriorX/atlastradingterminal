"""Add a strategy to the tracker ledger: backtest it once on all BTC daily history up to today and freeze the result.

    python -m atlas_api.btclab.track_cli add <strategy_id> --idea "where the rule comes from" --why "why it is worth testing"
    python -m atlas_api.btclab.track_cli show

Downloads Coinbase daily candles into a temporary database (the app's own database is not touched). The strategy must already be registered in strategies.py with FIXED parameters.
"""
from __future__ import annotations

import argparse
import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..db import DB
from . import tracker as T
from .data import BtcData
from .strategies import S


async def _rows():
    with tempfile.TemporaryDirectory() as d:
        data = BtcData(DB(str(Path(d) / "t.db")))
        await data.refresh_bars("1d")
        return data.stored("1d")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("id")
    a.add_argument("--idea", required=True)
    a.add_argument("--why", required=True)
    sub.add_parser("show")
    args = ap.parse_args(argv)
    led = T.load()
    if args.cmd == "show":
        for e in led["entries"]:
            sn = e["snapshot"]
            print(e["added_at"], e["id"], sn["evidence"]["level"], "oos", round(sn["out_of_sample"]["net_return_pct"] or 0, 1), "full", round(sn["full"]["net_return_pct"] or 0, 1))
        return 0
    if args.id not in S:
        raise SystemExit(f"unknown strategy '{args.id}': register it in strategies.py first")
    if any(e["id"] == args.id for e in led["entries"]):
        raise SystemExit(f"'{args.id}' is already in the ledger; a frozen backtest is never rerun")
    rows = asyncio.run(_rows())
    st = S[args.id]
    entry = {"id": args.id, "name": st.name, "family": st.family, "added_at": datetime.now(timezone.utc).date().isoformat(), "idea": args.idea, "why": args.why, "snapshot": T.snapshot(args.id, rows)}
    led["entries"].append(entry)
    T.save(led)
    sn = entry["snapshot"]
    print(f"added {args.id}: evidence={sn['evidence']['level']} oos={sn['out_of_sample']['net_return_pct']:.1f}% full={sn['full']['net_return_pct']:.1f}% trades={sn['full']['trades']} data to {sn['data_to']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
