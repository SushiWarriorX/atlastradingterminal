"""Euro-area government bond yields (ECB Data Portal, YC dataflow, AAA curve): parsed from real responses (fetched 2026-11-18 02:2x UTC: SR_10Y for the last 2,700 days to 2026-11-16, eight other rates and spreads for the last 520 days and the six model parameters of the newest day; the whole record, 5,675 business days from 2004-09-06 for fifteen series, was read to set the checks, see the module's docstring)."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import euroyields as S
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_yields.json").read_text())
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
LAST = date(2026, 11, 16)                                              # a Monday
UN = ("PCPA", "0")
TEN = "SR_10Y"
RATES = ("SR_3M", "SR_1Y", "SR_2Y", "SR_5Y", "SR_10Y", "SR_30Y")
SPREADS = ("SRS_10Y_3M", "SRS_10Y_1Y", "SRS_10Y_2Y")
SPREAD_OF = {"SRS_10Y_3M": "SR_3M", "SRS_10Y_1Y": "SR_1Y", "SRS_10Y_2Y": "SR_2Y"}
PARAMS = ("BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2")
YEARS = {"SR_3M": 0.25, "SR_1Y": 1.0, "SR_2Y": 2.0, "SR_5Y": 5.0, "SR_10Y": 10.0, "SR_30Y": 30.0}
NAMES = {"SR_3M": "the 3-month rate", "SR_1Y": "the 1-year rate", "SR_2Y": "the 2-year rate", "SR_5Y": "the 5-year rate", "SR_10Y": "the 10-year rate", "SR_30Y": "the 30-year rate",
         "SRS_10Y_3M": "the spread of the 10-year over the 3-month rate", "SRS_10Y_1Y": "the spread of the 10-year over the 1-year rate", "SRS_10Y_2Y": "the spread of the 10-year over the 2-year rate",
         "BETA0": "model parameter Beta 0", "BETA1": "model parameter Beta 1", "BETA2": "model parameter Beta 2", "BETA3": "model parameter Beta 3", "TAU1": "model parameter Tau 1", "TAU2": "model parameter Tau 2"}
# the limits set from the real record, spelled out here so that a changed limit fails a test instead of moving the test with it
RATE_LIMITS, SPREAD_LIMITS = (-3.0, 10.0), (-4.0, 6.0)
PARAM_LIMITS = {"BETA0": (-3.0, 10.0), "BETA1": (-10.0, 10.0), "BETA2": (-30.0, 60.0), "BETA3": (-60.0, 30.0), "TAU1": (0.1, 30.0), "TAU2": (0.1, 30.0)}
MOVES = {"SR_3M": (-1.5, 0.5), "SR_1Y": (-0.8, 0.5), "SR_2Y": (-0.8, 0.5), "SR_5Y": (-0.6, 0.5), "SR_10Y": (-0.5, 0.5), "SR_30Y": (-1.0, 0.6), "SRS_10Y_3M": (-0.6, 1.5), "SRS_10Y_1Y": (-0.5, 0.5), "SRS_10Y_2Y": (-0.4, 0.6)}
P0 = {"BETA0": 2.0, "BETA1": -1.0, "BETA2": 3.0, "BETA3": 1.0, "TAU1": 2.0, "TAU2": 8.0}
ZERO = {"BETA0": 0.0, "BETA1": 0.0, "BETA2": 0.0, "BETA3": 0.0, "TAU1": 2.0, "TAU2": 8.0}          # a flat curve at 0: every rate and spread is exactly 0.0
K = S.svensson({**P0, "BETA0": 0.0}, 10.0)                                                         # the 10-year rate of P0 without its Beta 0: a level L needs Beta 0 = L - K


def _days(n, end=LAST):
    """`n` consecutive weekdays ending on `end`, oldest first."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _world(n=600, params=None, fn=None, status=None, end=LAST, dates=None):
    """`n` weekdays ending 2026-11-16 (or the given `dates`). `fn(i, day)` may give the model parameters of day number i; every rate is the Svensson curve of that day's parameters and every spread is the 10-year rate minus the shorter one, so both of the ECB's identities hold by construction and every check but the one under test passes. The parameters are given for the newest day only, as the provider fetches them."""
    days = dates or _days(n, end)
    v = {sid: {} for sid in RATES + SPREADS}
    for i, d in enumerate(days):
        p = fn(i, d) if fn else (params or P0)
        for sid in RATES:
            v[sid][d] = S.svensson(p, YEARS[sid])
        for sid, other in SPREAD_OF.items():
            v[sid][d] = v[TEN][d] - v[other][d]
    for sid in PARAMS:
        v[sid] = {days[-1]: p[sid]}
    return v, {sid: UN for sid in v}, status if status is not None else {TEN: "A"}


