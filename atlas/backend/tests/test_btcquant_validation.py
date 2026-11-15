"""btcquant validation: selection that prefers a stable region, the stability gate at its exact boundaries, the deflated Sharpe ratio against a closed form computed a second way, the random-timing null
on a planted skill and on no skill, calendar arithmetic and the walk-forward windows, every admission and promotion gate at the value that just passes and the value that just fails, and one family end to end."""
import json
import math
import statistics
from datetime import date

import numpy as np
import pytest

from atlas_api.btcquant import backtest as B
from atlas_api.btcquant import config as C
from atlas_api.btcquant import metrics as M
from atlas_api.btcquant import strategies as S
from atlas_api.btcquant import validation as V

DAY = 86400


class FakeRun:
    def __init__(self, sharpe, turnover=1.0):
        self.metrics = {"sharpe": sharpe, "turnover": turnover}


def runs_for(fam_id, sharpes, turnovers=None):
    cfgs = S.configs(S.FAMILIES[fam_id])
    return {B.param_key(p): FakeRun(sharpes[i], 1.0 if turnovers is None else turnovers[i]) for i, p in enumerate(cfgs)}


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def phi_inv(p):
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if phi(mid) < p else (lo, mid)
    return (lo + hi) / 2


# ---- selection ----

def test_the_winner_is_the_stable_region_not_the_isolated_peak():
    fam = S.FAMILIES["donchian"]                                                       # N = 20, 40, 55, 80 in a line
    sel = V.select(runs_for("donchian", [1.0, 0.2, 0.9, 0.8]), fam)
    # scores: 20 -> mean(1.0, 0.2) = 0.6; 40 -> mean(0.2, 1.0, 0.9) = 0.7; 55 -> mean(0.9, 0.2, 0.8) = 0.633; 80 -> mean(0.8, 0.9) = 0.85
    assert sel["params"] == {"N": 80} and sel["scores"][B.param_key({"N": 20})] == pytest.approx(0.6) and sel["scores"][B.param_key({"N": 40})] == pytest.approx(0.7)
    assert sel["scores"][B.param_key({"N": 55})] == pytest.approx((0.9 + 0.2 + 0.8) / 3) and sel["scores"][B.param_key({"N": 80})] == pytest.approx(0.85)
    assert [dict(k)["N"] for k in sel["ranking"]] == [80, 40, 55, 20]


def test_a_tie_goes_to_lower_turnover_then_to_the_first_in_grid_order():
    fam = S.FAMILIES["donchian"]
    sel = V.select(runs_for("donchian", [0.5] * 4, turnovers=[3.0, 1.0, 2.0, 1.5]), fam)
    assert sel["params"] == {"N": 40}
    same = V.select(runs_for("donchian", [0.5] * 4, turnovers=[2.0, 2.0, 2.0, 2.0]), fam)
    assert same["params"] == {"N": 20}
    assert [dict(k)["N"] for k in V.select(runs_for("donchian", [0.5] * 4, turnovers=[3.0, 1.0, 2.0, 1.5]), fam)["ranking"]] == [40, 80, 55, 20]


def test_an_undefined_sharpe_counts_as_zero_when_ranking():
    fam = S.FAMILIES["donchian"]
    sel = V.select(runs_for("donchian", [None, None, None, -0.1]), fam)
    assert sel["sharpe"][B.param_key({"N": 20})] == 0.0 and sel["params"] == {"N": 20}                # scores: 0, 0, -0.033, -0.05: the first of the tied best


def test_selection_uses_the_neighbours_of_a_two_parameter_grid():
    fam = S.FAMILIES["sma_cross"]
    cfgs = S.configs(fam)
    sharpes = [0.0] * len(cfgs)
    spike = cfgs.index({"fast": 30, "slow": 100})
    sharpes[spike] = 2.0                                                               # a lone spike with the best own Sharpe, surrounded by zeros
    block = [{"fast": 10, "slow": 150}, {"fast": 10, "slow": 200}, {"fast": 20, "slow": 150}, {"fast": 20, "slow": 200}]
    for p in block:
        sharpes[cfgs.index(p)] = 1.0                                                   # a 2 x 2 block of decent configurations
    sel = V.select(runs_for("sma_cross", sharpes), fam)
    # (10, 200) has the neighbours (20, 200) and (10, 150), both in the block: (1 + 1 + 1) / 3 = 1.0. The spike scores (2 + 0 + 0 + 0 + 0) / 5 = 0.4.
    assert sel["params"] == {"fast": 10, "slow": 200} and sel["scores"][B.param_key(sel["params"])] == pytest.approx(1.0)
    assert sel["scores"][B.param_key({"fast": 30, "slow": 100})] == pytest.approx(0.4) and sel["params"] in block
    assert sel["scores"][B.param_key({"fast": 20, "slow": 150})] == pytest.approx(0.6) and sel["scores"][B.param_key({"fast": 10, "slow": 150})] == pytest.approx(0.75)


