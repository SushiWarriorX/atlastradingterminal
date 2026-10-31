from datetime import datetime, timezone
from decimal import Decimal as Dec

import pytest
from pydantic import ValidationError

from atlas_api.models import DataStatus, Provenance, Quote
from atlas_api.trading import sim
from atlas_api.trading.accounting import AccountingError, Position, apply_fill
from atlas_api.trading.models import OrderIn, RiskLimits, SimParams
from atlas_api.trading.money import D, q
from atlas_api.trading.risk import RiskContext, check, entry_estimate

P = SimParams()


def quote(price=100.0, bid=None, ask=None, volume=None, status=DataStatus.LIVE):
    return Quote(instrument_id="X", price=price, bid=bid, ask=ask, volume=volume, prev_close=price,
                 prov=Provenance(provider="t", instrument_id="X", ingested_time=datetime.now(timezone.utc), status=status))


def order(**kw):
    base = {"side": "buy", "type": "market", "qty_remaining": Dec(10), "limit_price": None, "stop_price": None, "triggered": False}
    return {**base, **kw}


# --- money / models -------------------------------------------------------------------
def test_decimal_from_float_is_exact():
    assert D(0.1) + D(0.2) == Dec("0.3")               # 0.1 + 0.2 != 0.3 in binary floating point
    assert q(D(2.675), 2) == Dec("2.68")


def test_order_validation():
    ok = OrderIn(instrument_id="BTC", side="buy", qty=0.5, type="limit", limit_price="70000.5")
    assert ok.qty == Dec("0.5") and ok.limit_price == Dec("70000.5")
    for bad in ({"qty": 0}, {"qty": -1}, {"type": "limit"}, {"type": "stop"}, {"type": "stop_limit", "stop_price": 1},
                {"type": "market", "limit_price": 1}, {"type": "limit", "limit_price": 1, "stop_price": 1}, {"type": "stop", "stop_price": 1, "limit_price": 1},
                {"qty": "abc"}, {"planned_stop": 0}, {"side": "short"}, {"type": "limit", "limit_price": -5}):
        with pytest.raises(ValidationError):
            OrderIn(**{"instrument_id": "X", "side": "buy", "qty": 1, **bad})


def test_risk_limits_validation():
    assert RiskLimits().max_risk_per_trade_pct == 0.5
    for bad in ({"max_position_pct": 0}, {"max_position_pct": 101}, {"daily_loss_warning_pct": 5, "max_daily_loss_pct": 3},
                {"max_risk_per_trade_pct": 3, "max_aggregate_risk_pct": 2}):
        with pytest.raises(ValidationError):
            RiskLimits(**bad)


# --- accounting (hand-computed) ---------------------------------------------------------
def test_average_cost_realized_pnl_and_fees_by_hand():
    pos, cash = Position(), Dec(100_000)
    pos, cash = apply_fill(pos, cash, "buy", Dec(10), Dec(100), Dec(1))        # cost 1001 -> avg 100.1
    assert (pos.qty, pos.avg_cost, cash) == (10, Dec("100.1"), Dec(98_999))
    pos, cash = apply_fill(pos, cash, "buy", Dec(10), Dec(110), Dec(1))        # cost 1101 -> avg (1001+1101)/20
    assert (pos.qty, pos.avg_cost, cash) == (20, Dec("105.1"), Dec(97_898))
    pos, cash = apply_fill(pos, cash, "sell", Dec(5), Dec(120), Dec(1))        # proceeds 599; realized 599 - 5*105.1
    assert (pos.qty, pos.avg_cost, pos.realized, cash) == (15, Dec("105.1"), Dec("73.5"), Dec(98_497))
    pos, cash = apply_fill(pos, cash, "sell", Dec(15), Dec(100), Dec(0))       # proceeds 1500 vs cost 1576.5 -> -76.5
    assert (pos.qty, pos.avg_cost, pos.realized, cash) == (0, 0, Dec("-3.0"), Dec(99_997))
    assert cash - Dec(100_000) == pos.realized     # flat position: cash change equals realized P&L exactly (no float drift)


def test_accounting_rejects_invalid_operations():
    pos = Position(Dec(5), Dec(10))
    with pytest.raises(AccountingError):
        apply_fill(pos, Dec(100), "sell", Dec(6), Dec(10), Dec(0))             # no shorting
    with pytest.raises(AccountingError):
        apply_fill(Position(), Dec(100), "buy", Dec(2), Dec(60), Dec(0))       # insufficient cash
    for args in ((Dec(0), Dec(1), Dec(0)), (Dec(1), Dec(0), Dec(0)), (Dec(1), Dec(1), Dec(-1))):
        with pytest.raises(AccountingError):
            apply_fill(Position(Dec(5), Dec(1)), Dec(100), "buy", *args)


