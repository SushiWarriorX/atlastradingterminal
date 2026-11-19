"""Euro-area bank lending (ECB Data Portal, BSI dataflow: loans of euro-area banks to firms and households, adjusted for loan sales and securitisation, seasonally adjusted, monthly): parsed from real responses (fetched 2026-11-18 08:3x UTC: the provider's four requests with 125 months each; the whole record, 285 months from 2003-01 for the totals, was read to set the checks, see the module's docstring)."""
import asyncio
import itertools
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import eurolending as S
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_lending.json").read_text())
TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)                                                  # the newest month of the real record
ENT = ("firms", "firms_short", "firms_mid", "firms_long", "households", "house", "consumer", "other")
IDS = tuple(f"{e}.{k}" for e in ENT for k in ("stock", "flow", "growth"))
AMOUNT, GROWTH_UNIT = ("EUR", "6"), ("PCCH", "0")
UNITS = {sid: GROWTH_UNIT if sid.endswith(".growth") else AMOUNT for sid in IDS}
LABEL = {"firms": "loans to firms", "firms_short": "loans to firms of up to one year", "firms_mid": "loans to firms of one to five years", "firms_long": "loans to firms of over five years",
         "households": "loans to households", "house": "lending to households for house purchase", "consumer": "consumer credit", "other": "other lending to households"}
WORD = {"stock": "amount outstanding", "flow": "monthly flow", "growth": "annual growth"}
NAMES = {f"{e}.{k}": f"{LABEL[e]} ({WORD[k]})" for e in ENT for k in WORD}
# the limits set from the real record, spelled out here so that a changed limit fails a test instead of moving the test with it
STOCK_LIMITS = {"firms": (1500000.0, 12000000.0), "firms_short": (300000.0, 3000000.0), "firms_mid": (400000.0, 4000000.0), "firms_long": (1200000.0, 10000000.0),
                "households": (1700000.0, 15000000.0), "house": (1500000.0, 15000000.0), "consumer": (200000.0, 2500000.0), "other": (250000.0, 2500000.0)}
GROWTH_LIMITS = {"firms": (-10.0, 25.0), "firms_short": (-30.0, 40.0), "firms_mid": (-20.0, 30.0), "firms_long": (-10.0, 20.0),
                 "households": (-5.0, 15.0), "house": (-10.0, 20.0), "consumer": (-15.0, 25.0), "other": (-15.0, 15.0)}
SUM_MSG = {("firms", "stock"): "loans to firms are not the sum of the loans of up to one year, of one to five years and of over five years",
           ("firms", "flow"): "the monthly flow of loans to firms is not the sum of the flows of the three maturities",
           ("households", "stock"): "loans to households are not the sum of lending for house purchase, consumer credit and other lending",
           ("households", "flow"): "the monthly flow of loans to households is not the sum of the flows of house purchase, consumer credit and other lending"}
PARTS_OF = {"firms": ("firms_short", "firms_mid", "firms_long"), "households": ("house", "consumer", "other")}
# a world's six parts: the amount at the end of the month before the first, and the net flow in every month
PARTS = {"firms_short": (900000.0, 3000.0), "firms_mid": (1200000.0, 5000.0), "firms_long": (3400000.0, 2000.0), "house": (5700000.0, 9000.0), "consumer": (840000.0, 2500.0), "other": (670000.0, 1200.0)}
EXACT = {"firms_short": (1000000.0, 0.0), "firms_mid": (1000000.0, 0.0), "firms_long": (2000000.0, 0.0), "house": (4000000.0, 0.0), "consumer": (500000.0, 0.0), "other": (500000.0, 0.0)}
TOL = 2 ** -4


def _i(d):
    return d.year * 12 + d.month - 1


