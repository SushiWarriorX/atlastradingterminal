import asyncio
import json
import math
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.derivatives import compute as C
from atlas_api.derivatives import venues as V
from atlas_api.derivatives.service import DemoVenueClient, DerivativesService

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def run(c):
    return asyncio.run(c)


# --- fixtures in the documented shapes ---------------------------------------------------------------------------------------------------
HL = [{"universe": [{"name": "ETH"}, {"name": "BTC"}]}, [{"funding": "0.00002", "openInterest": "1", "markPx": "3000"},
                                                        {"funding": "0.0000125", "openInterest": "30000.5", "markPx": "67100.0", "oraclePx": "67050.0"}]]
BN_P = {"symbol": "BTCUSDT", "markPrice": "67120.50", "indexPrice": "67100.00", "lastFundingRate": "0.00010000", "nextFundingTime": NOW_MS + 3_600_000, "time": NOW_MS}
BN_O = {"symbol": "BTCUSDT", "openInterest": "80000.250", "time": NOW_MS}
BY = {"retCode": 0, "retMsg": "OK", "result": {"category": "linear", "list": [{"symbol": "BTCUSDT", "markPrice": "67110.0", "indexPrice": "67095.0", "fundingRate": "0.00008",
                                                                              "openInterest": "50000", "nextFundingTime": str(NOW_MS + 1000)}]}, "time": NOW_MS}
OK_F = {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "fundingRate": "0.00006", "fundingTime": str(NOW_MS), "nextFundingTime": str(NOW_MS + 8 * 3_600_000)}]}
OK_O = {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "oi": "5000000", "oiCcy": "50000.0", "oiUsd": "3355000000", "ts": str(NOW_MS)}]}
OK_M = {"code": "0", "data": [{"markPx": "67105.0", "ts": str(NOW_MS)}]}
OK_I = {"code": "0", "data": [{"idxPx": "67098.0", "ts": str(NOW_MS)}]}


# --- parsers ------------------------------------------------------------------------------------------------------------------------------
def test_each_venue_parses_to_the_same_record_with_units_normalised():
    h, b, y, o = V.parse_hyperliquid(HL), V.parse_binance(BN_P, BN_O), V.parse_bybit(BY), V.parse_okx(OK_F, OK_O, OK_M, OK_I)
    assert (h["mark"], h["index"], h["funding_rate"], h["funding_interval_h"], h["oi_btc"]) == (67100.0, 67050.0, 0.0000125, 1.0, 30000.5)
    assert (b["mark"], b["index"], b["funding_rate"], b["funding_interval_h"], b["oi_btc"], b["ts_ms"]) == (67120.5, 67100.0, 0.0001, 8.0, 80000.25, NOW_MS)
    assert (y["mark"], y["funding_rate"], y["funding_interval_h"], y["oi_btc"]) == (67110.0, 0.00008, 8.0, 50000.0)
    assert (o["funding_interval_h"], o["oi_btc"], o["mark"], o["index"]) == (8.0, 50000.0, 67105.0, 67098.0)       # OKX: interval measured, OI in coin units not contracts
    assert any("assumed 8 h" in n for n in b["notes"]) and not any("assumed" in n for n in o["notes"])


def test_okx_interval_is_measured_not_assumed():
    f = {"code": "0", "data": [{"fundingRate": "0.00001", "fundingTime": str(NOW_MS), "nextFundingTime": str(NOW_MS + 4 * 3_600_000)}]}
    assert V.parse_okx(f, OK_O, OK_M, OK_I)["funding_interval_h"] == 4.0
    bad = {"code": "0", "data": [{"fundingRate": "0.00001", "fundingTime": str(NOW_MS), "nextFundingTime": str(NOW_MS)}]}
    with pytest.raises(V.VenueError, match="cannot measure the funding interval"):
        V.parse_okx(bad, OK_O, OK_M, OK_I)


