import httpx
import pytest

from atlas_api import instruments as I
from atlas_api.models import DataStatus, ProviderUnavailable
from atlas_api.providers.coinbase import CoinbaseProvider
from atlas_api.providers.fred import FredProvider
from atlas_api.providers.http import Http
from atlas_api.service import MarketService


def test_catalog_search_and_ids():
    assert I.search("btc")[0].id == "CRYPTO:COINBASE:BTC-USD:SPOT"
    assert I.search("apple")[0].symbol == "AAPL" and I.search("AAPL")[0].id == "EQUITY:NASDAQ:AAPL"
    assert I.get("ETF:ARCA:SPY").exchange == "ARCA"
    ad = I.search("ZZZZ")[0]
    assert ad.exchange == "UNVERIFIED" and ad.id == "EQUITY:US:ZZZZ"  # uncatalogued tickers are flagged, not trusted
    assert I.search("") == []


async def test_demo_is_labeled_and_derives_intervals(demo_service):
    inst = I.by_symbol("BTC")
    q = await demo_service.quote(inst)
    assert q.prov.status == DataStatus.DEMO and q.prov.provider == "demo"
    o = await demo_service.ohlcv(inst, "4h", 40)
    assert o.derived_from == "1h" and o.interval == "4h" and all(c.time % 14400 == 0 for c in o.candles)
    with pytest.raises(ProviderUnavailable):
        await demo_service.ohlcv(inst, "1M", 10)


async def test_missing_provider_is_unavailable_not_synthetic():
    svc = MarketService({}, demo=False)
    with pytest.raises(ProviderUnavailable):
        await svc.quote(I.by_symbol("AAPL"))


def mock_http(handler, provider):
    return Http("https://x.test", provider, min_interval=0, retries=2, client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://x.test"))


async def test_coinbase_parsing_and_live_status():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def h(req):
        if req.url.path.endswith("/ticker"):
            return httpx.Response(200, json={"price": "100.5", "bid": "100.4", "ask": "100.6", "time": now})
        return httpx.Response(200, json={"open": "98", "high": "101", "low": "97", "volume": "1234.5"})

    svc = MarketService({"coinbase": CoinbaseProvider(mock_http(h, "coinbase"))})
    q = await svc.quote(I.by_symbol("BTC"))
    assert q.prov.status == DataStatus.LIVE and q.prov.venue == "COINBASE"
    assert q.spread == pytest.approx(0.2) and q.change_pct == pytest.approx(2.551, abs=1e-3)
    assert "vwap" in q.unsupported_fields and q.prev_close_basis == "24h rolling open"
    assert svc.health["coinbase"]["ok"] == 1


async def test_http_retries_then_reports_unavailable_and_health():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(503)

    svc = MarketService({"coinbase": CoinbaseProvider(mock_http(h, "coinbase"))})
    with pytest.raises(ProviderUnavailable):
        await svc.quote(I.by_symbol("BTC"))
    assert len(calls) >= 2  # retried
    assert svc.health["coinbase"]["consecutive_failures"] == 1 and svc.health["coinbase"]["last_error"]


async def test_fred_skips_missing_observations():
    csv = "observation_date,DGS10\n2026-03-05,4.10\n2026-03-06,.\n2026-03-09,4.20\n"
    svc = MarketService({"fred": FredProvider(mock_http(lambda r: httpx.Response(200, text=csv), "fred"))})
    q = await svc.quote(I.by_symbol("US10Y"))
    assert q.price == 4.20 and q.prev_close == 4.10 and q.prov.status == DataStatus.HISTORICAL


def test_db_migrations_and_prefs(db):
    assert db.migrate() == []  # idempotent
    db.pref_set("theme", "dark")
    assert db.pref_get("theme") == "dark" and db.pref_get("missing", 5) == 5


async def test_ohlcv_freshness_uses_bar_close_not_bar_open():
    """A forming 1h bar that opened 40 min ago is fresh data, not 40-minute-old data."""
    import time

    from atlas_api.models import Candle

    now = int(time.time())

    class P:
        name, entitlement, delay_seconds, native_intervals = "coinbase", "test", 0, {"1h", "1d"}

        def __init__(self, last_open):
            self.last_open = last_open

        async def ohlcv(self, inst, interval, limit):
            from datetime import datetime, timezone

            from atlas_api.models import OHLCV, Provenance

            c = [Candle(time=self.last_open, open=1, high=1, low=1, close=1)]
            return OHLCV(instrument_id=inst.id, interval=interval, candles=c, prov=Provenance(
                provider="coinbase", instrument_id=inst.id, event_time=datetime.fromtimestamp(self.last_open, timezone.utc),
                ingested_time=datetime.now(timezone.utc)))

    btc = I.by_symbol("BTC")
    forming = await MarketService({"coinbase": P(now - 2400)}).ohlcv(btc, "1h", 1)        # opened 40 min ago, still forming
    assert forming.prov.status == DataStatus.LIVE
    gap = await MarketService({"coinbase": P(now - 3 * 3600)}).ohlcv(btc, "1h", 1)        # last bar closed 2h ago: provider is behind
    assert gap.prov.status == DataStatus.STALE
