"""US factory orders (Census Bureau M3 survey via FRED, 13 monthly series in two groups): the real saved record, the limits and tolerances as literals, one check at a time, the figures of the summary and the class."""
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

import atlas_api.usfactoryorders as U

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usfactoryorders.json").read_text())
TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)

ORD_T, ORD_N, SHP_T, SHP_N, INV_T, INV_N, UNF_T = "AMTMNO", "AMNMNO", "AMTMVS", "AMNMVS", "AMTMTI", "AMNMTI", "AMTMUO"
ORD_D, SHP_D, INV_D, UNF_D, CORE, EXTR = "DGORDER", "AMDMVS", "AMDMTI", "AMDMUO", "NEWORDER", "ADXTNO"
FULL = [ORD_T, ORD_N, SHP_T, SHP_N, INV_T, INV_N, UNF_T]
DUR = [ORD_D, SHP_D, INV_D, UNF_D, CORE, EXTR]
IDS = FULL + DUR
NAME = {ORD_T: "new orders", ORD_N: "nondurable orders", SHP_T: "shipments", SHP_N: "nondurable shipments", INV_T: "inventories", INV_N: "nondurable inventories", UNF_T: "unfilled orders",
        ORD_D: "durable orders", SHP_D: "durable shipments", INV_D: "durable inventories", UNF_D: "durable unfilled orders", CORE: "core capital orders", EXTR: "orders excluding transport"}
LIMITS = {ORD_T: (180000.0, 1355000.0), ORD_N: (98000.0, 665000.0), SHP_T: (187000.0, 1340000.0), SHP_N: (98000.0, 665000.0), INV_T: (315000.0, 1955000.0), INV_N: (121000.0, 735000.0),
          UNF_T: (530000.0, 3250000.0), ORD_D: (82000.0, 695000.0), SHP_D: (89000.0, 680000.0), INV_D: (190000.0, 1230000.0), UNF_D: (530000.0, 3280000.0), CORE: (28000.0, 179000.0), EXTR: (67000.0, 455000.0)}
LEAVES = {ORD_D: 300000.0, ORD_N: 300000.0, SHP_D: 290000.0, INV_D: 500000.0, INV_N: 300000.0, UNF_D: 1200000.0, CORE: 80000.0, EXTR: 200000.0}       # every total and the nondurable shipments follow from these
SUMS = [(ORD_T, (ORD_D, ORD_N), "new orders", "durable plus nondurable orders"), (SHP_T, (SHP_D, SHP_N), "shipments", "durable plus nondurable shipments"), (INV_T, (INV_D, INV_N), "inventories", "durable plus nondurable inventories")]


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


def build(l):
    v = dict(l)
    v[ORD_T], v[SHP_N] = l[ORD_D] + l[ORD_N], l[ORD_N]
    v[SHP_T], v[INV_T], v[UNF_T] = l[SHP_D] + l[ORD_N], l[INV_D] + l[INV_N], l[UNF_D]
    return v


NEXT = mback(LAST, -1)                                                            # the month only the durable series have


def world(n=140, last=LAST, ahead=True, **changed):
    one = build({**LEAVES, **changed})
    data = {sid: {mback(last, i): v for i in range(n - 1, -1, -1)} for sid, v in one.items()}
    if ahead:
        for sid in DUR:
            data[sid][mback(last, -1)] = one[sid]
    return data


def world_by(fn, n=140, last=LAST, ahead=True):
    data = {sid: {} for sid in IDS}
    for i in range(n - 1, -1, -1):
        for sid, v in build(fn(n - 1 - i)).items():
            data[sid][mback(last, i)] = v
    if ahead:
        for sid, v in build(fn(n)).items():
            if sid in DUR:
                data[sid][mback(last, -1)] = v
    return data


def trend(k):                                                                      # every step exact in binary and in decimal
    return {ORD_D: 300000.0 + 1000.0 * k, ORD_N: 300000.0 + 500.0 * k, SHP_D: 290000.0 + 800.0 * k, INV_D: 500000.0 + 200.0 * k, INV_N: 300000.0 + 100.0 * k,
            UNF_D: 1200000.0 + 2000.0 * k, CORE: 80000.0 + 100.0 * k, EXTR: 200000.0 + 400.0 * k}


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


def drop(data, ids, month):
    d = {sid: dict(s) for sid, s in data.items()}
    for sid in ids:
        del d[sid][month]
    return d


OLDEST, MIDDLE, TESTED = mback(LAST, 139), mback(LAST, 70), mback(LAST, 1)        # TESTED: the newest month the sums look at (the newest common month is not tested)


def sum_msg(i, gap, month):
    return f"{SUMS[i][2]} are {num(gap)} million off {SUMS[i][3]} in {label(month)}, over 1.5"


def equal_msg(name, what, gap, month):
    return f"{name} are {num(gap)} million off {what} in {label(month)}, over 1"


# ---------------------------------------------------------------- the real record


