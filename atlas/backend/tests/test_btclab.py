"""BTC Strategy Lab: engine accounting (fees, slippage, stops, funding, liquidation, no look-ahead), indicators, evaluation honesty, data handling, API."""
import asyncio
import math

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.btclab import data as D
from atlas_api.btclab import evaluate as E
from atlas_api.btclab import strategies as ST
from atlas_api.btclab.engine import Costs, simulate
from atlas_api.btclab.service import demo_funding, demo_rows
from atlas_api.db import DB


def arrays(prices, spread=0.0):
    """Flat bars: open = previous close, so fills happen at known prices."""
    c = np.array(prices, float)
    o = np.r_[c[0], c[:-1]]
    return np.arange(len(c)) * 86400.0, o, np.maximum(o, c) * (1 + spread), np.minimum(o, c) * (1 - spread), c


def sim(prices, target, costs=None, funding=None, spread=0.0):
    t, o, h, l, c = arrays(prices, spread)
    return simulate(t, o, h, l, c, np.array(target, float), costs or Costs(fee_bps=0, slippage_bps=0), 0, len(c), funding)


def test_signal_acts_on_the_next_open_not_the_same_bar():
    # decide at the close of bar 1 (target[1]=1); the fill is bar 2's open, which equals bar 1's close = 110 here
    r = sim([100, 110, 121, 133.1], [0, 1, 1, 1])
    assert r["trades"][0]["entry_px"] == pytest.approx(110.0) and r["trades"][0]["open"]
    assert r["curve"][-1] == pytest.approx(133.1 / 110)          # gains from bar 2 onward only, not the 10% already made on bar 1


def test_round_trip_costs_are_exact():
    c = Costs(fee_bps=10, slippage_bps=20)                        # 0.10% fee and 0.20% slippage per side
    r = sim([100, 100, 100, 100, 100], [1, 1, 0, 0, 0], c)
    entry = 100 * 1.002
    exit_ = 100 * 0.998
    gross = exit_ / entry - 1
    expect = 1 - 0.001 + gross - 0.001 * (1 + gross)            # entry fee on the starting notional, exit fee on the notional at exit
    assert r["curve"][-1] == pytest.approx(expect, rel=1e-6)
    assert r["trades"][0]["reason"] == "signal" and r["fees_paid_pct"] > 0


def test_spot_never_shorts_but_perps_do():
    prices = [100, 100, 90, 81, 81]
    spot = sim(prices, [-1, -1, -1, -1, -1])
    assert spot["trades"] == [] and spot["curve"][-1] == 1.0
    perp = sim(prices, [-1, -1, -1, -1, -1], Costs(fee_bps=0, slippage_bps=0, perp=True), funding=[0] * 5)
    assert perp["curve"][-1] == pytest.approx(1 + (1 - 81 / 100), rel=1e-6)


def test_stop_fills_at_the_stop_price_or_worse_at_a_gap():
    t, o, h, l, c = (np.arange(4) * 86400.0, np.array([100, 100, 100, 100.0]), np.array([100, 101, 100, 100.0]), np.array([100, 94, 100, 100.0]), np.array([100, 95, 95, 95.0]))
    r = simulate(t, o, h, l, c, np.array([1, 1, 1, 1.0]), Costs(fee_bps=0, slippage_bps=0, stop_pct=5), 0, 4)
    assert r["trades"][0]["reason"] == "stop" and r["trades"][0]["exit_px"] == pytest.approx(95.0)
    o2 = np.array([100, 100, 90, 90.0])                           # gaps down through the stop on bar 2
    h2, l2, c2 = np.array([100, 100, 91, 91.0]), np.array([100, 99, 89, 89.0]), np.array([100, 100, 90, 90.0])
    r2 = simulate(t, o2, h2, l2, c2, np.array([1, 1, 1, 1.0]), Costs(fee_bps=0, slippage_bps=0, stop_pct=5), 0, 4)
    assert r2["trades"][0]["exit_px"] == pytest.approx(90.0)      # the open, not the 95 stop


