"""US bank loans and leases (Board of Governors of the Federal Reserve System, H.8 Assets and Liabilities of Commercial Banks, via FRED: 14 weekly series): parsed from real responses (fetched 2026-11-25 02:2x UTC, 619 Wednesdays from 2015-01-07 to 2026-11-11).

The limits are literals, set from the whole real record before any test was written: each series' real lowest and highest value, a lower limit near half the lowest and an upper limit about twice the highest. The four sums hold to the rounding of the published figures (kept to 0.0001 billion dollars): the real largest gap is 0.0002 in the total (five figures) and in commercial real estate (five figures)
and 0.0001 in real estate and in residential real estate (three figures each); each tolerance is the arithmetic bound of its figures each rounded to 0.0001 (0.00005 each): 0.00025, 0.00015, 0.00015 and 0.00025."""
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

from atlas_api import usbankloans as U
from atlas_api.app import create_app
from atlas_api.failreason import dates_in_words, fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usbankloans.json").read_text())
TODAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
LAST = date(2026, 11, 11)

TOT, CI, REL, CON, AOL = "TOTLL", "TOTCI", "RELACBW027SBOG", "CLSACBW027SBOG", "AOLACBW027SBOG"
RRE, CRE, CRL, RHE = "RREACBW027SBOG", "CREACBW027SBOG", "CRLACBW027SBOG", "RHEACBW027SBOG"
CLD, SNF, SMP, SBF, LNF = "CLDACBW027SBOG", "SNFACBW027SBOG", "SMPACBW027SBOG", "SBFACBW027SBOG", "LNFACBW027SBOG"
IDS = [TOT, CI, REL, CON, AOL, RRE, CRE, CRL, RHE, CLD, SNF, SMP, SBF, LNF]
NAME = {TOT: "total loans", CI: "business loans", REL: "real estate loans", CON: "consumer loans", AOL: "other loans", RRE: "residential loans", CRE: "commercial real estate", CRL: "closed-end residential",
        RHE: "home equity loans", CLD: "construction loans", SNF: "nonfarm nonresidential", SMP: "multifamily loans", SBF: "farmland loans", LNF: "nondepository loans"}
LIMITS = {TOT: (3810.0, 28600.0), CI: (890.0, 6200.0), REL: (1820.0, 11800.0), CON: (590.0, 3900.0), AOL: (510.0, 7000.0), RRE: (1010.0, 5500.0), CRE: (800.0, 6400.0), CRL: (780.0, 4900.0),
          RHE: (120.0, 920.0), CLD: (110.0, 990.0), SNF: (530.0, 3900.0), SMP: (110.0, 1300.0), LNF: (160.0, 4300.0), SBF: (40.0, 250.0)}
LEAVES = {CI: 3000.0, CRL: 2400.0, RHE: 300.0, CLD: 400.0, SNF: 1900.0, SMP: 600.0, SBF: 100.0, CON: 1900.0, LNF: 2000.0}
REST = 1400.0                                           # all other loans less loans to nondepository financial institutions


def mback(d, n):
    return d - timedelta(days=7 * n)


def num(v):
    s = f"{v:,.1f}"
    return s[:-2] if s.endswith(".0") else s


def real():
    return {sid: U.parse(F[sid], sid) for sid in IDS}


def build(leaves, rest=REST):
    v = dict(leaves)
    v[RRE] = v[CRL] + v[RHE]
    v[CRE] = v[CLD] + v[SNF] + v[SMP] + v[SBF]
    v[REL] = v[RRE] + v[CRE]
    v[AOL] = v[LNF] + rest
    v[TOT] = v[CI] + v[REL] + v[CON] + v[AOL]
    return v


def world(n=620, last=LAST, **changed):
    one = build({**LEAVES, **changed})
    return {sid: {mback(last, i): v for i in range(n - 1, -1, -1)} for sid, v in one.items()}


def world_by(fn, n=620, last=LAST):
    data = {sid: {} for sid in IDS}
    for i in range(n - 1, -1, -1):
        for sid, v in build(*fn(n - 1 - i)).items():
            data[sid][mback(last, i)] = v
    return data


STEPS = {CI: 2.0, CRL: 1.0, RHE: 0.5, CLD: 0.5, SNF: 1.0, SMP: 0.5, SBF: 0.0, CON: 1.0, LNF: 1.5}        # billions a week, every one exact in binary


