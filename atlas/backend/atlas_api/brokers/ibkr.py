"""Interactive Brokers via TWS / IB Gateway (ib_async). Local connection: your credentials never touch ATLAS.

Two modes, chosen by the operator in the backend environment (never by the browser or an AI agent):
  readonly        API connection opened with readonly=True: positions, balances and executions only. Works with ANY account, including live.
  paper_trading   Orders allowed, but ONLY if the live-trading ports are not used and EVERY managed account is a paper account (id starts
                  with "DU"). Anything else is refused and disconnected. There is no mode that routes orders to a live account.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from ..journal.matching import Exec
from ..trading.money import ZERO, D

log = logging.getLogger("atlas.ibkr")
PAPER_PORTS = {7497, 4002}
LIVE_PORTS = {7496, 4001}
PAPER_ACCOUNT = re.compile(r"^DU\d+$")
UNSET = 1e10          # IBKR reports "unset" doubles as ~1.797e308


class BrokerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class IBKRSettings:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 21
    mode: str = "readonly"             # readonly | paper_trading
    account: str | None = None
    timeout: float = 8.0


def mask(acct: str) -> str:
    return acct[:2] + "…" + acct[-3:] if len(acct) > 5 else "***"


class IBKRBroker:
    def __init__(self, settings: IBKRSettings, ib_factory=None):
        if settings.mode not in ("readonly", "paper_trading"):
            raise ValueError("IBKR mode must be readonly or paper_trading")
        self.s = settings
        self._factory = ib_factory
        self.ib = None
        self.account: str | None = None
        self.accounts: list[str] = []
        self.last_error: str | None = None
        self._lock = asyncio.Lock()

    # --- connection ---------------------------------------------------------
    @property
    def can_trade(self) -> bool:
        return self.s.mode == "paper_trading" and self.connected and bool(self.account) and bool(PAPER_ACCOUNT.match(self.account))

    @property
    def connected(self) -> bool:
        return bool(self.ib and self.ib.isConnected())

    async def connect(self) -> dict:
        async with self._lock:
            if self.connected:
                return self.status()
            if self.s.mode == "paper_trading" and self.s.port in LIVE_PORTS:
                raise BrokerError("LIVE_PORT_REFUSED", f"port {self.s.port} is the live-trading port. Paper trading mode only connects to paper ports {sorted(PAPER_PORTS)}.")
            if self.ib is None:
                if self._factory is None:
                    from ib_async import IB
                    self._factory = IB
                self.ib = self._factory()
            try:
                await self.ib.connectAsync(self.s.host, self.s.port, clientId=self.s.client_id, readonly=self.s.mode == "readonly", timeout=self.s.timeout)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"[:200]
                raise BrokerError("IBKR_UNREACHABLE", f"Could not connect to TWS/IB Gateway at {self.s.host}:{self.s.port} ({self.last_error}). Is it running with the API enabled?")
            accounts = list(self.ib.managedAccounts())
            if not accounts:
                self.ib.disconnect()
                raise BrokerError("NO_ACCOUNT", "connected, but IBKR reported no managed accounts")
            if self.s.mode == "paper_trading":
                live = [a for a in accounts if not PAPER_ACCOUNT.match(a)]
                if live:
                    self.ib.disconnect()
                    self.last_error = "live account on a paper-trading connection"
                    raise BrokerError("LIVE_ACCOUNT_REFUSED", "paper-trading mode refuses connections that include a non-paper account. Log in to TWS/Gateway with your PAPER credentials, or use readonly mode.")
            self.accounts = accounts
            want = self.s.account
            if want and want not in accounts:
                self.ib.disconnect()
                raise BrokerError("ACCOUNT_NOT_FOUND", f"configured account {mask(want)} is not among the connected accounts")
            self.account = want or accounts[0]
            self.last_error = None
            return self.status()

    async def disconnect(self) -> None:
        async with self._lock:
            if self.ib and self.ib.isConnected():
                self.ib.disconnect()
            self.account = None

    def status(self) -> dict:
        return {"configured": True, "mode": self.s.mode, "connected": self.connected, "host": self.s.host, "port": self.s.port,
                "accounts": [mask(a) for a in self.accounts], "account": mask(self.account) if self.account else None,
                "account_is_paper": bool(self.account and PAPER_ACCOUNT.match(self.account)), "can_trade": self.can_trade, "last_error": self.last_error,
                "note": "readonly: positions, balances and executions only" if self.s.mode == "readonly" else "orders are routed to the PAPER account only"}

    def _need(self):
        if not self.connected:
            raise BrokerError("NOT_CONNECTED", "not connected to IBKR: press Connect in Settings")

    # --- reads ----------------------------------------------------------------
    async def summary(self) -> dict:
        self._need()
        vals = await self.ib.accountSummaryAsync(self.account)
        out: dict = {}
        for v in vals:
            if v.tag in ("TotalCashValue", "NetLiquidation") and v.currency in ("USD", "BASE", ""):
                out.setdefault(v.tag, D(v.value))
        if "TotalCashValue" not in out:
            raise BrokerError("NO_CASH_DATA", "IBKR did not return TotalCashValue for this account")
        return {"cash": out["TotalCashValue"], "net_liquidation": out.get("NetLiquidation"), "account": self.account}

    async def positions(self) -> list[dict]:
        self._need()
        await self.ib.reqPositionsAsync()
        return [{"symbol": p.contract.symbol, "sec_type": p.contract.secType, "currency": p.contract.currency, "qty": D(p.position), "avg_cost": D(p.avgCost),
                 "con_id": getattr(p.contract, "conId", None)} for p in self.ib.positions(self.account) if p.position]

    async def executions(self) -> list[Exec]:
        """Executions TWS still holds (roughly the last trading day(s)). Older history needs a Flex Query import."""
        self._need()
        from ib_async import ExecutionFilter

        fills = await self.ib.reqExecutionsAsync(ExecutionFilter(acctCode=self.account))
        out = []
        for f in fills:
            ex, c = f.execution, f.contract
            ts = ex.time if ex.time.tzinfo else ex.time.replace(tzinfo=timezone.utc)
            comm = getattr(getattr(f, "commissionReport", None), "commission", None)
            fee = D(comm) if comm is not None and abs(comm) < UNSET else ZERO
            mult = D(c.multiplier) if getattr(c, "multiplier", None) not in (None, "") else Decimal(1)
            cls = {"STK": "stock", "FUT": "future", "OPT": "option", "CASH": "forex", "CRYPTO": "crypto"}.get(c.secType, c.secType.lower())
            out.append(Exec(source=f"ibkr:{self.account}", ext_id=ex.execId, ts=ts.astimezone(timezone.utc), symbol=c.symbol, asset_class=cls,
                            side="buy" if ex.side.upper() in ("BOT", "BUY") else "sell", qty=D(ex.shares), price=D(ex.price), fee=abs(fee), currency=c.currency or "USD", multiplier=mult))
        return out

    # --- orders (paper trading mode only) ---------------------------------------
    def _trade_by_ref(self, ref: str):
        for t in self.ib.trades():
            if getattr(t.order, "orderRef", None) == ref:
                return t
        return None

    def _trade_by_id(self, broker_order_id: str):
        for t in self.ib.trades():
            if str(t.order.orderId) == str(broker_order_id) or str(getattr(t.order, "permId", "")) == str(broker_order_id):
                return t
        return None

    async def place_order(self, *, symbol: str, side: str, qty: Decimal, type: str, tif: str, limit_price: Decimal | None, stop_price: Decimal | None, client_key: str) -> dict:
        if not self.can_trade:
            raise BrokerError("BROKER_READONLY", "IBKR is connected read-only (or not a paper account): orders cannot be placed.")
        from ib_async import LimitOrder, MarketOrder, Stock, StopLimitOrder, StopOrder

        existing = self._trade_by_ref(client_key)
        if existing is not None:                                   # a retry after a crash: adopt, never double-place
            return {"broker_order_id": str(existing.order.orderId), "status": existing.orderStatus.status, "adopted": True}
        action = "BUY" if side == "buy" else "SELL"
        q = float(qty)
        order = {"market": lambda: MarketOrder(action, q), "limit": lambda: LimitOrder(action, q, float(limit_price)), "stop": lambda: StopOrder(action, q, float(stop_price)),
                 "stop_limit": lambda: StopLimitOrder(action, q, float(limit_price), float(stop_price))}[type]()
        order.tif, order.orderRef, order.account = tif, client_key, self.account
        contract = Stock(symbol, "SMART", "USD")
        try:
            qualified = await self.ib.qualifyContractsAsync(contract)
            if not qualified:
                raise BrokerError("CONTRACT_NOT_FOUND", f"IBKR could not resolve {symbol} as a US stock/ETF")
            trade = self.ib.placeOrder(qualified[0], order)
        except BrokerError:
            raise
        except Exception as e:  # noqa: BLE001
            raise BrokerError("PLACE_FAILED", f"{type_name(e)}: {e}"[:200])
        return {"broker_order_id": str(trade.order.orderId), "status": trade.orderStatus.status, "adopted": False}

    async def find_by_ref(self, ref: str) -> dict | None:
        self._need()
        t = self._trade_by_ref(ref)
        return {"broker_order_id": str(t.order.orderId), "status": t.orderStatus.status} if t else None

    async def order_status(self, broker_order_id: str) -> dict:
        self._need()
        t = self._trade_by_id(broker_order_id)
        if t is None:
            raise BrokerError("ORDER_UNKNOWN", f"IBKR has no record of order {broker_order_id} in this session")
        st = t.orderStatus
        fills = []
        for f in t.fills:
            comm = getattr(getattr(f, "commissionReport", None), "commission", None)
            ts = f.execution.time if f.execution.time.tzinfo else f.execution.time.replace(tzinfo=timezone.utc)
            fills.append({"exec_id": f.execution.execId, "qty": D(f.execution.shares), "price": D(f.execution.price), "ts": ts.astimezone(timezone.utc),
                          "fee": abs(D(comm)) if comm is not None and abs(comm) < UNSET else ZERO, "side": "buy" if f.execution.side.upper() in ("BOT", "BUY") else "sell"})
        return {"status": st.status, "filled": D(st.filled), "remaining": D(st.remaining), "avg_price": D(st.avgFillPrice) if st.avgFillPrice else None, "fills": fills,
                "state": map_status(st.status, D(st.filled), D(st.remaining))}

    async def cancel(self, broker_order_id: str) -> None:
        if not self.can_trade:
            raise BrokerError("BROKER_READONLY", "IBKR is connected read-only: orders cannot be cancelled from here.")
        t = self._trade_by_id(broker_order_id)
        if t is None:
            raise BrokerError("ORDER_UNKNOWN", f"IBKR has no record of order {broker_order_id} in this session")
        self.ib.cancelOrder(t.order)


def type_name(e: Exception) -> str:
    return type(e).__name__


def map_status(status: str, filled: Decimal, remaining: Decimal) -> str:
    """IBKR order status -> our order state."""
    if status == "Filled" or (filled > 0 and remaining == 0):
        return "filled"
    if status in ("Cancelled", "ApiCancelled"):
        return "cancelled"
    if status == "Inactive":
        return "rejected"
    return "partially_filled" if filled > 0 else "working"      # PendingSubmit / PreSubmitted / Submitted / PendingCancel
