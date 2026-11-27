"""US consumer credit (Board of Governors of the Federal Reserve System, G.19 Consumer Credit, via FRED: 3 monthly series): parsed from real responses (fetched 2026-11-24 23:20 UTC, 441 months from 1990-01 to 2026-09).

The limits are literals, set from the whole real record before any test was written (it is in the log): each series' real lowest and highest value, a lower limit near half the lowest and an upper limit about twice the highest (levels grow). The one sum (total = revolving + nonrevolving)
holds to the rounding of the published figures: the figures are kept to 0.01 million dollars, the real largest gap is 0.01 (in 104 of 441 months; exactly 0 in the other 337) and the tolerance is the arithmetic bound of three figures each rounded to 0.01, 0.015."""
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

from atlas_api import usconsumercredit as U
from atlas_api.app import create_app
from atlas_api.failreason import dates_in_words, fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usconsumercredit.json").read_text())
TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)

IDS = ["TOTALSL", "REVOLSL", "NONREVSL"]
NAME = {"TOTALSL": "total consumer credit", "REVOLSL": "revolving credit", "NONREVSL": "nonrevolving credit"}
LIMITS = {"TOTALSL": (400_000.0, 10_500_000.0), "REVOLSL": (100_000.0, 2_800_000.0), "NONREVSL": (260_000.0, 8_000_000.0)}
BASE = {"rev": 1_300_000.0, "non": 3_700_000.0}


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
    return {"TOTALSL": base["rev"] + base["non"], "REVOLSL": base["rev"], "NONREVSL": base["non"]}


def world(n=180, last=LAST, **changed):
    one = build({**BASE, **changed})
    return {sid: {mback(last, i): v for i in range(n - 1, -1, -1)} for sid, v in one.items()}


def world_by(fn, n=180, last=LAST):
    data = {sid: {} for sid in IDS}
    for i in range(n - 1, -1, -1):
        for sid, v in build(fn(i)).items():
            data[sid][mback(last, i)] = v
    return data


def trend(i):
    k = 179 - i
    return {"rev": 1_200_000.0 + 1_000.0 * k, "non": 3_500_000.0 + 2_000.0 * k}


def run(data, today=TODAY):
    return U.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        U.summarize(data, TODAY)


def months_of(data):
    return sorted(data["TOTALSL"])


def pct1(new, old):
    return round(100.0 * (new - old) / old, 1)


# ---------------------------------------------------------------- the real record

def test_the_real_record_is_441_months_of_3_series_from_january_1990_to_september_2026():
    d = real()
    assert sorted(d) == sorted(IDS) and all(len(s) == 441 for s in d.values())
    assert min(d["TOTALSL"]) == date(1990, 1, 1) and max(d["TOTALSL"]) == LAST


def test_the_real_record_passes_every_check_and_reads_september_2026():
    r = run(real())
    assert r["available"] is True and r["date"] == "2026-09-01" and r["month"] == "2026-09" and r["age_days"] == 84 and r["freshness"] == "CURRENT"
    assert r["source"] == "Board of Governors of the Federal Reserve System, G.19 Consumer Credit, via FRED, St. Louis Fed (official, free public data)" and r["url"] == "https://fred.stlouisfed.org/series/TOTALSL"
    t = r["total"]
    assert (t["total_millions"], t["revolving_millions"], t["nonrevolving_millions"], t["revolving_share_pct"]) == (5224415.99, 1368452.96, 3855963.04, 26.2)
    assert (t["change_month_millions"], t["change_month_pct"], t["change_year_millions"], t["change_year_pct"]) == (27838.63, 0.5, 152452.56, 3.0)
    assert t["growth_range"] == {"months": 120, "first": "2016-10", "lowest": {"value": -1.1, "month": "2025-02"}, "highest": {"value": 10.1, "month": "2022-04"}, "share_lower_pct": 38}
    rev, non = r["kinds"]
    assert (rev["key"], rev["millions"], rev["share_pct"], rev["change_month_millions"], rev["change_month_pct"], rev["change_year_millions"], rev["change_year_pct"]) == ("revolving", 1368452.96, 26.2, 16298.61, 1.2, 55739.39, 4.2)
    assert (non["key"], non["millions"], non["share_pct"], non["change_month_millions"], non["change_month_pct"], non["change_year_millions"], non["change_year_pct"]) == ("nonrevolving", 3855963.04, 73.8, 11540.02, 0.3, 96713.19, 2.6)
    assert [(x["month"], x["total_millions"], x["revolving_millions"], x["nonrevolving_millions"], x["change_millions"]) for x in r["recent"]] == [
        ("2026-04", 5152692.28, 1349979.48, 3802712.79, 21263.4), ("2026-05", 5155910.75, 1347844.7, 3808066.05, 3218.47), ("2026-06", 5170754.93, 1354418.69, 3816336.24, 14844.18),
        ("2026-07", 5188386.46, 1357122.75, 3831263.71, 17631.53), ("2026-08", 5196577.36, 1352154.35, 3844423.02, 8190.9), ("2026-09", 5224415.99, 1368452.96, 3855963.04, 27838.63)]
    assert r["detail"] == {"months_checked": 441, "first_month": "1990-01", "last_month": "2026-09", "largest_sum_gap": 0.01}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "totals_add_up_ok": True}


