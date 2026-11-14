"""The listings service with fake bars, SEC and a mocked calendar: independent confirmation, newness checks, SEC verification, honest messages when a check cannot be made, and status recomputed at read time."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

from atlas_api.db import DB
from atlas_api.discover import listings as L
from atlas_api.discover.listings_service import ListingsService, confirm_from_bars, first_bar
from atlas_api.models import Candle

FIX = Path(__file__).parent / "fixtures"
MONTHS = {m: json.loads((FIX / f"nasdaq_ipo_{m}.json").read_text()) for m in ("2026-09", "2026-10", "2026-11")}
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def ts(d):
    return int(datetime.fromisoformat(d + "T14:30:00+00:00").timestamp())


def candles(*days):
    return [Candle(time=ts(d), open=1, high=1, low=1, close=1, volume=1) for d in days]


def calendar_client():
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=MONTHS.get(req.url.params["date"], {"status": {"rCode": 200}, "data": {}}))))


class FakeBars:
    def __init__(self, hist, fail=False, failed=None):
        self.hist, self.fail, self.failed = hist, fail, failed or {}

    async def fetch(self, symbols, progress=None):
        if self.fail:
            raise RuntimeError("down")
        return SimpleNamespace(bars={s: self.hist[s] for s in symbols if s in self.hist}, failed=self.failed)


class FakeEdgar:
    enabled = True

    async def cik(self, t):
        return (1, "X") if t == "NARA" else None

    async def all_filings(self, cik):
        return {"filings": [{"form": "424B4", "filed": "2026-11-03", "link": "https://www.sec.gov/a"}]}, "live", NOW


def service(tmp_path, bars=None, edgar=None, demo=False):
    db = DB(str(tmp_path / "ls.db"))
    return ListingsService(db, L.NasdaqIpoFeed(db, calendar_client()), bars, edgar, demo)


def test_first_trade_is_confirmed_only_when_the_first_bar_follows_the_pricing_date():
    assert first_bar(candles("2026-11-03", "2026-11-04")) == "2026-11-03" and first_bar([]) is None
    ok = confirm_from_bars(candles("2026-11-03", "2026-11-04"), "2026-11-02")
    assert ok["first_trade"] == "2026-11-03" and ok["newness"]["new"] is True
    old = confirm_from_bars(candles("2019-05-01", "2026-11-04"), "2026-11-02")
    assert old["first_trade"] is None and old["newness"]["new"] is False and "transfer" in old["newness"]["reason"]
    late = confirm_from_bars(candles("2026-11-20"), "2026-11-02")
    assert late["first_trade"] is None                                                                  # far from the pricing date: not accepted as its debut
    assert confirm_from_bars([], "2026-11-02") == {"first_trade": None, "earliest_price": None, "newness": None}


def test_confirmed_and_verified_deals_are_marked_and_unchecked_ones_say_so(tmp_path):
    s = service(tmp_path, FakeBars({"NARA": candles("2026-11-03", "2026-11-04")}), FakeEdgar())
    out = asyncio.run(s.refresh(NOW))
    assert out["available"] and out["confirmed"] == 1 and out["verified"] == 1
    feed = s.read(30, NOW)
    nara = next(x for x in feed["recent"] if x["symbol"] == "NARA")
    assert nara["status"] == "trading" and nara["first_trade_date"] == "2026-11-03" and nara["verification"]["verified"] is True and nara["newness"]["new"] is True
    other = next(x for x in feed["recent"] if x["symbol"] != "NARA" and x["status"] == "priced")
    assert "not independently confirmed" in other["status_text"] or "Not yet trading" in other["status_text"]
    assert feed["counts"]["confirmed_trading"] == 1 and feed["counts"]["verified_by_sec"] == 1 and feed["stale"] is False


def test_without_price_history_or_sec_nothing_is_claimed_and_the_feed_says_why(tmp_path):
    s = service(tmp_path)
    out = asyncio.run(s.refresh(NOW))
    assert out["confirmed"] == 0 and out["verified"] == 0 and any("No price-history source" in e for e in out["errors"]) and any("SEC verification is off" in e for e in out["errors"])
    feed = s.read(30, NOW)
    assert feed["counts"]["confirmed_trading"] == 0 and all(x["status"] == "priced" for x in feed["recent"]) and feed["errors"]


def test_a_failing_price_source_is_said_and_does_not_hide_the_deals(tmp_path):
    out = asyncio.run(service(tmp_path, FakeBars({}, fail=True), FakeEdgar()).refresh(NOW))
    assert out["available"] and out["rows"] > 20 and any("Price history could not be read" in e for e in out["errors"])


def test_statuses_are_recomputed_against_today_when_the_page_is_read(tmp_path):
    s = service(tmp_path)
    asyncio.run(s.refresh(NOW))
    f1 = s.read(30, NOW)
    nara_then = next(x for x in f1["recent"] if x["symbol"] == "NARA")
    assert nara_then["status"] == "priced"
    later = s.read(30, datetime(2026, 12, 20, 12, tzinfo=timezone.utc))                                  # six weeks on: outside the rolling window, and the feed is stale
    assert all(x["symbol"] != "NARA" for x in later["recent"]) and later["stale"] is True
    rz = next(x for x in f1["upcoming"] if x["symbol"] == "RZRA")
    assert rz["status"] == "upcoming"
    assert next(x for x in s.read(30, datetime(2026, 11, 20, 12, tzinfo=timezone.utc))["upcoming"] if x["symbol"] == "RZRA")["status"] == "upcoming_date_passed"


def test_demo_and_not_yet_fetched_are_explicit(tmp_path):
    assert asyncio.run(service(tmp_path, demo=True).refresh(NOW))["available"] is False
    s = ListingsService(DB(str(tmp_path / "fresh.db")), L.NasdaqIpoFeed(), None, None)
    r = s.read(30, NOW)
    assert r["available"] is False and "has not been fetched yet" in r["reason"] and r["recent"] == [] and "IPOs only" in r["coverage"]
