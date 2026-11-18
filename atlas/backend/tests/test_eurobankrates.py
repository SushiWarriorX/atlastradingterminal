"""Euro-area bank interest rates (ECB Data Portal, MIR dataflow: what euro-area banks charge on new loans and pay on new deposits, monthly): parsed from real responses (fetched 2026-11-18 11:3x UTC: the provider's four requests with 125 months each; the whole record, 285 months from 2003-01, was read to set the checks, see the module's docstring)."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import eurobankrates as S
from atlas_api.app import create_app
from atlas_api.failreason import fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_bank_rates.json").read_text())
TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)                                                  # the newest month of the real record
BLOCKS = ("firms", "house", "consumer", "other", "household_term", "firms_term")
SINGLES = ("household_overnight", "firms_overnight", "firms_cost", "house_cost")
LOANS = BLOCKS[:4]
DEPOSITS = ("household_overnight", "household_term", "firms_overnight", "firms_term")
COSTS = ("firms_cost", "house_cost")
OVERNIGHT = ("household_overnight", "firms_overnight")
PARTS = ("A", "F", "K")
IDS = tuple(f"{b}.{p}.{k}" for b in BLOCKS for p in PARTS for k in ("rate", "volume")) + tuple(f"{s}.rate" for s in SINGLES)
RATES = tuple(i for i in IDS if i.endswith(".rate"))
VOLUMES = tuple(i for i in IDS if i.endswith(".volume"))
SHOWN = ("firms.A.rate", "house.A.rate", "consumer.A.rate", "other.A.rate", "household_term.A.rate", "firms_term.A.rate", "household_overnight.rate", "firms_overnight.rate", "firms_cost.rate", "house_cost.rate")
RATE_U, VOLUME_U = ("PCPA", "0"), ("EUR", "6")
UNITS = {sid: VOLUME_U if sid.endswith(".volume") else RATE_U for sid in IDS}
LABEL = {"firms": "loans to firms", "house": "loans for house purchase", "consumer": "consumer credit", "other": "other loans to households",
         "household_term": "household term deposits", "firms_term": "firms' term deposits", "household_overnight": "household overnight deposits",
         "firms_overnight": "firms' overnight deposits", "firms_cost": "the ECB's cost of borrowing for firms", "house_cost": "the ECB's cost of borrowing for house purchase"}
WORDS = {"A": "all new business", "F": "floating or up to 1 year fixed", "K": "over 1 year fixed"}
NAMES = {**{f"{b}.{p}.rate": f"the rate on {LABEL[b]} ({WORDS[p]})" for b in BLOCKS for p in PARTS}, **{f"{b}.{p}.volume": f"the new business volume of {LABEL[b]} ({WORDS[p]})" for b in BLOCKS for p in PARTS},
         "household_overnight.rate": "the rate on household overnight deposits", "firms_overnight.rate": "the rate on firms' overnight deposits",
         "firms_cost.rate": "the ECB's cost of borrowing for firms", "house_cost.rate": "the ECB's cost of borrowing for house purchase"}
# the limits set from the real record, spelled out here so that a changed limit fails a test instead of moving the test with it
RATE_LIMITS = (-1.0, 12.0)
VOLUME_LIMITS = (100.0, 1000000.0)
TOL = 2 ** -6
# a world's six blocks: (volume with a floating or up to 1 year fixed, volume over 1 year fixed, their two rates); the rate on all of it is the volume-weighted average, exact in binary
W = {"firms": (3000.0, 1000.0, 3.0, 7.0), "house": (1000.0, 3000.0, 2.0, 4.0), "consumer": (1000.0, 3000.0, 5.0, 9.0), "other": (2000.0, 2000.0, 3.0, 5.0),
     "household_term": (3000.0, 1000.0, 2.0, 6.0), "firms_term": (1000.0, 3000.0, 2.0, 3.0)}
SINGLE = {"household_overnight": 0.25, "firms_overnight": 0.5, "firms_cost": 4.5, "house_cost": 3.25}       # the composites sit 0.5 above and 0.25 below the rates on all new loans of firms (4.0) and for house purchase (3.5)
A_RATE = {"firms": 4.0, "house": 3.5, "consumer": 8.0, "other": 4.0, "household_term": 3.0, "firms_term": 2.75}


def _i(d):
    return d.year * 12 + d.month - 1


def _d(i):
    return date(i // 12, i % 12 + 1, 1)


def _lab(d):
    return f"{d.year}-{d.month:02d}"


def _back(d, n):
    return _d(_i(d) - n)


def _world(last=LAST, extra=0, status=None):
    """Forty series for the 36 months (plus `extra` older ones) ending on `last`, where every check passes by construction: six blocks whose volumes add up and whose rate on all of it is exactly the volume-weighted average of the two parts' rates, two overnight rates and two composites within a point of their totals; every value constant."""
    n = 36 + extra
    months = [_d(_i(last) - n + 1 + k) for k in range(n)]
    v = {}
    for b, (vf, vk, rf, rk) in W.items():
        for p, vol, rate in (("A", vf + vk, (vf * rf + vk * rk) / (vf + vk)), ("F", vf, rf), ("K", vk, rk)):
            v[f"{b}.{p}.volume"] = {m: vol for m in months}
            v[f"{b}.{p}.rate"] = {m: rate for m in months}
    for s, r in SINGLE.items():
        v[f"{s}.rate"] = {m: r for m in months}
    return v, dict(UNITS), {} if status is None else status


def _real():
    v = {sid: {date(int(m[:4]), int(m[5:]), 1): x for m, x in zip(d["months"], d["values"])} for sid, d in F["series"].items()}
    return v, {sid: tuple(d["unit"]) for sid, d in F["series"].items()}, {sid: d["status"][-1] for sid, d in F["series"].items()}


def _run(world, today=TODAY):
    return S.summarize(*world, today)


def _err(world, today=TODAY):
    """The refusal's text, or None when the world passes every check."""
    try:
        _run(world, today)
    except ValueError as e:
        return str(e)
    return None


def _shift(w, e, delta, back=0):
    """Add `delta` points to the rates of `e` (a block's three rates, or the one rate) in the month `back` before the newest, and to the composite that sits beside the total (firms, house purchase), so that no other check is disturbed."""
    d = _back(LAST, back)
    sids = [f"{e}.{p}.rate" for p in PARTS] if e in BLOCKS else [f"{e}.rate"]
    if e in ("firms", "house"):
        sids.append(f"{e}_cost.rate")
    for sid in sids:
        w[0][sid][d] += delta
    return d


def _moved(sid, ch, d, limit):
    return f"{NAMES[sid]} moved by {ch:+.2f} points in {_lab(d)}, more than {limit:g}"


def _sum_msg(b, d, off):
    return f"the new business volume of {LABEL[b]} is not the sum of its floating-rate and its longer-fixation parts in {_lab(d)} (off by {off:+,.2f} million euro)"


def _rate_msg(b, d, gap):
    return f"the rate on new {LABEL[b]} in {_lab(d)} is {abs(gap):.3f} points away from the average of its two parts weighted by their volumes, more than 0.015625"


def _cost_msg(c, total, d, gap):
    return f"{NAMES[c + '.rate']} is {abs(gap):.2f} points away from the rate on {LABEL[total]} in {_lab(d)}, more than 1"


