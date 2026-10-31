import pytest

from atlas_api.backtest import engine, portfolio
from atlas_api.backtest.run import compute
from atlas_api.backtest.spec import BtSpec
from atlas_api.models import Candle
from atlas_api.scanner import features as feat
from atlas_api.scanner.rules import Filter

DAY = 86400
T0 = 1_700_000_000 - 1_700_000_000 % DAY


def bars(tail, flat=70, base=100.0):
    """`flat` quiet bars (high/low +-1%) then explicit (o,h,l,c) tail bars."""
    out = [Candle(time=T0 + i * DAY, open=base, high=base * 1.01, low=base * 0.99, close=base, volume=1e6) for i in range(flat)]
    for k, (o, h, l, c) in enumerate(tail):
        out.append(Candle(time=T0 + (flat + k) * DAY, open=o, high=h, low=l, close=c, volume=1e6))
    return out


def spec(**kw):
    base = dict(entry=[Filter(field="price", op=">", value=105)], stop_atr=None, commission_bps=0, slippage_bps=0, max_hold_bars=3, oos_fraction=0)
    base.update(kw)
    return BtSpec(**base)


SIGNAL = (100, 111, 100, 110)             # bar 70: close 110 > 105 fires the entry signal


def test_entry_is_next_open_and_time_exit_is_hand_checked():
    # signal at the close of bar 70; fill at the OPEN of bar 71 (112), never at the signal close (110)
    cs = bars([SIGNAL, (112, 113, 111, 112), (112, 114, 111, 113), (113, 116, 112, 115), (115, 116, 114, 115)])
    r = engine.simulate("X", cs, None, spec())
    assert len(r["trades"]) == 1
    t = r["trades"][0]
    assert t["entry_px"] == 112 and t["signal_date"] != t["entry_date"]
    # bars held 71,72,73 -> time exit at the close of bar 73 (115)
    assert t["exit_reason"] == "time" and t["exit_px"] == 115 and t["bars_held"] == 3
    assert t["net_pct"] == pytest.approx((115 / 112 - 1) * 100)


def test_costs_hit_both_sides():
    cs = bars([SIGNAL, (112, 113, 111, 112), (112, 114, 111, 113), (113, 116, 112, 115), (115, 116, 114, 115)])
    t = engine.simulate("X", cs, None, spec(slippage_bps=10, commission_bps=2))["trades"][0]
    assert t["entry_px"] == pytest.approx(112 * 1.001) and t["exit_px"] == pytest.approx(115 * 0.999)
    assert t["cost_pct"] == pytest.approx(0.04)
    assert t["net_pct"] == pytest.approx((115 * 0.999 / (112 * 1.001) - 1) * 100 - 0.04)


def _atr_at_signal(cs):
    return feat.compute("X", cs[:71])["atr_pct"] / 100 * 110


def test_stop_fills_at_stop_and_target_in_r():
    cs = bars([SIGNAL, (112, 113, 111, 112), (112, 113, 105, 106)])
    s = spec(stop_atr=1.0, max_hold_bars=10)
    t = engine.simulate("X", cs, None, s)["trades"][0]
    atr = _atr_at_signal(cs)
    assert t["stop"] == pytest.approx(112 - atr)
    assert t["exit_reason"] == "stop" and t["exit_px"] == pytest.approx(112 - atr)
    assert t["r_multiple"] == pytest.approx(-1.0)            # a stop-out with no costs is exactly -1R


def test_gap_through_stop_fills_at_the_open_not_the_stop():
    cs = bars([SIGNAL, (112, 113, 111, 112), (100, 101, 99, 100)])
    t = engine.simulate("X", cs, None, spec(stop_atr=1.0, max_hold_bars=10))["trades"][0]
    assert t["exit_reason"] == "stop" and t["exit_px"] == 100 and t["exit_px"] < t["stop"]
    assert t["r_multiple"] < -1


def test_stop_wins_when_stop_and_target_touch_in_one_bar():
    cs = bars([SIGNAL, (112, 113, 111, 112), (112, 140, 100, 120)])
    t = engine.simulate("X", cs, None, spec(stop_atr=1.0, target_r=1.0, max_hold_bars=10))["trades"][0]
    assert t["exit_reason"] == "stop"


