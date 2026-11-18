"""Euro-area money supply (ECB Data Portal, BSI dataset): parsed from real responses (fetched 2026-11-17 14:3x UTC: 177 monthly values per series from 2012-01, newest 2026-09, provisional; the full history of 561 months for M1, M2 and M3 and 349 for the parts was read first to set every limit). Hand-worked figures (recomputed in plain Python from the saved responses, outside the module), the edges of every check one at a time on synthetic worlds that satisfy every other check by construction, the real shocks of 2020 and 2023 and every real month since 2015 (never refused), and the provider: caching, failure, demo and route."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import euromoney as E
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_money.json").read_text())
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)
PREFIX = "BSI.M.U2.Y.V."
SU, GU = ("EUR", "6"), ("PCCH", "0")


def _real():
    stocks, s_units, status = E.parse(F["stocks"], E.STOCK_IDS, PREFIX)
    growth, g_units, _ = E.parse(F["growth"], tuple(E.STOCKS), PREFIX)
    return stocks, growth, s_units, g_units, status


def _idx(d):
    """Months from LAST: 0 for the newest month, -1 for the one before."""
    return (d.year * 12 + d.month) - (LAST.year * 12 + LAST.month)


# a flat world, in millions of euro: every sum holds by construction
PARTS = {"L10": 1_600_000.0, "L21": 9_700_000.0, "L22": 2_600_000.0, "L23": 2_500_000.0, "L24A": 200_000.0, "L30": 900_000.0, "L40": 60_000.0}


def _levels(parts):
    p = dict(parts)
    p["M10"] = p["L10"] + p["L21"]
    p["M20"] = p["M10"] + p["L22"] + p["L23"]
    p["LT3"] = p["L24A"] + p["L30"] + p["L40"]
    p["M30"] = p["M20"] + p["LT3"]
    return p


def _world(parts=None, factor=lambda d: 1.0, n_months=48, edit=None, growth_edit=None):
    """`n_months` months ending 2026-09. Every amount is its flat level times `factor(month)`; the published growth is the growth of the amounts over twelve months (0 for the first twelve months), so the gap check holds by construction. `edit(id, month, value)` may change an amount after the sums were built, `growth_edit(id, month, value)` a published rate."""
    lv = _levels(parts or PARTS)
    months = [E._months_back(LAST, i) for i in range(n_months - 1, -1, -1)]
    stocks = {sid: {d: lv[sid] * factor(d) for d in months} for sid in E.STOCK_IDS}
    growth = {sid: {d: (100 * (stocks[sid][d] / stocks[sid][E._months_back(d, 12)] - 1) if E._months_back(d, 12) in stocks[sid] else 0.0) for d in months} for sid in E.STOCKS}
    if edit:
        for sid in stocks:
            for d in months:
                stocks[sid][d] = edit(sid, d, stocks[sid][d])
    if growth_edit:
        for sid in growth:
            for d in months:
                growth[sid][d] = growth_edit(sid, d, growth[sid][d])
    return stocks, growth, {sid: SU for sid in stocks}, {sid: GU for sid in growth}, {"M30": "P"}


def _run(world, today=TODAY):
    stocks, growth, s_units, g_units, status = world
    return E.summarize(stocks, growth, s_units, g_units, status, today)


def _at(sid_, months_back, delta):
    """An `edit` that adds `delta` to one amount in one month (the newest by default)."""
    return lambda sid, d, v: v + delta if (sid == sid_ and _idx(d) == -months_back) else v


def test_latest_amounts_growth_makeup_range_and_checks_by_hand():
    s = _run(_real())
    assert (s["date"], s["month"], s["age_days"], s["freshness"], s["provisional"]) == ("2026-09-01", "2026-09", 48, "CURRENT", True)
    assert s["m3"] == {"level_millions": 17717267.0, "growth_pct": 3.5, "change_1m_pct": 0.39, "change_3m_pct": 0.6}      # against 17,647,597 (Aug) and 17,612,461 (Jun): +0.395%, +0.596%
    assert s["m2"] == {"level_millions": 16491926.0, "growth_pct": 3.3, "change_1m_pct": 0.26, "change_3m_pct": 0.45}      # 16,449,710 and 16,417,415
    assert s["m1"] == {"level_millions": 11333724.0, "growth_pct": 2.7, "change_1m_pct": 0.33, "change_3m_pct": 0.08}      # 11,296,114 and 11,325,136
    assert [(m["id"], m["level_millions"], m["share_pct"]) for m in s["makeup"]] == [("M1", 11333724.0, 64.0), ("term", 2584866.0, 14.6), ("notice", 2573336.0, 14.5), ("marketable", 1225341.0, 6.9)]   # 63.970%, 14.590%, 14.524%, 6.916% of 17,717,267
    assert s["growth_range"] == {"months": 120, "lowest": {"pct": -1.3, "month": "2023-08"}, "highest": {"pct": 12.5, "month": "2021-01"}, "share_lower_pct": 31}       # 2016-10 to 2026-09; 37 of the 120 months grew slower than 3.504%
    assert s["detail"] == {"months_checked": 24, "sums_checked": 96, "largest_gap_points": 0.78, "largest_gap_month": "2026-09"}      # 4.285% for the amounts over the year against the published 3.504%
    assert all(s["checks"].values()) and s["source"].startswith("European Central Bank") and s["url"] == "https://data-api.ecb.europa.eu/service/data/BSI/M.U2.Y.V.M30.X.1.U2.2300.Z01.E"
    assert "not a market signal or a forecast" in s["note"] and "provisional" in s["note"] and "Plain checks: the units are the ones assumed" in s["note"]


def test_the_newest_month_is_provisional_only_when_the_ecb_says_so():
    assert _run(_world())["provisional"] is True
    w = _world()
    assert _run((*w[:4], {"M30": "A"}))["provisional"] is False
    assert _run((*w[:4], {}))["provisional"] is False


def test_the_history_is_the_last_36_months_of_m3_in_millions_oldest_first():
    s = _run(_real())
    assert len(s["history"]) == 36 and s["history"][0] == {"date": "2023-10-01", "level_millions": 15983253.0} and s["history"][-1] == {"date": "2026-09-01", "level_millions": 17717267.0}
    assert [h["date"] for h in s["history"]] == sorted(h["date"] for h in s["history"])


def test_a_short_history_says_not_available_for_what_it_cannot_compute():
    stocks, growth, su, gu, status = _real()
    keep = LAST - timedelta(days=300)
    stocks = {k: {d: v for d, v in s.items() if d >= keep} for k, s in stocks.items()}
    growth = {k: {d: v for d, v in s.items() if d >= keep} for k, s in growth.items()}
    s = E.summarize(stocks, growth, su, gu, status, TODAY)
    assert s["growth_range"] is None and s["m3"]["change_3m_pct"] == 0.6 and s["m3"]["level_millions"] == 17717267.0
    assert s["detail"]["months_checked"] == 10 and s["detail"]["sums_checked"] == 40


def test_the_ten_year_comparison_needs_at_least_60_months_of_published_growth():
    assert _run(_world(n_months=59))["growth_range"] is None
    g = _run(_world(n_months=60))["growth_range"]
    assert g == {"months": 60, "lowest": {"pct": 0.0, "month": g["lowest"]["month"]}, "highest": {"pct": 0.0, "month": g["highest"]["month"]}, "share_lower_pct": 0}


def test_overdue_after_75_days_from_the_end_of_the_month():
    end = date(2026, 9, 30)
    assert _run(_world(), end + timedelta(days=75))["freshness"] == "CURRENT"
    s = _run(_world(), end + timedelta(days=76))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 76
    assert _run(_world(), date(2026, 10, 3))["age_days"] == 3 and _run(_world(), date(2026, 9, 30))["age_days"] == 0       # a month's end is its last day, not the first of the next


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    stocks, growth, su, gu, status = _world()
    for sid in E.STOCK_IDS:
        for bad in (("EUR", "9"), ("USD", "6"), ("", "")):
            u = dict(su)
            u[sid] = bad
            with pytest.raises(ValueError, match=f"reports {sid} in other units than millions of euro"):
                E.summarize(stocks, growth, u, gu, status, TODAY)
    for sid in E.STOCKS:
        for bad in (("PCCH", "2"), ("PURE_NUMB", "0")):
            u = dict(gu)
            u[sid] = bad
            with pytest.raises(ValueError, match=f"growth of {E.STOCKS[sid]} in other units than percent"):
                E.summarize(stocks, growth, su, u, status, TODAY)


def test_a_series_ending_in_another_month_or_missing_a_month_is_refused():
    for kind, sids in (("stocks", E.STOCK_IDS), ("growth", tuple(E.STOCKS))):
        for sid in sids:
            stocks, growth, su, gu, status = _world()
            target = stocks if kind == "stocks" else growth
            del target[sid][LAST]
            with pytest.raises(ValueError, match="end in different months"):
                E.summarize(stocks, growth, su, gu, status, TODAY)
            stocks, growth, su, gu, status = _world()
            target = stocks if kind == "stocks" else growth
            target[sid][date(2026, 10, 1)] = 1.0                                       # a series that is a month AHEAD of the others
            with pytest.raises(ValueError, match="end in different months"):
                E.summarize(stocks, growth, su, gu, status, TODAY)
            if not (kind == "stocks" and sid == "M30"):
                stocks, growth, su, gu, status = _world()
                target = stocks if kind == "stocks" else growth
                del target[sid][E._months_back(LAST, 5)]
                with pytest.raises(ValueError, match=f"{sid} is missing for 2026-04"):
                    E.summarize(stocks, growth, su, gu, status, TODAY)
    stocks, growth, su, gu, status = _world()
    del stocks["L24A"][E._months_back(LAST, 24)]                                       # a hole before the window: not looked at
    assert E.summarize(stocks, growth, su, gu, status, TODAY)["detail"]["months_checked"] == 24


def test_the_months_of_m3_must_follow_each_other_in_the_last_24():
    def without(pos):
        stocks, growth, su, gu, status = _world()
        del stocks["M30"][sorted(stocks["M30"])[pos]]
        return stocks, growth, su, gu, status
    with pytest.raises(ValueError, match="skip a month"):
        _run(without(-10))
    with pytest.raises(ValueError, match="skip a month"):
        _run(without(-24))                                                              # the oldest month of the window: the gap sits between it and the next one
    assert _run(without(-25))["available"]                                              # before the window: not looked at


def test_each_aggregate_must_be_inside_its_range_and_a_slip_of_ten_is_caught():
    edge = dict(L10=700_000.0, L21=800_000.0, L22=750_000.0, L23=750_000.0, L24A=100_000.0, L30=400_000.0, L40=0.0)       # M1 1.5, M2 3.0 and M3 3.5 million million euro: each exactly at its floor
    r = _run(_world(edge))
    assert (r["m1"]["level_millions"], r["m2"]["level_millions"], r["m3"]["level_millions"]) == (1_500_000.0, 3_000_000.0, 3_500_000.0)
    with pytest.raises(ValueError, match="M1 is outside the plausible range"):
        _run(_world({**edge, "L21": 799_999.0}))                                           # M1 a million under (M2 and M3 too, but M1 is checked first)
    with pytest.raises(ValueError, match="M2 is outside the plausible range"):
        _run(_world({**edge, "L22": 749_999.0}))                                           # M1 at its floor, M2 a million under
    with pytest.raises(ValueError, match="M3 is outside the plausible range"):
        _run(_world({**edge, "L40": -1.0}))                                                # M1 and M2 at their floors, M3 a million under
    top = dict(PARTS, L40=4e7 - 17_560_000.0 + 60_000.0)                                   # M3 exactly 40 million million
    assert _run(_world(top))["m3"]["level_millions"] == 4e7
    with pytest.raises(ValueError, match="M3 is outside the plausible range"):
        _run(_world(dict(top, L40=top["L40"] + 1.0)))
    with pytest.raises(ValueError, match="M2 is outside the plausible range"):
        _run(_world(dict(PARTS, L22=4.0e7 - PARTS["L10"] - PARTS["L21"] - PARTS["L23"] + 1.0)))
    with pytest.raises(ValueError, match="M1 is outside the plausible range"):
        _run(_world(dict(PARTS, L21=4.0e7 - PARTS["L10"] + 1.0)))
    for sid in ("M10", "M20", "M30"):                                                      # a x10 or /10 slip in the amount itself
        for k in (10.0, 0.1):
            stocks, growth, su, gu, status = _world()
            stocks[sid] = {d: v * k for d, v in stocks[sid].items()}
            with pytest.raises(ValueError, match=f"{E.STOCKS[sid]} is outside the plausible range"):
                E.summarize(stocks, growth, su, gu, status, TODAY)


def test_the_ceilings_of_m1_and_m2_are_forty_million_million_too():
    huge = dict(L10=1_000_000.0, L21=38_500_000.0, L22=200_000.0, L23=200_000.0, L24A=20_000.0, L30=20_000.0, L40=10_000.0)      # M1 39.5, M2 39.9 and M3 39.95 million million euro: under 40 for all three
    r = _run(_world(huge))
    assert (r["m1"]["level_millions"], r["m2"]["level_millions"], r["m3"]["level_millions"]) == (39_500_000.0, 39_900_000.0, 39_950_000.0)


def test_levels_are_whole_millions_of_euro_in_the_summary_and_in_the_history():
    r = _run(_world(dict(PARTS, L21=9_700_000.4)))                                      # M1 11,300,000.4 and M3 17,560,000.4 (the real ECB values are whole millions today)
    assert r["m1"]["level_millions"] == 11_300_000.0 and r["m3"]["level_millions"] == 17_560_000.0 and r["history"][-1]["level_millions"] == 17_560_000.0


def test_a_growth_rate_exactly_at_a_limit_is_allowed():
    boom = lambda sid, d, v: 20.0 if (sid in ("M20", "M30") and d == LAST) else v      # the amounts grow 19.6% over the year; the ECB's published rate for the newest month is exactly 20.0
    assert _run(_world(factor=lambda d: 1.015 ** (_idx(d) + 47), growth_edit=boom))["m3"]["growth_pct"] == 20.0
    shrink = lambda sid, d, v: -5.0 if (sid in ("M20", "M30") and d == LAST) else v    # the amounts shrink 4.9%; published exactly -5.0
    assert _run(_world(factor=lambda d: 0.9958 ** (_idx(d) + 47), growth_edit=shrink))["m3"]["growth_pct"] == -5.0


def test_the_range_check_looks_at_the_last_24_months_and_no_further_back():
    def low_until(cut):
        return _world(factor=lambda d: 0.1 if _idx(d) <= -cut else 1.0)                    # every amount a tenth of itself up to `cut` months back
    with pytest.raises(ValueError, match="M1 is outside the plausible range"):
        _run(low_until(23))                                                                # the oldest month of the window is under the floor: inside
    with pytest.raises(ValueError) as e:
        _run(low_until(24))                                                                # only the months before the window are: they are not range-checked, what stops it now is the jump in the growth of the amounts
    assert "plausible range" not in str(e.value) and "growth of M1" in str(e.value)


def test_a_one_month_change_of_an_amount_under_minus_5_or_over_plus_10_percent_is_refused():
    def step(f):
        return _world(factor=lambda d: f if d == LAST else 1.0)
    assert _run(step(1.099))["m3"]["change_1m_pct"] == 9.9 and _run(step(0.951))["m3"]["change_1m_pct"] == -4.9        # the published growth follows the amounts in these worlds
    with pytest.raises(ValueError, match=r"M1 changed by 10.1% in 2026-09, outside -5% to \+10%"):
        _run(step(1.101))
    with pytest.raises(ValueError, match=r"M1 changed by -5.1% in 2026-09, outside -5% to \+10%"):
        _run(step(0.949))
    for sid, who in (("M20", "M2"), ("M30", "M3")):                                      # the other two alone (the sums are broken too, but this check comes first)
        with pytest.raises(ValueError, match=rf"{who} changed by 10.1% in 2026-09"):
            _run(_world(edit=lambda s, d, v, sid=sid: v * 1.101 if (s == sid and d == LAST) else v))
        with pytest.raises(ValueError, match=rf"{who} changed by -5.1% in 2026-09"):
            _run(_world(edit=lambda s, d, v, sid=sid: v * 0.949 if (s == sid and d == LAST) else v))


def test_the_month_move_check_looks_at_the_last_24_months_and_no_further_back():
    def step_up_at(back):
        return _world(factor=lambda d: 1.5 if _idx(d) >= -back else 1.0)
    second = E._label(E._months_back(LAST, 22))
    with pytest.raises(ValueError, match=f"M1 changed by 50.0% in {second}"):
        _run(step_up_at(22))                                                               # the step lands on the 2nd month of the window: the move into it is inside
    with pytest.raises(ValueError) as e:
        _run(step_up_at(23))                                                               # the step lands on the first month of the window: the move into it comes from before it, so what stops it is the +50% growth over the year
    assert "changed by" not in str(e.value) and "growth of M1 is +50.0%" in str(e.value)


def test_a_published_growth_rate_outside_its_range_is_refused_and_a_real_boom_is_not():
    boom = _world(factor=lambda d: 1.015 ** (_idx(d) + 47))                                # amounts growing 1.5% a month: 19.6% over the year, as published
    assert _run(boom)["m3"]["growth_pct"] == 19.6
    fast = _world(factor=lambda d: 1.0154 ** (_idx(d) + 47))                               # 20.1% over the year: over the limit of M2 and M3, under that of M1 (25%)
    with pytest.raises(ValueError, match=r"the growth of M2 is \+20.1% in 2024-10, outside -5% to \+20%"):
        _run(fast)
    shrink = _world(factor=lambda d: 0.9958 ** (_idx(d) + 47))                             # amounts shrinking 0.42% a month: -4.9% over the year
    assert _run(shrink)["m3"]["growth_pct"] == -4.9
    for sid, who, lo_bad, hi_bad in (("M10", "M1", -15.1, 25.1), ("M20", "M2", -5.1, 20.1), ("M30", "M3", -5.1, 20.1)):
        for bad in (hi_bad, lo_bad):
            want = re.escape(f"the growth of {who} is {bad:+.1f}% in 2026-09")
            with pytest.raises(ValueError, match=want):
                _run(_world(growth_edit=lambda s, d, v, sid=sid, bad=bad: bad if (s == sid and d == LAST) else v))


@pytest.mark.parametrize("which, edit_for", [("M1", ("L21", "M1 is not currency plus overnight deposits")),
                                              ("M2", ("L22", "M2 is not M1 plus the deposits with an agreed maturity and the deposits redeemable at notice")),
                                              ("marketable", ("L40", "the marketable instruments are not the repurchase agreements, money market fund shares and debt securities")),
                                              ("M3", ("M30", "M3 is not M2 plus the marketable instruments"))])
def test_each_sum_holds_to_one_million_euro_in_each_of_the_last_24_months(which, edit_for):
    sid, text = edit_for
    assert _run(_world(edit=_at(sid, 0, 1.0)))["available"]                              # one million: rounding, allowed
    assert _run(_world(edit=_at(sid, 0, -1.0)))["available"]
    with pytest.raises(ValueError, match=rf"{text} in 2026-09 \(off by"):
        _run(_world(edit=_at(sid, 0, 1.1)))
    with pytest.raises(ValueError, match=rf"{text} in 2026-09"):
        _run(_world(edit=_at(sid, 0, -1.1)))
    oldest = E._label(E._months_back(LAST, 23))
    with pytest.raises(ValueError, match=rf"{text} in {oldest}"):
        _run(_world(edit=_at(sid, 23, 5.0)))                                             # the 24th month back: inside
    assert _run(_world(edit=_at(sid, 24, 5.0)))["available"]                             # the 25th: outside


def test_the_sums_say_how_far_off_they_are():
    with pytest.raises(ValueError, match=r"off by -2 million euro"):                       # a part two million too large leaves the aggregate two million short of the sum
        _run(_world(edit=_at("L21", 0, 2.0)))
    with pytest.raises(ValueError, match=r"off by \+3 million euro"):
        _run(_world(edit=_at("L21", 0, -3.0)))


def test_the_published_growth_must_stay_within_4_points_of_the_growth_of_the_amounts_for_m3_4_and_a_half_for_m2_7_for_m1():
    for sid, who, tol in (("M30", "M3", 4.0), ("M20", "M2", 4.5), ("M10", "M1", 7.0)):
        def off(by, back=0, sid=sid):
            return _world(growth_edit=lambda s, d, v: v + by if (s == sid and _idx(d) == -back) else v)
        assert _run(off(tol - 0.1))["available"] and _run(off(-(tol - 0.1)))["available"]
        assert _run(off(tol))["available"] and _run(off(-tol))["available"]                 # exactly at the tolerance: allowed
        with pytest.raises(ValueError, match=rf"the published growth of {who} in 2026-09 is {tol + 0.1:.1f} points away from the growth of the amounts, more than {tol:g}"):
            _run(off(tol + 0.1))
        with pytest.raises(ValueError, match=rf"{who} in 2026-09 is {tol + 0.1:.1f} points away"):
            _run(off(-(tol + 0.1)))
        oldest = E._label(E._months_back(LAST, 23))
        with pytest.raises(ValueError, match=rf"{who} in {oldest}"):
            _run(off(tol + 0.1, back=23))                                                 # the 24th month back: inside
        assert _run(off(tol + 0.1, back=24))["available"]                                 # the 25th: outside


def test_the_growth_of_the_amounts_is_over_exactly_twelve_months():
    dip = _world(factor=lambda d: 0.952 if _idx(d) == -12 else 1.0)                      # a month 12 back that is 4.8% lower than its neighbours: with 11 or 13 months the published growth would disagree by 5 points
    assert _run(dip)["available"]


def test_a_month_ends_on_its_last_day():
    assert E._month_end(date(2026, 9, 1)) == date(2026, 9, 30) and E._month_end(date(2026, 12, 1)) == date(2026, 12, 31) and E._month_end(date(2024, 2, 1)) == date(2024, 2, 29)


def test_the_largest_gap_of_the_window_is_reported_with_its_month_not_the_last_one():
    w = _world(growth_edit=lambda s, d, v: v + (1.234 if (s == "M30" and _idx(d) in (-5, -3)) else 0.3 if (s == "M30" and d == LAST) else 0.0))
    d = _run(w)["detail"]
    assert d["largest_gap_points"] == -1.23 and d["largest_gap_month"] == "2026-04"       # published above the amounts: the gap is negative; two equal gaps: the earlier month
    assert _run(_world())["detail"]["largest_gap_points"] == 0.0 and _run(_world())["detail"]["largest_gap_month"] is None


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    assert list(_run(_world())["checks"]) == ["units_ok", "months_in_a_row", "range_ok", "monthly_move_ok", "growth_range_ok", "sums_ok", "growth_agrees_ok"]
    with pytest.raises(ValueError, match="M1 changed by"):                              # a +50% month with a matching published growth is stopped by the size of the move first
        _run(_world(factor=lambda d: 1.5 if d == LAST else 1.0))


def test_the_real_months_since_2015_are_never_refused_and_the_shocks_read_as_they_were():
    stocks, growth, su, gu, status = _real()
    months = sorted(stocks["M30"])
    cuts = [m for m in months if m >= date(2015, 1, 1)]
    for cut in cuts:                                                                      # the card would never have gone dark in 141 real months
        s = {k: {d: v for d, v in ser.items() if d <= cut} for k, ser in stocks.items()}
        g = {k: {d: v for d, v in ser.items() if d <= cut} for k, ser in growth.items()}
        assert E.summarize(s, g, su, gu, status, cut + timedelta(days=40))["available"], cut
    for cut, one_month, growth_pct, m1_growth in ((date(2020, 3, 1), 2.64, 7.5, 10.6), (date(2020, 4, 1), 1.16, 8.1, 11.8), (date(2021, 2, 1), 0.55, 12.4, 16.6), (date(2023, 8, 1), -0.05, -1.3, -10.4)):
        s = {k: {d: v for d, v in ser.items() if d <= cut} for k, ser in stocks.items()}
        g = {k: {d: v for d, v in ser.items() if d <= cut} for k, ser in growth.items()}
        r = E.summarize(s, g, su, gu, status, cut + timedelta(days=40))
        assert (r["m3"]["change_1m_pct"], r["m3"]["growth_pct"], r["m1"]["growth_pct"]) == (one_month, growth_pct, m1_growth)


def test_the_parts_the_card_needs_are_asked_for_and_the_ecb_builds_the_sums_not_a_third_party():
    assert set(E.STOCK_IDS) == {"M10", "M20", "M30", "L10", "L21", "L22", "L23", "L24A", "L30", "L40", "LT3"} and set(E.STOCKS) == {"M10", "M20", "M30"}
    assert "by its own arithmetic" in E.__doc__ and "not that the ECB's figures are right" in E.__doc__ and "all 561 months" in E.__doc__


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_month_are_an_error():
    head = "KEY,BS_ITEM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
    ok = PREFIX + "M30.X.1.U2.2300.Z01.E"
    text = head + f"{ok},M30,2026-07,17600000,A,EUR,6\n{ok},M30,2026-08,,A,EUR,6\n{ok},M30,2026-09,n/a,P,EUR,6\n{ok},M30,2026-W40,1,A,EUR,6\nOTHER.KEY,M30,2026-06,5,A,EUR,6\n{ok},M30,2026-07-15,2,A,EUR,6\n{ok},M30,2026-10,nan,A,EUR,6\n{ok},M30,2026-11,inf,A,EUR,6\n{ok},M20,2026-07,3,A,EUR,6\n"
    v, units, status = E.parse(text, ("M30",), PREFIX)
    assert v == {"M30": {date(2026, 7, 1): 17600000.0}} and units == {"M30": ("EUR", "6")} and status == {"M30": "A"}      # a day-form date, nan, inf, another series and another key are all left out
    padded = head + f"{ok},M30,2026-09,3,P, EUR , 6 \n"
    assert E.parse(padded, ("M30",), PREFIX)[1] == {"M30": ("EUR", "6")}                    # spaces around a unit are not a different unit
    two = head + f"{ok},M30,2026-07,1,A,EUR,6\n{ok},M30,2026-09,3,P,EUR,6\n{ok},M30,2026-08,2,A,EUR,6\n"
    assert E.parse(two, ("M30",), PREFIX)[2] == {"M30": "P"}                                # the status is the newest month's, whatever the order of the rows
    with pytest.raises(ValueError, match="M30 has two values for 2026-07"):
        E.parse(text + f"{ok},M30,2026-07,1,A,EUR,6\n", ("M30",), PREFIX)
    with pytest.raises(ValueError, match="no values for L99"):
        E.parse(text, ("M30", "L99"), PREFIX)


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F["stocks"] if req.url.path.endswith(E.STOCK_KEY) else F["growth"])


def test_overview_fetches_two_requests_and_caches():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = E.EuroMoneySupply(client=_transport(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["m3"]["level_millions"] == 17717267.0 and len(seen) == 2 and r["source"].startswith("European Central Bank")
    assert {req.url.params["lastNObservations"] for req in seen} == {"48", "121"} and all(req.url.params["format"] == "csvdata" for req in seen)
    assert {req.url.path: req.url.params["lastNObservations"] for req in seen} == {"/service/data/BSI/M.U2.Y.V.L10+L21+L22+L23+L24A+L30+L40+LT3+M10+M20+M30..1.U2.2300.Z01.E": "48", "/service/data/BSI/M.U2.Y.V.M10+M20+M30.X.I.U2.2300.Z01.A": "121"}
    assert all(req.headers["user-agent"] == "ATLAS research terminal" for req in seen)       # the ECB host takes it, as the other ECB cards do
    assert all("%2B" not in str(req.url) and "+" in str(req.url) for req in seen)            # the + that joins the series of one key must reach the ECB as it is
    asyncio.run(svc.overview(NOW))
    assert len(seen) == 2


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(E.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = E.EuroMoneySupply(client=_transport(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 2
    clock["t"] += E.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 2                                                                   # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 4           # two minutes on it asks again
    clock["t"] += E.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 4
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6 and (E.FAIL_TTL, E.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(E.EuroMoneySupply(client=_transport(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "m3" not in r
    bad = F["stocks"].replace("M30,2026-09,17717267", "M30,2026-09,177172670")           # a decimal slip in the newest M3: a check failing shows nothing either
    r = asyncio.run(E.EuroMoneySupply(client=_transport(lambda req: httpx.Response(200, text=bad if req.url.path.endswith(E.STOCK_KEY) else F["growth"]))).overview(NOW))
    assert r["available"] is False and "M3 is outside the plausible range" in r["reason"] and "m3" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(E.EuroMoneySupply(client=_transport(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The euro-area money supply could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(E.EuroMoneySupply(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "m3" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-money-supply")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