def test_the_real_latest_rates_changes_volumes_ten_year_ranges_recent_months_and_checks_by_hand():
    r = _run(_real())
    assert r["available"] is True and r["month"] == "2026-09" and r["date"] == "2026-09-01" and r["age_days"] == 49 and r["freshness"] == "CURRENT" and r["provisional"] is True    # 2026-09-30 to 2026-11-18 is 49 days
    window = lambda lo, lo_m, hi, hi_m, share: {"months": 120, "lowest": {"pct": lo, "month": lo_m}, "highest": {"pct": hi, "month": hi_m}, "share_lower_pct": share}
    assert r["loans"] == [
        {"id": "firms", "label": "loans to firms", "rate_pct": 3.79, "change_month_points": 0.16, "change_year_points": 0.41, "window": window(1.22, "2021-03", 5.25, "2023-10", 78), "volume_millions": 306963.0},
        {"id": "house", "label": "loans for house purchase", "rate_pct": 3.62, "change_month_points": 0.02, "change_year_points": 0.3, "window": window(1.3, "2021-06", 4.06, "2023-11", 86), "volume_millions": 75811.0},
        {"id": "consumer", "label": "consumer credit", "rate_pct": 7.82, "change_month_points": -0.12, "change_year_points": 0.42, "window": window(5.05, "2020-06", 8.01, "2024-01", 91), "volume_millions": 29391.0},
        {"id": "other", "label": "other loans to households", "rate_pct": 4.38, "change_month_points": -0.01, "change_year_points": 0.3, "window": window(1.89, "2021-12", 5.56, "2023-10", 78), "volume_millions": 13395.0}]
    assert r["deposits"] == [
        {"id": "household_overnight", "label": "household overnight deposits", "rate_pct": 0.3, "change_month_points": 0.01, "change_year_points": 0.05, "window": window(0.0, "2022-05", 0.39, "2024-01", 82), "volume_millions": None},
        {"id": "household_term", "label": "household term deposits", "rate_pct": 2.37, "change_month_points": 0.19, "change_year_points": 0.59, "window": window(0.21, "2021-06", 3.32, "2023-11", 82), "volume_millions": 159931.0},
        {"id": "firms_overnight", "label": "firms' overnight deposits", "rate_pct": 0.68, "change_month_points": 0.07, "change_year_points": 0.16, "window": window(-0.06, "2022-03", 0.91, "2024-03", 84), "volume_millions": None},
        {"id": "firms_term", "label": "firms' term deposits", "rate_pct": 2.48, "change_month_points": 0.23, "change_year_points": 0.57, "window": window(-0.35, "2021-08", 3.72, "2023-11", 79), "volume_millions": 288972.0}]
    assert r["costs"] == [
        {"id": "firms_cost", "label": "the ECB's cost of borrowing for firms", "rate_pct": 3.9, "change_month_points": 0.13, "change_year_points": 0.4, "window": window(1.36, "2021-12", 5.28, "2023-10", 78), "volume_millions": None},
        {"id": "house_cost", "label": "the ECB's cost of borrowing for house purchase", "rate_pct": 3.62, "change_month_points": 0.02, "change_year_points": 0.31, "window": window(1.3, "2021-09", 4.03, "2023-11", 86), "volume_millions": None}]
    assert [(x["month"], x["date"], x["firms_cost_pct"], x["house_cost_pct"]) for x in r["recent"]] == [
        ("2026-09", "2026-09-01", 3.9, 3.62), ("2026-08", "2026-08-01", 3.77, 3.6), ("2026-07", "2026-07-01", 3.8, 3.54), ("2026-06", "2026-06-01", 3.79, 3.51), ("2026-05", "2026-05-01", 3.63, 3.48), ("2026-04", "2026-04-01", 3.62, 3.44)]
    assert r["detail"] == {"months_checked": 36, "sums_checked": 216, "rate_months_checked": 24, "rates_checked": 144, "largest_sum_gap_millions": -0.01, "largest_sum_gap_month": "2024-06", "largest_sum_gap_series": "firms' term deposits",
                           "largest_rate_gap_points": 0.009, "largest_rate_gap_month": "2026-06", "largest_rate_gap_series": "household term deposits"}
    assert r["checks"] == {"units_ok": True, "months_in_a_row": True, "range_ok": True, "monthly_move_ok": True, "volume_sums_ok": True, "rates_follow_the_volumes_ok": True, "cost_of_borrowing_ok": True}
    assert r["source"].startswith("European Central Bank") and r["url"] == "https://data-api.ecb.europa.eu/service/data/MIR/M.U2.B.A2I.AM.R.A.2240.EUR.N"
    assert "not a market signal or a forecast" in r["note"] and "NEW loans and pay on NEW deposits" in r["note"] and "Plain checks: the units are the ones assumed and no month is missing" in r["note"] and "The newest month is provisional and is revised later" in r["note"]


def test_the_real_record_by_plain_python_outside_the_module():
    s = F["series"]
    assert all(d["months"][-1] == "2026-09" and len(d["months"]) == 125 and d["months"][0] == "2016-05" for d in s.values()) and set(map(tuple, (d["unit"] for d in s.values()))) == {RATE_U, VOLUME_U}
    for sid, now, m1, m12, lower, lo, lo_m, hi, hi_m in (
            ("firms.A.rate", 3.79, 3.63, 3.38, 93, 1.22, "2021-03", 5.25, "2023-10"), ("house.A.rate", 3.62, 3.6, 3.32, 103, 1.3, "2021-06", 4.06, "2023-11"), ("consumer.A.rate", 7.82, 7.94, 7.4, 109, 5.05, "2020-06", 8.01, "2024-01"),
            ("other.A.rate", 4.38, 4.39, 4.08, 94, 1.89, "2021-12", 5.56, "2023-10"), ("household_overnight.rate", 0.3, 0.29, 0.25, 99, 0.0, "2022-05", 0.39, "2024-01"), ("household_term.A.rate", 2.37, 2.18, 1.78, 99, 0.21, "2021-06", 3.32, "2023-11"),
            ("firms_overnight.rate", 0.68, 0.61, 0.52, 101, -0.06, "2022-03", 0.91, "2024-03"), ("firms_term.A.rate", 2.48, 2.25, 1.91, 95, -0.35, "2021-08", 3.72, "2023-11"),
            ("firms_cost.rate", 3.9, 3.77, 3.5, 94, 1.36, "2021-12", 5.28, "2023-10"), ("house_cost.rate", 3.62, 3.6, 3.31, 103, 1.3, "2021-09", 4.03, "2023-11")):
        m, x = s[sid]["months"], s[sid]["values"]
        ten, ten_m = x[-120:], m[-120:]
        assert (x[-1], x[-2], x[-13]) == (now, m1, m12) and ten_m[0] == "2016-10"                                                  # the newest value, a month and a year before it
        assert sum(1 for y in ten if y < now) == lower                                                                              # 93 of 120 is 77.5%, shown as 78 (the even one); 103 of 120 is 85.8, shown as 86
        assert (min(ten), ten_m[ten.index(min(ten))], max(ten), ten_m[ten.index(max(ten))]) == (lo, lo_m, hi, hi_m)
    last = lambda sid: s[sid]["values"][-1]
    for b, vols, rates in (("firms", (306962.54, 261162.27, 45800.27), (3.79, 3.71, 4.25)), ("house", (75811.41, 12347.35, 63464.07), (3.62, 3.89, 3.57)), ("consumer", (29390.97, 2712.77, 26678.2), (7.82, 7.33, 7.86)),
                           ("other", (13395.24, 7424.33, 5970.91), (4.38, 4.18, 4.63)), ("household_term", (159930.9, 141535.1, 18395.81), (2.37, 2.33, 2.67)), ("firms_term", (288971.78, 280270.8, 8700.97), (2.48, 2.46, 3.1))):
        assert tuple(last(f"{b}.{p}.volume") for p in PARTS) == vols and tuple(last(f"{b}.{p}.rate") for p in PARTS) == rates
        assert abs(vols[0] - vols[1] - vols[2]) <= 0.0101                                                                           # the volumes add up to the cent of a million (two decimals): the biggest gap is 0.01
        assert abs(rates[0] - (vols[1] * rates[1] + vols[2] * rates[2]) / (vols[1] + vols[2])) <= 0.0093                            # and the rate on all of it is the volume-weighted average of the two parts, to rounding
    assert round(12347.35 * 3.89 + 63464.07 * 3.57, 2) == 274597.92 and round(274597.92 / (12347.35 + 63464.07), 4) == 3.6221         # house purchase by hand: 48,031.19 + 226,566.73 = 274,597.92 over 75,811.42 is 3.6221, against the published 3.62
    assert (last("firms_cost.rate") - last("firms.A.rate"), last("house_cost.rate") - last("house.A.rate")) == (pytest.approx(0.11), pytest.approx(0.0))
    assert {sid: d["status"][-1] for sid, d in s.items() if d["status"][-1] != "P"} == {"firms_cost.rate": "A", "house_cost.rate": "A"}    # the ECB marks the newest month provisional, except the two composites


