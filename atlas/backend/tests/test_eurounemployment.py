"""Euro-area unemployment (ECB Data Portal, LFSI dataflow): parsed from real responses (fetched 2026-11-17 20:2x UTC: monthly rates and numbers of unemployed persons of seven series from 2014-01, newest month 2026-09; the full history from 2000 was read to set the checks, see the module's docstring)."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import eurounemployment as U
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_unemployment.json").read_text())
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)
RU, LU = ("PC", "0"), ("PERS", "3")
T, W, M, Y, A = "15_74.T", "15_74.F", "15_74.M", "15_24.T", "25_74.T"
NAMES = {T: "everybody aged 15 to 74", W: "women", M: "men", Y: "people under 25", A: "people aged 25 to 74"}
# the limits set from the real record, spelled out here so that a changed limit fails a test instead of moving the test with it
RATE_LIMITS = {T: (3.0, 20.0), W: (3.0, 20.0), M: (3.0, 20.0), Y: (5.0, 45.0), A: (3.0, 20.0)}
RATE_MOVE = {T: (-1.0, 1.0), W: (-1.5, 1.5), M: (-1.5, 1.5), Y: (-3.0, 3.0), A: (-1.0, 1.0)}
LEVEL_LIMITS = {T: (5_000.0, 40_000.0), W: (2_500.0, 20_000.0), M: (2_500.0, 20_000.0), Y: (1_000.0, 10_000.0), A: (4_000.0, 30_000.0)}
LEVEL_MOVE = (-10.0, 15.0)


def _real():
    rates, ru, status = U.parse(F["rates"], "UNEHRT", U.IDS)
    levels, lu, _ = U.parse(F["levels"], "UNEMPL", U.IDS)
    return rates, ru, levels, lu, status


def _real_until(cut, today=None):
    rates, ru, levels, lu, status = _real()
    r = {k: {d: v for d, v in s.items() if d <= cut} for k, s in rates.items()}
    l = {k: {d: v for d, v in s.items() if d <= cut} for k, s in levels.items()}
    return U.summarize(r, ru, l, lu, status, today or cut + timedelta(days=45))


def _idx(d):
    return (d.year * 12 + d.month) - (LAST.year * 12 + LAST.month)


def _world(n_months=48, women=(5000.0, 7.0), men=(5500.0, 6.0), youth=(1500.0, 15.0), scale=None, shape=None, status=None):
    """`n_months` months ending 2026-09. Women, men and the under 25 are given as (thousands unemployed, rate); everything else follows so that every identity holds by construction: everybody is women plus men, the 25 to 74 are everybody minus the under 25, and a labour force is persons over rate, so the rate for everybody and for the 25 to 74 are the ones that make the labour forces add up. `scale(month)` multiplies the persons, `shape(id, month)` adds points to the rate of women, men or the under 25."""
    months = [U._months_back(LAST, i) for i in range(n_months - 1, -1, -1)]
    rates = {sid: {} for sid in U.IDS}
    levels = {sid: {} for sid in U.IDS}
    for d in months:
        k = scale(d) if scale else 1.0
        rf, rm, ry = women[1] + (shape(W, d) if shape else 0.0), men[1] + (shape(M, d) if shape else 0.0), youth[1] + (shape(Y, d) if shape else 0.0)
        uf, um, uy = women[0] * k, men[0] * k, youth[0] * k
        ut, ua = uf + um, uf + um - uy
        lf_t = uf / (rf / 100) + um / (rm / 100)
        lf_a = lf_t - uy / (ry / 100)
        for sid, u, r in ((W, uf, rf), (M, um, rm), (Y, uy, ry), (T, ut, 100 * ut / lf_t), (A, ua, 100 * ua / lf_a)):
            levels[sid][d], rates[sid][d] = u, r
    return rates, {s: RU for s in rates}, levels, {s: LU for s in levels}, status if status is not None else {T: "A"}


def _run(world, today=TODAY):
    return U.summarize(*world, today)


def _err(world, today=TODAY):
    """The refusal's text, or None when the world passes every check."""
    try:
        _run(world, today)
    except ValueError as e:
        return str(e)
    return None


