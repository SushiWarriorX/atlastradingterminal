"""US jobs in detail (BLS Current Employment Statistics via FRED, 26 monthly series: seven parents and the 19 parts they are made of): the real saved record, the limits and tolerances as literals, one check at a time, the figures of the summary and the class."""
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

import atlas_api.usjobsdetail as U

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usjobsdetail.json").read_text(encoding="utf-8"))
TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
LAST = date(2026, 10, 1)

GROUPS = (("trade", "Trade, transportation and utilities", "USTPU", 0.75,
           (("wholesale", "Wholesale trade", "USWTRADE"), ("retail", "Retail trade", "USTRADE"), ("transport", "Transportation and warehousing", "CES4300000001"), ("utilities", "Utilities", "CES4422000001"))),
          ("construction", "Construction", "USCONS", 0.75,
           (("buildings", "Construction of buildings", "CES2023600001"), ("heavy", "Heavy and civil engineering construction", "CES2023700001"), ("specialty", "Specialty trade contractors", "CES2023800001"))),
          ("financial", "Financial activities", "USFIRE", 0.75,
           (("finance", "Finance and insurance", "CES5552000001"), ("realestate", "Real estate and rental and leasing", "CES5553000001"))),
          ("professional", "Professional and business services", "USPBS", 0.75,
           (("technical", "Professional, scientific and technical services", "CES6054000001"), ("management", "Management of companies and enterprises", "CES6055000001"),
            ("administrative", "Administrative, support and waste services", "CES6056000001"))),
          ("education_health", "Education and health services", "USEHS", 0.75,
           (("education", "Private educational services", "CES6561000001"), ("health", "Health care and social assistance", "CES6562000001"))),
          ("leisure", "Leisure and hospitality", "USLAH", 0.75,
           (("arts", "Arts, entertainment and recreation", "CES7071000001"), ("food", "Accommodation and food services", "CES7072000001"))),
          ("government", "Government", "USGOVT", 2.0,
           (("federal", "Federal government", "CES9091000001"), ("state", "State government", "CES9092000001"), ("local", "Local government", "CES9093000001"))))
PARENTS = [g[2] for g in GROUPS]
CHILDREN = [c[2] for g in GROUPS for c in g[4]]
IDS = [sid for g in GROUPS for sid in (g[2], *[c[2] for c in g[4]])]
OF_PARENT = {c[2]: g[2] for g in GROUPS for c in g[4]}
GROUP_OF = {sid: i for i, g in enumerate(GROUPS) for sid in (g[2], *[c[2] for c in g[4]])}
NAME = {"USTPU": "trade, transport and utilities payrolls", "USWTRADE": "wholesale trade payrolls", "USTRADE": "retail trade payrolls", "CES4300000001": "transportation and warehousing payrolls",
        "CES4422000001": "utilities payrolls", "USCONS": "construction payrolls", "CES2023600001": "construction of buildings payrolls", "CES2023700001": "heavy and civil engineering payrolls",
        "CES2023800001": "specialty trade contractors payrolls", "USFIRE": "financial activities payrolls", "CES5552000001": "finance and insurance payrolls", "CES5553000001": "real estate and leasing payrolls",
        "USPBS": "professional and business payrolls", "CES6054000001": "professional and technical payrolls", "CES6055000001": "management of companies payrolls", "CES6056000001": "administrative and waste payrolls",
        "USEHS": "education and health payrolls", "CES6561000001": "private education payrolls", "CES6562000001": "health care and social assistance payrolls", "USLAH": "leisure and hospitality payrolls",
        "CES7071000001": "arts and recreation payrolls", "CES7072000001": "accommodation and food payrolls", "USGOVT": "government payrolls", "CES9091000001": "federal government payrolls",
        "CES9092000001": "state government payrolls", "CES9093000001": "local government payrolls"}
LIMITS = {"USTPU": (3300.0, 57800.0), "USWTRADE": (730.0, 12300.0), "USTRADE": (1550.0, 31800.0), "CES4300000001": (1300.0, 13400.0), "CES4422000001": (235.0, 1490.0),
          "USCONS": (520.0, 16800.0), "CES2023600001": (590.0, 3750.0), "CES2023700001": (360.0, 2430.0), "CES2023800001": (885.0, 10600.0),
          "USFIRE": (680.0, 18500.0), "CES5552000001": (2450.0, 13500.0), "CES5553000001": (805.0, 4950.0),
          "USPBS": (970.0, 45800.0), "CES6054000001": (2250.0, 21800.0), "CES6055000001": (815.0, 5270.0), "CES6056000001": (2265.0, 19200.0),
          "USEHS": (690.0, 56200.0), "CES6561000001": (830.0, 8130.0), "CES6562000001": (4550.0, 48100.0),
          "USLAH": (930.0, 34100.0), "CES7071000001": (555.0, 5410.0), "CES7072000001": (3750.0, 28800.0),
          "USGOVT": (2000.0, 48000.0), "CES9091000001": (455.0, 6880.0), "CES9092000001": (575.0, 11100.0), "CES9093000001": (1745.0, 30400.0)}