def test_the_whole_real_record_passes_the_sums_and_equalities_hold_in_every_month_but_the_newest_common_one():
    data = real()
    months, dmonths = sorted(data[ORD_T]), sorted(data[ORD_D])
    assert len(months) == 141 and months[0] == date(2015, 1, 1) and months[-1] == LAST and all(set(data[s]) == set(months) for s in FULL)
    assert len(dmonths) == 142 and dmonths[-1] == date(2026, 10, 1) and all(set(data[s]) == set(dmonths) for s in DUR)
    for whole, parts, _, _ in SUMS:
        assert {data[whole][d] - sum(data[p][d] for p in parts) for d in months[:-1]} == {0.0}                 # whole millions that add up exactly in 140 of 141 months
    assert {data[ORD_N][d] - data[SHP_N][d] for d in months} == {0.0} and {data[UNF_T][d] - data[UNF_D][d] for d in months[:-1]} == {0.0}
    assert (data[ORD_T][LAST] - data[ORD_D][LAST] - data[ORD_N][LAST], data[SHP_T][LAST] - data[SHP_D][LAST] - data[SHP_N][LAST], data[INV_T][LAST] - data[INV_D][LAST] - data[INV_N][LAST], data[UNF_T][LAST] - data[UNF_D][LAST]) == (-270.0, 83.0, -516.0, -326.0)
    assert all(data[EXTR][d] <= data[ORD_D][d] and data[CORE][d] <= data[ORD_D][d] for d in dmonths)
    r = run(data)
    assert r["available"] is True and r["date"] == "2026-09-01" and r["month"] == "2026-09" and r["durable_month"] == "2026-10" and r["durable_advance"] is True
    assert r["age_days"] == 85 and r["freshness"] == "CURRENT"
    assert r["detail"] == {"months_checked": 141, "first_month": "2015-01", "last_month": "2026-09", "durable_last_month": "2026-10", "largest_sum_gap": 0.0, "largest_equal_gap": 0.0,
                           "newest_common": {"month": "2026-09", "orders": -270.0, "shipments": 83.0, "inventories": -516.0, "unfilled": -326.0}}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "sums_ok": True, "equal_ok": True, "parts_ok": True}
    assert r["source"] == "U.S. Census Bureau, Manufacturers' Shipments, Inventories, and Orders (M3 survey), via FRED, St. Louis Fed (official, free public data)" and r["url"] == "https://fred.stlouisfed.org/series/AMTMNO"


def test_the_figures_of_the_newest_real_months():
    r = run(real())
    got = lambda items: {x["key"]: (x["millions"], x["change_month_millions"], x["change_month_pct"], x["change_year_millions"], x["change_year_pct"]) for x in items}
    assert got(r["full"]) == {"orders": (677247.0, 12243.0, 1.8, 64373.0, 10.5), "shipments": (668454.0, 8823.0, 1.3, 61932.0, 10.2), "inventories": (976044.0, 3740.0, 0.4, 29350.0, 3.1), "unfilled": (1623818.0, 13781.0, 0.9, 133682.0, 9.0)}
    assert [(x["key"], x["label"]) for x in r["full"]] == [("orders", "New orders"), ("shipments", "Shipments"), ("inventories", "Inventories"), ("unfilled", "Unfilled orders")]
    assert got(r["nondurable"]) == {"orders": (331575.0, 5756.0, 1.8, 32848.0, 11.0), "inventories": (365685.0, 1681.0, 0.5, 8783.0, 2.5)}
    assert [(x["key"], x["label"], x["share_pct"]) for x in r["nondurable"]] == [("orders", "Nondurable goods orders and shipments", 49.0), ("inventories", "Nondurable goods inventories", 37.5)]
    assert got(r["durable"]) == {"orders": (346717.0, 775.0, 0.2, 39147.0, 12.7), "ex_transport": (226726.0, 1095.0, 0.5, 23254.0, 11.4), "core_capital": (89383.0, 1040.0, 1.2, 11435.0, 14.7),
                                 "shipments": (338591.0, 1795.0, 0.5, 29246.0, 9.5), "inventories": (613317.0, 2442.0, 0.4, 22600.0, 3.8), "unfilled": (1637192.0, 13048.0, 0.8, 143913.0, 9.6)}
    assert [(x["key"], x["label"]) for x in r["durable"]] == [("orders", "Durable goods orders"), ("ex_transport", "Orders excluding transportation"), ("core_capital", "Core capital goods orders"),
                                                             ("shipments", "Durable goods shipments"), ("inventories", "Durable goods inventories"), ("unfilled", "Durable goods unfilled orders")]
    assert all("share_pct" not in x for x in r["full"] + r["durable"])
    assert r["recent"] == [{"month": "2026-04", "orders": 665895.0, "orders_change": 33245.0, "shipments": 642896.0}, {"month": "2026-05", "orders": 658836.0, "orders_change": -7059.0, "shipments": 653231.0},
                           {"month": "2026-06", "orders": 657790.0, "orders_change": -1046.0, "shipments": 653505.0}, {"month": "2026-07", "orders": 662837.0, "orders_change": 5047.0, "shipments": 658647.0},
                           {"month": "2026-08", "orders": 665004.0, "orders_change": 2167.0, "shipments": 659631.0}, {"month": "2026-09", "orders": 677247.0, "orders_change": 12243.0, "shipments": 668454.0}]


def test_the_limits_are_the_literals_about_half_the_lowest_and_twice_the_highest_real_value():
    assert U.LIMITS == LIMITS and U.NAMES == NAME and U.SERIES == IDS and U.FULL == tuple(FULL) and U.DURABLE == tuple(DUR)
    data = real()
    for sid, (lo, hi) in LIMITS.items():
        low, high = min(data[sid].values()), max(data[sid].values())
        assert lo < low < hi and lo < high < hi
        assert 0.45 < lo / low < 0.55 and 1.95 < hi / high < 2.05, sid


def test_the_constants_the_address_the_source_and_the_ids_are_the_literals_written_here():
    assert U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and U.PAGE == "https://fred.stlouisfed.org/series/AMTMNO"
    assert U.SOURCE == "U.S. Census Bureau, Manufacturers' Shipments, Inventories, and Orders (M3 survey), via FRED, St. Louis Fed (official, free public data)"
    assert (U.ORD_T, U.ORD_N, U.SHP_T, U.SHP_N, U.INV_T, U.INV_N, U.UNF_T) == (ORD_T, ORD_N, SHP_T, SHP_N, INV_T, INV_N, UNF_T) and (U.ORD_D, U.SHP_D, U.INV_D, U.UNF_D, U.CORE, U.EXTR) == (ORD_D, SHP_D, INV_D, UNF_D, CORE, EXTR)


