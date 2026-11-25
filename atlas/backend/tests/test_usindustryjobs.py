"""US jobs by industry (BLS Current Employment Statistics via FRED, 17 monthly series): the real saved record, the limits and tolerances as literals, one check at a time, the figures of the summary and the class."""
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

import atlas_api.usindustryjobs as U

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usindustryjobs.json").read_text(encoding="utf-8"))
TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
LAST = date(2026, 10, 1)

TOTAL, PRIV, GOV, GOOD, SERV = "PAYEMS", "USPRIV", "USGOVT", "USGOOD", "CES0800000001"
MINE, CONS, MAN, DUR, NDUR = "USMINE", "USCONS", "MANEMP", "DMANEMP", "NDMANEMP"
TPU, INFO, FIN, PBS, EDH, LAH, OTH = "USTPU", "USINFO", "USFIRE", "USPBS", "USEHS", "USLAH", "USSERV"
IDS = [TOTAL, PRIV, GOV, GOOD, SERV, MINE, CONS, MAN, DUR, NDUR, TPU, INFO, FIN, PBS, EDH, LAH, OTH]
SEVEN = (TPU, INFO, FIN, PBS, EDH, LAH, OTH)
ELEVEN = (MINE, CONS, MAN) + SEVEN + (GOV,)
NAME = {TOTAL: "total payrolls", PRIV: "private payrolls", GOV: "government payrolls", GOOD: "goods-producing payrolls", SERV: "private service payrolls", MINE: "mining and logging payrolls",
        CONS: "construction payrolls", MAN: "manufacturing payrolls", DUR: "durable manufacturing payrolls", NDUR: "nondurable manufacturing payrolls", TPU: "trade, transport and utilities payrolls",
        INFO: "information payrolls", FIN: "financial activities payrolls", PBS: "professional and business payrolls", EDH: "education and health payrolls", LAH: "leisure and hospitality payrolls",
        OTH: "other services payrolls"}
LIMITS = {TOTAL: (15000.0, 320000.0), PRIV: (13000.0, 275000.0), GOV: (2000.0, 48000.0), GOOD: (5500.0, 51000.0), SERV: (7400.0, 230000.0), MINE: (270.0, 2500.0), CONS: (520.0, 16800.0),
          MAN: (4500.0, 39200.0), DUR: (2200.0, 24700.0), NDUR: (2100.0, 14500.0), TPU: (3300.0, 57800.0), INFO: (550.0, 7500.0), FIN: (680.0, 18500.0), PBS: (970.0, 45800.0),
          EDH: (690.0, 56200.0), LAH: (930.0, 34100.0), OTH: (270.0, 12100.0)}
SUMS = [(TOTAL, (PRIV, GOV), 1.5, "private plus government"), (PRIV, (GOOD, SERV), 1.5, "goods-producing plus private service"), (GOOD, (MINE, CONS, MAN), 2.0, "mining, construction and manufacturing"),
        (MAN, (DUR, NDUR), 1.5, "durable plus nondurable manufacturing"), (SERV, SEVEN, 4.0, "the seven private service industries"), (TOTAL, ELEVEN, 6.0, "the eleven industries")]
LEAVES = {DUR: 8000.0, NDUR: 4500.0, MINE: 600.0, CONS: 8000.0, TPU: 28000.0, INFO: 3000.0, FIN: 9000.0, PBS: 22000.0, EDH: 28000.0, LAH: 16000.0, OTH: 6000.0, GOV: 23000.0}
STEP = {DUR: 10.0, NDUR: 5.0, MINE: 1.0, CONS: 20.0, TPU: 30.0, INFO: 2.0, FIN: 10.0, PBS: 20.0, EDH: 60.0, LAH: 25.0, OTH: 5.0, GOV: 15.0}


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
    v[MAN] = l[DUR] + l[NDUR]
    v[GOOD] = l[MINE] + l[CONS] + v[MAN]
    v[SERV] = sum(l[s] for s in SEVEN)
    v[PRIV] = v[GOOD] + v[SERV]
    v[TOTAL] = v[PRIV] + l[GOV]
    return v


def world(n=140, last=LAST, **changed):
    one = build({**LEAVES, **changed})
    return {sid: {mback(last, i): v for i in range(n - 1, -1, -1)} for sid, v in one.items()}


def world_by(fn, n=142, last=LAST):
    data = {sid: {} for sid in IDS}
    for i in range(n - 1, -1, -1):
        for sid, v in build(fn(n - 1 - i)).items():
            data[sid][mback(last, i)] = v
    return data


def trend(k):                                                                      # every step exact in binary and in decimal
    return {sid: LEAVES[sid] + STEP[sid] * k for sid in LEAVES}


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