WORDS = {2: "two", 3: "three", 4: "four"}
LEAVES = {"USWTRADE": 6000.0, "USTRADE": 15500.0, "CES4300000001": 6600.0, "CES4422000001": 600.0, "CES2023600001": 1800.0, "CES2023700001": 1200.0, "CES2023800001": 5200.0, "CES5552000001": 6600.0,
          "CES5553000001": 2400.0, "CES6054000001": 10800.0, "CES6055000001": 2600.0, "CES6056000001": 9000.0, "CES6561000001": 4000.0, "CES6562000001": 24000.0, "CES7071000001": 2600.0, "CES7072000001": 14300.0,
          "CES9091000001": 2700.0, "CES9092000001": 5500.0, "CES9093000001": 15200.0}
STEP = {"USWTRADE": 2.0, "USTRADE": 10.0, "CES4300000001": 5.0, "CES4422000001": 1.0, "CES2023600001": 1.0, "CES2023700001": 1.0, "CES2023800001": 3.0, "CES5552000001": 4.0, "CES5553000001": 2.0,
        "CES6054000001": 8.0, "CES6055000001": 1.0, "CES6056000001": 6.0, "CES6561000001": 1.0, "CES6562000001": 20.0, "CES7071000001": 1.0, "CES7072000001": 6.0, "CES9091000001": 1.0, "CES9092000001": 2.0, "CES9093000001": 3.0}


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
    for g in GROUPS:
        v[g[2]] = sum(l[c[2]] for c in g[4])
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
    for sid, g in deltas.items():
        d[sid][month] += g
    return d


def gap(data, month, g, e):
    """Make the sum of group `g` (an index of GROUPS) off by exactly `e` in one month and leave everything else alone: the parent is the sum of its parts plus e."""
    d = {sid: dict(s) for sid, s in data.items()}
    d[GROUPS[g][2]][month] = sum(d[c[2]][month] for c in GROUPS[g][4]) + e
    return d


OLDEST, MIDDLE = mback(LAST, 139), mback(LAST, 70)


def sum_msg(g, gp, month):
    return f"{NAME[GROUPS[g][2]]} are {num(gp)} thousand off its {WORDS[len(GROUPS[g][4])]} parts in {label(month)}, over {GROUPS[g][3]:g}"


# ---------------------------------------------------------------- the real record

REAL_ITEMS = {"trade": (28818.0, 22.0, 0.1, 104.0, 0.4, None), "wholesale": (6068.8, -9.1, -0.1, 14.2, 0.2, 21.1), "retail": (15501.3, 6.0, 0.0, 63.3, 0.4, 53.8), "transport": (6636.1, 24.8, 0.4, 17.0, 0.3, 23.0),
              "utilities": (611.5, 0.1, 0.0, 9.6, 1.6, 2.1), "construction": (8367.0, -3.0, 0.0, 124.0, 1.5, None), "buildings": (1873.5, 1.7, 0.1, 29.9, 1.6, 22.4), "heavy": (1212.7, 2.5, 0.2, 29.2, 2.5, 14.5),
              "specialty": (5281.0, -7.3, -0.1, 65.3, 1.3, 63.1), "financial": (9085.0, 7.0, 0.1, -99.0, -1.1, None), "finance": (6640.8, 1.3, 0.0, -97.0, -1.4, 73.1), "realestate": (2443.9, 5.6, 0.2, -1.9, -0.1, 26.9),
              "professional": (22604.0, 70.0, 0.3, 269.0, 1.2, None), "technical": (10881.3, 32.9, 0.3, 127.2, 1.2, 48.1), "management": (2630.8, 8.7, 0.3, 5.6, 0.2, 11.6),
              "administrative": (9091.4, 28.1, 0.3, 135.5, 1.5, 40.2), "education_health": (28058.0, 53.0, 0.2, 525.0, 1.9, None), "education": (4053.3, -2.0, 0.0, 6.1, 0.2, 14.4),
              "health": (24004.6, 55.1, 0.2, 518.8, 2.2, 85.6), "leisure": (16964.0, -13.0, -0.1, 16.0, 0.1, None), "arts": (2659.9, -2.6, -0.1, -37.7, -1.4, 15.7), "food": (14304.1, -10.6, -0.1, 53.4, 0.4, 84.3),
              "government": (23332.0, 6.0, 0.0, -58.0, -0.2, None), "federal": (2677.0, -1.0, 0.0, -71.0, -2.6, 11.5), "state": (5479.0, 8.0, 0.1, -14.0, -0.3, 23.5), "local": (15176.0, -1.0, 0.0, 27.0, 0.2, 65.0)}
