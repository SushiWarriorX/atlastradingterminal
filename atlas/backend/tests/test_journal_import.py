from datetime import datetime, timezone
from decimal import Decimal as Dec

import pytest

from atlas_api.journal import importers as imp
from atlas_api.journal.store import JournalError, JournalStore
from atlas_api.trading.engine import TradingEngine
from atlas_api.service import MarketService

GENERIC = """timestamp,symbol,side,quantity,price,fee,trade_id
2026-03-09T14:30:00Z,AAPL,buy,10,200.50,1.00,a1
2026-03-09T15:30:00Z,AAPL,sell,10,205.00,1.00,a2
"""
VARIATIONAL = """Trade ID,Created At,Side,Underlying,Price,Quantity,Trade Type,Status
t1,2026-03-01 10:00:00,Buy,BTC-PERP,"70,000.50",0.5,trade,filled
t2,2026-03-02 11:00:00,Sell,BTC-PERP,71000,0.5,trade,filled
t3,2026-03-03 12:00:00,Buy,ETH-PERP,3500,2,trade,pending
t4,2026-03-04 13:00:00,Sell,ETH/USDC,3400,1,liquidation,completed
t5,2026-03-05 14:00:00,Buy,SOL-PERP,150,10,rebalance,filled
"""
FLEX = """AssetClass,Symbol,DateTime,Buy/Sell,Quantity,TradePrice,IBCommission,IBExecID,CurrencyPrimary,Multiplier
STK,AAPL,20260309;093000,BUY,10,200.5,-1.0,exec-1,USD,1
STK,AAPL,20260309;153000,SELL,-10,205,-1.0,exec-2,USD,1
FUT,ES,20260310;100000,BUY,2,5000,-4.5,exec-3,USD,50
"""
FUNDING = """timestamp,underlying,type,amount,funding_rate
2026-03-01 18:00:00,BTC-PERP,Funding,-0.40,0.0001
2026-03-02 02:00:00,BTC-PERP,funding,0.10,-0.00005
2026-03-02 09:00:00,,Transfer,500,
2026-03-02 10:00:00,BTC-PERP,Realized PnL,500,
"""


def parse(text, preset="generic", kind="trades", **kw):
    return imp.parse(text, source="src", kind=kind, preset=preset, **kw)


# --- mapping suggestions -----------------------------------------------------------------------------
def test_generic_mapping_is_suggested_from_header_names_one_column_per_role():
    r = parse(GENERIC)
    assert r.mapping["ts"] == "timestamp" and r.mapping["symbol"] == "symbol" and r.mapping["qty"] == "quantity" and r.mapping["ext_id"] == "trade_id"
    assert len({v for v in r.mapping.values() if v}) == len([v for v in r.mapping.values() if v])       # no column serves two roles
    assert not r.errors and len(r.executions) == 2


def test_variational_style_headers_and_flex_preset_names():
    m = imp.suggest_mapping(["Trade ID", "Created At", "Side", "Underlying", "Price", "Quantity", "Trade Type", "Status"], imp.ROLES_TRADES, "variational")
    assert m["ext_id"] == "Trade ID" and m["ts"] == "Created At" and m["symbol"] == "Underlying" and m["kind"] == "Trade Type" and m["status"] == "Status" and m["qty"] == "Quantity"
    f = imp.suggest_mapping(["AssetClass", "Symbol", "DateTime", "Buy/Sell", "Quantity", "TradePrice", "IBCommission", "IBExecID"], imp.ROLES_TRADES, "ibkr_flex")
    assert f["side"] == "Buy/Sell" and f["price"] == "TradePrice" and f["fee"] == "IBCommission" and f["ext_id"] == "IBExecID" and f["asset_class"] == "AssetClass"
    assert imp.PRESETS["variational"]["verified"] is False and "could not be reached" in imp.PRESETS["variational"]["note"]


