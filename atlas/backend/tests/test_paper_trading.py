import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dec

import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.models import Candle, OHLCV, Provenance, ProviderUnavailable, Quote
from atlas_api.service import MarketService
from atlas_api.trading import analytics
from atlas_api.trading.engine import EngineError, TradingEngine
from atlas_api.trading.models import OrderIn

BTC = "CRYPTO:COINBASE:BTC-USD:SPOT"
AAPL = "EQUITY:NASDAQ:AAPL"
DAY = 86400


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


class Market:
    """Scriptable provider. `book` maps symbol -> dict(price, bid, ask, volume); `hist` maps symbol -> candles."""

    def __init__(self, name, book, hist=None):
        self.name, self.entitlement, self.delay_seconds = name, "test", 0
        self.native_intervals = {"1d", "1h", "15m"}
        self.book, self.hist, self.age, self.fail = book, hist or {}, 0, False

    async def quote(self, inst):
        if self.fail:
            raise ProviderUnavailable(self.name, "down")
        b = self.book[inst.symbol]
        ev = datetime.now(timezone.utc) - timedelta(seconds=self.age)
        return Quote(instrument_id=inst.id, price=b["price"], bid=b.get("bid"), ask=b.get("ask"), volume=b.get("volume"), prev_close=b.get("prev", b["price"]),
                     prov=Provenance(provider=self.name, instrument_id=inst.id, venue=inst.exchange, event_time=ev, ingested_time=datetime.now(timezone.utc),
                                     entitlement="test", delay_seconds=0))

    async def ohlcv(self, inst, interval, limit):
        if self.fail:
            raise ProviderUnavailable(self.name, "down")
        c = self.hist[inst.symbol][-limit:]
        return OHLCV(instrument_id=inst.id, interval=interval, candles=c, prov=Provenance(
            provider=self.name, instrument_id=inst.id, event_time=datetime.now(timezone.utc), ingested_time=datetime.now(timezone.utc), delay_seconds=0))


class Clock:
    def __init__(self, t=None):
        self.t = t or time.time()

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    from atlas_api import service

    monkeypatch.setitem(service._TTL, "quote", 0.0)
    monkeypatch.setitem(service._TTL, "ohlcv", 0.0)


BTC_BOOK = {"price": 70000.0, "bid": 69999.0, "ask": 70001.0}
AAPL_BOOK = {"price": 200.0, "bid": 199.99, "ask": 200.01}
SPX_BOOK = {"price": 5000.0}


@pytest.fixture
def env(db):
    book = {"BTC-USD": dict(BTC_BOOK), "AAPL": dict(AAPL_BOOK), "SPX": dict(SPX_BOOK)}
    cb, yh = Market("coinbase", book), Market("yahoo", book)
    clock = Clock()
    eng = TradingEngine(db, MarketService({"coinbase": cb, "yahoo": yh}), clock=clock)
    eng.mk = (book, cb, yh, clock)
    return eng


def btc_order(qty="0.1", **kw):
    return OrderIn(**{"instrument_id": "BTC-USD", "side": "buy", "qty": qty, "type": "market", "planned_stop": 68000, **kw})


async def buy(eng, order, key=None, pid=None):
    pv = await eng.preview(order)
    return await eng.submit(order, pv["preview_id"], key or f"key-{time.time_ns()}")


# --- lifecycle, exact accounting ----------------------------------------------------------
async def test_default_portfolio_is_created_once(db):
    e1 = TradingEngine(db, MarketService({}))
    e2 = TradingEngine(db, MarketService({}))
    ps = e2.portfolios()
    assert len(ps) == 1 and ps[0]["kind"] == "paper" and ps[0]["cash"] == "100000" and e1.portfolio(None)["id"] == ps[0]["id"]


async def test_preview_creates_nothing_and_describes_the_order(env):
    pv = await env.preview(btc_order())
    assert pv["verdict"] == "APPROVE_FOR_PAPER_REVIEW" and pv["requires_confirmation"] and pv["preview_id"] and pv["environment"] == "paper"
    assert Dec(pv["estimate"]["price"]) == Dec("70015.0002") and Dec(pv["estimate"]["notional"]) == Dec("7001.50002")
    assert Dec(pv["estimate"]["total_cost"]) == Dec("7008.50152002") and "simulated" in pv["simulator"]
    assert env.orders() == [] and env.fills() == []
    assert {c["name"] for c in pv["checks"]} >= {"environment", "kill_switch", "data_fresh", "buying_power", "position_cap", "risk_per_trade", "event_risk", "confirmation"}


async def test_market_buy_fills_with_exact_decimal_accounting_and_reconciles(env):
    r = await buy(env, btc_order())
    o = r["order"]
    assert r["duplicate"] is False and o["state"] == "filled" and o["filled_qty"] == "0.1" and Dec(o["avg_fill_price"]) == Dec("70015.0002")
    assert [e["event"] for e in o["events"]] == ["accepted", "fill"] and o["data_status"] == "LIVE" and o["environment"] == "paper"
    f = env.fills()[0]
    assert (f["qty"], f["fee"], f["data_status"], f["provider"]) == ("0.1", "7.00150002", "LIVE", "coinbase") and "ask" in f["note"]
    pf = env.portfolio(None)
    assert Dec(pf["cash"]) == Dec("100000") - Dec("7008.50152002") == Dec("92991.49847998")
    p = env.positions(pf["id"])[0]
    assert Dec(p["qty"]) == Dec("0.1") and Dec(p["avg_cost"]) == Dec("70085.0152002") and p["planned_stop"] == "68000"     # fee capitalised into cost
    assert env.reconcile(pf["id"])["consistent"] is True