def trend(k):
    return {sid: v + STEPS[sid] * k for sid, v in LEAVES.items()}, REST + 0.5 * k


def run(data, today=TODAY):
    return U.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        U.summarize(data, TODAY)


def pct1(new, old):
    return round(100.0 * (new - old) / old, 1)


def weeks_of(data):
    return sorted(data[TOT])


# ---------------------------------------------------------------- the real record

def test_the_real_record_is_619_wednesdays_of_14_series_from_january_2015_to_november_11_2026():
    d = real()
    assert sorted(d) == sorted(IDS) and all(len(s) == 619 for s in d.values())
    assert min(d[TOT]) == date(2015, 1, 7) and max(d[TOT]) == LAST and all(day.weekday() == 2 for day in d[TOT])


def test_the_real_record_passes_every_check_and_reads_the_week_ending_november_11_2026():
    r = run(real())
    assert r["available"] is True and r["date"] == "2026-11-11" and r["age_days"] == 14 and r["freshness"] == "CURRENT"
    assert r["source"] == "Board of Governors of the Federal Reserve System, H.8 Assets and Liabilities of Commercial Banks, via FRED, St. Louis Fed (official, free public data)" and r["url"] == "https://fred.stlouisfed.org/series/TOTLL"
    t = r["total"]
    assert (t["loans_billions"], t["change_week_billions"], t["change_week_pct"], t["change_year_billions"], t["change_year_pct"]) == (14264.2085, 38.2202, 0.3, 1033.1284, 7.8)
    assert t["growth_range"] == {"weeks": 520, "first": "2016-11-30", "lowest": {"value": -4.8, "date": "2021-05-05"}, "highest": {"value": 12.4, "date": "2022-12-07"}, "share_lower_pct": 85}
    k = {x["key"]: x for x in r["kinds"]}
    assert [x["key"] for x in r["kinds"]] == ["business", "real_estate", "consumer", "other"]
    assert [x["label"] for x in r["kinds"]] == ["Business loans (commercial and industrial)", "Real estate loans", "Consumer loans", "All other loans and leases"]
    assert (k["business"]["billions"], k["business"]["share_pct"], k["business"]["change_week_billions"], k["business"]["change_week_pct"], k["business"]["change_year_billions"], k["business"]["change_year_pct"]) == (3018.1473, 21.2, 26.0326, 0.9, 319.9448, 11.9)
    assert (k["real_estate"]["billions"], k["real_estate"]["share_pct"], k["real_estate"]["change_week_billions"], k["real_estate"]["change_week_pct"], k["real_estate"]["change_year_billions"], k["real_estate"]["change_year_pct"]) == (5859.257, 41.1, 1.9421, 0.0, 146.5004, 2.6)
    assert (k["consumer"]["billions"], k["consumer"]["share_pct"], k["consumer"]["change_week_billions"], k["consumer"]["change_week_pct"], k["consumer"]["change_year_billions"], k["consumer"]["change_year_pct"]) == (1933.9418, 13.6, -0.3062, 0.0, 83.6384, 4.5)
    assert str(k["consumer"]["change_week_pct"]) == "0.0"                                                      # a fall of 0.02% is 0.0, not -0.0
    assert (k["other"]["billions"], k["other"]["share_pct"], k["other"]["change_week_billions"], k["other"]["change_week_pct"], k["other"]["change_year_billions"], k["other"]["change_year_pct"]) == (3452.8624, 24.2, 10.5517, 0.3, 483.0449, 16.3)
    res, com = r["real_estate"]
    assert (res["key"], res["label"], res["billions"], res["share_pct"]) == ("residential", "Residential real estate", 2696.714, 46.0)
    assert [(p["key"], p["label"], p["billions"]) for p in res["parts"]] == [("closed_end", "Closed-end residential loans", 2404.406), ("home_equity", "Home equity lines of credit", 292.308)]
    assert (com["key"], com["label"], com["billions"], com["share_pct"]) == ("commercial", "Commercial real estate", 3162.543, 54.0)
    assert [(p["key"], p["label"], p["billions"]) for p in com["parts"]] == [("nonfarm_nonresidential", "Office, retail and other nonfarm nonresidential", 1927.0805), ("multifamily", "Multifamily housing", 648.2978),
                                                                           ("construction", "Construction and land development", 463.1123), ("farmland", "Farmland", 124.0525)]
    assert r["other"] == {"nondepository_billions": 2137.4087, "share_of_other_pct": 61.9}
    assert [(x["date"], x["total_billions"], x["change_billions"]) for x in r["recent"]] == [
        ("2026-10-07", 14178.7012, 32.8958), ("2026-10-14", 14205.1679, 26.4667), ("2026-10-21", 14217.6636, 12.4957), ("2026-10-28", 14218.1277, 0.4641), ("2026-11-04", 14225.9883, 7.8606), ("2026-11-11", 14264.2085, 38.2202)]
    assert r["detail"] == {"weeks_checked": 619, "first_week": "2015-01-07", "last_week": "2026-11-11", "largest_sum_gap": 0.0002}
    assert r["checks"] == {"weeks_in_a_row": True, "range_ok": True, "sums_ok": True, "nondepository_within_other_ok": True}


