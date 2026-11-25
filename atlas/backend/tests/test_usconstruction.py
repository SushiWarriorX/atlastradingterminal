"""US construction spending (Census Bureau via FRED, 9 monthly series): the real saved record, the limits and tolerances as literals, one check at a time, the figures of the summary and the class."""
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

import atlas_api.usconstruction as U

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usconstruction.json").read_text())
TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)

TOT, PRV, PUB, RES, NRS = "TTLCONS", "TLPRVCONS", "TLPBLCONS", "TLRESCONS", "TLNRESCONS"
PRR, PRN, PBR, PBN = "PRRESCONS", "PNRESCONS", "PBRESCONS", "PBNRESCONS"
IDS = [TOT, PRV, PUB, RES, NRS, PRR, PRN, PBR, PBN]
NAME = {TOT: "total spending", PRV: "private spending", PUB: "public spending", RES: "residential spending", NRS: "nonresidential spending",
        PRR: "private residential spending", PRN: "private nonresidential spending", PBR: "public residential spending", PBN: "public nonresidential spending"}
LIMITS = {TOT: (530000.0, 4550000.0), PRV: (390000.0, 3500000.0), PUB: (140000.0, 1100000.0), RES: (205000.0, 1975000.0), NRS: (325000.0, 2700000.0),
          PRR: (200000.0, 1960000.0), PRN: (185000.0, 1625000.0), PBR: (2800.0, 26500.0), PBN: (135000.0, 1075000.0)}
LEAVES = {PRR: 800000.0, PRN: 700000.0, PBR: 10000.0, PBN: 500000.0}          # the four parts of the 2-by-2 table; every other figure is a sum of them, so all six relations hold exactly
# the six relations, written out here on purpose (not read back from the module): whole, parts, the whole's name, what the parts are called
REL = [(TOT, (PRV, PUB), "total spending", "private plus public spending"),
       (TOT, (RES, NRS), "total spending", "residential plus nonresidential spending"),
       (PRV, (PRR, PRN), "private spending", "private residential plus nonresidential"),
       (PUB, (PBR, PBN), "public spending", "public residential plus nonresidential"),
       (RES, (PRR, PBR), "residential spending", "private plus public residential"),
       (NRS, (PRN, PBN), "nonresidential spending", "private plus public nonresidential")]
# shifts that break relation i first and leave the relations before it whole (the relations are not independent: the sixth follows from the first five, so it needs the larger shift of all three parts)
SHIFTS = [lambda x: {TOT: x, RES: x}, lambda x: {TOT: x, PRV: x}, lambda x: {TOT: x, PRV: x, RES: x}, lambda x: {TOT: x, PUB: x, RES: x},
          lambda x: {RES: x, NRS: -x}, lambda x: {TOT: 3 * x, PRV: x, PUB: x, NRS: 3 * x}]
FIRST_RELATION = {TOT: 0, PRV: 0, PUB: 0, RES: 1, NRS: 1, PRR: 2, PRN: 2, PBR: 3, PBN: 3}      # the first relation a lone shift of a series breaks


def mback(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, m + 1, 1)


def num(v):
    s = f"{v:,.1f}"
    return s[:-2] if s.endswith(".0") else s


def real():
    return {sid: U.parse(F[sid], sid) for sid in IDS}


def build(leaves):
    v = {k: leaves[k] for k in (PRR, PRN, PBR, PBN)}
    v[PRV], v[PUB] = v[PRR] + v[PRN], v[PBR] + v[PBN]
    v[RES], v[NRS] = v[PRR] + v[PBR], v[PRN] + v[PBN]
    v[TOT] = v[PRR] + v[PRN] + v[PBR] + v[PBN]
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


STEPS = {PRR: 2000.0, PRN: 1000.0, PBR: 100.0, PBN: 500.0}                     # millions a month, every one exact in binary


def trend(k):
    return {name: v + STEPS[name] * k for name, v in LEAVES.items()}


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


def label(d):
    return f"{d.year}-{d.month:02d}"


def sum_msg(i, gap, month):
    return f"{REL[i][2]} is {num(gap)} million off {REL[i][3]} in {label(month)}, over 1.5"


# ---------------------------------------------------------------- the real record