async def test_idempotency_key_prevents_a_second_order(env):
    o = btc_order()
    pv = await env.preview(o)
    a = await env.submit(o, pv["preview_id"], "same-key-1")
    cash = env.portfolio(None)["cash"]
    b = await env.submit(btc_order(qty="9"), "ignored", "same-key-1")                           # a retry, even with different content, returns the original
    assert b["duplicate"] is True and b["order"]["id"] == a["order"]["id"] and len(env.orders()) == 1 and env.portfolio(None)["cash"] == cash
    with pytest.raises(EngineError) as e:
        await env.submit(o, pv["preview_id"], "short")
    assert e.value.code == "IDEMPOTENCY_KEY_REQUIRED"


async def test_confirmation_flow_blocks_unconfirmed_changed_expired_previews(env):
    o = btc_order()
    for pid, code in ((None, "PREVIEW_REQUIRED"), ("nope", "PREVIEW_REQUIRED")):
        with pytest.raises(EngineError) as e:
            await env.submit(o, pid, "key-aaaaaaa")
        assert e.value.code == code and e.value.status == 409
    pv = await env.preview(o)
    with pytest.raises(EngineError) as e:
        await env.submit(btc_order(qty="0.2"), pv["preview_id"], "key-bbbbbbb")                 # different from what was previewed
    assert e.value.code == "PREVIEW_MISMATCH"
    env.mk[3].t += 61
    with pytest.raises(EngineError) as e:
        await env.submit(o, pv["preview_id"], "key-ccccccc")
    assert e.value.code == "PREVIEW_EXPIRED" and env.orders() == []
    pv = await env.preview(o)
    await env.submit(o, pv["preview_id"], "key-ddddddd")
    with pytest.raises(EngineError):
        await env.submit(o, pv["preview_id"], "key-eeeeeee")                                    # a preview is single-use


async def test_risk_is_rechecked_at_submit(env):
    o = btc_order()
    pv = await env.preview(o)
    assert pv["verdict"] == "APPROVE_FOR_PAPER_REVIEW"
    await env.set_halted(True)                                                                 # state changes between preview and confirm
    with pytest.raises(EngineError) as e:
        await env.submit(o, pv["preview_id"], "key-fffffff")
    assert e.value.code == "RISK_REJECTED" and e.value.status == 422 and e.value.extra["verdict"] == "REJECT"
    assert any(c["name"] == "kill_switch" and c["status"] == "fail" for c in e.value.extra["checks"]) and env.orders() == []
    await env.set_halted(False)
    big = btc_order(qty="2")                                                                   # 140k notional: cap/buying power
    assert (await env.preview(big))["verdict"] == "REJECT"
    pv = await env.preview(big)
    with pytest.raises(EngineError):
        await env.submit(big, pv["preview_id"], "key-ggggggg")


async def test_partial_fills_follow_volume_participation_and_complete(env):
    book, *_ = env.mk
    book["BTC-USD"]["volume"] = 5.0                                                            # 1% participation -> 0.05 BTC per evaluation
    r = await buy(env, btc_order(qty="0.12"))
    assert r["order"]["state"] == "partially_filled" and r["order"]["filled_qty"] == "0.05" and r["order"]["remaining_qty"] == "0.07"
    await env.evaluate()
    assert env.orders()[0]["state"] == "partially_filled" and env.orders()[0]["filled_qty"] == "0.1"
    await env.evaluate()
    o = env.orders()[0]
    assert o["state"] == "filled" and o["filled_qty"] == "0.12" and Dec(o["avg_fill_price"]) == Dec("70015.0002")
    assert [e["event"] for e in o["events"]] == ["accepted", "partial_fill", "partial_fill", "fill"] and len(env.fills()) == 3
    assert any("partial fill capped" in f["note"] for f in env.fills())
    assert env.reconcile(1)["consistent"] is True


async def test_passive_limit_waits_reserves_cash_then_fills_at_limit(env):
    book, *_ = env.mk
    await env.set_halted(False)
    env.set_limits({"max_position_pct": 100, "max_risk_per_trade_pct": 2, "max_aggregate_risk_pct": 5})
    lim = btc_order(qty="1.3", type="limit", limit_price=69000, planned_stop=68000)
    r = await buy(env, lim)
    assert r["order"]["state"] == "working" and env.fills() == []
    second = btc_order(qty="0.2")                                                              # needs ~14k; only ~10.3k unreserved
    pv = await env.preview(second)
    assert pv["verdict"] == "REJECT" and next(c for c in pv["checks"] if c["name"] == "buying_power")["status"] == "fail"
    book["BTC-USD"].update(price=68990.0, bid=68989.0, ask=69010.0)                           # ask above the limit; last printed below it
    await env.evaluate()
    o = env.orders()[0]
    assert o["state"] == "filled" and Dec(o["avg_fill_price"]) == Dec("69000") and "through" in env.fills()[0]["note"]