def _level(levels, **kw):
    """A world whose 10-year rate is `levels[i]` on day i (the other rates follow the same curve shifted)."""
    return _world(len(levels), fn=lambda i, d: {**P0, "BETA0": levels[i] - K}, **kw)


def _real():
    t, o = F["ten"], F["others"]
    v = {TEN: {date.fromisoformat(d): x for d, x in zip(t["dates"], t["values"])}}
    od = [date.fromisoformat(d) for d in o["dates"]]
    for sid in ("SR_3M", "SR_1Y", "SR_2Y", "SR_5Y", "SR_30Y") + SPREADS:
        v[sid] = dict(zip(od, o[sid]))
    for sid in PARAMS:
        v[sid] = {date.fromisoformat(F["params"]["date"]): F["params"][sid]}
    return v, {sid: UN for sid in v}, {TEN: "A"}


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
        for s in world[0].values():
            s.pop(d, None)
    return world


def _follow(sid, first_day):
    """The refusal a world gets once the range or move check has let `sid` through: the identity that the changed series breaks."""
    if sid == TEN:
        return f"{NAMES['SRS_10Y_3M']} is not the difference of the two rates on {first_day.isoformat()}"
    if sid in SPREADS:
        return f"{NAMES[sid]} is not the difference of the two rates on {first_day.isoformat()}"
    for sp, other in SPREAD_OF.items():
        if other == sid:
            return f"{NAMES[sp]} is not the difference of the two rates on {first_day.isoformat()}"
    return f"{NAMES[sid]} on {LAST.isoformat()} is "


def test_the_real_latest_rates_spreads_ten_year_comparison_and_checks_by_hand():
    r = _run(_real())
    assert r["available"] and r["date"] == "2026-11-16" and r["age_days"] == 1 and r["freshness"] == "CURRENT" and r["provisional"] is False
    want = [("SR_3M", "3 months", 0.25, 2.65, ("2026-11-09", 2.61, 0.04), ("2026-10-16", 2.57, 0.08)), ("SR_1Y", "1 year", 1.0, 2.99, ("2026-11-09", 2.85, 0.13), ("2026-10-16", 2.89, 0.1)),
            ("SR_2Y", "2 years", 2.0, 3.11, ("2026-11-09", 2.94, 0.17), ("2026-10-16", 3.03, 0.08)), ("SR_5Y", "5 years", 5.0, 3.17, ("2026-11-09", 3.01, 0.16), ("2026-10-16", 3.16, 0.02)),
            ("SR_10Y", "10 years", 10.0, 3.42, ("2026-11-09", 3.27, 0.15), ("2026-10-16", 3.44, -0.02)), ("SR_30Y", "30 years", 30.0, 3.67, ("2026-11-09", 3.57, 0.1), ("2026-10-16", 3.71, -0.04))]
    assert r["rates"] == [{"id": i, "label": lab, "years": y, "rate_pct": x, "week_ago": {"date": w[0], "value": w[1], "change": w[2]}, "month_ago": {"date": m[0], "value": m[1], "change": m[2]}} for i, lab, y, x, w, m in want]
    assert r["spreads"] == [{"id": "SRS_10Y_3M", "label": "10 years minus 3 months", "points": 0.77}, {"id": "SRS_10Y_1Y", "label": "10 years minus 1 year", "points": 0.44}, {"id": "SRS_10Y_2Y", "label": "10 years minus 2 years", "points": 0.31}]
    assert r["window"] == {"days": 2550, "from": "2016-11-17", "years": 10, "median": 0.58, "lowest": {"value": -0.82, "date": "2020-03-09"}, "highest": {"value": 3.63, "date": "2026-09-28"}, "share_lower_pct": 99}
    assert r["detail"] == {"days_checked": 2700, "rate_days_checked": 520, "largest_spread_gap": 0.0, "largest_curve_gap": 0.0}
    assert list(r["checks"]) == ["units_ok", "days_in_a_row", "range_ok", "daily_move_ok", "parameters_in_range_ok", "spreads_are_differences_ok", "rates_follow_the_curve_ok"] and all(r["checks"].values())
    assert r["source"].startswith("European Central Bank") and r["url"] == "https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y" and "not a market signal or a forecast" in r["note"]
    assert "fitted curve, not a market quote" in r["note"]