@pytest.mark.parametrize("sid", SHOWN)
def test_the_newest_value_is_provisional_when_a_rate_the_card_prints_is_not_final(sid):
    for st, expected in (("A", False), ("", False), ("P", True), ("E", True), ("F", True)):
        assert _run(_world(status={sid: st}))["provisional"] is expected, (sid, st)


def test_only_the_rates_the_card_prints_decide_whether_it_says_provisional():
    others = {sid: "P" for sid in IDS if sid not in SHOWN}
    assert len(others) == 30 and _run(_world(status=others))["provisional"] is False                                                # the parts and the volumes are provisional too, and not printed
    assert _run(_world(status={**others, "firms_term.A.rate": "P"}))["provisional"] is True
    assert _run(_world(status={sid: "A" for sid in IDS}))["provisional"] is False


def test_overdue_after_75_days_from_the_end_of_the_newest_month():
    end = date(2026, 9, 30)
    r = _run(_world(), end + timedelta(days=75))
    assert (r["age_days"], r["freshness"]) == (75, "CURRENT")
    r = _run(_world(), end + timedelta(days=76))
    assert (r["age_days"], r["freshness"]) == (76, "OVERDUE")
    assert _run(_world(), end)["age_days"] == 0


def test_each_month_ends_on_its_own_last_day():
    for last, today, age in ((date(2026, 2, 1), date(2026, 3, 5), 5), (date(2024, 2, 1), date(2024, 3, 2), 2), (date(2025, 12, 1), date(2026, 1, 4), 4), (date(2026, 4, 1), date(2026, 5, 2), 2), (date(2026, 1, 1), date(2026, 2, 3), 3)):
        r = _run(_world(last), today)
        assert r["month"] == _lab(last) and r["age_days"] == age, last                                                         # February 2024 has 29 days, April 30, December 31


def _g(n, last=LAST, f=lambda k: 0.1 * k):
    """`n` months of a rate ending on `last`, oldest first: the month k steps from the oldest is f(k)."""
    return {_d(_i(last) - n + 1 + k): f(k) for k in range(n)}


def test_the_ten_year_comparison_needs_60_months_and_counts_only_the_120_newest():
    assert S._range(_g(59), LAST) is None
    r = S._range(_g(60), LAST)
    assert r is not None and r["months"] == 60
    r = S._range({**_g(125), date(2016, 8, 1): -50.0, date(2016, 9, 1): -40.0}, LAST)                                         # the two months before 2016-10 are older than ten years: not counted
    assert r["months"] == 120 and r["lowest"] == {"pct": 0.5, "month": "2016-10"} and r["highest"] == {"pct": 12.4, "month": "2026-09"}
    assert S._range(_g(125), date(2026, 8, 1))["months"] == 120 and S._range(_g(125), date(2026, 8, 1))["highest"]["month"] == "2026-08"      # months after `last` are not counted


def test_the_share_of_lower_months_counts_only_months_strictly_below_and_is_a_whole_percent():
    assert S._range(_g(120, f=lambda k: 1.0), LAST)["share_lower_pct"] == 0                                                    # all tied with the newest: none is lower
    assert S._range(_g(120, f=lambda k: 1.0 if k < 119 else 2.0), LAST)["share_lower_pct"] == 99                               # 119 of 120 are lower: 99.17, shown as 99
    assert S._range(_g(120, f=lambda k: 0.5 if k < 3 else 1.0), LAST)["share_lower_pct"] == 2                                  # 3 of 120 are lower: 2.5, shown as 2 (the even one)
    assert S._range(_g(120, f=lambda k: 0.5 if k < 9 else 1.0), LAST)["share_lower_pct"] == 8                                  # 9 of 120: 7.5, shown as 8
    assert S._range(_g(120, f=lambda k: 0.5 if k < 1 else 1.0), LAST)["share_lower_pct"] == 1                                  # 1 of 120: 0.83, shown as 1
    assert S._range(_g(80, f=lambda k: 0.5 if k < 20 else 1.0), LAST)["share_lower_pct"] == 25                                 # 20 of the 80 months there are: 25%, not 20 of 120


def test_lowest_and_highest_with_their_months_and_two_decimals():
    r = S._range(_g(120, f=lambda k: -3.14159 if k in (5, 9) else 2.71828 if k in (6, 30) else 0.0), LAST)                  # the oldest of the 120 months is 2016-10
    assert r["lowest"] == {"pct": -3.14, "month": "2017-03"} and r["highest"] == {"pct": 2.72, "month": "2017-04"}             # a tie names the earlier month (k = 5 and 6 steps after October 2016); values are shown to two decimals


def test_every_figure_is_shown_to_the_decimals_the_card_prints():
    w = _world()
    w[0]["firms.A.rate"][LAST] = 4.0 + 2 ** -8                                                                                   # 4.00390625 is shown as 4.0 (one, two and three decimals: 4.0, 4.0, 4.004)
    w[0]["firms.A.rate"][_back(LAST, 1)] = 4.0 - 2 ** -8                                                                         # 3.99609375 also rounds to 4.0, but the move between them (0.0078125) is 0.01, not 4.0 - 4.0 = 0.0
    _shift(w, "firms", -(0.5 + 2 ** -8), back=12)                                                                                # a year earlier 3.49609375 (rounds to 3.5): 0.5078125 is 0.51, not 4.0 - 3.5 = 0.5
    row = _run(w)["loans"][0]
    assert (row["rate_pct"], row["change_month_points"], row["change_year_points"]) == (4.0, 0.01, 0.51)
    w = _world()
    w[0]["firms.A.rate"][LAST] = 4.0 + 2 ** -7                                                                                   # 4.0078125: one, two and three decimals read 4.0, 4.01 and 4.008
    _shift(w, "firms", -(0.5 + 2 ** -7), back=12)                                                                                # a year earlier 3.4921875: the difference 0.515625 reads 0.5, 0.52 and 0.516
    row = _run(w)["loans"][0]
    assert (row["rate_pct"], row["change_month_points"], row["change_year_points"]) == (4.01, 0.01, 0.52)                       # and the month's move, 0.0078125, reads 0.0, 0.01 and 0.008
    w = _world()
    for p, x in (("F", 3000.5), ("K", 1000.25), ("A", 4000.75)):
        w[0][f"firms.{p}.volume"] = {m: x for m in w[0][f"firms.{p}.volume"]}                                                    # a volume of 4,000.75 million euro is shown as 4,001 whole millions (the rate identity moves by 0.00006)
    assert _run(w)["loans"][0]["volume_millions"] == 4001.0
    w = _world()
    for p, x in (("F", 3000.25), ("K", 1000.0), ("A", 4000.25)):
        w[0][f"firms.{p}.volume"] = {m: x for m in w[0][f"firms.{p}.volume"]}
    assert _run(w)["loans"][0]["volume_millions"] == 4000.0                                                                      # 4,000.25 is shown as 4,000