async def test_marketable_limit_gets_price_improvement(env):
    book, *_ = env.mk
    env.set_limits({"max_position_pct": 100, "max_risk_per_trade_pct": 2, "max_aggregate_risk_pct": 5})
    book["BTC-USD"].update(price=68900.0, bid=68899.0, ask=68901.0)
    r = await buy(env, btc_order(qty="0.1", type="limit", limit_price=69000, planned_stop=67000))
    assert Dec(r["order"]["avg_fill_price"]) == Dec("68901")                                   # better of limit 69000 and ask 68901


async def test_stop_sell_triggers_fills_at_market_below_the_stop_and_realizes_loss(env):
    book, *_ = env.mk
    await buy(env, btc_order())
    stop = OrderIn(instrument_id="BTC-USD", side="sell", qty="0.1", type="stop", stop_price=69000)
    r = await buy(env, stop)
    assert r["order"]["state"] == "working" and r["order"]["triggered"] == 0
    book["BTC-USD"].update(price=68500.0, bid=68499.0, ask=68501.0)                           # gapped through the stop
    await env.evaluate()
    o = env.orders()[0]
    assert o["state"] == "filled" and Dec(o["avg_fill_price"]) == Dec("68485.3002") and Dec(o["avg_fill_price"]) < 69000      # filled at market, not at the stop
    assert any(e["event"] == "triggered" for e in o["events"])
    pos = env.db.q("SELECT * FROM positions WHERE portfolio_id=1")[0]
    # proceeds = 0.1*68485.3002 - fee 6.84853002 = 6841.68148998 ; cost basis 7008.50152002 ; realized -166.82003004
    assert Dec(pos["qty"]) == 0 and Dec(pos["realized"]) == Dec("-166.82003004") and env.positions(1) == []
    assert Dec(env.portfolio(None)["cash"]) == Dec("100000") + Dec("-166.82003004") and env.reconcile(1)["consistent"] is True


async def test_cancel_and_cancel_failures(env):
    r = await buy(env, btc_order(type="limit", limit_price=60000, planned_stop=58000))
    oid = r["order"]["id"]
    res_before = env._reserved(1)[0]
    assert res_before == Dec("0.1") * 60000
    c = await env.cancel(oid)
    assert c["state"] == "cancelled" and c["events"][-1]["event"] == "cancelled" and env._reserved(1)[0] == 0           # reservation released
    with pytest.raises(EngineError) as e:
        await env.cancel(oid)
    assert e.value.code == "ORDER_NOT_CANCELABLE" and e.value.status == 409
    filled = await buy(env, btc_order())
    with pytest.raises(EngineError) as e:
        await env.cancel(filled["order"]["id"])
    assert e.value.code == "ORDER_NOT_CANCELABLE"
    with pytest.raises(EngineError) as e:
        await env.cancel(9999)
    assert e.value.code == "ORDER_NOT_FOUND" and e.value.status == 404


async def test_stale_and_unavailable_data_block_orders_and_fills(env):
    book, cb, yh, clock = env.mk
    cb.age = 600                                                                                 # 10-minute-old crypto quote: STALE
    pv = await env.preview(btc_order())
    assert pv["verdict"] == "NEEDS_MORE_DATA" and next(c for c in pv["checks"] if c["name"] == "data_fresh")["status"] == "needs_data"
    with pytest.raises(EngineError) as e:
        await env.submit(btc_order(), pv["preview_id"], "key-stale-1")
    assert e.value.extra["verdict"] == "NEEDS_MORE_DATA"
    cb.age = 0
    r = await buy(env, btc_order(type="limit", limit_price=60000, planned_stop=58000))                               # working order
    cb.age = 600
    for _ in range(3):
        await env.evaluate()                                                                     # stale: nothing may fill, and the event is not spammed
    ev = [e["event"] for e in env.orders()[0]["events"]]
    assert ev.count("skipped_no_fresh_data") == 1 and env.fills() == []
    cb.age, cb.fail = 0, True
    assert (await env.preview(btc_order()))["verdict"] == "NEEDS_MORE_DATA"
    await env.evaluate()
    assert env.fills() == []


# --- equities: sessions, TIF, lots ------------------------------------------------------------
async def test_equity_session_rules_queue_limits_reject_market_orders_and_fill_at_open(env):
    book, cb, yh, clock = env.mk
    clock.t = utc(2026, 3, 7, 15)                                                                 # Saturday
    mk = OrderIn(instrument_id="AAPL", side="buy", qty=10, type="market", planned_stop=190)
    pv = await env.preview(mk)
    assert pv["verdict"] == "REJECT" and next(c for c in pv["checks"] if c["name"] == "market_session")["status"] == "fail"
    lim = OrderIn(instrument_id="AAPL", side="buy", qty=10, type="limit", limit_price=190, planned_stop=180)
    r = await buy(env, lim)
    assert r["order"]["state"] == "working" and r["order"]["events"][-1]["event"] == "waiting" and "CLOSED" in r["order"]["events"][-1]["detail"]
    await env.evaluate()
    assert len([e for e in env.orders()[0]["events"] if e["event"] == "waiting"]) == 1            # throttled
    clock.t = utc(2026, 3, 9, 15)                                                                 # Monday, regular session
    book["AAPL"].update(price=189.0, bid=188.99, ask=189.01)
    await env.evaluate()
    o = env.orders()[0]
    assert o["state"] == "filled" and Dec(o["avg_fill_price"]) == Dec("189.01") and Dec(env.fills()[0]["fee"]) == 0