def test_explicit_mapping_overrides_the_suggestion():
    txt = "when,ticker,dir,n,px\n2026-03-09 10:00:00,AAPL,buy,5,100\n"
    r = parse(txt, mapping={"ts": "when", "symbol": "ticker", "side": "dir", "qty": "n", "price": "px"})
    assert not r.errors and r.executions[0].symbol == "AAPL" and r.executions[0].qty == 5


# --- parsing -----------------------------------------------------------------------------------------
def test_generic_rows_become_exact_decimal_executions_in_utc():
    e = parse(GENERIC).executions
    assert e[0].ts == datetime(2026, 3, 9, 14, 30, tzinfo=timezone.utc) and e[0].price == Dec("200.50") and e[0].fee == Dec("1.00") and e[0].ext_id == "a1"
    assert (e[0].side, e[1].side, e[0].asset_class, e[0].currency) == ("buy", "sell", "stock", "USD")


def test_naive_timestamps_use_the_timezone_option_and_warn_when_assumed_utc():
    txt = "timestamp,symbol,side,quantity,price\n2026-03-09 09:30:00,AAPL,buy,1,1\n"
    ny = parse(txt, options={"tz": "America/New_York"})
    assert ny.executions[0].ts == datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc) and not any("assumed UTC" in w for w in ny.warnings)    # 09:30 EDT
    utc = parse(txt)
    assert utc.executions[0].ts.hour == 9 and any("assumed UTC" in w for w in utc.warnings)
    est = parse("timestamp,symbol,side,quantity,price\n2026-01-09 09:30:00,AAPL,buy,1,1\n", options={"tz": "America/New_York"})
    assert est.executions[0].ts.hour == 14                                                                                                   # EST = UTC-5 in January


@pytest.mark.parametrize("raw,expect", [("1773066600", datetime(2026, 3, 9, 14, 30, tzinfo=timezone.utc)), ("1773066600000", datetime(2026, 3, 9, 14, 30, tzinfo=timezone.utc)),
                                        ("20260309;143000", datetime(2026, 3, 9, 14, 30, tzinfo=timezone.utc)), ("03/09/2026 14:30:00", datetime(2026, 3, 9, 14, 30, tzinfo=timezone.utc)),
                                        ("2026-03-09T09:30:00-05:00", datetime(2026, 3, 9, 14, 30, tzinfo=timezone.utc)), ("2026-03-09 14:30:00.250", datetime(2026, 3, 9, 14, 30, 0, 250000, tzinfo=timezone.utc))])
def test_timestamp_formats(raw, expect):
    assert imp.parse_ts(raw) == expect


def test_bad_timestamp_and_numbers_are_reported_per_line_not_dropped_silently():
    txt = "timestamp,symbol,side,quantity,price\n2026-03-09 10:00:00,AAPL,buy,1,100\nyesterday,AAPL,buy,1,100\n2026-03-09 11:00:00,AAPL,buy,1,abc\n2026-03-09 12:00:00,AAPL,hold,1,100\n"
    r = parse(txt)
    assert len(r.executions) == 1 and [e["line"] for e in r.errors] == [3, 4, 5]
    assert "unrecognised timestamp" in r.errors[0]["error"] and "not a number" in r.errors[1]["error"] and "unrecognised side" in r.errors[2]["error"]
    assert r.rows_total == 4


@pytest.mark.parametrize("raw,expect", [("1,234.50", Dec("1234.50")), ("$5", Dec(5)), ("(3.2)", Dec("-3.2")), ("−2", Dec(-2)), ("", None), ("n/a", None), (" 7 ", Dec(7))])
def test_number_parsing(raw, expect):
    assert imp.to_decimal(raw) == expect
    with pytest.raises(ValueError):
        imp.to_decimal("12abc")


