"""US business inventories and sales (U.S. Census Bureau, Manufacturing and Trade Inventories and Sales, via FRED: 12 monthly series): parsed from real responses (fetched 2026-11-24 20:40 UTC, 417 months from 1992-01 to 2026-09).

The limits are literals, set from the whole real record before any test was written (it is in the log): each series' real lowest and highest value, a lower limit near half the lowest (a level) or 0.8 times it (a ratio) and an upper limit about twice the highest (a level, because levels grow)
or 1.26 times it (a ratio). The two sums (inventories and sales of the three kinds of business) hold EXACTLY in all 417 months, so their tolerance is not a measured gap but the arithmetic bound of four figures each rounded to a million, 2.0. The four ratios are published to two decimals, so
their tolerance is half a hundredth plus the rounding of the figures they are worked from, 0.0051 (the real largest gap is 0.004996)."""
import asyncio
import csv
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import usinventories as U
from atlas_api.app import create_app
from atlas_api.failreason import dates_in_words, fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usinventories.json").read_text())
TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)

IDS = ["BUSINV", "TOTBUSSMSA", "ISRATIO", "MNFCTRIMSA", "WHLSLRIMSA", "RETAILIMSA", "MNFCTRSMSA", "WHLSLRSMSA", "RETAILSMSA", "MNFCTRIRSA", "WHLSLRIRSA", "RETAILIRSA"]
NAME = {"BUSINV": "total inventories", "TOTBUSSMSA": "total sales", "ISRATIO": "total ratio", "MNFCTRIMSA": "manufacturers' inventories", "WHLSLRIMSA": "wholesalers' inventories",
        "RETAILIMSA": "retailers' inventories", "MNFCTRSMSA": "manufacturers' sales", "WHLSLRSMSA": "wholesalers' sales", "RETAILSMSA": "retailers' sales",
        "MNFCTRIRSA": "manufacturers' ratio", "WHLSLRIRSA": "wholesalers' ratio", "RETAILIRSA": "retailers' ratio"}
LIMITS = {"BUSINV": (400_000.0, 6_000_000.0), "TOTBUSSMSA": (250_000.0, 4_500_000.0), "ISRATIO": (1.0, 2.2),
          "MNFCTRIMSA": (180_000.0, 2_000_000.0), "WHLSLRIMSA": (90_000.0, 2_100_000.0), "RETAILIMSA": (110_000.0, 1_800_000.0),
          "MNFCTRSMSA": (110_000.0, 1_400_000.0), "WHLSLRSMSA": (70_000.0, 1_700_000.0), "RETAILSMSA": (70_000.0, 1_300_000.0),
          "MNFCTRIRSA": (0.9, 2.4), "WHLSLRIRSA": (0.9, 2.1), "RETAILIRSA": (0.9, 2.2)}
RATIOS = (("ISRATIO", "BUSINV", "TOTBUSSMSA"), ("MNFCTRIRSA", "MNFCTRIMSA", "MNFCTRSMSA"), ("WHLSLRIRSA", "WHLSLRIMSA", "WHLSLRSMSA"), ("RETAILIRSA", "RETAILIMSA", "RETAILSMSA"))
PARTS = {"BUSINV": ("MNFCTRIMSA", "WHLSLRIMSA", "RETAILIMSA"), "TOTBUSSMSA": ("MNFCTRSMSA", "WHLSLRSMSA", "RETAILSMSA")}
# the primaries of the default world: inventories and sales of manufacturers (m), merchant wholesalers (w) and retailers (r); the totals are their sums and every ratio is inventories over sales to two decimals
BASE = {"mi": 950_000.0, "wi": 1_000_000.0, "ri": 880_000.0, "ms": 660_000.0, "ws": 830_000.0, "rs": 650_000.0}
EXACT = {"mi": 1_000_000.0, "wi": 1_000_000.0, "ri": 1_000_000.0, "ms": 800_000.0, "ws": 800_000.0, "rs": 800_000.0}          # every ratio, the total's too, is exactly 1.25


