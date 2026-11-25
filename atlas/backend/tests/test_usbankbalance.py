"""US bank balance sheet (Federal Reserve H.8 via FRED, 10 weekly series): the real saved record, the limits and tolerances as literals, one check at a time, the figures of the summary and the class."""
from __future__ import annotations

import asyncio
import json
import re
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import atlas_api.usbankbalance as U

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usbankbalance.json").read_text())
TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
LAST = date(2026, 11, 11)

TA, BC, LL, SEC, TAS = "TLAACBW027SBOG", "TOTBKCR", "TOTLL", "SBCACBW027SBOG", "TASACBW027SBOG"
OSE, CASH, DEP, TLB, RES = "OSEACBW027SBOG", "CASACBW027SBOG", "DPSACBW027SBOG", "TLBACBW027SBOG", "RALACBW027SBOG"
IDS = [TA, BC, LL, SEC, TAS, OSE, CASH, DEP, TLB, RES]
NAME = {TA: "total assets", BC: "bank credit", LL: "loans and leases", SEC: "securities", TAS: "Treasury and agency", OSE: "other securities", CASH: "cash assets",
        DEP: "deposits", TLB: "total liabilities", RES: "the residual"}
LIMITS = {TA: (7590.0, 52400.0), BC: (5290.0, 40300.0), LL: (3810.0, 28600.0), SEC: (1470.0, 11800.0), TAS: (1020.0, 9710.0), OSE: (410.0, 2350.0), CASH: (790.0, 8400.0),
          DEP: (5250.0, 39800.0), TLB: (6760.0, 47400.0), RES: (810.0, 5110.0)}
LEAVES = {LL: 14000.0, TAS: 4800.0, OSE: 1000.0, CASH: 3000.0, DEP: 19800.0, "rest_assets": 3000.0, "other_liabilities": 3800.0}     # every figure below is built from these, so every sum holds exactly


def mback(d, n):
    return d - timedelta(days=7 * n)


def num(v):
    s = f"{v:,.1f}"
    return s[:-2] if s.endswith(".0") else s


def real():
    return {sid: U.parse(F[sid], sid) for sid in IDS}


def build(leaves):
    v = {LL: leaves[LL], TAS: leaves[TAS], OSE: leaves[OSE], CASH: leaves[CASH], DEP: leaves[DEP]}
    v[SEC] = v[TAS] + v[OSE]
    v[BC] = v[LL] + v[SEC]
    v[TA] = v[BC] + v[CASH] + leaves["rest_assets"]
    v[TLB] = v[DEP] + leaves["other_liabilities"]
    v[RES] = v[TA] - v[TLB]
    return v


def world(n=620, last=LAST, **changed):
    one = build({**LEAVES, **changed})
    return {sid: {mback(last, i): v for i in range(n - 1, -1, -1)} for sid, v in one.items()}


def world_by(fn, n=620, last=LAST):
    data = {sid: {} for sid in IDS}
    for i in range(n - 1, -1, -1):
        for sid, v in build(fn(n - 1 - i)).items():
            data[sid][mback(last, i)] = v
    return data


STEPS = {LL: 2.0, TAS: 1.0, OSE: 0.5, CASH: 1.0, DEP: 3.0, "rest_assets": 0.5, "other_liabilities": 0.5}        # billions a week, every one exact in binary


def trend(k):
    return {name: v + STEPS[name] * k for name, v in LEAVES.items()}


def run(data, today=TODAY):
    return U.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        U.summarize(data, TODAY)


def pct1(new, old):
    return round(100.0 * (new - old) / old, 1)


def weeks_of(data):
    return sorted(data[TA])


