"""US international trade in goods and services (Census Bureau and Bureau of Economic Analysis, balance-of-payments basis, via FRED: exports, imports and the balance for the total, for goods and for services, nine monthly series): parsed from real responses (fetched 2026-11-24 14:21 UTC, 417 months from 1992-01 to 2026-09).

The limits are literals, set from the whole real record before any test was written: the levels (9,688 to 426,558 million dollars), the balances (total -132,983 to -831, goods -159,453 to -5,593, services +4,298 to +32,455), the largest month-on-month moves of the six level series (-25.41% goods exports 2020-04, +15.04% goods exports 2020-06) and the six sums, whose real largest gap is 1 million dollars in every one (three published figures each rounded to a million: the arithmetic bound is 1.5, exact in binary)."""
import asyncio
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import ustrade as T
from atlas_api.app import create_app
from atlas_api.failreason import dates_in_words, fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "fred_ustrade.json").read_text())
TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)
MAY = date(2019, 5, 1)

TEXP, TIMP, TBAL = "BOPTEXP", "BOPTIMP", "BOPGSTB"
GEXP, GIMP, GBAL = "BOPGEXP", "BOPGIMP", "BOPGTB"
SEXP, SIMP, SBAL = "BOPSEXP", "BOPSIMP", "BOPSTB"
IDS = (TEXP, TIMP, TBAL, GEXP, GIMP, GBAL, SEXP, SIMP, SBAL)
NAME = {TEXP: "total exports", TIMP: "total imports", TBAL: "total balance", GEXP: "goods exports", GIMP: "goods imports", GBAL: "goods balance",
        SEXP: "services exports", SIMP: "services imports", SBAL: "services balance"}
BASE = dict(ge=200_000.0, gi=400_000.0, se=100_000.0, si=100_000.0)


def mback(d, n):
    i = d.year * 12 + d.month - 1 - n
    return date(i // 12, i % 12 + 1, 1)


def mlab(d):
    return f"{d.year}-{d.month:02d}"


def real():
    return {sid: T.parse(F[sid], sid) for sid in IDS}


def build(ge, gi, se, si):
    """All nine series from four primary levels, so that every one of the six sums holds exactly."""
    return {GEXP: ge, GIMP: gi, SEXP: se, SIMP: si, TEXP: ge + se, TIMP: gi + si, GBAL: ge - gi, SBAL: se - si, TBAL: (ge + se) - (gi + si)}


def world(n=180, last=LAST, **primaries):
    """`n` months ending at `last`, every figure constant (default: goods 200,000 sold and 400,000 bought, services 100,000 and 100,000, so the total balance is -200,000)."""
    p = {**BASE, **primaries}
    return {sid: {mback(last, i): v for i in range(n - 1, -1, -1)} for sid, v in build(**p).items()}


def world_step(start=MAY, n=180, last=LAST, **new):
    """Like `world`, but from `start` on the primary levels named in `new` take their new value (and every sum still holds)."""
    data = {sid: {} for sid in IDS}
    for i in range(n - 1, -1, -1):
        d = mback(last, i)
        for sid, v in build(**{**BASE, **(new if d >= start else {})}).items():
            data[sid][d] = v
    return data


def bump(data, when, **offsets):
    """Add the offsets (keyed by the series' short names te ti tb ge gi gb se si sb) to one month."""
    short = {"te": TEXP, "ti": TIMP, "tb": TBAL, "ge": GEXP, "gi": GIMP, "gb": GBAL, "se": SEXP, "si": SIMP, "sb": SBAL}
    for k, v in offsets.items():
        data[short[k]][when] += v
    return data


def months_of(data):
    return sorted(data[TEXP])


def run(data, today=TODAY):
    return T.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        T.summarize(data, TODAY)


def not_a_range_refusal(data):
    try:
        T.summarize(data, TODAY)
    except ValueError as e:
        assert "is outside" not in str(e), str(e)


# ---------------------------------------------------------------- the real record

def test_the_real_record_passes_every_check_and_reports_its_window():
    r = run(real())
    assert r["available"] is True and r["date"] == "2026-09-01" and r["month"] == "2026-09" and r["age_days"] == 84 and r["freshness"] == "CURRENT"
    assert r["detail"] == {"months_checked": 417, "first_month": "1992-01", "last_month": "2026-09", "largest_gap_million": 1.0, "largest_gap_month": "1992-07"}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "moves_ok": True, "identity_ok": True}


def test_the_real_headline_figures_are_pinned():
    r = run(real())
    assert r["total"] == {"exports": 321.511, "imports": 426.558, "balance": -105.047, "balance_change": 0.69, "balance_year_ago": -59.392,
                          "exports_change_year_pct": 9.97, "imports_change_year_pct": 21.27,
                          "range": {"months": 417, "first": "1992-01", "lowest": {"value": -132.98, "month": "2025-03"}, "highest": {"value": -0.83, "month": "1992-02"}, "share_lower_pct": 1}}
    assert r["goods"] == {"exports": 210.968, "imports": 346.879, "balance": -135.911, "balance_change": 0.716, "balance_year_ago": -87.897,
                          "exports_change_year_pct": 13.14, "imports_change_year_pct": 26.43}
    assert r["services"] == {"exports": 110.543, "imports": 79.678, "balance": 30.865, "balance_change": -0.026, "balance_year_ago": 28.505,
                             "exports_change_year_pct": 4.4, "imports_change_year_pct": 2.97}


