"""US real consumer spending (the Bureau of Economic Analysis' monthly Personal Income and Outlays, via FRED: real spending in chained 2017 dollars, spending in the dollars of the day, and the PCE price index with and without food and energy): parsed from real responses (fetched 2026-11-24 11:22 UTC, the four series from 2007-01 to 2026-09).

The limits are literals, set from the whole real record before any test was written (237 months, 2007-01 to 2026-09): the levels, the largest month-on-month moves (real spending -10.9% in 2020-04 and +8.3% in 2020-05; the price index -1.2% to +1.2% since 1959) and the one identity, real spending times the price index over 100 equals spending in dollars, whose largest real gap is 0.0378% of spending (2021-03). The tolerance is 2 to the power -10 of spending (0.0977%), exact in binary."""
import asyncio
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import usrealspending as R
from atlas_api.app import create_app
from atlas_api.failreason import dates_in_words, fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usrealspending.json").read_text())
TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)

REAL, NOMINAL, PRICE, CORE = "PCEC96", "PCE", "PCEPI", "PCEPILFE"
IDS = (REAL, NOMINAL, PRICE, CORE)
NAME = {REAL: "real consumer spending", NOMINAL: "consumer spending in dollars", PRICE: "PCE price index", CORE: "core PCE price index"}


def mback(d, n):
    i = d.year * 12 + d.month - 1 - n
    return date(i // 12, i % 12 + 1, 1)


def mlab(d):
    return f"{d.year}-{d.month:02d}"


def real():
    return {sid: R.parse(F[sid], sid) for sid in IDS}


def world(n=180, last=LAST, real_level=10000.0, price=100.0, core=100.0, nominal=None):
    """`n` months ending at `last`: real spending, the price index and the core index constant, spending in dollars = real x price / 100, so every check is satisfied exactly."""
    ms = [mback(last, i) for i in range(n - 1, -1, -1)]
    nom = real_level * price / 100.0 if nominal is None else nominal
    return {REAL: {d: real_level for d in ms}, NOMINAL: {d: nom for d in ms}, PRICE: {d: price for d in ms}, CORE: {d: core for d in ms}}


def months_of(data):
    return sorted(data[REAL])


def run(data, today=TODAY):
    return R.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        R.summarize(data, TODAY)


def step(data, sid, start, value):
    """Set `sid` to `value` from `start` on."""
    for d in data[sid]:
        if d >= start:
            data[sid][d] = value
    return data


# ---------------------------------------------------------------- the real record

def test_the_real_record_passes_every_check_and_reports_its_window():
    r = run(real())
    assert r["available"] is True and r["date"] == "2026-09-01" and r["month"] == "2026-09" and r["age_days"] == 84 and r["freshness"] == "CURRENT"
    assert r["detail"] == {"months_checked": 237, "first_month": "2007-01", "last_month": "2026-09", "largest_identity_gap_pct": 0.0378, "largest_identity_gap_month": "2021-03"}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "moves_ok": True, "identity_ok": True}


def test_the_real_headline_figures_are_pinned():
    r = run(real())
    assert r["real"]["level_billions"] == 16977.6 and r["real"]["change_pct"] == 0.02 and r["real"]["change_year_pct"] == 2.54
    assert r["nominal"] == {"level_billions": 22452.8, "change_pct": 0.51, "change_year_pct": 6.28}
    assert r["prices"] == {"index": 132.257, "change_pct": 0.49, "change_year_pct": 3.65, "core_index": 130.902, "core_change_pct": 0.32, "core_change_year_pct": 3.12}
    assert r["year"] == {"nominal_pct": 6.28, "real_pct": 2.54, "prices_pct": 3.65, "core_prices_pct": 3.12, "gap_points": 0.0}
    assert r["real"]["range"] == {"months": 225, "first": "2008-01", "lowest": {"value": -14.66, "month": "2020-04"}, "highest": {"value": 25.45, "month": "2021-04"}, "share_lower_pct": 61}