# ---- the stability gate ----

def test_stability_needs_sixty_percent_of_the_neighbours_at_seventy_percent_of_the_chosen_sharpe():
    fam = S.FAMILIES["rsi_momentum"]
    chosen = {"n": 14, "enter": 60, "exit": 45}
    nbs = [B.param_key(q) for q in S.neighbours(fam, chosen)]
    assert len(nbs) == 5

    def check(values):
        sharpe = {B.param_key(chosen): 1.0}
        sharpe.update({k: v for k, v in zip(nbs, values)})
        return V.stability(sharpe, fam, chosen)
    ok = check([0.7, 0.7, 0.7, 0.69, 0.0])                                             # three of five reach 0.7 exactly: 60% passes
    assert ok["passes"] and ok["reaching"] == 3 and ok["share"] == pytest.approx(0.6) and ok["threshold"] == pytest.approx(0.7) and ok["applicable"]
    assert not check([0.7, 0.7, 0.69, 0.69, 0.69])["passes"]                           # two of five: 40%
    assert check([0.6999, 0.9, 0.9, 0.9, 0.9])["passes"]                               # four of five reach it: 80%
    assert V.stability({B.param_key(chosen): 1.0, **{k: 1.2 for k in nbs}}, fam, chosen)["passes"]


def test_stability_is_not_computed_for_a_chosen_configuration_that_is_not_positive():
    fam = S.FAMILIES["donchian"]
    for own in (0.0, -0.5):
        res = V.stability({B.param_key({"N": 20}): own, B.param_key({"N": 40}): 5.0, B.param_key({"N": 55}): 0.0, B.param_key({"N": 80}): 0.0}, fam, {"N": 20})
        assert res["applicable"] is False and res["passes"] is False


def test_a_family_with_one_configuration_has_no_neighbours_so_a4_asks_only_that_its_own_train_sharpe_is_above_zero():
    fam = S.FAMILIES["monday"]
    key = B.param_key({"day": 0})
    for own in (0.01, 0.4, 3.0):
        assert V.stability({key: own}, fam, {"day": 0}) == {"applicable": False, "passes": True, "neighbours": 0, "reaching": 0, "share": None, "threshold": None, "single": True}
    for own in (0.0, -0.3):                                                                    # nothing to compare with, but a rule that lost money on TRAIN is still not stable in any useful sense
        res = V.stability({key: own}, fam, {"day": 0})
        assert res["passes"] is False and res["single"] is True and res["neighbours"] == 0 and res["applicable"] is False
    many = V.stability({B.param_key({"N": 20}): 1.0, B.param_key({"N": 40}): 0.9, B.param_key({"N": 55}): 0.0, B.param_key({"N": 80}): 0.0}, S.FAMILIES["donchian"], {"N": 20})
    assert "single" not in many and many["neighbours"] == 1 and many["passes"] is True               # a family with neighbours is judged as before


def test_a_two_neighbour_family_needs_both_neighbours_to_keep_the_result():
    fam = S.FAMILIES["donchian"]                                                       # N = 40 has the neighbours 20 and 55
    base = {B.param_key({"N": 40}): 1.0, B.param_key({"N": 80}): 0.0}
    one = {**base, B.param_key({"N": 20}): 0.7, B.param_key({"N": 55}): 0.0}
    both = {**base, B.param_key({"N": 20}): 0.7, B.param_key({"N": 55}): 0.7}
    assert not V.stability(one, fam, {"N": 40})["passes"] and V.stability(both, fam, {"N": 40})["passes"]       # one of two is 50%: not enough


def test_a_single_neighbour_family_must_have_that_neighbour_keep_the_result():
    fam = S.FAMILIES["donchian"]                                                       # N = 20 has only the neighbour N = 40
    base = {B.param_key({"N": 20}): 1.0, B.param_key({"N": 55}): 0.0, B.param_key({"N": 80}): 0.0}
    assert V.stability({**base, B.param_key({"N": 40}): 0.7}, fam, {"N": 20})["passes"] and not V.stability({**base, B.param_key({"N": 40}): 0.6}, fam, {"N": 20})["passes"]