# --- simulation --------------------------------------------------------------------------
def test_market_orders_use_ask_or_bid_plus_slippage_and_crypto_fee():
    qt = quote(100.05, bid=100.0, ask=100.10)
    b = sim.decide(order(side="buy"), qt, "crypto", P)
    assert b.price == Dec("100.12002") and b.fee == q(Dec(10) * Dec("100.12002") * Dec("0.001"), 8) and "ask" in b.note and not b.triggered
    s = sim.decide(order(side="sell"), qt, "crypto", P)
    assert s.price == Dec("99.98") and "bid" in s.note                              # 100.0 * (1 - 2bp)


def test_missing_bid_ask_uses_assumed_spread_and_says_so():
    d = sim.decide(order(side="buy"), quote(100.0), "equity", P)
    assert "assumed spread" in d.note and d.price == q(Dec("100") * Dec("1.0001") * Dec("1.0002"), 8)
    assert d.fee == 0                                                               # default equity commission is 0
    assert sim.decide(order(), quote(100.0), "equity", SimParams(equity_per_share_fee=0.005)).fee == Dec("0.05")


def test_limit_orders_marketable_passive_and_conservative():
    qt = quote(100.05, bid=100.0, ask=100.10)
    m = sim.decide(order(type="limit", limit_price=Dec("100.5")), qt, "equity", P)
    assert m.price == Dec("100.10") and "marketable" in m.note                     # price improvement: better of limit and book
    assert sim.decide(order(type="limit", limit_price=Dec(99)), quote(100.0, bid=99.99, ask=100.01), "equity", P) is None
    assert sim.decide(order(type="limit", limit_price=Dec(99)), quote(99.0, bid=98.99, ask=99.01), "equity", P) is None      # touched, not through
    through = sim.decide(order(type="limit", limit_price=Dec(99)), quote(98.99, bid=98.90, ask=99.20), "equity", P)       # ask above the limit: passive; last printed below it
    assert through.price == Dec(99) and "through" in through.note
    touch = SimParams(conservative_limit_fills=False)
    assert sim.decide(order(type="limit", limit_price=Dec(99)), quote(99.0, bid=98.99, ask=99.01), "equity", touch).price == Dec(99)
    sell = sim.decide(order(side="sell", type="limit", limit_price=Dec(101)), quote(101.5, bid=101.4, ask=101.6), "equity", P)
    assert sell.price == Dec("101.4")                                                                                      # marketable sell: better of limit 101 and bid 101.4


def test_stop_orders_trigger_and_fill_at_market_not_at_the_stop():
    o = order(side="sell", type="stop", stop_price=Dec(95))
    assert sim.decide(o, quote(96.0, bid=95.99, ask=96.01), "equity", P) is None
    d = sim.decide(o, quote(94.0, bid=93.9, ask=94.1), "equity", P)               # gapped through the stop
    assert d.triggered and d.price == q(Dec("93.9") * Dec("0.9998"), 8) and d.price < 95 and "gap risk" in d.note
    buy = sim.decide(order(side="buy", type="stop", stop_price=Dec(105)), quote(106.0, bid=105.9, ask=106.1), "equity", P)
    assert buy.triggered and buy.price > Dec("106.1")


def test_stop_limit_trigger_is_remembered_even_when_not_fillable():
    o = order(type="stop_limit", stop_price=Dec(105), limit_price=Dec(106))
    assert sim.decide(o, quote(104.0), "equity", P) is None
    gap = sim.decide(o, quote(107.0, bid=106.9, ask=107.0), "equity", P)           # gapped through the stop AND above the limit: triggered, not fillable
    assert gap.triggered and gap.qty == 0
    later = sim.decide({**o, "triggered": True}, quote(105.2, bid=105.1, ask=105.3), "equity", P)
    assert later.qty == 10 and later.price == Dec("105.3") and not later.triggered


def test_participation_cap_makes_partial_fills_and_whole_shares():
    d = sim.decide(order(qty_remaining=Dec(25)), quote(100.0, bid=99.99, ask=100.01, volume=1000), "equity", P)
    assert d.qty == 10 and "partial" in d.note                                    # 1% of 1000
    assert sim.decide(order(qty_remaining=Dec(25)), quote(100.0, bid=99.99, ask=100.01, volume=50), "equity", P) is None   # cap 0.5 shares -> floor 0
    assert sim.decide(order(qty_remaining=Dec(25)), quote(100.0, bid=99.99, ask=100.01, volume=1000), "equity", P, allow_fractional=True).qty == 10
    c = sim.decide(order(qty_remaining=Dec("2.5")), quote(70000.0, bid=69999, ask=70001, volume=100), "crypto", P)
    assert c.qty == 1 and "partial" in c.note                                     # 1% of 100 BTC
    assert sim.decide(order(qty_remaining=Dec("0.000001")), quote(70000.0, bid=69999, ask=70001), "crypto", P) is None   # below min lot


