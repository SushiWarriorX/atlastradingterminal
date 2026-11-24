"""US household income, spending and saving (the Bureau of Economic Analysis' monthly Personal Income and Outlays and the quarterly split of consumer spending, via FRED: eight monthly and four quarterly series): parsed from real responses (fetched 2026-11-19 02:2x UTC: 180 monthly points from 2011-10 and 60 quarterly points from 2011-Q4, the tail of the 813 months and 271 quarters of the whole record the limits were set from), checked one rule at a time on worlds whose numbers are exact in binary, then the class: requests, cache, failures, demo, route. Every limit and tolerance is written here as a literal, not read back from the module."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import ushousehold as H
from atlas_api.app import create_app
from atlas_api.failreason import fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "fred_ushousehold.json").read_text())
TODAY = date(2026, 11, 19)
NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)
QLAST = date(2026, 7, 1)

MONTHLY = ("PI", "W055RC1", "DSPI", "A068RC1", "PCE", "B069RC1", "PMSAVE")
RATE = "PSAVERT"
QUARTERLY = ("PCEC", "PCDG", "PCND", "PCESV")
IDS = (*MONTHLY, RATE, *QUARTERLY)
NAME = {"PI": "personal income", "W055RC1": "personal taxes", "DSPI": "disposable income", "A068RC1": "personal outlays", "PCE": "monthly consumer spending", "B069RC1": "interest payments",
        "PMSAVE": "personal saving", "PSAVERT": "saving rate", "PCEC": "quarterly consumer spending", "PCDG": "durable goods", "PCND": "nondurable goods", "PCESV": "services"}
BASE = {"PI": 12000.0, "W055RC1": 2000.0, "DSPI": 10000.0, "A068RC1": 9600.0, "PCE": 9000.0, "B069RC1": 400.0, "PMSAVE": 400.0, "PSAVERT": 4.0,
        "PCEC": 9000.0, "PCDG": 1000.0, "PCND": 2000.0, "PCESV": 6000.0}      # 12,000 - 2,000 = 10,000; 10,000 - 9,600 = 400; 100 x 400 / 10,000 = 4; 9,000 + 400 + 200 = 9,600; 1,000 + 2,000 + 6,000 = 9,000 = the mean of three months of 9,000 (all exact in binary)


def mback(d, n):
    i = d.year * 12 + d.month - 1 - n
    return date(i // 12, i % 12 + 1, 1)


def qback(d, n):
    i = d.year * 4 + (d.month - 1) // 3 - n
    return date(i // 4, (i % 4) * 3 + 1, 1)


def mlab(d):
    return f"{d.year}-{d.month:02d}"


def qlab(d):
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def real():
    return {sid: H.parse(F[sid], sid) for sid in IDS}


def world(n=180, last=LAST):
    """`n` months ending at `last` and every quarter whose three months are all there, with every check satisfied exactly."""
    ms = [mback(last, i) for i in range(n - 1, -1, -1)]
    qs = [d for d in ms if d.month in (1, 4, 7, 10) and mback(d, -2) in ms]
    data = {s: {d: BASE[s] for d in ms} for s in (*MONTHLY, RATE)}
    data.update({s: {d: BASE[s] for d in qs} for s in QUARTERLY})
    return data


def custom(first_month, n_months, first_quarter, n_quarters):
    """`n_months` months from `first_month` and `n_quarters` quarters from `first_quarter`, whether or not their three months are all there."""
    ms = [mback(first_month, -i) for i in range(n_months)]
    qs = [qback(first_quarter, -i) for i in range(n_quarters)]
    data = {s: {d: BASE[s] for d in ms} for s in (*MONTHLY, RATE)}
    data.update({s: {d: BASE[s] for d in qs} for s in QUARTERLY})
    return data


def run(data, today=TODAY):
    return H.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        H.summarize(data, TODAY)


MID = date(2019, 5, 1)                                                              # the second month of 2019-Q2: a month in the middle of every world
MIDQ = date(2019, 4, 1)
M, Q = mlab(MID), qlab(MIDQ)
FIRST, QFIRST = mback(LAST, 179), qback(QLAST, 59)                                  # 2011-10 and 2011-Q4: the oldest month and quarter of a 180-month world


# ---------------------------------------------------------------- what the module is made of

def test_the_series_and_the_limits_are_the_ones_set_from_the_whole_record():
    assert H.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and H.PAGE == "https://fred.stlouisfed.org/series/PSAVERT" and H.START == "1959-01-01"
    assert H.SOURCE.startswith("U.S. Bureau of Economic Analysis, Personal Income and Outlays") and H.SOURCE.endswith("via FRED, St. Louis Fed (official, free public data)")
    assert H.MONTHLY == MONTHLY and H.RATE == RATE and H.QUARTERLY == QUARTERLY and H.SERIES == list(IDS) and H.NAMES == NAME
    assert H.LIMITS == {"PI": (200.0, 100_000.0), "W055RC1": (20.0, 15_000.0), "DSPI": (200.0, 80_000.0), "A068RC1": (150.0, 80_000.0), "PCE": (150.0, 80_000.0), "B069RC1": (2.0, 3_000.0),
                        "PMSAVE": (-500.0, 20_000.0), "PCEC": (150.0, 80_000.0), "PCDG": (20.0, 10_000.0), "PCND": (60.0, 20_000.0), "PCESV": (60.0, 60_000.0)}
    assert H.RATE_LIMITS == (-10.0, 60.0)
    assert H.INCOME_TOLERANCE == 5 / 32 == 0.15625 and H.RATE_TOLERANCE == 9 / 128 == 0.0703125 and H.SPLIT_TOLERANCE == 2 ** -8 == 0.00390625
    assert H.MEAN_TOLERANCE == 2 ** -4 == 0.0625 and H.OTHER_FLOOR == -5 / 32 == -0.15625
    assert (H.MIN_MONTHS, H.MIN_QUARTERS, H.RECENT_MONTHS, H.OVERDUE_AFTER_DAYS, H.QUARTER_OVERDUE_AFTER_DAYS, H.TTL, H.FAIL_TTL) == (120, 40, 6, 100, 240, 21600.0, 120.0)
    assert H.SPLIT == (("durable", "Durable goods", "PCDG"), ("nondurable", "Nondurable goods", "PCND"), ("services", "Services", "PCESV"))


def test_the_months_of_a_quarter_are_the_first_month_and_the_two_that_follow_it():
    for m in (1, 4, 7, 10):
        assert H._quarter_months(date(2026, m, 1)) == [date(2026, m, 1), date(2026, m + 1, 1), date(2026, m + 2, 1)]


def test_the_saved_files_are_the_real_record_fetched_for_this_card():
    assert set(F) == set(IDS)
    for sid in (*MONTHLY, RATE):
        lines = F[sid].strip().splitlines()
        assert lines[0] == f"observation_date,{sid}" and len(lines) == 181 and lines[1].startswith("2011-10-01,") and lines[-1].startswith("2026-09-01,")
    for sid in QUARTERLY:
        lines = F[sid].strip().splitlines()
        assert lines[0] == f"observation_date,{sid}" and len(lines) == 61 and lines[1].startswith("2011-10-01,") and lines[-1].startswith("2026-07-01,")
    assert F["PI"].splitlines()[-1] == "2026-09-01,27707.8" and F["PSAVERT"].splitlines()[-1] == "2026-09-01,3.8" and F["PCEC"].splitlines()[-1] == "2026-07-01,22312.825"


def test_missing_values_are_skipped_never_filled():
    text = "observation_date,PSAVERT\n2026-07-01,4.5\n2026-08-01,.\n2026-09-01,3.8\n"
    assert H.parse(text, "PSAVERT") == {date(2026, 7, 1): 4.5, date(2026, 9, 1): 3.8}


def test_the_whole_real_record_passes_every_check_and_the_largest_gaps_are_the_ones_found_beforehand():
    s = run(real())
    assert s["detail"] == {"months_checked": 180, "first_month": "2011-10", "last_month": "2026-09", "quarters_checked": 60, "first_quarter": "2011-Q4", "last_quarter": "2026-Q3", "quarters_compared": 60,
                           "largest_income_gap": 0.1, "largest_saving_gap": 0.1, "largest_rate_gap": 0.0499, "largest_split_gap": 0.001, "largest_mean_gap": 0.0433, "smallest_other_outlays": 152.1}
    assert s["checks"] == {"months_in_a_row": True, "quarters_in_a_row": True, "range_ok": True, "income_adds_up_ok": True, "saving_adds_up_ok": True, "rate_follows_levels_ok": True,
                           "outlays_cover_spending_ok": True, "spending_types_add_up_ok": True, "quarter_matches_months_ok": True}


def test_the_download_the_card_makes_gives_the_same_card():
    r = asyncio.run(H.UsHousehold(client=_client(_handler)).overview(NOW))
    assert {k: v for k, v in r.items() if k not in ("as_of", "demo")} == run(real(), NOW.date()) and r["demo"] is False


def test_the_newest_month_by_hand():
    s = run(real())
    assert s["available"] is True and s["month"] == "2026-09" and s["date"] == "2026-09-01" and s["age_days"] == 79 and s["freshness"] == "CURRENT"
    assert s["source"] == H.SOURCE and s["url"] == "https://fred.stlouisfed.org/series/PSAVERT"
    assert s["saving"] == {"rate_pct": 3.8, "month_before_pct": 4.0, "year_ago_pct": 5.1, "level_billions": 911.1, "change_billions": -60.3, "change_year_billions": -278.8,
                           "range": {"months": 180, "first": "2011-10", "lowest": {"value": 2.4, "month": "2022-06"}, "highest": {"value": 31.8, "month": "2020-04"}, "share_lower_pct": 4}}      # 8 of the 180 months were lower
    assert s["income"] == [{"key": "income", "label": "Personal income", "level_billions": 27707.8, "change_pct": 0.2, "change_year_pct": 4.15},
                           {"key": "taxes", "label": "Taxes on it", "level_billions": 3418.8, "change_pct": 0.05, "change_year_pct": 0.79},
                           {"key": "disposable", "label": "Disposable income", "level_billions": 24289.0, "change_pct": 0.22, "change_year_pct": 4.64}]
    assert s["outlays"] == {"key": "outlays", "label": "Personal outlays", "level_billions": 23377.9, "change_pct": 0.49, "change_year_pct": 6.15, "parts": [
        {"key": "spending", "label": "Consumer spending", "level_billions": 22452.8, "change_pct": 0.51, "change_year_pct": 6.28, "share_pct": 96.0},
        {"key": "interest", "label": "Interest payments", "level_billions": 617.9, "change_pct": -0.13, "change_year_pct": 4.32, "share_pct": 2.6},
        {"key": "other", "label": "Everything else", "level_billions": 307.2, "share_pct": 1.3}]}
    assert s["split"] == {"quarter": "2026-Q3", "date": "2026-07-01", "age_days": 141, "freshness": "CURRENT", "total_billions": 22312.825, "total_change_year_pct": 6.11, "parts": [
        {"key": "durable", "label": "Durable goods", "level_billions": 2417.153, "share_pct": 10.8, "change_year_pct": 6.14},
        {"key": "nondurable", "label": "Nondurable goods", "level_billions": 4504.346, "share_pct": 20.2, "change_year_pct": 5.99},
        {"key": "services", "label": "Services", "level_billions": 15391.326, "share_pct": 69.0, "change_year_pct": 6.14}]}
    assert s["recent"] == [{"month": "2026-04", "saving_rate_pct": 4.4, "income_change_pct": 0.05, "spending_change_pct": 0.76}, {"month": "2026-05", "saving_rate_pct": 4.4, "income_change_pct": 0.77, "spending_change_pct": 0.78},
                           {"month": "2026-06", "saving_rate_pct": 4.4, "income_change_pct": 0.26, "spending_change_pct": 0.31}, {"month": "2026-07", "saving_rate_pct": 4.5, "income_change_pct": 0.36, "spending_change_pct": 0.23},
                           {"month": "2026-08", "saving_rate_pct": 4.0, "income_change_pct": 0.33, "spending_change_pct": 0.87}, {"month": "2026-09", "saving_rate_pct": 3.8, "income_change_pct": 0.22, "spending_change_pct": 0.51}]


def test_a_clean_exact_world_passes_with_no_gap_at_all():
    s = run(world())
    assert s["detail"] == {"months_checked": 180, "first_month": "2011-10", "last_month": "2026-09", "quarters_checked": 60, "first_quarter": "2011-Q4", "last_quarter": "2026-Q3", "quarters_compared": 60,
                           "largest_income_gap": 0.0, "largest_saving_gap": 0.0, "largest_rate_gap": 0.0, "largest_split_gap": 0.0, "largest_mean_gap": 0.0, "smallest_other_outlays": 200.0}


# ---------------------------------------------------------------- same months and quarters, dates, a row, enough of them

@pytest.mark.parametrize("sid", (*MONTHLY, RATE))
def test_monthly_series_that_end_in_different_months_are_refused(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the monthly household series end in different months")


@pytest.mark.parametrize("sid", QUARTERLY)
def test_quarterly_series_that_end_in_different_quarters_are_refused(sid):
    d = world()
    del d[sid][QLAST]
    refused(d, "the spending split series end in different quarters")


@pytest.mark.parametrize("sid", (*MONTHLY[1:], RATE))
def test_a_monthly_series_with_a_month_missing_in_the_middle_is_refused_and_named(sid):
    d = world()
    del d[sid][MID]
    refused(d, f"the {NAME[sid]} series covers different months than personal income")


def test_personal_income_with_the_hole_makes_the_first_other_series_the_one_named():
    d = world()
    del d["PI"][MID]
    refused(d, "the personal taxes series covers different months than personal income")


@pytest.mark.parametrize("sid", QUARTERLY[1:])
def test_a_quarterly_series_with_a_quarter_missing_in_the_middle_is_refused_and_named(sid):
    d = world()
    del d[sid][MIDQ]
    refused(d, f"the {NAME[sid]} series covers different quarters than quarterly consumer spending")


def test_quarterly_consumer_spending_with_the_hole_makes_the_first_other_series_the_one_named():
    d = world()
    del d["PCEC"][MIDQ]
    refused(d, "the durable goods series covers different quarters than quarterly consumer spending")


@pytest.mark.parametrize("bad", [date(2019, 5, 2), date(2019, 5, 31)])
def test_a_monthly_date_that_is_not_the_1st_is_refused(bad):
    d = world()
    for s in (*MONTHLY, RATE):
        d[s][bad] = d[s].pop(MID)
    refused(d, "a household date is not the 1st of a month")


@pytest.mark.parametrize("bad", [date(2019, m, 1) for m in (2, 3, 5, 6, 8, 9, 11, 12)] + [date(2019, 4, 2), date(2019, 4, 30)])      # every month that does not start a quarter, and two days that are not the 1st
def test_a_quarterly_date_that_is_not_the_first_of_a_quarter_is_refused(bad):
    d = world()
    for s in QUARTERLY:
        d[s][bad] = d[s].pop(MIDQ)
    refused(d, "a spending split date is not the 1st of a quarter")


def test_the_first_of_each_of_the_four_quarter_months_is_accepted():
    d = world()
    assert {x.month for x in d["PCEC"]} == {1, 4, 7, 10} and all(x.day == 1 for x in d["PCEC"]) and run(d)["available"] is True


def test_months_that_skip_a_month_are_refused():
    d = world()
    for s in (*MONTHLY, RATE):
        del d[s][MID]
    refused(d, "the household months skip a month after 2019-04")


def test_a_skipped_month_across_the_turn_of_the_year_is_found_too():
    d = world()
    for s in (*MONTHLY, RATE):
        del d[s][date(2018, 1, 1)]
    refused(d, "the household months skip a month after 2017-12")


def test_quarters_that_skip_a_quarter_are_refused():
    d = world()
    for s in QUARTERLY:
        del d[s][MIDQ]
    refused(d, "the spending split quarters skip a quarter after 2019-Q1")


def test_a_skipped_quarter_across_the_turn_of_the_year_is_found_too():
    d = world()
    for s in QUARTERLY:
        del d[s][date(2018, 1, 1)]
    refused(d, "the spending split quarters skip a quarter after 2017-Q4")


def test_fewer_than_120_months_are_refused_and_120_pass():
    assert run(world(120))["detail"]["months_checked"] == 120
    refused(world(119), "the household record covers 119 months, fewer than the 120 expected")


def test_fewer_than_40_quarters_are_refused_and_40_pass():
    assert run(world(120))["detail"]["quarters_checked"] == 40
    d = world()
    oldest = sorted(d["PCEC"])
    for q in oldest[:20]:
        for s in QUARTERLY:
            del d[s][q]
    assert len(d["PCEC"]) == 40 and run(d)["detail"]["quarters_checked"] == 40
    for s in QUARTERLY:
        del d[s][oldest[20]]
    refused(d, "the spending split covers 39 quarters, fewer than the 40 expected")


def test_a_quarter_is_compared_with_its_months_only_when_it_has_all_three():
    d = custom(date(2016, 11, 1), 122, date(2016, 10, 1), 41)                         # months 2016-11 to 2026-12; quarters 2016-Q4 (two of its three months) to 2026-Q4
    s = run(d)["detail"]
    assert s["quarters_checked"] == 41 and s["quarters_compared"] == 40 and s["first_quarter"] == "2016-Q4" and s["last_quarter"] == "2026-Q4" and s["months_checked"] == 122


def test_comparing_a_quarter_with_fewer_than_40_quarters_of_months_is_refused():
    d = custom(date(2016, 11, 1), 121, date(2017, 1, 1), 40)                          # 40 quarters in the series: 2017-Q1 to 2026-Q3 are whole (39), 2026-Q4 has two months
    refused(d, "quarterly spending could be compared with its months in only 39 quarters, fewer than the 40 expected")


def test_a_quarter_newer_than_the_months_is_skipped_by_the_comparison_and_counted():
    d = world()
    for s in (*MONTHLY, RATE):
        del d[s][LAST]                                                                # the months now end in 2026-08: 2026-Q3 has two of its three months
    d["PCEC"][QLAST], d["PCDG"][QLAST] = 9100.0, 1100.0                               # a quarter that would fail the comparison (a gap of 100) while its three types still add up
    s = run(d)
    assert s["month"] == "2026-08" and s["detail"]["quarters_checked"] == 60 and s["detail"]["quarters_compared"] == 59 and s["detail"]["largest_mean_gap"] == 0.0 and s["split"]["quarter"] == "2026-Q3"
    full = world()
    full["PCEC"][QLAST], full["PCDG"][QLAST] = 9100.0, 1100.0
    refused(full, "quarterly spending differs from the average of its months by 100.000 billion in 2026-Q3, over 0.0625")      # the same quarter with its three months is compared


# ---------------------------------------------------------------- ranges: both edges of every limit; what speaks next when the value sits inside an edge

EDGES = [
    ("PI", 200.0, f"income minus taxes differs from disposable income by 11800.00 billion in {M}, over 0.15625"),
    ("PI", 199.9, f"the personal income of 199.9 billion in {M} is outside 200 to 100,000"),
    ("PI", 100000.0, f"income minus taxes differs from disposable income by 88000.00 billion in {M}, over 0.15625"),
    ("PI", 100000.1, f"the personal income of 100,000.1 billion in {M} is outside 200 to 100,000"),
    ("W055RC1", 20.0, f"income minus taxes differs from disposable income by 1980.00 billion in {M}, over 0.15625"),
    ("W055RC1", 19.9, f"the personal taxes of 19.9 billion in {M} is outside 20 to 15,000"),
    ("W055RC1", 15000.0, f"income minus taxes differs from disposable income by 13000.00 billion in {M}, over 0.15625"),
    ("W055RC1", 15000.1, f"the personal taxes of 15,000.1 billion in {M} is outside 20 to 15,000"),
    ("DSPI", 200.0, f"income minus taxes differs from disposable income by 9800.00 billion in {M}, over 0.15625"),
    ("DSPI", 199.9, f"the disposable income of 199.9 billion in {M} is outside 200 to 80,000"),
    ("DSPI", 80000.0, f"income minus taxes differs from disposable income by 70000.00 billion in {M}, over 0.15625"),
    ("DSPI", 80000.1, f"the disposable income of 80,000.1 billion in {M} is outside 200 to 80,000"),
    ("A068RC1", 150.0, f"disposable income minus outlays differs from saving by 9450.00 billion in {M}, over 0.15625"),
    ("A068RC1", 149.9, f"the personal outlays of 149.9 billion in {M} is outside 150 to 80,000"),
    ("A068RC1", 80000.0, f"disposable income minus outlays differs from saving by 70400.00 billion in {M}, over 0.15625"),
    ("A068RC1", 80000.1, f"the personal outlays of 80,000.1 billion in {M} is outside 150 to 80,000"),
    ("PCE", 150.0, f"quarterly spending differs from the average of its months by 2950.000 billion in {Q}, over 0.0625"),
    ("PCE", 149.9, f"the monthly consumer spending of 149.9 billion in {M} is outside 150 to 80,000"),
    ("PCE", 80000.0, f"spending plus interest exceed personal outlays by 70800.0 billion in {M}"),
    ("PCE", 80000.1, f"the monthly consumer spending of 80,000.1 billion in {M} is outside 150 to 80,000"),
    ("B069RC1", 1.9, f"the interest payments of 1.9 billion in {M} is outside 2 to 3,000"),
    ("B069RC1", 3000.0, f"spending plus interest exceed personal outlays by 2400.0 billion in {M}"),
    ("B069RC1", 3000.1, f"the interest payments of 3,000.1 billion in {M} is outside 2 to 3,000"),
    ("PMSAVE", -500.0, f"disposable income minus outlays differs from saving by 900.00 billion in {M}, over 0.15625"),
    ("PMSAVE", -500.1, f"the personal saving of -500.1 billion in {M} is outside -500 to 20,000"),
    ("PMSAVE", 20000.0, f"disposable income minus outlays differs from saving by 19600.00 billion in {M}, over 0.15625"),
    ("PMSAVE", 20000.1, f"the personal saving of 20,000.1 billion in {M} is outside -500 to 20,000"),
    ("PSAVERT", -10.0, f"the saving rate is -10% in {M} but 4.00% from the levels, over 0.0703125"),
    ("PSAVERT", -10.1, f"the saving rate of -10.1% in {M} is outside -10 to 60"),
    ("PSAVERT", 60.0, f"the saving rate is 60% in {M} but 4.00% from the levels, over 0.0703125"),
    ("PSAVERT", 60.1, f"the saving rate of 60.1% in {M} is outside -10 to 60"),
    ("PSAVERT", 60.25, f"the saving rate of 60.25% in {M} is outside -10 to 60"),
    ("PSAVERT", -10.25, f"the saving rate of -10.25% in {M} is outside -10 to 60"),
    ("PCEC", 150.0, f"the three spending types differ from the total by 8850.000 billion in {Q}, over 0.00390625"),
    ("PCEC", 149.9, f"the quarterly consumer spending of 149.9 billion in {Q} is outside 150 to 80,000"),
    ("PCEC", 80000.0, f"the three spending types differ from the total by 71000.000 billion in {Q}, over 0.00390625"),
    ("PCEC", 80000.1, f"the quarterly consumer spending of 80,000.1 billion in {Q} is outside 150 to 80,000"),
    ("PCDG", 20.0, f"the three spending types differ from the total by 980.000 billion in {Q}, over 0.00390625"),
    ("PCDG", 19.9, f"the durable goods of 19.9 billion in {Q} is outside 20 to 10,000"),
    ("PCDG", 10000.0, f"the three spending types differ from the total by 9000.000 billion in {Q}, over 0.00390625"),
    ("PCDG", 10000.1, f"the durable goods of 10,000.1 billion in {Q} is outside 20 to 10,000"),
    ("PCND", 60.0, f"the three spending types differ from the total by 1940.000 billion in {Q}, over 0.00390625"),
    ("PCND", 59.9, f"the nondurable goods of 59.9 billion in {Q} is outside 60 to 20,000"),
    ("PCND", 20000.0, f"the three spending types differ from the total by 18000.000 billion in {Q}, over 0.00390625"),
    ("PCND", 20000.1, f"the nondurable goods of 20,000.1 billion in {Q} is outside 60 to 20,000"),
    ("PCESV", 60.0, f"the three spending types differ from the total by 5940.000 billion in {Q}, over 0.00390625"),
    ("PCESV", 59.9, f"the services of 59.9 billion in {Q} is outside 60 to 60,000"),
    ("PCESV", 60000.0, f"the three spending types differ from the total by 54000.000 billion in {Q}, over 0.00390625"),
    ("PCESV", 60000.1, f"the services of 60,000.1 billion in {Q} is outside 60 to 60,000"),
]


@pytest.mark.parametrize("sid, v, text", EDGES)
def test_each_limit_is_pinned_at_both_edges(sid, v, text):
    d = world()
    d[sid][MIDQ if sid in QUARTERLY else MID] = v
    refused(d, text)


def test_interest_payments_at_their_lower_limit_pass_everything():
    d = world()
    d["B069RC1"][MID] = 2.0
    s = run(d)
    assert s["available"] is True and s["detail"]["smallest_other_outlays"] == 200.0


@pytest.mark.parametrize("sid", IDS)
def test_a_range_is_checked_in_the_oldest_and_the_newest_period_not_only_in_the_middle(sid):
    lo, hi = H.RATE_LIMITS if sid == RATE else H.LIMITS[sid]
    start = "the saving rate of " if sid == RATE else f"the {NAME[sid]} of "
    for when in ((QFIRST, QLAST) if sid in QUARTERLY else (FIRST, LAST)):
        for bad in (hi + 0.1, lo - 0.1):
            d = world()
            d[sid][when] = bad
            with pytest.raises(ValueError) as e:
                H.summarize(d, TODAY)
            label = qlab(when) if sid in QUARTERLY else mlab(when)
            assert str(e.value).startswith(start) and f" in {label} is outside " in str(e.value)


# ---------------------------------------------------------------- the sums, one at a time

@pytest.mark.parametrize("when", [FIRST, LAST, MID])
def test_income_minus_taxes_must_equal_disposable_income_within_5_over_32(when):
    d = world()
    d["PI"][when] = 12000.15625                                                       # exactly the tolerance: passes
    assert run(d)["detail"]["largest_income_gap"] == 0.156
    d["PI"][when] = 12000.171875                                                      # 11/64 over: the message names the month
    refused(d, f"income minus taxes differs from disposable income by 0.17 billion in {mlab(when)}, over 0.15625")


def test_every_term_of_the_income_sum_counts():
    for sid, v in (("PI", 12000.25), ("W055RC1", 2000.25), ("DSPI", 10000.25), ("PI", 11999.75)):         # the last one is below: it is the size of the gap that counts
        d = world()
        d[sid][MID] = v
        refused(d, f"income minus taxes differs from disposable income by 0.25 billion in {M}, over 0.15625")


@pytest.mark.parametrize("when", [FIRST, LAST, MID])
def test_disposable_income_minus_outlays_must_equal_saving_within_5_over_32(when):
    d = world()
    d["A068RC1"][when] = 9600.15625
    assert run(d)["detail"]["largest_saving_gap"] == 0.156
    d["A068RC1"][when] = 9600.25
    refused(d, f"disposable income minus outlays differs from saving by 0.25 billion in {mlab(when)}, over 0.15625")


def test_every_term_of_the_saving_sum_counts():
    d = world()
    d["PMSAVE"][MID] = 400.25
    refused(d, f"disposable income minus outlays differs from saving by 0.25 billion in {M}, over 0.15625")
    d = world()
    d["PI"][MID], d["DSPI"][MID] = 12000.25, 10000.25                                  # disposable income moves with income, so the income sum still holds
    refused(d, f"disposable income minus outlays differs from saving by 0.25 billion in {M}, over 0.15625")
    d = world()
    d["A068RC1"][MID] = 9599.75
    refused(d, f"disposable income minus outlays differs from saving by 0.25 billion in {M}, over 0.15625")


@pytest.mark.parametrize("when", [FIRST, LAST, MID])
def test_the_saving_rate_must_equal_saving_over_disposable_income_within_9_over_128(when):
    d = world()
    d["PSAVERT"][when] = 4.0703125                                                    # exactly the tolerance
    assert run(d)["detail"]["largest_rate_gap"] == 0.0703
    d["PSAVERT"][when] = 4.07421875                                                   # 2**-8 over
    refused(d, f"the saving rate is 4.07422% in {mlab(when)} but 4.00% from the levels, over 0.0703125")
    d["PSAVERT"][when] = 3.9296875                                                    # and the same distance below
    assert run(d)["detail"]["largest_rate_gap"] == 0.0703
    d["PSAVERT"][when] = 3.92578125
    refused(d, f"the saving rate is 3.92578% in {mlab(when)} but 4.00% from the levels, over 0.0703125")


def test_saving_and_disposable_income_are_both_in_the_rate_sum():
    d = world()
    d["PMSAVE"][MID], d["A068RC1"][MID] = 410.0, 9590.0                                # saving up and outlays down: the saving sum holds and the rate should be 4.1
    refused(d, f"the saving rate is 4% in {M} but 4.10% from the levels, over 0.0703125")
    d = world()
    d["PI"][MID], d["DSPI"][MID], d["A068RC1"][MID] = 12200.0, 10200.0, 9800.0         # disposable income up with every sum still holding: the rate should be 3.92
    refused(d, f"the saving rate is 4% in {M} but 3.92% from the levels, over 0.0703125")


@pytest.mark.parametrize("when", [FIRST, LAST, MID])
def test_consumer_spending_plus_interest_must_not_exceed_outlays_by_more_than_5_over_32(when):
    d = world()
    d["A068RC1"][when], d["PMSAVE"][when], d["PSAVERT"][when] = 9399.84375, 600.15625, 6.0              # outlays - 9,000 - 400 = -0.15625: exactly the floor
    assert run(d)["detail"]["smallest_other_outlays"] == -0.2
    d["A068RC1"][when], d["PMSAVE"][when] = 9399.8125, 600.1875                          # -0.1875: below it
    refused(d, f"spending plus interest exceed personal outlays by 0.2 billion in {mlab(when)}")


def test_spending_and_interest_are_both_in_the_outlays_property():
    d = world()
    d["B069RC1"][MID] = 700.0                                                          # 9,600 - 9,000 - 700 = -100
    refused(d, f"spending plus interest exceed personal outlays by 100.0 billion in {M}")
    d = world()
    d["PCE"][MID] = 9300.0                                                             # 9,600 - 9,300 - 400 = -100
    refused(d, f"spending plus interest exceed personal outlays by 100.0 billion in {M}")


@pytest.mark.parametrize("when", [QFIRST, QLAST, MIDQ])
def test_the_three_types_of_spending_must_add_up_to_the_total_within_2_to_the_minus_8(when):
    d = world()
    d["PCDG"][when] = 1000.00390625                                                    # exactly the tolerance
    assert run(d)["detail"]["largest_split_gap"] == 0.0039
    d["PCDG"][when] = 1000.0048828125                                                  # 2**-10 over
    refused(d, f"the three spending types differ from the total by 0.005 billion in {qlab(when)}, over 0.00390625")


def test_every_term_of_the_spending_split_counts():
    for sid, delta in (("PCEC", 0.25), ("PCDG", 0.25), ("PCND", 0.25), ("PCESV", 0.25), ("PCND", -0.25)):
        d = world()
        d[sid][MIDQ] += delta
        refused(d, f"the three spending types differ from the total by 0.250 billion in {Q}, over 0.00390625")


@pytest.mark.parametrize("when", [QFIRST, QLAST, MIDQ])
def test_quarterly_spending_must_equal_the_average_of_its_months_within_2_to_the_minus_4(when):
    d = world()
    d["PCE"][when] = 9000.1875                                                         # the first month of the quarter: the mean moves by exactly 0.0625
    assert run(d)["detail"]["largest_mean_gap"] == 0.0625
    d["PCE"][when] = 9000.25
    refused(d, f"quarterly spending differs from the average of its months by 0.083 billion in {qlab(when)}, over 0.0625")


@pytest.mark.parametrize("k", [0, 1, 2])
def test_each_of_the_three_months_of_a_quarter_is_in_the_average(k):
    for v in (9000.25, 8999.75):                                                       # above and below
        d = world()
        d["PCE"][mback(MIDQ, -k)] = v
        refused(d, f"quarterly spending differs from the average of its months by 0.083 billion in {Q}, over 0.0625")


def test_the_months_of_the_neighbouring_quarters_are_not_in_the_average():
    d = world()
    d["PCE"][mback(MIDQ, -3)] = 9100.0                                                 # July 2019 belongs to 2019-Q3
    refused(d, "quarterly spending differs from the average of its months by 33.333 billion in 2019-Q3, over 0.0625")
    d = world()
    d["PCE"][mback(MIDQ, 1)] = 9100.0                                                  # March 2019 belongs to 2019-Q1
    refused(d, "quarterly spending differs from the average of its months by 33.333 billion in 2019-Q1, over 0.0625")


def test_the_quarterly_total_is_in_the_average_comparison():
    d = world()
    d["PCEC"][MIDQ], d["PCDG"][MIDQ] = 9000.25, 1000.25                                # the three types still add up to the total
    refused(d, f"quarterly spending differs from the average of its months by 0.250 billion in {Q}, over 0.0625")


# ---------------------------------------------------------------- what is reported about the checks

def test_the_largest_gap_of_each_sum_is_the_largest_not_the_first_or_the_last():
    d = world()
    d["PI"][mback(MID, 20)], d["PI"][mback(MID, 5)], d["PI"][mback(MID, -9)] = 12000.0625, 12000.125, 12000.03125         # 0.0625, 0.125, 0.03125: the middle one is the largest
    d["A068RC1"][mback(MID, 18)], d["A068RC1"][mback(MID, 4)], d["A068RC1"][mback(MID, -8)] = 9600.125, 9600.0625, 9600.03125      # the first of three is the largest
    d["PSAVERT"][mback(MID, 17)], d["PSAVERT"][mback(MID, 3)], d["PSAVERT"][mback(MID, -7)] = 4.0625, 4.0078125, 4.03125
    d["PCDG"][qback(MIDQ, 7)], d["PCDG"][qback(MIDQ, 2)], d["PCDG"][qback(MIDQ, -3)] = 1000.001953125, 1000.00390625, 1000.0009765625
    d["PCE"][mback(MID, 16)], d["PCE"][mback(MID, 1)], d["PCE"][mback(MID, -6)] = 9000.0625, 9000.1875, 9000.09375
    s = run(d)["detail"]
    assert s["largest_income_gap"] == 0.125 and s["largest_saving_gap"] == 0.125 and s["largest_rate_gap"] == 0.0625 and s["largest_split_gap"] == 0.0039 and s["largest_mean_gap"] == 0.0625


def test_the_reported_gaps_are_rounded_to_three_three_four_four_four_and_one_decimals():
    d = world()
    d["PI"][MID] = 12000.15625                                                          # 0.15625 -> 0.156 (three decimals)
    d["A068RC1"][mback(MID, 4)] = 9600.0703125                                          # 0.0703125 -> 0.07 (three decimals)
    d["PSAVERT"][mback(MID, 8)] = 4.0703125                                             # 0.0703125 -> 0.0703 (four decimals)
    d["PCDG"][MIDQ] = 1000.00390625                                                     # 0.00390625 -> 0.0039 (four decimals)
    d["PCE"][mback(MID, 12)] = 9000.13                                                  # the mean moves by 0.04333... -> 0.0433 (four decimals)
    d["A068RC1"][FIRST], d["PMSAVE"][FIRST], d["PSAVERT"][FIRST] = 9400.26, 599.74, 6.0 # outlays - 9,000 - 400 = 0.26: the smallest rest, reported to one decimal as 0.3
    s = run(d)["detail"]
    assert s["largest_income_gap"] == 0.156 and s["largest_saving_gap"] == 0.07 and s["largest_rate_gap"] == 0.0703 and s["largest_split_gap"] == 0.0039 and s["largest_mean_gap"] == 0.0433
    assert s["smallest_other_outlays"] == 0.3


def test_the_smallest_rest_of_outlays_is_the_smallest_not_the_first_or_the_last():
    d = world()
    for when, rest in ((mback(MID, 30), 150.0), (mback(MID, 10), 25.5), (mback(MID, -10), 80.0)):
        d["A068RC1"][when] = 9400.0 + rest
        d["PMSAVE"][when] = 10000.0 - d["A068RC1"][when]
        d["PSAVERT"][when] = d["PMSAVE"][when] / 100.0
    assert run(d)["detail"]["smallest_other_outlays"] == 25.5


# ---------------------------------------------------------------- the order in which the checks speak

def test_the_checks_run_in_a_fixed_order():
    def two(first, second, text):
        d = world()
        first(d)
        second(d)
        refused(d, text)

    def monthly_ends(d): del d["PSAVERT"][LAST]
    def quarterly_ends(d): del d["PCND"][QLAST]
    def monthly_covers(d): del d["B069RC1"][MID]
    def quarterly_covers(d): del d["PCDG"][MIDQ]
    def monthly_dates(d):
        for s in (*MONTHLY, RATE):
            d[s][mback(MID, 14) + timedelta(days=1)] = d[s].pop(mback(MID, 14))
    def quarterly_dates(d):
        for s in QUARTERLY:
            d[s][qback(MIDQ, 9) + timedelta(days=1)] = d[s].pop(qback(MIDQ, 9))
    def monthly_skip(d):
        for s in (*MONTHLY, RATE):
            del d[s][mback(MID, 7)]
    def quarterly_skip(d):
        for s in QUARTERLY:
            del d[s][qback(MIDQ, 5)]
    def rng(d): d["PI"][mback(MID, 20)] = 100000.1
    def inc(d): d["PI"][MID] = 12000.25
    def sav(d): d["PMSAVE"][MID] = 400.25
    def rate(d): d["PSAVERT"][MID] = 4.25
    def rest(d): d["B069RC1"][MID] = 700.0
    def split(d): d["PCND"][MIDQ] = 2000.25
    def mean(d): d["PCE"][MID] = 9000.25
    two(monthly_ends, quarterly_ends, "the monthly household series end in different months")
    two(quarterly_ends, monthly_covers, "the spending split series end in different quarters")
    two(monthly_covers, quarterly_covers, "the interest payments series covers different months than personal income")
    two(quarterly_covers, monthly_dates, "the durable goods series covers different quarters than quarterly consumer spending")
    two(monthly_dates, quarterly_dates, "a household date is not the 1st of a month")
    two(quarterly_dates, monthly_skip, "a spending split date is not the 1st of a quarter")
    two(monthly_skip, quarterly_skip, f"the household months skip a month after {mlab(mback(MID, 8))}")
    two(quarterly_skip, rng, f"the spending split quarters skip a quarter after {qlab(qback(MIDQ, 6))}")
    two(rng, inc, f"the personal income of 100,000.1 billion in {mlab(mback(MID, 20))} is outside 200 to 100,000")
    two(inc, sav, f"income minus taxes differs from disposable income by 0.25 billion in {M}, over 0.15625")
    two(sav, rate, f"disposable income minus outlays differs from saving by 0.25 billion in {M}, over 0.15625")
    two(rate, rest, f"the saving rate is 4.25% in {M} but 4.00% from the levels, over 0.0703125")
    two(rest, split, f"spending plus interest exceed personal outlays by 100.0 billion in {M}")
    two(split, mean, f"the three spending types differ from the total by 0.250 billion in {Q}, over 0.00390625")


def test_the_minimum_count_of_months_comes_before_the_ranges():
    d = world(119)
    d["PI"][MID] = 100000.1
    refused(d, "the household record covers 119 months, fewer than the 120 expected")


def test_a_failed_comparison_is_named_before_the_count_of_comparisons_is_judged():
    d = custom(date(2016, 11, 1), 121, date(2017, 1, 1), 40)                          # 39 quarters can be compared, one too few
    d["PCE"][date(2020, 4, 1)] = 9000.25                                               # 2020-Q2 is whole, so it is compared and fails first
    refused(d, "quarterly spending differs from the average of its months by 0.083 billion in 2020-Q2, over 0.0625")


def test_ranges_are_checked_series_by_series_in_the_order_of_the_table_and_the_rate_last():
    d = world()
    d["PI"][MID], d["PCEC"][MIDQ], d["PSAVERT"][MID] = 100000.1, 80000.1, 60.1
    refused(d, f"the personal income of 100,000.1 billion in {M} is outside 200 to 100,000")
    d = world()
    d["PCEC"][MIDQ], d["PSAVERT"][MID] = 80000.1, 60.1
    refused(d, f"the quarterly consumer spending of 80,000.1 billion in {Q} is outside 150 to 80,000")


def test_an_earlier_month_is_named_before_a_later_one_in_the_same_series():
    d = world()
    d["PI"][mback(MID, 10)] = d["PI"][mback(MID, -10)] = 100000.1
    refused(d, f"the personal income of 100,000.1 billion in {mlab(mback(MID, 10))} is outside 200 to 100,000")


# ---------------------------------------------------------------- summary: changes, shares, rounding, ranges, freshness

def test_the_month_changes_and_the_year_comparison_use_the_right_months():
    d = world()
    for back, pi in ((1, 11000.0), (12, 10500.0), (11, 10100.0), (13, 10200.0)):      # taxes make up the difference, so disposable income stays 10,000 and every sum holds
        d["PI"][mback(LAST, back)] = pi
        d["W055RC1"][mback(LAST, back)] = pi - 10000.0
    rows = {x["key"]: x for x in run(d)["income"]}
    assert (rows["income"]["change_pct"], rows["income"]["change_year_pct"]) == (9.09, 14.29)           # 12,000 against 11,000 the month before and 10,500 a year ago, not against 10,100 or 10,200
    assert (rows["taxes"]["change_pct"], rows["taxes"]["change_year_pct"]) == (100.0, 300.0)             # 2,000 against 1,000 and 500


def test_a_percent_change_is_rounded_to_two_decimals():
    d = world()
    for back, pi in ((1, 11990.0), (12, 11000.0)):
        d["PI"][mback(LAST, back)] = pi
        d["W055RC1"][mback(LAST, back)] = pi - 10000.0
    row = {x["key"]: x for x in run(d)["income"]}["income"]
    assert row["change_pct"] == 0.08 and row["change_year_pct"] == 9.09                    # 0.0834 and 9.0909: not 0.1 or 0.083, and not 9.1 or 9.091


def test_the_shares_of_outlays_and_the_rest_are_rounded_to_one_decimal():
    s = run(world())["outlays"]
    assert [(p["key"], p["level_billions"], p["share_pct"]) for p in s["parts"]] == [("spending", 9000.0, 93.8), ("interest", 400.0, 4.2), ("other", 200.0, 2.1)]       # 93.75, 4.1667 and 2.0833
    d = world()
    d["A068RC1"][LAST], d["PMSAVE"][LAST] = 9600.04, 399.96
    s = run(d)["outlays"]
    assert s["parts"][2]["level_billions"] == 200.0 and s["level_billions"] == 9600.04      # 200.04 is reported as 200.0


def test_the_saving_changes_in_billions_are_rounded_to_one_decimal_and_use_the_right_months():
    d = world()
    for back, sav in ((0, 400.26), (1, 399.0), (12, 300.0), (11, 350.0), (13, 450.0)):
        m = mback(LAST, back)
        d["PMSAVE"][m], d["A068RC1"][m] = sav, 10000.0 - sav
        d["PSAVERT"][m] = sav / 100.0
    s = run(d)["saving"]
    assert s["level_billions"] == 400.26 and s["change_billions"] == 1.3 and s["change_year_billions"] == 100.3             # 400.26 - 399 and 400.26 - 300, not 350 or 450


def test_the_saving_rate_range_covers_every_month_and_counts_only_strictly_lower_ones():
    d = world()
    rates = {mback(LAST, i): 5.0 for i in range(180)}
    for i in (100, 50, 40):
        rates[mback(LAST, i)] = 4.0                                                    # three months at the same low: the earliest is named
    for i in (60, 20):
        rates[mback(LAST, i)] = 6.0                                                    # two at the same high: the earliest is named
    rates[LAST] = 4.0                                                                   # the newest equals the lowest: none is strictly lower
    for m, v in rates.items():
        d["PSAVERT"][m], d["PMSAVE"][m], d["A068RC1"][m] = v, v * 100.0, 10000.0 - v * 100.0
    assert run(d)["saving"]["range"] == {"months": 180, "first": "2011-10", "lowest": {"value": 4.0, "month": mlab(mback(LAST, 100))}, "highest": {"value": 6.0, "month": mlab(mback(LAST, 60))}, "share_lower_pct": 0}
    d["PSAVERT"][LAST], d["PMSAVE"][LAST], d["A068RC1"][LAST] = 5.0, 500.0, 9500.0
    assert run(d)["saving"]["range"]["share_lower_pct"] == 2                           # the three low months of 180, 1.7 percent


def test_the_range_values_are_rounded_to_two_decimals_and_nothing_else_is():
    d = world()
    d["PSAVERT"][MID] = 4.0703125
    assert run(d)["saving"]["range"]["highest"] == {"value": 4.07, "month": M}


def test_the_six_recent_months_are_oldest_first_with_the_right_changes():
    d = world()
    d["PI"][LAST], d["DSPI"][LAST], d["A068RC1"][LAST], d["PCE"][LAST] = 12100.0, 10100.0, 9700.0, 9100.0            # disposable income +1%, spending +1.11%
    d["PSAVERT"][LAST] = round(100 * 400.0 / 10100.0, 4)
    d["PCEC"][QLAST], d["PCDG"][QLAST] = 9000.0 + 100.0 / 3, 1000.0 + 100.0 / 3         # the quarter follows the mean of its months
    s = run(d)
    assert [r["month"] for r in s["recent"]] == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    assert s["recent"][-1] == {"month": "2026-09", "saving_rate_pct": 3.9604, "income_change_pct": 1.0, "spending_change_pct": 1.11}
    assert s["recent"][0] == {"month": "2026-04", "saving_rate_pct": 4.0, "income_change_pct": 0.0, "spending_change_pct": 0.0}


def test_the_split_uses_the_newest_quarter_and_the_same_quarter_a_year_earlier():
    d = world()
    for back, durable in ((0, 1100.0), (4, 800.0), (3, 700.0), (5, 600.0)):           # nondurable goods take the other side, so the total stays 9,000 and every sum holds
        q = qback(QLAST, back)
        d["PCDG"][q], d["PCND"][q] = durable, 3000.0 - durable
    sp = run(d)["split"]
    assert sp["total_billions"] == 9000.0 and sp["total_change_year_pct"] == 0.0
    assert [(p["key"], p["level_billions"], p["share_pct"], p["change_year_pct"]) for p in sp["parts"]] == [
        ("durable", 1100.0, 12.2, 37.5), ("nondurable", 1900.0, 21.1, -13.64), ("services", 6000.0, 66.7, 0.0)]       # 1,100 against 800 a year ago, not 700 or 600; 1,900 against 2,200


def test_the_month_and_the_quarter_have_their_own_age_and_freshness():
    s = run(world(), LAST + timedelta(days=100))
    assert s["age_days"] == 100 and s["freshness"] == "CURRENT" and s["split"]["age_days"] == 162 and s["split"]["freshness"] == "CURRENT"
    s = run(world(), LAST + timedelta(days=101))
    assert s["age_days"] == 101 and s["freshness"] == "OVERDUE" and s["split"]["age_days"] == 163 and s["split"]["freshness"] == "CURRENT"
    s = run(world(), QLAST + timedelta(days=240))
    assert s["split"]["age_days"] == 240 and s["split"]["freshness"] == "CURRENT"
    assert run(world(), QLAST + timedelta(days=241))["split"]["freshness"] == "OVERDUE"


def test_the_note_says_what_the_numbers_are_and_what_they_are_not():
    note = run(world())["note"]
    for phrase in ("monthly Personal Income and Outlays of the US Bureau of Economic Analysis", "Personal income is what households receive; taxes come off it, and what is left is disposable income",
                   "consumer spending, interest payments and everything else (found by subtraction)", "Saving is disposable income minus outlays, and the saving rate is saving as a share of disposable income",
                   "billions of dollars at a seasonally adjusted annual rate and in the prices of the time, not adjusted for inflation", "from the GDP release",
                   "The newest months are revised in later releases; each figure carries its month", "Plain checks:", "the Check line"):
        assert phrase in note, phrase
    assert note.endswith("This describes household finances that already happened: it is not a market signal or a forecast.") and len(note) <= 1100


def test_the_module_says_why_each_series_is_asked_for_alone_and_what_it_does_not_check():
    for phrase in ("combined request", "FIRST series only", "NOT checked", "MONTHLY series", "QUARTERLY consumer spending", "BETWEEN two tables", "closest thing to an independent check"):
        assert phrase in H.__doc__, phrase


def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    for _sid, _v, text in EDGES:
        assert len(text) <= 110, text
        assert fail_reason(ValueError(text)) == f"the data failed a check: {text}"


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_twelve_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = H.UsHousehold(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["saving"]["rate_pct"] == 3.8 and n["n"] == 12 and r["source"].startswith("U.S. Bureau of Economic Analysis") and r["url"] == "https://fred.stlouisfed.org/series/PSAVERT"
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 12


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(H.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = H.UsHousehold(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 12
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 12                                                              # still the failure from the cache
    clock["t"] += 1
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 24      # exactly two minutes on it asks again
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 24                                                              # one second short of six hours: kept
    clock["t"] += 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 36                                                              # exactly six hours on: asked again


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = H.UsHousehold(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(H.UsHousehold(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US household figures could not be read right now (the server had an error, HTTP 503)" and "saving" not in r and "income" not in r
    r = asyncio.run(H.UsHousehold(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]                      # anything but 200 is a failure


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == "B069RC1" else _handler(req)

    r = asyncio.run(H.UsHousehold(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "saving" not in r and "split" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    bad = dict(F)
    bad["PSAVERT"] = F["PSAVERT"].replace("2026-09-01,3.8", "2026-09-01,38")           # a decimal slip in the newest rate that stays inside the range
    r = asyncio.run(H.UsHousehold(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US household figures could not be read right now (the data failed a check: the saving rate is 38% in 2026-09 but 3.75% from the levels, over 0.0703125)" and "saving" not in r
    bad = dict(F)
    bad["PI"] = F["PI"].replace("2026-09-01,27707.8", "2026-09-01,277078.0")
    r = asyncio.run(H.UsHousehold(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US household figures could not be read right now (the data failed a check: the personal income of 277,078 billion in 2026-09 is outside 200 to 100,000)"
    bad = dict(F)
    bad["PCE"] = F["PCE"].replace("2026-09-01,22452.8", "2026-09-01,x")
    r = asyncio.run(H.UsHousehold(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "a PCE row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(H.UsHousehold(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US household figures could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("PI")

    monkeypatch.setattr(H, "summarize", boom)
    r = asyncio.run(H.UsHousehold(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US household figures could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(H.UsHousehold(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US household figures are not shown because made-up values would look real." and "saving" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/us-household")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_card_is_refreshed_with_the_other_macro_sources():
    jobs = (Path(__file__).parent.parent / "atlas_api" / "sched" / "jobs.py").read_text(encoding="utf-8")
    app = (Path(__file__).parent.parent / "atlas_api" / "app.py").read_text(encoding="utf-8")
    assert '"us_gdp", "us_household", "us_real_spending", "bank_reserves"' in jobs and '"us_household": us_household' in app and "us_household = UsHousehold(demo=demo)" in app


def test_the_age_and_the_freshness_are_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(H.UsHousehold(client=_client(_handler)).overview(datetime(2027, 1, 15, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 136 and r["freshness"] == "OVERDUE" and r["split"]["age_days"] == 198 and r["as_of"] == "2027-01-15T12:00:00+00:00"           # 2026-09-01 and 2026-07-01 to 2027-01-15


def test_each_request_asks_for_one_series_from_1959_with_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(H.UsHousehold(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)             # never a combined request: FRED applies one start date to the first series only
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert {req.url.params["cosd"] for req in seen} == {"1959-01-01"}


def test_a_client_made_here_waits_25_seconds_and_is_closed_and_one_given_is_left_open(monkeypatch):
    seen = {"closed": False}

    class Fake:
        def __init__(self, **kw):
            seen["timeout"] = kw.get("timeout")

        async def get(self, url, params=None):
            return httpx.Response(200, text=F[params["id"]])

        async def aclose(self):
            seen["closed"] = True

    monkeypatch.setattr(H.httpx, "AsyncClient", Fake)
    r = asyncio.run(H.UsHousehold().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(H.UsHousehold(client=given).overview(NOW))
    assert given.is_closed is False