def test_the_headline_figures_equal_a_plain_python_recomputation_from_the_saved_responses():
    rows = {sid: {} for sid in IDS}
    for sid in IDS:
        for line in F[sid].strip().splitlines()[1:]:
            d, v = line.split(",")
            rows[sid][d] = float(v)
    ds = sorted(rows[REAL])
    last, before, ago = ds[-1], ds[-2], ds[-13]
    r = run(real())
    for key, sid in (("real", REAL), ("nominal", NOMINAL)):
        assert r[key]["level_billions"] == rows[sid][last]
        assert r[key]["change_pct"] == round(100 * (rows[sid][last] / rows[sid][before] - 1), 2)
        assert r[key]["change_year_pct"] == round(100 * (rows[sid][last] / rows[sid][ago] - 1), 2)
    assert r["prices"]["change_year_pct"] == round(100 * (rows[PRICE][last] / rows[PRICE][ago] - 1), 2)
    assert r["prices"]["core_change_year_pct"] == round(100 * (rows[CORE][last] / rows[CORE][ago] - 1), 2)
    # the three yearly changes come from three separate series and fit: (1 + nominal) = (1 + real)(1 + prices)
    n, re_, p = (rows[s][last] / rows[s][ago] - 1 for s in (NOMINAL, REAL, PRICE))
    assert abs((1 + n) / ((1 + re_) * (1 + p)) - 1) < 0.0005


def test_the_six_recent_months_are_oldest_first_with_the_right_changes():
    r = run(real())
    assert r["recent"] == [
        {"month": "2026-04", "real_change_pct": 0.32, "prices_change_pct": 0.44, "nominal_change_pct": 0.76},
        {"month": "2026-05", "real_change_pct": 0.34, "prices_change_pct": 0.44, "nominal_change_pct": 0.78},
        {"month": "2026-06", "real_change_pct": 0.41, "prices_change_pct": -0.1, "nominal_change_pct": 0.31},
        {"month": "2026-07", "real_change_pct": 0.17, "prices_change_pct": 0.06, "nominal_change_pct": 0.23},
        {"month": "2026-08", "real_change_pct": 0.55, "prices_change_pct": 0.32, "nominal_change_pct": 0.87},
        {"month": "2026-09", "real_change_pct": 0.02, "prices_change_pct": 0.49, "nominal_change_pct": 0.51}]


def test_the_source_and_the_page_are_named():
    r = run(real())
    assert r["source"].startswith("U.S. Bureau of Economic Analysis, Personal Income and Outlays") and "FRED" in r["source"] and r["url"] == "https://fred.stlouisfed.org/series/PCEC96"


def test_the_note_says_what_the_numbers_are_and_what_they_are_not():
    n = run(real())["note"]
    assert "chained 2017 dollars" in n and "seasonally adjusted annual rate" in n and "not a market signal or a forecast" in n and "Check line" in n
    assert "Plain checks: the units are the ones assumed and no month is missing; the ranges, the monthly moves and the sum of real spending and prices against spending in dollars are in the Check line." in n


# ---------------------------------------------------------------- age and freshness

@pytest.mark.parametrize("days, fresh", [(100, "CURRENT"), (101, "OVERDUE")])
def test_a_month_turns_overdue_after_100_days_from_its_first_day(days, fresh):
    r = run(world(), LAST + timedelta(days=days))
    assert r["age_days"] == days and r["freshness"] == fresh


