"""Euro-area consumer prices (ECB Data Portal, HICP dataflow): parsed from real responses (fetched 2026-11-17 17:2x UTC: monthly annual rates of seven series from 2012-01, indices of six series from 2012-01, yearly basket weights of six series from 2011; newest month 2026-10, an estimate; the full history from 1996 was read to set the checks, see the module's docstring)."""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import eurohicp as H
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_inflation.json").read_text())
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
LAST = date(2026, 10, 1)
RU, IU, WU = ("PCCH", "0"), ("IX", "0"), ("PM", "0")


def _real():
    rates, ru, status = H.parse(F["rates"], H.RATE_IDS, "M", "ANR")
    indices, iu, _ = H.parse(F["indices"], H.INDEX_IDS, "M", "INX")
    weights, wu, _ = H.parse(F["weights"], H.WEIGHT_IDS, "A", "INW")
    return rates, ru, indices, iu, weights, wu, status


def _real_until(cut, today=None):
    """The real answers as they would have looked with `cut` as the newest month."""
    rates, ru, indices, iu, weights, wu, status = _real()
    r = {k: {d: v for d, v in s.items() if d <= cut} for k, s in rates.items()}
    i = {k: {d: v for d, v in s.items() if d <= cut} for k, s in indices.items()}
    return H.summarize(r, ru, i, iu, weights, wu, status, today or cut + timedelta(days=20))


def _idx(d):
    """Months from LAST: 0 for the newest month, -1 for the one before."""
    return (d.year * 12 + d.month) - (LAST.year * 12 + LAST.month)


# the basket weights of the synthetic world, per mille; they differ from year to year so that a check using the wrong year's weights is noticed
WEIGHTS = {2021: {"FOODPR": 190.0, "FOODUN": 100.0, "IGXE00": 200.0, "NRGY00": 230.0, "SERV00": 280.0},
           2022: {"FOODPR": 180.0, "FOODUN": 90.0, "IGXE00": 210.0, "NRGY00": 210.0, "SERV00": 310.0},
           2023: {"FOODPR": 170.0, "FOODUN": 80.0, "IGXE00": 220.0, "NRGY00": 180.0, "SERV00": 350.0},
           2024: {"FOODPR": 160.0, "FOODUN": 70.0, "IGXE00": 230.0, "NRGY00": 150.0, "SERV00": 390.0},
           2025: {"FOODPR": 150.0, "FOODUN": 60.0, "IGXE00": 240.0, "NRGY00": 120.0, "SERV00": 430.0},
           2026: {"FOODPR": 140.0, "FOODUN": 50.0, "IGXE00": 250.0, "NRGY00": 90.0, "SERV00": 470.0}}
DRIFT = {"FOODPR": 1.001, "FOODUN": 1.003, "IGXE00": 1.001, "NRGY00": 1.01, "SERV00": 1.003}      # monthly growth of each part's index: 1.2%, 3.7%, 1.2%, 12.7% and 3.7% a year
RATE_LIMITS = {"000000": (-3.0, 20.0), "FOODPR": (-3.0, 25.0), "FOODUN": (-10.0, 30.0), "IGXE00": (-3.0, 12.0), "NRGY00": (-30.0, 80.0), "SERV00": (-2.0, 12.0), "XEF000": (-2.0, 12.0)}   # percent: the limits set from the real record, spelled out here so that a changed limit fails a test
MONTH_MOVE = {"000000": (-3.0, 4.0), "FOODPR": (-1.5, 3.0), "FOODUN": (-5.0, 6.0), "IGXE00": (-6.0, 6.0), "NRGY00": (-10.0, 16.0), "SERV00": (-3.0, 3.0)}     # percent change of an index in one month
INDEX_LIMITS = (20.0, 250.0)
STEADY = {s: 1.008 for s in H.PARTS}                                                                   # every part growing 0.8% a month: 10.0% a year


def _world(n_months=59, growth=None, shape=None, status=None):
    """`n_months` months ending 2026-10 (the default starts in December 2021, the first base). Every part's index is 100 times its monthly growth to the power of the months since the start, times `shape(sid, month)`; the all-items index is built by the chain-linking rule from the parts and the year's weights, so every identity holds by construction; the published rates are the rates the indices give (for the months without an index a year earlier: the rate the growth gives); core is the weighted mean of the goods and the services."""
    g = growth or {}
    months = [H._months_back(LAST, i) for i in range(n_months - 1, -1, -1)]
    idx = {sid: {} for sid in H.INDEX_IDS}
    for sid in H.PARTS:
        for k, d in enumerate(months):
            idx[sid][d] = 100.0 * g.get(sid, 1.0) ** k * (shape(sid, d) if shape else 1.0)
    years = range(months[0].year, LAST.year + 1)
    weights = {sid: {y: WEIGHTS[y][sid] for y in years} for sid in H.PARTS}
    weights[H.TOTAL] = {y: 1000.0 for y in years}
    first_dec = next(d for d in months if d.month == 12)
    idx[H.TOTAL][first_dec] = 100.0
    for d in months:
        if d > first_dec:
            base = date(d.year - 1, 12, 1)
            idx[H.TOTAL][d] = idx[H.TOTAL][base] * sum(weights[s][d.year] / 1000 * idx[s][d] / idx[s][base] for s in H.PARTS)
    rates = {sid: {} for sid in H.RATE_IDS}
    for d in months:
        ago = H._months_back(d, 12)
        for sid in H.PARTS:
            rates[sid][d] = 100 * (idx[sid][d] / idx[sid][ago] - 1) if ago in idx[sid] else 100 * (g.get(sid, 1.0) ** 12 - 1)
        rates[H.TOTAL][d] = 100 * (idx[H.TOTAL][d] / idx[H.TOTAL][ago] - 1) if (d in idx[H.TOTAL] and ago in idx[H.TOTAL]) else sum(weights[s][d.year] / 1000 * rates[s][d] for s in H.PARTS)
        wg, ws = weights["IGXE00"][d.year], weights["SERV00"][d.year]
        rates[H.CORE][d] = (wg * rates["IGXE00"][d] + ws * rates["SERV00"][d]) / (wg + ws)
    return (rates, {s: RU for s in rates}, idx, {s: IU for s in idx}, weights, {s: WU for s in weights}, status if status is not None else {H.TOTAL: "E"})