def test_target_fills_at_target_and_gap_up_fills_at_open_without_slippage():
    cs = bars([SIGNAL, (112, 113, 111, 112), (112, 120, 111, 119)])
    atr = _atr_at_signal(cs)
    t = engine.simulate("X", cs, None, spec(stop_atr=1.0, target_r=1.0, max_hold_bars=10, slippage_bps=50))["trades"][0]
    fill = 112 * 1.005
    assert t["exit_reason"] == "target" and t["exit_px"] == pytest.approx(fill + atr)      # a limit: no slippage on the way out
    cs2 = bars([SIGNAL, (112, 113, 111, 112), (130, 131, 129, 130)])
    t2 = engine.simulate("X", cs2, None, spec(stop_atr=1.0, target_r=1.0, max_hold_bars=10))["trades"][0]
    assert t2["exit_px"] == 130


def test_short_side_mirrors():
    # signal: price < 95 -> short at the next open
    cs = bars([(100, 100, 89, 90), (88, 89, 87, 88), (88, 89, 84, 85), (85, 86, 83, 84), (84, 85, 83, 84)])
    t = engine.simulate("X", cs, None, spec(side="short", entry=[Filter(field="price", op="<", value=95)]))["trades"][0]
    assert t["entry_px"] == 88 and t["exit_px"] == 84                  # bars 71,72,73 held, exit at close of bar 73
    assert t["net_pct"] == pytest.approx((1 - 84 / 88) * 100)


def test_signal_on_last_bar_is_pending_not_a_trade():
    cs = bars([SIGNAL])
    r = engine.simulate("X", cs, None, spec())
    assert r["trades"] == [] and r["pending_signal"]["symbol"] == "X"


def test_open_position_at_end_is_reported_and_not_counted():
    cs = bars([SIGNAL, (112, 113, 111, 112), (112, 113, 111, 113)])
    r = engine.simulate("X", cs, None, spec(max_hold_bars=10))
    assert r["trades"] == [] and r["open_at_end"]["entry_px"] == 112 and r["open_at_end"]["last_close"] == 113


def test_missing_data_never_passes_a_rule():
    cs = bars([SIGNAL, (112, 113, 111, 112), (112, 114, 111, 113), (113, 116, 112, 115)])
    r = engine.simulate("X", cs, None, spec(entry=[Filter(field="rs_21d", op=">", value=-1000)]))   # no benchmark -> field is None
    assert r["trades"] == []


def test_no_lookahead_truncating_the_future_does_not_change_the_past():
    tail = [SIGNAL, (112, 113, 111, 112), (112, 114, 111, 113), (113, 116, 112, 115), (115, 116, 114, 115)] * 3
    # make the tail wiggle so several trades occur
    cs = bars([(o + (i % 4), h + (i % 4), l + (i % 4), c + (i % 4)) for i, (o, h, l, c) in enumerate(tail)])
    s = spec(stop_atr=1.5, max_hold_bars=2)
    full = engine.simulate("X", cs, None, s)["trades"]
    cut = len(cs) - 4
    part = engine.simulate("X", cs[:cut], None, s)["trades"]
    assert part, "need at least one trade for this check to mean anything"
    keyf = lambda t: (t["entry_t"], t["exit_t"], t["exit_px"])  # noqa: E731
    assert [keyf(t) for t in part] == [keyf(t) for t in full if t["exit_t"] <= cs[cut - 1].time][: len(part)]


# --- portfolio -----------------------------------------------------------------------------------------------------------------------
def tr(sym, et, xt, ep, xp, stop=None, side="long"):
    return {"symbol": sym, "side": side, "entry_t": et, "exit_t": xt, "entry_px": ep, "exit_px": xp, "stop": stop}


def closes(sym, px):
    return {sym: {T0 + i * DAY: p for i, p in enumerate(px)}}


def test_risk_sizing_and_cap():
    s = spec(initial_capital=100_000, risk_pct=1, max_position_pct=100)
    c = closes("A", [100, 100, 110])
    r = portfolio.run([tr("A", T0, T0 + 2 * DAY, 100, 110, stop=98)], c, s)
    t = r["trades"][0]
    assert t["qty"] == 500                                          # 1% of 100k = 1000 / 2 per share
    assert r["final_equity"] == pytest.approx(100_000 + 500 * 10)
    s2 = spec(initial_capital=100_000, risk_pct=1, max_position_pct=20)
    assert portfolio.run([tr("A", T0, T0 + 2 * DAY, 100, 110, stop=98)], c, s2)["trades"][0]["qty"] == 200   # capped by 20% of equity / price


