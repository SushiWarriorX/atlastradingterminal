"""Experiment 5 (Bitcoin held only while Fed net liquidity is expanding): the liquidity formula and carry-forward by hand, the signal, the Friday timing and no look-ahead, the sealed segment and the entry cost, the null's invariants,
an end-to-end run with a planted relationship and without one, and the INVALID paths. No network."""
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from atlas_api.btclab import exp_liquidity as X

W0 = date(2024, 1, 3)                                        # a Wednesday


def weds(n, w0=W0):
    return [w0 + timedelta(days=7 * i) for i in range(n)]


def test_net_liquidity_by_hand_with_a_carried_forward_reverse_repo():
    ws = weds(2)
    walcl = {ws[0]: 7_000_000.0, ws[1]: 7_100_000.0}                     # millions
    wdtgal = {ws[0]: 700_000.0, ws[1]: 800_000.0}                        # millions
    rrp = {ws[0]: 500.0, ws[1] - timedelta(days=1): 400.0}               # billions; none ON the second Wednesday, but one the day before
    L, st = X.net_liquidity(walcl, wdtgal, rrp)
    assert L[ws[0]] == pytest.approx(7000 - 700 - 500) and L[ws[1]] == pytest.approx(7100 - 800 - 400)
    assert st == {"wednesdays": 2, "rrp_carried": 1, "dropped_no_rrp": 0}
    L2, st2 = X.net_liquidity(walcl, wdtgal, rrp, start=ws[1])           # weeks before `start` are not used and not counted
    assert list(L2) == [ws[1]] and st2["wednesdays"] == 1
    assert X.net_liquidity({ws[1]: 1.0}, {ws[1]: 1.0}, {ws[1] - timedelta(days=5): 1.0})[1]["dropped_no_rrp"] == 1       # too far back: left out, counted
    with pytest.raises(ValueError, match="Wednesday"):
        X.net_liquidity({date(2024, 1, 4): 1.0}, {date(2024, 1, 4): 1.0}, {date(2024, 1, 1): 1.0})


def test_signal_is_the_91_day_change_and_zero_is_off():
    ws = weds(15)
    L = {w: 5000.0 for w in ws}
    L[ws[13]] = 5001.0                                         # up against 13 weeks earlier (ws[0] = 5000)
    L[ws[14]] = 4000.0                                         # down
    s = X.signal(L)
    assert sorted(s)[0] == ws[13] and s[ws[13]] is True and s[ws[14]] is False
    L2 = {w: 5000.0 for w in ws}
    assert X.signal(L2)[ws[13]] is False                       # exactly zero change = OFF


def test_validity_checks():
    ws = weds(30)
    ok = {w: 5000.0 for w in ws}
    st = {"wednesdays": 30, "rrp_carried": 1, "dropped_no_rrp": 0}
    assert X.validity(ok, st) is None
    assert "gap" in X.validity({w: 5000.0 for w in ws if w != ws[10]}, st)
    assert "outside" in X.validity({**ok, ws[3]: 12000.0}, st)
    assert "outside" in X.validity({**ok, ws[3]: 2000.0}, st)
    assert "carried" in X.validity(ok, {"wednesdays": 30, "rrp_carried": 5, "dropped_no_rrp": 0})
    assert "no reverse repo" in X.validity(ok, {"wednesdays": 31, "rrp_carried": 1, "dropped_no_rrp": 1})
    assert "no net liquidity" in X.validity({}, {"wednesdays": 0, "rrp_carried": 0, "dropped_no_rrp": 0})


def test_weights_change_only_on_fridays_use_the_wednesday_two_days_earlier_and_never_look_ahead():
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(21)]                  # Mon Jan 1 .. Sun Jan 21
    sig = {date(2024, 1, 3): True, date(2024, 1, 10): False, date(2024, 1, 17): True}
    w, st = X.weight_sequence(days, sig)
    fri = {d: i for i, d in enumerate(days) if d.weekday() == 4}
    assert fri == {date(2024, 1, 5): 4, date(2024, 1, 12): 11, date(2024, 1, 19): 18}
    # w[i] is the weight DECIDED at the close of bar i: flat until Friday Jan 5 (ON), Friday Jan 12 (OFF), Friday Jan 19 (ON)
    assert [float(x) for x in w] == [0.0] * 4 + [1.0] * 7 + [0.0] * 7 + [1.0] * 3
    assert st == {"fridays": 3, "from_signal": 3, "kept_previous": 0}
    # no look-ahead: changing a LATER Wednesday's signal cannot change any earlier weight
    sig2 = dict(sig)
    sig2[date(2024, 1, 17)] = False
    w2, _ = X.weight_sequence(days, sig2)
    assert list(w2[:18]) == list(w[:18]) and list(w2[18:]) == [0.0] * 3
    # a missing Wednesday keeps the previous state and is counted; with no signal at all the weight stays 0
    w3, st3 = X.weight_sequence(days, {date(2024, 1, 3): True})
    assert list(w3[4:]) == [1.0] * 17 and st3["kept_previous"] == 2
    w4, st4 = X.weight_sequence(days, {})
    assert list(w4) == [0.0] * 21 and st4 == {"fridays": 3, "from_signal": 0, "kept_previous": 3}


