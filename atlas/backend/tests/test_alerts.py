import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from atlas_api import commands
from atlas_api.alerts.manager import AlertManager
from atlas_api.alerts.rules import decide, parse_rule
from atlas_api.app import create_app
from atlas_api.models import Candle, OHLCV, Provenance, ProviderUnavailable, Quote
from atlas_api.scanner.bars import BarBatch
from atlas_api.service import MarketService
from atlas_api.models import DataStatus

HOUR = 3600


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    """The service caches quotes (3s) and bars (20s). Tests mutate the provider between evaluations, so disable it."""
    from atlas_api import service

    monkeypatch.setitem(service._TTL, "quote", 0.0)
    monkeypatch.setitem(service._TTL, "ohlcv", 0.0)
BTC = "CRYPTO:COINBASE:BTC-USD:SPOT"


class Script:
    """Scriptable crypto provider registered as 'coinbase'. Mutate fields between evaluations."""
    name, entitlement, delay_seconds = "coinbase", "test", 0
    native_intervals = {"1m", "5m", "15m", "1h", "1d"}

    def __init__(self):
        self.price, self.prev, self.age, self.fail = 100.0, 100.0, 0, False
        self.candles: list[Candle] | None = None

    async def quote(self, inst):
        if self.fail:
            raise ProviderUnavailable("coinbase", "down")
        ev = datetime.now(timezone.utc) - timedelta(seconds=self.age)
        return Quote(instrument_id=inst.id, price=self.price, prev_close=self.prev, prev_close_basis="24h rolling open",
                     prov=Provenance(provider="coinbase", venue="COINBASE", instrument_id=inst.id, event_time=ev,
                                     ingested_time=datetime.now(timezone.utc), entitlement="test", delay_seconds=0))

    async def ohlcv(self, inst, interval, limit):
        c = self.candles or []
        return OHLCV(instrument_id=inst.id, interval=interval, candles=c, prov=Provenance(
            provider="coinbase", venue="COINBASE", instrument_id=inst.id, event_time=datetime.fromtimestamp(c[-1].time, timezone.utc),
            ingested_time=datetime.now(timezone.utc), entitlement="test", delay_seconds=0))


def bars(closes, *, forming=True, seconds=HOUR, vols=None):
    """Candles ending with a forming bar (opened half an interval ago) or a completed one."""
    now = int(time.time())
    last_open = now - seconds // 2 if forming else now - seconds
    n = len(closes)
    return [Candle(time=last_open - (n - 1 - i) * seconds, open=c, high=c * 1.001, low=c * 0.999, close=c,
                   volume=(vols[i] if vols else 1e6)) for i, c in enumerate(closes)]


@pytest.fixture
def env(db):
    prov = Script()
    svc = MarketService({"coinbase": prov})
    mgr = AlertManager(db, svc, bars=None, universe_loader=None)
    return prov, mgr


def price_rule(op="above", level=100.5, **kw):
    return {"kind": "price", "instrument_id": BTC, "op": op, "level": level, "cooldown_seconds": 600, **kw}


def test_decide_table():
    assert decide(None, True, None, 0, 60) == "baseline"
    assert decide(None, False, None, 0, 60) == "baseline"
    assert decide(False, True, None, 0, 60) == "fire"
    assert decide(True, True, None, 0, 60) == "none"
    assert decide(False, False, None, 0, 60) == "none"
    assert decide(True, False, None, 0, 60) == "none"
    assert decide(False, True, 0, 59, 60) == "suppressed"
    assert decide(False, True, 0, 60, 60) == "fire"


def test_rule_validation():
    for bad in ({"kind": "price", "instrument_id": "BTC", "op": "above", "level": -1}, {"kind": "price", "instrument_id": "BTC", "op": "sideways", "level": 1},
                {"kind": "rsi", "instrument_id": "BTC", "op": "above", "level": 101}, {"kind": "nope"},
                {"kind": "price", "instrument_id": "BTC", "op": "above", "level": 1, "cooldown_seconds": 5},
                {"kind": "scan"}, {"kind": "scan", "preset": "breakout", "spec": {"filters": []}}):
        with pytest.raises(ValueError):
            parse_rule(bad)


