"""Signal HTTP API: the mobile contract (shapes, errors), read-only guarantees, demo labelling, and live-mode behaviour with scripted providers."""
import json
import re
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import app as app_module
from atlas_api.app import create_app
from atlas_api.signal import assets as A
from atlas_api.signal import fixtures
from signal_helpers import FakeFund, ScriptProvider

BTC, AAPL, SPY = "CRYPTO:COINBASE:BTC-USD:SPOT", "EQUITY:NASDAQ:AAPL", "ETF:ARCA:SPY"


@pytest.fixture(autouse=True)
def regular_session(monkeypatch):
    monkeypatch.setattr("atlas_api.service.session_state", lambda now=None: {"state": "REGULAR"})


@pytest.fixture
def demo(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=True, alert_loop=False)) as c:
        yield c


def data(r):
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    return j["data"]


def test_meta_says_research_only_and_what_is_covered(demo):
    m = data(demo.get("/api/signal/meta"))
    assert m["demo"] is True and m["live_trading"] is False and m["agents"] == ["news", "technical", "macro", "fundamentals"] and m["ai"]["enabled"] is False
    assert "Coinbase" in m["coverage"]["crypto"] and "Nasdaq Trader" in m["coverage"]["stocks_etfs"] and "Nothing in this service places or authorises an order" in m["notes"][0]


def test_search_results_have_stable_ids_types_and_venues(demo):
    r = data(demo.get("/api/signal/search", params={"q": "sol"}))
    assert r["results"][0] == {"id": "CRYPTO:COINBASE:SOL-USD:SPOT", "symbol": "SOL", "name": "Solana", "type": "crypto", "venue": "Coinbase spot (USD)", "support": "supported",
                               "note": r["results"][0]["note"]}
    assert data(demo.get("/api/signal/search", params={"q": ""}))["results"] == []
    none = data(demo.get("/api/signal/search", params={"q": "qwertyuiop"}))
    assert none["results"] == [] and "No supported asset" in none["unsupported"]["message"]


def test_watchlist_add_is_idempotent_validates_ids_and_reports_the_new_order(demo):
    assert data(demo.post("/api/signal/watchlist", json={"id": AAPL}))["added"] is True
    again = data(demo.post("/api/signal/watchlist", json={"id": AAPL}))
    assert again["added"] is False and again["ids"] == [AAPL]
    bad = demo.post("/api/signal/watchlist", json={"id": "NOPE"})
    assert bad.status_code == 404 and bad.json() == {"ok": False, "error": {"code": "UNKNOWN_ASSET", "message": bad.json()["error"]["message"]}}
    assert demo.post("/api/signal/watchlist", json={}).status_code == 422
    data(demo.post("/api/signal/watchlist", json={"id": BTC}))
    assert data(demo.put("/api/signal/watchlist/positions", json={"ids": [BTC, AAPL]}))["ids"] == [BTC, AAPL]
    mismatch = demo.put("/api/signal/watchlist/positions", json={"ids": [BTC]})
    assert mismatch.status_code == 409 and mismatch.json()["error"]["code"] == "ORDER_MISMATCH"
    assert [r["asset"]["id"] for r in data(demo.get("/api/signal/watchlist"))["items"]] == [BTC, AAPL]
    assert data(demo.delete(f"/api/signal/watchlist/{BTC}"))["removed"] is True and data(demo.delete(f"/api/signal/watchlist/{BTC}"))["removed"] is False


def test_watchlist_rows_are_labelled_demo_in_demo_mode(demo):
    data(demo.post("/api/signal/watchlist", json={"id": AAPL}))
    w = data(demo.get("/api/signal/watchlist"))
    row = w["items"][0]
    assert w["demo"] is True and row["quote"]["prov"]["status"] == "DEMO" and row["quote"]["prov"]["provider"] == "demo" and row["takeaway"]["source"].startswith("Technical")
    assert len(row["spark"]) == 30 and row["asset"]["type"] == "stock"