def test_the_sealed_sequence_is_what_the_simulator_trades_and_every_comparator_starts_flat():
    n, k = 100, 70
    o = c = np.full(n, 100.0)                                               # flat price: only costs move the curve
    s = X._sim(o, c, np.ones(n), k)
    assert s["net_return_pct"] == pytest.approx(-0.1) and s["mean_weight"] == 1.0                   # entry from flat at the first sealed bar: 10 bps on the whole position, once
    w = np.ones(n)
    w2 = w.copy()
    w2[n - 1] = 0.0                                                          # the weight decided on the last bar is never traded
    w2[:k - 1] = 0.0                                                         # nor is anything before the weight decided at the close of bar k-1
    assert X._sim(o, c, w2, k) == s
    w3 = w.copy()
    w3[k - 1] = 0.0                                                          # but that one is traded, from the open of bar k: one bar of the 30 is spent flat
    assert X._sim(o, c, w3, k)["mean_weight"] == pytest.approx((n - k - 1) / (n - k)) and (n - k) == 30


def test_switches_count_changes_inside_the_traded_sequence_only():
    #            0    1    2    3    4    5    6    7           n = 8, k = 3: traded sequence = w[2:7]
    w = np.array([0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0])
    assert X.switches(w, 3) == 2                                              # 1->0 and 0->1; not the entry 0->1 before it, not the untraded last weight
    assert X.switches(np.ones(8), 3) == 0