def test_funding_is_paid_by_longs_and_received_by_shorts():
    p = [100] * 6
    f = [0.001] * 6
    c = Costs(fee_bps=0, slippage_bps=0, perp=True)
    long_ = sim(p, [1] * 6, c, f)
    short = sim(p, [-1] * 6, c, f)
    assert long_["curve"][-1] < 1 < short["curve"][-1]
    assert long_["funding_paid_pct"] > 0 > short["funding_paid_pct"]
    assert sim(p, [1] * 6, Costs(fee_bps=0, slippage_bps=0), f)["curve"][-1] == 1.0       # spot ignores funding


def test_leverage_scales_returns_and_liquidation_wipes_the_account():
    p = [100, 100, 110, 110]
    two = sim(p, [1, 1, 1, 1], Costs(fee_bps=0, slippage_bps=0, perp=True, leverage=2.0), funding=[0] * 4)
    assert two["curve"][-1] == pytest.approx(1.2)
    t, o, h, l, c = (np.arange(4) * 86400.0, np.array([100, 100, 100, 70.0]), np.array([100, 100, 100, 70.0]), np.array([100, 100, 60.0, 60.0]), np.array([100, 100, 70.0, 70.0]))
    r = simulate(t, o, h, l, c, np.array([1, 1, 1, 1.0]), Costs(fee_bps=0, slippage_bps=0, perp=True, leverage=3.0), 0, 4, [0] * 4)
    assert r["liquidated"] and r["curve"][-1] == 0.0 and r["trades"][-1]["reason"] == "liquidated"


