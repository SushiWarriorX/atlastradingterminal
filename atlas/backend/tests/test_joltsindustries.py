"""US job openings by industry (the Bureau of Labor Statistics' JOLTS, sixteen series of FRED): parsed from real responses (fetched 2026-11-19 05:2x UTC: 130 monthly points from 2015-12 of each series; the module itself asks for the whole record from 2000-12), every limit pinned at both edges with literals, every sum at its tolerance and just over it, and the newest month worked by hand from the saved files, without the module."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import joltsindustries as J
from atlas_api.app import create_app
from atlas_api.failreason import dates_in_words, fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "fred_joltsindustries.json").read_text())
TODAY = date(2026, 11, 19)
NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)

IDS = ("JTSJOL", "JTS1000JOL", "JTS9000JOL", "JTS9200JOL", "JTS2300JOL", "JTS3000JOL", "JTS3200JOL", "JTS3400JOL", "JTS4000JOL", "JTS4400JOL", "JTS540099JOL", "JTS6000JOL", "JTS6200JOL",
       "JTS7000JOL", "JTS7100JOL", "JTS7200JOL")
NAME = {"JTSJOL": "total nonfarm", "JTS1000JOL": "private", "JTS9000JOL": "government", "JTS9200JOL": "state and local", "JTS2300JOL": "construction", "JTS3000JOL": "manufacturing",
        "JTS3200JOL": "durable goods", "JTS3400JOL": "nondurable goods", "JTS4000JOL": "trade and transport", "JTS4400JOL": "retail", "JTS540099JOL": "business services",
        "JTS6000JOL": "education and health", "JTS6200JOL": "health care", "JTS7000JOL": "leisure", "JTS7100JOL": "arts", "JTS7200JOL": "food and lodging"}
BASE = {"JTSJOL": 7700.0, "JTS1000JOL": 6700.0, "JTS9000JOL": 1000.0, "JTS9200JOL": 800.0, "JTS2300JOL": 300.0, "JTS3000JOL": 600.0, "JTS3200JOL": 400.0, "JTS3400JOL": 200.0,
        "JTS4000JOL": 1300.0, "JTS4400JOL": 700.0, "JTS540099JOL": 1300.0, "JTS6000JOL": 1600.0, "JTS6200JOL": 1500.0, "JTS7000JOL": 800.0, "JTS7100JOL": 100.0, "JTS7200JOL": 700.0}
# 6,700 + 1,000 = 7,700; 400 + 200 = 600; 100 + 700 = 800; the six industries 300 + 600 + 1,300 + 1,300 + 1,600 + 800 = 5,900 leave 800 of private for the four not fetched (all exact in binary)


def mback(d, n):
    i = d.year * 12 + d.month - 1 - n
    return date(i // 12, i % 12 + 1, 1)


def mlab(d):
    return f"{d.year}-{d.month:02d}"


def real():
    return {sid: J.parse(F[sid], sid) for sid in IDS}


def world(n=130, last=LAST):
    """`n` months ending at `last`, every series at its BASE value, every check satisfied exactly."""
    ms = [mback(last, i) for i in range(n - 1, -1, -1)]
    return {s: {d: BASE[s] for d in ms} for s in IDS}


def run(data, today=TODAY):
    return J.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        J.summarize(data, TODAY)


MID = date(2019, 5, 1)                                                                # a month in the middle of every world
M = mlab(MID)
FIRST = mback(LAST, 129)                                                              # 2015-12: the oldest month of a 130-month world
YEAR_AGO = mback(LAST, 12)


# ---------------------------------------------------------------- what the module is made of

def test_the_series_and_the_limits_are_the_ones_set_from_the_whole_record():
    assert J.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and J.PAGE == "https://fred.stlouisfed.org/series/JTSJOL" and J.START == "2000-12-01"
    assert J.SOURCE == "U.S. Bureau of Labor Statistics, Job Openings and Labor Turnover Survey, via FRED, St. Louis Fed (official, free public data)"
    assert J.SERIES == list(IDS) and J.NAMES == NAME and J.TOTAL == "JTSJOL" and J.PRIVATE == "JTS1000JOL"
    assert J.LIMITS == {"JTSJOL": (1_000.0, 25_000.0), "JTS1000JOL": (1_000.0, 25_000.0), "JTS9000JOL": (130.0, 2_500.0), "JTS9200JOL": (100.0, 2_100.0), "JTS2300JOL": (10.0, 1_000.0),
                        "JTS3000JOL": (40.0, 2_000.0), "JTS3200JOL": (20.0, 1_300.0), "JTS3400JOL": (20.0, 800.0), "JTS4000JOL": (150.0, 4_500.0), "JTS4400JOL": (100.0, 3_000.0),
                        "JTS540099JOL": (200.0, 5_000.0), "JTS6000JOL": (200.0, 4_500.0), "JTS6200JOL": (200.0, 4_200.0), "JTS7000JOL": (100.0, 3_500.0), "JTS7100JOL": (8.0, 450.0),
                        "JTS7200JOL": (80.0, 3_100.0)}
    assert J.SUMS == (("JTSJOL", ("JTS1000JOL", "JTS9000JOL")), ("JTS3000JOL", ("JTS3200JOL", "JTS3400JOL")), ("JTS7000JOL", ("JTS7100JOL", "JTS7200JOL")))
    assert J.WITHIN == (("JTS4400JOL", "JTS4000JOL"), ("JTS6200JOL", "JTS6000JOL"), ("JTS9200JOL", "JTS9000JOL"))
    assert J.SIX == ("JTS2300JOL", "JTS3000JOL", "JTS4000JOL", "JTS540099JOL", "JTS6000JOL", "JTS7000JOL")
    assert J.SUM_TOLERANCE == 1.5 and J.PART_TOLERANCE == 1.0 and J.REST_TOLERANCE == 3.5
    assert (J.MIN_MONTHS, J.HISTORY_MONTHS, J.OVERDUE_AFTER_DAYS, J.TTL, J.FAIL_TTL) == (120, 120, 105, 21600.0, 120.0)
    assert J.GROUPS == (("education_health", "Private education and health services", "JTS6000JOL", (("health_care", "Health care and social assistance", "JTS6200JOL"), ("education", "Private educational services", None))),
                        ("business", "Professional and business services", "JTS540099JOL", ()),
                        ("trade_transport", "Trade, transportation and utilities", "JTS4000JOL", (("retail", "Retail trade", "JTS4400JOL"), ("wholesale_transport", "Wholesale trade, transportation and utilities", None))),
                        ("government", "Government", "JTS9000JOL", (("state_local", "State and local government", "JTS9200JOL"), ("federal", "Federal government", None))),
                        ("leisure", "Leisure and hospitality", "JTS7000JOL", (("food_lodging", "Accommodation and food services", "JTS7200JOL"), ("arts", "Arts, entertainment and recreation", "JTS7100JOL"))),
                        ("manufacturing", "Manufacturing", "JTS3000JOL", (("durable", "Durable goods manufacturing", "JTS3200JOL"), ("nondurable", "Nondurable goods manufacturing", "JTS3400JOL"))),
                        ("construction", "Construction", "JTS2300JOL", ()))
    assert J.REST == ("other_private", "Everything else in the private sector (mining and logging, information, financial activities, other services)")


def test_the_saved_files_are_the_real_record_fetched_for_this_card():
    assert set(F) == set(IDS)
    for sid in IDS:
        lines = F[sid].strip().splitlines()
        assert lines[0] == f"observation_date,{sid}" and len(lines) == 131 and lines[1].startswith("2015-12-01,") and lines[-1].startswith("2026-09-01,")
    assert [F[s].splitlines()[-1] for s in ("JTSJOL", "JTS1000JOL", "JTS9000JOL", "JTS7000JOL")] == ["2026-09-01,7523", "2026-09-01,6644", "2026-09-01,880", "2026-09-01,779"]


def test_missing_values_are_skipped_never_filled():
    text = "observation_date,JTSJOL\n2026-07-01,7335\n2026-08-01,.\n2026-09-01,7523\n"
    assert J.parse(text, "JTSJOL") == {date(2026, 7, 1): 7335.0, date(2026, 9, 1): 7523.0}


def test_the_whole_real_record_passes_every_check_and_the_gaps_are_the_ones_worked_out_beforehand():
    s = run(real())
    assert s["detail"] == {"months_checked": 130, "first_month": "2015-12", "last_month": "2026-09", "largest_sum_gap": 1.0, "closest_part_margin": 68.0, "smallest_rest_of_private": 497.0}
    assert s["checks"] == {"months_in_a_row": True, "range_ok": True, "totals_add_up_ok": True, "parts_inside_wholes_ok": True}


def test_the_download_the_card_makes_gives_the_same_card():
    r = asyncio.run(J.JoltsIndustries(client=_client(_handler)).overview(NOW))
    assert {k: v for k, v in r.items() if k not in ("as_of", "demo")} == run(real(), NOW.date()) and r["demo"] is False


def test_the_newest_month_by_hand():
    s = run(real())
    assert s["available"] is True and s["month"] == "2026-09" and s["date"] == "2026-09-01" and s["age_days"] == 79 and s["freshness"] == "CURRENT"
    assert s["source"] == J.SOURCE and s["url"] == "https://fred.stlouisfed.org/series/JTSJOL"
    assert s["total"] == {"openings_thousands": 7523.0, "year_ago_thousands": 7169.0, "change_year_pct": 4.9, "private_thousands": 6644.0, "private_share_pct": 88.3,
                          "government_thousands": 880.0, "government_share_pct": 11.7,
                          "range": {"months": 120, "first": "2016-10", "lowest": {"value": 4606.0, "month": "2020-04"}, "highest": {"value": 12301.0, "month": "2022-03"}, "share_lower_pct": 62}}
    rest = "Everything else in the private sector (mining and logging, information, financial activities, other services)"
    assert [(g["key"], g["label"], g["derived"], g["openings_thousands"], g["share_pct"], g["year_ago_thousands"], g["change_year_pct"], g["range"]["share_lower_pct"]) for g in s["industries"]] == [
        ("education_health", "Private education and health services", False, 1614.0, 21.5, 1548.0, 4.3, 59),
        ("business", "Professional and business services", False, 1310.0, 17.4, 1267.0, 3.4, 53),
        ("trade_transport", "Trade, transportation and utilities", False, 1283.0, 17.1, 1054.0, 21.7, 52),
        ("government", "Government", False, 880.0, 11.7, 764.0, 15.2, 63),
        ("leisure", "Leisure and hospitality", False, 779.0, 10.4, 1152.0, -32.4, 9),
        ("manufacturing", "Manufacturing", False, 584.0, 7.8, 389.0, 50.1, 75),
        ("construction", "Construction", False, 298.0, 4.0, 206.0, 44.7, 51),
        ("other_private", rest, True, 776.0, 10.3, 789.0, -1.6, 32)]
    assert {g["key"]: [(p["key"], p["label"], p["derived"], p["openings_thousands"], p["share_pct"], p["year_ago_thousands"], p["change_year_pct"], p["range"]["share_lower_pct"]) for p in g["parts"]] for g in s["industries"]} == {
        "education_health": [("health_care", "Health care and social assistance", False, 1479.0, 19.7, 1417.0, 4.4, 60), ("education", "Private educational services", True, 135.0, 1.8, 131.0, 3.1, 53)],
        "business": [],
        "trade_transport": [("retail", "Retail trade", False, 698.0, 9.3, 588.0, 18.7, 39), ("wholesale_transport", "Wholesale trade, transportation and utilities", True, 585.0, 7.8, 466.0, 25.5, 68)],
        "government": [("state_local", "State and local government", False, 776.0, 10.3, 656.0, 18.3, 68), ("federal", "Federal government", True, 104.0, 1.4, 108.0, -3.7, 28)],
        "leisure": [("food_lodging", "Accommodation and food services", False, 659.0, 8.8, 989.0, -33.4, 8), ("arts", "Arts, entertainment and recreation", False, 120.0, 1.6, 164.0, -26.8, 39)],
        "manufacturing": [("durable", "Durable goods manufacturing", False, 403.0, 5.4, 248.0, 62.5, 78), ("nondurable", "Nondurable goods manufacturing", False, 180.0, 2.4, 141.0, 27.7, 56)],
        "construction": [], "other_private": []}
    by_key = {g["key"]: g for g in s["industries"]}
    assert by_key["construction"]["range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 135.0, "month": "2024-12"}, "highest": {"value": 457.0, "month": "2022-03"}, "share_lower_pct": 51}
    assert by_key["other_private"]["range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 497.0, "month": "2020-04"}, "highest": {"value": 1390.0, "month": "2022-06"}, "share_lower_pct": 32}


def test_a_clean_exact_world_passes_with_no_gap_at_all():
    s = run(world())
    assert s["detail"] == {"months_checked": 130, "first_month": "2015-12", "last_month": "2026-09", "largest_sum_gap": 0.0, "closest_part_margin": 100.0, "smallest_rest_of_private": 800.0}


# ---------------------------------------------------------------- same months, dates, a row, enough of them

@pytest.mark.parametrize("sid", IDS)
def test_series_that_end_in_different_months_are_refused(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the JOLTS industry series end in different months")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_a_month_missing_in_the_middle_is_refused_and_named(sid):
    d = world()
    del d[sid][MID]
    refused(d, f"the {NAME[sid]} series covers different months than total nonfarm")


def test_total_nonfarm_with_the_hole_makes_the_first_other_series_the_one_named():
    d = world()
    del d["JTSJOL"][MID]
    refused(d, "the private series covers different months than total nonfarm")


@pytest.mark.parametrize("bad", [date(2019, 5, 2), date(2019, 5, 31)])
def test_a_date_that_is_not_the_1st_is_refused(bad):
    d = world()
    for s in IDS:
        d[s][bad] = d[s].pop(MID)
    refused(d, "a JOLTS industry date is not the 1st of a month")


def test_months_that_skip_a_month_are_refused():
    d = world()
    for s in IDS:
        del d[s][MID]
    refused(d, "the JOLTS industry months skip a month after 2019-04")


def test_a_skipped_month_across_the_turn_of_the_year_is_found_too():
    d = world()
    for s in IDS:
        del d[s][date(2018, 1, 1)]
    refused(d, "the JOLTS industry months skip a month after 2017-12")


def test_a_skip_right_after_the_oldest_month_and_right_before_the_newest_is_found_too():
    d = world()
    for s in IDS:
        del d[s][mback(FIRST, -1)]                                                    # the second month of the world
    refused(d, "the JOLTS industry months skip a month after 2015-12")
    d = world()
    for s in IDS:
        del d[s][mback(LAST, 1)]                                                      # the month before the newest
    refused(d, "the JOLTS industry months skip a month after 2026-07")


def test_fewer_than_120_months_are_refused_and_120_pass():
    assert run(world(120))["detail"]["months_checked"] == 120
    refused(world(119), "the JOLTS industries cover 119 months, fewer than the 120 expected")


# ---------------------------------------------------------------- ranges: both edges of every limit; what speaks next when the value sits inside an edge

EDGES = [
    ("JTSJOL", 1000.0, f"total nonfarm differs from private plus government by 6700 thousand in {M}, over 1.5"),
    ("JTSJOL", 999.9, f"total nonfarm openings of 999.9 thousand in {M} is outside 1,000 to 25,000"),
    ("JTSJOL", 25000.0, f"total nonfarm differs from private plus government by 17300 thousand in {M}, over 1.5"),
    ("JTSJOL", 25000.1, f"total nonfarm openings of 25,000.1 thousand in {M} is outside 1,000 to 25,000"),
    ("JTS1000JOL", 1000.0, f"total nonfarm differs from private plus government by 5700 thousand in {M}, over 1.5"),
    ("JTS1000JOL", 999.9, f"private openings of 999.9 thousand in {M} is outside 1,000 to 25,000"),
    ("JTS1000JOL", 25000.0, f"total nonfarm differs from private plus government by 18300 thousand in {M}, over 1.5"),
    ("JTS1000JOL", 25000.1, f"private openings of 25,000.1 thousand in {M} is outside 1,000 to 25,000"),
    ("JTS9000JOL", 130.0, f"total nonfarm differs from private plus government by 870 thousand in {M}, over 1.5"),
    ("JTS9000JOL", 129.9, f"government openings of 129.9 thousand in {M} is outside 130 to 2,500"),
    ("JTS9000JOL", 2500.0, f"total nonfarm differs from private plus government by 1500 thousand in {M}, over 1.5"),
    ("JTS9000JOL", 2500.1, f"government openings of 2,500.1 thousand in {M} is outside 130 to 2,500"),
    ("JTS9200JOL", 99.9, f"state and local openings of 99.9 thousand in {M} is outside 100 to 2,100"),
    ("JTS9200JOL", 2100.0, f"state and local openings exceed government by 1100 thousand in {M}, over 1"),
    ("JTS9200JOL", 2100.1, f"state and local openings of 2,100.1 thousand in {M} is outside 100 to 2,100"),
    ("JTS2300JOL", 9.9, f"construction openings of 9.9 thousand in {M} is outside 10 to 1,000"),
    ("JTS2300JOL", 1000.1, f"construction openings of 1,000.1 thousand in {M} is outside 10 to 1,000"),
    ("JTS3000JOL", 40.0, f"manufacturing differs from durable goods plus nondurable goods by 560 thousand in {M}, over 1.5"),
    ("JTS3000JOL", 39.9, f"manufacturing openings of 39.9 thousand in {M} is outside 40 to 2,000"),
    ("JTS3000JOL", 2000.0, f"manufacturing differs from durable goods plus nondurable goods by 1400 thousand in {M}, over 1.5"),
    ("JTS3000JOL", 2000.1, f"manufacturing openings of 2,000.1 thousand in {M} is outside 40 to 2,000"),
    ("JTS3200JOL", 20.0, f"manufacturing differs from durable goods plus nondurable goods by 380 thousand in {M}, over 1.5"),
    ("JTS3200JOL", 19.9, f"durable goods openings of 19.9 thousand in {M} is outside 20 to 1,300"),
    ("JTS3200JOL", 1300.0, f"manufacturing differs from durable goods plus nondurable goods by 900 thousand in {M}, over 1.5"),
    ("JTS3200JOL", 1300.1, f"durable goods openings of 1,300.1 thousand in {M} is outside 20 to 1,300"),
    ("JTS3400JOL", 20.0, f"manufacturing differs from durable goods plus nondurable goods by 180 thousand in {M}, over 1.5"),
    ("JTS3400JOL", 19.9, f"nondurable goods openings of 19.9 thousand in {M} is outside 20 to 800"),
    ("JTS3400JOL", 800.0, f"manufacturing differs from durable goods plus nondurable goods by 600 thousand in {M}, over 1.5"),
    ("JTS3400JOL", 800.1, f"nondurable goods openings of 800.1 thousand in {M} is outside 20 to 800"),
    ("JTS4000JOL", 150.0, f"retail openings exceed trade and transport by 550 thousand in {M}, over 1"),
    ("JTS4000JOL", 149.9, f"trade and transport openings of 149.9 thousand in {M} is outside 150 to 4,500"),
    ("JTS4000JOL", 4500.0, f"the six industries add up to more than private by 2400 thousand in {M}, over 3.5"),
    ("JTS4000JOL", 4500.1, f"trade and transport openings of 4,500.1 thousand in {M} is outside 150 to 4,500"),
    ("JTS4400JOL", 99.9, f"retail openings of 99.9 thousand in {M} is outside 100 to 3,000"),
    ("JTS4400JOL", 3000.0, f"retail openings exceed trade and transport by 1700 thousand in {M}, over 1"),
    ("JTS4400JOL", 3000.1, f"retail openings of 3,000.1 thousand in {M} is outside 100 to 3,000"),
    ("JTS540099JOL", 199.9, f"business services openings of 199.9 thousand in {M} is outside 200 to 5,000"),
    ("JTS540099JOL", 5000.0, f"the six industries add up to more than private by 2900 thousand in {M}, over 3.5"),
    ("JTS540099JOL", 5000.1, f"business services openings of 5,000.1 thousand in {M} is outside 200 to 5,000"),
    ("JTS6000JOL", 200.0, f"health care openings exceed education and health by 1300 thousand in {M}, over 1"),
    ("JTS6000JOL", 199.9, f"education and health openings of 199.9 thousand in {M} is outside 200 to 4,500"),
    ("JTS6000JOL", 4500.0, f"the six industries add up to more than private by 2100 thousand in {M}, over 3.5"),
    ("JTS6000JOL", 4500.1, f"education and health openings of 4,500.1 thousand in {M} is outside 200 to 4,500"),
    ("JTS6200JOL", 199.9, f"health care openings of 199.9 thousand in {M} is outside 200 to 4,200"),
    ("JTS6200JOL", 4200.0, f"health care openings exceed education and health by 2600 thousand in {M}, over 1"),
    ("JTS6200JOL", 4200.1, f"health care openings of 4,200.1 thousand in {M} is outside 200 to 4,200"),
    ("JTS7000JOL", 100.0, f"leisure differs from arts plus food and lodging by 700 thousand in {M}, over 1.5"),
    ("JTS7000JOL", 99.9, f"leisure openings of 99.9 thousand in {M} is outside 100 to 3,500"),
    ("JTS7000JOL", 3500.0, f"leisure differs from arts plus food and lodging by 2700 thousand in {M}, over 1.5"),
    ("JTS7000JOL", 3500.1, f"leisure openings of 3,500.1 thousand in {M} is outside 100 to 3,500"),
    ("JTS7100JOL", 8.0, f"leisure differs from arts plus food and lodging by 92 thousand in {M}, over 1.5"),
    ("JTS7100JOL", 7.9, f"arts openings of 7.9 thousand in {M} is outside 8 to 450"),
    ("JTS7100JOL", 450.0, f"leisure differs from arts plus food and lodging by 350 thousand in {M}, over 1.5"),
    ("JTS7100JOL", 450.1, f"arts openings of 450.1 thousand in {M} is outside 8 to 450"),
    ("JTS7200JOL", 80.0, f"leisure differs from arts plus food and lodging by 620 thousand in {M}, over 1.5"),
    ("JTS7200JOL", 79.9, f"food and lodging openings of 79.9 thousand in {M} is outside 80 to 3,100"),
    ("JTS7200JOL", 3100.0, f"leisure differs from arts plus food and lodging by 2400 thousand in {M}, over 1.5"),
    ("JTS7200JOL", 3100.1, f"food and lodging openings of 3,100.1 thousand in {M} is outside 80 to 3,100"),
]
PASSES = [("JTS9200JOL", 100.0), ("JTS2300JOL", 10.0), ("JTS2300JOL", 1000.0), ("JTS4400JOL", 100.0), ("JTS540099JOL", 200.0), ("JTS6200JOL", 200.0)]      # on a limit, and no sum or part sees them


@pytest.mark.parametrize("sid, v, text", EDGES)
def test_each_limit_is_pinned_at_both_edges(sid, v, text):
    d = world()
    d[sid][MID] = v
    refused(d, text)


@pytest.mark.parametrize("sid, v", PASSES)
def test_a_value_on_its_limit_that_no_other_check_sees_passes_everything(sid, v):
    d = world()
    d[sid][MID] = v
    assert run(d)["available"] is True


@pytest.mark.parametrize("sid", IDS)
def test_a_range_is_checked_in_the_oldest_and_the_newest_month_not_only_in_the_middle(sid):
    lo, hi = J.LIMITS[sid]
    for when in (FIRST, LAST):
        for bad in (hi + 0.1, lo - 0.1):
            d = world()
            d[sid][when] = bad
            with pytest.raises(ValueError) as e:
                J.summarize(d, TODAY)
            assert str(e.value).startswith(f"{NAME[sid]} openings of ") and f" in {mlab(when)} is outside " in str(e.value)


# ---------------------------------------------------------------- the sums, one at a time

SUMS = [("JTSJOL", ("JTS1000JOL", "JTS9000JOL"), "total nonfarm differs from private plus government"),
        ("JTS3000JOL", ("JTS3200JOL", "JTS3400JOL"), "manufacturing differs from durable goods plus nondurable goods"),
        ("JTS7000JOL", ("JTS7100JOL", "JTS7200JOL"), "leisure differs from arts plus food and lodging")]


@pytest.mark.parametrize("whole, parts, text", SUMS)
@pytest.mark.parametrize("when", [FIRST, LAST, MID])
def test_each_sum_must_hold_within_one_and_a_half_thousand(whole, parts, text, when):
    d = world()
    d[whole][when] = BASE[whole] + 1.5                                                # exactly the tolerance: passes
    assert run(d)["detail"]["largest_sum_gap"] == 1.5
    d[whole][when] = BASE[whole] + 1.75                                               # a quarter over: the message names the month
    refused(d, f"{text} by 1.75 thousand in {mlab(when)}, over 1.5")
    d[whole][when] = BASE[whole] - 1.5                                                # and the same distance below
    assert run(d)["detail"]["largest_sum_gap"] == 1.5
    d[whole][when] = BASE[whole] - 1.75
    refused(d, f"{text} by 1.75 thousand in {mlab(when)}, over 1.5")


@pytest.mark.parametrize("whole, parts, text", SUMS)
def test_every_term_of_a_sum_counts(whole, parts, text):
    for sid, v in ((whole, BASE[whole] + 2.0), (parts[0], BASE[parts[0]] + 2.0), (parts[1], BASE[parts[1]] + 2.0), (parts[0], BASE[parts[0]] - 2.0), (parts[1], BASE[parts[1]] - 2.0)):
        d = world()
        d[sid][MID] = v
        refused(d, f"{text} by 2 thousand in {M}, over 1.5")


def test_the_largest_gap_of_the_sums_is_the_largest_not_the_first_or_the_last():
    d = world()
    d["JTSJOL"][date(2018, 1, 1)] = BASE["JTSJOL"] + 0.5                              # the first sum, an early month
    d["JTS3000JOL"][MID] = BASE["JTS3000JOL"] - 1.25                                  # the second sum, the largest
    d["JTS7000JOL"][LAST] = BASE["JTS7000JOL"] + 1.0                                  # the third sum, the newest month
    assert run(d)["detail"]["largest_sum_gap"] == 1.25


def test_the_largest_sum_gap_is_rounded_to_three_decimals():
    d = world()
    d["JTSJOL"][MID] = BASE["JTSJOL"] + 1.1239
    assert run(d)["detail"]["largest_sum_gap"] == 1.124


# ---------------------------------------------------------------- the parts inside their wholes

WITHIN = [("JTS4400JOL", "JTS4000JOL", "retail openings exceed trade and transport"),
          ("JTS6200JOL", "JTS6000JOL", "health care openings exceed education and health"),
          ("JTS9200JOL", "JTS9000JOL", "state and local openings exceed government")]


@pytest.mark.parametrize("part, whole, text", WITHIN)
@pytest.mark.parametrize("when", [FIRST, LAST, MID])
def test_a_part_may_exceed_its_whole_by_the_rounding_only(part, whole, text, when):
    d = world()
    d[part][when] = BASE[whole] + 1.0                                                 # exactly the tolerance: passes
    assert run(d)["detail"]["closest_part_margin"] == -1.0
    d[part][when] = BASE[whole] + 1.25                                                # a quarter over
    refused(d, f"{text} by 1.25 thousand in {mlab(when)}, over 1")


@pytest.mark.parametrize("part, whole, text", WITHIN)
def test_the_whole_counts_in_the_comparison_too(part, whole, text):
    d = world()
    d[whole][MID] = BASE[part] - 1.25                                                 # the whole falls below its part by 1.25 ...
    if whole == "JTS9000JOL":
        d["JTSJOL"][MID] = BASE["JTSJOL"] - (BASE[whole] - d[whole][MID])             # ... and, for government, the total follows it so that the sum still holds
    refused(d, f"{text} by 1.25 thousand in {M}, over 1")


def test_the_closest_margin_is_the_smallest_of_the_three_pairs_and_all_months_not_the_first_or_the_last():
    d = world()
    d["JTS4400JOL"][MID] = 1280.0                                                     # retail: margin 20 (the first pair)
    d["JTS6200JOL"][date(2018, 1, 1)] = 1598.0                                        # health care: margin 2, the smallest, in the middle of the second pair
    d["JTS9200JOL"][LAST] = 993.0                                                     # state and local: margin 7 in the newest month of the third pair
    assert run(d)["detail"]["closest_part_margin"] == 2.0


def test_the_closest_margin_and_the_smallest_rest_are_rounded_to_three_decimals():
    d = world()
    d["JTS6200JOL"][MID] = 1597.875                                                   # margin 2.125: two decimals would give 2.12
    assert run(d)["detail"]["closest_part_margin"] == 2.125
    d = world()
    d["JTS540099JOL"][MID] = BASE["JTS540099JOL"] + 0.125                             # rest 799.875: two decimals would give 799.88
    assert run(d)["detail"]["smallest_rest_of_private"] == 799.875


# ---------------------------------------------------------------- what is left of private after the six industries

def test_the_six_industries_may_exceed_private_by_the_rounding_only():
    d = world()
    d["JTS540099JOL"][MID] = BASE["JTS540099JOL"] + 803.5                             # the rest of private is exactly -3.5: passes
    assert run(d)["detail"]["smallest_rest_of_private"] == -3.5
    d["JTS540099JOL"][MID] = BASE["JTS540099JOL"] + 803.75
    refused(d, f"the six industries add up to more than private by 3.75 thousand in {M}, over 3.5")


@pytest.mark.parametrize("when", [FIRST, LAST])
def test_the_rest_of_private_is_checked_in_the_oldest_and_the_newest_month(when):
    d = world()
    d["JTS540099JOL"][when] = BASE["JTS540099JOL"] + 803.75
    refused(d, f"the six industries add up to more than private by 3.75 thousand in {mlab(when)}, over 3.5")


@pytest.mark.parametrize("sid, follower", [("JTS3000JOL", "JTS3200JOL"), ("JTS4000JOL", None), ("JTS540099JOL", None), ("JTS6000JOL", None), ("JTS7000JOL", "JTS7200JOL")])
def test_every_one_of_the_six_industries_counts_in_the_rest(sid, follower):
    d = world()
    d[sid][MID] = BASE[sid] + 803.75
    if follower:
        d[follower][MID] = BASE[follower] + 803.75                                    # its part follows it so that its own sum still holds
    refused(d, f"the six industries add up to more than private by 3.75 thousand in {M}, over 3.5")


def test_construction_counts_in_the_rest_too():
    d = world()
    d["JTS2300JOL"][MID] = 1000.0                                                     # construction on its limit (+700) ...
    d["JTS540099JOL"][MID] = BASE["JTS540099JOL"] + 103.5
    assert run(d)["detail"]["smallest_rest_of_private"] == -3.5                       # ... and 103.5 more elsewhere: the rest is -3.5
    d["JTS540099JOL"][MID] = BASE["JTS540099JOL"] + 103.75
    refused(d, f"the six industries add up to more than private by 3.75 thousand in {M}, over 3.5")


def test_private_counts_in_the_rest_too():
    d = world()
    d["JTS1000JOL"][MID] = BASE["JTS1000JOL"] - 803.75
    d["JTSJOL"][MID] = BASE["JTSJOL"] - 803.75                                        # the total follows private so that the first sum still holds
    refused(d, f"the six industries add up to more than private by 3.75 thousand in {M}, over 3.5")


def test_the_smallest_rest_is_the_smallest_month_not_the_first_or_the_last():
    d = world()
    d["JTS540099JOL"][FIRST] = BASE["JTS540099JOL"] + 100.0                           # rest 700 in the oldest month
    d["JTS540099JOL"][date(2018, 1, 1)] = BASE["JTS540099JOL"] + 500.0                # rest 300 in the middle: the smallest
    d["JTS540099JOL"][LAST] = BASE["JTS540099JOL"] + 200.0                            # rest 600 in the newest
    assert run(d)["detail"]["smallest_rest_of_private"] == 300.0


# ---------------------------------------------------------------- the order in which the checks speak

def test_the_checks_run_in_a_fixed_order():
    d = world()                                                                       # 1. ending in different months comes before a hole in the middle
    del d["JTS1000JOL"][LAST]
    del d["JTS9000JOL"][MID]
    refused(d, "the JOLTS industry series end in different months")
    d = world()                                                                       # 2. a hole comes before a date that is not the 1st (the date is the same in every series)
    del d["JTS1000JOL"][MID]
    for s in IDS:
        d[s][date(2019, 6, 2)] = d[s].pop(date(2019, 6, 1))
    refused(d, "the private series covers different months than total nonfarm")
    d = world()                                                                       # 3. a date that is not the 1st comes before a skipped month
    for s in IDS:
        d[s][date(2019, 6, 2)] = d[s].pop(date(2019, 6, 1))
        del d[s][date(2018, 1, 1)]
    refused(d, "a JOLTS industry date is not the 1st of a month")
    d = world(119)                                                                    # 4. a skipped month comes before the count of months
    for s in IDS:
        del d[s][date(2021, 1, 1)]
    refused(d, "the JOLTS industry months skip a month after 2020-12")
    d = world(119)                                                                    # 5. the count of months comes before the ranges
    d["JTSJOL"][MID] = 10.0
    refused(d, "the JOLTS industries cover 119 months, fewer than the 120 expected")
    d = world()                                                                       # 6. a range comes before a sum (the value is outside its range and breaks the first sum)
    d["JTSJOL"][MID] = 25000.1
    refused(d, f"total nonfarm openings of 25,000.1 thousand in {M} is outside 1,000 to 25,000")
    d = world()                                                                       # 7. a sum comes before a part inside its whole (retail is over trade and transport, and the first sum is broken)
    d["JTS4400JOL"][MID] = 1400.0
    d["JTSJOL"][MID] = BASE["JTSJOL"] + 5.0
    refused(d, f"total nonfarm differs from private plus government by 5 thousand in {M}, over 1.5")
    d = world()                                                                       # 8. a part inside its whole comes before the rest of private (retail is over its whole, and the six exceed private)
    d["JTS4400JOL"][MID] = 1400.0
    d["JTS540099JOL"][MID] = BASE["JTS540099JOL"] + 900.0
    refused(d, f"retail openings exceed trade and transport by 100 thousand in {M}, over 1")


def test_the_sums_speak_in_the_order_of_the_table():
    d = world()
    d["JTS3000JOL"][MID] = BASE["JTS3000JOL"] + 5.0
    d["JTS7000JOL"][MID] = BASE["JTS7000JOL"] + 7.0
    refused(d, f"manufacturing differs from durable goods plus nondurable goods by 5 thousand in {M}, over 1.5")
    d["JTSJOL"][MID] = BASE["JTSJOL"] + 3.0
    refused(d, f"total nonfarm differs from private plus government by 3 thousand in {M}, over 1.5")


def test_the_parts_inside_their_wholes_speak_in_the_order_of_the_table():
    d = world()
    d["JTS6200JOL"][MID] = 1700.0
    d["JTS9200JOL"][MID] = 1200.0
    refused(d, f"health care openings exceed education and health by 100 thousand in {M}, over 1")
    d["JTS4400JOL"][MID] = 1500.0
    refused(d, f"retail openings exceed trade and transport by 200 thousand in {M}, over 1")


def test_ranges_are_checked_series_by_series_in_the_order_of_the_table_and_then_month_by_month():
    d = world()
    d["JTS9000JOL"][FIRST] = 2600.0
    d["JTS1000JOL"][LAST] = 25001.0
    refused(d, "private openings of 25,001 thousand in 2026-09 is outside 1,000 to 25,000")
    d = world()
    d["JTS1000JOL"][LAST] = 25001.0
    d["JTS1000JOL"][FIRST] = 26000.0
    refused(d, "private openings of 26,000 thousand in 2015-12 is outside 1,000 to 25,000")


# ---------------------------------------------------------------- summary: order, shares, changes, derived rows, ranges, freshness

def test_a_flat_world_is_listed_largest_first_with_the_remainder_last():
    s = run(world())
    assert [g["key"] for g in s["industries"]] == ["education_health", "business", "trade_transport", "government", "leisure", "manufacturing", "construction", "other_private"]
    assert {g["key"]: [p["key"] for p in g["parts"]] for g in s["industries"]} == {"education_health": ["health_care", "education"], "business": [], "trade_transport": ["retail", "wholesale_transport"],
                                                                                   "government": ["state_local", "federal"], "leisure": ["food_lodging", "arts"], "manufacturing": ["durable", "nondurable"],
                                                                                   "construction": [], "other_private": []}
    assert [(g["key"], g["openings_thousands"], g["derived"]) for g in s["industries"]][-1] == ("other_private", 800.0, True)
    assert [(p["key"], p["openings_thousands"], p["derived"]) for g in s["industries"] for p in g["parts"] if p["derived"]] == [("education", 100.0, True), ("wholesale_transport", 600.0, True), ("federal", 200.0, True)]


def test_the_order_follows_the_size_not_the_order_of_the_table():
    d = world()
    d["JTS540099JOL"][LAST] = 1700.0                                                  # business services now the largest
    d["JTS6200JOL"][LAST] = 200.0                                                     # health care now the smaller part of education and health (education is 1,400)
    s = run(d)
    assert [g["key"] for g in s["industries"]][:2] == ["business", "education_health"]
    assert [p["key"] for g in s["industries"] if g["key"] == "education_health" for p in g["parts"]] == ["education", "health_care"]


def test_equal_sizes_are_listed_in_the_order_of_their_names():
    d = world()
    d["JTS2300JOL"][LAST] = 1000.0                                                    # construction equals government (1,000): "Construction" comes before "Government"
    d["JTS9200JOL"][LAST] = 500.0                                                     # state and local equals federal (500): "Federal government" comes before "State and local government"
    s = run(d)
    assert [g["key"] for g in s["industries"]] == ["education_health", "business", "trade_transport", "construction", "government", "leisure", "manufacturing", "other_private"]
    assert [p["key"] for g in s["industries"] if g["key"] == "government" for p in g["parts"]] == ["federal", "state_local"]


def test_equal_sizes_are_ordered_by_their_labels_not_by_their_keys():
    d = world()
    d["JTS6000JOL"][LAST] = 1300.0                                                    # education and health equals business services and trade (1,300): by label "Private education ..." comes first, by key "business" would
    d["JTS6200JOL"][LAST] = 1200.0
    assert [g["key"] for g in run(d)["industries"]][:3] == ["education_health", "business", "trade_transport"]
    d = world()
    d["JTS6200JOL"][LAST] = 800.0                                                     # health care equals private educational services (800): by label "Health care ..." comes first, by key "education" would
    assert [p["key"] for g in run(d)["industries"] if g["key"] == "education_health" for p in g["parts"]] == ["health_care", "education"]


def test_the_shares_are_of_total_nonfarm_and_rounded_to_one_decimal():
    s = run(world())
    assert [(g["key"], g["share_pct"]) for g in s["industries"]] == [("education_health", 20.8), ("business", 16.9), ("trade_transport", 16.9), ("government", 13.0), ("leisure", 10.4),
                                                                      ("manufacturing", 7.8), ("construction", 3.9), ("other_private", 10.4)]
    assert [(p["key"], p["share_pct"]) for g in s["industries"] for p in g["parts"]] == [("health_care", 19.5), ("education", 1.3), ("retail", 9.1), ("wholesale_transport", 7.8),
                                                                                         ("state_local", 10.4), ("federal", 2.6), ("food_lodging", 9.1), ("arts", 1.3), ("durable", 5.2), ("nondurable", 2.6)]
    assert s["total"]["private_share_pct"] == 87.0 and s["total"]["government_share_pct"] == 13.0 and s["total"]["private_thousands"] == 6700.0 and s["total"]["government_thousands"] == 1000.0


def test_the_year_comparison_uses_the_same_month_a_year_earlier_and_one_decimal():
    d = world()
    d["JTS2300JOL"][YEAR_AGO] = 270.0
    d["JTS2300JOL"][mback(LAST, 11)] = 280.0                                          # the neighbouring months differ, so a wrong offset is seen
    d["JTS2300JOL"][mback(LAST, 13)] = 250.0
    s = run(d)
    construction = next(g for g in s["industries"] if g["key"] == "construction")
    assert construction["year_ago_thousands"] == 270.0 and construction["change_year_pct"] == 11.1                  # 100 x 30 / 270 = 11.11
    d["JTSJOL"][YEAR_AGO] = BASE["JTSJOL"] - 100.0
    d["JTS1000JOL"][YEAR_AGO] = BASE["JTS1000JOL"] - 100.0                            # the sum holds a year earlier too
    assert run(d)["total"]["year_ago_thousands"] == 7600.0 and run(d)["total"]["change_year_pct"] == 1.3                # 100 x 100 / 7,600 = 1.3158


def test_a_derived_part_has_its_own_year_ago_and_no_change_when_that_was_zero():
    d = world()
    d["JTS9200JOL"][YEAR_AGO] = BASE["JTS9000JOL"]                                    # state and local equal to government a year ago: no federal openings then
    s = run(d)
    federal = next(p for g in s["industries"] for p in g["parts"] if p["key"] == "federal")
    assert federal["derived"] is True and federal["year_ago_thousands"] == 0.0 and federal["change_year_pct"] is None and federal["openings_thousands"] == 200.0


def test_the_range_covers_the_last_120_months_not_the_whole_record_and_counts_strictly_lower_months():
    d = world()
    d["JTS2300JOL"][mback(LAST, 120)] = 900.0                                         # the 121st month back: outside the window
    d["JTS2300JOL"][mback(LAST, 119)] = 950.0                                         # the oldest month inside it
    d["JTS2300JOL"][mback(LAST, 30)] = 100.0
    s = run(d)
    construction = next(g for g in s["industries"] if g["key"] == "construction")
    assert construction["range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 100.0, "month": "2024-03"}, "highest": {"value": 950.0, "month": "2016-10"}, "share_lower_pct": 1}      # 1 of the 120 months is lower than 300
    flat = run(world())
    assert flat["total"]["range"] == {"months": 120, "first": "2016-10", "lowest": {"value": 7700.0, "month": "2016-10"}, "highest": {"value": 7700.0, "month": "2016-10"}, "share_lower_pct": 0}


def test_the_age_and_the_freshness_are_105_days_from_the_1st_of_the_month():
    s = run(world(), LAST + timedelta(days=105))
    assert s["age_days"] == 105 and s["freshness"] == "CURRENT"
    s = run(world(), LAST + timedelta(days=106))
    assert s["age_days"] == 106 and s["freshness"] == "OVERDUE"


def test_the_note_says_what_the_numbers_are_and_what_they_are_not():
    note = run(world())["note"]
    for phrase in ("Job Openings and Labor Turnover Survey (JOLTS) of the US Bureau of Labor Statistics, seasonally adjusted, monthly: job openings by industry",
                   "jobs not filled on the last business day of the month", "The industries add up to the total, within the rounding of each figure to a thousand",
                   "FRED carries sixteen of the survey's industry series; the rest are worked out by subtraction and marked as such", "the federal government, private educational services, wholesale trade with transportation and utilities",
                   "mining and logging, information, financial activities and other services together", "The newest months are preliminary and are revised later; each figure carries its month",
                   "Smaller samples make industry figures noisier than the total", "Plain checks:", "the Check line"):
        assert phrase in note, phrase
    assert note.endswith("This describes the labour market that already happened: it is not a market signal or a forecast.") and len(note) <= 1100


def test_the_module_says_why_each_series_is_asked_for_alone_and_what_it_does_not_check():
    for phrase in ("combined request", "FIRST series only", "NOT checked", "BY SUBTRACTION", "HTTP 404", "the closest the real record comes is 25 thousand"):
        assert phrase in J.__doc__, phrase


def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    for _sid, _v, text in EDGES:
        assert len(text) <= 110, text
        assert fail_reason(ValueError(text)) == f"the data failed a check: {dates_in_words(text)}"
    for text in ("the six industries add up to more than private by 3.75 thousand in 2019-05, over 3.5", "manufacturing differs from durable goods plus nondurable goods by 1400 thousand in 2019-05, over 1.5",
                 "health care openings exceed education and health by 1300 thousand in 2019-05, over 1", "the JOLTS industries cover 119 months, fewer than the 120 expected"):
        assert len(text) <= 110 and fail_reason(ValueError(text)) == f"the data failed a check: {dates_in_words(text)}"


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_sixteen_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = J.JoltsIndustries(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["total"]["openings_thousands"] == 7523.0 and n["n"] == 16 and r["source"].startswith("U.S. Bureau of Labor Statistics") and r["url"] == "https://fred.stlouisfed.org/series/JTSJOL"
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 16


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(J.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = J.JoltsIndustries(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 16
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 16                                                              # still the failure from the cache
    clock["t"] += 1
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 32      # exactly two minutes on it asks again
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 32                                                              # one second short of six hours: kept
    clock["t"] += 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 48                                                              # exactly six hours on: asked again


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = J.JoltsIndustries(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(J.JoltsIndustries(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US job openings by industry could not be read right now (the server had an error, HTTP 503)" and "total" not in r and "industries" not in r
    r = asyncio.run(J.JoltsIndustries(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]                      # anything but 200 is a failure


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == "JTS7100JOL" else _handler(req)

    r = asyncio.run(J.JoltsIndustries(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "total" not in r and "industries" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    bad = dict(F)
    bad["JTSJOL"] = F["JTSJOL"].replace("2026-09-01,7523", "2026-09-01,7253")          # two digits swapped in the newest total: inside its range, but the first sum no longer holds
    r = asyncio.run(J.JoltsIndustries(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US job openings by industry could not be read right now (the data failed a check: total nonfarm differs from private plus government by 271 thousand in September 2026, over 1.5)" and "total" not in r
    bad = dict(F)
    bad["JTS1000JOL"] = F["JTS1000JOL"].replace("2026-09-01,6644", "2026-09-01,66440")
    r = asyncio.run(J.JoltsIndustries(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US job openings by industry could not be read right now (the data failed a check: private openings of 66,440 thousand in September 2026 is outside 1,000 to 25,000)"
    bad = dict(F)
    bad["JTS7100JOL"] = F["JTS7100JOL"].replace("2026-09-01,120", "2026-09-01,x")
    r = asyncio.run(J.JoltsIndustries(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "a JTS7100JOL row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(J.JoltsIndustries(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US job openings by industry could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("JTSJOL")

    monkeypatch.setattr(J, "summarize", boom)
    r = asyncio.run(J.JoltsIndustries(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US job openings by industry could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(J.JoltsIndustries(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US job openings by industry are not shown because made-up values would look real." and "total" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/jolts-industries")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_card_is_refreshed_with_the_other_macro_sources():
    jobs = (Path(__file__).parent.parent / "atlas_api" / "sched" / "jobs.py").read_text(encoding="utf-8")
    app = (Path(__file__).parent.parent / "atlas_api" / "app.py").read_text(encoding="utf-8")
    assert '"jolts", "jolts_industries", "jolts_flows", "us_jobs"' in jobs and '"jolts_industries": jolts_industries' in app and "jolts_industries = JoltsIndustries(demo=demo)" in app and '"/api/macro/jolts-industries"' in app


def test_the_age_and_the_freshness_are_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(J.JoltsIndustries(client=_client(_handler)).overview(datetime(2027, 1, 15, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 136 and r["freshness"] == "OVERDUE" and r["as_of"] == "2027-01-15T12:00:00+00:00"           # 2026-09-01 to 2027-01-15


def test_each_request_asks_for_one_series_from_2000_with_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(J.JoltsIndustries(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)             # never a combined request: FRED applies one start date to the first series only
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert {req.url.params["cosd"] for req in seen} == {"2000-12-01"}


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
    r = asyncio.run(J.JoltsIndustries().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(J.JoltsIndustries(client=given).overview(NOW))
    assert given.is_closed is False