def test_the_real_record_recomputed_in_plain_python_agrees_with_the_limits_and_the_tolerance_of_this_file():
    rows = {sid: {r[0]: float(r[1]) for r in list(csv.reader(io.StringIO(F[sid])))[1:]} for sid in IDS}
    assert all(len(v) == 441 for v in rows.values())
    for sid, (lo, hi) in LIMITS.items():
        assert lo <= min(rows[sid].values()) and max(rows[sid].values()) <= hi, sid
    gaps = [round(rows["TOTALSL"][d] - rows["REVOLSL"][d] - rows["NONREVSL"][d], 3) for d in rows["TOTALSL"]]
    assert max(abs(g) for g in gaps) == 0.01 and sum(1 for g in gaps if g == 0) == 337 and sum(1 for g in gaps if g == 0.01) == 52 and sum(1 for g in gaps if g == -0.01) == 52
    assert min(rows["TOTALSL"].values()) == 797276.31 and max(rows["TOTALSL"].values()) == 5224415.99


def test_the_series_are_asked_for_in_this_order_and_the_limits_are_these_literals():
    assert U.SERIES == IDS and U.LIMITS == LIMITS and U.NAMES == NAME and U.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv"
    assert U.SUM_TOLERANCE == 0.015 and U.MIN_MONTHS == 132 and U.HISTORY_MONTHS == 120 and U.RECENT_MONTHS == 6 and U.OVERDUE_AFTER_DAYS == 105 and U.CONCURRENCY == 3


# ---------------------------------------------------------------- the default world and the changes

def test_the_default_world_passes_and_every_figure_is_the_one_built():
    r = run(world())
    t = r["total"]
    assert (t["total_millions"], t["revolving_millions"], t["nonrevolving_millions"], t["revolving_share_pct"]) == (5000000.0, 1300000.0, 3700000.0, 26.0)
    assert (t["change_month_millions"], t["change_month_pct"], t["change_year_millions"], t["change_year_pct"]) == (0.0, 0.0, 0.0, 0.0)
    assert [(k["key"], k["label"], k["millions"], k["share_pct"]) for k in r["kinds"]] == [
        ("revolving", "Revolving credit (credit cards and other revolving plans)", 1300000.0, 26.0), ("nonrevolving", "Nonrevolving credit (car, student and other instalment loans)", 3700000.0, 74.0)]
    assert r["detail"]["largest_sum_gap"] == 0.0 and r["detail"]["months_checked"] == 180 and r["detail"]["first_month"] == "2011-10"
    assert len(r["recent"]) == 6 and r["recent"][0]["month"] == "2026-04" and r["recent"][-1]["month"] == "2026-09" and r["recent"][-1]["change_millions"] == 0.0