def test_the_real_record_recomputed_in_plain_python_agrees_with_the_limits_and_the_tolerances_of_this_file():
    rows = {sid: {r[0]: float(r[1]) for r in list(csv.reader(io.StringIO(F[sid])))[1:]} for sid in IDS}
    assert all(len(v) == 619 for v in rows.values()) and all(sorted(v) == sorted(rows[TOT]) for v in rows.values())
    for sid, (lo, hi) in LIMITS.items():
        assert lo <= min(rows[sid].values()) and max(rows[sid].values()) <= hi, sid
        assert lo <= min(rows[sid].values()) / 2 and hi >= max(rows[sid].values()) * 1.9, sid                          # about half the lowest and about twice the highest
    gaps = {
        "total": max(abs(rows[TOT][d] - rows[CI][d] - rows[REL][d] - rows[CON][d] - rows[AOL][d]) for d in rows[TOT]),
        "real estate": max(abs(rows[REL][d] - rows[RRE][d] - rows[CRE][d]) for d in rows[TOT]),
        "residential": max(abs(rows[RRE][d] - rows[CRL][d] - rows[RHE][d]) for d in rows[TOT]),
        "commercial": max(abs(rows[CRE][d] - rows[CLD][d] - rows[SNF][d] - rows[SMP][d] - rows[SBF][d]) for d in rows[TOT]),
    }
    assert {k: round(v, 6) for k, v in gaps.items()} == {"total": 0.0002, "real estate": 0.0001, "residential": 0.0001, "commercial": 0.0002}
    assert all(rows[LNF][d] <= rows[AOL][d] for d in rows[TOT]) and min(rows[AOL][d] - rows[LNF][d] for d in rows[TOT]) > 700


def test_the_series_the_limits_and_the_tolerances_are_these_literals():
    assert U.SERIES == IDS and U.LIMITS == LIMITS and U.NAMES == NAME and U.START == "2015-01-07"
    assert U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and U.PAGE == "https://fred.stlouisfed.org/series/TOTLL"
    assert [(w, p, t, text) for w, p, t, text in U.SUMS] == [
        (TOT, (CI, REL, CON, AOL), 0.00025, "the four kinds"), (REL, (RRE, CRE), 0.00015, "residential plus commercial"),
        (RRE, (CRL, RHE), 0.00015, "closed-end plus home equity"), (CRE, (CLD, SNF, SMP, SBF), 0.00025, "its four parts")]
    assert U.MIN_WEEKS == 572 and U.HISTORY_WEEKS == 520 and U.RECENT_WEEKS == 6 and U.OVERDUE_AFTER_DAYS == 18 and U.CONCURRENCY == 6


# ---------------------------------------------------------------- the default world and the changes