def test_the_null_shift_keeps_exposure_and_every_switch_on_its_weekday_and_moves_nothing_else():
    k, whole_weeks, extra = 11, 40, 3
    L = 7 * whole_weeks + extra                                              # traded sequence length n - k
    n = k + L
    rng = np.random.default_rng(3)
    states = rng.integers(0, 2, size=80).astype(float)
    pos = np.arange(n) - (k - 1)                                             # position inside the traded sequence
    w = states[(pos - 3) // 7 % 80]                                          # weekly states that change only at positions = 3 (mod 7), like Fridays
    base = X.switches(w, k)
    assert base > 8                                                          # the fixture really switches
    for m in (8, 13, 31):
        sh = X.shifted_weights(w, k, m)
        assert list(sh[:k - 1]) == list(w[:k - 1]) and sh[n - 1] == w[n - 1]                      # nothing outside the traded sequence moves
        assert list(sh[k - 1 + 7 * whole_weeks:n - 1]) == list(w[k - 1 + 7 * whole_weeks:n - 1])    # the last 3 days stay
        assert sh[k - 1:n - 1].sum() == w[k - 1:n - 1].sum()                                         # exposure exactly the same
        rel = np.flatnonzero(np.abs(np.diff(sh[k - 1:n - 1])) > 0) + 1                               # position of each bar where the weight changed
        seams = {7 * m, 7 * whole_weeks}
        assert all(int(r) % 7 == 3 or int(r) in seams for r in rel)                                  # every switch is on its weekday, except at the two seams
        assert abs(X.switches(sh, k) - base) <= 2
        assert not np.array_equal(sh, w)


def _synthetic(n_days=1500, seed=1, aligned=True, history_weeks=30):
    """Daily bars from 2020-01-01 and weekly FRED-like series whose 13-week change flips often. When `aligned`, price drifts +0.4%/day on days the strategy holds and -0.4% otherwise."""
    d0 = date(2020, 1, 1)                                                        # a Wednesday
    days = [d0 + timedelta(days=i) for i in range(n_days)]
    ws = [d0 - timedelta(days=7 * history_weeks) + timedelta(days=7 * i) for i in range(history_weeks + n_days // 7 + 8)]
    Lw = {w: 5000.0 + 100 * np.sin(2 * np.pi * i / 9.0) + 60 * np.sin(2 * np.pi * i / 5.3) for i, w in enumerate(ws)}
    walcl = {w: (v + 800.0 + 300.0) * 1000.0 for w, v in Lw.items()}              # + TGA 800 + RRP 300 (billions) -> millions
    wdtgal = {w: 800_000.0 for w in ws}
    rrp = {w: 300.0 for w in ws}
    rrp[ws[0] - timedelta(days=100)] = 300.0                                       # the RRP series starts before the first Wednesday
    used, _ = X.net_liquidity(walcl, wdtgal, rrp, start=days[0] - timedelta(days=X.USED_FROM_DAYS_BEFORE_FIRST_BAR))
    wt, _ = X.weight_sequence(days, X.signal(used))
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 0.003, n_days)
    ret = (np.where(np.roll(wt, 1) > 0, 0.004, -0.004) if aligned else 0.0) + noise
    c = 100.0 * np.cumprod(1 + ret)
    o = np.concatenate([[100.0], c[:-1]])
    rows = [(int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()), o[i], max(o[i], c[i]), min(o[i], c[i]), c[i], 1.0) for i, d in enumerate(days)]
    return rows, walcl, wdtgal, rrp


def test_end_to_end_a_signal_that_really_leads_price_passes_every_condition():
    rows, walcl, wdtgal, rrp = _synthetic(aligned=True)
    res = X.run(rows, walcl, wdtgal, rrp)
    assert res["valid"] and res["sealed_from_bar"] == int(len(rows) * 0.7) and res["sealed_bars"] == len(rows) - res["sealed_from_bar"]
    assert res["sealed"]["switches"] >= 10 and res["null"]["runs"] == 1000
    assert res["conditions"] == {key: True for key in res["conditions"]} and res["passed"] is True
    assert res["sealed"]["strategy"]["sharpe"] > res["null"]["sharpe_95th"] > res["null"]["sharpe_median"]
    assert res["null"]["switches_max"] - res["null"]["switches_min"] <= 4              # the shifted copies keep the switch count to within the seams
    assert res["liquidity_used_from"] >= (date(2020, 1, 1) - timedelta(days=X.USED_FROM_DAYS_BEFORE_FIRST_BAR)).isoformat()


def test_end_to_end_a_signal_unrelated_to_price_does_not_pass():
    rows, walcl, wdtgal, rrp = _synthetic(aligned=False, seed=7)
    res = X.run(rows, walcl, wdtgal, rrp)
    assert res["valid"] and res["passed"] is False
    assert res["conditions"]["b_sharpe_above_95th_pct_of_shifted_schedules"] is False


def test_end_to_end_is_deterministic():
    rows, walcl, wdtgal, rrp = _synthetic(aligned=True)
    assert X.run(rows, walcl, wdtgal, rrp) == X.run(rows, walcl, wdtgal, rrp)


def test_invalid_data_is_not_a_fail_and_old_unused_weeks_do_not_matter():
    rows, walcl, wdtgal, rrp = _synthetic(aligned=True)
    first_bar = datetime.fromtimestamp(rows[0][0], timezone.utc).date()
    old = sorted(w for w in walcl if w < first_bar - timedelta(days=X.USED_FROM_DAYS_BEFORE_FIRST_BAR))
    assert old, "the fixture must have weeks older than the used window"
    holed_old = dict(walcl)
    del holed_old[old[2]]                                                       # a hole before the window: never reaches a signal
    assert X.run(rows, holed_old, wdtgal, rrp)["valid"] is True
    inside = sorted(w for w in walcl if first_bar - timedelta(days=60) <= w <= first_bar)
    holed_in = dict(walcl)
    del holed_in[inside[2]]                                                     # a hole inside the window
    bad = X.run(rows, holed_in, wdtgal, rrp)
    assert bad["valid"] is False and "gap" in bad["reason"] and "passed" not in bad
    odd = dict(walcl)
    odd[date(2020, 2, 5) + timedelta(days=1)] = 1.0                             # a Thursday in a weekly series
    wd2 = dict(wdtgal)
    wd2[date(2020, 2, 6)] = 1.0
    assert X.run(rows, odd, wd2, rrp)["valid"] is False
    skipped = rows[:100] + rows[101:]                                           # a missing daily bar
    assert "gap" in X.run(skipped, walcl, wdtgal, rrp)["reason"]
    short = X.run(rows[:60], walcl, wdtgal, rrp)                                # a sealed period too short for the shifted copies
    assert short["valid"] is False and "too short" in short["reason"]