# ---- statistics of returns and the deflated Sharpe ratio ----

def test_return_statistics_by_hand():
    r = [0.01, -0.01, 0.02, 0.0]                                                       # mean 0.005; deviations 0.005, -0.015, 0.015, -0.005
    s = V.return_stats(r)
    assert s["T"] == 4 and s["sr_daily"] == pytest.approx(0.005 / statistics.stdev(r)) and s["sharpe"] == pytest.approx(7.39932429, rel=1e-8)
    assert s["skew"] == pytest.approx(0.0, abs=1e-12)                                  # the third moments cancel
    assert s["kurt"] == pytest.approx(1.64)                                            # m4 = 2.5625e-8, variance (population) 1.25e-4, so 2.5625e-8 / 1.5625e-8
    for bad in ([0.01, 0.01, 0.01], [0.0, 0.0, 0.0], [0.01, 0.02], []):
        assert V.return_stats(bad)["sr_daily"] is None


def test_the_expected_maximum_of_independent_normals():
    assert V.expected_max_normal(100) == pytest.approx((1 - V.EULER) * phi_inv(0.99) + V.EULER * phi_inv(1 - 1 / (100 * math.e)), rel=1e-9) and V.expected_max_normal(100) == pytest.approx(2.5306029, rel=1e-7)
    assert V.expected_max_normal(2) < V.expected_max_normal(10) < V.expected_max_normal(100) < V.expected_max_normal(1000)


def test_the_deflated_sharpe_ratio_against_a_closed_form():
    d = V.deflated_sharpe(0.1, 1000, 0.0, 3.0, 100, 1e-4)
    assert d["sr0"] == pytest.approx(0.01 * 2.5306028932, rel=1e-9) and d["z"] == pytest.approx(2.3549693673, rel=1e-9) and d["dsr"] == pytest.approx(0.9907378837, rel=1e-9)
    assert V.deflated_sharpe(0.1, 1000, -1.0, 3.0, 100, 1e-4)["dsr"] == pytest.approx(0.9876442528, rel=1e-9)             # a negative skew lowers it
    assert V.deflated_sharpe(0.1, 1000, -1.0, 3.0, 100, 1e-4)["dsr"] < d["dsr"] < V.deflated_sharpe(0.1, 1000, 1.0, 3.0, 100, 1e-4)["dsr"]


def test_the_deflated_sharpe_ratio_moves_the_right_way():
    base = V.deflated_sharpe(0.1, 1000, 0.0, 3.0, 100, 1e-4)["dsr"]
    assert V.deflated_sharpe(0.12, 1000, 0.0, 3.0, 100, 1e-4)["dsr"] > base                                     # a higher Sharpe
    assert V.deflated_sharpe(0.1, 1000, 0.0, 3.0, 100, 4e-4)["dsr"] < base                                      # trials that disagree more: a higher bar
    assert V.deflated_sharpe(0.1, 1000, 0.0, 3.0, 1000, 1e-4)["dsr"] < base                                     # more trials
    assert V.deflated_sharpe(0.1, 2000, 0.0, 3.0, 100, 1e-4)["dsr"] > base                                      # a longer record
    assert V.deflated_sharpe(0.1, 1000, 0.0, 8.0, 100, 1e-4)["dsr"] < base                                      # fatter tails


def test_a_sharpe_exactly_at_the_luck_threshold_gives_one_half_and_impossible_inputs_give_none():
    sr0 = V.deflated_sharpe(0.1, 1000, 0.0, 3.0, 100, 1e-4)["sr0"]
    assert V.deflated_sharpe(sr0, 1000, 0.0, 3.0, 100, 1e-4)["dsr"] == pytest.approx(0.5, abs=1e-12)
    assert V.deflated_sharpe(None, 1000, 0.0, 3.0, 100, 1e-4)["dsr"] is None and V.deflated_sharpe(0.1, 1, 0.0, 3.0, 100, 1e-4)["dsr"] is None
    assert V.deflated_sharpe(0.1, 1000, None, 3.0, 100, 1e-4)["dsr"] is None and V.deflated_sharpe(0.1, 1000, 0.0, None, 100, 1e-4)["dsr"] is None
    assert V.deflated_sharpe(5.0, 1000, 10.0, 3.0, 100, 1e-4)["dsr"] is None                                    # the variance of the estimate would be negative
    with pytest.raises(ValueError):
        V.deflated_sharpe(0.1, 1000, 0.0, 3.0, 1, 1e-4)


# ---- the random-timing null ----

