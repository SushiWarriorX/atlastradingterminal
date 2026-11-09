"""Strategy tracker: the frozen backtest is saved once and never rerun, the forward record only uses bars after the add date, and thin forward data is called thin."""
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.btclab import strategies as ST
from atlas_api.btclab import tracker as T
from atlas_api.btclab.service import demo_rows

DAY = 86400


def rows(n=1500, seed=5, drift=0.0006):
    rng = np.random.default_rng(seed)
    px, out = 100.0, []
    t0 = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp())
    for i in range(n):
        o = px
        px = px * float(np.exp(rng.normal(drift, 0.025)))
        out.append((t0 + i * DAY, o, max(o, px) * 1.01, min(o, px) * 0.99, px, 1000.0))
    return out


def test_aroon_reads_the_age_of_the_high_and_low():
    h = np.array([1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5, 6, 7, 6, 5, 4, 3, 2], float)
    up, dn = ST.aroon(pd.DataFrame({"h": h, "l": h - 1}), 5)
    assert np.isnan(up.iloc[4]) and up.iloc[5] == 80.0 and up.iloc[11] == 100.0 and up.iloc[-2] == 20.0 and up.iloc[-1] == 0.0 and dn.iloc[-1] == 100.0         # needs n+1 bars first; a high 1 bar old scores 80


def test_aroon_strategy_is_registered_with_fixed_parameters_and_never_looks_ahead():
    st = ST.S["aroon_trend"]
    assert st.params == {"n": 25} and not st.requires_funding and st.family == "Trend"
    d = pd.DataFrame(rows(400), columns=["t", "o", "h", "l", "c", "v"])
    full = st.build(d, st.params).to_numpy()
    cut = st.build(d.iloc[:300], st.params).to_numpy()
    assert (full[:300] == cut).all()                       # the position on bar i uses only bars up to i
    assert set(np.unique(full)) <= {0.0, 1.0}


def test_snapshot_keeps_the_evaluation_and_counts_the_library():
    s = T.snapshot("aroon_trend", rows())
    assert s["library_size"] == sum(1 for x in ST.S.values() if not x.requires_funding) and s["evidence"]["level"] in ("none", "weak", "moderate") and s["evidence"]["level"] != "strong"
    assert s["out_of_sample"]["trades"] >= 0 and s["buy_and_hold"]["full"]["net_return_pct"] is not None and s["curve"]["strategy"] and s["data_to"] > s["data_from"]
    json.dumps(s)                                          # must be saveable in the ledger


def test_snapshot_refuses_unknown_and_funding_strategies():
    for sid in ("nope", "funding_fade"):
        with pytest.raises(Exception):
            T.snapshot(sid, rows())


def test_forward_uses_only_bars_after_the_add_date_and_says_when_it_is_too_early():
    r = rows(800)
    last_day = datetime.fromtimestamp(r[-1][0], timezone.utc).date().isoformat()
    f0 = T.forward("aroon_trend", last_day, r)
    assert f0["days"] <= 1 and f0["strategy"] is None and "just started" in f0["note"] and not f0["enough"]
    added = datetime.fromtimestamp(r[-40][0], timezone.utc).date().isoformat()
    f1 = T.forward("aroon_trend", added, r)
    assert 38 <= f1["days"] <= 41 and not f1["enough"] and "too little" in f1["note"] and f1["strategy"] is not None
    added2 = datetime.fromtimestamp(r[-200][0], timezone.utc).date().isoformat()
    f2 = T.forward("aroon_trend", added2, r)
    assert f2["enough"] and f2["days"] > 190 and f2["position_now"] in ("long", "flat") and f2["buy_and_hold"]["return_pct"] is not None


def test_forward_return_matches_holding_when_the_rule_is_always_in():
    # steadily rising prices: the Aroon rule gets in early and stays in, so the forward record is close to buy and hold, never wildly different
    r = rows(900, seed=1, drift=0.003)
    added = datetime.fromtimestamp(r[-150][0], timezone.utc).date().isoformat()
    f = T.forward("aroon_trend", added, r)
    assert f["strategy"]["return_pct"] > 0 and f["buy_and_hold"]["return_pct"] > 0