# --- pre-trade risk ----------------------------------------------------------------------
def ctx(**kw):
    base = dict(limits=RiskLimits(), sim=P, halted=False, asset_class="equity", tradable=True, symbol="AAA", quote=quote(100.0, bid=99.99, ask=100.01),
                session="REGULAR", equity=Dec(100_000), cash_available=Dec(100_000), sellable_qty=Dec(0), position_value=Dec(0),
                other_planned_risk=Dec(0), unquantified_positions=0, day_start_equity=Dec(100_000), duplicate_working=0)
    return RiskContext(**{**base, **kw})


def run(o=None, c=None, **oo):
    o = o or OrderIn(**{"instrument_id": "AAA", "side": "buy", "qty": 100, "type": "limit", "limit_price": 100, "planned_stop": 95, **oo})
    return check(o, c or ctx(), lambda qty, price: Dec(0))


def status(r, name):
    return next(c["status"] for c in r["checks"] if c["name"] == name)


def test_happy_path_approves_for_paper_review_only():
    r = run()
    assert r["verdict"] == "APPROVE_FOR_PAPER_REVIEW" and "not authorization for live trading" in r["disclaimer"]
    assert status(r, "environment") == "pass" and status(r, "confirmation") == "pass" and status(r, "event_risk") == "not_checked"
    assert r["estimate"]["notional"] == 10_000


def test_position_cap_boundary():
    assert status(run(), "position_cap") == "pass"                                  # exactly 10% of 100k
    r = run(qty=101)
    assert status(r, "position_cap") == "fail" and r["verdict"] == "REJECT"
    assert status(run(c=ctx(position_value=Dec(5_000)), qty=51), "position_cap") == "fail"      # existing exposure counts


def test_risk_per_trade_boundary_and_stop_validity():
    assert status(run(planned_stop=95), "risk_per_trade") == "pass"                 # 100*(100-95) = 500 = 0.5% exactly
    assert status(run(planned_stop=Dec("94.9")), "risk_per_trade") == "fail"        # 510 = 0.51%
    r = run(planned_stop=101)
    assert status(r, "risk_per_trade") == "fail" and "below the entry" in next(c["detail"] for c in r["checks"] if c["name"] == "risk_per_trade")


def test_aggregate_risk_boundary_and_coverage_warning():
    assert status(run(c=ctx(other_planned_risk=Dec(1_500))), "aggregate_risk") == "pass"          # 1500 + 500 = 2.0%
    assert status(run(c=ctx(other_planned_risk=Dec(1_600))), "aggregate_risk") == "fail"          # 2.1%
    r = run(c=ctx(unquantified_positions=2))
    assert status(r, "aggregate_risk_coverage") == "warn" and r["verdict"] == "APPROVE_FOR_PAPER_REVIEW"


def test_missing_stop_needs_more_data_unless_not_required():
    o = OrderIn(instrument_id="AAA", side="buy", qty=10, type="limit", limit_price=100)
    r = run(o)
    assert r["verdict"] == "NEEDS_MORE_DATA" and status(r, "risk_per_trade") == "needs_data"
    relaxed = ctx(limits=RiskLimits(require_stop=False))
    r2 = run(o, relaxed)
    assert r2["verdict"] == "APPROVE_FOR_PAPER_REVIEW" and status(r2, "risk_per_trade") == "not_checked"


def test_exits_are_not_blocked_by_exposure_stop_or_daily_loss_rules():
    blown = ctx(equity=Dec(90_000), day_start_equity=Dec(100_000), sellable_qty=Dec(50), position_value=Dec(5_000))
    o = OrderIn(instrument_id="AAA", side="sell", qty=50, type="limit", limit_price=100)
    r = run(o, blown)
    assert r["verdict"] == "APPROVE_FOR_PAPER_REVIEW" and status(r, "position_available") == "pass"
    assert "risk_per_trade" not in [c["name"] for c in r["checks"]] and "daily_loss" not in [c["name"] for c in r["checks"]]
    assert run(OrderIn(instrument_id="AAA", side="sell", qty=51, type="limit", limit_price=100), blown)["verdict"] == "REJECT"   # no shorting