def test_a_row_has_a_volume_only_when_the_source_has_one():
    r = _run(_world())
    assert [x["volume_millions"] for x in r["loans"]] == [4000.0, 4000.0, 4000.0, 4000.0] and [x["volume_millions"] for x in r["deposits"]] == [None, 4000.0, None, 4000.0] and [x["volume_millions"] for x in r["costs"]] == [None, None]
    assert [x["rate_pct"] for x in r["loans"]] == [4.0, 3.5, 8.0, 4.0] and [x["rate_pct"] for x in r["deposits"]] == [0.25, 3.0, 0.5, 2.75] and [x["rate_pct"] for x in r["costs"]] == [4.5, 3.25]
    assert [x["id"] for x in r["loans"]] == list(LOANS) and [x["id"] for x in r["deposits"]] == list(DEPOSITS) and [x["id"] for x in r["costs"]] == list(COSTS)
    assert [x["label"] for x in r["loans"] + r["deposits"] + r["costs"]] == [LABEL[e] for e in LOANS + DEPOSITS + COSTS]
    assert all(x["window"] is None for x in r["loans"] + r["deposits"] + r["costs"])                                             # 36 months is under the 60 a comparison needs
    r = _run(_world(extra=24))                                                                                                   # 60 months are enough
    assert all(x["window"] is not None and x["window"]["months"] == 60 for x in r["loans"] + r["deposits"] + r["costs"])


def test_the_recent_months_are_the_six_newest_in_order_and_the_card_gets_both_composites_for_each():
    r = _run(_world())
    assert [x["month"] for x in r["recent"]] == ["2026-09", "2026-08", "2026-07", "2026-06", "2026-05", "2026-04"] and len(r["recent"]) == 6
    w = _world()
    for k in range(6):
        w[0]["firms_cost.rate"][_back(LAST, k)], w[0]["house_cost.rate"][_back(LAST, k)] = 4.0 + 0.0625 * (k + 1), 3.5 - 0.0625 * (k + 1)       # 4.0625, 4.125 ... and 3.4375, 3.375 ...: within a point of the totals
    r = _run(w)
    assert [(x["month"], x["firms_cost_pct"], x["house_cost_pct"]) for x in r["recent"]] == [("2026-09", 4.06, 3.44), ("2026-08", 4.12, 3.38), ("2026-07", 4.19, 3.31), ("2026-06", 4.25, 3.25), ("2026-05", 4.31, 3.19), ("2026-04", 4.38, 3.12)]
    assert _run(w)["recent"][0]["date"] == "2026-09-01" and _run(w)["recent"][5]["date"] == "2026-04-01"


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    for sid in IDS:
        for wrong in (("PC", UNITS[sid][1]), (UNITS[sid][0], "3"), (UNITS[sid][0], "")):
            w = _world()
            w[1][sid] = wrong
            assert _err(w) == f"the ECB reports {NAMES[sid]} in other units than the card assumes", (sid, wrong)
    assert _err(_world()) is None
    w = _world()
    w[1]["firms.A.volume"] = RATE_U                                                                                                # a volume labelled as a rate, and a rate labelled as a volume
    assert _err(w) == f"the ECB reports {NAMES['firms.A.volume']} in other units than the card assumes"
    w = _world()
    w[1]["firms.A.rate"] = VOLUME_U
    assert _err(w) == f"the ECB reports {NAMES['firms.A.rate']} in other units than the card assumes"


def test_series_ending_in_different_months_are_refused():
    for sid in IDS:
        w = _world()
        w[0][sid].pop(LAST)
        assert _err(w) == "the bank interest rate series end in different months", sid
        w = _world()
        w[0][sid][_d(_i(LAST) + 1)] = w[0][sid][LAST]
        assert _err(w) == "the bank interest rate series end in different months", sid
    assert _err(_world()) is None


def test_a_month_missing_in_the_last_36_is_refused_and_an_older_one_is_not():
    for sid in IDS:
        for back in (1, 18, 35):
            w = _world()
            d = _back(LAST, back)
            w[0][sid].pop(d)
            assert _err(w) == f"{NAMES[sid]} is missing for {_lab(d)}", (sid, back)
        w = _world(extra=1)                                                                                                    # 37 months: the oldest is outside the 36 that are looked at
        w[0][sid].pop(_back(LAST, 36))
        assert _err(w) is None, sid
        w = _world(extra=1)
        w[0][sid].pop(_back(LAST, 35))
        assert _err(w) == f"{NAMES[sid]} is missing for {_lab(_back(LAST, 35))}", sid


def test_each_rate_must_lie_between_minus_one_and_twelve_percent_in_every_month_of_the_window():
    for sid in RATES:
        for edge, outside in ((-1.0, -1.01), (12.0, 12.01)):
            w = _world()
            w[0][sid][LAST] = edge
            msg = _err(w)
            assert msg is None or ", outside -1% to 12%" not in msg, (sid, edge, msg)                                           # at the limit it passes the range check; a later check may speak
            w = _world()
            w[0][sid][LAST] = outside
            assert _err(w) == f"{NAMES[sid]} is {outside:.2f}% in 2026-09, outside -1% to 12%", (sid, outside)
    w = _world()
    w[0]["consumer.A.rate"][_back(LAST, 30)] = 12.5                                                                              # not only the newest month
    assert _err(w) == f"{NAMES['consumer.A.rate']} is 12.50% in 2024-03, outside -1% to 12%"
    w = _world()
    w[0]["firms_term.F.rate"][_back(LAST, 35)] = -1.5                                                                            # the oldest month of the window is looked at too
    assert _err(w) == f"{NAMES['firms_term.F.rate']} is -1.50% in 2023-10, outside -1% to 12%"
    w = _world()
    for m in w[0]["household_overnight.rate"]:
        w[0]["household_overnight.rate"][m] = 12.0                                                                               # a rate at the upper limit in every month, with nothing else disturbed, passes
    assert _err(w) is None
    w = _world()
    for m in w[0]["household_overnight.rate"]:
        w[0]["household_overnight.rate"][m] = -1.0
    assert _err(w) is None


def test_each_volume_must_lie_between_100_and_a_million_million_euro_in_every_month_of_the_window():
    for sid in VOLUMES:
        for edge, outside, shown in ((100.0, 99.0, "99"), (1000000.0, 1000001.0, "1,000,001")):
            w = _world()
            w[0][sid][LAST] = edge
            msg = _err(w)
            assert msg is None or ", outside 100 to 1,000,000" not in msg, (sid, edge, msg)                                     # at the limit it passes the range check; the sum it then breaks is what speaks
            w = _world()
            w[0][sid][LAST] = outside
            assert _err(w) == f"{NAMES[sid]} is {shown} million euro in 2026-09, outside 100 to 1,000,000", (sid, outside)
    w = _world()
    w[0]["other.K.volume"][_back(LAST, 30)] = 1000001.0
    assert _err(w) == f"{NAMES['other.K.volume']} is 1,000,001 million euro in 2024-03, outside 100 to 1,000,000"
    w = _world()
    w[0]["other.K.volume"][_back(LAST, 35)] = 99.0
    assert _err(w) == f"{NAMES['other.K.volume']} is 99 million euro in 2023-10, outside 100 to 1,000,000"


@pytest.mark.parametrize("e", ("firms", "house", "consumer", "other", "household_term", "firms_term", "firms_cost", "house_cost"))
def test_a_loan_term_deposit_or_composite_rate_may_move_by_up_to_two_points_in_a_month(e):
    sid = f"{e}.A.rate" if e in BLOCKS else f"{e}.rate"
    for delta in (2.0, -2.0):                                                                                                    # exact in binary: a move of exactly the limit is allowed
        w = _world()
        _shift(w, e, delta)
        msg = _err(w)
        assert msg is None or "moved by" not in msg, (e, delta, msg)
    for delta, text in ((2.25, "+2.25"), (-2.25, "-2.25")):
        w = _world()
        d = _shift(w, e, delta)
        assert _err(w) == f"{NAMES[sid]} moved by {text} points in {_lab(d)}, more than 2", (e, delta)
    w = _world()
    d = _shift(w, e, 3.0, back=20)                                                                                               # an older month is looked at too; the series then falls back, which is a move as well
    assert _err(w) == f"{NAMES[sid]} moved by +3.00 points in {_lab(d)}, more than 2", e


