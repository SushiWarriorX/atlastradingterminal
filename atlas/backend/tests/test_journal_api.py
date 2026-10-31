import csv
import io
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dec

import pytest
from fastapi.testclient import TestClient

from atlas_api.ai.tools import Registry, ToolError
from atlas_api.app import create_app
from atlas_api.journal.store import JournalStore
from atlas_api.service import MarketService
from test_ibkr import FakeIB, broker as make_broker
from test_journal_import import FLEX, FUNDING, GENERIC, VARIATIONAL


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "j.db"), demo=True, alert_loop=False)) as c:
        yield c


def imp(client, text, source="s1", preview=False, **kw):
    path = "/api/journal/import/preview" if preview else "/api/journal/import"
    body = {"source": source, "text": text, "kind": "trades", **kw}
    if not preview:
        body.setdefault("confirm", True)
    return client.post(path, json=body)


def many_trades_csv(n=40, win_every=2):
    """n closed round trips, 1 unit each: even index wins +10, odd loses -5. Entries 09:30 UTC on consecutive days."""
    rows = ["timestamp,symbol,side,quantity,price,fee,trade_id"]
    t = datetime(2026, 1, 5, 9, 30, tzinfo=timezone.utc)
    for i in range(n):
        win = i % win_every == 0
        rows.append(f"{t.isoformat()},BTC,buy,1,100,0,b{i}")
        rows.append(f"{(t + timedelta(hours=2)).isoformat()},BTC,sell,1,{110 if win else 95},0,s{i}")
        t += timedelta(days=1)
    return "\n".join(rows)


# --- import flow ----------------------------------------------------------------------------------------
def test_preview_writes_nothing_and_explains_what_it_understood(client):
    r = imp(client, VARIATIONAL, "variational", preview=True, preset="variational", kind="trades").json()["data"]
    assert r["mapping"]["symbol"] == "Underlying" and r["parsed"] == 4 and r["skipped"] == {"status=pending": 1} and r["will_insert"] == 4 and r["already_imported"] == 0
    assert r["preset"]["verified"] is False and "could not be reached" in r["preset"]["note"] and r["time_range"][0].startswith("2026-03-01")
    assert r["sample"][0]["symbol"] == "BTC" and r["kinds"] == {"trade": 3, "liquidation": 1} and any("assumed UTC" in w for w in r["warnings"])
    assert client.get("/api/journal/sources").json()["data"]["sources"] == []                                          # a preview never touches the database


def test_import_requires_explicit_confirmation_then_is_idempotent(client):
    assert imp(client, GENERIC, confirm=False).json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    first = imp(client, GENERIC, filename="a.csv", preset="generic").json()["data"]
    assert (first["inserted"], first["duplicates"]) == (2, 0)
    again = imp(client, GENERIC, filename="a.csv", preset="generic").json()["data"]
    assert (again["inserted"], again["duplicates"]) == (0, 2)
    prev = imp(client, GENERIC, preview=True).json()["data"]
    assert prev["already_imported"] == 2 and prev["will_insert"] == 0
    src = client.get("/api/journal/sources").json()["data"]
    assert src["sources"][0]["executions"] == 2 and [b["inserted"] for b in src["batches"]] == [0, 2] and src["batches"][1]["filename"] == "a.csv"


def test_mapping_edits_apply_and_bad_files_are_rejected_clearly(client):
    txt = "when,ticker,dir,n,px\n2026-03-09 10:00:00,AAPL,buy,5,100\n2026-03-09 11:00:00,AAPL,sell,5,110\n"
    bad_map = imp(client, txt, preview=True).json()["data"]
    assert bad_map["parsed"] == 0 and "required column(s) not mapped" in bad_map["errors"][0]["error"]
    ok_map = imp(client, txt, preview=True, mapping={"ts": "when", "symbol": "ticker", "side": "dir", "qty": "n", "price": "px"}).json()["data"]
    assert ok_map["parsed"] == 2 and ok_map["errors_total"] == 0
    assert imp(client, txt).json()["error"]["code"] == "IMPORT_FAILED"                                                  # nothing parseable: no empty batch is stored
    assert imp(client, "", preview=True).status_code == 422
    assert imp(client, "a,a\n1,2\n", preview=True).json()["error"]["code"] == "INVALID_FILE"
    assert imp(client, GENERIC, preview=True, preset="nope").status_code == 422
    assert imp(client, GENERIC, preview=True, kind="orders").status_code == 422
    assert imp(client, GENERIC, source="bad/source!").status_code == 422