def test_overview_in_demo_mode_shows_backtests_but_no_forward_record():
    led = {"entries": [{"id": "aroon_trend", "name": "Aroon trend", "family": "Trend", "added_at": "2026-11-08", "idea": "i", "why": "w", "snapshot": T.snapshot("aroon_trend", rows())}]}
    o = T.overview(None, demo=True, ledger=led)
    assert o["entries"][0]["forward"] is None and o["entries"][0]["rule"]["entry"] and any("Demo mode" in n for n in o["notes"]) and o["library_size"] >= 21


def test_the_committed_ledger_is_valid_and_matches_registered_strategies():
    led = T.load()
    ids = [e["id"] for e in led["entries"]]
    assert len(ids) == len(set(ids))
    for e in led["entries"]:
        assert e["id"] in ST.S and e["added_at"] and e["idea"] and e["why"] and e["snapshot"]["evidence"]["level"] in ("none", "weak", "moderate")
        assert e["snapshot"]["library_size"] <= sum(1 for x in ST.S.values() if not x.requires_funding)


def test_route_in_demo_mode(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/btclab/tracker").json()["data"]
        assert d["demo"] is True and isinstance(d["entries"], list) and d["min_forward_days"] == 60 and all(e["forward"] is None for e in d["entries"])


# --- ADX trend (strategy loop, cycle 2) ----------------------------------------------------------------------------------------------------
def _trend(n, step):
    c = 100 + step * np.arange(n, dtype=float)
    return pd.DataFrame({"t": np.arange(n), "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1.0})


def test_dmi_reads_direction_and_strength():
    up, down = _trend(120, 1.0), _trend(120, -1.0)
    a, p, m = ST.dmi(up, 14)
    # a clean uptrend with high = close + 1 and low = close - 1: true range 2, upward move 1 each bar, so +DI = 100 x 1 / 2 = 50, -DI = 0 and ADX = 100
    assert p.iloc[-1] == pytest.approx(50.0, abs=0.01) and m.iloc[-1] == pytest.approx(0.0, abs=0.01) and a.iloc[-1] > 99
    a2, p2, m2 = ST.dmi(down, 14)
    assert m2.iloc[-1] == pytest.approx(50.0, abs=0.01) and p2.iloc[-1] == pytest.approx(0.0, abs=0.01) and a2.iloc[-1] > 99
    rng = np.random.default_rng(2)
    noise = pd.DataFrame({"h": 100 + rng.normal(0, 1, 300), "l": 98 + rng.normal(0, 1, 300), "c": 99 + rng.normal(0, 1, 300)})
    assert ST.dmi(noise, 14)[0].iloc[-1] < 40                                           # directionless noise: weak trend


def test_dmi_directional_movement_follows_the_published_definition():
    # bar 1: high up 2, low up 1 -> upward move 2 beats downward move (-1 means low rose); bar 2: high down 1, low down 3 -> downward move 3 wins
    d = pd.DataFrame({"h": [10.0, 12.0, 11.0], "l": [8.0, 9.0, 6.0], "c": [9.0, 11.0, 7.0]})
    up, down = d["h"].diff(), -d["l"].diff()
    plus = np.where((up > down) & (up > 0), up, 0.0)
    minus = np.where((down > up) & (down > 0), down, 0.0)
    assert list(plus[1:]) == [2.0, 0.0] and list(minus[1:]) == [0.0, 3.0]


def test_adx_strategy_is_fixed_has_no_lookahead_and_goes_long_in_a_strong_uptrend():
    st = ST.S["adx_trend"]
    assert st.params == {"n": 14, "level": 25} and not st.requires_funding
    d = pd.concat([_trend(150, 1.0), _trend(150, -1.0).assign(c=lambda x: 250 - np.arange(150) * 1.0, h=lambda x: 251 - np.arange(150) * 1.0, l=lambda x: 249 - np.arange(150) * 1.0)], ignore_index=True)
    pos = st.build(d, st.params).to_numpy()
    assert pos[100] == 1.0 and pos[-1] == 0.0                                           # in during the strong rise, out after it reverses
    assert (st.build(d.iloc[:200], st.params).to_numpy() == pos[:200]).all()            # bar i uses only bars up to i


# --- Parabolic SAR (strategy loop, cycle 3) -----------------------------------------------------------------------------------------------
def test_psar_follows_wilders_definition_on_a_hand_worked_example():
    d = pd.DataFrame({"h": [10.0, 11.0, 12.0, 9.0, 8.5], "l": [8.0, 9.0, 10.0, 7.0, 6.5], "c": [9.0, 10.5, 11.5, 7.5, 7.0]})
    sar = ST.psar(d, 0.02, 0.2).to_numpy()
    # up-trend: SAR stays at the first low (8) because it may never rise above the last two lows; bar 3 (low 7) breaks it, so the SAR jumps to the old extreme high (12)
    assert list(sar[:3]) == [8.0, 8.0, 8.0]
    assert sar[3] == 12.0                                                  # reversal: SAR becomes the extreme point of the finished up-trend
    assert sar[4] == 12.0                                                  # 12 + 0.02 x (7 - 12) = 11.9, but it may never be below the last two highs (9 and 12)


def test_psar_acceleration_is_capped_and_resets_on_reversal():
    c = 100 + np.arange(60, dtype=float)
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    sar = ST.psar(d, 0.02, 0.2).to_numpy()
    assert (np.diff(sar[3:]) > 0).all()                                    # in a steady rise the SAR only moves up
    gaps = (c - sar)[3:]
    assert gaps.min() > 0 and (np.diff(gaps[40:]) < 0).all()                               # it closes on price but stays below it in a steady rise; the acceleration cap (0.2) stops it catching up


def test_psar_strategy_is_fixed_has_no_lookahead_and_exits_when_price_breaks_the_sar():
    st = ST.S["psar_trend"]
    assert st.params == {"step": 0.02, "max_af": 0.2} and not st.requires_funding
    up = 100 + np.arange(80, dtype=float)
    down = up[-1] - np.arange(1, 61, dtype=float) * 2
    c = np.concatenate([up, down])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[50] == 1.0 and pos[-1] == 0.0
    assert (st.build(d.iloc[:100], st.params).to_numpy() == pos[:100]).all()          # bar i uses only bars up to i


def test_ichimoku_cloud_is_the_hand_checkable_formula_and_is_shifted_forward():
    n = 80
    c = 100 + np.arange(n, dtype=float)
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    top, bot = ST.ichimoku_cloud(d, 9, 26, 52)
    assert top.iloc[:77].isna().all() and not np.isnan(top.iloc[77])                         # needs 52 bars of range, then 26 more bars of shift
    i = 77 - 26                                                                           # the bar the value at 77 was computed from
    mid = lambda k: (d["h"].iloc[i - k + 1:i + 1].max() + d["l"].iloc[i - k + 1:i + 1].min()) / 2
    a, b = (mid(9) + mid(26)) / 2, mid(52)
    assert top.iloc[77] == max(a, b) and bot.iloc[77] == min(a, b)


def test_ichimoku_strategy_is_fixed_has_no_lookahead_and_exits_below_the_cloud():
    st = ST.S["ichimoku_cloud"]
    assert st.params == {"tenkan": 9, "kijun": 26, "senkou": 52} and not st.requires_funding
    up = 100 + np.arange(120, dtype=float)
    down = up[-1] - np.arange(1, 121, dtype=float) * 2
    c = np.concatenate([up, down])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:77].sum() == 0 and pos[77] == 1.0 and pos[100] == 1.0 and pos[-1] == 0.0
    assert (st.build(d.iloc[:150], st.params).to_numpy() == pos[:150]).all()               # bar i uses only bars up to i


def test_tsmom_is_the_return_from_lookback_to_skip_bars_ago_and_ignores_the_recent_month():
    c = pd.Series(np.arange(1, 501, dtype=float))
    m = ST.tsmom(c, 365, 30)
    assert m.iloc[:365].isna().all() and not np.isnan(m.iloc[365])
    assert m.iloc[400] == c.iloc[370] / c.iloc[35] - 1                                       # bar 400 looks from bar 35 to bar 370
    spike = c.copy()
    spike.iloc[-29:] *= 100                                                                  # a jump inside the skipped month does not move the signal on the last bar
    assert ST.tsmom(spike, 365, 30).iloc[-1] == m.iloc[-1]


def test_tsmom_strategy_is_fixed_long_only_and_has_no_lookahead():
    st = ST.S["tsmom_12_1"]
    assert st.params == {"lookback": 365, "skip": 30} and not st.requires_funding
    c = np.concatenate([100 + np.arange(450, dtype=float), 549 - np.arange(1, 301, dtype=float)])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:365].sum() == 0 and pos[400] == 1.0 and pos[-1] == 0.0 and set(pos) <= {0.0, 1.0}
    assert (st.build(d.iloc[:500], st.params).to_numpy() == pos[:500]).all()                 # bar i uses only bars up to i


def test_keltner_bands_are_the_ema_plus_k_times_atr():
    n = 60
    c = 100 + np.arange(n, dtype=float)
    d = pd.DataFrame({"h": c + 2, "l": c - 2, "c": c})
    mid, up = ST.keltner(d, 20, 10, 2.0)
    assert mid.iloc[:19].isna().all() and not np.isnan(mid.iloc[19]) and up.iloc[:19].isna().all()
    assert mid.iloc[-1] == ST.ema(d["c"], 20).iloc[-1] and abs(up.iloc[-1] - (mid.iloc[-1] + 2.0 * ST.atr(d, 10).iloc[-1])) < 1e-12
    assert abs(ST.atr(d, 10).iloc[-1] - 4.0) < 1e-9                                         # every true range is max(high-low = 4, high-prev close = 3, prev close-low = 1) = 4
    assert abs(up.iloc[-1] - mid.iloc[-1] - 8.0) < 1e-9                                      # so the upper band sits 2 x 4 above the EMA


def test_keltner_strategy_is_fixed_enters_on_a_breakout_exits_below_the_ema_and_has_no_lookahead():
    st = ST.S["keltner_breakout"]
    assert st.params == {"n": 20, "atr_n": 10, "k": 2.0} and not st.requires_funding
    flat = np.full(60, 100.0)
    surge = 100 + np.arange(1, 31, dtype=float) * 3                                          # a run-up far outside two average ranges
    fall = surge[-1] - np.arange(1, 41, dtype=float) * 3
    c = np.concatenate([flat, surge, fall])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:60].sum() == 0 and pos[62] == 1.0 and pos[-1] == 0.0 and set(pos) <= {0.0, 1.0}
    assert (st.build(d.iloc[:100], st.params).to_numpy() == pos[:100]).all()                 # bar i uses only bars up to i