@pytest.mark.parametrize("call", [
    lambda: V.parse_hyperliquid([{"universe": [{"name": "ETH"}]}, [{}]]),
    lambda: V.parse_hyperliquid("nope"),
    lambda: V.parse_binance({"code": -1121, "msg": "Invalid symbol."}, BN_O),
    lambda: V.parse_binance({**BN_P, "markPrice": "0"}, BN_O),
    lambda: V.parse_binance({**BN_P, "lastFundingRate": "NaN"}, BN_O),
    lambda: V.parse_bybit({"retCode": 10001, "retMsg": "params error"}),
    lambda: V.parse_bybit({"retCode": 0, "result": {"list": []}}),
    lambda: V.parse_okx({"code": "51001", "msg": "Instrument ID does not exist"}, OK_O, OK_M, OK_I),
    lambda: V.parse_okx(OK_F, {"code": "0", "data": []}, OK_M, OK_I),
    lambda: V.parse_binance(BN_P, {"openInterest": "-5"}),
])
def test_wrong_shapes_and_error_replies_raise_instead_of_guessing(call):
    with pytest.raises(V.VenueError):
        call()


# --- arithmetic ---------------------------------------------------------------------------------------------------------------------------
def row(raw, now=NOW):
    return C.enrich(raw, now)


def test_funding_basis_and_open_interest_are_hand_checked():
    h = row(V.parse_hyperliquid(HL))
    assert h["funding_8h_pct"] == pytest.approx(0.0000125 * 8 * 100) and h["funding_annual_pct"] == pytest.approx(0.0000125 * 8760 * 100)         # hourly venue: x8 and x8760
    assert h["basis_pct"] == pytest.approx((67100 - 67050) / 67050 * 100) and h["oi_usd"] == pytest.approx(30000.5 * 67100)
    b = row(V.parse_binance(BN_P, BN_O))
    assert b["funding_8h_pct"] == pytest.approx(0.01) and b["funding_annual_pct"] == pytest.approx(0.0001 * 3 * 365 * 100)       # 0.01% per 8h = 10.95% a year
    assert b["status"] == "LIVE" and b["age_seconds"] == pytest.approx(0)


def test_aggregate_is_oi_weighted_and_discloses_coverage_and_disagreement():
    rows = [row(V.parse_binance(BN_P, BN_O)), row(V.parse_bybit(BY)), row(V.parse_okx(OK_F, OK_O, OK_M, OK_I)),
            {"venue": "hyperliquid", "ok": False, "error": {"code": "blocked", "message": "x"}}]
    a = C.aggregate(rows, 4)
    w = [(r["funding_annual_pct"], r["oi_usd"]) for r in rows if r.get("ok")]
    assert a["funding_annual_pct"] == pytest.approx(sum(f * o for f, o in w) / sum(o for _, o in w))
    assert a["oi_btc"] == pytest.approx(80000.25 + 50000 + 50000) and a["venues_ok"] == 3 and a["venues_failed"] == ["hyperliquid"]
    assert any("only 3 of 4 venues answered" in f for f in a["flags"])
    assert a["funding_spread_annual_pct"] == pytest.approx(max(r["funding_annual_pct"] for r in rows[:3]) - min(r["funding_annual_pct"] for r in rows[:3]))


def test_price_disagreement_and_sign_disagreement_raise_flags():
    a = row(V.parse_binance(BN_P, BN_O))
    b = row({**V.parse_bybit(BY), "mark": 67_700.0, "funding_rate": -0.0001})
    flags = " ".join(C.aggregate([a, b], 2)["flags"])
    assert "disagree on the mark price" in flags and "disagree on the sign of funding" in flags


def test_staleness_and_clock_skew_are_labelled():
    old = row({**V.parse_binance(BN_P, BN_O), "ts_ms": NOW_MS - 600_000})
    assert old["status"] == "STALE" and C.aggregate([old], 1)["flags"][0].startswith("at least one venue")
    future = row({**V.parse_binance(BN_P, BN_O), "ts_ms": NOW_MS + 600_000})
    assert any("future" in n for n in future["notes"])
    none = row({**V.parse_binance(BN_P, BN_O), "ts_ms": 0})
    assert none["status"] == "STALE" and any("freshness unknown" in n for n in none["notes"])


def test_nothing_answering_is_unavailable_not_zero():
    assert C.aggregate([{"venue": "x", "ok": False}], 4) == {"venues_ok": 0, "venues_expected": 4, "venues_failed": ["x"], "flags": [], "available": False}