def test_timing_sharpe_by_hand_for_the_real_schedule_and_a_shifted_one():
    e, r = [0.0, 1.0, 1.0, 0.0], [0.01, 0.02, -0.01, 0.03]
    assert V.timing_sharpe(e, r, 0.001, 0) == pytest.approx(3.133788091542021, rel=1e-12)                       # returns 0, 0.019, -0.01, -0.001 (cost on each change; starts flat)
    assert V.timing_sharpe(e, r, 0.001, 1) == pytest.approx(4.854279311100739, rel=1e-12)                       # shifted: held = 0, 0, 1, 1; the circular previous of index 0 is 1


def test_the_real_schedule_pays_to_enter_on_its_first_day_even_when_it_ends_invested():
    # held = 1, 1, 0, 1 and the real schedule starts flat: the first day pays for the purchase (a circular reading would have found it already invested)
    assert V.timing_sharpe([1.0, 1.0, 0.0, 1.0], [0.01, 0.02, -0.01, 0.03], 0.001, 0) == pytest.approx(20.864968638834796, rel=1e-12)


def test_the_shift_sample_depends_on_the_seed_and_defaults_to_the_fixed_one():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.02, 700)
    e = (rng.random(700) > 0.5).astype(float)
    a, b = V.random_timing(e, r, n_shifts=100, seed=1), V.random_timing(e, r, n_shifts=100, seed=2)
    c, d = V.random_timing(e, r, n_shifts=100), V.random_timing(e, r, n_shifts=100, seed=V.NULL_SEED)
    assert c == d and len({a["median_shifted"], b["median_shifted"], c["median_shifted"]}) == 3


def test_a_schedule_that_knows_the_future_is_caught_and_a_schedule_that_does_not_is_not():
    rng = np.random.default_rng(5)
    n = 900
    r = rng.normal(0.0004, 0.03, n)
    skill = V.random_timing((r > 0).astype(float), r)
    assert skill["p"] == 0.0 and skill["real"] > 5 and skill["shifts"] == 781 and skill["at_least_as_good"] == 0
    blocks = np.repeat(np.random.default_rng(11).integers(0, 2, n // 30 + 1), 30)[:n].astype(float)
    none = V.random_timing(blocks, r)
    assert none["p"] > 0.2 and none["real"] < 1.0
    assert V.random_timing(np.zeros(n), r)["p"] is None


def test_the_shifts_are_distinct_whole_days_at_least_sixty_from_the_real_alignment(monkeypatch):
    seen = []
    real = V.timing_sharpe

    def spy(e, r, cost, shift):
        seen.append(shift)
        return real(e, r, cost, shift)
    monkeypatch.setattr(V, "timing_sharpe", spy)
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.02, 500)
    V.random_timing((rng.random(500) > 0.5).astype(float), r, n_shifts=100)
    shifts = seen[1:]                                                                  # the first call is the real schedule (shift 0)
    assert seen[0] == 0 and len(shifts) == 100 and len(set(shifts)) == 100 and min(shifts) >= 60 and max(shifts) <= 500 - 60
    seen.clear()
    V.random_timing((rng.random(130) > 0.5).astype(float), r[:130])                    # 130 days: only shifts 60 to 70 exist, so all eleven are used
    assert sorted(seen[1:]) == list(range(60, 71))


def test_the_p_value_is_the_share_of_shifted_copies_at_least_as_good_as_the_real_schedule(monkeypatch):
    def fake(e, r, cost, shift):
        return 1.0 if shift % 2 == 0 else 0.0                                          # the real one (shift 0) scores 1.0; even shifts tie it
    monkeypatch.setattr(V, "timing_sharpe", fake)
    out = V.random_timing(np.ones(130), np.zeros(130))
    assert out["shifts"] == 11 and out["at_least_as_good"] == 6 and out["p"] == pytest.approx(6 / 11)                # shifts 60, 62, ..., 70
    assert V.random_timing(np.ones(130), np.zeros(130), seed=3)["p"] == pytest.approx(6 / 11)


def test_the_null_is_reproducible_for_a_seed():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.02, 700)
    e = (rng.random(700) > 0.5).astype(float)
    assert V.random_timing(e, r) == V.random_timing(e, r) and V.random_timing(e, r, n_shifts=200, seed=1) == V.random_timing(e, r, n_shifts=200, seed=1)


# ---- calendar and walk-forward ----