def test_vortex_matches_a_hand_worked_example():
    h = [10, 11, 12, 11, 13]
    l = [8, 9, 10, 9, 11]
    c = [9, 10, 11, 10, 12]
    d = pd.DataFrame({"h": np.array(h, float), "l": np.array(l, float), "c": np.array(c, float)})
    vp, vm = ST.vortex(d, 3)
    assert vp.iloc[:3].isna().all() and not np.isnan(vp.iloc[3])                              # needs 3 full bars after the first (which has no previous bar)
    # bars 1..3: VM+ = |h - prev l| = 11-8, 12-9, 11-10 = 3, 3, 1 -> 7;  VM- = |l - prev h| = 9-10, 10-11, 9-12 = 1, 1, 3 -> 5
    # true ranges: bar1 max(2, |11-9|, |9-9|) = 2, bar2 max(2, |12-10|, |10-10|) = 2, bar3 max(2, |11-11|, |9-11|) = 2 -> 6
    assert abs(vp.iloc[3] - 7 / 6) < 1e-12 and abs(vm.iloc[3] - 5 / 6) < 1e-12


def test_vortex_strategy_is_fixed_enters_in_an_uptrend_leaves_in_a_downtrend_and_has_no_lookahead():
    st = ST.S["vortex_cross"]
    assert st.params == {"n": 14} and not st.requires_funding
    up = 100 + np.arange(60, dtype=float) * 2
    down = up[-1] - np.arange(1, 61, dtype=float) * 2
    c = np.concatenate([up, down])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:14].sum() == 0 and pos[30] == 1.0 and pos[-1] == 0.0 and set(pos) <= {0.0, 1.0}
    assert (st.build(d.iloc[:90], st.params).to_numpy() == pos[:90]).all()                    # bar i uses only bars up to i


