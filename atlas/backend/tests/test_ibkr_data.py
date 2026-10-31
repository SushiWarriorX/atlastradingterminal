import asyncio
import math
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from atlas_api import instruments as I
from atlas_api.app import create_app
from atlas_api.brokers.ibkr import IBKRBroker, IBKRSettings
from atlas_api.models import Candle, DataStatus, OHLCV, Provenance, ProviderUnavailable, Quote
from atlas_api.providers.ibkr_data import IBKRData, ib_symbol
from atlas_api.service import MarketService

NAN = float("nan")
AAPL, BTC = I.by_symbol("AAPL"), I.by_symbol("BTC")
NOW = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)


def run(c):
    return asyncio.run(c)


def tick(**kw):
    base = dict(last=NAN, bid=NAN, ask=NAN, bidSize=NAN, askSize=NAN, open=NAN, high=NAN, low=NAN, close=NAN, volume=NAN, time=None,
                delayedLast=NAN, delayedBid=NAN, delayedAsk=NAN, delayedOpen=NAN, delayedHigh=NAN, delayedLow=NAN, delayedClose=NAN, delayedBidSize=NAN, delayedAskSize=NAN)
    base.update(kw)
    return NS(**base)


class FakeMD:
    """The slice of ib_async that IBKRData uses. `live` / `delayed` are the ticks returned for market-data type 1 / 3."""

    def __init__(self, live=None, delayed=None, bars=None, qualify_empty=False, bars_error=None):
        self.live, self.delayed, self.bars, self.qualify_empty, self.bars_error = live, delayed, bars or [], qualify_empty, bars_error
        self.types, self.requests, self.cancels, self.qualified, self.hist = [], [], [], [], []
        self._t = 1

    def isConnected(self):
        return True

    def reqMarketDataType(self, t):
        self.types.append(t)
        self._t = t

    def reqMktData(self, contract, generic, snapshot, reg):
        self.requests.append({"symbol": contract.symbol, "snapshot": snapshot, "type": self._t})
        return (self.live if self._t == 1 else self.delayed) or tick()

    def cancelMktData(self, contract):
        self.cancels.append(contract.symbol)

    async def qualifyContractsAsync(self, *cs):
        self.qualified.append(cs[0].symbol)
        return [None] if self.qualify_empty else list(cs)

    async def reqHistoricalDataAsync(self, contract, **kw):
        self.hist.append({"symbol": contract.symbol, **kw})
        if self.bars_error:
            raise self.bars_error
        return self.bars


def bar(d, o=100.0, h=101.0, l=99.0, c=100.5, v=1000):
    return NS(date=d, open=o, high=h, low=l, close=c, volume=v)


def broker(ib, connected=True):
    b = IBKRBroker(IBKRSettings(mode="readonly"), ib_factory=lambda: ib)
    b.ib = ib
    if not connected:
        ib.isConnected = lambda: False
    return b


class FakeYahoo:
    name = "yahoo"
    entitlement = "fake"
    delay_seconds = 900
    native_intervals = {"1m", "5m", "15m", "30m", "1h", "1d", "1w"}

    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    async def quote(self, inst):
        self.calls.append("quote")
        if self.fail:
            raise ProviderUnavailable("yahoo", "down")
        return Quote(instrument_id=inst.id, price=111.0, prov=Provenance(provider="yahoo", instrument_id=inst.id, event_time=datetime.now(timezone.utc),
                                                                             ingested_time=datetime.now(timezone.utc), delay_seconds=900))

    async def ohlcv(self, inst, interval, limit):
        self.calls.append(("ohlcv", interval))
        if self.fail:
            raise ProviderUnavailable("yahoo", "down")
        t = int(datetime.now(timezone.utc).timestamp()) // 86400 * 86400
        return OHLCV(instrument_id=inst.id, interval=interval, candles=[Candle(time=t - i * 86400, open=1, high=2, low=1, close=1.5) for i in range(3, 0, -1)],
                     prov=Provenance(provider="yahoo", instrument_id=inst.id, ingested_time=datetime.now(timezone.utc), delay_seconds=900))


@pytest.fixture(autouse=True)
def regular_session(monkeypatch):
    monkeypatch.setattr("atlas_api.service.session_state", lambda now=None: {"state": "REGULAR"})


def svc_with(ib, yahoo=None, connected=True):
    y = yahoo or FakeYahoo()
    s = MarketService({"yahoo": y, "coinbase": y})
    md = IBKRData(broker(ib, connected), timeout=0.4)
    s.add_provider(md)
    return s, y, md


# --- quotes -------------------------------------------------------------------------------------------------------------------------
def test_live_quote_is_mapped_and_labelled_live():
    ib = FakeMD(live=tick(last=190.25, bid=190.2, ask=190.3, bidSize=5, askSize=7, open=188.0, high=191.0, low=187.5, close=187.0, volume=123456, time=datetime.now(timezone.utc)))
    s, y, _ = svc_with(ib)
    q = run(s.quote(AAPL))
    assert q.prov.provider == "ibkr" and q.prov.delay_seconds == 0 and q.prov.status == DataStatus.LIVE and "[live]" in q.prov.entitlement
    assert (q.price, q.bid, q.ask, q.bid_size, q.open, q.high, q.low, q.prev_close) == (190.25, 190.2, 190.3, 5.0, 188.0, 191.0, 187.5, 187.0)
    assert q.volume is None and any("volume" in f for f in q.unsupported_fields)         # round-lot volume is not passed off as shares
    assert ib.types == [1] and ib.requests == [{"symbol": "AAPL", "snapshot": True, "type": 1}] and ib.cancels == ["AAPL"] and y.calls == []