def test_daily_loss_blocks_new_buys_warns_earlier():
    assert status(run(c=ctx(equity=Dec(97_500))), "daily_loss") == "warn"           # 2.5%
    r = run(c=ctx(equity=Dec(96_000)))                                              # 4%
    assert status(r, "daily_loss") == "fail" and r["verdict"] == "REJECT"
    assert status(run(c=ctx(day_start_equity=None)), "daily_loss") == "not_checked"


def test_buying_power_includes_fees_and_reservations():
    o = OrderIn(instrument_id="AAA", side="buy", qty=100, type="limit", limit_price=100, planned_stop=95)
    assert status(check(o, ctx(cash_available=Dec(10_000)), lambda qty, price: Dec(0)), "buying_power") == "pass"
    assert status(check(o, ctx(cash_available=Dec(10_000)), lambda qty, price: Dec("0.01")), "buying_power") == "fail"    # fee tips it over
    assert status(run(c=ctx(cash_available=Dec(9_999))), "buying_power") == "fail"


def test_market_session_rules():
    closed = ctx(session="CLOSED")
    assert status(run(c=closed), "market_session") == "warn"                       # limit orders queue
    m = run(OrderIn(instrument_id="AAA", side="buy", qty=10, type="market", planned_stop=90), closed)
    assert status(m, "market_session") == "fail" and m["verdict"] == "REJECT"       # a market order would gap at the open
    crypto = ctx(asset_class="crypto", session=None, quote=quote(70000.0, bid=69999, ask=70001))
    assert status(run(OrderIn(instrument_id="BTC", side="buy", qty="0.1", type="market", planned_stop=60000), crypto), "market_session") == "pass"


def test_data_freshness_gates():
    assert run(c=ctx(quote=quote(status=DataStatus.STALE)))["verdict"] == "NEEDS_MORE_DATA"
    assert run(c=ctx(quote=None))["verdict"] == "NEEDS_MORE_DATA"
    d = run(c=ctx(quote=quote(100.0, bid=99.99, ask=100.01, status=DataStatus.DELAYED)))
    assert status(d, "data_fresh") == "warn" and d["verdict"] == "APPROVE_FOR_PAPER_REVIEW"
    assert status(run(c=ctx(quote=quote(100.0, bid=99.99, ask=100.01, status=DataStatus.DEMO))), "data_fresh") == "warn"


def test_spread_kill_switch_blocklist_and_untradable():
    assert status(run(c=ctx(quote=quote(100.0, bid=99.0, ask=101.0))), "spread") == "fail"          # ~200bp
    assert status(run(c=ctx(quote=quote(100.0))), "spread") == "not_checked"                          # no bid/ask
    assert run(c=ctx(halted=True))["verdict"] == "REJECT"
    assert run(c=ctx(limits=RiskLimits(blocked_symbols=["aaa"])))["verdict"] == "REJECT"
    assert run(c=ctx(tradable=False))["verdict"] == "REJECT"


def test_quantity_rules_and_notional_cap_and_duplicates():
    assert status(run(qty=Dec("1.5")), "quantity") == "fail"                                          # fractional equity
    assert status(run(qty=Dec("1.5"), c=ctx(limits=RiskLimits(allow_fractional_equities=True))), "quantity") == "pass"
    crypto = ctx(asset_class="crypto", session=None, quote=quote(70000.0, bid=69999, ask=70001))
    assert status(run(OrderIn(instrument_id="BTC", side="buy", qty="0.000001", type="market", planned_stop=60000), crypto), "quantity") == "fail"
    assert status(run(c=ctx(limits=RiskLimits(max_order_notional=5_000))), "order_notional") == "fail"
    assert status(run(c=ctx(duplicate_working=1)), "duplicate") == "warn"


def test_entry_estimate_by_order_type():
    qt = quote(100.0, bid=99.9, ask=100.1)
    mk = OrderIn(instrument_id="X", side="buy", qty=1)
    assert entry_estimate(mk, qt, "equity", P) == Dec("100.1") * Dec("1.0002")
    assert entry_estimate(OrderIn(instrument_id="X", side="buy", qty=1, type="limit", limit_price=99), qt, "equity", P) == 99
    assert entry_estimate(OrderIn(instrument_id="X", side="buy", qty=1, type="stop", stop_price=110), qt, "equity", P) == Dec(110) * Dec("1.0002")
    assert entry_estimate(OrderIn(instrument_id="X", side="sell", qty=1), qt, "equity", P) == Dec("99.9") * Dec("0.9998")
