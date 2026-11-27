"""US building permits (Census Bureau and HUD via FRED, 8 monthly series): the real saved record, the limits and tolerances as literals, one check at a time, the figures of the summary and the class."""
from __future__ import annotations

import asyncio
import json
import re
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import atlas_api.usbuildingpermits as U

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usbuildingpermits.json").read_text())
TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
LAST = date(2026, 10, 1)

TOT, ONE, TWO, FIVE = "PERMIT", "PERMIT1", "PERMIT24", "PERMIT5"
NE, MW, SO, WE = "PERMITNE", "PERMITMW", "PERMITS", "PERMITW"
IDS = [TOT, ONE, TWO, FIVE, NE, MW, SO, WE]
NAME = {TOT: "total permits", ONE: "single-family permits", TWO: "2-4 unit permits", FIVE: "5+ unit permits", NE: "Northeast permits", MW: "Midwest permits", SO: "South permits", WE: "West permits"}
LIMITS = {TOT: (520.0, 3850.0), ONE: (310.0, 2500.0), TWO: (12.0, 135.0), FIVE: (170.0, 1525.0), NE: (30.0, 575.0), MW: (70.0, 545.0), SO: (260.0, 2070.0), WE: (125.0, 960.0)}
LEAVES = {ONE: 800.0, TWO: 50.0, FIVE: 450.0, NE: 130.0, MW: 200.0, SO: 700.0}          # the total is 1,300 and the West is what is left, 270, so that both sums hold exactly
TYPE_PARTS, REGION_PARTS = (ONE, TWO, FIVE), (NE, MW, SO, WE)


def mback(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, m + 1, 1)


def num(v):
    s = f"{v:,.1f}"
    return s[:-2] if s.endswith(".0") else s


def real():
    return {sid: U.parse(F[sid], sid) for sid in IDS}


def build(leaves):
    v = {k: leaves[k] for k in (ONE, TWO, FIVE, NE, MW, SO)}
    v[TOT] = v[ONE] + v[TWO] + v[FIVE]
    v[WE] = v[TOT] - v[NE] - v[MW] - v[SO]
    return v


def world(n=140, last=LAST, **changed):
    one = build({**LEAVES, **changed})
    return {sid: {mback(last, i): v for i in range(n - 1, -1, -1)} for sid, v in one.items()}


def world_by(fn, n=140, last=LAST):
    data = {sid: {} for sid in IDS}
    for i in range(n - 1, -1, -1):
        for sid, v in build(fn(n - 1 - i)).items():
            data[sid][mback(last, i)] = v
    return data


STEPS = {ONE: 2.0, TWO: 0.5, FIVE: 1.0, NE: 0.5, MW: 0.5, SO: 1.0}                     # thousands a month, every one exact in binary


def trend(k):
    return {name: v + STEPS[name] * k for name, v in LEAVES.items()}


def run(data, today=TODAY):
    return U.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        U.summarize(data, TODAY)


def shifted(data, month, sids, gap):
    d = {sid: dict(s) for sid, s in data.items()}
    for sid in sids:
        d[sid][month] += gap
    return d


OLDEST, MIDDLE = mback(LAST, 139), mback(LAST, 70)


def label(d):
    return f"{d.year}-{d.month:02d}"


def types_msg(gap, month):
    return f"total permits is {num(gap)} thousand off single-family plus 2-4 unit plus 5+ unit permits in {label(month)}, over 2"


def regions_msg(gap, month):
    return f"total permits is {num(gap)} thousand off the four regions together in {label(month)}, over 2.5"


# ---------------------------------------------------------------- the real record