async def test_price_alert_lifecycle_edge_cooldown_and_provenance(env):
    prov, mgr = env
    a = mgr.create(price_rule())
    t = time.time()
    assert await mgr.evaluate_all(t) == []                       # baseline: price 100 < 100.5
    prov.price = 101.0
    ev = await mgr.evaluate_all(t + 1)
    assert len(ev) == 1 and ev[0]["delivery"] == "in_app:delivered" and ev[0]["rule_version"] == 1
    d = ev[0]["trigger"]["data"]
    assert d["status"] == "LIVE" and d["provider"] == "coinbase" and d["venue"] == "COINBASE" and d["event_time"] and d["ingested_time"]
    assert ev[0]["trigger"]["value"] == 101.0 and ev[0]["trigger"]["rule"]["level"] == 100.5
    assert await mgr.evaluate_all(t + 2) == []                   # still true: no repeat (edge-triggered)
    prov.price = 99.0
    assert await mgr.evaluate_all(t + 3) == []                   # re-arm
    prov.price = 102.0
    sup = await mgr.evaluate_all(t + 10)                         # new edge inside cooldown
    assert [e["delivery"] for e in sup] == ["suppressed_cooldown"]
    assert mgr.events()["unread"] == 1                           # suppressed events never count as notifications
    prov.price = 99.0
    await mgr.evaluate_all(t + 20)
    prov.price = 103.0
    ev = await mgr.evaluate_all(t + 5000)                        # after cooldown
    assert [e["delivery"] for e in ev] == ["in_app:delivered"]
    assert mgr.events()["unread"] == 2 and len(mgr.events()["events"]) == 3
    assert mgr.get(a["id"])["state"]["fires"] == 2


async def test_condition_already_true_at_creation_does_not_fire(env):
    prov, mgr = env
    prov.price = 200.0
    mgr.create(price_rule())
    assert await mgr.evaluate_all() == []
    assert await mgr.evaluate_all() == []


async def test_stale_or_unavailable_data_is_gated_and_state_untouched(env):
    prov, mgr = env
    a = mgr.create(price_rule())
    await mgr.evaluate_all()                                     # baseline false
    prov.price, prov.age = 105.0, 600                            # would fire, but data is 10 min old (STALE for crypto)
    assert await mgr.evaluate_all() == []
    st = mgr.get(a["id"])["state"]
    assert st["last_status"] == "STALE" and "STALE" in st["last_skip"] and st["prev"] is False
    prov.age, prov.fail = 0, True
    assert await mgr.evaluate_all() == []
    assert "unavailable" in mgr.get(a["id"])["state"]["last_skip"]
    prov.fail = False
    assert len(await mgr.evaluate_all()) == 1                    # fresh data: the edge is still there and now fires


async def test_update_bumps_version_and_rebaselines_and_enable_toggle(env):
    prov, mgr = env
    a = mgr.create(price_rule())
    await mgr.evaluate_all()
    prov.price = 101
    assert len(await mgr.evaluate_all()) == 1
    b = mgr.update(a["id"], price_rule(level=150))
    assert b["version"] == 2 and b["state"] == {}
    prov.price = 160
    assert await mgr.evaluate_all() == []                        # re-baselined on the new rule (already true)
    prov.price = 100
    await mgr.evaluate_all()
    prov.price = 160
    ev = await mgr.evaluate_all()
    assert ev[0]["rule_version"] == 2
    mgr.set_enabled(a["id"], False)
    prov.price = 100
    assert await mgr.evaluate_all() == [] and mgr.get(a["id"])["state"]["prev"] is True   # disabled: not evaluated
    mgr.set_enabled(a["id"], True)
    assert mgr.get(a["id"])["state"] == {}                       # re-enable re-baselines (no stale edge)
    assert mgr.update(999, price_rule()) is None and mgr.set_enabled(999, True) is None


