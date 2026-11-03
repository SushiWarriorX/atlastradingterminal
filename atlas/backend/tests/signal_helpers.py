"""Shared fakes for the Signal tests: deterministic bars, a scriptable market provider, and stand-ins for news, fundamentals, macro and Fed Watch."""
from __future__ import annotations

import asyncio
import math
import re
import time
from datetime import datetime, timedelta, timezone

from atlas_api.fundamentals.normalize import normalize
from atlas_api.models import Candle, DataStatus, OHLCV, ProviderUnavailable, Provenance, Quote
from atlas_api.service import MarketService
from atlas_api.signal import assets as A
from atlas_api.signal.agents.common import Ctx
from atlas_api.signal.summary import MarketSummary

SEC = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400, "1w": 7 * 86400}
# words that must never appear in anything the agents write: orders, advice, price targets
ORDER_WORDS = re.compile(r"\b(buy now|sell now|you should (buy|sell)|go long|go short|price target of|take profit|stop[- ]loss|guaranteed|will (rise|fall|crash|moon|rally))\b", re.I)


def bars(interval: str, n: int, *, start: float = 100.0, drift: float = 0.002, vol: float = 1_000_000.0, now: float | None = None, age: int = 0) -> list[Candle]:
    """n candles ending at the CURRENT (still forming) bar like a real provider, with a drift and a deterministic wiggle. `age` shifts everything into the past (stale data)."""
    sec = SEC[interval]
    now = int(now if now is not None else time.time()) - age
    end = now - now % sec
    out, px = [], start
    for i in range(n):
        o = px
        c = o * (1 + drift + math.sin(i * 1.7) * 0.004)
        out.append(Candle(time=end - (n - 1 - i) * sec, open=o, high=max(o, c) * 1.003, low=min(o, c) * 0.997, close=c, volume=vol * (1 + 0.3 * math.sin(i))))
        px = c
    return out


class ScriptProvider:
    """A market provider whose behaviour each test scripts: trend, failures, status, bar counts."""
    entitlement = "test"
    delay_seconds = 900
    native_intervals = {"1m", "5m", "15m", "1h", "1d", "1w"}

    def __init__(self, *, drift: float = 0.002, status: DataStatus = DataStatus.DELAYED, fail_intervals: set[str] | None = None, fail_quote: bool = False, max_bars: int | None = None,
                 price: float | None = None, name: str = "yahoo", age: int = 0, drift_by: dict[str, float] | None = None):
        self.name, self.drift, self.status, self.fail, self.fail_quote, self.max_bars, self.price, self.age = name, drift, status, fail_intervals or set(), fail_quote, max_bars, price, age
        self.drift_by = drift_by or {}
        self.calls: list[tuple] = []

    def _prov(self, inst, ev: datetime) -> Provenance:
        return Provenance(provider=inst.provider, instrument_id=inst.id, event_time=ev, ingested_time=datetime.now(timezone.utc), delay_seconds=self.delay_seconds, status=self.status)

    async def quote(self, inst) -> Quote:
        self.calls.append(("quote", inst.id))
        if self.fail_quote:
            raise ProviderUnavailable(inst.provider, "quote service down")
        c = bars("1d", 5, drift=self.drift)
        px = self.price if self.price is not None else c[-1].close
        return Quote(instrument_id=inst.id, price=px, prev_close=c[-2].close, prov=self._prov(inst, datetime.now(timezone.utc) - timedelta(seconds=self.age)))

    async def ohlcv(self, inst, interval: str, limit: int) -> OHLCV:
        self.calls.append(("ohlcv", inst.id, interval))
        if interval in self.fail:
            raise ProviderUnavailable(inst.provider, f"{interval} history unavailable")
        n = min(limit, self.max_bars) if self.max_bars else limit
        return OHLCV(instrument_id=inst.id, interval=interval, candles=bars(interval, n, drift=self.drift_by.get(interval, self.drift), age=self.age), prov=self._prov(inst, datetime.now(timezone.utc) - timedelta(seconds=self.age)))