async def test_day_orders_expire_at_the_session_close_including_dst_and_early_close(env):
    book, cb, yh, clock = env.mk
    clock.t = utc(2026, 3, 9, 15)                                                                 # Mon, EDT: close 20:00 UTC
    await buy(env, OrderIn(instrument_id="AAPL", side="buy", qty=10, type="limit", limit_price=150, tif="DAY", planned_stop=140))
    assert env.orders()[0]["expires_at"].startswith("2026-03-09T20:00:00")
    clock.t = utc(2026, 3, 9, 19, 59)
    await env.evaluate()
    assert env.orders()[0]["state"] == "working"
    clock.t = utc(2026, 3, 9, 20, 1)
    await env.evaluate()
    o = env.orders()[0]
    assert o["state"] == "expired" and o["events"][-1]["event"] == "expired"
    clock.t = utc(2026, 11, 27, 15)                                                               # day after Thanksgiving: early close 18:00 UTC
    await buy(env, OrderIn(instrument_id="AAPL", side="buy", qty=10, type="limit", limit_price=150, tif="DAY", planned_stop=140))
    assert env.orders()[0]["expires_at"].startswith("2026-11-27T18:00:00")


async def test_equity_lot_rules_and_crypto_min_size(env):
    book, cb, yh, clock = env.mk
    clock.t = utc(2026, 3, 9, 15)
    frac = await env.preview(OrderIn(instrument_id="AAPL", side="buy", qty="1.5", type="limit", limit_price=190, planned_stop=180))
    assert frac["verdict"] == "REJECT" and next(c for c in frac["checks"] if c["name"] == "quantity")["status"] == "fail"
    tiny = await env.preview(btc_order(qty="0.000001"))
    assert tiny["verdict"] == "REJECT"
    idx = await env.preview(OrderIn(instrument_id="SPX", side="buy", qty=1, type="limit", limit_price=5000, planned_stop=4000))
    assert idx["verdict"] == "REJECT" and next(c for c in idx["checks"] if c["name"] == "instrument")["status"] == "fail"


# --- risk gate behaviours -----------------------------------------------------------------------
async def test_sells_need_a_position_exits_are_allowed_after_the_daily_loss_limit(env):
    sell = OrderIn(instrument_id="BTC-USD", side="sell", qty="0.1", type="market")
    pv = await env.preview(sell)
    assert pv["verdict"] == "REJECT" and next(c for c in pv["checks"] if c["name"] == "position_available")["status"] == "fail"       # no shorting
    await buy(env, btc_order())
    env.snapshot_equity_value(1, Dec("100000"), Dec("92991.49847998"), min_gap=0)                   # start-of-day equity on record
    env.db.x("UPDATE portfolios SET cash=? WHERE id=1", ("88000",))                                  # simulate a large loss: equity ~95k -> >3% down
    blocked = await env.preview(btc_order())
    dl = next(c for c in blocked["checks"] if c["name"] == "daily_loss")
    assert blocked["verdict"] == "REJECT" and dl["status"] == "fail" and "exits are allowed" in dl["detail"]
    assert (await env.preview(sell))["verdict"] == "APPROVE_FOR_PAPER_REVIEW"                       # closing risk is never blocked


async def test_kill_switch_blocks_new_orders_and_can_cancel_open_ones(env):
    r1 = await buy(env, btc_order(type="limit", limit_price=60000, planned_stop=58000))
    r2 = await buy(env, btc_order(type="limit", limit_price=59000, planned_stop=57000))
    out = await env.set_halted(True, cancel_open=True)
    assert out["halted"] and sorted(out["cancelled_orders"]) == sorted([r1["order"]["id"], r2["order"]["id"]])
    assert all(o["state"] == "cancelled" and o["reason"] == "cancelled by kill switch" for o in env.orders())
    pv = await env.preview(btc_order())
    assert pv["verdict"] == "REJECT" and next(c for c in pv["checks"] if c["name"] == "kill_switch")["status"] == "fail"
    await env.set_halted(False)
    assert (await env.preview(btc_order()))["verdict"] == "APPROVE_FOR_PAPER_REVIEW"


async def test_risk_limits_are_validated_and_enforced(env):
    for bad in ({"max_position_pct": 0}, {"max_position_pct": 500}, {"daily_loss_warning_pct": 9}, {"unknown_field": 1}):
        with pytest.raises(Exception):
            env.set_limits(bad)
    assert env.limits().max_position_pct == 10                                                     # a rejected update changes nothing
    env.set_limits({"max_position_pct": 5})
    pv = await env.preview(btc_order())                                                            # 7% position now exceeds the 5% cap
    assert pv["verdict"] == "REJECT" and next(c for c in pv["checks"] if c["name"] == "position_cap")["status"] == "fail"
    env.set_limits({"blocked_symbols": ["btc-usd"], "max_position_pct": 10})
    assert (await env.preview(btc_order()))["verdict"] == "REJECT"


