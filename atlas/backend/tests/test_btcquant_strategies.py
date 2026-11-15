"""btcquant strategy families: the rule of every family worked by hand on tiny series (including the boundary where a comparison is exactly equal), the 100-configuration grid, neighbours, the specification hash,
a no-look-ahead test over every configuration (changing later candles never moves an earlier signal), the replayed trailing stop agreeing with the account engine, and a check that each family's note says what the code does.

Logic tests use a stand-in for the candle container that hands over only the indicator arrays written into the test, and fails loudly (KeyError) if a family asks for an indicator with other parameters than it should.
"""
import json
import re
from datetime import datetime, timezone

import numpy as np
import pytest

from atlas_api.btcquant import backtest as B
from atlas_api.btcquant import config as C
from atlas_api.btcquant import strategies as S
from atlas_api.btcquant.account import Sig, make_account

DAY = 86400
T0 = 1_700_000_000 - 1_700_000_000 % DAY
NAN = float("nan")


class Fake:
    """Stands in for strategies.Bars: closes/highs/lows plus exactly the indicator arrays the test supplies."""

    def __init__(self, c, l=None, h=None, **ind):
        self.c = np.array(c, dtype=float)
        self.n = len(self.c)
        self.l = np.array(l if l is not None else c, dtype=float)
        self.h = np.array(h if h is not None else c, dtype=float)
        self._ind = {k: np.array(v, dtype=float) for k, v in ind.items()}
        self._ind.setdefault("atr_14", np.full(self.n, np.nan))                          # the fixed 3 ATR stop asks for it; these tests are about the state, not the stop
        self.asked = []

    def ind(self, name, *args):
        key = name + "".join("_" + str(a) for a in args)                  # e.g. "rsi_14", "sma_50", "atr_14"
        self.asked.append(key)
        return self._ind[key]


def candles(closes, highs=None, lows=None, opens=None):
    n = len(closes)
    o = opens if opens is not None else [closes[0]] + list(closes[:-1])
    h = highs if highs is not None else [max(a, b) for a, b in zip(o, closes)]
    l = lows if lows is not None else [min(a, b) for a, b in zip(o, closes)]
    return [(T0 + i * DAY, float(o[i]), float(h[i]), float(l[i]), float(closes[i]), 1.0) for i in range(n)]


def states(sig):
    return [bool(x) for x in sig.state]