def test_month_arithmetic():
    assert V.add_months(date(2021, 12, 31), 6) == date(2022, 6, 30) and V.add_months(date(2022, 6, 30), 6) == date(2022, 12, 30)
    assert V.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29) and V.add_months(date(2023, 1, 31), 1) == date(2023, 2, 28) and V.add_months(date(2023, 11, 15), 3) == date(2024, 2, 15)
    assert V.month_end(date(2022, 12, 30)) == date(2022, 12, 31) and V.month_end(date(2024, 2, 10)) == date(2024, 2, 29) and V.month_end(date(2023, 4, 30)) == date(2023, 4, 30)


def test_the_walk_forward_windows_tile_the_time_after_the_first_fit_with_no_gap_or_overlap():
    segs = V.wf_segments(date(2021, 12, 31), 6, date(2026, 11, 14))
    assert len(segs) == 10 and segs[0] == (date(2021, 12, 31), date(2022, 1, 1), date(2022, 6, 30)) and segs[1] == (date(2022, 6, 30), date(2022, 7, 1), date(2022, 12, 31))
    assert segs[-1] == (date(2026, 6, 30), date(2026, 7, 1), date(2026, 11, 14))
    for a, b in zip(segs, segs[1:]):
        assert (b[1] - a[2]).days == 1 and b[0] == a[2]
    assert V.wf_segments(date(2021, 12, 31), 6, date(2021, 12, 31)) == []
    assert V.wf_segments(date(2021, 12, 31), 6, date(2022, 1, 1)) == [(date(2021, 12, 31), date(2022, 1, 1), date(2022, 1, 1))]
    assert V.wf_segments(date(2021, 12, 31), 6, date(2022, 6, 30)) == [(date(2021, 12, 31), date(2022, 1, 1), date(2022, 6, 30))]
    assert V.wf_segments(date(2021, 12, 31), 6, date(2022, 7, 1))[-1] == (date(2022, 6, 30), date(2022, 7, 1), date(2022, 7, 1))


def test_the_walk_forward_verdict_at_its_boundaries():
    assert V.wf_passes(1.0, 1.0, 3, 5) is True and V.wf_passes(0.99, 1.0, 5, 5) is False and V.wf_passes(1.0, 1.0, 2, 5) is False
    assert V.wf_passes(None, 1.0, 5, 5) is False and V.wf_passes(1.0, None, 5, 5) is False and V.wf_passes(1.0, 1.0, 0, 0) is False
    assert V.wf_passes(1.0, 1.0, 6, 10) is True and V.wf_passes(1.0, 1.0, 5, 10) is False


def history(n, seed=1, start=20_000.0, vol=0.03):
    from test_btcquant_backtest import history as h
    return h(n, seed=seed, start=start, vol=vol)


def test_walk_forward_chooses_each_window_from_the_data_before_it_and_stitches_the_record():
    cs = history(1100, seed=14, vol=0.035)                                                # 2019-01-01 to 2022-01-04
    prep = B.Prepared(cs)
    out = V.walk_forward(prep, "tsmom", fit_start=date(2020, 1, 1), first_fit_end=date(2020, 12, 31), step_months=3)
    assert out["windows"] == 5 and [r["oos_end"] for r in out["segments"]] == ["2021-03-31", "2021-06-30", "2021-09-30", "2021-12-31", "2022-01-04"]
    assert out["segments"][-1]["days"] == 4
    fam = S.FAMILIES["tsmom"]
    for row in out["segments"]:
        f0, f1 = prep.span(date(2020, 1, 1), date.fromisoformat(row["fit_end"]))
        assert row["chosen"] == V.select(B.run_all(prep, "tsmom", f0, f1), fam)["params"]                # the same rule as the TRAIN selection, on the data up to the fit end
    assert out["stitched_return"] == pytest.approx(float(np.prod([1 + r["return"] for r in out["segments"]]) - 1))
    for row in out["segments"]:
        o0, o1 = prep.span(date.fromisoformat(row["oos_start"]), date.fromisoformat(row["oos_end"]))
        again = B.run(prep, "tsmom", row["chosen"], o0, o1)                                      # a fresh run of the chosen configuration over the window, from a flat start
        assert row["return"] == pytest.approx(again.metrics["total_return"]) and row["trades"] == again.metrics["trades"] and row["days"] == o1 - o0 + 1
    first, last = prep.span(date(2021, 1, 1), date(2021, 3, 31))[0], prep.span(date(2022, 1, 1), date(2022, 1, 4))[1]
    hold = B.run(prep, "buy_hold", {}, first, last)
    assert out["hold_return"] == pytest.approx(hold.metrics["total_return"]) and out["hold_sharpe"] == pytest.approx(hold.metrics["sharpe"])
    assert sum(r["days"] for r in out["segments"]) == last - first + 1 and out["positive_windows"] == sum(1 for r in out["segments"] if r["return"] > 0)
    assert out["passes"] == V.wf_passes(out["stitched_sharpe"], out["hold_sharpe"], out["positive_windows"], out["windows"])