def test_the_headline_figures_equal_a_plain_python_recomputation_from_the_saved_responses():
    rows = {sid: {} for sid in IDS}
    for sid in IDS:
        for line in F[sid].strip().splitlines()[1:]:
            d, v = line.split(",")
            rows[sid][d] = float(v)
    ds = sorted(rows[TEXP])
    last, before, ago = ds[-1], ds[-2], ds[-13]
    r = run(real())
    for key, (e, i, b) in (("total", (TEXP, TIMP, TBAL)), ("goods", (GEXP, GIMP, GBAL)), ("services", (SEXP, SIMP, SBAL))):
        g = r[key]
        assert g["exports"] == rows[e][last] / 1000 and g["imports"] == rows[i][last] / 1000 and g["balance"] == rows[b][last] / 1000
        assert g["balance_change"] == round((rows[b][last] - rows[b][before]) / 1000, 3) and g["balance_year_ago"] == rows[b][ago] / 1000
        assert g["exports_change_year_pct"] == round(100 * (rows[e][last] / rows[e][ago] - 1), 2) and g["imports_change_year_pct"] == round(100 * (rows[i][last] / rows[i][ago] - 1), 2)
        assert abs(rows[b][last] - (rows[e][last] - rows[i][last])) <= 1                       # the sum holds to the million in the newest month
    lows = sum(1 for d in ds if rows[TBAL][d] < rows[TBAL][last])
    assert r["total"]["range"]["share_lower_pct"] == round(100 * lows / len(ds))


def test_the_six_recent_months_are_oldest_first_with_their_own_figures():
    r = run(real())
    assert r["recent"] == [
        {"month": "2026-04", "exports": 329.893, "imports": 382.776, "balance": -52.883},
        {"month": "2026-05", "exports": 319.979, "imports": 395.731, "balance": -75.752},
        {"month": "2026-06", "exports": 317.335, "imports": 388.517, "balance": -71.182},
        {"month": "2026-07", "exports": 310.723, "imports": 403.55, "balance": -92.826},
        {"month": "2026-08", "exports": 315.666, "imports": 421.403, "balance": -105.737},
        {"month": "2026-09", "exports": 321.511, "imports": 426.558, "balance": -105.047}]


def test_the_source_and_the_page_are_named():
    r = run(real())
    assert r["source"].startswith("U.S. Census Bureau and U.S. Bureau of Economic Analysis, U.S. International Trade in Goods and Services") and "FRED" in r["source"]
    assert r["url"] == "https://fred.stlouisfed.org/series/BOPGSTB"


def test_the_note_says_what_the_numbers_are_and_what_they_are_not():
    n = run(real())["note"]
    assert "seasonally adjusted" in n and "balance-of-payments basis" in n and "not a market signal or a forecast" in n and "Check line" in n
    assert "A negative balance is a deficit" in n
    assert "Plain checks: the units are the ones assumed and no month is missing; the ranges, the monthly moves and the six sums (each balance against its exports and imports, and the totals against goods plus services) are in the Check line." in n


# ---------------------------------------------------------------- age and freshness

@pytest.mark.parametrize("days, fresh", [(105, "CURRENT"), (106, "OVERDUE")])
def test_a_month_turns_overdue_after_105_days_from_its_first_day(days, fresh):
    r = run(world(), LAST + timedelta(days=days))
    assert r["age_days"] == days and r["freshness"] == fresh