def test_the_age_is_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(R.UsRealSpending(client=_client(_handler)).overview(datetime(2027, 1, 15, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 136 and r["freshness"] == "OVERDUE" and r["as_of"] == "2027-01-15T12:00:00+00:00"            # 2026-09-01 to 2027-01-15


# ---------------------------------------------------------------- the months

def test_series_that_end_in_different_months_are_refused_whichever_one_is_short():
    for sid in (NOMINAL, PRICE, CORE):
        data = world()
        del data[sid][LAST]
        refused(data, "the real spending series end in different months")
    data = world()
    del data[REAL][LAST]
    refused(data, "the real spending series end in different months")


def test_a_series_with_a_hole_names_itself_and_the_first_one_in_table_order_is_named():
    mid = mback(LAST, 50)
    for sid in (NOMINAL, PRICE, CORE):
        data = world()
        del data[sid][mid]
        refused(data, f"the {NAME[sid]} series covers different months than real consumer spending")
    data = world()
    for sid in (CORE, PRICE):
        del data[sid][mid]
    refused(data, "the PCE price index series covers different months than real consumer spending")


def test_the_hole_in_real_spending_itself_is_a_skipped_month():
    data = world()
    mid = mback(LAST, 50)
    for sid in IDS:
        del data[sid][mid]
    refused(data, f"the real spending months skip a month after {mlab(mback(mid, 1))}")


def test_a_skipped_month_across_the_turn_of_the_year_is_found_too():
    data = world()
    jan = date(2025, 1, 1)
    for sid in IDS:
        del data[sid][jan]
    refused(data, "the real spending months skip a month after 2024-12")


@pytest.mark.parametrize("bad", [date(2019, 5, 2), date(2019, 5, 31)])
def test_a_date_that_is_not_the_1st_is_refused(bad):
    data = world()
    for sid in IDS:
        data[sid][bad] = data[sid].pop(date(2019, 5, 1))
    refused(data, "a real spending date is not the 1st of a month")


def test_fewer_than_120_months_are_refused_and_120_pass():
    refused(world(n=119), "the real spending record covers 119 months, fewer than the 120 expected")
    assert run(world(n=120))["detail"]["months_checked"] == 120


def test_the_months_of_the_record_come_from_every_series_not_only_the_first_checked():
    data = world(n=130)
    assert run(data)["detail"]["first_month"] == mlab(mback(LAST, 129))


# ---------------------------------------------------------------- ranges (both edges, every series)

EDGES = [
    # series, a world whose value sits exactly on the limit, the same world one step outside, the refusal text of that step
    (REAL, dict(real_level=3000.0, price=100.0), 2999.9, "the real consumer spending of 2,999.9 billion in {m} is outside 3,000 to 60,000"),
    (REAL, dict(real_level=60000.0, price=100.0), 60000.1, "the real consumer spending of 60,000.1 billion in {m} is outside 3,000 to 60,000"),
    (NOMINAL, dict(real_level=3000.0, price=5.0), 149.9, "the consumer spending in dollars of 149.9 billion in {m} is outside 150 to 80,000"),
    (NOMINAL, dict(real_level=40000.0, price=200.0), 80000.1, "the consumer spending in dollars of 80,000.1 billion in {m} is outside 150 to 80,000"),
    (PRICE, dict(real_level=6000.0, price=5.0), 4.9, "the PCE price index of 4.9 in {m} is outside 5 to 500"),
    (PRICE, dict(real_level=6000.0, price=500.0), 500.1, "the PCE price index of 500.1 in {m} is outside 5 to 500"),
    (CORE, dict(real_level=10000.0, price=100.0, core=5.0), 4.9, "the core PCE price index of 4.9 in {m} is outside 5 to 500"),
    (CORE, dict(real_level=10000.0, price=100.0, core=500.0), 500.1, "the core PCE price index of 500.1 in {m} is outside 5 to 500"),
]


@pytest.mark.parametrize("sid, kw, outside, text", EDGES)
def test_each_limit_is_pinned_at_both_edges(sid, kw, outside, text):
    data = world(**kw)
    assert run(data)["available"] is True                                           # exactly on the limit passes
    first = months_of(data)[0]
    data[sid][first] = outside
    refused(data, text.format(m=mlab(first)))


@pytest.mark.parametrize("sid", IDS)
def test_a_range_is_checked_in_the_oldest_and_the_newest_month_not_only_in_the_middle(sid):
    for when in (mback(LAST, 179), mback(LAST, 90), LAST):
        data = world()
        data[sid][when] = 1.0                                                          # far below every lower limit; the range check comes before the moves and the sum
        with pytest.raises(ValueError, match=f"^the {re.escape(NAME[sid])} of 1 .*in {mlab(when)} is outside"):
            R.summarize(data, TODAY)


def test_the_numbers_in_a_refusal_are_written_with_thousands_separators_and_no_trailing_zero():
    data = world()
    data[NOMINAL][LAST] = 123456.0
    refused(data, "the consumer spending in dollars of 123,456 billion in 2026-09 is outside 150 to 80,000")


def test_ranges_are_checked_series_by_series_in_the_order_of_the_table_and_the_oldest_month_first():
    data = world()
    for sid in (CORE, PRICE, NOMINAL, REAL):
        data[sid][mback(LAST, 3)] = 1.0
        data[sid][mback(LAST, 100)] = 1.0
    refused(data, f"the real consumer spending of 1 billion in {mlab(mback(LAST, 100))} is outside 3,000 to 60,000")
    del data[REAL][mback(LAST, 100)]                                                  # take real spending out of the way: the next series in the table is named
    for sid in (NOMINAL, PRICE, CORE):
        del data[sid][mback(LAST, 100)]
    refused(data, f"the real spending months skip a month after {mlab(mback(LAST, 101))}")


def test_the_minimum_count_of_months_comes_before_the_ranges():
    data = world(n=119)
    data[REAL][LAST] = 1.0
    refused(data, "the real spending record covers 119 months, fewer than the 120 expected")


# ---------------------------------------------------------------- moves in a month

MOVES = [
    # series, the step at the 2019-05 month (value from then on), what else moves with it so the sum still holds, the refusal text one step outside
    (REAL, 12500.0, {NOMINAL: 12500.0}, 12500.1, {NOMINAL: 12500.1}, "the real consumer spending moved +25.0% in 2019-05, outside -25 to 25"),
    (REAL, 7500.0, {NOMINAL: 7500.0}, 7499.9, {NOMINAL: 7499.9}, "the real consumer spending moved -25.0% in 2019-05, outside -25 to 25"),
    (NOMINAL, 12500.0, {REAL: 12500.0}, 12500.1, {REAL: 12500.0}, "the consumer spending in dollars moved +25.0% in 2019-05, outside -25 to 25"),
    (NOMINAL, 7500.0, {REAL: 7500.0}, 7499.9, {REAL: 7500.0}, "the consumer spending in dollars moved -25.0% in 2019-05, outside -25 to 25"),
    (PRICE, 105.0, {NOMINAL: 10500.0}, 105.01, {NOMINAL: 10501.0}, "the PCE price index moved +5.0% in 2019-05, outside -5 to 5"),
    (PRICE, 95.0, {NOMINAL: 9500.0}, 94.99, {NOMINAL: 9499.0}, "the PCE price index moved -5.0% in 2019-05, outside -5 to 5"),
    (CORE, 105.0, {}, 105.01, {}, "the core PCE price index moved +5.0% in 2019-05, outside -5 to 5"),
    (CORE, 95.0, {}, 94.99, {}, "the core PCE price index moved -5.0% in 2019-05, outside -5 to 5"),
]
MAY = date(2019, 5, 1)


@pytest.mark.parametrize("sid, edge, also, outside, also_outside, text", MOVES)
def test_each_monthly_move_limit_is_pinned_at_both_edges(sid, edge, also, outside, also_outside, text):
    ok = world()
    for s, v in {sid: edge, **also}.items():
        step(ok, s, MAY, v)
    assert run(ok)["available"] is True                                             # a move of exactly the limit passes
    bad = world()
    for s, v in {sid: outside, **also_outside}.items():
        step(bad, s, MAY, v)
    refused(bad, text)


def test_the_move_is_measured_from_the_month_before_and_named_by_the_later_month():
    data = world()
    step(data, REAL, date(2019, 5, 1), 20000.0)
    step(data, NOMINAL, date(2019, 5, 1), 20000.0)
    refused(data, "the real consumer spending moved +100.0% in 2019-05, outside -25 to 25")


def test_a_one_month_spike_is_a_move_up_and_a_move_back_and_the_first_is_named():
    data = world()
    data[REAL][MAY] = data[NOMINAL][MAY] = 20000.0
    refused(data, "the real consumer spending moved +100.0% in 2019-05, outside -25 to 25")


def test_moves_are_checked_series_by_series_in_table_order_and_the_oldest_month_first():
    data = world()
    step(data, CORE, date(2019, 3, 1), 150.0)
    step(data, PRICE, date(2019, 4, 1), 150.0)
    step(data, NOMINAL, date(2019, 5, 1), 20000.0)
    step(data, REAL, date(2019, 6, 1), 20000.0)
    refused(data, "the real consumer spending moved +100.0% in 2019-06, outside -25 to 25")
    step(data, REAL, date(2019, 6, 1), 10000.0)
    refused(data, "the consumer spending in dollars moved +100.0% in 2019-05, outside -25 to 25")


def test_a_move_is_judged_at_four_decimals_so_the_last_bit_of_a_float_never_decides():
    ok = world()
    step(ok, PRICE, MAY, 105.00004)
    step(ok, NOMINAL, MAY, 10500.004)                                                # +5.00004% rounds to 5.0 and passes
    assert run(ok)["available"] is True
    bad = world()
    step(bad, PRICE, MAY, 105.00006)
    step(bad, NOMINAL, MAY, 10500.006)                                               # +5.00006% rounds to 5.0001 and does not
    refused(bad, "the PCE price index moved +5.0% in 2019-05, outside -5 to 5")


def test_a_change_that_rounds_to_zero_from_below_is_zero_and_not_negative_zero():
    data = world()
    data[REAL][LAST] = 9999.9                                                        # -0.001% on the month before and on a year earlier
    r = run(data)
    for value in (r["real"]["change_pct"], r["real"]["change_year_pct"], r["year"]["real_pct"], r["recent"][-1]["real_change_pct"]):
        assert value == 0.0 and math.copysign(1.0, value) == 1.0 and json.dumps(value) == "0.0"


def test_the_moves_come_before_the_sum():
    data = world()
    step(data, REAL, MAY, 20000.0)                                                   # the sum is also broken from 2019-05 on, but the move is named
    refused(data, "the real consumer spending moved +100.0% in 2019-05, outside -25 to 25")


# ---------------------------------------------------------------- the one identity: real x price / 100 = spending in dollars, to 2 to the power -10

@pytest.mark.parametrize("when", [mback(LAST, 179), mback(LAST, 90), LAST])
def test_real_spending_times_prices_must_equal_spending_in_dollars_within_2_to_the_minus_10(when):
    ok = world()
    ok[REAL][when] = 10009.765625                                                    # 10,000 + 10,000 x 2**-10, exactly the tolerance
    assert run(ok)["available"] is True
    ok = world()
    ok[REAL][when] = 9990.234375                                                     # and exactly the tolerance below
    assert run(ok)["available"] is True
    bad = world()
    bad[REAL][when] = 10009.766
    refused(bad, f"real spending times prices is 0.098% off spending in dollars in {mlab(when)}, over 0.098%")
    bad = world()
    bad[REAL][when] = 9990.234
    refused(bad, f"real spending times prices is 0.098% off spending in dollars in {mlab(when)}, over 0.098%")


def test_the_price_index_and_spending_in_dollars_are_both_in_the_sum():
    for sid, v in ((PRICE, 101.0), (NOMINAL, 10100.0)):
        data = world()
        data[sid][LAST] = v
        refused(data, "real spending times prices is 1.000% off spending in dollars in 2026-09, over 0.098%" if sid == PRICE else "real spending times prices is 0.990% off spending in dollars in 2026-09, over 0.098%")


def test_the_core_index_is_not_in_the_sum():
    data = world()
    data[CORE][LAST] = 101.0                                                         # a move of +1% in the last month, inside every limit
    assert run(data)["available"] is True


def test_the_tolerance_is_relative_to_spending_in_dollars():
    ok = world(real_level=20000.0)
    ok[REAL][LAST] = 20019.53125                                                     # 20,000 x 2**-10 = 19.53125 above
    assert run(ok)["available"] is True
    bad = world(real_level=20000.0)
    bad[REAL][LAST] = 20019.54
    refused(bad, "real spending times prices is 0.098% off spending in dollars in 2026-09, over 0.098%")


def test_the_largest_gap_is_the_largest_not_the_first_or_the_last_and_names_its_month():
    data = world()
    data[REAL][mback(LAST, 100)] = 10001.0
    data[REAL][mback(LAST, 50)] = 10005.0
    data[REAL][mback(LAST, 10)] = 10002.0
    d = run(data)["detail"]
    assert d["largest_identity_gap_pct"] == 0.05 and d["largest_identity_gap_month"] == mlab(mback(LAST, 50))


def test_the_largest_gap_is_rounded_to_four_decimals_and_a_gap_of_zero_names_no_month_oddly():
    data = world()
    data[REAL][LAST] = 10003.3333
    assert run(data)["detail"]["largest_identity_gap_pct"] == 0.0333
    d = run(world())["detail"]
    assert d["largest_identity_gap_pct"] == 0.0 and d["largest_identity_gap_month"] == mlab(mback(LAST, 179))


def test_the_first_month_of_equal_gaps_is_named():
    data = world()
    data[REAL][mback(LAST, 20)] = data[REAL][mback(LAST, 10)] = 10002.0
    assert run(data)["detail"]["largest_identity_gap_month"] == mlab(mback(LAST, 20))


def test_a_wrong_series_in_place_of_the_price_index_is_caught_in_the_real_record():
    data = real()
    data[PRICE] = dict(data[CORE])                                                   # the core index instead of the headline index: 1.0% off in 2026-09
    with pytest.raises(ValueError, match=r"^real spending times prices is \d+\.\d{3}% off spending in dollars in \d{4}-\d\d, over 0\.098%$"):
        R.summarize(data, TODAY)


# ---------------------------------------------------------------- how the figures are worked

def trend_world(n=180):
    """A world with changing figures: real spending cycles through seven levels, prices rise 0.25% a month; spending in dollars is their product, rounded to 0.1 like the source."""
    ms = [mback(LAST, i) for i in range(n - 1, -1, -1)]
    data = {REAL: {}, NOMINAL: {}, PRICE: {}, CORE: {}}
    for k, d in enumerate(ms):
        r = 10000.0 * (1 + 0.01 * (k % 7))
        p = round(100.0 * 1.0025 ** k, 3)
        data[REAL][d], data[PRICE][d], data[CORE][d] = r, p, round(100.0 * 1.002 ** k, 3)
        data[NOMINAL][d] = round(r * p / 100.0, 1)
    return data


def test_the_month_and_year_changes_use_the_right_months_and_are_rounded_to_two_decimals():
    data = trend_world()
    r = run(data)
    ms = months_of(data)
    for key, sid in (("real", REAL), ("nominal", NOMINAL)):
        assert r[key]["change_pct"] == round(100 * (data[sid][ms[-1]] / data[sid][ms[-2]] - 1), 2)
        assert r[key]["change_year_pct"] == round(100 * (data[sid][ms[-1]] / data[sid][ms[-13]] - 1), 2)
    assert r["prices"]["change_pct"] == round(100 * (data[PRICE][ms[-1]] / data[PRICE][ms[-2]] - 1), 2) == 0.25
    assert r["prices"]["core_change_pct"] == round(100 * (data[CORE][ms[-1]] / data[CORE][ms[-2]] - 1), 2) == 0.2
    assert r["prices"]["change_year_pct"] == round(100 * (data[PRICE][ms[-1]] / data[PRICE][ms[-13]] - 1), 2) == 3.04
    assert r["prices"]["core_change_year_pct"] == round(100 * (data[CORE][ms[-1]] / data[CORE][ms[-13]] - 1), 2) == 2.43
    assert r["prices"]["index"] == data[PRICE][ms[-1]] and r["prices"]["core_index"] == data[CORE][ms[-1]]


def test_the_yearly_decomposition_uses_the_same_four_series_and_reports_its_gap_unsigned_to_three_decimals():
    data = trend_world()
    y = run(data)["year"]
    ms = months_of(data)
    n, re_, p = (data[s][ms[-1]] / data[s][ms[-13]] - 1 for s in (NOMINAL, REAL, PRICE))
    assert y["nominal_pct"] == round(100 * n, 2) and y["real_pct"] == round(100 * re_, 2) and y["prices_pct"] == round(100 * p, 2)
    assert y["core_prices_pct"] == round(100 * (data[CORE][ms[-1]] / data[CORE][ms[-13]] - 1), 2)
    assert y["gap_points"] == round(abs(100 * ((1 + n) / ((1 + re_) * (1 + p)) - 1)), 3) and y["gap_points"] >= 0


def test_a_negative_gap_is_reported_as_a_positive_one():
    data = trend_world()
    ms = months_of(data)
    data[NOMINAL][ms[-1]] = round(data[NOMINAL][ms[-1]] * 0.9995, 1)                 # a little under the product in the newest month, inside the tolerance
    assert run(data)["year"]["gap_points"] > 0


def test_the_range_is_over_the_year_on_year_growth_of_real_spending_and_counts_only_strictly_lower_months():
    data = trend_world()
    ms = months_of(data)
    growth = {d: 100 * (data[REAL][d] / data[REAL][mback(d, 12)] - 1) for d in ms[12:]}
    rg = run(data)["real"]["range"]
    assert rg["months"] == len(growth) == 168 and rg["first"] == mlab(ms[12])
    assert rg["lowest"] == {"value": round(min(growth.values()), 2), "month": mlab(min(growth, key=growth.get))}
    assert rg["highest"] == {"value": round(max(growth.values()), 2), "month": mlab(max(growth, key=growth.get))}
    assert rg["share_lower_pct"] == round(100 * sum(1 for v in growth.values() if v < growth[ms[-1]]) / len(growth))


def test_the_six_recent_months_have_their_own_changes_and_the_oldest_comes_first():
    data = trend_world()
    ms = months_of(data)
    rec = run(data)["recent"]
    assert [x["month"] for x in rec] == [mlab(m) for m in ms[-6:]]
    for x, m in zip(rec, ms[-6:]):
        assert x["real_change_pct"] == round(100 * (data[REAL][m] / data[REAL][mback(m, 1)] - 1), 2)
        assert x["prices_change_pct"] == round(100 * (data[PRICE][m] / data[PRICE][mback(m, 1)] - 1), 2)
        assert x["nominal_change_pct"] == round(100 * (data[NOMINAL][m] / data[NOMINAL][mback(m, 1)] - 1), 2)


def test_the_level_is_the_newest_months_not_an_earlier_one():
    data = trend_world()
    ms = months_of(data)
    r = run(data)
    assert r["real"]["level_billions"] == data[REAL][ms[-1]] and r["nominal"]["level_billions"] == data[NOMINAL][ms[-1]]


def test_the_record_must_be_long_enough_for_a_year_on_year_range():
    r = run(world(n=120))
    assert r["real"]["range"]["months"] == 108 and r["real"]["range"]["share_lower_pct"] == 0


def test_a_series_with_an_extra_month_covers_different_months_too():
    for sid in (NOMINAL, PRICE, CORE):
        data = world()
        first = months_of(data)[0]
        data[sid][mback(first, 1)] = data[sid][first]                                  # one month before the others start: the same months are required, not just at least the same
        refused(data, f"the {NAME[sid]} series covers different months than real consumer spending")


def test_a_move_is_checked_in_the_first_pair_of_months_and_in_the_last():
    data = world()
    ms = months_of(data)
    for sid in (REAL, NOMINAL):
        step(data, sid, ms[1], 20000.0)                                                # the only move is from the first month to the second
    refused(data, f"the real consumer spending moved +100.0% in {mlab(ms[1])}, outside -25 to 25")
    data = world()
    for sid in (REAL, NOMINAL):
        data[sid][LAST] = 20000.0                                                      # and the only move here is into the newest month
    refused(data, "the real consumer spending moved +100.0% in 2026-09, outside -25 to 25")


def test_the_yearly_gap_is_reported_to_three_decimals():
    data = world()
    data[NOMINAL][LAST] = 10002.89                                                     # 0.0289% above real x prices (inside the sum's tolerance); real spending and prices did not move over the year
    assert run(data)["year"]["gap_points"] == 0.029


# ---------------------------------------------------------------- refusals fit the visible 110 characters

def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    texts = [t.format(m="2026-09") for _s, _k, _o, t in EDGES]
    texts += [m[5] for m in MOVES]
    texts += ["real spending times prices is 0.098% off spending in dollars in 2026-09, over 0.098%",
              "the PCE price index series covers different months than real consumer spending",
              "the real spending record covers 119 months, fewer than the 120 expected", "the real spending months skip a month after 2024-12"]
    for text in texts:
        assert len(text) <= 110, text
        assert fail_reason(ValueError(text)) == f"the data failed a check: {dates_in_words(text)}"


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_four_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = R.UsRealSpending(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["real"]["change_year_pct"] == 2.54 and n["n"] == 4 and r["demo"] is False and r["as_of"] == NOW.isoformat()
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 4


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(R.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = R.UsRealSpending(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 4
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 4                                                               # still the failure from the cache
    clock["t"] += 1
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 8       # exactly two minutes on it asks again
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 8                                                               # one second short of six hours: kept
    clock["t"] += 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 12                                                              # exactly six hours on: asked again


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = R.UsRealSpending(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(R.UsRealSpending(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US real consumer spending could not be read right now (the server had an error, HTTP 503)" and "real" not in r and "prices" not in r
    r = asyncio.run(R.UsRealSpending(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]                      # anything but 200 is a failure


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == CORE else _handler(req)

    r = asyncio.run(R.UsRealSpending(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "real" not in r and "year" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    bad = dict(F)
    bad[PRICE] = F[PRICE].replace("2026-09-01,132.257", "2026-09-01,1322.57")        # a decimal slip that stays inside the 5 to 500 range? no: it is outside, so the range names it
    r = asyncio.run(R.UsRealSpending(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US real consumer spending could not be read right now (the data failed a check: the PCE price index of 1,322.6 in September 2026 is outside 5 to 500)" and "real" not in r
    bad = dict(F)
    bad[REAL] = F[REAL].replace("2026-09-01,16977.6", "2026-09-01,17977.6")            # a digit slip that stays inside every range and move: only the sum finds it
    r = asyncio.run(R.UsRealSpending(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US real consumer spending could not be read right now (the data failed a check: real spending times prices is 5.896% off spending in dollars in September 2026, over 0.098%)"
    bad = dict(F)
    bad[NOMINAL] = F[NOMINAL].replace("2026-09-01,22452.8", "2026-09-01,x")
    r = asyncio.run(R.UsRealSpending(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "a PCE row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(R.UsRealSpending(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US real consumer spending could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("PCE")

    monkeypatch.setattr(R, "summarize", boom)
    r = asyncio.run(R.UsRealSpending(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US real consumer spending could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(R.UsRealSpending(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US consumer spending figures are not shown because made-up values would look real." and "real" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/us-real-spending")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_card_is_refreshed_with_the_other_macro_sources():
    jobs = (Path(__file__).parent.parent / "atlas_api" / "sched" / "jobs.py").read_text(encoding="utf-8")
    app = (Path(__file__).parent.parent / "atlas_api" / "app.py").read_text(encoding="utf-8")
    assert '"us_real_spending"' in jobs and '"us_real_spending": us_real_spending' in app and "us_real_spending = UsRealSpending(demo=demo)" in app


def test_each_request_asks_for_one_series_from_2007_with_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(R.UsRealSpending(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)             # never a combined request: FRED applies one start date to the first series only
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert {req.url.params["cosd"] for req in seen} == {"2007-01-01"}


def test_a_client_made_here_waits_25_seconds_and_is_closed_and_one_given_is_left_open(monkeypatch):
    seen = {"closed": False}

    class Fake:
        def __init__(self, **kw):
            seen["timeout"] = kw.get("timeout")

        async def get(self, url, params=None):
            return httpx.Response(200, text=F[params["id"]])

        async def aclose(self):
            seen["closed"] = True

    monkeypatch.setattr(R.httpx, "AsyncClient", Fake)
    r = asyncio.run(R.UsRealSpending().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(R.UsRealSpending(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_module_says_why_each_series_is_asked_for_alone_and_what_it_does_not_check():
    doc = R.__doc__
    assert "ALONE" in doc and "chain-type" in doc and "NOT checked" in doc and "approximate" in doc