def _run(world, today=TODAY):
    return H.summarize(*world, today)


def _err(world, today=TODAY):
    """The refusal's text, or None when the world passes every check."""
    try:
        _run(world, today)
    except ValueError as e:
        return str(e)
    return None


def _step(moves, growth=None):
    """A world where each part's index steps by `moves[sid]` percent in the newest month only, on top of its growth (flat by default): every identity still holds."""
    return _world(growth=growth, shape=lambda sid, d: 1 + moves.get(sid, 0.0) / 100 if d == LAST else 1.0)


def _fix_total_rate(w, d):
    """Set the all-items rate of month d to the rate its index gives, after the index was edited."""
    w[0][H.TOTAL][d] = 100 * (w[2][H.TOTAL][d] / w[2][H.TOTAL][H._months_back(d, 12)] - 1)


def test_latest_headline_parts_contributions_range_and_checks_by_hand():
    s = _run(_real())
    assert (s["date"], s["month"], s["age_days"], s["freshness"], s["estimate"]) == ("2026-10-01", "2026-10", 17, "CURRENT", True)
    assert s["headline"] == {"rate_pct": 4.0, "change_1m_points": 0.2, "change_3m_points": 1.1, "core_rate_pct": 2.5}                     # 3.8 in September and 2.9 in July
    assert [(p["id"], p["rate_pct"], p["share_pct"], p["points"]) for p in s["parts"]] == [("FOODPR", 0.5, 13.8, 0.07), ("FOODUN", 4.6, 5.1, 0.24), ("IGXE00", 1.2, 25.2, 0.3), ("NRGY00", 20.8, 9.0, 1.88), ("SERV00", 3.3, 46.8, 1.55)]
    # 2026 weights 137.95, 51.40, 252.16, 90.26 and 468.23 per mille: 0.13795 x 0.5 = 0.0690, 0.0514 x 4.6 = 0.2364, 0.25216 x 1.2 = 0.3026, 0.09026 x 20.8 = 1.8774, 0.46823 x 3.3 = 1.5452; the sum 4.0306 is 0.0306 above the headline 4.0
    assert s["contributions"] == {"shown": True, "sum_points": 4.03, "gap_points": 0.03}
    assert s["range"] == {"months": 120, "lowest": {"pct": -0.3, "month": "2020-09"}, "highest": {"pct": 10.6, "month": "2022-10"}, "share_lower_pct": 79}      # 2016-11 to 2026-10; 95 of the 120 months were under 4.0
    assert s["detail"] == {"months_checked": 24, "largest_rate_gap_points": 0.05, "largest_index_gap": 0.009, "largest_index_gap_month": "2025-11"}    # 0.0500 for processed food in 2026-05; 0.00897 index points in 2025-11
    assert all(s["checks"].values()) and s["source"].startswith("Eurostat") and s["url"] == "https://data-api.ecb.europa.eu/service/data/HICP/M.U2.N.000000.4D0.ANR"
    assert "not a market signal or a forecast" in s["note"] and "flash" in s["note"] and "not that the figures are right" in s["note"]


def test_the_newest_month_is_an_estimate_only_when_the_source_says_so():
    assert _run(_world())["estimate"] is True
    assert _run(_world(status={H.TOTAL: "P"}))["estimate"] is True
    assert _run(_world(status={H.TOTAL: "A"}))["estimate"] is False
    assert _run(_world(status={}))["estimate"] is False
    assert _run(_world(status={"NRGY00": "E"}))["estimate"] is False                                       # the headline's own status decides


def test_the_history_is_the_last_60_months_of_the_headline_oldest_first():
    s = _run(_real())
    assert len(s["history"]) == 60 and s["history"][0] == {"date": "2021-11-01", "rate_pct": 4.9} and s["history"][-1] == {"date": "2026-10-01", "rate_pct": 4.0}
    assert [h["date"] for h in s["history"]] == sorted(h["date"] for h in s["history"])


def test_a_history_too_short_for_the_checks_is_refused_not_skipped():
    with pytest.raises(ValueError, match="the index of all items is missing for 2023-11"):
        _run(_world(n_months=46))                                                                          # 24 checked months (2024-11 to 2026-10) need the indices of the 12 months before the first of them
    w = _world(n_months=47)                                                                                # 2022-12 to 2026-10: the first December a year before the window, just enough
    assert _run(w)["detail"]["months_checked"] == 24 and min(w[2][H.TOTAL]) == date(2022, 12, 1)


def test_the_ten_year_comparison_needs_at_least_60_months_of_the_headline():
    assert _run(_world(n_months=59))["range"] is None
    g = _run(_world(n_months=60))["range"]                                                                 # a flat world: every rate 0.0, so none is lower than the newest
    assert g == {"months": 60, "lowest": {"pct": 0.0, "month": g["lowest"]["month"]}, "highest": {"pct": 0.0, "month": g["highest"]["month"]}, "share_lower_pct": 0}