def test_the_age_is_worked_from_the_time_of_the_question_not_from_the_clock():
    r = asyncio.run(T.UsTrade(client=_client(_handler)).overview(datetime(2027, 1, 15, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 136 and r["freshness"] == "OVERDUE" and r["as_of"] == "2027-01-15T12:00:00+00:00"            # 2026-09-01 to 2027-01-15


# ---------------------------------------------------------------- the months

def test_series_that_end_in_different_months_are_refused_whichever_one_is_short():
    for sid in IDS:
        data = world()
        del data[sid][LAST]
        refused(data, "the trade series end in different months")


def test_a_series_with_a_hole_names_itself_and_the_first_one_in_table_order_is_named():
    mid = mback(LAST, 50)
    for sid in IDS[1:]:
        data = world()
        del data[sid][mid]
        refused(data, f"the {NAME[sid]} series covers different months than total exports")
    data = world()
    for sid in (SBAL, GIMP, TBAL):
        del data[sid][mid]
    refused(data, "the total balance series covers different months than total exports")


def test_the_hole_in_every_series_is_a_skipped_month():
    data = world()
    mid = mback(LAST, 50)
    for sid in IDS:
        del data[sid][mid]
    refused(data, f"the trade months skip a month after {mlab(mback(mid, 1))}")


def test_a_skipped_month_across_the_turn_of_the_year_is_found_too():
    data = world()
    for sid in IDS:
        del data[sid][date(2025, 1, 1)]
    refused(data, "the trade months skip a month after 2024-12")


def test_a_skipped_month_is_found_in_the_first_pair_of_months_and_in_the_last():
    for hole, after in ((mback(LAST, 178), mback(LAST, 179)), (mback(LAST, 1), mback(LAST, 2))):        # the month after the oldest one, and the month before the newest one
        data = world()
        for sid in IDS:
            del data[sid][hole]
        refused(data, f"the trade months skip a month after {mlab(after)}")


@pytest.mark.parametrize("bad", [date(2019, 5, 2), date(2019, 5, 31)])
def test_a_date_that_is_not_the_1st_is_refused(bad):
    data = world()
    for sid in IDS:
        data[sid][bad] = data[sid].pop(date(2019, 5, 1))
    refused(data, "a trade date is not the 1st of a month")


def test_fewer_than_120_months_are_refused_and_120_pass():
    refused(world(n=119), "the trade record covers 119 months, fewer than the 120 expected")
    assert run(world(n=120))["detail"]["months_checked"] == 120


def test_the_months_of_the_record_come_from_the_series_and_the_window_is_reported():
    d = run(world(n=130))["detail"]
    assert d["first_month"] == mlab(mback(LAST, 129)) and d["last_month"] == "2026-09" and d["months_checked"] == 130


def test_a_series_with_an_extra_month_covers_different_months_too():
    data = world()
    data[SBAL][mback(LAST, 200)] = 30_000.0
    refused(data, "the services balance series covers different months than total exports")


# ---------------------------------------------------------------- ranges (both edges, every series)

LEVEL = (3000.0, 1_500_000.0)
LIMITS = {TEXP: LEVEL, TIMP: LEVEL, GEXP: LEVEL, GIMP: LEVEL, SEXP: LEVEL, SIMP: LEVEL, TBAL: (-600_000.0, 100_000.0), GBAL: (-700_000.0, 100_000.0), SBAL: (-100_000.0, 150_000.0)}
RANGE_TEXT = {TEXP: "the total exports", TIMP: "the total imports", GEXP: "the goods exports", GIMP: "the goods imports", SEXP: "the services exports", SIMP: "the services imports",
              TBAL: "the total balance", GBAL: "the goods balance", SBAL: "the services balance"}
EDGES = [
    # series, a value exactly on the limit, one step outside it, the refusal text of that step
    (TEXP, 3000.0, 2999.9, "the total exports of 2,999.9 million in {m} is outside 3,000 to 1,500,000"),
    (TEXP, 1_500_000.0, 1_500_000.1, "the total exports of 1,500,000.1 million in {m} is outside 3,000 to 1,500,000"),
    (TIMP, 3000.0, 2999.9, "the total imports of 2,999.9 million in {m} is outside 3,000 to 1,500,000"),
    (TIMP, 1_500_000.0, 1_500_000.1, "the total imports of 1,500,000.1 million in {m} is outside 3,000 to 1,500,000"),
    (GEXP, 3000.0, 2999.9, "the goods exports of 2,999.9 million in {m} is outside 3,000 to 1,500,000"),
    (GEXP, 1_500_000.0, 1_500_000.1, "the goods exports of 1,500,000.1 million in {m} is outside 3,000 to 1,500,000"),
    (GIMP, 3000.0, 2999.9, "the goods imports of 2,999.9 million in {m} is outside 3,000 to 1,500,000"),
    (GIMP, 1_500_000.0, 1_500_000.1, "the goods imports of 1,500,000.1 million in {m} is outside 3,000 to 1,500,000"),
    (SEXP, 3000.0, 2999.9, "the services exports of 2,999.9 million in {m} is outside 3,000 to 1,500,000"),
    (SEXP, 1_500_000.0, 1_500_000.1, "the services exports of 1,500,000.1 million in {m} is outside 3,000 to 1,500,000"),
    (SIMP, 3000.0, 2999.9, "the services imports of 2,999.9 million in {m} is outside 3,000 to 1,500,000"),
    (SIMP, 1_500_000.0, 1_500_000.1, "the services imports of 1,500,000.1 million in {m} is outside 3,000 to 1,500,000"),
    (TBAL, -600_000.0, -600_000.1, "the total balance of -600,000.1 million in {m} is outside -600,000 to 100,000"),
    (TBAL, 100_000.0, 100_000.1, "the total balance of 100,000.1 million in {m} is outside -600,000 to 100,000"),
    (GBAL, -700_000.0, -700_000.1, "the goods balance of -700,000.1 million in {m} is outside -700,000 to 100,000"),
    (GBAL, 100_000.0, 100_000.1, "the goods balance of 100,000.1 million in {m} is outside -700,000 to 100,000"),
    (SBAL, -100_000.0, -100_000.1, "the services balance of -100,000.1 million in {m} is outside -100,000 to 150,000"),
    (SBAL, 150_000.0, 150_000.1, "the services balance of 150,000.1 million in {m} is outside -100,000 to 150,000"),
]


@pytest.mark.parametrize("sid, edge, outside, text", EDGES)
def test_each_limit_is_pinned_at_both_edges(sid, edge, outside, text):
    data = world()
    first = months_of(data)[0]
    data[sid][first] = edge
    not_a_range_refusal(data)                                                       # exactly on the limit the range check does not speak (a later check may)
    data[sid][first] = outside
    refused(data, text.format(m=mlab(first)))


def test_the_limits_in_the_module_are_the_literals_of_this_file():
    assert T.LIMITS == LIMITS and T.MOVE_LIMIT == 50.0 and T.IDENTITY_TOLERANCE == 1.5 and T.MIN_MONTHS == 120 and T.RECENT_MONTHS == 6
    assert T.OVERDUE_AFTER_DAYS == 105 and T.START == "1992-01-01" and T.TTL == 6 * 3600.0 and T.FAIL_TTL == 120.0
    assert T.SERIES == IDS and T.MOVE_SERIES == (TEXP, TIMP, GEXP, GIMP, SEXP, SIMP)


@pytest.mark.parametrize("sid", IDS)
def test_a_range_is_checked_in_the_oldest_and_the_newest_month_not_only_in_the_middle(sid):
    for when in (mback(LAST, 179), mback(LAST, 90), LAST):
        data = world()
        data[sid][when] = 1e9                                                         # far above every upper limit; the range check comes before the moves and the sums
        with pytest.raises(ValueError, match=f"^{re.escape(RANGE_TEXT[sid])} of 1,000,000,000 million in {mlab(when)} is outside"):
            T.summarize(data, TODAY)


def test_the_numbers_in_a_refusal_are_written_with_thousands_separators_and_no_trailing_zero():
    data = world()
    data[SIMP][LAST] = 1_234_567.0
    data[SIMP][mback(LAST, 1)] = 1_600_000.0
    refused(data, "the services imports of 1,600,000 million in 2026-08 is outside 3,000 to 1,500,000")


def test_ranges_are_checked_series_by_series_in_the_order_of_the_table_and_the_oldest_month_first():
    data = world()
    for sid in reversed(IDS):
        data[sid][mback(LAST, 3)] = 1e9
        data[sid][mback(LAST, 100)] = 1e9
    refused(data, f"the total exports of 1,000,000,000 million in {mlab(mback(LAST, 100))} is outside 3,000 to 1,500,000")
    data[TEXP][mback(LAST, 100)] = data[TEXP][mback(LAST, 3)] = 200_000.0
    refused(data, f"the total imports of 1,000,000,000 million in {mlab(mback(LAST, 100))} is outside 3,000 to 1,500,000")
    data[TIMP][mback(LAST, 100)] = data[TIMP][mback(LAST, 3)] = 200_000.0
    refused(data, f"the total balance of 1,000,000,000 million in {mlab(mback(LAST, 100))} is outside -600,000 to 100,000")


def test_the_minimum_count_of_months_comes_before_the_ranges():
    data = world(n=119)
    data[TEXP][LAST] = 1e9
    refused(data, "the trade record covers 119 months, fewer than the 120 expected")


# ---------------------------------------------------------------- moves in a month (the six level series, +-50%)

MOVES = [
    # what is true from 2019-05 on at the limit (every sum still holds), one step outside it, the refusal text of that step
    (dict(ge=300_000.0), dict(ge=300_000.2), "the goods exports moved +50.0% in 2019-05, outside -50 to 50"),
    (dict(ge=100_000.0), dict(ge=99_999.8), "the goods exports moved -50.0% in 2019-05, outside -50 to 50"),
    (dict(gi=600_000.0), dict(gi=600_000.4), "the goods imports moved +50.0% in 2019-05, outside -50 to 50"),
    (dict(gi=200_000.0), dict(gi=199_999.6), "the goods imports moved -50.0% in 2019-05, outside -50 to 50"),
    (dict(se=150_000.0), dict(se=150_000.1), "the services exports moved +50.0% in 2019-05, outside -50 to 50"),
    (dict(se=50_000.0), dict(se=49_999.9), "the services exports moved -50.0% in 2019-05, outside -50 to 50"),
    (dict(si=150_000.0), dict(si=150_000.1), "the services imports moved +50.0% in 2019-05, outside -50 to 50"),
    (dict(si=50_000.0), dict(si=49_999.9), "the services imports moved -50.0% in 2019-05, outside -50 to 50"),
    (dict(ge=300_000.0, se=150_000.0), dict(ge=300_000.2, se=150_000.0), "the total exports moved +50.0% in 2019-05, outside -50 to 50"),
    (dict(ge=100_000.0, se=50_000.0), dict(ge=99_999.8, se=50_000.0), "the total exports moved -50.0% in 2019-05, outside -50 to 50"),
    (dict(gi=600_000.0, si=150_000.0), dict(gi=600_000.4, si=150_000.0), "the total imports moved +50.0% in 2019-05, outside -50 to 50"),
    (dict(gi=200_000.0, si=50_000.0), dict(gi=199_999.6, si=50_000.0), "the total imports moved -50.0% in 2019-05, outside -50 to 50"),
]


@pytest.mark.parametrize("at_limit, outside, text", MOVES)
def test_each_monthly_move_limit_is_pinned_at_both_edges(at_limit, outside, text):
    assert run(world_step(**at_limit))["available"] is True                         # a move of exactly the limit passes (and so does every other check)
    refused(world_step(**outside), text)


def test_a_move_is_measured_from_the_month_before_and_named_by_the_later_month():
    refused(world_step(date(2019, 5, 1), ge=400_000.0), "the total exports moved +66.7% in 2019-05, outside -50 to 50")


def test_a_one_month_spike_is_refused_at_the_month_it_appears():
    data = world()
    data[GEXP][MAY] = 420_000.0
    data[TEXP][MAY] = 520_000.0                                                      # the sums are broken in that month too, but the move comes first
    refused(data, "the total exports moved +73.3% in 2019-05, outside -50 to 50")


def test_the_six_level_series_are_checked_in_table_order_and_the_oldest_month_first():
    data = world()
    for sid, when in ((SIMP, date(2019, 2, 1)), (SEXP, date(2019, 3, 1)), (GIMP, date(2019, 4, 1)), (GEXP, date(2019, 5, 1)), (TIMP, date(2019, 6, 1)), (TEXP, date(2019, 7, 1))):
        for d in data[sid]:
            if d >= when:
                data[sid][d] *= 2.0
    refused(data, "the total exports moved +100.0% in 2019-07, outside -50 to 50")
    for d in data[TEXP]:
        if d >= date(2019, 7, 1):
            data[TEXP][d] /= 2.0
    refused(data, "the total imports moved +100.0% in 2019-06, outside -50 to 50")
    for d in data[TIMP]:
        if d >= date(2019, 6, 1):
            data[TIMP][d] /= 2.0
    refused(data, "the goods exports moved +100.0% in 2019-05, outside -50 to 50")


def test_a_balance_is_not_move_checked_it_follows_from_the_sums():
    data = world()
    for sid in (TBAL, GBAL, SBAL):
        data[sid][MAY] += 1.0                                                        # not a move of a level series; the sums allow a gap of 1.5
    assert run(data)["available"] is True
    data = world()
    data[TBAL][MAY] = -400_000.0                                                      # a huge move of a balance, inside its range: the sum names it, not a move
    refused(data, "the total balance is 200000 million off exports minus imports in 2019-05, over 1.5")


def test_a_move_is_judged_at_four_decimals_so_the_last_bit_of_a_float_never_decides():
    assert run(world_step(se=150_000.04))["available"] is True                       # +50.00004% rounds to 50.0 and passes (the sums are exact in the world)
    refused(world_step(se=150_000.06), "the services exports moved +50.0% in 2019-05, outside -50 to 50")        # +50.00006% rounds to 50.0001 and does not


def test_the_moves_are_checked_in_the_first_pair_of_months_and_in_the_last():
    data = world()
    first, second = months_of(data)[:2]
    data[TIMP][first] = 100_000.0                                                    # the oldest month is far from the next one
    refused(data, f"the total imports moved +400.0% in {mlab(second)}, outside -50 to 50")
    data = world()
    data[GEXP][LAST] = 500_000.0                                                     # the newest month is far from the one before
    refused(data, "the goods exports moved +150.0% in 2026-09, outside -50 to 50")


def _is_plain_zero(v):
    return v == 0.0 and math.copysign(1.0, v) == 1.0 and json.dumps(v) == "0.0"


def test_a_change_that_rounds_to_zero_from_below_is_zero_and_not_negative_zero():
    data = world()
    data[TEXP][LAST] = 299_999.9                                                     # -0.00003% on the month before and on a year earlier; the sums allow a gap of 0.1
    assert _is_plain_zero(run(data)["total"]["exports_change_year_pct"])
    data = world()
    data[TIMP][LAST] = 499_999.9
    assert _is_plain_zero(run(data)["total"]["imports_change_year_pct"])
    data = world()
    data[TBAL][LAST] = -200_000.0001                                                 # 0.0000001 billion below the month before: rounds to -0.0 at three decimals
    assert _is_plain_zero(run(data)["total"]["balance_change"])


def test_the_moves_come_before_the_sums():
    data = world()
    for d in data[GEXP]:
        if d >= MAY:
            data[GEXP][d] *= 3.0                                                     # the sums are broken from 2019-05 on, but the move is named
    refused(data, "the goods exports moved +200.0% in 2019-05, outside -50 to 50")


# ---------------------------------------------------------------- the six sums, to 1.5 million dollars

WHENS = [mback(LAST, 179), mback(LAST, 90), LAST]
SUMS = [
    # name, what to add to one month so that this sum is off by exactly the tolerance and no sum before it is off by more (it passes), the same one step over
    # (this sum is the first to fail), and the refusal text. The offsets are keyed by the short names of `bump`.
    ("a total balance", {"tb": 1.5}, {"tb": 1.6}, "the total balance is 1.6 million off exports minus imports in {m}, over 1.5"),
    ("b goods balance", {"gb": 1.5}, {"gb": 1.6}, "the goods balance is 1.6 million off goods exports minus imports in {m}, over 1.5"),
    ("c services balance", {"sb": 1.5}, {"sb": 1.6}, "the services balance is 1.6 million off services exports minus imports in {m}, over 1.5"),
    ("d total exports", {"te": 1.5, "tb": 1.5}, {"te": 1.6, "tb": 1.6}, "total exports are 1.6 million off goods plus services in {m}, over 1.5"),
    ("e total imports", {"ti": 1.5, "tb": -1.5}, {"ti": 1.6, "tb": -1.6}, "total imports are 1.6 million off goods plus services in {m}, over 1.5"),
    ("f balances", {"tb": 1.5, "te": 1.5}, {"tb": 1.6, "te": 1.5}, "the total balance is 1.6 million off goods plus services balances in {m}, over 1.5"),
]


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("when", WHENS)
@pytest.mark.parametrize("name, ok_offsets, bad_offsets, text", SUMS)
def test_each_sum_holds_exactly_at_1_5_million_and_is_refused_just_over(name, ok_offsets, bad_offsets, text, when, sign):
    ok = bump(world(), when, **{k: sign * v for k, v in ok_offsets.items()})
    assert run(ok)["available"] is True                                               # a gap of exactly the tolerance passes (1.5 is exact in binary)
    bad = bump(world(), when, **{k: sign * v for k, v in bad_offsets.items()})
    refused(bad, text.format(m=mlab(when)))


def test_the_sixth_sum_can_fail_alone_with_all_the_others_inside_the_tolerance():
    data = bump(world(), LAST, te=1.5, tb=3.0, ti=-1.5)                                # a: 0, d: 1.5, e: 1.5, f: 3.0
    refused(data, "the total balance is 3 million off goods plus services balances in 2026-09, over 1.5")


def test_a_gap_is_printed_with_g_so_a_whole_number_has_no_decimals_and_a_fraction_keeps_its_digits():
    data = bump(world(), LAST, tb=2.0)
    refused(data, "the total balance is 2 million off exports minus imports in 2026-09, over 1.5")
    data = bump(world(), LAST, tb=-2.0)
    refused(data, "the total balance is 2 million off exports minus imports in 2026-09, over 1.5")
    refused(bump(world(), LAST, tb=1.75), "the total balance is 1.75 million off exports minus imports in 2026-09, over 1.5")       # exact in binary: not rounded to one decimal


def test_the_sums_are_checked_in_table_order_and_the_oldest_month_first():
    data = world()
    bump(data, mback(LAST, 10), tb=5.0, gb=5.0)                                       # a and b and f are off in 2026-... but a comes first
    bump(data, mback(LAST, 100), gb=5.0)                                              # b is off in an older month
    refused(data, f"the total balance is 5 million off exports minus imports in {mlab(mback(LAST, 10))}, over 1.5")
    data = world()
    bump(data, mback(LAST, 10), gb=5.0)
    bump(data, mback(LAST, 100), gb=5.0, sb=5.0)
    refused(data, f"the goods balance is 5 million off goods exports minus imports in {mlab(mback(LAST, 100))}, over 1.5")


def test_a_sum_is_checked_in_the_newest_month_and_in_every_older_one():
    for when in (mback(LAST, 179), mback(LAST, 120), mback(LAST, 1), LAST):
        refused(bump(world(), when, sb=9.0), f"the services balance is 9 million off services exports minus imports in {mlab(when)}, over 1.5")


def test_a_balance_series_swapped_for_another_is_caught_in_the_real_record():
    data = real()
    data[TBAL] = dict(data[GBAL])                                                    # the goods balance instead of the total balance: off by the services surplus
    with pytest.raises(ValueError, match=r"^the total balance is \d+ million off exports minus imports in \d{4}-\d\d, over 1\.5$"):
        T.summarize(data, TODAY)
    data = real()
    data[TEXP], data[TIMP] = dict(data[TIMP]), dict(data[TEXP])                       # exports and imports swapped
    with pytest.raises(ValueError, match=r"^the total balance is \d+ million off exports minus imports in \d{4}-\d\d, over 1\.5$"):
        T.summarize(data, TODAY)


def test_the_largest_gap_is_the_largest_not_the_first_or_the_last_and_names_its_month():
    data = world()
    bump(data, mback(LAST, 100), tb=1.0)
    bump(data, mback(LAST, 50), gb=1.5)
    bump(data, mback(LAST, 10), sb=-1.0)
    d = run(data)["detail"]
    assert d["largest_gap_million"] == 1.5 and d["largest_gap_month"] == mlab(mback(LAST, 50))


def test_the_largest_gap_is_reported_to_three_decimals_and_a_perfect_record_names_its_first_month():
    data = world()
    bump(data, LAST, tb=0.3333333)
    assert run(data)["detail"]["largest_gap_million"] == 0.333
    d = run(world())["detail"]
    assert d["largest_gap_million"] == 0.0 and d["largest_gap_month"] == mlab(mback(LAST, 179))


def test_the_first_month_of_equal_gaps_is_named_and_the_first_sum_of_equal_gaps_in_the_same_month():
    data = world()
    bump(data, mback(LAST, 20), tb=1.0)
    bump(data, mback(LAST, 10), tb=1.0)
    assert run(data)["detail"]["largest_gap_month"] == mlab(mback(LAST, 20))
    data = world()
    bump(data, mback(LAST, 30), sb=1.0)
    bump(data, mback(LAST, 40), gb=1.0)
    assert run(data)["detail"]["largest_gap_month"] == mlab(mback(LAST, 40))          # the goods balance sum (b) comes before the services balance sum (c)


# ---------------------------------------------------------------- how the figures are worked

def trend_world(n=180):
    """Changing figures: each primary level cycles with its own period, so every change differs and none is a round number."""
    data = {sid: {} for sid in IDS}
    for k in range(n):
        d = mback(LAST, n - 1 - k)
        p = dict(ge=200_000.0 + 1_234.0 * (k % 7), gi=300_000.0 + 2_345.0 * (k % 5), se=100_000.0 + 777.0 * (k % 4), si=70_000.0 + 321.0 * (k % 3))
        for sid, v in build(**p).items():
            data[sid][d] = v
    return data


def test_the_month_and_year_changes_use_the_right_months_and_are_rounded():
    data = trend_world()
    r = run(data)
    ms = months_of(data)
    last, before, ago = ms[-1], ms[-2], ms[-13]
    for key, (e, i, b) in (("total", (TEXP, TIMP, TBAL)), ("goods", (GEXP, GIMP, GBAL)), ("services", (SEXP, SIMP, SBAL))):
        g = r[key]
        assert g["exports"] == round(data[e][last] / 1000, 3) and g["imports"] == round(data[i][last] / 1000, 3) and g["balance"] == round(data[b][last] / 1000, 3)
        assert g["balance_change"] == round((data[b][last] - data[b][before]) / 1000, 3)
        assert g["balance_year_ago"] == round(data[b][ago] / 1000, 3)
        assert g["exports_change_year_pct"] == round(100 * (data[e][last] / data[e][ago] - 1), 2)
        assert g["imports_change_year_pct"] == round(100 * (data[i][last] / data[i][ago] - 1), 2)
    # the world has changes whose one-, two- and three-decimal forms differ, so a rounding to another decimal or another span would show
    assert len({round(100 * (data[GIMP][last] / data[GIMP][ago] - 1), k) for k in (1, 2, 3)}) == 3                        # 1.5, 1.54 and 1.539
    assert round((data[GBAL][last] - data[GBAL][before]) / 1000, 3) != round((data[GBAL][last] - data[GBAL][before]) / 1000, 2)
    assert len({round(100 * (data[GEXP][last] / data[GEXP][mback(last, k)] - 1), 2) for k in (1, 11, 12, 13)}) == 4        # 11, 12 and 13 months back all give another change
    assert r["goods"]["exports_change_year_pct"] == round(100 * (data[GEXP][last] / data[GEXP][mback(last, 12)] - 1), 2)


def world_by(fn, n=180):
    """Month k (0 = oldest) takes the primary levels `fn(k)` returns, over the defaults; every sum holds."""
    data = {sid: {} for sid in IDS}
    for k in range(n):
        d = mback(LAST, n - 1 - k)
        for sid, v in build(**{**BASE, **fn(k)}).items():
            data[sid][d] = v
    return data


def test_the_range_is_over_the_total_balance_and_counts_only_strictly_lower_months():
    # the oldest 90 months have a balance of -220,000 (services imports 120,000), the newest 90 months -200,000, which is also the value now
    data = world_by(lambda k: {"si": 120_000.0} if k < 90 else {})
    rng = run(data)["total"]["range"]
    assert rng == {"months": 180, "first": mlab(mback(LAST, 179)), "lowest": {"value": -220.0, "month": mlab(mback(LAST, 179))},
                   "highest": {"value": -200.0, "month": mlab(mback(LAST, 89))}, "share_lower_pct": 50}             # the equal months are not lower; the earliest month of a tie is named
    assert run(world())["total"]["range"]["share_lower_pct"] == 0


def test_a_level_is_written_in_billions_to_three_decimals_and_a_fraction_of_a_million_is_rounded():
    data = world()
    data[TEXP][LAST] = 300_000.6                                                     # the published figures are whole millions, but the rounding is the module's own: 300.0006 billion is 300.001
    r = run(data)
    assert r["total"]["exports"] == 300.001 and r["recent"][-1]["exports"] == 300.001
    assert run(world())["total"]["exports"] == 300.0


def test_the_six_recent_months_have_their_own_figures_and_the_oldest_comes_first():
    data = trend_world()
    r = run(data)
    ms = months_of(data)
    assert [m["month"] for m in r["recent"]] == [mlab(d) for d in ms[-6:]]
    for m, d in zip(r["recent"], ms[-6:]):
        assert m == {"month": mlab(d), "exports": round(data[TEXP][d] / 1000, 3), "imports": round(data[TIMP][d] / 1000, 3), "balance": round(data[TBAL][d] / 1000, 3)}


def test_the_level_is_the_newest_months_not_an_earlier_one():
    data = trend_world()
    r = run(data)
    assert r["total"]["exports"] == round(data[TEXP][LAST] / 1000, 3) != round(data[TEXP][mback(LAST, 1)] / 1000, 3)


def test_the_year_ago_figure_is_twelve_months_back_not_eleven_or_thirteen():
    data = trend_world()
    ago = {round(data[TBAL][mback(LAST, k)] / 1000, 3) for k in (11, 13)}
    assert run(data)["total"]["balance_year_ago"] == round(data[TBAL][mback(LAST, 12)] / 1000, 3) and run(data)["total"]["balance_year_ago"] not in ago


# ---------------------------------------------------------------- refusals fit the visible 110 characters

def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    texts = [t.format(m="2026-09") for _s, _e, _o, t in EDGES]
    texts += [m[2] for m in MOVES]
    texts += [t.replace("1.6", "1234567.5").format(m="2026-09") for _n, _ok, _bad, t in SUMS]
    texts += [f"the {NAME[s]} series covers different months than total exports" for s in IDS[1:]]
    texts += ["the trade record covers 119 months, fewer than the 120 expected", "the trade months skip a month after 2024-12", "the trade series end in different months", "a trade date is not the 1st of a month"]
    for text in texts:
        assert len(text) <= 110, (len(text), text)
        assert fail_reason(ValueError(text)) == f"the data failed a check: {dates_in_words(text)}"


# ---------------------------------------------------------------- the class: requests, cache, failures, demo, route

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def test_overview_fetches_nine_series_one_request_each_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = T.UsTrade(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["total"]["balance"] == -105.047 and n["n"] == 9 and r["demo"] is False and r["as_of"] == NOW.isoformat()
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 9


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(T.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = T.UsTrade(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 9
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 9                                                               # still the failure from the cache
    clock["t"] += 1
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 18      # exactly two minutes on it asks again
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 18                                                              # one second short of six hours: kept
    clock["t"] += 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 27                                                              # exactly six hours on: asked again


def test_without_a_time_the_question_is_asked_at_the_present_moment_in_utc():
    r = asyncio.run(T.UsTrade(client=_client(_handler)).overview())
    asked = datetime.fromisoformat(r["as_of"])
    assert asked.tzinfo is not None and asked.utcoffset() == timedelta(0)
    assert abs((datetime.now(timezone.utc) - asked).total_seconds()) < 60


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = T.UsTrade(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(T.UsTrade(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US international trade could not be read right now (the server had an error, HTTP 503)" and "total" not in r and "recent" not in r
    r = asyncio.run(T.UsTrade(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]                      # anything but 200 is a failure


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == SBAL else _handler(req)

    r = asyncio.run(T.UsTrade(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "total" not in r and "goods" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    def answer(replace):
        bad = dict(F)
        for sid, (old, new) in replace.items():
            assert old in F[sid]
            bad[sid] = F[sid].replace(old, new)
        return asyncio.run(T.UsTrade(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))

    r = answer({TIMP: ("2026-09-01,426558", "2026-09-01,4265580")})                  # a decimal slip beyond the range
    assert r["available"] is False and r["reason"] == "US international trade could not be read right now (the data failed a check: the total imports of 4,265,580 million in September 2026 is outside 3,000 to 1,500,000)" and "total" not in r
    r = answer({TBAL: ("2026-09-01,-105047", "2026-09-01,-115047")})                  # a digit slip that stays inside every range and move: only the sum finds it
    assert r["available"] is False and r["reason"] == "US international trade could not be read right now (the data failed a check: the total balance is 10000 million off exports minus imports in September 2026, over 1.5)"
    r = answer({SEXP: ("2026-09-01,110543", "2026-09-01,x")})
    assert r["available"] is False and "a BOPSEXP row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(T.UsTrade(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US international trade could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("BOPGSTB")

    monkeypatch.setattr(T, "summarize", boom)
    r = asyncio.run(T.UsTrade(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US international trade could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(T.UsTrade(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US trade figures are not shown because made-up values would look real." and "total" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/us-trade")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_card_is_refreshed_with_the_other_macro_sources():
    jobs = (Path(__file__).parent.parent / "atlas_api" / "sched" / "jobs.py").read_text(encoding="utf-8")
    app = (Path(__file__).parent.parent / "atlas_api" / "app.py").read_text(encoding="utf-8")
    assert '"us_trade"' in jobs and '"us_trade": us_trade' in app and "us_trade = UsTrade(demo=demo)" in app


def test_each_request_asks_for_one_series_from_1992_with_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(T.UsTrade(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)             # never a combined request: FRED applies one start date to the first series only
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert {req.url.params["cosd"] for req in seen} == {"1992-01-01"}


def test_a_client_made_here_waits_25_seconds_and_is_closed_and_one_given_is_left_open(monkeypatch):
    seen = {"closed": False}

    class Fake:
        def __init__(self, **kw):
            seen["timeout"] = kw.get("timeout")

        async def get(self, url, params=None):
            return httpx.Response(200, text=F[params["id"]])

        async def aclose(self):
            seen["closed"] = True

    monkeypatch.setattr(T.httpx, "AsyncClient", Fake)
    r = asyncio.run(T.UsTrade().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(T.UsTrade(client=given).overview(NOW))
    assert given.is_closed is False


def test_the_module_says_why_each_series_is_asked_for_alone_and_what_it_does_not_check():
    doc = T.__doc__
    assert "ALONE" in doc and "NOT checked" in doc and "rounded to a million" in doc and "Table 1" in doc
