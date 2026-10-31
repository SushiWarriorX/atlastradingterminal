import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from atlas_api import commands
from atlas_api.app import create_app
from atlas_api.models import Candle, DataStatus
from atlas_api.scanner import engine, features as feat, nl, presets, universe
from atlas_api.scanner.bars import BarBatch
from atlas_api.scanner.rules import Filter, ScanSpec

DAY = 86400


def mk(closes, vols=None, t0=1_700_000_000 - 1_700_000_000 % DAY):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(Candle(time=t0 + i * DAY, open=prev, high=c * 1.01, low=c * 0.99, close=c, volume=(vols or [1e6] * len(closes))[i]))
        prev = c
    return out


FLAT = [100.0] * 100
BREAKOUT = mk(FLAT[:-1] + [110.0], [1e6] * 99 + [3e6])
QUIET = mk(FLAT)
SHORT = mk([100.0] * 30)                       # < 60 bars: insufficient history
BENCH = mk(FLAT)
FALLING = mk([100.0] * 90 + [99, 98, 97, 96, 95, 94, 93, 92, 91, 90], [1e6] * 95 + [2e6] * 5)


class Fake:
    name = "fake"

    def __init__(self, bars):
        self.bars, self.calls = bars, 0

    async def fetch(self, symbols, progress=None):
        self.calls += 1
        got = {s: self.bars[s] for s in symbols if s in self.bars}
        if progress:
            progress(len(symbols), len(symbols))
        return BarBatch(got, {s: "no data returned" for s in symbols if s not in self.bars}, "fake", DataStatus.HISTORICAL, None, ["fake source"])


UNIVERSE = {"BRK": BREAKOUT, "QUIET": QUIET, "SHORT": SHORT, "FALL": FALLING, "SPY": BENCH}


def test_features_hand_checked():
    f = feat.compute("BRK", BREAKOUT, BENCH)
    assert f["price"] == 110 and f["change_pct"] == pytest.approx(10.0)
    assert f["rvol"] == pytest.approx(3.0) and f["avg_volume_20"] == pytest.approx(1e6)
    assert f["dollar_volume_avg20"] == pytest.approx(100 * 1e6)
    assert f["ret_21d"] == pytest.approx(10.0) and f["rs_21d"] == pytest.approx(10.0)   # benchmark flat
    assert f["breakout_20"] is True and f["breakdown_20"] is False and f["above_sma50"] is True
    assert f["setup"] == "Breakout" and f["dist_52w_high_pct"] == pytest.approx(110 / (110 * 1.01) * 100 - 100)
    assert f["consec_up"] == 1


def test_insufficient_history_leaves_fields_none_and_never_passes():
    f = feat.compute("SHORT", SHORT, BENCH)
    assert f["sufficient"] is False and f["rvol"] is None and f["rsi14"] is None and f["price"] == 100
    # even a filter that a flat price trivially satisfies must not pass on a row with insufficient history
    spec = ScanSpec(filters=[Filter(field="price", op=">", value=1)])
    assert engine.evaluate(spec, [f]) == []
    assert Filter(field="rvol", op=">", value=0).passes(f) is False


def test_no_benchmark_means_rs_is_none():
    f = feat.compute("BRK", BREAKOUT, None)
    assert f["rs_21d"] is None and f["ret_21d"] == pytest.approx(10.0)


def test_spec_validation_rejects_bad_input():
    for bad in ({"field": "nope", "op": ">", "value": 1}, {"field": "rvol", "op": "in", "value": ["a"]},
                {"field": "rvol", "op": ">", "value": "high"}, {"field": "above_sma50", "op": ">", "value": True},
                {"field": "sector", "op": ">", "value": "Tech"}, {"field": "price", "op": "between", "value": [1]}):
        with pytest.raises(ValidationError):
            Filter(**bad)
    with pytest.raises(ValidationError):
        ScanSpec(score_weights={"sector": 1})
    with pytest.raises(ValidationError):
        ScanSpec(sort_by="drop table")
    with pytest.raises(ValidationError):
        ScanSpec(limit=0)


async def test_engine_filters_scores_and_is_reproducible():
    spec = presets.PRESETS["momentum_breakout"]["spec"]
    src = Fake(UNIVERSE)
    r1 = await engine.run(spec, src, ["BRK", "QUIET", "SHORT", "FALL", "MISSING"])
    r2 = await engine.run(spec, src, ["BRK", "QUIET", "SHORT", "FALL", "MISSING"])
    assert [x["symbol"] for x in r1["results"]] == ["BRK"]
    assert r1["results"] == r2["results"]                                   # deterministic
    m = r1["meta"]
    assert (m["universe_size"], m["with_data"], m["failed"], m["insufficient_history"], m["matched"]) == (5, 4, 1, 1, 1)
    assert m["coverage_pct"] == 80.0 and m["failed_sample"] == {"MISSING": "no data returned"} and "fake source" in m["notes"]
    assert m["status"] == "HISTORICAL" and m["latest_bar_date"]