def chain(data, month, e0=0.0, e1=0.0, e2=0.0, e3=0.0, e4=0.0):
    """Make the first five sums off by exactly e0 .. e4 in one month and keep every other relation true: each whole is rebuilt from its parts plus its own gap, from manufacturing up to the total. The eleven-industries sum is then off by e0 + e1 + e2 + e4."""
    d = {sid: dict(s) for sid, s in data.items()}
    v = lambda sid: d[sid][month]
    d[MAN][month] = v(DUR) + v(NDUR) + e3
    d[GOOD][month] = v(MINE) + v(CONS) + v(MAN) + e2
    d[SERV][month] = sum(v(s) for s in SEVEN) + e4
    d[PRIV][month] = v(GOOD) + v(SERV) + e1
    d[TOTAL][month] = v(PRIV) + v(GOV) + e0
    return d


OLDEST, MIDDLE = mback(LAST, 139), mback(LAST, 70)


def sum_msg(i, gap, month):
    return f"{NAME[SUMS[i][0]]} are {num(gap)} thousand off {SUMS[i][3]} in {label(month)}, over {SUMS[i][2]:g}"


# ---------------------------------------------------------------- the real record

REAL_ITEMS = {                       # (thousands, change on the month, % , change on the year, %, share %), read from the saved CSV text and added up by hand
    "total": (159293.0, 165.0, 0.1, 885.0, 0.6, None), "goods": (21653.0, 15.0, 0.1, 201.0, 0.9, 13.6), "services": (114308.0, 144.0, 0.1, 742.0, 0.7, 71.8), "government": (23332.0, 6.0, 0.0, -58.0, -0.2, 14.6),
    "mining": (605.0, -1.0, -0.2, -1.0, -0.2, 0.4), "construction": (8367.0, -3.0, 0.0, 124.0, 1.5, 5.3), "manufacturing": (12681.0, 19.0, 0.2, 78.0, 0.6, 8.0),
    "trade": (28818.0, 22.0, 0.1, 104.0, 0.4, 18.1), "information": (2734.0, -1.0, 0.0, -119.0, -4.2, 1.7), "financial": (9085.0, 7.0, 0.1, -99.0, -1.1, 5.7),
    "professional": (22604.0, 70.0, 0.3, 269.0, 1.2, 14.2), "education_health": (28058.0, 53.0, 0.2, 525.0, 1.9, 17.6), "leisure": (16964.0, -13.0, -0.1, 16.0, 0.1, 10.6),
    "other": (6045.0, 6.0, 0.1, 46.0, 0.8, 3.8), "durable": (7928.0, 25.0, 0.3, 123.0, 1.6, 62.5), "nondurable": (4753.0, -6.0, -0.1, -45.0, -0.9, 37.5)}


def items_of(r):
    return [r["total"]] + r["groups"] + r["industries"] + r["manufacturing"]


def got_of(r):
    return {x["key"]: (x["thousands"], x["change_month"], x["change_month_pct"], x["change_year"], x["change_year_pct"], x.get("share_pct")) for x in items_of(r)}


def test_the_whole_real_record_adds_up_in_every_month_and_the_checks_pass():
    data = real()
    months = sorted(data[TOTAL])
    assert len(months) == 142 and months[0] == date(2015, 1, 1) and months[-1] == LAST and all(set(data[s]) == set(months) for s in IDS)
    for whole, parts, _, what in SUMS:
        assert {data[whole][d] - sum(data[p][d] for p in parts) for d in months} == {0.0}, what                 # whole thousands that add up exactly in every month of all six sums
    r = run(data)
    assert r["available"] is True and r["date"] == "2026-10-01" and r["month"] == "2026-10" and r["age_days"] == 55 and r["freshness"] == "CURRENT"
    assert r["detail"] == {"months_checked": 142, "first_month": "2015-01", "last_month": "2026-10", "largest_sum_gap": 0.0}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "sums_ok": True}
    assert r["source"] == U.SOURCE and r["url"] == "https://fred.stlouisfed.org/series/PAYEMS"


