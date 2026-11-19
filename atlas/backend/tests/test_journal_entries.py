"""Simple journal entries: notes by default, exact P&L only when the data is there, edit/delete, filters, and the unified log with imported trades."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.journal import entries as E


@pytest.fixture()
def c(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "j.db"), demo=True, alert_loop=False)) as client:
        yield client


def post(c, **kw):
    r = c.post("/api/journal/entries", json=kw)
    return r.status_code, r.json()


def test_a_note_is_a_valid_entry_and_has_no_pnl(c):
    code, r = post(c, symbol="btc", note="Watching the weekly close")
    d = r["data"]
    assert code == 200 and d["symbol"] == "BTC" and d["status"] == "note" and d["net_pnl"] is None and d["origin"] == "manual" and d["editable"] is True
    assert d["pnl_missing"] == ["size", "entry price", "exit price"] and d["direction"] == "long" and d["entry_at"]


def test_realised_pnl_is_exact_for_long_and_short_with_fees_and_return(c):
    _, r = post(c, symbol="AAPL", direction="long", size="10", entry_price="100.10", exit_price="110.30", fees="1.50", entry_at="2026-10-01", exit_at="2026-10-05")
    d = r["data"]
    assert d["status"] == "closed" and d["gross_pnl"] == "102" and d["net_pnl"] == "100.5" and d["net_pnl_num"] == 100.5
    assert d["return_pct"] == pytest.approx(100.5 / 1001.0 * 100) and d["holding_seconds"] == 4 * 86400
    _, r = post(c, symbol="BTC-USD", direction="short", size="0.5", entry_price="70000", exit_price="68000", planned_stop="71000")
    d = r["data"]
    assert d["net_pnl"] == "1000" and d["r_multiple"] == pytest.approx(1000 / (0.5 * 1000))                                 # short: entry - exit, risk = |entry - stop| x size
    _, r = post(c, symbol="ETH", direction="long", size="2", entry_price="3000", exit_price="2900")
    assert r["data"]["net_pnl"] == "-200" and r["data"]["return_pct"] == pytest.approx(-200 / 6000 * 100)


def test_an_open_trade_has_no_pnl_and_says_so(c):
    _, r = post(c, symbol="NVDA", size="5", entry_price="400")
    d = r["data"]
    assert d["status"] == "open" and d["net_pnl"] is None and d["pnl_missing"] == ["exit price"]


def test_validation_is_specific(c):
    assert post(c)[0] == 422                                                                                                  # a symbol is required
    for bad in ({"symbol": "BTC", "size": "-1"}, {"symbol": "BTC", "size": "abc"}, {"symbol": "BTC", "entry_price": "0"}, {"symbol": "BTC", "fees": "-2"},
                {"symbol": "BTC", "direction": "up"}, {"symbol": "BTC", "asset_class": "bond"}, {"symbol": "bad symbol!"}, {"symbol": "BTC", "entry_at": "yesterday"},
                {"symbol": "BTC", "entry_at": "2026-10-05", "exit_at": "2026-10-01"}, {"symbol": "BTC", "screenshot": "data:text/html;base64,AAAA"},
                {"symbol": "BTC", "note": "x" * 5001}, {"symbol": "BTC", "unknown_field": 1}):
        assert post(c, **bad)[0] == 422, bad


def test_edit_changes_only_what_was_sent_and_recalculates(c):
    _, r = post(c, symbol="AAPL", size="10", entry_price="100", note="first")
    eid = r["data"]["id"].split(":")[1]
    r = c.put(f"/api/journal/entries/{eid}", json={"exit_price": "120"}).json()["data"]
    assert r["status"] == "closed" and r["net_pnl"] == "200" and r["note"] == "first"
    r = c.put(f"/api/journal/entries/{eid}", json={"exit_price": None, "note": None}).json()["data"]                           # null clears an optional field
    assert r["status"] == "open" and r["net_pnl"] is None and r["note"] is None
    assert c.put(f"/api/journal/entries/{eid}", json={"entry_at": None}).status_code == 422 and c.put(f"/api/journal/entries/{eid}", json={"symbol": None}).status_code == 422
    assert c.put("/api/journal/entries/9999", json={"note": "x"}).status_code == 404


def test_delete_and_get(c):
    _, r = post(c, symbol="SPY", note="gone soon")
    eid = r["data"]["id"].split(":")[1]
    assert c.get(f"/api/journal/entries/{eid}").json()["data"]["note"] == "gone soon"
    assert c.delete(f"/api/journal/entries/{eid}").json()["data"]["deleted"] is True
    assert c.get(f"/api/journal/entries/{eid}").status_code == 404 and c.delete(f"/api/journal/entries/{eid}").status_code == 404


def test_screenshot_is_kept_but_not_sent_in_the_list(c):
    shot = "data:image/png;base64,iVBORw0KGgo="
    _, r = post(c, symbol="BTC", screenshot=shot)
    eid = r["data"]["id"].split(":")[1]
    assert r["data"]["has_screenshot"] is True and c.get(f"/api/journal/entries/{eid}").json()["data"]["screenshot"] == shot
    item = c.get("/api/journal/log").json()["data"]["items"][0]
    assert item["has_screenshot"] is True and "screenshot" not in item


def test_log_filters_search_and_statistics(c):
    post(c, symbol="AAPL", size="10", entry_price="100", exit_price="110", entry_at="2026-09-01", exit_at="2026-09-03", thesis="Services growth")
    post(c, symbol="AAPL", direction="short", size="10", entry_price="100", exit_price="105", entry_at="2026-09-10", exit_at="2026-09-11")
    post(c, symbol="BTC", note="just a note", entry_at="2026-09-20")
    post(c, symbol="MSFT", size="1", entry_price="300", entry_at="2026-10-02")
    log = lambda **p: c.get("/api/journal/log", params=p).json()["data"]
    d = log()
    assert d["total"] == 4 and [i["symbol"] for i in d["items"]] == ["MSFT", "BTC", "AAPL", "AAPL"]                           # newest first
    assert d["stats"]["n"] == 2 and d["stats"]["wins"] == 1 and d["stats"]["losses"] == 1
    assert d["stats"]["net_pnl"] == pytest.approx(100 - 50)                                                                   # +100 long win, -50 short loss
    assert log(status="open")["total"] == 1 and log(status="note")["total"] == 1 and log(status="closed")["total"] == 2
    assert log(symbol="aapl")["total"] == 2 and log(direction="short")["total"] == 1 and log(q="services")["total"] == 1 and log(origin="imported")["total"] == 0
    assert log(since="2026-09-15")["total"] == 2 and log(until="2026-09-05")["total"] == 1
    assert c.get("/api/journal/log", params={"status": "weird"}).status_code == 422


def test_imported_trades_appear_in_the_same_list_read_only(c):
    csv = "Date,Symbol,Side,Qty,Price,Fee\n2026-09-01T10:00:00Z,AAPL,buy,10,100,0\n2026-09-02T10:00:00Z,AAPL,sell,10,110,0\n"
    pre = c.get("/api/journal/presets").json()["data"]
    assert pre is not None
    post(c, symbol="BTC", note="mine")
    r = c.post("/api/journal/executions", json={"symbol": "AAPL", "side": "buy", "qty": "10", "price": "100", "ts": "2026-09-01T10:00:00Z", "asset_class": "stock"})
    r2 = c.post("/api/journal/executions", json={"symbol": "AAPL", "side": "sell", "qty": "10", "price": "110", "ts": "2026-09-02T10:00:00Z", "asset_class": "stock"})
    assert r.status_code == 200 and r2.status_code == 200
    d = c.get("/api/journal/log").json()["data"]
    imp = [i for i in d["items"] if i["origin"] == "imported"]
    assert len(imp) == 1 and imp[0]["editable"] is False and imp[0]["status"] == "closed" and imp[0]["net_pnl_num"] == pytest.approx(100) and imp[0]["id"].startswith("t:")
    assert d["stats"]["n"] == 1 and c.get("/api/journal/log", params={"origin": "manual"}).json()["data"]["total"] == 1


def test_calc_is_pure_decimal_arithmetic():
    row = {"direction": "long", "size": "3", "entry_price": "0.1", "exit_price": "0.3", "fees": "0", "planned_stop": None, "entry_at": None, "exit_at": None}
    assert E.calc(row)["gross_pnl"] == "0.6" and Decimal(E.calc(row)["net_pnl"]) == Decimal("0.6")                            # no 0.6000000000000001
