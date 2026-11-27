"""US producer prices (the Bureau of Labor Statistics' Producer Price Index, nine seasonally adjusted monthly series via FRED: final demand, final demand without foods and energy, finished goods, finished consumer goods, finished consumer foods, finished consumer energy goods, processed, unprocessed and services for intermediate demand).

Producer price indexes have no sums, so every check is a plain one: the series end in the same month, cover the same months, are dated the 1st, skip no month, number at least 132, lie inside a range and move by no more than a limit in a month. The limits are literals, set from the whole real record before any test was written (the oldest series begin in 1947, the youngest in 2010; the real extremes are in the module's comments). The figures of the real record are worked out below with plain Python from the saved responses, not with the module.
"""
import asyncio
import csv
import io
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import usproducerprices as P
from atlas_api.app import create_app
from atlas_api.failreason import dates_in_words, fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "fred_usproducerprices.json").read_text())
TODAY = date(2026, 11, 26)
NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
LAST = date(2026, 10, 1)

FINAL, CORE, FINISHED, CONSUMER, FOODS, ENERGY, PROCESSED, UNPROCESSED, SERVICES = "PPIFIS", "PPIFES", "WPSFD49207", "WPSFD49502", "WPSFD4111", "WPSFD4121", "WPSID61", "WPSID62", "WPSID63"
IDS = (FINAL, CORE, FINISHED, CONSUMER, FOODS, ENERGY, PROCESSED, UNPROCESSED, SERVICES)
NAME = {FINAL: "final demand", CORE: "core final demand", FINISHED: "finished goods", CONSUMER: "finished consumer goods", FOODS: "finished consumer foods", ENERGY: "finished consumer energy",
        PROCESSED: "processed intermediate goods", UNPROCESSED: "unprocessed intermediate goods", SERVICES: "intermediate services"}