def test_latest_headline_groups_persons_range_and_checks_by_hand():
    s = _run(_real())
    assert (s["date"], s["month"], s["age_days"], s["freshness"], s["provisional"]) == ("2026-09-01", "2026-09", 48, "CURRENT", False)
    assert s["headline"] == {"rate_pct": 6.6, "change_1m_points": 0.1, "change_3m_points": 0.1, "change_12m_points": 0.2}                     # 6.5 in August and June, 6.4 a year ago
    assert s["persons"] == {"total_thousands": 11452.1, "change_12m_thousands": 426.5, "women_thousands": 5556.5, "men_thousands": 5895.7, "youth_thousands": 2452.8, "adults_thousands": 8999.3,
                            "women_share_pct": 49, "youth_share_pct": 21}                                                                      # 11,452.1 - 11,025.6; 5,556.5 / 11,452.1 = 48.5%; 2,452.8 / 11,452.1 = 21.4%
    assert [(g["id"], g["label"], g["rate_pct"]) for g in s["groups"]] == [("15_74.F", "women", 6.8), ("15_74.M", "men", 6.4), ("15_24.T", "people under 25", 15.4), ("25_74.T", "people aged 25 to 74", 5.7)]
    assert s["range"] == {"months": 120, "lowest": {"pct": 6.2, "month": "2024-10"}, "highest": {"pct": 9.9, "month": "2016-10"}, "share_lower_pct": 28}      # 2016-10 to 2026-09; 9.9 in 2016-10 and 2016-11 (the earlier month); 33 of 120 months under 6.6
    assert s["detail"] == {"months_checked": 24, "largest_sum_gap_thousands": 0.1, "largest_labour_force_gap_pct": 1.37, "largest_labour_force_gap_month": "2025-12"}      # 0.1 thousand rounding; -1.366% in 2025-12
    assert all(s["checks"].values()) and s["source"].startswith("Eurostat") and s["url"] == "https://data-api.ecb.europa.eu/service/data/LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T"
    assert "fixed composition" in s["note"] and "not a market signal or a forecast" in s["note"] and "Plain checks: the units are the ones assumed" in s["note"]


def test_the_newest_month_is_provisional_only_when_the_source_says_so():
    assert _run(_world())["provisional"] is False
    for st in ("P", "E", "B"):
        assert _run(_world(status={T: st}))["provisional"] is True
    assert _run(_world(status={}))["provisional"] is False
    assert _run(_world(status={W: "P"}))["provisional"] is False                                           # the headline's own status decides


def test_the_history_is_the_last_60_months_of_the_headline_oldest_first():
    s = _run(_real())
    assert len(s["history"]) == 60 and s["history"][0] == {"date": "2021-10-01", "rate_pct": 7.3} and s["history"][-1] == {"date": "2026-09-01", "rate_pct": 6.6}
    assert [h["date"] for h in s["history"]] == sorted(h["date"] for h in s["history"])


def test_a_short_history_says_not_available_for_what_it_cannot_compute():
    s = _run(_world(n_months=10))
    assert s["detail"]["months_checked"] == 10 and s["range"] is None and s["headline"]["change_12m_points"] is None and s["persons"]["change_12m_thousands"] is None
    assert s["headline"]["change_3m_points"] == 0.0 and s["headline"]["change_1m_points"] == 0.0
    assert _run(_world(n_months=13))["headline"]["change_12m_points"] == 0.0


def test_the_ten_year_comparison_needs_at_least_60_months_of_the_headline():
    assert _run(_world(n_months=59))["range"] is None
    g = _run(_world(n_months=60))["range"]                                                                 # a flat world: every rate is 6.4, so none is lower than the newest
    assert g == {"months": 60, "lowest": {"pct": 6.4, "month": g["lowest"]["month"]}, "highest": {"pct": 6.4, "month": g["highest"]["month"]}, "share_lower_pct": 0}


def test_overdue_after_75_days_from_the_end_of_the_month():
    end = date(2026, 9, 30)
    assert _run(_world(), end + timedelta(days=75))["freshness"] == "CURRENT"
    s = _run(_world(), end + timedelta(days=76))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 76
    assert _run(_world(), date(2026, 10, 3))["age_days"] == 3 and _run(_world(), end)["age_days"] == 0
    assert U._month_end(date(2026, 9, 1)) == date(2026, 9, 30) and U._month_end(date(2026, 12, 1)) == date(2026, 12, 31) and U._month_end(date(2024, 2, 1)) == date(2024, 2, 29)


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    for pos, kind, right in ((1, "rate", RU), (3, "number of unemployed", LU)):
        for sid in U.IDS:
            for bad in (("PC", "2"), ("PERS", "0"), ("PERS", "6"), ("EUR", "3"), ("", "")):
                if bad == right:
                    continue
                w = list(_world())
                w[pos] = dict(w[pos])
                w[pos][sid] = bad
                with pytest.raises(ValueError, match=re.escape(f"the ECB reports the {kind} of {NAMES[sid]} in other units than the card assumes")):
                    U.summarize(*w, TODAY)