def test_the_whole_real_record_passes_and_all_six_sums_hold_within_one_million_in_every_month():
    data = real()
    months = sorted(data[TOT])
    assert len(months) == 141 and months[0] == date(2015, 1, 1) and months[-1] == LAST and all(set(data[s]) == set(months) for s in IDS)
    for whole, parts, _, _ in REL:
        gaps = {data[whole][d] - sum(data[p][d] for p in parts) for d in months}
        assert gaps == {-1.0, 0.0, 1.0}, whole                     # whole millions, each rounded on its own: never more than one off, and both signs occur
    r = run(data)
    assert r["available"] is True and r["date"] == "2026-09-01" and r["month"] == "2026-09" and r["age_days"] == 85 and r["freshness"] == "CURRENT"
    assert r["detail"] == {"months_checked": 141, "first_month": "2015-01", "last_month": "2026-09", "largest_sum_gap": 1.0}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "sums_ok": True}
    assert r["source"] == "U.S. Census Bureau, Construction Spending (value of construction put in place), via FRED, St. Louis Fed (official, free public data)" and r["url"] == "https://fred.stlouisfed.org/series/TTLCONS"


def test_the_figures_of_the_newest_real_month_and_the_ten_year_growth_range():
    r = run(real())
    assert r["total"] == {"millions": 2186145.0, "change_month_millions": -41229.0, "change_month_pct": -1.9, "change_year_millions": -59654.0, "change_year_pct": -2.7,
                          "growth_range": {"months": 120, "first": "2016-10", "lowest": {"value": -4.2, "month": "2026-04"}, "highest": {"value": 18.5, "month": "2022-04"}, "share_lower_pct": 5}}
    got = {x["key"]: (x["millions"], x["share_pct"], x["change_month_millions"], x["change_month_pct"], x["change_year_millions"], x["change_year_pct"]) for x in r["owners"] + r["uses"] + r["parts"]}
    assert got == {"private": (1639330.0, 75.0, -40937.0, -2.4, -65040.0, -3.8), "public": (546815.0, 25.0, -293.0, -0.1, 5386.0, 1.0),
                   "residential": (861192.0, 39.4, -48996.0, -5.4, -83050.0, -8.8), "nonresidential": (1324954.0, 60.6, 7768.0, 0.6, 23397.0, 1.8),
                   "private_residential": (848777.0, 38.8, -49218.0, -5.5, -82446.0, -8.9), "private_nonresidential": (790554.0, 36.2, 8282.0, 1.1, 17406.0, 2.3),
                   "public_residential": (12415.0, 0.6, 222.0, 1.8, -605.0, -4.6), "public_nonresidential": (534400.0, 24.4, -514.0, -0.1, 5991.0, 1.1)}
    assert [x["key"] for x in r["owners"]] == ["private", "public"] and [x["key"] for x in r["uses"]] == ["residential", "nonresidential"]
    assert [x["key"] for x in r["parts"]] == ["private_residential", "private_nonresidential", "public_residential", "public_nonresidential"]
    assert [x["label"] for x in r["owners"]] == ["Private", "Public"] and [x["label"] for x in r["uses"]] == ["Residential", "Nonresidential"]
    assert [x["label"] for x in r["parts"]] == ["Private residential", "Private nonresidential", "Public residential", "Public nonresidential"]
    assert r["recent"] == [{"month": "2026-04", "millions": 2168231.0, "change_millions": -31168.0}, {"month": "2026-05", "millions": 2168396.0, "change_millions": 165.0}, {"month": "2026-06", "millions": 2187350.0, "change_millions": 18954.0},
                           {"month": "2026-07", "millions": 2184026.0, "change_millions": -3324.0}, {"month": "2026-08", "millions": 2227374.0, "change_millions": 43348.0}, {"month": "2026-09", "millions": 2186145.0, "change_millions": -41229.0}]


def test_the_limits_are_the_literals_about_half_the_lowest_and_twice_the_highest_real_value():
    assert U.LIMITS == LIMITS and U.NAMES == NAME and U.SERIES == IDS
    data = real()
    for sid, (lo, hi) in LIMITS.items():
        low, high = min(data[sid].values()), max(data[sid].values())
        assert lo < low < hi and lo < high < hi
        assert 0.45 < lo / low < 0.55 and 1.95 < hi / high < 2.05, sid


