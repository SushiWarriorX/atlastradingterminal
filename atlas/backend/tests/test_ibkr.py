import time
from datetime import datetime, timezone
from decimal import Decimal as Dec
from types import SimpleNamespace as NS

import pytest

from atlas_api.brokers.ibkr import BrokerError, IBKRBroker, IBKRSettings, map_status
from atlas_api.journal.store import JournalStore
from atlas_api.service import MarketService
from atlas_api.trading.engine import EngineError, TradingEngine
from atlas_api.trading.models import OrderIn
from test_paper_trading import Clock, Market

UTC = timezone.utc


class FakeIB:
    """Mirrors the slice of the ib_async API the adapter uses. Records everything so tests can assert exactly what was sent."""

    def __init__(self, accounts=("DU1234567",), refuse=False, cash="50000", positions=None):
        self.accounts, self.refuse, self.cash = list(accounts), refuse, cash
        self.connected, self.connect_calls, self.disconnected = False, [], False
        self._trades, self.placed, self.cancelled, self.unknown_symbols = [], [], [], set()
        self.fail_place = False
        self._positions = positions if positions is not None else ([NS(account=accounts[0], contract=NS(symbol="AAPL", secType="STK", currency="USD", conId=1), position=10.0, avgCost=150.0)] if accounts else [])
        self.exec_fills = []
        self._next_id = 100

    async def connectAsync(self, host, port, clientId=0, readonly=False, timeout=4):
        self.connect_calls.append({"host": host, "port": port, "clientId": clientId, "readonly": readonly})
        if self.refuse:
            raise ConnectionRefusedError("[Errno 111] Connect call failed")
        self.connected = True

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected, self.disconnected = False, True

    def managedAccounts(self):
        return self.accounts

    async def accountSummaryAsync(self, account):
        return [NS(tag="TotalCashValue", value="12.0", currency="EUR", account=account), NS(tag="TotalCashValue", value=self.cash, currency="USD", account=account),
                NS(tag="NetLiquidation", value="60000", currency="USD", account=account)]

    async def reqPositionsAsync(self):
        return None

    def positions(self, account):
        return [p for p in self._positions if p.account == account]

    async def qualifyContractsAsync(self, *cs):
        return [] if cs[0].symbol in self.unknown_symbols else list(cs)

    def placeOrder(self, contract, order):
        if self.fail_place:
            raise RuntimeError("Error 201, Order rejected - reason: insufficient buying power")
        self._next_id += 1
        order.orderId = self._next_id
        t = NS(order=order, contract=contract, orderStatus=NS(status="Submitted", filled=0.0, remaining=float(order.totalQuantity), avgFillPrice=0.0), fills=[])
        self._trades.append(t)
        self.placed.append((contract, order))
        return t

    def trades(self):
        return list(self._trades)

    def openTrades(self):
        return [t for t in self._trades if t.orderStatus.status in ("Submitted", "PreSubmitted")]

    def cancelOrder(self, order):
        self.cancelled.append(order.orderId)
        next(t for t in self._trades if t.order.orderId == order.orderId).orderStatus.status = "Cancelled"

    async def reqExecutionsAsync(self, flt):
        return self.exec_fills

    # test helpers
    def fill(self, order_id, qty, price, exec_id, commission=1.0, final=True):
        t = next(t for t in self._trades if t.order.orderId == order_id)
        f = NS(contract=t.contract, execution=NS(execId=exec_id, time=datetime(2026, 3, 9, 15, 0, tzinfo=UTC), side="BOT" if t.order.action == "BUY" else "SLD", shares=qty, price=price,
                                                  acctNumber="DU1234567", orderRef=t.order.orderRef, orderId=order_id), commissionReport=NS(commission=commission))
        t.fills.append(f)
        tot = sum(x.execution.shares for x in t.fills)
        t.orderStatus.filled, t.orderStatus.remaining = float(tot), float(t.order.totalQuantity - tot)
        t.orderStatus.avgFillPrice = sum(x.execution.shares * x.execution.price for x in t.fills) / tot
        t.orderStatus.status = "Filled" if t.orderStatus.remaining == 0 and final else "Submitted"


