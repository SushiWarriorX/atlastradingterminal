import json

import pytest
from fastapi.testclient import TestClient

from atlas_api.ai.llm import LLMResponse
from atlas_api.app import create_app
from atlas_api import commands


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(db_path=str(tmp_path / "a.db"), demo=True))


@pytest.fixture
def client_live_no_net(tmp_path):
    """Not demo, no providers configured: must report UNAVAILABLE, never synthetic quotes."""
    return TestClient(create_app(db_path=str(tmp_path / "b.db"), demo=False, providers={}))


def test_status_and_safety_flags(client):
    d = client.get("/api/market/status").json()["data"]
    assert d["broker_env"] == "PAPER" and d["live_trading_enabled"] is False and d["demo_mode"] is True
    assert d["ny"]["state"] in {"PREMARKET", "REGULAR", "AFTER_HOURS", "CLOSED", "HOLIDAY"}
    assert client.get("/api/ai/status").json()["data"]["order_tools"] == []


def test_quote_envelope_and_status_labels(client):
    r = client.get("/api/quotes", params={"ids": "BTC-USD,AAPL,NOPE1234"})
    assert r.status_code == 404  # unknown instrument is a structured error
    assert r.json()["error"]["code"] == "UNKNOWN_INSTRUMENT"
    r = client.get("/api/quotes", params={"ids": "BTC-USD,AAPL"}).json()
    assert r["ok"] and all(q["prov"]["status"] == "DEMO" for q in r["data"])


def test_unavailable_is_explicit_without_demo(client_live_no_net):
    r = client_live_no_net.get("/api/quotes", params={"ids": "AAPL"}).json()["data"][0]
    assert r["status"] == "UNAVAILABLE" and "price" not in r
    r = client_live_no_net.get("/api/ohlcv/AAPL")
    assert r.status_code == 503 and r.json()["error"]["code"] == "DATA_UNAVAILABLE"
    strip = client_live_no_net.get("/api/market/strip").json()["data"]
    assert all(s["status"] == "UNAVAILABLE" for s in strip)


def test_ohlcv_indicators_levels(client):
    o = client.get("/api/ohlcv/CRYPTO:COINBASE:BTC-USD:SPOT", params={"interval": "4h", "limit": 120}).json()["data"]
    assert o["derived_from"] == "1h" and len(o["candles"]) == 120
    i = client.get("/api/technical/indicators", params={"instrument_id": "BTC", "interval": "1d", "ind_specs": "sma:20,rsi:14,bb:20:2,macd"}).json()["data"]
    assert len(i["times"]) == len(i["series"]["sma:20"]) and i["series"]["sma:20"][0] is None and i["series"]["sma:20"][-1] is not None
    assert "bb:20:2:upper" in i["series"] and "macd:hist" in i["series"]
    bad = client.get("/api/technical/indicators", params={"instrument_id": "BTC", "ind_specs": "foo:3"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_INDICATOR"
    lv = client.get("/api/technical/levels", params={"instrument_id": "SPY", "interval": "15m"}).json()["data"]
    assert lv["levels"] and all(l["derivation"] for l in lv["levels"])


def test_watchlists_and_prefs_persist_across_restart(tmp_path):
    path = str(tmp_path / "p.db")
    c = TestClient(create_app(db_path=path, demo=True))
    wl = c.get("/api/watchlists").json()["data"]
    assert wl[0]["name"] == "Core" and "CRYPTO:COINBASE:BTC-USD:SPOT" in wl[0]["items"]
    new = c.post("/api/watchlists", json={"name": "Semis"}).json()["data"]
    c.post(f"/api/watchlists/{new['id']}/items", json={"instrument_id": "NVDA"})
    c.post(f"/api/watchlists/{new['id']}/items", json={"instrument_id": "AMD"})
    c.delete(f"/api/watchlists/{new['id']}/items/EQUITY:NASDAQ:AMD")
    assert c.post("/api/watchlists", json={"name": "Semis"}).status_code == 409
    c.put("/api/prefs", json={"theme": "light", "update_seconds": 10})
    c.put("/api/layouts/overview", json={"lg": [{"i": "chart", "x": 1, "y": 2, "w": 3, "h": 4}]})
    assert c.put("/api/prefs", json={"theme": "pink"}).status_code == 422
    c2 = TestClient(create_app(db_path=path, demo=True))  # "restart"
    lists = {w["name"]: w["items"] for w in c2.get("/api/watchlists").json()["data"]}
    assert lists["Semis"] == ["EQUITY:NASDAQ:NVDA"]
    assert c2.get("/api/prefs").json()["data"]["theme"] == "light"
    assert c2.get("/api/layouts/overview").json()["data"]["lg"][0]["w"] == 3


def test_websocket_pushes_quotes_with_provenance(client):
    with client.websocket_connect("/ws/market-data") as ws:
        ws.send_json({"subscribe": ["BTC-USD", "SPY"]})
        msg = ws.receive_json()  # first push may precede subscription; poll once more if empty
        if not msg["data"]:
            msg = ws.receive_json()
        assert msg["type"] == "quotes" and {q["instrument_id"] for q in msg["data"]} == {"CRYPTO:COINBASE:BTC-USD:SPOT", "ETF:ARCA:SPY"}
        assert msg["data"][0]["prov"]["status"] == "DEMO"


def test_ai_unconfigured_is_503(client):
    r = client.post("/api/ai/chat", json={"message": "hi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "AI_NOT_CONFIGURED"


# --- command grammar -------------------------------------------------------
@pytest.mark.parametrize("text,view,impl", [
    ("BTC", "btc", True), ("BTC CHART", "charts", True), ("AAPL", "equities", True), ("NVDA TECH", "charts", True),
    ("NVDA NEWS", "news", True), ("BTC OI", "btc", True), ("BTC FUNDING", "btc", True),
    ("SCAN", "scanner", True), ("SCAN BREAKOUT", "scanner", True), ("MACRO", "macro", True), ("FED", "macro", True),
    ("RISK", "risk", True), ("JOURNAL", "journal", True), ("PERF", "journal", True), ("PORT", "portfolio", True), ("BUY AAPL 10", "portfolio", True), ("SELL BTC 0.1 STOP 68000", "portfolio", True), ("AI BTC", "ai", True), ("COMPARE BTC QQQ", "charts", True), ("BTC MTF", "btc", True), ("NVDA MTF", "equities", True),
    ("HELP", "help", True), ("aapl gp", "charts", True),
])
def test_commands(text, view, impl):
    c = commands.resolve(text)
    assert c.ok and c.view == view and c.implemented is impl, c


def test_command_errors_suggest():
    c = commands.resolve("MACROO")
    assert not c.ok and "MACRO" in c.suggestions
    c = commands.resolve("BTC CHRAT")
    assert not c.ok and "CHART" in c.suggestions
    assert not commands.resolve("   ").ok
    nl = commands.resolve("Why is BTC selling off today and what changed")
    assert nl.view == "ai" and nl.params["ask"].startswith("Why is BTC")