def test_the_constants_the_address_the_source_and_the_ids_are_the_literals_written_here():
    assert U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and U.PAGE == "https://fred.stlouisfed.org/series/TTLCONS"
    assert U.SOURCE == "U.S. Census Bureau, Construction Spending (value of construction put in place), via FRED, St. Louis Fed (official, free public data)"
    assert (U.TOT, U.PRV, U.PUB, U.RES, U.NRS, U.PRR, U.PRN, U.PBR, U.PBN) == (TOT, PRV, PUB, RES, NRS, PRR, PRN, PBR, PBN)
    assert U.OWNERS == (("private", "Private", PRV), ("public", "Public", PUB)) and U.USES == (("residential", "Residential", RES), ("nonresidential", "Nonresidential", NRS))
    assert U.PARTS == (("private_residential", "Private residential", PRR), ("private_nonresidential", "Private nonresidential", PRN), ("public_residential", "Public residential", PBR), ("public_nonresidential", "Public nonresidential", PBN))


def test_the_tolerances_are_half_a_million_for_each_figure_of_a_sum_and_the_record_starts_in_2015():
    assert [(w, p, t, what) for w, p, t, what in U.SUMS] == [(w, p, 1.5, what) for w, p, _, what in REL]
    assert U.START == "2015-01-01" and U.MIN_MONTHS == 132 and U.HISTORY_MONTHS == 120 and U.RECENT_MONTHS == 6 and U.OVERDUE_AFTER_DAYS == 100 and U.TTL == 6 * 3600.0 and U.FAIL_TTL == 120.0 and U.CONCURRENCY == 6


# ---------------------------------------------------------------- the months


