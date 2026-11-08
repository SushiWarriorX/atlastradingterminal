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