TREND_ITEMS = {"trade": (31238.0, 18.0, 0.1, 216.0, 0.7, None), "wholesale": (6282.0, 2.0, 0.0, 24.0, 0.4, 20.1), "retail": (16910.0, 10.0, 0.1, 120.0, 0.7, 54.1), "transport": (7305.0, 5.0, 0.1, 60.0, 0.8, 23.4),
               "utilities": (741.0, 1.0, 0.1, 12.0, 1.6, 2.4), "construction": (8905.0, 5.0, 0.1, 60.0, 0.7, None), "buildings": (1941.0, 1.0, 0.1, 12.0, 0.6, 21.8), "heavy": (1341.0, 1.0, 0.1, 12.0, 0.9, 15.1),
               "specialty": (5623.0, 3.0, 0.1, 36.0, 0.6, 63.1), "financial": (9846.0, 6.0, 0.1, 72.0, 0.7, None), "finance": (7164.0, 4.0, 0.1, 48.0, 0.7, 72.8), "realestate": (2682.0, 2.0, 0.1, 24.0, 0.9, 27.2),
               "professional": (24515.0, 15.0, 0.1, 180.0, 0.7, None), "technical": (11928.0, 8.0, 0.1, 96.0, 0.8, 48.7), "management": (2741.0, 1.0, 0.0, 12.0, 0.4, 11.2),
               "administrative": (9846.0, 6.0, 0.1, 72.0, 0.7, 40.2), "education_health": (30961.0, 21.0, 0.1, 252.0, 0.8, None), "education": (4141.0, 1.0, 0.0, 12.0, 0.3, 13.4),
               "health": (26820.0, 20.0, 0.1, 240.0, 0.9, 86.6), "leisure": (17887.0, 7.0, 0.0, 84.0, 0.5, None), "arts": (2741.0, 1.0, 0.0, 12.0, 0.4, 15.3), "food": (15146.0, 6.0, 0.0, 72.0, 0.5, 84.7),
               "government": (24246.0, 6.0, 0.0, 72.0, 0.3, None), "federal": (2841.0, 1.0, 0.0, 12.0, 0.4, 11.7), "state": (5782.0, 2.0, 0.0, 24.0, 0.4, 23.8), "local": (15623.0, 3.0, 0.0, 36.0, 0.2, 64.4)}


def items_of(r):
    return [x for g in r["groups"] for x in [g["parent"]] + g["children"]]


def got_of(r):
    return {x["key"]: (x["thousands"], x["change_month"], x["change_month_pct"], x["change_year"], x["change_year_pct"], x.get("share_pct")) for x in items_of(r)}


def test_the_whole_real_record_adds_up_in_every_month_and_the_checks_pass():
    data = real()
    months = sorted(data["USTPU"])
    assert len(months) == 142 and months[0] == date(2015, 1, 1) and months[-1] == LAST and all(set(data[s]) == set(months) for s in IDS)
    for g in GROUPS:
        gaps = [abs(data[g[2]][d] - sum(data[c[2]][d] for c in g[4])) for d in months]
        assert max(gaps) <= (0.5 if g[2] != "USGOVT" else 0.0) + 1e-9, g[0]                  # the six private parents are whole thousands over parts with one decimal; government adds up exactly
    r = run(data)
    assert r["available"] is True and r["date"] == "2026-10-01" and r["month"] == "2026-10" and r["age_days"] == 55 and r["freshness"] == "CURRENT"
    assert r["detail"] == {"months_checked": 142, "first_month": "2015-01", "last_month": "2026-10", "largest_sum_gap": 0.5}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "sums_ok": True}
    assert r["source"] == U.SOURCE and r["url"] == "https://fred.stlouisfed.org/series/USTRADE"


def test_the_figures_of_the_newest_real_months():
    r = run(real())
    got = got_of(r)
    assert set(got) == set(REAL_ITEMS) and len(items_of(r)) == 26
    for key, want in REAL_ITEMS.items():
        assert got[key] == want, key
    assert [(g["key"], g["label"], g["parent"]["key"], g["parent"]["label"]) for g in r["groups"]] == [(g[0], g[1], g[0], g[1]) for g in GROUPS]
    assert [[(c["key"], c["label"]) for c in g["children"]] for g in r["groups"]] == [[(c[0], c[1]) for c in g[4]] for g in GROUPS]
    assert all("share_pct" not in g["parent"] and all("share_pct" in c for c in g["children"]) for g in r["groups"])