def test_a_series_ending_in_another_month_or_missing_a_month_is_refused():
    for which in (0, 2):
        for sid in U.IDS:
            w = _world()
            del w[which][sid][LAST]
            with pytest.raises(ValueError, match="end in different months"):
                _run(w)
            w = _world()
            w[which][sid][date(2026, 10, 1)] = 1.0                                                          # one month AHEAD of the others
            with pytest.raises(ValueError, match="end in different months"):
                _run(w)
    for sid in U.IDS:
        if sid != T:
            w = _world()
            del w[0][sid][U._months_back(LAST, 5)]
            with pytest.raises(ValueError, match=re.escape(f"the unemployment rate of {NAMES[sid]} is missing for 2026-04")):
                _run(w)
        w = _world()
        del w[2][sid][U._months_back(LAST, 5)]
        with pytest.raises(ValueError, match=re.escape(f"the number of unemployed {NAMES[sid]} is missing for 2026-04")):
            _run(w)
    w = _world()
    del w[2][A][U._months_back(LAST, 24)]                                                                  # a hole before the window: not looked at
    assert _run(w)["detail"]["months_checked"] == 24


def test_the_months_must_follow_each_other_in_the_last_24():
    def without(pos):
        w = _world()
        for sid in U.IDS:
            del w[0][sid][sorted(w[0][sid])[pos]]
        return w
    with pytest.raises(ValueError, match="skip a month"):
        _run(without(-10))
    with pytest.raises(ValueError, match="skip a month"):
        _run(without(-24))                                                                                 # the oldest month of the window: the gap sits between it and the next one
    assert _run(without(-25))["available"]                                                                 # before the window: not looked at


def test_each_rate_must_be_inside_its_range():
    for sid, (lo, hi) in RATE_LIMITS.items():
        for edge, bad in ((hi, hi + 0.1), (lo, lo - 0.1)):
            w = _world()
            w[0][sid][LAST] = edge
            assert not re.search(r"unemployment rate of .* is .*% in 2026-09, outside", _err(w) or ""), (sid, edge)    # at the limit the range check lets it through (a later check refuses the made-up value)
            w = _world()
            w[0][sid][LAST] = bad
            assert _err(w) == f"the unemployment rate of {NAMES[sid]} is {bad:.1f}% in 2026-09, outside {lo:.0f}% to {hi:.0f}%", (sid, bad)


def test_the_rate_range_check_looks_at_the_last_24_months_and_no_further_back():
    w = _world()
    w[0][Y][U._months_back(LAST, 23)] = 46.0
    assert _err(w) == "the unemployment rate of people under 25 is 46.0% in 2024-10, outside 5% to 45%"      # the oldest month of the window
    w = _world()
    w[0][Y][U._months_back(LAST, 24)] = 46.0
    assert _err(w) is None


def test_each_number_of_unemployed_must_be_inside_its_range():
    for sid, (lo, hi) in LEVEL_LIMITS.items():
        for edge, bad in ((hi, hi + 1.0), (lo, lo - 1.0)):
            w = _world()
            w[2][sid][LAST] = edge
            assert "outside the plausible range" not in (_err(w) or ""), (sid, edge)
            w = _world()
            w[2][sid][LAST] = bad
            assert _err(w) == f"the number of unemployed {NAMES[sid]} is outside the plausible range in 2026-09", (sid, bad)
    for k in (10.0, 0.1):                                                                                  # a x10 or /10 slip in the whole series
        w = _world()
        w[2][T] = {d: v * k for d, v in w[2][T].items()}
        assert _err(w) == "the number of unemployed everybody aged 15 to 74 is outside the plausible range in 2024-10"
    w = _world()
    w[2][W][U._months_back(LAST, 24)] = 99_999.0
    assert _err(w) is None                                                                                 # before the window: not looked at