def test_asset_header_includes_saved_flag_and_chart_ranges(demo):
    h = data(demo.get(f"/api/signal/asset/{AAPL}"))
    assert h["saved"] is False and h["quote"]["prov"]["event_time"]
    data(demo.post("/api/signal/watchlist", json={"id": AAPL}))
    assert data(demo.get(f"/api/signal/asset/{AAPL}"))["saved"] is True
    for rng in ("1D", "1W", "1M", "3M", "1Y", "5Y"):
        ch = data(demo.get(f"/api/signal/chart/{AAPL}", params={"range": rng}))
        assert ch["range"] == rng and len(ch["points"]) >= 2 and ch["prov"]["status"] == "DEMO"
    bad = demo.get(f"/api/signal/chart/{AAPL}", params={"range": "10Y"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_RANGE"
    assert demo.get("/api/signal/chart/NOT-REAL").status_code == 404


def test_research_bundle_has_four_findings_a_briefing_and_demo_labels_everywhere(demo):
    r = data(demo.get(f"/api/signal/research/{AAPL}", params={"wait": 20}))
    assert r["pending"] == [] and r["demo"] is True and set(r["findings"]) == {"news", "technical", "macro", "fundamentals"}
    for name, f in r["findings"].items():
        assert f["demo"] is True and f["status"] in ("ok", "partial") and f["takeaway"] and f["analyzed_at"] and f["ttl_seconds"] > 0, name
        assert f["sources"] and all(x["source"] for x in f["facts"]), name
    news = r["findings"]["news"]
    assert all(s["title"].startswith("[DEMO]") and s["demo"] is True and s["link"] is None for s in news["stories"])
    assert r["briefing"]["demo"] is True and r["briefing"]["headline"] and r["briefing"]["coverage"]["agents_total"] == 4
    assert any("Demo" in x["source"] for x in r["findings"]["fundamentals"]["facts"]) or r["findings"]["fundamentals"]["sources"][0]["status"] == "DEMO"


def test_research_returns_partial_results_quickly_and_completes_later(demo):
    first = data(demo.get(f"/api/signal/research/{SPY}", params={"wait": 0}))
    assert set(first["pending"]) | {n for n, f in first["findings"].items() if f["status"] != "pending"} == {"news", "technical", "macro", "fundamentals"}
    deadline = time.time() + 20
    while time.time() < deadline:
        r = data(demo.get(f"/api/signal/research/{SPY}", params={"wait": 2}))
        if not r["pending"]:
            break
    assert r["pending"] == [] and all(f["status"] != "pending" for f in r["findings"].values())


def test_agent_refresh_has_a_cooldown_and_validates_the_agent(demo):
    data(demo.get(f"/api/signal/research/{BTC}", params={"wait": 20}))
    ok = demo.post(f"/api/signal/research/{BTC}/refresh", json={"agent": "news"})
    assert ok.status_code == 200 and ok.json()["data"]["findings"]["news"]["status"] in ("ok", "partial")
    again = demo.post(f"/api/signal/research/{BTC}/refresh", json={"agent": "news"})
    assert again.status_code == 429 and again.json()["error"]["code"] == "COOLDOWN"
    assert demo.post(f"/api/signal/research/{BTC}/refresh", json={"agent": "weather"}).status_code == 422


def test_there_is_no_way_to_trade_through_signal(demo):
    for method, path in (("post", "/api/signal/orders"), ("post", "/api/signal/trade"), ("put", f"/api/signal/asset/{AAPL}"), ("post", f"/api/signal/asset/{AAPL}")):
        assert getattr(demo, method)(path, json={"side": "buy", "qty": 1}).status_code in (404, 405)
    assert demo.post("/api/orders/live", json={}).status_code == 403                                           # the terminal's live-order route still refuses everything
    paths = {getattr(r, "path", "") for r in demo.app.routes}
    sig = [p for p in paths if p.startswith("/api/signal")]
    assert sig and not any(re.search(r"order|trade|buy|sell|execute", p) for p in sig)


def test_demo_fixtures_are_labelled_synthetic_everywhere():
    from datetime import datetime, timezone
    a, now = A.describe(AAPL), datetime.now(timezone.utc)
    news = fixtures.news(a, now)
    assert all(s["title"].startswith("[DEMO]") and s["link"] is None and s["status"] == "DEMO" for s in news["items"])
    mo = fixtures.macro_overview(now)
    assert mo["demo_fixture"] is True and all(f["status"] == "DEMO" for f in mo["facts"])
    assert "synthetic" in fixtures.etf_raw(a)["info"]["longName"] and "demo" in fixtures.coin_raw(A.describe(BTC))["name"] and "Synthetic" in fixtures.coin_raw(A.describe(BTC))["description"]["en"]


# --- live mode with scripted providers (no network) -----------------------------------------------------------------------------------------------
@pytest.fixture
def live(tmp_path, monkeypatch):
    async def noop(self):
        return None
    monkeypatch.setattr(A.AssetRegistry, "ensure_directory", noop)
    monkeypatch.setattr(A.AssetRegistry, "ensure_products", noop)
    for name in ("news", "macro_overview", "fedwatch", "etf_raw", "coin_raw", "btc_snapshot"):
        monkeypatch.setattr(fixtures, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("demo fixture used in live mode")))
    p = ScriptProvider(drift=0.003)
    net = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    app = create_app(db_path=str(tmp_path / "l.db"), demo=False, providers={"yahoo": p, "coinbase": p}, alert_loop=False, news_loop=False, news_client=net, fundamentals_provider=_FundProvider())
    with TestClient(app) as c:
        c.provider = p
        yield c


class _FundProvider:
    name = "yahoo"

    async def fetch(self, inst):
        from signal_helpers import HEALTHY_INFO
        return dict(HEALTHY_INFO), 100.0, None


def test_live_mode_research_has_no_demo_labels_and_reports_unconfigured_sources(live):
    live.post("/api/signal/watchlist", json={"id": AAPL})
    r = data(live.get(f"/api/signal/research/{AAPL}", params={"wait": 25}))
    assert r["demo"] is False and not any(f["demo"] for f in r["findings"].values())
    macro = r["findings"]["macro"]
    assert macro["status"] == "unavailable" and "not configured" in macro["error"].lower()                      # no FRED provider was given: said plainly, never faked
    assert r["findings"]["technical"]["status"] in ("ok", "partial") and r["findings"]["fundamentals"]["status"] in ("ok", "partial") and r["findings"]["fundamentals"]["sources"][0]["name"].startswith("Yahoo")
    news = r["findings"]["news"]
    assert news["status"] in ("unavailable", "partial", "ok") and "[DEMO]" not in json.dumps(news)
    assert r["briefing"]["coverage"]["unavailable"] and "macro" in {u["agent"] for u in r["briefing"]["coverage"]["unavailable"]}
    assert "DEMO" not in json.dumps(r)


def test_live_stale_provider_data_is_labelled_stale_end_to_end(tmp_path, monkeypatch):
    async def noop(self):
        return None
    monkeypatch.setattr(A.AssetRegistry, "ensure_directory", noop)
    monkeypatch.setattr(A.AssetRegistry, "ensure_products", noop)
    p = ScriptProvider(age=3 * 86400)
    app = create_app(db_path=str(tmp_path / "s.db"), demo=False, providers={"yahoo": p, "coinbase": p}, alert_loop=False, news_loop=False,
                     news_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))), fundamentals_provider=_FundProvider())
    with TestClient(app) as c:
        c.post("/api/signal/watchlist", json={"id": AAPL})
        w = data(c.get("/api/signal/watchlist"))["items"][0]
        assert w["quote"]["prov"]["status"] == "STALE"
        t = data(c.get(f"/api/signal/research/{AAPL}", params={"wait": 25}))["findings"]["technical"]
        assert t["sources"][0]["status"] == "STALE"


def test_a_provider_outage_shows_in_rows_and_in_the_technical_finding_only(live):
    live.provider.fail_quote = True
    live.provider.fail = {"1d"}
    live.post("/api/signal/watchlist", json={"id": AAPL})
    row = data(live.get("/api/signal/watchlist"))["items"][0]
    assert row["quote"] is None and row["error"]["code"] == "DATA_UNAVAILABLE" and row["spark"] is None
    r = data(live.get(f"/api/signal/research/{AAPL}", params={"wait": 25}))
    assert r["findings"]["technical"]["status"] == "unavailable" and r["findings"]["fundamentals"]["status"] in ("ok", "partial")
    ch = live.get(f"/api/signal/chart/{AAPL}", params={"range": "1M"})
    assert ch.status_code == 503 and ch.json()["error"]["code"] == "DATA_UNAVAILABLE"