def test_overdue_after_50_days_from_the_end_of_the_month():
    end = date(2026, 10, 31)
    assert _run(_world(), end + timedelta(days=50))["freshness"] == "CURRENT"
    s = _run(_world(), end + timedelta(days=51))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 51
    assert _run(_world(), date(2026, 11, 3))["age_days"] == 3 and _run(_world(), end)["age_days"] == 0       # a month's end is its last day, not the first of the next
    assert H._month_end(date(2026, 10, 1)) == date(2026, 10, 31) and H._month_end(date(2026, 12, 1)) == date(2026, 12, 31) and H._month_end(date(2024, 2, 1)) == date(2024, 2, 29)


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    for pos, kind, ids, right in ((1, "annual rate", H.RATE_IDS, RU), (3, "index", H.INDEX_IDS, IU), (5, "weight", H.WEIGHT_IDS, WU)):
        for sid in ids:
            for bad in (("PCCH", "2"), ("IX", "1"), ("PM", "3"), ("EUR", "6"), ("", "")):
                if bad == right:
                    continue
                w = list(_world())
                w[pos] = dict(w[pos])
                w[pos][sid] = bad
                with pytest.raises(ValueError, match=re.escape(f"the ECB reports the {kind} of {H.NAMES[sid]} in other units than the card assumes")):
                    H.summarize(*w, TODAY)


def test_a_series_ending_in_another_month_or_missing_a_month_is_refused():
    for which, ids in ((0, H.RATE_IDS), (2, H.INDEX_IDS)):
        for sid in ids:
            w = _world()
            del w[which][sid][LAST]
            with pytest.raises(ValueError, match="end in different months"):
                _run(w)
            w = _world()
            w[which][sid][date(2026, 11, 1)] = 1.0                                                          # one month AHEAD of the others
            with pytest.raises(ValueError, match="end in different months"):
                _run(w)
    for sid in H.RATE_IDS:
        if sid == H.TOTAL:
            continue
        w = _world()
        del w[0][sid][H._months_back(LAST, 5)]
        with pytest.raises(ValueError, match=re.escape(f"the annual rate of {H.NAMES[sid]} is missing for 2026-05")):
            _run(w)
    for sid in H.INDEX_IDS:
        for back in (5, 17, 35):                                                                           # a checked month; another checked month; the month a year before the oldest checked one
            w = _world()
            del w[2][sid][H._months_back(LAST, back)]
            with pytest.raises(ValueError, match=re.escape(f"the index of {H.NAMES[sid]} is missing for {H._label(H._months_back(LAST, back))}")):
                _run(w)
    w = _world()
    del w[0]["SERV00"][H._months_back(LAST, 24)]                                                           # a hole before the window: not looked at
    assert _run(w)["detail"]["months_checked"] == 24


def test_the_december_before_each_year_of_the_window_is_needed():
    w = _world()
    del w[2]["NRGY00"][date(2023, 12, 1)]                                                                   # the base of the 2024 months in the window
    with pytest.raises(ValueError, match="the index of energy is missing for 2023-12"):
        _run(w)
    w = _world()
    del w[2][H.TOTAL][date(2024, 12, 1)]
    with pytest.raises(ValueError, match="the index of all items is missing for 2024-12"):
        _run(w)


def test_the_months_must_follow_each_other_in_the_last_24():
    def without(pos):
        w = _world()
        for sid in H.RATE_IDS:
            del w[0][sid][sorted(w[0][sid])[pos]]
        return w
    with pytest.raises(ValueError, match="skip a month"):
        _run(without(-10))
    with pytest.raises(ValueError, match="skip a month"):
        _run(without(-24))                                                                                 # the oldest month of the window: the gap sits between it and the next one
    assert _run(without(-25))["available"]                                                                 # before the window: not looked at


def test_each_annual_rate_must_be_inside_its_range():
    for sid, (lo, hi) in RATE_LIMITS.items():
        for edge, bad in ((hi, hi + 0.1), (lo, lo - 0.1)):
            w = _world()
            w[0][sid][LAST] = edge
            assert not re.search(r"annual rate of .* outside", _err(w) or ""), (sid, edge)                    # at the limit the range check lets it through (a later check refuses the made-up value)
            w = _world()
            w[0][sid][LAST] = bad
            assert _err(w) == f"the annual rate of {H.NAMES[sid]} is {bad:+.1f}% in 2026-10, outside {lo:+.0f}% to {hi:+.0f}%", (sid, bad)


def test_the_rate_range_check_looks_at_the_last_24_months_and_no_further_back():
    w = _world()
    w[0]["NRGY00"][H._months_back(LAST, 23)] = 90.0
    assert _err(w) == "the annual rate of energy is +90.0% in 2024-11, outside -30% to +80%"               # the oldest month of the window
    w = _world()
    w[0]["NRGY00"][H._months_back(LAST, 24)] = 90.0
    assert _err(w) is None


def test_an_index_slip_of_ten_is_caught_and_the_edges_are_allowed():
    lo, hi = INDEX_LIMITS
    for sid in H.PARTS:
        for level, ok in ((lo, True), (lo - 0.01, False), (hi, True), (hi + 0.01, False)):
            w = _world()
            for d in w[2][sid]:
                w[2][sid][d] = level                                                                      # a flat index at that level: no move, and the ratios (so the identity) are unchanged
            e = _err(w)
            if ok:
                assert e is None, (sid, level, e)
            else:
                assert e == f"the index of {H.NAMES[sid]} is outside the plausible range", (sid, level, e)
    for k in (10.0, 0.1):
        w = _world()
        w[2][H.TOTAL] = {d: v * k for d, v in w[2][H.TOTAL].items()}
        assert _err(w) == "the index of all items is outside the plausible range"