def test_the_newest_day_is_provisional_only_when_the_source_says_so():
    for status, want in (({TEN: "A"}, False), ({}, False), ({TEN: ""}, False), ({TEN: "P"}, True), ({TEN: "E"}, True), ({"SR_2Y": "P"}, False)):
        assert _run(_world(status=status))["provisional"] is want, status


def test_overdue_after_8_days_from_the_last_day():
    w = _world()
    for age, want in ((0, "CURRENT"), (8, "CURRENT"), (9, "OVERDUE"), (30, "OVERDUE")):
        r = _run(w, LAST + timedelta(days=age))
        assert (r["age_days"], r["freshness"]) == (age, want)


def test_the_ten_year_comparison_needs_1300_days_and_counts_only_the_days_after_the_ten_year_mark():
    assert _run(_world(1299))["window"] is None and _run(_world(1300))["window"]["days"] == 1300
    w = _run(_world(2700))["window"]
    assert w["days"] == 2608 and w["from"] == "2016-11-17"                                           # 2,608 weekdays from 2016-11-17 to 2026-11-16 (counted by hand outside the module): the day exactly 3,652 days back is not in, the one 3,651 back is
    assert (LAST - timedelta(days=3652)).weekday() < 5 and (LAST - timedelta(days=3651)).weekday() < 5


def test_the_share_of_lower_days_counts_only_days_strictly_below_and_is_a_whole_percent():
    def share(below, equal_before, above):
        levels = [1.4] * above + [1.0] * equal_before + [0.6] * below + [1.0]                          # the newest day is one of the equal ones; every step is 0.4
        assert len(levels) == 1400
        return _run(_level(levels))["window"]["share_lower_pct"]
    assert share(420, 99, 880) == 30                                                                   # 420 of 1,400; the 100 equal days are not lower
    assert share(421, 99, 879) == 30                                                                   # 30.07
    assert share(428, 99, 872) == 31                                                                   # 30.57
    assert share(0, 1399, 0) == 0