def test_a_one_month_move_of_a_rate_outside_its_bounds_is_refused_and_inside_is_not():
    for sid, (lo, hi) in RATE_MOVE.items():
        base = _world()[0][sid][U._months_back(LAST, 1)]
        for ch in (hi - 0.1, lo + 0.1):
            w = _world()
            w[0][sid][LAST] = base + ch
            assert "moved by" not in (_err(w) or ""), (sid, ch)                                            # inside the bound: a later check may refuse the made-up value, not this one
        for ch in (hi + 0.1, lo - 0.1):
            w = _world()
            w[0][sid][LAST] = base + ch
            assert _err(w) == f"the unemployment rate of {NAMES[sid]} moved by {ch:+.1f} points in 2026-09, outside {lo:+.1f} to {hi:+.1f}", (sid, ch)


def test_a_rate_move_of_exactly_the_bound_is_allowed():
    for sid, (lo, hi) in RATE_MOVE.items():
        for edge in (lo, hi):
            w = _world()
            for d in w[0][sid]:
                w[0][sid][d] = 10.0                                                                        # a flat 10.0 and then a step of exactly the bound: every number here is exact in binary
            w[0][sid][LAST] = 10.0 + edge
            assert "moved by" not in (_err(w) or ""), (sid, edge)                                          # a later check refuses the made-up series, this one does not


def test_the_rate_move_check_looks_at_the_last_24_months_and_no_further_back():
    def spike_at(back, ch=1.2):
        w = _world()
        w[0][T][U._months_back(LAST, back)] += ch
        return w
    assert _err(spike_at(22)) == "the unemployment rate of everybody aged 15 to 74 moved by +1.2 points in 2024-11, outside -1.0 to +1.0"      # the 2nd month of the window: the move into it is inside
    assert _err(spike_at(23)) == "the unemployment rate of everybody aged 15 to 74 moved by -1.2 points in 2024-11, outside -1.0 to +1.0"      # the 1st: the move into it is before the window, the move out of it is inside
    assert _err(spike_at(24)) is None                                                                       # before the window: neither move is looked at


def test_a_one_month_change_in_the_number_of_unemployed_under_minus_10_or_over_plus_15_percent_is_refused():
    for sid in U.IDS:
        for k, bad in ((1.149, False), (0.901, False), (1.151, True), (0.899, True)):
            w = _world()
            w[2][sid][LAST] *= k
            e = _err(w)
            if bad:
                assert e == f"the number of unemployed {NAMES[sid]} changed by {100 * (k - 1):+.1f}% in 2026-09, outside -10% to +15%", (sid, k)
            else:
                assert "changed by" not in (e or ""), (sid, k)


def test_the_level_move_check_looks_at_the_last_24_months_and_no_further_back():
    def step(back):
        w = _world()
        for d in w[2][T]:
            if _idx(d) >= -back:
                w[2][T][d] *= 1.5
        return w
    assert _err(step(22)) == "the number of unemployed everybody aged 15 to 74 changed by +50.0% in 2024-11, outside -10% to +15%"
    assert "changed by" not in (_err(step(23)) or "")                                                      # the step lands on the first month of the window: the move into it comes from before it
    assert "changed by" not in (_err(step(24)) or "")


def test_the_rate_for_everybody_must_lie_between_women_and_men():
    base = _world()
    lo, hi = sorted((base[0][W][LAST], base[0][M][LAST]))
    assert _err(base) is None and lo < base[0][T][LAST] < hi
    for value in (hi + 0.09, lo - 0.09):
        w = _world()
        w[0][T][LAST] = value
        assert "range of the rates of women and men" not in (_err(w) or ""), value                         # inside the tolerance of 0.1 the between check passes; the labour forces then disagree, a later check
    for value in (hi + 0.11, lo - 0.11):
        w = _world()
        w[0][T][LAST] = value
        assert _err(w) == f"the rate for everybody in 2026-09 ({value:.1f}%) is outside the range of the rates of women and men ({lo:.1f}% to {hi:.1f}%)"
    w = _world()
    w[0][T][U._months_back(LAST, 23)] = hi + 0.3                                                           # a spike that stays inside the move bound
    assert _err(w) == f"the rate for everybody in 2024-10 ({hi + 0.3:.1f}%) is outside the range of the rates of women and men ({lo:.1f}% to {hi:.1f}%)"      # the oldest month of the window is inside
    w = _world()
    w[0][T][U._months_back(LAST, 24)] = hi + 0.3
    assert _err(w) is None