def test_a_one_month_move_of_a_part_outside_its_bounds_is_refused_and_inside_is_not():
    for sid, (lo, hi) in MONTH_MOVE.items():
        if sid == H.TOTAL:
            continue
        assert _err(_step({sid: hi - 0.01})) is None                                                        # a flat world: the month's move is the step
        assert _err(_step({sid: hi + 0.1})) == f"the index of {H.NAMES[sid]} changed by {hi + 0.1:+.1f}% in 2026-10, outside {lo:+.1f}% to {hi:+.1f}%"
        def step_for(move):                                                                                 # steady growth of 0.8% a month, then the step that makes the month's move `move`
            return _step({sid: ((1 + move / 100) / 1.008 - 1) * 100}, STEADY)
        assert _err(step_for(lo + 0.01)) is None
        assert _err(step_for(lo - 0.1)) == f"the index of {H.NAMES[sid]} changed by {lo - 0.1:+.1f}% in 2026-10, outside {lo:+.1f}% to {hi:+.1f}%"


def test_a_one_month_move_of_the_all_items_index_under_minus_3_or_over_plus_4_percent_is_refused():
    w26 = WEIGHTS[2026]
    for target, g, growth in ((3.9, 1.0, None), (4.1, 1.0, None), (-2.9, 1.008, STEADY), (-3.1, 1.008, STEADY)):
        side = 1 if target > 0 else 0
        reach = sum(w26[s] / 1000 * MONTH_MOVE[s][side] for s in H.PARTS)                                  # the weighted step if every part stepped to its own bound
        need = 100 * ((1 + target / 100) / g - 1)                                                            # the weighted step that makes the all-items index move by `target` on top of the growth
        moves = {s: need / reach * MONTH_MOVE[s][side] for s in H.PARTS}                                   # every part inside its own bound
        e = _err(_step(moves, growth))
        if -3.0 <= target <= 4.0:
            assert e is None, (target, e)
        else:
            assert e == f"the index of all items changed by {target:+.1f}% in 2026-10, outside -3.0% to +4.0%", (target, e)


def test_the_month_move_check_looks_at_the_last_24_months_and_no_further_back():
    def spike_at(back):
        return _world(shape=lambda sid, d: 1.2 if (sid == "NRGY00" and _idx(d) == -back) else 1.0)       # energy 20% high for one month: +20.0% into it, -16.7% out of it
    assert _err(spike_at(22)) == f"the index of energy changed by +20.0% in {H._label(H._months_back(LAST, 22))}, outside -10.0% to +16.0%"      # the 2nd month of the window: the move into it is inside
    assert _err(spike_at(23)) == f"the index of energy changed by -16.7% in {H._label(H._months_back(LAST, 22))}, outside -10.0% to +16.0%"      # the 1st month: the move into it comes from before the window, the move out of it is inside
    assert _err(spike_at(24)) is None                                                                       # before the window: neither move is looked at


def test_the_basket_weights_must_add_up_to_1000_in_each_year_of_the_window():
    for year in (2024, 2025, 2026):
        w = _world()
        w[4]["SERV00"][year] += 0.04
        assert "add up to" not in (_err(w) or "")                                                           # inside the tolerance of 0.05: allowed
        w = _world()
        w[4][H.TOTAL][year] = 999.96
        assert "add up to" not in (_err(w) or "")
        for off in (0.06, -0.06):
            w = _world()
            w[4]["SERV00"][year] += off
            assert _err(w) == f"the basket weights of {year} add up to {1000 + off:.2f} (all items 1000.00) per mille, not 1000"
        for total in (1000.06, 999.94):
            w = _world()
            w[4][H.TOTAL][year] = total
            assert _err(w) == f"the basket weights of {year} add up to 1000.00 (all items {total:.2f}) per mille, not 1000"
    w = _world()
    w[4]["SERV00"][2023] += 40.0                                                                            # a year before the window: not looked at
    assert "add up to" not in (_err(w) or "")
    w = _world()
    del w[4]["IGXE00"][2025]
    assert _err(w) == "the basket weight of non-energy industrial goods is missing for 2025"


def test_the_headline_must_lie_between_the_lowest_and_the_highest_rate_of_its_five_parts():
    base = _world(growth=DRIFT)
    five = [base[0][s][LAST] for s in H.PARTS]
    lo, hi = min(five), max(five)
    assert _err(base) is None and lo < base[0][H.TOTAL][LAST] < hi
    for value in (hi + 0.09, lo - 0.09):
        w = _world(growth=DRIFT)
        w[0][H.TOTAL][LAST] = value
        assert "range of its five parts" not in _err(w), value                                              # inside the tolerance of 0.1 the between check passes; the published rate then disagrees with its index, a later check
    for value in (hi + 0.11, lo - 0.11):
        w = _world(growth=DRIFT)
        w[0][H.TOTAL][LAST] = value
        assert _err(w) == f"the headline rate in 2026-10 ({value:.1f}%) is outside the range of its five parts ({lo:.1f}% to {hi:.1f}%)"
    w = _world(growth=DRIFT)
    w[0][H.TOTAL][H._months_back(LAST, 23)] = 19.0                                                          # under the range limit of +20%, over the highest part
    assert _err(w).startswith("the headline rate in 2024-11 (19.0%) is outside the range of its five parts")      # the oldest month of the window is inside
    w = _world(growth=DRIFT)
    w[0][H.TOTAL][H._months_back(LAST, 24)] = 19.0
    assert _err(w) is None