async def test_bearish_breakdown_preset_and_custom_spec():
    r = await engine.run(presets.PRESETS["bearish_breakdown"]["spec"], Fake(UNIVERSE), ["BRK", "FALL", "QUIET"])
    assert [x["symbol"] for x in r["results"]] == ["FALL"] and r["results"][0]["setup"] == "Breakdown"
    spec = ScanSpec(filters=[Filter(field="rvol", op=">=", value=0.5)], sort_by="rvol", limit=2)
    r = await engine.run(spec, Fake(UNIVERSE), ["BRK", "QUIET", "FALL"])
    assert [x["symbol"] for x in r["results"]] == ["BRK", "FALL"]            # sorted by rvol desc, limited
    assert all(x["score"] is None for x in r["results"])                    # no weights -> no score claimed


def test_score_breakdown_is_transparent_and_sums():
    rows = [{"rvol": 1.0, "rs_21d": 5.0}, {"rvol": 3.0, "rs_21d": 1.0}, {"rvol": 2.0, "rs_21d": None}]
    engine.rank_scores(rows, {"rvol": 1, "rs_21d": -1})                     # negative weight: lower is better
    for r in rows:
        assert r["score"] == pytest.approx(sum(p["contribution"] for p in r["score_breakdown"]), abs=0.1)
    assert rows[1]["score_breakdown"][0]["percentile"] == 100 and rows[0]["score_breakdown"][1]["percentile"] == 100
    assert rows[2]["score_breakdown"][1]["percentile"] is None and rows[2]["score_breakdown"][1]["contribution"] == 0   # missing factor penalised


def test_every_preset_is_valid_and_uses_liquidity_floor():
    assert len(presets.PRESETS) == 7
    for p in presets.PRESETS.values():
        assert p["spec"].filters[0].field == "dollar_volume_avg20" and p["spec"].score_weights


def test_natural_language_translation_and_honesty():
    r = nl.translate("Show me technology stocks above their 50-day moving average with relative volume above 2")
    assert r["ok"]
    rules = {(f["field"], f["op"], str(f["value"])) for f in r["spec"]["filters"]}
    assert ("above_sma50", "==", "True") in rules and ("rvol", ">=", "2.0") in rules and ("sector", "in", "['Technology']") in rules
    r = nl.translate("Find stocks outperforming QQQ over the last month but pulling back today")
    assert r["spec"]["benchmark"] == "QQQ" and {f["field"] for f in r["spec"]["filters"]} == {"rs_21d", "change_pct"}
    r = nl.translate("Find profitable technology companies above their 50-day moving average")
    assert r["ok"] and any("fundamentals" in u for u in r["unsupported"])       # 'profitable' is reported, not silently dropped
    r = nl.translate("Find liquid stocks with bearish MACD divergence")
    assert any("divergence" in u for u in r["unsupported"])
    r = nl.translate("what is the weather")
    assert not r["ok"] and r["spec"] is None
    r = nl.translate("technology stocks breaking above their 20-day highs on unusually high volume")
    assert {f["field"] for f in r["spec"]["filters"]} == {"breakout_20", "rvol", "sector"}


def test_scan_command_routing():
    assert commands.resolve("SCAN BREAKOUT").params == {"preset": "momentum_breakout"}
    assert commands.resolve("SCAN NEWS CATALYST").implemented is False
    bad = commands.resolve("SCAN BREAKUOT")
    assert not bad.ok and "BREAKOUT" in bad.suggestions


def test_directory_parsing_drops_tests_etfs_and_deficient():
    nasdaq = ("Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
              "AAPL|Apple|Q|N|N|100|N|N\nZZZZT|Test co|Q|Y|N|100|N|N\nQQQ|Invesco|G|N|N|100|Y|N\nBADCO|Bad|S|N|D|100|N|N\n"
              "File Creation Time: 1030202617:00|||||||\n")
    other = ("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
             "BRK.B|Berkshire|N|BRK.B|N|100|N|BRK.B\nSPY|SPDR|P|SPY|Y|100|N|SPY\nTEST|x|N|TEST|N|100|Y|TEST\nWEIRD$A|x|N|W|N|100|N|W\n")
    assert universe.parse_directory(nasdaq, other) == ["AAPL", "BRK-B"]
    assert "QQQ" in universe.parse_directory(nasdaq, other, include_etfs=True)


