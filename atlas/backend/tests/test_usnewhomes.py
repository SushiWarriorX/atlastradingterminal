"""US new home sales (Census Bureau and HUD via FRED, 9 monthly series): the real saved record, the limits and tolerances as literals, one check at a time, the figures of the summary and the class."""
from __future__ import annotations

import asyncio
import json
import math
import re
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import atlas_api.usnewhomes as U

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usnewhomes.json").read_text())
TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)

TOT, NE, MW, SO, WE = "HSN1F", "HSN1FNE", "HSN1FMW", "HSN1FS", "HSN1FW"
INV, SUP, MED, AVG = "HNFSEPUSSA", "MSACSR", "MSPNHSUS", "ASPNHSUS"
IDS = [TOT, NE, MW, SO, WE, INV, SUP, MED, AVG]
NAME = {TOT: "sales", NE: "Northeast sales", MW: "Midwest sales", SO: "South sales", WE: "West sales", INV: "homes for sale", SUP: "months' supply", MED: "median price", AVG: "average price"}
LIMITS = {TOT: (230.0, 2060.0), NE: (6.0, 120.0), MW: (23.0, 245.0), SO: (130.0, 1195.0), WE: (52.0, 590.0), INV: (100.0, 1010.0), SUP: (1.6, 20.6), MED: (142000.0, 920000.0), AVG: (163000.0, 1080000.0)}
LEAVES = {NE: 40.0, MW: 100.0, SO: 420.0, WE: 200.0, INV: 570.0, MED: 400000.0, AVG: 480000.0}            # sales 760; the months' supply 12 * 570 / 760 is exactly 9.0


def mback(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, m + 1, 1)


def num(v):
    s = f"{v:,.1f}"
    return s[:-2] if s.endswith(".0") else s


def label(d):
    return f"{d.year}-{d.month:02d}"


def real():
    return {sid: U.parse(F[sid], sid) for sid in IDS}


def build(leaves):
    v = dict(leaves)
    v[TOT] = leaves[NE] + leaves[MW] + leaves[SO] + leaves[WE]
    v[SUP] = round(12 * leaves[INV] / v[TOT], 1)
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


def trend(k):                                                                      # every step exact in binary: sales grow by 0.5 a month
    return {**LEAVES, MW: 100.0 + k / 8, SO: 420.0 + k / 4, WE: 200.0 + k / 8, MED: 400000.0 + 1000.0 * k, AVG: 480000.0 + 1500.0 * k}


def run(data, today=TODAY):
    return U.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        U.summarize(data, TODAY)


def bump(data, month, deltas):
    d = {sid: dict(s) for sid, s in data.items()}
    for sid, gap in deltas.items():
        d[sid][month] += gap
    return d


OLDEST, MIDDLE = mback(LAST, 139), mback(LAST, 70)


def sum_msg(gap, month):
    return f"sales are {num(gap)} off the sum of the four regions in {label(month)}, over 2.5"


def supply_msg(sup, month, gap, calc):
    return f"the months' supply of {num(sup)} in {label(month)} is {gap} off 12 times homes for sale over sales ({calc}), over 0.1"


def price_msg(avg, med, month):
    return f"the average price of {num(avg)} is below the median of {num(med)} in {label(month)}"


# ---------------------------------------------------------------- the real record


def test_the_whole_real_record_passes_the_regions_add_up_in_every_month_and_the_supply_agrees_to_a_twentieth():
    data = real()
    months = sorted(data[TOT])
    assert len(months) == 141 and months[0] == date(2015, 1, 1) and months[-1] == LAST and all(set(data[s]) == set(months) for s in IDS)
    assert {data[TOT][d] - sum(data[s][d] for s in (NE, MW, SO, WE)) for d in months} == {0.0}              # whole thousands that add up exactly in all 141 months
    gaps = [abs(data[SUP][d] - 12.0 * data[INV][d] / data[TOT][d]) for d in months]
    assert max(gaps) < 0.0500001 and sum(1 for g in gaps if g > 0.0495) == 3                                  # the supply is published to a tenth: never more than half a tenth off
    assert min(data[AVG][d] - data[MED][d] for d in months) == 33800.0 and max(data[AVG][d] - data[MED][d] for d in months) == 135400.0
    r = run(data)
    assert r["available"] is True and r["date"] == "2026-09-01" and r["month"] == "2026-09" and r["age_days"] == 85 and r["freshness"] == "CURRENT"
    assert r["detail"] == {"months_checked": 141, "first_month": "2015-01", "last_month": "2026-09", "largest_sum_gap": 0.0, "largest_supply_gap": 0.05, "smallest_price_gap": 33800.0}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "sum_ok": True, "supply_ok": True, "prices_ok": True}
    assert r["source"] == "U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Sales, via FRED, St. Louis Fed (official, free public data)"
    assert r["url"] == "https://fred.stlouisfed.org/series/HSN1F"