@pytest.mark.parametrize("e", OVERNIGHT)
def test_an_overnight_deposit_rate_may_move_by_up_to_one_point_in_a_month(e):
    sid = f"{e}.rate"
    for delta in (1.0, -1.0):
        w = _world()
        _shift(w, e, delta)
        assert _err(w) is None, (e, delta)                                                                                       # nothing else looks at an overnight rate
    for delta, text in ((1.25, "+1.25"), (-1.25, "-1.25")):
        w = _world()
        d = _shift(w, e, delta)
        assert _err(w) == f"{NAMES[sid]} moved by {text} points in {_lab(d)}, more than 1", (e, delta)


def test_the_parts_of_a_block_are_not_held_to_the_monthly_move_the_printed_rates_are():
    w = _world()
    d = LAST
    w[0]["consumer.F.rate"][d], w[0]["consumer.K.rate"][d], w[0]["consumer.A.rate"][d] = 7.5, 8.0, 7.875                         # the floating rate jumps by 2.5 points, the fixed rate falls by 1, the total (1000 and 3000 million euro) moves by -0.125
    assert (1000.0 * 7.5 + 3000.0 * 8.0) / 4000.0 == 7.875
    assert _err(w) is None


def _sum_world(b, off, part="A", back=0):
    w = _world()
    d = _back(LAST, back)
    w[0][f"{b}.{part}.volume"][d] += off
    return w, d


def test_all_new_business_must_equal_its_two_parts_to_0_016_million_euro_for_each_of_the_six_blocks():
    for b in BLOCKS:
        for off, ok in ((TOL, True), (-TOL, True), (TOL + 2 ** -10, False), (-TOL - 2 ** -10, False), (0.25, False), (-0.25, False)):      # a gap of exactly the tolerance is allowed
            w, d = _sum_world(b, off)
            if ok:
                assert _err(w) is None, (b, off)
            else:
                assert _err(w) == _sum_msg(b, d, off), (b, off)
        for p in ("F", "K"):
            w, d = _sum_world(b, 0.25, p)
            assert _err(w) == _sum_msg(b, d, -0.25), (b, p)                                                                      # a part too large makes the total too small
    for b in ("firms", "firms_term"):
        for back in (17, 35):                                                                                                    # old months are looked at too, the oldest of the window as well
            w, d = _sum_world(b, 0.5, back=back)
            assert _err(w) == _sum_msg(b, d, 0.5), (b, back)
    assert _err(_world(extra=1)) is None
    w = _world(extra=1)
    w[0]["house.A.volume"][_back(LAST, 36)] += 0.5                                                                               # the 37th month is outside the window
    assert _err(w) is None


def _rate_world(b, gap, back=0):
    w = _world()
    d = _back(LAST, back)
    w[0][f"{b}.A.rate"][d] += gap
    return w, d


def test_the_rate_on_all_new_business_must_equal_the_volume_weighted_average_of_its_parts_to_0_016_points_for_each_block():
    for b in BLOCKS:
        for gap, ok in ((TOL, True), (-TOL, True), (TOL + 2 ** -10, False), (-TOL - 2 ** -10, False), (0.25, False), (-0.25, False)):
            w, d = _rate_world(b, gap)
            if ok:
                assert _err(w) is None, (b, gap)
            else:
                assert _err(w) == _rate_msg(b, d, gap), (b, gap)
    for b in ("house", "firms_term"):
        w, d = _rate_world(b, 0.25, back=23)                                                                                     # the rate identity looks at the last 24 months
        assert _err(w) == _rate_msg(b, d, 0.25), b
        w, d = _rate_world(b, 0.25, back=24)
        assert _err(w) is None, b
    w = _world()
    w[0]["firms.F.rate"][LAST] += 0.5                                                                                            # a part's rate that moves the weighted average by 0.375 (three quarters of the weight)
    d = LAST
    assert _err(w) == _rate_msg("firms", d, -0.375)
    w = _world()
    w[0]["firms.K.rate"][LAST] += 0.5                                                                                            # and a quarter of the weight moves it by 0.125
    assert _err(w) == _rate_msg("firms", LAST, -0.125)


def test_the_weights_are_the_volumes_of_the_two_parts_not_of_all_of_it():
    w = _world()
    w[0]["firms.F.volume"][LAST], w[0]["firms.K.volume"][LAST] = 1000.0, 1000.0                                                  # equal weights now: the average of 3 and 7 is 5, not 4.0
    w[0]["firms.A.volume"][LAST] = 2000.0
    assert _err(w) == _rate_msg("firms", LAST, -1.0)
    w[0]["firms.A.rate"][LAST] = 5.0
    assert _err(w) is None                                                                                                       # with the rate that matches the new weights everything passes


def test_a_composite_must_lie_within_one_point_of_the_rate_on_all_new_loans_of_the_same_borrowers():
    for c, total, base in (("firms_cost", "firms", 4.0), ("house_cost", "house", 3.5)):
        for gap, ok in ((1.0, True), (-1.0, True), (1.0 + 2 ** -10, False), (-1.0 - 2 ** -10, False), (1.5, False), (-1.5, False)):      # exact in binary: a gap of exactly one point is allowed
            w = _world()
            w[0][f"{c}.rate"][LAST] = base + gap
            if ok:
                assert _err(w) is None, (c, gap)
            else:
                assert _err(w) == _cost_msg(c, total, LAST, gap), (c, gap)
        for back in (17, 35):                                                                                                    # old months are looked at too, the oldest of the window as well
            w = _world()
            d = _back(LAST, back)
            w[0][f"{c}.rate"][d] = base + 1.5
            w[0][f"{c}.rate"][_back(d, -1)] = base + 1.5                                                                         # two months in a row at +1.5, so that the stretch makes no move of more than 2 points
            assert _err(w) == _cost_msg(c, total, d, 1.5), (c, back)
        w = _world(extra=1)
        w[0][f"{c}.rate"][_back(LAST, 36)] = base + 1.5
        assert _err(w) is None, c                                                                                                # the 37th month is outside the window


def test_the_composite_gap_message_names_the_composite_and_the_borrowers_rate():
    w = _world()
    w[0]["firms_cost.rate"][LAST] = 5.5
    assert _err(w) == "the ECB's cost of borrowing for firms is 1.50 points away from the rate on loans to firms in 2026-09, more than 1"
    w = _world()
    for m in w[0]["house_cost.rate"]:
        w[0]["house_cost.rate"][m] = 2.0
    assert _err(w) == "the ECB's cost of borrowing for house purchase is 1.50 points away from the rate on loans for house purchase in 2023-10, more than 1"       # the oldest month of the window speaks first


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    w = _world()
    w[1]["firms.A.rate"] = ("PC", "0")
    w[0]["firms.A.volume"].pop(LAST)
    assert _err(w).startswith("the ECB reports the rate on loans to firms (all new business) in other units")                    # the units before the end months
    w = _world()
    w[0]["firms.A.volume"].pop(LAST)
    w[0]["house.A.rate"].pop(_back(LAST, 5))
    assert _err(w) == "the bank interest rate series end in different months"                                                    # the end months before the holes
    w = _world()
    w[0]["house.A.rate"].pop(_back(LAST, 5))
    w[0]["firms.A.volume"][LAST] = 1.0
    assert _err(w) == f"{NAMES['house.A.rate']} is missing for {_lab(_back(LAST, 5))}"                                          # the holes before the ranges
    w = _world()
    w[0]["firms.A.volume"][LAST] = 99.0
    w[0]["house.A.rate"][LAST] = 99.0
    assert _err(w).startswith(f"{NAMES['firms.A.volume']} is 99 million euro")                                                  # the ranges of the first series before those of a later one
    w = _world()
    w[0]["firms_overnight.rate"][LAST] = 12.5
    assert _err(w) == f"{NAMES['firms_overnight.rate']} is 12.50% in 2026-09, outside -1% to 12%"                               # a range before the move it makes too (a jump of 12 points)
    w = _world()
    w[0]["firms_overnight.rate"][LAST] = 1.75
    assert _err(w) == _moved("firms_overnight.rate", 1.25, LAST, 1)
    w = _world()
    w[0]["firms.A.volume"][LAST] += 5.0
    w[0]["firms_overnight.rate"][LAST] = 1.75
    assert _err(w) == _moved("firms_overnight.rate", 1.25, LAST, 1)                                                              # the moves before the sums
    w = _world()
    w[0]["firms_term.A.volume"][LAST] += 5.0
    w[0]["firms.A.rate"][LAST] += 0.25
    assert _err(w) == _sum_msg("firms_term", LAST, 5.0)                                                                          # the sums (all six blocks) before the rate identities
    w = _world()
    w[0]["house.A.rate"][LAST] += 0.25
    w[0]["firms_cost.rate"][LAST] = 6.5
    assert _err(w) == _rate_msg("house", LAST, 0.25)                                                                             # the rate identities before the composites
    w = _world()
    w[0]["firms_cost.rate"][LAST] = 6.0
    w[0]["firms_cost.rate"][_back(LAST, 1)] = 6.0
    w[0]["house_cost.rate"][LAST] = 5.0
    w[0]["house_cost.rate"][_back(LAST, 1)] = 5.0
    assert _err(w) == _cost_msg("firms_cost", "firms", _back(LAST, 1), 2.0)                                                      # the firms' composite before the house composite
    w = _world()
    w[0]["firms.A.volume"][LAST] += 5.0
    w[0]["other.A.volume"][LAST] += 5.0
    assert _err(w) == _sum_msg("firms", LAST, 5.0)                                                                               # the first block with a gap speaks
    w = _world()
    w[0]["consumer.A.rate"][LAST] += 0.25
    w[0]["other.A.rate"][LAST] += 0.25
    assert _err(w) == _rate_msg("consumer", LAST, 0.25)