def test_the_relations_and_tolerances_are_written_out_here_and_the_record_starts_in_2015():
    assert U.SUMS == tuple((w, p, 1.5, what) for w, p, _, what in SUMS)                  # half a million for each of the three figures
    assert U.EQUALS == ((ORD_N, SHP_N, 1.0, "nondurable shipments", False), (UNF_T, UNF_D, 1.0, "durable unfilled orders", True)) and U.PARTS == ((EXTR, ORD_D), (CORE, ORD_D))
    assert U.START == "2015-01-01" and U.MIN_MONTHS == 132 and U.RECENT_MONTHS == 6 and U.OVERDUE_AFTER_DAYS == 100 and U.TTL == 6 * 3600.0 and U.FAIL_TTL == 120.0 and U.CONCURRENCY == 6


# ---------------------------------------------------------------- the months


@pytest.mark.parametrize("sid", FULL)
def test_a_full_report_series_that_ends_a_month_early_is_refused_first_whichever_series_it_is(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the full report series end in different months")


@pytest.mark.parametrize("sid", DUR)
def test_a_durable_series_that_ends_a_month_early_is_refused_whichever_series_it_is(sid):
    d = world()
    del d[sid][NEXT]
    refused(d, "the durable goods series end in different months")


def test_the_durable_series_end_with_the_full_report_or_one_month_after_it_and_not_otherwise():
    assert run(world(ahead=False))["durable_advance"] is False and run(world(ahead=False))["durable_month"] == "2026-09"
    assert run(world(ahead=True))["durable_advance"] is True and run(world(ahead=True))["durable_month"] == "2026-10"
    d = world()
    for sid in DUR:
        d[sid][mback(LAST, -2)] = d[sid][NEXT]
    refused(d, "the durable goods series end in a month that is neither the full report's nor the one after it")
    d = world(ahead=False)
    for sid in DUR:
        del d[sid][LAST]
    refused(d, "the durable goods series end in a month that is neither the full report's nor the one after it")


def test_the_full_report_is_checked_before_the_durable_series():
    d = world()
    del d[ORD_T][LAST]
    del d[SHP_D][NEXT]
    refused(d, "the full report series end in different months")


def test_a_series_that_covers_other_months_is_named_and_the_first_series_of_its_group_is_the_base():
    for sid in FULL[1:]:
        d = world()
        del d[sid][MIDDLE]
        refused(d, f"the {NAME[sid]} series covers different months than new orders")
    for sid in DUR[1:]:
        d = world()
        del d[sid][MIDDLE]
        refused(d, f"the {NAME[sid]} series covers different months than durable orders")
    d = world()
    del d[UNF_T][MIDDLE]
    del d[ORD_N][MIDDLE]
    refused(d, "the nondurable orders series covers different months than new orders")                   # the first one in the series order is named
    d = world()
    del d[ORD_T][MIDDLE]
    refused(d, "the nondurable orders series covers different months than new orders")
    d = world()
    del d[ORD_D][MIDDLE]
    refused(d, "the durable shipments series covers different months than durable orders")


def test_the_durable_series_must_cover_the_months_of_the_full_report_and_no_others():
    refused(drop(world(), DUR, MIDDLE), "the durable goods series cover other months than the full report")
    d = world()
    for sid in DUR:
        d[sid][mback(OLDEST, 1)] = d[sid][OLDEST]
    refused(d, "the durable goods series cover other months than the full report")


def test_a_date_that_is_not_the_first_of_a_month_is_refused():
    d = {sid: {k + timedelta(days=1): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a factory orders date is not the 1st of a month")
    d = {sid: {(k + timedelta(days=1) if k == MIDDLE else k): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a factory orders date is not the 1st of a month")
    for sid in (ORD_T, SHP_N, UNF_D, EXTR):                                                                  # in one series only: said before the months that differ and before the month after the full report
        d = world()
        d[sid] = {(k + timedelta(days=1) if k == MIDDLE else k): v for k, v in d[sid].items()}
        refused(d, "a factory orders date is not the 1st of a month")
    d = world()
    d[ORD_D] = {(k + timedelta(days=1) if k == NEXT else k): v for k, v in d[ORD_D].items()}
    for sid in DUR[1:]:
        d[sid] = {(k + timedelta(days=1) if k == NEXT else k): v for k, v in d[sid].items()}
    refused(d, "a factory orders date is not the 1st of a month")                                           # the newest durable month on the 2nd: not "neither the full report's nor the one after it"


def test_the_ends_are_checked_before_the_dates_and_both_before_anything_else():
    d = world()
    del d[ORD_T][LAST]
    d[SHP_N] = {(k + timedelta(days=1) if k == MIDDLE else k): v for k, v in d[SHP_N].items()}
    refused(d, "the full report series end in different months")
    d = world()
    del d[SHP_D][NEXT]
    d[SHP_N] = {(k + timedelta(days=1) if k == MIDDLE else k): v for k, v in d[SHP_N].items()}
    refused(d, "the durable goods series end in different months")


def test_a_skipped_month_is_named_by_the_month_before_it():
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    refused(d, f"the factory orders months skip a month after {label(mback(MIDDLE, 1))}")
    d = {sid: {k: v for k, v in s.items() if k != OLDEST} for sid, s in world().items()}
    assert run(d)["detail"]["months_checked"] == 139


def test_a_skipped_month_is_named_before_the_count_of_months():
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world(n=131).items()}                # 130 months left, and one of them missing in the middle: the skip is said first
    refused(d, f"the factory orders months skip a month after {label(mback(MIDDLE, 1))}")


def test_fewer_than_132_months_are_refused_and_132_pass():
    refused(world(n=131), "the factory orders series cover 131 months, fewer than the 132 expected")
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
        U._check_ranges(one_month(sid, v), {s: [LAST] for s in IDS})
    for v in (lo - 0.1, hi + 0.1):
        with pytest.raises(ValueError, match=f"^{re.escape(f'{NAME[sid]} of {num(v)} in 2026-09 is outside {num(lo)} to {num(hi)}')}$"):
            U._check_ranges(one_month(sid, v), {s: [LAST] for s in IDS})


@pytest.mark.parametrize("sid", IDS)
def test_the_oldest_and_the_newest_month_of_each_series_are_both_range_checked(sid):
    lo, hi = LIMITS[sid]
    for month in (OLDEST, NEXT if sid in DUR else LAST):
        for v in (lo - 1.0, hi + 1.0):
            d = world()
            d[sid][month] = v
            refused(d, f"{NAME[sid]} of {num(v)} in {label(month)} is outside {num(lo)} to {num(hi)}")


def test_every_months_check_comes_before_the_ranges():
    d = {sid: {k + timedelta(days=1): v for k, v in s.items()} for sid, s in world().items()}
    d[ORD_T][OLDEST + timedelta(days=1)] = 99999999.0
    refused(d, "a factory orders date is not the 1st of a month")
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    d[ORD_T][OLDEST] = 99999999.0
    refused(d, f"the factory orders months skip a month after {label(mback(MIDDLE, 1))}")
    d = world(n=131)
    d[ORD_T][mback(LAST, 130)] = 99999999.0
    refused(d, "the factory orders series cover 131 months, fewer than the 132 expected")
    d = world()
    d[ORD_T][OLDEST] = 99999999.0
    del d[ORD_N][MIDDLE]
    refused(d, "the nondurable orders series covers different months than new orders")
    d = world()
    d[ORD_T][OLDEST] = 99999999.0
    del d[SHP_D][NEXT]
    refused(d, "the durable goods series end in different months")


def test_the_ranges_come_before_the_sums_the_equalities_and_the_order_of_the_parts():
    refused(bump(world(), LAST, {ORD_T: 900000.0}), "new orders of 1,500,000 in 2026-09 is outside 180,000 to 1,355,000")
    refused(bump(world(), TESTED, {UNF_T: 3000000.0}), "unfilled orders of 4,200,000 in 2026-08 is outside 530,000 to 3,250,000")
    refused(bump(world(), NEXT, {CORE: 200000.0}), "core capital orders of 280,000 in 2026-10 is outside 28,000 to 179,000")


def test_a_message_names_the_first_wrong_series_in_the_series_order_and_the_oldest_month():
    d = world()
    d[EXTR][LAST] = 99999999.0
    d[ORD_T][MIDDLE] = 99999999.0
    refused(d, f"new orders of 99,999,999 in {label(MIDDLE)} is outside 180,000 to 1,355,000")
    d = world()
    d[ORD_N][LAST] = 99999999.0
    d[ORD_N][OLDEST] = 99999999.0
    refused(d, f"nondurable orders of 99,999,999 in {label(OLDEST)} is outside 98,000 to 665,000")


# ---------------------------------------------------------------- the three sums


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, TESTED])
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("i", range(3))
def test_each_sum_holds_at_one_and_a_half_million_off_and_is_refused_just_beyond(i, sign, month):
    whole = SUMS[i][0]
    assert run(bump(world(), month, {whole: 1.5 * sign}))["detail"]["largest_sum_gap"] == 1.5
    refused(bump(world(), month, {whole: 1.6 * sign}), sum_msg(i, 1.6, month))


@pytest.mark.parametrize("sid", [ORD_T, ORD_D, ORD_N, SHP_T, SHP_D, SHP_N, INV_T, INV_D, INV_N])
def test_each_series_takes_part_in_its_sum(sid):
    i = {ORD_T: 0, ORD_D: 0, ORD_N: 0, SHP_T: 1, SHP_D: 1, SHP_N: 1, INV_T: 2, INV_D: 2, INV_N: 2}[sid]
    refused(bump(world(), TESTED, {sid: 3.0}), sum_msg(i, 3, TESTED))
    refused(bump(world(), TESTED, {sid: -3.0}), sum_msg(i, 3, TESTED))


def test_the_newest_common_month_is_not_tested_and_its_gaps_are_reported_instead():
    r = run(bump(world(), LAST, {ORD_T: 5000.0, SHP_T: -83.0, INV_T: 516.0, UNF_T: 326.0}))
    assert r["detail"]["newest_common"] == {"month": "2026-09", "orders": 5000.0, "shipments": -83.0, "inventories": 516.0, "unfilled": 326.0}
    assert r["detail"]["largest_sum_gap"] == 0.0 and r["detail"]["largest_equal_gap"] == 0.0
    assert run(world(ahead=False))["detail"]["newest_common"] == {"month": "2026-09", "orders": 0.0, "shipments": 0.0, "inventories": 0.0, "unfilled": 0.0}
    r = run(bump(world(ahead=False), LAST, {ORD_T: 5000.0}))
    assert r["detail"]["newest_common"]["orders"] == 5000.0                          # also when the durable series end with the others: the newest month is left out either way


def test_the_gaps_of_the_newest_common_month_are_kept_to_a_tenth_and_a_gap_that_rounds_to_nothing_is_a_plain_zero():
    n = run(bump(world(), LAST, {ORD_T: -0.04, SHP_T: -0.04, INV_T: -0.04, UNF_T: -0.04}))["detail"]["newest_common"]
    assert n == {"month": "2026-09", "orders": 0.0, "shipments": 0.0, "inventories": 0.0, "unfilled": 0.0}
    assert all(math.copysign(1.0, n[k]) > 0 for k in ("orders", "shipments", "inventories", "unfilled"))
    n = run(bump(world(), LAST, {ORD_T: 0.46, SHP_T: -0.44, INV_T: 12.34, UNF_T: -0.06}))["detail"]["newest_common"]
    assert n == {"month": "2026-09", "orders": 0.5, "shipments": -0.4, "inventories": 12.3, "unfilled": -0.1}
    n = run(bump(world(), LAST, {ORD_N: 0.5}))["detail"]["newest_common"]                                                              # nondurable orders and shipments may differ by a million: each total uses its own
    assert (n["orders"], n["shipments"]) == (-0.5, 0.0)
    n = run(bump(world(), LAST, {SHP_N: 0.5}))["detail"]["newest_common"]
    assert (n["orders"], n["shipments"]) == (0.0, -0.5)
    n = run(bump(world(), LAST, {ORD_T: 300.0, SHP_T: 0.0, INV_T: -300.0, UNF_T: 100.0}))["detail"]["newest_common"]
    assert n == {"month": "2026-09", "orders": 300.0, "shipments": 0.0, "inventories": -300.0, "unfilled": 100.0}                      # the total less the parts, in that direction, and each from its own series


def test_the_sums_are_scanned_one_after_the_other_and_the_oldest_month_first():
    d = bump(bump(world(), OLDEST, {SHP_T: 3.0}), TESTED, {ORD_T: 4.0})
    refused(d, sum_msg(0, 4, TESTED))                                                # the second sum breaks in the oldest month, the first only in the newest tested: the first sum is scanned first
    d = bump(bump(world(), OLDEST, {INV_T: 3.0}), TESTED, {SHP_T: 4.0})
    refused(d, sum_msg(1, 4, TESTED))
    d = bump(bump(world(), TESTED, {ORD_T: 4.0}), MIDDLE, {ORD_T: 5.0})
    refused(d, sum_msg(0, 5, MIDDLE))                                                # inside a sum the oldest month comes first


def test_the_largest_sum_gap_is_kept_over_all_sums_and_all_the_tested_months():
    assert run(world())["detail"]["largest_sum_gap"] == 0.0
    assert run(bump(world(), MIDDLE, {ORD_T: 1.0}))["detail"]["largest_sum_gap"] == 1.0
    assert run(bump(bump(world(), MIDDLE, {ORD_T: 1.0}), TESTED, {INV_T: 1.5}))["detail"]["largest_sum_gap"] == 1.5
    assert run(bump(bump(world(), OLDEST, {ORD_T: 0.5}), TESTED, {SHP_T: 0.25}))["detail"]["largest_sum_gap"] == 0.5
    assert run(bump(world(), TESTED, {ORD_T: 0.00004}))["detail"]["largest_sum_gap"] == 0.0
    assert run(bump(world(), TESTED, {ORD_T: 0.0001}))["detail"]["largest_sum_gap"] == 0.0001


# ---------------------------------------------------------------- the published equalities


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, TESTED, LAST])
@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_nondurable_orders_and_shipments_may_differ_by_one_million_and_are_refused_just_beyond_in_every_month_including_the_newest(sign, month):
    ok = run(bump(world(), month, {SHP_N: 1.0 * sign, ORD_N: 0.0}))
    assert ok["detail"]["largest_equal_gap"] == 1.0
    refused(bump(world(), month, {SHP_N: 1.1 * sign}), equal_msg("nondurable orders", "nondurable shipments", 1.1, month))


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, TESTED])
@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_total_unfilled_orders_may_differ_from_the_durable_ones_by_one_million_and_are_refused_just_beyond(sign, month):
    assert run(bump(world(), month, {UNF_T: 1.0 * sign}))["detail"]["largest_equal_gap"] == 1.0
    refused(bump(world(), month, {UNF_T: 1.1 * sign}), equal_msg("unfilled orders", "durable unfilled orders", 1.1, month))