def test_signed_quantity_exports_without_a_side_column_and_side_aliases():
    txt = "time,symbol,qty,price\n2026-03-09 10:00:00,AAPL,10,100\n2026-03-09 11:00:00,AAPL,-10,101\n"
    r = parse(txt)
    assert [(e.side, e.qty) for e in r.executions] == [("buy", 10), ("sell", 10)]
    for word, side in (("BOT", "buy"), ("SLD", "sell"), ("Long", "buy"), ("short", "sell"), ("B", "buy"), ("Sell to Close", "sell")):
        assert parse(f"timestamp,symbol,side,quantity,price\n2026-03-09 10:00:00,X,{word},1,1\n").executions[0].side == side


def test_status_filtering_and_zero_quantity_are_counted():
    r = parse(VARIATIONAL, preset="variational")
    assert len(r.executions) == 4 and r.skipped == {"status=pending": 1}
    z = parse("timestamp,symbol,side,quantity,price\n2026-03-09 10:00:00,X,buy,0,5\n")
    assert z.executions == [] and z.skipped == {"zero quantity": 1}


def test_variational_symbols_kinds_and_instrument_ids():
    r = parse(VARIATIONAL, preset="variational")
    by = {e.ext_id: e for e in r.executions}
    assert by["t1"].symbol == "BTC" and by["t1"].price == Dec("70000.50") and by["t1"].asset_class == "crypto" and by["t1"].instrument_id == "CRYPTO:VARIATIONAL:BTC-USD:PERP"
    assert by["t4"].symbol == "ETH" and by["t4"].kind == "liquidation" and by["t5"].kind == "trade"
    assert r.kinds == {"trade": 3, "liquidation": 1} and any("rebalance" in w for w in r.warnings)                      # unknown trade types are surfaced


def test_flex_style_export_signed_quantities_commissions_and_multipliers():
    r = parse(FLEX, preset="ibkr_flex", options={"tz": "America/New_York"})
    a, b, c = r.executions
    assert (a.ext_id, a.side, a.qty, a.fee, a.asset_class) == ("exec-1", "buy", 10, Dec("1.0"), "stock")
    assert b.side == "sell" and b.qty == 10 and a.ts == datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc)                  # side column wins; quantity made positive
    assert c.asset_class == "future" and c.multiplier == 50 and c.fee == Dec("4.5")


def test_required_columns_and_file_level_errors():
    r = parse("foo,bar\n1,2\n")
    assert r.executions == [] and "required column(s) not mapped" in r.errors[0]["error"]
    for bad in ("", "   \n", "timestamp,symbol\n"):
        with pytest.raises(ValueError):
            parse(bad)
    with pytest.raises(ValueError):
        parse("a,a\n1,2\n")


def test_delimiters_and_bom_are_handled():
    semi = "﻿timestamp;symbol;side;quantity;price\n2026-03-09 10:00:00;AAPL;buy;2,5;100\n".replace("2,5", "2")
    r = parse(semi)
    assert not r.errors and r.executions[0].qty == 2
    assert len(parse(GENERIC.replace(",", "\t")).executions) == 2


# --- ids and idempotency ------------------------------------------------------------------------------
def test_synthetic_ids_are_stable_and_identical_rows_stay_distinct():
    txt = "timestamp,symbol,side,quantity,price\n2026-03-09 10:00:00,X,buy,1,5\n2026-03-09 10:00:00,X,buy,1,5\n2026-03-09 10:00:01,X,buy,1,5\n"
    a, b = parse(txt), parse(txt)
    ids = [e.ext_id for e in a.executions]
    assert len(set(ids)) == 3 and ids == [e.ext_id for e in b.executions] and ids[0].endswith("#1") and ids[1].endswith("#2")


@pytest.fixture
def store(db):
    return JournalStore(db)


def test_reimporting_the_same_file_adds_nothing(store):
    r = parse(GENERIC)
    assert store.insert_executions(r.executions) == (2, 0)
    assert store.insert_executions(parse(GENERIC).executions) == (0, 2)
    assert len(store.load()[0]) == 2
    txt = "timestamp,symbol,side,quantity,price\n2026-03-09 10:00:00,X,buy,1,5\n2026-03-09 10:00:00,X,buy,1,5\n"
    assert store.insert_executions(parse(txt).executions) == (2, 0) and store.insert_executions(parse(txt).executions) == (0, 2)


