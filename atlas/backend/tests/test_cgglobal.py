"""CoinGecko whole-market snapshot: parsed from a real response (fetched 2026-11-08), arithmetic, rate-limit message, staleness, failures labelled, demo invents nothing."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import cgglobal as G
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "coingecko_global.json").read_text())
UPDATED = datetime.fromtimestamp(RAW["data"]["updated_at"], timezone.utc)
NOW = UPDATED.replace(minute=UPDATED.minute)


def test_the_real_response_is_read_with_arithmetic_on_it():
    r = G.parse(RAW, NOW)
    d = RAW["data"]
    assert r["total_market_cap_trillions"] == round(d["total_market_cap"]["usd"] / 1e12, 3) and r["btc_dominance_pct"] == round(d["market_cap_percentage"]["btc"], 1)
    assert r["volume_to_cap_pct"] == round(d["total_volume"]["usd"] / d["total_market_cap"]["usd"] * 100, 1) and r["change_24h_pct"] == round(d["market_cap_change_percentage_24h_usd"], 2)
    assert r["btc_dominance_pct"] + r["eth_dominance_pct"] + r["other_pct"] == pytest.approx(100.0, abs=0.11)
    assert r["stablecoin_share_pct"] == round(d["market_cap_percentage"]["usdt"] + d["market_cap_percentage"]["usdc"], 1) and "USDT" in [t["symbol"] for t in r["top"]] and r["top"][0]["symbol"] == "BTC"
    assert r["freshness"] == "CURRENT" and r["age_minutes"] == 0


def test_stale_data_is_overdue_and_a_missing_stablecoin_share_is_none_not_zero():
    later = datetime.fromtimestamp(RAW["data"]["updated_at"] + 5 * 3600, timezone.utc)
    assert G.parse(RAW, later)["freshness"] == "OVERDUE"
    raw = json.loads(json.dumps(RAW))
    raw["data"]["market_cap_percentage"].pop("usdt")
    raw["data"]["market_cap_percentage"].pop("usdc")
    r = G.parse(raw, NOW)
    assert r["stablecoin_share_pct"] is None and r["stablecoin_note"] is None


def test_zero_market_value_and_missing_fields_are_refused():
    raw = json.loads(json.dumps(RAW))
    raw["data"]["total_market_cap"]["usd"] = 0
    with pytest.raises(ValueError):
        G.parse(raw, NOW)
    with pytest.raises(KeyError):
        G.parse({"data": {}}, NOW)


def go(handler, demo=False):
    return asyncio.run(G.CoinGeckoGlobal(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_the_snapshot_with_credit_and_source():
    r = go(lambda req: httpx.Response(200, json=RAW))
    assert r["available"] and r["credit"] == "Data provided by CoinGecko" and "CoinGecko" in r["source"] and "not a signal" in r["note"]


def test_rate_limit_is_said_plainly_and_other_failures_show_no_numbers():
    r = go(lambda req: httpx.Response(429))
    assert r["available"] is False and "rate limited" in r["reason"] and "total_market_cap_trillions" not in r
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={"data": {}}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "CoinGecko" in r["reason"] and "btc_dominance_pct" not in r


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, json=RAW), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "g.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/btc/market").json()["data"]
        assert d["demo"] is True and d["available"] is False