def test_the_largest_gaps_are_reported_with_their_sign_month_and_block_and_keep_the_earlier_of_two_equal_ones():
    w = _world()
    assert _run(w)["detail"] == {"months_checked": 36, "sums_checked": 216, "rate_months_checked": 24, "rates_checked": 144, "largest_sum_gap_millions": 0.0, "largest_sum_gap_month": None, "largest_sum_gap_series": None,
                                 "largest_rate_gap_points": 0.0, "largest_rate_gap_month": None, "largest_rate_gap_series": None}
    w[0]["firms.A.volume"][_back(LAST, 3)] += 2 ** -7                                                                            # +0.0078125 shown as 0.0078
    w[0]["house.A.volume"][_back(LAST, 9)] -= 2 ** -6                                                                            # -0.015625 shown as -0.0156: the largest, and negative
    w[0]["firms.A.rate"][_back(LAST, 2)] += 2 ** -7                                                                              # +0.0078125
    w[0]["consumer.A.rate"][_back(LAST, 11)] -= 2 ** -8                                                                          # -0.00390625
    d = _run(w)["detail"]
    assert (d["largest_sum_gap_millions"], d["largest_sum_gap_month"], d["largest_sum_gap_series"]) == (-0.0156, "2025-12", "loans for house purchase")
    assert (d["largest_rate_gap_points"], d["largest_rate_gap_month"], d["largest_rate_gap_series"]) == (0.0078, "2026-07", "loans to firms")
    w = _world()
    w[0]["firms_term.A.volume"][_back(LAST, 2)] += 2 ** -6                                                                       # the largest is positive this time
    w[0]["other.A.volume"][_back(LAST, 4)] -= 2 ** -7
    w[0]["other.A.rate"][_back(LAST, 6)] -= 2 ** -6
    w[0]["house.A.rate"][_back(LAST, 7)] += 2 ** -7
    d = _run(w)["detail"]
    assert (d["largest_sum_gap_millions"], d["largest_sum_gap_month"], d["largest_sum_gap_series"]) == (0.0156, "2026-07", "firms' term deposits")
    assert (d["largest_rate_gap_points"], d["largest_rate_gap_month"], d["largest_rate_gap_series"]) == (-0.0156, "2026-03", "other loans to households")
    w = _world()
    w[0]["firms.A.volume"][_back(LAST, 2)] -= 2 ** -7                                                                            # two equal gaps in one block: the earlier month stays, whichever sign it has
    w[0]["firms.A.volume"][_back(LAST, 5)] += 2 ** -7
    w[0]["house.A.volume"][_back(LAST, 8)] += 2 ** -7                                                                            # and an equal gap in a later block does not replace the earlier block's
    d = _run(w)["detail"]
    assert (d["largest_sum_gap_millions"], d["largest_sum_gap_month"], d["largest_sum_gap_series"]) == (0.0078, "2026-04", "loans to firms")
    w = _world()
    w[0]["firms.A.rate"][_back(LAST, 2)] -= 2 ** -7
    w[0]["firms.A.rate"][_back(LAST, 5)] += 2 ** -7
    w[0]["house.A.rate"][_back(LAST, 8)] += 2 ** -7
    d = _run(w)["detail"]
    assert (d["largest_rate_gap_points"], d["largest_rate_gap_month"], d["largest_rate_gap_series"]) == (0.0078, "2026-04", "loans to firms")
    w = _world()
    w[0]["firms.A.volume"][LAST] += 2 ** -15                                                                                     # 0.0000305 rounds to 0.0 at four decimals: no month, no series
    w[0]["firms.A.rate"][LAST] += 2 ** -15
    d = _run(w)["detail"]
    assert d["largest_sum_gap_millions"] == 0.0 and d["largest_sum_gap_month"] is None and d["largest_sum_gap_series"] is None
    assert d["largest_rate_gap_points"] == 0.0 and d["largest_rate_gap_month"] is None and d["largest_rate_gap_series"] is None


def test_the_real_record_passes_every_check_and_is_pinned():
    assert _err(_real()) is None
    v = _real()[0]
    extremes = {}
    for sid in SHOWN:
        months = sorted(v[sid])
        ch = [(round(v[sid][y] - v[sid][x], 2), _lab(y)) for x, y in zip(months, months[1:])]
        extremes[sid] = (min(ch), max(ch))
    assert extremes == {"firms.A.rate": ((-0.25, "2024-09"), (0.59, "2022-09")), "house.A.rate": ((-0.21, "2025-01"), (0.23, "2022-10")), "consumer.A.rate": ((-0.31, "2017-12"), (0.56, "2023-01")),
                        "other.A.rate": ((-0.32, "2024-12"), (0.42, "2022-10")), "household_term.A.rate": ((-0.25, "2024-10"), (0.31, "2022-10")), "firms_term.A.rate": ((-0.22, "2024-10"), (0.55, "2022-11")),
                        "household_overnight.rate": ((-0.02, "2025-02"), (0.04, "2023-08")), "firms_overnight.rate": ((-0.07, "2025-04"), (0.1, "2023-03")),
                        "firms_cost.rate": ((-0.21, "2024-09"), (0.53, "2022-09")), "house_cost.rate": ((-0.14, "2025-01"), (0.22, "2022-11"))}      # all inside the bounds of 2 points and (overnight) 1 point