def test_the_unfilled_equality_is_not_tested_in_the_newest_common_month_and_the_gap_is_reported():
    r = run(bump(world(), LAST, {UNF_T: 50000.0}))
    assert r["detail"]["newest_common"]["unfilled"] == 50000.0 and r["detail"]["largest_equal_gap"] == 0.0


def test_the_largest_equal_gap_is_kept_to_four_decimals_over_both_equalities_and_all_months():
    assert run(world())["detail"]["largest_equal_gap"] == 0.0
    assert run(bump(world(), TESTED, {UNF_T: 0.00004}))["detail"]["largest_equal_gap"] == 0.0
    assert run(bump(world(), TESTED, {UNF_T: 0.0001}))["detail"]["largest_equal_gap"] == 0.0001
    assert run(bump(world(), LAST, {SHP_N: 0.00004, ORD_N: 0.0}))["detail"]["largest_equal_gap"] == 0.0
    assert run(bump(world(), LAST, {SHP_N: 0.0001, ORD_N: 0.0}))["detail"]["largest_equal_gap"] == 0.0001
    assert run(bump(bump(world(), MIDDLE, {UNF_T: 0.25}), TESTED, {UNF_T: 0.5}))["detail"]["largest_equal_gap"] == 0.5
    assert run(bump(bump(world(), OLDEST, {UNF_T: 0.75}), TESTED, {UNF_T: 0.5}))["detail"]["largest_equal_gap"] == 0.75
    assert run(bump(bump(world(), MIDDLE, {SHP_N: 0.5, ORD_N: 0.0}), TESTED, {UNF_T: 0.25}))["detail"]["largest_equal_gap"] == 0.5          # the gap of the first equality is kept when the second one is smaller


