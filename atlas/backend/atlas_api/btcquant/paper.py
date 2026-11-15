"""btcquant paper engine (protocol section 9): persistent virtual accounts, one per challenger and per benchmark, stepped through each newly completed daily candle by the SAME account code the backtester uses.

Nothing here places an order anywhere: every trade is a line in a file. Each account keeps
  state/accounts/<id>.json   its full state (cash, Bitcoin quantity, stop, pending order, peak, circuit-breaker state, the equity curve and the closed trades), rewritten after every step batch
  state/ledger/<id>.jsonl    its ledger, append-only: an order row is written the moment a signal creates it ("on signal"), then the fill, rejection, stop-out or circuit-breaker rows when they happen
A run is idempotent (candles at or before the account's last processed bar are skipped) and refuses to step across a missing candle: a gap stops that account and says so, it is never papered over.
The account opens at the close of the latest complete candle: a rule already ON then may enter at the next open, which executes when the next candle completes (the 00:15 UTC run is modelled as if
orders were placed at the 00:00 open, protocol section 3).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import backtest as B
from . import config as C
from . import strategies as S
from .account import Account, make_account


class GapError(Exception):
    """A completed candle is missing between the last processed bar and the next one."""


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonable(x):
    """Python numbers only, so that a saved state round-trips exactly."""
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


class PaperBook:
    def __init__(self, root: Path | None = None, now=_now):
        self.root = Path(root) if root is not None else C.STATE_DIR
        self._now = now

    # ---- paths ----
    def account_path(self, account_id: str) -> Path:
        return self.root / "accounts" / f"{account_id}.json"

    def ledger_path(self, account_id: str) -> Path:
        return self.root / "ledger" / f"{account_id}.jsonl"

    def ids(self) -> list:
        d = self.root / "accounts"
        return sorted(p.stem for p in d.glob("*.json")) if d.exists() else []

    def exists(self, account_id: str) -> bool:
        return self.account_path(account_id).exists()

    # ---- persistence ----
    def save(self, account: Account, meta: dict) -> None:
        state = account.to_dict()
        state["curve"] = [list(r) for r in account.curve]
        state["trades"] = list(account.trades)
        self.account_path(meta["id"]).parent.mkdir(parents=True, exist_ok=True)
        self.account_path(meta["id"]).write_text(json.dumps({"meta": _jsonable(meta), "account": _jsonable(state)}, sort_keys=True) + "\n", encoding="utf-8")

    def load(self, account_id: str) -> tuple:
        raw = json.loads(self.account_path(account_id).read_text(encoding="utf-8"))
        st = dict(raw["account"])
        curve, trades = st.pop("curve", []), st.pop("trades", [])
        a = Account.from_dict(st)
        a.curve, a.trades, a.events = [tuple(r) for r in curve], list(trades), []
        a.verbose = True
        return a, raw["meta"]

    def _append_ledger(self, account_id: str, rows: list) -> None:
        if not rows:
            return
        p = self.ledger_path(account_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        seq = sum(1 for _ in p.open(encoding="utf-8")) if p.exists() else 0
        with p.open("a", encoding="utf-8") as fh:
            for r in rows:
                seq += 1
                fh.write(json.dumps({"seq": seq, "recorded_at": self._now(), **_jsonable(r)}, sort_keys=True) + "\n")

    def ledger(self, account_id: str) -> list:
        p = self.ledger_path(account_id)
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []

    # ---- opening an account ----
    def open(self, account_id: str, family: str, params: dict, prep: B.Prepared, *, at_index: int | None = None, start_equity: float = C.START_EQUITY_STRATEGY,
             cool_off_days: int | None = C.BREAKER_COOL_OFF_DAYS, stage: str = "challenger", version: int = 1) -> dict:
        """Create the account at the close of candle `at_index` (default: the latest complete candle) and write its first ledger rows. Refuses an id that already exists."""
        if self.exists(account_id):
            raise ValueError(f"the account {account_id} already exists")
        fam = S.FAMILIES[family]
        i = len(prep.candles) - 1 if at_index is None else at_index
        sig = prep.signals(fam, params) if fam.kind in ("stop", "weight") else None
        a = make_account(account_id, fam.kind, start_equity=start_equity, trail=fam.trail, cool_off_days=cool_off_days, verbose=True)
        a.begin(prep.candles[i], B._sig(prep, fam, sig, params, i, True), C.DAY)
        sp = S.spec(family, params, version)
        meta = {"id": account_id, "family": family, "params": params, "version": version, "spec": sp, "spec_hash": S.hash_spec(sp), "stage": stage, "opened_at": self._now(),
                "start_equity": start_equity, "cool_off_days": cool_off_days, "last_bar": int(prep.times[i]), "last_bar_iso": _iso(int(prep.times[i])), "opened_after_candle": _iso(int(prep.times[i]))}
        self._append_ledger(account_id, [{"event": "account_opened", "account": account_id, "family": family, "params": params, "spec_hash": meta["spec_hash"], "stage": stage,
                                          "start_equity": start_equity, "after_candle": meta["last_bar_iso"]}] + a.events)
        a.events = []
        self.save(a, meta)
        return meta

    # ---- stepping ----
    def catch_up(self, account_id: str, prep: B.Prepared, *, max_candles: int | None = None) -> dict:
        """Step the account through every completed candle after its last processed bar. Returns what happened. Raises GapError (after saving what was done) when the next completed candle is not the next day."""
        a, meta = self.load(account_id)
        fam, params = S.FAMILIES[meta["family"]], meta["params"]
        sig = prep.signals(fam, params) if fam.kind in ("stop", "weight") else None
        last = meta["last_bar"]
        start = int(np.searchsorted(prep.bars.t, last, side="right"))
        done, gap = 0, None
        for i in range(start, len(prep.candles)):
            if prep.times[i] != last + C.DAY:
                gap = (last, prep.times[i])
                break
            a.step(prep.candles[i], B._sig(prep, fam, sig, params, i, True), C.DAY)
            last = prep.times[i]
            done += 1
            if max_candles is not None and done >= max_candles:
                break
        new_rows = list(a.events)
        a.events = []
        meta["last_bar"], meta["last_bar_iso"] = int(last), _iso(int(last))
        self._append_ledger(account_id, new_rows)
        self.save(a, meta)
        if gap:
            raise GapError(f"{account_id}: the candle after {_iso(gap[0])} is missing (the next stored one is {_iso(gap[1])}); stopped there")
        return {"id": account_id, "processed": done, "events": len(new_rows), "last_bar": meta["last_bar_iso"], "equity": a.curve[-1][1] if a.curve else a.start_equity, "halted": a.halted}

    def catch_up_all(self, prep: B.Prepared) -> dict:
        """Every account; a gap or any other failure in one account is reported and does not stop the others."""
        out = {}
        for account_id in self.ids():
            try:
                out[account_id] = self.catch_up(account_id, prep)
            except GapError as e:
                out[account_id] = {"id": account_id, "error": str(e)}
        return out