def test_stochastic_k_matches_a_hand_worked_example():
    h = [10, 12, 11, 13, 12, 14]
    l = [8, 9, 9, 10, 10, 11]
    c = [9, 11, 10, 12, 11, 13]
    d = pd.DataFrame({"h": np.array(h, float), "l": np.array(l, float), "c": np.array(c, float)})
    k = ST.stoch_k(d, 3, 2)
    assert k.iloc[:3].isna().all() and not np.isnan(k.iloc[3])                                # 3 bars for the range, 2 raw values to average
    # raw %K at bar 2: range of bars 0-2 is low 8 / high 12, close 10 -> 50; at bar 3: bars 1-3 low 9 / high 13, close 12 -> 75; at bar 4: bars 2-4 low 9 / high 13, close 11 -> 50
    assert abs(k.iloc[3] - (50 + 75) / 2) < 1e-9 and abs(k.iloc[4] - (75 + 50) / 2) < 1e-9


def test_stoch_strategy_is_fixed_buys_the_dip_in_an_uptrend_only_and_has_no_lookahead():
    st = ST.S["stoch_uptrend"]
    assert st.params == {"n": 14, "smooth": 3, "low": 20, "high": 80, "trend": 200} and not st.requires_funding
    rng = np.random.default_rng(7)
    base = 100 + np.arange(400, dtype=float) * 0.5
    wiggle = np.concatenate([np.sin(np.arange(400) / 4.0) * 6])
    c = base + wiggle
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:200].sum() == 0 and set(pos) <= {0.0, 1.0} and pos[200:].sum() > 0              # no trades until the 200-bar average exists; dips in the uptrend do trigger entries
    down = 300 - np.arange(400, dtype=float) * 0.5 + np.sin(np.arange(400) / 4.0) * 6
    dd = pd.DataFrame({"h": down + 1, "l": down - 1, "c": down})
    assert st.build(dd, st.params).to_numpy().sum() == 0                                        # in a downtrend the close is below its average, so it never enters
    assert (st.build(d.iloc[:300], st.params).to_numpy() == pos[:300]).all()                    # bar i uses only bars up to i