def test_the_equalities_come_after_the_sums_and_are_scanned_in_their_order_and_the_oldest_month_first():
    refused(bump(world(), TESTED, {ORD_N: 5.0}), sum_msg(0, 5, TESTED))                   # the nondurable orders also feed the sum: it speaks first
    d = bump(bump(world(), OLDEST, {UNF_T: 3.0}), TESTED, {SHP_N: 1.2})
    refused(d, equal_msg("nondurable orders", "nondurable shipments", 1.2, TESTED))        # the first equality is scanned first
    d = bump(bump(world(), TESTED, {SHP_N: 1.2}), MIDDLE, {SHP_N: 1.3})
    refused(d, equal_msg("nondurable orders", "nondurable shipments", 1.3, MIDDLE))
    assert run(bump(bump(world(), MIDDLE, {UNF_T: 0.5}), TESTED, {UNF_T: 0.75}))["detail"]["largest_equal_gap"] == 0.75


# ---------------------------------------------------------------- the order of the durable parts


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST, NEXT])
def test_orders_excluding_transport_may_equal_durable_orders_and_are_refused_one_above_it_in_every_durable_month(month):
    assert run(bump(world(), month, {EXTR: 100000.0}))["checks"]["parts_ok"] is True
    refused(bump(world(), month, {EXTR: 100001.0}), f"orders excluding transport of 300,001 is above durable orders of 300,000 in {label(month)}")


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST, NEXT])
def test_core_capital_orders_may_equal_durable_orders_and_are_refused_one_above_it_in_every_durable_month(month):
    low = {ORD_D: 100000.0, EXTR: 90000.0}                                           # durable orders small enough for core capital goods to reach them, and still above the orders excluding transport
    assert run(bump(world(**low), month, {CORE: 20000.0}))["checks"]["parts_ok"] is True
    refused(bump(world(**low), month, {CORE: 20001.0}), f"core capital orders of 100,001 is above durable orders of 100,000 in {label(month)}")