def broker(mode="paper_trading", port=7497, **fake_kw):
    ib = FakeIB(**fake_kw)
    return IBKRBroker(IBKRSettings(port=port, mode=mode), ib_factory=lambda: ib), ib


# --- connection guards ---------------------------------------------------------------------------------
async def test_readonly_mode_connects_to_a_live_account_but_can_never_trade():
    b, ib = broker("readonly", port=7496, accounts=("U7654321",))
    st = await b.connect()
    assert st["connected"] and st["mode"] == "readonly" and st["account_is_paper"] is False and st["can_trade"] is False
    assert ib.connect_calls[0]["readonly"] is True and ib.connect_calls[0]["port"] == 7496                      # the API itself is told read-only
    assert "7654321" not in str(st) and st["account"] == "U7…321"                                               # account ids are masked
    assert (await b.summary())["cash"] == Dec("50000") and (await b.positions())[0]["symbol"] == "AAPL"
    with pytest.raises(BrokerError) as e:
        await b.place_order(symbol="AAPL", side="buy", qty=Dec(1), type="market", tif="GTC", limit_price=None, stop_price=None, client_key="k")
    assert e.value.code == "BROKER_READONLY" and ib.placed == []
    with pytest.raises(BrokerError) as e:
        await b.cancel("1")
    assert e.value.code == "BROKER_READONLY"


async def test_paper_trading_mode_connects_to_paper_accounts_and_can_trade():
    b, ib = broker()
    st = await b.connect()
    assert st["can_trade"] and st["account_is_paper"] and ib.connect_calls[0]["readonly"] is False and "PAPER" in st["note"]
    assert (await b.connect())["connected"] and len(ib.connect_calls) == 1                                      # idempotent


@pytest.mark.parametrize("accounts", [("U7654321",), ("DU1234567", "U7654321"), ("DUX123",), ("du1234567",)])
async def test_paper_trading_mode_refuses_any_non_paper_account_and_disconnects(accounts):
    b, ib = broker(accounts=accounts)
    with pytest.raises(BrokerError) as e:
        await b.connect()
    assert e.value.code == "LIVE_ACCOUNT_REFUSED" and ib.disconnected and not b.connected and not b.can_trade
    assert b.status()["last_error"] and b.account is None


@pytest.mark.parametrize("port", [7496, 4001])
async def test_paper_trading_mode_never_even_attempts_a_live_port(port):
    b, ib = broker(port=port)
    with pytest.raises(BrokerError) as e:
        await b.connect()
    assert e.value.code == "LIVE_PORT_REFUSED" and ib.connect_calls == []


async def test_connection_failures_are_reported_clearly():
    b, ib = broker(refuse=True)
    with pytest.raises(BrokerError) as e:
        await b.connect()
    assert e.value.code == "IBKR_UNREACHABLE" and "127.0.0.1:7497" in e.value.message and "ConnectionRefusedError" in b.status()["last_error"] and not b.connected
    b2, _ = broker(accounts=())
    with pytest.raises(BrokerError) as e:
        await b2.connect()
    assert e.value.code == "NO_ACCOUNT"
    ib3 = FakeIB()
    b3 = IBKRBroker(IBKRSettings(account="DU9999999"), ib_factory=lambda: ib3)
    with pytest.raises(BrokerError) as e:
        await b3.connect()
    assert e.value.code == "ACCOUNT_NOT_FOUND" and "DU9999999" not in e.value.message
    with pytest.raises(ValueError):
        IBKRBroker(IBKRSettings(mode="live"))                                                                   # there is no live trading mode
    for fn in (b.summary, b.positions, b.executions):
        with pytest.raises(BrokerError) as e:
            await fn()
        assert e.value.code == "NOT_CONNECTED"