def test_the_first_walk_forward_fit_is_the_train_selection_when_it_covers_the_same_days():
    prep = B.Prepared(history(2875, seed=3))
    train = B.run_all(prep, "sma_filter", *prep.period("TRAIN"))
    out = V.walk_forward(prep, "sma_filter", first_fit_end=date(2022, 12, 31), step_months=6)
    assert out["segments"][0]["chosen"] == V.select(train, S.FAMILIES["sma_filter"])["params"] and out["segments"][0]["oos_start"] == "2023-01-01"


def test_a_walk_forward_with_no_window_is_empty_and_does_not_pass():
    prep = B.Prepared(history(800, seed=2))
    out = V.walk_forward(prep, "tsmom", fit_start=date(2020, 1, 1), first_fit_end=date(2021, 3, 9))                # the data end on 2021-03-10 ... one day of window
    assert out["windows"] == 1 and out["segments"][0]["days"] >= 1
    prep2 = B.Prepared(history(800, seed=2)[:799])
    empty = V.walk_forward(prep2, "tsmom", fit_start=date(2020, 1, 1), first_fit_end=date(2021, 3, 9))
    assert empty["windows"] == 0 and empty["passes"] is False and empty["stitched_sharpe"] is None


# ---- sensitivity ----

def test_higher_costs_lower_the_sharpe_ratio_at_each_of_the_four_settings():
    prep = B.Prepared(history(2875, seed=8, vol=0.035))
    ranges = [prep.period("TRAIN"), prep.period("VALIDATION")]
    tab = V.cost_table(prep, "sma_cross", {"fast": 10, "slow": 50}, ranges)
    assert [(t["fee"], t["slippage"]) for t in tab] == list(C.COST_SENSITIVITY)
    sh = [t["sharpe"] for t in tab]
    assert sh[0] > sh[1] > sh[2] > sh[3] and tab[3]["fees_paid"] > tab[0]["fees_paid"] and all(len(t["returns"]) == 2 for t in tab)
    both = [B.run(prep, "sma_cross", {"fast": 10, "slow": 50}, a, b, fee=0.002, slip=0.001) for a, b in ranges]
    assert tab[2]["sharpe"] == pytest.approx(M.sharpe(np.concatenate([r.returns for r in both])), rel=1e-12) and tab[2]["returns"] == pytest.approx([r.metrics["total_return"] for r in both])


# ---- gates ----

def adm(**kw):
    n = {"activity": 10, "weight_mode": False, "train_ir": 0.1, "validation_ir": 0.1, "validation_null_p": 0.05, "stability": {"passes": True}, "doubled_cost_sharpe": 0.1}
    n.update(kw)
    return V.admission(n)


def test_a_candidate_that_just_clears_every_admission_gate_is_admitted():
    res = adm()                                                                         # 10 trades, a validation timing p-value of exactly 0.05, every other gate comfortably met
    assert res["outcome"] == "admitted" and res["failed"] == [] and all(g["passed"] for g in res["gates"].values()) and sorted(res["gates"]) == ["A1", "A2", "A3", "A4", "A5"]


def test_each_admission_gate_fails_just_past_its_boundary_and_says_which():
    cases = [("A2", dict(train_ir=0.0)), ("A2", dict(train_ir=-0.1)), ("A2", dict(train_ir=None)), ("A2", dict(validation_ir=0.0)), ("A2", dict(validation_ir=None)),
             ("A3", dict(validation_null_p=0.0501)), ("A3", dict(validation_null_p=0.1)), ("A3", dict(validation_null_p=1.0)), ("A3", dict(validation_null_p=None)), ("A4", dict(stability={"passes": False})),
             ("A5", dict(doubled_cost_sharpe=0.0)), ("A5", dict(doubled_cost_sharpe=None))]
    for gate, change in cases:
        res = adm(**change)
        assert res["failed"] == [gate] and res["outcome"] == "rejected", (gate, change)
    assert adm(validation_null_p=0.0)["outcome"] == "admitted" and adm(train_ir=1e-9)["outcome"] == "admitted"