async def test_pct_change_alert(env):
    prov, mgr = env
    mgr.create({"kind": "pct_change", "instrument_id": BTC, "op": "below", "threshold": -3})
    await mgr.evaluate_all()
    prov.price, prov.prev = 96.0, 100.0
    ev = await mgr.evaluate_all()
    assert len(ev) == 1 and "-4.00%" in ev[0]["message"] and "24h rolling open" in ev[0]["message"]


async def test_rsi_uses_completed_candle_unless_told_otherwise(env):
    prov, mgr = env
    alternating = [100 + (i % 2) for i in range(60)]
    prov.candles = bars(alternating + [130], forming=True)       # forming bar spikes: RSI on it would be > 70
    on_close = mgr.create({"kind": "rsi", "instrument_id": BTC, "op": "above", "level": 70, "interval": "1h"})
    repaint = mgr.create({"kind": "rsi", "instrument_id": BTC, "op": "above", "level": 70, "interval": "1h", "on_close": False})
    prov.candles = bars(alternating + [100], forming=True)
    await mgr.evaluate_all()                                     # baselines
    prov.candles = bars(alternating + [130], forming=True)
    ev = await mgr.evaluate_all()
    assert [e["alert_id"] for e in ev] == [repaint["id"]]        # only the forming-bar rule reacts
    assert mgr.get(on_close["id"])["state"]["prev"] is False
    prov.candles = bars(alternating + [130, 131], forming=True)  # the spike bar is now completed
    ev = await mgr.evaluate_all()
    assert [e["alert_id"] for e in ev] == [on_close["id"]]


async def test_ma_macd_and_rvol_alerts(env):
    prov, mgr = env
    down = [200 - 0.02 * i * i for i in range(80)]   # accelerating decline: histogram clearly negative (a linear one converges to exactly 0)
    ma = mgr.create({"kind": "ma", "instrument_id": BTC, "op": "above", "length": 20, "interval": "1h"})
    macd = mgr.create({"kind": "macd", "instrument_id": BTC, "direction": "bullish", "interval": "1h"})
    prov.candles = bars(down + [down[-1]], forming=True)
    await mgr.evaluate_all()
    up = down + [down[-1] + 4 * (i + 1) for i in range(15)]
    prov.candles = bars(up + [up[-1]], forming=True)
    fired = {e["alert_id"] for e in await mgr.evaluate_all()}
    assert fired == {ma["id"], macd["id"]}
    rv = mgr.create({"kind": "rvol", "instrument_id": BTC, "threshold": 2.5})
    prov.candles = bars([100.0] * 60, seconds=86400, vols=[1e6] * 60)
    await mgr.evaluate_all()
    prov.candles = bars([100.0] * 60, seconds=86400, vols=[1e6] * 59 + [3e6])
    ev = await mgr.evaluate_all()
    assert [e["alert_id"] for e in ev] == [rv["id"]] and "RVOL 3.00x" in ev[0]["message"]
    prov.candles = bars([100.0] * 10, seconds=86400)             # too little history: skipped, not fired
    assert await mgr.evaluate_all() == [] and "not enough history" in mgr.get(rv["id"])["state"]["last_skip"]


async def test_one_failing_rule_or_channel_does_not_block_others(env):
    prov, mgr = env
    bad = mgr.db.x("INSERT INTO alerts(name,kind,rule,version,enabled,state,created_at,updated_at) VALUES('bad','scan',?,1,1,'{}','x','x')",
                   (json.dumps({"kind": "scan", "preset": "does_not_exist"}),))
    good = mgr.create(price_rule())

    class Boom:
        name = "boom"

        async def deliver(self, ev, rule):
            raise RuntimeError("smtp down")

    mgr.notifiers.append(Boom())
    await mgr.evaluate_all()
    prov.price = 101
    ev = await mgr.evaluate_all()
    assert len(ev) == 1 and ev[0]["alert_id"] == good["id"]
    assert "in_app:delivered" in ev[0]["delivery"] and "boom:failed:RuntimeError" in ev[0]["delivery"]   # event kept despite channel failure
    assert "unknown preset" in mgr.get(bad)["state"]["error"] and len(mgr.events()["events"]) == 1