def test_the_parts_come_last_and_are_scanned_in_their_order_and_the_oldest_month_first():
    d = bump(bump(world(), NEXT, {EXTR: 100001.0}), OLDEST, {UNF_T: 3.0})
    refused(d, f"unfilled orders are 3 million off durable unfilled orders in {label(OLDEST)}, over 1")      # an equality breaks first
    d = bump(bump(world(), NEXT, {EXTR: 100001.0}), MIDDLE, {EXTR: 100002.0})
    refused(d, f"orders excluding transport of 300,002 is above durable orders of 300,000 in {label(MIDDLE)}")


# ---------------------------------------------------------------- the figures


def test_a_flat_world_has_no_change_and_no_negative_zero_and_shares_that_need_rounding():
    r = run(world())
    assert r["full"][0] == {"key": "orders", "label": "New orders", "millions": 600000.0, "change_month_millions": 0.0, "change_month_pct": 0.0, "change_year_millions": 0.0, "change_year_pct": 0.0}
    assert [(x["key"], x["millions"], x["share_pct"]) for x in r["nondurable"]] == [("orders", 300000.0, 50.0), ("inventories", 300000.0, 37.5)]
    assert [(x["key"], x["millions"]) for x in r["durable"]] == [("orders", 300000.0), ("ex_transport", 200000.0), ("core_capital", 80000.0), ("shipments", 290000.0), ("inventories", 500000.0), ("unfilled", 1200000.0)]
    flat = [v for x in r["full"] + r["nondurable"] + r["durable"] for v in (x["change_month_millions"], x["change_month_pct"], x["change_year_millions"], x["change_year_pct"])]
    assert all(math.copysign(1.0, v) > 0 and v == 0.0 for v in flat)


def test_a_fall_to_nothing_is_a_plain_zero_and_a_change_is_kept_to_a_tenth():
    r = run(world_by(lambda k: {**LEAVES, CORE: 80000.0 - 0.01 * (k == 140)}))
    core = next(x for x in r["durable"] if x["key"] == "core_capital")
    assert core["change_month_millions"] == 0.0 and str(core["change_month_millions"]) == "0.0" and str(core["change_month_pct"]) == "0.0" and str(core["change_year_millions"]) == "0.0"
    r = run(world_by(lambda k: {**LEAVES, ORD_D: 300000.0 - 12000.0 * (k == 139)}, ahead=False))
    assert r["full"][0]["change_month_millions"] == -12000.0 and r["full"][0]["change_month_pct"] == -2.0 and r["full"][0]["change_year_millions"] == -12000.0
    r = run(world_by(lambda k: {**LEAVES, CORE: 80000.0 + 0.44 * (k == 140)}))
    core = next(x for x in r["durable"] if x["key"] == "core_capital")
    assert core["change_month_millions"] == 0.4 and core["change_year_millions"] == 0.4                  # kept to a tenth: not to a whole million and not to hundredths


def test_the_nondurable_item_follows_nondurable_orders_and_not_their_shipments():
    d = bump(bump(bump(world(), LAST, {SHP_N: 1.0}), mback(LAST, 1), {SHP_N: 0.5}), mback(LAST, 12), {SHP_N: 0.25})              # the shipments drift by up to a million, which the equality allows
    item = run(d)["nondurable"][0]
    assert (item["key"], item["millions"], item["change_month_millions"], item["change_year_millions"]) == ("orders", 300000.0, 0.0, 0.0)


