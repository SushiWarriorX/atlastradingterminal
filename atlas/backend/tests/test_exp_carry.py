"""Experiment 4 (funding carry with a regime switch): hand-worked numbers, no look-ahead, costs, the sealed split, the data check. No network."""
from datetime import date, datetime, timedelta, timezone

import pytest

from atlas_api.btclab import exp_carry as X

D0 = date(2024, 1, 1)


def days(n, d0=D0):
    return [d0 + timedelta(days=i) for i in range(n)]


def test_hourly_records_drop_the_early_eight_hour_spacing():
    t0 = 1_684_022_400
    recs = [(t0, 1.0), (t0 + 8 * 3600, 1.0), (t0 + 16 * 3600, 1.0), (t0 + 17 * 3600, 2.0), (t0 + 18 * 3600, 3.0)]
    assert [r[1] for r in X.hourly_records(recs)] == [1.0, 2.0, 3.0]            # starts at the record BEFORE the first 1-hour gap
    assert X.hourly_records([(0, 1.0), (28800, 1.0)]) == []


def test_daily_funding_sums_complete_days_only():
    base = int(datetime(2024, 1, 1, 0, tzinfo=timezone.utc).timestamp())
    recs = [(base + h * 3600, 0.0001) for h in range(24 * 3)] + [(base + 72 * 3600 + h * 3600, 0.0002) for h in range(5)]          # 3 full days then 5 hours of day 4
    f = X.daily_funding(recs)
    assert sorted(f) == [D0, D0 + timedelta(1), D0 + timedelta(2)]                        # the partial last day is dropped
    assert f[D0] == pytest.approx(0.0024)                                                   # 24 x 0.0001


def test_fill_bills_carries_forward():
    b = X.fill_bills([(date(2024, 1, 1), 5.0), (date(2024, 1, 4), 4.0)], days(5))
    assert [b[d] for d in days(5)] == [5.0, 5.0, 5.0, 4.0, 4.0]
    with pytest.raises(ValueError):
        X.fill_bills([(date(2024, 1, 3), 5.0)], days(2))


def test_decision_uses_only_funding_up_to_the_previous_day_and_the_hurdle_by_hand():
    ds = days(20)
    fund = {d: 0.0 for d in ds}
    bills = {d: 4.0 for d in ds}
    # 14-day window days[0..13] each 0.0006: F14 = 0.0006*365 = 0.219 -> 0.5*F14 = 0.1095 >= 0.04 + 0.01 -> ON on day index 14
    for d in ds[:14]:
        fund[d] = 0.0006
    s = X.decisions(ds, fund, bills)
    assert s[ds[14]] is True and sorted(s)[0] == ds[14]
    # a huge value on day 14 itself must NOT affect day 14's decision (no look-ahead)
    fund2 = dict(fund); fund2[ds[14]] = 9.9
    assert X.decisions(ds, fund2, bills)[ds[14]] is True
    fund3 = {d: 0.0 for d in ds}; fund3[ds[14]] = 9.9
    assert X.decisions(ds, fund3, bills)[ds[14]] is False
    # exactly at the hurdle counts as ON: 0.5*F14 == 0.05 -> F14 = 0.10 -> per-day sum 0.10/365*14... use equal days
    each = (0.05 / 0.5) / 365                                                                 # per-day funding giving F14 = 0.10
    fund4 = {d: each for d in ds}
    assert X.decisions(ds, fund4, bills)[ds[14]] is True


def test_simulate_by_hand_with_switching_costs():
    ds = days(4)
    fund = {ds[0]: 0.001, ds[1]: 0.001, ds[2]: -0.0005, ds[3]: 0.001}
    bills = {d: 3.65 for d in ds}                                                             # 3.65% a year = 0.0001 a day
    state = {ds[0]: True, ds[1]: True, ds[2]: False, ds[3]: True}
    r = X.simulate(ds, fund, bills, state, start_on=False)
    assert r[0] == pytest.approx(0.0005 - 0.0030)                                            # ON: 0.5 x 0.001, minus the switch cost
    assert r[1] == pytest.approx(0.0005)                                                     # still ON, no cost
    assert r[2] == pytest.approx(0.0001 - 0.0030)                                            # OFF: bill return, minus the switch cost
    assert r[3] == pytest.approx(0.0005 - 0.0030)
    # a negative funding day while ON hurts: 0.5 x -0.0005
    assert X.simulate(ds[:1], {ds[0]: -0.0005}, {ds[0]: 3.65}, {ds[0]: True}, start_on=True)[0] == pytest.approx(-0.00025)


