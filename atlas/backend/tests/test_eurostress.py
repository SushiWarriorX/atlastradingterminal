"""Euro-area financial stress (ECB Data Portal, CISS dataflow): parsed from real responses (fetched 2026-11-17 23:2x UTC: the new CISS for the last 2,700 days to 2026-11-16 and its six contributions for the last 520 days, rounded to 8 decimals in the fixture; the whole record, 12,236 days of the index from 1980 and 7,272 of each contribution from 1999, was read to set the checks, see the module's docstring)."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import eurostress as S
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_stress.json").read_text())
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
LAST = date(2026, 11, 16)                                              # a Monday
UN = ("PURE_NUMB", "0")
I, B, E, N, X, M, C = "SS_CIN", "SS_BMN", "SS_EMN", "SS_FIN", "SS_FXN", "SS_MMN", "SS_CON"
SEG_IDS = (B, E, N, X, M)
NAMES = {I: "the stress index", C: "the correlation term", B: "the contribution of the bond market", E: "the contribution of the equity market", N: "the contribution of the financial intermediaries",
         X: "the contribution of the foreign exchange market", M: "the contribution of the money market"}
SEG = (0.03, 0.02, 0.025, 0.01, 0.015)                                 # sums to 0.1; with CORR the index is 0.05
CORR = -0.05
# the limits set from the real record, spelled out here so that a changed limit fails a test instead of moving the test with it
INDEX_LIMITS, INDEX_MOVE, SEGMENT_LIMITS, CORRELATION_LIMITS = (0.0, 1.0), (-0.25, 0.25), (0.0, 1.0), (-1.0, 0.0)


def _days(n, end=LAST):
    """`n` consecutive weekdays ending on `end`, oldest first."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _world(n=600, seg=SEG, corr=CORR, fn=None, status=None, end=LAST):
    """`n` weekdays ending 2026-11-16. `fn(i, day)` may give (five segment contributions, correlation term) for day number i; the index is their sum, so the ECB's identity holds by construction and every check but the one under test passes."""
    index, parts = {}, {sid: {} for sid in S.PART_IDS}
    for i, d in enumerate(_days(n, end)):
        s, c = fn(i, d) if fn else (seg, corr)
        for sid, v in zip(SEG_IDS, s):
            parts[sid][d] = v
        parts[C][d] = c
        index[d] = sum(s) + c
    return index, {I: UN}, parts, {sid: UN for sid in parts}, status if status is not None else {I: "A"}


def _real():
    c, k = F["composite"], F["contrib"]
    cd = [date.fromisoformat(x) for x in k["dates"]]
    parts = {sid: dict(zip(cd, k[sid])) for sid in S.PART_IDS}
    return {date.fromisoformat(d): v for d, v in zip(c["dates"], c["values"])}, {I: UN}, parts, {sid: UN for sid in parts}, {I: "A"}


def _run(world, today=TODAY):
    return S.summarize(*world, today)


def _err(world, today=TODAY):
    """The refusal's text, or None when the world passes every check."""
    try:
        _run(world, today)
    except ValueError as e:
        return str(e)
    return None


def _drop(world, days):
    for d in days:
        world[0].pop(d, None)
        for p in world[2].values():
            p.pop(d, None)
    return world


def _const(seg, corr):
    return lambda i, d: (seg, corr)