def test_the_default_world_passes_and_every_figure_is_the_one_built():
    r = run(world())
    t = r["total"]
    assert (t["loans_billions"], t["change_week_billions"], t["change_week_pct"], t["change_year_billions"], t["change_year_pct"]) == (14000.0, 0.0, 0.0, 0.0, 0.0)
    assert [(x["key"], x["billions"], x["share_pct"]) for x in r["kinds"]] == [("business", 3000.0, 21.4), ("real_estate", 5700.0, 40.7), ("consumer", 1900.0, 13.6), ("other", 3400.0, 24.3)]
    res, com = r["real_estate"]
    assert (res["billions"], res["share_pct"], com["billions"], com["share_pct"]) == (2700.0, 47.4, 3000.0, 52.6)
    assert [p["billions"] for p in res["parts"]] == [2400.0, 300.0] and [p["billions"] for p in com["parts"]] == [1900.0, 600.0, 400.0, 100.0]
    assert r["other"] == {"nondepository_billions": 2000.0, "share_of_other_pct": 58.8} and r["detail"]["largest_sum_gap"] == 0.0 and r["detail"]["weeks_checked"] == 620 and r["detail"]["first_week"] == "2014-12-31"
    assert len(r["recent"]) == 6 and r["recent"][0]["date"] == "2026-10-07" and r["recent"][-1]["date"] == "2026-11-11" and r["recent"][-1]["change_billions"] == 0.0


def test_the_changes_are_worked_against_the_week_before_and_the_same_week_52_weeks_before():
    d = world_by(trend)
    last, before, ago = build(*trend(619)), build(*trend(618)), build(*trend(619 - 52))
    r = run(d)
    t = r["total"]
    assert t["change_week_billions"] == round(last[TOT] - before[TOT], 4) and t["change_week_pct"] == pct1(last[TOT], before[TOT])
    assert t["change_year_billions"] == round(last[TOT] - ago[TOT], 4) and t["change_year_pct"] == pct1(last[TOT], ago[TOT])
    assert t["change_week_billions"] == 8.5 and t["change_year_billions"] == 442.0
    for x, sid in zip(r["kinds"], (CI, REL, CON, AOL)):
        assert (x["change_week_billions"], x["change_week_pct"]) == (round(last[sid] - before[sid], 4), pct1(last[sid], before[sid]))
        assert (x["change_year_billions"], x["change_year_pct"]) == (round(last[sid] - ago[sid], 4), pct1(last[sid], ago[sid]))
        assert x["share_pct"] == round(100.0 * last[sid] / last[TOT], 1)


def test_a_tiny_fall_that_rounds_to_nothing_is_zero_not_minus_zero():
    d = world()
    for sid in (TOT, CI):
        d[sid][LAST] -= 0.00001
    r = run(d)
    t, biz = r["total"], r["kinds"][0]
    assert str(t["change_week_pct"]) == "0.0" and str(t["change_year_pct"]) == "0.0" and str(biz["change_week_pct"]) == "0.0" and str(biz["change_year_pct"]) == "0.0"
    assert str(t["change_week_billions"]) == "0.0" and str(t["change_year_billions"]) == "0.0" and str(biz["change_week_billions"]) == "0.0" and str(r["recent"][-1]["change_billions"]) == "0.0"
    assert str(U._diff(5.0, 5.0)) == "0.0" and str(U._diff(5.0, 5.00001)) == "0.0" and U._diff(5.0, 3.0) == 2.0 and U._diff(3.0, 5.0) == -2.0 and U._diff(1.00006, 1.0) == 0.0001


def test_the_growth_range_is_the_ten_years_of_year_on_year_growth_and_counts_the_weeks_strictly_lower():
    r = run(world_by(trend))
    tot = lambda k: build(*trend(k))[TOT]
    vals = [pct1(tot(k), tot(k - 52)) for k in range(619 - 519, 620)]                      # the oldest of the 520 weeks first
    g = r["total"]["growth_range"]
    assert g["weeks"] == 520 and g["first"] == mback(LAST, 519).isoformat()
    assert g["lowest"]["value"] == min(vals) and g["highest"]["value"] == max(vals)
    assert g["lowest"]["date"] == mback(LAST, 619 - (619 - 519 + vals.index(min(vals)))).isoformat() and g["highest"]["date"] == mback(LAST, 619 - (619 - 519 + vals.index(max(vals)))).isoformat()
    assert g["share_lower_pct"] == round(100 * sum(1 for v in vals if v < vals[-1]) / 520)


def test_the_growth_range_ranks_the_newest_week_not_the_week_before():
    def jump(k):
        return {**LEAVES, CI: LEAVES[CI] + (300.0 if k == 619 else 0.0)}, REST                  # no growth in any earlier week, 300 of 14,000 in the newest
    g = run(world_by(jump))["total"]["growth_range"]
    assert g["highest"] == {"value": 2.1, "date": LAST.isoformat()} and g["lowest"] == {"value": 0.0, "date": mback(LAST, 519).isoformat()}
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
        assert (x["total_billions"], x["change_billions"]) == (build(*trend(k))[TOT], round(build(*trend(k))[TOT] - build(*trend(k - 1))[TOT], 4))