# ---------------------------------------------------------------- the real record
def test_the_real_record_passes_every_check_and_gives_these_figures():
    r = run(real())
    assert (r["available"], r["date"], r["age_days"], r["freshness"]) == (True, "2026-11-11", 14, "CURRENT")
    assert r["source"] == U.SOURCE and r["url"] == "https://fred.stlouisfed.org/series/TLAACBW027SBOG"
    t = r["total"]
    assert (t["assets_billions"], t["change_week_billions"], t["change_week_pct"], t["change_year_billions"], t["change_year_pct"]) == (26143.8881, -27.5708, -0.1, 1677.297, 6.9)
    assert t["growth_range"] == {"weeks": 520, "first": "2016-11-30", "lowest": {"value": -0.8, "date": "2023-08-09"}, "highest": {"value": 18.6, "date": "2020-04-29"}, "share_lower_pct": 81}
    assert [(a["key"], a["label"], a["billions"], a["share_pct"], a["change_week_billions"], a["change_week_pct"], a["change_year_billions"], a["change_year_pct"]) for a in r["assets"]] == [
        ("loans", "Loans and leases", 14264.2085, 54.6, 38.2202, 0.3, 1033.1284, 7.8), ("securities", "Securities", 5868.9758, 22.4, 24.0599, 0.4, 203.6223, 3.6),
        ("cash", "Cash assets", 3078.6685, 11.8, -68.2578, -2.2, 119.844, 4.1), ("rest", "Everything else", 2932.0353, 11.2, -21.5931, -0.7, 320.7022, 12.3)]
    assert r["securities"] == [{"key": "treasury_agency", "label": "Treasury and agency securities", "billions": 4852.899, "share_pct": 82.7}, {"key": "other", "label": "Other securities", "billions": 1016.0768, "share_pct": 17.3}]
    li = r["liabilities"]
    assert (li["total_billions"], li["change_week_billions"], li["change_week_pct"], li["change_year_billions"], li["change_year_pct"]) == (23671.469, -10.079, 0.0, 1692.0113, 7.7)
    assert [(a["key"], a["label"], a["billions"], a["share_pct"], a["change_week_billions"], a["change_week_pct"], a["change_year_billions"], a["change_year_pct"]) for a in li["items"]] == [
        ("deposits", "Deposits", 19825.171, 83.8, -37.7014, -0.2, 1300.6152, 7.0), ("other", "Everything else", 3846.298, 16.2, 27.6224, 0.7, 391.3961, 11.3)]
    assert r["residual"] == {"billions": 2472.4192, "share_of_assets_pct": 9.5, "change_year_billions": -14.7142, "change_year_pct": -0.6}
    assert [(x["date"], x["total_billions"], x["change_billions"]) for x in r["recent"]] == [
        ("2026-10-07", 26091.2622, 78.1464), ("2026-10-14", 26126.9998, 35.7376), ("2026-10-21", 26084.5745, -42.4253), ("2026-10-28", 26083.3245, -1.25), ("2026-11-04", 26171.4589, 88.1344), ("2026-11-11", 26143.8881, -27.5708)]
    assert r["detail"] == {"weeks_checked": 619, "first_week": "2015-01-07", "last_week": "2026-11-11", "largest_sum_gap": 0.0001}
    assert r["checks"] == {"weeks_in_a_row": True, "range_ok": True, "sums_ok": True, "orders_ok": True}


def test_every_real_series_has_the_same_619_wednesdays_and_the_saved_record_is_the_one_the_limits_came_from():
    d = real()
    weeks = sorted(d[TA])
    assert len(weeks) == 619 and weeks[0] == date(2015, 1, 7) and weeks[-1] == LAST and all(w.weekday() == 2 for w in weeks)
    assert all(set(d[sid]) == set(weeks) for sid in IDS)
    for sid, (lo, hi) in LIMITS.items():
        assert lo <= min(d[sid].values()) and max(d[sid].values()) <= hi and lo <= min(d[sid].values()) * 0.55 and hi >= max(d[sid].values()) * 1.9


def test_the_series_the_limits_the_sums_and_the_orders_are_these_literals():
    assert U.SERIES == IDS and U.LIMITS == LIMITS and U.NAMES == NAME and U.START == "2015-01-07"
    assert U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and U.PAGE == "https://fred.stlouisfed.org/series/TLAACBW027SBOG"
    assert [(w, p, t, text) for w, p, t, text in U.SUMS] == [(BC, (LL, SEC), 0.00015, "loans plus securities"), (SEC, (TAS, OSE), 0.00015, "Treasury plus other securities"), (TA, (TLB, RES), 0.00015, "liabilities plus the residual")]
    assert [(w, p, text) for w, p, text in U.ORDERS] == [(TA, (BC, CASH), "bank credit plus cash assets"), (TLB, (DEP,), "deposits")]
    assert U.MIN_WEEKS == 572 and U.HISTORY_WEEKS == 520 and U.RECENT_WEEKS == 6 and U.OVERDUE_AFTER_DAYS == 18 and U.CONCURRENCY == 6 and U.TTL == 21600.0 and U.FAIL_TTL == 120.0
    assert U.WEEK == timedelta(days=7) and U.YEAR == timedelta(days=364)
    assert "Board of Governors of the Federal Reserve System, H.8 Assets and Liabilities of Commercial Banks, via FRED" in U.SOURCE