def test_the_changes_are_worked_against_the_month_before_and_the_same_month_a_year_before():
    d = world_by(trend)
    last, before, ago = trend(0), trend(1), trend(12)
    tot = lambda p: p["rev"] + p["non"]
    r = run(d)
    t = r["total"]
    assert t["change_month_millions"] == round(tot(last) - tot(before), 2) == 3000.0 and t["change_month_pct"] == pct1(tot(last), tot(before)) == 0.1
    assert t["change_year_millions"] == round(tot(last) - tot(ago), 2) == 36000.0 and t["change_year_pct"] == pct1(tot(last), tot(ago)) == 0.7
    rev, non = r["kinds"]
    assert (rev["change_month_millions"], rev["change_month_pct"], rev["change_year_millions"], rev["change_year_pct"]) == (1000.0, pct1(last["rev"], before["rev"]), 12000.0, pct1(last["rev"], ago["rev"]))
    assert (non["change_month_millions"], non["change_month_pct"], non["change_year_millions"], non["change_year_pct"]) == (2000.0, pct1(last["non"], before["non"]), 24000.0, pct1(last["non"], ago["non"]))
    assert rev["share_pct"] == round(100 * last["rev"] / tot(last), 1) and non["share_pct"] == round(100 * last["non"] / tot(last), 1)


def test_a_tiny_fall_that_rounds_to_nothing_is_zero_not_minus_zero():
    d = world()
    d["TOTALSL"][LAST] -= 0.001
    d["NONREVSL"][LAST] -= 0.001
    r = run(d)
    t, non = r["total"], r["kinds"][1]
    assert t["change_month_pct"] == 0.0 and str(t["change_month_pct"]) == "0.0" and str(t["change_year_pct"]) == "0.0" and str(non["change_month_pct"]) == "0.0" and str(non["change_year_pct"]) == "0.0"
    assert str(t["change_month_millions"]) == "0.0" and str(t["change_year_millions"]) == "0.0" and str(non["change_month_millions"]) == "0.0" and str(non["change_year_millions"]) == "0.0" and str(r["recent"][-1]["change_millions"]) == "0.0"
    assert str(U._diff(5.0, 5.0)) == "0.0" and str(U._diff(5.0, 5.001)) == "0.0" and U._diff(5.0, 3.0) == 2.0 and U._diff(3.0, 5.0) == -2.0 and U._diff(1.006, 1.0) == 0.01


def test_the_growth_range_is_the_ten_years_of_year_on_year_growth_and_counts_the_months_strictly_lower():
    d = world_by(trend)
    r = run(d)
    tot = lambda i: trend(i)["rev"] + trend(i)["non"]
    vals = [pct1(tot(i), tot(i + 12)) for i in range(119, -1, -1)]                           # oldest of the 120 months first
    g = r["total"]["growth_range"]
    assert g["months"] == 120 and g["first"] == mlab(mback(LAST, 119))
    assert g["lowest"]["value"] == min(vals) and g["highest"]["value"] == max(vals)
    assert g["lowest"]["month"] == mlab(mback(LAST, 119 - vals.index(min(vals)))) and g["highest"]["month"] == mlab(mback(LAST, 119 - vals.index(max(vals))))
    assert g["share_lower_pct"] == round(100 * sum(1 for v in vals if v < vals[-1]) / 120)


def test_the_six_recent_months_have_their_own_figures_and_the_oldest_comes_first():
    r = run(world_by(trend))
    assert [x["month"] for x in r["recent"]] == [mlab(mback(LAST, i)) for i in range(5, -1, -1)]
    for x, i in zip(r["recent"], range(5, -1, -1)):
        one, was = build(trend(i)), build(trend(i + 1))
        assert (x["total_millions"], x["revolving_millions"], x["nonrevolving_millions"], x["change_millions"]) == (one["TOTALSL"], one["REVOLSL"], one["NONREVSL"], round(one["TOTALSL"] - was["TOTALSL"], 2))


def test_freshness_is_current_for_105_days_from_the_first_of_the_month_and_overdue_after():
    d = world()
    assert run(d, LAST + timedelta(days=105))["freshness"] == "CURRENT" and run(d, LAST + timedelta(days=105))["age_days"] == 105
    assert run(d, LAST + timedelta(days=106))["freshness"] == "OVERDUE"