def test_percentile_needs_enough_history():
    assert C.percentile([1.0] * 10, 5.0) == {"available": False, "have": 10, "need": 100}
    p = C.percentile(list(range(100)), 50.0)
    assert p["available"] and p["pctile"] == pytest.approx(51.0)


# --- client (HTTP failure handling) -------------------------------------------------------------------------------------------------------
def client_with(handler):
    return V.VenueClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("status,code", [(451, "blocked"), (403, "blocked"), (429, "rate_limited"), (500, "http")])
def test_http_errors_are_classified_without_echoing_the_url(status, code):
    c = client_with(lambda r: httpx.Response(status))
    with pytest.raises(V.VenueError) as e:
        run(c.bybit())
    assert e.value.code == code and "bybit.com" not in e.value.message and "api." not in e.value.message


def test_non_json_and_network_errors_are_venue_errors():
    with pytest.raises(V.VenueError, match="not JSON"):
        run(client_with(lambda r: httpx.Response(200, content=b"<html>")).bybit())

    def boom(r):
        raise httpx.ConnectError("dns")
    with pytest.raises(V.VenueError, match="unreachable"):
        run(client_with(boom).bybit())


def test_client_fetches_the_documented_endpoints():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.host, req.url.path, req.url.query.decode()))
        h, p = req.url.host, req.url.path
        if h == "api.hyperliquid.xyz":
            assert json.loads(req.content) == {"type": "metaAndAssetCtxs"}
            return httpx.Response(200, json=HL)
        if h == "fapi.binance.com":
            return httpx.Response(200, json=BN_P if p.endswith("premiumIndex") else BN_O)
        if h == "api.bybit.com":
            return httpx.Response(200, json=BY)
        return httpx.Response(200, json={"public/funding-rate": OK_F, "public/open-interest": OK_O, "public/mark-price": OK_M, "market/index-tickers": OK_I}[p.split("/v5/")[1]])
    c = client_with(handler)
    for v in V.VENUES:
        assert run(c.fetch(v))["venue"] == v
    assert ("POST", "api.hyperliquid.xyz", "/info", "") in seen and any(p == "/fapi/v1/openInterest" for _, _, p, _ in seen)
    assert ("GET", "api.bybit.com", "/v5/market/tickers", "category=linear&symbol=BTCUSDT") in seen and sum(1 for s in seen if s[1] == "www.okx.com") == 4


# --- service ------------------------------------------------------------------------------------------------------------------------------
class Fake:
    def __init__(self, fail=(), mark_shift=0.0):
        self.fail, self.calls, self.shift = set(fail), [], mark_shift

    async def fetch(self, venue):
        self.calls.append(venue)
        if venue in self.fail:
            raise V.VenueError("blocked", "the exchange refused the connection (HTTP 451)")
        raw = {"hyperliquid": V.parse_hyperliquid(HL), "binance": V.parse_binance(BN_P, BN_O), "bybit": V.parse_bybit(BY), "okx": V.parse_okx(OK_F, OK_O, OK_M, OK_I)}[venue]
        return {**raw, "ts_ms": int(time.time() * 1000), "mark": raw["mark"] + self.shift}


def test_one_blocked_venue_does_not_sink_the_rest_and_history_is_recorded(db):
    s = DerivativesService(db, Fake(fail={"binance"}))
    snap = run(s.snapshot())
    by = {r["venue"]: r for r in snap["venues"]}
    assert by["binance"]["ok"] is False and by["binance"]["status"] == "UNAVAILABLE" and "HTTP 451" in by["binance"]["error"]["message"]
    assert by["bybit"]["ok"] and snap["aggregate"]["venues_ok"] == 3 and any("only 3 of 4" in f for f in snap["aggregate"]["flags"])
    assert db.q("SELECT COUNT(*) FROM deriv_history WHERE venue='ALL'")[0][0] == 1 and db.q("SELECT COUNT(*) FROM deriv_history WHERE venue='binance'")[0][0] == 0
    assert snap["aggregate"]["funding_percentile_30d"] == {"available": False, "have": 1, "need": 100}
    assert snap["aggregate"]["oi_change_24h_pct"]["available"] is False and "keep ATLAS running" in snap["aggregate"]["oi_change_24h_pct"]["reason"]


