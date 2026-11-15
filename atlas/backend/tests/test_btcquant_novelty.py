"""btcquant novelty pre-screen (the research queue): each queued rule on hand-made candles with the answers worked out by hand, the rule that nothing at or before day i may depend on later candles, and the
screen itself (all 100 configurations, the TRAIN and VALIDATION days, the 0.90 line for a renamed copy) with its edge cases."""
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from atlas_api.btcquant import backtest as B
from atlas_api.btcquant import config as C
from atlas_api.btcquant import data as D
from atlas_api.btcquant import novelty as N
from atlas_api.btcquant import strategies as S

DAY = 86400
T2019 = int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp())
MONDAY = int(datetime(2026, 11, 16, tzinfo=timezone.utc).timestamp())          # 2026-11-16 was a Monday


def history(n, seed=1, start=20_000.0, vol=0.03, t0=T2019):
    rng = np.random.default_rng(seed)
    c = start * np.exp(np.cumsum(rng.normal(0.0004, vol, n)))
    o = np.concatenate([[start], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    v = rng.lognormal(4.0, 0.5, n)
    return [(t0 + i * DAY, float(o[i]), float(h[i]), float(l[i]), float(c[i]), float(v[i])) for i in range(n)]


def bars_from(closes, vols=None, hi=None, lo=None, t0=MONDAY):
    """Candles built from closes (and optionally volumes, highs, lows); open = high = low = close unless given."""
    n = len(closes)
    hi = closes if hi is None else hi
    lo = closes if lo is None else lo
    vols = [10.0] * n if vols is None else vols
    return S.Bars([(t0 + i * DAY, closes[i], hi[i], lo[i], closes[i], vols[i]) for i in range(n)])


def on(arr):
    return [i for i, x in enumerate(arr) if x]


# ---------------------------------------------------------------------------------------------------------- the calendar rule
def test_weekday_counts_monday_as_zero_from_the_utc_open_time():
    assert weekday_of(0) == 3                                                              # 1970-01-01 was a Thursday
    assert [weekday_of(MONDAY + i * DAY) for i in range(7)] == [0, 1, 2, 3, 4, 5, 6]
    assert weekday_of(MONDAY - 1) == 6 and weekday_of(MONDAY + DAY - 1) == 0 and weekday_of(MONDAY + 3600) == 0       # one second before Monday is Sunday; any time inside a day is that day


def weekday_of(t):
    return int(N.weekday([t])[0])


def test_monday_is_on_the_day_before_the_day_it_holds():
    b = bars_from([100.0] * 14)                                                           # Monday 16 Nov to Sunday 29 Nov
    assert on(N.monday(b)) == [6, 13]                                                      # ON at the close of each Sunday: the position is held through the Monday candle
    assert on(N.monday(b, day=3)) == [2, 9]                                                # Thursday is held from the Wednesday close
    assert on(N.monday(b, day=6)) == [5, 12]                                               # Sunday is held from the Saturday close
    assert on(N.monday(b, day=1)) == [0, 7]                                                # Tuesday: from the Monday close, and the first candle itself counts


# ---------------------------------------------------------------------------------------------------------- volume surge
def test_volume_surge_holds_for_five_candles_after_a_heavy_up_day():
    closes = [100.0 + i for i in range(30)]
    vols = [10.0] * 30
    vols[22] = 20.0                                                                        # exactly twice the mean of the previous 20 days: the boundary counts
    assert on(N.volume_surge(bars_from(closes, vols))) == [22, 23, 24, 25, 26]
    vols[22] = 19.99
    assert on(N.volume_surge(bars_from(closes, vols))) == []                               # just under twice: nothing
    vols[22] = 30.0
    assert on(N.volume_surge(bars_from(closes, vols), hold=2)) == [22, 23]
    vols[24] = 30.0                                                                        # a second surge two days later extends the hold: 22..26 and 24..28
    assert on(N.volume_surge(bars_from(closes, vols))) == [22, 23, 24, 25, 26, 27, 28]


def test_volume_surge_needs_an_up_close_and_twenty_days_of_history():
    closes = [100.0 + i for i in range(30)]
    vols = [10.0] * 30
    vols[22] = 30.0
    closes[22] = closes[21] - 1.0                                                          # heavy volume on a DOWN day
    assert on(N.volume_surge(bars_from(closes, vols))) == []
    closes = [100.0 + i for i in range(30)]
    vols = [10.0] * 30
    vols[5] = 100.0                                                                        # a heavy up day before 20 days of history exist
    assert on(N.volume_surge(bars_from(closes, vols))) == []
    closes[22] = closes[21]                                                                # an unchanged close is not an up close
    vols = [10.0] * 30
    vols[22] = 30.0
    assert on(N.volume_surge(bars_from(closes, vols))) == []


# ---------------------------------------------------------------------------------------------------------- near the high
def test_near_high_looks_at_closes_not_at_intraday_highs():
    closes = [10.0, 11, 12, 13, 14, 15, 12, 14.5, 14, 11, 20]
    spiky = bars_from(closes, hi=[c + 50.0 if i == 5 else c for i, c in enumerate(closes)])     # one huge intraday high that never closed there
    assert (N.near_high(spiky, window=5, frac=0.9) == N.near_high(bars_from(closes), window=5, frac=0.9)).all()


def test_near_high_is_on_within_the_fraction_of_the_window_high():
    closes = [10, 11, 12, 13, 14, 15, 12, 14.5, 14, 11, 20]
    got = N.near_high(bars_from([float(c) for c in closes]), window=5, frac=0.9)
    assert [bool(x) for x in got] == [False, False, False, False, True, True, False, True, True, False, True]
    # the first four days have no five-day window: never ON in the warm-up, however high the close
    assert not N.near_high(bars_from([1.0, 2.0, 3.0, 4.0]), window=5, frac=0.5).any()


# ---------------------------------------------------------------------------------------------------------- squeeze and break
def test_squeeze_break_enters_after_a_quiet_spell_and_leaves_below_the_middle_band():
    closes = [100.0] * 10 + [110.0, 110.0, 110.0, 90.0, 90.0, 90.0, 90.0]
    got = N.squeeze_break(bars_from(closes), n=3, k=1.0, lookback=4, pct=25.0)
    # ten flat days (width 0, a squeeze), then a jump above the upper band: ON at 10; 11 and 12 stay above the middle band (12 equals it exactly); 13 is below it: OFF, and flat 90s do not re-enter
    assert on(got) == [10, 11, 12]


def test_a_squeeze_is_a_width_at_or_below_the_percentile_of_the_widths_before_it():
    w = np.array([np.nan, np.nan, 5.0, 1.0, 3.0, 2.0, 1.5, 2.0, 3.6, 3.4])
    # windows of four (worked by hand, linear interpolation between the sorted values):
    #   index 6: 5, 1, 3, 2 -> sorted 1, 2, 3, 5: 25th percentile 1.75, 75th 3.5; width 1.5 is below both
    #   index 7: 1, 3, 2, 1.5 -> sorted 1, 1.5, 2, 3: 25th 1.375, 75th 2.25; width 2.0 is above the first, below the second
    #   index 8: 3, 2, 1.5, 2 -> sorted 1.5, 2, 2, 3: 25th 1.875, 75th 2.25; width 3.6 is above both
    #   index 9: 2, 1.5, 2, 3.6 -> sorted 1.5, 2, 2, 3.6: 25th 1.875, 75th 2.4; width 3.4 is above both; indices 4 and 5 have a NaN in their windows
    assert on(N._squeezed(w, 4, 25.0)) == [6]
    assert on(N._squeezed(w, 4, 75.0)) == [6, 7]
    assert on(N._squeezed(np.array([1.0, 2.0, 3.0]), 4, 25.0)) == []                       # fewer days than the lookback: nothing can be squeezed yet
    assert on(N._squeezed(np.array([2.0, 2.0, 2.0, 2.0, np.nan, 2.0, 2.0]), 3, 50.0)) == [3]     # a flat spell equals its own percentile; a missing width, or a window with one, is never a squeeze


def test_squeeze_break_needs_the_close_above_the_upper_band_not_just_the_middle_one():
    closes = [100.0] * 10 + [110.0, 110.0, 110.0, 90.0, 90.0, 90.0, 90.0]                  # the same flat spell and jump as above
    # with a three-day window and TWO standard deviations the upper band (116.1 at the jump) is above any jump out of a flat spell: no entry, although the close is above the middle band (103.3)
    assert not N.squeeze_break(bars_from(closes), n=3, k=2.0, lookback=4, pct=25.0).any()


def test_squeeze_break_ignores_a_break_that_was_not_preceded_by_a_squeeze():
    closes = [100, 101, 100, 102, 100, 103, 100, 104, 100, 105, 130]                       # the bands keep widening, then a jump far above the upper band
    assert not N.squeeze_break(bars_from([float(c) for c in closes]), n=3, k=1.0, lookback=4, pct=25.0).any()


# ---------------------------------------------------------------------------------------------------------- three lower closes
def test_three_down_buys_the_third_lower_close_and_leaves_on_the_first_close_that_is_not_lower():
    assert on(N.three_down(bars_from([10.0, 9, 8, 7, 8, 7, 6, 5, 5, 6]))) == [3, 7]        # second streak ends on a flat close
    assert on(N.three_down(bars_from([10.0, 9, 8, 7, 6, 5, 6]))) == [3, 4, 5]             # a longer streak keeps it ON until the up close
    assert on(N.three_down(bars_from([10.0, 9, 8, 9]), streak=2)) == [2]


# ---------------------------------------------------------------------------------------------------------- money flow
def test_money_flow_weights_each_days_close_position_by_its_volume():
    hi, lo = [110.0] * 6, [90.0] * 6
    got = N.money_flow(bars_from([110.0, 110, 110, 90, 90, 90], hi=hi, lo=lo), n=3)
    assert on(got) == [2, 3]                                                               # closes at the high (+1) for three days, then one at the low: 10/30 is still above 0.05; two lows: negative
    heavy = N.money_flow(bars_from([110.0, 110, 90], vols=[10.0, 10.0, 30.0], hi=hi[:3], lo=lo[:3]), n=3)
    assert on(heavy) == []                                                                 # unweighted the mean is +0.33; weighted by volume it is (10 + 10 - 30) / 50 = -0.2


def test_money_flow_must_be_above_the_threshold_not_just_above_zero():
    hi, lo = [110.0] * 3, [90.0] * 3                                                       # range 20: the position of a close is (close - 100) / 10, so 101, 99.6 and 100 are +0.10, -0.04 and 0
    b = bars_from([101.0, 99.6, 100.0], hi=hi, lo=lo)
    assert on(N.money_flow(b, n=3)) == []                                                  # the mean is 0.02: positive, but under the default 0.05
    assert on(N.money_flow(b, n=3, threshold=0.0)) == [2]
    assert on(N.money_flow(b, n=3, threshold=0.01)) == [2] and on(N.money_flow(b, n=3, threshold=0.03)) == []


def test_a_day_with_no_range_counts_as_zero_flow_inside_a_window_of_real_flow():
    hi = [110.0, 110.0, 100.0, 100.0]
    lo = [90.0, 90.0, 100.0, 100.0]
    got = N.money_flow(bars_from([110.0, 110.0, 100.0, 100.0], hi=hi, lo=lo), n=3)          # closes at the high, at the high, then two days with high = low = close
    assert on(got) == [2, 3]                                                               # (1 + 1 + 0) / 3 and (1 + 0 + 0) / 3 are both above 0.05


def test_money_flow_survives_a_day_with_no_range():
    flat = bars_from([100.0] * 8)                                                          # high = low = close: the close has no position within the range; counted as zero, never a division error
    assert not N.money_flow(flat, n=3).any()


# ---------------------------------------------------------------------------------------------------------- no look-ahead
@pytest.mark.parametrize("cid", list(N.CANDIDATES))
def test_no_queued_rule_uses_a_later_candle(cid):
    fn = N.CANDIDATES[cid].fn
    a = history(700, seed=5)
    full = fn(S.Bars(a))
    for k in (260, 333, 480):
        later = history(700, seed=99, start=a[k][4])
        changed = a[:k + 1] + [(a[k][0] + (j + 1) * DAY, *later[j][1:]) for j in range(700 - k - 1)]
        assert (fn(S.Bars(changed))[:k + 1] == full[:k + 1]).all(), f"{cid} changed at or before day {k}"


def test_every_queued_rule_is_neither_always_on_nor_never_on_over_five_years_of_random_walk():
    b = S.Bars(history(1900, seed=3, vol=0.04))
    for cid, c in N.CANDIDATES.items():
        s = c.fn(b)
        assert s.dtype == bool and len(s) == b.n and s.any() and not s.all(), cid


# ---------------------------------------------------------------------------------------------------------- the screen
@pytest.fixture(scope="module")
def prep():
    return B.Prepared(history(2300, seed=11, vol=0.035))


def test_the_days_are_the_train_days_followed_by_the_validation_days(prep):
    idx = N.days(prep)
    assert list(idx) == list(range(365, 365 + 1096 + 731))                                 # 2020-01-01 to 2024-12-31: the two periods are back to back


def test_existing_series_are_all_hundred_configurations_of_the_protocol(prep):
    ex = N.existing(prep)
    assert len(ex) == 100 == sum(len(S.configs(f)) for f in S.FAMILIES.values() if f.kind in ("stop", "weight"))
    assert all(len(s) == prep.bars.n for s in ex.values())
    fams = {k[0] for k in ex}
    assert fams == {f.id for f in S.FAMILIES.values() if f.kind in ("stop", "weight")} and len(fams) == 12
    for (fid, _), s in ex.items():
        assert s.min() >= 0.0 and s.max() <= 1.0 and (S.FAMILIES[fid].kind == "weight" or set(np.unique(s)) <= {0.0, 1.0})
    assert ex[("sma_cross", B.param_key({"fast": 10, "slow": 50}))].astype(bool).tolist() == S.FAMILIES["sma_cross"].build(prep.bars, {"fast": 10, "slow": 50}).state.tolist()
    w = ex[("vol_target", B.param_key({"target": 0.4, "window": 40}))]
    assert w.tolist() == np.nan_to_num(np.asarray(S.FAMILIES["vol_target"].build(prep.bars, {"target": 0.4, "window": 40}).weight, dtype=float)).tolist()


def test_correlations_are_pearson_over_the_given_days_only_and_skip_series_that_never_change():
    x = np.array([1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 0], dtype=float)
    y = np.array([1, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1], dtype=float)
    series = {"same": x.copy(), "inverse": 1 - x, "flat": np.ones(12), "other": y}
    idx = np.arange(12)
    got = N.correlations(x, series, idx)
    assert [k for _, k in got] == ["same", "other", "inverse"] and "flat" not in [k for _, k in got]
    assert got[0][0] == pytest.approx(1.0) and got[2][0] == pytest.approx(-1.0) and got[1][0] == pytest.approx(np.corrcoef(x, y)[0, 1])
    z = x.copy()
    z[[0, 5, 9]] = 1 - z[[0, 5, 9]]                                                        # differs from x on three days...
    assert N.correlations(x, {"z": z}, np.arange(12))[0][0] < 0.99
    assert N.correlations(x, {"z": z}, np.array([1, 2, 3, 4, 6, 7, 8, 10, 11]))[0][0] == pytest.approx(1.0)       # ...none of them among the days compared
    assert N.correlations(np.ones(12), series, idx) == []                                  # a candidate that never changes has no correlation with anything


def test_the_screen_flags_a_renamed_copy_and_names_what_it_copies(prep):
    copy = lambda bars: S.FAMILIES["sma_cross"].build(bars, {"fast": 10, "slow": 50}).state
    r = N.prescreen(prep, copy)
    assert r["renamed"] is True and r["max_correlation"] == pytest.approx(1.0) and r["days"] == 1827
    assert any(c["family"] == "sma_cross" and c["params"] == {"fast": 10, "slow": 50} and c["correlation"] == pytest.approx(1.0) for c in r["closest"]) and len(r["closest"]) == 3
    assert r["closest"] == sorted(r["closest"], key=lambda c: -c["correlation"])
    json.dumps(r)


def test_the_screen_line_is_drawn_at_point_nine(monkeypatch):
    n = 20
    x = np.array([1.0, 0.0] * 10)
    one_off, two_off = x.copy(), x.copy()
    one_off[0] = 0.0                                                                       # one ON day dropped: r = 0.9045
    two_off[[0, 2]] = 0.0                                                                  # two dropped: r = 0.8165
    pad = lambda v: np.concatenate([v, np.zeros(60 - n)])
    p = B.Prepared(history(60, seed=2))
    monkeypatch.setattr(N, "days", lambda prep_: np.arange(n))                             # compare only the first twenty days
    a, b = ("a", ()), ("b", ())
    both = N.prescreen(p, lambda bars: pad(x), series={a: pad(one_off), b: pad(two_off)})
    assert both["max_correlation"] == pytest.approx(0.9045, abs=1e-3) and both["renamed"] is True and both["closest"][0]["family"] == "a"
    assert both["closest"][1]["correlation"] == pytest.approx(0.8165, abs=1e-3)
    only_two = N.prescreen(p, lambda bars: pad(x), series={b: pad(two_off)})
    assert only_two["max_correlation"] == pytest.approx(0.8165, abs=1e-3) and only_two["renamed"] is False


def test_a_candidate_that_never_changes_is_not_called_a_copy(prep):
    r = N.prescreen(prep, lambda bars: np.zeros(bars.n, dtype=bool))
    assert r["max_correlation"] is None and r["renamed"] is False and r["closest"] == [] and r["share_on"] == 0.0


def test_the_share_of_days_on_is_counted_over_the_compared_days_only(prep):
    r = N.prescreen(prep, N.monday)
    wk = N.weekday(prep.bars.t)[N.days(prep)]
    assert r["share_on"] == pytest.approx(float(np.mean(wk == 6)))                         # the Sunday candles among the 1,827 compared days
    assert abs(r["share_on"] - 1 / 7) < 0.01 and r["renamed"] is False


def test_prescreen_all_screens_every_queued_candidate_once(prep):
    out = N.prescreen_all(prep)
    assert list(out) == ["monday", "volume_surge", "near_high", "squeeze_break", "three_down", "money_flow"]
    for cid, r in out.items():
        assert set(r) == {"name", "days", "share_on", "max_correlation", "renamed", "closest"} and r["name"] == N.CANDIDATES[cid].name and r["days"] == 1827
        assert r["renamed"] == (r["max_correlation"] is not None and r["max_correlation"] >= 0.90)


def test_the_command_writes_the_result_with_the_data_version_it_used(tmp_path, monkeypatch, capsys):
    candles = history(2300, seed=11, vol=0.035)
    D.save(tmp_path / "data" / "btcusd_1d.csv", candles)
    monkeypatch.setattr(C, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(C, "REPORT_DIR", tmp_path / "reports")
    assert N.main([]) == 0
    out = json.loads((tmp_path / "reports" / "novelty.json").read_text())
    assert out["threshold"] == 0.9 and out["protocol"] == C.PROTOCOL_VERSION and out["data"]["candles"] == 2300 and out["data"]["last"].startswith("2025-04-")
    assert set(out["candidates"]) == set(N.CANDIDATES) and out["data"]["sha256"] == D.manifest(candles, C.DAY)["sha256"]
    text = capsys.readouterr().out
    assert "2,300" not in text and "novelty pre-screen on 2300 candles" in text and all(cid in text for cid in N.CANDIDATES)


def test_the_command_says_so_when_there_are_no_candles(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(C, "DATA_DIR", tmp_path / "nothing")
    monkeypatch.setattr(C, "REPORT_DIR", tmp_path / "reports")
    assert N.main([]) == 1 and "no stored daily candles" in capsys.readouterr().out and not (tmp_path / "reports").exists()