def test_the_market_drift_alone_cannot_admit_a_candidate_because_no_gate_reads_raw_returns():
    # a candidate with a high raw Sharpe but no timing skill (information ratios at or below zero, a timing p-value near one) fails whatever its raw numbers say
    res = adm(train_ir=-0.05, validation_ir=0.02, validation_null_p=0.7, doubled_cost_sharpe=1.5)
    assert res["outcome"] == "rejected" and res["failed"] == ["A2", "A3"]


def test_too_few_trades_is_too_thin_to_judge_not_rejected_whatever_else_fails():
    assert adm(activity=9)["outcome"] == "too_thin" and adm(activity=9)["failed"] == ["A1"]
    res = adm(activity=0, train_ir=-1.0, validation_null_p=0.9)
    assert res["outcome"] == "too_thin" and "A1" in res["failed"] and "A2" in res["failed"] and "A3" in res["failed"]
    assert adm(activity=10)["gates"]["A1"]["passed"] is True


def test_weight_mode_counts_position_changes_and_says_so():
    g = adm(weight_mode=True, activity=9)["gates"]["A1"]
    assert "position changes" in g["need"] and g["passed"] is False
    assert "trades" in adm()["gates"]["A1"]["need"]


def promo(**kw):
    n = {"trades": 30, "profit_without_best": 1.0, "test_sharpe": 1.1, "hold_test_sharpe": 1.0, "test_drawdown": 0.2, "matched_test_drawdown": 0.4, "dsr_excess_all": 0.95, "null_p": 0.05,
         "wf_passes": True, "forward": {"days": 90, "trades": 5, "trips": 0, "return": 0.0, "matched_return": 0.05}}
    f = kw.pop("forward", None)
    n.update(kw)
    if f:
        n["forward"] = {**n["forward"], **f}
    return V.promotion_gates(n)


def test_a_candidate_that_just_clears_every_promotion_gate_is_promoted():
    res = promo()
    assert res["outcome"] == "promoted" and res["failed"] == []


def test_each_promotion_gate_fails_just_past_its_boundary():
    cases = [("P1", dict(trades=29)), ("P1", dict(profit_without_best=0.0)), ("P1", dict(profit_without_best=None)), ("P2", dict(test_sharpe=1.099)), ("P2", dict(test_drawdown=0.31, matched_test_drawdown=0.4)),
             ("P2", dict(test_sharpe=None)), ("P3", dict(dsr_excess_all=0.9499)), ("P3", dict(null_p=0.0501)), ("P3", dict(null_p=None)), ("P3", dict(dsr_excess_all=None)), ("P4", dict(wf_passes=False)),
             ("P5", dict(forward=dict(trades=4))), ("P5", dict(forward=dict(trips=1))), ("P5", dict(forward={"return": -0.0001}))]
    for gate, change in cases:
        res = promo(**change)
        assert gate in res["failed"] and res["outcome"] == "not_promoted", (gate, change)
    assert promo(test_drawdown=0.3, matched_test_drawdown=0.4)["outcome"] == "promoted"                     # 75% of 0.4 = 0.30


def test_the_forward_record_decides_between_too_early_waiting_and_a_verdict():
    assert promo(forward=dict(days=59, trades=0))["outcome"] == "too_early" and promo(forward=dict(days=0, trades=0, trips=2))["outcome"] == "too_early"
    assert promo(forward=dict(days=60))["outcome"] == "waiting" and promo(forward=dict(days=89))["outcome"] == "waiting" and promo(forward=dict(days=90))["outcome"] == "promoted"
    assert promo(forward=dict(days=75, trips=1))["outcome"] == "not_promoted"                                # a trip is a failure however early
    assert promo(forward=dict(days=75), dsr_excess_all=0.5)["outcome"] == "not_promoted"                            # another gate failed: no waiting for the days


# ---- one family end to end ----