def test_the_real_latest_figures_the_ten_year_comparison_segments_and_checks_by_hand():
    r = _run(_real())
    assert r["available"] and r["date"] == "2026-11-16" and r["age_days"] == 1 and r["freshness"] == "CURRENT" and r["provisional"] is False
    assert r["index"] == 0.0054 and r["index"] == round(F["composite"]["values"][-1], 4)
    assert r["week_ago"] == {"date": "2026-11-09", "value": 0.0059, "change": -0.0005} and r["month_ago"] == {"date": "2026-10-16", "value": 0.0096, "change": -0.0042}
    assert r["window"] == {"days": 2616, "from": "2016-11-17", "years": 10, "median": 0.0437, "lowest": {"value": 0.0007, "date": "2017-11-27"}, "highest": {"value": 0.738, "date": "2022-10-17"}, "share_lower_pct": 8}
    assert r["segments"] == [{"id": B, "label": "bond market", "contribution": 0.031}, {"id": N, "label": "financial intermediaries", "contribution": 0.0269}, {"id": E, "label": "equity market", "contribution": 0.018},
                             {"id": M, "label": "money market", "contribution": 0.0129}, {"id": X, "label": "foreign exchange market", "contribution": 0.0079}]
    assert r["segments_total"] == 0.0966 == round(sum(F["contrib"][s][-1] for s in SEG_IDS), 4) and r["correlation"] == -0.0912 == round(F["contrib"][C][-1], 4)
    assert r["detail"] == {"days_checked": 2700, "contribution_days_checked": 520, "largest_daily_move": 0.1017, "largest_identity_gap": 2e-08}      # the gap is the fixture's rounding to 8 decimals
    assert list(r["checks"]) == ["units_ok", "days_in_a_row", "range_ok", "daily_move_ok", "segments_in_range_ok", "correlation_in_range_ok", "contributions_add_up_ok"] and all(r["checks"].values())
    assert r["source"].startswith("European Central Bank") and r["url"] == "https://data-api.ecb.europa.eu/service/data/CISS/D.U2.Z0Z.4F.EC.SS_CIN.IDX" and "not a market signal or a forecast" in r["note"]


def test_the_newest_day_is_provisional_only_when_the_source_says_so():
    for status, want in (({I: "A"}, False), ({}, False), ({I: ""}, False), ({I: "P"}, True), ({I: "E"}, True), ({B: "P"}, False)):
        assert _run(_world(status=status))["provisional"] is want, status


def test_overdue_after_8_days_from_the_last_day():
    w = _world()
    for age, want in ((0, "CURRENT"), (8, "CURRENT"), (9, "OVERDUE"), (30, "OVERDUE")):
        r = _run(w, LAST + timedelta(days=age))
        assert (r["age_days"], r["freshness"]) == (age, want)


def test_the_ten_year_comparison_needs_1300_days_and_counts_only_the_days_after_the_ten_year_mark():
    assert _run(_world(1299))["window"] is None and _run(_world(1300))["window"]["days"] == 1300
    w = _run(_world(2700))["window"]
    assert w["days"] == 2608 and w["from"] == "2016-11-17"                                           # 2,608 weekdays from 2016-11-17 to 2026-11-16 (counted by hand outside the module): the day exactly 3,652 days back (2016-11-16) is not in, the one 3,651 back is
    assert (LAST - timedelta(days=3652)).weekday() < 5 and (LAST - timedelta(days=3651)).weekday() < 5


def _share(below, equal, above):
    """A world with that many days below, equal to and above the newest value (the newest is one of the equal ones); every step is smaller than the daily bound."""
    vals = [0.20] * above + [0.05] * below + [0.10] * equal
    return _world(len(vals), fn=lambda i, d: ((vals[i], 0.0, 0.0, 0.0, 0.0), 0.0))


def test_the_share_of_calmer_days_counts_only_days_strictly_below_and_is_a_whole_percent():
    assert _run(_share(420, 100, 880))["window"]["share_lower_pct"] == 30                           # 420 of 1,400; the 100 equal days are not lower
    assert _run(_share(421, 100, 879))["window"]["share_lower_pct"] == 30                           # 30.07
    assert _run(_share(428, 100, 872))["window"]["share_lower_pct"] == 31                           # 30.57
    assert _run(_share(0, 1400, 0))["window"]["share_lower_pct"] == 0