def test_the_limits_and_tolerances_are_the_ones_set_from_the_real_record():
    assert (S.RATE_LIMITS, S.VOLUME_LIMITS) == (RATE_LIMITS, VOLUME_LIMITS) and (S.MONTH_MOVE, S.OVERNIGHT_MOVE) == (2.0, 1.0)
    assert (S.SUM_TOLERANCE, S.RATE_TOLERANCE, S.COST_GAP) == (0.015625, 0.015625, 1.0)
    assert (S.CHECK_MONTHS, S.DEPTH, S.LAST_N, S.RATE_WINDOW, S.MIN_WINDOW, S.RECENT_MONTHS, S.OVERDUE_AFTER_DAYS) == (24, 36, 125, 120, 60, 6, 75)
    assert (S.TTL, S.FAIL_TTL, S.TIMEOUT) == (21600.0, 120.0, 90.0)
    assert S.BASE == "https://data-api.ecb.europa.eu/service/data/MIR/" and S.NAMES == NAMES and S.LABEL == LABEL and S.PART_WORDS == WORDS
    assert (S.RATE_UNIT, S.VOLUME_UNIT) == (RATE_U, VOLUME_U) and S.PARTS == PARTS
    assert S.LOANS == LOANS and S.DEPOSITS == DEPOSITS and S.COSTS == COSTS and S.OVERNIGHT == OVERNIGHT and S.COST_OF == {"firms_cost": "firms", "house_cost": "house"} and S.SHOWN == SHOWN
    assert S.BLOCKS == {"firms": ("A2A", "2240", "loans to firms"), "house": ("A2C", "2250", "loans for house purchase"), "consumer": ("A2B", "2250", "consumer credit"),
                        "other": ("A2D", "2250", "other loans to households"), "household_term": ("L22", "2250", "household term deposits"), "firms_term": ("L22", "2240", "firms' term deposits")}
    assert S.SINGLES == {"household_overnight": ("L21", "A", "2250", "household overnight deposits"), "firms_overnight": ("L21", "A", "2240", "firms' overnight deposits"),
                         "firms_cost": ("A2I", "AM", "2240", "the ECB's cost of borrowing for firms"), "house_cost": ("A2C", "AM", "2250", "the ECB's cost of borrowing for house purchase")}
    item = {"firms": ("A2A", "2240"), "house": ("A2C", "2250"), "consumer": ("A2B", "2250"), "other": ("A2D", "2250"), "household_term": ("L22", "2250"), "firms_term": ("L22", "2240")}
    keys = {f"{b}.{p}.{k}": (f"M.U2.B.{item[b][0]}.{p}.{t}.A.{item[b][1]}.EUR.N", RATE_U if k == "rate" else VOLUME_U) for b in BLOCKS for p in PARTS for k, t in (("rate", "R"), ("volume", "B"))}
    keys.update({"household_overnight.rate": ("M.U2.B.L21.A.R.A.2250.EUR.N", RATE_U), "firms_overnight.rate": ("M.U2.B.L21.A.R.A.2240.EUR.N", RATE_U),
                 "firms_cost.rate": ("M.U2.B.A2I.AM.R.A.2240.EUR.N", RATE_U), "house_cost.rate": ("M.U2.B.A2C.AM.R.A.2250.EUR.N", RATE_U)})
    assert S.SERIES == keys and len(keys) == 40 and tuple(keys) == tuple(sorted(keys, key=list(S.SERIES).index))
    assert S.PAGE == "https://data-api.ecb.europa.eu/service/data/MIR/M.U2.B.A2I.AM.R.A.2240.EUR.N"
    assert S.SOURCE == "European Central Bank, ECB Data Portal: interest rates that euro-area banks charge on new loans and pay on new deposits (MFI interest rate statistics, official, free public data)"
    assert S.REQUESTS == (("M.U2.B.A2C+A2B+A2D.A+F+K.R+B.A.2250.EUR.N", tuple(f"{b}.{p}.{k}" for b in ("house", "consumer", "other") for p in PARTS for k in ("rate", "volume"))),
                          ("M.U2.B.A2A.A+F+K.R+B.A.2240.EUR.N", tuple(f"firms.{p}.{k}" for p in PARTS for k in ("rate", "volume"))),
                          ("M.U2.B.L21+L22.A+F+K.R+B.A.2250+2240.EUR.N", tuple(f"{b}.{p}.{k}" for b in ("household_term", "firms_term") for p in PARTS for k in ("rate", "volume")) + ("household_overnight.rate", "firms_overnight.rate")),
                          ("M.U2.B.A2I+A2C.AM.R.A.2240+2250.EUR.N", ("firms_cost.rate", "house_cost.rate")))


def test_the_four_requests_return_exactly_the_40_series_of_the_card_and_each_series_once():
    ids = [i for key, group in S.REQUESTS for i in group]
    assert len(ids) == 40 and sorted(ids) == sorted(IDS) and len(S.REQUESTS) == 4
    assert all(sid in S.SERIES for sid in ids)


HEAD = "KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
OK = "MIR.M.U2.B.A2A.A.R.A.2240.EUR.N,M"


def test_the_real_layout_of_a_response_is_read():
    v, units, status = S.parse(F["raw_head"], ("consumer.A.volume",))
    assert v == {"consumer.A.volume": {date(2016, 5, 1): 20211.64, date(2016, 6, 1): 22186.86}} and units == {"consumer.A.volume": VOLUME_U} and status == {"consumer.A.volume": "A"}
    assert F["raw_head"].startswith("KEY,FREQ,REF_AREA,BS_REP_SECTOR,BS_ITEM,MATURITY_NOT_IRATE,DATA_TYPE_MIR,AMOUNT_CAT,BS_COUNT_SECTOR,CURRENCY_TRANS,IR_BUS_COV,TIME_PERIOD,OBS_VALUE,OBS_STATUS,")
    assert ",UNIT,UNIT_MULT" in F["raw_head"].split("\n")[0]


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_month_are_an_error():
    text = HEAD + f"{OK},2026-08,0.5,A,PCPA,0\n{OK},26-09,1,A,PCPA,0\n{OK},2026-9,1,A,PCPA,0\n{OK},2026-07,,M,PCPA,0\n{OK},2026-06,n/a,A,PCPA,0\n{OK},2026,1,A,PCPA,0\n{OK},2026-13,1,A,PCPA,0\n{OK},2026-00,1,A,PCPA,0\n"
    text += f"{OK},2026-Q3,1,A,PCPA,0\n{OK},2026-05-01,1,A,PCPA,0\n{OK}, 2026-04,1,A,PCPA,0\n{OK},2026-03x,1,A,PCPA,0\n{OK},2026-02,nan,A,PCPA,0\n{OK},2026-01,inf,A,PCPA,0\n"
    text += f"{OK},2026-03\n"                                                                                                     # a row cut short: no value at all, left out
    text += "MIR.M.U2.B.A2A.A.R.A.2240.EUR.O,M,2026-08,0.9,A,PCPA,0\nMIR.Q.U2.B.A2A.A.R.A.2240.EUR.N,Q,2026-08,0.8,A,PCPA,0\nMIR.M.U2.B.A2A.A.R.A.2250.EUR.N,M,2026-08,0.7,A,PCPA,0\n"
    v, units, status = S.parse(text, ("firms.A.rate",))
    assert v == {"firms.A.rate": {date(2026, 8, 1): 0.5}} and units == {"firms.A.rate": RATE_U} and status == {"firms.A.rate": "A"}       # a month with no value, a year, bad months, nan, inf, the outstanding amounts, another frequency and another sector are all left out
    padded = HEAD + f"{OK},2026-08,0.5, P , PCPA , 0 \n"
    assert S.parse(padded, ("firms.A.rate",))[1] == {"firms.A.rate": RATE_U} and S.parse(padded, ("firms.A.rate",))[2] == {"firms.A.rate": "P"}          # spaces around a unit or a status are not a different one
    two = HEAD + f"{OK},2026-07,0.1,A,PCPA,0\n{OK},2026-09,0.3,P,PCPA,0\n{OK},2026-08,0.2,A,PCPA,0\n"
    assert S.parse(two, ("firms.A.rate",))[2] == {"firms.A.rate": "P"}                                                           # the status is the newest month's, whatever the order of the rows
    two = HEAD + f"{OK},2026-07,0.3,P,PCPA,0\n{OK},2026-08,0.1,A,PCPA,0\n"
    assert S.parse(two, ("firms.A.rate",))[2] == {"firms.A.rate": "A"}
    with pytest.raises(ValueError, match=r"firms.A.rate has two values for 2026-08"):
        S.parse(text + f"{OK},2026-08,0.1,A,PCPA,0\n", ("firms.A.rate",))
    with pytest.raises(ValueError, match=r"no values for house.A.rate"):
        S.parse(text, ("firms.A.rate", "house.A.rate"))
    with pytest.raises(ValueError, match=r"the source returned no values for house.A.rate, other.A.rate$"):
        S.parse(text, ("house.A.rate", "other.A.rate"))