def test_one_family_end_to_end_gives_a_complete_json_record_consistent_with_its_own_numbers():
    prep = B.Prepared(history(2875, seed=17, vol=0.035))
    tr, va = prep.period("TRAIN"), prep.period("VALIDATION")
    runs = {"TRAIN": B.run_all(prep, "sma_cross", *tr), "VALIDATION": B.run_all(prep, "sma_cross", *va)}
    ev = V.evaluate_family(prep, "sma_cross", runs, trial_var=1e-4, n_trials=100, trial_var_excess=2e-4, n_shifts=200)
    json.dumps(ev)
    assert ev["family"] == "sma_cross" and ev["protocol"] == C.PROTOCOL_VERSION == "1.3" and ev["configurations"] == 15 and len(ev["table"]) == 15 and ev["outcome"] in ("admitted", "rejected", "too_thin")
    assert ev["spec_hash"] == S.spec_hash("sma_cross", ev["chosen"]) and ev["outcome"] == ev["admission"]["outcome"]
    best = max(ev["table"], key=lambda r: r["score"])
    assert best["params"] == ev["chosen"] or best["score"] == pytest.approx(next(r["score"] for r in ev["table"] if r["params"] == ev["chosen"]))
    assert ev["train"]["trades"] + ev["validation"]["trades"] == ev["admission"]["gates"]["A1"]["value"] and ev["full_exposure"]["TRAIN"]["exposure"] > ev["train"]["exposure"]
    assert len(ev["costs"]) == 4 and ev["walk_forward"]["windows"] == 10 and ev["pooled"]["T"] == 1096 + 731
    assert ev["random_timing"]["shifts"] == 200 and 0.0 <= ev["random_timing"]["p"] <= 1.0
    ck = B.param_key(ev["chosen"])
    ct, cv = runs["TRAIN"][ck], runs["VALIDATION"][ck]
    assert ev["excess"]["train"] == pytest.approx(M.sharpe(ct.returns - ct.matched_returns), rel=1e-12) and ev["excess"]["validation"] == pytest.approx(M.sharpe(cv.returns - cv.matched_returns), rel=1e-12)
    assert ev["validation_timing"]["p"] == V.random_timing(cv.exposure, prep.btc_returns[cv.i0:cv.i1 + 1], n_shifts=200)["p"]                    # the test runs on the VALIDATION days only
    g = ev["admission"]["gates"]
    assert g["A2"]["value"] == {"train_ir": ev["excess"]["train"], "validation_ir": ev["excess"]["validation"]} and g["A3"]["value"] == ev["validation_timing"]["p"] and g["A5"]["value"] == ev["costs"][2]["sharpe"]
    assert ev["validation_timing"]["shifts"] == 200 and ev["excess"]["pooled"]["T"] == 1827 and ev["excess"]["deflated"]["n_trials"] == 100 and ev["deflated_sharpe"]["dsr"] is not None
    assert ev["excess"]["deflated"]["sr0"] == pytest.approx(math.sqrt(2e-4) * V.expected_max_normal(100), rel=1e-12) and ev["deflated_sharpe"]["sr0"] == pytest.approx(math.sqrt(1e-4) * V.expected_max_normal(100), rel=1e-12)


def test_a_weight_family_is_counted_by_position_changes_and_has_no_full_exposure_variant():
    prep = B.Prepared(history(2875, seed=17, vol=0.035))
    tr, va = prep.period("TRAIN"), prep.period("VALIDATION")
    runs = {"TRAIN": B.run_all(prep, "sma_filter", *tr), "VALIDATION": B.run_all(prep, "sma_filter", *va)}
    ev = V.evaluate_family(prep, "sma_filter", runs, trial_var=1e-4, n_trials=100, walk=False, n_shifts=50)
    assert ev["full_exposure"] is None and ev["walk_forward"] is None
    assert ev["admission"]["gates"]["A1"]["value"] == ev["train"]["fills"] + ev["validation"]["fills"] and "position changes" in ev["admission"]["gates"]["A1"]["need"]


def test_the_whole_procedure_always_counts_all_the_trials_whichever_families_are_asked_for():
    prep = B.Prepared(history(2875, seed=23, vol=0.035))
    out = V.evaluate_all(prep, families=["donchian", "sma_filter"], walk=False, n_shifts=30)
    assert out["n_trials"] == 101 == S.n_configurations() and set(out["families"]) == {"donchian", "sma_filter"} and out["protocol"] == C.PROTOCOL_VERSION
    tr, va = prep.period("TRAIN"), prep.period("VALIDATION")
    sharpes = []
    for f in S.RESEARCH:
        a, b = B.run_all(prep, f.id, *tr), B.run_all(prep, f.id, *va)
        for k in a:
            st = V.return_stats(np.concatenate([a[k].returns, b[k].returns]))["sr_daily"]
            sharpes.append(0.0 if st is None else st)
    assert out["trial_variance"] == pytest.approx(float(np.var(sharpes, ddof=1)), rel=1e-12) and len(sharpes) == 101
    for fid, ev in out["families"].items():
        assert ev["deflated_sharpe"]["n_trials"] == 101 and ev["deflated_sharpe"]["sr0"] == pytest.approx(math.sqrt(out["trial_variance"]) * V.expected_max_normal(101), rel=1e-12)
    json.dumps(out)