# --- portfolios, valuation, sizing, reconciliation -------------------------------------------------
async def test_valuation_exposure_and_unpriced_positions(env):
    book, cb, yh, clock = env.mk
    await buy(env, btc_order())
    clock.t = utc(2026, 3, 9, 15)
    await buy(env, OrderIn(instrument_id="AAPL", side="buy", qty=10, type="limit", limit_price=250, planned_stop=205))     # marketable: fills at ask (planned risk 450 stays under 0.5% of equity)
    v = await env.valuation(1)
    by = {p["symbol"]: p for p in v["positions"]}
    assert by["BTC-USD"]["mark"] == Dec(70000) and by["BTC-USD"]["value"] == Dec("7000.0") and by["AAPL"]["value"] == Dec("2000.0")
    assert v["equity"] == v["cash"] + Dec("7000.0") + Dec("2000.0") and v["unpriced_positions"] == 0
    assert set(v["exposure"]["by_asset_class"]) == {"crypto", "equity"} and set(v["exposure"]["by_sector"]) == {"Crypto", "Technology"}
    assert sum(x["value"] for x in v["exposure"]["by_asset_class"].values()) == v["exposure"]["gross"]
    assert by["BTC-USD"]["unrealized"] == Dec("0.1") * (Dec(70000) - Dec("70085.0152002"))
    cb.fail = True                                                                                  # the price disappears
    v2 = await env.valuation(1)
    b2 = next(p for p in v2["positions"] if p["symbol"] == "BTC-USD")
    assert b2["valuation"] == "at_cost" and b2["mark"] is None and "at cost" in v2["valuation_note"] and v2["unpriced_positions"] == 1
    assert (await env.preview(btc_order()))["verdict"] == "NEEDS_MORE_DATA"


async def test_manual_portfolio_is_user_entered_and_cannot_trade(env):
    m = env.create_portfolio("My holdings", "manual", Dec(5000))
    with pytest.raises(EngineError) as e:
        await env.preview(btc_order(portfolio_id=m["id"]))
    assert e.value.code == "MANUAL_PORTFOLIO" and e.value.status == 409
    env.set_manual_position(m["id"], "AAPL", Dec(10), Dec(150))
    env.set_manual_position(m["id"], "BTC-USD", Dec("0.5"), Dec(30000))
    v = await env.valuation(m["id"])
    assert v["cash"] == 5000 and v["equity"] == Dec(5000) + Dec(10) * Dec("200.0") + Dec("0.5") * Dec("70000.0")
    env.set_manual_position(m["id"], "AAPL", Dec(0), Dec(0))                                       # qty 0 removes it
    assert [p["symbol"] for p in env.positions(m["id"])] == ["BTC-USD"]
    for fn in (lambda: env.set_manual_position(1, "AAPL", Dec(1), Dec(1)), lambda: env.set_manual_cash(1, Dec(1))):
        with pytest.raises(EngineError) as e:
            fn()
        assert e.value.code == "NOT_MANUAL"
    for bad in (lambda: env.set_manual_position(m["id"], "AAPL", Dec(-1), Dec(1)), lambda: env.set_manual_position(m["id"], "SPX", Dec(1), Dec(1)),
                lambda: env.create_portfolio("My holdings", "manual", Dec(1)), lambda: env.create_portfolio("x", "margin", Dec(1))):
        with pytest.raises(EngineError):
            bad()
    assert env.reconcile(m["id"])["applicable"] is False


async def test_position_sizing_picks_the_binding_constraint(env):
    s = await env.size(None, "AAPL", Dec(100), Dec(98))
    assert Dec(s["by_risk"]) == Dec(250) and Dec(s["by_position_cap"]) == Dec(100) and s["qty"] == "100" and s["binding_constraint"] == "position cap"
    s = await env.size(None, "AAPL", Dec(100), Dec(95))                                            # 0.5% of 100k = 500 / 5 = 100 shares: risk and cap tie
    assert s["qty"] == "100"
    s = await env.size(None, "AAPL", Dec(100), Dec(90), risk_pct=0.2)                              # 200/10 = 20 shares
    assert s["qty"] == "20" and s["binding_constraint"] == "risk per trade" and Dec(s["planned_risk"]) == Dec(200)
    b = await env.size(None, "BTC-USD", Dec(70000), Dec(68000))
    assert Dec(b["qty"]) == Dec("0.14285714") and b["binding_constraint"] == "position cap"        # 10k / 70000, floored to 8 dp
    for bad in ((Dec(100), Dec(100)), (Dec(100), Dec(110)), (Dec(-1), Dec(1))):
        with pytest.raises(EngineError):
            await env.size(None, "AAPL", *bad)


async def test_reconcile_detects_tampering(env):
    await buy(env, btc_order())
    assert env.reconcile(1)["consistent"] is True
    env.db.x("UPDATE portfolios SET cash='1' WHERE id=1")
    r = env.reconcile(1)
    assert r["consistent"] is False and r["issues"][0]["what"] == "cash"
    env.db.x("UPDATE portfolios SET cash=? WHERE id=1", ("92991.49847998",))
    env.db.x("UPDATE positions SET qty='5' WHERE portfolio_id=1")
    assert any(i["what"].startswith("position") for i in env.reconcile(1)["issues"])