def make_svc(provider: ScriptProvider | None = None) -> tuple[MarketService, ScriptProvider]:
    p = provider or ScriptProvider()
    return MarketService({"yahoo": p, "coinbase": p}), p


# --- news ---------------------------------------------------------------------------------------------------------------------------------
def story(i: int, title: str, *, hours_ago: float = 2.0, feed: str = "Wire", link: str | None = None, summary: str = "", symbols=("AAPL",), also=None, now: datetime | None = None) -> dict:
    when = (now or datetime.now(timezone.utc)) - timedelta(hours=hours_ago)
    return {"id": i, "title": title, "link": link if link is not None else f"https://news.example/{i}", "summary": summary, "feed": feed, "published": when.isoformat(),
            "fetched_at": when.isoformat(), "symbols": list(symbols), "status": "DELAYED", "also": also or []}


class FakeNews:
    def __init__(self, items=None, *, meta=None, symbol_error: str | None = None, fail: bool = False, general=None):
        self.items_ = items or []
        self.general = general
        self.meta = {"feeds_enabled": 7, "feeds_ok": 7, "feeds_failing": [], "never_fetched": 0, "as_of": datetime.now(timezone.utc).isoformat(), **(meta or {})}
        self.symbol_error, self.fail, self.refreshed, self.queries = symbol_error, fail, [], []

    async def refresh_symbol(self, ysym, tag, force=False):
        self.refreshed.append((ysym, tag))
        return {"name": "Symbol feed", "error": self.symbol_error} if self.symbol_error else None

    def items(self, symbol=None, q=None, hours=72, limit=60):
        self.queries.append((symbol, hours))
        if self.fail:
            raise RuntimeError("db locked")
        src = self.items_ if symbol else (self.general if self.general is not None else [])
        return {"items": list(src)[:limit], "total_stories": len(src), "raw_items": len(src), "meta": dict(self.meta)}


# --- fundamentals -------------------------------------------------------------------------------------------------------------------------
HEALTHY_INFO = {"longName": "Acme Corp", "quoteType": "EQUITY", "sector": "Technology", "currentPrice": 100.0, "trailingEps": 4.0, "forwardEps": 5.0, "marketCap": 2e11, "enterpriseValue": 2.1e11,
                "totalRevenue": 8e10, "ebitda": 2.5e10, "bookValue": 20.0, "sharesOutstanding": 2e9, "totalCash": 5e10, "totalDebt": 4e10, "revenueGrowth": 0.12, "earningsGrowth": 0.2,
                "profitMargins": 0.22, "grossMargins": 0.6, "operatingMargins": 0.3, "operatingCashflow": 2.8e10, "freeCashflow": 2.2e10, "mostRecentQuarter": int((datetime.now(timezone.utc) - timedelta(days=40)).timestamp())}


class FakeFund:
    def __init__(self, info=None, *, fail: str | None = None, price: float | None = 100.0, calendar=None):
        self.info, self.fail, self.price, self.calendar = info if info is not None else dict(HEALTHY_INFO), fail, price, calendar
        self.calls = 0

    async def get(self, inst, force=False):
        self.calls += 1
        if self.fail:
            raise ProviderUnavailable("yahoo", self.fail)
        now = datetime.now(timezone.utc)
        snap = normalize(self.info, self.price, self.calendar if self.calendar is not None else {"Earnings Date": [(now + timedelta(days=12)).date()]}, now)
        return {"instrument_id": inst.id, "symbol": inst.symbol, **snap, "prov": {"provider": "yahoo", "fetched_at": now.isoformat(), "origin": "live", "status": "DELAYED", "quality": []}}