def test_the_rate_for_everybody_must_lie_between_the_under_25_and_the_25_to_74():
    base = _world(youth=(1500.0, 6.6))                                                                     # under 25 at 6.6%, so the 25 to 74 come out at about 6.41% and everybody (6.44%) in between
    lo, hi = sorted((base[0][Y][LAST], base[0][A][LAST]))
    assert _err(base) is None and lo < base[0][T][LAST] < hi and (round(lo, 1), round(hi, 1)) == (6.4, 6.6)
    for value in (hi + 0.09, lo - 0.09):
        w = _world(youth=(1500.0, 6.6))
        w[0][T][LAST] = value
        assert "range of the rates of people under 25" not in (_err(w) or ""), value                       # inside the tolerance of 0.1 the between check passes; the labour forces then disagree, a later check
    for value in (hi + 0.11, lo - 0.11):
        w = _world(youth=(1500.0, 6.6))
        w[0][T][LAST] = value
        assert _err(w) == f"the rate for everybody in 2026-09 ({value:.1f}%) is outside the range of the rates of people under 25 and people aged 25 to 74 ({lo:.1f}% to {hi:.1f}%)", value
    w = _world(youth=(1500.0, 6.6))
    w[0][T][U._months_back(LAST, 23)] = hi + 0.3
    assert _err(w) == f"the rate for everybody in 2024-10 ({hi + 0.3:.1f}%) is outside the range of the rates of people under 25 and people aged 25 to 74 ({lo:.1f}% to {hi:.1f}%)"
    w = _world(youth=(1500.0, 6.6))
    w[0][T][U._months_back(LAST, 24)] = hi + 0.3
    assert _err(w) is None


def test_the_numbers_of_unemployed_must_add_up_to_the_total_within_two_tenths_of_a_thousand():
    for sid, what in ((W, "women and men"), (Y, "people under 25 and people aged 25 to 74")):
        for off in (0.19, -0.19):
            w = _world()
            w[2][sid][LAST] += off
            assert "do not add up" not in (_err(w) or ""), (sid, off)                                      # inside the tolerance of 0.2
        for off in (0.4, -0.4):
            w = _world()
            w[2][sid][LAST] += off
            assert _err(w) == f"the numbers of unemployed {what} do not add up to the total in 2026-09 (off by {off:+.1f} thousand)", (sid, off)
        w = _world()
        w[2][sid][U._months_back(LAST, 23)] += 0.4
        assert _err(w).startswith("the numbers of unemployed") and "in 2024-10" in _err(w)                 # the oldest month of the window is inside
        w = _world()
        w[2][sid][U._months_back(LAST, 24)] += 0.4
        assert _err(w) is None


def _gap(world, d, sexes=True):
    rates, _, levels, _, _ = world
    x, y = (W, M) if sexes else (Y, A)
    force = levels[T][d] / (rates[T][d] / 100)
    return 100 * ((levels[x][d] / (rates[x][d] / 100) + levels[y][d] / (rates[y][d] / 100)) / force - 1)


def _world_with_gap(target, sexes=True, back=0, **kw):
    """A world where the labour force implied by the parts is `target` percent away from the one for everybody in one month, made by moving one part's rate (women's, or the 25 to 74's) by the amount found by bisection."""
    sid = W if sexes else A
    d = U._months_back(LAST, back)
    lo, hi = 0.0, 2.0
    for _ in range(80):
        mid = (lo + hi) / 2
        w = _world(**kw)
        w[0][sid][d] += mid
        if abs(_gap(w, d, sexes)) < target:
            lo = mid
        else:
            hi = mid
    w = _world(**kw)
    w[0][sid][d] += hi
    assert abs(abs(_gap(w, d, sexes)) - target) < 1e-6
    return w


def test_the_labour_force_implied_by_the_parts_must_agree_with_the_one_for_everybody_within_2_5_percent():
    for sexes, what in ((True, "women and men"), (False, "people under 25 and people aged 25 to 74")):
        assert _err(_world_with_gap(2.4, sexes)) is None, what
        w = _world_with_gap(2.6, sexes)
        assert _err(w) == f"the labour force implied for {what} in 2026-09 is 2.60% away from the one implied for everybody, more than 2.5%", what
        assert _err(_world_with_gap(2.6, sexes, back=23)) == f"the labour force implied for {what} in 2024-10 is 2.60% away from the one implied for everybody, more than 2.5%"      # the oldest month of the window
        w = _world()
        d = U._months_back(LAST, 24)
        w[0][W if sexes else A][d] += 0.3
        assert _err(w) is None                                                                             # before the window: not looked at