async def test_universe_unavailable_without_network(monkeypatch, tmp_path):
    import httpx

    monkeypatch.chdir(tmp_path)
    c = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(universe.UniverseUnavailable):
        await universe.load("us_listed", c)
    with pytest.raises(universe.UniverseUnavailable):
        await universe.load("nonsense")


# --- API ----------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    # `with` keeps one event loop alive for the whole test: scan jobs are background asyncio tasks
    with TestClient(create_app(db_path=str(tmp_path / "s.db"), demo=False, providers={}, bar_source=Fake(UNIVERSE), alert_loop=False)) as c:
        c.app.state.scan_universes["core"] = ["BRK", "QUIET", "SHORT", "FALL"]
        yield c


def wait(client, jid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/scanner/jobs/{jid}").json()["data"]
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("scan did not finish")


def test_api_run_preset_job_and_results_link_to_instruments(client):
    jid = client.post("/api/scanner/run", json={"preset": "breakout"}).json()["data"]["job_id"]   # alias
    j = wait(client, jid)
    assert j["status"] == "done" and j["total"] == 5 and j["done"] == 5
    r = j["result"]["results"][0]
    assert r["symbol"] == "BRK" and r["instrument_id"] == "EQUITY:US:BRK" and r["score_breakdown"]
    assert client.get("/api/scanner/runs").json()["data"][0]["matched"] == 1


def test_api_errors_and_unavailable_presets(client):
    assert client.post("/api/scanner/run", json={"preset": "news_catalyst"}).json()["error"]["code"] == "PRESET_NOT_AVAILABLE"
    assert client.post("/api/scanner/run", json={"preset": "zzz"}).status_code == 404
    bad = client.post("/api/scanner/run", json={"spec": {"filters": [{"field": "nope", "op": ">", "value": 1}]}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_SPEC" and "unknown field" in bad.json()["error"]["message"]
    assert client.post("/api/scanner/run", json={"spec": {"universe": "mars"}}).status_code == 422
    assert client.post("/api/scanner/run", json={}).status_code == 422
    assert client.get("/api/scanner/jobs/none").status_code == 404


def test_api_us_listed_unreachable_is_explicit(client, monkeypatch):
    async def boom(u):
        raise universe.UniverseUnavailable("directory unreachable")
    monkeypatch.setattr("atlas_api.scanner.universe.load", boom)
    r = client.post("/api/scanner/run", json={"spec": {"universe": "us_listed", "filters": []}})
    assert r.status_code == 503 and r.json()["error"]["code"] == "UNIVERSE_UNAVAILABLE"


def test_api_saved_scans_persist_across_restart(tmp_path):
    path = str(tmp_path / "p.db")
    spec = {"filters": [{"field": "rvol", "op": ">=", "value": 2}], "score_weights": {"rvol": 1}}
    c = TestClient(create_app(db_path=path, demo=False, providers={}, bar_source=Fake(UNIVERSE)))
    assert c.post("/api/scanner/save", json={"name": "My RVOL", "spec": spec}).json()["ok"]
    assert c.post("/api/scanner/save", json={"name": "Bad", "spec": {"filters": [{"field": "x", "op": ">", "value": 1}]}}).status_code == 422
    c2 = TestClient(create_app(db_path=path, demo=False, providers={}, bar_source=Fake(UNIVERSE)))
    saved = c2.get("/api/scanner/saved").json()["data"]
    assert [s["name"] for s in saved] == ["My RVOL"] and saved[0]["spec"]["filters"][0]["field"] == "rvol"
    c2.delete(f"/api/scanner/saved/{saved[0]['id']}")
    assert c2.get("/api/scanner/saved").json()["data"] == []


def test_api_nl_and_catalog(client):
    r = client.post("/api/scanner/nl", json={"text": "stocks with relative volume above 3"}).json()["data"]
    assert r["ok"] and r["rules"]
    p = client.get("/api/scanner/presets").json()["data"]
    assert len(p["presets"]) == 7 and set(p["unavailable"]) == {"news_catalyst", "earnings_momentum", "sector_rotation"}
    assert "rvol" in client.get("/api/scanner/fields").json()["data"]


def test_demo_mode_scans_core_universe_and_labels_data(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=True, alert_loop=False)) as c:
        jid = c.post("/api/scanner/run", json={"spec": {"filters": [{"field": "price", "op": ">", "value": 0}], "limit": 500}}).json()["data"]["job_id"]
        j = wait(c, jid, 30)
        assert j["status"] == "done" and j["result"]["meta"]["status"] == "DEMO" and j["result"]["meta"]["matched"] > 50
        assert c.post("/api/scanner/run", json={"spec": {"universe": "us_listed"}}).json()["error"]["code"] == "DEMO_UNIVERSE"