def test_a_fall_or_rise_that_rounds_to_nothing_is_a_plain_zero_in_the_real_record_too():
    r = run(real())
    zero = [x for x in items_of(r) if x["change_month_pct"] == 0.0]
    assert {x["key"] for x in zero} >= {"retail", "construction", "finance", "federal", "local", "utilities"}          # real moves of a few thousand on a hundred thousand: -0.04 to 0.04 percent
    assert all(math.copysign(1.0, x["change_month_pct"]) > 0 for x in zero)


def test_the_limits_are_the_literals_about_half_the_lowest_and_twice_the_highest_value_of_the_whole_record():
    assert U.LIMITS == LIMITS and U.NAMES == NAME and list(U.SERIES) == IDS
    data = real()
    for sid, (lo, hi) in LIMITS.items():                                     # the saved record starts in 2015: it sits well inside the limits taken from the whole record
        low, high = min(data[sid].values()), max(data[sid].values())
        assert lo < low < hi and lo < high < hi, sid


def test_the_constants_the_address_the_source_and_the_groups_are_the_literals_written_here():
    assert U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and U.PAGE == "https://fred.stlouisfed.org/series/USTRADE"
    assert U.SOURCE == "U.S. Bureau of Labor Statistics, Current Employment Statistics (the Employment Situation payrolls in detail), via FRED, St. Louis Fed (official, free public data)"
    assert U.GROUPS == GROUPS and len(IDS) == 26 and len(CHILDREN) == 19 and len(set(IDS)) == 26
    assert U.START == "2015-01-01" and U.MIN_MONTHS == 132 and U.OVERDUE_AFTER_DAYS == 70 and U.TTL == 6 * 3600.0 and U.FAIL_TTL == 120.0 and U.CONCURRENCY == 6 and U.WORDS == WORDS


def test_the_sums_and_their_tolerances_are_written_out_here_and_the_six_private_ones_are_binary_numbers_above_the_rounding_bound():
    assert U.SUMS == tuple((g[2], tuple(c[2] for c in g[4]), g[3]) for g in GROUPS)
    assert [s[2] for s in U.SUMS] == [0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 2.0]
    for g in GROUPS[:-1]:
        assert 0.5 + 0.05 * len(g[4]) < g[3] <= 0.75 and g[3] * 4 == int(g[3] * 4)         # the parent's own rounding (0.5) and 0.05 for each part with one decimal; three quarters is exact in binary
    assert 0.5 * (1 + len(GROUPS[-1][4])) == GROUPS[-1][3]                                  # government and its parts are whole thousands: four figures


# ---------------------------------------------------------------- the months