def test_median_lowest_and_highest_with_their_days_and_ties_name_the_earlier_day():
    def fn(i, d):                                                                                      # 2 days at 0.02, 698 at 0.10, 698 at 0.12, 2 at 0.30: the 700th and 701st of 1,400 are 0.10 and 0.12
        v = 0.02347 if i in (100, 200) else 0.30126 if i in (350, 450) else (0.10 if (i // 50) % 2 == 0 else 0.12)
        return (v, 0.0, 0.0, 0.0, 0.0), 0.0
    days = _days(1400)
    r = _run(_world(1400, fn=fn))["window"]
    assert r["lowest"] == {"value": 0.0235, "date": days[100].isoformat()} and r["highest"] == {"value": 0.3013, "date": days[350].isoformat()}      # not 0.023 and 0.301
    assert r["median"] == 0.11                                                                         # an even number of days: the average of the middle two


def test_a_week_and_a_month_back_use_the_newest_day_on_or_before_the_target_and_say_which_day():
    w = _world(60, fn=lambda i, d: ((0.01 * (i % 10), 0.0, 0.0, 0.0, 0.0), 0.0))
    r = _run(w)
    exact = date(2026, 11, 9)                                                                          # seven days before Monday 2026-11-16 is a weekday that exists
    assert r["week_ago"]["date"] == exact.isoformat() and r["month_ago"]["date"] == "2026-10-16"      # thirty days back is a Saturday: the Friday before
    _drop(w, [exact])                                                                                  # without that day the Friday before it is the newest on or before the target
    assert _run(w)["week_ago"]["date"] == "2026-11-06"
    three = _world(3)
    assert _run(three)["week_ago"] is None and _run(three)["month_ago"] is None
    wed = date(2026, 11, 18)                                                                           # a Wednesday: seven days back is a Wednesday and thirty days back a Monday, both existing days
    r = _run(_world(60, end=wed, fn=lambda i, d: ((0.01 * (i % 10), 0.0, 0.0, 0.0, 0.0), 0.0)), wed + timedelta(days=1))
    assert (r["week_ago"]["date"], r["month_ago"]["date"]) == ("2026-11-11", "2026-10-19")           # 6, 8, 29 and 31 days back would name the Tuesday, the Thursday, the Sunday's Friday and the Tuesday after


def test_the_change_over_a_week_is_taken_before_rounding():
    vals = {date(2026, 11, 9): 0.099951, LAST: 0.100049}
    w = _world(60, fn=lambda i, d: ((vals.get(d, 0.1), 0.0, 0.0, 0.0, 0.0), 0.0))
    r = _run(w)
    assert (r["index"], r["week_ago"]["value"], r["week_ago"]["change"]) == (0.1, 0.1, 0.0001)         # the two values both round to 0.1000, the change of 0.000098 rounds to 0.0001


def test_figures_are_rounded_to_four_decimals_even_when_the_source_gives_more():
    seg, corr = (0.03123456, 0.02234567, 0.01345678, 0.00456789, 0.00567891), -0.04567391
    r = _run(_world(seg=seg, corr=corr))
    assert (r["index"], r["segments_total"], r["correlation"]) == (0.0316, 0.0773, -0.0457)
    assert [(s["id"], s["contribution"]) for s in r["segments"]] == [(B, 0.0312), (E, 0.0223), (N, 0.0135), (M, 0.0057), (X, 0.0046)]
    for v in (0.0316099, 0.07728381, 0.04567391, 0.03123456, 0.02234567, 0.01345678, 0.00567891, 0.00456789):
        assert round(v, 5) != round(v, 4) and round(v, 3) != round(v, 4), v                           # the world really tells four decimals from three and from five


def test_segments_are_listed_largest_first_and_equal_contributions_keep_the_order_of_the_segments():
    assert [s["id"] for s in _run(_world(seg=(0.01, 0.05, 0.02, 0.04, 0.03), corr=-0.1))["segments"]] == [E, X, M, N, B]
    assert [s["id"] for s in _run(_world(seg=(0.02, 0.02, 0.02, 0.02, 0.02), corr=-0.05))["segments"]] == [B, E, N, X, M]


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    for sid in (I,) + S.PART_IDS:
        for bad in (("PURE_NUMB", "3"), ("PC", "0"), ("", ""), ("PURE_NUMB", "")):
            w = _world()
            (w[1] if sid == I else w[3])[sid] = bad
            assert _err(w) == f"the ECB reports {NAMES[sid]} in other units than the card assumes", (sid, bad)
    assert _err(_world()) is None


def test_series_ending_on_different_days_are_refused():
    for sid in (I,) + S.PART_IDS:
        w = _world()
        (w[0] if sid == I else w[2][sid]).pop(LAST)
        assert _err(w) == "the stress series end on different days", sid
        w = _world()
        (w[0] if sid == I else w[2][sid])[LAST + timedelta(days=1)] = 0.05 if sid == I else (CORR if sid == C else 0.02)
        assert _err(w) == "the stress series end on different days", sid


def test_a_hole_of_more_than_5_days_in_the_index_is_refused_and_5_days_is_not():
    days = _days(600)
    def hole(*gone):
        return _drop(_world(), gone)
    fri = next(d for d in days if d.weekday() == 4 and d > days[0] + timedelta(days=60))             # Friday, then drop Monday and Tuesday: Friday to Wednesday is 5 days
    mon, tue, wed = fri + timedelta(days=3), fri + timedelta(days=4), fri + timedelta(days=5)
    assert _err(hole(mon, tue)) is None
    assert _err(hole(mon, tue, wed)) == f"the stress index skips from {fri.isoformat()} to {(fri + timedelta(days=6)).isoformat()}, more than 5 days"
    old = days[10]                                                                                      # a hole at the start of the fetched window counts too
    while old.weekday() != 4:
        old += timedelta(days=1)
    assert _err(hole(old + timedelta(days=3), old + timedelta(days=4))) is None
    assert _err(hole(old + timedelta(days=3), old + timedelta(days=4), old + timedelta(days=5))).startswith(f"the stress index skips from {old.isoformat()} to ")


def test_a_contribution_missing_one_of_the_last_520_days_is_refused_and_an_older_one_is_not():
    days = _days(600)
    for sid in S.PART_IDS:
        w = _world()
        w[2][sid].pop(days[-100])
        assert _err(w) == f"{NAMES[sid]} is missing for {days[-100].isoformat()}", sid
        w = _world()
        w[2][sid].pop(days[-520])
        assert _err(w) == f"{NAMES[sid]} is missing for {days[-520].isoformat()}", sid
        w = _world()
        w[2][sid].pop(days[-521])
        assert _err(w) is None, sid


def test_the_index_must_be_inside_0_to_1_on_every_day_of_the_window():
    assert _err(_world(fn=_const((0.0, 0.0, 0.0, 0.0, 0.0), 0.0))) is None                          # exactly 0
    assert _err(_world(fn=_const((0.5, 0.5, 0.0, 0.0, 0.0), 0.0))) is None                          # exactly 1
    days = _days(600)
    assert _err(_world(fn=_const((0.0, 0.0, 0.0, 0.0, 0.0), -0.0000001))) == f"the stress index is -0.0000 on {days[0].isoformat()}, outside 0 to 1"
    assert _err(_world(fn=_const((0.5, 0.5, 0.0, 0.0, 0.0000001), 0.0))) == f"the stress index is 1.0000 on {days[0].isoformat()}, outside 0 to 1"
    over = lambda day_no: _world(fn=lambda i, d: ((0.5, 0.5, 0.0, 0.0, 0.0001), 0.0) if i == day_no else ((0.5, 0.5, 0.0, 0.0, 0.0), 0.0))
    assert _err(over(0)) == f"the stress index is 1.0001 on {days[0].isoformat()}, outside 0 to 1"          # one day only: the oldest of the window is looked at ...
    assert _err(over(599)) == f"the stress index is 1.0001 on {LAST.isoformat()}, outside 0 to 1"             # ... and the newest
    under = _world(fn=lambda i, d: ((0.0, 0.0, 0.0, 0.0, 0.0), -0.0001 if i == 599 else 0.0))
    assert _err(under) == f"the stress index is -0.0001 on {LAST.isoformat()}, outside 0 to 1"


def _step(before, after, at=-1):
    """A world whose index is `before` for the days before day number `600 + at` and `after` from then on (the first segment carries the value, so the ECB's identity holds)."""
    return _world(fn=lambda i, d: (((before if i < 600 + at else after), 0.0, 0.0, 0.0, 0.0), 0.0))


def test_a_one_day_move_of_the_index_over_0_25_is_refused_and_exactly_0_25_is_not():
    last = LAST.isoformat()
    assert _err(_step(0.5, 0.75)) is None and _err(_step(0.75, 0.5)) is None                         # exactly +0.25 and exactly -0.25 (exact in binary)
    assert _err(_step(0.5, 0.75 + 2 ** -20)) == f"the stress index moved by +0.2500 on {last}, outside -0.25 to +0.25"
    assert _err(_step(0.75, 0.5 - 2 ** -20)) == f"the stress index moved by -0.2500 on {last}, outside -0.25 to +0.25"
    assert _err(_step(0.5, 0.6)) is None and _err(_step(0.5, 0.9)).startswith("the stress index moved by +0.4000")
    assert _err(_step(0.9, 0.5)).startswith("the stress index moved by -0.4000")


def test_the_move_check_looks_at_the_whole_window_not_only_the_last_520_days():
    assert _err(_step(0.5, 0.9, at=-300)).startswith("the stress index moved by +0.4000")            # 299 days back: inside the last 520
    w = _world(fn=lambda i, d: ((0.5, 0.0, 0.0, 0.0, 0.0) if i < 30 else (0.9, 0.0, 0.0, 0.0, 0.0), 0.0))
    assert _err(w) == f"the stress index moved by +0.4000 on {_days(600)[30].isoformat()}, outside -0.25 to +0.25"      # 570 days back: older than the contributions' window


def test_each_segment_must_contribute_between_0_and_1_and_only_over_the_last_520_days():
    days = _days(600)
    for k, sid in enumerate(SEG_IDS):
        assert _err(_world(fn=_const(tuple(1.0 if j == k else 0.0 for j in range(5)), 0.0))) is None    # exactly 1
        assert _err(_world(fn=_const((0.0, 0.0, 0.0, 0.0, 0.0), 0.0))) is None                          # exactly 0
        low = tuple(-0.0000001 if j == k else 0.1 for j in range(5))
        assert _err(_world(fn=_const(low, -0.1))) == f"{NAMES[sid]} is -0.0000 on {days[-520].isoformat()}, outside 0 to 1", sid
        high = tuple(1.0000001 if j == k else 0.0 for j in range(5))
        assert _err(_world(fn=_const(high, -0.5))) == f"{NAMES[sid]} is +1.0000 on {days[-520].isoformat()}, outside 0 to 1", sid
    w = _world()
    w[2][B][days[-521]] = -0.5
    assert _err(w) is None                                                                              # older than the last 520 days: not looked at
    w[2][B][days[-520]] = -0.5
    assert _err(w) == f"the contribution of the bond market is -0.5000 on {days[-520].isoformat()}, outside 0 to 1"


def test_the_correlation_term_must_lie_between_minus_1_and_0():
    days = _days(600)
    assert _err(_world(fn=_const((0.0, 0.0, 0.0, 0.0, 0.0), 0.0))) is None                          # exactly 0
    assert _err(_world(fn=_const((0.5, 0.5, 0.5, 0.5, 0.0), -1.0))) is None                          # exactly -1
    assert _err(_world(fn=_const((0.1, 0.1, 0.1, 0.1, 0.1), 0.0000001))) == f"the correlation term is +0.0000 on {days[-520].isoformat()}, outside -1 to 0"
    assert _err(_world(fn=_const((0.5, 0.5, 0.5, 0.5, 0.0), -1.0000001))) == f"the correlation term is -1.0000 on {days[-520].isoformat()}, outside -1 to 0"
    w = _world()
    w[2][C][days[-521]] = 0.3
    assert _err(w) is None
    w[2][C][days[-520]] = 0.3
    assert _err(w) == f"the correlation term is +0.3000 on {days[-520].isoformat()}, outside -1 to 0"


def test_the_contributions_must_add_up_to_the_index_within_a_millionth_over_the_last_520_days():
    days = _days(600)
    for sid in S.PART_IDS:
        w = _world()
        w[2][sid][LAST] += 0.0000005
        r = _run(w)
        assert r["detail"]["largest_identity_gap"] == 5e-07, sid                                        # inside the tolerance and reported
        w = _world()
        w[2][sid][LAST] += 0.000002
        assert _err(w) == f"the contributions do not add up to the stress index on {LAST.isoformat()} (off by -0.000002)", sid
        w = _world()
        w[2][sid][LAST] -= 0.000002
        assert _err(w) == f"the contributions do not add up to the stress index on {LAST.isoformat()} (off by +0.000002)", sid
    w = _world()
    w[0][days[-521]] += 0.01
    assert _err(w) is None                                                                              # older than the last 520 days: not looked at
    w[0][days[-520]] += 0.01
    assert _err(w) == f"the contributions do not add up to the stress index on {days[-520].isoformat()} (off by +0.010000)"


def test_a_gap_of_exactly_the_tolerance_is_allowed_and_a_little_more_is_not():
    w = _world(fn=_const((0.0, 0.0, 0.0, 0.0, 0.0), 0.0))
    for d in w[0]:
        w[0][d] = 0.000001                                                                              # every contribution is 0 and the index is exactly the tolerance: the same number, so the gap is exactly 0.000001
    assert _run(w)["detail"]["largest_identity_gap"] == 1e-06
    for d in w[0]:
        w[0][d] = 0.0000011
    assert _err(w) == f"the contributions do not add up to the stress index on {_days(600)[-520].isoformat()} (off by +0.000001)"


def test_a_moved_contribution_series_is_caught_by_the_sum_even_when_each_value_is_plausible():
    w = _world(fn=lambda i, d: ((0.03 + 0.001 * (i % 7), 0.02, 0.025, 0.01, 0.015), -0.05))
    shifted = {d: w[2][B][nxt] for d, nxt in zip(_days(600), _days(600)[1:])}                       # the bond market's contributions of the next day: a series one day out of step
    shifted[LAST] = w[2][B][LAST]
    w[2][B].update(shifted)
    assert _err(w).startswith("the contributions do not add up to the stress index on ")


def test_the_largest_move_and_the_largest_gap_are_reported_rounded_to_four_and_nine_decimals():
    w = _world(fn=lambda i, d: ((0.05 + (0.1234567 if i == 599 else 0.0), 0.0, 0.0, 0.0, 0.0), 0.0))
    assert _run(w)["detail"]["largest_daily_move"] == 0.1235
    fall = _world(fn=lambda i, d: ((0.5 if i < 599 else 0.35, 0.0, 0.0, 0.0, 0.0), 0.0))
    assert _run(fall)["detail"]["largest_daily_move"] == 0.15                                          # the largest move in size, whichever way it goes
    w = _world()
    w[2][B][LAST] += 0.000000456789
    assert _run(w)["detail"]["largest_identity_gap"] == 4.57e-07


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    assert list(_run(_world())["checks"]) == ["units_ok", "days_in_a_row", "range_ok", "daily_move_ok", "segments_in_range_ok", "correlation_in_range_ok", "contributions_add_up_ok"]
    days = _days(600)
    fri = next(d for d in days if d.weekday() == 4 and d > days[0] + timedelta(days=60))
    hole = [fri + timedelta(days=k) for k in (3, 4, 5)]                                                  # Monday to Wednesday after a Friday: a hole of 6 days
    w = _world()
    w[1][I] = ("PC", "0")
    w[2][B].pop(LAST)
    assert _err(w).startswith("the ECB reports the stress index in other units")                    # the units before the end days
    w = _world()
    w[2][B].pop(LAST)
    _drop(w, hole)
    assert _err(w) == "the stress series end on different days"                                       # the end days before the holes
    w = _world()
    _drop(w, hole)
    w[0][LAST] = 1.5
    assert _err(w).startswith("the stress index skips from ")                                         # the holes before the range
    w = _world()
    w[0][LAST] = 1.5
    w[2][B][LAST] = -0.5
    assert _err(w).startswith("the stress index is 1.5000")                                           # the range of the index before its move and before the contributions
    w = _world()
    w[0][LAST] = 0.9
    w[2][B][LAST] = -0.5
    assert _err(w).startswith("the stress index moved by +0.8500")                                    # the move before the contributions' range
    w = _world()
    w[2][B][LAST] = -0.5
    w[2][C][LAST] = 0.5
    assert _err(w).startswith("the contribution of the bond market is -0.5000")                       # the segments before the correlation term
    w = _world()
    w[2][C][LAST] = 0.5
    assert _err(w).startswith("the correlation term is +0.5000")                                      # the ranges before the sum (the sum is off by 0.55 as well)


def test_the_real_window_passes_every_check_and_its_largest_real_moves_are_pinned():
    r = _run(_real())
    assert r["available"] and r["detail"]["largest_daily_move"] == 0.1017                              # +0.1017 on 2022-09-23, the largest in the ten years; the whole record's largest is +0.1364 (2010)
    index = _real()[0]
    assert round(index[date(2022, 9, 23)] - index[date(2022, 9, 22)], 4) == 0.1017 and round(index[date(2022, 7, 4)] - index[date(2022, 7, 1)], 4) == -0.0627
    assert min(index.values()) == 0.00068515 and max(index.values()) == 0.73804464 and len(index) == 2700


def test_the_limits_and_tolerances_are_the_ones_set_from_the_real_record():
    assert (S.INDEX_LIMITS, S.INDEX_MOVE, S.SEGMENT_LIMITS, S.CORRELATION_LIMITS) == (INDEX_LIMITS, INDEX_MOVE, SEGMENT_LIMITS, CORRELATION_LIMITS)
    assert (S.IDENTITY_TOLERANCE, S.MAX_GAP_DAYS, S.UNIT) == (0.000001, 5, UN)
    assert (S.INDEX_LAST_N, S.PARTS_LAST_N, S.WINDOW_DAYS, S.MIN_WINDOW_DAYS, S.OVERDUE_AFTER_DAYS) == (2700, 520, 3652, 1300, 8)
    assert S.INDEX == I and S.CORRELATION == C and S.PART_IDS == (B, E, N, X, M, C) and S.NAMES == NAMES
    assert S.INDEX_KEY == "D.U2.Z0Z.4F.EC.SS_CIN.IDX" and S.PARTS_KEY == "D.U2.Z0Z.4F.EC.SS_BMN+SS_EMN+SS_FIN+SS_FXN+SS_MMN+SS_CON.CON"
    assert "the ECB's own arithmetic" in S.__doc__ and "not that the figures are right" in S.__doc__ and "12,236 days" in S.__doc__ and "7,272" in S.__doc__ and "Properties that are not the ECB's own sum" in S.__doc__


HEAD = "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
OK = "CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX"


def test_the_real_layout_of_a_response_is_read():
    v, units, status = S.parse(F["raw_head"], "IDX", (I,))
    assert v == {I: {date(2026, 11, 13): 0.00521175167227121, date(2026, 11, 16): 0.005381544281470239}} and units == {I: UN} and status == {I: "A"}
    assert F["raw_head"].startswith("KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,")


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_day_are_an_error():
    text = HEAD + f"{OK},2026-11-10,0.5,A,PURE_NUMB,0\n{OK},2026-11-11,,M,PURE_NUMB,0\n{OK},2026-11-12,n/a,A,PURE_NUMB,0\n{OK},2026-11,1,A,PURE_NUMB,0\n{OK},2026-11-1x,1,A,PURE_NUMB,0\n{OK},2026-13-40,1,A,PURE_NUMB,0\n{OK},2026-11-13T00:00,1,A,PURE_NUMB,0\n{OK},2026-11-100,0.9,A,PURE_NUMB,0\n"
    text += f"{OK},2026-11-09,nan,A,PURE_NUMB,0\n{OK},2026-11-06,inf,A,PURE_NUMB,0\nCISS.D.DE.Z0Z.4F.EC.SS_CIN.IDX,2026-11-10,0.9,A,PURE_NUMB,0\nCISS.D.U2.Z0Z.4F.EC.SS_CI.IDX,2026-11-10,0.8,A,PURE_NUMB,0\nCISS.D.U2.Z0Z.4F.EC.SS_CIN.CON,2026-11-10,0.7,A,PURE_NUMB,0\n"
    text += f"CISS.M.U2.Z0Z.4F.EC.SS_CIN.IDX,2026-11-10,0.6,A,PURE_NUMB,0\nCISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX.X,2026-11-10,0.55,A,PURE_NUMB,0\nCISS.D.U2.Z0Z.4F.EC.SS_BMN.IDX,2026-11-10,0.4,A,PURE_NUMB,0\n"
    v, units, status = S.parse(text, "IDX", (I,))
    assert v == {I: {date(2026, 11, 10): 0.5}} and units == {I: UN} and status == {I: "A"}            # a day with no value, a month, a bad day, a day with a time, nan, inf and every other series are all left out
    padded = HEAD + f"{OK},2026-11-10,0.5, P , PURE_NUMB , 0 \n"
    assert S.parse(padded, "IDX", (I,))[1] == {I: UN} and S.parse(padded, "IDX", (I,))[2] == {I: "P"}   # spaces around a unit or a status are not a different one
    two = HEAD + f"{OK},2026-11-09,0.1,A,PURE_NUMB,0\n{OK},2026-11-11,0.3,P,PURE_NUMB,0\n{OK},2026-11-10,0.2,A,PURE_NUMB,0\n"
    assert S.parse(two, "IDX", (I,))[2] == {I: "P"}                                                   # the status is the newest day's, whatever the order of the rows
    with pytest.raises(ValueError, match=r"SS_CIN has two values for 2026-11-10"):
        S.parse(text + f"{OK},2026-11-10,0.1,A,PURE_NUMB,0\n", "IDX", (I,))
    with pytest.raises(ValueError, match=r"no values for SS_EMN"):
        S.parse(text, "IDX", (I, E))                                                                    # a series asked for and absent from the response (SS_BMN's row above is not asked for)
    con = HEAD + "".join(f"CISS.D.U2.Z0Z.4F.EC.{sid}.CON,2026-11-10,0.1,A,PURE_NUMB,0\n" for sid in S.PART_IDS)
    assert S.parse(con, "CON", S.PART_IDS)[0] == {sid: {date(2026, 11, 10): 0.1} for sid in S.PART_IDS}
    with pytest.raises(ValueError, match=r"no values for SS_CIN"):
        S.parse(con, "IDX", (I,))                                                                       # the contributions' rows are not the index's


def _index_text(replace=None):
    c = F["composite"]
    rows = [f"{OK},{d},{v},A,PURE_NUMB,0" for d, v in zip(c["dates"], c["values"])]
    text = HEAD + "\n".join(rows) + "\n"
    return text.replace(*replace) if replace else text


def _parts_text():
    k = F["contrib"]
    return HEAD + "\n".join(f"CISS.D.U2.Z0Z.4F.EC.{sid}.CON,{d},{k[sid][i]},A,PURE_NUMB,0" for sid in S.PART_IDS for i, d in enumerate(k["dates"])) + "\n"


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req, replace=None):
    return httpx.Response(200, text=_index_text(replace) if req.url.path.endswith(".IDX") else _parts_text())


def test_overview_fetches_two_requests_and_caches():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = S.EuroStress(client=_transport(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["index"] == 0.0054 and len(seen) == 2 and r["source"].startswith("European Central Bank")
    assert {req.url.path: req.url.params["lastNObservations"] for req in seen} == {"/service/data/CISS/D.U2.Z0Z.4F.EC.SS_CIN.IDX": "2700", "/service/data/CISS/D.U2.Z0Z.4F.EC.SS_BMN+SS_EMN+SS_FIN+SS_FXN+SS_MMN+SS_CON.CON": "520"}
    assert all(req.url.params["format"] == "csvdata" for req in seen) and all(req.headers["user-agent"] == "ATLAS research terminal" for req in seen)
    assert all("%2B" not in str(req.url) for req in seen) and any("+" in str(req.url) for req in seen)  # the + that joins the series of one key must reach the ECB as it is
    asyncio.run(svc.overview(NOW))
    assert len(seen) == 2


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(S.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = S.EuroStress(client=_transport(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 2
    clock["t"] += S.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 2                                                                                 # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 4                         # two minutes on it asks again
    clock["t"] += S.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 4
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6 and (S.FAIL_TTL, S.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(S.EuroStress(client=_transport(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "index" not in r
    slip = (f"{OK},2026-11-16,0.00538154,", f"{OK},2026-11-16,0.538154,")                                # a decimal slip in the newest value: a check failing shows nothing either
    assert slip[0] in _index_text() and slip[1] in _index_text(slip)
    r = asyncio.run(S.EuroStress(client=_transport(lambda req: _handler(req, slip))).overview(NOW))
    assert r["available"] is False and "the stress index moved by +0.5329 on 2026-11-16, outside -0.25 to +0.25" in r["reason"] and "index" not in r


def test_a_response_in_other_units_is_refused_and_shows_nothing():
    for which, what in (("IDX", "the stress index"), ("CON", "the contribution of the bond market")):
        def handler(req, which=which):
            r = _handler(req)
            return httpx.Response(200, text=r.text.replace(",A,PURE_NUMB,0", ",A,PURE_NUMB,3")) if req.url.path.endswith("." + which) else r
        r = asyncio.run(S.EuroStress(client=_transport(handler)).overview(NOW))
        assert r["available"] is False and f"the ECB reports {what} in other units than the card assumes" in r["reason"] and "index" not in r, which


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(S.EuroStress(client=_transport(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The euro-area stress index could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(S.EuroStress(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "index" not in d
    assert d["reason"] == "Demo mode: the real euro-area stress index is not shown because made-up values would look real."


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-stress")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