# --- scan alerts ----------------------------------------------------------------
class FakeBars:
    name = "fake"

    def __init__(self, data):
        self.data = data

    async def fetch(self, symbols, progress=None):
        return BarBatch({s: self.data[s] for s in symbols if s in self.data}, {}, "fake", DataStatus.HISTORICAL, None, [])


def daily(closes, vols=None):
    t0 = 1_700_000_000 - 1_700_000_000 % 86400
    return [Candle(time=t0 + i * 86400, open=closes[max(i - 1, 0)], high=c * 1.01, low=c * 0.99, close=c, volume=(vols or [1e6] * len(closes))[i])
            for i, c in enumerate(closes)]


FLAT = [100.0] * 100
BRK = daily(FLAT[:-1] + [110.0], [1e6] * 99 + [3e6])


async def test_scan_alert_fires_only_on_new_entrants_with_per_symbol_dedupe(db):
    data = {"SPY": daily(FLAT), "AAA": daily(FLAT), "BBB": daily(FLAT)}
    src = FakeBars(data)

    async def uni(_):
        return ["AAA", "BBB"]

    mgr = AlertManager(db, MarketService({}), src, uni)
    a = mgr.create({"kind": "scan", "preset": "BREAKOUT", "interval_seconds": 300, "cooldown_seconds": 3600})
    t = 1_000_000.0
    assert await mgr.evaluate_all(t) == []                       # baseline: nothing matches yet
    assert await mgr.evaluate_all(t + 100) == []                 # inside the scan interval: not even evaluated
    data["AAA"] = BRK
    ev = await mgr.evaluate_all(t + 400)
    assert len(ev) == 1 and ev[0]["trigger"]["symbols"] == ["AAA"] and "1 new match: AAA" in ev[0]["message"]
    assert ev[0]["trigger"]["rows"][0]["rvol"] == pytest.approx(3.0) and ev[0]["trigger"]["data"]["status"] == "HISTORICAL"
    assert await mgr.evaluate_all(t + 800) == []                 # AAA still matches: not new
    data["AAA"] = daily(FLAT)
    await mgr.evaluate_all(t + 1200)                             # drops out
    data["AAA"] = BRK
    ev = await mgr.evaluate_all(t + 1600)                        # re-enters inside the per-symbol cooldown
    assert [e["delivery"] for e in ev] == ["suppressed_cooldown"]
    data["AAA"], data["BBB"] = daily(FLAT), BRK
    ev = await mgr.evaluate_all(t + 2000)                        # a different symbol is not blocked by AAA's cooldown
    assert [(e["delivery"], e["trigger"]["symbols"]) for e in ev] == [("in_app:delivered", ["BBB"])]
    data["AAA"] = BRK
    ev = await mgr.evaluate_all(t + 2400)                        # AAA fired at t+400; 2000s < 3600s cooldown
    assert [(e["delivery"], e["trigger"]["symbols"]) for e in ev] == [("suppressed_cooldown", ["AAA"])]
    ev = await mgr.evaluate_all(t + 400 + 3601 + 400)            # keep BBB/AAA matching: nothing new
    assert ev == [] and mgr.get(a["id"])["state"]["fires"] == 2


async def test_scan_alert_batches_new_symbols_into_one_event(db):
    data = {"SPY": daily(FLAT), **{s: daily(FLAT) for s in ("A", "B", "C")}}

    async def uni(_):
        return ["A", "B", "C"]

    mgr = AlertManager(db, MarketService({}), FakeBars(data), uni)
    mgr.create({"kind": "scan", "preset": "momentum_breakout", "interval_seconds": 300, "max_symbols": 2})
    await mgr.evaluate_all(0.0)
    for s in data:
        if s != "SPY":
            data[s] = BRK
    ev = await mgr.evaluate_all(400.0)
    assert len(ev) == 1 and len(ev[0]["trigger"]["symbols"]) == 2 and ev[0]["trigger"]["more"] == 1   # one alert, not three


async def test_run_loop_evaluates_in_background(env):
    prov, mgr = env
    a = mgr.create(price_rule())
    task = asyncio.create_task(mgr.run_loop(0.05))
    await asyncio.sleep(0.4)
    task.cancel()
    assert mgr.get(a["id"])["state"].get("last_eval_at")


