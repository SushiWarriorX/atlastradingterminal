"""Provider health check: separate connectivity / structure / freshness / quality, strictly read-only, bounded, localhost-protected."""
import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import health_check as H
from atlas_api import instruments as I
from atlas_api.app import create_app
from atlas_api.db import DB
from atlas_api.derivatives import venues as V
from atlas_api.derivatives.service import DerivativesService
from atlas_api.models import Provenance, ProviderUnavailable, Quote
from atlas_api.news.service import NewsService
from atlas_api.service import MarketService

from test_derivatives import BN_O, BN_P, BY, HL, NOW_MS, OK_F, OK_I, OK_M, OK_O
from test_ibkr_data import FakeMD, FakeYahoo, broker, tick
from test_ibkr_data import svc_with as ibkr_svc

SPY = I.by_symbol("SPY")


@pytest.fixture(autouse=True)
def regular_session(monkeypatch):
    monkeypatch.setattr("atlas_api.service.session_state", lambda now=None: {"state": "REGULAR"})


def run(c):
    return asyncio.run(c)


def now():
    return datetime.now(timezone.utc)


def q(price=100.0, age=0, delay=0, **kw):
    t = now() - timedelta(seconds=age)
    return Quote(instrument_id="X", price=price, prov=Provenance(provider="coinbase", instrument_id="X", event_time=t, ingested_time=t, delay_seconds=delay), **kw)


class FakeQuoteProvider:
    entitlement, delay_seconds, native_intervals = "fake", 0, {"1d"}

    def __init__(self, name="coinbase", quote=None, exc=None, sleep=0.0):
        self.name, self._q, self.exc, self.sleep, self.calls, self.cancelled = name, quote, exc, sleep, 0, False

    async def quote(self, inst):
        self.calls += 1
        try:
            if self.sleep:
                await asyncio.sleep(self.sleep)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.exc:
            raise self.exc
        out = self._q.model_copy(deep=True)
        out.prov.provider = self.name
        return out


def probe(provider, key="coinbase"):
    svc = MarketService({key: provider})
    return run(H.probe_quote(svc, key, "Label", "crypto", provider, I.by_symbol("BTC"))), svc


# --- the four separate questions -----------------------------------------------------------------------------------------------------
def test_healthy_quote_passes_all_four_checks():
    r, _ = probe(FakeQuoteProvider(quote=q()))
    assert (r["connectivity"], r["structure"], r["quality"], r["freshness"], r["state"]) == ("pass", "pass", "pass", "LIVE", "OK")
    assert r["observed_at"] and r["age_seconds"] is not None and r["request_budget"] == 2


@pytest.mark.parametrize("bad", [0.0, -5.0, float("nan"), float("inf")])
def test_a_successful_response_with_an_invalid_price_is_not_ok(bad):
    r, _ = probe(FakeQuoteProvider(quote=q(price=bad)))
    assert r["connectivity"] == "pass" and r["quality"] == "fail" and r["state"] == "INVALID" and any("price" in i for i in r["issues"])


def test_other_invalid_fields_are_listed():
    r, _ = probe(FakeQuoteProvider(quote=q(bid=101.0, ask=100.0, volume=-1.0, high=1.0, low=2.0)))
    text = " ".join(r["issues"])
    assert r["state"] == "INVALID" and "crossed" in text and "volume" in text and "high is below low" in text


def test_future_and_missing_timestamps_are_quality_failures():
    assert "future" in " ".join(probe(FakeQuoteProvider(quote=q(age=-3600)))[0]["issues"])
    nots = q()
    nots.prov.event_time = None
    r, _ = probe(FakeQuoteProvider(quote=nots))
    assert any("timestamp" in i for i in r["issues"]) and r["quality"] == "fail"


def test_old_crypto_data_is_reachable_and_valid_but_stale():
    r, _ = probe(FakeQuoteProvider(quote=q(age=600)))
    assert (r["connectivity"], r["structure"], r["quality"]) == ("pass", "pass", "pass") and r["freshness"] == "STALE" and r["state"] == "STALE" and r["action"]