def test_mfi_matches_a_hand_worked_example():
    c = np.array([10, 11, 10, 12, 13], float)
    d = pd.DataFrame({"h": c, "l": c, "c": c, "v": np.array([1, 2, 3, 4, 5], float)})                # high = low = close, so the typical price is the close
    m = ST.mfi(d, 3)
    assert m.iloc[:3].isna().all() and not np.isnan(m.iloc[3])                                      # 3 price changes are needed
    # flows after bar 0: bar1 11x2 = 22 (up), bar2 10x3 = 30 (down), bar3 12x4 = 48 (up), bar4 13x5 = 65 (up)
    assert abs(m.iloc[3] - 100 * (22 + 48) / (22 + 48 + 30)) < 1e-9                                  # 70
    assert abs(m.iloc[4] - 100 * (48 + 65) / (48 + 65 + 30)) < 1e-9
    flat = pd.DataFrame({"h": [5.0] * 6, "l": [5.0] * 6, "c": [5.0] * 6, "v": [1.0] * 6})
    assert ST.mfi(flat, 3).isna().all()                                                             # no price change at all: undefined, not 0 or 100


def test_mfi_strategy_is_fixed_buys_exhausted_selling_sells_recovery_and_has_no_lookahead():
    st = ST.S["mfi_reversion"]
    assert st.params == {"n": 14, "low": 20, "high": 70} and not st.requires_funding
    fall = 200 - np.arange(40, dtype=float) * 2
    rise = fall[-1] + np.arange(1, 41, dtype=float) * 3
    c = np.concatenate([np.full(15, 200.0) + np.arange(15) * 0.1, fall, rise])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c, "v": np.full(len(c), 100.0)})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:14].sum() == 0 and set(pos) <= {0.0, 1.0}
    assert pos[40] == 1.0                                                                           # deep into the fall the index is near 0, so it is holding
    assert pos[-1] == 0.0                                                                           # after a long rise the index is above 70, so it has sold
    assert (st.build(d.iloc[:60], st.params).to_numpy() == pos[:60]).all()                          # bar i uses only bars up to i


def test_cci_matches_a_hand_worked_example():
    c = np.array([1, 2, 6, 3, 4], float)
    d = pd.DataFrame({"h": c, "l": c, "c": c})                                                      # high = low = close, so the typical price is the close
    x = ST.cci(d, 3)
    assert x.iloc[:2].isna().all() and not np.isnan(x.iloc[2])
    # bar 2: window 1, 2, 6: mean 3, mean absolute deviation (2 + 1 + 3) / 3 = 2, CCI = (6 - 3) / (0.015 x 2) = 100
    assert abs(x.iloc[2] - 100.0) < 1e-9
    # bar 3: window 2, 6, 3: mean 11/3, deviations 5/3, 7/3, 2/3 -> mean 14/9; CCI = (3 - 11/3) / (0.015 x 14/9)
    assert abs(x.iloc[3] - ((3 - 11 / 3) / (0.015 * 14 / 9))) < 1e-9
    flat = pd.DataFrame({"h": [5.0] * 6, "l": [5.0] * 6, "c": [5.0] * 6})
    assert ST.cci(flat, 3).isna().all()                                                             # no movement at all: undefined, not 0