def _with(back, off):
    w = _world()
    w[0][W][U._months_back(LAST, back)] += off
    return w


def test_the_largest_gaps_are_reported_with_their_month_and_equal_gaps_name_the_earlier_month():
    def detail(*pairs):
        w = _world()
        for back, off in pairs:
            w[0][W][U._months_back(LAST, back)] += off
        return _run(w)["detail"]
    d = detail((5, 0.1), (3, 0.1))                                                                          # equal gaps in two months: the earlier one
    assert d["largest_labour_force_gap_month"] == "2026-04" and d["largest_labour_force_gap_pct"] == round(abs(_gap(_with(5, 0.1), U._months_back(LAST, 5))), 2)
    d = detail((5, 0.05), (0, 0.1))                                                                         # a larger gap in a later month
    assert d["largest_labour_force_gap_month"] == "2026-09"
    d = detail((5, 0.1), (0, -0.05))                                                                        # the other sign: counted by its size
    assert d["largest_labour_force_gap_month"] == "2026-04"
    d0 = _run(_world())["detail"]
    assert d0["largest_labour_force_gap_pct"] == 0.0 and d0["largest_labour_force_gap_month"] is None and d0["largest_sum_gap_thousands"] == 0.0
    for off_a, off_b, want in ((0.14, -0.12, 0.1), (0.18, -0.12, 0.2), (0.12, -0.18, 0.2)):               # the largest sum gap of the window, by its size
        w = _world()
        w[2][W][U._months_back(LAST, 7)] += off_a
        w[2][W][U._months_back(LAST, 2)] += off_b
        assert _run(w)["detail"]["largest_sum_gap_thousands"] == want, (off_a, off_b)


def test_changes_shares_and_rates_are_rounded_to_one_decimal_or_a_whole_percent_even_when_the_source_gives_more():
    w = _world(n_months=60, shape=lambda sid, d: (0.1237 if sid in (W, M) else 0.0731 if sid == Y else 0.0) * (60 + _idx(d)))      # rates drifting upwards by 0.1237 and 0.0731 points a month: more decimals than the source gives, and a different change over every span
    s = _run(w)
    r, l = w[0], w[2]
    for sid in U.IDS:                                                                                      # every figure rounded below really differs between one and two decimals
        assert round(r[sid][LAST], 1) != round(r[sid][LAST], 2), sid
    for n in (1, 3, 12):
        diff = r[T][LAST] - r[T][U._months_back(LAST, n)]
        assert round(diff, 1) != round(diff, 2), n
    assert len({round(r[T][LAST] - r[T][U._months_back(LAST, n)], 1) for n in (1, 2, 3, 11, 12, 13)}) == 6                  # so a change over the wrong span shows
    assert s["headline"]["rate_pct"] == round(r[T][LAST], 1)
    assert s["headline"]["change_1m_points"] == round(r[T][LAST] - r[T][U._months_back(LAST, 1)], 1)
    assert s["headline"]["change_3m_points"] == round(r[T][LAST] - r[T][U._months_back(LAST, 3)], 1)
    assert s["headline"]["change_12m_points"] == round(r[T][LAST] - r[T][U._months_back(LAST, 12)], 1)
    assert [g["rate_pct"] for g in s["groups"]] == [round(r[sid][LAST], 1) for sid in (W, M, Y, A)]
    assert s["persons"]["women_share_pct"] == round(100 * l[W][LAST] / l[T][LAST]) and s["persons"]["youth_share_pct"] == round(100 * l[Y][LAST] / l[T][LAST])
    window = [r[T][U._months_back(LAST, i)] for i in range(60)]
    assert s["range"]["lowest"]["pct"] == round(min(window), 1) and s["range"]["highest"]["pct"] == round(max(window), 1)
    assert s["history"][-1]["rate_pct"] == round(r[T][LAST], 1)
    assert round(min(window), 1) != round(min(window), 2) and round(max(window), 1) != round(max(window), 2)