def test_always_on_and_bills_and_metrics_by_hand():
    ds = days(2)
    assert X.always_on(ds, {ds[0]: 0.002, ds[1]: 0.002}) == [pytest.approx(0.001 - 0.003), pytest.approx(0.001)]
    assert X.always_bills(ds, {ds[0]: 3.65, ds[1]: 3.65}) == [pytest.approx(0.0001)] * 2
    assert X.ann_return([0.001] * 365) == pytest.approx(1.001 ** 365 - 1)
    assert X.worst_drop([0.1, -0.1, 0.05]) == pytest.approx(-0.1)
    assert X.worst_drop([0.01, 0.01]) == 0.0
    assert X.excess_sharpe([0.001, 0.001], [0.001, 0.001]) is None


def test_gap_check():
    base = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    recs = [(base + h * 3600, 0.0) for h in range(10)] + [(base + 20 * 3600, 0.0)]
    assert X.max_gap_hours(recs, D0, D0) == pytest.approx(11.0)             # hour 9 to hour 20
    assert X.max_gap_hours(recs[:10], D0, D0) == pytest.approx(1.0)


def _series(n, rate):
    base = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    return [(base + h * 3600, rate(h // 24)) for h in range(24 * n)] + [(base + 24 * n * 3600 + h * 3600, 0.0) for h in range(3)]       # 3 extra hours so the last full day is complete


def test_run_end_to_end_always_high_funding_passes_and_split_is_70_30():
    n = 120
    recs = _series(n, lambda d: 0.0004)                                                       # F = 0.0004*24*365 = 3.5 a year? per hour 0.0004 -> per day 0.0096
    dtb3 = [(date(2023, 12, 1), 4.0)]
    close = {D0 + timedelta(i): 100.0 + i for i in range(-1, n + 5)}
    res = X.run(recs, dtb3, close)
    assert res["valid"] and res["panel_days"] == n - X.WINDOW                               # the 3-hour partial last day is dropped; 14-day warm-up
    assert res["sealed_days"] == res["panel_days"] - int(res["panel_days"] * 0.7)
    assert res["strategy"]["worst_drop"] > -0.03 and res["passed"] is True
    assert res["btc_hold"]["ann_return"] > 0


def test_run_low_funding_stays_in_bills_and_fails_condition_a():
    recs = _series(120, lambda d: 0.0)
    res = X.run(recs, [(date(2023, 12, 1), 4.0)], {D0 + timedelta(i): 100.0 for i in range(-1, 130)})
    assert res["valid"] and res["days_on_in_sealed"] == 0 and res["switches_in_sealed"] == 0
    assert res["strategy"]["ann_return"] == pytest.approx(res["always_bills"]["ann_return"])
    assert res["conditions"]["a_beats_bills_by_1pp"] is False and res["passed"] is False


def test_run_is_invalid_with_a_gap_in_the_sealed_period_or_missing_days():
    recs = _series(120, lambda d: 0.0004)
    cut = [r for r in recs if not (60 * 24 * 3600 + recs[0][0] + 5 * 3600 < r[0] < recs[0][0] + 100 * 24 * 3600 + 3600 * 24 * 0 + 1)]
    res = X.run(recs, [(date(2023, 12, 1), 4.0)], {D0 + timedelta(i): 100.0 for i in range(-1, 130)})
    assert res["valid"]
    holed = [r for r in recs if not (recs[0][0] + 90 * 86400 <= r[0] < recs[0][0] + 91 * 86400)]                 # a whole day missing
    assert X.run(holed, [(date(2023, 12, 1), 4.0)], {D0 + timedelta(i): 100.0 for i in range(-1, 130)})["valid"] is False
    gappy = [r for r in recs if not (recs[0][0] + 100 * 86400 + 3600 < r[0] < recs[0][0] + 100 * 86400 + 6 * 3600)]            # 5-hour gap inside the sealed tail
    out = X.run(gappy, [(date(2023, 12, 1), 4.0)], {D0 + timedelta(i): 100.0 for i in range(-1, 130)})
    assert out["valid"] is False and "gap" in out["reason"]