@pytest.mark.parametrize("sid", IDS)
def test_a_series_that_ends_a_month_early_is_refused_first_whichever_series_it_is(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the jobs detail series end in different months")


@pytest.mark.parametrize("sid", IDS)
def test_a_series_that_runs_a_month_longer_than_the_others_is_refused_the_same_way(sid):
    d = world()
    d[sid][mback(LAST, -1)] = build(LEAVES)[sid]
    refused(d, "the jobs detail series end in different months")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_that_covers_other_months_is_named(sid):
    d = world()
    del d[sid][MIDDLE]
    refused(d, f"the {NAME[sid]} series covers different months than the first series")


def test_the_first_series_is_the_base_and_the_first_series_that_differs_in_the_series_order_is_named():
    d = world()
    del d["USTPU"][MIDDLE]
    refused(d, "the wholesale trade payrolls series covers different months than the first series")
    d = world()
    del d["USLAH"][MIDDLE]
    del d["USGOVT"][MIDDLE]
    refused(d, "the leisure and hospitality payrolls series covers different months than the first series")
    d = world()
    d["USEHS"][date(2010, 1, 1)] = 1.0                                       # an extra month the others do not have: the same kind of difference
    refused(d, "the education and health payrolls series covers different months than the first series")


@pytest.mark.parametrize("days", [1, 14])
@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
def test_a_date_that_is_not_the_first_of_a_month_is_refused_in_any_month(month, days):
    d = {sid: {(k + timedelta(days=days) if k == month else k): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a jobs detail date is not the 1st of a month")


def test_the_ends_come_first_then_the_covers_then_the_dates_then_the_skips_then_the_count():
    d = world(n=131)
    del d["USGOVT"][mback(LAST, 50)]
    del d["USLAH"][LAST]
    refused(d, "the jobs detail series end in different months")
    d = world(n=131)
    del d["USGOVT"][mback(LAST, 50)]
    refused(d, "the government payrolls series covers different months than the first series")
    d = {sid: {k + timedelta(days=1): v for k, v in s.items() if k != MIDDLE} for sid, s in world(n=131).items()}
    refused(d, "a jobs detail date is not the 1st of a month")
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world(n=131).items()}
    refused(d, f"the jobs detail months skip a month after {label(mback(MIDDLE, 1))}")


def test_a_skipped_month_is_named_by_the_month_before_it():
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    refused(d, f"the jobs detail months skip a month after {label(mback(MIDDLE, 1))}")
    d = {sid: {k: v for k, v in s.items() if k != LAST and k != mback(LAST, 1)} for sid, s in world().items()}
    assert run(d)["month"] == "2026-08" and run(d)["detail"]["months_checked"] == 138              # the newest months missing in every series is no skip: the record just ends earlier
    d = {sid: {k: v for k, v in s.items() if k != mback(LAST, 140)} for sid, s in world(n=141).items()}
    assert run(d)["detail"]["months_checked"] == 140 and run(d)["detail"]["first_month"] == "2015-03"        # nor is the oldest month


def test_fewer_than_132_months_are_refused_and_132_pass():
    refused(world(n=131), "the jobs detail series cover 131 months, fewer than the 132 expected")
    assert run(world(n=132))["detail"]["months_checked"] == 132
    assert run(world(n=133))["detail"]["months_checked"] == 133


def test_every_months_check_comes_before_the_ranges():
    d = {sid: {k + timedelta(days=1): v for k, v in s.items()} for sid, s in world().items()}
    d["USTPU"][OLDEST + timedelta(days=1)] = 99999999.0
    refused(d, "a jobs detail date is not the 1st of a month")
    d = {sid: {k: v for k, v in s.items() if k != MIDDLE} for sid, s in world().items()}
    d["USTPU"][OLDEST] = 99999999.0
    refused(d, f"the jobs detail months skip a month after {label(mback(MIDDLE, 1))}")
    d = world(n=131)
    d["USTPU"][mback(LAST, 130)] = 99999999.0
    refused(d, "the jobs detail series cover 131 months, fewer than the 132 expected")
    d = world()
    d["USTPU"][OLDEST] = 99999999.0
    del d["USWTRADE"][MIDDLE]
    refused(d, "the wholesale trade payrolls series covers different months than the first series")
    d = world()
    d["USTPU"][OLDEST] = 99999999.0
    del d["USCONS"][LAST]
    refused(d, "the jobs detail series end in different months")


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
    refused(bump(world(), LAST, {"USTPU": 900000.0}), "trade, transport and utilities payrolls of 928,700 in 2026-10 is outside 3,300 to 57,800")
    refused(bump(world(), MIDDLE, {"CES4422000001": 5000.0}), f"utilities payrolls of 5,600 in {label(MIDDLE)} is outside 235 to 1,490")
    refused(bump(world(), OLDEST, {"CES9091000001": -2700.0}), f"federal government payrolls of 0 in {label(OLDEST)} is outside 455 to 6,880")


def test_a_message_names_the_first_wrong_series_in_the_series_order_and_the_oldest_month():
    d = world()
    d["USGOVT"][LAST] = 99999999.0
    d["USCONS"][MIDDLE] = 99999999.0
    refused(d, f"construction payrolls of 99,999,999 in {label(MIDDLE)} is outside 520 to 16,800")
    d = world()
    d["CES7071000001"][LAST] = 99999999.0
    d["CES7071000001"][OLDEST] = 99999999.0
    refused(d, f"arts and recreation payrolls of 99,999,999 in {label(OLDEST)} is outside 555 to 5,410")
    d = world()
    d["CES9093000001"][OLDEST] = 99999999.0
    d["CES5553000001"][LAST] = 99999999.0
    refused(d, f"real estate and leasing payrolls of 99,999,999 in {label(LAST)} is outside 805 to 4,950")


# ---------------------------------------------------------------- the seven sums


@pytest.mark.parametrize("month", [OLDEST, MIDDLE, LAST])
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("g", range(7))
def test_each_sum_holds_at_its_tolerance_and_is_refused_just_beyond(g, sign, month):
    tol = GROUPS[g][3]
    assert run(gap(world(), month, g, tol * sign))["detail"]["largest_sum_gap"] == tol
    refused(gap(world(), month, g, (tol + 0.25) * sign), sum_msg(g, tol + 0.25, month))


@pytest.mark.parametrize("sid", IDS)
def test_each_series_takes_part_in_its_own_sum_and_in_no_other(sid):
    g = GROUP_OF[sid]
    refused(bump(world(), LAST, {sid: 5.0}), sum_msg(g, 5, LAST))
    refused(bump(world(), LAST, {sid: -5.0}), sum_msg(g, 5, LAST))
    other = bump(world(), LAST, {sid: 0.5})                                  # half a thousand is inside every tolerance: nothing speaks, and the gap is exactly that
    assert run(other)["detail"]["largest_sum_gap"] == 0.5


def test_the_sums_are_scanned_one_after_the_other_and_the_oldest_month_first():
    d = gap(gap(world(), OLDEST, 6, 5.0), LAST, 0, 3.0)
    refused(d, sum_msg(0, 3, LAST))                                          # the last sum breaks in the oldest month, the first only in the newest: the first sum is scanned first
    d = gap(gap(world(), OLDEST, 3, 4.0), LAST, 2, 2.0)
    refused(d, sum_msg(2, 2, LAST))
    d = gap(gap(world(), LAST, 0, 4.0), MIDDLE, 0, 5.0)
    refused(d, sum_msg(0, 5, MIDDLE))                                        # inside a sum the oldest month comes first
    d = gap(gap(world(), OLDEST, 6, 5.0), MIDDLE, 5, 4.0)
    refused(d, sum_msg(5, 4, MIDDLE))


def test_the_largest_sum_gap_is_kept_over_all_sums_and_all_months_to_four_decimals():
    assert run(world())["detail"]["largest_sum_gap"] == 0.0
    assert run(gap(world(), MIDDLE, 0, 0.5))["detail"]["largest_sum_gap"] == 0.5
    assert run(gap(gap(world(), MIDDLE, 0, 0.5), LAST, 4, -0.75))["detail"]["largest_sum_gap"] == 0.75
    assert run(gap(gap(world(), OLDEST, 6, 1.0), LAST, 2, 0.25))["detail"]["largest_sum_gap"] == 1.0
    assert run(gap(world(), LAST, 0, 0.00004))["detail"]["largest_sum_gap"] == 0.0
    assert run(gap(world(), LAST, 0, 0.0001))["detail"]["largest_sum_gap"] == 0.0001


# ---------------------------------------------------------------- the figures


def test_a_flat_world_has_no_change_and_no_negative_zero_and_shares_that_need_rounding():
    r = run(world())
    assert all(x["change_month"] == 0.0 and x["change_year"] == 0.0 and x["change_month_pct"] == 0.0 and x["change_year_pct"] == 0.0 for x in items_of(r))
    assert all(math.copysign(1.0, x[k]) > 0 for x in items_of(r) for k in ("change_month", "change_month_pct", "change_year", "change_year_pct"))
    assert [g["parent"]["thousands"] for g in r["groups"]] == [28700.0, 8200.0, 9000.0, 22400.0, 28000.0, 16900.0, 23400.0]
    assert {x["key"]: x["share_pct"] for g in r["groups"] for x in g["children"]} == {
        "wholesale": 20.9, "retail": 54.0, "transport": 23.0, "utilities": 2.1, "buildings": 22.0, "heavy": 14.6, "specialty": 63.4, "finance": 73.3, "realestate": 26.7, "technical": 48.2, "management": 11.6,
        "administrative": 40.2, "education": 14.3, "health": 85.7, "arts": 15.4, "food": 84.6, "federal": 11.5, "state": 23.5, "local": 65.0}


def test_a_fall_that_rounds_to_nothing_is_a_plain_zero_and_a_change_is_kept_to_a_tenth():
    def fn(k):
        return {**LEAVES, "USTRADE": LEAVES["USTRADE"] + (0.04 if k == 140 else 0.0)}
    r = run(world_by(fn))
    retail, trade = r["groups"][0]["children"][1], r["groups"][0]["parent"]
    assert retail["change_month"] == 0.0 and trade["change_month"] == 0.0
    assert all(math.copysign(1.0, x[k]) > 0 for x in (retail, trade) for k in ("change_month", "change_month_pct"))
    def fn2(k):
        return {**LEAVES, "USTRADE": LEAVES["USTRADE"] + (0.26 if k == 140 else 0.0)}
    r = run(world_by(fn2))
    assert r["groups"][0]["children"][1]["change_month"] == -0.3 and r["groups"][0]["parent"]["change_month"] == -0.3


def test_a_rising_trend_gives_exact_levels_changes_and_shares():
    r = run(world_by(trend))
    assert got_of(r) == TREND_ITEMS
    assert r["detail"] == {"months_checked": 142, "first_month": "2015-01", "last_month": "2026-10", "largest_sum_gap": 0.0}


def test_the_month_change_and_the_year_change_each_use_their_own_month():
    def fn(k):                        # n = 142: the newest is k = 141, a month earlier 140, a year earlier 129; the neighbours of each get their own value
        bumps = {140: 1000.0, 139: 2000.0, 129: 5000.0, 130: 7000.0, 128: 9000.0}
        return {**LEAVES, "USTRADE": LEAVES["USTRADE"] + bumps.get(k, 0.0)}
    r = run(world_by(fn))
    retail, trade = r["groups"][0]["children"][1], r["groups"][0]["parent"]
    assert (retail["thousands"], retail["change_month"], retail["change_year"]) == (15500.0, -1000.0, -5000.0)
    assert (retail["change_month_pct"], retail["change_year_pct"]) == (-6.1, -24.4)
    assert (trade["thousands"], trade["change_month"], trade["change_year"]) == (28700.0, -1000.0, -5000.0)
    assert (trade["change_month_pct"], trade["change_year_pct"]) == (-3.4, -14.8)
    assert retail["share_pct"] == 54.0                                       # the share is of the newest month's parent, not of an earlier one


def test_a_release_that_is_late_is_marked_overdue_after_70_days_from_the_first_of_the_month():
    assert run(world(), LAST + timedelta(days=70))["freshness"] == "CURRENT" and run(world(), LAST + timedelta(days=70))["age_days"] == 70
    assert run(world(), LAST + timedelta(days=71))["freshness"] == "OVERDUE" and run(world(), LAST + timedelta(days=71))["age_days"] == 71
    assert run(world(), LAST)["age_days"] == 0 and run(world(), LAST)["freshness"] == "CURRENT"


def test_the_note_says_what_the_figures_are_and_are_not_and_points_to_the_check_line():
    note = run(world())["note"]
    assert note.startswith("Payrolls in detail from the Bureau of Labor Statistics (the Current Employment Statistics survey of employers, the payroll half of the monthly Employment Situation), in thousands of jobs, seasonally adjusted, for the pay period that includes the 12th: seven of the larger industries and the parts each is made of. ")
    assert ". A job is a position on a payroll, not a person: someone with two jobs counts twice. Only non-farm employers are counted, so farm work and the self-employed are not in it, and government counts civilian employees only. The newest months are revised twice and again every year. " in note
    assert "Plain checks: the units are the ones assumed and no month is missing; the ranges and the seven sums are in the Check line. " in note and note.count("the Check line") == 1
    assert note.endswith("This describes employment that already happened: it is not a market signal or a forecast.") and len(note) <= 1100


# ---------------------------------------------------------------- the messages


def test_every_failure_message_fits_in_the_110_characters_a_card_shows():
    worst = [f"{NAME[g[2]]} are 123,456.7 thousand off its {WORDS[len(g[4])]} parts in 2015-01, over {g[3]:g}" for g in GROUPS]
    worst += [f"{NAME[sid]} of 99,999,999 in 2015-01 is outside {num(LIMITS[sid][0])} to {num(LIMITS[sid][1])}" for sid in IDS]
    worst += [f"the {NAME[sid]} series covers different months than the first series" for sid in IDS[1:]]
    worst += ["the jobs detail series end in different months", "a jobs detail date is not the 1st of a month", "the jobs detail months skip a month after 2015-01", "the jobs detail series cover 131 months, fewer than the 132 expected"]
    assert max(len(m) for m in worst) <= 110, [(len(m), m) for m in worst if len(m) > 110]
    assert len(sum_msg(3, 3, LAST)) < 110


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

    arun(U.UsJobsDetail(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(urls) == 26 and all(u == ("https", "fred.stlouisfed.org", "/graph/fredgraph.csv", ["cosd", "id"]) for u in urls)


def test_demo_mode_shows_nothing_and_says_why_without_a_request():
    seen = []
    c = U.UsJobsDetail(client=make_client(world(), seen), demo=True)
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is True and r["reason"] == "Demo mode: the real US jobs detail figures are not shown because made-up values would look real." and seen == []
    assert "groups" not in r and r["as_of"] == NOW.isoformat()


def test_one_request_per_series_each_with_its_id_and_the_start_date_and_six_at_a_time():
    seen, stats = [], {"now": 0, "peak": 0}
    c = U.UsJobsDetail(client=make_client(world(), seen, delay=0.01, stats=stats))
    r = arun(c.overview(NOW))
    assert r["available"] is True and r["demo"] is False and r["date"] == "2026-10-01" and r["age_days"] == 55
    assert sorted(x["id"] for x in seen) == sorted(IDS) and all(x == {"id": x["id"], "cosd": "2015-01-01"} for x in seen)
    assert stats["peak"] == 6


def test_the_real_record_through_the_class_gives_the_same_answer_as_the_summary():
    r = arun(U.UsJobsDetail(client=make_client(real())).overview(NOW))
    assert r["available"] is True and r["groups"][0]["parent"]["thousands"] == 28818.0 and r["detail"]["months_checked"] == 142 and r["as_of"] == NOW.isoformat()
    assert got_of(r) == REAL_ITEMS


def test_a_good_answer_is_kept_for_six_hours_and_asked_again_after_that(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(U, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    seen = []
    c = U.UsJobsDetail(client=make_client(world(), seen))
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
    c = U.UsJobsDetail(client=make_client(world(), seen, status=500))
    r = arun(c.overview(NOW))
    assert r["available"] is False and r["demo"] is False and r["reason"].startswith("US jobs detail could not be read right now (") and "groups" not in r
    n = len(seen)
    clock[0] += 119.0
    arun(c.overview(NOW))
    assert len(seen) == n
    clock[0] += 1.0
    arun(c.overview(NOW))
    assert len(seen) > n


def test_a_figure_that_fails_a_check_is_named_in_words_with_its_month_in_words():
    d = world()
    d["USTPU"][LAST] = 9000000.0
    r = arun(U.UsJobsDetail(client=make_client(d)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US jobs detail could not be read right now (the data failed a check: trade, transport and utilities payrolls of 9,000,000 in October 2026 is outside 3,300 to 57,800)" and "groups" not in r
    d = world()
    d["USCONS"][LAST] += 3.0
    r = arun(U.UsJobsDetail(client=make_client(d)).overview(NOW))
    assert r["reason"] == "US jobs detail could not be read right now (the data failed a check: construction payrolls are 3 thousand off its three parts in October 2026, over 0.75)"


def test_a_client_it_makes_itself_is_closed_and_one_it_is_given_is_not(monkeypatch):
    made, instances = [], []

    class Own(REAL_CLIENT):
        def __init__(self, **kw):
            made.append(kw)
            instances.append(self)
            super().__init__(transport=transport_for(world()))

    monkeypatch.setattr(U.httpx, "AsyncClient", Own)
    c = U.UsJobsDetail()
    assert arun(c.overview(NOW))["available"] is True and made == [{"timeout": 25}] and instances[0].is_closed is True
    given = make_client(world())
    arun(U.UsJobsDetail(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_default_clock_is_utc_and_stamps_the_answer():
    r = arun(U.UsJobsDetail(client=make_client(world())).overview())
    stamp = datetime.fromisoformat(r["as_of"])
    assert stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0) and abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


def test_each_request_goes_with_the_clients_own_user_agent_and_nothing_added():
    seen, data = [], world()

    async def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text=csv_text(request.url.params["id"], data[request.url.params["id"]]))

    arun(U.UsJobsDetail(client=REAL_CLIENT(transport=httpx.MockTransport(handler))).overview(NOW))
    assert len(seen) == 26 and all(ua.startswith("python-httpx/") for ua in seen)


def test_a_dropped_connection_a_timeout_and_a_missing_key_read_plainly(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("")

    def slow(request):
        raise httpx.ReadTimeout("")

    for fail, words in ((boom, "the connection could not be made"), (slow, "the request timed out")):
        r = arun(U.UsJobsDetail(client=REAL_CLIENT(transport=httpx.MockTransport(fail))).overview(NOW))
        assert r["available"] is False and r["reason"] == f"US jobs detail could not be read right now ({words})"

    def no_key(data, today):
        raise KeyError("USTPU")

    monkeypatch.setattr(U, "summarize", no_key)
    r = arun(U.UsJobsDetail(client=make_client(world())).overview(NOW))
    assert r["available"] is False and r["reason"] == "US jobs detail could not be read right now (the answer was not in the expected shape)"


def test_any_answer_but_200_is_refused_with_its_status_in_words():
    r = arun(U.UsJobsDetail(client=make_client(world(), status=500)).overview(NOW))
    assert r["reason"] == "US jobs detail could not be read right now (the server had an error, HTTP 500)"
    r = arun(U.UsJobsDetail(client=make_client(world(), status=204)).overview(NOW))
    assert r["reason"] == "US jobs detail could not be read right now (the server answered HTTP 204)"


def test_the_clock_decides_the_age_not_the_computer_date():
    c = U.UsJobsDetail(client=make_client(world()))
    r = arun(c.overview(datetime(2026, 12, 11, 1, tzinfo=timezone.utc)))
    assert r["age_days"] == 71 and r["freshness"] == "OVERDUE"