def test_the_figures_of_the_newest_real_month_and_the_ten_year_ranges():
    r = run(real())
    assert r["sales"] == {"thousands": 676.0, "change_month": -4.0, "change_month_pct": -0.6, "change_year": -38.0, "change_year_pct": -5.3,
                          "growth_range": {"months": 120, "first": "2016-10", "lowest": {"value": -33.2, "month": "2021-10"}, "highest": {"value": 51.4, "month": "2020-07"}, "share_lower_pct": 29}}
    got = {x["key"]: (x["thousands"], x["share_pct"], x["change_month"], x["change_month_pct"], x["change_year"], x["change_year_pct"]) for x in r["regions"]}
    assert got == {"northeast": (32.0, 4.7, 7.0, 28.0, 3.0, 10.3), "midwest": (89.0, 13.2, -7.0, -7.3, -8.0, -8.2),
                   "south": (413.0, 61.1, -29.0, -6.6, -3.0, -0.7), "west": (142.0, 21.0, 25.0, 21.4, -30.0, -17.4)}
    assert [x["key"] for x in r["regions"]] == ["northeast", "midwest", "south", "west"] and [x["label"] for x in r["regions"]] == ["Northeast", "Midwest", "South", "West"]
    assert r["stock"] == {"for_sale": 476.0, "for_sale_change_month": -5.0, "for_sale_change_year": -11.0, "months_supply": 8.4, "supply_change_month": -0.1, "supply_change_year": 0.2,
                          "supply_range": {"months": 120, "first": "2016-10", "lowest": {"value": 3.3, "month": "2020-10"}, "highest": {"value": 10.3, "month": "2022-07"}, "share_lower_pct": 73}}
    assert r["prices"] == {"median": 400400.0, "median_change_year": -16400.0, "median_change_year_pct": -3.9, "average": 472800.0, "average_change_year": -34000.0, "average_change_year_pct": -6.7,
                           "median_range": {"months": 120, "first": "2016-10", "lowest": {"value": 298000.0, "month": "2017-02"}, "highest": {"value": 460300.0, "month": "2022-10"}, "share_lower_pct": 53}}
    assert r["recent"] == [{"month": "2026-04", "thousands": 641.0, "change": -18.0, "months_supply": 9.0}, {"month": "2026-05", "thousands": 636.0, "change": -5.0, "months_supply": 9.2},
                           {"month": "2026-06", "thousands": 680.0, "change": 44.0, "months_supply": 8.5}, {"month": "2026-07", "thousands": 647.0, "change": -33.0, "months_supply": 8.9},
                           {"month": "2026-08", "thousands": 680.0, "change": 33.0, "months_supply": 8.5}, {"month": "2026-09", "thousands": 676.0, "change": -4.0, "months_supply": 8.4}]


def test_the_limits_are_the_literals_about_half_the_lowest_and_twice_the_highest_real_value():
    assert U.LIMITS == LIMITS and U.NAMES == NAME and U.SERIES == IDS
    data = real()
    for sid, (lo, hi) in LIMITS.items():
        low, high = min(data[sid].values()), max(data[sid].values())
        assert lo < low < hi and lo < high < hi
        assert 0.45 < lo / low < 0.55 and 1.95 < hi / high < 2.05, sid


def test_the_constants_the_address_the_source_and_the_ids_are_the_literals_written_here():
    assert U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and U.PAGE == "https://fred.stlouisfed.org/series/HSN1F"
    assert U.SOURCE == "U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Sales, via FRED, St. Louis Fed (official, free public data)"
    assert (U.TOT, U.NE, U.MW, U.SO, U.WE, U.INV, U.SUP, U.MED, U.AVG) == (TOT, NE, MW, SO, WE, INV, SUP, MED, AVG)
    assert U.REGIONS == (("northeast", "Northeast", NE), ("midwest", "Midwest", MW), ("south", "South", SO), ("west", "West", WE))


def test_the_tolerances_follow_the_rounding_and_the_record_starts_in_2015():
    assert U.SUM_TOLERANCE == 2.5 and U.SUPPLY_TOLERANCE == 0.1                       # five figures at half a thousand each; the supply is published to a tenth
    assert U.START == "2015-01-01" and U.MIN_MONTHS == 132 and U.HISTORY_MONTHS == 120 and U.RECENT_MONTHS == 6 and U.OVERDUE_AFTER_DAYS == 95 and U.TTL == 6 * 3600.0 and U.FAIL_TTL == 120.0 and U.CONCURRENCY == 6