def test_the_figures_of_the_newest_real_months():
    r = run(real())
    got = got_of(r)
    assert set(got) == set(REAL_ITEMS) and len(items_of(r)) == 17                 # government is in the groups and in the industries
    for key, want in REAL_ITEMS.items():
        assert got[key] == want, key
    assert [(x["key"], x["label"]) for x in [r["total"]]] == [("total", "Total nonfarm payrolls")]
    assert [(x["key"], x["label"]) for x in r["groups"]] == [("goods", "Goods-producing"), ("services", "Private service-providing"), ("government", "Government")]
    assert [(x["key"], x["label"]) for x in r["industries"]] == [("mining", "Mining and logging"), ("construction", "Construction"), ("manufacturing", "Manufacturing"), ("trade", "Trade, transportation and utilities"),
                                                                ("information", "Information"), ("financial", "Financial activities"), ("professional", "Professional and business services"),
                                                                ("education_health", "Education and health services"), ("leisure", "Leisure and hospitality"), ("other", "Other services"), ("government", "Government")]
    assert [(x["key"], x["label"]) for x in r["manufacturing"]] == [("durable", "Durable goods manufacturing"), ("nondurable", "Nondurable goods manufacturing")]
    assert "share_pct" not in r["total"] and all("share_pct" in x for x in r["groups"] + r["industries"] + r["manufacturing"])
    assert r["recent"] == [{"month": "2026-05", "thousands": 158861.0, "change": 63.0}, {"month": "2026-06", "thousands": 158892.0, "change": 31.0}, {"month": "2026-07", "thousands": 158882.0, "change": -10.0},
                           {"month": "2026-08", "thousands": 159068.0, "change": 186.0}, {"month": "2026-09", "thousands": 159128.0, "change": 60.0}, {"month": "2026-10", "thousands": 159293.0, "change": 165.0}]


def test_a_fall_or_rise_that_rounds_to_nothing_is_a_plain_zero_in_the_real_record_too():
    r = run(real())
    for x in r["industries"]:
        if x["key"] in ("construction", "information"):                    # real falls of 3 and 1 thousand on 8,370 and 2,735: -0.04 and -0.04 percent
            assert x["change_month_pct"] == 0.0 and math.copysign(1.0, x["change_month_pct"]) > 0


def test_the_limits_are_the_literals_about_half_the_lowest_and_twice_the_highest_value_of_the_whole_record():
    assert U.LIMITS == LIMITS and U.NAMES == NAME and U.SERIES == IDS
    data = real()
    for sid, (lo, hi) in LIMITS.items():                                     # the saved record starts in 2015: it sits well inside the limits taken from 1939
        low, high = min(data[sid].values()), max(data[sid].values())
        assert lo < low < hi and lo < high < hi, sid


def test_the_constants_the_address_the_source_and_the_ids_are_the_literals_written_here():
    assert U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and U.PAGE == "https://fred.stlouisfed.org/series/PAYEMS"
    assert U.SOURCE == "U.S. Bureau of Labor Statistics, Current Employment Statistics (the Employment Situation payrolls by industry), via FRED, St. Louis Fed (official, free public data)"
    assert (U.TOTAL, U.PRIV, U.GOV, U.GOOD, U.SERV) == (TOTAL, PRIV, GOV, GOOD, SERV) and (U.MINE, U.CONS, U.MAN, U.DUR, U.NDUR) == (MINE, CONS, MAN, DUR, NDUR)
    assert (U.TPU, U.INFO, U.FIN, U.PBS, U.EDH, U.LAH, U.OTH) == (TPU, INFO, FIN, PBS, EDH, LAH, OTH)


def test_the_relations_and_tolerances_are_written_out_here_and_the_record_starts_in_2015():
    assert U.SUMS == tuple(SUMS)                                              # half a thousand for each of the figures: 1.5, 1.5, 2, 1.5, 4 and 6
    assert [s[2] for s in U.SUMS] == [0.5 * (1 + len(parts)) for _, parts, _, _ in SUMS]
    assert U.START == "2015-01-01" and U.MIN_MONTHS == 132 and U.RECENT_MONTHS == 6 and U.OVERDUE_AFTER_DAYS == 70 and U.TTL == 6 * 3600.0 and U.FAIL_TTL == 120.0 and U.CONCURRENCY == 6
    assert [(k, l, s) for k, l, s in U.INDUSTRIES] == [("mining", "Mining and logging", MINE), ("construction", "Construction", CONS), ("manufacturing", "Manufacturing", MAN), ("trade", "Trade, transportation and utilities", TPU),
                                                      ("information", "Information", INFO), ("financial", "Financial activities", FIN), ("professional", "Professional and business services", PBS),
                                                      ("education_health", "Education and health services", EDH), ("leisure", "Leisure and hospitality", LAH), ("other", "Other services", OTH), ("government", "Government", GOV)]
    assert [(k, l, s) for k, l, s in U.GROUPS] == [("goods", "Goods-producing", GOOD), ("services", "Private service-providing", SERV), ("government", "Government", GOV)]


# ---------------------------------------------------------------- the months