def test_median_lowest_and_highest_with_their_days_and_ties_name_the_earlier_day():
    def level(i):                                                                                      # 2 days at 0.6347, 698 at 1.0, 698 at 1.1, 2 at 1.4653: the 700th and 701st of 1,400 are 1.0 and 1.1
        return 0.6347 if i in (100, 200) else 1.4653 if i in (350, 450) else (1.0 if (i // 50) % 2 == 0 else 1.1)
    days = _days(1400)
    r = _run(_level([level(i) for i in range(1400)]))["window"]
    assert r["lowest"] == {"value": 0.63, "date": days[100].isoformat()} and r["highest"] == {"value": 1.47, "date": days[350].isoformat()}      # not 0.6 and 1.5, not 0.635 and 1.465
    assert r["median"] == 1.05                                                                         # an even number of days: the average of the middle two


def test_a_week_and_a_month_back_use_the_newest_day_on_or_before_the_target_and_say_which_day():
    mk = lambda **kw: _level([1.0 + 0.01 * (i % 10) for i in range(60)], **kw)
    r = _run(mk())
    exact = date(2026, 11, 9)                                                                          # seven days before Monday 2026-11-16 is a weekday that exists
    assert {x["id"]: (x["week_ago"]["date"], x["month_ago"]["date"]) for x in r["rates"]} == {s: ("2026-11-09", "2026-10-16") for s in RATES}      # thirty days back is a Saturday: the Friday before
    w = _drop(mk(), [exact])
    assert _run(w)["rates"][0]["week_ago"]["date"] == "2026-11-06"                                      # without that day the Friday before it is the newest on or before the target
    three = _world(3)
    assert all(x["week_ago"] is None and x["month_ago"] is None for x in _run(three)["rates"])
    wed = date(2026, 11, 18)                                                                           # a Wednesday: seven days back is a Wednesday and thirty days back a Monday, both existing days
    r = _run(_level([1.0 + 0.01 * (i % 10) for i in range(60)], end=wed), wed + timedelta(days=1))
    assert (r["rates"][0]["week_ago"]["date"], r["rates"][0]["month_ago"]["date"]) == ("2026-11-11", "2026-10-19")     # 6, 8, 29 and 31 days back would name the Tuesday, the Thursday, the Sunday's Friday and the Tuesday after


def test_the_change_is_taken_before_rounding_and_every_figure_is_rounded_to_two_decimals():
    levels = [3.0] * 59 + [3.0049]
    levels[-6] = 2.9951                                                                                # Monday 2026-11-09 is five weekdays before the newest day
    r = _run(_level(levels))
    ten = next(x for x in r["rates"] if x["id"] == TEN)
    assert (ten["rate_pct"], ten["week_ago"]["value"], ten["week_ago"]["change"]) == (3.0, 3.0, 0.01)       # both levels round to 3.00; their change of 0.0098 rounds to 0.01
    vals = [S.svensson({**P0, "BETA0": 1.42731 - K}, YEARS[s]) for s in RATES]                          # 0.0138, 0.5777, 1.0325, 1.4623, 1.4273, 1.1361
    r = _run(_world(fn=lambda i, d: {**P0, "BETA0": 1.42731 - K}))
    assert [x["rate_pct"] for x in r["rates"]] == [0.01, 0.58, 1.03, 1.46, 1.43, 1.14]
    assert all(round(x, 3) != round(x, 2) and round(x, 1) != round(x, 2) for x in vals)                  # the world really tells two decimals from one and from three
    assert all(isinstance(x["points"], float) and round(x["points"], 2) == x["points"] for x in r["spreads"])


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    for sid in RATES + SPREADS + PARAMS:
        for bad in (("PCPA", "3"), ("PC", "0"), ("", ""), ("PCPA", "")):
            w = _world()
            w[1][sid] = bad
            assert _err(w) == f"the ECB reports {NAMES[sid]} in other units than the card assumes", (sid, bad)
    assert _err(_world()) is None


def test_series_ending_on_different_days_are_refused():
    for sid in RATES + SPREADS + PARAMS:
        w = _world()
        if sid in PARAMS:
            w[0][sid] = {LAST - timedelta(days=3): w[0][sid][LAST]}                                      # the parameter of the Friday before: its series ends a day too early
        else:
            w[0][sid].pop(LAST)
        assert _err(w) == "the yield curve series end on different days", sid
        w = _world()
        w[0][sid][LAST + timedelta(days=1)] = 1.0
        assert _err(w) == "the yield curve series end on different days", sid


def _gap_world(gap):
    days = _days(600)
    i = next(k for k in range(100, 300) if days[k].weekday() == 3)                                       # a Thursday
    b = days[i] + timedelta(days=gap)
    return _world(dates=days[:i + 1] + [b] + [d for d in days if d > b]), days[i], b


def test_a_hole_of_more_than_8_days_in_the_ten_year_rate_is_refused_and_8_days_is_not():
    w, a, b = _gap_world(8)
    assert _err(w) is None                                                                             # 8 days: a Thursday to the Friday of the next week
    w, a, b = _gap_world(9)
    assert _err(w) == f"the 10-year rate skips from {a.isoformat()} to {b.isoformat()}, more than 8 days"
    w, a, b = _gap_world(20)
    assert _err(w) == f"the 10-year rate skips from {a.isoformat()} to {b.isoformat()}, more than 8 days"


def test_a_rate_or_spread_missing_one_of_the_last_520_days_is_refused_and_an_older_one_is_not():
    days = _days(600)
    for sid in RATES + SPREADS:
        if sid == TEN:
            continue
        w = _world()
        w[0][sid].pop(days[-100])
        assert _err(w) == f"{NAMES[sid]} is missing for {days[-100].isoformat()}", sid
        w = _world()
        w[0][sid].pop(days[-520])
        assert _err(w) == f"{NAMES[sid]} is missing for {days[-520].isoformat()}", sid
        w = _world()
        w[0][sid].pop(days[-521])
        assert _err(w) is None, sid


def test_each_rate_and_spread_must_lie_inside_its_range_on_every_day_of_its_window():
    days = _days(600)
    for sid in RATES + SPREADS:
        lo, hi = RATE_LIMITS if sid in RATES else SPREAD_LIMITS
        win = days if sid == TEN else days[-520:]
        for edge, outside in ((lo, lo - 0.0001), (hi, hi + 0.0001)):
            w = _world()
            for d in win:
                w[0][sid][d] = edge
            assert _err(w).startswith(_follow(sid, days[-520])), (sid, edge)                             # exactly at the limit the range check lets it through: the identity it breaks (looked at over the last 520 days) is what speaks
            w = _world()
            for d in win:
                w[0][sid][d] = outside
            assert _err(w) == f"{NAMES[sid]} is {outside:.4f} on {win[0].isoformat()}, outside {lo:g} to {hi:g}", (sid, outside)
    w = _world()
    w[0]["SR_2Y"][days[-521]] = 50.0
    assert _err(w) is None                                                                             # the other rates are looked at over the last 520 days only
    w[0]["SR_2Y"][days[-520]] = 50.0
    assert _err(w) == f"{NAMES['SR_2Y']} is 50.0000 on {days[-520].isoformat()}, outside -3 to 10"
    w = _world()
    w[0][TEN][days[0]] = 50.0
    assert _err(w) == f"{NAMES[TEN]} is 50.0000 on {days[0].isoformat()}, outside -3 to 10"            # the 10-year rate is looked at over the whole window


def _step_world(sid, prev, new):
    w = _world()
    days = _days(600)
    w[0][sid][days[-2]], w[0][sid][days[-1]] = prev, new
    return w, days[-2]


def test_a_one_day_move_over_the_bound_is_refused_and_a_move_inside_it_is_not():
    for sid, (lo, hi) in MOVES.items():
        base = (_world()[0][sid][_days(600)[-2]])
        prev = round(base * 64) / 64                                                                    # a number exact in binary, close to the world's value
        for bound, sign in ((hi, 1), (lo, -1)):
            inside, outside = bound - 0.01 * sign, bound + 0.01 * sign
            w, a = _step_world(sid, prev, prev + inside)
            assert _err(w).startswith(_follow(sid, a)), (sid, bound, "inside")
            w, a = _step_world(sid, prev, prev + outside)
            assert _err(w) == f"{NAMES[sid]} moved by {outside:+.4f} points on {LAST.isoformat()}, outside {lo:+.1f} to {hi:+.1f}", (sid, bound, "outside")
    for sid, bound in (("SR_10Y", 0.5), ("SR_10Y", -0.5), ("SR_3M", 0.5), ("SR_3M", -1.5), ("SR_30Y", -1.0), ("SRS_10Y_3M", 1.5), ("SRS_10Y_1Y", 0.5), ("SRS_10Y_1Y", -0.5), ("SR_5Y", 0.5), ("SR_1Y", 0.5), ("SR_2Y", 0.5)):
        base = _world()[0][sid][_days(600)[-2]]
        prev = round(base * 64) / 64
        w, a = _step_world(sid, prev, prev + bound)                                                    # exactly at the bound (exact in binary): allowed
        assert _err(w).startswith(_follow(sid, a)), (sid, bound)


def test_the_move_check_covers_the_whole_window_of_each_series():
    days = _days(600)
    w = _world()
    w[0][TEN][days[30]] += 0.6                                                                         # 570 days back: the 10-year rate is checked over its whole window
    assert _err(w) == f"{NAMES[TEN]} moved by +0.6000 points on {days[30].isoformat()}, outside -0.5 to +0.5"
    w = _world()
    w[0]["SR_2Y"][days[-100]] += 1.0                                                                   # the other rates within the last 520 days
    assert _err(w) == f"{NAMES['SR_2Y']} moved by +1.0000 points on {days[-100].isoformat()}, outside -0.8 to +0.5"
    w = _world()
    w[0]["SR_2Y"][days[-530]] += 1.0                                                                   # ... and no further back
    assert _err(w) is None


def test_each_model_parameter_must_lie_inside_its_range_on_the_newest_day():
    for sid, (lo, hi) in PARAM_LIMITS.items():
        for edge, outside in ((lo, lo - 0.0001), (hi, hi + 0.0001)):
            w = _world()
            w[0][sid][LAST] = edge
            assert _err(w).startswith(f"{NAMES['SR_3M']} on {LAST.isoformat()} is "), (sid, edge)          # at the limit it passes the range check; the curve it no longer follows speaks
            w = _world()
            w[0][sid][LAST] = outside
            assert _err(w) == f"{NAMES[sid]} is {outside:.4f} on {LAST.isoformat()}, outside {lo:g} to {hi:g}", (sid, outside)


def test_the_spreads_must_be_the_ten_year_rate_minus_the_shorter_one_within_a_millionth_over_the_last_520_days():
    days = _days(600)
    for sid in SPREADS:
        w = _world()
        w[0][sid][LAST] += 0.0000005
        assert _run(w)["detail"]["largest_spread_gap"] == 5e-07, sid                                    # inside the tolerance and reported
        w = _world()
        w[0][sid][LAST] -= 0.0000005
        assert _run(w)["detail"]["largest_spread_gap"] == 5e-07, sid                                    # a spread below its identity: the gap is reported as a size, never as a negative number
        w = _world()
        w[0][sid][LAST] += 0.000002
        assert _err(w) == f"{NAMES[sid]} is not the difference of the two rates on {LAST.isoformat()} (off by +0.000002)", sid
        w = _world()
        w[0][sid][LAST] -= 0.000002
        assert _err(w) == f"{NAMES[sid]} is not the difference of the two rates on {LAST.isoformat()} (off by -0.000002)", sid
        w = _world()
        w[0][sid][days[-521]] += 0.01
        assert _err(w) is None, sid                                                                     # older than the last 520 days: not looked at
        w[0][sid][days[-520]] += 0.01
        assert _err(w) == f"{NAMES[sid]} is not the difference of the two rates on {days[-520].isoformat()} (off by +0.010000)", sid


def test_a_spread_gap_of_exactly_the_tolerance_is_allowed_and_a_little_more_is_not():
    for gap, ok in ((0.000001, True), (0.0000011, False)):
        w = _world(params=ZERO)
        for d in _days(600)[-520:]:
            w[0]["SRS_10Y_3M"][d] = gap                                                                 # every rate is exactly 0.0, so the gap is exactly the number given
        if ok:
            assert _run(w)["detail"]["largest_spread_gap"] == 1e-06
        else:
            assert _err(w) == f"{NAMES['SRS_10Y_3M']} is not the difference of the two rates on {_days(600)[-520].isoformat()} (off by +0.000001)"


def test_each_rate_must_follow_the_published_curve_within_a_millionth_on_the_newest_day_only():
    days = _days(600)
    for sid in RATES:
        w = _world()
        w[0][sid][LAST] += 0.0000005
        for sp, other in SPREAD_OF.items():                                                              # keep the spreads consistent, so that only the curve is under test
            w[0][sp][LAST] = w[0][TEN][LAST] - w[0][other][LAST]
        r = _run(w)
        assert r["detail"]["largest_curve_gap"] == 5e-07, sid
        w = _world()
        w[0][sid][LAST] += 0.000002
        for sp, other in SPREAD_OF.items():
            w[0][sp][LAST] = w[0][TEN][LAST] - w[0][other][LAST]
        assert _err(w) == f"{NAMES[sid]} on {LAST.isoformat()} is 0.000002 points away from the curve of the published model parameters, more than 1e-06", sid
        w = _world()
        w[0][sid][days[-5]] += 0.01                                                                     # an older day that does not follow its parameters is not looked at
        for sp, other in SPREAD_OF.items():
            w[0][sp][days[-5]] = w[0][TEN][days[-5]] - w[0][other][days[-5]]
        assert _err(w) is None, sid


def test_the_curve_check_uses_the_parameters_of_the_newest_day_even_if_older_days_come_with_them():
    w = _world()
    older = _days(600)[-2]
    for sid, x in {"BETA0": 5.0, "BETA1": 4.0, "BETA2": -2.0, "BETA3": -3.0, "TAU1": 1.0, "TAU2": 5.0}.items():
        w[0][sid][older] = x                                                                            # the curve of these is not the curve any published rate follows
    assert _err(w) is None
    assert _run(w)["detail"]["largest_curve_gap"] == 0.0


def test_a_curve_gap_of_exactly_the_tolerance_is_allowed_and_a_little_more_is_not():
    for gap, ok in ((0.000001, True), (0.0000011, False)):
        w = _world(params=ZERO)
        w[0]["SR_5Y"][LAST] = gap
        if ok:
            assert _run(w)["detail"]["largest_curve_gap"] == 1e-06
        else:
            assert _err(w) == f"{NAMES['SR_5Y']} on {LAST.isoformat()} is 0.000001 points away from the curve of the published model parameters, more than 1e-06"


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    days = _days(600)
    w = _world()
    w[1][TEN] = ("PC", "0")
    w[0]["SR_2Y"].pop(LAST)
    assert _err(w).startswith("the ECB reports the 10-year rate in other units")                       # the units before the end days
    w, ga, gb = _gap_world(20)
    w[0]["SR_2Y"].pop(LAST)
    assert _err(w) == "the yield curve series end on different days"                                    # the end days before the holes
    w, ga, gb = _gap_world(20)
    w[0]["SR_2Y"].pop(_days(600)[-100])
    assert _err(w).startswith("the 10-year rate skips from ")                                           # the holes before a missing day of another series
    w = _world()
    w[0]["SR_2Y"].pop(days[-100])
    w[0][TEN][LAST] = 50.0
    assert _err(w) == f"{NAMES['SR_2Y']} is missing for {days[-100].isoformat()}"                       # a missing day before the ranges
    w = _world()
    w[0][TEN][LAST] = 50.0
    assert _err(w).startswith("the 10-year rate is 50.0000")                                            # the range before the move
    w = _world()
    w[0][TEN][LAST] += 0.7
    w[0]["BETA0"][LAST] = 99.0
    assert _err(w).startswith("the 10-year rate moved by +0.7000")                                      # the moves before the parameters
    w = _world()
    w[0]["BETA0"][LAST] = 99.0
    w[0]["SRS_10Y_3M"][LAST] += 0.01
    assert _err(w).startswith("model parameter Beta 0 is 99.0000")                                      # the parameters before the spreads
    w = _world()
    w[0]["SRS_10Y_3M"][LAST] += 0.01
    w[0]["SR_3M"][LAST] += 0.01
    assert _err(w).startswith(f"{NAMES['SRS_10Y_3M']} is not the difference")                           # the spreads before the curve


def test_the_real_window_passes_every_check_and_its_largest_real_ten_year_moves_are_pinned():
    r = _run(_real())
    assert r["available"] and r["detail"]["days_checked"] == 2700
    ten = _real()[0][TEN]
    days = sorted(ten)
    ch = [(ten[b] - ten[a], b) for a, b in zip(days, days[1:])]
    assert (round(max(ch)[0], 4), max(ch)[1]) == (0.2362, date(2025, 3, 5)) and (round(min(ch)[0], 4), min(ch)[1]) == (-0.2646, date(2023, 3, 15))      # the real extremes are inside the bound of 0.5


def test_the_limits_and_tolerances_are_the_ones_set_from_the_real_record():
    assert (S.RATE_LIMITS, S.SPREAD_LIMITS, S.PARAM_LIMITS, S.MOVES) == (RATE_LIMITS, SPREAD_LIMITS, PARAM_LIMITS, MOVES)
    assert (S.SPREAD_TOLERANCE, S.CURVE_TOLERANCE, S.MAX_GAP_DAYS, S.UNIT) == (0.000001, 0.000001, 8, UN)
    assert (S.TEN_LAST_N, S.RATES_LAST_N, S.PARAMS_LAST_N, S.WINDOW_DAYS, S.MIN_WINDOW_DAYS, S.OVERDUE_AFTER_DAYS) == (2700, 520, 1, 3652, 1300, 8)
    assert (S.RATES, S.SPREADS, S.PARAMS, S.TEN, S.YEARS, S.SPREAD_OF, S.NAMES) == (RATES, SPREADS, PARAMS, TEN, YEARS, SPREAD_OF, NAMES)
    assert S.CURVE == "B.U2.EUR.4F.G_N_A.SV_C_YM."
    assert "the ECB's own arithmetic" in S.__doc__ and "not that the figures are right" in S.__doc__ and "5,675 business days" in S.__doc__ and "2022-06-23" in S.__doc__ and "These are plain checks" in S.__doc__


HEAD = "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
OK = "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"


def test_the_real_layout_of_a_response_is_read():
    v, units, status = S.parse(F["raw_head"], (TEN, "BETA0"))
    assert v == {TEN: {date(2026, 11, 16): 3.4224059614}, "BETA0": {date(2026, 11, 16): 1.6351443905}} and units == {TEN: UN, "BETA0": UN} and status == {TEN: "A", "BETA0": "A"}
    assert F["raw_head"].startswith("KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,")


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_day_are_an_error():
    text = HEAD + f"{OK},2026-11-10,0.5,A,PCPA,0\n{OK},2026-11-11,,M,PCPA,0\n{OK},2026-11-12,n/a,A,PCPA,0\n{OK},2026-11,1,A,PCPA,0\n{OK},2026-11-1x,1,A,PCPA,0\n{OK},2026-13-40,1,A,PCPA,0\n{OK},2026-11-100,0.9,A,PCPA,0\n{OK},2026-11-13T00:00,1,A,PCPA,0\n"
    text += f"{OK},2026-11-09,nan,A,PCPA,0\n{OK},2026-11-06,inf,A,PCPA,0\nYC.B.U2.EUR.4F.G_N_C.SV_C_YM.SR_10Y,2026-11-10,0.9,A,PCPA,0\nYC.D.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y,2026-11-10,0.8,A,PCPA,0\nYC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_9Y,2026-11-10,0.7,A,PCPA,0\n"
    v, units, status = S.parse(text, (TEN,))
    assert v == {TEN: {date(2026, 11, 10): 0.5}} and units == {TEN: UN} and status == {TEN: "A"}      # a day with no value, a month, bad days, a day with a time, nan, inf, the all-issuers curve, another frequency and another maturity are all left out
    padded = HEAD + f"{OK},2026-11-10,0.5, P , PCPA , 0 \n"
    assert S.parse(padded, (TEN,))[1] == {TEN: UN} and S.parse(padded, (TEN,))[2] == {TEN: "P"}       # spaces around a unit or a status are not a different one
    two = HEAD + f"{OK},2026-11-09,0.1,A,PCPA,0\n{OK},2026-11-11,0.3,P,PCPA,0\n{OK},2026-11-10,0.2,A,PCPA,0\n"
    assert S.parse(two, (TEN,))[2] == {TEN: "P"}                                                       # the status is the newest day's, whatever the order of the rows
    with pytest.raises(ValueError, match=r"SR_10Y has two values for 2026-11-10"):
        S.parse(text + f"{OK},2026-11-10,0.1,A,PCPA,0\n", (TEN,))
    with pytest.raises(ValueError, match=r"no values for SR_2Y"):
        S.parse(text, (TEN, "SR_2Y"))


def _ten_text(replace=None):
    t = F["ten"]
    text = HEAD + "\n".join(f"{OK},{d},{x},A,PCPA,0" for d, x in zip(t["dates"], t["values"])) + "\n"
    return text.replace(*replace) if replace else text


def _others_text():
    o = F["others"]
    return HEAD + "\n".join(f"YC.B.U2.EUR.4F.G_N_A.SV_C_YM.{sid},{d},{o[sid][i]},A,PCPA,0" for sid in ("SR_3M", "SR_1Y", "SR_2Y", "SR_5Y", "SR_30Y") + SPREADS for i, d in enumerate(o["dates"])) + "\n"


def _params_text():
    p = F["params"]
    return HEAD + "\n".join(f"YC.B.U2.EUR.4F.G_N_A.SV_C_YM.{sid},{p['date']},{p[sid]},A,PCPA,0" for sid in PARAMS) + "\n"


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req, replace=None, units=None):
    path = req.url.path
    text = _ten_text(replace) if path.endswith(".SR_10Y") else _params_text() if path.endswith("TAU2") else _others_text()
    if units and path.endswith(units[0]):
        text = text.replace(",A,PCPA,0", ",A,PCPA,3")
    return httpx.Response(200, text=text)


def test_overview_fetches_three_requests_and_caches():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = S.EuroYields(client=_transport(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["rates"][4]["rate_pct"] == 3.42 and len(seen) == 3 and r["source"].startswith("European Central Bank")
    base = "/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM."
    assert {req.url.path: req.url.params["lastNObservations"] for req in seen} == {base + "SR_10Y": "2700", base + "SR_3M+SR_1Y+SR_2Y+SR_5Y+SR_30Y+SRS_10Y_3M+SRS_10Y_1Y+SRS_10Y_2Y": "520", base + "BETA0+BETA1+BETA2+BETA3+TAU1+TAU2": "1"}
    assert all(req.url.params["format"] == "csvdata" for req in seen) and all(req.headers["user-agent"] == "ATLAS research terminal" for req in seen)
    assert all("%2B" not in str(req.url) for req in seen) and sum("+" in str(req.url) for req in seen) == 2      # the + that joins the series of one key must reach the ECB as it is
    asyncio.run(svc.overview(NOW))
    assert len(seen) == 3


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(S.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = S.EuroYields(client=_transport(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 3
    clock["t"] += S.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3                                                                                 # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 6                          # two minutes on it asks again
    clock["t"] += S.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 9 and (S.FAIL_TTL, S.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(S.EuroYields(client=_transport(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "rates" not in r
    slip = (f"{OK},2026-11-16,3.4224059614,", f"{OK},2026-11-16,34.224059614,")                          # a decimal slip in the newest 10-year rate: a check failing shows nothing either
    assert slip[0] in _ten_text() and slip[1] in _ten_text(slip)
    r = asyncio.run(S.EuroYields(client=_transport(lambda req: _handler(req, slip))).overview(NOW))
    assert r["available"] is False and "the 10-year rate is 34.2241 on 2026-11-16, outside -3 to 10" in r["reason"] and "rates" not in r


def test_a_response_in_other_units_is_refused_and_shows_nothing():
    for suffix, what in (("SR_10Y", "the 10-year rate"), ("SRS_10Y_2Y", "the 3-month rate"), ("TAU2", "model parameter Beta 0")):
        r = asyncio.run(S.EuroYields(client=_transport(lambda req, s=suffix: _handler(req, units=(s,)))).overview(NOW))
        assert r["available"] is False and f"the ECB reports {what} in other units than the card assumes" in r["reason"] and "rates" not in r, suffix


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(S.EuroYields(client=_transport(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The euro-area yield curve could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(S.EuroYields(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "rates" not in d
    assert d["reason"] == "Demo mode: the real euro-area yield curve is not shown because made-up values would look real."


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-yields")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