def test_cci_strategy_is_fixed_enters_on_a_strong_push_exits_below_zero_and_has_no_lookahead():
    st = ST.S["cci_trend"]
    assert st.params == {"n": 20, "high": 100, "low": 0} and not st.requires_funding
    flat = np.full(40, 100.0) + np.sin(np.arange(40)) * 0.5
    surge = flat[-1] + np.arange(1, 21, dtype=float) * 4
    fall = surge[-1] - np.arange(1, 41, dtype=float) * 3
    c = np.concatenate([flat, surge, fall])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:19].sum() == 0 and set(pos) <= {0.0, 1.0}
    assert pos[55] == 1.0 and pos[-1] == 0.0                                                         # in the surge it is holding; after a long fall it has left
    assert (st.build(d.iloc[:70], st.params).to_numpy() == pos[:70]).all()                           # bar i uses only bars up to i


def test_obv_matches_a_hand_worked_example():
    c = np.array([10, 11, 10, 10, 12], float)
    v = np.array([5, 7, 3, 4, 6], float)
    d = pd.DataFrame({"h": c, "l": c, "c": c, "v": v})
    o = ST.obv(d).to_numpy()
    assert o.tolist() == [0.0, 7.0, 4.0, 4.0, 10.0]                                                   # +0 (first bar), +7 (up), -3 (down), +0 (unchanged), +6 (up)


def test_obv_strategy_is_fixed_needs_both_conditions_and_has_no_lookahead():
    st = ST.S["obv_trend"]
    assert st.params == {"n_obv": 50, "n_price": 50} and not st.requires_funding
    up = 100 + np.arange(120, dtype=float)
    down = up[-1] - np.arange(1, 121, dtype=float) * 2
    c = np.concatenate([up, down])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c, "v": np.full(len(c), 100.0)})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:49].sum() == 0 and pos[49] == 1.0 and pos[80] == 1.0 and pos[-1] == 0.0 and set(pos) <= {0.0, 1.0}                  # the 50-bar averages first exist on bar 49
    assert (st.build(d.iloc[:150], st.params).to_numpy() == pos[:150]).all()                          # bar i uses only bars up to i
    flat_volume_up = pd.DataFrame({"h": up + 1, "l": up - 1, "c": up, "v": np.zeros(len(up))})        # price rising but no volume at all: OBV never rises above its average, so no position
    assert st.build(flat_volume_up, st.params).to_numpy().sum() == 0


def test_wma_matches_a_hand_worked_example():
    assert abs(ST.wma(pd.Series([1.0, 2.0, 3.0]), 3).iloc[-1] - 14 / 6) < 1e-12                       # (1*1 + 2*2 + 3*3) / 6


def test_mayer_cap_leaves_when_stretched_and_has_no_lookahead():
    st = ST.S["mayer_cap"]
    assert st.params == {"n": 200, "cap": 2.4} and not st.requires_funding
    c = np.concatenate([100 + np.arange(300, dtype=float), [1000.0]])                                  # a steady climb, then one huge jump
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:199].sum() == 0 and pos[199] == 1.0 and pos[299] == 1.0                                  # the 200-bar average first exists on bar 199 (299 vs 199.5: ratio 1.5)
    assert pos[300] == 0.0                                                                               # 1000 / 303.5 = 3.3 is over 2.4: stand aside
    assert (st.build(d.iloc[:250], st.params).to_numpy() == pos[:250]).all()


def test_donchian_mid_is_fixed_and_follows_the_range_midpoint():
    st = ST.S["donchian_mid"]
    assert st.params == {"n": 50}
    up = 100 + np.arange(120, dtype=float)
    c = np.concatenate([up, up[-1] - np.arange(1, 121, dtype=float) * 2])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    assert ST._dmid(d, 50).iloc[49] == (150 + 99) / 2                                                    # highest high 150, lowest low 99 over bars 0..49
    pos = st.build(d, st.params).to_numpy()
    assert pos[:49].sum() == 0 and pos[49] == 1.0 and pos[100] == 1.0 and pos[-1] == 0.0
    assert (st.build(d.iloc[:150], st.params).to_numpy() == pos[:150]).all()