async def test_reset_paper_requires_a_paper_portfolio_and_restores_cash(env):
    await buy(env, btc_order())
    m = env.create_portfolio("m", "manual", Dec(1))
    with pytest.raises(EngineError):
        env.reset_paper(m["id"])
    env.reset_paper(1)
    assert env.portfolio(1)["cash"] == "100000" and env.orders() == [] and env.fills() == [] and env.positions(1) == []


async def test_equity_history_sampling_throttle_and_day_start(env):
    clock = env.mk[3]
    clock.t = utc(2026, 3, 9, 15)
    assert env.snapshot_equity_value(1, Dec(100_000), Dec(100_000)) is True
    clock.t += 30
    assert env.snapshot_equity_value(1, Dec(99_000), Dec(99_000)) is False                         # within the 60 s throttle
    clock.t += 31
    assert env.snapshot_equity_value(1, Dec(98_000), Dec(98_000)) is True
    assert env.day_start_equity(1) == Dec(100_000)                                                  # first sample of the New York day
    clock.t = utc(2026, 3, 10, 15)
    assert env.day_start_equity(1) is None                                                          # new day: not yet recorded


# --- analytics (constructed returns with known answers) --------------------------------------------
def candles(rets, offset_hours=0, start=100.0):
    closes = [start]
    for r in rets:
        closes.append(closes[-1] * (1 + r))
    d = datetime.now(timezone.utc).replace(hour=offset_hours, minute=0, second=0, microsecond=0)
    days = []
    while len(days) < len(closes):                                                                  # weekdays only, newest last
        if d.weekday() < 5:
            days.append(int(d.timestamp()))
        d -= timedelta(days=1)
    days.reverse()
    return [Candle(time=t, open=c, high=c * 1.001, low=c * 0.999, close=c, volume=1000.0) for t, c in zip(days, closes)]


async def make_portfolio(db, hist, positions):
    book = {s: {"price": 100.0, "bid": 99.99, "ask": 100.01} for s in ("BTC-USD", "AAPL", "SPY")}
    cb, yh = Market("coinbase", book, {k: v for k, v in hist.items() if k == "BTC-USD"}), Market("yahoo", book, {k: v for k, v in hist.items() if k != "BTC-USD"})
    eng = TradingEngine(db, MarketService({"coinbase": cb, "yahoo": yh}))
    m = eng.create_portfolio("t", "manual", Dec(50_000))
    for sym, qty in positions.items():
        eng.set_manual_position(m["id"], sym, Dec(qty), Dec(100))
    return eng, m["id"], (cb, yh)


async def test_var_es_drawdown_and_vol_exact_on_constructed_returns(db):
    r = [-0.02] * 11 + [0.001] * 189                                                               # 11 bad days of 200: the 5th percentile is exactly -2%
    import random

    random.Random(4).shuffle(r)
    eng, pid, _ = await make_portfolio(db, {"BTC-USD": candles(r)}, {"BTC-USD": "500"})            # 500 * 100 = 50k of 100k equity: weight 0.5
    out = await analytics.portfolio_risk(eng, pid, "none")
    assert out["available"] and out["observations"] == 200 and out["window"]["weights"]["BTC-USD"] == pytest.approx(0.5)
    assert out["var_95_1d"]["pct"] == pytest.approx(1.0) and out["var_95_1d"]["amount"] == pytest.approx(1000.0)      # 0.5 * 2% of 100k
    assert out["es_95_1d"]["pct"] == pytest.approx(1.0) and out["es_95_1d"]["tail_observations"] == 11
    assert out["worst_day_pct"] == pytest.approx(-1.0) and out["var_99_1d"]["pct"] == pytest.approx(1.0)
    assert out["volatility_ann_pct"] > 0 and out["max_drawdown_pct"] < 0 and any("Not a forecast" in a for a in out["assumptions"])
    assert out["concentration"]["top_position"] == "BTC-USD" and out["concentration"]["hhi_invested"] == pytest.approx(1.0)
    liq = out["liquidity"]["positions"][0]
    assert liq["adv_usd_20d"] == pytest.approx(sum(c.close * 1000 for c in candles(r)[-20:]) / 20) and liq["days_to_exit_at_10pct"] > 0


async def test_beta_correlation_and_unavailable_cases(db):
    import numpy as np

    rng = np.random.default_rng(7)
    base = list(rng.normal(0, 0.01, 150))
    hist = {"SPY": candles(base, 4), "AAPL": candles([2 * x for x in base], 4), "BTC-USD": candles([-x for x in base], 0)}
    eng, pid, _ = await make_portfolio(db, hist, {"AAPL": "100", "BTC-USD": "100"})
    out = await analytics.portfolio_risk(eng, pid, "SPY")
    assert out["beta"]["by_position"]["AAPL"] == pytest.approx(2.0) and out["beta"]["by_position"]["BTC-USD"] == pytest.approx(-1.0)
    c = out["correlation"]["matrix"]
    assert c[0][1] == pytest.approx(-1.0) and c[0][0] == pytest.approx(1.0) and out["most_correlated"][0]["corr"] == pytest.approx(-1.0)
    assert out["var_99_1d"]["available"] is False and "need 200" in out["var_99_1d"]["reason"]            # 150 obs: no 1% tail claimed
    short = await make_portfolio(db.__class__(":memory:"), {"BTC-USD": candles([0.01] * 30)}, {"BTC-USD": "10"})
    r = await analytics.portfolio_risk(short[0], short[1], "none")
    assert r["available"] is False and "overlapping" in r["reason"]
    empty = await make_portfolio(db.__class__(":memory:"), {}, {})
    assert (await analytics.portfolio_risk(empty[0], empty[1]))["reason"] == "no positions"
    eng2, pid2, (cb2, yh2) = await make_portfolio(db.__class__(":memory:"), hist, {"AAPL": "100"})
    yh2.fail = True
    r = await analytics.portfolio_risk(eng2, pid2, "SPY")
    assert r["available"] is False and "history unavailable" in r["reason"]