def test_the_whole_real_record_passes_and_both_sums_hold_exactly_in_every_month():
    data = real()
    months = sorted(data[TOT])
    assert len(months) == 142 and months[0] == date(2015, 1, 1) and months[-1] == LAST and all(set(data[s]) == set(months) for s in IDS)
    for d in months:
        assert data[TOT][d] == data[ONE][d] + data[TWO][d] + data[FIVE][d] == data[NE][d] + data[MW][d] + data[SO][d] + data[WE][d]
    r = run(data)
    assert r["available"] is True and r["date"] == "2026-10-01" and r["month"] == "2026-10" and r["age_days"] == 55 and r["freshness"] == "CURRENT"
    assert r["detail"] == {"months_checked": 142, "first_month": "2015-01", "last_month": "2026-10", "largest_sum_gap": 0.0}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "sums_ok": True}
    assert r["source"] == "U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Construction (building permits), via FRED, St. Louis Fed (official, free public data)" and r["url"] == "https://fred.stlouisfed.org/series/PERMIT"


def test_the_figures_of_the_newest_real_month_and_the_ten_year_growth_range():
    r = run(real())
    assert r["total"] == {"thousands": 1295.0, "change_month_thousands": -103.0, "change_month_pct": -7.4, "change_year_thousands": -123.0, "change_year_pct": -8.7,
                          "growth_range": {"months": 120, "first": "2016-11", "lowest": {"value": -26.3, "month": "2023-01"}, "highest": {"value": 58.5, "month": "2021-04"}, "share_lower_pct": 10}}
    got = {x["key"]: (x["thousands"], x["share_pct"], x["change_month_thousands"], x["change_month_pct"], x["change_year_thousands"], x["change_year_pct"]) for x in r["types"] + r["regions"]}
    assert got == {"single_family": (772.0, 59.6, -74.0, -8.7, -114.0, -12.9), "two_to_four": (48.0, 3.7, -3.0, -5.9, -7.0, -12.7), "five_or_more": (475.0, 36.7, -26.0, -5.2, -2.0, -0.4),
                   "northeast": (135.0, 10.4, -10.0, -6.9, -10.0, -6.9), "midwest": (213.0, 16.4, 1.0, 0.5, 16.0, 8.1), "south": (675.0, 52.1, -81.0, -10.7, -61.0, -8.3), "west": (272.0, 21.0, -13.0, -4.6, -68.0, -20.0)}
    assert [x["key"] for x in r["types"]] == ["single_family", "two_to_four", "five_or_more"] and [x["key"] for x in r["regions"]] == ["northeast", "midwest", "south", "west"]
    assert [x["label"] for x in r["types"]] == ["Single-family homes", "Homes in buildings of 2 to 4 units", "Homes in buildings of 5 or more units"]
    assert [x["label"] for x in r["regions"]] == ["Northeast", "Midwest", "South", "West"]
    assert r["recent"] == [{"month": "2026-05", "thousands": 1410.0, "change_thousands": -13.0}, {"month": "2026-06", "thousands": 1374.0, "change_thousands": -36.0}, {"month": "2026-07", "thousands": 1433.0, "change_thousands": 59.0},
                           {"month": "2026-08", "thousands": 1403.0, "change_thousands": -30.0}, {"month": "2026-09", "thousands": 1398.0, "change_thousands": -5.0}, {"month": "2026-10", "thousands": 1295.0, "change_thousands": -103.0}]


def test_the_limits_are_the_literals_about_half_the_lowest_and_twice_the_highest_real_value():
    assert U.LIMITS == LIMITS and U.NAMES == NAME and U.SERIES == IDS
    data = real()
    for sid, (lo, hi) in LIMITS.items():
        low, high = min(data[sid].values()), max(data[sid].values())
        assert lo < low < hi and lo < high < hi
        assert 0.45 < lo / low < 0.55 and 1.95 < hi / high < 2.05, sid


def test_the_tolerances_are_half_a_thousand_for_each_figure_of_a_sum_and_the_record_starts_in_2015():
    assert [(w, p, t, what) for w, p, t, what in U.SUMS] == [(TOT, (ONE, TWO, FIVE), 2.0, "single-family plus 2-4 unit plus 5+ unit permits"), (TOT, (NE, MW, SO, WE), 2.5, "the four regions together")]
    assert U.START == "2015-01-01" and U.MIN_MONTHS == 132 and U.HISTORY_MONTHS == 120 and U.RECENT_MONTHS == 6 and U.OVERDUE_AFTER_DAYS == 90 and U.TTL == 6 * 3600.0 and U.FAIL_TTL == 120.0 and U.CONCURRENCY == 6