def test_commission_is_charged_on_both_fills():
    s = spec(initial_capital=100_000, risk_pct=1, max_position_pct=100, commission_bps=10)
    r = portfolio.run([tr("A", T0, T0 + 2 * DAY, 100, 110, stop=98)], closes("A", [100, 100, 110]), s)
    assert r["final_equity"] == pytest.approx(100_000 + 5000 - 500 * 100 * 0.001 - 500 * 110 * 0.001)


def test_capacity_skips_are_counted_never_resized():
    s = spec(initial_capital=100_000, max_position_pct=20, max_positions=2)
    cl = {**closes("A", [100] * 5), **closes("B", [100] * 5), **closes("C", [100] * 5)}
    ts = [tr(x, T0, T0 + 3 * DAY, 100, 100) for x in "ABC"]
    r = portfolio.run(ts, cl, s)
    assert len(r["trades"]) == 2 and r["skipped"]["max_positions"] == 1
    assert {t["symbol"] for t in r["trades"]} == {"A", "B"}          # alphabetical tie-break


def test_gross_exposure_cap_blocks_leverage():
    s = spec(initial_capital=10_000, max_position_pct=100, max_positions=5)
    cl = {**closes("A", [100] * 4), **closes("B", [100] * 4)}
    r = portfolio.run([tr("A", T0, T0 + 3 * DAY, 100, 100), tr("B", T0, T0 + 3 * DAY, 100, 100)], cl, s)
    assert len(r["trades"]) == 1 and r["skipped"]["gross_exposure"] == 1


def test_daily_mark_to_market_drawdown_is_not_hidden_by_a_recovery():
    s = spec(initial_capital=100_000, risk_pct=1, max_position_pct=100)
    r = portfolio.run([tr("A", T0, T0 + 3 * DAY, 100, 100, stop=90)], closes("A", [100, 90, 100, 100]), s)
    assert r["final_equity"] == pytest.approx(100_000)               # round trip: flat at the end...
    assert r["metrics"]["max_drawdown_pct"] < -0.5                   # ...but the dip on the way is in the drawdown
    assert min(x["equity"] for x in r["curve"]) < 100_000


def test_short_pnl_sign():
    s = spec(initial_capital=100_000, risk_pct=1, max_position_pct=100)
    r = portfolio.run([tr("A", T0, T0 + 2 * DAY, 100, 90, stop=102, side="short")], closes("A", [100, 95, 90]), s)
    assert r["trades"][0]["qty"] < 0 and r["trades"][0]["pnl"] > 0
    assert r["final_equity"] == pytest.approx(100_000 + 500 * 10)


def test_metrics_hand_values():
    ts = [T0 + i * DAY for i in range(4)]
    m = portfolio.metrics(ts, [100, 110, 99, 120])
    assert m["total_return_pct"] == pytest.approx(20) and m["max_drawdown_pct"] == pytest.approx(-10)
    assert m["cagr_pct"] is None                                      # < 3 months: not annualised


# --- compute -------------------------------------------------------------------------------------------------------------------------
def test_compute_reports_split_reliability_and_open_signals():
    cs = bars([SIGNAL, (112, 113, 111, 112), (112, 114, 111, 113), (113, 116, 112, 115), (115, 116, 114, 115)])
    r = compute(spec(oos_fraction=0.2), {"X": cs}, ["X"], None)
    assert r["summary"]["n"] == 1 and r["summary"]["reliable"] is False
    assert r["split"]["cutoff_date"] and r["symbols_traded"] == 1
    assert "max_drawdown" not in r["summary"]
    assert r["portfolio"]["metrics"]["days"] >= 3


# --- API -----------------------------------------------------------------------------------------------------------------------------
import time  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from atlas_api.app import create_app  # noqa: E402
from atlas_api.models import DataStatus  # noqa: E402
from atlas_api.scanner.bars import BarBatch  # noqa: E402


class FakeBars:
    name = "fake"

    def __init__(self, data):
        self.data = data

    async def fetch(self, symbols, progress=None):
        got = {s: self.data[s] for s in symbols if s in self.data}
        return BarBatch(got, {s: "no data returned" for s in symbols if s not in self.data}, "fake", DataStatus.HISTORICAL, None, ["fake source"])