def test_timezone_option_changes_the_parsed_times_visibly(client):
    txt = "timestamp,symbol,side,quantity,price\n2026-03-09 09:30:00,AAPL,buy,1,1\n"
    utc = imp(client, txt, preview=True).json()["data"]
    ny = imp(client, txt, preview=True, options={"tz": "America/New_York"}).json()["data"]
    assert utc["sample"][0]["ts"].startswith("2026-03-09T09:30") and ny["sample"][0]["ts"].startswith("2026-03-09T13:30")
    assert any("assumed UTC" in w for w in utc["warnings"]) and not any("assumed UTC" in w for w in ny["warnings"])


def test_funding_import_attaches_to_the_open_trade(client):
    imp(client, VARIATIONAL, "var", preset="variational")
    r = client.post("/api/journal/import", json={"source": "var", "kind": "flows", "text": FUNDING, "preset": "variational", "confirm": True}).json()["data"]
    assert r["inserted"] == 3 and any("POSITIVE amount" in w for w in r["warnings"])
    t = next(t for t in client.get("/api/journal/trades", params={"source": "var"}).json()["data"]["trades"] if t["symbol"] == "BTC")
    assert t["funding"] == "-0.3" and t["status"] == "closed"


def test_flex_import_builds_a_stock_trade_and_a_future_with_a_multiplier(client):
    r = imp(client, FLEX, "ibkr:flex", preset="ibkr_flex", options={"tz": "America/New_York"}).json()["data"]
    assert r["inserted"] == 3
    trades = {t["symbol"]: t for t in client.get("/api/journal/trades", params={"source": "ibkr:flex"}).json()["data"]["trades"]}
    assert Dec(trades["AAPL"]["net_pnl"]) == Dec("43")                                                                  # (205 - 200.5) * 10 - 2 commissions
    assert trades["ES"]["status"] == "open" and trades["ES"]["asset_class"] == "future"


def test_manual_execution_validation_and_trade_building(client):
    post = lambda **kw: client.post("/api/journal/executions", json={"symbol": "eth", "side": "buy", "qty": "2", "price": "3000", "ts": "2026-03-01T10:00:00Z", **kw})
    assert post().json()["data"] == {"inserted": 1}
    assert client.post("/api/journal/executions", json={"symbol": "ETH", "side": "sell", "qty": "2", "price": "3100", "fee": "1", "ts": "2026-03-02T10:00:00Z"}).json()["ok"]
    (t,) = client.get("/api/journal/trades").json()["data"]["trades"]
    assert t["symbol"] == "ETH" and t["source"] == "manual" and Dec(t["net_pnl"]) == Dec("199")
    for bad in ({"side": "hold"}, {"qty": "0"}, {"price": "-1"}, {"fee": "-1"}, {"ts": "not a time"}, {"qty": "abc"}):
        assert post(**bad).status_code in (409, 422) and not post(**bad).json()["ok"], bad


def test_delete_source_needs_confirmation(client):
    imp(client, GENERIC)
    assert client.delete("/api/journal/source", params={"source": "s1"}).json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert client.delete("/api/journal/source", params={"source": "s1", "confirm": True}).json()["data"]["executions_deleted"] == 2
    assert client.get("/api/journal/trades").json()["data"]["total"] == 0


# --- trades, notes ---------------------------------------------------------------------------------------
def test_trade_detail_notes_and_validation(client):
    imp(client, GENERIC)
    (t,) = client.get("/api/journal/trades").json()["data"]["trades"]
    d = client.get("/api/journal/trade", params={"key": t["key"]}).json()["data"]
    assert [e["ext_id"] for e in d["executions"]] == ["a1", "a2"] and d["note"] is None and d["trade"]["status"] == "closed"
    n = client.put("/api/journal/notes", params={"key": t["key"]}, json={"setup": "breakout", "thesis": "range break", "planned_stop": "198.5", "tags": ["a"], "mistakes": ["late"]})
    assert n.json()["data"]["setup"] == "breakout"
    d = client.get("/api/journal/trade", params={"key": t["key"]}).json()["data"]
    assert d["trade"]["setup"] == "breakout" and d["trade"]["r_multiple"] == pytest.approx(2.15)                          # net 43 / (10 shares * |200.5 - 198.5|)
    assert d["trade"]["tags"] == ["a", "mistake: late"]
    bad = client.put("/api/journal/notes", params={"key": t["key"]}, json={"unknown": 1})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_NOTE"
    assert client.put("/api/journal/notes", params={"key": "nope|X|y"}, json={"setup": "x"}).status_code == 404
    assert client.get("/api/journal/trade", params={"key": "nope"}).status_code == 404
    assert client.put("/api/journal/notes", params={"key": t["key"]}, json={"screenshot": "http://x/y.png"}).status_code == 422


