"""Paper-trading engine: portfolios, order lifecycle, fills, risk gate, reconciliation.

Execution safety: this engine is PAPER ONLY. There is no live broker adapter. The risk gate runs in this process at preview and again
at submit, an order needs a valid preview id (explicit confirmation) and an idempotency key, and a kill switch halts new orders.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .. import instruments as I
from ..db import DB, now as iso_now
from ..models import DataStatus, ProviderUnavailable
from ..service import MarketService
from ..brokers.ibkr import BrokerError, IBKRBroker
from ..sessions import NY, next_session_close, session_state
from . import risk, sim
from .accounting import AccountingError, Position, apply_fill
from .models import OrderIn, RiskLimits, SimParams
from .money import ZERO, D, floor_to, q, s

log = logging.getLogger("atlas.trading")
PREVIEW_TTL = 60.0
OPEN_STATES = ("pending_submit", "working", "partially_filled")
SKIP = {DataStatus.STALE, DataStatus.UNAVAILABLE}
TRADABLE = {"equity", "etf", "crypto"}


class EngineError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra or {}


def jsonable(x):
    """Decimals become exact strings (the UI parses them for display only)."""
    if isinstance(x, Decimal):
        return s(x)
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    return x


def _ts(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


class TradingEngine:
    def __init__(self, db: DB, svc: MarketService, clock=time.time, broker: IBKRBroker | None = None):
        self.db, self.svc, self.clock, self.broker = db, svc, clock, broker
        self._last_broker_sync: dict[int, float] = {}
        self._lock = asyncio.Lock()
        self._previews: dict[str, dict] = {}
        self.ensure_default()

    # --- settings ---------------------------------------------------------
    def limits(self) -> RiskLimits:
        return RiskLimits(**self.db.pref_get("risk_limits", {}))

    def set_limits(self, data: dict) -> RiskLimits:
        new = RiskLimits(**{**self.limits().model_dump(), **data})   # validates the merged result
        self.db.pref_set("risk_limits", new.model_dump())
        self.db.audit("user", "risk_limits_update", data)
        return new

    def sim_params(self) -> SimParams:
        return SimParams(**self.db.pref_get("sim_params", {}))

    def set_sim_params(self, data: dict) -> SimParams:
        new = SimParams(**{**self.sim_params().model_dump(), **data})
        self.db.pref_set("sim_params", new.model_dump())
        self.db.audit("user", "sim_params_update", data)
        return new

    def halted(self) -> bool:
        return bool(self.db.pref_get("trading_halted", False))

    async def set_halted(self, halted: bool, cancel_open: bool = False) -> dict:
        self.db.pref_set("trading_halted", halted)
        self.db.audit("user", "trading_halt" if halted else "trading_resume", {"cancel_open": cancel_open})
        cancelled = []
        if halted and cancel_open:
            async with self._lock:
                for o in self.db.q("SELECT id, venue, broker_order_id FROM orders WHERE state IN ('pending_submit','working','partially_filled')"):
                    if o["venue"] == "ibkr" and o["broker_order_id"]:
                        try:
                            await self.broker.cancel(o["broker_order_id"])
                            self._event(o["id"], "cancel_requested", "cancelled by kill switch")
                            cancelled.append(o["id"])
                        except BrokerError as e:
                            self._event(o["id"], "cancel_failed", f"{e.code}: {e.message}")
                        continue
                    self._cancel_locked(o["id"], "cancelled by kill switch")
                    cancelled.append(o["id"])
        return {"halted": halted, "cancelled_orders": cancelled}

    # --- portfolios -------------------------------------------------------
    def ensure_default(self) -> None:
        if not self.db.q("SELECT 1 FROM portfolios LIMIT 1"):
            self.create_portfolio("Paper", "paper", Decimal(100_000))

    def portfolios(self) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT * FROM portfolios ORDER BY id")]

    def portfolio(self, pid: int | None) -> dict:
        r = self.db.q("SELECT * FROM portfolios WHERE id=?", (pid,)) if pid else self.db.q("SELECT * FROM portfolios WHERE kind='paper' ORDER BY id LIMIT 1")
        if not r:
            raise EngineError("PORTFOLIO_NOT_FOUND", "portfolio not found", 404)
        return dict(r[0])

    def create_portfolio(self, name: str, kind: str, starting_cash: Decimal, venue: str = "sim", broker_account: str | None = None) -> dict:
        if kind not in ("paper", "manual"):
            raise EngineError("INVALID_REQUEST", "kind must be paper or manual", 422)
        if starting_cash < 0:
            raise EngineError("INVALID_REQUEST", "starting cash cannot be negative", 422)
        if self.db.q("SELECT 1 FROM portfolios WHERE name=?", (name,)):
            raise EngineError("DUPLICATE", "a portfolio with that name exists", 409)
        pid = self.db.x("INSERT INTO portfolios(name,kind,starting_cash,cash,created_at,venue,broker_account) VALUES(?,?,?,?,?,?,?)",
                        (name, kind, s(starting_cash), s(starting_cash), iso_now(), venue, broker_account))
        self.db.audit("user", "portfolio_create", {"id": pid, "kind": kind, "venue": venue})
        return self.portfolio(pid)

    def positions(self, pid: int) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT * FROM positions WHERE portfolio_id=? AND CAST(qty AS REAL) > 0 ORDER BY symbol", (pid,))]

    # manual holdings: user-entered, never invented
    def set_manual_position(self, pid: int, instrument_id: str, qty: Decimal, avg_cost: Decimal) -> None:
        pf = self.portfolio(pid)
        if pf["kind"] != "manual" or pf["venue"] != "sim":
            raise EngineError("NOT_MANUAL", "holdings can only be edited directly on a manual portfolio (broker-linked accounts are read from the broker)", 409)
        inst = I.resolve(instrument_id)
        if inst is None or inst.asset_class not in TRADABLE:
            raise EngineError("UNKNOWN_INSTRUMENT", f"unknown or non-holdable instrument '{instrument_id}'", 404)
        if qty < 0 or avg_cost < 0:
            raise EngineError("INVALID_REQUEST", "qty and avg_cost cannot be negative", 422)
        if qty == 0:
            self.db.x("DELETE FROM positions WHERE portfolio_id=? AND instrument_id=?", (pid, inst.id))
        else:
            self.db.x("INSERT INTO positions(portfolio_id,instrument_id,symbol,qty,avg_cost) VALUES(?,?,?,?,?) ON CONFLICT(portfolio_id,instrument_id) "
                      "DO UPDATE SET qty=excluded.qty, avg_cost=excluded.avg_cost", (pid, inst.id, inst.symbol, s(qty), s(avg_cost)))
        self.db.audit("user", "manual_position", {"pid": pid, "instrument": inst.id, "qty": s(qty)})

    def set_manual_cash(self, pid: int, cash: Decimal) -> None:
        pf = self.portfolio(pid)
        if pf["kind"] != "manual" or pf["venue"] != "sim":
            raise EngineError("NOT_MANUAL", "cash can only be edited directly on a manual portfolio (broker-linked accounts are read from the broker)", 409)
        if cash < 0:
            raise EngineError("INVALID_REQUEST", "cash cannot be negative", 422)
        self.db.x("UPDATE portfolios SET cash=? WHERE id=?", (s(cash), pid))
        self.db.audit("user", "manual_cash", {"pid": pid, "cash": s(cash)})

    def reset_paper(self, pid: int) -> dict:
        pf = self.portfolio(pid)
        if pf["kind"] != "paper" or pf["venue"] != "sim":
            raise EngineError("NOT_PAPER", "only simulated paper portfolios can be reset (broker-linked accounts are read from the broker)", 409)
        with self.db.tx() as c:
            for t in ("fills", "order_events"):
                c.execute(f"DELETE FROM {t} WHERE order_id IN (SELECT id FROM orders WHERE portfolio_id=?)", (pid,))
            for t in ("orders", "positions", "equity_history"):
                c.execute(f"DELETE FROM {t} WHERE portfolio_id=?", (pid,))
            c.execute("UPDATE portfolios SET cash=starting_cash WHERE id=?", (pid,))
        self.db.audit("user", "paper_reset", {"pid": pid})
        return self.portfolio(pid)

    # --- valuation --------------------------------------------------------
    async def _quote(self, inst):
        try:
            return await self.svc.quote(inst)
        except ProviderUnavailable:
            return None

    async def valuation(self, pid: int) -> dict:
        pf = self.portfolio(pid)
        rows = self.positions(pf["id"])
        insts = [I.resolve(r["instrument_id"]) for r in rows]
        quotes = await asyncio.gather(*(self._quote(i) if i else asyncio.sleep(0) for i in insts))
        pos, invested, unpriced = [], ZERO, 0
        for r, i, qt in zip(rows, insts, quotes):
            qty, avg = D(r["qty"]), D(r["avg_cost"])
            priced = qt is not None and qt.prov.status != DataStatus.UNAVAILABLE
            mark = D(qt.price) if priced else None
            value = qty * (mark if mark is not None else avg)
            unpriced += 0 if priced else 1
            invested += value
            ps = D(r["planned_stop"]) if r["planned_stop"] else None
            pos.append({
                "instrument_id": r["instrument_id"], "symbol": r["symbol"], "asset_class": i.asset_class if i else "unknown", "sector": _sector(i),
                "qty": qty, "avg_cost": avg, "mark": mark, "value": value, "valuation": "mark" if priced else "at_cost",
                "unrealized": qty * (mark - avg) if mark is not None else None,
                "unrealized_pct": ((mark / avg - 1) * 100) if mark is not None and avg > 0 else None,
                "day_pnl": qty * D(qt.change) if priced and qt.change is not None else None,
                "realized": D(r["realized"]), "planned_stop": ps,
                "planned_risk": qty * (mark - ps) if (ps is not None and mark is not None and mark > ps) else (ZERO if ps is not None else None),
                "data": {"status": qt.prov.status.value, "provider": qt.prov.provider, "event_time": qt.prov.event_time.isoformat() if qt.prov.event_time else None} if qt else None,
            })
        cash = D(pf["cash"])
        equity = cash + invested
        for p in pos:
            p["weight_pct"] = (p["value"] / equity * 100) if equity > 0 else None
        exp: dict[str, dict] = {"asset_class": {}, "sector": {}}
        for p in pos:
            for k, key in (("asset_class", p["asset_class"]), ("sector", p["sector"])):
                exp[k][key] = exp[k].get(key, ZERO) + p["value"]
        gross = sum((p["value"] for p in pos), ZERO)
        return {
            "portfolio": pf, "cash": cash, "invested": invested, "equity": equity, "positions": pos,
            "unpriced_positions": unpriced, "realized_total": sum((p["realized"] for p in pos), ZERO),
            "unrealized_total": sum((p["unrealized"] for p in pos if p["unrealized"] is not None), ZERO),
            "day_pnl_total": sum((p["day_pnl"] for p in pos if p["day_pnl"] is not None), ZERO),
            "exposure": {"gross": gross, "net": gross, "gross_pct": (gross / equity * 100) if equity > 0 else None, "leverage": (gross / equity) if equity > 0 else None,
                         "by_asset_class": {k: {"value": v, "pct": (v / equity * 100) if equity > 0 else None} for k, v in exp["asset_class"].items()},
                         "by_sector": {k: {"value": v, "pct": (v / equity * 100) if equity > 0 else None} for k, v in exp["sector"].items()},
                         "largest_position_pct": max((p["weight_pct"] for p in pos if p["weight_pct"] is not None), default=None)},
            "valuation_note": f"{unpriced} position(s) valued at cost because no price was available: equity is approximate." if unpriced else None,
        }

    def snapshot_equity_value(self, pid: int, equity: Decimal, cash: Decimal, min_gap: float = 60.0) -> bool:
        last = self.db.q("SELECT ts FROM equity_history WHERE portfolio_id=? ORDER BY ts DESC LIMIT 1", (pid,))
        now = self.clock()
        if last and now - datetime.fromisoformat(last[0]["ts"]).timestamp() < min_gap:
            return False
        self.db.x("INSERT OR IGNORE INTO equity_history VALUES(?,?,?,?)", (pid, _ts(now), s(equity), s(cash)))
        return True

    def day_start_equity(self, pid: int) -> Decimal | None:
        d0 = datetime.fromtimestamp(self.clock(), timezone.utc).astimezone(NY).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        r = self.db.q("SELECT equity FROM equity_history WHERE portfolio_id=? AND ts>=? ORDER BY ts LIMIT 1", (pid, d0.isoformat()))
        return D(r[0]["equity"]) if r else None

    # --- risk context + preview ------------------------------------------
    def _reserved(self, pid: int, instrument_id: str | None = None) -> tuple[Decimal, Decimal]:
        """(cash reserved by working buys, qty reserved by working sells for instrument_id)."""
        cash = qty = ZERO
        for o in self.db.q("SELECT * FROM orders WHERE portfolio_id=? AND state IN ('pending_submit','working','partially_filled')", (pid,)):
            rem = D(o["qty"]) - D(o["filled_qty"])
            if o["side"] == "buy":
                cash += rem * D(o["est_price"])
            elif instrument_id and o["instrument_id"] == instrument_id:
                qty += rem
        return cash, qty

    def _fee(self, inst, qty: Decimal, price: Decimal) -> Decimal:
        return sim.fee_for(inst.asset_class, qty, price, self.sim_params())

    async def _context(self, pf: dict, inst, o: OrderIn) -> risk.RiskContext:
        val = await self.valuation(pf["id"])
        quote = await self._quote(inst)
        held = next((p for p in val["positions"] if p["instrument_id"] == inst.id), None)
        res_cash, res_qty = self._reserved(pf["id"], inst.id)
        other = sum((p["planned_risk"] for p in val["positions"] if p["planned_risk"] is not None), ZERO)
        unq = sum(1 for p in val["positions"] if p["planned_stop"] is None)
        since = _ts(self.clock() - 60)
        dup = self.db.q("SELECT COUNT(*) FROM orders WHERE portfolio_id=? AND instrument_id=? AND side=? AND type=? AND qty=? AND state IN ('pending_submit','working','partially_filled') AND created_at>=?",
                        (pf["id"], inst.id, o.side, o.type, s(o.qty), since))[0][0]
        return risk.RiskContext(
            limits=self.limits(), sim=self.sim_params(), halted=self.halted(), asset_class=inst.asset_class, tradable=inst.asset_class in TRADABLE, symbol=inst.symbol,
            quote=quote, session=session_state(datetime.fromtimestamp(self.clock(), timezone.utc))["state"] if inst.is_equity_like else None,
            equity=val["equity"], cash_available=val["cash"] - res_cash, sellable_qty=(held["qty"] if held else ZERO) - res_qty,
            position_value=held["value"] if held else ZERO, other_planned_risk=other, unquantified_positions=unq,
            day_start_equity=self.day_start_equity(pf["id"]), duplicate_working=dup, valuation_note=val["valuation_note"],
            venue=pf["venue"], venue_block=("the IBKR adapter trades US stocks and ETFs only" if pf["venue"] == "ibkr" and inst.asset_class not in ("equity", "etf") else None))

    def _normalize(self, o: OrderIn, inst) -> OrderIn:
        return o.model_copy(update={"instrument_id": inst.id})

    def _resolve(self, o: OrderIn):
        inst = I.resolve(o.instrument_id)
        if inst is None:
            raise EngineError("UNKNOWN_INSTRUMENT", f"unknown instrument '{o.instrument_id}'", 404)
        pf = self.portfolio(o.portfolio_id)
        if pf["kind"] != "paper":
            raise EngineError("MANUAL_PORTFOLIO", "orders can only be placed on a paper portfolio; manual and read-only broker portfolios cannot trade", 409)
        if pf["venue"] == "ibkr" and not (self.broker and self.broker.can_trade):
            raise EngineError("BROKER_READONLY", "this portfolio is linked to IBKR but the connection cannot place orders (not connected, read-only, or not a paper account)", 409)
        return pf, inst

    @staticmethod
    def _hash(o: OrderIn, pid: int) -> str:
        d = {k: (s(v) if isinstance(v, Decimal) else v) for k, v in o.model_dump().items() if k != "portfolio_id"}
        return hashlib.sha256(json.dumps({**d, "pid": pid}, sort_keys=True).encode()).hexdigest()

    async def preview(self, o: OrderIn) -> dict:
        pf, inst = self._resolve(o)
        o = self._normalize(o, inst)
        ctx = await self._context(pf, inst, o)
        r = risk.check(o, ctx, lambda qty, price: self._fee(inst, qty, price))
        est = r["estimate"]
        pid_ = str(uuid.uuid4())
        self._previews = {k: v for k, v in self._previews.items() if v["exp"] > self.clock()}
        self._previews[pid_] = {"hash": self._hash(o, pf["id"]), "exp": self.clock() + PREVIEW_TTL, "verdict": r["verdict"]}
        after_cash = ctx.cash_available - (est["notional"] + est["fee"]) if (o.side == "buy" and est["notional"] is not None) else None
        return jsonable({
            "preview_id": pid_, "expires_in_seconds": PREVIEW_TTL, "requires_confirmation": True, "portfolio_id": pf["id"],
            "order": {**o.model_dump(), "symbol": inst.symbol}, "verdict": r["verdict"], "checks": r["checks"], "disclaimer": r["disclaimer"],
            "estimate": {"price": est["price"], "notional": est["notional"], "fee": est["fee"], "total_cost": (est["notional"] + est["fee"]) if est["notional"] is not None else None,
                         "cash_available_before": ctx.cash_available, "cash_available_after": after_cash},
            "environment": "paper", "data": {"status": ctx.quote.prov.status.value, "provider": ctx.quote.prov.provider} if ctx.quote else None,
            "simulator": "Paper fills are simulated from polled quotes with assumed spread, slippage and fees; real execution would differ."})

    # --- submit / cancel --------------------------------------------------
    def _order_row(self, oid: int) -> dict:
        r = self.db.q("SELECT * FROM orders WHERE id=?", (oid,))
        if not r:
            raise EngineError("ORDER_NOT_FOUND", "order not found", 404)
        return dict(r[0])

    def _event(self, oid: int, event: str, detail: dict | str = "", throttle: bool = False) -> None:
        d = detail if isinstance(detail, str) else json.dumps(detail, default=str)
        if throttle:
            last = self.db.q("SELECT event, detail FROM order_events WHERE order_id=? ORDER BY id DESC LIMIT 1", (oid,))
            if last and last[0]["event"] == event and last[0]["detail"] == d:
                return
        self.db.x("INSERT INTO order_events(order_id,ts,event,detail) VALUES(?,?,?,?)", (oid, _ts(self.clock()), event, d))

    async def submit(self, o: OrderIn, preview_id: str | None, client_key: str | None) -> dict:
        if not client_key or len(client_key) < 8:
            raise EngineError("IDEMPOTENCY_KEY_REQUIRED", "client_key (min 8 chars) is required so a retry can never create a second order", 422)
        pf, inst = self._resolve(o)
        o = self._normalize(o, inst)
        async with self._lock:
            ex = self.db.q("SELECT id FROM orders WHERE portfolio_id=? AND client_key=?", (pf["id"], client_key))
            if ex:
                return jsonable({"order": self._order_view(self._order_row(ex[0]["id"])), "duplicate": True})
            prev = self._previews.get(preview_id or "")
            if prev is None:
                raise EngineError("PREVIEW_REQUIRED", "preview the order first and confirm it with the returned preview_id", 409)
            if prev["exp"] < self.clock():
                self._previews.pop(preview_id, None)
                raise EngineError("PREVIEW_EXPIRED", "the preview expired: preview again so risk is re-checked on fresh data", 409)
            if prev["hash"] != self._hash(o, pf["id"]):
                raise EngineError("PREVIEW_MISMATCH", "the order differs from the one that was previewed", 409)
            ctx = await self._context(pf, inst, o)
            r = risk.check(o, ctx, lambda qty, price: self._fee(inst, qty, price))     # re-run: state may have changed since the preview
            if r["verdict"] != "APPROVE_FOR_PAPER_REVIEW":
                raise EngineError("RISK_REJECTED", f"risk gate: {r['verdict']}", 422, {"verdict": r["verdict"], "checks": jsonable(r["checks"])})
            self._previews.pop(preview_id, None)
            now = self.clock()
            expires = None
            if o.tif == "DAY":
                expires = next_session_close(datetime.fromtimestamp(now, timezone.utc)) if inst.is_equity_like else \
                    (datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
            oid = self.db.x(
                "INSERT INTO orders(portfolio_id,client_key,instrument_id,symbol,side,type,tif,qty,limit_price,stop_price,planned_stop,est_price,state,data_status,created_at,updated_at,expires_at,venue) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pf["id"], client_key, inst.id, inst.symbol, o.side, o.type, o.tif, s(o.qty), s(o.limit_price) if o.limit_price else None, s(o.stop_price) if o.stop_price else None,
                 s(o.planned_stop) if o.planned_stop else None, s(r["estimate"]["price"]), "pending_submit" if pf["venue"] == "ibkr" else "working",
                 ctx.quote.prov.status.value if ctx.quote else None, _ts(now), _ts(now), expires.isoformat() if expires else None, pf["venue"]))
            self._event(oid, "accepted", {"verdict": r["verdict"], "est_price": s(r["estimate"]["price"])})
            self.db.audit("user", "paper_order", {"id": oid, "symbol": inst.symbol, "side": o.side, "qty": s(o.qty), "type": o.type})
            if pf["venue"] == "ibkr":
                await self._broker_place(self._order_row(oid), inst, o)
            else:
                await self._evaluate_order(self._order_row(oid))
            return jsonable({"order": self._order_view(self._order_row(oid)), "duplicate": False, "risk": {"verdict": r["verdict"], "checks": r["checks"]}})

    def _cancel_locked(self, oid: int, reason: str = "cancelled by user") -> dict:
        o = self._order_row(oid)
        if o["state"] not in OPEN_STATES:
            raise EngineError("ORDER_NOT_CANCELABLE", f"order is {o['state']} and cannot be cancelled", 409)
        self.db.x("UPDATE orders SET state='cancelled', reason=?, updated_at=? WHERE id=?", (reason, _ts(self.clock()), oid))
        self._event(oid, "cancelled", reason)
        self.db.audit("user", "paper_cancel", {"id": oid})
        return self._order_row(oid)

    async def cancel(self, oid: int) -> dict:
        async with self._lock:
            o = self._order_row(oid)
            if o["venue"] == "ibkr":
                if o["state"] not in OPEN_STATES:
                    raise EngineError("ORDER_NOT_CANCELABLE", f"order is {o['state']} and cannot be cancelled", 409)
                if not o["broker_order_id"]:
                    return jsonable(self._order_view(self._cancel_locked(oid, "cancelled before reaching IBKR")))
                try:
                    await self.broker.cancel(o["broker_order_id"])
                except BrokerError as e:
                    raise EngineError(e.code, e.message, 502)
                self._event(oid, "cancel_requested", "cancel sent to IBKR; the final state comes from the broker")
                self.db.audit("user", "ibkr_cancel", {"id": oid})
                await self._sync_broker_order(self._order_row(oid))
                return jsonable(self._order_view(self._order_row(oid)))
            return jsonable(self._order_view(self._cancel_locked(oid)))

    # --- fills ------------------------------------------------------------
    def _order_view(self, r: dict) -> dict:
        ev = self.db.q("SELECT ts,event,detail FROM order_events WHERE order_id=? ORDER BY id", (r["id"],))
        return {**r, "events": [dict(e) for e in ev], "remaining_qty": s(D(r["qty"]) - D(r["filled_qty"]))}

    async def _evaluate_order(self, o: dict) -> bool:
        """Try to fill one open order against the latest quote. Returns True if anything changed."""
        if o["state"] not in OPEN_STATES:
            return False
        if o["venue"] == "ibkr":
            return await self._sync_broker_order(o)
        oid, now = o["id"], self.clock()
        if o["expires_at"] and now >= datetime.fromisoformat(o["expires_at"]).timestamp():
            self.db.x("UPDATE orders SET state='expired', reason='time in force (DAY) elapsed', updated_at=? WHERE id=?", (_ts(now), oid))
            self._event(oid, "expired", "DAY order reached the end of its session")
            return True
        inst = I.resolve(o["instrument_id"])
        if inst is None:
            return False
        if inst.is_equity_like:
            st = session_state(datetime.fromtimestamp(now, timezone.utc))["state"]
            if st != "REGULAR":
                self._event(oid, "waiting", f"US market is {st}: equity orders fill only in the regular session", throttle=True)
                return False
        qt = await self._quote(inst)
        if qt is None or qt.prov.status in SKIP:
            self._event(oid, "skipped_no_fresh_data", f"no fresh price ({qt.prov.status.value if qt else 'unavailable'}): no fill is simulated on stale data", throttle=True)
            return False
        p = self.sim_params()
        rem = D(o["qty"]) - D(o["filled_qty"])
        dec = sim.decide({"side": o["side"], "type": o["type"], "qty_remaining": rem, "limit_price": D(o["limit_price"]) if o["limit_price"] else None,
                          "stop_price": D(o["stop_price"]) if o["stop_price"] else None, "triggered": bool(o["triggered"])},
                         qt, inst.asset_class, p, self.limits().allow_fractional_equities)
        if dec is None:
            return False
        if dec.triggered:
            self.db.x("UPDATE orders SET triggered=1, updated_at=? WHERE id=?", (_ts(now), oid))
            self._event(oid, "triggered", f"stop {o['stop_price']} hit at last {qt.price}")
        if dec.qty <= 0:
            return dec.triggered
        try:
            self._apply_fill(o, inst, dec, qt)
        except AccountingError as e:
            self.db.x("UPDATE orders SET state='rejected', reason=?, updated_at=? WHERE id=?", (str(e), _ts(now), oid))
            self._event(oid, "rejected", str(e))
            return True
        return True

    def _apply_fill(self, o: dict, inst, dec: sim.Decision, qt) -> None:
        now = _ts(self.clock())
        with self.db.tx() as c:
            pf = c.execute("SELECT cash FROM portfolios WHERE id=?", (o["portfolio_id"],)).fetchone()
            pr = c.execute("SELECT * FROM positions WHERE portfolio_id=? AND instrument_id=?", (o["portfolio_id"], o["instrument_id"])).fetchone()
            pos = Position(D(pr["qty"]), D(pr["avg_cost"]), D(pr["realized"])) if pr else Position()
            new_pos, new_cash = apply_fill(pos, D(pf["cash"]), o["side"], dec.qty, dec.price, dec.fee)
            stop = o["planned_stop"] if (o["side"] == "buy" and o["planned_stop"]) else (pr["planned_stop"] if pr else None)
            c.execute("INSERT INTO positions(portfolio_id,instrument_id,symbol,qty,avg_cost,realized,planned_stop) VALUES(?,?,?,?,?,?,?) "
                      "ON CONFLICT(portfolio_id,instrument_id) DO UPDATE SET qty=excluded.qty, avg_cost=excluded.avg_cost, realized=excluded.realized, planned_stop=excluded.planned_stop",
                      (o["portfolio_id"], o["instrument_id"], o["symbol"], s(new_pos.qty), s(new_pos.avg_cost), s(new_pos.realized), stop if new_pos.qty > 0 else None))
            c.execute("UPDATE portfolios SET cash=? WHERE id=?", (s(new_cash), o["portfolio_id"]))
            filled = D(o["filled_qty"]) + dec.qty
            avg = (D(o["filled_qty"]) * D(o["avg_fill_price"] or 0) + dec.qty * dec.price) / filled
            state = "filled" if filled >= D(o["qty"]) else "partially_filled"
            c.execute("UPDATE orders SET filled_qty=?, avg_fill_price=?, state=?, updated_at=? WHERE id=?", (s(filled), s(avg), state, now, o["id"]))
            c.execute("INSERT INTO fills(order_id,portfolio_id,instrument_id,symbol,side,qty,price,fee,ts,data_status,provider,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (o["id"], o["portfolio_id"], o["instrument_id"], o["symbol"], o["side"], s(dec.qty), s(dec.price), s(dec.fee), now, qt.prov.status.value, qt.prov.provider, dec.note))
            c.execute("INSERT INTO order_events(order_id,ts,event,detail) VALUES(?,?,?,?)",
                      (o["id"], now, "fill" if state == "filled" else "partial_fill", json.dumps({"qty": s(dec.qty), "price": s(dec.price), "fee": s(dec.fee), "note": dec.note})))

    async def evaluate(self) -> int:
        """One pass over every open order (called by the background loop, and after submissions). Also samples equity history."""
        changed = 0
        async with self._lock:
            for o in self.db.q("SELECT * FROM orders WHERE state IN ('pending_submit','working','partially_filled') ORDER BY id"):
                try:
                    changed += bool(await self._evaluate_order(dict(o)))
                except Exception:  # noqa: BLE001  one bad order must not stop the others
                    log.exception("order %s evaluation failed", o["id"])
            # IBKR reports commissions after the fill: keep re-reading recently FILLED broker orders that still have a zero-fee fill
            grace = _ts(self.clock() - 300)
            for o in self.db.q("SELECT * FROM orders WHERE venue='ibkr' AND state='filled' AND broker_order_id IS NOT NULL AND updated_at>=? "
                               "AND EXISTS (SELECT 1 FROM fills f WHERE f.order_id=orders.id AND CAST(f.fee AS REAL)=0)", (grace,)):
                try:
                    await self._sync_broker_order(dict(o))
                except Exception:  # noqa: BLE001
                    log.exception("fee refresh failed for order %s", o["id"])
        for pf in self.portfolios():
            try:
                if pf["venue"] == "ibkr" and self.broker and self.broker.connected and self.clock() - self._last_broker_sync.get(pf["id"], 0) >= 15:
                    self._last_broker_sync[pf["id"]] = self.clock()
                    await self.sync_broker_portfolio(pf["id"])
                v = await self.valuation(pf["id"])
                if v["positions"] and v["unpriced_positions"] == 0 or not v["positions"]:
                    self.snapshot_equity_value(pf["id"], v["equity"], v["cash"])
            except Exception:  # noqa: BLE001
                log.exception("equity snapshot failed for %s", pf["id"])
        return changed

    async def run_loop(self, seconds: float) -> None:
        while True:
            try:
                await self.evaluate()
            except Exception:  # noqa: BLE001
                log.exception("trading loop iteration failed")
            await asyncio.sleep(seconds)

    # --- IBKR ----------------------------------------------------------------
    async def link_ibkr_portfolio(self, name: str) -> dict:
        if not (self.broker and self.broker.connected):
            raise EngineError("NOT_CONNECTED", "connect to IBKR first (Settings)", 409)
        kind = "paper" if self.broker.can_trade else "manual"      # a read-only (possibly live) account can be viewed but never traded
        cash = (await self.broker.summary())["cash"]
        pf = self.create_portfolio(name, kind, cash, venue="ibkr", broker_account=self.broker.account)
        await self.sync_broker_portfolio(pf["id"])
        return self.portfolio(pf["id"])

    async def sync_broker_portfolio(self, pid: int) -> dict:
        """Broker is the source of truth for cash and positions of a linked portfolio."""
        pf = self.portfolio(pid)
        if pf["venue"] != "ibkr" or not (self.broker and self.broker.connected):
            raise EngineError("NOT_CONNECTED", "portfolio is not linked to a connected IBKR session", 409)
        if self.broker.account != pf["broker_account"]:
            raise EngineError("ACCOUNT_MISMATCH", "the connected IBKR account differs from the one this portfolio was linked to", 409)
        try:
            summ, poss = await self.broker.summary(), await self.broker.positions()
        except BrokerError as e:
            raise EngineError(e.code, e.message, 502)
        unsupported, keep = [], {}
        for p in poss:
            if p["sec_type"] != "STK":
                unsupported.append(f"{p['symbol']} ({p['sec_type']})")
                continue
            inst = I.by_symbol(p["symbol"]) or I.adhoc(p["symbol"])
            if inst is None:
                unsupported.append(f"{p['symbol']} (symbol not recognised)")
                continue
            keep[inst.id] = (inst.symbol, p["qty"], p["avg_cost"])
        with self.db.tx() as c:
            c.execute("UPDATE portfolios SET cash=? WHERE id=?", (s(summ["cash"]), pid))
            old = {r["instrument_id"]: r["planned_stop"] for r in c.execute("SELECT instrument_id, planned_stop FROM positions WHERE portfolio_id=?", (pid,))}
            c.execute("DELETE FROM positions WHERE portfolio_id=?", (pid,))
            for iid, (sym, qty, avg) in keep.items():
                c.execute("INSERT INTO positions(portfolio_id,instrument_id,symbol,qty,avg_cost,realized,planned_stop) VALUES(?,?,?,?,?,'0',?)", (pid, iid, sym, s(qty), s(avg), old.get(iid)))
        return {"portfolio_id": pid, "cash": s(summ["cash"]), "positions": len(keep), "unsupported": unsupported}

    async def _broker_place(self, o: dict, inst, order: OrderIn) -> None:
        oid = o["id"]
        try:
            res = await self.broker.place_order(symbol=inst.symbol, side=order.side, qty=order.qty, type=order.type, tif=order.tif,
                                                limit_price=order.limit_price, stop_price=order.stop_price, client_key=o["client_key"])
        except BrokerError as e:
            self.db.x("UPDATE orders SET state='rejected', reason=?, updated_at=? WHERE id=?", (f"{e.code}: {e.message}", _ts(self.clock()), oid))
            self._event(oid, "rejected", f"{e.code}: {e.message}")
            self.db.audit("system", "ibkr_order_rejected", {"id": oid, "code": e.code})
            raise EngineError("BROKER_REJECTED", e.message, 502, {"code": e.code, "order_id": oid})
        self.db.x("UPDATE orders SET broker_order_id=?, state='working', updated_at=? WHERE id=?", (res["broker_order_id"], _ts(self.clock()), oid))
        self._event(oid, "sent_to_ibkr", {"broker_order_id": res["broker_order_id"], "status": res["status"], "adopted": res["adopted"]})
        self.db.audit("user", "ibkr_order", {"id": oid, "broker_order_id": res["broker_order_id"]})
        await self._sync_broker_order(self._order_row(oid))

    async def _sync_broker_order(self, o: dict) -> bool:
        oid, now = o["id"], self.clock()
        b = self.broker
        if b is None or not b.connected:
            self._event(oid, "waiting_for_broker", "not connected to IBKR: the order state is unknown until it reconnects", throttle=True)
            return False
        try:
            if not o["broker_order_id"]:
                found = await b.find_by_ref(o["client_key"])
                if found:
                    self.db.x("UPDATE orders SET broker_order_id=?, state='working', updated_at=? WHERE id=?", (found["broker_order_id"], _ts(now), oid))
                    self._event(oid, "adopted", "found at IBKR by its order reference")
                    return True
                if now - datetime.fromisoformat(o["created_at"]).timestamp() > 30:
                    self.db.x("UPDATE orders SET state='rejected', reason='never reached IBKR (no order with this reference exists there)', updated_at=? WHERE id=?", (_ts(now), oid))
                    self._event(oid, "rejected", "never reached IBKR")
                    return True
                return False
            st = await b.order_status(o["broker_order_id"])
        except BrokerError as e:
            self._event(oid, "broker_error", f"{e.code}: {e.message}", throttle=True)
            return False
        changed = False
        with self.db.tx() as c:
            for f in st["fills"]:
                cur = c.execute("INSERT OR IGNORE INTO fills(order_id,portfolio_id,instrument_id,symbol,side,qty,price,fee,ts,data_status,provider,note,ext_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (oid, o["portfolio_id"], o["instrument_id"], o["symbol"], f["side"], s(f["qty"]), s(f["price"]), s(f["fee"]), f["ts"].isoformat(), "BROKER", "ibkr",
                                 "executed at IBKR (paper account)", f["exec_id"]))
                if cur.rowcount:
                    changed = True
                    c.execute("INSERT INTO order_events(order_id,ts,event,detail) VALUES(?,?,?,?)", (oid, _ts(now), "fill", json.dumps({"qty": s(f["qty"]), "price": s(f["price"]), "exec_id": f["exec_id"]})))
                elif f["fee"] > 0:      # IBKR reports commissions after the fill: fill in a missing fee, never overwrite a real one
                    c.execute("UPDATE fills SET fee=? WHERE portfolio_id=? AND ext_id=? AND CAST(fee AS REAL)=0", (s(f["fee"]), o["portfolio_id"], f["exec_id"]))
            new_state = st["state"]
            if (new_state, s(st["filled"])) != (o["state"], s(D(o["filled_qty"]))) or changed:
                c.execute("UPDATE orders SET state=?, filled_qty=?, avg_fill_price=?, updated_at=?, reason=? WHERE id=?",
                          (new_state, s(st["filled"]), s(st["avg_price"]) if st["avg_price"] else None, _ts(now),
                           f"IBKR status: {st['status']}" if new_state in ("cancelled", "rejected") else o["reason"], oid))
                c.execute("INSERT INTO order_events(order_id,ts,event,detail) VALUES(?,?,?,?)", (oid, _ts(now), "state", f"{new_state} (IBKR status {st['status']})"))
                changed = True
        return changed

    # --- queries ----------------------------------------------------------
    def orders(self, pid: int | None = None, state: str | None = None, limit: int = 100) -> list[dict]:
        pf = self.portfolio(pid)["id"]
        sql, args = "SELECT * FROM orders WHERE portfolio_id=?", [pf]
        if state == "open":
            sql += " AND state IN ('pending_submit','working','partially_filled')"
        elif state:
            sql += " AND state=?"
            args.append(state)
        return jsonable([self._order_view(dict(r)) for r in self.db.q(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))])

    def fills(self, pid: int | None = None, limit: int = 100) -> list[dict]:
        pf = self.portfolio(pid)["id"]
        return [dict(r) for r in self.db.q("SELECT * FROM fills WHERE portfolio_id=? ORDER BY id DESC LIMIT ?", (pf, limit))]

    def reconcile(self, pid: int) -> dict:
        """Recompute cash and positions from the fill ledger and compare with the stored state."""
        pf = self.portfolio(pid)
        if pf["kind"] != "paper" or pf["venue"] != "sim":
            return {"portfolio_id": pid, "applicable": False, "reason": "only simulated paper portfolios have a local ledger (broker accounts are read from IBKR)"}
        cash, pos = D(pf["starting_cash"]), {}
        for f in self.db.q("SELECT * FROM fills WHERE portfolio_id=? ORDER BY id", (pid,)):
            p = pos.get(f["instrument_id"], Position())
            p, cash = apply_fill(p, cash, f["side"], D(f["qty"]), D(f["price"]), D(f["fee"]))
            pos[f["instrument_id"]] = p
        issues = []
        if cash != D(pf["cash"]):
            issues.append({"what": "cash", "ledger": s(cash), "stored": pf["cash"]})
        stored = {r["instrument_id"]: r for r in self.db.q("SELECT * FROM positions WHERE portfolio_id=?", (pid,))}
        for iid in set(pos) | set(stored):
            lp, sp = pos.get(iid, Position()), stored.get(iid)
            sq, sa, sr = (D(sp["qty"]), D(sp["avg_cost"]), D(sp["realized"])) if sp else (ZERO, ZERO, ZERO)
            if (lp.qty, lp.avg_cost if lp.qty else ZERO, lp.realized) != (sq, sa if sq else ZERO, sr):
                issues.append({"what": f"position {iid}", "ledger": {"qty": s(lp.qty), "avg_cost": s(lp.avg_cost), "realized": s(lp.realized)},
                               "stored": {"qty": s(sq), "avg_cost": s(sa), "realized": s(sr)}})
        bad_orders = [o["id"] for o in self.db.q("SELECT o.id FROM orders o LEFT JOIN (SELECT order_id, SUM(CAST(qty AS REAL)) q FROM fills GROUP BY order_id) f ON f.order_id=o.id "
                                                  "WHERE portfolio_id=? AND ABS(CAST(o.filled_qty AS REAL) - COALESCE(f.q,0)) > 1e-9", (pid,))]
        if bad_orders:
            issues.append({"what": "order filled_qty vs fills", "orders": bad_orders})
        return {"portfolio_id": pid, "applicable": True, "consistent": not issues, "issues": issues, "fills_checked": self.db.q("SELECT COUNT(*) FROM fills WHERE portfolio_id=?", (pid,))[0][0]}

    async def size(self, pid: int | None, instrument_id: str, entry: Decimal, stop: Decimal, risk_pct: float | None = None) -> dict:
        pf = self.portfolio(pid)
        inst = I.resolve(instrument_id)
        if inst is None or inst.asset_class not in TRADABLE:
            raise EngineError("UNKNOWN_INSTRUMENT", f"unknown or non-tradable instrument '{instrument_id}'", 404)
        if not (entry > 0 and 0 < stop < entry):
            raise EngineError("INVALID_REQUEST", "for a long, 0 < stop < entry", 422)
        L = self.limits()
        val = await self.valuation(pf["id"])
        eq = val["equity"]
        rp = D(risk_pct if risk_pct is not None else L.max_risk_per_trade_pct)
        by_risk = eq * rp / 100 / (entry - stop)
        held = next((p["value"] for p in val["positions"] if p["instrument_id"] == inst.id), ZERO)
        by_pos = max(eq * D(L.max_position_pct) / 100 - held, ZERO) / entry
        res_cash, _ = self._reserved(pf["id"])
        by_cash = max(val["cash"] - res_cash, ZERO) / entry
        qty = min(by_risk, by_pos, by_cash)
        binding = "risk per trade" if qty == by_risk else "position cap" if qty == by_pos else "buying power"
        qty = floor_to(qty, 8) if inst.asset_class == "crypto" else floor_to(qty, 0) if not L.allow_fractional_equities else floor_to(qty, 4)
        return jsonable({"equity": eq, "risk_pct": rp, "entry": entry, "stop": stop, "qty": qty, "binding_constraint": binding,
                         "by_risk": by_risk, "by_position_cap": by_pos, "by_buying_power": by_cash, "planned_risk": qty * (entry - stop),
                         "note": "Planned risk assumes the stop fills at its price. Gaps and slippage can make the real loss larger."})


def _sector(inst) -> str:
    if inst is None:
        return "Unclassified"
    if inst.asset_class == "crypto":
        return "Crypto"
    if inst.asset_class == "etf":
        return "ETF"
    return inst.sector or "Unclassified"