def mback(d, n):
    i = d.year * 12 + d.month - 1 - n
    return date(i // 12, i % 12 + 1, 1)


def mlab(d):
    return f"{d.year}-{d.month:02d}"


def num(v):
    s = f"{v:,.1f}"
    return s[:-2] if s.endswith(".0") else s


def real():
    return {sid: U.parse(F[sid], sid) for sid in IDS}


def build(base):
    """All 12 series of one month from the six primaries: totals are the sums, ratios are inventories over sales rounded to two decimals."""
    out = {"MNFCTRIMSA": base["mi"], "WHLSLRIMSA": base["wi"], "RETAILIMSA": base["ri"], "MNFCTRSMSA": base["ms"], "WHLSLRSMSA": base["ws"], "RETAILSMSA": base["rs"]}
    out["BUSINV"] = base["mi"] + base["wi"] + base["ri"]
    out["TOTBUSSMSA"] = base["ms"] + base["ws"] + base["rs"]
    out["ISRATIO"] = round(out["BUSINV"] / out["TOTBUSSMSA"], 2)
    out["MNFCTRIRSA"] = round(base["mi"] / base["ms"], 2)
    out["WHLSLRIRSA"] = round(base["wi"] / base["ws"], 2)
    out["RETAILIRSA"] = round(base["ri"] / base["rs"], 2)
    return out


def world(n=180, last=LAST, base=BASE, **changed):
    one = build({**base, **changed})
    return {sid: {mback(last, i): v for i in range(n - 1, -1, -1)} for sid, v in one.items()}


def world_by(fn, n=180, last=LAST):
    data = {sid: {} for sid in IDS}
    for i in range(n - 1, -1, -1):
        for sid, v in build(fn(i)).items():
            data[sid][mback(last, i)] = v
    return data


def trend(i):
    """The primaries of the month `i` months before LAST: inventories and sales grow by 1,000 and 500 a month towards LAST."""
    k = 179 - i
    return {"mi": 900_000.0 + 1_000.0 * k, "wi": 950_000.0 + 1_000.0 * k, "ri": 850_000.0 + 1_000.0 * k, "ms": 640_000.0 + 500.0 * k, "ws": 800_000.0 + 500.0 * k, "rs": 630_000.0 + 500.0 * k}


def run(data, today=TODAY):
    return U.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        U.summarize(data, TODAY)


def months_of(data):
    return sorted(data["BUSINV"])


# ---------------------------------------------------------------- the real record

def test_the_real_record_is_417_months_of_12_series_from_january_1992_to_september_2026():
    d = real()
    assert sorted(d) == sorted(IDS) and all(len(s) == 417 for s in d.values())
    assert min(d["BUSINV"]) == date(1992, 1, 1) and max(d["BUSINV"]) == LAST


def test_the_real_record_passes_every_check_and_reads_september_2026():
    r = run(real())
    assert r["available"] is True and r["date"] == "2026-09-01" and r["month"] == "2026-09" and r["age_days"] == 84 and r["freshness"] == "CURRENT"
    assert r["source"] == "U.S. Census Bureau, Manufacturing and Trade Inventories and Sales, via FRED, St. Louis Fed (official, free public data)" and r["url"] == "https://fred.stlouisfed.org/series/BUSINV"
    t = r["total"]
    assert (t["inventories_millions"], t["sales_millions"], t["ratio"]) == (2873438.0, 2162520.0, 1.33)
    assert (t["inventories_change_month_pct"], t["sales_change_month_pct"], t["inventories_change_year_pct"], t["sales_change_year_pct"], t["ratio_year_ago"]) == (0.5, 1.8, 5.1, 12.5, 1.42)
    assert t["ratio_range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 1.26, "month": "2021-04"}, "highest": {"value": 1.74, "month": "2020-04"}, "share_lower_pct": 12}
    w, m, rt = r["sectors"]
    assert [x["key"] for x in r["sectors"]] == ["wholesalers", "manufacturers", "retailers"] and [x["label"] for x in r["sectors"]] == ["Merchant wholesalers", "Manufacturers", "Retailers"]
    assert (w["inventories_millions"], w["sales_millions"], w["ratio"], w["share_pct"], w["inventories_change_year_pct"], w["sales_change_year_pct"], w["ratio_year_ago"]) == (1013103.0, 840123.0, 1.21, 35.3, 7.6, 19.8, 1.34)
    assert (m["inventories_millions"], m["sales_millions"], m["ratio"], m["share_pct"], m["inventories_change_year_pct"], m["sales_change_year_pct"], m["ratio_year_ago"]) == (976044.0, 668454.0, 1.46, 34.0, 3.1, 10.2, 1.56)
    assert (rt["inventories_millions"], rt["sales_millions"], rt["ratio"], rt["share_pct"], rt["inventories_change_year_pct"], rt["sales_change_year_pct"], rt["ratio_year_ago"]) == (884291.0, 653943.0, 1.35, 30.8, 4.7, 6.5, 1.38)
    assert w["ratio_range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 1.21, "month": "2021-07"}, "highest": {"value": 1.67, "month": "2020-04"}, "share_lower_pct": 0}
    assert m["ratio_range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 1.35, "month": "2018-05"}, "highest": {"value": 1.88, "month": "2020-04"}, "share_lower_pct": 28}
    assert rt["ratio_range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 1.1, "month": "2021-04"}, "highest": {"value": 1.68, "month": "2020-04"}, "share_lower_pct": 34}
    assert [(x["month"], x["inventories_millions"], x["sales_millions"], x["ratio"]) for x in r["recent"]] == [
        ("2026-04", 2808412.0, 2065906.0, 1.36), ("2026-05", 2821668.0, 2109353.0, 1.34), ("2026-06", 2824258.0, 2091388.0, 1.35),
        ("2026-07", 2847600.0, 2098966.0, 1.36), ("2026-08", 2858902.0, 2125174.0, 1.35), ("2026-09", 2873438.0, 2162520.0, 1.33)]
    assert r["detail"] == {"months_checked": 417, "first_month": "1992-01", "last_month": "2026-09", "largest_sum_gap": 0.0, "largest_ratio_gap": 0.005}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "totals_add_up_ok": True, "ratios_match_ok": True}


def test_the_real_record_recomputed_in_plain_python_agrees_with_the_limits_the_sums_and_the_ratios_of_this_file():
    rows = {sid: {r[0]: float(r[1]) for r in list(csv.reader(io.StringIO(F[sid])))[1:]} for sid in IDS}
    assert all(len(v) == 417 for v in rows.values())
    for sid, (lo, hi) in LIMITS.items():
        assert lo <= min(rows[sid].values()) and max(rows[sid].values()) <= hi, sid
    for whole, parts in PARTS.items():
        assert max(abs(rows[whole][d] - sum(rows[p][d] for p in parts)) for d in rows[whole]) == 0.0
    for ratio, inv, sales in RATIOS:
        assert 0.0049 < max(abs(rows[ratio][d] - rows[inv][d] / rows[sales][d]) for d in rows[ratio]) < 0.005
    assert min(rows["ISRATIO"].values()) == 1.24 and max(rows["ISRATIO"].values()) == 1.74
    assert min(rows["BUSINV"].values()) == 800927.0 and max(rows["BUSINV"].values()) == 2873438.0


def test_the_series_are_asked_for_in_this_order_and_the_limits_are_these_literals():
    assert U.SERIES == IDS and U.LIMITS == LIMITS and U.NAMES == NAME
    assert U.SUM_TOLERANCE == 2.0 and U.RATIO_TOLERANCE == 0.0051 and U.MIN_MONTHS == 120 and U.HISTORY_MONTHS == 120 and U.RECENT_MONTHS == 6 and U.OVERDUE_AFTER_DAYS == 110 and U.CONCURRENCY == 6


# ---------------------------------------------------------------- the default world

def test_the_default_world_passes_and_every_figure_is_the_one_built():
    r = run(world())
    t = r["total"]
    assert (t["inventories_millions"], t["sales_millions"], t["ratio"]) == (2830000.0, 2140000.0, 1.32)
    assert (t["inventories_change_month_pct"], t["sales_change_month_pct"], t["inventories_change_year_pct"], t["sales_change_year_pct"], t["ratio_year_ago"]) == (0.0, 0.0, 0.0, 0.0, 1.32)
    assert [x["key"] for x in r["sectors"]] == ["wholesalers", "manufacturers", "retailers"]
    assert [(x["inventories_millions"], x["sales_millions"], x["ratio"], x["share_pct"]) for x in r["sectors"]] == [
        (1000000.0, 830000.0, 1.2, 35.3), (950000.0, 660000.0, 1.44, 33.6), (880000.0, 650000.0, 1.35, 31.1)]
    assert r["detail"]["largest_sum_gap"] == 0.0 and r["detail"]["largest_ratio_gap"] == 0.00482 and r["detail"]["months_checked"] == 180 and r["detail"]["first_month"] == "2011-10"
    assert len(r["recent"]) == 6 and r["recent"][0]["month"] == "2026-04" and r["recent"][-1]["month"] == "2026-09"


def test_sectors_are_sorted_by_inventories_with_ties_by_label():
    r = run(world(mi=1_000_000.0, wi=900_000.0, ri=1_000_000.0))
    assert [x["key"] for x in r["sectors"]] == ["manufacturers", "retailers", "wholesalers"]                  # manufacturers and retailers tie: "Manufacturers" before "Retailers"
    r = run(world(mi=800_000.0, wi=800_000.0, ri=800_000.0))
    assert [x["key"] for x in r["sectors"]] == ["manufacturers", "wholesalers", "retailers"]                   # all three tie: "Manufacturers", "Merchant wholesalers", "Retailers"


def test_the_changes_are_worked_against_the_month_before_and_the_same_month_a_year_before():
    d = world_by(trend)
    last, before, ago = trend(0), trend(1), trend(12)
    r = run(d)
    inv = lambda p: p["mi"] + p["wi"] + p["ri"]
    sal = lambda p: p["ms"] + p["ws"] + p["rs"]
    t = r["total"]
    assert t["inventories_change_month_pct"] == round(100 * (inv(last) - inv(before)) / inv(before), 1) == 0.1
    assert t["sales_change_month_pct"] == round(100 * (sal(last) - sal(before)) / sal(before), 1) == 0.1
    assert t["inventories_change_year_pct"] == round(100 * (inv(last) - inv(ago)) / inv(ago), 1) == 1.1
    assert t["sales_change_year_pct"] == round(100 * (sal(last) - sal(ago)) / sal(ago), 1) == 0.8
    assert t["ratio_year_ago"] == build(ago)["ISRATIO"]
    for x in r["sectors"]:
        k = {"manufacturers": "m", "wholesalers": "w", "retailers": "r"}[x["key"]]
        assert x["inventories_change_year_pct"] == round(100 * (last[k + "i"] - ago[k + "i"]) / ago[k + "i"], 1)
        assert x["sales_change_year_pct"] == round(100 * (last[k + "s"] - ago[k + "s"]) / ago[k + "s"], 1)
        assert x["ratio_year_ago"] == build(ago)[{"m": "MNFCTRIRSA", "w": "WHLSLRIRSA", "r": "RETAILIRSA"}[k]]


def test_a_tiny_fall_that_rounds_to_nothing_is_zero_not_minus_zero():
    d = world()
    d["BUSINV"][LAST] -= 1.0
    d["MNFCTRIMSA"][LAST] -= 1.0                                                                          # the sum still holds; the fall is 0.00004 percent
    r = run(d)
    assert r["total"]["inventories_change_month_pct"] == 0.0 and str(r["total"]["inventories_change_month_pct"]) == "0.0"
    assert str(r["total"]["inventories_change_year_pct"]) == "0.0"


def test_the_ratio_range_is_the_ten_years_to_the_newest_month_and_counts_the_months_strictly_lower():
    d = world_by(trend)
    r = run(d)
    vals = [build(trend(i))["ISRATIO"] for i in range(119, -1, -1)]
    rng = r["total"]["ratio_range"]
    assert rng["months"] == 120 and rng["first"] == mlab(mback(LAST, 119))
    assert rng["lowest"]["value"] == min(vals) and rng["highest"]["value"] == max(vals)
    assert rng["share_lower_pct"] == round(100 * sum(1 for v in vals if v < vals[-1]) / 120)
    assert rng["lowest"]["month"] == mlab(mback(LAST, 119 - vals.index(min(vals))))


def test_the_six_recent_months_have_their_own_figures_and_the_oldest_comes_first():
    r = run(world_by(trend))
    assert [x["month"] for x in r["recent"]] == [mlab(mback(LAST, i)) for i in range(5, -1, -1)]
    for x, i in zip(r["recent"], range(5, -1, -1)):
        one = build(trend(i))
        assert (x["inventories_millions"], x["sales_millions"], x["ratio"]) == (one["BUSINV"], one["TOTBUSSMSA"], one["ISRATIO"])


def test_freshness_is_current_for_110_days_from_the_first_of_the_month_and_overdue_after():
    d = world()
    assert run(d, LAST + timedelta(days=110))["freshness"] == "CURRENT" and run(d, LAST + timedelta(days=110))["age_days"] == 110
    assert run(d, LAST + timedelta(days=111))["freshness"] == "OVERDUE"


# ---------------------------------------------------------------- the months

def test_series_that_end_in_different_months_are_refused():
    d = world()
    del d["TOTBUSSMSA"][LAST]
    refused(d, "the inventory series end in different months")
    d = world()
    d["RETAILIRSA"][LAST + timedelta(days=31)] = 1.3
    refused(d, "the inventory series end in different months")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_that_covers_other_months_than_total_inventories_is_refused_by_name(sid):
    d = world()
    del d[sid][mback(LAST, 50)]
    refused(d, f"the {NAME[sid]} series covers different months than total inventories")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_as_many_months_but_one_of_them_different_is_refused_by_name(sid):
    d = world()
    value = d[sid].pop(mback(LAST, 50))
    d[sid][mback(LAST, 200)] = value                                                                      # one month swapped for an older one: the same count, another set
    refused(d, f"the {NAME[sid]} series covers different months than total inventories")


def test_a_date_that_is_not_the_first_of_a_month_is_refused():
    d = world()
    d = {sid: {(k.replace(day=2) if k == mback(LAST, 100) else k): v for k, v in s.items()} for sid, s in d.items()}
    refused(d, "an inventory date is not the 1st of a month")


def test_a_skipped_month_is_refused_after_the_month_before_the_gap():
    d = world()
    gone = mback(LAST, 40)
    d = {sid: {k: v for k, v in s.items() if k != gone} for sid, s in d.items()}
    refused(d, f"the inventory months skip a month after {mlab(mback(LAST, 41))}")


def test_fewer_than_120_months_are_refused_and_120_are_enough():
    refused(world(n=119), "the inventory series cover 119 months, fewer than the 120 expected")
    assert run(world(n=120))["detail"]["months_checked"] == 120


# ---------------------------------------------------------------- the ranges

def money(v):
    return num(v)


def ratio_text(v):
    return f"{v:.2f}"


def edge_message(sid, v, lo, hi, when=LAST):
    if sid in ("ISRATIO", "MNFCTRIRSA", "WHLSLRIRSA", "RETAILIRSA"):
        return f"{NAME[sid]} of {ratio_text(v)} in {mlab(when)} is outside {lo:g} to {hi:g}"
    return f"{NAME[sid]} of {money(v)} in {mlab(when)} is outside {num(lo)} to {num(hi)}"


@pytest.mark.parametrize("sid", IDS)
def test_a_value_just_under_the_lower_limit_or_just_over_the_upper_one_is_refused_and_the_limits_themselves_are_not(sid):
    lo, hi = LIMITS[sid]
    step = 0.01 if sid in ("ISRATIO", "MNFCTRIRSA", "WHLSLRIRSA", "RETAILIRSA") else 1.0
    for edge in (lo, hi):
        d = world()
        d[sid][LAST] = edge
        U._check_ranges(d, months_of(d))                                                                  # the limit itself is inside
    d = world()
    d[sid][LAST] = lo - step
    refused(d, edge_message(sid, lo - step, lo, hi))
    d = world()
    d[sid][LAST] = hi + step
    refused(d, edge_message(sid, hi + step, lo, hi))


def test_the_oldest_month_that_is_out_of_range_speaks_first():
    d = world()
    d["BUSINV"][mback(LAST, 100)] = 399_999.0
    d["BUSINV"][mback(LAST, 20)] = 6_000_001.0
    refused(d, edge_message("BUSINV", 399_999.0, *LIMITS["BUSINV"], when=mback(LAST, 100)))


def test_the_first_series_in_the_list_that_is_out_of_range_speaks_first():
    d = world()
    d["RETAILIRSA"][LAST] = 5.0
    d["TOTBUSSMSA"][LAST] = 1.0
    refused(d, edge_message("TOTBUSSMSA", 1.0, *LIMITS["TOTBUSSMSA"]))


# ---------------------------------------------------------------- the two sums

@pytest.mark.parametrize("whole, text", [("BUSINV", "total inventories"), ("TOTBUSSMSA", "total sales")])
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("age", [0, 90, 179])
def test_a_total_that_is_two_million_off_its_three_kinds_passes_and_2_5_million_off_is_refused(whole, text, sign, age):
    when = mback(LAST, age)
    d = world()
    d[whole][when] += sign * 2.0
    assert run(d)["detail"]["largest_sum_gap"] == 2.0
    d = world()
    d[whole][when] += sign * 2.5
    refused(d, f"{text} are 2.5 million off the sum of the three kinds in {mlab(when)}, over 2")


def test_a_part_that_is_off_is_found_through_its_total():
    d = world()
    d["RETAILSMSA"][LAST] += 3.0
    refused(d, f"total sales are 3 million off the sum of the three kinds in {mlab(LAST)}, over 2")


def test_the_inventory_sum_speaks_before_the_sales_sum_and_the_oldest_month_before_the_newest():
    d = world()
    d["TOTBUSSMSA"][LAST] += 10.0
    d["BUSINV"][LAST] += 5.0
    refused(d, f"total inventories are 5 million off the sum of the three kinds in {mlab(LAST)}, over 2")
    d = world()
    d["BUSINV"][LAST] += 5.0
    d["BUSINV"][mback(LAST, 60)] += 9.0
    refused(d, f"total inventories are 9 million off the sum of the three kinds in {mlab(mback(LAST, 60))}, over 2")


def test_the_largest_gap_of_either_sum_is_kept_in_the_detail():
    d = world()
    d["BUSINV"][mback(LAST, 3)] += 1.0
    d["TOTBUSSMSA"][mback(LAST, 9)] -= 2.0
    assert run(d)["detail"]["largest_sum_gap"] == 2.0
    d = world()
    d["BUSINV"][mback(LAST, 3)] -= 2.0
    d["TOTBUSSMSA"][mback(LAST, 9)] += 1.0
    assert run(d)["detail"]["largest_sum_gap"] == 2.0


def test_the_largest_sum_gap_is_kept_to_five_decimals():
    d = world()
    d["BUSINV"][LAST] += 1.23456
    assert run(d)["detail"]["largest_sum_gap"] == pytest.approx(1.23456, abs=1e-9)
    assert run(d)["detail"]["largest_sum_gap"] != round(1.23456, 4)


def test_a_change_over_nothing_is_none_and_a_tiny_fall_is_zero_not_minus_zero():
    assert U._change(5.0, None) is None and U._change(5.0, 0.0) is None
    assert U._change(105.0, 100.0) == 5.0 and U._change(95.0, 100.0) == -5.0 and U._change(100.0, 100.0) == 0.0
    assert str(U._change(99.99999, 100.0)) == "0.0"


# ---------------------------------------------------------------- the four ratios

@pytest.mark.parametrize("ratio, inv, sales", RATIOS)
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("age", [0, 90, 179])
def test_a_published_ratio_half_a_hundredth_off_inventories_over_sales_passes_and_two_hundredths_over_that_is_refused(ratio, inv, sales, sign, age):
    when = mback(LAST, age)
    d = world(base=EXACT)
    d[ratio][when] = 1.25 + sign * 0.005
    assert run(d)["detail"]["largest_ratio_gap"] == pytest.approx(0.005)
    d = world(base=EXACT)
    d[ratio][when] = 1.25 + sign * 0.0052
    refused(d, f"{NAME[ratio]} {1.25 + sign * 0.0052:.2f} is 0.0052 off inventories over sales in {mlab(when)}, over 0.0051")


def test_a_ratio_that_is_a_hundredth_off_is_refused_with_the_two_figures_in_the_message():
    d = world(base=EXACT)
    d["MNFCTRIRSA"][LAST] = 1.26
    refused(d, "manufacturers' ratio 1.26 is 0.0100 off inventories over sales in 2026-09, over 0.0051")


def test_the_total_ratio_speaks_before_the_three_sector_ratios_and_a_sum_speaks_before_any_ratio():
    d = world(base=EXACT)
    d["RETAILIRSA"][LAST] = 1.4
    d["ISRATIO"][LAST] = 1.3
    refused(d, "total ratio 1.30 is 0.0500 off inventories over sales in 2026-09, over 0.0051")
    d = world(base=EXACT)
    d["RETAILIRSA"][LAST] = 1.4
    d["TOTBUSSMSA"][LAST] += 5.0
    refused(d, "total sales are 5 million off the sum of the three kinds in 2026-09, over 2")
    d = world(base=EXACT)
    d["RETAILIRSA"][mback(LAST, 50)] = 1.4
    d["MNFCTRIRSA"][LAST] = 1.4
    refused(d, "manufacturers' ratio 1.40 is 0.1500 off inventories over sales in 2026-09, over 0.0051")


@pytest.mark.parametrize("first, second", [("ISRATIO", "MNFCTRIRSA"), ("MNFCTRIRSA", "WHLSLRIRSA"), ("WHLSLRIRSA", "RETAILIRSA")])
def test_the_ratios_speak_in_this_order_total_manufacturers_wholesalers_retailers(first, second):
    d = world(base=EXACT)
    d[first][LAST] = 1.4
    d[second][LAST] = 1.4
    refused(d, f"{NAME[first]} 1.40 is 0.1500 off inventories over sales in 2026-09, over 0.0051")


def test_the_oldest_month_of_a_ratio_speaks_first():
    d = world(base=EXACT)
    d["WHLSLRIRSA"][mback(LAST, 100)] = 1.4
    d["WHLSLRIRSA"][mback(LAST, 10)] = 1.5
    refused(d, f"wholesalers' ratio 1.40 is 0.1500 off inventories over sales in {mlab(mback(LAST, 100))}, over 0.0051")


def test_a_range_speaks_before_a_sum_and_a_sum_before_a_ratio_and_the_months_before_both():
    d = world()
    d["BUSINV"][LAST] = 7_000_000.0
    refused(d, edge_message("BUSINV", 7_000_000.0, *LIMITS["BUSINV"]))                                    # also 4 million off the sum: the range comes first
    d = world()
    del d["TOTBUSSMSA"][LAST]
    d["BUSINV"][mback(LAST, 20)] = 7_000_000.0
    refused(d, "the inventory series end in different months")


# ---------------------------------------------------------------- the messages

def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    texts = [edge_message(sid, 1_234_567.5 if sid not in ("ISRATIO", "MNFCTRIRSA", "WHLSLRIRSA", "RETAILIRSA") else 12.34, *LIMITS[sid]) for sid in IDS]
    texts += [f"{t} are 1,234,567.5 million off the sum of the three kinds in 2026-09, over 2" for t in ("total inventories", "total sales")]
    texts += [f"{NAME[r]} 12.34 is 12.3456 off inventories over sales in 2026-09, over 0.0051" for r, _i, _s in RATIOS]
    texts += [f"the {NAME[s]} series covers different months than total inventories" for s in IDS[1:]]
    texts += ["the inventory series cover 119 months, fewer than the 120 expected", "the inventory months skip a month after 2024-12", "the inventory series end in different months", "an inventory date is not the 1st of a month"]
    for text in texts:
        assert len(text) <= 110, (len(text), text)
        assert fail_reason(ValueError(text)) == f"the data failed a check: {dates_in_words(text)}"


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_12_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = U.UsInventories(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["total"]["inventories_millions"] == 2873438.0 and n["n"] == 12 and r["demo"] is False and r["as_of"] == NOW.isoformat()
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 12


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(U.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = U.UsInventories(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 12
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 12
    clock["t"] += 1
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 24
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 24
    clock["t"] += 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 36


def test_without_a_time_the_question_is_asked_at_the_present_moment_in_utc():
    r = asyncio.run(U.UsInventories(client=_client(_handler)).overview())
    asked = datetime.fromisoformat(r["as_of"])
    assert asked.tzinfo is not None and asked.utcoffset() == timedelta(0)
    assert abs((datetime.now(timezone.utc) - asked).total_seconds()) < 60


def test_the_age_in_an_answer_is_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(U.UsInventories(client=_client(_handler)).overview(datetime(2027, 1, 15, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 136 and r["freshness"] == "OVERDUE"


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = U.UsInventories(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(U.UsInventories(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US business inventories and sales could not be read right now (the server had an error, HTTP 503)" and "total" not in r and "recent" not in r
    r = asyncio.run(U.UsInventories(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == "RETAILIRSA" else _handler(req)

    r = asyncio.run(U.UsInventories(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "total" not in r and "sectors" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    def answer(replace):
        bad = dict(F)
        for sid, (old, new) in replace.items():
            assert old in F[sid]
            bad[sid] = F[sid].replace(old, new)
        return asyncio.run(U.UsInventories(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))

    r = answer({"BUSINV": ("2026-09-01,2873438", "2026-09-01,28734380")})                                 # a decimal slip beyond the range
    assert r["available"] is False and r["reason"] == "US business inventories and sales could not be read right now (the data failed a check: total inventories of 28,734,380 in September 2026 is outside 400,000 to 6,000,000)" and "total" not in r
    r = answer({"BUSINV": ("2026-09-01,2873438", "2026-09-01,2873538")})                                  # a digit slip that stays inside every range: only the sum finds it
    assert r["available"] is False and r["reason"] == "US business inventories and sales could not be read right now (the data failed a check: total inventories are 100 million off the sum of the three kinds in September 2026, over 2)"
    r = answer({"RETAILIRSA": ("2026-09-01,1.35", "2026-09-01,1.45")})                                    # a ratio that no longer matches its two parts
    assert r["available"] is False and r["reason"] == "US business inventories and sales could not be read right now (the data failed a check: retailers' ratio 1.45 is 0.0978 off inventories over sales in September 2026, over 0.0051)"
    r = answer({"RETAILSMSA": ("2026-09-01,653943", "2026-09-01,x")})
    assert r["available"] is False and "a RETAILSMSA row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(U.UsInventories(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US business inventories and sales could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("BUSINV")

    monkeypatch.setattr(U, "summarize", boom)
    r = asyncio.run(U.UsInventories(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US business inventories and sales could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(U.UsInventories(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US business inventories and sales are not shown because made-up values would look real." and "total" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/us-inventories")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_card_is_refreshed_with_the_other_macro_sources():
    jobs = (Path(__file__).parent.parent / "atlas_api" / "sched" / "jobs.py").read_text(encoding="utf-8")
    app = (Path(__file__).parent.parent / "atlas_api" / "app.py").read_text(encoding="utf-8")
    assert '"us_inventories"' in jobs and '"us_inventories": us_inventories' in app and "us_inventories = UsInventories(demo=demo)" in app


def test_each_request_asks_for_one_series_from_1992_with_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(U.UsInventories(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)
    assert {req.url.params["cosd"] for req in seen} == {"1992-01-01"}


def test_no_more_than_six_requests_are_open_at_once():
    state = {"open": 0, "most": 0}

    async def slow(req):
        state["open"] += 1
        state["most"] = max(state["most"], state["open"])
        await asyncio.sleep(0.01)
        state["open"] -= 1
        return _handler(req)

    asyncio.run(U.UsInventories(client=_client(slow)).overview(NOW))
    assert state["most"] == 6


def test_a_client_made_here_waits_25_seconds_and_is_closed_and_one_given_is_left_open(monkeypatch):
    seen = {"closed": False}

    class Fake:
        def __init__(self, **kw):
            seen["timeout"] = kw.get("timeout")

        async def get(self, url, params=None):
            return httpx.Response(200, text=F[params["id"]])

        async def aclose(self):
            seen["closed"] = True

    monkeypatch.setattr(U.httpx, "AsyncClient", Fake)
    r = asyncio.run(U.UsInventories().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(U.UsInventories(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_module_says_why_each_series_is_asked_for_alone_and_what_it_does_not_check():
    doc = U.__doc__
    assert "ALONE" in doc and "NOT checked" in doc and "417 months" in doc and "EXACTLY" in doc and "0.004996" in doc