def mback(d, n):
    i = d.year * 12 + d.month - 1 - n
    return date(i // 12, i % 12 + 1, 1)


def mlab(d):
    return f"{d.year}-{d.month:02d}"


def real():
    return {sid: P.parse(F[sid], sid) for sid in IDS}


def world(n=150, last=LAST, levels=None):
    """`n` months ending at `last`, every series flat at 100.0 (or at the level given for it): every check is satisfied, so one thing at a time can be broken."""
    levels = levels or {}
    ms = [mback(last, i) for i in range(n - 1, -1, -1)]
    return {sid: {d: levels.get(sid, 100.0) for d in ms} for sid in IDS}


def months_of(data):
    return sorted(data[FINAL])


def run(data, today=TODAY):
    return P.summarize(data, today)


def refused(data, text):
    with pytest.raises(ValueError, match=f"^{re.escape(text)}$"):
        P.summarize(data, TODAY)


def step(data, sid, start, value):
    """Set `sid` to `value` from `start` on."""
    for d in data[sid]:
        if d >= start:
            data[sid][d] = value
    return data


# ---------------------------------------------------------------- the real record

REAL_ITEMS = {  # key: label, base, index, change on the month, change on a year (plain arithmetic on the saved responses: 2026-10 against 2026-09 and 2025-10)
    "final": ("Final demand", "November 2009 = 100", 160.254, 0.35, 6.52),
    "core": ("Final demand without foods and energy", "April 2010 = 100", 156.74, 0.33, 5.04),
    "finished": ("Finished goods", "1982 = 100", 288.52, 0.56, 9.28),
    "consumer": ("Finished consumer goods", "1982 = 100", 310.993, 0.61, 11.3),
    "foods": ("Finished consumer foods", "1982 = 100", 287.951, 1.58, 0.91),
    "energy": ("Finished consumer energy goods", "1982 = 100", 280.601, 0.27, 32.77),
    "processed": ("Processed goods for intermediate demand", "1982 = 100", 299.923, 0.36, 14.47),
    "unprocessed": ("Unprocessed goods for intermediate demand", "1982 = 100", 284.779, -3.08, 17.05),
    "services": ("Services for intermediate demand", "November 2009 = 100", 166.167, 0.59, 6.78),
}
REAL_GROUPS = [("final", "Final demand", ["final", "core"]), ("finished", "Finished goods", ["finished", "consumer", "foods", "energy"]),
               ("intermediate", "Intermediate demand: what producers pay", ["processed", "unprocessed", "services"])]


def test_the_real_record_passes_every_check_and_reports_its_window():
    r = run(real())
    assert r["available"] is True and r["detail"] == {"months_checked": 199, "first_month": "2010-04", "last_month": "2026-10"}
    assert r["checks"] == {"months_in_a_row": True, "range_ok": True, "moves_ok": True}


def test_the_real_headline_figures_are_pinned():
    r = run(real())
    assert (r["date"], r["month"], r["age_days"], r["freshness"]) == ("2026-10-01", "2026-10", 56, "CURRENT")
    assert r["headline"] == {"key": "final", "label": "Final demand", "base": "November 2009 = 100", "index": 160.254, "change_pct": 0.35, "change_year_pct": 6.52, "core_change_year_pct": 5.04,
                             "range": {"months": 120, "first": "2016-11", "lowest": {"value": -1.35, "month": "2020-04"}, "highest": {"value": 11.59, "month": "2022-03"}, "share_lower_pct": 83}}


def test_every_real_line_of_every_group_is_pinned_in_its_order():
    groups = run(real())["groups"]
    assert [(g["key"], g["label"], [i["key"] for i in g["items"]]) for g in groups] == REAL_GROUPS
    for g in groups:
        for i in g["items"]:
            label, base, index, month, year = REAL_ITEMS[i["key"]]
            assert i == {"key": i["key"], "label": label, "base": base, "index": index, "change_pct": month, "change_year_pct": year}, i["key"]


def test_the_figures_equal_a_plain_python_recomputation_from_the_saved_responses():
    rows = {sid: [(r[0], float(r[1])) for r in list(csv.reader(io.StringIO(F[sid].strip())))[1:]] for sid in IDS}
    out = {i["key"]: i for g in run(real())["groups"] for i in g["items"]}
    keys = dict(zip(IDS, ["final", "core", "finished", "consumer", "foods", "energy", "processed", "unprocessed", "services"]))
    for sid, v in rows.items():
        last, prev, ago = v[-1][1], v[-2][1], v[-13][1]
        i = out[keys[sid]]
        assert i["index"] == last and i["change_pct"] == round(100.0 * (last / prev - 1.0), 2) and i["change_year_pct"] == round(100.0 * (last / ago - 1.0), 2), sid


def test_the_six_recent_months_are_oldest_first_with_the_right_changes():
    assert run(real())["recent"] == [{"month": "2026-05", "change_pct": 0.52, "core_change_pct": -0.01}, {"month": "2026-06", "change_pct": -0.13, "core_change_pct": 0.43},
                                     {"month": "2026-07", "change_pct": 0.1, "core_change_pct": 0.28}, {"month": "2026-08", "change_pct": 0.41, "core_change_pct": 0.19},
                                     {"month": "2026-09", "change_pct": 1.41, "core_change_pct": 0.82}, {"month": "2026-10", "change_pct": 0.35, "core_change_pct": 0.33}]


# ---------------------------------------------------------------- what the module says about itself

def test_the_source_the_page_the_address_and_every_series_are_named():
    assert P.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and P.PAGE == "https://fred.stlouisfed.org/series/PPIFIS" and P.START == "2010-04-01"
    assert P.SOURCE == "U.S. Bureau of Labor Statistics, Producer Price Index (final demand, finished goods and intermediate demand), via FRED, St. Louis Fed (official, free public data)"
    assert P.SERIES == ("PPIFIS", "PPIFES", "WPSFD49207", "WPSFD49502", "WPSFD4111", "WPSFD4121", "WPSID61", "WPSID62", "WPSID63")
    assert P.NAMES == NAME
    assert P.LABELS == {FINAL: "Final demand", CORE: "Final demand without foods and energy", FINISHED: "Finished goods", CONSUMER: "Finished consumer goods", FOODS: "Finished consumer foods", ENERGY: "Finished consumer energy goods",
                        PROCESSED: "Processed goods for intermediate demand", UNPROCESSED: "Unprocessed goods for intermediate demand", SERVICES: "Services for intermediate demand"}
    assert P.KEYS == {FINAL: "final", CORE: "core", FINISHED: "finished", CONSUMER: "consumer", FOODS: "foods", ENERGY: "energy", PROCESSED: "processed", UNPROCESSED: "unprocessed", SERVICES: "services"}
    assert P.BASES == {FINAL: "November 2009 = 100", CORE: "April 2010 = 100", FINISHED: "1982 = 100", CONSUMER: "1982 = 100", FOODS: "1982 = 100", ENERGY: "1982 = 100", PROCESSED: "1982 = 100", UNPROCESSED: "1982 = 100", SERVICES: "November 2009 = 100"}
    assert P.GROUPS == (("final", "Final demand", (FINAL, CORE)), ("finished", "Finished goods", (FINISHED, CONSUMER, FOODS, ENERGY)), ("intermediate", "Intermediate demand: what producers pay", (PROCESSED, UNPROCESSED, SERVICES)))


def test_the_limits_and_the_other_constants_are_the_literals_set_from_the_whole_record():
    assert P.LIMITS == {FINAL: (50.0, 320.0), CORE: (50.0, 315.0), FINISHED: (13.0, 580.0), CONSUMER: (14.0, 620.0), FOODS: (15.0, 580.0), ENERGY: (10.0, 560.0), PROCESSED: (11.0, 600.0), UNPROCESSED: (14.0, 720.0), SERVICES: (50.0, 330.0)}
    assert P.MOVE_LIMITS == {FINAL: (-4.0, 4.0), CORE: (-3.0, 3.0), FINISHED: (-8.0, 8.0), CONSUMER: (-10.0, 10.0), FOODS: (-20.0, 20.0), ENERGY: (-32.0, 32.0), PROCESSED: (-11.0, 11.0), UNPROCESSED: (-45.0, 45.0), SERVICES: (-4.0, 4.0)}
    assert (P.MIN_MONTHS, P.HISTORY_MONTHS, P.RECENT_MONTHS, P.OVERDUE_AFTER_DAYS, P.TTL, P.FAIL_TTL, P.CONCURRENCY) == (132, 120, 6, 75, 21600.0, 120.0, 6)


def test_the_note_says_what_the_figures_are_and_are_not_and_points_to_the_check_line():
    note = run(real())["note"]
    assert note.startswith("Producer price indexes from the Bureau of Labor Statistics: how the prices US producers receive for what they sell change over time, seasonally adjusted and published monthly. ")
    assert ". Final demand is what is sold to households, businesses, government and foreign buyers, in goods, services and construction; finished goods are goods ready for sale to final users; intermediate demand is what producers buy from each other as inputs. " in note
    assert ". Each series has its own base, the number beside it, so the levels of two series cannot be compared, only their changes. The newest months are revised in later releases. " in note
    assert ". Plain checks: the units are the ones assumed and no month is missing; the ranges and the monthly moves are in the Check line. " in note and note.count("the Check line") == 1
    assert note.endswith("This describes prices that already happened: it is not a market signal or a forecast.") and len(note) <= 1100


def test_no_sentence_of_the_note_is_said_twice():
    note = run(real())["note"]
    sentences = re.split(r"(?<=\.) ", note)
    assert len(sentences) == 6 and len(set(sentences)) == len(sentences)             # a repeated sentence still contains every clause the other tests look for


def test_the_docstring_says_there_are_no_sums_and_what_the_checks_do_not_show():
    doc = P.__doc__
    assert "have no sums" in doc and "every check here is a plain one" in doc and "not that the figures are right" in doc and "75 days" in doc and "a month is released about 13 days after it ends" in doc.lower()


@pytest.mark.parametrize("days, fresh", [(75, "CURRENT"), (76, "OVERDUE")])
def test_a_month_turns_overdue_after_75_days_from_its_first_day(days, fresh):
    assert run(real(), today=LAST + timedelta(days=days))["freshness"] == fresh


def test_the_age_is_worked_from_the_time_of_the_question_not_from_the_clock():
    assert run(real(), today=date(2026, 11, 1))["age_days"] == 31 and run(real(), today=date(2026, 12, 11))["age_days"] == 71


# ---------------------------------------------------------------- the order of the checks (each input fails the check and the next one)

ENDS = "the producer price series end in different months"
FIRST = "a producer price date is not the 1st of a month"
COUNT = "the producer price record covers {n} months, fewer than the 132 expected"


@pytest.mark.parametrize("sid", IDS)
def test_series_that_end_in_different_months_are_refused_whichever_one_is_short(sid):
    data = world()
    del data[sid][LAST]                                                              # it also covers different months: the end is checked first
    refused(data, ENDS)


@pytest.mark.parametrize("sid", IDS[1:])
def test_a_series_with_a_hole_names_itself_and_the_first_in_table_order_is_named(sid):
    data = world()
    del data[sid][mback(LAST, 50)]
    refused(data, f"the {NAME[sid]} series covers different months than final demand")
    for later in IDS[IDS.index(sid) + 1:]:
        del data[later][mback(LAST, 60)]
    refused(data, f"the {NAME[sid]} series covers different months than final demand")


def test_the_hole_in_final_demand_itself_is_found_as_a_difference_of_the_first_other_series():
    data = world()
    del data[FINAL][mback(LAST, 50)]
    refused(data, "the core final demand series covers different months than final demand")


def test_a_series_with_an_extra_month_covers_different_months_too():
    data = world()
    data[SERVICES][mback(LAST, 150)] = 100.0
    refused(data, "the intermediate services series covers different months than final demand")


def test_the_covering_comes_before_the_dates():
    data = world()
    del data[FOODS][mback(LAST, 50)]
    for sid in IDS:
        data[sid] = {d.replace(day=2): v for d, v in data[sid].items()}
    refused(data, "the finished consumer foods series covers different months than final demand")


@pytest.mark.parametrize("bad", [date(2019, 5, 2), date(2019, 5, 31)])
def test_a_date_that_is_not_the_1st_is_refused_and_comes_before_a_skipped_month(bad):
    data = world()
    for sid in IDS:
        data[sid][bad] = data[sid].pop(date(2019, 5, 1))
        del data[sid][date(2020, 1, 1)]                                              # a hole in every series as well: the date is named first
    refused(data, FIRST)


def test_a_skipped_month_is_found_in_the_middle_and_across_the_turn_of_the_year():
    data = world()
    for sid in IDS:
        del data[sid][mback(LAST, 70)]
    refused(data, f"the producer price months skip a month after {mlab(mback(LAST, 71))}")
    data = world(last=date(2026, 3, 1))
    for sid in IDS:
        del data[sid][date(2025, 12, 1)]
    refused(data, "the producer price months skip a month after 2025-11")


def test_the_skipped_month_comes_before_the_minimum_count():
    data = world(n=100)
    for sid in IDS:
        del data[sid][mback(LAST, 40)]
    refused(data, f"the producer price months skip a month after {mlab(mback(LAST, 41))}")


def test_fewer_than_132_months_are_refused_and_132_pass():
    refused(world(n=131), COUNT.format(n=131))
    assert run(world(n=132))["detail"]["months_checked"] == 132


def test_the_months_of_the_record_come_from_every_series_not_only_the_first_checked():
    assert run(world(n=140))["detail"]["first_month"] == mlab(mback(LAST, 139))


def test_the_minimum_count_comes_before_the_ranges():
    data = world(n=131)
    data[FINAL][LAST] = 1.0
    refused(data, COUNT.format(n=131))


# ---------------------------------------------------------------- ranges (both edges, every series)

EDGES = [
    # series, the limit itself (a flat world at it passes), one step outside, the refusal text of that step
    (FINAL, 50.0, 49.9, "the final demand index of 49.9 in {m} is outside 50 to 320"),
    (FINAL, 320.0, 320.1, "the final demand index of 320.1 in {m} is outside 50 to 320"),
    (CORE, 50.0, 49.9, "the core final demand index of 49.9 in {m} is outside 50 to 315"),
    (CORE, 315.0, 315.1, "the core final demand index of 315.1 in {m} is outside 50 to 315"),
    (FINISHED, 13.0, 12.9, "the finished goods index of 12.9 in {m} is outside 13 to 580"),
    (FINISHED, 580.0, 580.1, "the finished goods index of 580.1 in {m} is outside 13 to 580"),
    (CONSUMER, 14.0, 13.9, "the finished consumer goods index of 13.9 in {m} is outside 14 to 620"),
    (CONSUMER, 620.0, 620.1, "the finished consumer goods index of 620.1 in {m} is outside 14 to 620"),
    (FOODS, 15.0, 14.9, "the finished consumer foods index of 14.9 in {m} is outside 15 to 580"),
    (FOODS, 580.0, 580.1, "the finished consumer foods index of 580.1 in {m} is outside 15 to 580"),
    (ENERGY, 10.0, 9.9, "the finished consumer energy index of 9.9 in {m} is outside 10 to 560"),
    (ENERGY, 560.0, 560.1, "the finished consumer energy index of 560.1 in {m} is outside 10 to 560"),
    (PROCESSED, 11.0, 10.9, "the processed intermediate goods index of 10.9 in {m} is outside 11 to 600"),
    (PROCESSED, 600.0, 600.1, "the processed intermediate goods index of 600.1 in {m} is outside 11 to 600"),
    (UNPROCESSED, 14.0, 13.9, "the unprocessed intermediate goods index of 13.9 in {m} is outside 14 to 720"),
    (UNPROCESSED, 720.0, 720.1, "the unprocessed intermediate goods index of 720.1 in {m} is outside 14 to 720"),
    (SERVICES, 50.0, 49.9, "the intermediate services index of 49.9 in {m} is outside 50 to 330"),
    (SERVICES, 330.0, 330.1, "the intermediate services index of 330.1 in {m} is outside 50 to 330"),
]


@pytest.mark.parametrize("sid, edge, outside, text", EDGES)
def test_each_limit_is_pinned_at_both_edges(sid, edge, outside, text):
    data = world(levels={sid: edge})
    assert run(data)["available"] is True                                            # exactly on the limit passes
    first = months_of(data)[0]
    data[sid][first] = outside
    refused(data, text.format(m=mlab(first)))


@pytest.mark.parametrize("sid", IDS)
def test_a_range_is_checked_in_the_oldest_and_the_newest_month_not_only_in_the_middle(sid):
    for when in (mback(LAST, 149), mback(LAST, 75), LAST):
        data = world()
        data[sid][when] = 1.0                                                        # far below every lower limit; the ranges come before the moves
        with pytest.raises(ValueError, match=f"^the {re.escape(NAME[sid])} index of 1 in {mlab(when)} is outside"):
            P.summarize(data, TODAY)


def test_the_numbers_in_a_refusal_are_written_with_thousands_separators_and_no_trailing_zero():
    data = world()
    data[FINAL][LAST] = 1234.0
    refused(data, "the final demand index of 1,234 in 2026-10 is outside 50 to 320")
    data[FINAL][LAST] = 1234.56
    refused(data, "the final demand index of 1,234.6 in 2026-10 is outside 50 to 320")


def test_ranges_are_checked_series_by_series_in_the_order_of_the_table_and_the_oldest_month_first():
    data = world()
    for sid in (SERVICES, UNPROCESSED, FINAL):
        data[sid][mback(LAST, 3)] = 1.0
        data[sid][mback(LAST, 100)] = 1.0
    refused(data, f"the final demand index of 1 in {mlab(mback(LAST, 100))} is outside 50 to 320")
    data[FINAL][mback(LAST, 100)] = data[FINAL][mback(LAST, 3)] = 100.0
    refused(data, f"the unprocessed intermediate goods index of 1 in {mlab(mback(LAST, 100))} is outside 14 to 720")


# ---------------------------------------------------------------- moves in a month

MOVES = [
    # series, the step that moves exactly the limit up (passes), one step beyond it, the same down, and the refusal texts of the two steps beyond
    (FINAL, 104.0, 104.0001, 96.0, 95.9999, "the final demand moved +4.0% in {m}, outside -4 to 4", "the final demand moved -4.0% in {m}, outside -4 to 4"),
    (CORE, 103.0, 103.0001, 97.0, 96.9999, "the core final demand moved +3.0% in {m}, outside -3 to 3", "the core final demand moved -3.0% in {m}, outside -3 to 3"),
    (FINISHED, 108.0, 108.0001, 92.0, 91.9999, "the finished goods moved +8.0% in {m}, outside -8 to 8", "the finished goods moved -8.0% in {m}, outside -8 to 8"),
    (CONSUMER, 110.0, 110.0001, 90.0, 89.9999, "the finished consumer goods moved +10.0% in {m}, outside -10 to 10", "the finished consumer goods moved -10.0% in {m}, outside -10 to 10"),
    (FOODS, 120.0, 120.0001, 80.0, 79.9999, "the finished consumer foods moved +20.0% in {m}, outside -20 to 20", "the finished consumer foods moved -20.0% in {m}, outside -20 to 20"),
    (ENERGY, 132.0, 132.0001, 68.0, 67.9999, "the finished consumer energy moved +32.0% in {m}, outside -32 to 32", "the finished consumer energy moved -32.0% in {m}, outside -32 to 32"),
    (PROCESSED, 111.0, 111.0001, 89.0, 88.9999, "the processed intermediate goods moved +11.0% in {m}, outside -11 to 11", "the processed intermediate goods moved -11.0% in {m}, outside -11 to 11"),
    (UNPROCESSED, 145.0, 145.0001, 55.0, 54.9999, "the unprocessed intermediate goods moved +45.0% in {m}, outside -45 to 45", "the unprocessed intermediate goods moved -45.0% in {m}, outside -45 to 45"),
    (SERVICES, 104.0, 104.0001, 96.0, 95.9999, "the intermediate services moved +4.0% in {m}, outside -4 to 4", "the intermediate services moved -4.0% in {m}, outside -4 to 4"),
]


@pytest.mark.parametrize("sid, up, up_out, down, down_out, up_text, down_text", MOVES)
def test_each_monthly_move_limit_is_pinned_at_both_edges(sid, up, up_out, down, down_out, up_text, down_text):
    start = mback(LAST, 100)
    assert run(step(world(), sid, start, up))["available"] is True                   # exactly the limit up passes
    assert run(step(world(), sid, start, down))["available"] is True                 # and exactly the limit down
    refused(step(world(), sid, start, up_out), up_text.format(m=mlab(start)))
    refused(step(world(), sid, start, down_out), down_text.format(m=mlab(start)))


@pytest.mark.parametrize("sid", IDS)
@pytest.mark.parametrize("where", ["first", "last"])
def test_a_move_is_checked_in_the_first_pair_of_months_and_in_the_last(sid, where):
    row = next(m for m in MOVES if m[0] == sid)
    months = months_of(world())
    start = months[1] if where == "first" else LAST
    refused(step(world(), sid, start, row[2]), row[5].format(m=mlab(start)))


def test_the_move_is_measured_from_the_month_before_and_named_by_the_later_month():
    data = world()
    step(data, FINAL, mback(LAST, 10), 104.0001)
    with pytest.raises(ValueError, match=f"in {mlab(mback(LAST, 10))},"):
        P.summarize(data, TODAY)


def test_a_one_month_spike_is_a_move_up_and_a_move_back_and_the_first_is_named():
    data = world()
    data[FINAL][mback(LAST, 20)] = 105.0
    refused(data, f"the final demand moved +5.0% in {mlab(mback(LAST, 20))}, outside -4 to 4")


def test_moves_are_checked_series_by_series_in_table_order_and_the_oldest_month_first():
    data = world()
    step(data, CORE, mback(LAST, 30), 110.0)
    step(data, FINAL, mback(LAST, 30), 110.0)
    refused(data, f"the final demand moved +10.0% in {mlab(mback(LAST, 30))}, outside -4 to 4")
    step(data, FINAL, mback(LAST, 30), 100.0)
    step(data, CORE, mback(LAST, 60), 110.0)
    step(data, CORE, mback(LAST, 59), 100.0)
    refused(data, f"the core final demand moved +10.0% in {mlab(mback(LAST, 60))}, outside -3 to 3")


def test_a_move_is_judged_at_four_decimals_so_the_last_bit_of_a_float_never_decides():
    start = mback(LAST, 100)
    assert run(step(world(), FINAL, start, 104.00004))["available"] is True         # 4.00004% is 4.0000 at four decimals
    refused(step(world(), FINAL, start, 104.00006), f"the final demand moved +4.0% in {mlab(start)}, outside -4 to 4")
    assert run(step(world(), FINAL, start, 95.99996))["available"] is True
    refused(step(world(), FINAL, start, 95.99994), f"the final demand moved -4.0% in {mlab(start)}, outside -4 to 4")


def test_the_ranges_come_before_the_moves():
    data = world()
    data[FINAL][LAST] = 1.0                                                          # below the range and a move of -99%: the range is named
    refused(data, "the final demand index of 1 in 2026-10 is outside 50 to 320")


# ---------------------------------------------------------------- the figures in worlds where the right rule and its neighbours differ

S = {FINAL: 0.25, CORE: 0.5, FINISHED: 0.75, CONSUMER: 1.0, FOODS: 1.25, ENERGY: 1.5, PROCESSED: 1.75, UNPROCESSED: 2.0, SERVICES: 0.125}


def trend_world(n=150):
    """Every series grows by a fixed number of points a month from 100.0: value = 100 + step x month number (month number 0 is the oldest)."""
    ms = [mback(LAST, i) for i in range(n - 1, -1, -1)]
    return {sid: {d: 100.0 + S[sid] * j for j, d in enumerate(ms)} for sid in IDS}


TREND = {"final": (137.25, 0.18, 2.23), "core": (174.5, 0.29, 3.56), "finished": (211.75, 0.36, 4.44), "consumer": (249.0, 0.4, 5.06), "foods": (286.25, 0.44, 5.53),
         "energy": (323.5, 0.47, 5.89), "processed": (360.75, 0.49, 6.18), "unprocessed": (398.0, 0.51, 6.42), "services": (118.625, 0.11, 1.28)}


def test_the_month_and_year_changes_use_the_right_months_and_are_rounded_to_two_decimals():
    r = run(trend_world())
    for g in r["groups"]:
        for i in g["items"]:
            index, month, year = TREND[i["key"]]
            assert (i["index"], i["change_pct"], i["change_year_pct"]) == (index, month, year), i["key"]
    assert r["headline"]["change_pct"] == 0.18 and r["headline"]["change_year_pct"] == 2.23 and r["headline"]["core_change_year_pct"] == 3.56


def test_the_headline_range_is_over_the_last_120_months_of_final_demand_growth_on_a_year_earlier():
    h = run(trend_world())["headline"]
    assert h["range"] == {"months": 120, "first": "2016-11", "lowest": {"value": 2.23, "month": "2026-10"}, "highest": {"value": 2.87, "month": "2016-11"}, "share_lower_pct": 0}


def test_the_share_of_lower_months_is_strictly_lower_over_exactly_120_months_and_rounded():
    data = world()
    step(data, FINAL, mback(LAST, 11), 102.0)                                        # growth is 0% before, 2% for the last 12 months (this one included): 108 of 120 months are lower than now
    h = run(data)["headline"]
    assert h["range"] == {"months": 120, "first": "2016-11", "lowest": {"value": 0.0, "month": "2016-11"}, "highest": {"value": 2.0, "month": "2025-11"}, "share_lower_pct": 90}
    assert h["change_pct"] == 0.0 and h["change_year_pct"] == 2.0                    # 138 months would give 91 and "lower or equal" 100: neither is what the card says


def test_the_six_recent_months_have_their_own_changes_and_the_oldest_comes_first():
    r = run(trend_world())
    assert [m["month"] for m in r["recent"]] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert all(m["change_pct"] == 0.18 and m["core_change_pct"] == 0.29 for m in r["recent"])
    data = world()
    step(data, FINAL, mback(LAST, 2), 100.456)                                       # 0.456% in 2026-08: two decimals give 0.46 (one decimal 0.5, cut 0.45)
    step(data, CORE, mback(LAST, 1), 99.0)
    r = run(data, today=TODAY)
    assert [(m["month"], m["change_pct"], m["core_change_pct"]) for m in r["recent"]][-3:] == [("2026-08", 0.46, 0.0), ("2026-09", 0.0, -1.0), ("2026-10", 0.0, 0.0)]


def test_a_change_that_rounds_to_zero_from_below_is_zero_and_not_negative_zero():
    data = world()
    data[FINAL][LAST] = 99.9996                                                      # -0.0004% on the month and on the year
    h = run(data)["headline"]
    assert h["change_pct"] == 0.0 and h["change_year_pct"] == 0.0
    assert math.copysign(1.0, h["change_pct"]) == 1.0 and math.copysign(1.0, h["change_year_pct"]) == 1.0


def test_the_level_is_the_newest_month_not_an_earlier_one():
    data = world()
    data[FINAL][LAST] = 101.0
    assert run(data)["headline"]["index"] == 101.0 and run(data)["headline"]["change_pct"] == 1.0


# ---------------------------------------------------------------- refusals fit the visible 110 characters

def test_every_refusal_fits_in_the_visible_110_characters_so_the_figure_is_not_cut_off():
    texts = []
    for sid in IDS:
        lo, hi = P.LIMITS[sid]
        texts.append(f"the {NAME[sid]} index of 1,234,567.8 in 2026-10 is outside {lo:g} to {hi:g}")
        mlo, mhi = P.MOVE_LIMITS[sid]
        texts.append(f"the {NAME[sid]} moved -9999.9% in 2026-10, outside {mlo:g} to {mhi:g}")
        texts.append(f"the {NAME[sid]} series covers different months than final demand")
    texts += [ENDS, FIRST, COUNT.format(n=131), "the producer price months skip a month after 2025-12"]
    for text in texts:
        assert len(text) <= 110, text
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

    svc = P.UsProducerPrices(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["headline"]["change_year_pct"] == 6.52 and n["n"] == 9 and r["demo"] is False and r["as_of"] == NOW.isoformat()
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 9


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(P.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = P.UsProducerPrices(client=_client(handler))
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


def test_the_age_and_the_freshness_come_from_the_time_of_the_question_in_the_class_too():
    later = datetime(2027, 3, 3, 12, tzinfo=timezone.utc)                            # a date no real run has: 153 days after 2026-10-01
    r = asyncio.run(P.UsProducerPrices(client=_client(_handler)).overview(later))
    assert r["age_days"] == 153 and r["freshness"] == "OVERDUE" and r["as_of"] == later.isoformat()
    r = asyncio.run(P.UsProducerPrices(client=_client(_handler)).overview(datetime(2026, 12, 15, 12, tzinfo=timezone.utc)))
    assert r["age_days"] == 75 and r["freshness"] == "CURRENT"


def test_an_answer_from_the_cache_carries_the_time_of_the_question():
    svc = P.UsProducerPrices(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(hours=1)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and {k: v for k, v in b.items() if k != "as_of"} == {k: v for k, v in a.items() if k != "as_of"}


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(P.UsProducerPrices(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US producer prices could not be read right now (the server had an error, HTTP 503)" and "headline" not in r and "groups" not in r
    r = asyncio.run(P.UsProducerPrices(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and "HTTP 204" in r["reason"]                      # anything but 200 is a failure


def test_one_series_failing_refuses_the_whole_card():
    def handler(req):
        return httpx.Response(503) if req.url.params["id"] == SERVICES else _handler(req)

    r = asyncio.run(P.UsProducerPrices(client=_client(handler)).overview(NOW))
    assert r["available"] is False and "headline" not in r and "groups" not in r


def test_a_failed_check_shows_nothing_and_says_which():
    bad = dict(F)
    bad[FINAL] = F[FINAL].replace("2026-10-01,160.254", "2026-10-01,1602.54")        # a decimal slip: outside the 50 to 320 range
    r = asyncio.run(P.UsProducerPrices(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US producer prices could not be read right now (the data failed a check: the final demand index of 1,602.5 in October 2026 is outside 50 to 320)" and "headline" not in r
    bad = dict(F)
    bad[ENERGY] = F[ENERGY].replace("2026-10-01,280.601", "2026-10-01,380.601")      # a digit slip that stays inside the range (10 to 560) and is found by the move limit
    r = asyncio.run(P.UsProducerPrices(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and r["reason"] == "US producer prices could not be read right now (the data failed a check: the finished consumer energy moved +36.0% in October 2026, outside -32 to 32)"
    bad = dict(F)
    bad[CORE] = F[CORE].replace("2026-10-01,156.740", "2026-10-01,x")
    r = asyncio.run(P.UsProducerPrices(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "a PPIFES row was unreadable" in r["reason"]


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(P.UsProducerPrices(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US producer prices could not be read right now (the connection could not be made)"


def test_a_missing_key_while_reading_the_answer_reads_plainly(monkeypatch):
    def boom(data, today):
        raise KeyError("PPIFIS")

    monkeypatch.setattr(P, "summarize", boom)
    r = asyncio.run(P.UsProducerPrices(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "US producer prices could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(P.UsProducerPrices(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real US producer price figures are not shown because made-up values would look real." and "headline" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/us-producer-prices")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]


def test_the_card_is_refreshed_with_the_other_macro_sources():
    jobs = (Path(__file__).parent.parent / "atlas_api" / "sched" / "jobs.py").read_text(encoding="utf-8")
    app = (Path(__file__).parent.parent / "atlas_api" / "app.py").read_text(encoding="utf-8")
    assert '"us_producer_prices"' in jobs and '"us_producer_prices": us_producer_prices' in app and "us_producer_prices = UsProducerPrices(demo=demo)" in app


def test_each_request_asks_for_one_series_from_2010_04_with_no_custom_user_agent():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(P.UsProducerPrices(client=_client(handler)).overview(NOW))
    assert {f"{req.url.scheme}://{req.url.host}{req.url.path}" for req in seen} == {"https://fred.stlouisfed.org/graph/fredgraph.csv"}
    ids = [req.url.params["id"] for req in seen]
    assert sorted(ids) == sorted(IDS) and all("," not in i for i in ids)             # never a combined request: FRED applies one start date to the first series only
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert {req.url.params["cosd"] for req in seen} == {"2010-04-01"}


def test_at_most_six_requests_are_in_flight_at_once():
    state = {"now": 0, "max": 0}

    async def handler(req):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return _handler(req)

    r = asyncio.run(P.UsProducerPrices(client=_client(handler)).overview(NOW))
    assert r["available"] is True and state["max"] == 6


def test_a_client_made_here_waits_25_seconds_and_is_closed_and_one_given_is_left_open(monkeypatch):
    seen = {"closed": False}

    class Fake:
        def __init__(self, **kw):
            seen["timeout"] = kw.get("timeout")

        async def get(self, url, params=None):
            return httpx.Response(200, text=F[params["id"]])

        async def aclose(self):
            seen["closed"] = True

    monkeypatch.setattr(P.httpx, "AsyncClient", Fake)
    r = asyncio.run(P.UsProducerPrices().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(P.UsProducerPrices(client=given).overview(NOW))
    assert given.is_closed is False