# --- funding / flows -------------------------------------------------------------------------------------
def test_funding_file_kinds_signs_and_skips():
    r = parse(FUNDING, preset="variational", kind="flows")
    assert [(f.kind, f.symbol, f.amount) for f in r.flows] == [("funding", "BTC", Dec("-0.40")), ("funding", "BTC", Dec("0.10")), ("transfer", None, Dec(500))]
    assert sum(r.skipped.values()) == 1 and any("exchange-reported" in k for k in r.skipped) and any("POSITIVE amount" in w for w in r.warnings)
    inv = parse(FUNDING, preset="variational", kind="flows", options={"amount_sign": "invert"})
    assert inv.flows[0].amount == Dec("0.40") and not any("POSITIVE amount" in w for w in inv.warnings)


def test_end_to_end_import_build_trades_with_fees_funding_and_liquidation(store):
    trades_csv = parse(VARIATIONAL, preset="variational")
    flows_csv = parse(FUNDING, preset="variational", kind="flows")
    store.insert_executions(trades_csv.executions)
    store.insert_flows(flows_csv.flows)
    out = store.trades(source="src")
    by = {t["symbol"]: t for t in out["trades"]}
    btc = by["BTC"]
    assert btc["status"] == "closed" and btc["gross_pnl"] == "499.75" and btc["funding"] == "-0.3" and btc["net_pnl"] == Dec("499.45") and btc["side"] == "long"
    assert by["ETH"]["side"] == "short" and by["ETH"]["liquidated"] and by["ETH"]["status"] == "open"                 # the only fill is the liquidation sell
    assert by["SOL"]["status"] == "open"
    assert [c["kind"] for c in out["unattributed_cashflows"]] == ["transfer"]


# --- notes -----------------------------------------------------------------------------------------------
def make_trade(store):
    store.insert_executions(parse(GENERIC).executions)
    return store.trades()["trades"][0]


def test_notes_roundtrip_partial_update_and_r_multiple(store):
    t = make_trade(store)
    assert t["r_multiple"] is None and not t["has_notes"] and t["net_pnl"] == Dec("43.00")                              # (205-200.5)*10 - 2 fees
    n = store.upsert_note(t["key"], {"setup": "breakout", "thesis": "range break", "planned_stop": "198.50", "targets": ["210", "215.5"], "mistakes": ["late entry", "late entry"], "tags": ["B", "a"]})
    assert n["setup"] == "breakout" and n["planned_stop"] == "198.5" and n["targets"] == ["210", "215.5"] and n["mistakes"] == ["late entry"] and n["tags"] == ["B", "a"]
    store.upsert_note(t["key"], {"lessons": "wait for the close"})                                                       # partial update keeps the rest
    n = store.get_note(t["key"])
    assert n["lessons"] == "wait for the close" and n["setup"] == "breakout" and n["thesis"] == "range break"
    t2 = store.trades()["trades"][0]
    # risk = 10 * |200.5 - 198.5| = 20 ; net 43 -> 2.15R
    assert t2["r_multiple"] == pytest.approx(2.15) and t2["setup"] == "breakout" and t2["has_notes"] and t2["tags"] == ["B", "a", "mistake: late entry"]
    assert store.trades(symbol="aapl")["trades"] and store.trades(status="open")["trades"] == []


@pytest.mark.parametrize("bad", [{"unknown": 1}, {"thesis": "x" * 5001}, {"thesis": 5}, {"planned_stop": "abc"}, {"planned_stop": "-1"}, {"targets": ["x"]}, {"tags": [""]}, {"tags": "a"},
                                 {"tags": ["x" * 61]}, {"screenshot": "http://evil/x.png"}, {"screenshot": "data:text/html;base64,AAAA"}, {"screenshot": "data:image/png;base64," + "A" * 700_001}])
