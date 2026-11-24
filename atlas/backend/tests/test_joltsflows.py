"""US hires, quits and layoffs by industry (Job Openings and Labor Turnover Survey of the Bureau of Labor Statistics, via FRED: 33 monthly series): parsed from real responses (fetched 2026-11-24 17:21 UTC, 310 months from 2000-12 to 2026-09).

The limits are literals, set from the whole real record before any test was written (it is in the log): every series' real lowest and highest value, a lower limit near half the lowest and an upper one beyond the highest; the eight sums, whose real largest gap is 1 thousand in every one (three or four published figures each rounded to a thousand: the arithmetic bounds are 1.5 and 2.0, exact in binary); the closest an industry's quits come to its separations (102 thousand, manufacturing in 2013-10); and what is left of private after the six industries (at least 154 thousand, quits in 2020-04)."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import joltsflows as J
from atlas_api.app import create_app
from atlas_api.failreason import fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "fred_joltsflows.json").read_text())
TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)
MAY = date(2019, 5, 1)

SECTOR_MEASURES = ("HIL", "QUL", "LDL", "TSL", "OSL")
INDUSTRY_MEASURES = ("HIL", "QUL", "TSL")
MEASURE = {"HIL": "hires", "QUL": "quits", "LDL": "layoffs", "TSL": "separations", "OSL": "other separations"}
GROUPS = (("nf", "JTS", "nonfarm", SECTOR_MEASURES), ("pr", "JTS1000", "private", SECTOR_MEASURES), ("gv", "JTS9000", "government", SECTOR_MEASURES),
          ("co", "JTS2300", "construction", INDUSTRY_MEASURES), ("ma", "JTS3000", "manufacturing", INDUSTRY_MEASURES), ("tt", "JTS4000", "trade, transport and utilities", INDUSTRY_MEASURES),
          ("pb", "JTS540099", "professional and business services", INDUSTRY_MEASURES), ("eh", "JTS6000", "education and health services", INDUSTRY_MEASURES),
          ("lh", "JTS7000", "leisure and hospitality", INDUSTRY_MEASURES))
IDS = tuple(f"{p}{m}" for _k, p, _n, ms in GROUPS for m in ms)
NAME = {f"{p}{m}": f"{n} {MEASURE[m]}" for _k, p, n, ms in GROUPS for m in ms}
PREFIX = {k: p for k, p, _n, _ms in GROUPS}
GNAME = {k: n for k, _p, n, _ms in GROUPS}
INDUSTRIES = ("co", "ma", "tt", "pb", "eh", "lh")
LIMITS = {"JTSHIL": (1_500.0, 20_000.0), "JTSQUL": (800.0, 9_000.0), "JTSLDL": (600.0, 26_000.0), "JTSTSL": (1_900.0, 32_000.0), "JTSOSL": (100.0, 900.0),
          "JTS1000HIL": (1_500.0, 20_000.0), "JTS1000QUL": (700.0, 9_000.0), "JTS1000LDL": (600.0, 26_000.0), "JTS1000TSL": (1_800.0, 32_000.0), "JTS1000OSL": (90.0, 800.0),
          "JTS9000HIL": (100.0, 1_500.0), "JTS9000QUL": (40.0, 550.0), "JTS9000LDL": (25.0, 700.0), "JTS9000TSL": (130.0, 1_100.0), "JTS9000OSL": (20.0, 190.0),
          "JTS2300HIL": (100.0, 1_500.0), "JTS2300QUL": (15.0, 500.0), "JTS2300TSL": (100.0, 1_700.0),
          "JTS3000HIL": (80.0, 1_300.0), "JTS3000QUL": (30.0, 700.0), "JTS3000TSL": (100.0, 1_800.0),
          "JTS4000HIL": (350.0, 3_200.0), "JTS4000QUL": (150.0, 2_100.0), "JTS4000TSL": (350.0, 5_600.0),
          "JTS540099HIL": (300.0, 2_900.0), "JTS540099QUL": (120.0, 1_700.0), "JTS540099TSL": (330.0, 3_900.0),
          "JTS6000HIL": (200.0, 2_300.0), "JTS6000QUL": (100.0, 1_400.0), "JTS6000TSL": (200.0, 4_200.0),
          "JTS7000HIL": (200.0, 4_100.0), "JTS7000QUL": (150.0, 1_900.0), "JTS7000TSL": (300.0, 11_500.0)}
# the primaries of the default world: a sector is (hires, quits, layoffs, other), an industry (hires, quits, separations); the nonfarm series and every total are derived, so every identity holds exactly
BASE = {"gv": (300.0, 180.0, 80.0, 60.0), "pr": (5000.0, 3000.0, 1500.0, 250.0),
        "co": (350.0, 200.0, 340.0), "ma": (300.0, 190.0, 310.0), "tt": (1100.0, 700.0, 1050.0), "pb": (900.0, 450.0, 920.0), "eh": (800.0, 540.0, 780.0), "lh": (1000.0, 750.0, 1000.0)}


def mback(d, n):
    i = d.year * 12 + d.month - 1 - n
    return date(i // 12, i % 12 + 1, 1)


def mlab(d):
    return f"{d.year}-{d.month:02d}"


def num(v):
    s = f"{v:,.1f}"
    return s[:-2] if s.endswith(".0") else s


def real():
    return {sid: J.parse(F[sid], sid) for sid in IDS}


def build(base):
    """All 33 series of one month from the primaries; nonfarm = private + government in every measure and separations = quits + layoffs + other in every sector, exactly."""
    out, parts = {}, {}
    for k in ("gv", "pr"):
        h, q, l, o = base[k]
        parts[k] = (h, q, l, q + l + o, o)
        for m, v in zip(SECTOR_MEASURES, parts[k]):
            out[PREFIX[k] + m] = v
    for i, m in enumerate(SECTOR_MEASURES):
        out["JTS" + m] = parts["gv"][i] + parts["pr"][i]
    for k in INDUSTRIES:
        for m, v in zip(INDUSTRY_MEASURES, base[k]):
            out[PREFIX[k] + m] = v
    return out


def world(n=180, last=LAST, **changed):
    """`n` months ending at `last`, every figure constant (the BASE primaries, with those named in `changed` replaced)."""
    one = build({**BASE, **changed})
    return {sid: {mback(last, i): v for i in range(n - 1, -1, -1)} for sid, v in one.items()}


def world_by(fn, n=180, last=LAST):
    """Like `world`, but the primaries of the month `i` months before `last` are `fn(i)`."""
    data = {sid: {} for sid in IDS}
    for i in range(n - 1, -1, -1):
        for sid, v in build(fn(i)).items():
            data[sid][mback(last, i)] = v
    return data


def bump(data, when, offsets):
    for sid, v in offsets.items():
        data[sid][when] += v
    return data


def run(data, today=TODAY):
    return J.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        J.summarize(data, TODAY)


def not_a_range_refusal(data):
    try:
        J.summarize(data, TODAY)
    except ValueError as e:
        assert "is outside" not in str(e), str(e)


def plain(sid):
    """The saved response of one series as (month text, value) pairs, read without the module."""
    return [(ln.split(",")[0], float(ln.split(",")[1])) for ln in F[sid].strip().splitlines()[1:]]


# ---------------------------------------------------------------- the real record

def test_the_real_record_passes_every_check_and_reports_its_window():
    r = run(real())
    assert r["available"] is True and r["date"] == "2026-09-01" and r["month"] == "2026-09" and r["age_days"] == 84 and r["freshness"] == "CURRENT"
    assert r["detail"] == {"months_checked": 310, "first_month": "2000-12", "last_month": "2026-09", "largest_sum_gap": 1.0, "closest_part_margin": 102.0, "smallest_rest_of_private": 154.0}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "totals_add_up_ok": True, "quits_inside_separations_ok": True, "industries_inside_private_ok": True}


def test_the_real_headline_figures_are_pinned():
    r = run(real())
    t = r["total"]
    assert (t["hires_thousands"], t["quits_thousands"], t["layoffs_thousands"], t["other_thousands"], t["separations_thousands"], t["net_thousands"], t["quits_share_pct"]) == (5402.0, 3365.0, 1641.0, 313.0, 5319.0, 83.0, 63.3)
    pr, gv = r["sectors"]
    assert (pr["key"], pr["label"]) == ("private", "Private sector") and (gv["key"], gv["label"]) == ("government", "Government")
    assert (pr["hires_thousands"], pr["quits_thousands"], pr["layoffs_thousands"], pr["other_thousands"], pr["separations_thousands"], pr["net_thousands"], pr["quits_share_pct"]) == (5078.0, 3187.0, 1559.0, 250.0, 4997.0, 81.0, 63.8)
    assert (gv["hires_thousands"], gv["quits_thousands"], gv["layoffs_thousands"], gv["other_thousands"], gv["separations_thousands"], gv["net_thousands"], gv["quits_share_pct"]) == (324.0, 178.0, 82.0, 62.0, 322.0, 2.0, 55.3)
    rows = [(x["key"], x["label"], x["derived"], x["hires_thousands"], x["quits_thousands"], x["separations_thousands"], x["net_thousands"], x["quits_share_pct"]) for x in r["industries"]]
    assert rows == [("trade_transport", "Trade, transportation and utilities", False, 1163.0, 745.0, 1078.0, 85.0, 69.1),
                    ("leisure", "Leisure and hospitality", False, 1041.0, 752.0, 1013.0, 28.0, 74.2),
                    ("professional", "Professional and business services", False, 927.0, 463.0, 955.0, -28.0, 48.5),
                    ("education_health", "Private education and health services", False, 798.0, 543.0, 784.0, 14.0, 69.3),
                    ("construction", "Construction", False, 356.0, 198.0, 359.0, -3.0, 55.2),
                    ("manufacturing", "Manufacturing", False, 313.0, 199.0, 318.0, -5.0, 62.6),
                    ("other_private", "Everything else in the private sector (mining and logging, information, financial activities, other services)", True, 480.0, 287.0, 490.0, -10.0, 58.6)]


def test_the_headline_figures_equal_a_plain_python_recomputation_from_the_saved_responses():
    r = run(real())
    t = r["total"]
    for key, sid in (("hires", "JTSHIL"), ("quits", "JTSQUL"), ("layoffs", "JTSLDL"), ("separations", "JTSTSL")):
        rows = plain(sid)
        now, ago = rows[-1][1], rows[-13][1]
        assert rows[-1][0] == "2026-09-01" and rows[-13][0] == "2025-09-01"
        assert t[f"{key}_thousands"] == now and t[f"{key}_change_year_pct"] == round(100.0 * (now - ago) / ago, 1)
    for key, sid in (("hires", "JTSHIL"), ("quits", "JTSQUL"), ("layoffs", "JTSLDL")):
        rows = plain(sid)[-120:]
        vals = [v for _d, v in rows]
        lo, hi = vals.index(min(vals)), vals.index(max(vals))
        assert t[f"{key}_range"] == {"months": 120, "first": rows[0][0][:7], "lowest": {"value": min(vals), "month": rows[lo][0][:7]}, "highest": {"value": max(vals), "month": rows[hi][0][:7]},
                                     "share_lower_pct": round(100 * sum(1 for v in vals if v < vals[-1]) / 120)}
    for row in r["industries"][:-1]:
        for key, sid in (("hires", "HIL"), ("quits", "QUL")):
            prefix = {"trade_transport": "JTS4000", "leisure": "JTS7000", "professional": "JTS540099", "education_health": "JTS6000", "construction": "JTS2300", "manufacturing": "JTS3000"}[row["key"]]
            rows = plain(prefix + sid)
            assert row[f"{key}_change_year_pct"] == round(100.0 * (rows[-1][1] - rows[-13][1]) / rows[-13][1], 1)
    for row, prefix in zip(r["sectors"], ("JTS1000", "JTS9000")):
        for key, sid in (("hires", "HIL"), ("quits", "QUL")):
            rows = plain(prefix + sid)
            assert row[f"{key}_change_year_pct"] == round(100.0 * (rows[-1][1] - rows[-13][1]) / rows[-13][1], 1)


def test_the_six_recent_months_are_oldest_first_with_their_own_figures():
    r = run(real())
    assert [x["month"] for x in r["recent"]] == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    cols = {sid: plain(sid)[-6:] for sid in ("JTSHIL", "JTSQUL", "JTSLDL", "JTSTSL")}
    for i, x in enumerate(r["recent"]):
        h, q, l, s = (cols[sid][i][1] for sid in ("JTSHIL", "JTSQUL", "JTSLDL", "JTSTSL"))
        assert cols["JTSHIL"][i][0][:7] == x["month"]
        assert (x["hires_thousands"], x["quits_thousands"], x["layoffs_thousands"], x["separations_thousands"], x["net_thousands"]) == (h, q, l, s, h - s)


def test_the_source_and_the_page_are_named():
    r = run(real())
    assert "Bureau of Labor Statistics" in r["source"] and "Job Openings and Labor Turnover Survey" in r["source"] and "FRED" in r["source"]
    assert r["url"] == "https://fred.stlouisfed.org/series/JTSHIL"


def test_the_note_says_what_the_numbers_are_and_what_they_are_not():
    note = run(real())["note"]
    for phrase in ("Job Openings and Labor Turnover Survey", "seasonally adjusted", "hires", "quits", "layoffs and discharges", "total separations", "net", "worked out by subtraction and marked as such",
                   "preliminary and are revised later", "Smaller samples make industry figures noisier", "Plain checks:", "not a market signal or a forecast"):
        assert phrase in note, phrase


@pytest.mark.parametrize("days, fresh", [(105, "CURRENT"), (106, "OVERDUE")])
def test_a_month_turns_overdue_after_105_days_from_its_first_day(days, fresh):
    r = run(real(), LAST + timedelta(days=days))
    assert r["age_days"] == days and r["freshness"] == fresh


def test_the_age_is_worked_from_the_time_of_the_question_not_from_the_clock():
    assert run(real(), date(2026, 9, 2))["age_days"] == 1 and run(real(), date(2027, 1, 15))["freshness"] == "OVERDUE"


# ---------------------------------------------------------------- the structure of the record

@pytest.mark.parametrize("sid", IDS)
def test_series_that_end_in_different_months_are_refused_whichever_one_is_short(sid):
    d = world()
    del d[sid][LAST]
    refused(d, "the JOLTS flow series end in different months")


def test_a_series_with_a_hole_names_itself_and_the_first_one_in_table_order_is_named():
    for sid in IDS[1:]:
        d = world()
        del d[sid][mback(LAST, 40)]
        refused(d, f"the {NAME[sid]} series covers different months than nonfarm hires")
    d = world()
    del d["JTSHIL"][mback(LAST, 40)]
    refused(d, "the nonfarm quits series covers different months than nonfarm hires")


def test_the_hole_in_every_series_is_a_skipped_month():
    d = {sid: {m: v for m, v in s.items() if m != mback(LAST, 40)} for sid, s in world().items()}
    refused(d, f"the JOLTS flow months skip a month after {mlab(mback(LAST, 41))}")


def test_a_skipped_month_across_the_turn_of_the_year_is_found_too():
    d = {sid: {m: v for m, v in s.items() if m != date(2020, 1, 1)} for sid, s in world().items()}
    refused(d, "the JOLTS flow months skip a month after 2019-12")


def test_a_skipped_month_is_found_in_the_first_pair_of_months_and_in_the_last():
    first = {sid: {m: v for m, v in s.items() if m != mback(LAST, 178)} for sid, s in world().items()}
    refused(first, f"the JOLTS flow months skip a month after {mlab(mback(LAST, 179))}")
    last = {sid: {m: v for m, v in s.items() if m != mback(LAST, 1)} for sid, s in world().items()}
    refused(last, f"the JOLTS flow months skip a month after {mlab(mback(LAST, 2))}")
    refused({sid: {m: v for m, v in s.items() if m != mback(LAST, 0)} for sid, s in world(n=3).items()}, "the JOLTS flows cover 2 months, fewer than the 120 expected")


@pytest.mark.parametrize("bad", [date(2019, 5, 2), date(2019, 5, 31)])
def test_a_date_that_is_not_the_1st_is_refused(bad):
    d = world()
    for sid in IDS:
        d[sid][bad] = d[sid].pop(MAY)
    refused(d, "a JOLTS flow date is not the 1st of a month")


def test_fewer_than_120_months_are_refused_and_120_pass():
    refused(world(n=119), "the JOLTS flows cover 119 months, fewer than the 120 expected")
    assert run(world(n=120))["detail"]["months_checked"] == 120


def test_the_months_of_the_record_come_from_the_series_and_the_window_is_reported():
    r = run(world(n=150))
    assert r["detail"]["months_checked"] == 150 and r["detail"]["first_month"] == mlab(mback(LAST, 149)) and r["detail"]["last_month"] == "2026-09"


def test_a_series_with_an_extra_month_covers_different_months_too():
    d = world()
    d["JTS7000TSL"][date(2030, 1, 1)] = 1000.0
    refused(d, "the JOLTS flow series end in different months")
    d = world()
    d["JTS7000TSL"][date(2000, 1, 1)] = 1000.0
    refused(d, "the leisure and hospitality separations series covers different months than nonfarm hires")


# ---------------------------------------------------------------- the limits

EDGES = []
for _sid, (_lo, _hi) in LIMITS.items():
    for _edge, _out in ((_lo, _lo - 1.0), (_hi, _hi + 1.0)):
        EDGES.append((_sid, _edge, _out, f"{NAME[_sid]} of {num(_out)} thousand in 2026-09 is outside {num(_lo)} to {num(_hi)}"))


@pytest.mark.parametrize("sid, edge, outside, text", EDGES)
def test_each_limit_is_pinned_at_both_edges(sid, edge, outside, text):
    not_a_range_refusal(bump(world(), LAST, {sid: edge - world()[sid][LAST]}))
    refused(bump(world(), LAST, {sid: outside - world()[sid][LAST]}), text)


def test_the_limits_in_the_module_are_the_literals_of_this_file():
    assert J.LIMITS == LIMITS and list(J.SERIES) == list(IDS) and len(IDS) == 33


def test_a_range_is_checked_in_the_oldest_and_the_newest_month_not_only_in_the_middle():
    first, last = mback(LAST, 179), LAST
    for sid, (lo, hi) in LIMITS.items():
        for when in (first, last, mback(LAST, 90)):
            d = world()
            d[sid][when] = hi + 1.0
            with pytest.raises(ValueError, match=re.escape(f"{NAME[sid]} of {num(hi + 1.0)} thousand in {mlab(when)} is outside")):
                J.summarize(d, TODAY)


def test_the_numbers_in_a_refusal_are_written_with_thousands_separators_and_no_trailing_zero():
    refused(bump(world(), LAST, {"JTS1000HIL": 20_000.5 - 5000.0}), "private hires of 20,000.5 thousand in 2026-09 is outside 1,500 to 20,000")
    refused(bump(world(), LAST, {"JTSTSL": 32_001.0 - 5070.0}), "nonfarm separations of 32,001 thousand in 2026-09 is outside 1,900 to 32,000")


def test_ranges_are_checked_series_by_series_in_the_order_of_the_table_and_the_oldest_month_first():
    d = world()
    d["JTS7000TSL"][mback(LAST, 100)] = 50_000.0
    d["JTS2300HIL"][mback(LAST, 5)] = 5_000.0
    refused(d, f"construction hires of 5,000 thousand in {mlab(mback(LAST, 5))} is outside 100 to 1,500")
    d = world()
    d["JTS2300HIL"][mback(LAST, 5)] = 5_000.0
    d["JTS2300HIL"][mback(LAST, 100)] = 5_000.0
    refused(d, f"construction hires of 5,000 thousand in {mlab(mback(LAST, 100))} is outside 100 to 1,500")


def test_the_minimum_count_of_months_comes_before_the_ranges():
    d = world(n=119)
    d["JTSHIL"][LAST] = 99_999.0
    refused(d, "the JOLTS flows cover 119 months, fewer than the 120 expected")


# ---------------------------------------------------------------- the sums

SUMS = []
for _m in SECTOR_MEASURES:                         # a: nonfarm = private + government, one measure at a time (tolerance 1.5: three figures each rounded to a thousand)
    _whole = "JTS" + _m
    SUMS.append((f"a_{_m}", {_whole: 1.5}, {_whole: 1.6}, f"nonfarm {MEASURE[_m]} differ from private plus government by 1.6 thousand in 2026-09, over 1.5"))
for _k in ("nf", "pr", "gv"):                      # b: separations = quits + layoffs + other, one total at a time (tolerance 2.0: four figures)
    _p = PREFIX[_k]
    if _k == "nf":                                 # the nonfarm total also has to equal private + government, so those two move by half each
        _ok, _bad = {_p + "TSL": 2.0, "JTS1000TSL": 1.0, "JTS9000TSL": 1.0}, {_p + "TSL": 2.1, "JTS1000TSL": 1.05, "JTS9000TSL": 1.05}
    else:                                          # a private or government total moved alone would put the nonfarm sum out: the nonfarm total moves 1.5 with it (inside both of its tolerances)
        _ok, _bad = {_p + "TSL": 2.0, "JTSTSL": 1.5}, {_p + "TSL": 2.1, "JTSTSL": 1.5}
    SUMS.append((f"b_{_k}", _ok, _bad, f"{GNAME[_k]} separations differ from quits plus layoffs plus other by 2.1 thousand in 2026-09, over 2"))
WHENS = [mback(LAST, 179), mback(LAST, 90), LAST]


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("when", WHENS)
@pytest.mark.parametrize("name, ok_offsets, bad_offsets, text", SUMS)
def test_each_sum_holds_exactly_at_its_tolerance_and_is_refused_just_over(name, ok_offsets, bad_offsets, text, when, sign):
    assert run(bump(world(), when, {s: sign * v for s, v in ok_offsets.items()}))["available"] is True
    with pytest.raises(ValueError) as e:
        J.summarize(bump(world(), when, {s: sign * v for s, v in bad_offsets.items()}), TODAY)
    assert str(e.value) == text.replace("2026-09", mlab(when))


def test_the_sums_are_checked_in_table_order_and_the_oldest_month_first():
    d = bump(world(), LAST, {"JTSQUL": 40.0})                                     # the quits sum fails (and the nonfarm separations one), but the hires sum is first in the table
    bump(d, mback(LAST, 30), {"JTSHIL": 40.0})
    refused(d, f"nonfarm hires differ from private plus government by 40 thousand in {mlab(mback(LAST, 30))}, over 1.5")
    d = bump(world(), LAST, {"JTSTSL": 40.0})
    bump(d, mback(LAST, 7), {"JTSTSL": 40.0})
    refused(d, f"nonfarm separations differ from private plus government by 40 thousand in {mlab(mback(LAST, 7))}, over 1.5")


def test_the_separation_sums_come_after_the_total_sums_and_in_the_order_nonfarm_private_government():
    refused(bump(world(), LAST, {"JTSQUL": 3.0}), "nonfarm quits differ from private plus government by 3 thousand in 2026-09, over 1.5")      # fails its total sum and the nonfarm separation sum: the total sum speaks
    d = bump(world(), LAST, {"JTSTSL": 3.0, "JTS1000TSL": 3.0})                  # nonfarm and private are both 3 off their own parts; the total sum holds
    refused(d, "nonfarm separations differ from quits plus layoffs plus other by 3 thousand in 2026-09, over 2")
    d = bump(world(), LAST, {"JTS1000TSL": 3.0, "JTS9000TSL": -3.0})             # private 3 high and government 3 low: nonfarm still holds, and private speaks before government
    refused(d, "private separations differ from quits plus layoffs plus other by 3 thousand in 2026-09, over 2")
    d = bump(world(), LAST, {"JTS9000TSL": 3.0, "JTSTSL": 2.0})
    refused(d, "government separations differ from quits plus layoffs plus other by 3 thousand in 2026-09, over 2")


def test_a_separation_sum_is_checked_oldest_month_first_and_its_gap_counts_for_the_largest():
    d = world()
    for when in (mback(LAST, 50), mback(LAST, 10)):                                # nonfarm and private both 3 off their own parts in two months: the oldest is named
        bump(d, when, {"JTSTSL": 3.0, "JTS1000TSL": 3.0})
    refused(d, f"nonfarm separations differ from quits plus layoffs plus other by 3 thousand in {mlab(mback(LAST, 50))}, over 2")
    d = bump(world(), LAST, {"JTS1000TSL": 2.0, "JTSTSL": 1.5})                    # private 2.0 off its parts, the largest gap of the eight sums (the total sums hold within 0.5)
    assert run(d)["detail"]["largest_sum_gap"] == 2.0


def test_a_gap_is_printed_with_g_so_a_whole_number_has_no_decimals_and_a_fraction_keeps_its_digits():
    refused(bump(world(), LAST, {"JTSHIL": 3.0}), "nonfarm hires differ from private plus government by 3 thousand in 2026-09, over 1.5")
    refused(bump(world(), LAST, {"JTSHIL": 1.75}), "nonfarm hires differ from private plus government by 1.75 thousand in 2026-09, over 1.5")


def test_a_series_swapped_for_another_is_caught_in_the_real_record():
    d = real()
    d["JTS1000QUL"] = dict(d["JTS1000HIL"])                                       # private hires in the place of private quits: inside the range of the series, but the sums catch it
    refused(d, "nonfarm quits differ from private plus government by 2345 thousand in 2000-12, over 1.5")


def test_the_largest_gap_is_the_largest_not_the_first_or_the_last():
    d = bump(world(), mback(LAST, 100), {"JTSHIL": 1.25})
    bump(d, mback(LAST, 150), {"JTS9000HIL": 1.0})
    bump(d, LAST, {"JTSOSL": 1.0, "JTSTSL": 1.0})
    assert run(d)["detail"]["largest_sum_gap"] == 1.25
    assert run(world())["detail"]["largest_sum_gap"] == 0.0


def test_the_largest_gap_is_reported_to_three_decimals():
    assert run(bump(world(), LAST, {"JTSHIL": 1.0 + 1 / 3}))["detail"]["largest_sum_gap"] == 1.333


# ---------------------------------------------------------------- quits inside separations, the six industries inside private

BIG_PRIVATE = (5000.0, 4500.0, 1500.0, 250.0)       # private quits so large that no industry's quits can use up all that is left of private, whatever these tests do to them


@pytest.mark.parametrize("k", INDUSTRIES)
def test_an_industry_quits_may_exceed_its_separations_by_the_rounding_but_not_more(k):
    sid_q, sid_s = PREFIX[k] + "QUL", PREFIX[k] + "TSL"
    d = world(pr=BIG_PRIVATE)
    d[sid_q][LAST] = d[sid_s][LAST] + 1.0
    assert run(d)["available"] is True
    d[sid_q][LAST] = d[sid_s][LAST] + 1.25
    refused(d, f"{GNAME[k]} quits exceed its separations by 1.25 thousand in 2026-09, over 1")


def test_the_quits_inside_separations_check_looks_at_every_month_and_at_the_oldest_first():
    d = world()
    d["JTS3000QUL"][mback(LAST, 179)] = d["JTS3000TSL"][mback(LAST, 179)] + 5.0
    d["JTS3000QUL"][mback(LAST, 20)] = d["JTS3000TSL"][mback(LAST, 20)] + 6.0
    refused(d, f"manufacturing quits exceed its separations by 5 thousand in {mlab(mback(LAST, 179))}, over 1")


def test_the_quits_check_is_made_in_table_order_and_after_the_sums():
    d = world()
    d["JTS7000QUL"][LAST] = d["JTS7000TSL"][LAST] + 5.0
    d["JTS2300QUL"][LAST] = d["JTS2300TSL"][LAST] + 5.0
    refused(d, "construction quits exceed its separations by 5 thousand in 2026-09, over 1")
    bump(d, LAST, {"JTSHIL": 40.0})
    refused(d, "nonfarm hires differ from private plus government by 40 thousand in 2026-09, over 1.5")


REST = (("HIL", 0, 553.5, "JTS7000HIL"), ("QUL", 1, 173.5, "JTS7000QUL"), ("TSL", 2, 353.5, "JTS2300TSL"))


@pytest.mark.parametrize("m, i, up, sid", REST)
def test_the_six_industries_may_exceed_private_by_the_rounding_of_seven_figures_but_not_more(m, i, up, sid):
    d = bump(world(), LAST, {sid: up})                                            # what is left of private is then exactly -3.5
    assert run(d)["available"] is True
    d = bump(world(), LAST, {sid: up + 0.25})
    refused(d, f"the six industries add up to more than private {MEASURE[m]} by 3.75 thousand in 2026-09, over 3.5")


def test_the_six_industries_are_checked_against_private_in_every_month_and_the_oldest_first():
    d = bump(world(), mback(LAST, 30), {"JTS7000HIL": 600.0})
    bump(d, mback(LAST, 10), {"JTS7000HIL": 700.0})
    refused(d, f"the six industries add up to more than private hires by 50 thousand in {mlab(mback(LAST, 30))}, over 3.5")


def test_the_six_industries_are_checked_in_the_order_hires_then_quits_then_separations():
    d = bump(world(), LAST, {"JTS7000HIL": 600.0, "JTS2300TSL": 400.0})            # hires 50 over private and separations 50 over: hires speak first
    refused(d, "the six industries add up to more than private hires by 50 thousand in 2026-09, over 3.5")
    d = bump(world(), LAST, {"JTS2300TSL": 400.0})
    refused(d, "the six industries add up to more than private separations by 50 thousand in 2026-09, over 3.5")


def test_the_six_industries_are_checked_against_private_in_the_oldest_month_too():
    d = bump(world(), mback(LAST, 179), {"JTS7000HIL": 600.0})
    refused(d, f"the six industries add up to more than private hires by 50 thousand in {mlab(mback(LAST, 179))}, over 3.5")


def test_the_rest_of_private_is_the_smallest_over_the_three_measures_and_every_month():
    d = world()
    assert run(d)["detail"]["smallest_rest_of_private"] == 170.0 and run(d)["detail"]["closest_part_margin"] == 120.0
    d = bump(d, mback(LAST, 60), {"JTS7000QUL": 100.0})                           # quits left over: 170 - 100
    assert run(d)["detail"]["smallest_rest_of_private"] == 70.0
    assert run(bump(world(), LAST, {"JTS7000HIL": 400.0}))["detail"]["smallest_rest_of_private"] == 150.0
    assert run(bump(world(), LAST, {"JTS7000HIL": 400.125}))["detail"]["smallest_rest_of_private"] == 149.875      # three decimals are kept (149.875 rounds to 149.88 at two)


def test_the_closest_margin_of_quits_to_separations_is_the_smallest_over_the_six_industries_and_every_month():
    d = world(pr=BIG_PRIVATE)
    d["JTS6000QUL"][mback(LAST, 70)] = d["JTS6000TSL"][mback(LAST, 70)] - 7.0
    assert run(d)["detail"]["closest_part_margin"] == 7.0
    d["JTS2300QUL"][LAST] = d["JTS2300TSL"][LAST] - 3.5
    assert run(d)["detail"]["closest_part_margin"] == 3.5
    d["JTS3000QUL"][mback(LAST, 33)] = d["JTS3000TSL"][mback(LAST, 33)] - 3.125         # three decimals are kept (binary exact: 3.125 rounds to 3.12 at two)
    assert run(d)["detail"]["closest_part_margin"] == 3.125


# ---------------------------------------------------------------- what the card shows, worked in worlds where every figure differs


def trend(i):
    """The primaries `i` months before the newest month: each of the four kinds of figure grows at its own rate, so no two measures change by the same percentage."""
    f = [1 + 0.001 * (30 - i) * (j + 1) for j in range(4)]
    return {k: tuple(v * f[j] for j, v in enumerate(vals)) for k, vals in BASE.items()}


def test_the_month_and_year_changes_use_the_right_months_and_are_rounded():
    d = world_by(trend)
    r = run(d)
    now, ago = build(trend(0)), build(trend(12))
    t = r["total"]
    for key, sid in (("hires", "JTSHIL"), ("quits", "JTSQUL"), ("layoffs", "JTSLDL"), ("separations", "JTSTSL")):
        assert t[f"{key}_thousands"] == now[sid] and t[f"{key}_change_year_pct"] == round(100.0 * (now[sid] - ago[sid]) / ago[sid], 1)
    assert t["other_thousands"] == now["JTSOSL"] and t["net_thousands"] == now["JTSHIL"] - now["JTSTSL"] and t["quits_share_pct"] == round(100.0 * now["JTSQUL"] / now["JTSTSL"], 1)
    pr, gv = r["sectors"]
    for row, prefix in ((pr, "JTS1000"), (gv, "JTS9000")):
        assert row["hires_change_year_pct"] == round(100.0 * (now[prefix + "HIL"] - ago[prefix + "HIL"]) / ago[prefix + "HIL"], 1)
        assert row["quits_change_year_pct"] == round(100.0 * (now[prefix + "QUL"] - ago[prefix + "QUL"]) / ago[prefix + "QUL"], 1)
        assert row["layoffs_thousands"] == now[prefix + "LDL"] and row["other_thousands"] == now[prefix + "OSL"] and row["net_thousands"] == now[prefix + "HIL"] - now[prefix + "TSL"]
    assert len({t["hires_change_year_pct"], t["quits_change_year_pct"], t["layoffs_change_year_pct"], t["separations_change_year_pct"]}) == 4


def test_the_year_ago_figure_is_twelve_months_back_not_eleven_or_thirteen():
    d = world_by(trend)
    r = run(d)
    for back in (11, 13):
        wrong = build(trend(back))
        assert r["total"]["hires_change_year_pct"] != round(100.0 * (build(trend(0))["JTSHIL"] - wrong["JTSHIL"]) / wrong["JTSHIL"], 1)


def test_the_industries_are_sorted_by_hires_then_by_label_and_the_rest_of_private_comes_last_by_subtraction():
    d = world()
    r = run(d)
    assert [x["key"] for x in r["industries"]] == ["trade_transport", "leisure", "professional", "education_health", "construction", "manufacturing", "other_private"]
    d = world(co=(300.0, 200.0, 340.0))                                           # construction and manufacturing now tie on hires: the label decides
    assert [x["key"] for x in run(d)["industries"]][-3:] == ["construction", "manufacturing", "other_private"]
    d = world(co=(300.0, 200.0, 340.0), ma=(300.0, 190.0, 310.0), pb=(300.0, 450.0, 920.0))
    assert [x["key"] for x in run(d)["industries"]][2:] == ["education_health", "construction", "manufacturing", "professional", "other_private"]
    d = world(pb=(800.0, 450.0, 920.0))                                           # professional ties education and health at 800: the label decides, not the order of the table ("Private" sorts before "Professional" and the table has professional first)
    assert [x["key"] for x in run(d)["industries"]][2:4] == ["education_health", "professional"]
    rest = run(world())["industries"][-1]
    assert rest["derived"] is True and rest["hires_thousands"] == 5000.0 - 4450.0 and rest["quits_thousands"] == 3000.0 - 2830.0 and rest["separations_thousands"] == 4750.0 - 4400.0
    assert all(x["derived"] is False for x in run(world())["industries"][:-1])


def test_a_change_that_rounds_to_zero_from_below_is_zero_and_not_negative_zero():
    d = world_by(lambda i: BASE if i != 12 else {**BASE, "pr": (5000.0 + 0.0001, 3000.0, 1500.0, 250.0)})
    v = run(d)["sectors"][0]["hires_change_year_pct"]
    assert v == 0.0 and str(v) == "0.0" and json.dumps(v) == "0.0"


def test_the_range_counts_only_strictly_lower_months_and_names_the_earliest_of_equal_extremes():
    d = world_by(lambda i: {**BASE, "pr": (5000.0 + (i % 7) * 10, 3000.0, 1500.0, 250.0)})
    rng = run(d)["total"]["hires_range"]
    vals = [5300.0 + (i % 7) * 10 for i in range(119, -1, -1)]
    assert rng["months"] == 120 and rng["lowest"]["value"] == 5300.0 and rng["highest"]["value"] == 5360.0
    assert rng["share_lower_pct"] == round(100 * sum(1 for v in vals if v < vals[-1]) / 120)
    assert rng["lowest"]["month"] == mlab(mback(LAST, 119 - vals.index(5300.0))) and rng["first"] == mlab(mback(LAST, 119))


def test_the_net_is_hires_minus_separations_and_the_quits_share_is_quits_over_separations_in_one_decimal():
    d = world(pr=(5000.0, 3000.0, 1500.0, 250.0), gv=(300.0, 180.0, 80.0, 60.0), lh=(1000.0, 700.0, 1030.0))
    row = [x for x in run(d)["industries"] if x["key"] == "leisure"][0]
    assert row["net_thousands"] == -30.0 and row["quits_share_pct"] == round(100 * 700 / 1030, 1) == 68.0


def test_a_share_over_nothing_is_none_not_a_division_by_zero():
    d = world(pr=(5000.0, 3000.0, 1150.0, 250.0))                                  # private separations 4,400: the six industries use all of them
    rest = run(d)["industries"][-1]
    assert rest["separations_thousands"] == 0.0 and rest["quits_share_pct"] is None and rest["net_thousands"] == 550.0
    rest = run(world(pr=(5000.0, 3000.0, 1150.5, 250.0)))["industries"][-1]          # half a thousand left: any figure above nothing is a share
    assert rest["separations_thousands"] == 0.5 and rest["quits_share_pct"] == 34000.0


def test_the_six_recent_months_have_their_own_figures_and_the_oldest_comes_first():
    d = world_by(trend)
    r = run(d)
    assert [x["month"] for x in r["recent"]] == [mlab(mback(LAST, i)) for i in range(5, -1, -1)]
    for x, i in zip(r["recent"], range(5, -1, -1)):
        one = build(trend(i))
        assert x["hires_thousands"] == one["JTSHIL"] and x["layoffs_thousands"] == one["JTSLDL"] and x["net_thousands"] == one["JTSHIL"] - one["JTSTSL"]


def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    texts = [t for _s, _e, _o, t in EDGES]
    texts += [f"nonfarm {MEASURE[m]} differ from private plus government by 1234567.5 thousand in 2026-09, over 1.5" for m in SECTOR_MEASURES]
    texts += [f"{GNAME[k]} separations differ from quits plus layoffs plus other by 1234567.5 thousand in 2026-09, over 2" for k in ("nf", "pr", "gv")]
    texts += [f"the {NAME[s]} series covers different months than nonfarm hires" for s in IDS[1:]]
    texts += [f"{GNAME[k]} quits exceed its separations by 1234567.5 thousand in 2026-09, over 1" for k in INDUSTRIES]
    texts += [f"the six industries add up to more than private {MEASURE[m]} by 1234567.5 thousand in 2026-09, over 3.5" for m in ("HIL", "QUL", "TSL")]
    texts += ["the JOLTS flows cover 119 months, fewer than the 120 expected", "the JOLTS flow months skip a month after 2024-12", "the JOLTS flow series end in different months", "a JOLTS flow date is not the 1st of a month"]
    for text in texts:
        assert len(text) <= 110, (len(text), text)
        assert fail_reason(ValueError(text)) == f"the data failed a check: {text}"


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_33_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = J.JoltsFlows(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["total"]["hires_thousands"] == 5402.0 and n["n"] == 33 and r["demo"] is False and r["as_of"] == NOW.isoformat()
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 33


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(J.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = J.JoltsFlows(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 33
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 33                                                              # still the failure from the cache
    clock["t"] += 1
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 66      # exactly two minutes on it asks again
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 66                                                              # one second short of six hours: kept
    clock["t"] += 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 99                                                              # exactly six hours on: asked again


def test_without_a_time_the_question_is_asked_at_the_present_moment_in_utc():
    r = asyncio.run(J.JoltsFlows(client=_client(_handler)).overview())
    asked = datetime.fromisoformat(r["as_of"])
    assert asked.tzinfo is not None and asked.utcoffset() == timedelta(0)
    assert abs((datetime.now(timezone.utc) - asked).total_seconds()) < 60


def test_the_age_in_an_answer_is_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(J.JoltsFlows(client=_client(_handler)).overview(datetime(2027, 1, 15, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 136 and r["freshness"] == "OVERDUE"                      # a date that is not today's, so that the clock cannot give the same answer


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = J.JoltsFlows(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(J.JoltsFlows(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US hires, quits and layoffs by industry could not be read right now (the server had an error, HTTP 503)" and "total" not in r and "recent" not in r
    r = asyncio.run(J.JoltsFlows(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]                      # anything but 200 is a failure


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == "JTS7000TSL" else _handler(req)

    r = asyncio.run(J.JoltsFlows(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "total" not in r and "industries" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    def answer(replace):
        bad = dict(F)
        for sid, (old, new) in replace.items():
            assert old in F[sid]
            bad[sid] = F[sid].replace(old, new)
        return asyncio.run(J.JoltsFlows(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))

    r = answer({"JTS1000HIL": ("2026-09-01,5078", "2026-09-01,50780")})               # a decimal slip beyond the range
    assert r["available"] is False and r["reason"] == "US hires, quits and layoffs by industry could not be read right now (the data failed a check: private hires of 50,780 thousand in 2026-09 is outside 1,500 to 20,000)" and "total" not in r
    r = answer({"JTSQUL": ("2026-09-01,3365", "2026-09-01,3465")})                    # a digit slip that stays inside every range: only the sum finds it
    assert r["available"] is False and r["reason"] == "US hires, quits and layoffs by industry could not be read right now (the data failed a check: nonfarm quits differ from private plus government by 100 thousand in 2026-09, over 1.5)"
    r = answer({"JTS7000QUL": ("2026-09-01,752", "2026-09-01,x")})
    assert r["available"] is False and "a JTS7000QUL row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(J.JoltsFlows(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US hires, quits and layoffs by industry could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("JTSHIL")

    monkeypatch.setattr(J, "summarize", boom)
    r = asyncio.run(J.JoltsFlows(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US hires, quits and layoffs by industry could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(J.JoltsFlows(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US hires, quits and layoffs by industry are not shown because made-up values would look real." and "total" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/jolts-flows")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_card_is_refreshed_with_the_other_macro_sources():
    jobs = (Path(__file__).parent.parent / "atlas_api" / "sched" / "jobs.py").read_text(encoding="utf-8")
    app = (Path(__file__).parent.parent / "atlas_api" / "app.py").read_text(encoding="utf-8")
    assert '"jolts_flows"' in jobs and '"jolts_flows": jolts_flows' in app and "jolts_flows = JoltsFlows(demo=demo)" in app


def test_each_request_asks_for_one_series_from_2000_with_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(J.JoltsFlows(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)             # never a combined request: FRED applies one start date to the first series only
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert {req.url.params["cosd"] for req in seen} == {"2000-12-01"}


def test_no_more_than_eight_requests_are_open_at_once():
    state = {"open": 0, "most": 0}

    async def slow(req):
        state["open"] += 1
        state["most"] = max(state["most"], state["open"])
        await asyncio.sleep(0.01)
        state["open"] -= 1
        return _handler(req)

    asyncio.run(J.JoltsFlows(client=_client(slow)).overview(NOW))
    assert state["most"] == 8


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
    r = asyncio.run(J.JoltsFlows().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(J.JoltsFlows(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_module_says_why_each_series_is_asked_for_alone_and_what_it_does_not_check():
    doc = J.__doc__
    assert "ALONE" in doc and "NOT checked" in doc and "rounded to a thousand" in doc and "310 months" in doc