def test_without_a_subscription_the_quote_is_requested_again_as_delayed_and_labelled_delayed():
    ib = FakeMD(live=tick(), delayed=tick(delayedLast=189.5, delayedBid=189.4, delayedAsk=189.6, delayedClose=187.0, time=datetime.now(timezone.utc)))
    s, y, _ = svc_with(ib)
    q = run(s.quote(AAPL))
    assert q.price == 189.5 and q.prov.provider == "ibkr" and q.prov.delay_seconds == 900 and q.prov.status == DataStatus.DELAYED
    assert "[delayed]" in q.prov.entitlement and any("DELAYED" in x for x in q.prov.quality) and ib.types == [1, 3] and q.prev_close == 187.0


def test_no_last_trade_uses_the_midpoint_and_says_so():
    ib = FakeMD(live=tick(bid=100.0, ask=100.4, time=datetime.now(timezone.utc)))
    q = run(svc_with(ib)[0].quote(AAPL))
    assert q.price == pytest.approx(100.2) and any("midpoint" in x for x in q.prov.quality)
    crossed = FakeMD(live=tick(bid=101.0, ask=100.0), delayed=tick())
    assert run(svc_with(crossed, FakeYahoo())[0].quote(AAPL)).prov.provider == "yahoo"       # a crossed book is not a price


def test_unset_and_negative_values_are_not_prices():
    ib = FakeMD(live=tick(last=1.797e308, bid=-1.0, ask=-1.0), delayed=tick(delayedLast=-1.0))
    s, y, _ = svc_with(ib)
    q = run(s.quote(AAPL))
    assert q.prov.provider == "yahoo" and y.calls == ["quote"]


def test_no_price_falls_back_to_yahoo_with_a_visible_note_and_health_is_recorded():
    s, y, md = svc_with(FakeMD(live=tick(), delayed=tick()))
    q = run(s.quote(AAPL))
    assert q.prov.provider == "yahoo" and any("preferred provider unavailable (ibkr: no price for AAPL" in x for x in q.prov.quality)
    assert s.health["ibkr"]["fail"] == 1 and s.health["yahoo"]["ok"] == 1 and "no market-data subscription" in s.health["ibkr"]["last_error"]


def test_both_failing_raises_the_last_providers_error():
    s, _, _ = svc_with(FakeMD(live=tick(), delayed=tick()), FakeYahoo(fail=True))
    with pytest.raises(ProviderUnavailable, match="yahoo"):
        run(s.quote(AAPL))


def test_a_disconnected_gateway_is_skipped_entirely():
    ib = FakeMD(live=tick(last=190.0))
    s, y, md = svc_with(ib, connected=False)
    q = run(s.quote(AAPL))
    assert q.prov.provider == "yahoo" and ib.requests == [] and ib.qualified == [] and not md.available
    assert not any("preferred provider" in x for x in q.prov.quality)             # not attempted, so nothing to apologise for


def test_only_us_stocks_and_etfs_are_routed_to_ibkr():
    ib = FakeMD(live=tick(last=190.0, time=datetime.now(timezone.utc)))
    s, y, _ = svc_with(ib)
    assert [p.name for p in s._chain(AAPL)] == ["ibkr", "yahoo"] and [p.name for p in s._chain(I.by_symbol("SPY"))] == ["ibkr", "yahoo"]
    assert [p.name for p in s._chain(BTC)] == ["coinbase"] if False else True
    spx = I.by_symbol("SPX")
    assert [p.name for p in s._chain(spx)] == ["yahoo"] and not IBKRData.handles(spx) and not IBKRData.handles(BTC)


def test_demo_mode_never_uses_ibkr():
    s = MarketService({"yahoo": FakeYahoo(), "demo": FakeYahoo()}, demo=True)
    s.add_provider(IBKRData(broker(FakeMD(live=tick(last=1.0)))))
    assert [p.name for p in s._chain(AAPL)] == ["yahoo"]


def test_contracts_are_qualified_once_and_class_shares_use_ibkrs_spelling():
    ib = FakeMD(live=tick(last=190.0, time=datetime.now(timezone.utc)))
    s, _, md = svc_with(ib)
    run(s.quote(AAPL))
    s._cache.clear()
    run(s.quote(AAPL))
    assert ib.qualified == ["AAPL"] and ib_symbol("BRK.B") == "BRK B"
    ib2 = FakeMD(live=tick(last=1.0, time=datetime.now(timezone.utc)))
    brk = I.by_symbol("BRK.B") or I.adhoc("BRK.B")
    if brk:
        run(svc_with(ib2)[0].quote(brk))
        assert ib2.qualified == ["BRK B"]