# ---------------------------------------------------------------- the months


def test_series_that_end_in_different_months_are_refused_first():
    d = world()
    del d[ONE][LAST]
    refused(d, "the building permit series end in different months")
    d = world()
    del d[TOT][LAST]
    refused(d, "the building permit series end in different months")                    # the total counts too
    d = world()
    d[WE] = {k: v for k, v in d[WE].items() if k != LAST}
    refused(d, "the building permit series end in different months")


def test_a_series_that_covers_other_months_is_named_and_the_total_is_the_base():
    d = world()
    del d[ONE][MIDDLE]
    refused(d, "the single-family permits series covers different months than total permits")
    d = world()
    del d[WE][MIDDLE]
    refused(d, "the West permits series covers different months than total permits")
    d = world()
    del d[TWO][MIDDLE]
    del d[WE][MIDDLE]
    refused(d, "the 2-4 unit permits series covers different months than total permits")
    d = world()
    del d[TOT][MIDDLE]
    refused(d, "the single-family permits series covers different months than total permits")


def test_a_date_that_is_not_the_first_of_a_month_is_refused():
    d = {sid: {k + timedelta(days=1): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a building permit date is not the 1st of a month")
    d = {sid: {(k + timedelta(days=1) if k == MIDDLE else k): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a building permit date is not the 1st of a month")


def test_a_skipped_month_is_named_by_the_month_before_it():
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    refused(d, f"the building permit months skip a month after {label(mback(MIDDLE, 1))}")
    d = {sid: {k: v for k, v in s.items() if k != OLDEST} for sid, s in world().items()}
    assert run(d)["detail"]["months_checked"] == 139


def test_fewer_than_132_months_are_refused_and_132_pass():
    refused(world(n=131), "the building permit series cover 131 months, fewer than the 132 expected")
    assert run(world(n=132))["detail"]["months_checked"] == 132


# ---------------------------------------------------------------- the ranges


def one_month(sid, v):
    ok = build(LEAVES)
    data = {s: {LAST: ok[s]} for s in IDS}
    data[sid][LAST] = v
    return data


@pytest.mark.parametrize("sid", IDS)
def test_every_series_is_inside_its_range_at_both_edges_and_outside_one_thousand_beyond(sid):
    lo, hi = LIMITS[sid]
    for v in (lo, hi, (lo + hi) / 2):
        U._check_ranges(one_month(sid, v), [LAST])
    for v in (lo - 1.0, hi + 1.0):
        with pytest.raises(ValueError, match=f"^{re.escape(f'{NAME[sid]} of {num(v)} in 2026-10 is outside {num(lo)} to {num(hi)}')}$"):
            U._check_ranges(one_month(sid, v), [LAST])


@pytest.mark.parametrize("sid", IDS)
def test_the_oldest_and_the_newest_month_are_both_range_checked_for_every_series(sid):
    lo, hi = LIMITS[sid]
    for month in (OLDEST, LAST):
        for v in (lo - 1.0, hi + 1.0):
            d = world()
            d[sid][month] = v
            refused(d, f"{NAME[sid]} of {num(v)} in {label(month)} is outside {num(lo)} to {num(hi)}")


def test_every_months_check_comes_before_the_ranges():
    d = {sid: {k + timedelta(days=1): v for k, v in s.items()} for sid, s in world().items()}
    d[TOT][OLDEST + timedelta(days=1)] = 99999.0
    refused(d, "a building permit date is not the 1st of a month")
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    d[TOT][OLDEST] = 99999.0
    refused(d, f"the building permit months skip a month after {label(mback(MIDDLE, 1))}")
    d = world(n=131)
    d[TOT][mback(LAST, 130)] = 99999.0
    refused(d, "the building permit series cover 131 months, fewer than the 132 expected")


def test_the_ranges_come_before_the_sums_and_the_months_before_the_ranges():
    d = shifted(world(), LAST, [TOT], 5000.0)
    refused(d, "total permits of 6,300 in 2026-10 is outside 520 to 3,850")
    d = world()
    d[TOT][OLDEST] = 99999.0
    del d[ONE][MIDDLE]
    refused(d, "the single-family permits series covers different months than total permits")


def test_a_message_names_the_first_wrong_series_in_the_series_order_and_the_oldest_month():
    d = world()
    d[SO][LAST] = 9999.0
    d[ONE][MIDDLE] = 99999.0
    refused(d, f"single-family permits of 99,999 in {label(MIDDLE)} is outside 310 to 2,500")
    d = world()
    d[ONE][LAST] = 99999.0
    d[ONE][OLDEST] = 99999.0
    refused(d, f"single-family permits of 99,999 in {label(OLDEST)} is outside 310 to 2,500")


# ---------------------------------------------------------------- the sums


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_the_types_sum_holds_at_2_thousand_off_and_fails_at_2_and_a_half(month, sign):
    ok = shifted(world(), month, [TOT, WE], 2.0 * sign)                     # the regions still add up, the types are 2 off
    assert run(ok)["detail"]["largest_sum_gap"] == 2.0
    refused(shifted(world(), month, [TOT, WE], 2.5 * sign), types_msg(2.5, month))


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_the_regions_sum_holds_at_2_and_a_half_off_and_fails_at_3(month, sign):
    ok = shifted(world(), month, [TOT, ONE], 2.5 * sign)                    # the types still add up, the regions are 2.5 off
    assert run(ok)["detail"]["largest_sum_gap"] == 2.5
    refused(shifted(world(), month, [TOT, ONE], 3.0 * sign), regions_msg(3, month))


@pytest.mark.parametrize("part", TYPE_PARTS)
def test_each_type_takes_part_in_the_types_sum(part):
    refused(shifted(world(), LAST, [part], 3.0), types_msg(3, LAST))
    refused(shifted(world(), LAST, [part], -3.0), types_msg(3, LAST))


@pytest.mark.parametrize("part", REGION_PARTS)
def test_each_region_takes_part_in_the_regions_sum(part):
    refused(shifted(world(), LAST, [part], 3.0), regions_msg(3, LAST))
    refused(shifted(world(), LAST, [part], -3.0), regions_msg(3, LAST))


def test_the_total_takes_part_in_both_sums():
    refused(shifted(world(), LAST, [TOT], 3.0), types_msg(3, LAST))                    # the types come first
    d = shifted(world(), LAST, [TOT, ONE], 3.0)
    refused(d, regions_msg(3, LAST))


def test_the_types_are_checked_before_the_regions_and_the_oldest_month_first():
    d = shifted(shifted(world(), LAST, [ONE], 3.0), OLDEST, [NE], 3.0)
    refused(d, types_msg(3, LAST))                                                      # the regions break is older, but the types relation is scanned first
    d = shifted(shifted(world(), LAST, [ONE], 3.0), MIDDLE, [ONE], 4.0)
    refused(d, types_msg(4, MIDDLE))
    d = shifted(shifted(world(), LAST, [NE], 3.0), MIDDLE, [NE], 4.0)
    refused(d, regions_msg(4, MIDDLE))


def test_the_largest_gap_is_kept_over_both_relations_and_all_the_months():
    assert run(world())["detail"]["largest_sum_gap"] == 0.0
    d = shifted(world(), MIDDLE, [ONE], 1.0)
    assert run(d)["detail"]["largest_sum_gap"] == 1.0
    d = shifted(shifted(world(), MIDDLE, [ONE], 1.0), LAST, [NE], 2.0)
    assert run(d)["detail"]["largest_sum_gap"] == 2.0
    d = shifted(shifted(world(), OLDEST, [ONE], 0.5), LAST, [NE], 0.25)
    assert run(d)["detail"]["largest_sum_gap"] == 0.5
    d = shifted(world(), LAST, [ONE], 0.00004)
    assert run(d)["detail"]["largest_sum_gap"] == 0.0
    d = shifted(world(), LAST, [ONE], 0.0001)
    assert run(d)["detail"]["largest_sum_gap"] == 0.0001


# ---------------------------------------------------------------- the figures


def test_a_flat_world_has_no_change_and_no_negative_zero_and_exact_shares():
    r = run(world())
    assert r["total"] == {"thousands": 1300.0, "change_month_thousands": 0.0, "change_month_pct": 0.0, "change_year_thousands": 0.0, "change_year_pct": 0.0,
                          "growth_range": {"months": 120, "first": "2016-11", "lowest": {"value": 0.0, "month": "2016-11"}, "highest": {"value": 0.0, "month": "2016-11"}, "share_lower_pct": 0}}
    assert [(x["key"], x["thousands"], x["share_pct"], x["change_month_thousands"], x["change_month_pct"]) for x in r["types"]] == [("single_family", 800.0, 61.5, 0.0, 0.0), ("two_to_four", 50.0, 3.8, 0.0, 0.0), ("five_or_more", 450.0, 34.6, 0.0, 0.0)]
    assert [(x["key"], x["thousands"], x["share_pct"]) for x in r["regions"]] == [("northeast", 130.0, 10.0), ("midwest", 200.0, 15.4), ("south", 700.0, 53.8), ("west", 270.0, 20.8)]
    import math
    assert all(math.copysign(1.0, x) > 0 for x in (r["total"]["change_month_thousands"], r["total"]["change_month_pct"], r["total"]["change_year_thousands"], r["total"]["change_year_pct"]))


def test_a_falling_world_shows_the_changes_with_their_signs_and_a_fall_to_nothing_as_plain_zero():
    r = run(world_by(lambda k: {**LEAVES, TWO: 50.0 - 0.01 * (k == 139)}))
    two = next(x for x in r["types"] if x["key"] == "two_to_four")
    assert two["change_month_thousands"] == 0.0 and str(two["change_month_thousands"]) == "0.0" and two["change_month_pct"] == 0.0 and str(two["change_month_pct"]) == "0.0"
    r = run(world_by(lambda k: {**LEAVES, ONE: 800.0 - 25.0 * (k == 139)}))
    assert r["total"]["change_month_thousands"] == -25.0 and r["total"]["change_month_pct"] == -1.9 and r["total"]["change_year_thousands"] == -25.0


def test_a_rising_trend_gives_exact_levels_changes_shares_and_the_last_six_months():
    r = run(world_by(trend))
    assert r["total"] == {"thousands": 1786.5, "change_month_thousands": 3.5, "change_month_pct": 0.2, "change_year_thousands": 42.0, "change_year_pct": 2.4,
                          "growth_range": {"months": 120, "first": "2016-11", "lowest": {"value": 2.4, "month": "2026-02"}, "highest": {"value": 3.2, "month": "2016-11"}, "share_lower_pct": 0}}
    assert r["types"] == [{"key": "single_family", "label": "Single-family homes", "thousands": 1078.0, "share_pct": 60.3, "change_month_thousands": 2.0, "change_month_pct": 0.2, "change_year_thousands": 24.0, "change_year_pct": 2.3},
                          {"key": "two_to_four", "label": "Homes in buildings of 2 to 4 units", "thousands": 119.5, "share_pct": 6.7, "change_month_thousands": 0.5, "change_month_pct": 0.4, "change_year_thousands": 6.0, "change_year_pct": 5.3},
                          {"key": "five_or_more", "label": "Homes in buildings of 5 or more units", "thousands": 589.0, "share_pct": 33.0, "change_month_thousands": 1.0, "change_month_pct": 0.2, "change_year_thousands": 12.0, "change_year_pct": 2.1}]
    assert r["regions"] == [{"key": "northeast", "label": "Northeast", "thousands": 199.5, "share_pct": 11.2, "change_month_thousands": 0.5, "change_month_pct": 0.3, "change_year_thousands": 6.0, "change_year_pct": 3.1},
                            {"key": "midwest", "label": "Midwest", "thousands": 269.5, "share_pct": 15.1, "change_month_thousands": 0.5, "change_month_pct": 0.2, "change_year_thousands": 6.0, "change_year_pct": 2.3},
                            {"key": "south", "label": "South", "thousands": 839.0, "share_pct": 47.0, "change_month_thousands": 1.0, "change_month_pct": 0.1, "change_year_thousands": 12.0, "change_year_pct": 1.5},
                            {"key": "west", "label": "West", "thousands": 478.5, "share_pct": 26.8, "change_month_thousands": 1.5, "change_month_pct": 0.3, "change_year_thousands": 18.0, "change_year_pct": 3.9}]
    assert r["recent"] == [{"month": m, "thousands": v, "change_thousands": 3.5} for m, v in (("2026-05", 1769.0), ("2026-06", 1772.5), ("2026-07", 1776.0), ("2026-08", 1779.5), ("2026-09", 1783.0), ("2026-10", 1786.5))]
    assert r["detail"] == {"months_checked": 140, "first_month": "2015-03", "last_month": "2026-10", "largest_sum_gap": 0.0}


def test_the_month_change_and_the_year_change_each_use_their_own_month():
    r = run(world_by(lambda k: {**LEAVES, ONE: 800.0 + (100.0 if k == 139 - 12 else 0.0) + (10.0 if k == 139 - 1 else 0.0)}))
    assert r["total"]["change_month_thousands"] == -10.0 and r["total"]["change_year_thousands"] == -100.0
    assert r["total"]["change_month_pct"] == round(100 * -10 / 1310, 1) and r["total"]["change_year_pct"] == round(100 * -100 / 1400, 1)


def test_the_growth_range_ranks_all_120_months_and_counts_only_strictly_lower_ones():
    def bump(k):
        return {**LEAVES, ONE: LEAVES[ONE] + (30.0 if k == 139 else 0.0), SO: LEAVES[SO] + (30.0 if k == 139 else 0.0)}
    r = run(world_by(bump))
    assert r["total"]["change_month_thousands"] == 30.0 and r["total"]["change_month_pct"] == 2.3 and r["total"]["change_year_thousands"] == 30.0 and r["total"]["change_year_pct"] == 2.3
    assert r["total"]["growth_range"] == {"months": 120, "first": "2016-11", "lowest": {"value": 0.0, "month": "2016-11"}, "highest": {"value": 2.3, "month": "2026-10"}, "share_lower_pct": 99}
    r = run(world_by(lambda k: {**LEAVES, ONE: LEAVES[ONE] + (30.0 if k >= 130 else 0.0), SO: LEAVES[SO] + (30.0 if k >= 130 else 0.0)}))
    assert r["total"]["growth_range"]["months"] == 120 and r["total"]["growth_range"]["share_lower_pct"] == 92


def test_the_growth_window_is_the_last_120_months_of_a_longer_record():
    r = run(world_by(lambda k: {**LEAVES, ONE: LEAVES[ONE] + (300.0 if k == 5 else 0.0)}, n=140))
    g = r["total"]["growth_range"]
    assert g["months"] == 120 and g["first"] == "2016-11" and g["highest"]["value"] == 0.0 and g["lowest"]["value"] == 0.0
    r = run(world_by(lambda k: {**LEAVES, ONE: LEAVES[ONE] + (300.0 if k == 25 else 0.0)}, n=140))
    assert r["total"]["growth_range"]["highest"]["value"] == 23.1 and r["total"]["growth_range"]["highest"]["month"] == "2017-04"          # 114 months before 2026-10 is 2017-04


def test_a_release_that_is_late_is_marked_overdue_after_90_days_from_the_first_of_the_month():
    assert run(world(), LAST + timedelta(days=90))["freshness"] == "CURRENT" and run(world(), LAST + timedelta(days=90))["age_days"] == 90
    assert run(world(), LAST + timedelta(days=91))["freshness"] == "OVERDUE" and run(world(), LAST + timedelta(days=91))["age_days"] == 91
    assert run(world(), LAST)["age_days"] == 0 and run(world(), LAST)["freshness"] == "CURRENT"


def test_the_requests_go_to_the_fred_csv_address_and_carry_nothing_but_the_id_and_the_start():
    assert U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv"
    urls, data = [], world()

    async def handler(request):
        urls.append((request.url.scheme, request.url.host, request.url.path, sorted(request.url.params)))
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsBuildingPermits(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(urls) == 8 and all(u == ("https", "fred.stlouisfed.org", "/graph/fredgraph.csv", ["cosd", "id"]) for u in urls)


def test_the_note_says_what_a_permit_is_and_is_not_and_points_to_the_check_line():
    note = run(world())["note"]
    assert "A permit is permission to build, not a home built" in note and "permits usually come before starts" in note and "the Check line" in note
    assert note.endswith("This describes permission to build that already happened: it is not a market signal or a forecast.")


# ---------------------------------------------------------------- the messages


def test_every_failure_message_fits_in_the_110_characters_a_card_shows():
    msgs = [types_msg(2.5, OLDEST), regions_msg(3, OLDEST), types_msg(1234.5, OLDEST), "the building permit series end in different months",
            "the Northeast permits series covers different months than total permits", "a building permit date is not the 1st of a month",
            f"the building permit months skip a month after {label(OLDEST)}", "the building permit series cover 131 months, fewer than the 132 expected",
            f"single-family permits of 99,999 in {label(OLDEST)} is outside 310 to 2,500", f"total permits of 519.5 in {label(OLDEST)} is outside 520 to 3,850"]
    assert max(len(m) for m in msgs) <= 110


# ---------------------------------------------------------------- the class


def csv_text(sid, series):
    return f"observation_date,{sid}\n" + "".join(f"{d.isoformat()},{v}\n" for d, v in sorted(series.items()))


REAL_CLIENT = httpx.AsyncClient


def make_client(data, seen=None, status=None, delay=0.0, stats=None):
    return REAL_CLIENT(transport=transport_for(data, seen, status, delay, stats))


def transport_for(data, seen=None, status=None, delay=0.0, stats=None):
    async def handler(request):
        sid = request.url.params["id"]
        if seen is not None:
            seen.append(dict(request.url.params))
        if stats is not None:
            stats["now"] += 1
            stats["peak"] = max(stats["peak"], stats["now"])
        if delay:
            await asyncio.sleep(delay)
        if stats is not None:
            stats["now"] -= 1
        if status:
            return httpx.Response(status)
        return httpx.Response(200, text=csv_text(sid, data[sid]))
    return httpx.MockTransport(handler)


def arun(coro):
    return asyncio.run(coro)


def test_demo_mode_shows_nothing_and_says_why_without_a_request():
    seen = []
    c = U.UsBuildingPermits(client=make_client(world(), seen), demo=True)
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is True and r["reason"] == "Demo mode: the real US building permit figures are not shown because made-up values would look real." and seen == []
    assert "total" not in r and r["as_of"] == NOW.isoformat()


def test_one_request_per_series_each_with_its_id_and_the_start_date_and_six_at_a_time():
    seen, stats = [], {"now": 0, "peak": 0}
    c = U.UsBuildingPermits(client=make_client(world(), seen, delay=0.01, stats=stats))
    r = arun(c.overview(NOW))
    assert r["available"] is True and r["demo"] is False and r["date"] == "2026-10-01" and r["age_days"] == 55
    assert sorted(x["id"] for x in seen) == sorted(IDS) and all(x == {"id": x["id"], "cosd": "2015-01-01"} for x in seen)
    assert stats["peak"] == 6


def test_the_real_record_through_the_class_gives_the_same_answer_as_the_summary():
    r = arun(U.UsBuildingPermits(client=make_client(real())).overview(NOW))
    assert r["available"] is True and r["total"]["thousands"] == 1295.0 and r["detail"]["months_checked"] == 142 and r["as_of"] == NOW.isoformat()


def test_a_good_answer_is_kept_for_six_hours_and_asked_again_after_that(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(U, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    seen = []
    c = U.UsBuildingPermits(client=make_client(world(), seen))
    arun(c.overview(NOW))
    n = len(seen)
    clock[0] += 21599.0
    r = arun(c.overview(NOW + timedelta(hours=1)))
    assert len(seen) == n and r["as_of"] == (NOW + timedelta(hours=1)).isoformat()
    clock[0] += 1.0
    arun(c.overview(NOW))
    assert len(seen) == 2 * n


def test_a_failure_is_worded_without_the_raw_error_and_kept_for_120_seconds(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(U, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    seen = []
    c = U.UsBuildingPermits(client=make_client(world(), seen, status=500))
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is False and r["reason"].startswith("US building permits could not be read right now (") and "total" not in r
    n = len(seen)
    clock[0] += 119.0
    arun(c.overview(NOW))
    assert len(seen) == n
    clock[0] += 1.0
    arun(c.overview(NOW))
    assert len(seen) > n


def test_a_figure_that_fails_a_check_is_named_in_words_with_its_month_in_words():
    d = world()
    d[TOT][LAST] = 5000.0
    r = arun(U.UsBuildingPermits(client=make_client(d)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US building permits could not be read right now (the data failed a check: total permits of 5,000 in October 2026 is outside 520 to 3,850)" and "total" not in r


def test_a_client_it_makes_itself_is_closed_and_one_it_is_given_is_not(monkeypatch):
    made, instances = [], []

    class Own(REAL_CLIENT):
        def __init__(self, **kw):
            made.append(kw)
            instances.append(self)
            super().__init__(transport=transport_for(world()))

    monkeypatch.setattr(U.httpx, "AsyncClient", Own)
    c = U.UsBuildingPermits()
    assert arun(c.overview(NOW))["available"] is True and made == [{"timeout": 25}] and instances[0].is_closed is True
    given = make_client(world())
    arun(U.UsBuildingPermits(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_default_clock_is_utc_and_stamps_the_answer():
    r = arun(U.UsBuildingPermits(client=make_client(world())).overview())
    stamp = datetime.fromisoformat(r["as_of"])
    assert stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0) and abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


def test_each_request_goes_with_the_clients_own_user_agent_and_nothing_added():
    seen, data = [], world()

    async def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsBuildingPermits(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(seen) == 8 and all(ua.startswith("python-httpx/") for ua in seen)


def test_a_dropped_connection_a_timeout_and_a_missing_key_read_plainly(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("")

    def slow(request):
        raise httpx.ReadTimeout("")

    for fail, words in ((boom, "the connection could not be made"), (slow, "the request timed out")):
        r = arun(U.UsBuildingPermits(client=REAL_CLIENT(transport=httpx.MockTransport(fail))).overview(NOW))
        assert r["available"] is False and r["reason"] == f"US building permits could not be read right now ({words})"

    def no_key(data, today):
        raise KeyError("PERMIT")

    monkeypatch.setattr(U, "summarize", no_key)
    r = arun(U.UsBuildingPermits(client=make_client(world())).overview(NOW))
    assert r["available"] is False and r["reason"] == "US building permits could not be read right now (the answer was not in the expected shape)"


def test_any_answer_but_200_is_refused_with_its_status_in_words():
    r = arun(U.UsBuildingPermits(client=make_client(world(), status=500)).overview(NOW))
    assert r["reason"] == "US building permits could not be read right now (the server had an error, HTTP 500)"
    r = arun(U.UsBuildingPermits(client=make_client(world(), status=204)).overview(NOW))
    assert r["reason"] == "US building permits could not be read right now (the server answered HTTP 204)"


def test_the_clock_decides_the_age_not_the_computer_date():
    c = U.UsBuildingPermits(client=make_client(world()))
    r = arun(c.overview(datetime(2027, 1, 8, 1, tzinfo=timezone.utc)))
    assert r["age_days"] == 99 and r["freshness"] == "OVERDUE"