def test_connectivity_failure_vs_structure_failure():
    c, _ = probe(FakeQuoteProvider(exc=ProviderUnavailable("coinbase", "HTTP 503")))
    assert c["connectivity"] == "fail" and c["state"] == "UNAVAILABLE" and c["action"]
    s, _ = probe(FakeQuoteProvider(exc=ProviderUnavailable("coinbase", "KeyError: 'price'")))
    assert s["connectivity"] == "pass" and s["structure"] == "fail" and s["state"] == "INVALID" and "format" in s["action"]


def test_403_and_429_get_specific_actions():
    assert "network or region" in probe(FakeQuoteProvider(exc=ProviderUnavailable("c", "HTTP 403")))[0]["action"]
    assert "Rate limited" in probe(FakeQuoteProvider(exc=ProviderUnavailable("c", "HTTP 429")))[0]["action"]


def test_urls_and_secrets_never_reach_the_output():
    r, _ = probe(FakeQuoteProvider(exc=ProviderUnavailable("c", "GET https://api.example.com/x?apikey=SECRET123 failed")))
    assert "SECRET123" not in str(r) and "https://" not in str(r)


def test_extended_hours_yahoo_is_historical_not_stale(monkeypatch):
    monkeypatch.setattr("atlas_api.service.session_state", lambda now=None: {"state": "PREMARKET"})
    p = FakeQuoteProvider("yahoo", q(age=40 * 3600, delay=900))
    svc = MarketService({"yahoo": p})
    r = run(H.probe_quote(svc, "yahoo", "Yahoo", "equities", p, SPY))
    assert r["freshness"] == "HISTORICAL" and r["state"] == "OK"


# --- timeouts: a slow probe is cancelled, not left running -----------------------------------------------------------------------------
def test_timed_out_probe_is_cancelled(monkeypatch):
    monkeypatch.setattr(H, "PROBE_TIMEOUT", 0.05)
    p = FakeQuoteProvider(quote=q(), sleep=5)
    out = run(H.run_checks(svc=MarketService({"coinbase": p}), provs={"coinbase": p}, ibkr_md=None, broker=None, derivs=_derivs(), news=_news(), demo=False))
    r = next(x for x in out["rows"] if x["provider"] == "coinbase")
    assert r["state"] == "UNAVAILABLE" and r["error"] == "timed out" and p.cancelled


# --- derivatives -----------------------------------------------------------------------------------------------------------------------
class FakeVenues:
    def __init__(self, recs=None, errs=None):
        self.recs, self.errs, self.fetched = recs or {}, errs or {}, []

    async def fetch(self, venue):
        self.fetched.append(venue)
        if venue in self.errs:
            raise self.errs[venue]
        return self.recs[venue]


def rec(**kw):
    base = {"venue": "x", "mark": 67000.0, "index": 66990.0, "funding_rate": 0.0001, "funding_interval_h": 8.0, "oi_btc": 5000.0, "ts_ms": int(time.time() * 1000), "notes": []}
    return {**base, **kw}


def _derivs(client=None, tmp="/tmp/hc_d.db"):
    return DerivativesService(DB(tmp + str(time.time_ns())), client or FakeVenues(recs={v: rec() for v in V.VENUES}))


def test_venue_good_bad_stale_and_shape():
    d = _derivs(FakeVenues(recs={"hyperliquid": rec(), "binance": rec(mark=-1.0, funding_rate=0.9, oi_btc=0), "bybit": rec(ts_ms=int((time.time() - 3600) * 1000)), "okx": rec(funding_interval_h=3.0)},
                           errs={}))
    ok = run(H.probe_venue(d, "hyperliquid"))
    assert ok["state"] == "OK" and ok["freshness"] == "LIVE" and ok["quality"] == "pass"
    bad = run(H.probe_venue(d, "binance"))
    assert bad["state"] == "INVALID" and bad["connectivity"] == "pass" and len(bad["issues"]) == 3
    assert run(H.probe_venue(d, "bybit"))["state"] == "STALE"
    assert "interval" in " ".join(run(H.probe_venue(d, "okx"))["issues"])