def test_core_must_lie_between_the_goods_and_the_services():
    base = _world(growth=DRIFT)
    goods, services = sorted((base[0]["IGXE00"][LAST], base[0]["SERV00"][LAST]))
    assert _err(base) is None and goods < base[0][H.CORE][LAST] < services
    for value in (services + 0.09, goods - 0.09):
        w = _world(growth=DRIFT)
        w[0][H.CORE][LAST] = value
        assert _err(w) is None, value                                                                       # nothing else looks at the core rate
    for value in (services + 0.11, goods - 0.11):
        w = _world(growth=DRIFT)
        w[0][H.CORE][LAST] = value
        assert _err(w) == f"the core rate in 2026-10 ({value:.1f}%) is outside the range of the goods and the services ({goods:.1f}% to {services:.1f}%)"
    w = _world(growth=DRIFT)
    w[0][H.CORE][H._months_back(LAST, 23)] = 9.0
    assert _err(w).startswith("the core rate in 2024-11 (9.0%)")
    w = _world(growth=DRIFT)
    w[0][H.CORE][H._months_back(LAST, 24)] = 9.0
    assert _err(w) is None


def _total_off_by(off, back):
    """A drifting world where the all-items index of one month is `off` index points away from what its parts give, the published rates kept in line with the indices."""
    w = _world(growth=DRIFT)
    d = H._months_back(LAST, back)
    w[2][H.TOTAL][d] += off
    _fix_total_rate(w, d)
    if back >= 12:
        later = H._months_back(LAST, back - 12)                                                             # the month a year on has this one as its base
        _fix_total_rate(w, later)
    return w


def test_the_all_items_index_must_follow_its_parts_and_weights_within_half_a_hundredth_of_a_point():
    for back in (0, 11, 23):
        month = H._label(H._months_back(LAST, back))
        for off in (0.049, -0.049):
            assert _err(_total_off_by(off, back)) is None, (back, off)
        for off in (0.06, -0.06):
            assert _err(_total_off_by(off, back)) == f"the all-items index in {month} is {off:+.2f} points from what its five parts and their weights give, more than 0.05", (back, off)
    assert _err(_total_off_by(1.0, 24)) is None                                                             # a month before the window: its own identity is not looked at


def test_a_part_with_a_wrong_index_breaks_the_identity_in_proportion_to_its_weight():
    w = _world(growth=DRIFT)
    w[2]["NRGY00"][LAST] *= 1.01                                                                            # energy 1% too high: 0.09 x 1.105 x 1% x about 106 = 0.1 index points on the all-items index
    w[0]["NRGY00"][LAST] = 100 * (w[2]["NRGY00"][LAST] / w[2]["NRGY00"][H._months_back(LAST, 12)] - 1)
    assert re.fullmatch(r"the all-items index in 2026-10 is -0\.1\d points from what its five parts and their weights give, more than 0\.05", _err(w))


def test_the_identity_uses_the_weights_of_the_year_of_the_month_and_the_december_before():
    w = _world(growth=DRIFT)
    w[4]["NRGY00"][2025], w[4]["SERV00"][2025] = w[4]["NRGY00"][2025] + 60.0, w[4]["SERV00"][2025] - 60.0      # other 2025 weights, still adding up to 1000: the 2025 months no longer follow
    assert re.match(r"the all-items index in 2025-\d\d is", _err(w))
    w = _world(growth=DRIFT)
    w[4]["NRGY00"][2026], w[4]["SERV00"][2026] = w[4]["NRGY00"][2026] + 60.0, w[4]["SERV00"][2026] - 60.0
    assert re.match(r"the all-items index in 2026-\d\d is", _err(w))
    w = _world(growth=DRIFT)
    w[4]["NRGY00"][2024], w[4]["SERV00"][2024] = w[4]["NRGY00"][2024] + 60.0, w[4]["SERV00"][2024] - 60.0
    assert re.match(r"the all-items index in 2024-\d\d is", _err(w))
    w = _world(growth=DRIFT)
    for m in range(1, 11):
        d = date(2026, m, 1)
        w[2][H.TOTAL][d] *= 1.002                                                                           # the 2026 all-items indices 0.2% high, the published rates kept in line
        _fix_total_rate(w, d)
    assert re.fullmatch(r"the all-items index in 2026-01 is \+0\.2\d points from what its five parts and their weights give, more than 0\.05", _err(w))      # January is the first month off; 2025 still follows its parts


def test_the_published_rate_must_match_the_rate_the_index_gives_within_a_tenth_of_a_point():
    for sid in H.INDEX_IDS:
        for off in (0.09, -0.09):
            w = _world(growth=DRIFT)
            w[0][sid][LAST] += off
            assert _err(w) is None, (sid, off)
        for off in (0.11, -0.11):
            w = _world(growth=DRIFT)
            w[0][sid][LAST] += off
            assert _err(w) == f"the published annual rate of {H.NAMES[sid]} in 2026-10 is 0.11 points away from the rate the index gives, more than 0.1", (sid, off)
    w = _world(growth=DRIFT)
    w[0]["SERV00"][H._months_back(LAST, 23)] += 0.2
    assert _err(w) == "the published annual rate of services in 2024-11 is 0.20 points away from the rate the index gives, more than 0.1"
    w = _world(growth=DRIFT)
    w[0]["SERV00"][H._months_back(LAST, 24)] += 0.2
    assert _err(w) is None