def walk(n, seed, start=20_000.0, vol=0.03):
    """A synthetic daily random walk with plausible candles (high above, low below the open and close)."""
    rng = np.random.default_rng(seed)
    c = start * np.exp(np.cumsum(rng.normal(0.0004, vol, n)))
    o = np.concatenate([[start], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    return [(T0 + i * DAY, float(o[i]), float(h[i]), float(l[i]), float(c[i]), 100.0) for i in range(n)]


# ---- the grid ----

PROTOCOL_COUNTS = {"sma_cross": 15, "donchian": 4, "ma_atr_trend": 9, "tsmom": 5, "rsi_momentum": 18, "mom_vol": 9, "bollinger_mr": 6,
                   "rsi_oversold": 12, "vol_breakout": 9, "regime_switch": 3, "vol_target": 6, "sma_filter": 4, "monday": 1}


def test_the_grids_hold_exactly_the_protocol_counts_and_one_hundred_and_one_in_all():
    assert {f.id: len(S.configs(f)) for f in S.RESEARCH} == PROTOCOL_COUNTS
    assert S.n_configurations() == 101 == sum(PROTOCOL_COUNTS.values()) == 100 + len(S.configs(S.FAMILIES["monday"]))          # the twelve families of 1.2 hold 100 of them, the one family of 1.3 holds one
    assert [f.id for f in S.RESEARCH] == list(PROTOCOL_COUNTS)                                  # thirteen families in protocol order
    assert [len(S.configs(S.FAMILIES[b])) for b in ("buy_hold", "cash")] == [1, 1]


def test_the_counts_in_the_protocol_table_agree_with_the_code():
    text = (C.ROOT / "PROTOCOL.md").read_text(encoding="utf-8")
    section = text.split("## 5.")[1].split("## 6.")[0]
    seen = {}
    for line in section.splitlines():
        cells = [x.strip() for x in line.split("|")]
        if len(cells) > 5 and re.search(r"`(\w+)`", cells[2] or ""):
            fid = re.search(r"`(\w+)`", cells[2]).group(1)
            m = re.search(r"\((\d+)\)\s*$", cells[4])
            seen[fid] = int(m.group(1)) if m else None
    for fid, n in PROTOCOL_COUNTS.items():
        assert seen[fid] == n, fid
    assert seen["buy_hold"] is None and seen["cash"] is None


def test_the_crossover_grid_keeps_only_pairs_with_the_fast_average_shorter():
    cfgs = S.configs(S.FAMILIES["sma_cross"])
    assert all(c["fast"] < c["slow"] for c in cfgs) and len({(c["fast"], c["slow"]) for c in cfgs}) == 15
    assert {"fast": 50, "slow": 50} not in cfgs and {"fast": 50, "slow": 100} in cfgs and {"fast": 10, "slow": 50} in cfgs


def test_neighbours_are_one_step_in_exactly_one_parameter_and_must_be_valid():
    f = S.FAMILIES["sma_cross"]
    assert S.neighbours(f, {"fast": 10, "slow": 50}) == [{"fast": 20, "slow": 50}, {"fast": 10, "slow": 100}]
    assert S.neighbours(f, {"fast": 50, "slow": 100}) == [{"fast": 30, "slow": 100}, {"fast": 50, "slow": 150}]
    assert S.neighbours(f, {"fast": 30, "slow": 50}) == [{"fast": 20, "slow": 50}, {"fast": 30, "slow": 100}]     # (50, 50) is not a valid pair
    d = S.FAMILIES["donchian"]
    assert S.neighbours(d, {"N": 20}) == [{"N": 40}] and S.neighbours(d, {"N": 40}) == [{"N": 20}, {"N": 55}] and S.neighbours(d, {"N": 80}) == [{"N": 55}]
    assert S.neighbours(S.FAMILIES["buy_hold"], {}) == []
    r = S.FAMILIES["rsi_momentum"]
    assert len(S.neighbours(r, {"n": 14, "enter": 60, "exit": 45})) == 5                    # n has one neighbour, enter and exit two each


def test_every_neighbour_is_itself_a_configuration_of_the_family():
    for f in S.RESEARCH:
        cfgs = S.configs(f)
        for p in cfgs:
            for q in S.neighbours(f, p):
                assert q in cfgs, (f.id, p, q)


# ---- the specification hash ----

def test_the_specification_hash_is_stable_independent_of_key_order_and_sensitive_to_everything_that_matters(monkeypatch):
    h = S.spec_hash("sma_cross", {"fast": 20, "slow": 100})
    assert h == S.spec_hash("sma_cross", {"slow": 100, "fast": 20}) and re.fullmatch(r"[0-9a-f]{16}", h)
    assert h != S.spec_hash("sma_cross", {"fast": 20, "slow": 150}) and h != S.spec_hash("sma_cross", {"fast": 30, "slow": 100})
    assert h != S.spec_hash("sma_cross", {"fast": 20, "slow": 100}, version=2) and h != S.spec_hash("tsmom", {"fast": 20, "slow": 100})
    for name, value in (("FEE", 0.002), ("SLIPPAGE", 0.001), ("RISK_PER_TRADE", 0.02), ("STOP_ATR_MULT", 2.0), ("ATR_N", 10), ("CIRCUIT_BREAKER", 0.2), ("BREAKER_COOL_OFF_DAYS", 10), ("REBALANCE_BAND", 0.2)):
        with monkeypatch.context() as m:
            m.setattr(C, name, value)
            assert S.spec_hash("sma_cross", {"fast": 20, "slow": 100}) != h, name
    with monkeypatch.context() as m:                                                          # the protocol version a family was pre-registered under is in the hash; the number the protocol is at now is not
        m.setattr(C, "PROTOCOL_VERSION", "9.9")
        assert S.spec_hash("sma_cross", {"fast": 20, "slow": 100}) == h


# ---- family 1: sma_cross ----

def test_sma_cross_is_on_only_while_the_fast_average_is_strictly_above_the_slow_one():
    # SMA2 = [-, 10, 10, 10.5, 11.5, 11.5, 10, 8.5], SMA3 = [-, -, 10, 10.333, 11, 11.333, 10.667, 9.333]
    sig = S.signals("sma_cross", candles([10, 10, 10, 11, 12, 11, 9, 8]), {"fast": 2, "slow": 3})
    assert states(sig) == [False, False, False, True, True, True, False, False]            # index 2 is the equal case: not on; indices 0 and 1 have no slow average yet


def test_sma_cross_asks_for_the_fast_and_the_slow_average_it_was_given():
    b = Fake([1] * 5, sma_20=[NAN, 1, 2, 2, 2], sma_100=[NAN, 2, 1, 1, 1])
    sig = S.FAMILIES["sma_cross"].build(b, {"fast": 20, "slow": 100})
    assert sorted(set(b.asked)) == ["atr_14", "sma_100", "sma_20"] and states(sig) == [False, False, True, True, True]


def test_the_fixed_stop_is_the_close_less_three_atr_once_the_atr_exists():
    c = [(T0 + i * DAY, 100.0, 101.0, 99.0, 100.0, 1.0) for i in range(30)]                # every true range is 2
    sig = S.signals("sma_cross", c, {"fast": 2, "slow": 3})
    assert np.all(np.isnan(sig.stop[:13])) and np.allclose(sig.stop[13:], 94.0)


# ---- family 2: donchian ----

def donchian_series(entry_on_stop_day=False):
    # highs/lows/closes of 10 candles; N = 4 so the stop looks back 2 candles
    c = [10, 10, 10, 10, 12, 13, 14, 13, 15, 15]
    h = [10.5, 10.5, 10.5, 10.5, 12.5, 13.5, 14.5, 14.0, 15.5, 15.5]
    l = [9.5, 9.5, 9.5, 9.5, 11.0, 12.5, 13.0, 12.0, 14.0, 14.5]
    if entry_on_stop_day:
        c[7], h[7] = 15.0, 15.5                                                             # candle 7 touches the stop (low 12) AND closes above the previous 4 highs
        c[8], h[8], l[8] = 16.0, 16.5, 15.0
    return c, h, l


def test_donchian_enters_on_a_close_above_the_previous_highs_and_ratchets_its_stop_up_until_the_low_touches_it():
    c, h, l = donchian_series()
    sig = S.signals("donchian", candles(c, h, l), {"N": 4})
    # entry at 4 (12 > 10.5), stop 9.5 then 11 then 12.5; candle 7's low 12 touches 12.5: OFF; candle 8 closes at 15 above the previous 4 highs (14.5): a new entry
    assert states(sig) == [False, False, False, False, True, True, True, False, True, True]
    assert np.isnan(sig.stop[0]) and sig.stop[1] == 9.5 and sig.stop[4] == 9.5 and sig.stop[5] == 11.0 and sig.stop[6] == 12.5     # the stop candidates are the lowest low of the last 2 candles including i


def test_a_low_exactly_at_the_donchian_stop_touches_it():
    c, h, l = donchian_series()
    l[7] = 12.5                                                                            # the stop in force during candle 7 is 12.5
    sig = S.signals("donchian", candles(c, h, l), {"N": 4})
    assert states(sig)[6:8] == [True, False]
    l[7] = 12.51
    assert states(S.signals("donchian", candles(c, h, l), {"N": 4}))[6:8] == [True, True]


def test_a_donchian_entry_is_stopped_on_the_very_next_candle_when_its_low_goes_through_the_entry_stop():
    c, h, l = donchian_series()
    l[5] = 9.2                                                                             # the entry stop is 9.5 (the lowest low of candles 3 and 4)
    sig = S.signals("donchian", candles(c, h, l), {"N": 4})
    assert states(sig)[4:7] == [True, False, True]                                         # off at 5; a new breakout at 6 (14 above the previous highs 13.5) enters again with stop 9.2


def test_the_donchian_stop_never_falls_while_the_state_stays_on():
    for seed in (1, 2, 3):
        b = S.Bars(walk(900, seed=seed, vol=0.04))
        for p in S.configs(S.FAMILIES["donchian"]):
            sig = S.FAMILIES["donchian"].build(b, p)
            on_twice = sig.state[1:] & sig.state[:-1]
            assert np.all(sig.stop[1:][on_twice] >= sig.stop[:-1][on_twice]), (seed, p)


def test_a_donchian_candle_that_touches_the_stop_and_also_breaks_out_is_off_and_may_re_enter_only_at_the_next_close():
    c, h, l = donchian_series(entry_on_stop_day=True)
    sig = S.signals("donchian", candles(c, h, l), {"N": 4})
    assert states(sig)[6:10] == [True, False, True, True]                                  # 7 is off although its close is above the previous highs; 8 enters


def test_a_close_equal_to_the_highest_high_is_not_a_breakout():
    c = [10, 10, 10, 10, 10.5, 10.6]
    h = [10.5] * 6
    l = [9.5, 9.5, 9.5, 9.5, 9.5, 9.5]
    sig = S.signals("donchian", candles(c, h, l), {"N": 4})
    assert states(sig) == [False, False, False, False, False, True]                        # index 4: 10.5 is not above the previous highs of 10.5; index 5: 10.6 is


def test_the_donchian_stop_window_is_half_the_lookback_with_whole_number_division():
    n_candles = 120
    rng = np.random.default_rng(3)
    c = 100 + np.cumsum(rng.normal(0, 1, n_candles))
    cs = candles(list(c), list(c + 1), list(c - 1))
    sig = S.signals("donchian", cs, {"N": 55})
    low = np.array([x[3] for x in cs])
    expected = np.array([np.min(low[i - 26:i + 1]) for i in range(26, n_candles)])        # 55 // 2 = 27 candles including i
    assert np.allclose(sig.stop[26:], expected) and np.isnan(sig.stop[25])


def test_the_replayed_donchian_stop_matches_what_the_account_engine_does_with_the_same_signals():
    c, h, l = donchian_series()
    cs = candles(c, h, l)
    sig = S.signals("donchian", cs, {"N": 4})
    a = make_account("d", "stop", trail=True, verbose=True)
    for i, bar in enumerate(cs):
        a.step(bar, Sig(state=bool(sig.state[i]), stop=float(sig.stop[i])))
    first = a.trades[0]
    assert len(a.trades) == 1
    assert first["entry_t"] == T0 + 5 * DAY and first["exit_t"] == T0 + 7 * DAY and first["reason"] == "stop"      # signal at 4, fills at 5's open, stopped in candle 7
    assert first["exit_px"] == pytest.approx(12.5 * (1 - C.SLIPPAGE) * (1 - C.FEE), rel=1e-9)  # the open of 7 (14) is above the stop, so it fills at the stop less slippage; the trade record's price is net of the fee
    assert a.qty > 0 and a.open_trade["entry_t"] == T0 + 9 * DAY                             # the second entry: signal at 8, fills at 9's open, still open


# ---- family 3: ma_atr_trend ----

def test_ma_atr_trend_enters_above_the_average_trails_a_stop_and_needs_a_close_at_or_below_the_average_after_a_stop_out():
    sma = [NAN] + [100.0] * 11
    atr = [NAN] + [2.0] * 11
    c = [99, 99, 101, 103, 104, 102, 98, 97, 103, 105, 106, 99]
    l = [98, 98, 100, 102, 103, 100, 96, 95, 101, 104, 105, 97]
    b = Fake(c, l=l, sma_100=sma, atr_14=atr)
    sig = S.FAMILIES["ma_atr_trend"].build(b, {"L": 100, "m": 2})
    # entry at 2 (stop 97), ratchet to 99 and 100, candle 5's low 100 touches it (equal counts): off, although the close 102 is above the average (not armed)
    # armed again by the closes 98 and 97; enters at 8 (stop 99), ratchets to 101 and 102; candle 11 low 97 touches it
    assert states(sig) == [False, False, True, True, True, False, False, False, True, True, True, False]
    assert list(sig.stop[2:5]) == [97.0, 99.0, 100.0]                                        # candidates: close - 2 x ATR


def test_a_close_exactly_on_the_average_re_arms_the_trend_filter():
    sma = [NAN] + [100.0] * 8
    atr = [NAN] + [2.0] * 8
    c = [99, 99, 101, 103, 104, 102, 100, 103, 104]
    l = [98, 98, 100, 102, 103, 100, 99, 101, 102]                                         # stopped at index 5 (low 100 against the stop 100); index 6 closes exactly on the average
    sig = S.FAMILIES["ma_atr_trend"].build(Fake(c, l=l, sma_100=sma, atr_14=atr), {"L": 100, "m": 2})
    assert states(sig) == [False, False, True, True, True, False, False, True, True]


def test_the_trend_filter_stop_is_raised_but_never_lowered_by_a_falling_candidate():
    sma = [NAN] + [100.0] * 7
    atr = [NAN] + [2.0] * 7
    c = [99, 99, 101, 103, 104, 102, 101, 101]                                             # candidates (close - 4): -, 95, 97, 99, 100, 98, 97, 97
    l = [98, 98, 100, 102, 103, 100.5, 99.5, 100.5]                                        # the stop reaches 100 at index 4; index 5 closes lower (candidate 98) but its low 100.5 stays above 100
    sig = S.FAMILIES["ma_atr_trend"].build(Fake(c, l=l, sma_100=sma, atr_14=atr), {"L": 100, "m": 2})
    assert states(sig) == [False, False, True, True, True, True, False, False]             # index 6: low 99.5 touches the stop that is still 100 (not 98)


def test_ma_atr_trend_asks_for_the_right_average_and_the_fourteen_day_atr():
    b = Fake([99, 101], l=[98, 100], sma_150=[100, 100], atr_14=[2, 2])
    S.FAMILIES["ma_atr_trend"].build(b, {"L": 150, "m": 3})
    assert sorted(set(b.asked)) == ["atr_14", "sma_150"]


# ---- family 4: tsmom ----

def test_tsmom_is_on_when_the_return_over_the_lookback_is_strictly_positive():
    sig = S.signals("tsmom", candles([100, 101, 99, 102, 98, 97, 99]), {"L": 2})
    # returns over 2 candles: -, -, -1%, +0.99%, -1.0%, -4.9%, +1.0%
    assert states(sig) == [False, False, False, True, False, False, True]
    assert states(S.signals("tsmom", candles([100, 100, 100]), {"L": 2})) == [False, False, False]      # exactly zero is not positive


# ---- families 5 and 8: RSI with two thresholds ----

def test_rsi_momentum_turns_on_above_the_enter_level_off_below_the_exit_level_and_holds_in_between():
    b = Fake([1] * 10, rsi_14=[NAN, 50, 56, 54, 49, 44, 39, 45, 52, 61])
    sig = S.FAMILIES["rsi_momentum"].build(b, {"n": 14, "enter": 55, "exit": 45})
    assert states(sig) == [False, False, True, True, True, False, False, False, False, True]
    b = Fake([1] * 5, rsi_21=[50, 55, 56, 45, 44])
    assert states(S.FAMILIES["rsi_momentum"].build(b, {"n": 21, "enter": 55, "exit": 45})) == [False, False, True, True, False]      # 55 does not enter, 45 does not exit


def test_rsi_oversold_turns_on_below_the_enter_level_off_above_the_exit_level_and_holds_in_between():
    b = Fake([1] * 9, rsi_7=[NAN, 40, 24, 30, 50, 51, 26, 25, 56])
    sig = S.FAMILIES["rsi_oversold"].build(b, {"n": 7, "enter": 25, "exit": 50})
    assert states(sig) == [False, False, True, True, True, False, False, False, False]      # 25 does not enter, 50 does not exit, 51 does


# ---- family 6: mom_vol ----

def test_mom_vol_needs_a_positive_return_and_a_volatility_at_or_below_the_cap():
    b = Fake([1] * 6, change_60=[NAN, 0.1, 0.1, -0.1, 0.1, 0.0], vol_20=[NAN, 0.5, 0.9, 0.5, 0.8, 0.5])
    sig = S.FAMILIES["mom_vol"].build(b, {"L": 60, "cap": 0.8})
    assert states(sig) == [False, True, False, False, True, False]                         # 0.9 is over the cap, 0.8 is not, a zero return is not positive


# ---- family 7: bollinger_mr ----

def test_bollinger_enters_below_the_lower_band_and_leaves_at_the_middle_band():
    c = [100, 97, 95.9, 98, 99.9, 100, 96]
    b = Fake(c, sma_20=[NAN] + [100.0] * 6, std0_20=[NAN] + [2.0] * 6)                       # lower band at k = 2: 96
    sig = S.FAMILIES["bollinger_mr"].build(b, {"n": 20, "k": 2.0})
    assert states(sig) == [False, False, True, True, True, False, False]                    # 97 is above the band, 95.9 below it; stays on until 100 reaches the middle; 96 is not below 96


# ---- family 9: vol_breakout ----

def test_vol_breakout_holds_for_exactly_the_hold_period_and_ignores_breakouts_while_on_and_on_the_day_it_ends():
    c = [100, 100, 104, 108, 108, 112, 112, 116, 116, 116]
    b = Fake(c, atr_14=[NAN, 2, 100, 2, 2, 2, 2, 2, 2, 2])                                  # atr[2] is huge: the test must use the PREVIOUS candle's atr
    sig = S.FAMILIES["vol_breakout"].build(b, {"k": 1.5, "hold": 3})
    assert states(sig) == [False, False, True, True, True, False, False, True, True, True]


def test_a_move_equal_to_k_times_the_previous_atr_is_not_a_breakout():
    b = Fake([100, 100, 103, 103], atr_14=[NAN, 2, 2, 2])
    assert states(S.FAMILIES["vol_breakout"].build(b, {"k": 1.5, "hold": 3})) == [False, False, False, False]
    b = Fake([100, 100, 103.01, 103.01], atr_14=[NAN, 2, 2, 2])
    assert states(S.FAMILIES["vol_breakout"].build(b, {"k": 1.5, "hold": 2})) == [False, False, True, True]


def test_vol_breakout_ignores_down_moves():
    b = Fake([100, 100, 90, 90], atr_14=[NAN, 2, 2, 2])
    assert states(S.FAMILIES["vol_breakout"].build(b, {"k": 1.0, "hold": 3})) == [False] * 4


# ---- family 10: regime_switch ----

def test_regime_switch_follows_the_average_cross_when_trending_and_buys_the_lower_band_when_ranging():
    c = [100, 105, 105, 96, 98, 96, 96, 105]
    b = Fake(c, adx_14=[NAN, 30, 30, 20, 20, 25, 26, 30], sma_50=[NAN, 110, 90, 110, 110, 90, 110, 100], sma_200=[NAN] + [100.0] * 7,
             sma_20=[NAN] + [100.0] * 7, std0_20=[NAN] + [2.0] * 7)                          # lower band 100 - 1.5 x 2 = 97
    sig = S.FAMILIES["regime_switch"].build(b, {"adx": 25})
    # 1: trending, 50 above 200: on; 2: trending, 50 below 200: off; 3: ranging, 96 below 97: on; 4: ranging, 98 above the band: off although 50 is above 200;
    # 5: ADX exactly 25 is NOT above 25, so ranging: 96 is below the band: on, although the 50 is below the 200 (the ranging branch ignores the averages);
    # 6: ADX 26 trending, 50 above 200: on; 7: trending, 50 equal to 200 is not above: off
    assert states(sig) == [False, True, False, True, False, True, True, False]


# ---- family 11: vol_target ----

def test_vol_target_weight_is_target_over_volatility_capped_at_one_and_zero_without_a_volatility():
    b = Fake([1] * 6, vol_20=[NAN, 0.2, 0.5, 1.0, 0.0, 0.8])
    sig = S.FAMILIES["vol_target"].build(b, {"target": 0.4, "window": 20})
    assert list(sig.weight) == pytest.approx([0.0, 1.0, 0.8, 0.4, 0.0, 0.5]) and sig.state is None and sig.stop is None
    b = Fake([1] * 3, vol_40=[NAN, 0.2, 0.8])
    assert list(S.FAMILIES["vol_target"].build(b, {"target": 0.3, "window": 40}).weight) == pytest.approx([0.0, 1.0, 0.375])


# ---- family 12: sma_filter ----

def test_sma_filter_is_fully_invested_only_while_the_close_is_strictly_above_its_average():
    # SMA3 = [-, -, 11, 11.333, 10.667, 9.333, 10]
    sig = S.signals("sma_filter", candles([10, 11, 12, 11, 9, 8, 13]), {"L": 3})
    assert list(sig.weight) == [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0] and sig.state is None
    assert list(S.signals("sma_filter", candles([10, 10, 10, 10]), {"L": 3}).weight) == [0.0] * 4          # equal is not above


# ---- family 13: monday (a calendar rule, weight mode; pre-registered under protocol 1.3) ----

def utc(y, m, d, h=0, mi=0, sec=0):
    return int(datetime(y, m, d, h, mi, sec, tzinfo=timezone.utc).timestamp())


def flat_days(first=(2026, 11, 9), n=14, price=100.0):
    """n flat daily candles opening at 00:00 UTC, starting on `first` (a Monday): 2026-11-09 is a Monday and 2026-11-15 a Sunday."""
    t0 = utc(*first)
    return [(t0 + i * DAY, price, price, price, price, 1.0) for i in range(n)]


def true_weekday(t):
    return datetime.fromtimestamp(t, timezone.utc).weekday()                         # the calendar's own answer: Monday is 0


def test_the_weekday_number_is_monday_zero_counted_from_the_utc_open_time_of_the_candle():
    ts = [utc(1970, 1, 1), utc(2026, 11, 9), utc(2026, 11, 10), utc(2026, 11, 14), utc(2026, 11, 15), utc(2000, 2, 29), utc(2024, 2, 29)]
    assert S.weekday(ts).tolist() == [3, 0, 1, 5, 6, 1, 3] == [true_weekday(t) for t in ts]                        # 1970-01-01 was a Thursday; 2000-02-29 a Tuesday; 2024-02-29 a Thursday
    assert S.weekday([utc(2026, 11, 9) - 1]).tolist() == [6] and S.weekday([utc(2026, 11, 9, 23, 59, 59)]).tolist() == [0]      # the day changes at 00:00:00 UTC, not a second earlier


def test_monday_wants_all_of_the_equity_from_the_open_after_each_sunday_close_and_none_of_it_otherwise():
    cs = flat_days()
    sig = S.signals("monday", cs, {"day": 0})
    assert list(sig.weight) == [0.0] * 6 + [1.0] + [0.0] * 6 + [1.0] and sig.state is None and sig.stop is None
    for i in (6, 13):
        assert true_weekday(cs[i][0]) == 6                                                                             # the close of a Sunday candle ...
    n_held = [i + 1 for i in range(len(cs) - 1) if sig.weight[i] == 1.0]
    assert n_held == [7] and true_weekday(cs[7][0]) == 0                                                              # ... is when it buys, so the position is held through the Monday candle


def test_the_held_weekday_is_a_setting_and_the_day_before_it_wraps_around_the_week():
    cs = flat_days(n=21)
    for day in range(7):
        w = S.signals("monday", cs, {"day": day}).weight
        want = [1.0 if (true_weekday(t) + 1) % 7 == day else 0.0 for t, *_ in cs]                                     # on the close of the day before the held one
        assert list(w) == want, day
        assert sum(want) == 3                                                                                          # once a week
    assert S.signals("monday", cs, {"day": 6}).weight[5] == 1.0 and S.signals("monday", cs, {"day": 0}).weight[6] == 1.0     # holding Sunday: buy at the close of Saturday (index 5); holding Monday: close of Sunday (index 6)


def test_monday_needs_no_warm_up_and_reads_only_the_open_time_of_the_candle():
    assert list(S.signals("monday", flat_days(first=(2026, 11, 15), n=2), {"day": 0}).weight) == [1.0, 0.0]            # the first candle may already be a Sunday
    assert list(S.signals("monday", flat_days(n=1), {"day": 0}).weight) == [0.0]
    cs = flat_days(n=30)
    wild = [(t, o * 7, h * 9, l * 0.1, c * 3, v) for t, o, h, l, c, v in cs]
    assert list(S.signals("monday", wild, {"day": 0}).weight) == list(S.signals("monday", cs, {"day": 0}).weight)       # prices play no part in it


def test_monday_is_registered_as_family_13_in_weight_mode_with_one_configuration_and_no_neighbours():
    fam = S.FAMILIES["monday"]
    assert (fam.kind, fam.since, fam.trail, fam.category) == ("weight", "1.3", False, "calendar")
    assert S.configs(fam) == [{"day": 0}] and S.neighbours(fam, {"day": 0}) == []
    assert [f.id for f in S.RESEARCH][-1] == "monday" and S.spec("monday", {"day": 0})["protocol"] == "1.3" and S.spec("tsmom", {"L": 30})["protocol"] == "1.2"
    assert S.spec_hash("monday", {"day": 0}) != S.spec_hash("monday", {"day": 1})


def test_monday_explains_a_signal_with_the_weekday_of_the_candle_and_the_held_day():
    cs = flat_days()
    b = S.Bars(cs)
    assert S.FAMILIES["monday"].explain(b, {"day": 0}, 6) == {"close": 100.0, "candle_weekday": 6, "held_weekday": 0}
    assert S.FAMILIES["monday"].explain(b, {"day": 0}, 2) == {"close": 100.0, "candle_weekday": 2, "held_weekday": 0}


def test_monday_through_the_account_engine_a_flat_price_loses_exactly_the_round_trip_costs_each_week():
    cs = flat_days(n=35)                                                                          # Sundays at indices 6, 13, 20, 27 and 34
    prep = B.Prepared(cs)
    r = B.run(prep, "monday", {"day": 0}, 1, 34, keep_account=True)
    q = (1 - C.SLIPPAGE) * (1 - C.FEE) / ((1 + C.SLIPPAGE) * (1 + C.FEE))                       # one buy and one sell of the whole account at a flat price: the fee and the slippage on each side
    assert r.metrics["fills"] == 8                                                                  # four round trips; the fifth Sunday's order is still pending when the data end
    assert r.metrics["breaker_trips"] == 0 and r.account.curve[-1][1] == pytest.approx(C.START_EQUITY_STRATEGY * q ** 4, rel=1e-9)
    held = [j + 1 for j, e in enumerate(r.exposure) if e > 0.5]                                     # the candle index of each day the account is invested through (run index j is candle j + 1)
    assert held == [7, 14, 21, 28] and all(true_weekday(cs[i][0]) == 0 for i in held)               # fully invested through each Monday and through no other day
    assert r.exposure[6] == pytest.approx(1.0, rel=1e-6)


# ---- benchmarks ----

def test_the_benchmarks_carry_no_signal():
    for fid in ("buy_hold", "cash"):
        sig = S.signals(fid, candles([1, 2, 3]), {})
        assert sig.state is None and sig.weight is None and sig.stop is None
    assert S.FAMILIES["buy_hold"].kind == "hold" and S.FAMILIES["cash"].kind == "cash"


# ---- shape of the output for every configuration ----

def test_every_configuration_returns_signals_of_the_right_kind_and_length():
    cs = walk(420, seed=11)
    b = S.Bars(cs)
    for f in S.RESEARCH:
        for p in S.configs(f):
            sig = f.build(b, p)
            if f.kind == "stop":
                assert sig.state.dtype == bool and len(sig.state) == 420 and len(sig.stop) == 420 and sig.weight is None, (f.id, p)
            else:
                assert f.kind == "weight" and len(sig.weight) == 420 and sig.state is None, (f.id, p)
                assert np.all((sig.weight >= 0.0) & (sig.weight <= 1.0)), (f.id, p)


def test_stop_based_families_declare_trailing_stops_only_where_the_note_says_so():
    assert sorted(f.id for f in S.RESEARCH if f.trail) == ["donchian", "ma_atr_trend"]
    assert {f.id for f in S.RESEARCH if f.kind == "weight"} == {"vol_target", "sma_filter", "monday"}


def test_each_family_explains_a_signal_in_numbers_that_can_be_written_to_the_ledger():
    cs = walk(420, seed=5)
    b = S.Bars(cs)
    for f in S.FAMILIES.values():
        for p in S.configs(f)[:2]:
            info = f.explain(b, p, 300)
            assert isinstance(info, dict)
            json.dumps(info)                                                               # plain numbers only: no numpy types, no NaN objects
            for v in info.values():
                assert v is None or isinstance(v, float)
    assert S.FAMILIES["sma_cross"].explain(b, {"fast": 20, "slow": 100}, 300).keys() == {"close", "sma_fast", "sma_slow", "atr14"}
    assert S.FAMILIES["sma_cross"].explain(b, {"fast": 20, "slow": 100}, 5)["sma_slow"] is None             # before the average exists: None, not NaN


# ---- no look-ahead ----

@pytest.mark.parametrize("cut", [300, 520])
def test_changing_later_candles_never_moves_an_earlier_signal_for_any_configuration(cut):
    base = walk(700, seed=21)
    other = walk(700, seed=99, start=base[cut][4], vol=0.05)
    changed = base[:cut + 1] + [(base[i][0],) + other[i][1:] for i in range(cut + 1, 700)]
    b1, b2 = S.Bars(base), S.Bars(changed)
    moved_later = 0
    for f in S.RESEARCH:
        for p in S.configs(f):
            s1, s2 = f.build(b1, p), f.build(b2, p)
            for name in ("state", "weight", "stop"):
                a, c = getattr(s1, name), getattr(s2, name)
                if a is None:
                    assert c is None
                    continue
                assert np.array_equal(a[:cut + 1], c[:cut + 1], equal_nan=True), (f.id, p, name)
                moved_later += int(not np.array_equal(a[cut + 1:], c[cut + 1:], equal_nan=True))
    assert moved_later > 50                                                                # the test is able to see a dependence: later signals do move


def test_a_signal_needs_the_candle_it_is_made_on_but_not_the_one_after():
    base = walk(260, seed=2)
    shorter = base[:200]
    for f in S.RESEARCH:
        p = S.configs(f)[0]
        full, cut = f.build(S.Bars(base), p), f.build(S.Bars(shorter), p)
        for name in ("state", "weight", "stop"):
            a, c = getattr(full, name), getattr(cut, name)
            if a is not None:
                assert np.array_equal(a[:200], c, equal_nan=True), (f.id, name)


# ---- the notes say what the code does ----

REQUIRED = ["## Hypothesis", "## Why it might work", "## Where it should work, and where it should fail", "## Rules", "## Position sizing", "## Parameters", "## Costs and risk limits",
            "## Failure modes", "## Expectation written down before running", "## Sources"]


@pytest.mark.parametrize("fid", list(S.FAMILIES))
def test_each_family_and_benchmark_has_a_note_whose_grid_is_the_codes(fid):
    text = (C.ROOT / "strategies" / f"{fid}.md").read_text(encoding="utf-8")
    fam = S.FAMILIES[fid]
    grid = re.search(r"^Grid: (.*)$", text, re.M).group(1)
    n = int(re.search(r"^Configurations: (\d+)$", text, re.M).group(1))
    assert json.loads(grid) == fam.grid and n == len(S.configs(fam))
    if fam.category != "benchmark":
        for heading in REQUIRED:
            assert any(line.startswith(heading) for line in text.splitlines()), (fid, heading)
        assert "written 2026-11-15, before any run" in text and ("`SOURCES.md`" in text)


def test_the_sources_file_exists_and_every_cited_family_note_points_to_it():
    assert (C.ROOT / "strategies" / "SOURCES.md").is_file()
    assert "Still to check" in (C.ROOT / "strategies" / "SOURCES.md").read_text(encoding="utf-8")