# ---------------------------------------------------------------- the months

@pytest.mark.parametrize("sid", IDS)
def test_series_that_end_in_different_months_are_refused_whichever_series_is_short(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the consumer credit series end in different months")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_that_covers_other_months_than_total_consumer_credit_is_refused_by_name(sid):
    d = world()
    del d[sid][mback(LAST, 50)]
    refused(d, f"the {NAME[sid]} series covers different months than total consumer credit")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_an_extra_month_is_refused_by_name(sid):
    d = world()
    d[sid][mback(LAST, 200)] = BASE["rev"]
    refused(d, f"the {NAME[sid]} series covers different months than total consumer credit")


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_as_many_months_but_one_of_them_different_is_refused_by_name(sid):
    d = world()
    value = d[sid].pop(mback(LAST, 50))
    d[sid][mback(LAST, 200)] = value
    refused(d, f"the {NAME[sid]} series covers different months than total consumer credit")


def test_a_date_that_is_not_the_first_of_a_month_is_refused():
    d = world()
    d = {sid: {(k.replace(day=2) if k == mback(LAST, 100) else k): v for k, v in s.items()} for sid, s in d.items()}
    refused(d, "a consumer credit date is not the 1st of a month")


@pytest.mark.parametrize("age", [178, 40, 1])
def test_a_skipped_month_is_refused_after_the_month_before_the_gap_whether_it_is_next_to_the_oldest_in_the_middle_or_next_to_the_newest(age):
    d = world()
    gone = mback(LAST, age)
    d = {sid: {k: v for k, v in s.items() if k != gone} for sid, s in d.items()}
    refused(d, f"the consumer credit months skip a month after {mlab(mback(LAST, age + 1))}")


def test_fewer_than_132_months_are_refused_and_132_are_enough():
    refused(world(n=131), "the consumer credit series cover 131 months, fewer than the 132 expected")
    assert run(world(n=132))["detail"]["months_checked"] == 132


def test_every_month_check_speaks_before_the_ranges():
    gone = mback(LAST, 40)
    skipped = {sid: {k: v for k, v in s.items() if k != gone} for sid, s in world().items()}
    skipped["TOTALSL"][LAST] = 11_000_000.0
    refused(skipped, f"the consumer credit months skip a month after {mlab(mback(LAST, 41))}")
    dated = {sid: {(k.replace(day=2) if k == mback(LAST, 100) else k): v for k, v in s.items()} for sid, s in world().items()}
    dated["TOTALSL"][LAST] = 11_000_000.0
    refused(dated, "a consumer credit date is not the 1st of a month")
    short = world(n=131)
    short["TOTALSL"][LAST] = 11_000_000.0
    refused(short, "the consumer credit series cover 131 months, fewer than the 132 expected")
    other = world()
    del other["REVOLSL"][mback(LAST, 50)]
    other["TOTALSL"][LAST] = 11_000_000.0
    refused(other, f"the {NAME['REVOLSL']} series covers different months than total consumer credit")


# ---------------------------------------------------------------- the ranges

def edge_message(sid, v, lo, hi, when=LAST):
    return f"{NAME[sid]} of {num(v)} in {mlab(when)} is outside {num(lo)} to {num(hi)}"


@pytest.mark.parametrize("sid", IDS)
def test_a_value_just_under_the_lower_limit_or_just_over_the_upper_one_is_refused_and_the_limits_themselves_are_not(sid):
    lo, hi = LIMITS[sid]
    for edge in (lo, hi):
        d = world()
        d[sid][LAST] = edge
        U._check_ranges(d, months_of(d))
    d = world()
    d[sid][LAST] = lo - 1.0
    refused(d, edge_message(sid, lo - 1.0, lo, hi))
    d = world()
    d[sid][LAST] = hi + 1.0
    refused(d, edge_message(sid, hi + 1.0, lo, hi))


def test_the_oldest_month_that_is_out_of_range_speaks_first_and_the_first_series_in_the_list_speaks_first():
    d = world()
    d["TOTALSL"][mback(LAST, 100)] = 399_999.0
    d["TOTALSL"][mback(LAST, 20)] = 10_500_001.0
    refused(d, edge_message("TOTALSL", 399_999.0, *LIMITS["TOTALSL"], when=mback(LAST, 100)))
    d = world()
    d["NONREVSL"][LAST] = 9_000_000.0
    d["REVOLSL"][LAST] = 50_000.0
    refused(d, edge_message("REVOLSL", 50_000.0, *LIMITS["REVOLSL"]))


# ---------------------------------------------------------------- the sum

@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("age", [0, 90, 179])
def test_a_total_one_cent_of_a_million_off_the_sum_passes_and_two_cents_off_is_refused(sign, age):
    when = mback(LAST, age)
    d = world()
    d["TOTALSL"][when] += sign * 0.01
    assert run(d)["detail"]["largest_sum_gap"] == pytest.approx(0.01, abs=1e-6)
    d = world()
    d["TOTALSL"][when] += sign * 0.02
    refused(d, f"total consumer credit is 0.020 million off revolving plus nonrevolving in {mlab(when)}, over 0.015")


def test_a_part_that_is_off_is_found_through_the_total_and_the_oldest_month_speaks_first():
    d = world()
    d["NONREVSL"][LAST] += 5.0
    refused(d, f"total consumer credit is 5.000 million off revolving plus nonrevolving in {mlab(LAST)}, over 0.015")
    d = world()
    d["TOTALSL"][LAST] += 5.0
    d["TOTALSL"][mback(LAST, 60)] += 9.0
    refused(d, f"total consumer credit is 9.000 million off revolving plus nonrevolving in {mlab(mback(LAST, 60))}, over 0.015")


def test_the_largest_sum_gap_is_kept_to_four_decimals_and_is_the_largest_of_either_sign():
    d = world()
    d["TOTALSL"][mback(LAST, 3)] += 0.01234
    d["TOTALSL"][mback(LAST, 9)] -= 0.0071
    assert run(d)["detail"]["largest_sum_gap"] == 0.0123
    d = world()
    d["TOTALSL"][mback(LAST, 3)] += 0.0071
    d["TOTALSL"][mback(LAST, 9)] -= 0.01234
    assert run(d)["detail"]["largest_sum_gap"] == 0.0123


def test_a_range_speaks_before_the_sum_and_the_months_before_both():
    d = world()
    d["TOTALSL"][LAST] = 11_000_000.0
    refused(d, edge_message("TOTALSL", 11_000_000.0, *LIMITS["TOTALSL"]))
    d = world()
    del d["NONREVSL"][LAST]
    d["TOTALSL"][mback(LAST, 20)] = 11_000_000.0
    refused(d, "the consumer credit series end in different months")


def test_a_change_over_nothing_is_none_and_a_tiny_fall_is_zero():
    assert U._change(5.0, None) is None and U._change(5.0, 0.0) is None
    assert U._change(105.0, 100.0) == 5.0 and U._change(95.0, 100.0) == -5.0 and U._change(100.0, 100.0) == 0.0
    assert str(U._change(99.99999, 100.0)) == "0.0"


# ---------------------------------------------------------------- the messages

def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    texts = [edge_message(sid, 12_345_678.5, *LIMITS[sid]) for sid in IDS]
    texts += ["total consumer credit is 1234567.500 million off revolving plus nonrevolving in 2026-09, over 0.015"]
    texts += [f"the {NAME[s]} series covers different months than total consumer credit" for s in IDS[1:]]
    texts += ["the consumer credit series cover 131 months, fewer than the 132 expected", "the consumer credit months skip a month after 2024-12", "the consumer credit series end in different months", "a consumer credit date is not the 1st of a month"]
    for text in texts:
        assert len(text) <= 110, (len(text), text)
        assert fail_reason(ValueError(text)) == f"the data failed a check: {dates_in_words(text)}"


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_3_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = U.UsConsumerCredit(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["total"]["total_millions"] == 5224415.99 and n["n"] == 3 and r["demo"] is False and r["as_of"] == NOW.isoformat()
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(U.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = U.UsConsumerCredit(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 3
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3
    clock["t"] += 1
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 6
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6
    clock["t"] += 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 9


def test_without_a_time_the_question_is_asked_at_the_present_moment_in_utc():
    r = asyncio.run(U.UsConsumerCredit(client=_client(_handler)).overview())
    asked = datetime.fromisoformat(r["as_of"])
    assert asked.tzinfo is not None and asked.utcoffset() == timedelta(0)
    assert abs((datetime.now(timezone.utc) - asked).total_seconds()) < 60


def test_the_age_in_an_answer_is_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(U.UsConsumerCredit(client=_client(_handler)).overview(datetime(2027, 1, 15, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 136 and r["freshness"] == "OVERDUE"


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = U.UsConsumerCredit(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(U.UsConsumerCredit(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US consumer credit could not be read right now (the server had an error, HTTP 503)" and "total" not in r and "recent" not in r
    r = asyncio.run(U.UsConsumerCredit(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == "NONREVSL" else _handler(req)

    r = asyncio.run(U.UsConsumerCredit(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "total" not in r and "kinds" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    def answer(replace):
        bad = dict(F)
        for sid, (old, new) in replace.items():
            assert old in F[sid]
            bad[sid] = F[sid].replace(old, new)
        return asyncio.run(U.UsConsumerCredit(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))

    r = answer({"TOTALSL": ("2026-09-01,5224415.9900000002", "2026-09-01,52244159.9900000002")})            # a decimal slip beyond the range
    assert r["available"] is False and r["reason"] == "US consumer credit could not be read right now (the data failed a check: total consumer credit of 52,244,160 in September 2026 is outside 400,000 to 10,500,000)" and "total" not in r
    r = answer({"TOTALSL": ("2026-09-01,5224415.9900000002", "2026-09-01,5224515.9900000002")})            # a digit slip that stays inside every range: only the sum finds it
    assert r["available"] is False and r["reason"] == "US consumer credit could not be read right now (the data failed a check: total consumer credit is 99.990 million off revolving plus nonrevolving in September 2026, over 0.015)"
    r = answer({"REVOLSL": ("2026-09-01,1368452.9600000000", "2026-09-01,x")})
    assert r["available"] is False and "a REVOLSL row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(U.UsConsumerCredit(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US consumer credit could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("TOTALSL")

    monkeypatch.setattr(U, "summarize", boom)
    r = asyncio.run(U.UsConsumerCredit(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US consumer credit could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(U.UsConsumerCredit(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US consumer credit figures are not shown because made-up values would look real." and "total" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/us-consumer-credit")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_card_is_refreshed_with_the_other_macro_sources():
    jobs = (Path(__file__).parent.parent / "atlas_api" / "sched" / "jobs.py").read_text(encoding="utf-8")
    app = (Path(__file__).parent.parent / "atlas_api" / "app.py").read_text(encoding="utf-8")
    assert '"us_consumer_credit"' in jobs and '"us_consumer_credit": us_consumer_credit' in app and "us_consumer_credit = UsConsumerCredit(demo=demo)" in app


def test_each_request_asks_for_one_series_from_1990_with_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(U.UsConsumerCredit(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)
    assert {req.url.params["cosd"] for req in seen} == {"1990-01-01"}
    assert all(sorted(req.url.params.keys()) == ["cosd", "id"] for req in seen) and len(seen) == 3


def test_no_more_than_three_requests_are_open_at_once_and_all_three_can_be():
    state = {"open": 0, "most": 0}

    async def slow(req):
        state["open"] += 1
        state["most"] = max(state["most"], state["open"])
        await asyncio.sleep(0.01)
        state["open"] -= 1
        return _handler(req)

    asyncio.run(U.UsConsumerCredit(client=_client(slow)).overview(NOW))
    assert state["most"] == 3


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
    r = asyncio.run(U.UsConsumerCredit().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(U.UsConsumerCredit(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_module_says_why_each_series_is_asked_for_alone_and_what_it_does_not_check():
    doc = U.__doc__
    assert "ALONE" in doc and "NOT checked" in doc and "441 months" in doc and "0.01" in doc and "0.015" in doc