# --- reads ---------------------------------------------------------------------------------------------
async def test_summary_uses_usd_cash_and_positions_skip_flat_lines():
    b, ib = broker(positions=[NS(account="DU1234567", contract=NS(symbol="AAPL", secType="STK", currency="USD", conId=1), position=10.0, avgCost=150.25),
                              NS(account="DU1234567", contract=NS(symbol="MSFT", secType="STK", currency="USD", conId=2), position=0.0, avgCost=300.0),
                              NS(account="DU1234567", contract=NS(symbol="ES", secType="FUT", currency="USD", conId=3), position=1.0, avgCost=250000.0)])
    await b.connect()
    s = await b.summary()
    assert s["cash"] == Dec("50000") and s["net_liquidation"] == Dec("60000")                                    # the EUR line was ignored
    assert [(p["symbol"], p["qty"], p["avg_cost"], p["sec_type"]) for p in await b.positions()] == [("AAPL", 10, Dec("150.25"), "STK"), ("ES", 1, Dec("250000.0"), "FUT")]


async def test_executions_mapping_commission_quirks_and_multipliers():
    b, ib = broker()
    await b.connect()
    mk = lambda i, side, shares, price, comm, sec="STK", mult="", t=datetime(2026, 3, 9, 15, 0, tzinfo=UTC): NS(
        contract=NS(symbol="AAPL" if sec == "STK" else "ES", secType=sec, currency="USD", multiplier=mult),
        execution=NS(execId=f"e{i}", time=t, side=side, shares=shares, price=price), commissionReport=NS(commission=comm))
    ib.exec_fills = [mk(1, "BOT", 10, 200.5, 1.25), mk(2, "SLD", 10, 205.0, 1.7976931348623157e308), mk(3, "BOT", 2, 5000.0, -4.5, "FUT", "50"), mk(4, "BOT", 1, 1.0, 0.0, t=datetime(2026, 3, 9, 15, 0))]
    e = await b.executions()
    assert [x.ext_id for x in e] == ["e1", "e2", "e3", "e4"] and all(x.source == "ibkr:DU1234567" for x in e)
    assert (e[0].side, e[0].fee, e[0].asset_class, e[0].qty, e[0].price) == ("buy", Dec("1.25"), "stock", 10, Dec("200.5"))
    assert e[1].side == "sell" and e[1].fee == 0                                                                  # IBKR's "unset" commission sentinel is not a real fee
    assert e[2].asset_class == "future" and e[2].multiplier == 50 and e[2].fee == Dec("4.5") and e[3].ts.tzinfo is not None


# --- orders ----------------------------------------------------------------------------------------------
async def place(b, **kw):
    base = dict(symbol="AAPL", side="buy", qty=Dec(10), type="market", tif="GTC", limit_price=None, stop_price=None, client_key="key-aaaaaaaa")
    return await b.place_order(**{**base, **kw})


async def test_order_objects_are_built_correctly_for_every_type():
    b, ib = broker()
    await b.connect()
    cases = [dict(type="market"), dict(type="limit", limit_price=Dec("190.5"), side="sell", client_key="k2k2k2k2"), dict(type="stop", stop_price=Dec("180"), client_key="k3k3k3k3"),
             dict(type="stop_limit", limit_price=Dec("181"), stop_price=Dec("180"), tif="DAY", client_key="k4k4k4k4")]
    for c in cases:
        await place(b, **c)
    kinds = [(o.orderType, o.action, o.totalQuantity, getattr(o, "lmtPrice", None), getattr(o, "auxPrice", None), o.tif, o.orderRef, o.account) for _, o in ib.placed]
    assert kinds[0][:3] == ("MKT", "BUY", 10.0) and kinds[0][5:] == ("GTC", "key-aaaaaaaa", "DU1234567")
    assert kinds[1][:4] == ("LMT", "SELL", 10.0, 190.5)
    assert kinds[2][0] == "STP" and kinds[2][4] == 180.0
    assert kinds[3][0] == "STP LMT" and kinds[3][3] == 181.0 and kinds[3][4] == 180.0 and kinds[3][5] == "DAY"
    assert {c.symbol for c, _ in ib.placed} == {"AAPL"} and all(c.secType == "STK" and c.exchange == "SMART" and c.currency == "USD" for c, _ in ib.placed)