async def test_scenarios_explicit_and_beta_implied(db):
    import numpy as np

    rng = np.random.default_rng(9)
    base = list(rng.normal(0, 0.01, 150))
    hist = {"SPY": candles(base, 4), "AAPL": candles([2 * x for x in base], 4), "BTC-USD": candles(list(rng.normal(0, 0.02, 150)), 0)}
    eng, pid, _ = await make_portfolio(db, hist, {"AAPL": "100", "BTC-USD": "50"})                 # AAPL 10,000 ; BTC 5,000 ; cash 50,000 ; equity 65,000
    s = await analytics.scenario(eng, pid, {"BTC-USD": -10, "aapl": -5})
    assert Dec(s["pnl"]) == Dec(-500) + Dec(-500) and s["pnl_pct_of_equity"] == pytest.approx(-1000 / 65000 * 100) and Dec(s["equity_after"]) == Dec(64_000)
    assert [p["source"] for p in s["positions"]] == ["explicit", "explicit"] and s["ignored_shocks"] == []
    only = await analytics.scenario(eng, pid, {"BTC-USD": -10, "TSLA": -50})
    assert Dec(only["pnl"]) == Dec(-500) and only["ignored_shocks"] == ["TSLA"]                      # unknown symbol is reported, not silently dropped
    bs = await analytics.scenario(eng, pid, {}, "SPY", -5)
    aapl = next(p for p in bs["positions"] if p["symbol"] == "AAPL")
    assert aapl["shock_pct"] == pytest.approx(-10.0) and "beta-implied" in aapl["source"] and Dec(aapl["pnl"]) == Dec(-1000)            # beta 2 x -5%
    assert next(p for p in bs["positions"] if p["symbol"] == "BTC-USD")["source"].startswith("beta-implied")
    for bad in ({"shocks": {"AAPL": -150}}, {"shocks": {}, "benchmark_shock": -5}, {"shocks": {}, "benchmark": "SPY", "benchmark_shock": 2000}):
        with pytest.raises(ValueError):
            await analytics.scenario(eng, pid, **bad)
    nob = await analytics.scenario(eng, pid, {}, "none", -5)
    assert "unavailable" in (nob["note"] or "") and Dec(nob["pnl"]) == 0


async def test_performance_from_history(db):
    eng, pid, _ = await make_portfolio(db, {}, {})
    assert "fewer than 2" in analytics.performance(eng, pid)["reason"]
    for i, e in enumerate((100, 110, 99, 105)):
        eng.db.x("INSERT INTO equity_history VALUES(?,?,?,?)", (pid, f"2026-03-0{i + 1}T12:00:00+00:00", str(e), "0"))
    p = analytics.performance(eng, pid)
    assert p["samples"] == 4 and p["max_drawdown_pct"] == pytest.approx((99 / 110 - 1) * 100) and p["total_return_pct"] == pytest.approx(5.0)


# --- API --------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    book = {"BTC-USD": dict(BTC_BOOK), "AAPL": dict(AAPL_BOOK), "SPX": dict(SPX_BOOK)}
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), demo=False, alert_loop=False,
                               providers={"coinbase": Market("coinbase", book), "yahoo": Market("yahoo", book)})) as c:
        c.book = book
        yield c


def test_api_end_to_end_paper_flow(client):
    body = {"instrument_id": "BTC-USD", "side": "buy", "qty": "0.1", "type": "market", "planned_stop": "68000"}
    pv = client.post("/api/orders/preview", json=body).json()["data"]
    assert pv["verdict"] == "APPROVE_FOR_PAPER_REVIEW" and pv["order"]["symbol"] == "BTC-USD"
    r = client.post("/api/orders/paper", json={"order": body, "preview_id": pv["preview_id"], "client_key": "api-key-0001"}).json()["data"]
    assert r["order"]["state"] == "filled" and r["duplicate"] is False and Dec(r["order"]["avg_fill_price"]) == Dec("70015.0002")
    again = client.post("/api/orders/paper", json={"order": body, "preview_id": pv["preview_id"], "client_key": "api-key-0001"}).json()["data"]
    assert again["duplicate"] is True and len(client.get("/api/orders").json()["data"]) == 1
    pf = client.get("/api/portfolio").json()["data"]
    assert pf["cash"] == "92991.49847998" and pf["positions"][0]["symbol"] == "BTC-USD" and pf["halted"] is False and pf["positions"][0]["valuation"] == "mark"
    assert len(client.get("/api/fills").json()["data"]) == 1 and client.get("/api/portfolio/reconcile").json()["data"]["consistent"] is True
    assert client.get("/api/orders", params={"state": "open"}).json()["data"] == [] and len(client.get("/api/orders", params={"state": "filled"}).json()["data"]) == 1
    assert client.get("/api/market/status").json()["data"]["broker_env"] == "PAPER"