@pytest.mark.parametrize("sid", IDS)
def test_a_series_that_ends_a_month_early_is_refused_first_whichever_series_it_is(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the construction spending series end in different months")


def test_a_series_that_covers_other_months_is_named_and_the_total_is_the_base():
    for sid in IDS[1:]:
        d = world()
        del d[sid][MIDDLE]
        refused(d, f"the {NAME[sid]} series covers different months than total spending")
    d = world()
    del d[PBN][MIDDLE]
    del d[PRV][MIDDLE]
    refused(d, "the private spending series covers different months than total spending")           # the first one in the series order is named
    d = world()
    del d[TOT][MIDDLE]
    refused(d, "the private spending series covers different months than total spending")


def test_a_date_that_is_not_the_first_of_a_month_is_refused():
    d = {sid: {k + timedelta(days=1): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a construction spending date is not the 1st of a month")
    d = {sid: {(k + timedelta(days=1) if k == MIDDLE else k): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a construction spending date is not the 1st of a month")


def test_a_skipped_month_is_named_by_the_month_before_it():
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    refused(d, f"the construction spending months skip a month after {label(mback(MIDDLE, 1))}")
    d = {sid: {k: v for k, v in s.items() if k != OLDEST} for sid, s in world().items()}
    assert run(d)["detail"]["months_checked"] == 139


def test_fewer_than_132_months_are_refused_and_132_pass():
    refused(world(n=131), "the construction spending series cover 131 months, fewer than the 132 expected")
    assert run(world(n=132))["detail"]["months_checked"] == 132


# ---------------------------------------------------------------- the ranges


def one_month(sid, v):
    ok = build(LEAVES)
    data = {s: {LAST: ok[s]} for s in IDS}
    data[sid][LAST] = v
    return data


@pytest.mark.parametrize("sid", IDS)
def test_every_series_is_inside_its_range_at_both_edges_and_outside_one_million_beyond(sid):
    lo, hi = LIMITS[sid]
    for v in (lo, hi, (lo + hi) / 2):
        U._check_ranges(one_month(sid, v), [LAST])
    for v in (lo - 1.0, hi + 1.0):
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
    refused(d, "a construction spending date is not the 1st of a month")
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    d[TOT][OLDEST] = 99999999.0
    refused(d, f"the construction spending months skip a month after {label(mback(MIDDLE, 1))}")
    d = world(n=131)
    d[TOT][mback(LAST, 130)] = 99999999.0
    refused(d, "the construction spending series cover 131 months, fewer than the 132 expected")
    d = world()
    d[TOT][OLDEST] = 99999999.0
    del d[PRV][MIDDLE]
    refused(d, "the private spending series covers different months than total spending")
    d = world()
    d[TOT][OLDEST] = 99999999.0
    del d[PBN][LAST]
    refused(d, "the construction spending series end in different months")


def test_the_ranges_come_before_the_sums():
    refused(bump(world(), LAST, {TOT: 5000000.0}), "total spending of 7,010,000 in 2026-09 is outside 530,000 to 4,550,000")


def test_a_message_names_the_first_wrong_series_in_the_series_order_and_the_oldest_month():
    d = world()
    d[PBN][LAST] = 99999999.0
    d[PRV][MIDDLE] = 99999999.0
    refused(d, f"private spending of 99,999,999 in {label(MIDDLE)} is outside 390,000 to 3,500,000")
    d = world()
    d[PRV][LAST] = 99999999.0
    d[PRV][OLDEST] = 99999999.0
    refused(d, f"private spending of 99,999,999 in {label(OLDEST)} is outside 390,000 to 3,500,000")


# ---------------------------------------------------------------- the sums


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("i", range(6))
def test_each_sum_holds_at_one_and_a_half_million_off_and_is_refused_just_beyond(i, sign, month):
    at, beyond = (0.5, 0.6) if i == 5 else (1.5, 1.6)            # the sixth follows from the other five: three parts at a third of the gap each
    ok = bump(world(), month, {s: d * sign for s, d in SHIFTS[i](at).items()})
    assert run(ok)["detail"]["largest_sum_gap"] == 1.5
    gap = 3 * beyond if i == 5 else beyond
    refused(bump(world(), month, {s: d * sign for s, d in SHIFTS[i](beyond).items()}), sum_msg(i, gap, month))


@pytest.mark.parametrize("sid", IDS)
def test_each_series_takes_part_in_its_first_relation(sid):
    i = FIRST_RELATION[sid]
    refused(bump(world(), LAST, {sid: 3.0}), sum_msg(i, 3, LAST))
    refused(bump(world(), LAST, {sid: -3.0}), sum_msg(i, 3, LAST))


def test_the_relations_are_scanned_one_after_the_other_and_the_oldest_month_first():
    d = bump(bump(world(), OLDEST, {TOT: 2.0, PRV: 2.0}), LAST, {TOT: 2.0, RES: 2.0})
    refused(d, sum_msg(0, 2, LAST))                                    # the second relation breaks in the oldest month, the first only in the newest: the first relation is scanned first
    d = bump(bump(world(), OLDEST, {TOT: 2.0, PRV: 2.0, RES: 2.0}), LAST, {TOT: 2.0, PRV: 2.0})
    refused(d, sum_msg(1, 2, LAST))                                    # the third relation breaks in the oldest month, the second in the newest
    d = bump(bump(world(), LAST, {TOT: 2.0, RES: 2.0}), MIDDLE, {TOT: 3.0, RES: 3.0})
    refused(d, sum_msg(0, 3, MIDDLE))                                  # inside a relation the oldest month comes first
    d = bump(bump(world(), LAST, {PRR: 2.0}), MIDDLE, {PRR: 3.0})
    refused(d, sum_msg(2, 3, MIDDLE))


def test_the_largest_gap_is_kept_over_all_relations_and_all_the_months():
    assert run(world())["detail"]["largest_sum_gap"] == 0.0
    assert run(bump(world(), MIDDLE, {PRR: 1.0}))["detail"]["largest_sum_gap"] == 1.0
    assert run(bump(bump(world(), MIDDLE, {PRR: 1.0}), LAST, {PBN: 1.5}))["detail"]["largest_sum_gap"] == 1.5
    assert run(bump(bump(world(), OLDEST, {PRR: 0.5}), LAST, {PRN: 0.25}))["detail"]["largest_sum_gap"] == 0.5
    assert run(bump(world(), LAST, {PRR: 0.00004}))["detail"]["largest_sum_gap"] == 0.0
    assert run(bump(world(), LAST, {PRR: 0.0001}))["detail"]["largest_sum_gap"] == 0.0001


# ---------------------------------------------------------------- the figures


def test_a_flat_world_has_no_change_and_no_negative_zero_and_shares_that_need_rounding():
    r = run(world())
    assert r["total"] == {"millions": 2010000.0, "change_month_millions": 0.0, "change_month_pct": 0.0, "change_year_millions": 0.0, "change_year_pct": 0.0,
                          "growth_range": {"months": 120, "first": "2016-10", "lowest": {"value": 0.0, "month": "2016-10"}, "highest": {"value": 0.0, "month": "2016-10"}, "share_lower_pct": 0}}
    assert [(x["key"], x["millions"], x["share_pct"], x["change_month_millions"], x["change_month_pct"]) for x in r["owners"]] == [("private", 1500000.0, 74.6, 0.0, 0.0), ("public", 510000.0, 25.4, 0.0, 0.0)]
    assert [(x["key"], x["millions"], x["share_pct"]) for x in r["uses"]] == [("residential", 810000.0, 40.3), ("nonresidential", 1200000.0, 59.7)]        # 40.2985: rounded, not cut
    assert [(x["key"], x["millions"], x["share_pct"]) for x in r["parts"]] == [("private_residential", 800000.0, 39.8), ("private_nonresidential", 700000.0, 34.8), ("public_residential", 10000.0, 0.5), ("public_nonresidential", 500000.0, 24.9)]
    assert all(math.copysign(1.0, x) > 0 for x in (r["total"]["change_month_millions"], r["total"]["change_month_pct"], r["total"]["change_year_millions"], r["total"]["change_year_pct"]))


def test_a_falling_world_shows_the_changes_with_their_signs_and_a_fall_to_nothing_as_plain_zero():
    r = run(world_by(lambda k: {**LEAVES, PBR: 10000.0 - 0.01 * (k == 139)}))
    pbr = next(x for x in r["parts"] if x["key"] == "public_residential")
    assert pbr["change_month_millions"] == 0.0 and str(pbr["change_month_millions"]) == "0.0" and pbr["change_month_pct"] == 0.0 and str(pbr["change_month_pct"]) == "0.0"
    r = run(world_by(lambda k: {**LEAVES, PRR: 800000.0 - 25000.0 * (k == 139)}))
    assert r["total"]["change_month_millions"] == -25000.0 and r["total"]["change_month_pct"] == -1.2 and r["total"]["change_year_millions"] == -25000.0
    r = run(world_by(lambda k: {**LEAVES, PBR: 10000.0 + 0.44 * (k == 139)}))
    pbr = next(x for x in r["parts"] if x["key"] == "public_residential")
    assert pbr["change_month_millions"] == 0.4 and pbr["change_year_millions"] == 0.4                # a change in millions is kept to a tenth, not to a whole million and not to hundredths


def test_a_rising_trend_gives_exact_levels_changes_shares_and_the_last_six_months():
    r = run(world_by(trend))
    assert r["total"] == {"millions": 2510400.0, "change_month_millions": 3600.0, "change_month_pct": 0.1, "change_year_millions": 43200.0, "change_year_pct": 1.8,
                          "growth_range": {"months": 120, "first": "2016-10", "lowest": {"value": 1.8, "month": "2023-09"}, "highest": {"value": 2.1, "month": "2016-10"}, "share_lower_pct": 0}}
    want = {"private": (1917000.0, 76.4, 3000.0, 0.2, 36000.0, 1.9), "public": (593400.0, 23.6, 600.0, 0.1, 7200.0, 1.2),
            "residential": (1101900.0, 43.9, 2100.0, 0.2, 25200.0, 2.3), "nonresidential": (1408500.0, 56.1, 1500.0, 0.1, 18000.0, 1.3),
            "private_residential": (1078000.0, 42.9, 2000.0, 0.2, 24000.0, 2.3), "private_nonresidential": (839000.0, 33.4, 1000.0, 0.1, 12000.0, 1.5),
            "public_residential": (23900.0, 1.0, 100.0, 0.4, 1200.0, 5.3), "public_nonresidential": (569500.0, 22.7, 500.0, 0.1, 6000.0, 1.1)}
    got = {x["key"]: (x["millions"], x["share_pct"], x["change_month_millions"], x["change_month_pct"], x["change_year_millions"], x["change_year_pct"]) for x in r["owners"] + r["uses"] + r["parts"]}
    assert got == want                                                  # public residential 0.952 is 1.0 rounded (0.9 cut), public nonresidential 22.685 is 22.7 (22.6 cut)
    assert r["recent"] == [{"month": m, "millions": v, "change_millions": 3600.0} for m, v in (("2026-04", 2492400.0), ("2026-05", 2496000.0), ("2026-06", 2499600.0), ("2026-07", 2503200.0), ("2026-08", 2506800.0), ("2026-09", 2510400.0))]
    assert r["detail"] == {"months_checked": 140, "first_month": "2015-02", "last_month": "2026-09", "largest_sum_gap": 0.0}


def test_the_month_change_and_the_year_change_each_use_their_own_month():
    r = run(world_by(lambda k: {**LEAVES, PRR: 800000.0 + (100000.0 if k == 139 - 12 else 0.0) + (10000.0 if k == 139 - 1 else 0.0)}))
    assert r["total"]["change_month_millions"] == -10000.0 and r["total"]["change_year_millions"] == -100000.0
    assert r["total"]["change_month_pct"] == -0.5 and r["total"]["change_year_pct"] == -4.7


def test_the_growth_range_ranks_all_120_months_and_counts_only_strictly_lower_ones():
    r = run(world_by(lambda k: {**LEAVES, PRR: LEAVES[PRR] + (30000.0 if k == 139 else 0.0)}))
    assert r["total"]["change_month_millions"] == 30000.0 and r["total"]["change_month_pct"] == 1.5 and r["total"]["change_year_millions"] == 30000.0 and r["total"]["change_year_pct"] == 1.5
    assert r["total"]["growth_range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 0.0, "month": "2016-10"}, "highest": {"value": 1.5, "month": "2026-09"}, "share_lower_pct": 99}
    r = run(world_by(lambda k: {**LEAVES, PRR: LEAVES[PRR] + (30000.0 if k >= 130 else 0.0)}))
    assert r["total"]["growth_range"]["months"] == 120 and r["total"]["growth_range"]["share_lower_pct"] == 92


def test_the_growth_window_is_the_last_120_months_of_a_longer_record():
    r = run(world_by(lambda k: {**LEAVES, PRR: LEAVES[PRR] + (300000.0 if k == 5 else 0.0)}, n=140))
    g = r["total"]["growth_range"]
    assert g["months"] == 120 and g["first"] == "2016-10" and g["highest"]["value"] == 0.0 and g["lowest"]["value"] == 0.0
    r = run(world_by(lambda k: {**LEAVES, PRR: LEAVES[PRR] + (300000.0 if k == 25 else 0.0)}, n=140))
    assert r["total"]["growth_range"]["highest"]["value"] == 14.9 and r["total"]["growth_range"]["highest"]["month"] == "2017-03"          # 114 months before 2026-09 is 2017-03


def test_a_release_that_is_late_is_marked_overdue_after_100_days_from_the_first_of_the_month():
    assert run(world(), LAST + timedelta(days=100))["freshness"] == "CURRENT" and run(world(), LAST + timedelta(days=100))["age_days"] == 100
    assert run(world(), LAST + timedelta(days=101))["freshness"] == "OVERDUE" and run(world(), LAST + timedelta(days=101))["age_days"] == 101
    assert run(world(), LAST)["age_days"] == 0 and run(world(), LAST)["freshness"] == "CURRENT"


def test_the_requests_go_to_the_fred_csv_address_and_carry_nothing_but_the_id_and_the_start():
    urls, data = [], world()

    async def handler(request):
        urls.append((request.url.scheme, request.url.host, request.url.path, sorted(request.url.params)))
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsConstruction(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(urls) == 9 and all(u == ("https", "fred.stlouisfed.org", "/graph/fredgraph.csv", ["cosd", "id"]) for u in urls)


def test_the_note_says_what_the_figures_are_and_are_not_and_points_to_the_check_line():
    note = run(world())["note"]
    assert "not new orders and not buildings finished" in note and "the Check line" in note and note.count("the Check line") == 1
    assert note.endswith("This describes construction work that already happened: it is not a market signal or a forecast.")


# ---------------------------------------------------------------- the messages


def test_every_failure_message_fits_in_the_110_characters_a_card_shows():
    msgs = [sum_msg(i, 1234.5, OLDEST) for i in range(6)] + ["the construction spending series end in different months",
            "the private nonresidential spending series covers different months than total spending", "a construction spending date is not the 1st of a month",
            f"the construction spending months skip a month after {label(OLDEST)}", "the construction spending series cover 131 months, fewer than the 132 expected",
            f"private nonresidential spending of 99,999,999 in {label(OLDEST)} is outside 185,000 to 1,625,000", f"public nonresidential spending of 99,999,999 in {label(OLDEST)} is outside 135,000 to 1,075,000"]
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
    c = U.UsConstruction(client=make_client(world(), seen), demo=True)
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is True and r["reason"] == "Demo mode: the real US construction spending figures are not shown because made-up values would look real." and seen == []
    assert "total" not in r and r["as_of"] == NOW.isoformat()


def test_one_request_per_series_each_with_its_id_and_the_start_date_and_six_at_a_time():
    seen, stats = [], {"now": 0, "peak": 0}
    c = U.UsConstruction(client=make_client(world(), seen, delay=0.01, stats=stats))
    r = arun(c.overview(NOW))
    assert r["available"] is True and r["demo"] is False and r["date"] == "2026-09-01" and r["age_days"] == 85
    assert sorted(x["id"] for x in seen) == sorted(IDS) and all(x == {"id": x["id"], "cosd": "2015-01-01"} for x in seen)
    assert stats["peak"] == 6


def test_the_real_record_through_the_class_gives_the_same_answer_as_the_summary():
    r = arun(U.UsConstruction(client=make_client(real())).overview(NOW))
    assert r["available"] is True and r["total"]["millions"] == 2186145.0 and r["detail"]["months_checked"] == 141 and r["as_of"] == NOW.isoformat()


def test_a_good_answer_is_kept_for_six_hours_and_asked_again_after_that(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(U, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    seen = []
    c = U.UsConstruction(client=make_client(world(), seen))
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
    c = U.UsConstruction(client=make_client(world(), seen, status=500))
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is False and r["reason"].startswith("US construction spending could not be read right now (") and "total" not in r
    n = len(seen)
    clock[0] += 119.0
    arun(c.overview(NOW))
    assert len(seen) == n
    clock[0] += 1.0
    arun(c.overview(NOW))
    assert len(seen) > n


def test_a_figure_that_fails_a_check_is_named_in_words_with_its_month_in_words():
    d = world()
    d[TOT][LAST] = 9000000.0
    r = arun(U.UsConstruction(client=make_client(d)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US construction spending could not be read right now (the data failed a check: total spending of 9,000,000 in September 2026 is outside 530,000 to 4,550,000)" and "total" not in r


def test_a_client_it_makes_itself_is_closed_and_one_it_is_given_is_not(monkeypatch):
    made, instances = [], []

    class Own(REAL_CLIENT):
        def __init__(self, **kw):
            made.append(kw)
            instances.append(self)
            super().__init__(transport=transport_for(world()))

    monkeypatch.setattr(U.httpx, "AsyncClient", Own)
    c = U.UsConstruction()
    assert arun(c.overview(NOW))["available"] is True and made == [{"timeout": 25}] and instances[0].is_closed is True
    given = make_client(world())
    arun(U.UsConstruction(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_default_clock_is_utc_and_stamps_the_answer():
    r = arun(U.UsConstruction(client=make_client(world())).overview())
    stamp = datetime.fromisoformat(r["as_of"])
    assert stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0) and abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


def test_each_request_goes_with_the_clients_own_user_agent_and_nothing_added():
    seen, data = [], world()

    async def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsConstruction(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(seen) == 9 and all(ua.startswith("python-httpx/") for ua in seen)


def test_a_dropped_connection_a_timeout_and_a_missing_key_read_plainly(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("")

    def slow(request):
        raise httpx.ReadTimeout("")

    for fail, words in ((boom, "the connection could not be made"), (slow, "the request timed out")):
        r = arun(U.UsConstruction(client=REAL_CLIENT(transport=httpx.MockTransport(fail))).overview(NOW))
        assert r["available"] is False and r["reason"] == f"US construction spending could not be read right now ({words})"

    def no_key(data, today):
        raise KeyError("TTLCONS")

    monkeypatch.setattr(U, "summarize", no_key)
    r = arun(U.UsConstruction(client=make_client(world())).overview(NOW))
    assert r["available"] is False and r["reason"] == "US construction spending could not be read right now (the answer was not in the expected shape)"


def test_any_answer_but_200_is_refused_with_its_status_in_words():
    r = arun(U.UsConstruction(client=make_client(world(), status=500)).overview(NOW))
    assert r["reason"] == "US construction spending could not be read right now (the server had an error, HTTP 500)"
    r = arun(U.UsConstruction(client=make_client(world(), status=204)).overview(NOW))
    assert r["reason"] == "US construction spending could not be read right now (the server answered HTTP 204)"


def test_the_clock_decides_the_age_not_the_computer_date():
    c = U.UsConstruction(client=make_client(world()))
    r = arun(c.overview(datetime(2026, 12, 11, 1, tzinfo=timezone.utc)))
    assert r["age_days"] == 101 and r["freshness"] == "OVERDUE"