def _text(ids, units=None):
    rows = []
    for sid in ids:
        d = F["series"][sid]
        unit = units.get(sid, d["unit"]) if units else d["unit"]
        last = len(d["months"]) - 1
        rows += [f"MIR.{S.SERIES[sid][0]},M,{m},{x!r},{d['status'][0] if i == last else 'A'},{unit[0]},{unit[1]}" for i, (m, x) in enumerate(zip(d["months"], d["values"]))]
    return HEAD + "\n".join(rows) + "\n"


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ids_of(path):
    for key, ids in S.REQUESTS:
        if path == "/service/data/MIR/" + key:
            return ids
    raise AssertionError(path)


def _handler(req, replace=None, units=None):
    ids = _ids_of(req.url.path)
    text = _text(ids, units if units and any(i in units for i in ids) else None)
    return httpx.Response(200, text=text.replace(*replace) if replace else text)


def test_overview_fetches_four_requests_and_caches():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = S.EuroBankRates(client=_transport(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["loans"][0]["rate_pct"] == 3.79 and len(seen) == 4 and r["source"].startswith("European Central Bank")
    assert (r["age_days"], r["freshness"], r["provisional"]) == (49, "CURRENT", True)
    later = asyncio.run(S.EuroBankRates(client=_transport(_handler)).overview(datetime(2026, 12, 31, 12, tzinfo=timezone.utc)))
    assert (later["age_days"], later["as_of"], later["freshness"]) == (92, "2026-12-31T12:00:00+00:00", "OVERDUE")              # the age is counted to the day given, not to the machine's
    base = "/service/data/MIR/"
    assert {req.url.path: req.url.params["lastNObservations"] for req in seen} == {base + key: "125" for key, ids in S.REQUESTS}
    assert all(req.url.params["format"] == "csvdata" for req in seen) and all(req.headers["user-agent"] == "ATLAS research terminal" for req in seen)
    assert all(req.headers["accept"] == "text/csv" for req in seen)
    assert all("%2B" not in str(req.url) for req in seen) and sum("+" in str(req.url) for req in seen) == 4                      # the + that joins the values of one dimension must reach the ECB as it is
    asyncio.run(svc.overview(NOW))
    assert len(seen) == 4


def test_the_client_the_provider_makes_waits_90_seconds_and_is_closed_afterwards(monkeypatch):
    real, made = httpx.AsyncClient, []

    def factory(**kw):
        made.append(kw)
        c = real(transport=httpx.MockTransport(_handler))
        made.append(c)
        return c

    given = real(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(S.httpx, "AsyncClient", factory)
    r = asyncio.run(S.EuroBankRates().overview(NOW))
    assert r["available"] is True and made[0] == {"timeout": 90.0} and made[1].is_closed is True
    asyncio.run(S.EuroBankRates(client=given).overview(NOW))
    assert given.is_closed is False and len(made) == 2                                                                           # a client that was given stays open, and none was made


def test_a_final_newest_month_for_every_printed_rate_reaches_the_card():
    rows = []
    for sid in SHOWN:
        key = "MIR." + S.SERIES[sid][0]
        m, x = F["series"][sid]["months"][-1], F["series"][sid]["values"][-1]
        rows.append((f"{key},M,{m},{x!r},P,", f"{key},M,{m},{x!r},A,"))
    texts = "".join(_text(ids) for key, ids in S.REQUESTS)
    changed = [(old, new) for old, new in rows if old in texts]
    assert len(changed) == 8 and all(new not in texts for old, new in changed)                                                  # eight of the ten printed rates are provisional in the real response, the two composites are not
    def handler(req):
        r = _handler(req)
        t = r.text
        for old, new in changed:
            t = t.replace(old, new)
        return httpx.Response(200, text=t)
    r = asyncio.run(S.EuroBankRates(client=_transport(handler)).overview(NOW))
    assert r["available"] is True and r["provisional"] is False


def test_an_unexpected_missing_key_reads_as_unavailable_not_as_a_crash(monkeypatch):
    def boom(*args):
        raise KeyError("firms")

    monkeypatch.setattr(S, "summarize", boom)
    r = asyncio.run(S.EuroBankRates(client=_transport(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"].startswith("The euro-area bank interest rates could not be read right now (") and "loans" not in r


def test_a_cached_answer_carries_the_time_of_the_call_that_got_it_from_the_cache():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = S.EuroBankRates(client=_transport(handler))
    first = asyncio.run(svc.overview(NOW))
    again = asyncio.run(svc.overview(datetime(2026, 11, 18, 15, tzinfo=timezone.utc)))
    assert len(seen) == 4 and first["as_of"] == "2026-11-18T12:00:00+00:00" and again["as_of"] == "2026-11-18T15:00:00+00:00"
    assert {k: x for k, x in again.items() if k != "as_of"} == {k: x for k, x in first.items() if k != "as_of"}


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(S.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = S.EuroBankRates(client=_transport(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 4
    clock["t"] += S.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 4                                                                                                           # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 8                                                    # two minutes on it asks again
    clock["t"] += S.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 8
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 12 and (S.FAIL_TTL, S.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(S.EuroBankRates(client=_transport(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "loans" not in r and "deposits" not in r and "costs" not in r
    key = "MIR." + S.SERIES["firms_cost.rate"][0]
    slip = (f"{key},M,2026-09,3.9,A,", f"{key},M,2026-09,39.0,A,")                                                               # a decimal slip in the newest composite: a check failing shows nothing either
    assert slip[0] in _text(("firms_cost.rate",)) and slip[1] not in _text(("firms_cost.rate",))
    r = asyncio.run(S.EuroBankRates(client=_transport(lambda req: _handler(req, slip))).overview(NOW))
    assert r["available"] is False and "the ECB's cost of borrowing for firms is 39.00% in 2026-09, outside -1% to 12%" in r["reason"] and "loans" not in r


def test_a_response_in_other_units_is_refused_and_shows_nothing():
    for sid, what in (("firms.A.rate", "the rate on loans to firms (all new business)"), ("household_term.K.volume", "the new business volume of household term deposits (over 1 year fixed)"),
                      ("house_cost.rate", "the ECB's cost of borrowing for house purchase")):
        r = asyncio.run(S.EuroBankRates(client=_transport(lambda req, s=sid: _handler(req, units={s: ("EUR", "3")}))).overview(NOW))
        shown = fail_reason(ValueError(f"the ECB reports {what} in other units than the card assumes"))                           # the shared wording clips a long data-check message to 110 characters
        assert r["available"] is False and r["reason"] == f"The euro-area bank interest rates could not be read right now ({shown})" and "loans" not in r, sid
    assert fail_reason(ValueError("x" * 200)).endswith("…") and len(fail_reason(ValueError("x" * 200))) < 140


@pytest.mark.parametrize("code, words", [(400, "the server answered HTTP 400"), (403, "the server refused the request, HTTP 403"), (404, "the data was not found there, HTTP 404"), (429, "the server is limiting requests, HTTP 429"), (301, "the server answered HTTP 301"), (503, "the server had an error, HTTP 503")])
def test_any_answer_but_200_is_a_failure_that_names_its_code(code, words):
    r = asyncio.run(S.EuroBankRates(client=_transport(lambda req: httpx.Response(code))).overview(NOW))
    assert r["available"] is False and r["reason"] == f"The euro-area bank interest rates could not be read right now ({words})" and "loans" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(S.EuroBankRates(client=_transport(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The euro-area bank interest rates could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(S.EuroBankRates(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "loans" not in d
    assert d["reason"] == "Demo mode: the real euro-area bank interest rates are not shown because made-up values would look real."


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-bank-rates")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