# ---------------------------------------------------------------- the months


@pytest.mark.parametrize("sid", IDS)
def test_a_series_that_ends_a_month_early_is_refused_first_whichever_series_it_is(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the new home sales series end in different months")


def test_a_series_that_covers_other_months_is_named_and_sales_is_the_base():
    for sid in IDS[1:]:
        d = world()
        del d[sid][MIDDLE]
        refused(d, f"the {NAME[sid]} series covers different months than sales")
    d = world()
    del d[AVG][MIDDLE]
    del d[NE][MIDDLE]
    refused(d, "the Northeast sales series covers different months than sales")                 # the first one in the series order is named
    d = world()
    del d[TOT][MIDDLE]
    refused(d, "the Northeast sales series covers different months than sales")


def test_a_date_that_is_not_the_first_of_a_month_is_refused():
    d = {sid: {k + timedelta(days=1): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a new home sales date is not the 1st of a month")
    d = {sid: {(k + timedelta(days=1) if k == MIDDLE else k): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a new home sales date is not the 1st of a month")


def test_a_skipped_month_is_named_by_the_month_before_it():
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    refused(d, f"the new home sales months skip a month after {label(mback(MIDDLE, 1))}")
    d = {sid: {k: v for k, v in s.items() if k != OLDEST} for sid, s in world().items()}
    assert run(d)["detail"]["months_checked"] == 139


def test_fewer_than_132_months_are_refused_and_132_pass():
    refused(world(n=131), "the new home sales series cover 131 months, fewer than the 132 expected")
    assert run(world(n=132))["detail"]["months_checked"] == 132


# ---------------------------------------------------------------- the ranges


def one_month(sid, v):
    ok = build(LEAVES)
    data = {s: {LAST: ok[s]} for s in IDS}
    data[sid][LAST] = v
    return data


@pytest.mark.parametrize("sid", IDS)
def test_every_series_is_inside_its_range_at_both_edges_and_outside_just_beyond(sid):
    lo, hi = LIMITS[sid]
    for v in (lo, hi, (lo + hi) / 2):
        U._check_ranges(one_month(sid, v), [LAST])
    for v in (lo - 0.1, hi + 0.1):
        with pytest.raises(ValueError, match=f"^{re.escape(f'{NAME[sid]} of {num(v)} in 2026-09 is outside {num(lo)} to {num(hi)}')}$"):
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
    d[TOT][OLDEST + timedelta(days=1)] = 99999999.0
    refused(d, "a new home sales date is not the 1st of a month")
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    d[TOT][OLDEST] = 99999999.0
    refused(d, f"the new home sales months skip a month after {label(mback(MIDDLE, 1))}")
    d = world(n=131)
    d[TOT][mback(LAST, 130)] = 99999999.0
    refused(d, "the new home sales series cover 131 months, fewer than the 132 expected")
    d = world()
    d[TOT][OLDEST] = 99999999.0
    del d[NE][MIDDLE]
    refused(d, "the Northeast sales series covers different months than sales")
    d = world()
    d[TOT][OLDEST] = 99999999.0
    del d[AVG][LAST]
    refused(d, "the new home sales series end in different months")


def test_the_ranges_come_before_the_sum_the_supply_and_the_prices():
    refused(bump(world(), LAST, {TOT: 5000.0}), "sales of 5,760 in 2026-09 is outside 230 to 2,060")
    refused(bump(world(), LAST, {SUP: 50.0}), "months' supply of 59 in 2026-09 is outside 1.6 to 20.6")
    refused(bump(world(), LAST, {MED: 900000.0}), "median price of 1,300,000 in 2026-09 is outside 142,000 to 920,000")


def test_a_message_names_the_first_wrong_series_in_the_series_order_and_the_oldest_month():
    d = world()
    d[AVG][LAST] = 99999999.0
    d[NE][MIDDLE] = 99999999.0
    refused(d, f"Northeast sales of 99,999,999 in {label(MIDDLE)} is outside 6 to 120")
    d = world()
    d[NE][LAST] = 99999999.0
    d[NE][OLDEST] = 99999999.0
    refused(d, f"Northeast sales of 99,999,999 in {label(OLDEST)} is outside 6 to 120")


# ---------------------------------------------------------------- the sum of the regions


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("sid", [TOT, NE, MW, SO, WE])
def test_the_regions_may_be_two_and_a_half_thousand_off_and_are_refused_just_beyond(sid, sign, month):
    assert run(bump(world(), month, {sid: 2.5 * sign}))["detail"]["largest_sum_gap"] == 2.5
    refused(bump(world(), month, {sid: 2.6 * sign}), sum_msg(2.6, month))


def test_the_sum_is_scanned_from_the_oldest_month_and_the_largest_gap_is_kept_over_all_months():
    refused(bump(bump(world(), LAST, {NE: 4.0}), OLDEST, {SO: 3.0}), sum_msg(3, OLDEST))
    refused(bump(bump(world(), LAST, {NE: 3.0}), MIDDLE, {SO: 5.0}), sum_msg(5, MIDDLE))
    assert run(world())["detail"]["largest_sum_gap"] == 0.0
    assert run(bump(world(), MIDDLE, {NE: 1.0}))["detail"]["largest_sum_gap"] == 1.0
    assert run(bump(bump(world(), MIDDLE, {NE: 1.0}), LAST, {SO: 2.0}))["detail"]["largest_sum_gap"] == 2.0
    assert run(bump(bump(world(), OLDEST, {NE: 0.5}), LAST, {MW: 0.25}))["detail"]["largest_sum_gap"] == 0.5
    assert run(bump(world(), LAST, {NE: 0.00004}))["detail"]["largest_sum_gap"] == 0.0
    assert run(bump(world(), LAST, {NE: 0.0001}))["detail"]["largest_sum_gap"] == 0.0001


def test_the_sum_comes_before_the_supply_and_the_prices():
    refused(bump(world(), LAST, {TOT: 100.0, MED: 100000.0}), sum_msg(100, LAST))                # the supply and the order of the prices are wrong here too
    refused(bump(world(), LAST, {SO: 100.0}), sum_msg(100, LAST))


# ---------------------------------------------------------------- the months' supply


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_the_supply_may_be_a_tenth_off_and_is_refused_just_beyond(sign, month):
    ok = run(bump(world(), month, {SUP: 0.1 * sign}))
    assert ok["detail"]["largest_supply_gap"] == 0.1
    refused(bump(world(), month, {SUP: 0.11 * sign}), supply_msg(9.0 + 0.11 * sign, month, "0.11", "9.00"))


def test_the_supply_names_both_numbers_it_was_worked_out_from():
    refused(bump(world(), LAST, {INV: 50.0}), supply_msg(9.0, LAST, "0.79", "9.79"))                  # 12 * 620 / 760
    refused(bump(world(), LAST, {INV: -50.0}), supply_msg(9.0, LAST, "0.79", "8.21"))                 # 12 * 520 / 760
    refused(bump(world(), LAST, {SUP: 0.5}), supply_msg(9.5, LAST, "0.50", "9.00"))


def test_the_supply_is_scanned_from_the_oldest_month_and_the_largest_gap_is_kept():
    refused(bump(bump(world(), LAST, {SUP: 0.5}), OLDEST, {SUP: 0.3}), supply_msg(9.3, OLDEST, "0.30", "9.00"))
    assert run(world())["detail"]["largest_supply_gap"] == 0.0
    assert run(bump(bump(world(), MIDDLE, {SUP: 0.05}), LAST, {SUP: -0.075}))["detail"]["largest_supply_gap"] == 0.075
    assert run(bump(world(), LAST, {SUP: 0.00004}))["detail"]["largest_supply_gap"] == 0.0
    assert run(bump(world(), LAST, {SUP: 0.0001}))["detail"]["largest_supply_gap"] == 0.0001


def test_the_supply_comes_before_the_prices():
    refused(bump(world(), LAST, {SUP: 0.5, MED: 100000.0}), supply_msg(9.5, LAST, "0.50", "9.00"))


# ---------------------------------------------------------------- the order of the prices


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
def test_the_average_price_may_equal_the_median_and_is_refused_one_dollar_below_it(month):
    assert run(bump(world(), month, {AVG: -80000.0}))["detail"]["smallest_price_gap"] == 0.0
    refused(bump(world(), month, {AVG: -80001.0}), price_msg(399999.0, 400000.0, month))
    refused(bump(world(), month, {MED: 80001.0}), price_msg(480000.0, 480001.0, month))


def test_the_prices_are_scanned_from_the_oldest_month_and_the_smallest_gap_is_kept():
    refused(bump(bump(world(), LAST, {MED: 100000.0}), OLDEST, {MED: 90000.0}), price_msg(480000.0, 490000.0, OLDEST))
    assert run(world())["detail"]["smallest_price_gap"] == 80000.0
    assert run(bump(bump(world(), MIDDLE, {AVG: -70000.0}), LAST, {AVG: -75000.0}))["detail"]["smallest_price_gap"] == 5000.0
    assert run(bump(world(), OLDEST, {AVG: -79999.5}))["detail"]["smallest_price_gap"] == 0.5


@pytest.mark.parametrize("sid", IDS)
def test_each_series_takes_part_in_its_check(sid):
    want = {TOT: sum_msg(3, LAST), NE: sum_msg(3, LAST), MW: sum_msg(3, LAST), SO: sum_msg(3, LAST), WE: sum_msg(3, LAST),
            INV: supply_msg(9.0, LAST, "0.79", "9.79"), SUP: supply_msg(9.5, LAST, "0.50", "9.00"), MED: price_msg(480000.0, 500000.0, LAST), AVG: price_msg(380000.0, 400000.0, LAST)}
    shift = {TOT: 3.0, NE: 3.0, MW: -3.0, SO: 3.0, WE: -3.0, INV: 50.0, SUP: 0.5, MED: 100000.0, AVG: -100000.0}
    refused(bump(world(), LAST, {sid: shift[sid]}), want[sid])


# ---------------------------------------------------------------- the figures


def test_a_flat_world_has_no_change_and_no_negative_zero_and_shares_that_need_rounding():
    r = run(world())
    assert r["sales"] == {"thousands": 760.0, "change_month": 0.0, "change_month_pct": 0.0, "change_year": 0.0, "change_year_pct": 0.0,
                          "growth_range": {"months": 120, "first": "2016-10", "lowest": {"value": 0.0, "month": "2016-10"}, "highest": {"value": 0.0, "month": "2016-10"}, "share_lower_pct": 0}}
    assert [(x["key"], x["thousands"], x["share_pct"], x["change_month"], x["change_month_pct"], x["change_year"], x["change_year_pct"]) for x in r["regions"]] == [
        ("northeast", 40.0, 5.3, 0.0, 0.0, 0.0, 0.0), ("midwest", 100.0, 13.2, 0.0, 0.0, 0.0, 0.0), ("south", 420.0, 55.3, 0.0, 0.0, 0.0, 0.0), ("west", 200.0, 26.3, 0.0, 0.0, 0.0, 0.0)]      # 5.263, 13.158, 55.263 and 26.316: rounded, not cut
    assert r["stock"]["months_supply"] == 9.0 and r["stock"]["for_sale"] == 570.0 and r["stock"]["supply_change_month"] == 0.0 and r["stock"]["supply_change_year"] == 0.0
    assert r["prices"]["median"] == 400000.0 and r["prices"]["average"] == 480000.0 and r["prices"]["median_change_year_pct"] == 0.0 and r["prices"]["average_change_year"] == 0.0
    flat = [r["sales"]["change_month"], r["sales"]["change_month_pct"], r["sales"]["change_year"], r["sales"]["change_year_pct"], r["stock"]["for_sale_change_month"], r["stock"]["for_sale_change_year"],
            r["stock"]["supply_change_month"], r["stock"]["supply_change_year"], r["prices"]["median_change_year"], r["prices"]["median_change_year_pct"], r["prices"]["average_change_year"], r["prices"]["average_change_year_pct"]]
    assert all(math.copysign(1.0, x) > 0 for x in flat)


def test_a_fall_to_nothing_is_a_plain_zero_and_a_change_is_kept_to_a_tenth():
    r = run(world_by(lambda k: {**LEAVES, MW: 100.0 - 0.04 * (k == 139)}))
    mw = next(x for x in r["regions"] if x["key"] == "midwest")
    assert mw["change_month"] == 0.0 and str(mw["change_month"]) == "0.0" and mw["change_month_pct"] == 0.0 and str(mw["change_month_pct"]) == "0.0" and str(mw["change_year"]) == "0.0"
    r = run(world_by(lambda k: {**LEAVES, SO: 420.0 - 25.0 * (k == 139)}))
    assert r["sales"]["change_month"] == -25.0 and r["sales"]["change_month_pct"] == -3.3 and r["sales"]["change_year"] == -25.0
    r = run(world_by(lambda k: {**LEAVES, MW: 100.0 + 0.44 * (k == 139)}))
    mw = next(x for x in r["regions"] if x["key"] == "midwest")
    assert mw["change_month"] == 0.4 and mw["change_year"] == 0.4 and r["sales"]["change_month"] == 0.4          # kept to a tenth: not to a whole thousand and not to hundredths


def test_a_rising_trend_gives_exact_levels_changes_shares_ranges_and_the_last_six_months():
    r = run(world_by(trend))
    assert r["sales"] == {"thousands": 829.5, "change_month": 0.5, "change_month_pct": 0.1, "change_year": 6.0, "change_year_pct": 0.7,
                          "growth_range": {"months": 120, "first": "2016-10", "lowest": {"value": 0.7, "month": "2022-11"}, "highest": {"value": 0.8, "month": "2016-10"}, "share_lower_pct": 0}}
    got = {x["key"]: (x["thousands"], x["share_pct"], x["change_month"], x["change_month_pct"], x["change_year"], x["change_year_pct"]) for x in r["regions"]}
    assert got == {"northeast": (40.0, 4.8, 0.0, 0.0, 0.0, 0.0), "midwest": (117.375, 14.2, 0.1, 0.1, 1.5, 1.3), "south": (454.75, 54.8, 0.2, 0.1, 3.0, 0.7), "west": (217.375, 26.2, 0.1, 0.1, 1.5, 0.7)}
    assert r["stock"] == {"for_sale": 570.0, "for_sale_change_month": 0.0, "for_sale_change_year": 0.0, "months_supply": 8.2, "supply_change_month": -0.1, "supply_change_year": -0.1,
                          "supply_range": {"months": 120, "first": "2016-10", "lowest": {"value": 8.2, "month": "2026-09"}, "highest": {"value": 8.9, "month": "2016-10"}, "share_lower_pct": 0}}
    assert r["prices"] == {"median": 539000.0, "median_change_year": 12000.0, "median_change_year_pct": 2.3, "average": 688500.0, "average_change_year": 18000.0, "average_change_year_pct": 2.7,
                           "median_range": {"months": 120, "first": "2016-10", "lowest": {"value": 420000.0, "month": "2016-10"}, "highest": {"value": 539000.0, "month": "2026-09"}, "share_lower_pct": 99}}
    assert r["recent"] == [{"month": m, "thousands": v, "change": 0.5, "months_supply": s} for m, v, s in (("2026-04", 827.0, 8.3), ("2026-05", 827.5, 8.3), ("2026-06", 828.0, 8.3), ("2026-07", 828.5, 8.3), ("2026-08", 829.0, 8.3), ("2026-09", 829.5, 8.2))]
    assert r["detail"] == {"months_checked": 140, "first_month": "2015-02", "last_month": "2026-09", "largest_sum_gap": 0.0, "largest_supply_gap": 0.05, "smallest_price_gap": 80000.0}      # the world's supply is rounded to a tenth, so it is up to half a tenth off the exact ratio


def test_the_month_change_and_the_year_change_each_use_their_own_month():
    r = run(world_by(lambda k: {**LEAVES, SO: 420.0 + (100.0 if k == 139 - 12 else 0.0) + (10.0 if k == 139 - 1 else 0.0), INV: 570.0 + 150.0 * (k == 139 - 12) + 25.0 * (k == 139 - 1)}))
    assert r["sales"]["change_month"] == -10.0 and r["sales"]["change_year"] == -100.0
    assert r["sales"]["change_month_pct"] == -1.3 and r["sales"]["change_year_pct"] == -11.6
    assert r["stock"]["for_sale_change_month"] == -25.0 and r["stock"]["for_sale_change_year"] == -150.0 and r["stock"]["supply_change_month"] == -0.3 and r["stock"]["supply_change_year"] == -1.0


def test_the_prices_use_the_year_earlier_and_never_the_month_before():
    r = run(world_by(lambda k: {**LEAVES, MED: 400000.0 + (50000.0 if k == 139 - 12 else 0.0) + (30000.0 if k == 139 - 1 else 0.0), AVG: 480000.0 + (60000.0 if k == 139 - 12 else 0.0) + (30000.0 if k == 139 - 1 else 0.0)}))
    assert r["prices"]["median_change_year"] == -50000.0 and r["prices"]["median_change_year_pct"] == -11.1
    assert r["prices"]["average_change_year"] == -60000.0 and r["prices"]["average_change_year_pct"] == -11.1
    assert "median_change_month" not in r["prices"] and "average_change_month" not in r["prices"]


def test_the_growth_range_ranks_all_120_months_and_counts_only_strictly_lower_ones():
    r = run(world_by(lambda k: {**LEAVES, SO: LEAVES[SO] + (38.0 if k == 139 else 0.0)}))
    assert r["sales"]["change_month"] == 38.0 and r["sales"]["change_month_pct"] == 5.0 and r["sales"]["change_year"] == 38.0 and r["sales"]["change_year_pct"] == 5.0
    assert r["sales"]["growth_range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 0.0, "month": "2016-10"}, "highest": {"value": 5.0, "month": "2026-09"}, "share_lower_pct": 99}
    r = run(world_by(lambda k: {**LEAVES, SO: LEAVES[SO] + (38.0 if k >= 130 else 0.0)}))
    assert r["sales"]["growth_range"]["months"] == 120 and r["sales"]["growth_range"]["share_lower_pct"] == 92


def test_the_ranges_are_over_the_last_120_months_of_a_longer_record():
    r = run(world_by(lambda k: {**LEAVES, SO: LEAVES[SO] + (50.0 if k == 5 else 0.0), MED: LEAVES[MED] + (100000.0 if k == 5 else 0.0), AVG: LEAVES[AVG] + (100000.0 if k == 5 else 0.0)}, n=140))
    g = r["sales"]["growth_range"]
    assert g["months"] == 120 and g["first"] == "2016-10" and g["highest"]["value"] == 0.0 and g["lowest"]["value"] == 0.0
    assert r["prices"]["median_range"]["highest"]["value"] == 400000.0 and r["stock"]["supply_range"]["months"] == 120 and r["prices"]["median_range"]["months"] == 120
    r = run(world_by(lambda k: {**LEAVES, SO: LEAVES[SO] + (50.0 if k == 25 else 0.0), MED: LEAVES[MED] + (100000.0 if k == 25 else 0.0), AVG: LEAVES[AVG] + (100000.0 if k == 25 else 0.0)}, n=140))
    assert r["sales"]["growth_range"]["highest"]["value"] == 6.6 and r["sales"]["growth_range"]["highest"]["month"] == "2017-03"                  # 114 months before 2026-09 is 2017-03
    assert r["prices"]["median_range"]["highest"] == {"value": 500000.0, "month": "2017-03"}


def test_a_release_that_is_late_is_marked_overdue_after_95_days_from_the_first_of_the_month():
    assert run(world(), LAST + timedelta(days=95))["freshness"] == "CURRENT" and run(world(), LAST + timedelta(days=95))["age_days"] == 95
    assert run(world(), LAST + timedelta(days=96))["freshness"] == "OVERDUE" and run(world(), LAST + timedelta(days=96))["age_days"] == 96
    assert run(world(), LAST)["age_days"] == 0 and run(world(), LAST)["freshness"] == "CURRENT"


def test_the_requests_go_to_the_fred_csv_address_and_carry_nothing_but_the_id_and_the_start():
    urls, data = [], world()

    async def handler(request):
        urls.append((request.url.scheme, request.url.host, request.url.path, sorted(request.url.params)))
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsNewHomes(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(urls) == 9 and all(u == ("https", "fred.stlouisfed.org", "/graph/fredgraph.csv", ["cosd", "id"]) for u in urls)


def test_the_note_says_what_the_figures_are_and_are_not_and_points_to_the_check_line():
    note = run(world())["note"]
    assert note.startswith("New home sales from the Census Bureau and the Department of Housing and Urban Development (the New Residential Sales release): sales of new one-family houses in thousands at a seasonally adjusted annual rate, ")
    assert ", so 676 means sales were running at a pace of 676,000 houses a year. " in note
    assert ". The homes for sale are counted at the end of the month, and the months' supply is the Census Bureau's own ratio of the homes for sale to the sales rate. " in note
    assert ". Prices are not seasonally adjusted, so they are compared with a year earlier. These are new houses: sales of existing homes are another measure and are not here. The newest months are revised later. " in note
    assert "the ranges, the sum of the four regions, the months' supply and the order of the two prices are in the Check line" in note and note.count("the Check line") == 1
    assert note.endswith("This describes sales that already happened: it is not a market signal or a forecast.")


# ---------------------------------------------------------------- the messages


def test_every_failure_message_fits_in_the_110_characters_a_card_shows():
    msgs = [sum_msg(1234.5, OLDEST), supply_msg(20.6, OLDEST, "12.34", "33.18"), price_msg(1080000.0, 1080000.01, OLDEST), "the new home sales series end in different months",
            "the Northeast sales series covers different months than sales", "a new home sales date is not the 1st of a month", f"the new home sales months skip a month after {label(OLDEST)}",
            "the new home sales series cover 131 months, fewer than the 132 expected", f"Northeast sales of 99,999,999 in {label(OLDEST)} is outside 6 to 120", f"average price of 99,999,999 in {label(OLDEST)} is outside 163,000 to 1,080,000",
            f"median price of 99,999,999 in {label(OLDEST)} is outside 142,000 to 920,000"]
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
    c = U.UsNewHomes(client=make_client(world(), seen), demo=True)
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is True and r["reason"] == "Demo mode: the real US new home sales figures are not shown because made-up values would look real." and seen == []
    assert "sales" not in r and r["as_of"] == NOW.isoformat()


def test_one_request_per_series_each_with_its_id_and_the_start_date_and_six_at_a_time():
    seen, stats = [], {"now": 0, "peak": 0}
    c = U.UsNewHomes(client=make_client(world(), seen, delay=0.01, stats=stats))
    r = arun(c.overview(NOW))
    assert r["available"] is True and r["demo"] is False and r["date"] == "2026-09-01" and r["age_days"] == 85
    assert sorted(x["id"] for x in seen) == sorted(IDS) and all(x == {"id": x["id"], "cosd": "2015-01-01"} for x in seen)
    assert stats["peak"] == 6


def test_the_real_record_through_the_class_gives_the_same_answer_as_the_summary():
    r = arun(U.UsNewHomes(client=make_client(real())).overview(NOW))
    assert r["available"] is True and r["sales"]["thousands"] == 676.0 and r["detail"]["months_checked"] == 141 and r["as_of"] == NOW.isoformat()


def test_a_good_answer_is_kept_for_six_hours_and_asked_again_after_that(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(U, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    seen = []
    c = U.UsNewHomes(client=make_client(world(), seen))
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
    c = U.UsNewHomes(client=make_client(world(), seen, status=500))
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is False and r["reason"].startswith("US new home sales could not be read right now (") and "sales" not in r
    n = len(seen)
    clock[0] += 119.0
    arun(c.overview(NOW))
    assert len(seen) == n
    clock[0] += 1.0
    arun(c.overview(NOW))
    assert len(seen) > n


def test_a_figure_that_fails_a_check_is_named_in_words_with_its_month_in_words():
    d = world()
    d[TOT][LAST] = 9000.0
    r = arun(U.UsNewHomes(client=make_client(d)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US new home sales could not be read right now (the data failed a check: sales of 9,000 in September 2026 is outside 230 to 2,060)" and "sales" not in r


def test_a_client_it_makes_itself_is_closed_and_one_it_is_given_is_not(monkeypatch):
    made, instances = [], []

    class Own(REAL_CLIENT):
        def __init__(self, **kw):
            made.append(kw)
            instances.append(self)
            super().__init__(transport=transport_for(world()))

    monkeypatch.setattr(U.httpx, "AsyncClient", Own)
    c = U.UsNewHomes()
    assert arun(c.overview(NOW))["available"] is True and made == [{"timeout": 25}] and instances[0].is_closed is True
    given = make_client(world())
    arun(U.UsNewHomes(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_default_clock_is_utc_and_stamps_the_answer():
    r = arun(U.UsNewHomes(client=make_client(world())).overview())
    stamp = datetime.fromisoformat(r["as_of"])
    assert stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0) and abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


def test_each_request_goes_with_the_clients_own_user_agent_and_nothing_added():
    seen, data = [], world()

    async def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsNewHomes(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(seen) == 9 and all(ua.startswith("python-httpx/") for ua in seen)


def test_a_dropped_connection_a_timeout_and_a_missing_key_read_plainly(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("")

    def slow(request):
        raise httpx.ReadTimeout("")

    for fail, words in ((boom, "the connection could not be made"), (slow, "the request timed out")):
        r = arun(U.UsNewHomes(client=REAL_CLIENT(transport=httpx.MockTransport(fail))).overview(NOW))
        assert r["available"] is False and r["reason"] == f"US new home sales could not be read right now ({words})"

    def no_key(data, today):
        raise KeyError("HSN1F")

    monkeypatch.setattr(U, "summarize", no_key)
    r = arun(U.UsNewHomes(client=make_client(world())).overview(NOW))
    assert r["available"] is False and r["reason"] == "US new home sales could not be read right now (the answer was not in the expected shape)"


def test_any_answer_but_200_is_refused_with_its_status_in_words():
    r = arun(U.UsNewHomes(client=make_client(world(), status=500)).overview(NOW))
    assert r["reason"] == "US new home sales could not be read right now (the server had an error, HTTP 500)"
    r = arun(U.UsNewHomes(client=make_client(world(), status=204)).overview(NOW))
    assert r["reason"] == "US new home sales could not be read right now (the server answered HTTP 204)"


def test_the_clock_decides_the_age_not_the_computer_date():
    c = U.UsNewHomes(client=make_client(world()))
    r = arun(c.overview(datetime(2026, 12, 6, 1, tzinfo=timezone.utc)))
    assert r["age_days"] == 96 and r["freshness"] == "OVERDUE"