def test_persons_are_shown_to_one_decimal_and_the_change_over_a_year_is_over_exactly_twelve_months():
    w = _world(scale=lambda d: 1.0 + 0.001 * (60 + _idx(d)))
    s = _run(w)
    l = w[2]
    assert s["persons"]["total_thousands"] == round(l[T][LAST], 1) and s["persons"]["change_12m_thousands"] == round(l[T][LAST] - l[T][U._months_back(LAST, 12)], 1)
    assert s["persons"]["change_12m_thousands"] != round(l[T][LAST] - l[T][U._months_back(LAST, 11)], 1) and s["persons"]["change_12m_thousands"] != round(l[T][LAST] - l[T][U._months_back(LAST, 13)], 1)
    assert [s["persons"][k] for k in ("women_thousands", "men_thousands", "youth_thousands", "adults_thousands")] == [round(l[sid][LAST], 1) for sid in (W, M, Y, A)]


def test_the_real_months_since_2015_are_never_refused_and_the_shocks_read_as_they_were():
    cuts = [m for m in sorted(_real()[0][T]) if m >= date(2015, 1, 1)]
    assert len(cuts) == 141
    for cut in cuts:                                                                                        # the card would never have gone dark in 141 real months
        assert _real_until(cut)["available"], cut
    s = _real_until(date(2015, 1, 1))
    assert (s["headline"]["rate_pct"], [g["rate_pct"] for g in s["groups"]], s["persons"]["total_thousands"]) == (11.4, [11.5, 11.3, 23.6, 10.2], 18434.0)
    for cut, rate, women, total_k in ((date(2020, 3, 1), 7.2, 7.4, 11660.3), (date(2020, 4, 1), 7.5, 7.6, 11937.2), (date(2020, 7, 1), 8.5, 8.9, 13763.5)):
        s = _real_until(cut)
        assert (s["headline"]["rate_pct"], s["groups"][0]["rate_pct"], s["persons"]["total_thousands"]) == (rate, women, total_k), cut


def test_the_limits_and_tolerances_are_the_ones_set_from_the_real_record():
    assert U.RATE_LIMITS == RATE_LIMITS and U.RATE_MOVE == RATE_MOVE and U.LEVEL_LIMITS == LEVEL_LIMITS and U.LEVEL_MOVE == LEVEL_MOVE
    assert (U.BETWEEN_TOLERANCE, U.SUM_TOLERANCE, U.LABOUR_FORCE_TOLERANCE) == (0.1, 0.2, 2.5)
    assert (U.CHECK_MONTHS, U.HISTORY_MONTHS, U.RANGE_WINDOW, U.OVERDUE_AFTER_DAYS, U.RATE_LAST_N, U.LEVEL_LAST_N) == (24, 60, 120, 75, 121, 40)
    assert (U.RATE_UNIT, U.LEVEL_UNIT) == (RU, LU) and U.IDS == (T, W, M, Y, A)
    assert "Eurostat's own arithmetic" in U.__doc__ and "not that the figures are right" in U.__doc__ and "321 months" in U.__doc__ and "Two checks that are not" in U.__doc__


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    assert list(_run(_world())["checks"]) == ["units_ok", "months_in_a_row", "range_ok", "monthly_move_ok", "total_between_sexes_ok", "total_between_ages_ok", "persons_add_up_ok", "labour_force_agrees_ok"]
    w = _world()
    w[0][T][LAST] = 25.0
    w[2][T][LAST] += 5.0
    assert _err(w).startswith("the unemployment rate of everybody aged 15 to 74 is 25.0%")                 # a rate out of range is stopped before the persons are looked at
    w = _world()
    w[2][W][LAST] += 3.0
    w[0][W][LAST] += 2.0
    assert _err(w).startswith("the unemployment rate of women moved by")                                    # the move of a rate is stopped before the sums and the labour forces


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_month_are_an_error():
    head = "KEY,AGE_BREAKDOWN,GENDER,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
    ok = "LFSI.M.I9.S.UNEHRT.TOTAL0.15_74.T"
    text = head + f"{ok},15_74,T,2026-07,6.5,A,PC,0\n{ok},15_74,T,2026-08,,A,PC,0\n{ok},15_74,T,2026-09,n/a,A,PC,0\n{ok},15_74,T,2026-W40,1,A,PC,0\nOTHER.KEY,15_74,T,2026-06,5,A,PC,0\n{ok},15_74,T,2026-07-15,2,A,PC,0\n{ok},15_74,T,2026-05,nan,A,PC,0\n{ok},15_74,T,2026-04,inf,A,PC,0\n{ok},15_74,F,2026-07,9,A,PC,0\nLFSI.M.I9.S.UNEHRT.TOTAL0.15_74.F,15_74,F,2026-07,6.7,A,PC,0\n"
    v, units, status = U.parse(text, "UNEHRT", (T,))
    assert v == {T: {date(2026, 7, 1): 6.5}} and units == {T: ("PC", "0")} and status == {T: "A"}          # a day-form date, nan, inf, another series and another key are all left out
    other = head + f"LFSI.M.I9.S.UNEMPL.TOTAL0.15_74.T,15_74,T,2026-07,11000,A,PERS,3\n{ok},15_74,T,2026-07,6.5,A,PC,0\nLFSI.M.I8.S.UNEHRT.TOTAL0.15_74.T,15_74,T,2026-07,9.9,A,PC,0\nLFSI.M.I9.N.UNEHRT.TOTAL0.15_74.T,15_74,T,2026-07,8.8,A,PC,0\nLFSI.Q.I9.S.UNEHRT.TOTAL0.15_74.T,15_74,T,2026-07,7.7,A,PC,0\n"
    assert U.parse(other, "UNEHRT", (T,))[0] == {T: {date(2026, 7, 1): 6.5}}                               # only the exact series: not the persons, another area, the unadjusted one or the quarterly one
    padded = head + f"{ok},15_74,T,2026-09,6,P, PC , 0 \n"
    assert U.parse(padded, "UNEHRT", (T,))[1] == {T: ("PC", "0")}                                           # spaces around a unit are not a different unit
    two = head + f"{ok},15_74,T,2026-07,1,A,PC,0\n{ok},15_74,T,2026-09,3,P,PC,0\n{ok},15_74,T,2026-08,2,A,PC,0\n"
    assert U.parse(two, "UNEHRT", (T,))[2] == {T: "P"}                                                      # the status is the newest month's, whatever the order of the rows
    with pytest.raises(ValueError, match=r"15_74\.T has two values for 2026-07"):
        U.parse(text + f"{ok},15_74,T,2026-07,1,A,PC,0\n", "UNEHRT", (T,))
    with pytest.raises(ValueError, match=r"no values for 15_74\.F"):
        U.parse(text.replace("LFSI.M.I9.S.UNEHRT.TOTAL0.15_74.F", "X"), "UNEHRT", (T, W))


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F["rates"] if "UNEHRT" in req.url.path else F["levels"])


