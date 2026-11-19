"""US GDP by component (the Bureau of Economic Analysis' National Income and Product Accounts via FRED: seven nominal levels, real growth and four contributions, twelve series): parsed from real responses (fetched 2026-11-18 23:2x UTC: 51 quarterly points from 2014-Q1 to 2026-Q3 of each series; the whole record is 319 quarters from 1947-Q1, 318 of growth and contributions). The limits are literals, set from the whole real record before any test was written (consumer spending is the QUARTERLY series PCEC: FRED's PCE is monthly, and DPCERC1Q027SBEA answers HTTP 404). Whole record: GDP minus the four parts is 0.000 in 181 quarters, 0.001 in 137 and 0.002 in one (1984-Q3); net exports minus (exports minus imports) is 0.000 in 253 and 0.001 in 66; growth minus the four contributions is 0.00 to 0.07. Each check below is tested at both edges, in the first and the last quarter, and with the other checks satisfied exactly (a made-up world of constant values that adds up to the last digit)."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import usgdp as U
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usgdp.json").read_text())
TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
LAST = date(2026, 7, 1)

LEVELS = ("GDP", "PCEC", "GPDI", "GCE", "NETEXP", "EXPGS", "IMPGS")
GROWTH = "A191RL1Q225SBEA"
CONTRIB = ("DPCERY2Q224SBEA", "A006RY2Q224SBEA", "A822RY2Q224SBEA", "A019RY2Q224SBEA")
IDS = (*LEVELS, GROWTH, *CONTRIB)
NAME = {"GDP": "gross domestic product", "PCEC": "consumer spending", "GPDI": "private investment", "GCE": "government spending", "NETEXP": "net exports", "EXPGS": "exports", "IMPGS": "imports", GROWTH: "real GDP growth",
        "DPCERY2Q224SBEA": "consumer spending contribution", "A006RY2Q224SBEA": "private investment contribution", "A822RY2Q224SBEA": "government spending contribution", "A019RY2Q224SBEA": "net exports contribution"}
BASE = {"GDP": 30000.0, "PCEC": 20000.0, "GPDI": 6000.0, "GCE": 5000.0, "NETEXP": -1000.0, "EXPGS": 3000.0, "IMPGS": 4000.0, GROWTH: 3.0,
        "DPCERY2Q224SBEA": 2.0, "A006RY2Q224SBEA": 0.5, "A822RY2Q224SBEA": 0.25, "A019RY2Q224SBEA": 0.25}      # 20,000 + 6,000 + 5,000 - 1,000 = 30,000; 3,000 - 4,000 = -1,000; 2 + 0.5 + 0.25 + 0.25 = 3 (all exact in binary)


def back(d, n):
    i = d.year * 4 + (d.month - 1) // 3 - n
    return date(i // 4, (i % 4) * 3 + 1, 1)


def lab(d):
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def real():
    return {sid: U.parse(F[sid], sid) for sid in IDS}


def world(n=45):
    """`n` quarters ending 2026-Q3 with every check satisfied exactly."""
    quarters = [back(LAST, i) for i in range(n - 1, -1, -1)]
    return {s: {d: BASE[s] for d in quarters} for s in IDS}


def run(data, today=TODAY):
    return U.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        U.summarize(data, TODAY)


MID = back(LAST, 20)                                                                # 2021-Q3: a quarter in the middle of every world


def put(data, d, **kw):
    """Set levels in quarter `d`; net exports (exports minus imports) and GDP (the four parts) follow unless given, so every identity still holds exactly."""
    for s, v in kw.items():
        data[s][d] = v
    if "NETEXP" not in kw:
        data["NETEXP"][d] = data["EXPGS"][d] - data["IMPGS"][d]
    if "GDP" not in kw:
        data["GDP"][d] = data["PCEC"][d] + data["GPDI"][d] + data["GCE"][d] + data["NETEXP"][d]
    return data


def growth_at(data, d, g):
    """Real growth `g` in quarter `d`, shared equally by the four contributions (their sum is `g`)."""
    data[GROWTH][d] = g
    for s in CONTRIB:
        data[s][d] = g / 4
    return data


def contrib(data, d, sid, v):
    """One contribution set to `v`; the other three share what is left of the published growth, so the sum stays equal to it."""
    rest = (data[GROWTH][d] - v) / 3
    for s in CONTRIB:
        data[s][d] = v if s == sid else rest
    return data


def test_the_series_and_the_limits_are_the_ones_set_from_the_whole_record():
    assert U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and U.PAGE == "https://fred.stlouisfed.org/series/GDP"
    assert U.SOURCE.startswith("U.S. Bureau of Economic Analysis, National Income and Product Accounts") and U.SOURCE.endswith("via FRED, St. Louis Fed (official, free public data)")
    assert list(U.LEVELS) == list(LEVELS) and U.GROWTH == GROWTH and tuple(U.CONTRIBUTIONS) == CONTRIB and U.SERIES == list(IDS)
    assert U.PARTS == (("consumption", "Consumer spending", "PCEC", "DPCERY2Q224SBEA"), ("investment", "Private investment", "GPDI", "A006RY2Q224SBEA"),
                       ("government", "Government spending", "GCE", "A822RY2Q224SBEA"), ("net_exports", "Net exports", "NETEXP", "A019RY2Q224SBEA"))
    assert U.LEVEL_LIMITS == {"GDP": (5_000.0, 60_000.0), "PCEC": (3_000.0, 40_000.0), "GPDI": (1_000.0, 12_000.0), "GCE": (1_000.0, 12_000.0),
                              "NETEXP": (-3_000.0, 500.0), "EXPGS": (500.0, 8_000.0), "IMPGS": (700.0, 9_000.0)}
    assert U.GROWTH_LIMITS == (-40.0, 50.0) and U.CONTRIBUTION_LIMIT == 40.0
    assert U.NOMINAL_TOLERANCE == 2 ** -8 == 0.00390625 and U.NETEXP_TOLERANCE == 2 ** -9 == 0.001953125 and U.CONTRIBUTION_TOLERANCE == 9 / 128 == 0.0703125
    assert (U.MIN_QUARTERS, U.HISTORY_QUARTERS, U.RECENT_QUARTERS, U.OVERDUE_AFTER_DAYS, U.TTL, U.FAIL_TTL, U.LOOKBACK_DAYS) == (40, 40, 6, 240, 21600.0, 120.0, 4200)
    for sid, name in NAME.items():
        assert U._name(sid) == name


def test_quarters_are_labelled_and_counted_back_across_the_year():
    assert U._qlabel(date(2026, 1, 1)) == "2026-Q1" and U._qlabel(date(2026, 4, 1)) == "2026-Q2" and U._qlabel(date(2026, 7, 1)) == "2026-Q3" and U._qlabel(date(2026, 10, 1)) == "2026-Q4"
    assert U._quarters_back(date(2026, 7, 1), 0) == date(2026, 7, 1) and U._quarters_back(date(2026, 7, 1), 1) == date(2026, 4, 1)
    assert U._quarters_back(date(2026, 1, 1), 1) == date(2025, 10, 1) and U._quarters_back(date(2026, 4, 1), 2) == date(2025, 10, 1) and U._quarters_back(date(2026, 7, 1), 4) == date(2025, 7, 1)
    assert U._quarters_back(date(2026, 10, 1), 8) == date(2024, 10, 1) and U._quarters_back(date(2026, 1, 1), 5) == date(2024, 10, 1)


def test_every_month_belongs_to_its_own_quarter_in_the_label_and_in_the_count_back():
    for m in range(1, 13):                                                           # the module only meets the first month of a quarter, but the functions say what they mean for every month
        q = (m - 1) // 3 + 1
        assert U._qlabel(date(2026, m, 1)) == f"2026-Q{q}"
        assert U._quarters_back(date(2026, m, 1), 0) == date(2026, 3 * q - 2, 1)
        assert U._quarters_back(date(2026, m, 1), 1) == (date(2026, 3 * q - 5, 1) if q > 1 else date(2025, 10, 1))


def test_the_saved_files_are_the_real_record_fetched_for_this_card():
    assert set(F) == set(IDS)
    for sid in IDS:
        lines = F[sid].strip().splitlines()
        assert lines[0] == f"observation_date,{sid}" and len(lines) == 52 and lines[1].startswith("2014-01-01,") and lines[-1].startswith("2026-07-01,")
    assert F["GDP"].splitlines()[-1] == "2026-07-01,33010.036" and F[GROWTH].splitlines()[-1] == "2026-07-01,3.4" and F["NETEXP"].splitlines()[-1] == "2026-07-01,-1217.090"


def test_missing_values_are_skipped_never_filled():
    text = "observation_date,GDP\n2026-01-01,31906.274\n2026-04-01,.\n2026-07-01,33010.036\n"
    assert U.parse(text, "GDP") == {date(2026, 1, 1): 31906.274, date(2026, 7, 1): 33010.036}


def test_the_whole_real_record_passes_every_check_and_the_largest_gaps_are_the_ones_found_beforehand():
    s = run(real())
    assert s["detail"] == {"quarters_checked": 51, "first_quarter": "2014-Q1", "last_quarter": "2026-Q3", "largest_gdp_gap": 0.001, "largest_net_exports_gap": 0.001, "largest_contribution_gap": 0.06}
    assert s["checks"] == {"quarters_in_a_row": True, "range_ok": True, "parts_add_up_ok": True, "net_exports_ok": True, "contributions_add_up_ok": True}


def test_the_download_the_card_makes_gives_the_same_card():
    r = asyncio.run(U.UsGdp(client=_client(_handler)).overview(NOW))
    assert {k: v for k, v in r.items() if k not in ("as_of", "demo")} == run(real(), NOW.date()) and r["demo"] is False


def test_the_newest_quarter_by_hand():
    s = run(real())
    assert s["available"] is True and s["quarter"] == "2026-Q3" and s["date"] == "2026-07-01" and s["age_days"] == 140 and s["freshness"] == "CURRENT"
    assert s["source"] == U.SOURCE and s["url"] == "https://fred.stlouisfed.org/series/GDP"
    assert s["gdp"] == {"level_billions": 33010.036, "change_billions": 447.006, "change_pct": 1.37, "change_year_pct": 5.87}          # 33,010.036 - 32,563.030; against 2025-Q3 31,180.493
    g = s["growth"]
    assert g["pct"] == 3.4 and g["quarter_before_pct"] == 2.2 and g["year_ago_pct"] == 3.9 and g["contributions_sum_points"] == 3.37     # 2.52 + 3.27 + 0.90 - 3.32
    assert g["range"] == {"quarters": 40, "first": "2016-Q4", "lowest": {"value": -28.0, "quarter": "2020-Q2"}, "highest": {"value": 34.9, "quarter": "2020-Q3"}, "share_lower_pct": 62}
    assert [(c["key"], c["label"], c["level_billions"], c["share_pct"], c["contribution_points"]) for c in s["components"]] == [
        ("consumption", "Consumer spending", 22312.825, 67.6, 2.52), ("investment", "Private investment", 6141.723, 18.6, 3.27),
        ("government", "Government spending", 5772.578, 17.5, 0.9), ("net_exports", "Net exports", -1217.09, -3.7, -3.32)]
    assert s["trade"] == {"exports_billions": 3752.076, "imports_billions": 4969.165}
    assert s["recent"] == [{"quarter": "2025-Q2", "growth_pct": 4.0}, {"quarter": "2025-Q3", "growth_pct": 3.9}, {"quarter": "2025-Q4", "growth_pct": 0.2},
                           {"quarter": "2026-Q1", "growth_pct": 2.5}, {"quarter": "2026-Q2", "growth_pct": 2.2}, {"quarter": "2026-Q3", "growth_pct": 3.4}]


def test_a_clean_exact_world_passes_with_no_gap_at_all():
    s = run(world())
    assert s["detail"] == {"quarters_checked": 45, "first_quarter": "2015-Q3", "last_quarter": "2026-Q3", "largest_gdp_gap": 0.0, "largest_net_exports_gap": 0.0, "largest_contribution_gap": 0.0}


# ---------------------------------------------------------------- same quarters, dates, a row, enough of them

@pytest.mark.parametrize("sid", IDS)
def test_series_that_end_in_different_quarters_are_refused(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the GDP series end in different quarters")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_a_quarter_missing_in_the_middle_is_refused_and_named(sid):
    d = world()
    del d[sid][MID]
    refused(d, f"the {NAME[sid]} series covers different quarters than gross domestic product")


def test_gdp_with_the_hole_makes_the_first_other_series_the_one_named():
    d = world()
    del d["GDP"][MID]
    refused(d, "the consumer spending series covers different quarters than gross domestic product")


@pytest.mark.parametrize("bad", [date(2021, m, 1) for m in (2, 3, 5, 6, 8, 9, 11, 12)] + [date(2021, 7, 2), date(2021, 7, 31)])      # every month that does not start a quarter, and two days that are not the 1st
def test_a_date_that_is_not_the_first_of_a_quarter_is_refused(bad):
    d = world()
    for s in IDS:
        d[s][bad] = d[s].pop(MID)
    refused(d, "a GDP date is not the 1st of a quarter")


def test_the_first_of_each_of_the_four_quarter_months_is_accepted():
    assert {x.month for x in world()["GDP"]} == {1, 4, 7, 10} and all(x.day == 1 for x in world()["GDP"]) and run(world())["available"] is True


def test_quarters_that_skip_a_quarter_are_refused():
    d = world()
    for s in IDS:
        del d[s][MID]
    refused(d, f"the GDP quarters skip a quarter after {lab(back(MID, 1))}")


def test_a_skip_across_the_turn_of_the_year_is_found_too():
    d = world()
    gone = date(2021, 1, 1)
    for s in IDS:
        del d[s][gone]
    refused(d, "the GDP quarters skip a quarter after 2020-Q4")


def test_fewer_than_40_quarters_are_refused_and_40_pass():
    refused(world(39), "GDP covers 39 quarters, fewer than the 40 expected")
    assert run(world(40))["detail"]["quarters_checked"] == 40


# ---------------------------------------------------------------- the ranges, each at both edges

LIMIT_CASES = [
    ("GDP", dict(PCEC=3000.0, GPDI=1000.0, GCE=1000.0, EXPGS=3000.0, IMPGS=3000.0), dict(PCEC=3000.0, GPDI=1000.0, GCE=999.9, EXPGS=3000.0, IMPGS=3000.0), "the gross domestic product of 4,999.9 billion in {q} is outside 5,000 to 60,000"),
    ("GDP", dict(PCEC=40000.0, GPDI=12000.0, GCE=8000.0, EXPGS=3000.0, IMPGS=3000.0), dict(PCEC=40000.0, GPDI=12000.0, GCE=8000.1, EXPGS=3000.0, IMPGS=3000.0), "the gross domestic product of 60,000.1 billion in {q} is outside 5,000 to 60,000"),
    ("PCEC", dict(PCEC=3000.0), dict(PCEC=2999.9), "the consumer spending of 2,999.9 billion in {q} is outside 3,000 to 40,000"),
    ("PCEC", dict(PCEC=40000.0), dict(PCEC=40000.1), "the consumer spending of 40,000.1 billion in {q} is outside 3,000 to 40,000"),
    ("GPDI", dict(GPDI=1000.0), dict(GPDI=999.9), "the private investment of 999.9 billion in {q} is outside 1,000 to 12,000"),
    ("GPDI", dict(GPDI=12000.0), dict(GPDI=12000.1), "the private investment of 12,000.1 billion in {q} is outside 1,000 to 12,000"),
    ("GCE", dict(GCE=1000.0), dict(GCE=999.9), "the government spending of 999.9 billion in {q} is outside 1,000 to 12,000"),
    ("GCE", dict(GCE=12000.0), dict(GCE=12000.1), "the government spending of 12,000.1 billion in {q} is outside 1,000 to 12,000"),
    ("NETEXP", dict(EXPGS=3000.0, IMPGS=6000.0), dict(EXPGS=3000.0, IMPGS=6000.1), "the net exports of -3,000.1 billion in {q} is outside -3,000 to 500"),
    ("NETEXP", dict(EXPGS=3000.0, IMPGS=2500.0), dict(EXPGS=3000.0, IMPGS=2499.9), "the net exports of 500.1 billion in {q} is outside -3,000 to 500"),
    ("EXPGS", dict(EXPGS=500.0, IMPGS=1500.0), dict(EXPGS=499.9, IMPGS=1499.9), "the exports of 499.9 billion in {q} is outside 500 to 8,000"),
    ("EXPGS", dict(EXPGS=8000.0, IMPGS=9000.0), dict(EXPGS=8000.1, IMPGS=9000.1), "the exports of 8,000.1 billion in {q} is outside 500 to 8,000"),
    ("IMPGS", dict(EXPGS=500.0, IMPGS=700.0), dict(EXPGS=500.0, IMPGS=699.9), "the imports of 699.9 billion in {q} is outside 700 to 9,000"),
    ("IMPGS", dict(EXPGS=8000.0, IMPGS=9000.0), dict(EXPGS=8000.0, IMPGS=9000.1), "the imports of 9,000.1 billion in {q} is outside 700 to 9,000"),
]


@pytest.mark.parametrize("sid,ok,bad,text", LIMIT_CASES)
def test_each_level_limit_is_pinned_at_both_edges_with_the_sums_still_exact(sid, ok, bad, text):
    assert run(put(world(), MID, **ok))["available"] is True                         # on the edge itself: passes
    refused(put(world(), MID, **bad), text.format(q=lab(MID)))                       # a tenth beyond: refused, and by this series


def test_a_range_is_checked_in_every_quarter_not_only_the_newest():
    d = put(world(), back(LAST, 44), PCEC=2999.9)
    refused(d, "the consumer spending of 2,999.9 billion in 2015-Q3 is outside 3,000 to 40,000")
    d = put(world(), LAST, PCEC=2999.9)
    refused(d, "the consumer spending of 2,999.9 billion in 2026-Q3 is outside 3,000 to 40,000")


@pytest.mark.parametrize("g,text", [(-40.0, None), (50.0, None), (-40.1, "-40.1"), (50.1, "50.1")])
def test_real_growth_limits_at_both_edges(g, text):
    d = growth_at(world(), MID, g)
    if text is None:
        assert run(d)["available"] is True
    else:
        refused(d, f"real GDP growth of {text}% in {lab(MID)} is outside -40 to 50")


@pytest.mark.parametrize("sid", CONTRIB)
@pytest.mark.parametrize("v,text", [(40.0, None), (-40.0, None), (40.1, "40.1"), (-40.1, "-40.1")])
def test_each_contribution_limit_at_both_edges_with_the_sum_still_equal_to_growth(sid, v, text):
    d = contrib(world(), MID, sid, v)
    if text is None:
        assert run(d)["available"] is True
    else:
        refused(d, f"the {NAME[sid]} of {text} points in {lab(MID)} is outside -40 to 40")


# ---------------------------------------------------------------- the three identities

def test_the_four_parts_must_add_up_to_gdp_within_2_to_the_minus_8():
    tol = 2 ** -8
    for sign in (1, -1):
        d = world()
        d["GDP"][MID] += sign * tol                                                  # exactly on the tolerance: passes
        assert run(d)["detail"]["largest_gdp_gap"] == 0.0039
    d = world()
    d["GDP"][MID] += tol + 2 ** -10
    refused(d, f"the four parts differ from GDP by 0.005 billion in {lab(MID)}, over 0.00390625")
    d = world()
    d["GDP"][MID] -= tol + 2 ** -10
    refused(d, f"the four parts differ from GDP by 0.005 billion in {lab(MID)}, over 0.00390625")


@pytest.mark.parametrize("q", [back(LAST, 44), LAST])
def test_the_gdp_identity_is_checked_in_the_oldest_and_the_newest_quarter(q):
    d = world()
    d["GPDI"][q] += 1.0
    refused(d, f"the four parts differ from GDP by 1.000 billion in {lab(q)}, over 0.00390625")


def test_each_part_is_in_the_gdp_identity():
    for s in ("PCEC", "GPDI", "GCE"):
        d = world()
        d[s][MID] += 0.5
        refused(d, f"the four parts differ from GDP by 0.500 billion in {lab(MID)}, over 0.00390625")
    d = world()
    d["NETEXP"][MID] += 0.5                                                          # net exports off by 0.5 breaks the GDP sum first
    refused(d, f"the four parts differ from GDP by 0.500 billion in {lab(MID)}, over 0.00390625")


def test_net_exports_must_equal_exports_minus_imports_within_2_to_the_minus_9():
    tol = 2 ** -9
    for sign in (1, -1):
        d = world()
        d["NETEXP"][MID] += sign * tol
        d["GDP"][MID] += sign * tol                                                  # GDP follows, so the parts still add up
        assert run(d)["detail"]["largest_net_exports_gap"] == 0.002
    for sign in (1, -1):
        d = world()
        d["NETEXP"][MID] += sign * (tol + 2 ** -11)
        d["GDP"][MID] += sign * (tol + 2 ** -11)
        refused(d, f"exports minus imports differ from net exports by 0.002 billion in {lab(MID)}, over 0.00195312")


@pytest.mark.parametrize("q", [back(LAST, 44), LAST])
def test_the_net_exports_identity_is_checked_in_the_oldest_and_the_newest_quarter(q):
    d = world()
    d["EXPGS"][q] += 1.0
    refused(d, f"exports minus imports differ from net exports by 1.000 billion in {lab(q)}, over 0.00195312")


def test_imports_are_in_the_net_exports_identity_too():
    d = world()
    d["IMPGS"][MID] += 1.0
    refused(d, f"exports minus imports differ from net exports by 1.000 billion in {lab(MID)}, over 0.00195312")


def test_growth_must_equal_the_sum_of_the_four_contributions_within_9_over_128():
    tol = 9 / 128
    for sign in (1, -1):
        d = world()
        d[GROWTH][MID] += sign * tol
        assert run(d)["detail"]["largest_contribution_gap"] == 0.0703
    for sign in (1, -1):
        d = world()
        d[GROWTH][MID] += sign * (tol + 2 ** -9)
        refused(d, f"the four contributions differ from real growth by 0.072 points in {lab(MID)}, over 0.0703125")


@pytest.mark.parametrize("q", [back(LAST, 44), LAST])
def test_the_contribution_identity_is_checked_in_the_oldest_and_the_newest_quarter(q):
    d = world()
    d[GROWTH][q] += 1.0
    refused(d, f"the four contributions differ from real growth by 1.000 points in {lab(q)}, over 0.0703125")


@pytest.mark.parametrize("sid", CONTRIB)
def test_each_contribution_is_in_the_sum(sid):
    d = world()
    d[sid][MID] += 1.0
    refused(d, f"the four contributions differ from real growth by 1.000 points in {lab(MID)}, over 0.0703125")


def test_the_checks_run_in_a_fixed_order():
    d = world()                                                                      # a quarter that breaks all three identities: the GDP sum is reported
    d["GDP"][MID] += 1.0
    d["NETEXP"][MID] += 0.5
    d[GROWTH][MID] += 1.0
    refused(d, f"the four parts differ from GDP by 0.500 billion in {lab(MID)}, over 0.00390625")            # GDP +1.0 against net exports +0.5
    d = world()                                                                      # net exports and growth: net exports first
    d["EXPGS"][MID] += 1.0
    d[GROWTH][MID] += 1.0
    refused(d, f"exports minus imports differ from net exports by 1.000 billion in {lab(MID)}, over 0.00195312")
    d = world()                                                                      # a range beats every identity
    put(d, MID, PCEC=2999.9)
    d["GDP"][MID] += 1.0
    d[GROWTH][MID] += 1.0
    refused(d, f"the consumer spending of 2,999.9 billion in {lab(MID)} is outside 3,000 to 40,000")
    d = world()                                                                      # a level range beats a growth range
    put(d, MID, PCEC=2999.9)
    growth_at(d, MID, 50.1)
    refused(d, f"the consumer spending of 2,999.9 billion in {lab(MID)} is outside 3,000 to 40,000")
    d = world()                                                                      # growth range beats a contribution range
    growth_at(d, MID, 50.1)
    contrib(d, MID, "A006RY2Q224SBEA", 40.1)
    refused(d, f"real GDP growth of 50.1% in {lab(MID)} is outside -40 to 50")


# ---------------------------------------------------------------- what the card shows

def test_overdue_after_240_days_from_the_first_of_the_quarter():
    assert run(world(), LAST + timedelta(days=240))["freshness"] == "CURRENT"
    s = run(world(), LAST + timedelta(days=241))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 241


def test_the_quarter_changes_and_the_year_comparison_use_the_right_quarters():
    d = world()
    put(d, LAST, PCEC=19900.0)                                                       # GDP 29,900: down 100 on the quarter before
    put(d, back(LAST, 1), PCEC=20000.0)
    put(d, back(LAST, 3), PCEC=22000.0)                                              # decoys either side of the quarter a year earlier
    put(d, back(LAST, 4), PCEC=21000.0)                                              # GDP 31,000 a year earlier
    put(d, back(LAST, 5), PCEC=23000.0)
    s = run(d)["gdp"]
    assert s == {"level_billions": 29900.0, "change_billions": -100.0, "change_pct": -0.33, "change_year_pct": -3.55}      # 100 / 30,000 and 1,100 / 31,000


def test_growth_before_and_a_year_ago_use_the_right_quarters():
    d = world()
    growth_at(d, LAST, 1.0)
    growth_at(d, back(LAST, 1), 2.0)
    growth_at(d, back(LAST, 3), 7.0)
    growth_at(d, back(LAST, 4), 4.0)
    growth_at(d, back(LAST, 5), 8.0)
    g = run(d)["growth"]
    assert g["pct"] == 1.0 and g["quarter_before_pct"] == 2.0 and g["year_ago_pct"] == 4.0 and g["contributions_sum_points"] == 1.0


def test_the_six_recent_quarters_are_oldest_first():
    d = world()
    for i in range(8):
        growth_at(d, back(LAST, i), float(i))
    assert run(d)["recent"] == [{"quarter": lab(back(LAST, 5 - i)), "growth_pct": float(5 - i)} for i in range(6)]


def test_the_growth_range_covers_the_newest_40_quarters_only():
    d = world()
    growth_at(d, back(LAST, 40), -10.0)                                              # the 41st quarter back: outside the window
    r = run(d)["growth"]["range"]
    assert r == {"quarters": 40, "first": lab(back(LAST, 39)), "lowest": {"value": 3.0, "quarter": lab(back(LAST, 39))}, "highest": {"value": 3.0, "quarter": lab(back(LAST, 39))}, "share_lower_pct": 0}
    growth_at(d, back(LAST, 39), -10.0)                                              # the 40th: inside it
    growth_at(d, back(LAST, 38), -5.0)
    growth_at(d, back(LAST, 10), 9.0)
    r = run(d)["growth"]["range"]
    assert r == {"quarters": 40, "first": lab(back(LAST, 39)), "lowest": {"value": -10.0, "quarter": lab(back(LAST, 39))}, "highest": {"value": 9.0, "quarter": lab(back(LAST, 10))}, "share_lower_pct": 5}


def test_the_range_values_are_rounded_to_two_decimals_and_nothing_else_is():
    d = world()
    growth_at(d, back(LAST, 10), -1.236)
    growth_at(d, back(LAST, 5), 9.876)
    r = run(d)["growth"]["range"]
    assert r["lowest"] == {"value": -1.24, "quarter": lab(back(LAST, 10))} and r["highest"] == {"value": 9.88, "quarter": lab(back(LAST, 5))}


def test_ties_in_the_range_name_the_earliest_quarter_and_the_share_counts_strictly_lower_ones():
    d = world()
    growth_at(d, back(LAST, 20), 1.0)
    growth_at(d, back(LAST, 10), 1.0)
    growth_at(d, back(LAST, 15), 5.0)
    growth_at(d, back(LAST, 5), 5.0)
    growth_at(d, LAST, 3.0)
    r = run(d)["growth"]["range"]
    assert r["lowest"] == {"value": 1.0, "quarter": lab(back(LAST, 20))} and r["highest"] == {"value": 5.0, "quarter": lab(back(LAST, 15))} and r["share_lower_pct"] == 5      # 2 of 40 are below 3.0, the other 37 equal it or are above


def test_shares_and_signs_follow_the_levels():
    d = world()
    c = run(d)["components"]
    assert [(x["key"], x["level_billions"], x["share_pct"]) for x in c] == [("consumption", 20000.0, 66.7), ("investment", 6000.0, 20.0), ("government", 5000.0, 16.7), ("net_exports", -1000.0, -3.3)]
    assert [x["contribution_points"] for x in c] == [2.0, 0.5, 0.25, 0.25] and run(d)["trade"] == {"exports_billions": 3000.0, "imports_billions": 4000.0}


def test_the_note_says_what_the_numbers_are_and_what_they_are_not():
    note = run(world())["note"]
    for phrase in ("National Income and Product Accounts of the US Bureau of Economic Analysis", "counted by what it was spent on", "consumer spending, private investment, government spending and investment",
                   "net exports (exports minus imports, below zero when the country buys more from abroad than it sells)", "billions of dollars at a seasonally adjusted annual rate and in the prices of the time",
                   "Real growth is the change in GDP with prices held fixed, from the quarter before, at an annual rate", "each part's contribution to it is in percentage points",
                   "The newest quarter is revised in later releases; each figure carries its quarter", "Plain checks:", "the Check line"):
        assert phrase in note, phrase
    assert note.endswith("This describes the economy that already happened: it is not a market signal or a forecast.") and len(note) <= 1100


def test_the_module_says_why_each_series_is_asked_for_alone_and_what_it_does_not_check():
    assert "combined request" in U.__doc__ and "FIRST series only" in U.__doc__ and "NOT checked" in U.__doc__ and "QUARTERLY series" in U.__doc__


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

    svc = U.UsGdp(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["gdp"]["change_billions"] == 447.006 and n["n"] == 12 and r["source"].startswith("U.S. Bureau of Economic Analysis") and r["url"] == "https://fred.stlouisfed.org/series/GDP"
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 12


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(U.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = U.UsGdp(client=_client(handler))
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
    svc = U.UsGdp(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(U.UsGdp(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US GDP figures could not be read right now (the server had an error, HTTP 503)" and "gdp" not in r and "components" not in r
    r = asyncio.run(U.UsGdp(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]                      # anything but 200 is a failure


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == "A019RY2Q224SBEA" else _handler(req)

    r = asyncio.run(U.UsGdp(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "gdp" not in r and "growth" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    bad = dict(F)
    bad["GDP"] = F["GDP"].replace("2026-07-01,33010.036", "2026-07-01,330100.36")      # a decimal slip in the newest value
    r = asyncio.run(U.UsGdp(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US GDP figures could not be read right now (the data failed a check: the gross domestic product of 330,100.4 billion in 2026-Q3 is outside 5,000 to 60,000)" and "gdp" not in r
    bad = dict(F)
    bad[GROWTH] = F[GROWTH].replace("2026-07-01,3.4", "2026-07-01,x")
    r = asyncio.run(U.UsGdp(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "a A191RL1Q225SBEA row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(U.UsGdp(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US GDP figures could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("GDP")

    monkeypatch.setattr(U, "summarize", boom)
    r = asyncio.run(U.UsGdp(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US GDP figures could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(U.UsGdp(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US GDP figures are not shown because made-up values would look real." and "gdp" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/us-gdp")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_age_and_the_freshness_are_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(U.UsGdp(client=_client(_handler)).overview(datetime(2027, 3, 1, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 243 and r["freshness"] == "OVERDUE" and r["as_of"] == "2027-03-01T12:00:00+00:00"           # 2026-07-01 to 2027-03-01


def test_each_request_asks_for_one_series_with_a_start_date_and_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(U.UsGdp(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)             # never a combined request: FRED applies one start date to the first series only
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    starts = {req.url.params["cosd"] for req in seen}
    assert len(starts) == 1
    assert 4100 <= (date.today() - date.fromisoformat(starts.pop())).days <= 4300   # about 11.5 years: 45 quarters today


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
    r = asyncio.run(U.UsGdp().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(U.UsGdp(client=given).overview(NOW))
    assert given.is_closed is False