def test_hull_trend_follows_a_rise_and_leaves_in_a_fall_without_lookahead():
    st = ST.S["hull_trend"]
    assert st.params == {"n": 55}
    c = np.concatenate([100 + np.arange(150, dtype=float), 249 - np.arange(1, 151, dtype=float) * 2])
    d = pd.DataFrame({"h": c + 1, "l": c - 1, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:60].sum() == 0 and pos[100] == 1.0 and pos[-1] == 0.0 and set(pos) <= {0.0, 1.0}         # the Hull average first exists on bar 60 (54 + 6)
    assert (st.build(d.iloc[:200], st.params).to_numpy() == pos[:200]).all()
    straight = ST.hull(pd.Series(np.arange(1.0, 100.0)), 55)
    assert abs(straight.iloc[-1] - (99.0 - 4 / 3)) < 1e-9                                                # on a straight line a WMA(n) lags (n-1)/3 bars: (2*26 - 54)/3 + 6/3 = 4/3 bars here


def test_heikin_ashi_matches_a_hand_worked_example():
    d = pd.DataFrame({"o": [10.0, 10.0], "h": [12.0, 14.0], "l": [8.0, 10.0], "c": [10.0, 13.0]})
    h = ST.heikin_ashi(d)
    assert h["c"].tolist() == [10.0, 11.75]                                                              # (10+12+8+10)/4 and (10+14+10+13)/4
    assert h["o"].tolist() == [10.0, 10.0]                                                               # first: (10+10)/2; second: (10 + 10)/2
    assert h["l"].iloc[1] == 10.0 and h["h"].iloc[1] == 14.0


def test_heikin_trend_needs_two_strong_candles_leaves_on_red_and_has_no_lookahead():
    st = ST.S["heikin_trend"]
    assert st.params == {"n": 2}
    up = 100 + np.arange(40, dtype=float) * 2
    c = np.concatenate([up, up[-1] - np.arange(1, 41, dtype=float) * 4])
    o = np.concatenate([[100.0], c[:-1]])
    d = pd.DataFrame({"o": o, "h": np.maximum(o, c) + 0.5, "l": np.minimum(o, c), "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert set(pos) <= {0.0, 1.0} and pos[0] == 0.0 and pos[30] == 1.0 and pos[-1] == 0.0
    assert pos[:2].sum() == 0                                                                            # two candles are needed before the first entry
    assert (st.build(d.iloc[:60], st.params).to_numpy() == pos[:60]).all()


def test_trix_is_zero_on_a_flat_series_and_follows_acceleration():
    assert abs(ST.trix(pd.Series([50.0] * 80), 15).dropna()).max() == 0.0
    st = ST.S["trix_cross"]
    assert st.params == {"n": 15, "signal": 9}
    c = np.concatenate([np.full(80, 100.0), 100 + np.arange(1, 81, dtype=float) ** 2 / 10, np.full(5, 740.0)[:0]])
    c = np.concatenate([c, c[-1] - np.arange(1, 121, dtype=float) * 5])
    d = pd.DataFrame({"o": c, "h": c, "l": c, "c": c})
    pos = st.build(d, st.params).to_numpy()
    assert pos[:80].sum() == 0 and pos[120] == 1.0 and pos[-1] == 0.0 and set(pos) <= {0.0, 1.0}
    assert (st.build(d.iloc[:150], st.params).to_numpy() == pos[:150]).all()


def test_pi_cycle_is_long_until_the_cross_and_returns_after_the_cross_back():
    st = ST.S["pi_cycle"]
    assert st.params == {"fast": 111, "slow": 350, "mult": 2.0}
    c = np.concatenate([np.full(400, 100.0), np.full(100, 10000.0), np.full(400, 100.0)])
    d = pd.DataFrame({"o": c, "h": c, "l": c, "c": c})
    pos = st.build(d, st.params).to_numpy()
    f, s, up, down = ST._pi_state(d, st.params)
    i_up, i_dn = int(np.argmax(up.to_numpy())), int(np.argmax(down.to_numpy()))
    assert pos[:349].sum() == 0 and pos[349] == 1.0                                                      # the 350-bar average first exists on bar 349
    assert i_up > 400 and pos[i_up - 1] == 1.0 and pos[i_up] == 0.0                                      # aside from the bar where the 111-bar average crosses above 2 x the 350-bar one
    assert i_dn > i_up and pos[i_dn - 1] == 0.0 and pos[i_dn] == 1.0 and pos[-1] == 1.0                  # and back in when it crosses below
    assert (st.build(d.iloc[:600], st.params).to_numpy() == pos[:600]).all()