async def test_retry_with_the_same_reference_adopts_instead_of_double_placing():
    b, ib = broker()
    await b.connect()
    first = await place(b)
    again = await place(b)
    assert again["adopted"] is True and again["broker_order_id"] == first["broker_order_id"] and len(ib.placed) == 1
    assert (await b.find_by_ref("key-aaaaaaaa"))["broker_order_id"] == first["broker_order_id"] and await b.find_by_ref("nope") is None


async def test_placement_failures_surface_as_broker_errors():
    b, ib = broker()
    await b.connect()
    ib.unknown_symbols.add("ZZZZ")
    with pytest.raises(BrokerError) as e:
        await place(b, symbol="ZZZZ", client_key="kzzzzzzzz")
    assert e.value.code == "CONTRACT_NOT_FOUND"
    ib.fail_place = True
    with pytest.raises(BrokerError) as e:
        await place(b, client_key="kfailfail")
    assert e.value.code == "PLACE_FAILED" and "insufficient buying power" in e.value.message


async def test_order_status_fills_cancel_and_unknown_orders():
    b, ib = broker()
    await b.connect()
    oid = (await place(b))["broker_order_id"]
    st = await b.order_status(oid)
    assert st["state"] == "working" and st["filled"] == 0 and st["fills"] == []
    ib.fill(int(oid), 4, 200.0, "x1", final=False)
    st = await b.order_status(oid)
    assert st["state"] == "partially_filled" and st["filled"] == 4 and st["remaining"] == 6 and st["fills"][0]["exec_id"] == "x1" and st["fills"][0]["fee"] == Dec("1.0")
    ib.fill(int(oid), 6, 201.0, "x2", commission=1.7976931348623157e308)
    st = await b.order_status(oid)
    assert st["state"] == "filled" and st["avg_price"] == Dec("200.6") and [f["fee"] for f in st["fills"]] == [Dec("1.0"), Dec(0)]
    o2 = (await place(b, client_key="kcancel1"))["broker_order_id"]
    await b.cancel(o2)
    assert ib.cancelled == [int(o2)] and (await b.order_status(o2))["state"] == "cancelled"
    for fn in (lambda: b.order_status("999"), lambda: b.cancel("999")):
        with pytest.raises(BrokerError) as e:
            await fn()
        assert e.value.code == "ORDER_UNKNOWN"


def test_status_mapping():
    assert map_status("Filled", Dec(5), Dec(0)) == "filled" and map_status("Submitted", Dec(5), Dec(0)) == "filled"
    assert map_status("Cancelled", Dec(0), Dec(5)) == "cancelled" and map_status("ApiCancelled", Dec(0), Dec(5)) == "cancelled" and map_status("Inactive", Dec(0), Dec(5)) == "rejected"
    assert map_status("Submitted", Dec(2), Dec(3)) == "partially_filled"
    assert all(map_status(s, Dec(0), Dec(5)) == "working" for s in ("PendingSubmit", "PreSubmitted", "Submitted", "PendingCancel"))


# --- engine routing ------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    from atlas_api import service

    monkeypatch.setitem(service._TTL, "quote", 0.0)
    monkeypatch.setitem(service._TTL, "ohlcv", 0.0)


@pytest.fixture
async def env(db):
    book = {"AAPL": {"price": 200.0, "bid": 199.99, "ask": 200.01}, "BTC-USD": {"price": 70000.0, "bid": 69999.0, "ask": 70001.0}}
    clock = Clock(datetime(2026, 3, 9, 15, 0, tzinfo=UTC).timestamp())               # Monday, regular session
    b, ib = broker()
    await b.connect()
    eng = TradingEngine(db, MarketService({"coinbase": Market("coinbase", book), "yahoo": Market("yahoo", book)}), clock=clock, broker=b)
    pf = await eng.link_ibkr_portfolio("IBKR paper")
    eng.ib, eng.book, eng.clock_, eng.pid, eng.broker_ = ib, book, clock, pf["id"], b
    return eng


