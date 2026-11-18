"""US job openings and labour turnover (BLS JOLTS, with payroll employment and unemployed persons, via FRED): parsed from real responses (fetched 2026-11-18 17:28 UTC: the 12 JOLTS series have 310 monthly values each, 2000-12 to 2026-09; payroll employment and unemployed persons 322 each, 2000-01 to 2026-10). Every expected figure below was worked by hand from those files before the provider existed (openings 7,523 thousand and 4.5% in 2026-09, 7,190 a month before and 7,169 a year before; 1.058 openings per unemployed person; the 120-month ranges), and the limits are literals set from the whole record, not read back from the module. The synthetic worlds use payroll employment of 120,000 thousand, openings of 8,000 and 8,000 unemployed so that every rate is exact in binary (6.25, 5, 4, 2, 1.5, 0.5) and the edge of each limit can be reached to the last bit."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import jolts as J
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_jolts.json").read_text())
TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)
AFTER = date(2026, 10, 1)                                                           # payroll employment and unemployed persons come out a month before JOLTS does

LEVELS = ("JTSJOL", "JTSHIL", "JTSTSL", "JTSQUL", "JTSLDL", "JTSOSL")
RATES = ("JTSJOR", "JTSHIR", "JTSTSR", "JTSQUR", "JTSLDR", "JTSOSR")
PAIRS = dict(zip(LEVELS, RATES))
JOLTS12 = (*LEVELS, *RATES)
IDS = (*JOLTS12, "PAYEMS", "UNEMPLOY")
LEVEL_NAME = {"JTSJOL": "job openings", "JTSHIL": "hires", "JTSTSL": "total separations", "JTSQUL": "quits", "JTSLDL": "layoffs and discharges", "JTSOSL": "other separations"}
NAME = {**LEVEL_NAME, **{PAIRS[k]: f"{v} rate" for k, v in LEVEL_NAME.items()}}
BASE = {"JTSJOL": 8000.0, "JTSHIL": 6000.0, "JTSTSL": 4800.0, "JTSQUL": 2400.0, "JTSLDL": 1800.0, "JTSOSL": 600.0}
PAYROLLS = 120000.0
UNEMPLOYED = 8000.0


def back(d, n):
    y, m = d.year, d.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def lab(d):
    return f"{d.year}-{d.month:02d}"


def real():
    return {sid: J.parse(F[sid], sid) for sid in IDS}


def calc(data, lv, d):
    """The rate a level gives against payroll employment (openings: against payrolls plus openings), in percent, worked here."""
    pay = data["PAYEMS"][d]
    return 100.0 * data[lv][d] / (pay + data[lv][d] if lv == "JTSJOL" else pay)


def sync(data):
    """Every published rate set to what its level gives (nine decimals: exact for the base world)."""
    for lv, rt in PAIRS.items():
        data[rt] = {d: round(calc(data, lv, d), 9) for d in data[lv]}
    return data


def world(n=130):
    """`n` months ending 2026-09 with every check satisfied exactly; payroll employment and unemployed persons also have 2026-10."""
    months = [back(LAST, i) for i in range(n - 1, -1, -1)]
    data = {lv: {d: BASE[lv] for d in months} for lv in LEVELS}
    data["PAYEMS"] = {d: PAYROLLS for d in [*months, AFTER]}
    data["UNEMPLOY"] = {d: UNEMPLOYED for d in [*months, AFTER]}
    return sync(data)


def run(data, today=TODAY):
    return J.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        J.summarize(data, TODAY)


MID = back(LAST, 50)                                                                # 2022-07: a month in the middle of every world, so that "the check looks at every month" is tested


def test_the_series_and_the_limits_are_the_ones_set_from_the_whole_record():
    assert list(J.SERIES) == list(IDS)
    assert J.LEVELS == LEVEL_NAME and J.RATES == dict(zip(RATES, LEVELS))
    assert J.LEVEL_LIMITS == (100.0, 50000.0)                                       # the real range is 237 to 16,275 thousand
    assert J.PAYROLL_LIMITS == (100000.0, 250000.0)                                 # the real range since 2000 is 129,706 to 159,293 thousand
    assert J.UNEMPLOYED_LIMITS == (2000.0, 40000.0)                                 # the real range since 2000 is 5,634 to 23,084 thousand
    assert J.SEPARATIONS_TOLERANCE == 2.0                                           # four values each rounded to a thousand: the real largest gap is 1.0
    assert J.RATE_TOLERANCE == 0.0625 and J.RATE_TOLERANCE == 2 ** -4               # half a unit of the published decimal plus the rounding of a level and of payrolls: the real largest gap is 0.0504
    assert (J.MIN_MONTHS, J.HISTORY_MONTHS, J.OVERDUE_AFTER_DAYS, J.LOOKBACK_DAYS) == (120, 120, 105, 4200)
    assert (J.TTL, J.FAIL_TTL) == (21600.0, 120.0)


def test_the_saved_files_are_the_real_record_fetched_for_this_card():
    assert set(F) == set(IDS)
    assert all(F[s].startswith(f"observation_date,{s}\n") for s in IDS)
    assert {s: F[s].count("\n") - 1 for s in IDS} == {**{s: 310 for s in JOLTS12}, "PAYEMS": 322, "UNEMPLOY": 322}
    r = real()
    assert min(r["JTSJOL"]) == date(2000, 12, 1) and max(r["JTSJOL"]) == LAST and max(r["PAYEMS"]) == AFTER == max(r["UNEMPLOY"]) and min(r["PAYEMS"]) == date(2000, 1, 1)


def test_missing_values_are_skipped_never_filled():
    s = J.parse("observation_date,JTSJOL\n2026-07-01,7335\n2026-08-01,.\n2026-09-01,\n", "JTSJOL")
    assert s == {date(2026, 7, 1): 7335.0}


def test_the_whole_real_record_passes_every_check_and_the_largest_gaps_are_the_ones_found_beforehand():
    s = run(real())
    assert s["detail"] == {"months_checked": 310, "first_month": "2000-12", "last_month": "2026-09", "largest_separations_gap": 1.0, "largest_rate_gap": 0.0504}      # 0.050431 (hires, 2002-12)
    assert s["checks"] == {"months_in_a_row": True, "range_ok": True, "separations_add_up_ok": True, "rates_follow_levels_ok": True}


def test_the_download_the_card_makes_gives_the_same_card():
    cut = date(2015, 5, 1)                                                          # 4,200 days before 2026-11-18 is 2015-05-20, and FRED returns the month that contains it
    short = {sid: {d: v for d, v in s.items() if d >= cut} for sid, s in real().items()}
    a, b = run(short), run(real())
    assert a["detail"] == {"months_checked": 137, "first_month": "2015-05", "last_month": "2026-09", "largest_separations_gap": 1.0, "largest_rate_gap": 0.0501}      # 0.050063 (openings, 2024-08)
    assert all(a[k] == b[k] for k in ("date", "month", "age_days", "freshness", "openings", "per_unemployed", "flows"))


def test_latest_month_openings_and_openings_per_unemployed_person_by_hand():
    s = run(real())
    assert (s["date"], s["month"], s["age_days"], s["freshness"]) == ("2026-09-01", "2026-09", 78, "CURRENT")
    assert s["openings"] == {"level_thousands": 7523.0, "rate_pct": 4.5, "rate_year_ago_pct": 4.3, "change_1m_thousands": 333.0, "change_1y_pct": 4.9,           # 7,523 against 7,190 (+333) and 7,169 (+4.94%)
                             "range": {"months": 120, "first": "2016-10", "lowest": {"value": 3.4, "month": "2020-04"}, "highest": {"value": 7.5, "month": "2022-03"}, "share_lower_pct": 39}}      # 47 of the 120 months had a lower rate than 4.5
    assert s["per_unemployed"] == {"ratio": 1.06, "month": "2026-09", "unemployed_thousands": 7109.0, "year_ago": 0.94,                                        # 7,523 / 7,109 = 1.0582; 7,169 / 7,605 = 0.9427
                                   "range": {"months": 119, "first": "2016-10", "lowest": {"value": 0.2, "month": "2020-04"}, "highest": {"value": 2.04, "month": "2022-03"}, "share_lower_pct": 44}}      # 4,606 / 23,084 = 0.1995; 12,301 / 6,033 = 2.039; 52 of 119 months were lower; 2025-10 has no unemployed figure


def test_the_five_flows_by_hand_and_their_order():
    s = run(real())
    assert s["flows"] == [
        {"id": "hires", "name": "hires", "level_thousands": 5402.0, "rate_pct": 3.4, "rate_year_ago_pct": 3.3, "change_1y_pct": 3.0},                              # 5,402 against 5,244: +3.01%
        {"id": "separations", "name": "total separations", "level_thousands": 5319.0, "rate_pct": 3.3, "rate_year_ago_pct": 3.3, "change_1y_pct": 3.1},         # 5,319 against 5,161: +3.06%
        {"id": "quits", "name": "quits", "level_thousands": 3365.0, "rate_pct": 2.1, "rate_year_ago_pct": 1.9, "change_1y_pct": 12.5},                           # 3,365 against 2,990: +12.54%
        {"id": "layoffs", "name": "layoffs and discharges", "level_thousands": 1641.0, "rate_pct": 1.0, "rate_year_ago_pct": 1.1, "change_1y_pct": -9.6},      # 1,641 against 1,816: -9.64%
        {"id": "other", "name": "other separations", "level_thousands": 313.0, "rate_pct": 0.2, "rate_year_ago_pct": 0.2, "change_1y_pct": -12.1},             # 313 against 356: -12.08%
    ]


def test_a_clean_exact_world_passes_with_no_gap_at_all():
    s = run(world())
    assert s["detail"] == {"months_checked": 130, "first_month": lab(back(LAST, 129)), "last_month": "2026-09", "largest_separations_gap": 0.0, "largest_rate_gap": 0.0}
    assert s["openings"]["rate_pct"] == 6.25 and [f["rate_pct"] for f in s["flows"]] == [5.0, 4.0, 2.0, 1.5, 0.5]
    assert s["per_unemployed"]["ratio"] == 1.0 and s["per_unemployed"]["unemployed_thousands"] == 8000.0


# ---------------------------------------------------------------- the checks, one at a time, in the order the module makes them

def test_series_that_end_in_different_months_are_refused():
    for sid in JOLTS12:
        d = world()
        del d[sid][LAST]
        refused(d, "the JOLTS series end in different months")
        d = world()
        d[sid][AFTER] = d[sid][LAST]                                                # a series a month AHEAD of the others
        refused(d, "the JOLTS series end in different months")


@pytest.mark.parametrize("sid", JOLTS12[1:])
def test_a_series_with_a_month_missing_in_the_middle_is_refused_and_named(sid):
    d = world()
    del d[sid][MID]
    refused(d, f"the {NAME[sid]} series covers different months than the job openings series")


@pytest.mark.parametrize("sid", JOLTS12[1:])
def test_a_series_with_as_many_months_but_another_month_is_refused_and_named(sid):
    d = world()
    d[sid][date(2022, 7, 2)] = d[sid].pop(MID)                                      # the same count and the same newest month, one date different
    refused(d, f"the {NAME[sid]} series covers different months than the job openings series")


def test_when_the_openings_have_the_hole_the_first_other_series_is_named():
    d = world()
    del d["JTSJOL"][MID]
    refused(d, "the hires series covers different months than the job openings series")


def test_a_date_that_is_not_the_first_of_a_month_is_refused():
    d = world()
    for sid in JOLTS12:
        d[sid][date(2022, 7, 2)] = d[sid].pop(MID)                                  # the same shifted day in all twelve, so that they still cover the same months
    refused(d, "a JOLTS date is not the 1st of a month")


def test_a_month_missing_from_all_twelve_series_is_refused_and_the_first_gap_is_named():
    d = world()
    for sid in JOLTS12:
        del d[sid][date(2026, 4, 1)]
    refused(d, "the JOLTS values skip a month after 2026-03")
    for sid in JOLTS12:
        del d[sid][date(2022, 7, 1)]                                                # a second, older gap: the oldest is named
    refused(d, "the JOLTS values skip a month after 2022-06")


def test_fewer_than_120_months_are_refused_and_120_are_enough():
    refused(world(119), "JOLTS covers 119 months, fewer than the 120 expected")
    assert run(world(120))["detail"]["months_checked"] == 120


@pytest.mark.parametrize("sid", LEVELS)
def test_a_level_outside_100_to_50000_thousand_is_refused_in_any_month_and_named(sid):
    d = world()
    d[sid][MID] = 99.9
    refused(d, f"{LEVEL_NAME[sid]} of 99.9 thousand in 2022-07 is outside 100 to 50,000")
    d = world()
    d[sid][MID] = 50000.1
    refused(d, f"{LEVEL_NAME[sid]} of 50,000.1 thousand in 2022-07 is outside 100 to 50,000")


@pytest.mark.parametrize("sid", ("JTSJOL", "JTSHIL"))
def test_the_edges_of_the_level_range_are_inside(sid):
    for v in (100.0, 50000.0):
        d = world()
        d[sid][MID] = v
        assert run(sync(d))["detail"]["months_checked"] == 130, (sid, v)


def test_a_total_of_100_thousand_passes_the_range_and_fails_the_sum_not_the_range():
    d = world()
    d["JTSTSL"][MID] = 100.0
    sync(d)
    refused(d, "separations differ from quits plus layoffs plus other by 4,700 thousand in 2022-07, over 2")


def test_payroll_employment_must_cover_every_month_and_a_missing_one_is_named():
    for m, text in ((back(LAST, 5), "2026-04"), (back(LAST, 129), lab(back(LAST, 129))), (LAST, "2026-09")):
        d = world()
        del d["PAYEMS"][m]
        refused(d, f"payroll employment is missing for {text}")
    d = world()
    del d["PAYEMS"][AFTER]                                                          # the month JOLTS does not have yet: not needed
    assert run(d)["available"]


def test_payroll_employment_outside_100000_to_250000_thousand_is_refused_in_any_month():
    d = world()
    d["PAYEMS"][MID] = 99999.9
    refused(d, "payroll employment of 99,999.9 thousand in 2022-07 is outside 100,000 to 250,000")
    d = world()
    d["PAYEMS"][MID] = 250000.1
    refused(d, "payroll employment of 250,000.1 thousand in 2022-07 is outside 100,000 to 250,000")
    for v in (100000.0, 250000.0):
        d = world()
        d["PAYEMS"][MID] = v
        assert run(sync(d))["detail"]["months_checked"] == 130, v


def test_unemployed_persons_outside_2000_to_40000_thousand_are_refused_in_any_month_both_series_have():
    d = world()
    d["UNEMPLOY"][MID] = 1999.9
    refused(d, "unemployed persons of 1,999.9 thousand in 2022-07 is outside 2,000 to 40,000")
    d = world()
    d["UNEMPLOY"][MID] = 40000.1
    refused(d, "unemployed persons of 40,000.1 thousand in 2022-07 is outside 2,000 to 40,000")
    for v in (2000.0, 40000.0):
        d = world()
        d["UNEMPLOY"][MID] = v
        assert run(d)["available"], v
    d = world()
    d["UNEMPLOY"][AFTER] = 1.0                                                      # a month JOLTS does not have: not looked at
    d["UNEMPLOY"][back(LAST, 140)] = 1.0                                            # a month before the JOLTS record: not looked at
    assert run(d)["available"]


@pytest.mark.parametrize("sid", ("JTSTSL", "JTSQUL", "JTSLDL", "JTSOSL"))
def test_separations_may_differ_from_quits_plus_layoffs_plus_other_by_2_thousand_and_no_more_in_either_direction(sid):
    for off in (2.0, -2.0):
        d = world()
        d[sid][MID] += off
        assert run(sync(d))["detail"]["largest_separations_gap"] == 2.0, (sid, off)
    for off in (2.5, -2.5):
        d = world()
        d[sid][MID] += off
        refused(sync(d), "separations differ from quits plus layoffs plus other by 2.5 thousand in 2022-07, over 2")
    d = world()
    d[sid][MID] += 2.0 + 2 ** -30                                                   # a hair over the edge: the message rounds it to 2, but it is refused
    refused(sync(d), "separations differ from quits plus layoffs plus other by 2 thousand in 2022-07, over 2")


def test_the_sum_check_looks_at_every_month_and_a_negative_gap_counts_as_much_as_a_positive_one():
    for m in (back(LAST, 129), LAST):
        d = world()
        d["JTSTSL"][m] -= 3.0
        refused(sync(d), f"separations differ from quits plus layoffs plus other by 3 thousand in {lab(m)}, over 2")


@pytest.mark.parametrize("lv, rt", PAIRS.items())
def test_a_rate_may_be_one_sixteenth_of_a_point_from_what_its_level_gives_and_no_more(lv, rt):
    exact = world()[rt][MID]
    for off in (0.0625, -0.0625):
        d = world()
        d[rt][MID] = exact + off
        assert run(d)["detail"]["largest_rate_gap"] == 0.0625, (rt, off)
    for off in (0.0625 + 2 ** -30, -(0.0625 + 2 ** -30)):
        d = world()
        d[rt][MID] = exact + off
        with pytest.raises(ValueError, match=f"^the {NAME[rt]} is "):
            run(d)
    for off in (0.07, -0.07):
        d = world()
        d[rt][MID] = exact + off
        shown = calc(d, lv, MID)
        refused(d, f"the {NAME[rt]} is {exact + off:g} in 2022-07 but {shown:.2f} from its level and payrolls, over 0.0625")


def test_the_openings_rate_is_openings_over_payrolls_plus_openings_and_the_others_over_payrolls_alone():
    d = world()
    d["JTSJOR"][LAST] = round(100 * 8000.0 / 120000.0, 4)                           # openings over payrolls alone: 6.6667, which is NOT what the source publishes
    refused(d, "the job openings rate is 6.6667 in 2026-09 but 6.25 from its level and payrolls, over 0.0625")
    d = world()
    d["JTSHIR"][LAST] = round(100 * 6000.0 / 126000.0, 4)                           # hires over payrolls plus hires: 4.7619
    refused(d, "the hires rate is 4.7619 in 2026-09 but 5.00 from its level and payrolls, over 0.0625")


def test_the_rate_check_looks_at_every_month_and_every_rate():
    for m in (back(LAST, 129), LAST):
        d = world()
        d["JTSQUR"][m] += 0.5
        refused(d, f"the quits rate is {2.5:g} in {lab(m)} but 2.00 from its level and payrolls, over 0.0625")


def test_the_gaps_reported_are_the_largest_found_rounded_to_three_and_four_decimals():
    d = world()
    d["JTSHIR"][LAST] += 0.0123456                                                  # a rate gap of 0.0123456
    d["JTSLDR"][MID] += 0.0234567                                                   # another rate, another month, a larger gap: this one is reported
    d["JTSTSL"][LAST] += 1.2346                                                     # a separations gap of 1.2346 (its rate moves by only 0.001)
    d["JTSOSL"][MID] += 0.4                                                         # a smaller one in another month
    s = run(d)
    assert s["detail"]["largest_rate_gap"] == 0.0235 and s["detail"]["largest_separations_gap"] == 1.235


def _break(kind):
    d = world()
    if kind == "rate":
        d["JTSLDR"][MID] = 11.25
    elif kind == "level":
        d["JTSJOL"][MID] = 50000.1
    elif kind == "payroll":
        d["PAYEMS"][MID] = 250000.1
    elif kind == "unemployed":
        d["UNEMPLOY"][MID] = 40000.1
    elif kind == "sum":
        d["JTSTSL"][MID] += 4700.0
        sync(d)
    elif kind == "months":
        del d["JTSLDR"][MID]
    elif kind == "other rate":
        d["JTSOSR"][MID] += 29.0
    return d


@pytest.mark.parametrize("kind", ("rate", "level", "payroll", "unemployed", "sum", "months", "other rate"))
def test_every_message_fits_in_the_110_characters_the_failure_line_keeps(kind):
    with pytest.raises(ValueError) as e:
        run(_break(kind))
    assert len(str(e.value)) <= 110, str(e.value)
    assert not str(e.value).endswith(("…", "."))


# ---------------------------------------------------------------- what the card shows

def test_the_change_from_the_month_before_has_one_decimal_and_uses_that_month_and_the_year_before_is_twelve_months_back():
    d = world()
    d["JTSJOL"][LAST] = 8400.0
    d["JTSJOL"][back(LAST, 1)] = 7900.06                                            # 8,400 - 7,900.06 = 499.94: one decimal, 499.9
    d["JTSJOL"][back(LAST, 2)] = 5000.0                                             # decoys either side of the right months
    for k, v in ((11, 1000.0), (12, 7000.0), (13, 2000.0)):
        d["JTSJOL"][back(LAST, k)] = v
    s = run(sync(d))["openings"]
    assert s["level_thousands"] == 8400.0 and s["change_1m_thousands"] == 499.9 and s["change_1y_pct"] == 20.0         # 8,400 against 7,000
    assert s["rate_pct"] == d["JTSJOR"][LAST] and s["rate_year_ago_pct"] == d["JTSJOR"][back(LAST, 12)] == round(100 * 7000 / 127000, 9)


def test_each_flow_is_compared_with_its_own_year_before_and_a_fall_has_a_minus_sign():
    d = world()
    d["JTSHIL"][back(LAST, 12)] = 7000.0
    d["JTSLDL"][back(LAST, 12)] = 1500.0
    d["JTSTSL"][back(LAST, 12)] = 4500.0                                            # 2,400 + 1,500 + 600: the year-ago month still adds up
    f = {x["id"]: x for x in run(sync(d))["flows"]}
    assert f["hires"]["change_1y_pct"] == -14.3 and f["hires"]["rate_year_ago_pct"] == round(100 * 7000 / 120000, 9)              # 6,000 against 7,000
    assert f["layoffs"]["change_1y_pct"] == 20.0 and f["quits"]["change_1y_pct"] == 0.0


def test_the_ratio_is_openings_over_unemployed_persons_to_two_decimals_with_the_year_before():
    d = world()
    d["UNEMPLOY"][LAST] = 7000.0
    d["UNEMPLOY"][back(LAST, 12)] = 5000.0
    r = run(d)["per_unemployed"]
    assert (r["ratio"], r["month"], r["unemployed_thousands"], r["year_ago"]) == (1.14, "2026-09", 7000.0, 1.6)             # 8,000 / 7,000 = 1.1429; 8,000 / 5,000


def test_without_an_unemployed_figure_for_the_newest_month_the_ratio_is_the_newest_month_that_has_both_and_says_which():
    d = real()
    del d["UNEMPLOY"][LAST]
    s = run(d)
    r = s["per_unemployed"]
    assert (r["ratio"], r["month"], r["unemployed_thousands"], r["year_ago"]) == (1.02, "2026-08", 7031.0, 0.94)               # 7,190 / 7,031 = 1.0226; 6,919 / 7,380 = 0.9375
    assert r["range"]["months"] == 118 and r["range"]["share_lower_pct"] == 39 and s["openings"]["level_thousands"] == 7523.0       # 46 of 118 were lower than 1.0226; the openings still show September


def test_the_year_before_ratio_is_taken_from_the_ratio_month_not_the_openings_month():
    d = world()
    del d["UNEMPLOY"][LAST]
    d["UNEMPLOY"][back(LAST, 13)] = 5000.0                                          # a year before 2026-08
    d["UNEMPLOY"][back(LAST, 12)] = 4000.0                                          # a year before 2026-09: the wrong month
    r = run(d)["per_unemployed"]
    assert (r["month"], r["ratio"], r["year_ago"]) == ("2026-08", 1.0, 1.6)         # 8,000 / 5,000


def test_levels_are_shown_as_they_come_with_no_rounding():
    d = world()
    d["JTSJOL"][LAST] = 8400.5
    d["JTSHIL"][LAST] = 6000.25
    s = run(sync(d))
    assert s["openings"]["level_thousands"] == 8400.5 and s["flows"][0]["level_thousands"] == 6000.25


def test_the_year_before_ratio_is_none_when_that_month_has_no_unemployed_figure():
    d = world()
    del d["UNEMPLOY"][back(LAST, 12)]
    assert run(d)["per_unemployed"]["year_ago"] is None


def test_no_month_with_both_figures_in_the_newest_120_is_refused():
    d = world()
    d["UNEMPLOY"] = {AFTER: 8000.0, back(LAST, 125): 8000.0}                       # a month ahead of JOLTS and a month older than the window
    refused(d, "no month of the last 120 has both job openings and unemployed persons")


def test_the_ranges_look_at_the_newest_120_months_only():
    d = world()
    for k in range(120, 130):
        d["JTSJOL"][back(LAST, k)] = 4000.0                                         # older than the window: a lower rate that must not count
    r = run(sync(d))["openings"]["range"]
    assert r["months"] == 120 and r["first"] == lab(back(LAST, 119)) and r["lowest"] == {"value": 6.25, "month": lab(back(LAST, 119))}
    d = world()
    d["JTSJOL"][back(LAST, 119)] = 4000.0                                           # the oldest month INSIDE the window counts
    r = run(sync(d))["openings"]["range"]
    assert r["lowest"] == {"value": 3.23, "month": lab(back(LAST, 119))} and r["highest"] == {"value": 6.25, "month": lab(back(LAST, 118))}       # 100 x 4,000 / 124,000 = 3.2258


def test_equal_months_name_the_earliest_and_equal_or_higher_months_are_not_lower():
    d = world()
    for k in range(1, 6):
        d["JTSJOL"][back(LAST, k)] = 12000.0                                        # five months with a higher rate
    r = run(sync(d))["openings"]["range"]
    assert r["share_lower_pct"] == 0 and r["lowest"] == {"value": 6.25, "month": lab(back(LAST, 119))} and r["highest"]["month"] == lab(back(LAST, 5))         # 100 x 12,000 / 132,000 = 9.09, first reached five months back


def test_share_lower_is_the_share_of_months_with_a_strictly_lower_rate_rounded_as_round_does():
    for k, want in ((0, 0), (3, 2), (9, 8), (30, 25), (119, 99)):                     # 2.5 rounds to 2 and 7.5 to 8 (to even); 119 of 120 is 99.17
        d = world()
        for i in range(1, k + 1):
            d["JTSJOL"][back(LAST, i)] = 4000.0
        assert run(sync(d))["openings"]["range"]["share_lower_pct"] == want, k


def test_the_ratio_range_uses_only_months_with_an_unemployed_figure_to_two_decimals():
    d = world()
    for k in (3, 4, 5):
        del d["UNEMPLOY"][back(LAST, k)]
    d["UNEMPLOY"][back(LAST, 7)] = 16000.0                                          # a ratio of 0.5 once
    del d["UNEMPLOY"][back(LAST, 119)]                                              # and the first month of the window has none: the window still starts there
    r = run(d)["per_unemployed"]["range"]
    assert r == {"months": 116, "first": lab(back(LAST, 119)), "lowest": {"value": 0.5, "month": lab(back(LAST, 7))}, "highest": {"value": 1.0, "month": lab(back(LAST, 118))}, "share_lower_pct": 1}      # 1 of 116 months is lower than 1.0


def test_overdue_after_105_days_from_the_first_of_the_month():
    assert run(world(), LAST + timedelta(days=105))["freshness"] == "CURRENT"
    s = run(world(), LAST + timedelta(days=106))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 106


def test_the_note_says_what_the_numbers_are_and_what_they_are_not():
    note = run(world())["note"]
    for phrase in ("US Bureau of Labor Statistics, seasonally adjusted, monthly", "not filled on the last business day of the month", "could start within 30 days", "active recruiting", "removed without filling positions", "counted over the whole month",
                   "quits (the worker's choice)", "layoffs and discharges (the employer's)", "other (retirements, deaths, transfers)", "Rates divide a count by payroll employment (openings: by payroll employment plus openings)",
                   "unemployed persons of the household survey", "The newest months are preliminary and are revised later; each figure carries its month", "Plain checks:", "the Check line"):
        assert phrase in note, phrase
    assert note.endswith("This describes the labour market that already happened: it is not a market signal or a forecast.") and len(note) <= 1100


def test_the_age_and_the_freshness_are_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(J.Jolts(client=_client(_handler)).overview(datetime(2027, 3, 1, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 181 and r["freshness"] == "OVERDUE" and r["as_of"] == "2027-03-01T12:00:00+00:00"           # 2026-09-01 to 2027-03-01


def test_the_module_says_why_each_series_is_asked_for_alone():
    assert "combined request" in J.__doc__ and "FIRST series only" in J.__doc__ and "NOT an identity" in J.__doc__


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_fourteen_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = J.Jolts(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["openings"]["level_thousands"] == 7523.0 and n["n"] == 14 and r["source"].startswith("U.S. Bureau of Labor Statistics") and r["url"] == "https://fred.stlouisfed.org/series/JTSJOL"
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 14


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(J.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = J.Jolts(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 14
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 14                                                              # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 28      # two minutes on it asks again
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 28
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 42


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = J.Jolts(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(J.Jolts(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US job openings could not be read right now (the server had an error, HTTP 503)" and "openings" not in r
    r = asyncio.run(J.Jolts(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]                      # anything but 200 is a failure


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == "UNEMPLOY" else _handler(req)

    r = asyncio.run(J.Jolts(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "openings" not in r and "per_unemployed" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    bad = dict(F)
    bad["JTSJOL"] = F["JTSJOL"].replace("2026-09-01,7523", "2026-09-01,75230")      # a decimal slip in the newest value
    r = asyncio.run(J.Jolts(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US job openings could not be read right now (the data failed a check: job openings of 75,230 thousand in 2026-09 is outside 100 to 50,000)" and "openings" not in r
    bad = dict(F)
    bad["PAYEMS"] = F["PAYEMS"].replace("2026-09-01,159128", "2026-09-01,x")
    r = asyncio.run(J.Jolts(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "a PAYEMS row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(J.Jolts(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US job openings could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("JTSJOL")

    monkeypatch.setattr(J, "summarize", boom)
    r = asyncio.run(J.Jolts(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US job openings could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(J.Jolts(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US job openings figures are not shown because made-up values would look real." and "openings" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/jolts")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_each_request_asks_for_one_series_with_a_start_date_and_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(J.Jolts(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)             # never a combined request: FRED applies one start date to the first series only
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    starts = {req.url.params["cosd"] for req in seen}
    assert len(starts) == 1
    assert 4100 <= (date.today() - date.fromisoformat(starts.pop())).days <= 4300   # about 11.5 years: 137 months today


def test_a_client_made_here_waits_25_seconds_and_is_closed_and_one_given_is_left_open(monkeypatch):
    seen = {"closed": False}

    class Fake:
        def __init__(self, **kw):
            seen["timeout"] = kw.get("timeout")

        async def get(self, url, params=None):
            return httpx.Response(200, text=F[params["id"]])

        async def aclose(self):
            seen["closed"] = True

    monkeypatch.setattr(J.httpx, "AsyncClient", Fake)
    r = asyncio.run(J.Jolts().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(J.Jolts(client=given).overview(NOW))
    assert given.is_closed is False