def test_freshness_is_current_for_18_days_from_the_wednesday_and_overdue_after():
    d = world()
    assert run(d, LAST + timedelta(days=18))["freshness"] == "CURRENT" and run(d, LAST + timedelta(days=18))["age_days"] == 18
    assert run(d, LAST + timedelta(days=19))["freshness"] == "OVERDUE"


def test_the_share_of_the_other_loans_that_goes_to_nondepository_lenders_is_worked_and_rounded_to_one_decimal():
    r = run(world(**{LNF: 1700.0}))
    assert r["other"] == {"nondepository_billions": 1700.0, "share_of_other_pct": 54.8}              # 1700 / 3100


# ---------------------------------------------------------------- the weeks

@pytest.mark.parametrize("sid", IDS)
def test_series_that_end_in_different_weeks_are_refused_whichever_series_is_short(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the bank loan series end in different weeks")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_that_covers_other_weeks_than_total_loans_is_refused_by_name(sid):
    d = world()
    del d[sid][mback(LAST, 50)]
    refused(d, f"the {NAME[sid]} series covers different weeks than total loans")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_an_extra_week_is_refused_by_name(sid):
    d = world()
    d[sid][mback(LAST, 700)] = d[sid][LAST]
    refused(d, f"the {NAME[sid]} series covers different weeks than total loans")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_as_many_weeks_but_one_of_them_different_is_refused_by_name(sid):
    d = world()
    value = d[sid].pop(mback(LAST, 50))
    d[sid][mback(LAST, 700)] = value
    refused(d, f"the {NAME[sid]} series covers different weeks than total loans")


def test_a_date_that_is_not_a_wednesday_is_refused():
    d = {sid: {(k + timedelta(days=1) if k == mback(LAST, 100) else k): v for k, v in s.items()} for sid, s in world().items()}
    refused(d, "a bank loan date is not a Wednesday")


@pytest.mark.parametrize("age", [618, 300, 1])
def test_a_skipped_week_is_refused_after_the_week_before_the_gap_whether_it_is_next_to_the_oldest_in_the_middle_or_next_to_the_newest(age):
    gone = mback(LAST, age)
    d = {sid: {k: v for k, v in s.items() if k != gone} for sid, s in world().items()}
    refused(d, f"the bank loan weeks skip a week after {mback(LAST, age + 1).isoformat()}")


def test_fewer_than_572_weeks_are_refused_and_572_are_enough():
    refused(world(n=571), "the bank loan series cover 571 weeks, fewer than the 572 expected")
    assert run(world(n=572))["detail"]["weeks_checked"] == 572


def test_every_week_check_speaks_before_the_ranges():
    gone = mback(LAST, 300)
    skipped = {sid: {k: v for k, v in s.items() if k != gone} for sid, s in world().items()}
    skipped[TOT][LAST] = 29_000.0
    refused(skipped, f"the bank loan weeks skip a week after {mback(LAST, 301).isoformat()}")
    dated = {sid: {(k + timedelta(days=1) if k == mback(LAST, 100) else k): v for k, v in s.items()} for sid, s in world().items()}
    dated[TOT][LAST + timedelta(days=0)] = 29_000.0
    refused(dated, "a bank loan date is not a Wednesday")
    short = world(n=571)
    short[TOT][LAST] = 29_000.0
    refused(short, "the bank loan series cover 571 weeks, fewer than the 572 expected")
    other = world()
    del other[CON][mback(LAST, 50)]
    other[TOT][LAST] = 29_000.0
    refused(other, f"the {NAME[CON]} series covers different weeks than total loans")


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


def test_the_oldest_week_that_is_out_of_range_speaks_first_and_the_first_series_in_the_list_speaks_first():
    d = world()
    d[TOT][mback(LAST, 100)] = 3000.0
    d[TOT][mback(LAST, 20)] = 29_000.0
    refused(d, edge_message(TOT, 3000.0, *LIMITS[TOT], when=mback(LAST, 100)))
    d = world()
    d[LNF][LAST] = 4400.0
    d[CI][LAST] = 800.0
    refused(d, edge_message(CI, 800.0, *LIMITS[CI]))


@pytest.mark.parametrize("sid", IDS)
def test_the_oldest_week_of_every_series_is_checked_against_its_range_too(sid):
    lo, hi = LIMITS[sid]
    first = weeks_of(world())[0]
    assert first == mback(LAST, 619)
    for bad in (lo - 0.5, hi + 0.5):
        d = world()
        d[sid][first] = bad
        refused(d, edge_message(sid, bad, lo, hi, when=first))


# ---------------------------------------------------------------- the sums

def shifted(data, week, sids, gap):
    for sid in sids:
        data[sid][week] += gap
    return data


UPSTREAM = {0: (TOT,), 1: (REL, TOT), 2: (RRE, REL, TOT), 3: (CRE, REL, TOT)}                 # the whole of a relation and the wholes above it: shifting all keeps every other sum exact


@pytest.mark.parametrize("which, small, large, tol_text, what", [(0, 0.0002, 0.0003, "0.00025", "the four kinds"), (1, 0.0001, 0.0002, "0.00015", "residential plus commercial"),
                                                                (2, 0.0001, 0.0002, "0.00015", "closed-end plus home equity"), (3, 0.0002, 0.0003, "0.00025", "its four parts")])
@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("age", [0, 300, 619])
def test_a_gap_inside_the_rounding_of_the_figures_passes_and_one_unit_more_is_refused_for_each_sum_both_signs_in_three_weeks(which, small, large, tol_text, what, sign, age):
    whole = U.SUMS[which][0]
    week = mback(LAST, age)
    assert run(shifted(world(), week, UPSTREAM[which], sign * small))["detail"]["largest_sum_gap"] == pytest.approx(small, abs=1e-6)
    with pytest.raises(ValueError) as e:
        U.summarize(shifted(world(), week, UPSTREAM[which], sign * large), TODAY)
    assert str(e.value) == f"{NAME[whole]} is {large:.4f} billion off {what} on {week.isoformat()}, over {tol_text}"


def test_a_part_that_is_off_is_found_through_the_whole_and_the_oldest_week_speaks_first():
    d = world()
    d[CI][LAST] += 5.0
    refused(d, f"total loans is 5.0000 billion off the four kinds on {LAST.isoformat()}, over 0.00025")
    d = world()
    d[TOT][LAST] += 5.0
    d[TOT][mback(LAST, 60)] += 9.0
    refused(d, f"total loans is 9.0000 billion off the four kinds on {mback(LAST, 60).isoformat()}, over 0.00025")


def test_the_sums_speak_in_the_order_total_real_estate_residential_commercial():
    d = world()
    d[TOT][LAST] += 0.01
    d[CRE][LAST] += 0.01                                                            # the total is 0.01 off, real estate is 0.01 off its parts, commercial is 0.01 off its parts
    refused(d, f"total loans is 0.0100 billion off the four kinds on {LAST.isoformat()}, over 0.00025")
    d = world()
    d[RRE][LAST] += 0.01                                                            # real estate 0.01 off its parts and residential 0.01 off its parts
    refused(d, f"real estate loans is 0.0100 billion off residential plus commercial on {LAST.isoformat()}, over 0.00015")
    d = world()
    shifted(d, LAST, (RRE, REL, TOT), 0.01)                                         # only residential
    refused(d, f"residential loans is 0.0100 billion off closed-end plus home equity on {LAST.isoformat()}, over 0.00015")
    d = world()
    shifted(d, LAST, (CRE, REL, TOT), 0.01)                                         # only commercial
    refused(d, f"commercial real estate is 0.0100 billion off its four parts on {LAST.isoformat()}, over 0.00025")


def test_the_largest_sum_gap_is_kept_to_five_decimals_and_is_the_largest_of_any_sum_and_either_sign():
    d = world()
    shifted(d, mback(LAST, 3), (TOT,), 0.000234)
    shifted(d, mback(LAST, 9), (RRE, REL, TOT), -0.0001)
    assert run(d)["detail"]["largest_sum_gap"] == 0.00023
    d = world()
    shifted(d, mback(LAST, 3), (TOT,), 0.0001)
    shifted(d, mback(LAST, 9), (CRE, REL, TOT), -0.000234)
    assert run(d)["detail"]["largest_sum_gap"] == 0.00023


# ---------------------------------------------------------------- the loans to nondepository lenders are part of the other loans

def test_loans_to_nondepository_lenders_may_equal_the_other_loans_but_not_exceed_them():
    d = world()
    d[LNF][LAST] = 3400.0
    assert run(d)["other"] == {"nondepository_billions": 3400.0, "share_of_other_pct": 100.0}
    d[LNF][LAST] = 3400.5
    refused(d, f"nondepository loans of 3,400.5 exceed other loans of 3,400 on {LAST.isoformat()}")


def test_the_oldest_week_where_nondepository_loans_exceed_the_other_loans_speaks_first():
    d = world()
    d[LNF][mback(LAST, 200)] = 3500.0
    d[LNF][mback(LAST, 10)] = 3600.0
    refused(d, f"nondepository loans of 3,500 exceed other loans of 3,400 on {mback(LAST, 200).isoformat()}")


def test_the_oldest_week_is_checked_for_nondepository_loans_above_the_other_loans_too():
    first = weeks_of(world())[0]
    d = world()
    d[LNF][first] = 3500.0
    refused(d, f"nondepository loans of 3,500 exceed other loans of 3,400 on {first.isoformat()}")
    d = world()
    d[LNF][first] = 3400.0
    assert run(d)["detail"]["first_week"] == first.isoformat()


# ---------------------------------------------------------------- the order of the checks

def test_a_range_speaks_before_a_sum_and_a_sum_before_the_nondepository_check():
    d = world()
    d[TOT][LAST] = 29_000.0
    refused(d, edge_message(TOT, 29_000.0, *LIMITS[TOT]))
    d = world()
    d[TOT][LAST] += 1.0
    d[LNF][LAST] = 3500.0
    refused(d, f"total loans is 1.0000 billion off the four kinds on {LAST.isoformat()}, over 0.00025")


def test_the_sums_are_checked_one_relation_at_a_time_in_the_listed_order_each_from_its_oldest_week():
    # relation by relation: the first relation in the list speaks even when a later relation fails in an older week
    d = shifted(world(), mback(LAST, 100), UPSTREAM[1], 5.0)
    shifted(d, LAST, UPSTREAM[0], 5.0)
    refused(d, f"total loans is 5.0000 billion off the four kinds on {LAST.isoformat()}, over 0.00025")
    d = shifted(world(), mback(LAST, 100), UPSTREAM[3], 5.0)
    shifted(d, mback(LAST, 10), UPSTREAM[2], 5.0)
    refused(d, f"residential loans is 5.0000 billion off closed-end plus home equity on {mback(LAST, 10).isoformat()}, over 0.00015")
    # within one relation the oldest failing week speaks
    d = shifted(world(), LAST, UPSTREAM[1], 5.0)
    shifted(d, mback(LAST, 100), UPSTREAM[1], 5.0)
    refused(d, f"real estate loans is 5.0000 billion off residential plus commercial on {mback(LAST, 100).isoformat()}, over 0.00015")


def test_a_change_over_nothing_is_none_and_a_tiny_fall_is_zero():
    assert U._change(5.0, None) is None and U._change(5.0, 0.0) is None
    assert U._change(105.0, 100.0) == 5.0 and U._change(95.0, 100.0) == -5.0 and U._change(100.0, 100.0) == 0.0 and str(U._change(99.99999, 100.0)) == "0.0"


# ---------------------------------------------------------------- the messages

def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    texts = [edge_message(sid, 12_345_678.5, *LIMITS[sid]) for sid in IDS]
    texts += [f"{NAME[w]} is 1234567.5000 billion off {text} on 2026-11-11, over {tol:g}" for w, _, tol, text in U.SUMS]
    texts += [f"the {NAME[s]} series covers different weeks than total loans" for s in IDS[1:]]
    texts += ["nondepository loans of 12,345,678.5 exceed other loans of 12,345,678 on 2026-11-11", "the bank loan series cover 571 weeks, fewer than the 572 expected",
              "the bank loan weeks skip a week after 2024-12-25", "the bank loan series end in different weeks", "a bank loan date is not a Wednesday"]
    for text in texts:
        assert len(dates_in_words(text)) <= 130 and len(text) <= 110, (len(text), text)
        assert fail_reason(ValueError(text)) == f"the data failed a check: {dates_in_words(text)}"


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_14_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = U.UsBankLoans(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["total"]["loans_billions"] == 14264.2085 and n["n"] == 14 and r["demo"] is False and r["as_of"] == NOW.isoformat()
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 14


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(U.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = U.UsBankLoans(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 14
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 14
    clock["t"] += 1
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 28
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 28
    clock["t"] += 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 42


def test_without_a_time_the_question_is_asked_at_the_present_moment_in_utc():
    r = asyncio.run(U.UsBankLoans(client=_client(_handler)).overview())
    asked = datetime.fromisoformat(r["as_of"])
    assert asked.tzinfo is not None and asked.utcoffset() == timedelta(0) and abs((datetime.now(timezone.utc) - asked).total_seconds()) < 60


def test_the_age_in_an_answer_is_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(U.UsBankLoans(client=_client(_handler)).overview(datetime(2027, 1, 15, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 65 and r["freshness"] == "OVERDUE"


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = U.UsBankLoans(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(U.UsBankLoans(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US bank loans could not be read right now (the server had an error, HTTP 503)" and "total" not in r and "recent" not in r
    r = asyncio.run(U.UsBankLoans(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == SBF else _handler(req)

    r = asyncio.run(U.UsBankLoans(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "total" not in r and "kinds" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    def answer(replace):
        bad = dict(F)
        for sid, (old, new) in replace.items():
            assert old in F[sid]
            bad[sid] = F[sid].replace(old, new)
        return asyncio.run(U.UsBankLoans(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))

    r = answer({TOT: ("2026-11-11,14264.2085", "2026-11-11,142642.0850")})                             # a decimal slip beyond the range
    assert r["available"] is False and r["reason"] == "US bank loans could not be read right now (the data failed a check: total loans of 142,642.1 on November 11, 2026 is outside 3,810 to 28,600)" and "total" not in r
    r = answer({TOT: ("2026-11-11,14264.2085", "2026-11-11,14274.2085")})                              # a digit slip that stays inside every range: only the sum finds it
    assert r["available"] is False and r["reason"] == "US bank loans could not be read right now (the data failed a check: total loans is 10.0000 billion off the four kinds on November 11, 2026, over 0.00025)"
    r = answer({CI: ("2026-11-11,3018.1473", "2026-11-11,x")})
    assert r["available"] is False and "a TOTCI row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(U.UsBankLoans(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US bank loans could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("TOTLL")

    monkeypatch.setattr(U, "summarize", boom)
    r = asyncio.run(U.UsBankLoans(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US bank loans could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(U.UsBankLoans(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US bank loan figures are not shown because made-up values would look real." and "total" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/us-bank-loans")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_card_is_refreshed_with_the_other_macro_sources():
    jobs = (Path(__file__).parent.parent / "atlas_api" / "sched" / "jobs.py").read_text(encoding="utf-8")
    app = (Path(__file__).parent.parent / "atlas_api" / "app.py").read_text(encoding="utf-8")
    assert '"us_bank_loans"' in jobs and '"us_bank_loans": us_bank_loans' in app and "us_bank_loans = UsBankLoans(demo=demo)" in app
    assert jobs.split('"us_bank_loans"')[1].lstrip().startswith("):") or jobs.split('"us_bank_loans"')[1].lstrip().startswith(",")


def test_each_request_asks_for_one_series_from_2015_with_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(U.UsBankLoans(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)
    assert {req.url.params["cosd"] for req in seen} == {"2015-01-07"}
    assert all(sorted(req.url.params.keys()) == ["cosd", "id"] for req in seen) and len(seen) == 14


def test_no_more_than_six_requests_are_open_at_once_and_six_can_be():
    state = {"open": 0, "most": 0}

    async def slow(req):
        state["open"] += 1
        state["most"] = max(state["most"], state["open"])
        await asyncio.sleep(0.01)
        state["open"] -= 1
        return _handler(req)

    asyncio.run(U.UsBankLoans(client=_client(slow)).overview(NOW))
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
    r = asyncio.run(U.UsBankLoans().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(U.UsBankLoans(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_module_says_why_each_series_is_asked_for_alone_what_the_sums_are_and_what_is_not_checked():
    doc = U.__doc__
    assert "ALONE" in doc and "NOT checked" in doc and "619 weeks" in doc and "0.0001" in doc and "0.00025" in doc and "0.00015" in doc and "Wednesday" in doc and "reclassif" in doc
