"""US jobs report (the Bureau of Labor Statistics' Employment Situation via FRED: payrolls from the establishment survey, the labour force from the household survey, ten series): parsed from real responses (fetched 2026-11-18 20:22 UTC: 322 monthly payroll values per series since 2000-01 and 321 household values, newest 2026-10; the household survey has no figure for 2025-10). Every expected figure was worked by hand from those files before the provider existed (payrolls 159,293 thousand, +165 on the month: private +159, government +6; unemployment rate 4.1% against 4.2%; the ten-year range 3.4% to 14.8%), and the limits are literals set from the whole record (payrolls 1939 on, household 1948 on), not read back from the module. The synthetic worlds use payrolls of 150,000 thousand (120,000 private and 30,000 government) and a labour force of 160,000 (152,000 employed, 8,000 unemployed) in a population of 256,000, so that every rate is exact in binary (5, 62.5 and 59.375) and the edge of each limit can be reached to the last bit."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import usjobs as U
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usjobs.json").read_text())
TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
LAST = date(2026, 10, 1)

PAY = ("PAYEMS", "USPRIV", "USGOVT")
LEVELS = ("CLF16OV", "CE16OV", "UNEMPLOY", "CNP16OV")
RATES = ("UNRATE", "CIVPART", "EMRATIO")
HOUSEHOLD = (*LEVELS, *RATES)
IDS = (*PAY, *LEVELS, *RATES)
NAME = {"PAYEMS": "total nonfarm payrolls", "USPRIV": "private payrolls", "USGOVT": "government payrolls", "CLF16OV": "labour force", "CE16OV": "employed people", "UNEMPLOY": "unemployed people", "CNP16OV": "population",
        "UNRATE": "unemployment rate", "CIVPART": "participation rate", "EMRATIO": "employment-population ratio"}
RELATIONS = {"UNRATE": ("UNEMPLOY", "CLF16OV"), "CIVPART": ("CLF16OV", "CNP16OV"), "EMRATIO": ("CE16OV", "CNP16OV")}
BASE = {"PAYEMS": 150000.0, "USPRIV": 120000.0, "USGOVT": 30000.0, "CLF16OV": 160000.0, "CE16OV": 152000.0, "UNEMPLOY": 8000.0, "CNP16OV": 256000.0}


def back(d, n):
    y, m = d.year, d.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def lab(d):
    return f"{d.year}-{d.month:02d}"


def real():
    return {sid: U.parse(F[sid], sid) for sid in IDS}


def sync(data):
    """The three published rates set to what the levels give (nine decimals: exact for the base world), in every household month."""
    months = data["CLF16OV"]
    data["UNRATE"] = {d: round(100.0 * data["UNEMPLOY"][d] / data["CLF16OV"][d], 9) for d in months}
    data["CIVPART"] = {d: round(100.0 * data["CLF16OV"][d] / data["CNP16OV"][d], 9) for d in months}
    data["EMRATIO"] = {d: round(100.0 * data["CE16OV"][d] / data["CNP16OV"][d], 9) for d in months}
    return data


def world(n=130):
    """`n` months ending 2026-10 with every check satisfied exactly."""
    months = [back(LAST, i) for i in range(n - 1, -1, -1)]
    return sync({s: {d: BASE[s] for d in months} for s in (*PAY, *LEVELS)})


def run(data, today=TODAY):
    return U.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        U.summarize(data, TODAY)


MID = back(LAST, 50)                                                                # 2022-08: a month in the middle of every world


def drop(data, month, series):
    for s in series:
        del data[s][month]


def test_the_series_and_the_limits_are_the_ones_set_from_the_whole_record():
    assert list(U.SERIES) == list(IDS)
    assert U.PAYROLLS == {"PAYEMS": "total nonfarm payrolls", "USPRIV": "private payrolls", "USGOVT": "government payrolls"}
    assert U.HOUSEHOLD == {"CLF16OV": "labour force", "CE16OV": "employed people", "UNEMPLOY": "unemployed people", "CNP16OV": "population"}
    assert U.RATES == {"UNRATE": "unemployment rate", "CIVPART": "participation rate", "EMRATIO": "employment-population ratio"}
    assert U.RELATIONS == (("UNRATE", "UNEMPLOY", "CLF16OV"), ("CIVPART", "CLF16OV", "CNP16OV"), ("EMRATIO", "CE16OV", "CNP16OV"))
    assert U.LEVEL_LIMITS == {"PAYEMS": (100000.0, 250000.0), "USPRIV": (80000.0, 200000.0), "USGOVT": (10000.0, 40000.0), "CLF16OV": (100000.0, 250000.0), "CE16OV": (100000.0, 250000.0), "UNEMPLOY": (2000.0, 40000.0), "CNP16OV": (150000.0, 400000.0)}
    assert U.SUM_TOLERANCE == 1.5                                                   # three values each rounded to a thousand: the real largest gaps are 0 (payrolls) and 1 (household)
    assert U.RATE_TOLERANCE == 0.0625 and U.RATE_TOLERANCE == 2 ** -4               # half a unit of the published decimal plus rounding: the real largest gap is 0.04998
    assert (U.MIN_MONTHS, U.HISTORY_MONTHS, U.MAX_HOUSEHOLD_HOLES, U.RECENT_MONTHS, U.OVERDUE_AFTER_DAYS, U.LOOKBACK_DAYS) == (120, 120, 3, 6, 75, 4200)
    assert (U.TTL, U.FAIL_TTL) == (21600.0, 120.0)


def test_the_saved_files_are_the_real_record_fetched_for_this_card():
    assert set(F) == set(IDS) and all(F[s].startswith(f"observation_date,{s}\n") for s in IDS) and {s: F[s].count("\n") - 1 for s in IDS} == {s: 322 for s in IDS}
    r = real()
    assert min(r["PAYEMS"]) == date(2000, 1, 1) and max(r["PAYEMS"]) == LAST and len(r["PAYEMS"]) == 322 and len(r["CLF16OV"]) == 321 and date(2025, 10, 1) in r["PAYEMS"] and date(2025, 10, 1) not in r["UNRATE"]


def test_missing_values_are_skipped_never_filled():
    assert U.parse("observation_date,UNRATE\n2026-08-01,4.3\n2026-09-01,.\n2026-10-01,\n", "UNRATE") == {date(2026, 8, 1): 4.3}


def test_the_whole_real_record_passes_every_check_and_the_largest_gaps_are_the_ones_found_beforehand():
    s = run(real())
    assert s["detail"] == {"months_checked": 322, "household_months_checked": 321, "first_month": "2000-01", "last_month": "2026-10", "largest_payroll_gap": 0.0, "largest_labour_force_gap": 1.0, "largest_rate_gap": 0.0498}
    assert s["checks"] == {"months_in_a_row": True, "range_ok": True, "payroll_parts_add_up_ok": True, "labour_force_adds_up_ok": True, "rates_follow_levels_ok": True}


def test_the_download_the_card_makes_gives_the_same_card():
    cut = date(2015, 5, 1)                                                          # 4,200 days before 2026-11-18 is 2015-05-20, and FRED returns the month that contains it
    short = {sid: {d: v for d, v in s.items() if d >= cut} for sid, s in real().items()}
    a, b = run(short), run(real())
    assert a["detail"] == {"months_checked": 138, "household_months_checked": 137, "first_month": "2015-05", "last_month": "2026-10", "largest_payroll_gap": 0.0, "largest_labour_force_gap": 1.0, "largest_rate_gap": 0.0498}
    assert all(a[k] == b[k] for k in ("date", "month", "age_days", "freshness", "payrolls", "household", "household_gaps"))


def test_the_newest_month_by_hand_payrolls_first():
    s = run(real())
    assert (s["date"], s["month"], s["age_days"], s["freshness"]) == ("2026-10-01", "2026-10", 48, "CURRENT")
    assert s["payrolls"] == {"level_thousands": 159293.0, "change_thousands": 165.0, "change_year_thousands": 885.0,                                    # 159,293 against 159,128 (+165) and 158,408 (+885)
                             "private": {"level_thousands": 135961.0, "change_thousands": 159.0, "change_year_thousands": 943.0},
                             "government": {"level_thousands": 23332.0, "change_thousands": 6.0, "change_year_thousands": -58.0},                         # 159 + 6 = 165; 943 - 58 = 885
                             "recent": [{"month": "2026-05", "change_thousands": 63.0}, {"month": "2026-06", "change_thousands": 31.0}, {"month": "2026-07", "change_thousands": -10.0},
                                        {"month": "2026-08", "change_thousands": 186.0}, {"month": "2026-09", "change_thousands": 60.0}, {"month": "2026-10", "change_thousands": 165.0}]}


def test_the_newest_month_by_hand_the_household_survey():
    s = run(real())
    assert s["household"] == {"unemployment_rate": {"pct": 4.1, "month_before_pct": 4.2, "year_ago_pct": None},                                          # 2025-10 has no household figure: nothing to compare
                              "participation_rate": {"pct": 61.9, "month_before_pct": 61.8, "year_ago_pct": None},
                              "employment_ratio": {"pct": 59.3, "month_before_pct": 59.2, "year_ago_pct": None},
                              "labour_force_thousands": 170683.0, "employed_thousands": 163615.0, "unemployed_thousands": 7068.0,
                              "range": {"months": 119, "first": "2016-11", "lowest": {"value": 3.4, "month": "2023-04"}, "highest": {"value": 14.8, "month": "2020-04"}, "share_lower_pct": 47}}      # 56 of 119 months had a lower rate than 4.1
    assert s["household_gaps"] == ["2025-10"]


def test_a_clean_exact_world_passes_with_no_gap_at_all():
    s = run(world())
    assert s["detail"] == {"months_checked": 130, "household_months_checked": 130, "first_month": lab(back(LAST, 129)), "last_month": "2026-10", "largest_payroll_gap": 0.0, "largest_labour_force_gap": 0.0, "largest_rate_gap": 0.0}
    h = s["household"]
    assert (h["unemployment_rate"]["pct"], h["participation_rate"]["pct"], h["employment_ratio"]["pct"]) == (5.0, 62.5, 59.375) and s["household_gaps"] == []


# ---------------------------------------------------------------- the checks, one at a time, in the order the module makes them

@pytest.mark.parametrize("sid", PAY)
def test_payroll_series_that_end_in_different_months_are_refused(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the payroll series end in different months")
    d = world()
    d[sid][date(2026, 11, 1)] = BASE[sid]
    refused(d, "the payroll series end in different months")


@pytest.mark.parametrize("sid", HOUSEHOLD)
def test_household_series_that_end_in_different_months_are_refused(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the household series end in different months")
    d = world()
    d[sid][date(2026, 11, 1)] = d[sid][LAST]
    refused(d, "the household series end in different months")


def test_payrolls_and_the_household_survey_must_end_in_the_same_month():
    d = world()
    for s in HOUSEHOLD:
        del d[s][LAST]
    refused(d, "payrolls end in 2026-10 but the household survey in 2026-09")
    d = world()
    for s in PAY:
        d[s][date(2026, 11, 1)] = BASE[s]
    refused(d, "payrolls end in 2026-11 but the household survey in 2026-10")
    d = world()
    for s in HOUSEHOLD:
        d[s][date(2026, 11, 1)] = d[s][LAST]                                        # the household survey a month AHEAD of payrolls
    refused(d, "payrolls end in 2026-10 but the household survey in 2026-11")


@pytest.mark.parametrize("sid", PAY[1:])
def test_a_payroll_series_with_a_month_missing_in_the_middle_is_refused_and_named(sid):
    d = world()
    del d[sid][MID]
    refused(d, f"the {NAME[sid]} series covers different months than total nonfarm payrolls")


def test_total_payrolls_with_the_hole_name_the_first_part():
    d = world()
    del d["PAYEMS"][MID]
    refused(d, "the private payrolls series covers different months than total nonfarm payrolls")


@pytest.mark.parametrize("sid", HOUSEHOLD)
def test_a_household_series_with_a_month_missing_in_the_middle_is_refused_and_named(sid):
    d = world()
    del d[sid][MID]
    if sid == "CLF16OV":                                                            # the reference series: the first other one is named
        refused(d, "the employed people series covers different months than the labour force")
    else:
        refused(d, f"the {NAME[sid]} series covers different months than the labour force")


@pytest.mark.parametrize("sid", (*PAY[1:], *HOUSEHOLD[1:]))
def test_a_series_with_as_many_months_but_another_month_is_refused_and_named(sid):
    d = world()
    d[sid][date(2022, 8, 2)] = d[sid].pop(MID)                                      # the same count and the same newest month, one date different
    reference = "total nonfarm payrolls" if sid in PAY else "labour force"
    refused(d, f"the {NAME[sid]} series covers different months than {reference}" if sid in PAY else f"the {NAME[sid]} series covers different months than the labour force")


def test_a_date_that_is_not_the_first_of_a_month_is_refused():
    d = world()
    for s in IDS:
        d[s][date(2022, 8, 2)] = d[s].pop(MID)
    refused(d, "a jobs report date is not the 1st of a month")


def test_a_month_missing_from_every_series_is_refused_and_the_first_gap_is_named():
    d = world()
    for s in IDS:
        del d[s][date(2026, 4, 1)]
    refused(d, "the payroll months skip a month after 2026-03")
    for s in IDS:
        del d[s][date(2022, 8, 1)]                                                  # a second, older gap: the oldest is named
    refused(d, "the payroll months skip a month after 2022-07")


def test_fewer_than_120_payroll_months_are_refused_and_120_are_enough():
    refused(world(119), "payrolls cover 119 months, fewer than the 120 expected")
    assert run(world(120))["detail"]["months_checked"] == 120


def test_a_household_month_without_payrolls_is_refused():
    d = world()
    old = back(LAST, 130)                                                           # a month before the payrolls begin
    for s in HOUSEHOLD:
        d[s][old] = BASE.get(s, 1.0)
    refused(d, f"payroll figures are missing for {lab(old)}")


def test_up_to_3_months_may_lack_household_figures_inside_the_window_and_they_are_listed():
    d = world()
    gone = [back(LAST, 3), back(LAST, 40), back(LAST, 119)]
    for m in gone:
        for s in HOUSEHOLD:
            del d[s][m]
    s = run(d)
    assert s["household_gaps"] == [lab(back(LAST, 119)), lab(back(LAST, 40)), lab(back(LAST, 3))] and s["detail"]["household_months_checked"] == 127
    assert s["household"]["range"]["months"] == 117
    for m in (back(LAST, 5),):
        for series in HOUSEHOLD:
            del d[series][m]
    refused(d, "household figures are missing for 4 of the last 120 months")


def test_household_months_missing_before_the_window_are_not_counted():
    d = world()
    for m in (back(LAST, 120), back(LAST, 121), back(LAST, 122), back(LAST, 123), back(LAST, 124), back(LAST, 3), back(LAST, 4), back(LAST, 5)):          # five months older than the window and three inside it (the most allowed)
        for s in HOUSEHOLD:
            del d[s][m]
    assert run(d)["household_gaps"] == [lab(back(LAST, 5)), lab(back(LAST, 4)), lab(back(LAST, 3))]


def test_the_120_months_are_counted_in_the_payrolls_not_in_the_household_survey():
    d = world(135)
    for m in [back(LAST, k) for k in range(120, 135)] + [back(LAST, 5)]:          # 15 months older than the window and one inside it have no household figure: 119 household months, 135 payroll months
        for s in HOUSEHOLD:
            del d[s][m]
    assert run(d)["detail"]["household_months_checked"] == 119


def test_the_first_month_is_the_first_payroll_month_even_when_the_household_survey_starts_later():
    d = world()
    for s in HOUSEHOLD:
        del d[s][back(LAST, 129)]
    s = run(d)["detail"]
    assert s["first_month"] == lab(back(LAST, 129)) and s["months_checked"] == 130 and s["household_months_checked"] == 129


@pytest.mark.parametrize("sid", ("PAYEMS", "USPRIV", "USGOVT", "CLF16OV", "CE16OV", "UNEMPLOY", "CNP16OV"))
def test_a_level_outside_its_range_is_refused_in_any_month_and_named(sid):
    lo, hi = U.LEVEL_LIMITS[sid]
    for v, text in ((lo - 0.1, f"{lo - 0.1:,.1f}"), (hi + 0.1, f"{hi + 0.1:,.1f}")):
        d = world()
        d[sid][MID] = v
        refused(d, f"the {NAME[sid]} of {text} thousand in 2022-08 is outside {lo:,.0f} to {hi:,.0f}")


def test_the_edges_of_every_level_range_are_inside():
    for sid, lo, hi, fix in (("USPRIV", 80000.0, 200000.0, "pay"), ("USGOVT", 10000.0, 40000.0, "pay")):
        for v in (lo, hi):
            d = world()
            d[sid][MID] = v
            d["PAYEMS"][MID] = d["USPRIV"][MID] + d["USGOVT"][MID]                   # the total follows, so that the parts still add up
            assert run(d)["detail"]["months_checked"] == 130, (sid, v)
    d = world()
    d["USPRIV"][MID], d["USGOVT"][MID], d["PAYEMS"][MID] = 80000.0, 20000.0, 100000.0   # total payrolls at its lower edge, with parts that add up
    assert run(d)["available"]
    for v in (2000.0, 40000.0):
        d = world()
        d["UNEMPLOY"][MID] = v
        d["CE16OV"][MID] = d["CLF16OV"][MID] - v
        assert run(sync(d))["available"], v
    for v in (150000.0, 400000.0):
        d = world()
        d["CNP16OV"][MID] = v
        assert run(sync(d))["available"], v
    d = world()
    d["CE16OV"][MID], d["CLF16OV"][MID] = 100000.0, 108000.0                         # employed people at the lower edge, with a labour force that adds up
    assert run(sync(d))["available"]
    d = world()
    d["CLF16OV"][MID], d["CE16OV"][MID], d["UNEMPLOY"][MID] = 250000.0, 242000.0, 8000.0
    assert run(sync(d))["available"]


def test_total_payrolls_of_250000_and_the_labour_force_of_100000_pass_their_ranges_and_fail_the_sums_not_the_ranges():
    d = world()
    d["PAYEMS"][MID] = 250000.0
    refused(d, "private plus government payrolls differ from total nonfarm by 100,000 thousand in 2022-08, over 1.5")
    d = world()
    d["CLF16OV"][MID] = 100000.0
    refused(sync(d), "employed plus unemployed people differ from the labour force by 60,000 thousand in 2022-08, over 1.5")
    d = world()
    d["CE16OV"][MID] = 250000.0
    refused(sync(d), "employed plus unemployed people differ from the labour force by 98,000 thousand in 2022-08, over 1.5")


@pytest.mark.parametrize("sid", PAY)
def test_payrolls_may_differ_from_private_plus_government_by_1_5_thousand_and_no_more_in_either_direction(sid):
    for off in (1.5, -1.5):
        d = world()
        d[sid][MID] += off
        assert run(d)["detail"]["largest_payroll_gap"] == 1.5, (sid, off)
    for off in (2.0, -2.0):
        d = world()
        d[sid][MID] += off
        refused(d, "private plus government payrolls differ from total nonfarm by 2 thousand in 2022-08, over 1.5")
    d = world()
    d[sid][MID] += 1.5 + 2 ** -30                                                   # a hair over the edge: the message rounds it to 1.5, but it is refused
    refused(d, "private plus government payrolls differ from total nonfarm by 1.5 thousand in 2022-08, over 1.5")


@pytest.mark.parametrize("sid", ("CLF16OV", "CE16OV", "UNEMPLOY"))
def test_the_labour_force_may_differ_from_employed_plus_unemployed_by_1_5_thousand_and_no_more_in_either_direction(sid):
    for off in (1.5, -1.5):
        d = world()
        d[sid][MID] += off
        assert run(sync(d))["detail"]["largest_labour_force_gap"] == 1.5, (sid, off)
    for off in (2.0, -2.0):
        d = world()
        d[sid][MID] += off
        refused(sync(d), "employed plus unemployed people differ from the labour force by 2 thousand in 2022-08, over 1.5")
    d = world()
    d[sid][MID] += 1.5 + 2 ** -30
    refused(sync(d), "employed plus unemployed people differ from the labour force by 1.5 thousand in 2022-08, over 1.5")


def test_the_sum_checks_look_at_every_month_both_ends_included():
    for m in (back(LAST, 129), LAST):
        d = world()
        d["USPRIV"][m] -= 3.0
        refused(d, f"private plus government payrolls differ from total nonfarm by 3 thousand in {lab(m)}, over 1.5")
        d = world()
        d["CE16OV"][m] += 3.0
        refused(sync(d), f"employed plus unemployed people differ from the labour force by 3 thousand in {lab(m)}, over 1.5")


@pytest.mark.parametrize("rate", RATES)
def test_a_rate_may_be_one_sixteenth_of_a_point_from_what_its_levels_give_and_no_more(rate):
    exact = world()[rate][MID]
    for off in (0.0625, -0.0625):
        d = world()
        d[rate][MID] = exact + off
        assert run(d)["detail"]["largest_rate_gap"] == 0.0625, (rate, off)
    for off in (0.0625 + 2 ** -30, -(0.0625 + 2 ** -30)):
        d = world()
        d[rate][MID] = exact + off
        with pytest.raises(ValueError, match=f"^the {NAME[rate]} is "):
            run(d)
    for off in (0.07, -0.07):
        d = world()
        d[rate][MID] = exact + off
        refused(d, f"the {NAME[rate]} is {exact + off:g} in 2022-08 but {exact:.2f} from the levels, over 0.0625")


def test_each_rate_is_its_own_numerator_over_its_own_denominator():
    d = world()
    d["UNRATE"][LAST] = round(100 * 8000.0 / 256000.0, 4)                           # unemployed over the population, not the labour force: 3.125
    refused(d, "the unemployment rate is 3.125 in 2026-10 but 5.00 from the levels, over 0.0625")
    d = world()
    d["CIVPART"][LAST] = round(100 * 152000.0 / 256000.0, 4)                        # employed over the population: 59.375
    refused(d, "the participation rate is 59.375 in 2026-10 but 62.50 from the levels, over 0.0625")
    d = world()
    d["EMRATIO"][LAST] = round(100 * 160000.0 / 256000.0, 4)                        # the labour force over the population: 62.5
    refused(d, "the employment-population ratio is 62.5 in 2026-10 but 59.38 from the levels, over 0.0625")


def test_the_rate_check_looks_at_every_month_and_every_rate():
    for m in (back(LAST, 129), LAST):
        for rate in RATES:
            d = world()
            d[rate][m] += 0.5
            refused(d, f"the {NAME[rate]} is {d[rate][m]:g} in {lab(m)} but {world()[rate][m]:.2f} from the levels, over 0.0625")


def test_the_gaps_reported_are_the_largest_found_rounded_to_three_and_four_decimals():
    d = world()
    d["USGOVT"][LAST] += 1.2346                                                     # a payroll gap of 1.2346 (the larger of the sum gaps)
    d["UNEMPLOY"][MID] += 0.4006                                                    # a smaller household gap; its rate moves by under 0.001
    d["UNRATE"][LAST] += 0.0123456
    d["CIVPART"][MID] += 0.0234567                                                  # another rate in another month, a larger gap: this one is reported
    s = run(d)
    assert s["detail"]["largest_rate_gap"] == 0.0235 and s["detail"]["largest_payroll_gap"] == 1.235 and s["detail"]["largest_labour_force_gap"] == 0.401


def _break(kind):
    d = world()
    if kind == "rate":
        d["EMRATIO"][MID] = 69.375
    elif kind == "level":
        d["CNP16OV"][MID] = 400000.1
    elif kind == "sum":
        d["CE16OV"][MID] += 90000.0
        sync(d)
    elif kind == "payroll sum":
        d["USPRIV"][MID] += 90000.0
    elif kind == "months":
        del d["EMRATIO"][MID]
    elif kind == "holes":
        for m in (back(LAST, 3), back(LAST, 4), back(LAST, 5), back(LAST, 6)):
            for s in HOUSEHOLD:
                del d[s][m]
    elif kind == "ends":
        for s in HOUSEHOLD:
            del d[s][LAST]
    return d


@pytest.mark.parametrize("kind", ("rate", "level", "sum", "payroll sum", "months", "holes", "ends"))
def test_every_message_fits_in_the_110_characters_the_failure_line_keeps(kind):
    with pytest.raises(ValueError) as e:
        run(_break(kind))
    assert len(str(e.value)) <= 110, str(e.value)
    assert not str(e.value).endswith(("…", "."))


# ---------------------------------------------------------------- what the card shows

def test_payroll_changes_use_the_right_months_and_one_decimal():
    d = world()
    d["PAYEMS"][LAST], d["USPRIV"][LAST] = 150400.06, 120400.06
    d["PAYEMS"][back(LAST, 1)], d["USPRIV"][back(LAST, 1)] = 150000.0, 120000.0
    d["PAYEMS"][back(LAST, 2)], d["USPRIV"][back(LAST, 2)] = 110000.0, 80000.0                                     # decoys either side of the right months (the parts still add up)
    for k, v in ((11, 140000.0), (12, 149000.5), (13, 130000.0)):
        d["PAYEMS"][back(LAST, k)] = v
        d["USPRIV"][back(LAST, k)] = v - 30000.0
    p = run(d)["payrolls"]
    assert p["level_thousands"] == 150400.06 and p["change_thousands"] == 400.1 and p["change_year_thousands"] == 1399.6          # 150,400.06 - 150,000; 150,400.06 - 149,000.5
    assert p["private"]["change_thousands"] == 400.1 and p["private"]["change_year_thousands"] == 1399.6
    assert p["government"] == {"level_thousands": 30000.0, "change_thousands": 0.0, "change_year_thousands": 0.0}


def test_the_recent_changes_are_the_last_six_months_oldest_first_each_against_its_own_month_before():
    d = world()
    for i in range(0, 8):                                                           # a level that grows faster the newer it is, so that every month's change differs
        m = back(LAST, i)
        d["PAYEMS"][m] = 150000.0 + 100 * (8 - i) ** 2
        d["USPRIV"][m] = d["PAYEMS"][m] - 30000.0
    d["PAYEMS"][LAST] += 0.06                                                       # a fraction of a thousand in the newest month: 1,500.06 shows as 1,500.1
    d["USPRIV"][LAST] += 0.06
    rec = run(d)["payrolls"]["recent"]
    assert rec == [{"month": lab(back(LAST, 5)), "change_thousands": 500.0}, {"month": lab(back(LAST, 4)), "change_thousands": 700.0}, {"month": lab(back(LAST, 3)), "change_thousands": 900.0},
                   {"month": lab(back(LAST, 2)), "change_thousands": 1100.0}, {"month": lab(back(LAST, 1)), "change_thousands": 1300.0}, {"month": lab(LAST), "change_thousands": 1500.1}]       # 150,900 - 150,400 and so on up to 156,400 - 154,900


def test_a_rate_is_compared_with_the_month_before_and_the_year_before_and_a_missing_month_gives_none():
    d = world()
    d["UNEMPLOY"][back(LAST, 1)], d["CE16OV"][back(LAST, 1)] = 7000.0, 153000.0
    d["UNEMPLOY"][back(LAST, 12)], d["CE16OV"][back(LAST, 12)] = 9600.0, 150400.0
    d["UNEMPLOY"][back(LAST, 2)], d["CE16OV"][back(LAST, 2)] = 4000.0, 156000.0                                     # decoys
    d["UNEMPLOY"][back(LAST, 11)], d["CE16OV"][back(LAST, 11)] = 4000.0, 156000.0
    d["UNEMPLOY"][back(LAST, 13)], d["CE16OV"][back(LAST, 13)] = 4000.0, 156000.0
    u = run(sync(d))["household"]["unemployment_rate"]
    assert u == {"pct": 5.0, "month_before_pct": 4.375, "year_ago_pct": 6.0}                                           # 7,000 / 160,000 and 9,600 / 160,000
    d = world()
    for m in (back(LAST, 1), back(LAST, 12)):
        for s in HOUSEHOLD:
            del d[s][m]
    h = run(d)["household"]
    assert h["unemployment_rate"]["month_before_pct"] is None and h["unemployment_rate"]["year_ago_pct"] is None and h["participation_rate"]["pct"] == 62.5


def test_the_household_levels_are_shown_as_they_come_and_the_rates_as_published():
    d = world()
    d["CLF16OV"][LAST], d["CE16OV"][LAST], d["UNEMPLOY"][LAST] = 160000.5, 152000.25, 8000.25
    h = run(sync(d))["household"]
    assert (h["labour_force_thousands"], h["employed_thousands"], h["unemployed_thousands"]) == (160000.5, 152000.25, 8000.25)
    assert h["unemployment_rate"]["pct"] == d["UNRATE"][LAST]


def test_the_range_looks_at_the_newest_120_payroll_months_only_and_ties_name_the_earliest():
    d = world()
    for k in range(120, 130):
        d["UNEMPLOY"][back(LAST, k)] = 4000.0
        d["CE16OV"][back(LAST, k)] = 156000.0                                       # older than the window: a lower rate that must not count
    r = run(sync(d))["household"]["range"]
    assert r["months"] == 120 and r["first"] == lab(back(LAST, 119)) and r["lowest"] == {"value": 5.0, "month": lab(back(LAST, 119))} and r["highest"] == {"value": 5.0, "month": lab(back(LAST, 119))}
    d = world()
    d["UNEMPLOY"][back(LAST, 119)], d["CE16OV"][back(LAST, 119)] = 4000.0, 156000.0   # the oldest month INSIDE the window counts
    r = run(sync(d))["household"]["range"]
    assert r["lowest"] == {"value": 2.5, "month": lab(back(LAST, 119))} and r["highest"]["month"] == lab(back(LAST, 118))


def test_share_lower_is_the_share_of_months_with_a_strictly_lower_rate_rounded_as_round_does():
    for k, want in ((0, 0), (3, 2), (9, 8), (30, 25), (119, 99)):                     # 2.5 rounds to 2 and 7.5 to 8 (to even); 119 of 120 is 99.17
        d = world()
        for i in range(1, k + 1):
            d["UNEMPLOY"][back(LAST, i)], d["CE16OV"][back(LAST, i)] = 4000.0, 156000.0
        assert run(sync(d))["household"]["range"]["share_lower_pct"] == want, k
    d = world()
    for i in range(1, 6):
        d["UNEMPLOY"][back(LAST, i)], d["CE16OV"][back(LAST, i)] = 12000.0, 148000.0   # five months with a HIGHER rate: not counted
    assert run(sync(d))["household"]["range"]["share_lower_pct"] == 0


def test_the_range_counts_only_months_with_a_household_figure_and_says_its_window_starts_at_the_first_payroll_month():
    d = world()
    for s in HOUSEHOLD:
        del d[s][back(LAST, 119)]
    r = run(d)["household"]["range"]
    assert r["months"] == 119 and r["first"] == lab(back(LAST, 119))


def test_overdue_after_75_days_from_the_first_of_the_month():
    assert run(world(), LAST + timedelta(days=75))["freshness"] == "CURRENT"
    s = run(world(), LAST + timedelta(days=76))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 76


def test_the_note_says_what_the_numbers_are_and_what_they_are_not():
    note = run(world())["note"]
    for phrase in ("Employment Situation of the US Bureau of Labor Statistics, monthly, seasonally adjusted", "Payrolls count jobs at employers", "private and government", "the labour force is the employed plus the unemployed",
                   "the unemployed as a share of the labour force", "the labour force as a share of the population aged 16 and over", "the employed as a share of that population", "not looking is not unemployed",
                   "do not agree month to month", "The newest months are revised in later releases; each figure carries its month", "Plain checks:", "the Check line"):
        assert phrase in note, phrase
    assert note.endswith("This describes the labour market that already happened: it is not a market signal or a forecast.") and len(note) <= 1100


def test_the_module_says_why_each_series_is_asked_for_alone_and_what_it_does_not_check():
    assert "combined request" in U.__doc__ and "FIRST series only" in U.__doc__ and "NOT checked" in U.__doc__


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_ten_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = U.UsJobs(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["payrolls"]["change_thousands"] == 165.0 and n["n"] == 10 and r["source"].startswith("U.S. Bureau of Labor Statistics") and r["url"] == "https://fred.stlouisfed.org/series/PAYEMS"
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 10


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(U.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = U.UsJobs(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 10
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 10                                                              # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 20      # two minutes on it asks again
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 20
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 30


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = U.UsJobs(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(U.UsJobs(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US jobs figures could not be read right now (the server had an error, HTTP 503)" and "payrolls" not in r
    r = asyncio.run(U.UsJobs(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]                      # anything but 200 is a failure


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == "EMRATIO" else _handler(req)

    r = asyncio.run(U.UsJobs(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "payrolls" not in r and "household" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    bad = dict(F)
    bad["PAYEMS"] = F["PAYEMS"].replace("2026-10-01,159293", "2026-10-01,1592930")      # a decimal slip in the newest value
    r = asyncio.run(U.UsJobs(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US jobs figures could not be read right now (the data failed a check: the total nonfarm payrolls of 1,592,930 thousand in 2026-10 is outside 100,000 to 250,000)" and "payrolls" not in r
    bad = dict(F)
    bad["UNRATE"] = F["UNRATE"].replace("2026-10-01,4.1", "2026-10-01,x")
    r = asyncio.run(U.UsJobs(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "a UNRATE row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(U.UsJobs(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US jobs figures could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("PAYEMS")

    monkeypatch.setattr(U, "summarize", boom)
    r = asyncio.run(U.UsJobs(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US jobs figures could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(U.UsJobs(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US jobs figures are not shown because made-up values would look real." and "payrolls" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/us-jobs")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_age_and_the_freshness_are_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(U.UsJobs(client=_client(_handler)).overview(datetime(2027, 3, 1, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 151 and r["freshness"] == "OVERDUE" and r["as_of"] == "2027-03-01T12:00:00+00:00"           # 2026-10-01 to 2027-03-01


def test_each_request_asks_for_one_series_with_a_start_date_and_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(U.UsJobs(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)             # never a combined request: FRED applies one start date to the first series only
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    starts = {req.url.params["cosd"] for req in seen}
    assert len(starts) == 1
    assert 4100 <= (date.today() - date.fromisoformat(starts.pop())).days <= 4300   # about 11.5 years: 138 months today


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
    r = asyncio.run(U.UsJobs().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(U.UsJobs(client=given).overview(NOW))
    assert given.is_closed is False