# --- API ----------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    prov = Script()
    with TestClient(create_app(db_path=str(tmp_path / "a.db"), demo=False, providers={"coinbase": prov}, bar_source=FakeBars({}), alert_loop=False)) as c:
        c.prov = prov
        yield c


def test_api_validation_errors(client):
    p = client.post
    assert p("/api/alerts", json={"kind": "price", "instrument_id": "NOPE123456", "op": "above", "level": 1}).json()["error"]["code"] == "UNKNOWN_INSTRUMENT"
    for bad in ({"kind": "price", "instrument_id": "BTC", "op": "above", "level": -5}, {"kind": "wat"},
                {"kind": "scan", "preset": "zzz"}, {"kind": "scan", "preset": "breakout", "spec": {"filters": []}},
                {"kind": "scan", "spec": {"filters": [{"field": "nope", "op": ">", "value": 1}]}}):
        r = p("/api/alerts", json=bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_ALERT", bad
    assert client.get("/api/alerts").json()["data"] == []


def test_api_crud_events_and_evaluate(client):
    a = client.post("/api/alerts", json={"kind": "price", "instrument_id": "BTC", "op": "above", "level": 100.5}).json()["data"]
    assert a["rule"]["instrument_id"] == BTC and a["name"] == "BTC-USD price above 100.5" and a["version"] == 1   # symbol canonicalised
    assert client.post("/api/alerts/evaluate").json()["data"] == {"events": [], "evaluated": 1}
    client.prov.price = 101
    ev = client.post("/api/alerts/evaluate").json()["data"]["events"]
    assert len(ev) == 1
    out = client.get("/api/alerts/events").json()["data"]
    assert out["unread"] == 1 and out["events"][0]["trigger"]["data"]["status"] == "LIVE"
    assert client.get("/api/alerts/events", params={"unread_only": True}).json()["data"]["events"]
    assert client.post("/api/alerts/events/read", json={"ids": None}).json()["data"] == {"marked": 1}   # count of events actually changed
    assert client.post("/api/alerts/events/read", json={"ids": None}).json()["data"] == {"marked": 0}
    assert client.get("/api/alerts/events").json()["data"]["unread"] == 0
    assert client.post(f"/api/alerts/{a['id']}/enabled", json={"enabled": False}).json()["data"]["enabled"] is False
    assert client.post("/api/alerts/evaluate").json()["data"]["evaluated"] == 0
    upd = client.put(f"/api/alerts/{a['id']}", json={"kind": "price", "instrument_id": "BTC", "op": "below", "level": 50}).json()["data"]
    assert upd["version"] == 2
    assert client.put("/api/alerts/999", json={"kind": "price", "instrument_id": "BTC", "op": "below", "level": 50}).status_code == 404
    client.delete(f"/api/alerts/{a['id']}")
    assert client.get("/api/alerts").json()["data"] == []


def test_api_alerts_and_events_persist_across_restart(tmp_path):
    path, prov = str(tmp_path / "p.db"), Script()
    mk = lambda: TestClient(create_app(db_path=path, demo=False, providers={"coinbase": prov}, bar_source=FakeBars({}), alert_loop=False))
    with mk() as c:
        c.post("/api/alerts", json={"kind": "price", "instrument_id": "BTC", "op": "above", "level": 100.5})
        c.post("/api/alerts/evaluate")
        prov.price = 101
        c.post("/api/alerts/evaluate")
    with mk() as c2:
        assert len(c2.get("/api/alerts").json()["data"]) == 1
        assert c2.get("/api/alerts/events").json()["data"]["unread"] == 1
        prov.price = 99
        c2.post("/api/alerts/evaluate")                          # persisted state (prev=True) re-arms the rule after the restart
        prov.price = 102
        ev = c2.post("/api/alerts/evaluate").json()["data"]["events"]
        assert [e["delivery"] for e in ev] == ["suppressed_cooldown"]   # last_fired_at survived the restart, so the cooldown still applies