def test_indicators_are_causal():
    rng = np.random.default_rng(3)
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))))
    df = pd.DataFrame({"o": c.shift(1).fillna(c.iloc[0]), "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1.0})
    for sid, s in ST.S.items():
        if s.requires_funding:
            continue
        full = s.build(df, s.params).to_numpy()
        cut = s.build(df.iloc[:300], s.params).to_numpy()
        assert np.array_equal(full[:300], cut), f"{sid} changes its past decisions when future bars are added (look-ahead)"


def test_library_is_complete_and_honest():
    assert 12 <= len(ST.S) <= 25
    for s in ST.S.values():
        assert s.entry and s.exit and s.stop and s.sizing and s.params and s.grid and s.family
        assert len(next(iter(s.grid.values()))) == 5
    assert len(ST.DEFAULT_FIVE) == 5 and all(i in ST.S for i in ST.DEFAULT_FIVE)


def test_evaluation_flags_too_few_trades_and_losers_and_is_deterministic():
    rows = demo_rows("1d")
    req = dict(strategies=list(ST.S), timeframe="1d", market="spot", leverage=1.0, long_short=False, fee_bps=5, slippage_bps=5)
    a = E.run_lab(rows, None, req)
    b = E.run_lab(rows, None, req)
    assert a == b
    assert a["skipped"][0]["id"] == "funding_fade"
    for r in a["results"]:
        ev = r["evidence"]
        assert ev["level"] in ("none", "weak", "moderate") and ev["reasons"]
        if r["out_of_sample"]["trades"] < E.MIN_TRADES:
            assert ev["level"] == "none" and any("too few" in x for x in ev["reasons"])
        if (r["out_of_sample"]["net_return_pct"] or 0) <= 0:
            assert ev["level"] == "none"
        assert r["now"]["rule_position"] in ("long", "flat") and "not a prediction" in r["now"]["note"]
    levels = [E.EVIDENCE_RANK[r["evidence"]["level"]] for r in a["results"]]
    assert levels == sorted(levels, reverse=True)                 # ranked by evidence first
    assert any("few market cycles" in c or "few market cycles" in c.lower() for c in a["caveats"])


def test_perp_run_needs_funding_and_reports_the_shorter_window():
    rows = demo_rows("1d")
    base = dict(strategies=["sma_cross", "funding_fade"], timeframe="1d", market="perp", leverage=2.0, long_short=True, fee_bps=5, slippage_bps=5)
    with pytest.raises(E.LabError, match="funding"):
        E.run_lab(rows, None, base)
    out = E.run_lab(rows, demo_funding(rows), base)
    assert {r["id"] for r in out["results"]} == {"sma_cross", "funding_fade"} and out["settings"]["leverage"] == 2.0
    assert any("funding from" in n for n in out["notes"])


def test_too_little_history_is_refused():
    with pytest.raises(E.LabError, match="at least 250"):
        E.run_lab(demo_rows("1d")[:100], None, dict(strategies=["sma_cross"], timeframe="1d", market="spot", leverage=1.0, long_short=False, fee_bps=5, slippage_bps=5))


def test_4h_bars_are_built_only_from_complete_hours():
    hrs = [(i * 3600, 1.0 + i, 2.0 + i, 0.5 + i, 1.5 + i, 1.0) for i in range(10)]
    out = D.resample_4h(hrs)
    assert [b[0] for b in out] == [0, 14400] and out[0][1] == 1.0 and out[0][4] == 4.5 and out[0][2] == 5.0 and out[0][3] == 0.5 and out[0][5] == 4.0
    assert D.resample_4h(hrs[1:]) == [(14400, 5.0, 9.0, 4.5, 8.5, 4.0)]            # the incomplete first window (hours 1-3) is dropped


def test_gap_detection_reports_missing_bars():
    rows = [(0, 1, 1, 1, 1, 1), (86400, 1, 1, 1, 1, 1), (86400 * 4, 1, 1, 1, 1, 1)]
    g = D.gaps(rows, 86400)
    assert len(g) == 1 and g[0]["missing_bars"] == 2


def test_data_refresh_pages_incrementally_and_stores_funding(tmp_path):
    db = DB(str(tmp_path / "b.db"))
    calls = []

    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if "candles" in str(req.url):
            start = int(pd.Timestamp(req.url.params["start"]).timestamp())
            return httpx.Response(200, json=[[start + 86400 * i, 99, 101, 100, 100.5, 5] for i in range(3)] if start < 1.9e9 else [])
        import json as _j
        since = _j.loads(req.content)["startTime"]
        rows = [{"coin": "BTC", "fundingRate": "0.0001", "premium": "0", "time": 1700000000000 + 3600000 * i} for i in range(3)]
        return httpx.Response(200, json=[x for x in rows if x["time"] >= since])          # like the real API: only rows from startTime on
    d = D.BtcData(db, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(d.refresh_funding()) == 3 and len(d.funding()) == 3
    assert d.funding()[0] == (1700000000, 0.0001)
    assert asyncio.run(d.refresh_funding()) == 0                    # second call asks only for newer data and stores nothing new


def test_api_validates_and_runs_in_demo_mode(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        s = c.get("/api/btclab/strategies").json()["data"]
        assert len(s["strategies"]) >= 12 and s["max_leverage"] == 3.0 and s["defaults"] == ST.DEFAULT_FIVE
        assert s["findings"]["as_of"] and len(s["findings"]["points"]) >= 3 and "not recommendations" in " ".join(s["findings"]["points"])
        assert c.post("/api/btclab/run", json={"leverage": 5}).status_code == 422                 # never above 3x
        assert c.post("/api/btclab/run", json={"strategies": ["nope"]}).status_code == 422
        assert c.post("/api/btclab/run", json={"strategies": ["sma_cross", "sma_cross"]}).status_code == 422
        r = c.post("/api/btclab/run", json={})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["findings"]["as_of"] and len(d["results"]) == 5 and d["data"]["status"] == "DEMO" and "DEMO" in d["data"]["source"] and d["caveats"]
        assert c.post("/api/btclab/run", json={"market": "perp", "leverage": 3, "long_short": True, "strategies": ["sma_cross"]}).status_code == 200
        spot = c.post("/api/btclab/run", json={"market": "spot", "leverage": 3, "strategies": ["sma_cross"]}).json()["data"]
        assert spot["settings"]["leverage"] == 1.0                                              # spot is never leveraged


# --- judgement: luck check, capture, regimes -----------------------------------------------------------------------------------------------------
def test_sharpe_lower_bound_is_deterministic_and_gets_stricter_with_more_strategies():
    rng = np.random.default_rng(5)
    r = rng.normal(0.0015, 0.02, 700)
    one = E.sharpe_lower_bound(r, 365, 1, seed=1)
    ten = E.sharpe_lower_bound(r, 365, 20, seed=1)
    assert one == E.sharpe_lower_bound(r, 365, 1, seed=1)                      # same inputs, same answer
    assert ten["lower"] < one["lower"] and ten["confidence_pct"] > one["confidence_pct"]
    assert E.sharpe_lower_bound(r[:30], 365, 1, seed=1) is None                 # too little data to say anything
    assert E.sharpe_lower_bound(np.zeros(200), 365, 1, seed=1) is None          # no variation, no ratio


def test_pure_noise_does_not_clear_the_luck_check_but_a_real_edge_does():
    rng = np.random.default_rng(9)
    noise = rng.normal(0.0, 0.02, 600)
    edge = rng.normal(0.004, 0.01, 600)
    assert E.sharpe_lower_bound(noise, 365, 20, seed=2)["lower"] < 0
    assert E.sharpe_lower_bound(edge, 365, 20, seed=2)["lower"] > 0


def test_capture_ratios_describe_timing_value():
    rb = np.array([0.02, -0.02] * 30)
    assert E.capture(rb, rb) == {"up_pct": pytest.approx(100.0), "down_pct": pytest.approx(100.0)}      # holding captures everything
    flat = np.zeros(60)
    assert E.capture(flat, rb) == {"up_pct": pytest.approx(0.0), "down_pct": pytest.approx(0.0)}
    good_timing = np.where(rb > 0, rb, rb * 0.2)                                                         # keeps the ups, dodges most downs
    c = E.capture(good_timing, rb)
    assert c["up_pct"] == pytest.approx(100.0) and c["down_pct"] == pytest.approx(20.0)
    assert E.capture(rb[:10], rb[:10]) is None


def test_regimes_split_by_the_previous_bars_trend_and_hide_thin_samples():
    rows = demo_rows("1d")
    f = E.Frame(rows, "1d", None, False)
    bh = E.buy_and_hold(f, dict(fee_bps=0, slippage_bps=0), f.first, f.last)
    r = E.regimes(f, bh, bh, f.first, f.last)
    assert set(r) == {"uptrend", "downtrend"}
    for v in r.values():
        if v is not None:
            assert v["bars"] >= 60 and v["strategy_yearly_pct"] == pytest.approx(v["buy_hold_yearly_pct"])      # compared with itself: identical


def test_results_carry_judgement_and_never_claim_moderate_when_the_library_is_this_big():
    rows = demo_rows("1d")
    out = E.run_lab(rows, None, dict(strategies=["momentum_filtered"], timeframe="1d", market="spot", leverage=1.0, long_short=False, fee_bps=5, slippage_bps=5))
    r = out["results"][0]
    j = r["judgement"]
    assert "library" in j["note"]
    if j["sharpe_lower_bound"] is not None:
        assert j["sharpe_lower_bound"]["n_compared"] >= 20
    else:
        assert "Too few out-of-sample trades" in j["luck_check_note"]
    assert j["regimes"].keys() == {"uptrend", "downtrend"}
    if j["sharpe_lower_bound"] is not None and j["sharpe_lower_bound"]["lower"] <= 0:
        assert r["evidence"]["level"] != "moderate" and any("rule out luck" in x for x in r["evidence"]["reasons"])
    if j["sharpe_lower_bound"] is None:
        assert r["evidence"]["level"] == "none"                       # too few trades can never be better than "no reliable evidence"


def test_no_luck_check_is_shown_for_a_rule_with_too_few_trades():
    out = E.run_lab(demo_rows("1d"), None, dict(strategies=["momentum_roc"], timeframe="1d", market="spot", leverage=1.0, long_short=False, fee_bps=5, slippage_bps=5))
    r = out["results"][0]
    assert r["out_of_sample"]["trades"] < E.MIN_TRADES
    j = r["judgement"]
    assert j["sharpe_lower_bound"] is None and "Too few out-of-sample trades" in j["luck_check_note"] and str(E.MIN_TRADES) in j["luck_check_note"]
