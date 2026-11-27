"""US industrial production (Federal Reserve G.17 via FRED): parsed from real responses (fetched 2026-11-17 11:40 UTC: 177 monthly values per series from 2012-01, newest 2026-09; the full history of 1,293 months was read first to set every limit). Hand-worked level, changes, groups, capacity utilization, ten-year growth range and check figures (recomputed in plain Python from the saved responses, outside the module), the edges of every check one at a time on synthetic series that satisfy every other check by construction, the real shocks of 2020 and 2021, and the provider: caching, failure, demo and route."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import industrialproduction as I
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_industrial.json").read_text())
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)
GROUP_NAMES = {"IPMANSICS": "manufacturing", "IPMINE": "mining", "IPUTIL": "electric and gas utilities"}


def _data():
    return {sid: I.parse(F[sid], sid) for sid in I.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _idx(d):
    """Months from LAST: 0 for the newest month, -1 for the one before."""
    return (d.year * 12 + d.month) - (LAST.year * 12 + LAST.month)


def _synthetic(total=None, man=None, mine=None, util=None, tcu=None, n_months=40):
    """A clean synthetic set: `n_months` months ending 2026-09 with all four indexes at 100 and utilization at 76 unless a function of the month is given for that series. Flat series satisfy every check by construction (no move, the total between its groups, a constant implied capacity), so a test can break one thing."""
    months = [I._months_back(LAST, i) for i in range(n_months - 1, -1, -1)]
    fs = {"INDPRO": total, "IPMANSICS": man, "IPMINE": mine, "IPUTIL": util, "TCU": tcu}
    base = {"INDPRO": 100.0, "IPMANSICS": 100.0, "IPMINE": 100.0, "IPUTIL": 100.0, "TCU": 76.0}
    return {sid: {d: float(fs[sid](d)) if fs[sid] else base[sid] for d in months} for sid in I.SERIES}


def _moved(at=0, total=1.0, man=1.0, mine=1.0, util=1.0, tcu=1.0, tcu_base=76.0, stay=False, n_months=40):
    """Flat series with the given factors applied `at` months from LAST (0 = the newest month), only there or, with `stay`, from there on."""
    def f(base, k):
        return lambda d: base * (k if (_idx(d) >= at if stay else _idx(d) == at) else 1.0)
    return _synthetic(f(100.0, total), f(100.0, man), f(100.0, mine), f(100.0, util), f(tcu_base, tcu), n_months)


def _path(steps, tcu_base):
    """All four indexes (and utilization, from `tcu_base`) follow the same factors by month, 1.0 where none is given: a clean way to move the whole picture and reach one year-on-year edge."""
    def f(base):
        return lambda d: base * steps.get(_idx(d), 1.0)
    return _synthetic(f(100.0), f(100.0), f(100.0), f(100.0), f(tcu_base))


def test_latest_level_changes_groups_capacity_growth_and_checks_by_hand():
    s = I.summarize(_data(), TODAY)
    assert (s["date"], s["month"], s["age_days"], s["freshness"]) == ("2026-09-01", "2026-09", 77, "CURRENT")
    assert s["level"] == 103.95
    assert s["change_1m_pct"] == 0.7 and s["change_3m_pct"] == 1.0 and s["change_1y_pct"] == 2.2          # against 103.2664 (Aug), 102.9610 (Jun) and 101.6680 (Sep 2025): +0.663%, +0.961%, +2.245%
    assert s["manufacturing"] == {"level": 98.44, "change_1m_pct": 0.3, "change_1y_pct": 1.1}          # 98.4387 against 98.1741 (+0.270%) and 97.3415 (+1.127%)
    assert s["mining"] == {"level": 124.52, "change_1m_pct": 0.2, "change_1y_pct": 2.8}                # 124.5239 against 124.3366 (+0.151%) and 121.1275 (+2.804%)
    assert s["utilities"] == {"level": 117.25, "change_1m_pct": 3.5, "change_1y_pct": 8.7}             # 117.2504 against 113.2842 (+3.501%) and 107.8237 (+8.743%)
    assert s["capacity"] == {"utilization_pct": 76.9, "change_1m_points": 0.4, "change_1y_points": 0.8}  # 76.8504 against 76.4184 (+0.432 points) and 76.0461 (+0.804 points)
    assert s["growth"] == {"months": 120, "slowest": {"pct": -17.3, "month": "2020-04"}, "fastest": {"pct": 16.6, "month": "2021-04"}, "share_slower_pct": 76}      # 2016-10 to 2026-09; the year to 2026-09 is +2.245%
    assert s["detail"] == {"months_checked": 24, "changes_checked": 23, "largest_miss_points": 0.0, "capacity_change_pct": {"smallest": 0.08, "largest": 0.12},
                           "newest": {"month": "2026-09", "total_change_pct": 0.66}}
    assert all(s["checks"].values()) and s["source"].startswith("Board of Governors of the Federal Reserve System") and s["url"] == "https://fred.stlouisfed.org/series/INDPRO"
    assert "not a market signal or a forecast" in s["note"] and "estimate that is revised" in s["note"] and "since May 1971" in s["note"]


def test_levels_keep_two_decimals_for_the_total_and_each_group_and_one_for_utilization():
    s = I.summarize(_synthetic(lambda d: 100.456, lambda d: 99.994, lambda d: 101.0049, lambda d: 120.1251, lambda d: 76.449), TODAY)
    assert s["level"] == 100.46 and s["manufacturing"]["level"] == 99.99 and s["mining"]["level"] == 101.0 and s["utilities"]["level"] == 120.13 and s["capacity"]["utilization_pct"] == 76.4


def test_utilization_changes_are_in_points_against_one_month_and_one_year_back():
    s = I.summarize(_synthetic(tcu=lambda d: 76.4 if _idx(d) == 0 else 76.3 if _idx(d) == -1 else 76.0), TODAY)
    assert s["capacity"] == {"utilization_pct": 76.4, "change_1m_points": 0.1, "change_1y_points": 0.4}      # not 0.4 against the month before that, and not a percent


def test_the_history_is_the_last_36_months_oldest_first():
    s = I.summarize(_data(), TODAY)
    assert len(s["history"]) == 36 and s["history"][0] == {"date": "2023-10-01", "level": 100.47} and s["history"][-1] == {"date": "2026-09-01", "level": 103.95}
    assert [h["date"] for h in s["history"]] == sorted(h["date"] for h in s["history"])


def test_a_short_history_says_not_available_for_what_it_cannot_compute():
    d = _data()
    keep = LAST - timedelta(days=300)                                                # about 10 months
    d = {sid: {k: v for k, v in s.items() if k >= keep} for sid, s in d.items()}
    s = I.summarize(d, TODAY)
    assert s["change_1y_pct"] is None and s["growth"] is None and s["change_3m_pct"] == 1.0 and s["level"] == 103.95
    assert s["manufacturing"]["change_1y_pct"] is None and s["manufacturing"]["change_1m_pct"] == 0.3
    assert s["capacity"] == {"utilization_pct": 76.9, "change_1m_points": 0.4, "change_1y_points": None}


def test_the_ten_year_growth_comparison_needs_at_least_60_months_of_yearly_growth():
    assert I.summarize(_synthetic(n_months=71), TODAY)["growth"] is None             # 71 months give 59 yearly growth figures
    g = I.summarize(_synthetic(n_months=72), TODAY)["growth"]                        # 72 give 60
    assert g == {"months": 60, "slowest": {"pct": 0.0, "month": g["slowest"]["month"]}, "fastest": {"pct": 0.0, "month": g["fastest"]["month"]}, "share_slower_pct": 0}


def test_overdue_after_90_days_from_the_first_of_the_month():
    assert I.summarize(_data(), LAST + timedelta(days=90))["freshness"] == "CURRENT"
    s = I.summarize(_data(), LAST + timedelta(days=91))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 91


def test_each_index_must_be_between_30_and_300_inclusive_and_a_slip_of_ten_is_caught():
    for pos, sid in enumerate(I.INDEXES):
        def one(v):
            fs = [None] * 4
            fs[pos] = lambda d, v=v: v
            return _synthetic(*fs)
        assert I.summarize(one(30.0), TODAY)["available"] and I.summarize(one(300.0), TODAY)["available"]
        with pytest.raises(ValueError, match="index is outside the plausible range"):
            I.summarize(one(29.99), TODAY)
        with pytest.raises(ValueError, match="index is outside the plausible range"):
            I.summarize(one(300.01), TODAY)
    d = _data()
    for sid in d:
        for k in d[sid]:
            d[sid][k] *= 10.0
    with pytest.raises(ValueError, match="plausible range"):                         # a x10 slip in every series
        I.summarize(d, TODAY)
    d = _data()
    for sid in d:
        for k in d[sid]:
            d[sid][k] /= 10.0
    with pytest.raises(ValueError, match="plausible range"):                         # a /10 slip in every series
        I.summarize(d, TODAY)


def test_capacity_utilization_must_be_between_40_and_100_percent_inclusive():
    assert I.summarize(_synthetic(tcu=lambda d: 40.0), TODAY)["capacity"]["utilization_pct"] == 40.0
    assert I.summarize(_synthetic(tcu=lambda d: 100.0), TODAY)["capacity"]["utilization_pct"] == 100.0
    with pytest.raises(ValueError, match="utilization is outside the plausible range"):
        I.summarize(_synthetic(tcu=lambda d: 39.9), TODAY)
    with pytest.raises(ValueError, match="utilization is outside the plausible range"):
        I.summarize(_synthetic(tcu=lambda d: 100.1), TODAY)


def test_the_range_checks_look_at_the_last_24_months_and_no_further_back():
    def low_until(cut):
        """Every month up to `cut` months back from 2026-09 has all four indexes at 29 (under the floor); the later ones are at 40: a step of 38% that the move and year-on-year checks allow."""
        f = lambda d: 29.0 if _idx(d) <= -cut else 40.0
        return _synthetic(f, f, f, f)
    with pytest.raises(ValueError, match="plausible range"):
        I.summarize(low_until(23), TODAY)                                            # the oldest month of the window (23 months before 2026-09) is under the floor: inside
    assert I.summarize(low_until(24), TODAY)["available"]                            # only the month before the window and older are under the floor: outside every window

    def util_until(cut):
        return _synthetic(tcu=lambda d: 30.0 if _idx(d) <= -cut else 40.0)
    with pytest.raises(ValueError, match="utilization is outside"):
        I.summarize(util_until(23), TODAY)
    assert I.summarize(util_until(24), TODAY)["available"]


def test_the_months_must_follow_each_other_in_the_last_24_and_start_on_the_1st():
    def without(pos):
        d = _synthetic()
        del d["INDPRO"][sorted(d["INDPRO"])[pos]]
        return d
    with pytest.raises(ValueError, match="skip a month"):
        I.summarize(without(-10), TODAY)
    with pytest.raises(ValueError, match="skip a month"):
        I.summarize(without(-24), TODAY)                                             # the oldest month of the window: the gap sits between it and the next one
    assert I.summarize(without(-25), TODAY)["available"]                             # the gap sits before the oldest month of the window: not looked at
    d = _synthetic()
    d["INDPRO"][date(2026, 8, 15)] = d["INDPRO"].pop(date(2026, 8, 1))
    with pytest.raises(ValueError, match="not the 1st"):
        I.summarize(d, TODAY)


def test_a_date_that_is_not_the_1st_matters_only_inside_the_window():
    d = _synthetic()
    old = I._months_back(LAST, 30)
    d["INDPRO"][date(old.year, old.month, 15)] = d["INDPRO"].pop(old)                # 30 months back: outside the 24-month window
    assert I.summarize(d, TODAY)["available"]


def test_a_one_month_move_of_the_total_under_minus_30_or_over_plus_40_percent_is_refused():
    def whole(f, tcu_base):
        """Everything (the total, the three groups and utilization) moves by the factor in the newest month, so only the size of the move is wrong."""
        return _moved(total=f, man=f, mine=f, util=f, tcu=f, tcu_base=tcu_base)
    assert I.summarize(whole(1.399, 50.0), TODAY)["change_1m_pct"] == 39.9           # +39.9%
    assert I.summarize(whole(0.701, 90.0), TODAY)["change_1m_pct"] == -29.9          # -29.9%
    with pytest.raises(ValueError, match=r"industrial production changed by 40.1% in 2026-09, outside -30% to \+40%"):
        I.summarize(whole(1.401, 50.0), TODAY)
    with pytest.raises(ValueError, match=r"industrial production changed by -30.1% in 2026-09, outside -30% to \+40%"):
        I.summarize(whole(0.699, 90.0), TODAY)


def test_the_month_move_check_looks_at_the_last_24_months_and_no_further_back():
    def step_up_at(months_back):
        return _moved(at=-months_back, total=1.5, man=1.5, mine=1.5, util=1.5, tcu=1.5, tcu_base=50.0, stay=True)
    second = I._label(I._months_back(LAST, 22))
    with pytest.raises(ValueError, match=f"changed by 50.0% in {second}"):
        I.summarize(step_up_at(22), TODAY)                                           # the step lands on the 2nd month of the window (22 months before 2026-09): the move into it is inside
    assert I.summarize(step_up_at(23), TODAY)["available"]                           # the step lands on the first month of the window: the move into it comes from before the window


def test_a_group_move_under_minus_60_or_over_plus_100_percent_is_refused_for_each_group():
    for sid, kw in (("IPMANSICS", "man"), ("IPMINE", "mine"), ("IPUTIL", "util")):
        name = GROUP_NAMES[sid]
        assert I.summarize(_moved(**{kw: 1.999}), TODAY)["available"]                # +99.9%: the total is between the groups, so only the size of the move is tested
        assert I.summarize(_moved(**{kw: 0.401}), TODAY)["available"]                # -59.9%
        assert I.summarize(_moved(**{kw: 2.0}), TODAY)["available"]                  # exactly +100%: allowed (200 against 100 is exact in floating point)
        assert I.summarize(_moved(**{kw: 0.4}), TODAY)["available"]                  # exactly -60%
        with pytest.raises(ValueError, match=rf"{name} changed by 100.1% in 2026-09, outside -60% to \+100%"):
            I.summarize(_moved(**{kw: 2.001}), TODAY)
        with pytest.raises(ValueError, match=rf"{name} changed by -60.1% in 2026-09, outside -60% to \+100%"):
            I.summarize(_moved(**{kw: 0.399}), TODAY)


def test_the_group_move_check_looks_at_the_last_24_months_and_no_further_back():
    second = I._label(I._months_back(LAST, 22))
    with pytest.raises(ValueError, match=f"mining changed by 150.0% in {second}"):
        I.summarize(_moved(at=-22, mine=2.5, stay=True), TODAY)
    assert I.summarize(_moved(at=-23, mine=2.5, stay=True), TODAY)["available"]


def test_year_on_year_change_over_plus_90_percent_or_under_minus_55_is_refused():
    wiggle = {-13: 0.9, -11: 1.1}                                                                       # the months 13 and 11 back differ from the one 12 back (1.0), so the year is exactly twelve months
    assert I.summarize(_path({**wiggle, -1: 1.39, 0: 1.899}, 50.0), TODAY)["change_1y_pct"] == 89.9    # +89.9%: just under the limit, like the real +62.0% of July 1933
    with pytest.raises(ValueError, match=r"industrial production changed by 90.1% over the year to 2026-09, outside -55% to \+90%"):
        I.summarize(_path({**wiggle, -1: 1.39, 0: 1.901}, 50.0), TODAY)                                # +90.1%
    assert I.summarize(_path({**wiggle, -2: 0.75, -1: 0.55, 0: 0.451}, 90.0), TODAY)["change_1y_pct"] == -54.9    # -54.9%: just inside, like the real -33.7% of February 1946
    with pytest.raises(ValueError, match=r"industrial production changed by -55.1% over the year to 2026-09, outside -55% to \+90%"):
        I.summarize(_path({**wiggle, -2: 0.75, -1: 0.55, 0: 0.449}, 90.0), TODAY)                      # -55.1%


def test_the_year_on_year_check_covers_every_month_of_the_window_not_only_the_newest():
    with pytest.raises(ValueError, match=r"over the year to 2026-08, outside"):
        I.summarize(_path({-2: 1.39, -1: 1.94, 0: 1.4}, 50.0), TODAY)                                  # +94% in the month before the newest, back to +40% in the newest


def test_the_real_months_of_2012_to_2026_are_never_refused_and_the_shocks_read_as_they_were():
    d = _data()
    cuts = [m for m in sorted(d["INDPRO"]) if m >= date(2013, 12, 1)]
    for cut in cuts:                                                                  # the card would never have gone dark in 154 real months
        sub = {sid: {k: v for k, v in s.items() if k <= cut} for sid, s in d.items()}
        assert I.summarize(sub, cut + timedelta(days=60))["available"], cut
    for cut, one_month, one_year, util in ((date(2020, 3, 1), -3.9, -5.3, 73.8), (date(2020, 4, 1), -13.2, -17.3, 64.1), (date(2020, 6, 1), 6.6, -10.6, 69.5),
                                           (date(2021, 4, 1), 0.2, 16.6, 76.1), (date(2021, 2, 1), -3.3, -5.7, 73.6)):
        sub = {sid: {k: v for k, v in s.items() if k <= cut} for sid, s in d.items()}
        s = I.summarize(sub, cut + timedelta(days=60))
        assert (s["change_1m_pct"], s["change_1y_pct"], s["capacity"]["utilization_pct"]) == (one_month, one_year, util)
    sub = {sid: {k: v for k, v in s.items() if k <= date(2023, 1, 1)} for sid, s in d.items()}
    assert I.summarize(sub, date(2023, 3, 1))["utilities"]["change_1m_pct"] == -10.0   # the largest fall of a group in the last 14 years, -10.03%


def test_the_total_may_not_move_more_than_two_hundredths_of_a_point_outside_the_range_of_its_three_groups():
    groups_up = dict(man=1.01, mine=1.01, util=1.01, tcu=1.005)                       # every group +1.00%, utilization +0.50%
    assert I.summarize(_moved(total=1.00985, **groups_up), TODAY)["available"]       # +0.985%: 0.015 points under the lowest group
    assert I.summarize(_moved(total=1.01015, **groups_up), TODAY)["available"]       # +1.015%: 0.015 points over the highest group
    assert I.summarize(_moved(total=1.00985, **groups_up), TODAY)["detail"]["largest_miss_points"] == 0.015
    assert I.summarize(_moved(at=-5, total=1.00985, **groups_up), TODAY)["detail"]["largest_miss_points"] == 0.015   # the largest miss of the window is reported, not the last one (the month after it misses by 0.0147)
    with pytest.raises(ValueError, match=r"industrial production changed by \+0.97% in 2026-09 while manufacturing, mining and utilities moved between \+1.00% and \+1.00%"):
        I.summarize(_moved(total=1.0097, **groups_up), TODAY)                        # 0.03 under
    with pytest.raises(ValueError, match=r"industrial production changed by \+1.03% in 2026-09 while manufacturing, mining and utilities moved between \+1.00% and \+1.00%"):
        I.summarize(_moved(total=1.0103, **groups_up), TODAY)                        # 0.03 over


def test_the_range_of_the_groups_is_their_lowest_and_highest_not_the_first_or_the_last():
    mixed = dict(man=0.99, mine=1.02, util=1.005)                                     # -1.0%, +2.0% and +0.5%

    def case(total):
        return _moved(total=total, tcu=total, **mixed)                               # utilization moves with output, so the implied capacity stays put
    assert I.summarize(case(1.019), TODAY)["available"]                              # above two of the groups and below the third
    assert I.summarize(case(0.9902), TODAY)["available"]                             # -0.98%: above the lowest
    with pytest.raises(ValueError, match=r"moved between -1.00% and \+2.00%"):
        I.summarize(case(1.0203), TODAY)                                             # over the highest by 0.03
    with pytest.raises(ValueError, match=r"moved between -1.00% and \+2.00%"):
        I.summarize(case(0.9897), TODAY)                                             # under the lowest by 0.03


def test_the_between_groups_check_looks_at_the_last_24_months_and_no_further_back():
    second = I._label(I._months_back(LAST, 22))
    with pytest.raises(ValueError, match=f"changed by \\+3.00% in {second} while"):
        I.summarize(_moved(at=-22, total=1.03, tcu=1.03, stay=True), TODAY)          # the total alone steps up 3% (and utilization with it, so the implied capacity stays put)
    assert I.summarize(_moved(at=-23, total=1.03, tcu=1.03, stay=True), TODAY)["available"]


def test_the_capacity_implied_by_output_and_utilization_may_move_between_minus_half_and_plus_one_percent_a_month():
    assert I.summarize(_moved(tcu=1 / 1.009), TODAY)["detail"]["capacity_change_pct"]["largest"] == 0.9         # utilization falls, so the implied capacity rises 0.9%
    assert I.summarize(_moved(tcu=1 / 0.996), TODAY)["detail"]["capacity_change_pct"]["smallest"] == -0.4       # and falls 0.4%
    with pytest.raises(ValueError, match=r"the capacity implied by output and utilization changed by 1.10% in 2026-09, outside -0.5% to \+1.0%"):
        I.summarize(_moved(tcu=1 / 1.011), TODAY)
    with pytest.raises(ValueError, match=r"the capacity implied by output and utilization changed by -0.60% in 2026-09, outside -0.5% to \+1.0%"):
        I.summarize(_moved(tcu=1 / 0.994), TODAY)
    swapped = _data()
    swapped["TCU"] = {k: v + (5.0 if k >= date(2026, 9, 1) else 0.0) for k, v in swapped["TCU"].items()}     # utilization five points off in the newest month only
    with pytest.raises(ValueError, match="implied by output and utilization"):
        I.summarize(swapped, TODAY)


def test_the_capacity_check_looks_at_the_last_24_months_and_no_further_back():
    second = I._label(I._months_back(LAST, 22))
    with pytest.raises(ValueError, match=f"changed by -1.96% in {second}"):
        I.summarize(_moved(at=-22, tcu=1.02, stay=True), TODAY)                      # utilization steps up 2% with output flat: the implied capacity falls 1.96%
    assert I.summarize(_moved(at=-23, tcu=1.02, stay=True), TODAY)["available"]


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    assert [k for k in I.summarize(_synthetic(), TODAY)["checks"]] == ["range_ok", "months_in_a_row", "monthly_move_ok", "yearly_change_ok", "between_groups_ok", "capacity_ok"]
    # a total that moves 45% while its groups and utilization stay flat is stopped by the size of the move, which comes before the comparison with the groups
    with pytest.raises(ValueError, match="outside -30% to"):
        I.summarize(_moved(total=1.45), TODAY)


def test_a_series_missing_a_month_or_ending_in_another_month_is_refused():
    for sid in I.SERIES:
        d = _synthetic()
        del d[sid][LAST]
        with pytest.raises(ValueError, match="end in different months"):
            I.summarize(d, TODAY)
        d = _synthetic()
        d[sid][date(2026, 10, 1)] = 100.0                                            # a series that is a month AHEAD of the others
        with pytest.raises(ValueError, match="end in different months"):
            I.summarize(d, TODAY)
    for sid in ("IPMANSICS", "IPMINE", "IPUTIL", "TCU"):
        d = _synthetic()
        del d[sid][I._months_back(LAST, 5)]
        with pytest.raises(ValueError, match=f"{I.SERIES[sid]} is missing for 2026-04"):
            I.summarize(d, TODAY)
    d = _synthetic()
    del d["IPMINE"][I._months_back(LAST, 24)]                                        # a hole before the window: not looked at
    assert I.summarize(d, TODAY)["detail"]["months_checked"] == 24


def test_missing_values_are_skipped_never_filled():
    s = I.parse("observation_date,INDPRO\n2026-07-01,103.2006\n2026-08-01,.\n2026-09-01,\n", "INDPRO")
    assert s == {date(2026, 7, 1): 103.2006}


def test_the_series_asked_for_are_the_five_the_total_is_checked_against_and_not_the_naics_group():
    assert set(I.SERIES) == {"INDPRO", "IPMANSICS", "IPMINE", "IPUTIL", "TCU"} and "IPMAN" not in I.SERIES
    assert "NAICS" in I.__doc__ and "0.059" in I.__doc__ and "May 1971" in I.__doc__          # the module says why the SIC group was chosen


def test_overview_fetches_five_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = I.IndustrialProduction(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["level"] == 103.95 and n["n"] == 5 and r["source"].startswith("Board of Governors") and r["url"] == "https://fred.stlouisfed.org/series/INDPRO"
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 5


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(I.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = I.IndustrialProduction(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 5
    clock["t"] += I.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 5                                                               # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 10      # two minutes on it asks again
    clock["t"] += I.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 10
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 15 and (I.FAIL_TTL, I.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(I.IndustrialProduction(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "level" not in r
    bad = dict(F)
    bad["INDPRO"] = F["INDPRO"].replace("2026-09-01,103.9506", "2026-09-01,1039.506")                              # a decimal slip in the newest value: a check failing shows nothing either
    r = asyncio.run(I.IndustrialProduction(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "plausible range" in r["reason"] and "level" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(I.IndustrialProduction(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "Industrial production could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(I.IndustrialProduction(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "level" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/industrial-production")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(I.IndustrialProduction(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(I.SERIES)
    start = date.fromisoformat(seen[0].url.params["cosd"])
    assert 4100 <= (date.today() - start).days <= 4300                                       # about 11.5 years, enough for ten years of yearly change