def aapl(qty=10, **kw):
    return OrderIn(**{"instrument_id": "AAPL", "side": "buy", "qty": qty, "type": "limit", "limit_price": 190, "planned_stop": 185, "portfolio_id": None, **kw})


async def go(eng, order, key="ibkr-key-0001"):
    order = order.model_copy(update={"portfolio_id": eng.pid})
    pv = await eng.preview(order)
    return await eng.submit(order, pv["preview_id"], key)


async def test_linking_reads_cash_and_positions_from_the_broker(env):
    pf = env.portfolio(env.pid)
    assert (pf["venue"], pf["kind"], pf["cash"], pf["starting_cash"]) == ("ibkr", "paper", "50000", "50000") and pf["broker_account"] == "DU1234567"
    (p,) = env.positions(env.pid)
    assert (p["symbol"], p["qty"], p["avg_cost"], p["instrument_id"]) == ("AAPL", "10", "150", "EQUITY:NASDAQ:AAPL")
    v = await env.valuation(env.pid)
    assert v["equity"] == Dec(50000) + Dec(10) * Dec("200.0")


async def test_sync_overwrites_from_broker_preserves_stops_and_reports_unsupported(env):
    env.db.x("UPDATE positions SET planned_stop='140' WHERE portfolio_id=?", (env.pid,))
    env.ib.cash = "41000"
    env.ib._positions = [NS(account="DU1234567", contract=NS(symbol="AAPL", secType="STK", currency="USD", conId=1), position=12.0, avgCost=151.0),
                         NS(account="DU1234567", contract=NS(symbol="ES", secType="FUT", currency="USD", conId=3), position=1.0, avgCost=1.0),
                         NS(account="DU1234567", contract=NS(symbol="BRK B", secType="STK", currency="USD", conId=4), position=1.0, avgCost=1.0)]
    out = await env.sync_broker_portfolio(env.pid)
    assert out["cash"] == "41000" and out["positions"] == 1 and out["unsupported"] == ["ES (FUT)", "BRK B (symbol not recognised)"]
    (p,) = env.positions(env.pid)
    assert (p["qty"], p["avg_cost"], p["planned_stop"]) == ("12", "151", "140")
    env.ib.accounts = ["DU7777777"]
    env.broker_.account = "DU7777777"
    with pytest.raises(EngineError) as e:
        await env.sync_broker_portfolio(env.pid)
    assert e.value.code == "ACCOUNT_MISMATCH"


async def test_order_is_risk_checked_then_routed_to_ibkr_not_the_simulator(env):
    order = aapl().model_copy(update={"portfolio_id": env.pid})
    pv = await env.preview(order)
    venue = next(c for c in pv["checks"] if c["name"] == "venue")
    assert pv["verdict"] == "APPROVE_FOR_PAPER_REVIEW" and venue["status"] == "pass" and "IBKR PAPER" in venue["detail"]
    r = await env.submit(order, pv["preview_id"], "ibkr-key-0001")
    o = r["order"]
    assert o["venue"] == "ibkr" and o["state"] == "working" and o["broker_order_id"] == "101"
    assert [e["event"] for e in o["events"]][:2] == ["accepted", "sent_to_ibkr"]
    (contract, sent), = env.ib.placed
    assert (sent.orderRef, sent.action, sent.totalQuantity, sent.lmtPrice, sent.account) == ("ibkr-key-0001", "BUY", 10.0, 190.0, "DU1234567")
    assert env.fills(env.pid) == []                                                                   # nothing is simulated: fills come only from IBKR