def test_a_rising_trend_gives_exact_levels_changes_shares_and_the_last_six_months():
    r = run(world_by(trend))
    got = lambda items: {x["key"]: (x["millions"], x["change_month_millions"], x["change_month_pct"], x["change_year_millions"], x["change_year_pct"]) for x in items}
    assert got(r["full"]) == {"orders": (808500.0, 1500.0, 0.2, 18000.0, 2.3), "shipments": (770700.0, 1300.0, 0.2, 15600.0, 2.1), "inventories": (841700.0, 300.0, 0.0, 3600.0, 0.4), "unfilled": (1478000.0, 2000.0, 0.1, 24000.0, 1.7)}
    assert got(r["nondurable"]) == {"orders": (369500.0, 500.0, 0.1, 6000.0, 1.7), "inventories": (313900.0, 100.0, 0.0, 1200.0, 0.4)}
    assert [x["share_pct"] for x in r["nondurable"]] == [45.7, 37.3]                                      # 45.70 and 37.29: rounded, not cut
    assert got(r["durable"]) == {"orders": (440000.0, 1000.0, 0.2, 12000.0, 2.8), "ex_transport": (256000.0, 400.0, 0.2, 4800.0, 1.9), "core_capital": (94000.0, 100.0, 0.1, 1200.0, 1.3),
                                 "shipments": (402000.0, 800.0, 0.2, 9600.0, 2.4), "inventories": (528000.0, 200.0, 0.0, 2400.0, 0.5), "unfilled": (1480000.0, 2000.0, 0.1, 24000.0, 1.6)}
    assert r["recent"] == [{"month": m, "orders": o, "orders_change": 1500.0, "shipments": s} for m, o, s in (("2026-04", 801000.0, 764200.0), ("2026-05", 802500.0, 765500.0), ("2026-06", 804000.0, 766800.0),
                                                                                                           ("2026-07", 805500.0, 768100.0), ("2026-08", 807000.0, 769400.0), ("2026-09", 808500.0, 770700.0))]
    assert r["detail"] == {"months_checked": 140, "first_month": "2015-02", "last_month": "2026-09", "durable_last_month": "2026-10", "largest_sum_gap": 0.0, "largest_equal_gap": 0.0,
                           "newest_common": {"month": "2026-09", "orders": 0.0, "shipments": 0.0, "inventories": 0.0, "unfilled": 0.0}}


def test_the_durable_block_uses_the_durable_months_and_the_full_block_the_full_months_when_they_differ_and_when_they_do_not():
    ahead, same = run(world_by(trend, ahead=True)), run(world_by(trend, ahead=False))
    assert ahead["month"] == "2026-09" and ahead["durable_month"] == "2026-10" and ahead["durable_advance"] is True
    assert same["month"] == "2026-09" and same["durable_month"] == "2026-09" and same["durable_advance"] is False
    assert same["durable"][0]["millions"] == 439000.0 and same["durable"][0]["change_month_millions"] == 1000.0 and same["durable"][0]["change_year_millions"] == 12000.0 and same["durable"][0]["change_year_pct"] == 2.8
    assert same["durable"][5]["millions"] == 1478000.0 and same["durable"][5]["change_year_pct"] == 1.7
    assert ahead["full"] == same["full"]                                                                    # the full block does not move with the durable month


def test_the_month_change_and_the_year_change_each_use_their_own_month():
    r = run(world_by(lambda k: {**LEAVES, ORD_N: 300000.0 + (60000.0 if k == 139 - 12 else 0.0) + (6000.0 if k == 139 - 1 else 0.0)}))
    assert r["full"][0]["change_month_millions"] == -6000.0 and r["full"][0]["change_year_millions"] == -60000.0
    assert r["full"][0]["change_month_pct"] == -1.0 and r["full"][0]["change_year_pct"] == -9.1
    r = run(world_by(lambda k: {**LEAVES, ORD_D: 300000.0 + (30000.0 if k == 140 - 12 else 0.0) + (3000.0 if k == 140 - 1 else 0.0)}))
    assert r["durable"][0]["change_month_millions"] == -3000.0 and r["durable"][0]["change_year_millions"] == -30000.0 and r["durable"][0]["change_month_pct"] == -1.0 and r["durable"][0]["change_year_pct"] == -9.1


def test_a_release_that_is_late_is_marked_overdue_after_100_days_from_the_first_of_the_month():
    assert run(world(), LAST + timedelta(days=100))["freshness"] == "CURRENT" and run(world(), LAST + timedelta(days=100))["age_days"] == 100
    assert run(world(), LAST + timedelta(days=101))["freshness"] == "OVERDUE" and run(world(), LAST + timedelta(days=101))["age_days"] == 101
    assert run(world(), LAST)["age_days"] == 0 and run(world(), LAST)["freshness"] == "CURRENT"