@pytest.mark.parametrize("sid", IDS)
def test_a_series_that_ends_a_month_early_is_refused_first_whichever_series_it_is(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the payroll series end in different months")


@pytest.mark.parametrize("sid", IDS)
def test_a_series_that_runs_a_month_longer_than_the_others_is_refused_the_same_way(sid):
    d = world()
    d[sid][mback(LAST, -1)] = build(LEAVES)[sid]
    refused(d, "the payroll series end in different months")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_that_covers_other_months_is_named(sid):
    d = world()
    del d[sid][MIDDLE]
    refused(d, f"the {NAME[sid]} series covers different months than total payrolls")


def test_total_payrolls_is_the_base_and_the_first_series_that_differs_in_the_series_order_is_named():
    d = world()
    del d[TOTAL][MIDDLE]
    refused(d, "the private payrolls series covers different months than total payrolls")
    d = world()
    del d[MINE][MIDDLE]
    del d[GOV][MIDDLE]
    refused(d, "the government payrolls series covers different months than total payrolls")
    d = world()
    d[GOOD][date(2010, 1, 1)] = 1.0                                          # an extra month the others do not have: the same kind of difference
    refused(d, "the goods-producing payrolls series covers different months than total payrolls")


@pytest.mark.parametrize("days", [1, 14])
@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
def test_a_date_that_is_not_the_first_of_a_month_is_refused_in_any_month(month, days):
    d = {sid: {(k + timedelta(days=days) if k == month else k): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a payroll date is not the 1st of a month")


def test_the_ends_come_first_then_the_covers_then_the_dates_then_the_skips_then_the_count():
    d = world(n=131)
    del d[GOV][mback(LAST, 50)]
    del d[MINE][LAST]
    refused(d, "the payroll series end in different months")
    d = world(n=131)
    del d[GOV][mback(LAST, 50)]
    refused(d, "the government payrolls series covers different months than total payrolls")
    d = {sid: {k + timedelta(days=1): v for k, v in s.items() if k != MIDDLE} for sid, s in world(n=131).items()}
    refused(d, "a payroll date is not the 1st of a month")
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world(n=131).items()}
    refused(d, f"the payroll months skip a month after {label(mback(MIDDLE, 1))}")


def test_a_skipped_month_is_named_by_the_month_before_it():
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    refused(d, f"the payroll months skip a month after {label(mback(MIDDLE, 1))}")
    d = {sid: {k: v for k, v in s.items() if k != LAST and k != mback(LAST, 1)} for sid, s in world().items()}
    assert run(d)["month"] == "2026-08" and run(d)["detail"]["months_checked"] == 138              # the newest months missing in every series is no skip: the record just ends earlier
    d = {sid: {k: v for k, v in s.items() if k != mback(LAST, 140)} for sid, s in world(n=141).items()}
    assert run(d)["detail"]["months_checked"] == 140 and run(d)["detail"]["first_month"] == "2015-03"        # nor is the oldest month


def test_fewer_than_132_months_are_refused_and_132_pass():
    refused(world(n=131), "the payroll series cover 131 months, fewer than the 132 expected")
    assert run(world(n=132))["detail"]["months_checked"] == 132
    assert run(world(n=133))["detail"]["months_checked"] == 133


def test_every_months_check_comes_before_the_ranges():
    d = {sid: {k + timedelta(days=1): v for k, v in s.items()} for sid, s in world().items()}
    d[TOTAL][OLDEST + timedelta(days=1)] = 99999999.0
    refused(d, "a payroll date is not the 1st of a month")
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    d[TOTAL][OLDEST] = 99999999.0
    refused(d, f"the payroll months skip a month after {label(mback(MIDDLE, 1))}")
    d = world(n=131)
    d[TOTAL][mback(LAST, 130)] = 99999999.0
    refused(d, "the payroll series cover 131 months, fewer than the 132 expected")
    d = world()
    d[TOTAL][OLDEST] = 99999999.0
    del d[PRIV][MIDDLE]
    refused(d, "the private payrolls series covers different months than total payrolls")
    d = world()
    d[TOTAL][OLDEST] = 99999999.0
    del d[MINE][LAST]
    refused(d, "the payroll series end in different months")


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
        with pytest.raises(ValueError, match=f"^{re.escape(f'{NAME[sid]} of {num(v)} in 2026-10 is outside {num(lo)} to {num(hi)}')}$"):
            U._check_ranges(one_month(sid, v), [LAST])


@pytest.mark.parametrize("sid", IDS)
def test_the_oldest_and_the_newest_month_of_each_series_are_both_range_checked(sid):
    lo, hi = LIMITS[sid]
    for month in (OLDEST, LAST):
        for v in (lo - 1.0, hi + 1.0):
            d = world()
            d[sid][month] = v
            refused(d, f"{NAME[sid]} of {num(v)} in {label(month)} is outside {num(lo)} to {num(hi)}")


def test_the_ranges_come_before_the_sums():
    refused(bump(world(), LAST, {TOTAL: 900000.0}), "total payrolls of 1,056,100 in 2026-10 is outside 15,000 to 320,000")
    refused(bump(world(), MIDDLE, {MINE: 5000.0}), f"mining and logging payrolls of 5,600 in {label(MIDDLE)} is outside 270 to 2,500")
    refused(bump(world(), OLDEST, {INFO: -3000.0}), f"information payrolls of 0 in {label(OLDEST)} is outside 550 to 7,500")


def test_a_message_names_the_first_wrong_series_in_the_series_order_and_the_oldest_month():
    d = world()
    d[GOV][LAST] = 99999999.0
    d[PRIV][MIDDLE] = 99999999.0
    refused(d, f"private payrolls of 99,999,999 in {label(MIDDLE)} is outside 13,000 to 275,000")
    d = world()
    d[LAH][LAST] = 99999999.0
    d[LAH][OLDEST] = 99999999.0
    refused(d, f"leisure and hospitality payrolls of 99,999,999 in {label(OLDEST)} is outside 930 to 34,100")
    d = world()
    d[OTH][OLDEST] = 99999999.0
    d[NDUR][LAST] = 99999999.0
    refused(d, f"nondurable manufacturing payrolls of 99,999,999 in {label(LAST)} is outside 2,100 to 14,500")


# ---------------------------------------------------------------- the six sums


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("i", range(5))
def test_each_of_the_first_five_sums_holds_at_its_tolerance_and_is_refused_just_beyond(i, sign, month):
    tol = SUMS[i][2]
    assert run(chain(world(), month, **{f"e{i}": tol * sign}))["detail"]["largest_sum_gap"] == tol
    refused(chain(world(), month, **{f"e{i}": (tol + 0.1) * sign}), sum_msg(i, tol + 0.1, month))


@pytest.mark.parametrize("sid", IDS)
def test_each_series_takes_part_in_its_sums_and_the_first_sum_it_breaks_in_the_scan_order_is_named(sid):
    first = {TOTAL: 0, PRIV: 0, GOV: 0, GOOD: 1, SERV: 1, MINE: 2, CONS: 2, MAN: 2, DUR: 3, NDUR: 3, **{s: 4 for s in SEVEN}}[sid]
    refused(bump(world(), LAST, {sid: 5.0}), sum_msg(first, 5, LAST))
    refused(bump(world(), LAST, {sid: -5.0}), sum_msg(first, 5, LAST))


def test_the_eleven_industries_sum_holds_at_six_thousand_off_and_is_refused_just_beyond_whichever_way_the_other_gaps_point():
    month = MIDDLE
    ok = run(chain(world(), month, e0=1.5, e1=1.5, e2=2.0, e4=1.0))
    assert ok["detail"]["largest_sum_gap"] == 6.0
    assert run(chain(world(), month, e0=-1.5, e1=-1.5, e2=-2.0, e4=-1.0))["detail"]["largest_sum_gap"] == 6.0
    refused(chain(world(), month, e0=1.5, e1=1.5, e2=2.0, e4=1.5), sum_msg(5, 6.5, month))
    refused(chain(world(), month, e0=-1.5, e1=-1.5, e2=-2.0, e4=-1.5), sum_msg(5, 6.5, month))
    refused(chain(world(), month, e0=1.5, e1=1.5, e2=2.0, e4=4.0), sum_msg(5, 9, month))
    assert run(chain(world(), month, e0=1.5, e1=-1.5, e2=2.0, e4=-2.0))["detail"]["largest_sum_gap"] == 2.0           # gaps that point opposite ways cancel in the eleven
    assert run(chain(world(), month, e3=1.5))["detail"]["largest_sum_gap"] == 1.5                                    # the manufacturing split is inside the eleven: no gap there


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
def test_the_eleven_industries_sum_is_checked_in_every_month_including_the_oldest_and_the_newest(month):
    refused(chain(world(), month, e0=1.5, e1=1.5, e2=2.0, e4=1.5), sum_msg(5, 6.5, month))


def test_the_sums_are_scanned_one_after_the_other_and_the_oldest_month_first():
    d = chain(chain(world(), OLDEST, e4=5.0), LAST, e0=3.0)
    refused(d, sum_msg(0, 3, LAST))                                          # the fifth sum breaks in the oldest month, the first only in the newest: the first sum is scanned first
    d = chain(chain(world(), OLDEST, e3=3.0), LAST, e2=4.0)
    refused(d, sum_msg(2, 4, LAST))
    d = chain(chain(world(), LAST, e0=4.0), MIDDLE, e0=5.0)
    refused(d, sum_msg(0, 5, MIDDLE))                                        # inside a sum the oldest month comes first
    d = chain(chain(world(), OLDEST, e4=5.0), MIDDLE, e1=4.0)
    refused(d, sum_msg(1, 4, MIDDLE))


def test_the_largest_sum_gap_is_kept_over_all_sums_and_all_months_to_four_decimals():
    assert run(world())["detail"]["largest_sum_gap"] == 0.0
    assert run(chain(world(), MIDDLE, e0=1.0))["detail"]["largest_sum_gap"] == 1.0
    assert run(chain(chain(world(), MIDDLE, e0=1.0), LAST, e1=1.5))["detail"]["largest_sum_gap"] == 1.5
    assert run(chain(chain(world(), OLDEST, e0=0.5), LAST, e4=0.25))["detail"]["largest_sum_gap"] == 0.5
    assert run(chain(world(), LAST, e0=0.00004))["detail"]["largest_sum_gap"] == 0.0
    assert run(chain(world(), LAST, e0=0.0001))["detail"]["largest_sum_gap"] == 0.0001


# ---------------------------------------------------------------- the figures


def test_a_flat_world_has_no_change_and_no_negative_zero_and_shares_that_need_rounding():
    r = run(world())
    assert all(x["change_month"] == 0.0 and x["change_year"] == 0.0 and x["change_month_pct"] == 0.0 and x["change_year_pct"] == 0.0 for x in items_of(r))
    assert all(math.copysign(1.0, x[k]) > 0 for x in items_of(r) for k in ("change_month", "change_month_pct", "change_year", "change_year_pct"))
    assert r["total"]["thousands"] == 156100.0
    assert {x["key"]: x["share_pct"] for x in r["groups"] + r["industries"] + r["manufacturing"]} == {
        "goods": 13.5, "services": 71.7, "government": 14.7, "mining": 0.4, "construction": 5.1, "manufacturing": 8.0, "trade": 17.9, "information": 1.9, "financial": 5.8, "professional": 14.1,
        "education_health": 17.9, "leisure": 10.2, "other": 3.8, "durable": 64.0, "nondurable": 36.0}


def test_a_fall_that_rounds_to_nothing_is_a_plain_zero_and_a_change_is_kept_to_a_tenth():
    def fn(k):
        return {**LEAVES, GOV: LEAVES[GOV] + (0.04 if k == 140 else 0.0)}
    r = run(world_by(fn))
    assert r["total"]["change_month"] == 0.0 and math.copysign(1.0, r["total"]["change_month"]) > 0 and r["industries"][-1]["change_month"] == 0.0
    assert math.copysign(1.0, r["industries"][-1]["change_month"]) > 0 and math.copysign(1.0, r["industries"][-1]["change_month_pct"]) > 0
    def fn2(k):
        return {**LEAVES, GOV: LEAVES[GOV] + (0.26 if k == 140 else 0.0)}
    r = run(world_by(fn2))
    assert r["industries"][-1]["change_month"] == -0.3 and r["total"]["change_month"] == -0.3


def test_a_rising_trend_gives_exact_levels_changes_shares_and_the_last_six_months():
    r = run(world_by(trend))
    want = {"total": (184723.0, 203.0, 0.1, 2436.0, 1.3, None), "goods": (26176.0, 36.0, 0.1, 432.0, 1.7, 14.2), "services": (133432.0, 152.0, 0.1, 1824.0, 1.4, 72.2),
            "government": (25115.0, 15.0, 0.1, 180.0, 0.7, 13.6), "mining": (741.0, 1.0, 0.1, 12.0, 1.6, 0.4), "construction": (10820.0, 20.0, 0.2, 240.0, 2.3, 5.9),
            "manufacturing": (14615.0, 15.0, 0.1, 180.0, 1.2, 7.9), "trade": (32230.0, 30.0, 0.1, 360.0, 1.1, 17.4), "information": (3282.0, 2.0, 0.1, 24.0, 0.7, 1.8),
            "financial": (10410.0, 10.0, 0.1, 120.0, 1.2, 5.6), "professional": (24820.0, 20.0, 0.1, 240.0, 1.0, 13.4), "education_health": (36460.0, 60.0, 0.2, 720.0, 2.0, 19.7),
            "leisure": (19525.0, 25.0, 0.1, 300.0, 1.6, 10.6), "other": (6705.0, 5.0, 0.1, 60.0, 0.9, 3.6), "durable": (9410.0, 10.0, 0.1, 120.0, 1.3, 64.4), "nondurable": (5205.0, 5.0, 0.1, 60.0, 1.2, 35.6)}
    assert got_of(r) == want
    assert r["recent"] == [{"month": "2026-05", "thousands": 183708.0, "change": 203.0}, {"month": "2026-06", "thousands": 183911.0, "change": 203.0}, {"month": "2026-07", "thousands": 184114.0, "change": 203.0},
                           {"month": "2026-08", "thousands": 184317.0, "change": 203.0}, {"month": "2026-09", "thousands": 184520.0, "change": 203.0}, {"month": "2026-10", "thousands": 184723.0, "change": 203.0}]
    assert r["detail"] == {"months_checked": 142, "first_month": "2015-01", "last_month": "2026-10", "largest_sum_gap": 0.0}


def test_the_month_change_and_the_year_change_each_use_their_own_month():
    def fn(k):                        # n = 142: the newest is k = 141, a month earlier 140, a year earlier 129; the neighbours of each get their own value
        bumps = {140: 1000.0, 139: 2000.0, 129: 5000.0, 130: 7000.0, 128: 9000.0}
        return {**LEAVES, GOV: LEAVES[GOV] + bumps.get(k, 0.0)}
    r = run(world_by(fn))
    gov = r["industries"][-1]
    assert (gov["thousands"], gov["change_month"], gov["change_year"]) == (23000.0, -1000.0, -5000.0)
    assert (r["total"]["change_month"], r["total"]["change_year"]) == (-1000.0, -5000.0)
    assert gov["change_month_pct"] == -4.2 and gov["change_year_pct"] == -17.9
    assert [x["change"] for x in r["recent"]] == [0.0, 0.0, 0.0, 2000.0, -1000.0, -1000.0]


def test_the_recent_months_are_the_last_six_and_each_change_uses_its_own_month_before():
    def fn(k):
        return {**LEAVES, GOV: LEAVES[GOV] + {141: 0.0, 140: 100.0, 139: 300.0, 138: 600.0, 137: 1000.0, 136: 1500.0, 135: 2100.0, 134: 2800.0}.get(k, 0.0)}
    r = run(world_by(fn))
    assert [(x["month"], x["change"]) for x in r["recent"]] == [("2026-05", -600.0), ("2026-06", -500.0), ("2026-07", -400.0), ("2026-08", -300.0), ("2026-09", -200.0), ("2026-10", -100.0)]
    assert [x["thousands"] for x in r["recent"]] == [157600.0, 157100.0, 156700.0, 156400.0, 156200.0, 156100.0]


def test_a_release_that_is_late_is_marked_overdue_after_70_days_from_the_first_of_the_month():
    assert run(world(), LAST + timedelta(days=70))["freshness"] == "CURRENT" and run(world(), LAST + timedelta(days=70))["age_days"] == 70
    assert run(world(), LAST + timedelta(days=71))["freshness"] == "OVERDUE" and run(world(), LAST + timedelta(days=71))["age_days"] == 71
    assert run(world(), LAST)["age_days"] == 0 and run(world(), LAST)["freshness"] == "CURRENT"


def test_the_note_says_what_the_figures_are_and_are_not_and_points_to_the_check_line():
    note = run(world())["note"]
    assert note.startswith("Payrolls by industry from the Bureau of Labor Statistics (the Current Employment Statistics survey of employers, the payroll half of the monthly Employment Situation), in thousands of jobs, seasonally adjusted, for the pay period that includes the 12th. ")
    assert ". A job is a position on a payroll, not a person: someone with two jobs counts twice. Only non-farm employers are counted, so farm work and the self-employed are not in it. The newest months are revised twice and again every year. " in note
    assert "Plain checks: the units are the ones assumed and no month is missing; the ranges and the six sums are in the Check line. " in note and note.count("the Check line") == 1
    assert note.endswith("This describes employment that already happened: it is not a market signal or a forecast.") and len(note) <= 1100


# ---------------------------------------------------------------- the messages


def test_every_failure_message_fits_in_the_110_characters_a_card_shows():
    worst = [f"{NAME[w]} are 123,456.7 thousand off {what} in 2015-01, over {tol:g}" for w, _, tol, what in SUMS]
    msgs = worst + ["the payroll series end in different months", "the trade, transport and utilities payrolls series covers different months than total payrolls", "a payroll date is not the 1st of a month",
                    "the payroll months skip a month after 2015-01", "the payroll series cover 131 months, fewer than the 132 expected",
                    "trade, transport and utilities payrolls of 99,999,999 in 2015-01 is outside 3,300 to 57,800", "nondurable manufacturing payrolls of 99,999,999 in 2015-01 is outside 2,100 to 14,500"]
    assert max(len(m) for m in msgs) <= 110, [(len(m), m) for m in msgs if len(m) > 110]
    assert len(sum_msg(2, 3, LAST)) < 110


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


def test_the_requests_go_to_the_fred_csv_address_and_carry_nothing_but_the_id_and_the_start():
    urls, data = [], world()

    async def handler(request):
        urls.append((request.url.scheme, request.url.host, request.url.path, sorted(request.url.params)))
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsIndustryJobs(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(urls) == 17 and all(u == ("https", "fred.stlouisfed.org", "/graph/fredgraph.csv", ["cosd", "id"]) for u in urls)


def test_demo_mode_shows_nothing_and_says_why_without_a_request():
    seen = []
    c = U.UsIndustryJobs(client=make_client(world(), seen), demo=True)
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is True and r["reason"] == "Demo mode: the real US jobs by industry figures are not shown because made-up values would look real." and seen == []
    assert "total" not in r and r["as_of"] == NOW.isoformat()


def test_one_request_per_series_each_with_its_id_and_the_start_date_and_six_at_a_time():
    seen, stats = [], {"now": 0, "peak": 0}
    c = U.UsIndustryJobs(client=make_client(world(), seen, delay=0.01, stats=stats))
    r = arun(c.overview(NOW))
    assert r["available"] is True and r["demo"] is False and r["date"] == "2026-10-01" and r["age_days"] == 55
    assert sorted(x["id"] for x in seen) == sorted(IDS) and all(x == {"id": x["id"], "cosd": "2015-01-01"} for x in seen)
    assert stats["peak"] == 6


def test_the_real_record_through_the_class_gives_the_same_answer_as_the_summary():
    r = arun(U.UsIndustryJobs(client=make_client(real())).overview(NOW))
    assert r["available"] is True and r["total"]["thousands"] == 159293.0 and r["detail"]["months_checked"] == 142 and r["as_of"] == NOW.isoformat()
    assert got_of(r) == REAL_ITEMS


def test_a_good_answer_is_kept_for_six_hours_and_asked_again_after_that(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(U, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    seen = []
    c = U.UsIndustryJobs(client=make_client(world(), seen))
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
    c = U.UsIndustryJobs(client=make_client(world(), seen, status=500))
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is False and r["reason"].startswith("US jobs by industry could not be read right now (") and "total" not in r
    n = len(seen)
    clock[0] += 119.0
    arun(c.overview(NOW))
    assert len(seen) == n
    clock[0] += 1.0
    arun(c.overview(NOW))
    assert len(seen) > n


def test_a_figure_that_fails_a_check_is_named_in_words_with_its_month_in_words():
    d = world()
    d[TOTAL][LAST] = 9000000.0
    r = arun(U.UsIndustryJobs(client=make_client(d)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US jobs by industry could not be read right now (the data failed a check: total payrolls of 9,000,000 in October 2026 is outside 15,000 to 320,000)" and "total" not in r
    d = world()
    d[GOOD][LAST] += 3.0
    r = arun(U.UsIndustryJobs(client=make_client(d)).overview(NOW))
    assert r["reason"] == "US jobs by industry could not be read right now (the data failed a check: private payrolls are 3 thousand off goods-producing plus private service in October 2026, over 1.5)"


def test_a_client_it_makes_itself_is_closed_and_one_it_is_given_is_not(monkeypatch):
    made, instances = [], []

    class Own(REAL_CLIENT):
        def __init__(self, **kw):
            made.append(kw)
            instances.append(self)
            super().__init__(transport=transport_for(world()))

    monkeypatch.setattr(U.httpx, "AsyncClient", Own)
    c = U.UsIndustryJobs()
    assert arun(c.overview(NOW))["available"] is True and made == [{"timeout": 25}] and instances[0].is_closed is True
    given = make_client(world())
    arun(U.UsIndustryJobs(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_default_clock_is_utc_and_stamps_the_answer():
    r = arun(U.UsIndustryJobs(client=make_client(world())).overview())
    stamp = datetime.fromisoformat(r["as_of"])
    assert stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0) and abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


def test_each_request_goes_with_the_clients_own_user_agent_and_nothing_added():
    seen, data = [], world()

    async def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsIndustryJobs(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(seen) == 17 and all(ua.startswith("python-httpx/") for ua in seen)


def test_a_dropped_connection_a_timeout_and_a_missing_key_read_plainly(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("")

    def slow(request):
        raise httpx.ReadTimeout("")

    for fail, words in ((boom, "the connection could not be made"), (slow, "the request timed out")):
        r = arun(U.UsIndustryJobs(client=REAL_CLIENT(transport=httpx.MockTransport(fail))).overview(NOW))
        assert r["available"] is False and r["reason"] == f"US jobs by industry could not be read right now ({words})"

    def no_key(data, today):
        raise KeyError("PAYEMS")

    monkeypatch.setattr(U, "summarize", no_key)
    r = arun(U.UsIndustryJobs(client=make_client(world())).overview(NOW))
    assert r["available"] is False and r["reason"] == "US jobs by industry could not be read right now (the answer was not in the expected shape)"


def test_any_answer_but_200_is_refused_with_its_status_in_words():
    r = arun(U.UsIndustryJobs(client=make_client(world(), status=500)).overview(NOW))
    assert r["reason"] == "US jobs by industry could not be read right now (the server had an error, HTTP 500)"
    r = arun(U.UsIndustryJobs(client=make_client(world(), status=204)).overview(NOW))
    assert r["reason"] == "US jobs by industry could not be read right now (the server answered HTTP 204)"


def test_the_clock_decides_the_age_not_the_computer_date():
    c = U.UsIndustryJobs(client=make_client(world()))
    r = arun(c.overview(datetime(2026, 12, 11, 1, tzinfo=timezone.utc)))
    assert r["age_days"] == 71 and r["freshness"] == "OVERDUE"