def test_the_largest_gaps_of_the_window_are_reported_with_their_month_not_the_last_one():
    def with_offsets(*pairs):
        w = _world(growth=DRIFT)
        for back, off in pairs:
            d = H._months_back(LAST, back)
            w[2][H.TOTAL][d] += off
            _fix_total_rate(w, d)
        return w
    detail = _run(with_offsets((5, 0.033), (3, 0.031), (0, 0.02)))["detail"]
    assert detail["largest_index_gap"] == 0.033 and detail["largest_index_gap_month"] == "2026-05"           # the largest, not the newest and not the first listed
    detail = _run(with_offsets((5, 0.02), (0, 0.033)))["detail"]
    assert detail["largest_index_gap"] == 0.033 and detail["largest_index_gap_month"] == "2026-10"
    d0 = _run(_world(growth=DRIFT))["detail"]
    assert d0["largest_index_gap"] == 0.0 and d0["largest_index_gap_month"] is None and d0["largest_rate_gap_points"] == 0.0
    w = _world(growth=DRIFT)
    w[0]["FOODUN"][H._months_back(LAST, 7)] += 0.07
    w[0]["SERV00"][H._months_back(LAST, 2)] -= 0.05
    assert _run(w)["detail"]["largest_rate_gap_points"] == 0.07


def test_the_contributions_are_shown_only_when_they_agree_with_the_headline(monkeypatch):
    s = _real_until(date(2026, 10, 1), TODAY)
    assert s["contributions"]["shown"] is True and s["contributions"]["gap_points"] == 0.03                  # 4.0306 against 4.0: 0.0306 points
    monkeypatch.setattr(H, "CONTRIBUTION_TOLERANCE", 0.03)
    hidden = _real_until(date(2026, 10, 1), TODAY)
    assert hidden["contributions"]["shown"] is False and all(p["points"] is None for p in hidden["parts"]) and hidden["contributions"]["sum_points"] == 4.03
    monkeypatch.setattr(H, "CONTRIBUTION_TOLERANCE", 0.031)
    assert _real_until(date(2026, 10, 1), TODAY)["contributions"]["shown"] is True
    monkeypatch.setattr(H, "CONTRIBUTION_TOLERANCE", 0.05)                                                  # December 2025: the parts add up to 0.06 points UNDER the headline
    low = _real_until(date(2025, 12, 1))
    assert low["contributions"]["gap_points"] == -0.06 and low["contributions"]["shown"] is False
    monkeypatch.setattr(H, "CONTRIBUTION_TOLERANCE", 0.07)
    assert _real_until(date(2025, 12, 1))["contributions"]["shown"] is True
    monkeypatch.undo()
    assert H.CONTRIBUTION_TOLERANCE == 0.3
    march = _real_until(date(2022, 3, 1))                                                                   # energy +44.3%: the parts add up to 7.915 against 7.4
    assert march["headline"]["rate_pct"] == 7.4 and march["contributions"]["shown"] is False and march["contributions"]["gap_points"] == 0.51 and all(p["points"] is None for p in march["parts"])
    assert _real_until(date(2023, 10, 1))["contributions"]["shown"] is False                                # 3.271 against 2.9: 0.371 points
    assert _real_until(date(2022, 10, 1))["contributions"]["shown"] is True                                 # 10.685 against 10.6
    assert [(c, _real_until(c)["contributions"]["gap_points"], _real_until(c)["contributions"]["shown"]) for c in (date(2023, 11, 1), date(2022, 2, 1), date(2022, 4, 1))] == [(date(2023, 11, 1), 0.28, True), (date(2022, 2, 1), 0.33, False), (date(2022, 4, 1), 0.31, False)]      # either side of 0.3


def test_the_real_months_since_2015_are_never_refused_and_the_shocks_read_as_they_were():
    rates = _real()[0]
    cuts = [m for m in sorted(rates[H.TOTAL]) if m >= date(2015, 1, 1)]
    for cut in cuts:                                                                                        # the card would never have gone dark in 142 real months
        assert _real_until(cut)["available"], cut
    assert len(cuts) == 142
    for cut, head, energy, core in ((date(2020, 9, 1), -0.3, -8.2, 0.2), (date(2022, 3, 1), 7.4, 44.3, 3.0), (date(2022, 10, 1), 10.6, 41.5, 5.0), (date(2023, 10, 1), 2.9, -11.2, 4.2)):
        s = _real_until(cut)
        assert (s["headline"]["rate_pct"], s["parts"][3]["rate_pct"], s["headline"]["core_rate_pct"]) == (head, energy, core), cut


def test_the_december_base_is_asked_for_even_when_no_checked_month_is_a_year_after_it(monkeypatch):
    monkeypatch.setattr(H, "CHECK_MONTHS", 6)                                                               # May to October 2026: their base, December 2025, is neither a checked month nor a year before one
    w = _world()
    assert _run(w)["detail"]["months_checked"] == 6
    del w[2][H.TOTAL][date(2025, 12, 1)]
    with pytest.raises(ValueError, match="the index of all items is missing for 2025-12"):
        _run(w)


def test_the_index_range_is_checked_in_every_month_of_the_window():
    w = _world()
    w[2]["NRGY00"][H._months_back(LAST, 10)] = 300.0
    assert _err(w) == "the index of energy is outside the plausible range"