def test_note_validation(store, bad):
    t = make_trade(store)
    with pytest.raises(JournalError) as e:
        store.upsert_note(t["key"], bad)
    assert e.value.code == "INVALID_NOTE" and not store.get_note(t["key"])                                               # a rejected note writes nothing


def test_screenshot_accepts_small_images_and_clears(store):
    t = make_trade(store)
    n = store.upsert_note(t["key"], {"screenshot": "data:image/png;base64,iVBORw0KGgo="})
    assert n["screenshot"].startswith("data:image/png") and store.trades()["trades"][0]["has_screenshot"]
    assert store.upsert_note(t["key"], {"screenshot": None})["screenshot"] is None


def test_delete_source_removes_its_data_and_notes_only(store):
    t = make_trade(store)
    store.upsert_note(t["key"], {"setup": "x"})
    store.insert_executions(imp.parse(GENERIC.replace("AAPL", "MSFT"), source="other", preset="generic").executions)
    out = store.delete_source("src")
    assert out["executions_deleted"] == 2 and store.get_note(t["key"]) is None
    assert [s["source"] for s in store.sources()] == ["other"] and len(store.trades()["trades"]) == 1


def test_sources_and_batches_listing(store):
    r = parse(GENERIC)
    ins, dup = store.insert_executions(r.executions)
    store.batch("src", "trades", "f.csv", r, ins, dup)
    s = store.sources()[0]
    assert s["source"] == "src" and s["executions"] == 2 and s["symbols"] == 1
    assert store.batches()[0]["filename"] == "f.csv" and store.batches()[0]["inserted"] == 2
    store.save_mapping("src", {"ts": "when"})
    assert store.get_mapping("src") == {"ts": "when"} and store.get_mapping("nope") is None


# --- paper engine -> journal ------------------------------------------------------------------------------
def test_paper_fills_sync_idempotently_and_inherit_the_planned_stop(db):
    eng = TradingEngine(db, MarketService({}))
    oid = db.x("INSERT INTO orders(portfolio_id,client_key,instrument_id,symbol,side,type,tif,qty,planned_stop,est_price,state,created_at,updated_at) VALUES(1,'k1','CRYPTO:COINBASE:BTC-USD:SPOT','BTC-USD','buy','market','GTC','0.1','68000','70000','filled','2026-03-09T14:00:00+00:00','2026-03-09T14:00:00+00:00')")
    o2 = db.x("INSERT INTO orders(portfolio_id,client_key,instrument_id,symbol,side,type,tif,qty,est_price,state,created_at,updated_at) VALUES(1,'k2','CRYPTO:COINBASE:BTC-USD:SPOT','BTC-USD','sell','market','GTC','0.1','71000','filled','2026-03-09T16:00:00+00:00','2026-03-09T16:00:00+00:00')")
    db.x("INSERT INTO fills(order_id,portfolio_id,instrument_id,symbol,side,qty,price,fee,ts) VALUES(?,?,?,?,?,?,?,?,?)", (oid, 1, "CRYPTO:COINBASE:BTC-USD:SPOT", "BTC-USD", "buy", "0.1", "70000", "7", "2026-03-09T14:00:00+00:00"))
    db.x("INSERT INTO fills(order_id,portfolio_id,instrument_id,symbol,side,qty,price,fee,ts) VALUES(?,?,?,?,?,?,?,?,?)", (o2, 1, "CRYPTO:COINBASE:BTC-USD:SPOT", "BTC-USD", "sell", "0.1", "71000", "7.1", "2026-03-09T16:00:00+00:00"))
    j = JournalStore(db)
    assert j.sync_paper() == {"paper_executions_added": 2} and j.sync_paper() == {"paper_executions_added": 0}
    (t,) = j.trades()["trades"]
    assert t["source"] == "paper:1" and t["asset_class"] == "crypto" and t["net_pnl"] == Dec("100") - Dec("14.1") and t["planned_stop"] == "68000"
    assert t["r_multiple"] == pytest.approx(85.9 / (0.1 * 2000))                                                          # R from the ORDER's planned stop, no manual entry needed