@pytest.fixture
def client(tmp_path):
    cs = bars([SIGNAL, (112, 113, 111, 112), (112, 114, 111, 113), (113, 116, 112, 115), (115, 116, 114, 115)])
    flat = bars([])
    with TestClient(create_app(db_path=str(tmp_path / "b.db"), demo=False, providers={}, bar_source=FakeBars({"AAA": cs, "BBB": flat, "SPY": flat}), alert_loop=False)) as c:
        c.app.state.scan_universes["core"] = ["AAA", "BBB"]
        yield c


def wait(client, jid):
    for _ in range(100):
        j = client.get(f"/api/backtest/jobs/{jid}").json()["data"]
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


RULE = [{"field": "price", "op": ">", "value": 105}]


def test_api_runs_saves_and_reopens(client):
    r = client.post("/api/backtest/run", json={"spec": {"name": "T", "entry": RULE, "stop_atr": None, "max_hold_bars": 3, "oos_fraction": 0,
                                                         "commission_bps": 0, "slippage_bps": 0}})
    j = wait(client, r.json()["data"]["job_id"])
    assert j["status"] == "done", j["error"]
    res = j["result"]
    assert res["summary"]["n"] == 1 and res["meta"]["provider"] == "fake" and res["meta"]["caveats"]
    assert res["meta"]["universe_size"] == 2 and res["symbols_traded"] == 1
    again = client.get(f"/api/backtest/runs/{j['run_id']}").json()["data"]["result"]
    assert again["summary"]["n"] == 1
    assert client.get("/api/backtest/runs").json()["data"][0]["trades"] == 1
    assert client.delete(f"/api/backtest/runs/{j['run_id']}").json()["ok"]
    assert client.get(f"/api/backtest/runs/{j['run_id']}").status_code == 404


def test_api_rejects_bad_specs(client):
    for bad in ({"entry": []}, {"entry": RULE, "target_r": 2, "stop_atr": None}, {"entry": RULE, "bogus": 1},
                {"entry": [{"field": "nope", "op": ">", "value": 1}]}, {"entry": RULE, "max_hold_bars": 0}):
        r = client.post("/api/backtest/run", json={"spec": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_SPEC", bad
    assert client.post("/api/backtest/run", json={}).status_code == 422
    assert client.post("/api/backtest/run", json={"preset": "news_catalyst"}).status_code == 501
    assert client.post("/api/backtest/run", json={"preset": "nope"}).status_code == 404


def test_api_presets_and_preset_run(client):
    p = client.get("/api/backtest/presets").json()["data"]
    ids = {x["id"] for x in p["presets"]}
    assert {"momentum_breakout", "bearish_breakdown"} <= ids and p["caveats"]
    assert next(x for x in p["presets"] if x["id"] == "bearish_breakdown")["spec"]["side"] == "short"
    r = client.post("/api/backtest/run", json={"preset": "BREAKOUT", "overrides": {"max_hold_bars": 5}})
    assert wait(client, r.json()["data"]["job_id"])["status"] == "done"


def test_parallel_path_equals_serial_path():
    from atlas_api.backtest import run as bt

    tail = [SIGNAL, (112, 113, 111, 112), (112, 114, 111, 113), (113, 116, 112, 115), (115, 116, 114, 115)] * 4
    data = {f"S{i}": bars([(o + (i + k) % 5, h + (i + k) % 5, l + (i + k) % 5, c + (i + k) % 5) for k, (o, h, l, c) in enumerate(tail)]) for i in range(10)}
    s = spec(stop_atr=1.5, max_hold_bars=3)
    syms = sorted(data)
    par = bt.compute(s, data, syms, None)
    old = bt.PARALLEL_MIN
    bt.PARALLEL_MIN = 10_000
    try:
        ser = bt.compute(s, data, syms, None)
    finally:
        bt.PARALLEL_MIN = old
    assert par["compute_mode"].startswith("parallel") and ser["compute_mode"] == "serial"   # the pool really ran, it did not fall back
    assert par["trades"] and par["trades"] == ser["trades"] and par["summary"] == ser["summary"]


def test_api_trades_carry_catalog_instrument_ids(client):
    r = client.post("/api/backtest/run", json={"spec": {"name": "T", "entry": RULE, "stop_atr": None, "max_hold_bars": 3, "oos_fraction": 0}})
    j = wait(client, r.json()["data"]["job_id"])
    assert j["result"]["trades"][0]["instrument_id"].startswith("EQUITY:")
    saved = client.get(f"/api/backtest/runs/{j['run_id']}").json()["data"]["result"]
    assert saved["trades"][0]["instrument_id"] == j["result"]["trades"][0]["instrument_id"]