def test_venue_errors_map_to_connectivity_or_structure():
    d = _derivs(FakeVenues(errs={"binance": V.VenueError("blocked", "the exchange refused the connection (HTTP 451)"), "okx": V.VenueError("shape", "OKX field missing: oi"),
                                 "bybit": V.VenueError("timeout", "timed out")}))
    b = run(H.probe_venue(d, "binance"))
    assert b["state"] == "UNAVAILABLE" and b["connectivity"] == "fail" and "network or region" in b["action"]
    o = run(H.probe_venue(d, "okx"))
    assert o["state"] == "INVALID" and o["connectivity"] == "pass" and o["structure"] == "fail"
    assert run(H.probe_venue(d, "bybit"))["connectivity"] == "fail"


def test_venue_probe_writes_no_history_and_uses_fetch_only():
    fv = FakeVenues(recs={v: rec() for v in V.VENUES})
    d = _derivs(fv)
    for v in V.VENUES:
        run(H.probe_venue(d, v))
    assert d.db.q("SELECT COUNT(*) FROM deriv_history")[0][0] == 0 and fv.fetched == list(V.VENUES)


def test_real_venue_client_request_counts_stay_within_budget():
    seen: list[str] = []

    def handler(req):
        u = str(req.url)
        seen.append(u)
        if "hyperliquid" in u:
            return httpx.Response(200, json=HL)
        if "binance" in u:
            return httpx.Response(200, json=BN_O if "openInterest" in u else BN_P)
        if "bybit" in u:
            return httpx.Response(200, json=BY)
        return httpx.Response(200, json={"funding-rate": OK_F, "open-interest": OK_O, "mark-price": OK_M, "index-tickers": OK_I}[u.split("?")[0].rsplit("/", 1)[1]])
    d = _derivs(V.VenueClient(httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    for v in V.VENUES:
        before = len(seen)
        r = run(H.probe_venue(d, v))
        assert len(seen) - before <= H.BUDGET[v], v
        assert r["connectivity"] == "pass" and r["structure"] == "pass"


# --- RSS: read-only ---------------------------------------------------------------------------------------------------------------------
def rss(age_h=1, title="Fed holds rates"):
    t = (now() - timedelta(hours=age_h)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><item><title>{title}</title><link>https://x.test/a</link><pubDate>{t}</pubDate><guid>g{age_h}{title}</guid></item></channel></rss>'.encode()


def _news(handler=None, tmp="/tmp/hc_n.db"):
    h = handler or (lambda req: httpx.Response(200, content=rss()))
    return NewsService(DB(tmp + str(time.time_ns())), httpx.AsyncClient(transport=httpx.MockTransport(h), follow_redirects=True))


def dump(db):
    return {t: db.q(f"SELECT * FROM {t}") for t in [r[0] for r in db.q("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]}


def test_rss_good_partial_total_failure_and_stale():
    assert run(H.probe_rss(_news()))["state"] == "OK"
    fail_one = lambda req: httpx.Response(500) if "cnbc" in str(req.url) else httpx.Response(200, content=rss())      # noqa: E731
    n = _news(fail_one)
    r = run(H.probe_rss(n))
    assert r["state"] == "DEGRADED" and r["issues"] and r["action"]
    r = run(H.probe_rss(_news(lambda req: httpx.Response(503))))
    assert r["state"] == "UNAVAILABLE" and r["connectivity"] == "fail"
    r = run(H.probe_rss(_news(lambda req: httpx.Response(200, content=rss(age_h=200)))))
    assert r["state"] == "STALE" and r["freshness"] == "STALE"
    r = run(H.probe_rss(_news(lambda req: httpx.Response(200, content=b"<html>not a feed</html>"))))
    assert r["connectivity"] == "pass" and r["structure"] == "fail" and r["state"] == "INVALID"


def test_rss_with_no_enabled_feed_is_not_configured():
    n = _news()
    n.db.x("UPDATE news_feeds SET enabled=0 WHERE kind='rss'")
    assert run(H.probe_rss(n))["state"] == "NOT_CONFIGURED"


def test_rss_probe_writes_nothing_and_respects_feed_cap():
    calls = []
    n = _news(lambda req: (calls.append(1), httpx.Response(200, content=rss()))[1])
    before = dump(n.db)
    run(H.probe_rss(n))
    assert dump(n.db) == before and len(calls) <= H.MAX_FEEDS_CHECKED


# --- IBKR ---------------------------------------------------------------------------------------------------------------------------------
def test_ibkr_not_configured_vs_not_connected_vs_live():
    common = dict(svc=MarketService({}), provs={}, broker=None, derivs=_derivs(), news=_news(), demo=False)
    off = next(r for r in run(H.run_checks(ibkr_md=None, **common))["rows"] if r["provider"] == "ibkr")
    assert off["state"] == "NOT_CONFIGURED"
    s, _, md = ibkr_svc(FakeMD(), connected=False)
    dis = next(r for r in run(H.run_checks(ibkr_md=md, **{**common, "svc": s}))["rows"] if r["provider"] == "ibkr")
    assert dis["state"] == "UNAVAILABLE" and "Connect" in dis["action"] and dis["request_budget"] == 0
    ib = FakeMD(live=tick(last=500.0, bid=499.9, ask=500.1, time=datetime.now(timezone.utc)))
    s, _, md = ibkr_svc(ib)
    r = next(r for r in run(H.run_checks(ibkr_md=md, **{**common, "svc": s}))["rows"] if r["provider"] == "ibkr")
    assert r["state"] == "OK" and r["freshness"] == "LIVE"
    assert [x["snapshot"] for x in ib.requests] == [True] and not hasattr(ib, "placeOrder")          # one read-only snapshot, no order API touched


def test_ibkr_delayed_is_reported_delayed():
    ib = FakeMD(live=tick(), delayed=tick(delayedLast=500.0, time=datetime.now(timezone.utc)))
    s, _, md = ibkr_svc(ib)
    r = run(H.probe_quote(s, "ibkr", "IBKR", "equities", md, SPY))
    assert r["freshness"] == "DELAYED" and r["state"] == "OK"


# --- demo / not configured / nothing modified ---------------------------------------------------------------------------------------------
def test_demo_mode_makes_no_calls_and_is_labelled_demo():
    p = FakeQuoteProvider(exc=AssertionError("must not be called"))
    fv = FakeVenues(errs={v: AssertionError("no") for v in V.VENUES})
    out = run(H.run_checks(svc=MarketService({}), provs={"coinbase": p}, ibkr_md=None, broker=None, derivs=_derivs(fv), news=_news(lambda r: 1 / 0), demo=True))
    states = {r["provider"]: r["state"] for r in out["rows"]}
    assert states["ibkr"] == "NOT_CONFIGURED" and {v for k, v in states.items() if k != "ibkr"} == {"DEMO"} and p.calls == 0 and fv.fetched == [] and out["max_outbound_requests"] == 0


def test_missing_provider_is_not_configured():
    out = run(H.run_checks(svc=MarketService({}), provs={}, ibkr_md=None, broker=None, derivs=_derivs(), news=_news(), demo=False))
    assert {r["provider"]: r["state"] for r in out["rows"]}["coinbase"] == "NOT_CONFIGURED"


def test_full_run_does_not_modify_database_cache_or_counters():
    good = {"coinbase": FakeQuoteProvider("coinbase", q()), "yahoo": FakeQuoteProvider("yahoo", q(delay=900)), "fred": FakeQuoteProvider("fred", q(age=86400 * 3))}
    svc = MarketService(good)
    d, n = _derivs(), _news()
    snap_d, snap_n = dump(d.db), dump(n.db)
    health_before = {k: dict(v) for k, v in svc.health.items()}
    out = run(H.run_checks(svc=svc, provs=good, ibkr_md=None, broker=None, derivs=d, news=n, demo=False))
    assert dump(d.db) == snap_d and dump(n.db) == snap_n and svc.health == health_before and svc._cache == {}
    assert len(out["rows"]) == 9 and out["max_outbound_requests"] == sum(r["request_budget"] for r in out["rows"]) <= 22
    assert {r["provider"] for r in out["rows"]} == {"coinbase", "yahoo", "ibkr", "fred", "hyperliquid", "binance", "bybit", "okx", "rss"}


def test_concurrency_is_bounded():
    active, peak = 0, 0

    class Slow(FakeQuoteProvider):
        async def quote(self, inst):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1
            return self._q.model_copy(deep=True)
    provs = {k: Slow(k, q()) for k in ("coinbase", "yahoo", "fred")}

    class SlowVenues(FakeVenues):
        async def fetch(self, venue):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1
            return rec()
    run(H.run_checks(svc=MarketService(provs), provs=provs, ibkr_md=None, broker=None, derivs=_derivs(SlowVenues()), news=_news(), demo=False))
    assert peak <= H.CONCURRENCY


# --- the API: localhost-only, cross-origin / DNS-rebinding protection, cooldown -----------------------------------------------------------------
HDR = {"X-Atlas-Request": "health-check"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    provs = {"coinbase": FakeQuoteProvider("coinbase", q()), "yahoo": FakeQuoteProvider("yahoo", q(delay=900)), "fred": FakeQuoteProvider("fred", q())}
    fv = FakeVenues(recs={v: rec() for v in V.VENUES})
    net = lambda req: httpx.Response(200, content=rss())      # noqa: E731
    app = create_app(db_path=str(tmp_path / "h.db"), demo=False, providers=provs, alert_loop=False, deriv_client=fv, news_client=httpx.AsyncClient(transport=httpx.MockTransport(net)))
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


def test_post_requires_marker_header(api):
    r = api.post("/api/health/check")
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN_ORIGIN"


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "192.168.1.5:8000", "localhost.evil.example"])
def test_dns_rebinding_host_is_refused(api, host):
    r = api.post("/api/health/check", headers={**HDR, "Host": host})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN_HOST"


def test_foreign_origin_and_cross_site_are_refused(api):
    assert api.post("/api/health/check", headers={**HDR, "Origin": "https://evil.example"}).status_code == 403
    assert api.post("/api/health/check", headers={**HDR, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert api.get("/api/health/check", headers={"Origin": "https://evil.example"}).status_code == 403
    assert api.get("/api/health/check", headers={"Host": "evil.example"}).status_code == 403


def test_local_app_request_runs_then_cooldown_then_allows_again(api, monkeypatch):
    good = {**HDR, "Origin": "http://localhost:5173"}
    r = api.post("/api/health/check", headers=good)
    assert r.status_code == 200
    d = r.json()["data"]
    assert len(d["last"]["rows"]) == 9 and d["cooldown_left"] > 0 and d["last"]["cooldown_seconds"] == 30
    again = api.post("/api/health/check", headers=good)
    assert again.status_code == 429 and again.json()["error"]["code"] == "COOLDOWN"
    last = api.get("/api/health/check").json()["data"]
    assert last["last"]["checked_at"] == d["last"]["checked_at"] and last["running"] is False
    monkeypatch.setattr(H, "COOLDOWN", 0.0)
    assert api.post("/api/health/check", headers=good).status_code == 200


def test_get_before_any_run_has_no_result_and_makes_no_network_call(api):
    assert api.get("/api/health/check").json()["data"]["last"] is None


def test_response_contains_no_secrets_or_urls(api):
    text = api.post("/api/health/check", headers=HDR).text
    assert "http://" not in text and "https://" not in text and "apikey" not in text.lower()


def test_demo_api_reports_demo_rows(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "dm.db"), demo=True, alert_loop=False), base_url="http://localhost:8000") as c:
        d = c.post("/api/health/check", headers=HDR).json()["data"]["last"]
        assert d["demo"] and {r["state"] for r in d["rows"]} == {"DEMO", "NOT_CONFIGURED"} and d["max_outbound_requests"] == 0