def test_notes_and_imports_persist_across_restart(tmp_path):
    path = str(tmp_path / "p.db")
    mk = lambda: TestClient(create_app(db_path=path, demo=True, alert_loop=False))
    with mk() as c:
        imp(c, GENERIC)
        key = c.get("/api/journal/trades").json()["data"]["trades"][0]["key"]
        c.put("/api/journal/notes", params={"key": key}, json={"lessons": "wait for the close"})
    with mk() as c2:
        t = c2.get("/api/journal/trades").json()["data"]["trades"][0]
        assert t["key"] == key and t["has_notes"] and c2.get("/api/journal/trade", params={"key": key}).json()["data"]["note"]["lessons"] == "wait for the close"
        assert imp(c2, GENERIC).json()["data"]["inserted"] == 0                                                        # idempotency survives a restart


# --- stats -----------------------------------------------------------------------------------------------
def test_stats_over_many_trades_are_reliable_and_hand_checkable(client):
    imp(client, many_trades_csv(40))
    d = client.get("/api/journal/stats").json()["data"]
    s = d["summary"]
    assert s["n"] == 40 and s["reliable"] is True and s["wins"] == 20 and s["losses"] == 20 and s["win_rate"] == 0.5
    assert s["net_pnl"] == 100 and s["expectancy"] == 2.5 and s["profit_factor"] == 2.0 and s["avg_win"] == 10 and s["avg_loss"] == -5 and s["payoff_ratio"] == 2.0
    assert s["expectancy_ci95"] is not None and s["note"] is None and s["max_loss_streak"] == 1
    assert [r["key"] for r in d["groups"]["hour_et"]] == ["04:00"]                                                       # 09:30 UTC in Jan-Feb = 04:30 EST
    assert d["groups"]["holding"][0]["key"] == "1h-1d" and d["groups"]["side"][0]["key"] == "long"
    assert any("Past performance" in c for c in d["caveats"]) and len(d["equity_curve"]) == 40 and d["equity_curve"][-1]["cum"] == 100


def test_stats_with_a_few_trades_refuse_to_look_conclusive(client):
    imp(client, many_trades_csv(5))
    s = client.get("/api/journal/stats").json()["data"]["summary"]
    assert s["n"] == 5 and s["reliable"] is False and "anecdotal" in s["note"] and s["expectancy_ci95"] is None


def test_stats_groups_use_notes_and_filters_and_open_trades_are_excluded(client):
    imp(client, many_trades_csv(34))
    trades = client.get("/api/journal/trades").json()["data"]["trades"]
    for i, t in enumerate(sorted(trades, key=lambda x: x["opened_at"])):
        client.put("/api/journal/notes", params={"key": t["key"]}, json={"setup": "breakout" if i < 31 else "rare", "planned_stop": "90", "mistakes": ["fomo"] if i % 10 == 0 else []})
    open_csv = "timestamp,symbol,side,quantity,price,fee,trade_id\n2026-03-20T10:00:00Z,BTC,buy,1,100,0,open1\n"
    imp(client, open_csv, "other")
    d = client.get("/api/journal/stats").json()["data"]
    assert d["summary"]["n"] == 34                                                                                      # the open trade is not counted
    rows = {r["key"]: r for r in d["groups"]["setup"]}
    assert rows["breakout"]["reliable"] is True and rows["rare"]["reliable"] is False and list(rows)[0] == "breakout"
    assert d["summary"]["r"]["n"] == 34 and d["summary"]["r"]["avg_r"] is not None                                      # R from the planned stops entered in the journal
    tags = {r["key"]: r["n"] for r in d["groups"]["tag"]}
    assert tags["mistake: fomo"] == 4 and tags["(untagged)"] == 30
    assert client.get("/api/journal/stats", params={"symbol": "ETH"}).json()["data"]["summary"]["n"] == 0
    assert client.get("/api/journal/stats", params={"source": "other"}).json()["data"]["summary"]["n"] == 0
    assert client.get("/api/journal/stats", params={"since": "2026-02-01"}).json()["data"]["summary"]["n"] < 34
    assert client.get("/api/journal/stats", params={"groups": "setup,tag"}).json()["data"]["groups"].keys() == {"setup", "tag"}
    assert client.get("/api/journal/stats", params={"groups": "nonsense"}).status_code == 422
    assert client.get("/api/journal/stats", params={"since": "garbage"}).status_code == 422