def test_two_equal_index_gaps_name_the_earlier_month_and_a_negative_gap_counts_by_its_size():
    def detail(*pairs):
        w = _world()                                                                                        # every index 100: the same sum for every month of a year, so equal edits give exactly equal gaps
        for back, off in pairs:
            d = H._months_back(LAST, back)
            w[2][H.TOTAL][d] += off
            _fix_total_rate(w, d)
        return _run(w)["detail"]
    d = detail((5, 0.03), (3, 0.03))
    assert d["largest_index_gap"] == 0.03 and d["largest_index_gap_month"] == "2026-05"
    d = detail((5, -0.04), (0, 0.02))
    assert d["largest_index_gap"] == 0.04 and d["largest_index_gap_month"] == "2026-05"


def test_rates_and_points_are_shown_to_one_decimal_even_when_the_source_gives_more():
    w = _world(growth=DRIFT, n_months=60)
    s = _run(w)
    rates = w[0]
    assert s["headline"]["rate_pct"] == round(rates[H.TOTAL][LAST], 1) and s["headline"]["core_rate_pct"] == round(rates[H.CORE][LAST], 1)
    assert s["headline"]["change_1m_points"] == round(rates[H.TOTAL][LAST] - rates[H.TOTAL][H._months_back(LAST, 1)], 1)
    assert s["headline"]["change_3m_points"] == round(rates[H.TOTAL][LAST] - rates[H.TOTAL][H._months_back(LAST, 3)], 1)
    assert [p["rate_pct"] for p in s["parts"]] == [round(rates[sid][LAST], 1) for sid in H.PARTS]
    assert s["history"][-1]["rate_pct"] == round(rates[H.TOTAL][LAST], 1)
    window = [rates[H.TOTAL][H._months_back(LAST, i)] for i in range(60)]
    assert s["range"]["lowest"]["pct"] == round(min(window), 1) and s["range"]["highest"]["pct"] == round(max(window), 1)
    assert s["headline"]["rate_pct"] != round(rates[H.TOTAL][LAST], 2) and s["headline"]["change_3m_points"] != round(rates[H.TOTAL][LAST] - rates[H.TOTAL][H._months_back(LAST, 3)], 2)       # the world's rates really do have more decimals


def test_the_limits_and_tolerances_are_the_ones_set_from_the_real_record():
    assert H.RATE_LIMITS == RATE_LIMITS and H.MONTH_MOVE == MONTH_MOVE and H.INDEX_LIMITS == INDEX_LIMITS
    assert (H.RATE_TOLERANCE, H.BETWEEN_TOLERANCE, H.INDEX_TOLERANCE, H.WEIGHT_TOLERANCE, H.CONTRIBUTION_TOLERANCE) == (0.1, 0.1, 0.05, 0.05, 0.3)
    assert (H.CHECK_MONTHS, H.HISTORY_MONTHS, H.RANGE_WINDOW, H.OVERDUE_AFTER_DAYS) == (24, 60, 120, 50)
    assert (H.RATE_LAST_N, H.INDEX_LAST_N, H.WEIGHT_LAST_N) == (121, 40, 4)