def test_api_errors_and_safety(client):
    post = client.post
    bad = post("/api/orders/preview", json={"instrument_id": "BTC-USD", "side": "buy", "qty": "0.1", "type": "market", "limit_price": "5"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_REQUEST"
    assert post("/api/orders/preview", json={"instrument_id": "NOPE123456", "side": "buy", "qty": 1}).json()["error"]["code"] == "UNKNOWN_INSTRUMENT"
    noprev = post("/api/orders/paper", json={"order": {"instrument_id": "BTC-USD", "side": "buy", "qty": "0.1"}, "client_key": "api-key-0002"})
    assert noprev.status_code == 409 and noprev.json()["error"]["code"] == "PREVIEW_REQUIRED"
    live = post("/api/orders/live", json={"instrument_id": "BTC-USD", "side": "buy", "qty": "0.1"})
    assert live.status_code == 403 and live.json()["error"]["code"] == "LIVE_TRADING_DISABLED"
    assert client.app.state.db.q("SELECT COUNT(*) FROM audit_log WHERE action='live_order_refused'")[0][0] == 1
    st = client.get("/api/trading/status").json()["data"]
    assert st["environment"] == "PAPER" and st["live_trading_enabled"] is False
    assert post("/api/portfolios/1/reset", json={}).json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert client.get("/api/portfolio", params={"pid": 999}).status_code == 404


def test_api_limits_halt_and_manual_portfolio(client):
    assert client.put("/api/risk/limits", json={"max_position_pct": 0}).json()["error"]["code"] == "INVALID_LIMITS"
    assert client.put("/api/risk/limits", json={"nonsense": 1}).status_code == 422
    assert client.put("/api/risk/limits", json={"max_position_pct": 5}).json()["data"]["max_position_pct"] == 5 and client.get("/api/risk/limits").json()["data"]["max_position_pct"] == 5
    body = {"instrument_id": "BTC-USD", "side": "buy", "qty": "0.1", "type": "market", "planned_stop": "68000"}
    assert client.post("/api/orders/preview", json=body).json()["data"]["verdict"] == "REJECT"                      # 7% > 5% cap
    client.put("/api/risk/limits", json={"max_position_pct": 10})
    assert client.post("/api/trading/halt", json={"halted": True}).json()["data"]["halted"] is True
    assert client.post("/api/orders/preview", json=body).json()["data"]["verdict"] == "REJECT"
    assert client.get("/api/market/status").json()["data"]["trading_halted"] is True
    client.post("/api/trading/halt", json={"halted": False})
    m = client.post("/api/portfolios", json={"name": "Holdings", "kind": "manual", "starting_cash": "2500.50"}).json()["data"]
    assert client.put(f"/api/portfolios/{m['id']}/manual/position", json={"instrument_id": "AAPL", "qty": "10", "avg_cost": "150"}).json()["ok"]
    pf = client.get("/api/portfolio", params={"pid": m["id"]}).json()["data"]
    assert pf["cash"] == "2500.5" and pf["positions"][0]["qty"] == "10" and Dec(pf["equity"]) == Dec("2500.50") + Dec(10) * Dec("200.0")
    assert client.post("/api/orders/preview", json={**body, "portfolio_id": m["id"]}).json()["error"]["code"] == "MANUAL_PORTFOLIO"
    assert client.post("/api/portfolios", json={"name": "Holdings", "kind": "manual"}).status_code == 409
    assert client.get("/api/risk/size", params={"instrument_id": "AAPL", "entry": "100", "stop": "98"}).json()["data"]["qty"] == "100"
    assert client.get("/api/risk/size", params={"instrument_id": "AAPL", "entry": "100", "stop": "abc"}).status_code == 422


def test_api_persists_orders_positions_and_limits_across_restart(tmp_path):
    book = {"BTC-USD": dict(BTC_BOOK), "AAPL": dict(AAPL_BOOK), "SPX": dict(SPX_BOOK)}
    mk = lambda: TestClient(create_app(db_path=str(tmp_path / "p.db"), demo=False, alert_loop=False,
                                       providers={"coinbase": Market("coinbase", book), "yahoo": Market("yahoo", book)}))
    body = {"instrument_id": "BTC-USD", "side": "buy", "qty": "0.1", "type": "market", "planned_stop": "68000"}
    with mk() as c:
        pv = c.post("/api/orders/preview", json=body).json()["data"]
        c.post("/api/orders/paper", json={"order": body, "preview_id": pv["preview_id"], "client_key": "persist-key-1"})
        c.put("/api/risk/limits", json={"max_position_pct": 12})
        c.post("/api/trading/halt", json={"halted": True})
    with mk() as c2:
        pf = c2.get("/api/portfolio").json()["data"]
        assert pf["cash"] == "92991.49847998" and pf["positions"][0]["qty"] == "0.1" and pf["halted"] is True      # the kill switch survives a restart
        assert c2.get("/api/risk/limits").json()["data"]["max_position_pct"] == 12 and len(c2.get("/api/orders").json()["data"]) == 1
        retry = c2.post("/api/orders/paper", json={"order": body, "preview_id": "x", "client_key": "persist-key-1"}).json()["data"]
        assert retry["duplicate"] is True                                                                       # the idempotency key survives too