# ---------------------------------------------------------------- the default world and the changes
def test_the_default_world_passes_and_every_figure_is_the_one_built():
    r = run(world())
    t = r["total"]
    assert (t["assets_billions"], t["change_week_billions"], t["change_week_pct"], t["change_year_billions"], t["change_year_pct"]) == (25800.0, 0.0, 0.0, 0.0, 0.0)
    assert [(a["key"], a["billions"], a["share_pct"]) for a in r["assets"]] == [("loans", 14000.0, 54.3), ("securities", 5800.0, 22.5), ("cash", 3000.0, 11.6), ("rest", 3000.0, 11.6)]
    assert [(a["key"], a["billions"], a["share_pct"]) for a in r["securities"]] == [("treasury_agency", 4800.0, 82.8), ("other", 1000.0, 17.2)]
    li = r["liabilities"]
    assert li["total_billions"] == 23600.0 and [(a["key"], a["billions"], a["share_pct"]) for a in li["items"]] == [("deposits", 19800.0, 83.9), ("other", 3800.0, 16.1)]
    assert r["residual"] == {"billions": 2200.0, "share_of_assets_pct": 8.5, "change_year_billions": 0.0, "change_year_pct": 0.0}
    assert r["detail"] == {"weeks_checked": 620, "first_week": "2014-12-31", "last_week": "2026-11-11", "largest_sum_gap": 0.0}
    assert len(r["recent"]) == 6 and r["recent"][0]["date"] == "2026-10-07" and r["recent"][-1]["date"] == "2026-11-11" and r["recent"][-1]["change_billions"] == 0.0


def test_the_changes_are_worked_against_the_week_before_and_the_same_week_52_weeks_before():
    d = world_by(trend)
    last, before, ago = build(trend(619)), build(trend(618)), build(trend(619 - 52))
    r = run(d)
    t = r["total"]
    assert t["change_week_billions"] == round(last[TA] - before[TA], 4) and t["change_week_pct"] == pct1(last[TA], before[TA])
    assert t["change_year_billions"] == round(last[TA] - ago[TA], 4) and t["change_year_pct"] == pct1(last[TA], ago[TA])
    assert t["change_week_billions"] == 5.0 and t["change_year_billions"] == 260.0                  # 2.0 + 1.0 + 0.5 + 1.0 + 0.5 a week
    for x, sid in zip(r["assets"][:3], (LL, SEC, CASH)):
        assert (x["change_week_billions"], x["change_week_pct"]) == (round(last[sid] - before[sid], 4), pct1(last[sid], before[sid]))
        assert (x["change_year_billions"], x["change_year_pct"]) == (round(last[sid] - ago[sid], 4), pct1(last[sid], ago[sid]))
        assert x["share_pct"] == round(100.0 * last[sid] / last[TA], 1)
    rest = lambda v: v[TA] - v[BC] - v[CASH]
    x = r["assets"][3]
    assert (x["billions"], x["change_week_billions"], x["change_week_pct"], x["change_year_billions"], x["change_year_pct"]) == (rest(last), round(rest(last) - rest(before), 4), pct1(rest(last), rest(before)), round(rest(last) - rest(ago), 4), pct1(rest(last), rest(ago)))
    li = r["liabilities"]
    assert (li["change_week_billions"], li["change_week_pct"], li["change_year_billions"], li["change_year_pct"]) == (round(last[TLB] - before[TLB], 4), pct1(last[TLB], before[TLB]), round(last[TLB] - ago[TLB], 4), pct1(last[TLB], ago[TLB]))
    dep, other = li["items"]
    assert (dep["change_week_billions"], dep["change_year_billions"], dep["share_pct"]) == (round(last[DEP] - before[DEP], 4), round(last[DEP] - ago[DEP], 4), round(100.0 * last[DEP] / last[TLB], 1))
    oth = lambda v: v[TLB] - v[DEP]
    assert (other["billions"], other["change_week_billions"], other["change_year_billions"], other["change_year_pct"]) == (oth(last), round(oth(last) - oth(before), 4), round(oth(last) - oth(ago), 4), pct1(oth(last), oth(ago)))
    res = r["residual"]
    assert (res["billions"], res["change_year_billions"], res["change_year_pct"], res["share_of_assets_pct"]) == (last[RES], round(last[RES] - ago[RES], 4), pct1(last[RES], ago[RES]), round(100.0 * last[RES] / last[TA], 1))
    assert [x["share_pct"] for x in r["securities"]] == [round(100.0 * last[TAS] / last[SEC], 1), round(100.0 * last[OSE] / last[SEC], 1)]