async def test_fills_arrive_from_the_broker_once_each_and_update_the_order(env):
    r = await go(env, aapl())
    oid = int(r["order"]["broker_order_id"])
    env.ib.fill(oid, 4, 189.5, "ex-1", final=False)
    await env.evaluate()
    o = env.orders(env.pid)[0]
    assert o["state"] == "partially_filled" and o["filled_qty"] == "4" and Dec(o["avg_fill_price"]) == Dec("189.5") and o["remaining_qty"] == "6"
    env.ib.fill(oid, 6, 190.0, "ex-2")
    await env.evaluate()
    await env.evaluate()                                                                              # re-polling must not duplicate fills
    o = env.orders(env.pid)[0]
    fills = env.fills(env.pid)
    assert o["state"] == "filled" and o["filled_qty"] == "10" and Dec(o["avg_fill_price"]) == Dec("189.8") and len(fills) == 2
    assert {f["ext_id"] for f in fills} == {"ex-1", "ex-2"} and all(f["data_status"] == "BROKER" and f["provider"] == "ibkr" and f["fee"] == "1" for f in fills)
    assert [e["event"] for e in o["events"]].count("fill") == 2


async def test_portfolio_state_follows_the_broker_after_fills(env):
    r = await go(env, aapl())
    env.ib.fill(int(r["order"]["broker_order_id"]), 10, 190.0, "ex-1")
    env.ib.cash = "48099"
    env.ib._positions[0].position, env.ib._positions[0].avgCost = 20.0, 170.0
    env.clock_.t += 20                                                                                # past the 15 s sync throttle
    await env.evaluate()
    pf = env.portfolio(env.pid)
    (p,) = env.positions(env.pid)
    assert pf["cash"] == "48099" and (p["qty"], p["avg_cost"]) == ("20", "170")                       # the broker, not a local ledger, is the source of truth
    assert env.reconcile(env.pid)["applicable"] is False


async def test_idempotent_resubmission_places_exactly_one_broker_order(env):
    await go(env, aapl(), key="same-key-0001")
    again = await env.submit(aapl().model_copy(update={"portfolio_id": env.pid}), "stale-preview", "same-key-0001")
    assert again["duplicate"] is True and len(env.ib.placed) == 1 and len(env.orders(env.pid)) == 1


async def test_cancel_goes_to_the_broker_and_state_comes_from_it(env):
    r = await go(env, aapl())
    c = await env.cancel(r["order"]["id"])
    assert env.ib.cancelled == [int(r["order"]["broker_order_id"])] and c["state"] == "cancelled" and "cancel_requested" in [e["event"] for e in c["events"]]
    with pytest.raises(EngineError) as e:
        await env.cancel(r["order"]["id"])
    assert e.value.code == "ORDER_NOT_CANCELABLE"
    r2 = await go(env, aapl(), key="ibkr-key-0002")
    env.ib.fill(int(r2["order"]["broker_order_id"]), 10, 190.0, "ex-9")
    await env.evaluate()
    with pytest.raises(EngineError) as e:
        await env.cancel(r2["order"]["id"])
    assert e.value.code == "ORDER_NOT_CANCELABLE"


async def test_broker_rejection_is_recorded_audited_and_raised(env):
    env.ib.fail_place = True
    order = aapl().model_copy(update={"portfolio_id": env.pid})
    pv = await env.preview(order)
    with pytest.raises(EngineError) as e:
        await env.submit(order, pv["preview_id"], "ibkr-key-0003")
    assert e.value.code == "BROKER_REJECTED" and e.value.status == 502 and "insufficient buying power" in e.value.message
    (o,) = env.orders(env.pid)
    assert o["state"] == "rejected" and "PLACE_FAILED" in o["reason"] and o["broker_order_id"] is None
    assert env.db.q("SELECT COUNT(*) FROM audit_log WHERE action='ibkr_order_rejected'")[0][0] == 1