def test_export_csv(client):
    imp(client, GENERIC)
    r = client.get("/api/journal/export.csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    assert rows[0][:5] == ["key", "source", "symbol", "side", "status"] and rows[1][2] == "AAPL" and rows[1][4] == "closed" and Dec(rows[1][13]) == Dec("43.00")


def test_paper_fills_flow_into_the_journal_automatically(client):
    body = {"instrument_id": "BTC-USD", "side": "buy", "qty": "0.05", "type": "market", "planned_stop": "65000"}
    pv = client.post("/api/orders/preview", json=body).json()["data"]
    assert pv["verdict"] == "APPROVE_FOR_PAPER_REVIEW"
    client.post("/api/orders/paper", json={"order": body, "preview_id": pv["preview_id"], "client_key": "journal-key-1"})
    body2 = {**body, "side": "sell"}
    body2.pop("planned_stop")
    pv2 = client.post("/api/orders/preview", json=body2).json()["data"]
    client.post("/api/orders/paper", json={"order": body2, "preview_id": pv2["preview_id"], "client_key": "journal-key-2"})
    t = client.get("/api/journal/trades").json()["data"]["trades"][0]
    assert t["source"] == "paper:1" and t["symbol"] == "BTC-USD" and t["status"] == "closed" and t["planned_stop"] == "65000" and t["r_multiple"] is not None
    assert client.post("/api/journal/sync").json()["data"]["paper_executions_added"] == 0 and client.post("/api/journal/sync").json()["data"]["ibkr"] == "not connected: nothing synced"


# --- AI journal tool ----------------------------------------------------------------------------------------
async def test_ai_journal_tool_is_read_only_and_carries_reliability(db):
    from atlas_api.journal import importers as jimp

    j = JournalStore(db)
    reg = Registry(MarketService({}), j)
    assert "get_journal_stats" in {s["name"] for s in reg.specs("desk")} and "get_journal_stats" not in {s["name"] for s in reg.specs("technical")}
    assert not any(w in n for n in reg.tools for w in ("order", "trade_", "write", "delete", "import"))
    empty = await reg.call("desk", "get_journal_stats", {})
    assert empty["closed_trades"] == 0 and empty["summary"]["n"] == 0
    j.insert_executions(jimp.parse(many_trades_csv(34), "s1", preset="generic").executions)
    out = await reg.call("desk", "get_journal_stats", {})
    assert out["source_id"] == "journal:stats" and out["summary"]["reliable"] and out["groups"]["setup"][0]["reliable"] is True and "Past performance" in " ".join(out["caveats"])
    with pytest.raises(ToolError):
        await reg.call("technical", "get_journal_stats", {})
    assert "never draw conclusions" in next(t for t in reg.specs("desk") if t["name"] == "get_journal_stats")["description"].lower()


# --- IBKR routes ----------------------------------------------------------------------------------------------
def ib_client(tmp_path, mode="paper_trading", port=7497, accounts=("DU1234567",), **kw):
    b, ib = make_broker(mode, port, accounts=accounts, **kw)
    c = TestClient(create_app(db_path=str(tmp_path / "i.db"), demo=True, alert_loop=False, broker=b))
    return c, b, ib


def test_ibkr_not_configured_is_explicit(client):
    assert client.get("/api/ibkr/status").json()["data"]["configured"] is False
    for path in ("/api/ibkr/connect", "/api/ibkr/sync"):
        r = client.post(path)
        assert r.status_code == 503 and r.json()["error"]["code"] == "IBKR_NOT_CONFIGURED" and "IBKR_MODE" in r.json()["error"]["message"]
    assert client.post("/api/ibkr/portfolio", json={"name": "x"}).status_code == 503
    assert client.get("/api/market/status").json()["data"]["ibkr"] == {"configured": False}


def test_ibkr_connect_link_sync_and_trade_through_the_api(tmp_path):
    c, b, ib = ib_client(tmp_path)
    with c:
        assert c.get("/api/ibkr/status").json()["data"]["connected"] is False
        st = c.post("/api/ibkr/connect").json()["data"]
        assert st["connected"] and st["can_trade"] and st["account"] == "DU…567" and "1234567" not in json.dumps(st)
        assert c.get("/api/market/status").json()["data"]["ibkr"]["can_trade"] is True
        pf = c.post("/api/ibkr/portfolio", json={"name": "IBKR paper"}).json()["data"]
        assert pf["venue"] == "ibkr" and pf["kind"] == "paper" and pf["cash"] == "50000"
        v = c.get("/api/portfolio", params={"pid": pf["id"]}).json()["data"]
        assert v["positions"][0]["symbol"] == "AAPL" and v["positions"][0]["qty"] == "10"
        body = {"instrument_id": "AAPL", "side": "buy", "qty": "5", "type": "limit", "limit_price": "100", "planned_stop": "95", "portfolio_id": pf["id"]}
        pv = c.post("/api/orders/preview", json=body).json()["data"]
        assert pv["verdict"] == "APPROVE_FOR_PAPER_REVIEW"
        o = c.post("/api/orders/paper", json={"order": body, "preview_id": pv["preview_id"], "client_key": "ibkr-api-key-1"}).json()["data"]["order"]
        assert o["venue"] == "ibkr" and o["state"] == "working" and len(ib.placed) == 1
        ib.cash = "47000"
        out = c.post("/api/ibkr/sync").json()["data"]
        assert out["portfolios"][0]["cash"] == "47000" and out["journal"]["executions_seen"] == 0
        assert c.post(f"/api/orders/{o['id']}/cancel").json()["data"]["state"] == "cancelled"


def test_ibkr_refusals_are_http_errors_with_codes(tmp_path):
    c, b, ib = ib_client(tmp_path, accounts=("U7654321",))                              # paper-trading mode pointed at a LIVE account
    with c:
        r = c.post("/api/ibkr/connect")
        assert r.status_code == 403 and r.json()["error"]["code"] == "LIVE_ACCOUNT_REFUSED" and ib.disconnected
        assert c.get("/api/ibkr/status").json()["data"]["connected"] is False and "7654321" not in c.get("/api/ibkr/status").text
    c2, b2, ib2 = ib_client(tmp_path, port=7496)
    with c2:
        r = c2.post("/api/ibkr/connect")
        assert r.status_code == 403 and r.json()["error"]["code"] == "LIVE_PORT_REFUSED" and ib2.connect_calls == []
    c3, b3, ib3 = ib_client(tmp_path, mode="readonly", port=7496, accounts=("U7654321",))
    with c3:                                                                              # read-only access to a live account is allowed, trading is not
        st = c3.post("/api/ibkr/connect").json()["data"]
        assert st["connected"] and not st["can_trade"] and ib3.connect_calls[0]["readonly"] is True
        pf = c3.post("/api/ibkr/portfolio", json={"name": "Live (read only)"}).json()["data"]
        assert pf["kind"] == "manual"
        r = c3.post("/api/orders/preview", json={"instrument_id": "AAPL", "side": "buy", "qty": "1", "type": "market", "planned_stop": "150", "portfolio_id": pf["id"]})
        assert r.status_code == 409 and r.json()["error"]["code"] == "MANUAL_PORTFOLIO"
    c4, b4, ib4 = ib_client(tmp_path, port=7497)
    ib4.refuse = True
    with c4:
        r = c4.post("/api/ibkr/connect")
        assert r.status_code == 502 and r.json()["error"]["code"] == "IBKR_UNREACHABLE"
        assert c4.post("/api/ibkr/portfolio", json={"name": "x"}).json()["error"]["code"] == "NOT_CONNECTED"


def test_ibkr_executions_reach_the_journal_through_sync(tmp_path):
    from types import SimpleNamespace as NS

    c, b, ib = ib_client(tmp_path, mode="readonly", port=7497)
    ib.exec_fills = [NS(contract=NS(symbol="AAPL", secType="STK", currency="USD", multiplier=""), execution=NS(execId=i, time=datetime(2026, 3, 9, 15, m, tzinfo=timezone.utc), side=sd, shares=10, price=px),
                        commissionReport=NS(commission=1.0)) for i, m, sd, px in (("e1", 1, "BOT", 190.0), ("e2", 5, "SLD", 200.0))]
    with c:
        c.post("/api/ibkr/connect")
        r = c.post("/api/journal/sync").json()["data"]
        assert r["ibkr"] == {"inserted": 2, "duplicates": 0} and c.post("/api/journal/sync").json()["data"]["ibkr"] == {"inserted": 0, "duplicates": 2}
        (t,) = c.get("/api/journal/trades").json()["data"]["trades"]
        assert t["source"] == "ibkr:DU1234567" and Dec(t["net_pnl"]) == Dec("98")