def _d(i):
    return date(i // 12, i % 12 + 1, 1)


def _lab(d):
    return f"{d.year}-{d.month:02d}"


def _world(last=LAST, extra=0, status=None, parts=PARTS):
    """Twenty-four series for the 36 months (plus `extra` older ones) ending on `last`, where every check passes by construction: six parts with a fixed net flow every month and an amount that adds the flow, the totals their sums, and the published growth rebuilt from the flows exactly as the ECB builds it (the months too early to be rebuilt take the first rebuilt value)."""
    n = 36 + extra
    months = [_d(_i(last) - n + 1 + k) for k in range(n)]
    amounts, flows, opening = {}, {}, {}
    for p, (start, flow) in parts.items():
        amounts[p], flows[p], opening[p] = [start + flow * (k + 1) for k in range(n)], [flow] * n, start
    for t, ps in PARTS_OF.items():
        amounts[t], flows[t], opening[t] = [sum(amounts[p][k] for p in ps) for k in range(n)], [sum(flows[p][k] for p in ps) for k in range(n)], sum(opening[p] for p in ps)
    v = {}
    for e in ENT:
        prev = [opening[e]] + amounts[e][:-1]                                           # the amount at the end of the month before
        growth = []
        for k in range(n):
            if k < 12:
                growth.append(None)
                continue
            prod = 1.0
            for i in range(12):
                prod *= 1 + flows[e][k - i] / prev[k - i]
            growth.append(100 * (prod - 1))
        first = next(g for g in growth if g is not None)
        v[e + ".stock"], v[e + ".flow"] = dict(zip(months, amounts[e])), dict(zip(months, flows[e]))
        v[e + ".growth"] = dict(zip(months, [first if g is None else g for g in growth]))
    return v, dict(UNITS), {"firms.growth": "A"} if status is None else status


def _exact_world():
    """No lending at all: every flow 0.0, every amount constant (whole millions) and every growth 0.0, so that a gap of exactly a tolerance can be made and read back."""
    return _world(parts=EXACT)


def _real():
    v = {sid: {date(int(m[:4]), int(m[5:]), 1): x for m, x in zip(d["months"], d["values"])} for sid, d in F["series"].items()}
    return v, {sid: tuple(d["unit"]) for sid, d in F["series"].items()}, {"firms.growth": F["series"]["firms.growth"]["status"][-1]}


def _run(world, today=TODAY):
    return S.summarize(*world, today)


def _err(world, today=TODAY):
    """The refusal's text, or None when the world passes every check."""
    try:
        _run(world, today)
    except ValueError as e:
        return str(e)
    return None


def _back(d, n):
    return _d(_i(d) - n)


def _gap_msg(e, d, points):
    return f"the published growth of {LABEL[e]} in {_lab(d)} is {points:.2f} points away from the growth rebuilt from the monthly flows, more than 0.0625"


def test_the_real_latest_growth_amounts_parts_ten_year_comparison_recent_months_and_checks_by_hand():
    r = _run(_real())
    assert r["available"] is True and r["month"] == "2026-09" and r["date"] == "2026-09-01" and r["age_days"] == 49 and r["freshness"] == "CURRENT" and r["provisional"] is True    # 2026-09-30 to 2026-11-18 is 49 days
    assert r["firms"] == {"id": "firms", "label": "loans to firms", "amount_millions": 5518191.0, "flow_millions": 13214.0, "growth_pct": 4.24, "growth_year_earlier_pct": 2.9,
                          "parts": [{"id": "firms_short", "label": "loans to firms of up to one year", "amount_millions": 907832.0, "flow_millions": 4955.0, "growth_pct": 6.72, "growth_year_earlier_pct": 1.07, "share_pct": 16.5},
                                    {"id": "firms_mid", "label": "loans to firms of one to five years", "amount_millions": 1195416.0, "flow_millions": 6559.0, "growth_pct": 4.25, "growth_year_earlier_pct": 4.11, "share_pct": 21.7},
                                    {"id": "firms_long", "label": "loans to firms of over five years", "amount_millions": 3414943.0, "flow_millions": 1700.0, "growth_pct": 3.61, "growth_year_earlier_pct": 2.95, "share_pct": 61.9}],
                          "window": {"months": 120, "lowest": {"pct": -0.2, "month": "2023-10"}, "highest": {"pct": 8.9, "month": "2022-09"}, "share_lower_pct": 72}}
    assert r["households"] == {"id": "households", "label": "loans to households", "amount_millions": 7276387.0, "flow_millions": 15128.0, "growth_pct": 3.07, "growth_year_earlier_pct": 2.62,
                               "parts": [{"id": "house", "label": "lending to households for house purchase", "amount_millions": 5748827.0, "flow_millions": 11255.0, "growth_pct": 3.03, "growth_year_earlier_pct": 2.62, "share_pct": 79.0},
                                         {"id": "consumer", "label": "consumer credit", "amount_millions": 848316.0, "flow_millions": 2610.0, "growth_pct": 4.84, "growth_year_earlier_pct": 4.92, "share_pct": 11.7},
                                         {"id": "other", "label": "other lending to households", "amount_millions": 679244.0, "flow_millions": 1263.0, "growth_pct": 1.3, "growth_year_earlier_pct": 0.03, "share_pct": 9.3}],
                               "window": {"months": 120, "lowest": {"pct": 0.2, "month": "2024-04"}, "highest": {"pct": 4.6, "month": "2022-05"}, "share_lower_pct": 58}}
    assert [(x["month"], x["date"], x["firms_growth_pct"], x["households_growth_pct"]) for x in r["recent"]] == [
        ("2026-09", "2026-09-01", 4.24, 3.07), ("2026-08", "2026-08-01", 4.23, 3.1), ("2026-07", "2026-07-01", 4.36, 3.06), ("2026-06", "2026-06-01", 4.02, 3.03), ("2026-05", "2026-05-01", 4.0, 3.05), ("2026-04", "2026-04-01", 3.39, 3.01)]
    assert r["detail"] == {"months_checked": 36, "sums_checked": 144, "growth_months_checked": 24, "largest_growth_gap_points": -0.0111, "largest_growth_gap_month": "2026-09", "largest_growth_gap_series": "loans to firms of up to one year"}
    assert r["checks"] == {"units_ok": True, "months_in_a_row": True, "range_ok": True, "monthly_move_ok": True, "growth_range_ok": True, "sums_ok": True, "growth_follows_the_flows_ok": True}
    assert r["source"].startswith("European Central Bank") and r["url"] == "https://data-api.ecb.europa.eu/service/data/BSI/M.U2.Y.U.A20T.A.I.U2.2240.Z01.A"
    assert "not a market signal or a forecast" in r["note"] and "(firms) and to households, adjusted for loan sales and securitisation (a loan a bank sells on or packages into a security stays in the figure" in r["note"] and "Plain checks: the units are the ones assumed and no month is missing" in r["note"] and "provisional and is revised later" in r["note"]


def test_the_real_record_by_plain_python_outside_the_module():
    s = F["series"]
    for e, lower, lo, lo_m, hi, hi_m in (("firms", 86, -0.24284481325127505, "2023-10", 8.89810287409334, "2022-09"), ("households", 70, 0.1913632647368324, "2024-04", 4.621872371952551, "2022-05")):
        g, m = s[e + ".growth"]["values"], s[e + ".growth"]["months"]
        ten = g[-120:]
        assert (m[-120], m[-1]) == ("2016-10", "2026-09") and sum(1 for x in ten if x < g[-1]) == lower                        # 86 of 120 is 71.7%, shown as 72; 70 of 120 is 58.3, shown as 58
        assert (min(ten), m[-120:][ten.index(min(ten))], max(ten), m[-120:][ten.index(max(ten))]) == (pytest.approx(lo), lo_m, pytest.approx(hi), hi_m)
    at = lambda sid: s[sid]["values"][-1]                                                                                      # every series ends in 2026-09
    assert all(d["months"][-1] == "2026-09" for d in s.values())
    assert at("firms.stock") == at("firms_short.stock") + at("firms_mid.stock") + at("firms_long.stock") == 5518191.0
    assert at("households.stock") == at("house.stock") + at("consumer.stock") + at("other.stock") == 7276387.0
    assert at("firms.flow") == at("firms_short.flow") + at("firms_mid.flow") + at("firms_long.flow") == 13214.0
    assert at("households.flow") == at("house.flow") + at("consumer.flow") + at("other.flow") == 15128.0
    prod = 1.0                                                                                                                 # the ECB's index of notional stocks: twelve monthly links of flow over the previous amount
    for k in range(12):
        prod *= 1 + s["firms.flow"]["values"][-1 - k] / s["firms.stock"]["values"][-2 - k]
    assert 100 * (prod - 1) == pytest.approx(4.244762490925091) and at("firms.growth") == pytest.approx(4.244776080053825)    # published 4.244776, rebuilt 4.244762: 0.000014 points apart


def test_the_newest_value_is_provisional_only_when_the_source_says_so():
    for st, expected in (("A", False), ("", False), ("P", True), ("E", True), ("F", True)):
        assert _run(_world(status={"firms.growth": st}))["provisional"] is expected, st
    assert _run(_world(status={"firms.growth": "A", "households.growth": "P", "firms.stock": "P", "house.flow": "E"}))["provisional"] is False         # only the growth rate of loans to firms counts


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
    """`n` months of growth ending on `last`, oldest first: the month k steps from the oldest is f(k)."""
    return {_d(_i(last) - n + 1 + k): f(k) for k in range(n)}


def test_the_ten_year_comparison_needs_60_months_and_counts_only_the_120_newest():
    assert S._growth_range(_g(59), LAST) is None
    r = S._growth_range(_g(60), LAST)
    assert r is not None and r["months"] == 60
    r = S._growth_range({**_g(125), date(2016, 8, 1): -50.0, date(2016, 9, 1): -40.0}, LAST)                                   # the two months before 2016-10 are older than ten years: not counted
    assert r["months"] == 120 and r["lowest"] == {"pct": 0.5, "month": "2016-10"} and r["highest"] == {"pct": 12.4, "month": "2026-09"}
    assert S._growth_range(_g(125), date(2026, 8, 1))["months"] == 120 and S._growth_range(_g(125), date(2026, 8, 1))["highest"]["month"] == "2026-08"      # months after `last` are not counted


def test_the_share_of_lower_months_counts_only_months_strictly_below_and_is_a_whole_percent():
    assert S._growth_range(_g(120, f=lambda k: 1.0), LAST)["share_lower_pct"] == 0                                             # all tied with the newest: none is lower
    assert S._growth_range(_g(120, f=lambda k: 1.0 if k < 119 else 2.0), LAST)["share_lower_pct"] == 99                         # 119 of 120 are lower: 99.17, shown as 99
    assert S._growth_range(_g(120, f=lambda k: 0.5 if k < 3 else 1.0), LAST)["share_lower_pct"] == 2                            # 3 of 120 are lower: 2.5, shown as 2 (the even one)
    assert S._growth_range(_g(120, f=lambda k: 0.5 if k < 9 else 1.0), LAST)["share_lower_pct"] == 8                            # 9 of 120: 7.5, shown as 8
    assert S._growth_range(_g(120, f=lambda k: 0.5 if k < 1 else 1.0), LAST)["share_lower_pct"] == 1                            # 1 of 120: 0.83, shown as 1
    assert S._growth_range(_g(80, f=lambda k: 0.5 if k < 20 else 1.0), LAST)["share_lower_pct"] == 25                          # 20 of the 80 months there are: 25%, not 20 of 120


def test_lowest_and_highest_with_their_months_and_one_decimal():
    r = S._growth_range(_g(120, f=lambda k: -3.14159 if k in (5, 9) else 2.71828 if k in (6, 30) else 0.0), LAST)                  # the oldest of the 120 months is 2016-10
    assert r["lowest"] == {"pct": -3.1, "month": "2017-03"} and r["highest"] == {"pct": 2.7, "month": "2017-04"}                    # a tie names the earlier month (k = 5 and 6 steps after October 2016); values are shown to one decimal


def test_every_figure_is_shown_to_the_decimals_the_card_prints():
    fractional = {"firms_short": (1000000.4, 0.0), "firms_mid": (1000000.4, 0.0), "firms_long": (2000000.4, 0.0), "house": (4000000.4, 0.0), "consumer": (500000.4, 0.0), "other": (500000.4, 0.0)}
    w = _world(parts=fractional)                                                                                                 # no lending, so the rebuilt growth is 0.0 and the published growth may differ from it by less than 0.0625
    v = w[0]
    v["firms.growth"][LAST], v["firms.growth"][_back(LAST, 12)] = 0.0468, 0.0123                                                # 1, 2 and 3 decimals of 0.0468 differ (0.0, 0.05, 0.047), and of 0.0123 (0.0, 0.01, 0.012)
    v["households.growth"][LAST], v["households.growth"][_back(LAST, 12)] = -0.0468, -0.0123
    r = _run(w)
    assert r["firms"]["growth_pct"] == 0.05 and r["firms"]["growth_year_earlier_pct"] == 0.01 and r["households"]["growth_pct"] == -0.05 and r["households"]["growth_year_earlier_pct"] == -0.01
    assert r["firms"]["amount_millions"] == 4000001.0 and r["households"]["amount_millions"] == 5000001.0                          # 4,000,001.2 and 5,000,001.2 millions are shown as whole millions
    assert [p["amount_millions"] for p in r["firms"]["parts"]] == [1000000.0, 1000000.0, 2000000.0] and [p["amount_millions"] for p in r["households"]["parts"]] == [4000000.0, 500000.0, 500000.0]
    flows = {"firms_short": (900000.0, 3000.6), "firms_mid": (1200000.0, 5000.0), "firms_long": (3400000.0, 2000.0), "house": (5700000.0, 9000.0), "consumer": (840000.0, 2500.0), "other": (670000.0, 1200.0)}
    r = _run(_world(parts=flows))
    assert r["firms"]["parts"][0]["flow_millions"] == 3001.0 and r["firms"]["flow_millions"] == 10001.0                           # flows of 3,000.6 and 10,000.6 millions are shown as 3,001 and 10,001
    r = _run(_world())                                                                                                           # shares of the total: 1,008,000 / 5,860,000 = 17.2014%, 1,380,000 -> 23.5495, 3,472,000 -> 59.2491; two decimals would read 17.20, 23.55 and 59.25
    assert [p["share_pct"] for p in r["firms"]["parts"]] == [17.2, 23.5, 59.2]
    assert [p["share_pct"] for p in r["households"]["parts"]] == [78.6, 12.1, 9.3]                                               # 6,024,000 / 7,667,200 = 78.5654%, 930,000 -> 12.1294, 713,200 -> 9.3020


def test_the_recent_months_are_the_six_newest_in_order_and_the_card_gets_two_growth_rates_for_each():
    r = _run(_world())
    assert [x["month"] for x in r["recent"]] == ["2026-09", "2026-08", "2026-07", "2026-06", "2026-05", "2026-04"] and len(r["recent"]) == 6
    w = _exact_world()
    for k in range(6):
        w[0]["firms.growth"][_back(LAST, k)], w[0]["households.growth"][_back(LAST, k)] = 0.01 * (k + 1), -0.01 * (k + 1)
    r = _run(w)
    assert [(x["month"], x["firms_growth_pct"], x["households_growth_pct"]) for x in r["recent"]] == [("2026-09", 0.01, -0.01), ("2026-08", 0.02, -0.02), ("2026-07", 0.03, -0.03), ("2026-06", 0.04, -0.04), ("2026-05", 0.05, -0.05), ("2026-04", 0.06, -0.06)]


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    for sid in IDS:
        for wrong in (("PC", UNITS[sid][1]), (UNITS[sid][0], "3"), (UNITS[sid][0], "")):
            w = _world()
            w[1][sid] = wrong
            assert _err(w) == f"the ECB reports {NAMES[sid]} in other units than the card assumes", (sid, wrong)
    assert _err(_world()) is None


def test_series_ending_in_different_months_are_refused():
    for sid in IDS:
        w = _world()
        w[0][sid].pop(LAST)
        assert _err(w) == "the bank lending series end in different months", sid
        w = _world()
        w[0][sid][_d(_i(LAST) + 1)] = w[0][sid][LAST]
        assert _err(w) == "the bank lending series end in different months", sid
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


def test_each_amount_must_lie_inside_its_range_in_every_month_of_the_window():
    for e, (lo, hi) in STOCK_LIMITS.items():
        for edge, outside in ((lo, lo - 1.0), (hi, hi + 1.0)):
            w = _world()
            w[0][e + ".stock"][LAST] = edge
            msg = _err(w)
            assert msg is not None and msg.startswith(f"{NAMES[e + '.stock']} changed by"), (e, edge, msg)                      # at the limit it passes the range check; the one-month change it then makes is what speaks
            w = _world()
            w[0][e + ".stock"][LAST] = outside
            assert _err(w) == f"{NAMES[e + '.stock']} is {outside:,.0f} million euro in 2026-09, outside {lo:,.0f} to {hi:,.0f}", (e, outside)
    w = _world()
    w[0]["house.stock"][_back(LAST, 30)] = 15000001.0                                                                          # not only the newest month
    assert _err(w) == f"{NAMES['house.stock']} is 15,000,001 million euro in 2024-03, outside 1,500,000 to 15,000,000"
    w = _world()
    w[0]["house.stock"][_back(LAST, 35)] = 1499999.0                                                                           # the oldest month of the window is looked at too
    assert _err(w) == f"{NAMES['house.stock']} is 1,499,999 million euro in 2023-10, outside 1,500,000 to 15,000,000"


def test_each_growth_rate_must_lie_inside_its_range_in_every_month_of_the_window():
    for e, (lo, hi) in GROWTH_LIMITS.items():
        for edge, outside in ((lo, lo - 0.0001), (hi, hi + 0.0001)):
            w = _world()
            w[0][e + ".growth"][LAST] = edge
            msg = _err(w)
            assert msg is not None and msg.startswith(f"the published growth of {LABEL[e]} in 2026-09 is"), (e, edge, msg)       # at the limit it passes the range check; the flows it no longer follows are what speak
            w = _world()
            w[0][e + ".growth"][LAST] = outside
            assert _err(w) == f"{NAMES[e + '.growth']} is {outside:+.1f}% in 2026-09, outside {lo:+g}% to {hi:+g}%", (e, outside)
    w = _world()
    w[0]["households.growth"][_back(LAST, 30)] = 15.0001                                                                       # an old month is looked at too, though the flows do not reach it
    assert _err(w) == f"{NAMES['households.growth']} is +15.0% in 2024-03, outside -5% to +15%"
    w = _world()
    w[0]["households.growth"][_back(LAST, 35)] = -5.0001
    assert _err(w) == f"{NAMES['households.growth']} is -5.0% in 2023-10, outside -5% to +15%"


def _move(w, e, ratio, back=0):
    """The amount of `e` in the month `back` before the newest becomes `ratio` times the month before it."""
    d = _back(LAST, back)
    s = w[0][e + ".stock"]
    s[d] = s[_back(d, 1)] * ratio
    return d


def test_an_amount_may_change_by_up_to_12_5_percent_in_a_month():
    for ratio in (1.125, 0.875):                                                                                               # exact in binary: a change of exactly +12.5% and -12.5% is allowed
        for e in ENT:
            w = _exact_world()
            _move(w, e, ratio)
            msg = _err(w)
            assert msg is None or not msg.startswith(f"{NAMES[e + '.stock']} changed by"), (e, ratio, msg)                    # a change of the total or of a part alone breaks a sum, which is the later check that speaks
    for ratio, text in ((1.13, "13.0%"), (0.87, "-13.0%")):
        for e in ENT:
            w = _exact_world()
            d = _move(w, e, ratio)
            assert _err(w) == f"{NAMES[e + '.stock']} changed by {text} in {_lab(d)}, outside -12.5% to +12.5%", (e, ratio)
    for back in (20, 30):                                                                                                      # an older month is looked at too, and one among the oldest of the window
        w = _exact_world()
        d = _move(w, "consumer", 1.5, back=back)
        assert _err(w) == f"{NAMES['consumer.stock']} changed by 50.0% in {_lab(d)}, outside -12.5% to +12.5%", back


def _sum_world(e, kind, off, back=0):
    w = _exact_world()
    d = _back(LAST, back)
    w[0][f"{e}.{kind}"][d] += off
    return w, d


def test_a_total_must_equal_the_sum_of_its_parts_within_one_million_euro_for_the_amounts_and_for_the_flows():
    for e, kind in SUM_MSG:
        for off, ok in ((1.0, True), (-1.0, True), (1.5, False), (-1.5, False), (2.0, False)):
            w, d = _sum_world(e, kind, off)
            if ok:
                assert _err(w) is None, (e, kind, off)                                                                          # a gap of exactly one million is allowed
            else:
                assert _err(w) == f"{SUM_MSG[(e, kind)]} in {_lab(d)} (off by {off:+,.0f} million euro)", (e, kind, off)
        for p in PARTS_OF[e]:
            w, d = _sum_world(p, kind, 2.0)
            assert _err(w) == f"{SUM_MSG[(e, kind)]} in {_lab(d)} (off by -2 million euro)", (p, kind)                         # a part too large makes the total too small
    for e, kind in SUM_MSG:
        for back in (17, 35):                                                                                                   # old months are looked at too, the oldest of the window as well
            w, d = _sum_world(e, kind, 5.0, back)
            assert _err(w) == f"{SUM_MSG[(e, kind)]} in {_lab(d)} (off by +5 million euro)", (e, kind, back)


def test_the_published_growth_must_follow_the_flows_and_amounts_within_the_tolerance():
    for e in ENT:
        for sign in (1, -1):
            w = _exact_world()
            w[0][e + ".growth"][LAST] = sign * TOL                                                                              # exactly 2 to the power -4 is allowed, and reported with its sign
            d = _run(w)["detail"]
            assert (d["largest_growth_gap_points"], d["largest_growth_gap_month"], d["largest_growth_gap_series"]) == (sign * TOL, "2026-09", LABEL[e]), (e, sign)
            w = _exact_world()
            w[0][e + ".growth"][LAST] = sign * 0.25
            assert _err(w) == _gap_msg(e, LAST, 0.25), (e, sign)
    w = _exact_world()
    w[0]["firms.growth"][LAST] = TOL + 2 ** -6                                                                                  # 0.078125 points: beyond the tolerance
    assert _err(w) == _gap_msg("firms", LAST, 0.078125)
    w = _exact_world()
    w[0]["firms.growth"][_back(LAST, 23)] = 0.25                                                                                # the oldest compared month is the 24th from the end
    assert _err(w) == _gap_msg("firms", _back(LAST, 23), 0.25)
    w = _exact_world()
    w[0]["firms.growth"][_back(LAST, 24)] = 0.25                                                                                # the 25th from the end has no twelve flows before it in the window: not compared
    assert _err(w) is None
    w = _exact_world()
    w[0]["firms.growth"][_back(LAST, 35)] = 0.25
    assert _err(w) is None


def test_the_largest_growth_gap_keeps_the_earlier_of_two_equal_gaps_and_reports_its_sign():
    w = _exact_world()
    w[0]["firms.growth"][_back(LAST, 10)], w[0]["firms.growth"][_back(LAST, 3)] = 0.03, -0.03                                    # equal in size: the earlier month stays
    d = _run(w)["detail"]
    assert (d["largest_growth_gap_points"], d["largest_growth_gap_month"], d["largest_growth_gap_series"]) == (0.03, _lab(_back(LAST, 10)), "loans to firms")
    w = _exact_world()
    w[0]["firms.growth"][_back(LAST, 3)], w[0]["households.growth"][_back(LAST, 10)] = -0.03, 0.03                               # equal in size across series: the first series stays, though its month is later
    d = _run(w)["detail"]
    assert (d["largest_growth_gap_points"], d["largest_growth_gap_month"], d["largest_growth_gap_series"]) == (-0.03, _lab(_back(LAST, 3)), "loans to firms")
    w = _exact_world()
    w[0]["house.growth"][_back(LAST, 5)] = -0.04
    w[0]["firms_mid.growth"][_back(LAST, 6)] = 0.02
    d = _run(w)["detail"]
    assert (d["largest_growth_gap_points"], d["largest_growth_gap_month"], d["largest_growth_gap_series"]) == (-0.04, _lab(_back(LAST, 5)), LABEL["house"])      # a larger negative gap beats a smaller positive one found earlier
    d = _run(_exact_world())["detail"]
    assert (d["largest_growth_gap_points"], d["largest_growth_gap_month"], d["largest_growth_gap_series"]) == (0.0, None, None)


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    w = _world()
    w[1]["firms.stock"] = ("PC", "6")
    w[0]["firms.flow"].pop(LAST)
    assert _err(w).startswith("the ECB reports loans to firms (amount outstanding) in other units")                            # the units before the end months
    w = _world()
    w[0]["firms.flow"].pop(LAST)
    w[0]["house.stock"].pop(_back(LAST, 5))
    assert _err(w) == "the bank lending series end in different months"                                                         # the end months before the holes
    w = _world()
    w[0]["house.stock"].pop(_back(LAST, 5))
    w[0]["firms.stock"][LAST] = 1.0
    assert _err(w) == f"{NAMES['house.stock']} is missing for {_lab(_back(LAST, 5))}"                                          # the holes before the ranges
    w = _world()
    w[0]["firms.stock"][LAST] = 1.0
    w[0]["house.growth"][LAST] = 99.0
    assert _err(w).startswith(f"{NAMES['firms.stock']} is 1 million euro")                                                      # the ranges of the first series before those of a later one
    w = _world()
    w[0]["firms.growth"][LAST] = 99.0
    _move(w, "firms", 1.5)
    assert _err(w).startswith(f"{NAMES['firms.growth']} is +99.0%")                                                             # a series' growth range before its own monthly change
    w = _world()
    _move(w, "firms", 1.5)
    assert _err(w).startswith(f"{NAMES['firms.stock']} changed by")                                                             # the monthly change before the sum that it also breaks
    w = _world()
    w[0]["house.stock"][LAST] += 10.0
    w[0]["firms.growth"][LAST] += 1.0
    assert _err(w).startswith(SUM_MSG[("households", "stock")])                                                                 # the sums before the growth against the flows
    w = _world()
    w[0]["firms.stock"][LAST] += 5.0
    w[0]["firms.flow"][LAST] += 5.0
    assert _err(w).startswith(SUM_MSG[("firms", "stock")])                                                                      # the amounts' sums before the flows' sums
    w = _world()
    w[0]["households.stock"][LAST] += 5.0
    w[0]["firms.flow"][LAST] += 5.0
    assert _err(w).startswith(SUM_MSG[("firms", "flow")])                                                                       # the firms' sums before the households'
    w = _world()
    w[0]["households.stock"][LAST] += 5.0
    w[0]["households.flow"][LAST] += 5.0
    assert _err(w).startswith(SUM_MSG[("households", "stock")])
    w = _world()
    w[0]["firms.growth"][LAST] += 1.0
    w[0]["other.growth"][LAST] += 1.0
    assert _err(w) == _gap_msg("firms", LAST, 1.0)                                                                              # the first series with a gap speaks


def test_the_real_record_passes_every_check_and_is_pinned():
    assert _err(_real()) is None
    v = _real()[0]
    extremes = {}
    for e in ENT:
        months = sorted(v[e + ".stock"])
        ch = [(100 * (v[e + ".stock"][y] / v[e + ".stock"][x] - 1), y) for x, y in zip(months, months[1:])]
        lo, hi = min(ch), max(ch)
        extremes[e] = (round(lo[0], 3), _lab(lo[1]), round(hi[0], 3), _lab(hi[1]))
    assert extremes == {"firms": (-2.588, "2022-01", 2.477, "2020-03"), "firms_short": (-2.914, "2022-12", 3.391, "2022-08"), "firms_mid": (-0.829, "2023-06", 2.183, "2022-08"), "firms_long": (-0.255, "2022-12", 0.631, "2023-01"),
                        "households": (-0.248, "2022-01", 0.631, "2026-01"), "house": (-0.01, "2023-06", 0.562, "2026-01"), "consumer": (-1.824, "2020-04", 1.614, "2026-01"), "other": (-4.261, "2022-01", 1.756, "2023-01")}     # all inside the bound of 12.5%


def test_the_limits_and_tolerances_are_the_ones_set_from_the_real_record():
    assert S.STOCK_LIMITS == STOCK_LIMITS and S.GROWTH_LIMITS == GROWTH_LIMITS and S.MONTH_MOVE == (-0.125, 0.125)
    assert (S.SUM_TOLERANCE, S.GROWTH_TOLERANCE) == (1.0, 0.0625)
    assert (S.CHECK_MONTHS, S.DEPTH, S.LAST_N, S.GROWTH_WINDOW, S.MIN_WINDOW, S.RECENT_MONTHS, S.OVERDUE_AFTER_DAYS) == (24, 36, 125, 120, 60, 6, 75)
    assert (S.TTL, S.FAIL_TTL, S.TIMEOUT) == (21600.0, 120.0, 45.0)
    assert S.BASE == "https://data-api.ecb.europa.eu/service/data/BSI/" and S.NAMES == NAMES
    assert S.FIRMS == ("firms", "firms_short", "firms_mid", "firms_long") and S.HOUSEHOLDS == ("households", "house", "consumer", "other")
    assert S.ENTITIES == {"firms": ("A20T", "A", "2240", "loans to firms"), "firms_short": ("A20T", "F", "2240", "loans to firms of up to one year"), "firms_mid": ("A20T", "I", "2240", "loans to firms of one to five years"),
                          "firms_long": ("A20T", "J", "2240", "loans to firms of over five years"), "households": ("A20T", "A", "2250", "loans to households"),
                          "house": ("A22T", "A", "2250", "lending to households for house purchase"), "consumer": ("A21T", "A", "2250", "consumer credit"), "other": ("A23T", "A", "2250", "other lending to households")}
    assert S.KINDS == {"stock": ("1", "E", AMOUNT, "amount outstanding"), "flow": ("4", "E", AMOUNT, "monthly flow"), "growth": ("I", "A", GROWTH_UNIT, "annual growth")}
    keys = {"firms": "M.U2.Y.U.A20T.A.{}.U2.2240.Z01.{}", "firms_short": "M.U2.Y.U.A20T.F.{}.U2.2240.Z01.{}", "firms_mid": "M.U2.Y.U.A20T.I.{}.U2.2240.Z01.{}", "firms_long": "M.U2.Y.U.A20T.J.{}.U2.2240.Z01.{}",
            "households": "M.U2.Y.U.A20T.A.{}.U2.2250.Z01.{}", "house": "M.U2.Y.U.A22T.A.{}.U2.2250.Z01.{}", "consumer": "M.U2.Y.U.A21T.A.{}.U2.2250.Z01.{}", "other": "M.U2.Y.U.A23T.A.{}.U2.2250.Z01.{}"}
    assert S.SERIES == {f"{e}.{k}": (keys[e].format(t, sfx), u) for e in ENT for k, t, sfx, u in (("stock", "1", "E", AMOUNT), ("flow", "4", "E", AMOUNT), ("growth", "I", "A", GROWTH_UNIT))}
    assert S.REQUESTS == (("M.U2.Y.U.A20T.A+F+I+J.1+4.U2.2240.Z01.E", tuple(f"{e}.{k}" for e in S.FIRMS for k in ("stock", "flow"))), ("M.U2.Y.U.A20T.A+F+I+J.I.U2.2240.Z01.A", tuple(f"{e}.growth" for e in S.FIRMS)),
                          ("M.U2.Y.U.A20T+A21T+A22T+A23T.A.1+4.U2.2250.Z01.E", tuple(f"{e}.{k}" for e in S.HOUSEHOLDS for k in ("stock", "flow"))), ("M.U2.Y.U.A20T+A21T+A22T+A23T.A.I.U2.2250.Z01.A", tuple(f"{e}.growth" for e in S.HOUSEHOLDS)))
    assert S.PAGE == "https://data-api.ecb.europa.eu/service/data/BSI/M.U2.Y.U.A20T.A.I.U2.2240.Z01.A"
    assert S.SUMS == (("firms", ("firms_short", "firms_mid", "firms_long"), SUM_MSG[("firms", "stock")], SUM_MSG[("firms", "flow")]), ("households", ("house", "consumer", "other"), SUM_MSG[("households", "stock")], SUM_MSG[("households", "flow")]))


def test_the_four_requests_return_exactly_the_24_series_of_the_card_and_each_series_once():
    seen = []
    for key, ids in S.REQUESTS:
        dims = [part.split("+") for part in key.split(".")]
        expanded = {"BSI." + ".".join(c) for c in itertools.product(*dims)}                                                       # the keys an OR-list stands for
        assert expanded == {"BSI." + S.SERIES[i][0] for i in ids}, key
        seen += ids
    assert sorted(seen) == sorted(IDS) and len(seen) == 24


HEAD = "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
OK = "BSI.M.U2.Y.U.A20T.A.I.U2.2240.Z01.A"


def test_the_real_layout_of_a_response_is_read():
    v, units, status = S.parse(F["raw_head"], ("firms.growth",))
    assert v == {"firms.growth": {date(2016, 5, 1): 1.770484252714466, date(2016, 6, 1): 1.9195025089225437}} and units == {"firms.growth": GROWTH_UNIT} and status == {"firms.growth": "A"}
    assert F["raw_head"].startswith("KEY,FREQ,REF_AREA,ADJUSTMENT,BS_REP_SECTOR,BS_ITEM,MATURITY_ORIG,DATA_TYPE,COUNT_AREA,BS_COUNT_SECTOR,CURRENCY_TRANS,BS_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS,")
    assert ",UNIT,UNIT_MULT" in F["raw_head"].split("\n")[0]


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_month_are_an_error():
    text = HEAD + f"{OK},2026-08,0.5,A,PCCH,0\n{OK},26-09,1,A,PCCH,0\n{OK},2026-9,1,A,PCCH,0\n{OK},2026-07,,M,PCCH,0\n{OK},2026-06,n/a,A,PCCH,0\n{OK},2026,1,A,PCCH,0\n{OK},2026-13,1,A,PCCH,0\n{OK},2026-00,1,A,PCCH,0\n"
    text += f"{OK},2026-Q3,1,A,PCCH,0\n{OK},2026-05-01,1,A,PCCH,0\n{OK}, 2026-04,1,A,PCCH,0\n{OK},2026-03x,1,A,PCCH,0\n{OK},2026-02,nan,A,PCCH,0\n{OK},2026-01,inf,A,PCCH,0\n"
    text += "BSI.M.U2.N.U.A20T.A.I.U2.2240.Z01.A,2026-08,0.9,A,PCCH,0\nBSI.Q.U2.Y.U.A20T.A.I.U2.2240.Z01.A,2026-08,0.8,A,PCCH,0\nBSI.M.U2.Y.U.A20T.A.I.U2.2250.Z01.A,2026-08,0.7,A,PCCH,0\n"
    v, units, status = S.parse(text, ("firms.growth",))
    assert v == {"firms.growth": {date(2026, 8, 1): 0.5}} and units == {"firms.growth": GROWTH_UNIT} and status == {"firms.growth": "A"}       # a month with no value, a year, bad months, nan, inf, the unadjusted series, another frequency and another sector are all left out
    padded = HEAD + f"{OK},2026-08,0.5, P , PCCH , 0 \n"
    assert S.parse(padded, ("firms.growth",))[1] == {"firms.growth": GROWTH_UNIT} and S.parse(padded, ("firms.growth",))[2] == {"firms.growth": "P"}          # spaces around a unit or a status are not a different one
    two = HEAD + f"{OK},2026-07,0.1,A,PCCH,0\n{OK},2026-09,0.3,P,PCCH,0\n{OK},2026-08,0.2,A,PCCH,0\n"
    assert S.parse(two, ("firms.growth",))[2] == {"firms.growth": "P"}                                                           # the status is the newest month's, whatever the order of the rows
    two = HEAD + f"{OK},2026-07,0.3,P,PCCH,0\n{OK},2026-08,0.1,A,PCCH,0\n"
    assert S.parse(two, ("firms.growth",))[2] == {"firms.growth": "A"}
    with pytest.raises(ValueError, match=r"firms.growth has two values for 2026-08"):
        S.parse(text + f"{OK},2026-08,0.1,A,PCCH,0\n", ("firms.growth",))
    with pytest.raises(ValueError, match=r"no values for consumer.growth"):
        S.parse(text, ("firms.growth", "consumer.growth"))
    with pytest.raises(ValueError, match=r"the source returned no values for house.growth, other.growth$"):
        S.parse(text, ("house.growth", "other.growth"))


def _text(ids, units=None):
    rows = []
    for sid in ids:
        d = F["series"][sid]
        unit = units.get(sid, d["unit"]) if units else d["unit"]
        rows += [f"BSI.{S.SERIES[sid][0]},{m},{x!r},{st},{unit[0]},{unit[1]}" for m, x, st in zip(d["months"], d["values"], d["status"])]
    return HEAD + "\n".join(rows) + "\n"


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ids_of(path):
    for key, ids in S.REQUESTS:
        if path == "/service/data/BSI/" + key:
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

    svc = S.EuroLending(client=_transport(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["firms"]["growth_pct"] == 4.24 and len(seen) == 4 and r["source"].startswith("European Central Bank")
    assert (r["age_days"], r["freshness"], r["provisional"]) == (49, "CURRENT", True)
    later = asyncio.run(S.EuroLending(client=_transport(_handler)).overview(datetime(2026, 12, 31, 12, tzinfo=timezone.utc)))
    assert (later["age_days"], later["as_of"], later["freshness"]) == (92, "2026-12-31T12:00:00+00:00", "OVERDUE")                # the age is counted to the day given, not to the machine's
    base = "/service/data/BSI/"
    assert {req.url.path: req.url.params["lastNObservations"] for req in seen} == {base + key: "125" for key, ids in S.REQUESTS}
    assert all(req.url.params["format"] == "csvdata" for req in seen) and all(req.headers["user-agent"] == "ATLAS research terminal" for req in seen)
    assert all(req.headers["accept"] == "text/csv" for req in seen)
    assert all("%2B" not in str(req.url) for req in seen) and sum("+" in str(req.url) for req in seen) == 4                      # the + that joins the values of one dimension must reach the ECB as it is
    asyncio.run(svc.overview(NOW))
    assert len(seen) == 4


def test_the_client_the_provider_makes_waits_45_seconds_and_is_closed_afterwards(monkeypatch):
    real, made = httpx.AsyncClient, []

    def factory(**kw):
        made.append(kw)
        c = real(transport=httpx.MockTransport(_handler))
        made.append(c)
        return c

    given = real(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(S.httpx, "AsyncClient", factory)
    r = asyncio.run(S.EuroLending().overview(NOW))
    assert r["available"] is True and made[0] == {"timeout": 45.0} and made[1].is_closed is True
    asyncio.run(S.EuroLending(client=given).overview(NOW))
    assert given.is_closed is False and len(made) == 2                                                                           # a client that was given stays open, and none was made


def test_a_provisional_newest_growth_rate_reaches_the_card():
    key = "BSI." + S.SERIES["firms.growth"][0]
    m, x = F["series"]["firms.growth"]["months"][-1], F["series"]["firms.growth"]["values"][-1]
    row = (f"{key},{m},{x!r},P,PCCH,0", f"{key},{m},{x!r},A,PCCH,0")
    assert row[0] in _text(("firms.growth",)) and row[1] not in _text(("firms.growth",))
    r = asyncio.run(S.EuroLending(client=_transport(lambda req: _handler(req, row))).overview(NOW))
    assert r["available"] is True and r["provisional"] is False


def test_an_unexpected_missing_key_reads_as_unavailable_not_as_a_crash(monkeypatch):
    def boom(*args):
        raise KeyError("firms")

    monkeypatch.setattr(S, "summarize", boom)
    r = asyncio.run(S.EuroLending(client=_transport(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"].startswith("The euro-area bank lending could not be read right now (") and "firms" not in r


def test_a_cached_answer_carries_the_time_of_the_call_that_got_it_from_the_cache():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = S.EuroLending(client=_transport(handler))
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

    svc = S.EuroLending(client=_transport(handler))
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
    r = asyncio.run(S.EuroLending(client=_transport(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "firms" not in r and "households" not in r
    last = F["series"]["firms.growth"]["values"][-1]
    slip = (f"{last!r}", f"{last * 100!r}")                                                                                      # a decimal slip in the newest growth rate: a check failing shows nothing either
    assert slip[0] in _text(("firms.growth",)) and slip[1] not in _text(("firms.growth",))
    r = asyncio.run(S.EuroLending(client=_transport(lambda req: _handler(req, slip))).overview(NOW))
    assert r["available"] is False and "loans to firms (annual growth) is +424.5% in 2026-09, outside -10% to +25%" in r["reason"] and "firms" not in r


def test_a_response_in_other_units_is_refused_and_shows_nothing():
    for sid, what in (("firms.stock", "loans to firms (amount outstanding)"), ("households.growth", "loans to households (annual growth)"), ("consumer.flow", "consumer credit (monthly flow)")):
        r = asyncio.run(S.EuroLending(client=_transport(lambda req, s=sid: _handler(req, units={s: ("EUR", "3")}))).overview(NOW))
        assert r["available"] is False and f"the ECB reports {what} in other units than the card assumes" in r["reason"] and "firms" not in r, sid


@pytest.mark.parametrize("code, words", [(400, "the server answered HTTP 400"), (403, "the server refused the request, HTTP 403"), (404, "the data was not found there, HTTP 404"), (429, "the server is limiting requests, HTTP 429"), (301, "the server answered HTTP 301"), (503, "the server had an error, HTTP 503")])
def test_any_answer_but_200_is_a_failure_that_names_its_code(code, words):
    r = asyncio.run(S.EuroLending(client=_transport(lambda req: httpx.Response(code))).overview(NOW))
    assert r["available"] is False and r["reason"] == f"The euro-area bank lending could not be read right now ({words})" and "firms" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(S.EuroLending(client=_transport(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The euro-area bank lending could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(S.EuroLending(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "firms" not in d
    assert d["reason"] == "Demo mode: the real euro-area bank lending figures are not shown because made-up values would look real."


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-lending")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
