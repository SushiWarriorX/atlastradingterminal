"""Regression tests: extended-hours status, date-aligned relative strength, request sharing, IBKR/Yahoo behaviour unchanged."""
import asyncio
from datetime import datetime, timezone

import pytest

from atlas_api import instruments as I
from atlas_api.models import Candle, DataStatus, OHLCV, Provenance, ProviderUnavailable, Quote
from atlas_api.scanner import features as feat
from atlas_api.service import MarketService
from atlas_api.status import classify

from test_ibkr_data import FakeMD, FakeYahoo, run, svc_with, tick

@pytest.fixture(autouse=True)
def regular_session(monkeypatch):
    monkeypatch.setattr("atlas_api.service.session_state", lambda now=None: {"state": "REGULAR"})


AAPL = I.by_symbol("AAPL")
DAY = 86400
NOW = datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc)          # 08:00 New York: pre-market
LAST_CLOSE = datetime(2026, 3, 6, 21, 0, tzinfo=timezone.utc)   # Friday's close, ~63h earlier


def cls(**k):
    base = dict(provider="yahoo", asset_class="equity", event_time=LAST_CLOSE, now=NOW, delay_seconds=900, session="PREMARKET",
                regular_hours_only=True)
    return classify(**{**base, **k})


# --- 1. extended-hours status ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("session", ["PREMARKET", "AFTER_HOURS"])
def test_regular_hours_only_provider_is_historical_not_stale_in_extended_hours(session):
    status, notes = cls(session=session)
    assert status == DataStatus.HISTORICAL and "regular-session" in notes[0]


def test_old_data_in_the_regular_session_is_still_stale():
    assert cls(session="REGULAR")[0] == DataStatus.STALE


def test_a_provider_that_serves_extended_hours_is_not_relabelled():
    assert cls(regular_hours_only=False)[0] == DataStatus.STALE                                   # unchanged behaviour
    fresh = cls(regular_hours_only=False, event_time=NOW, delay_seconds=0)[0]
    assert fresh == DataStatus.LIVE


def test_crypto_staleness_is_unaffected():
    assert cls(asset_class="crypto", delay_seconds=0, session=None)[0] == DataStatus.STALE


def test_service_marks_yahoo_quote_and_bars_historical_in_premarket(monkeypatch):
    monkeypatch.setattr("atlas_api.service.session_state", lambda now=None: {"state": "PREMARKET"})
    y = FakeYahoo()
    old = datetime.now(timezone.utc).replace(year=2025)

    async def q(inst):
        return Quote(instrument_id=inst.id, price=1.0, prov=Provenance(provider="yahoo", instrument_id=inst.id, event_time=old,
                                                                         ingested_time=old, delay_seconds=900))
    y.quote = q
    s = MarketService({"yahoo": y})
    assert run(s.quote(AAPL)).prov.status == DataStatus.HISTORICAL
    assert run(s.ohlcv(AAPL, "1d", 3)).prov.status == DataStatus.HISTORICAL


# --- 2. date-aligned relative strength -------------------------------------------------------------------------------------------------
T0 = 1_700_000_000 - 1_700_000_000 % DAY


def bars(closes, days=None):
    days = days if days is not None else range(len(closes))
    return [Candle(time=T0 + d * DAY, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1e6) for d, c in zip(days, closes)]


def rs5(stock, bench):
    return feat.compute("X", stock, bench)["rs_5d"]


def test_rs_matches_dates():
    stock = bars([100.0] * 94 + [100, 100, 100, 100, 100, 110])             # +10% over last 5 bars
    bench = bars([100.0] * 100)
    assert rs5(stock, bench) == pytest.approx(10.0)


def test_rs_is_unavailable_when_the_benchmark_lacks_a_matching_date():
    stock = bars([100.0] * 99 + [110.0])
    bench = bars([100.0] * 99, days=range(99))                              # benchmark is one day behind the stock
    assert rs5(stock, bench) is None
    gap = list(range(100)); gap.remove(94)                                  # benchmark missing the window's start date
    assert rs5(bars([100.0] * 99 + [110.0]), bars([100.0] * 99, days=gap)) is None


def test_old_position_based_result_would_have_been_wrong():
    # Stock has a missing day inside the window; positions would line up different dates.
    sdays = [d for d in range(101) if d != 97]
    stock = bars([100.0] * 99 + [110.0], days=sdays[-100:])
    bench = bars([100.0 + d for d in range(101)])                           # benchmark rises 1/day
    out = feat.compute("X", stock, bench)["rs_5d"]
    end, start = sdays[-1], sdays[-6]
    expected = 10.0 - ((100 + end) / (100 + start) - 1) * 100
    assert out == pytest.approx(expected)