# --- macro and Fed Watch ------------------------------------------------------------------------------------------------------------------
def macro_facts(*, y10_chg=32.0, usd_chg=2.4, curve=19.0, core=3.2, drop=()) -> dict:
    d = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    m = (datetime.now(timezone.utc) - timedelta(days=50)).date().replace(day=1).isoformat()
    ch = lambda v, u: [{"label": "vs ~1 month earlier", "ref_date": d, "value": v, "unit": u}]
    facts = [{"id": "us10y", "label": "US 10-year Treasury yield", "value": 4.31, "obs_date": d, "changes": ch(y10_chg, "bps")},
             {"id": "us2y", "label": "US 2-year Treasury yield", "value": 4.12, "obs_date": d, "changes": ch(10.0, "bps")},
             {"id": "curve", "label": "Yield curve", "value": curve, "obs_date": d, "changes": []},
             {"id": "core_cpi", "label": "Core CPI", "value": core, "obs_date": m, "changes": []},
             {"id": "cpi", "label": "CPI", "value": core - 0.2, "obs_date": m, "changes": []},
             {"id": "fed", "label": "Fed funds target range", "lower": 3.75, "upper": 4.0, "obs_date": d, "changes": []},
             {"id": "usd", "label": "Broad dollar index", "value": 121.4, "obs_date": d, "changes": ch(usd_chg, "%")}]
    return {"demo": False, "facts": [({"id": f["id"], "label": f["label"], "error": "unavailable (series down)"} if f["id"] in drop else f) for f in facts]}


class FakeMacro:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.calls = data or macro_facts(), fail, 0

    async def overview(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("fred down")
        return self.data


class FakeFedWatch:
    def __init__(self, *, fail=False, trend="shrinking", days_to_fomc=12):
        self.fail, self.trend, self.days = fail, trend, days_to_fomc

    async def overview(self, now=None):
        if self.fail:
            raise RuntimeError("fed watch down")
        now = now or datetime.now(timezone.utc)
        at = now + timedelta(days=self.days)
        return {"upcoming": [{"id": "statement-x", "type": "statement", "title": "FOMC statement", "meeting": "FOMC meeting", "at_utc": at.isoformat(), "link": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"}],
                "release_schedule": [{"series": "cpi", "label": "CPI", "name": "CPI release", "date": (now + timedelta(days=9)).date().isoformat(), "at_utc": (now + timedelta(days=9)).isoformat()}],
                "balance_sheet": {"id": "balance_sheet", "value": 6.6, "trend": self.trend, "obs_date": now.date().isoformat(), "changes": []}}


class FakeEtf:
    def __init__(self, raw=None, fail=False):
        self.raw, self.fail = raw, fail

    async def fetch(self, inst):
        if self.fail:
            raise ProviderUnavailable("yahoo", "no fund data")
        return self.raw


class FakeCoinGecko:
    def __init__(self, raw=None, fail=False):
        self.raw, self.fail = raw, fail

    async def coin(self, cg_id):
        if self.fail:
            raise ProviderUnavailable("coingecko", "rate limited (HTTP 429)")
        return self.raw


class FakeMempool:
    def __init__(self, snap=None, fail=False):
        self.snap, self.fail = snap or {"height": 900_000, "hashrate": {"currentHashrate": 9.5e20}, "fees": {"halfHourFee": 4}}, fail

    async def snapshot(self):
        if self.fail:
            raise ProviderUnavailable("mempool.space", "ConnectError")
        return self.snap


def ctx_for(asset_id: str, *, svc=None, news=None, fund=None, macro=None, fedwatch=None, etf=None, cg=None, mempool=None, demo=False, registry=None) -> Ctx:
    a = A.describe(asset_id)
    assert a is not None, asset_id
    svc = svc or make_svc()[0]
    return Ctx(asset=a, svc=svc, summary=MarketSummary(svc), news=news or FakeNews(), fundamentals=fund or FakeFund(), macro=macro or FakeMacro(), fedwatch=fedwatch or FakeFedWatch(),
               etf=etf or FakeEtf(), coingecko=cg, mempool=mempool, registry=registry, demo=demo)


def all_text(finding) -> list[str]:
    """Every sentence a finding can show, for scans like 'no order language anywhere'."""
    out = [finding.takeaway, *(i.text for i in finding.interpretations), *(p.text for p in finding.points), *finding.limitations]
    out += [s.why_it_matters or "" for s in finding.stories]
    return out