def test_a_tiny_fall_that_rounds_to_nothing_is_zero_not_minus_zero():
    d = world()
    for sid in (TA, TLB):
        d[sid][LAST] -= 0.00001
    d[RES][LAST] -= 0.0
    r = run(d)
    t = r["total"]
    assert str(t["change_week_pct"]) == "0.0" and str(t["change_year_pct"]) == "0.0" and str(t["change_week_billions"]) == "0.0" and str(t["change_year_billions"]) == "0.0" and str(r["recent"][-1]["change_billions"]) == "0.0"
    assert str(r["liabilities"]["change_week_pct"]) == "0.0" and str(r["liabilities"]["change_week_billions"]) == "0.0"
    assert str(U._diff(5.0, 5.0)) == "0.0" and str(U._diff(5.0, 5.00001)) == "0.0" and U._diff(5.0, 3.0) == 2.0 and U._diff(3.0, 5.0) == -2.0 and U._diff(1.00006, 1.0) == 0.0001


def test_the_growth_range_is_the_ten_years_of_year_on_year_growth_and_counts_the_weeks_strictly_lower():
    r = run(world_by(trend))
    tot = lambda k: build(trend(k))[TA]
    vals = [pct1(tot(k), tot(k - 52)) for k in range(619 - 519, 620)]                      # the oldest of the 520 weeks first
    g = r["total"]["growth_range"]
    assert g["weeks"] == 520 and g["first"] == mback(LAST, 519).isoformat()
    assert g["lowest"]["value"] == min(vals) and g["highest"]["value"] == max(vals)
    assert g["lowest"]["date"] == mback(LAST, 619 - (619 - 519 + vals.index(min(vals)))).isoformat() and g["highest"]["date"] == mback(LAST, 619 - (619 - 519 + vals.index(max(vals)))).isoformat()
    assert g["share_lower_pct"] == round(100 * sum(1 for v in vals if v < vals[-1]) / 520)


def test_the_growth_range_ranks_the_newest_week_not_the_week_before():
    def jump(k):
        return {**LEAVES, "rest_assets": LEAVES["rest_assets"] + (300.0 if k == 619 else 0.0)}          # no growth in any earlier week, 300 of 25,800 in the newest
    g = run(world_by(jump))["total"]["growth_range"]
    assert g["highest"] == {"value": 1.2, "date": LAST.isoformat()} and g["lowest"] == {"value": 0.0, "date": mback(LAST, 519).isoformat()}
    assert g["share_lower_pct"] == 100                                                           # 519 of 520 weeks are lower than the newest


def test_the_share_of_weeks_lower_than_now_is_a_whole_number_rounded_to_the_nearest_percent():
    days = [date(2020, 1, 1) + timedelta(days=7 * i) for i in range(7)]
    r = U._range_weeks(dict(zip(days, [1.0, 2.0, 3.0, 5.0, 6.0, 7.0, 4.0])), 4.0, days[0])
    assert r["share_lower_pct"] == 43 and type(r["share_lower_pct"]) is int                      # 3 of 7 are lower: 42.857 is 43, not 42 and not 42.9
    r = U._range_weeks(dict(zip(days, [1.0, 2.0, 5.0, 6.0, 7.0, 8.0, 9.0])), 5.0, days[0])
    assert r["share_lower_pct"] == 29                                                            # 2 of 7: 28.571
    r = U._range_weeks(dict(zip(days, [1.0, 2.0, 5.0, 6.0, 7.0, 8.0, 9.0])), 100.0, days[0])
    assert r["share_lower_pct"] == 100 and r["weeks"] == 7 and r["first"] == "2020-01-01"
    r = U._range_weeks(dict(zip(days, [4.0] * 7)), 4.0, days[0])
    assert r["share_lower_pct"] == 0 and r["lowest"]["date"] == "2020-01-01" and r["highest"]["date"] == "2020-01-01"


def test_the_six_recent_weeks_have_their_own_totals_and_the_oldest_comes_first():
    r = run(world_by(trend))
    assert [x["date"] for x in r["recent"]] == [mback(LAST, i).isoformat() for i in range(5, -1, -1)]
    for x, i in zip(r["recent"], range(5, -1, -1)):
        k = 619 - i
        assert (x["total_billions"], x["change_billions"]) == (build(trend(k))[TA], round(build(trend(k))[TA] - build(trend(k - 1))[TA], 4))