def test_rs_still_none_without_benchmark():
    assert feat.compute("X", bars([100.0] * 100), None)["rs_5d"] is None


# --- 3. request sharing ---------------------------------------------------------------------------------------------
class Counting:
    name = "yahoo"
    entitlement = "x"
    delay_seconds = 900
    native_intervals = {"1d"}

    def __init__(self, fail=False):
        self.n, self.fail = 0, fail

    async def quote(self, inst):
        self.n += 1
        await asyncio.sleep(0.05)
        if self.fail:
            raise ProviderUnavailable("yahoo", "down")
        now = datetime.now(timezone.utc)
        return Quote(instrument_id=inst.id, price=1.0, prov=Provenance(provider="yahoo", instrument_id=inst.id, event_time=now,
                                                                         ingested_time=now, delay_seconds=900))


async def test_simultaneous_identical_quotes_make_one_provider_call():
    p = Counting()
    s = MarketService({"yahoo": p})
    res = await asyncio.gather(*[s.quote(AAPL) for _ in range(6)])
    assert p.n == 1 and len({id(r) for r in res}) == 6          # one fetch, but each caller gets its own copy
    await s.quote(AAPL)
    assert p.n == 1                                             # still inside the TTL


async def test_different_symbols_are_not_merged():
    p = Counting()
    s = MarketService({"yahoo": p})
    await asyncio.gather(s.quote(AAPL), s.quote(I.by_symbol("SPY")))
    assert p.n == 2


async def test_failures_are_shared_between_simultaneous_callers_but_not_cached():
    p = Counting(fail=True)
    s = MarketService({"yahoo": p})
    r = await asyncio.gather(*[s.quote(AAPL) for _ in range(4)], return_exceptions=True)
    assert p.n == 1 and all(isinstance(x, ProviderUnavailable) for x in r)
    p.fail = False
    assert (await s.quote(AAPL)).price == 1.0 and p.n == 2       # recovery is immediate


async def test_a_cancelled_caller_does_not_break_the_shared_fetch():
    p = Counting()
    s = MarketService({"yahoo": p})
    t1 = asyncio.ensure_future(s.quote(AAPL))
    t2 = asyncio.ensure_future(s.quote(AAPL))
    await asyncio.sleep(0.01)
    t1.cancel()
    assert (await t2).price == 1.0 and p.n == 1


async def test_expired_cache_entries_are_evicted():
    s = MarketService({"yahoo": Counting()})
    for i in range(300):
        s._cache[("x", i)] = (0.0, i)
    await s.quote(AAPL)
    assert len(s._cache) < 10


# --- 4. IBKR live/delayed and Yahoo fallback unchanged -------------------------------------------------------------------------------
def test_ibkr_live_stays_live_and_delayed_stays_delayed_in_regular_hours():
    live = svc_with(FakeMD(live=tick(last=190.0, time=datetime.now(timezone.utc))))[0]
    q = run(live.quote(AAPL))
    assert q.prov.provider == "ibkr" and q.prov.status == DataStatus.LIVE
    dl = svc_with(FakeMD(live=tick(), delayed=tick(delayedLast=189.5, time=datetime.now(timezone.utc))))[0]
    q = run(dl.quote(AAPL))
    assert q.prov.provider == "ibkr" and q.prov.status == DataStatus.DELAYED and q.prov.delay_seconds == 900


def test_ibkr_quote_in_premarket_is_not_relabelled_historical(monkeypatch):
    monkeypatch.setattr("atlas_api.service.session_state", lambda now=None: {"state": "PREMARKET"})
    s = svc_with(FakeMD(live=tick(last=190.0, time=datetime.now(timezone.utc))))[0]
    assert run(s.quote(AAPL)).prov.status == DataStatus.LIVE      # a real-time extended-hours price keeps its label


def test_yahoo_fallback_still_happens_with_visible_note():
    s, y, _ = svc_with(FakeMD(live=tick(), delayed=tick()))
    q = run(s.quote(AAPL))
    assert q.prov.provider == "yahoo" and any("preferred provider unavailable" in x for x in q.prov.quality)
    assert s.health["ibkr"]["fail"] == 1 and s.health["yahoo"]["ok"] == 1