def test_the_parts_the_card_needs_are_asked_for_and_the_checks_are_labelled_for_what_they_are():
    assert set(H.RATE_IDS) == {"000000", "FOODPR", "FOODUN", "IGXE00", "NRGY00", "SERV00", "XEF000"} and set(H.INDEX_IDS) == set(H.WEIGHT_IDS) == {"000000", "FOODPR", "FOODUN", "IGXE00", "NRGY00", "SERV00"}
    assert "Eurostat's own arithmetic" in H.__doc__ and "not that the figures are right" in H.__doc__ and "311 real months" in H.__doc__ and "Two checks that are not" in H.__doc__
    assert [k.rsplit(".", 1)[1] for k in (H.RATE_KEY, H.INDEX_KEY, H.WEIGHT_KEY)] == ["ANR", "INX", "INW"] and all("+" in k for k in (H.RATE_KEY, H.INDEX_KEY, H.WEIGHT_KEY))


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    assert list(_run(_world())["checks"]) == ["units_ok", "months_in_a_row", "range_ok", "monthly_move_ok", "weights_ok", "headline_between_parts_ok", "core_between_ok", "index_follows_parts_ok", "rate_matches_index_ok"]
    w = _world(growth=DRIFT)
    w[0]["NRGY00"][LAST] = 95.0
    w[4]["SERV00"][2026] += 5.0
    assert _err(w).startswith("the annual rate of energy")                                                  # a rate out of range is stopped before the weights are read
    w = _world(growth=DRIFT)
    w[4]["SERV00"][2026] += 5.0
    w[0][H.TOTAL][LAST] = 4.0
    assert _err(w).startswith("the basket weights of 2026")                                                 # the weights come before the headline and the identity
    w = _world(growth=DRIFT)
    w[0][H.TOTAL][LAST] += 30.0
    w[0]["SERV00"][LAST] += 0.5
    assert _err(w).startswith("the annual rate of all items")


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_month_are_an_error():
    head = "KEY,ICP_ITEM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
    ok = "HICP.M.U2.N.000000.4D0.ANR"
    text = head + f"{ok},000000,2026-08,3.2,A,PCCH,0\n{ok},000000,2026-09,,A,PCCH,0\n{ok},000000,2026-10,n/a,E,PCCH,0\n{ok},000000,2026-W40,1,A,PCCH,0\nOTHER.KEY,000000,2026-06,5,A,PCCH,0\n{ok},000000,2026-07-15,2,A,PCCH,0\n{ok},000000,2026-05,nan,A,PCCH,0\n{ok},000000,2026-04,inf,A,PCCH,0\n{ok},NRGY00,2026-08,9,A,PCCH,0\nHICP.M.U2.N.NRGY00.4D0.ANR,NRGY00,2026-08,9,A,PCCH,0\n"
    v, units, status = H.parse(text, ("000000",), "M", "ANR")
    assert v == {"000000": {date(2026, 8, 1): 3.2}} and units == {"000000": ("PCCH", "0")} and status == {"000000": "A"}       # a day-form date, nan, inf, another series and another key are all left out
    other = head + f"HICP.M.U2.N.000000.4D0.CTR,000000,2026-08,3.1,A,PCCH,0\n{ok},000000,2026-08,3.2,A,PCCH,0\nHICP.M.U3.N.000000.4D0.ANR,000000,2026-08,9.9,A,PCCH,0\nHICP.M.U2.Y.000000.4D0.ANR,000000,2026-08,8.8,A,PCCH,0\nHICP.M.U2.N.000000.4D1.ANR,000000,2026-08,7.7,A,PCCH,0\n"
    assert H.parse(other, ("000000",), "M", "ANR")[0] == {"000000": {date(2026, 8, 1): 3.2}}                # only the exact series: not the constant-tax rate, another area, the adjusted one or another provider
    padded = head + f"{ok},000000,2026-09,3,E, PCCH , 0 \n"
    assert H.parse(padded, ("000000",), "M", "ANR")[1] == {"000000": ("PCCH", "0")}                          # spaces around a unit are not a different unit
    two = head + f"{ok},000000,2026-07,1,A,PCCH,0\n{ok},000000,2026-09,3,E,PCCH,0\n{ok},000000,2026-08,2,A,PCCH,0\n"
    assert H.parse(two, ("000000",), "M", "ANR")[2] == {"000000": "E"}                                       # the status is the newest month's, whatever the order of the rows
    with pytest.raises(ValueError, match="000000 has two values for 2026-08"):
        H.parse(text + f"{ok},000000,2026-08,1,A,PCCH,0\n", ("000000",), "M", "ANR")
    with pytest.raises(ValueError, match="no values for FOODPR"):
        H.parse(text, ("000000", "FOODPR"), "M", "ANR")
    annual = head + "HICP.A.U2.N.NRGY00.4D0.INW,NRGY00,2026,90.26,A,PM,0\nHICP.A.U2.N.NRGY00.4D0.INW,NRGY00,2025,93.98,A,PM,0\nHICP.A.U2.N.NRGY00.4D0.INW,NRGY00,2026-01,5,A,PM,0\nHICP.A.U2.N.NRGY00.4D0.INW,NRGY00,26,5,A,PM,0\n"
    assert H.parse(annual, ("NRGY00",), "A", "INW")[0] == {"NRGY00": {2026: 90.26, 2025: 93.98}}            # a year is exactly four digits
    with pytest.raises(ValueError, match="NRGY00 has two values for 2026"):
        H.parse(annual + "HICP.A.U2.N.NRGY00.4D0.INW,NRGY00,2026,1,A,PM,0\n", ("NRGY00",), "A", "INW")


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    path = req.url.path
    return httpx.Response(200, text=F["rates"] if path.endswith(H.RATE_KEY) else F["indices"] if path.endswith(H.INDEX_KEY) else F["weights"])


def test_overview_fetches_three_requests_and_caches():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = H.EuroInflation(client=_transport(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["headline"]["rate_pct"] == 4.0 and len(seen) == 3 and r["source"].startswith("Eurostat")
    assert {req.url.path: req.url.params["lastNObservations"] for req in seen} == {"/service/data/HICP/M.U2.N.000000+FOODPR+FOODUN+IGXE00+NRGY00+SERV00+XEF000.4D0.ANR": "121",
                                                                                   "/service/data/HICP/M.U2.N.000000+FOODPR+FOODUN+IGXE00+NRGY00+SERV00.4D0.INX": "40",
                                                                                   "/service/data/HICP/A.U2.N.000000+FOODPR+FOODUN+IGXE00+NRGY00+SERV00.4D0.INW": "4"}
    assert all(req.url.params["format"] == "csvdata" for req in seen) and all(req.headers["user-agent"] == "ATLAS research terminal" for req in seen)
    assert all("%2B" not in str(req.url) and "+" in str(req.url) for req in seen)                           # the + that joins the series of one key must reach the ECB as it is
    asyncio.run(svc.overview(NOW))
    assert len(seen) == 3


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(H.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = H.EuroInflation(client=_transport(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 3
    clock["t"] += H.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3                                                                                     # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 6                              # two minutes on it asks again
    clock["t"] += H.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 9 and (H.FAIL_TTL, H.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(H.EuroInflation(client=_transport(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "headline" not in r
    bad = F["rates"].replace("NRGY00,2026-10,20.8", "NRGY00,2026-10,208")                                    # a decimal slip in the newest energy rate: a check failing shows nothing either
    assert bad != F["rates"]
    r = asyncio.run(H.EuroInflation(client=_transport(lambda req: httpx.Response(200, text=bad if req.url.path.endswith(H.RATE_KEY) else F["indices"] if req.url.path.endswith(H.INDEX_KEY) else F["weights"]))).overview(NOW))
    assert r["available"] is False and "the annual rate of energy is +208.0% in 2026-10" in r["reason"] and "headline" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(H.EuroInflation(client=_transport(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The euro-area consumer prices could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(H.EuroInflation(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "headline" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-inflation")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