def test_everything_failing_is_unavailable_and_records_nothing(db):
    s = DerivativesService(db, Fake(fail=set(V.VENUES)))
    snap = run(s.snapshot())
    assert snap["aggregate"]["available"] is False and db.q("SELECT COUNT(*) FROM deriv_history")[0][0] == 0


def test_snapshot_is_cached_and_fresh_bypasses_the_cache(db):
    f = Fake()
    s = DerivativesService(db, f)
    run(s.snapshot())
    run(s.snapshot())
    assert len(f.calls) == 4
    run(s.snapshot(fresh=True))
    assert len(f.calls) == 8


def test_percentile_and_24h_change_come_from_recorded_history(db):
    s = DerivativesService(db, Fake())
    now = datetime.now(timezone.utc)
    cur = run(s.snapshot())["aggregate"]
    with db.tx() as c:                                                                  # 150 older points, and one point 24h ago with half the open interest
        for i in range(150):
            c.execute("INSERT INTO deriv_history(ts,venue,funding_annual_pct,oi_usd) VALUES(?,?,?,?)", ((now - timedelta(hours=1 + i / 10)).isoformat(), "ALL", cur["funding_annual_pct"] - 1 + (i % 3), cur["oi_usd"]))
        c.execute("INSERT INTO deriv_history(ts,venue,funding_annual_pct,oi_usd) VALUES(?,?,?,?)", ((now - timedelta(hours=24)).isoformat(), "ALL", 5.0, cur["oi_usd"] / 2))
    a = run(s.snapshot(fresh=True))["aggregate"]
    assert a["funding_percentile_30d"]["available"] and a["funding_percentile_30d"]["points"] >= 150
    assert a["oi_change_24h_pct"]["available"] and a["oi_change_24h_pct"]["value"] == pytest.approx(100.0, abs=1.0)
    h = s.history(48)
    assert len(h["funding_annual_pct"]) >= 150 and h["hours"] == 48


def test_demo_mode_is_labelled_demo_and_records_no_history(db):
    s = DerivativesService(db, None, demo=True)
    snap = run(s.snapshot())
    assert snap["demo"] is True and {r["status"] for r in snap["venues"]} == {"DEMO"} and all(any("synthetic" in n for n in r["notes"]) for r in snap["venues"])
    assert db.q("SELECT COUNT(*) FROM deriv_history")[0][0] == 0 and snap["aggregate"]["venues_ok"] == 4


def test_a_bug_inside_one_venue_is_contained(db):
    class Boom(Fake):
        async def fetch(self, venue):
            if venue == "okx":
                raise KeyError("x")
            return await super().fetch(venue)
    snap = run(DerivativesService(db, Boom()).snapshot())
    okx = next(r for r in snap["venues"] if r["venue"] == "okx")
    assert okx["ok"] is False and okx["error"]["code"] == "internal" and snap["aggregate"]["venues_ok"] == 3


# --- API --------------------------------------------------------------------------------------------------------------------------------
def test_api_serves_snapshot_history_and_commands(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=False, providers={}, alert_loop=False, deriv_client=Fake(fail={"okx"}))) as c:
        d = c.get("/api/derivatives/btc").json()["data"]
        assert [r["venue"] for r in d["venues"]] == list(V.VENUES) and d["aggregate"]["venues_ok"] == 3 and any("Liquidations, ETF flows" in n for n in d["notes"])
        assert c.get("/api/derivatives/btc/history", params={"hours": 24}).json()["data"]["hours"] == 24
        for text in ("BTC OI", "BTC FUNDING"):
            r = c.post("/api/command", json={"text": text}).json()["data"]
            assert r["view"] == "btc" and r["implemented"] is True and "derivatives" not in (r["message"] or "")


def test_api_demo_mode(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "dd.db"), demo=True, alert_loop=False)) as c:
        d = c.get("/api/derivatives/btc").json()["data"]
        assert d["demo"] is True and all(r["status"] == "DEMO" for r in d["venues"])