def test_freshness_is_current_for_18_days_from_the_wednesday_and_overdue_after():
    d = world()
    assert run(d, LAST + timedelta(days=18))["freshness"] == "CURRENT" and run(d, LAST + timedelta(days=18))["age_days"] == 18
    assert run(d, LAST + timedelta(days=19))["freshness"] == "OVERDUE"


# ---------------------------------------------------------------- the weeks
@pytest.mark.parametrize("sid", IDS)
def test_series_that_end_in_different_weeks_are_refused_whichever_series_is_short(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the bank balance sheet series end in different weeks")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_that_covers_other_weeks_than_total_assets_is_refused_by_name(sid):
    d = world()
    del d[sid][mback(LAST, 50)]
    refused(d, f"the {NAME[sid]} series covers different weeks than total assets")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_an_extra_week_is_refused_by_name(sid):
    d = world()
    d[sid][mback(LAST, 700)] = d[sid][LAST]
    refused(d, f"the {NAME[sid]} series covers different weeks than total assets")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_as_many_weeks_but_one_of_them_different_is_refused_by_name(sid):
    d = world()
    value = d[sid].pop(mback(LAST, 50))
    d[sid][mback(LAST, 700)] = value
    refused(d, f"the {NAME[sid]} series covers different weeks than total assets")


def test_a_date_that_is_not_a_wednesday_is_refused():
    d = {sid: {(k + timedelta(days=1) if k == mback(LAST, 100) else k): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a bank balance sheet date is not a Wednesday")


@pytest.mark.parametrize("age", [618, 300, 1])
def test_a_skipped_week_is_refused_after_the_week_before_the_gap_whether_it_is_next_to_the_oldest_in_the_middle_or_next_to_the_newest(age):
    gone = mback(LAST, age)
    d = {sid: {k: v for k, v in s.items() if k != gone} for sid, s in world().items()}
    refused(d, f"the bank balance sheet weeks skip a week after {mback(LAST, age + 1).isoformat()}")


def test_fewer_than_572_weeks_are_refused_and_572_are_enough():
    refused(world(n=571), "the bank balance sheet series cover 571 weeks, fewer than the 572 expected")
    assert run(world(n=572))["detail"]["weeks_checked"] == 572


def test_every_week_check_speaks_before_the_ranges():
    short = world(n=571)
    short[TA][LAST] = 99999.0
    refused(short, "the bank balance sheet series cover 571 weeks, fewer than the 572 expected")
    other = world()
    del other[CASH][mback(LAST, 50)]
    other[TA][LAST] = 99999.0
    refused(other, f"the {NAME[CASH]} series covers different weeks than total assets")


# ---------------------------------------------------------------- the ranges
def edge_message(sid, v, lo, hi, when=LAST):
    return f"{NAME[sid]} of {num(v)} on {when.isoformat()} is outside {num(lo)} to {num(hi)}"


@pytest.mark.parametrize("sid", IDS)
def test_a_value_just_under_the_lower_limit_or_just_over_the_upper_one_is_refused_and_the_limits_themselves_are_not(sid):
    lo, hi = LIMITS[sid]
    for edge in (lo, hi):
        d = world()
        d[sid][LAST] = edge
        U._check_ranges(d, weeks_of(d))
    d = world()
    d[sid][LAST] = lo - 0.5
    refused(d, edge_message(sid, lo - 0.5, lo, hi))
    d = world()
    d[sid][LAST] = hi + 0.5
    refused(d, edge_message(sid, hi + 0.5, lo, hi))


@pytest.mark.parametrize("sid", IDS)
def test_the_oldest_week_of_every_series_is_checked_against_its_range_too(sid):
    lo, hi = LIMITS[sid]
    first = weeks_of(world())[0]
    assert first == mback(LAST, 619)
    for bad in (lo - 0.5, hi + 0.5):
        d = world()
        d[sid][first] = bad
        refused(d, edge_message(sid, bad, lo, hi, when=first))


def test_the_oldest_week_that_is_out_of_range_speaks_first_and_the_first_series_in_the_list_speaks_first():
    d = world()
    d[TA][mback(LAST, 100)] = 3000.0
    d[TA][mback(LAST, 20)] = 99999.0
    refused(d, edge_message(TA, 3000.0, *LIMITS[TA], when=mback(LAST, 100)))
    d = world()
    d[RES][LAST] = 100.0
    d[BC][LAST] = 100.0
    refused(d, edge_message(BC, 100.0, *LIMITS[BC]))


# ---------------------------------------------------------------- the sums
def shifted(data, week, sids, gap):
    for sid in sids:
        data[sid][week] += gap
    return data


UPSTREAM = {0: (BC,), 1: (SEC, BC), 2: (TA,)}                 # the whole of a relation and the wholes above it: shifting all keeps every other sum exact (the three sums share no series but the securities)


@pytest.mark.parametrize("which, small, large, text", [(0, 0.0001, 0.0002, "loans plus securities"), (1, 0.0001, 0.0002, "Treasury plus other securities"), (2, 0.0001, 0.0002, "liabilities plus the residual")])
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("age", [0, 300, 619])
def test_a_gap_inside_the_rounding_of_the_figures_passes_and_one_unit_more_is_refused_for_each_sum_both_signs_in_three_weeks(which, small, large, text, sign, age):
    whole = U.SUMS[which][0]
    week = mback(LAST, age)
    assert run(shifted(world(), week, UPSTREAM[which], sign * small))["detail"]["largest_sum_gap"] == pytest.approx(small, abs=1e-6)
    with pytest.raises(ValueError) as e:
        U.summarize(shifted(world(), week, UPSTREAM[which], sign * large), TODAY)
    assert str(e.value) == f"{NAME[whole]} is {large:.4f} billion off {text} on {week.isoformat()}, over 0.00015"


@pytest.mark.parametrize("which, part", [(0, LL), (0, SEC), (1, TAS), (1, OSE), (2, TLB), (2, RES)])
def test_every_part_of_every_sum_counts(which, part):
    whole, parts, tol, text = U.SUMS[which]
    d = world()
    d[part][LAST] += 1.0
    with pytest.raises(ValueError) as e:
        U.summarize(d, TODAY)
    msg = str(e.value)
    assert msg.startswith(f"{NAME[whole]} is 1.0000 billion off ") or msg.startswith(f"{NAME[SEC]} is 1.0000 billion off ") or msg.startswith(f"{NAME[BC]} is 1.0000 billion off ")


def test_a_part_that_moves_alone_breaks_the_sum_it_belongs_to_and_names_it():
    d = world()
    d[LL][LAST] += 1.0
    refused(d, f"bank credit is 1.0000 billion off loans plus securities on {LAST.isoformat()}, over 0.00015")
    d = world()
    d[TAS][LAST] += 1.0
    refused(d, f"securities is 1.0000 billion off Treasury plus other securities on {LAST.isoformat()}, over 0.00015")
    d = world()
    d[RES][LAST] += 1.0
    refused(d, f"total assets is 1.0000 billion off liabilities plus the residual on {LAST.isoformat()}, over 0.00015")
    d = world()
    d[TLB][LAST] += 1.0
    refused(d, f"total assets is 1.0000 billion off liabilities plus the residual on {LAST.isoformat()}, over 0.00015")


def test_the_sums_are_checked_one_relation_at_a_time_in_the_listed_order_each_from_its_oldest_week():
    d = shifted(world(), mback(LAST, 100), UPSTREAM[1], 5.0)
    shifted(d, LAST, UPSTREAM[0], 5.0)
    refused(d, f"bank credit is 5.0000 billion off loans plus securities on {LAST.isoformat()}, over 0.00015")
    d = shifted(world(), mback(LAST, 100), UPSTREAM[2], 5.0)
    shifted(d, mback(LAST, 10), UPSTREAM[1], 5.0)
    refused(d, f"securities is 5.0000 billion off Treasury plus other securities on {mback(LAST, 10).isoformat()}, over 0.00015")
    d = shifted(world(), LAST, UPSTREAM[2], 5.0)
    shifted(d, mback(LAST, 100), UPSTREAM[2], 5.0)
    refused(d, f"total assets is 5.0000 billion off liabilities plus the residual on {mback(LAST, 100).isoformat()}, over 0.00015")


def test_the_largest_gap_is_kept_over_all_the_relations_and_weeks_to_five_decimals():
    d = shifted(world(), mback(LAST, 7), UPSTREAM[0], 0.00012)
    shifted(d, mback(LAST, 9), UPSTREAM[2], -0.00006)
    assert run(d)["detail"]["largest_sum_gap"] == 0.00012
    d = shifted(world(), mback(LAST, 7), UPSTREAM[0], 0.00004)
    shifted(d, mback(LAST, 9), UPSTREAM[2], -0.00009)
    assert run(d)["detail"]["largest_sum_gap"] == 0.00009
    d = shifted(world(), mback(LAST, 7), UPSTREAM[0], 0.000041)
    assert run(d)["detail"]["largest_sum_gap"] == 0.00004                # 4.1e-05 kept to five decimals: not 0.000041


# ---------------------------------------------------------------- the orders
def test_total_assets_may_equal_bank_credit_plus_cash_assets_but_not_fall_below_them():
    d = world(rest_assets=0.0, other_liabilities=800.0)                    # nothing but bank credit and cash on the asset side (the residual stays 2,200)
    assert run(d)["assets"][3]["billions"] == 0.0 and run(d)["assets"][3]["share_pct"] == 0.0
    d = world()
    d[CASH][LAST] = 6000.0                                   # 19,800 + 6,000 = 25,800 = total assets
    assert run(d)["assets"][2]["billions"] == 6000.0
    d[CASH][LAST] = 6000.5
    refused(d, f"total assets of 25,800 are below bank credit plus cash assets of 25,800.5 on {LAST.isoformat()}")


def test_total_liabilities_may_equal_deposits_but_not_fall_below_them():
    d = world()
    d[DEP][LAST] = 23600.0
    assert run(d)["liabilities"]["items"][0]["billions"] == 23600.0
    d[DEP][LAST] = 23600.5
    refused(d, f"total liabilities of 23,600 are below deposits of 23,600.5 on {LAST.isoformat()}")


@pytest.mark.parametrize("age", [619, 300])
def test_each_order_is_checked_in_the_oldest_week_and_the_oldest_failing_week_speaks_first(age):
    first = mback(LAST, 619)
    d = world()
    d[CASH][mback(LAST, age)] = 7000.0
    d[CASH][mback(LAST, 10)] = 7000.0
    refused(d, f"total assets of 25,800 are below bank credit plus cash assets of 26,800 on {mback(LAST, age).isoformat()}")
    d = world()
    d[DEP][mback(LAST, age)] = 23700.0
    d[DEP][mback(LAST, 10)] = 23800.0
    refused(d, f"total liabilities of 23,600 are below deposits of 23,700 on {mback(LAST, age).isoformat()}")
    assert first == weeks_of(world())[0]


def test_the_orders_are_checked_one_at_a_time_in_the_listed_order():
    d = world()
    d[CASH][LAST] = 7000.0
    d[DEP][mback(LAST, 100)] = 23700.0
    refused(d, f"total assets of 25,800 are below bank credit plus cash assets of 26,800 on {LAST.isoformat()}")


def test_a_range_speaks_before_a_sum_and_a_sum_before_an_order():
    d = world()
    d[TA][LAST] = 99999.0
    refused(d, edge_message(TA, 99999.0, *LIMITS[TA]))
    d = world()
    d[LL][LAST] += 1.0
    d[CASH][LAST] = 7000.0
    refused(d, f"bank credit is 1.0000 billion off loans plus securities on {LAST.isoformat()}, over 0.00015")


def test_a_change_over_nothing_is_none_and_a_tiny_fall_is_zero():
    assert U._change(5.0, None) is None and U._change(5.0, 0.0) is None
    assert U._change(105.0, 100.0) == 5.0 and U._change(95.0, 100.0) == -5.0 and U._change(100.0, 100.0) == 0.0 and str(U._change(99.99999, 100.0)) == "0.0"


# ---------------------------------------------------------------- the messages
def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    texts = [edge_message(sid, 12_345_678.5, *LIMITS[sid]) for sid in IDS]
    texts += [f"{NAME[w]} is 1234567.5000 billion off {text} on 2026-11-11, over {tol:g}" for w, _, tol, text in U.SUMS]
    texts += [f"{NAME[w]} of 12,345,678.5 are below {text} of 12,345,678 on 2026-11-11" for w, _, text in U.ORDERS]
    texts += [f"the {NAME[s]} series covers different weeks than total assets" for s in IDS[1:]]
    texts += ["the bank balance sheet series cover 571 weeks, fewer than the 572 expected", "the bank balance sheet weeks skip a week after 2024-12-25", "the bank balance sheet series end in different weeks", "a bank balance sheet date is not a Wednesday"]
    assert all(len(t) <= 110 for t in texts), [t for t in texts if len(t) > 110]


def test_the_note_is_short_says_what_it_does_not_check_and_never_forecasts():
    note = run(world())["note"]
    assert len(note) <= 1100 and note.endswith("it is not a market signal or a forecast.") and note.count("the Check line") == 1


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
    c = U.UsBankBalance(client=make_client(world(), seen), demo=True)
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is True and r["reason"] == "Demo mode: the real US bank balance sheet figures are not shown because made-up values would look real." and seen == []
    assert "total" not in r and r["as_of"] == NOW.isoformat()


def test_one_request_per_series_each_with_its_id_and_the_start_date_and_six_at_a_time():
    seen, stats = [], {"now": 0, "peak": 0}
    c = U.UsBankBalance(client=make_client(world(), seen, delay=0.01, stats=stats))
    r = arun(c.overview(NOW))
    assert r["available"] is True and r["demo"] is False and r["date"] == "2026-11-11" and r["age_days"] == 14
    assert sorted(x["id"] for x in seen) == sorted(IDS) and all(x == {"id": x["id"], "cosd": "2015-01-07"} for x in seen)
    assert stats["peak"] == 6


def test_a_good_answer_is_kept_for_six_hours_and_asked_again_after_that(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(U, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    seen = []
    c = U.UsBankBalance(client=make_client(world(), seen))
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
    c = U.UsBankBalance(client=make_client(world(), seen, status=500))
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is False and r["reason"].startswith("US bank balance sheet could not be read right now (") and "total" not in r
    n = len(seen)
    clock[0] += 119.0
    arun(c.overview(NOW))
    assert len(seen) == n
    clock[0] += 1.0
    arun(c.overview(NOW))
    assert len(seen) > n


def test_a_figure_that_fails_a_check_is_named_in_words_with_its_date_in_words():
    d = world()
    d[TA][LAST] = 261438.881
    r = arun(U.UsBankBalance(client=make_client(d)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US bank balance sheet could not be read right now (the data failed a check: total assets of 261,438.9 on November 11, 2026 is outside 7,590 to 52,400)" and "total" not in r


def test_a_client_it_makes_itself_is_closed_and_one_it_is_given_is_not(monkeypatch):
    made, instances = [], []

    class Own(REAL_CLIENT):
        def __init__(self, **kw):
            made.append(kw)
            instances.append(self)
            super().__init__(transport=transport_for(world()))

    monkeypatch.setattr(U.httpx, "AsyncClient", Own)
    c = U.UsBankBalance()
    assert arun(c.overview(NOW))["available"] is True and made == [{"timeout": 25}] and instances[0].is_closed is True
    given = make_client(world())
    arun(U.UsBankBalance(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_default_clock_is_utc_and_stamps_the_answer():
    r = arun(U.UsBankBalance(client=make_client(world())).overview())
    stamp = datetime.fromisoformat(r["as_of"])
    assert stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0) and abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


def test_each_request_goes_with_the_clients_own_user_agent_and_nothing_added():
    seen, data = [], world()

    async def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsBankBalance(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(seen) == 10 and all(ua.startswith("python-httpx/") for ua in seen)


def test_a_dropped_connection_a_timeout_and_a_missing_key_read_plainly(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("")

    def slow(request):
        raise httpx.ReadTimeout("")

    for fail, words in ((boom, "the connection could not be made"), (slow, "the request timed out")):
        r = arun(U.UsBankBalance(client=REAL_CLIENT(transport=httpx.MockTransport(fail))).overview(NOW))
        assert r["available"] is False and r["reason"] == f"US bank balance sheet could not be read right now ({words})"

    def no_key(data, today):
        raise KeyError("TLAACBW027SBOG")

    monkeypatch.setattr(U, "summarize", no_key)
    r = arun(U.UsBankBalance(client=make_client(world())).overview(NOW))
    assert r["available"] is False and r["reason"] == "US bank balance sheet could not be read right now (the answer was not in the expected shape)"


def test_any_answer_but_200_is_refused_with_its_status_in_words():
    r = arun(U.UsBankBalance(client=make_client(world(), status=500)).overview(NOW))
    assert r["reason"] == "US bank balance sheet could not be read right now (the server had an error, HTTP 500)"
    r = arun(U.UsBankBalance(client=make_client(world(), status=204)).overview(NOW))
    assert r["reason"] == "US bank balance sheet could not be read right now (the server answered HTTP 204)"


def test_the_clock_decides_the_age_not_the_computer_date():
    c = U.UsBankBalance(client=make_client(world()))
    r = arun(c.overview(datetime(2026, 12, 8, 1, tzinfo=timezone.utc)))
    assert r["age_days"] == 27 and r["freshness"] == "OVERDUE"