def test_the_requests_go_to_the_fred_csv_address_and_carry_nothing_but_the_id_and_the_start():
    urls, data = [], world()

    async def handler(request):
        urls.append((request.url.scheme, request.url.host, request.url.path, sorted(request.url.params)))
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsFactoryOrders(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(urls) == 13 and all(u == ("https", "fred.stlouisfed.org", "/graph/fredgraph.csv", ["cosd", "id"]) for u in urls)


def test_the_note_says_what_the_figures_are_and_are_not_and_points_to_the_check_line():
    note = run(world())["note"]
    assert note.startswith("Factory orders from the Census Bureau (the M3 survey of manufacturers' shipments, inventories and orders), in millions of dollars, seasonally adjusted: what customers ordered in the month, what was shipped, what manufacturers held at the month end and what was still owed. ")
    assert ". The totals and the nondurable goods come from the full report of a month; the durable goods figures come from the advance report that comes out about a week before it, so they can run one month ahead of the rest. " in note
    assert ". Nondurable goods orders are by definition the same as their shipments, and unfilled orders are counted for durable goods only. The newest months are revised later. " in note
    assert "the ranges, the sums, the published equalities and the order of the durable parts are in the Check line" in note and note.count("the Check line") == 1
    assert note.endswith("This describes factory activity that already happened: it is not a market signal or a forecast.")


# ---------------------------------------------------------------- the messages


def test_every_failure_message_fits_in_the_110_characters_a_card_shows():
    msgs = [sum_msg(0, 1234.5, OLDEST), sum_msg(2, 1234.5, OLDEST), equal_msg("nondurable orders", "nondurable shipments", 1234.5, OLDEST), equal_msg("unfilled orders", "durable unfilled orders", 1234.5, OLDEST),
            "the full report series end in different months", "the durable goods series end in different months", "the durable goods series end in a month that is neither the full report's nor the one after it",
            "the nondurable inventories series covers different months than new orders", "the durable unfilled orders series covers different months than durable orders", "the durable goods series cover other months than the full report",
            "a factory orders date is not the 1st of a month", f"the factory orders months skip a month after {label(OLDEST)}", "the factory orders series cover 131 months, fewer than the 132 expected",
            f"nondurable inventories of 99,999,999 in {label(OLDEST)} is outside 121,000 to 735,000", f"durable unfilled orders of 99,999,999 in {label(OLDEST)} is outside 530,000 to 3,280,000",
            f"orders excluding transport of 999,999 is above durable orders of 999,999 in {label(OLDEST)}", f"core capital orders of 999,999 is above durable orders of 999,999 in {label(OLDEST)}"]
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
    c = U.UsFactoryOrders(client=make_client(world(), seen), demo=True)
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is True and r["reason"] == "Demo mode: the real US factory orders figures are not shown because made-up values would look real." and seen == []
    assert "full" not in r and r["as_of"] == NOW.isoformat()


def test_one_request_per_series_each_with_its_id_and_the_start_date_and_six_at_a_time():
    seen, stats = [], {"now": 0, "peak": 0}
    c = U.UsFactoryOrders(client=make_client(world(), seen, delay=0.01, stats=stats))
    r = arun(c.overview(NOW))
    assert r["available"] is True and r["demo"] is False and r["date"] == "2026-09-01" and r["age_days"] == 85
    assert sorted(x["id"] for x in seen) == sorted(IDS) and all(x == {"id": x["id"], "cosd": "2015-01-01"} for x in seen)
    assert stats["peak"] == 6


def test_the_real_record_through_the_class_gives_the_same_answer_as_the_summary():
    r = arun(U.UsFactoryOrders(client=make_client(real())).overview(NOW))
    assert r["available"] is True and r["full"][0]["millions"] == 677247.0 and r["detail"]["months_checked"] == 141 and r["as_of"] == NOW.isoformat()


def test_a_good_answer_is_kept_for_six_hours_and_asked_again_after_that(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(U, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    seen = []
    c = U.UsFactoryOrders(client=make_client(world(), seen))
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
    c = U.UsFactoryOrders(client=make_client(world(), seen, status=500))
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is False and r["reason"].startswith("US factory orders could not be read right now (") and "full" not in r
    n = len(seen)
    clock[0] += 119.0
    arun(c.overview(NOW))
    assert len(seen) == n
    clock[0] += 1.0
    arun(c.overview(NOW))
    assert len(seen) > n


def test_a_figure_that_fails_a_check_is_named_in_words_with_its_month_in_words():
    d = world()
    d[ORD_T][LAST] = 9000000.0
    r = arun(U.UsFactoryOrders(client=make_client(d)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US factory orders could not be read right now (the data failed a check: new orders of 9,000,000 in September 2026 is outside 180,000 to 1,355,000)" and "full" not in r


def test_a_client_it_makes_itself_is_closed_and_one_it_is_given_is_not(monkeypatch):
    made, instances = [], []

    class Own(REAL_CLIENT):
        def __init__(self, **kw):
            made.append(kw)
            instances.append(self)
            super().__init__(transport=transport_for(world()))

    monkeypatch.setattr(U.httpx, "AsyncClient", Own)
    c = U.UsFactoryOrders()
    assert arun(c.overview(NOW))["available"] is True and made == [{"timeout": 25}] and instances[0].is_closed is True
    given = make_client(world())
    arun(U.UsFactoryOrders(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_default_clock_is_utc_and_stamps_the_answer():
    r = arun(U.UsFactoryOrders(client=make_client(world())).overview())
    stamp = datetime.fromisoformat(r["as_of"])
    assert stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0) and abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


def test_each_request_goes_with_the_clients_own_user_agent_and_nothing_added():
    seen, data = [], world()

    async def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsFactoryOrders(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(seen) == 13 and all(ua.startswith("python-httpx/") for ua in seen)


def test_a_dropped_connection_a_timeout_and_a_missing_key_read_plainly(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("")

    def slow(request):
        raise httpx.ReadTimeout("")

    for fail, words in ((boom, "the connection could not be made"), (slow, "the request timed out")):
        r = arun(U.UsFactoryOrders(client=REAL_CLIENT(transport=httpx.MockTransport(fail))).overview(NOW))
        assert r["available"] is False and r["reason"] == f"US factory orders could not be read right now ({words})"

    def no_key(data, today):
        raise KeyError("AMTMNO")

    monkeypatch.setattr(U, "summarize", no_key)
    r = arun(U.UsFactoryOrders(client=make_client(world())).overview(NOW))
    assert r["available"] is False and r["reason"] == "US factory orders could not be read right now (the answer was not in the expected shape)"


def test_any_answer_but_200_is_refused_with_its_status_in_words():
    r = arun(U.UsFactoryOrders(client=make_client(world(), status=500)).overview(NOW))
    assert r["reason"] == "US factory orders could not be read right now (the server had an error, HTTP 500)"
    r = arun(U.UsFactoryOrders(client=make_client(world(), status=204)).overview(NOW))
    assert r["reason"] == "US factory orders could not be read right now (the server answered HTTP 204)"


def test_the_clock_decides_the_age_not_the_computer_date():
    c = U.UsFactoryOrders(client=make_client(world()))
    r = arun(c.overview(datetime(2026, 12, 11, 1, tzinfo=timezone.utc)))
    assert r["age_days"] == 101 and r["freshness"] == "OVERDUE"