def test_overview_fetches_two_requests_and_caches():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = U.EuroUnemployment(client=_transport(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["headline"]["rate_pct"] == 6.6 and len(seen) == 2 and r["source"].startswith("Eurostat")
    assert {req.url.path: req.url.params["lastNObservations"] for req in seen} == {"/service/data/LFSI/M.I9.S.UNEHRT.TOTAL0.15_74+15_24+25_74.T+F+M": "121", "/service/data/LFSI/M.I9.S.UNEMPL.TOTAL0.15_74+15_24+25_74.T+F+M": "40"}
    assert all(req.url.params["format"] == "csvdata" for req in seen) and all(req.headers["user-agent"] == "ATLAS research terminal" for req in seen)
    assert all("%2B" not in str(req.url) and "+" in str(req.url) for req in seen)                           # the + that joins the series of one key must reach the ECB as it is
    asyncio.run(svc.overview(NOW))
    assert len(seen) == 2


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(U.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = U.EuroUnemployment(client=_transport(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 2
    clock["t"] += U.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 2                                                                                     # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 4                              # two minutes on it asks again
    clock["t"] += U.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 4
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6 and (U.FAIL_TTL, U.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(U.EuroUnemployment(client=_transport(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "headline" not in r
    bad = F["rates"].replace("LFSI.M.I9.S.UNEHRT.TOTAL0.15_74.T,15_74,T,2026-09,6.6", "LFSI.M.I9.S.UNEHRT.TOTAL0.15_74.T,15_74,T,2026-09,66")      # a decimal slip in the newest rate: a check failing shows nothing either
    assert bad != F["rates"]
    r = asyncio.run(U.EuroUnemployment(client=_transport(lambda req: httpx.Response(200, text=bad if "UNEHRT" in req.url.path else F["levels"]))).overview(NOW))
    assert r["available"] is False and "the unemployment rate of everybody aged 15 to 74 is 66.0% in September 2026" in r["reason"] and "headline" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(U.EuroUnemployment(client=_transport(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The euro-area unemployment could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(U.EuroUnemployment(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "headline" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-unemployment")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