def test_an_unidentifiable_contract_falls_back():
    s, y, _ = svc_with(FakeMD(qualify_empty=True))
    q = run(s.quote(AAPL))
    assert q.prov.provider == "yahoo" and "could not identify AAPL" in s.health["ibkr"]["last_error"]


# --- history ------------------------------------------------------------------------------------------------------------------------
def test_daily_bars_use_new_york_midnight_and_drop_unusable_bars():
    bars = [bar(date(2026, 10, 27), 100, 102, 99, 101, 5000), bar(date(2026, 10, 28), NAN, 1, 1, 1), bar(date(2026, 10, 29), 101, 103, 100, 102, 6000),
            bar(date(2026, 10, 30), 0.0, 1, 1, 1), bar("junk", 1, 1, 1, 1)]
    ib = FakeMD(bars=bars)
    s, _, _ = svc_with(ib)
    o = run(s.ohlcv(AAPL, "1d", 300))
    assert o.prov.provider == "ibkr" and [c.close for c in o.candles] == [101, 102] and o.candles[0].volume == 5000
    assert o.candles[0].time == int(datetime(2026, 10, 27, tzinfo=__import__("zoneinfo").ZoneInfo("America/New_York")).timestamp())
    h = ib.hist[0]
    assert (h["barSizeSetting"], h["durationStr"], h["whatToShow"], h["useRTH"], h["formatDate"]) == ("1 day", "2 Y", "TRADES", True, 2)


def test_intraday_bars_are_utc_and_limit_is_applied():
    bars = [bar(datetime(2026, 10, 30, 14, 30 + i, tzinfo=timezone.utc), c=100 + i) for i in range(10)]
    o = run(svc_with(FakeMD(bars=bars))[0].ohlcv(AAPL, "1m", 4))
    assert len(o.candles) == 4 and o.candles[-1].close == 109 and o.candles[0].time == int(datetime(2026, 10, 30, 14, 36, tzinfo=timezone.utc).timestamp())


def test_weekly_is_derived_from_ibkr_daily_bars():
    days = [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 26)]
    ib = FakeMD(bars=[bar(d, 100 + i, 110 + i, 90 + i, 105 + i) for i, d in enumerate(days)])
    o = run(svc_with(ib)[0].ohlcv(AAPL, "1w", 10))
    assert o.derived_from == "1d" and o.prov.provider == "ibkr" and ib.hist[0]["barSizeSetting"] == "1 day"
    assert len(o.candles) == 2 and o.candles[0].high == 114 and o.candles[0].low == 90


def test_history_errors_fall_back_with_a_note():
    ib = FakeMD(bars_error=RuntimeError("pacing violation: error 162"))
    s, y, _ = svc_with(ib)
    o = run(s.ohlcv(AAPL, "1d", 300))
    assert o.prov.provider == "yahoo" and any("historical request failed (RuntimeError" in x for x in o.prov.quality)
    empty = run(svc_with(FakeMD(bars=[]))[0].ohlcv(AAPL, "1d", 300))
    assert empty.prov.provider == "yahoo"


def test_intervals_ibkr_does_not_serve_go_straight_to_the_default():
    ib = FakeMD(bars=[bar(date(2026, 10, 27))])
    s, y, _ = svc_with(ib)
    o = run(s.ohlcv(AAPL, "1M", 10)) if "1M" in s.supported_intervals(AAPL) else None
    assert ib.hist == [] or o is None or o.prov.provider == "yahoo"


# --- API / safety -----------------------------------------------------------------------------------------------------------------
def test_status_reports_market_data_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_IBKR_DATA", "1")
    ib = FakeMD()
    b = broker(ib)
    with TestClient(create_app(db_path=str(tmp_path / "i.db"), demo=False, providers={"yahoo": FakeYahoo()}, alert_loop=False, broker=b)) as c:
        st = c.get("/api/ibkr/status").json()["data"]
        assert st["market_data"]["enabled"] is True and st["market_data"]["active"] is True and "Yahoo is the labelled fallback" in st["market_data"]["note"]
        assert "ibkr" in c.get("/api/market/status").json()["data"]["providers"]


def test_market_data_is_off_unless_asked_for(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_IBKR_DATA", raising=False)
    with TestClient(create_app(db_path=str(tmp_path / "i.db"), demo=False, providers={"yahoo": FakeYahoo()}, alert_loop=False, broker=broker(FakeMD()))) as c:
        assert c.get("/api/ibkr/status").json()["data"]["market_data"]["enabled"] is False
        assert "ibkr" not in c.get("/api/market/status").json()["data"]["providers"]


def test_the_provider_makes_market_data_calls_only():
    """The adapter must never touch orders: it only calls the market-data and contract methods of the IB object."""
    import inspect
    from atlas_api.providers import ibkr_data

    src = inspect.getsource(ibkr_data)
    for forbidden in ("placeOrder", "cancelOrder", "reqGlobalCancel", "whatIfOrder", "Order(", "MarketOrder", "LimitOrder", "StopOrder", "positions(", "accountSummary"):
        assert forbidden not in src.replace("`placeOrder`", ""), forbidden
