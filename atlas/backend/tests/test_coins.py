"""Multi-coin daily history (Coinbase): the real candle shape (fetched 2026-11-11), 300-bar windows, incremental refresh, unlisted coins, failures that do not stop the rest, completed days only,
gaps reported and never filled, and a panel that leaves missing days as NaN."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pytest

from atlas_api.btclab import coins as C

RAW = json.loads((Path(__file__).parent / "fixtures" / "coinbase_daily_candles.json").read_text())
DAY = 86400
NOW = int(datetime(2026, 11, 11, 12, tzinfo=timezone.utc).timestamp())


def _candles(start, end, listed_from=None, skip=()):
    """Fake Coinbase: one candle per day in [start, end), at most 300, newest first, like the real service."""
    t0 = (start // DAY) * DAY
    rows = []
    d = t0
    while d < min(end, NOW + 1) and len(rows) < 300:                              # the real service never serves a candle that has not started yet
        if (listed_from is None or d >= listed_from) and d not in skip:
            rows.append([d, 90.0 + (d // DAY) % 7, 110.0 + (d // DAY) % 7, 100.0 + (d // DAY) % 7, 101.0 + (d // DAY) % 7, 5.0])
        d += DAY
    return rows[::-1]


def _service(db, listed_from=None, skip=(), status=None, products=None, calls=None):
    def handler(req):
        if calls is not None:
            calls.append(str(req.url))
        sym = req.url.path.split("/")[2].split("-")[0]
        if products is not None and sym not in products:
            return httpx.Response(404, json={"message": "NotFound"})
        if status:
            return httpx.Response(status)
        q = dict(req.url.params)
        s, e = (int(datetime.fromisoformat(q[k]).timestamp()) for k in ("start", "end"))
        return httpx.Response(200, json=_candles(s, e, listed_from, skip))
    return C.CoinData(db, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_the_real_candle_shape_is_read_in_the_right_order():
    rows = C.parse_candles(RAW["ETH"])
    assert len(rows) == 45 and rows == sorted(rows)
    t, o, h, l, c, v = rows[-1]                                                   # real response row: [1794355200, 2040.86, 2067.3, 2050.58, 2048.38, 9179.02...] = time, low, high, open, close, volume
    assert (t, o, h, l, c) == (1794355200, 2050.58, 2067.3, 2040.86, 2048.38) and abs(v - 9179.02074018) < 1e-9
    assert all(l <= min(o, c) and h >= max(o, c) for _, o, h, l, c, _v in rows)    # every real candle is internally consistent


@pytest.mark.parametrize("bad", [[[1, 2, 3]], [[1, 5, 4, 4.5, 4.5, 1]], [[1, 0, 4, 3, 3, 1]], ["x"]])
def test_a_malformed_or_impossible_candle_refuses_the_whole_response(bad):
    with pytest.raises(ValueError):
        C.parse_candles(bad)


def test_history_is_fetched_in_300_bar_windows_and_stored_once(db):
    calls = []
    svc = _service(db, calls=calls)
    first = NOW - 650 * DAY
    db.x("INSERT INTO coin_bars(symbol,t,o,h,l,c,v) VALUES('BTC',?,1,2,1,1.5,1)", (first,))            # start 650 days back so the number of windows is known
    r = asyncio.run(svc.refresh("BTC", now=NOW))
    assert r["status"] == "ok" and len(calls) == 3                                                         # 650 days at 300 per window = 3 requests
    n = db.q("SELECT COUNT(*) n FROM coin_bars WHERE symbol='BTC'")[0]["n"]
    asyncio.run(svc.refresh("BTC", now=NOW))
    assert db.q("SELECT COUNT(*) n FROM coin_bars WHERE symbol='BTC'")[0]["n"] == n                       # fetching again adds nothing twice


def test_a_second_refresh_starts_from_the_newest_stored_day(db):
    calls = []
    svc = _service(db, calls=calls)
    db.x("INSERT INTO coin_bars(symbol,t,o,h,l,c,v) VALUES('ETH',?,1,2,1,1.5,1)", (NOW - 20 * DAY,))
    asyncio.run(svc.refresh("ETH", now=NOW))
    assert len(calls) == 1 and db.q("SELECT MAX(t) m FROM coin_bars WHERE symbol='ETH'")[0]["m"] >= NOW - 2 * DAY


def test_a_coin_coinbase_does_not_list_is_marked_not_listed_not_an_error(db):
    svc = _service(db, products={"BTC"})
    r = asyncio.run(svc.refresh("MATIC", now=NOW))
    assert r == {"symbol": "MATIC", "status": "not_listed", "added": 0}
    assert {x["symbol"]: x["status"] for x in svc.status()} == {"MATIC": "not_listed"}


def test_one_coins_failure_does_not_stop_the_others(db):
    def handler(req):
        sym = req.url.path.split("/")[2].split("-")[0]
        if sym == "ETH":
            return httpx.Response(500)
        q = dict(req.url.params)
        s, e = (int(datetime.fromisoformat(q[k]).timestamp()) for k in ("start", "end"))
        return httpx.Response(200, json=_candles(max(s, NOW - 5 * DAY), e))
    svc = C.CoinData(db, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = asyncio.run(svc.refresh_all(("BTC", "ETH", "LTC"), now=NOW))
    assert [x["status"] for x in out] == ["ok", "error", "ok"] and "HTTP 500" in out[1]["reason"]
    assert {x["symbol"]: x["status"] for x in svc.status()} == {"BTC": "ok", "ETH": "error", "LTC": "ok"}


def test_a_coin_listed_late_has_no_bars_before_its_listing(db):
    listed = NOW - 40 * DAY
    svc = _service(db, listed_from=(listed // DAY) * DAY)
    asyncio.run(svc.refresh("SOL", now=NOW))
    rows = svc.stored("SOL", now=NOW)
    assert rows[0][0] == (listed // DAY) * DAY                                                              # nothing is made up before the listing day


def test_only_completed_days_are_returned(db):
    svc = _service(db)
    db.x("INSERT INTO coin_bars(symbol,t,o,h,l,c,v) VALUES('BTC',?,1,2,1,1.5,1)", (NOW - 3 * DAY,))
    asyncio.run(svc.refresh("BTC", now=NOW))
    today = (NOW // DAY) * DAY
    assert max(x[0] for x in svc.stored("BTC", completed_only=False)) == today                             # the forming bar for today is stored
    assert max(x[0] for x in svc.stored("BTC", now=NOW)) == today - DAY                                    # but not offered for research until the day is over


def test_gaps_are_reported_and_never_filled(db):
    skip = {((NOW - 10 * DAY) // DAY) * DAY, ((NOW - 9 * DAY) // DAY) * DAY}
    svc = _service(db, skip=skip)
    db.x("INSERT INTO coin_bars(symbol,t,o,h,l,c,v) VALUES('BTC',?,1,2,1,1.5,1)", (NOW - 20 * DAY,))
    asyncio.run(svc.refresh("BTC", now=NOW))
    g = svc.gaps_in("BTC", now=NOW)
    assert len(g) == 1 and g[0]["missing_bars"] == 2
    assert not any(x[0] in skip for x in svc.stored("BTC", now=NOW))


def test_the_panel_aligns_coins_on_one_calendar_and_leaves_missing_days_empty(db):
    for sym, days in (("BTC", range(10, 0, -1)), ("SOL", range(5, 0, -1))):                                # SOL only has the last 5 days
        for k in days:
            db.x("INSERT INTO coin_bars(symbol,t,o,h,l,c,v) VALUES(?,?,1,2,1,?,1)", (sym, ((NOW // DAY) - k) * DAY, 100.0 + k if sym == "BTC" else 50.0 + k))
    p = C.CoinData(db).panel(("BTC", "SOL", "ETH"), now=NOW)
    assert p["symbols"] == ["BTC", "SOL"] and p["close"].shape == (10, 2)                                  # ETH has no data and is left out, not zero-filled
    assert not np.isnan(p["close"][:, 0]).any() and np.isnan(p["close"][:5, 1]).all() and not np.isnan(p["close"][5:, 1]).any()
    assert p["close"][0, 0] == 110.0 and p["close"][-1, 1] == 51.0


def test_the_list_is_fixed_and_has_no_duplicates():
    assert len(C.UNIVERSE) == len(set(C.UNIVERSE)) == 28 and C.UNIVERSE[0] == "BTC"