async def test_crash_recovery_adopts_or_gives_up_on_orders_that_never_got_a_broker_id(env):
    # a pending order whose broker id was never saved, but IBKR does have it (crash between placing and saving)
    sent = await place(env.broker_, client_key="orphan-key-1")
    now = env.clock_.t
    env.db.x("INSERT INTO orders(portfolio_id,client_key,instrument_id,symbol,side,type,tif,qty,limit_price,est_price,state,created_at,updated_at,venue) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (env.pid, "orphan-key-1", "EQUITY:NASDAQ:AAPL", "AAPL", "buy", "limit", "GTC", "10", "190", "190", "pending_submit", datetime.fromtimestamp(now, UTC).isoformat(), datetime.fromtimestamp(now, UTC).isoformat(), "ibkr"))
    env.db.x("INSERT INTO orders(portfolio_id,client_key,instrument_id,symbol,side,type,tif,qty,limit_price,est_price,state,created_at,updated_at,venue) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (env.pid, "ghost-key-1", "EQUITY:NASDAQ:AAPL", "AAPL", "buy", "limit", "GTC", "10", "190", "190", "pending_submit", datetime.fromtimestamp(now, UTC).isoformat(), datetime.fromtimestamp(now, UTC).isoformat(), "ibkr"))
    await env.evaluate()
    by = {o["client_key"]: o for o in env.orders(env.pid)}
    assert by["orphan-key-1"]["broker_order_id"] == sent["broker_order_id"] and by["orphan-key-1"]["state"] == "working"
    assert by["ghost-key-1"]["state"] == "pending_submit"                                              # not found yet, but not given up on within 30 s
    env.clock_.t += 31
    await env.evaluate()
    ghost = next(o for o in env.orders(env.pid) if o["client_key"] == "ghost-key-1")
    assert ghost["state"] == "rejected" and "never reached IBKR" in ghost["reason"]


async def test_disconnected_broker_leaves_orders_untouched_and_says_so_once(env):
    r = await go(env, aapl())
    env.ib.connected = False
    await env.evaluate()
    await env.evaluate()
    o = env.orders(env.pid)[0]
    assert o["state"] == "working" and [e["event"] for e in o["events"]].count("waiting_for_broker") == 1
    with pytest.raises(EngineError) as e:
        await env.preview(aapl().model_copy(update={"portfolio_id": env.pid}))
    assert e.value.code == "BROKER_READONLY"                                                           # no orders while the connection cannot trade


async def test_kill_switch_cancels_orders_at_the_broker(env):
    r = await go(env, aapl())
    out = await env.set_halted(True, cancel_open=True)
    assert out["cancelled_orders"] == [r["order"]["id"]] and env.ib.cancelled == [int(r["order"]["broker_order_id"])]
    env.ib.connected = True
    await env.evaluate()
    assert env.orders(env.pid)[0]["state"] == "cancelled"


async def test_crypto_cannot_be_routed_to_ibkr(env):
    order = OrderIn(instrument_id="BTC-USD", side="buy", qty="0.1", type="market", planned_stop=68000, portfolio_id=env.pid)
    pv = await env.preview(order)
    v = next(c for c in pv["checks"] if c["name"] == "venue")
    assert pv["verdict"] == "REJECT" and v["status"] == "fail" and "stocks and ETFs only" in v["detail"]


async def test_read_only_link_creates_a_portfolio_that_can_never_trade(db):
    b, ib = broker("readonly", port=7496, accounts=("U7654321",), positions=[NS(account="U7654321", contract=NS(symbol="AAPL", secType="STK", currency="USD", conId=1), position=5.0, avgCost=100.0)])
    await b.connect()
    eng = TradingEngine(db, MarketService({"yahoo": Market("yahoo", {"AAPL": {"price": 200.0, "bid": 199.99, "ask": 200.01}})}), broker=b)
    pf = await eng.link_ibkr_portfolio("My live account (read only)")
    assert pf["kind"] == "manual" and pf["venue"] == "ibkr" and eng.positions(pf["id"])[0]["qty"] == "5"
    with pytest.raises(EngineError) as e:
        await eng.preview(OrderIn(instrument_id="AAPL", side="buy", qty=1, type="market", planned_stop=150, portfolio_id=pf["id"]))
    assert e.value.code == "MANUAL_PORTFOLIO"
    for fn in (lambda: eng.set_manual_cash(pf["id"], Dec(1)), lambda: eng.set_manual_position(pf["id"], "AAPL", Dec(1), Dec(1)), lambda: eng.reset_paper(pf["id"])):
        with pytest.raises(EngineError):
            fn()                                                                                       # the broker's numbers cannot be overwritten by hand
    with pytest.raises(EngineError) as e:
        await TradingEngine(db, MarketService({})).link_ibkr_portfolio("x")
    assert e.value.code == "NOT_CONNECTED"


async def test_journal_gets_ibkr_executions_without_double_counting_engine_fills(env):
    r = await go(env, aapl())
    oid = int(r["order"]["broker_order_id"])
    env.ib.fill(oid, 10, 190.0, "ex-1")
    await env.evaluate()
    sell = await go(env, aapl(side="sell", limit_price=200), key="ibkr-key-sell1")
    env.ib.fill(int(sell["order"]["broker_order_id"]), 10, 200.0, "ex-2", commission=1.0)
    await env.evaluate()
    env.ib.exec_fills = [NS(contract=NS(symbol="AAPL", secType="STK", currency="USD", multiplier=""), execution=NS(execId=i, time=datetime(2026, 3, 9, 15, m, tzinfo=UTC), side=sd, shares=10, price=px),
                            commissionReport=NS(commission=1.0)) for i, m, sd, px in (("ex-1", 1, "BOT", 190.0), ("ex-2", 5, "SLD", 200.0))]
    j = JournalStore(env.db)
    assert j.insert_executions(await env.broker_.executions()) == (2, 0)
    assert j.insert_executions(await env.broker_.executions()) == (0, 2)                               # re-syncing is idempotent
    assert j.sync_paper() == {"paper_executions_added": 0}                                             # broker-linked fills are NOT also copied from the local fills table
    (t,) = j.trades()["trades"]
    assert t["source"] == "ibkr:DU1234567" and t["net_pnl"] == Dec("98") and t["status"] == "closed"  # (200-190)*10 - 2 commissions


async def test_a_commission_that_arrives_after_the_fill_is_filled_in_on_a_later_sync(env):
    mk = lambda comm: NS(contract=NS(symbol="AAPL", secType="STK", currency="USD", multiplier=""), execution=NS(execId="late-1", time=datetime(2026, 3, 9, 15, 0, tzinfo=UTC), side="BOT", shares=10, price=190.0),
                         commissionReport=NS(commission=comm))
    j = JournalStore(env.db)
    env.ib.exec_fills = [mk(1.7976931348623157e308)]                                                 # the commission report has not arrived yet: IBKR's "unset" sentinel
    assert j.insert_executions(await env.broker_.executions()) == (1, 0) and j.load()[0][0].fee == 0
    env.ib.exec_fills = [mk(1.25)]                                                                   # a later sync sees the real commission
    assert j.insert_executions(await env.broker_.executions()) == (0, 1) and j.last_fee_updates == 1 and j.load()[0][0].fee == Dec("1.25")
    env.ib.exec_fills = [mk(9.99)]                                                                   # a non-zero stored fee is never overwritten
    j.insert_executions(await env.broker_.executions())
    assert j.last_fee_updates == 0 and j.load()[0][0].fee == Dec("1.25")


async def test_engine_fill_fee_is_filled_in_when_ibkr_reports_the_commission_late(env):
    r = await go(env, aapl())
    oid = int(r["order"]["broker_order_id"])
    env.ib.fill(oid, 10, 190.0, "late-fill", commission=1.7976931348623157e308)                       # commission not reported yet
    await env.evaluate()
    assert env.fills(env.pid)[0]["fee"] == "0"
    env.ib._trades[0].fills[0].commissionReport.commission = 1.5                                      # it arrives
    await env.evaluate()
    assert env.fills(env.pid)[0]["fee"] == "1.5" and len(env.fills(env.pid)) == 1
    env.ib._trades[0].fills[0].commissionReport.commission = 9.0
    await env.evaluate()
    assert env.fills(env.pid)[0]["fee"] == "1.5"                                                      # a real fee is never overwritten
