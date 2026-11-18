"""Euro-area GDP (ECB Data Portal, MNA dataflow, the euro area of 21 countries `I10`, seasonally and calendar adjusted): parsed from real responses (fetched 2026-11-18 05:27 UTC: the provider's four requests with 45 quarters each; the whole record, 126 quarters from 1995-Q1 for ten series, was read to set the checks, see the module's docstring)."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import eurogdp as S
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_gdp.json").read_text())
TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
RE, BE = "2026-Q3", "2026-Q2"                                          # the newest quarter of real GDP and of the breakdown
IDS = ("gdp_nom", "gdp_real", "gdp_q", "gdp_y", "dd_nom", "dd_c", "ex_nom", "ex_c", "im_nom", "im_c")
REAL = ("gdp_real", "gdp_q", "gdp_y")
BREAK = ("gdp_nom", "dd_nom", "ex_nom", "im_nom", "dd_c", "ex_c", "im_c")
LEVEL, GROWTH, CONTRIB = ("EUR", "6"), ("EUR", "1"), ("EUR_R_B1GQ", "0")
UNITS = {"gdp_nom": LEVEL, "gdp_real": LEVEL, "gdp_q": GROWTH, "gdp_y": GROWTH, "dd_nom": LEVEL, "dd_c": CONTRIB, "ex_nom": LEVEL, "ex_c": CONTRIB, "im_nom": LEVEL, "im_c": CONTRIB}
NAMES = {"gdp_nom": "nominal GDP", "gdp_real": "real GDP", "gdp_q": "real GDP growth on the previous quarter", "gdp_y": "real GDP growth on the same quarter a year earlier",
         "dd_nom": "nominal domestic demand", "dd_c": "the contribution of domestic demand to growth", "ex_nom": "nominal exports", "ex_c": "the contribution of exports to growth",
         "im_nom": "nominal imports", "im_c": "the contribution of imports to growth"}
# the limits set from the real record, spelled out here so that a changed limit fails a test instead of moving the test with it
LIMITS = {"gdp_q": (-15.0, 15.0), "gdp_y": (-20.0, 20.0), "gdp_real": (1000000.0, 6000000.0), "gdp_nom": (1000000.0, 10000000.0), "dd_nom": (1000000.0, 10000000.0),
          "ex_nom": (200000.0, 6000000.0), "im_nom": (200000.0, 6000000.0), "dd_c": (-15.0, 15.0), "ex_c": (-12.0, 12.0), "im_c": (-12.0, 12.0)}
GROWTH_MSG = "is not the change of the real GDP level in"
NOMINAL_MSG = "nominal GDP is not domestic demand plus exports minus imports in"
CONTRIB_MSG = "the contributions of domestic demand, exports and imports do not add up to real GDP growth in"


def _i(q):
    return int(q[:4]) * 4 + int(q[6]) - 1


def _l(i):
    return f"{i // 4}-Q{i % 4 + 1}"


def _world(real_end=RE, break_end=BE, extra=0, status=None, growth=1.0025):
    """Ten series for the 45 quarters (plus `extra` older ones) ending on each group's newest quarter, where the ECB's three identities hold by construction and every other check passes: a real level growing by the factor `growth` a quarter (0.25% by default), nominal domestic demand, exports (with 123.456 millions on top) and imports growing by fixed steps, nominal GDP their combination, contributions of 0.2575 for exports and -0.1234 for imports and domestic demand as the rest."""
    n = 45 + extra
    re_i, be_i = _i(real_end), _i(break_end)
    first = re_i - n - 3                                                 # four quarters before the oldest real quarter, for its year-on-year growth
    level = {i: 3000000.0 * growth ** (i - first) for i in range(first, re_i + 1)}
    v = {s: {} for s in IDS}
    for i in range(re_i - n + 1, re_i + 1):
        q = _l(i)
        v["gdp_real"][q] = level[i]
        v["gdp_q"][q] = 100 * (level[i] / level[i - 1] - 1)
        v["gdp_y"][q] = 100 * (level[i] / level[i - 4] - 1)
    for i in range(be_i - n + 1, be_i + 1):
        q, j = _l(i), i - (be_i - n + 1)
        dd, ex, im = 3000000.0 + 10000.0 * j, 1600000.0 + 5000.0 * j + 123.456, 1500000.0 + 4000.0 * j
        v["dd_nom"][q], v["ex_nom"][q], v["im_nom"][q] = dd, ex, im
        v["gdp_nom"][q] = dd + ex - im
        v["ex_c"][q], v["im_c"][q] = 0.2575, -0.1234
        v["dd_c"][q] = v["gdp_q"][q] - 0.2575 + 0.1234 if q in v["gdp_q"] else 0.0
    return v, dict(UNITS), {"gdp_q": "A"} if status is None else status


def _exact_world():
    """A world whose newest quarter (real GDP and the breakdown end on it) has binary-exact figures (growth 6.25, contributions 6.0, 0.5 and -0.25), so that a gap of exactly a tolerance can be made."""
    w = _world(RE, RE)
    v = w[0]
    prev = _l(_i(RE) - 1)
    v["gdp_real"][RE] = v["gdp_real"][prev] * 1.0625
    v["gdp_q"][RE] = 6.25
    v["gdp_y"][RE] = 100 * (v["gdp_real"][RE] / v["gdp_real"][_l(_i(RE) - 4)] - 1)
    v["dd_c"][RE], v["ex_c"][RE], v["im_c"][RE] = 6.0, 0.5, -0.25
    return w


def _real():
    v = {sid: dict(zip(d["quarters"], d["values"])) for sid, d in F["series"].items()}
    return v, {sid: tuple(d["unit"]) for sid, d in F["series"].items()}, {"gdp_q": F["series"]["gdp_q"]["status"][-1]}


def _run(world, today=TODAY):
    return S.summarize(*world, today)


def _err(world, today=TODAY):
    """The refusal's text, or None when the world passes every check."""
    try:
        _run(world, today)
    except ValueError as e:
        return str(e)
    return None


def test_the_real_latest_growth_ten_year_comparison_recent_quarters_breakdown_and_checks_by_hand():
    r = _run(_real())
    assert r["available"] is True and r["quarter"] == "2026-Q3" and r["age_days"] == 49 and r["freshness"] == "CURRENT" and r["provisional"] is False    # 2026-09-30 to 2026-11-18 is 49 days
    assert r["growth"] == {"quarter": "2026-Q3", "quarter_on_quarter": 0.41, "year_on_year": 1.3, "previous_quarter": "2026-Q2", "year_earlier": "2025-Q3"}
    assert [(x["quarter"], x["quarter_on_quarter"], x["year_on_year"]) for x in r["recent"]] == [("2026-Q3", 0.41, 1.3), ("2026-Q2", 0.64, 1.2), ("2026-Q1", 0.0, 0.58), ("2025-Q4", 0.23, 1.07), ("2025-Q3", 0.32, 1.14), ("2025-Q2", 0.03, 1.38)]
    assert r["window"] == {"quarters": 40, "from": "2016-Q4", "years": 10, "median": 0.44, "lowest": {"value": -11.15, "quarter": "2020-Q2"}, "highest": {"value": 11.54, "quarter": "2020-Q3"}, "share_lower_pct": 48}    # 19 of 40 quarters were lower: 47.5%
    assert r["breakdown"] == {"quarter": "2026-Q2", "gdp": 4125.8, "domestic_demand": 3978.0, "exports": 2086.0, "imports": 1938.2, "net_trade": 147.8, "growth": 0.64,
                              "contributions": {"domestic_demand": -0.27, "exports": 1.7, "imports": -0.79, "net_trade": 0.91}}
    assert r["detail"] == {"quarters_checked": 45, "contribution_quarters_checked": 44, "largest_growth_gap": 0.0, "largest_nominal_gap": 1.3e-08, "largest_contribution_gap": 0.0}
    assert r["checks"] == {"units_ok": True, "quarters_in_a_row": True, "range_ok": True, "nominal_move_ok": True, "growth_follows_the_level_ok": True, "nominal_identity_ok": True, "contributions_add_up_ok": True}
    assert r["source"].startswith("European Central Bank") and r["url"] == "https://data-api.ecb.europa.eu/service/data/MNA/Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.G1"
    assert "not a market signal or a forecast" in r["note"] and "stopped at Q1 2026" in r["note"] and "about 45 days" in r["note"] and "about 65 days" in r["note"]


def test_the_real_record_by_plain_python_outside_the_module():
    s = F["series"]
    q, g = s["gdp_q"]["quarters"], s["gdp_q"]["values"]
    ten = g[-40:]
    assert (q[-40], q[-1]) == ("2016-Q4", "2026-Q3") and sum(1 for x in ten if x < g[-1]) == 19 and min(ten) == pytest.approx(-11.154725667811993) and max(ten) == pytest.approx(11.536554864687144)
    gaps = [abs(a - (b + c - d)) for a, b, c, d in zip(s["gdp_nom"]["values"], s["dd_nom"]["values"], s["ex_nom"]["values"], s["im_nom"]["values"])]
    assert max(gaps) == pytest.approx(1.30385160446167e-08) and len(gaps) == 45                  # the identity of the national accounts, to a hundredth of a billionth of a million euro
    n = s["gdp_nom"]["values"][-1]
    assert (round(n / 1000, 1), round(s["dd_nom"]["values"][-1] / 1000, 1), round((s["ex_nom"]["values"][-1] - s["im_nom"]["values"][-1]) / 1000, 1)) == (4125.8, 3978.0, 147.8)


def test_the_newest_value_is_provisional_only_when_the_source_says_so():
    for st, expected in (("A", False), ("", False), ("P", True), ("E", True), ("F", True)):
        assert _run(_world(status={"gdp_q": st}))["provisional"] is expected, st
    assert _run(_world(status={"gdp_q": "A", "gdp_y": "P", "gdp_nom": "P", "dd_c": "E"}))["provisional"] is False     # only the growth rate of the newest quarter counts


def test_overdue_after_135_days_from_the_end_of_the_newest_real_quarter():
    end = date(2026, 9, 30)
    r = _run(_world(), end + timedelta(days=135))
    assert (r["age_days"], r["freshness"]) == (135, "CURRENT")
    r = _run(_world(), end + timedelta(days=136))
    assert (r["age_days"], r["freshness"]) == (136, "OVERDUE")
    assert _run(_world(), end)["age_days"] == 0


def test_each_quarter_ends_on_its_own_last_day():
    for real_end, break_end, today, age in (("2026-Q1", "2025-Q4", date(2026, 4, 10), 10), ("2026-Q2", "2026-Q1", date(2026, 7, 5), 5), ("2026-Q3", "2026-Q2", date(2026, 10, 2), 2), ("2025-Q4", "2025-Q3", date(2026, 1, 4), 4)):
        r = _run(_world(real_end, break_end), today)
        assert r["quarter"] == real_end and r["age_days"] == age and r["breakdown"]["quarter"] == break_end, real_end


def _g(n, last="2026-Q3", f=lambda k: 0.1 * k):
    """`n` quarters of growth ending on `last`: the quarter k steps back from the end is f(n - 1 - k) ... oldest first."""
    return {_l(_i(last) - n + 1 + k): f(k) for k in range(n)}


def test_the_ten_year_comparison_needs_36_quarters_and_counts_only_the_40_newest():
    assert S._stats(_g(35), "2026-Q3") is None
    r = S._stats(_g(36), "2026-Q3")
    assert r is not None and r["quarters"] == 36 and r["from"] == "2017-Q4"
    r = S._stats({**_g(45), "2015-Q3": -50.0, "2016-Q3": -40.0}, "2026-Q3")                               # the two quarters before 2016-Q4 are older than ten years: not counted
    assert r["quarters"] == 40 and r["from"] == "2016-Q4" and r["lowest"] == {"value": 0.5, "quarter": "2016-Q4"}


def test_the_share_of_lower_quarters_counts_only_quarters_strictly_below_and_is_a_whole_percent():
    g = _g(40, f=lambda k: 1.0)
    assert S._stats(g, "2026-Q3")["share_lower_pct"] == 0                                                  # all tied with the newest: none is lower
    g = _g(40, f=lambda k: 1.0 if k < 39 else 2.0)
    assert S._stats(g, "2026-Q3")["share_lower_pct"] == 98                                                 # 39 of 40 are lower: 97.5, shown as 98
    g = _g(40, f=lambda k: 0.5 if k < 3 else 1.0)
    assert S._stats(g, "2026-Q3")["share_lower_pct"] == 8                                                  # 3 of 40 are lower: 7.5, shown as 8
    g = _g(40, f=lambda k: 0.5 if k < 1 else 1.0)
    assert S._stats(g, "2026-Q3")["share_lower_pct"] == 2                                                  # 1 of 40: 2.5, shown as 2 (the even one)


def test_median_lowest_and_highest_with_their_quarters_and_two_decimals():
    g = _g(40, f=lambda k: 0.0127 * k)                                                                      # rising: the median is the mean of the 20th and 21st value, 19.5 * 0.0127 = 0.24765
    r = S._stats(g, "2026-Q3")
    assert r["median"] == 0.25 and r["lowest"] == {"value": 0.0, "quarter": "2016-Q4"} and r["highest"] == {"value": 0.5, "quarter": "2026-Q3"}      # 39 * 0.0127 = 0.4953
    g = _g(40, f=lambda k: -3.14159 if k in (5, 9) else 2.71828 if k in (6, 30) else 0.0)
    r = S._stats(g, "2026-Q3")
    assert r["lowest"] == {"value": -3.14, "quarter": "2018-Q1"} and r["highest"] == {"value": 2.72, "quarter": "2018-Q2"}     # a tie names the earlier quarter; values are shown to two decimals


def test_every_figure_is_shown_to_the_decimals_the_card_prints():
    r = _run(_world(growth=1.00143))                                                                         # growth 0.143 on the quarter and 0.5732 on the year: the decimals differ between one, two and three
    assert r["growth"]["quarter_on_quarter"] == 0.14 and r["growth"]["year_on_year"] == 0.57
    assert [(x["quarter_on_quarter"], x["year_on_year"]) for x in r["recent"]] == [(0.14, 0.57)] * 6
    assert r["breakdown"] == {"quarter": BE, "gdp": 3584.1, "domestic_demand": 3440.0, "exports": 1820.1, "imports": 1676.0, "net_trade": 144.1, "growth": 0.14,
                              "contributions": {"domestic_demand": 0.01, "exports": 0.26, "imports": -0.12, "net_trade": 0.13}}      # GDP 3,584,123.456 millions, exports 1,820,123.456, net trade 144.123456 billions; contributions 0.0089, 0.2575, -0.1234 and 0.1341


def test_the_number_formats_of_the_refusal_messages():
    assert S._fmt(1000000.0) == "1,000,000.0000" and S._fmt(-0.5) == "-0.5000" and S._fmt(15.00004) == "15.0000" and S._fmt(1234.56789) == "1,234.5679"
    assert (S._lim(1000000.0), S._lim(-2000.0), S._lim(1000.0), S._lim(999.0), S._lim(15.0), S._lim(-12.0), S._lim(0.5), S._lim(-0.25), S._lim(1500.5)) == ("1,000,000", "-2,000", "1,000", "999", "15", "-12", "0.5", "-0.25", "1500.5")


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    for sid in IDS:
        for wrong in (("PC", UNITS[sid][1]), (UNITS[sid][0], "3"), (UNITS[sid][0], "")):
            w = _world()
            w[1][sid] = wrong
            assert _err(w) == f"the ECB reports {NAMES[sid]} in other units than the card assumes", (sid, wrong)
    assert _err(_world()) is None


def test_series_ending_on_different_quarters_are_refused_and_so_are_real_gdp_and_its_breakdown_a_quarter_too_far_apart():
    for sid in REAL:
        w = _world()
        w[0][sid].pop(RE)
        assert _err(w) == "the real GDP series end on different quarters", sid
    for sid in BREAK:
        w = _world()
        w[0][sid].pop(BE)
        assert _err(w) == "the GDP breakdown series end on different quarters", sid
    for real_end, break_end in (("2026-Q3", "2026-Q3"), ("2026-Q3", "2026-Q2")):                            # the same quarter, or real GDP a quarter ahead: both are normal
        assert _err(_world(real_end, break_end)) is None, (real_end, break_end)
    for real_end, break_end in (("2026-Q4", "2026-Q2"), ("2026-Q2", "2026-Q3"), ("2027-Q3", "2026-Q2")):
        assert _err(_world(real_end, break_end)) == "real GDP and its breakdown end more than a quarter apart", (real_end, break_end)


def test_a_quarter_missing_in_the_last_45_is_refused_and_an_older_one_is_not():
    for sid in IDS:
        end = _i(RE) if sid in REAL else _i(BE)
        for back in (1, 22, 44):
            w = _world()
            q = _l(end - back)
            w[0][sid].pop(q)
            assert _err(w) == f"{NAMES[sid]} is missing for {q}", (sid, back)
        w = _world(extra=1)                                                                                 # 46 quarters: the oldest is outside the 45 that are looked at
        w[0][sid].pop(_l(end - 45))
        assert _err(w) is None, sid
        w = _world(extra=1)
        w[0][sid].pop(_l(end - 44))
        assert _err(w) == f"{NAMES[sid]} is missing for {_l(end - 44)}", sid


def _fmt(x):
    return f"{x:,.4f}"


def _lim(x):
    return f"{x:,.0f}" if x == int(x) and abs(x) >= 1000 else f"{x:g}"


FOLLOW = {"gdp_q": f"{NAMES['gdp_q']} {GROWTH_MSG} {RE}", "gdp_y": f"{NAMES['gdp_y']} {GROWTH_MSG} {RE}", "gdp_real": f"{NAMES['gdp_q']} {GROWTH_MSG} {RE}",
          "gdp_nom": f"nominal GDP moved by", "dd_nom": f"{NOMINAL_MSG} {BE}", "ex_nom": f"{NOMINAL_MSG} {BE}", "im_nom": f"{NOMINAL_MSG} {BE}",
          "dd_c": f"{CONTRIB_MSG} {BE}", "ex_c": f"{CONTRIB_MSG} {BE}", "im_c": f"{CONTRIB_MSG} {BE}"}


def test_each_figure_must_lie_inside_its_range_in_every_quarter_of_its_window():
    for sid, (lo, hi) in LIMITS.items():
        q = RE if sid in REAL else BE
        for edge, outside in ((lo, lo - 0.0001), (hi, hi + 0.0001)):
            w = _world()
            w[0][sid][q] = edge
            e = _err(w)
            assert e is not None and e.startswith(FOLLOW[sid]), (sid, edge, e)                                # at the limit it passes the range check; the check it no longer follows speaks
            w = _world()
            w[0][sid][q] = outside
            assert _err(w) == f"{NAMES[sid]} is {_fmt(outside)} in {q}, outside {_lim(lo)} to {_lim(hi)}", (sid, outside)
    w = _world()
    w[0]["gdp_q"][_l(_i(RE) - 20)] = 15.0001                                                                 # not only the newest quarter
    assert _err(w) == f"{NAMES['gdp_q']} is 15.0001 in {_l(_i(RE) - 20)}, outside -15 to 15"


def _step(w, ratio, back=0):
    """Nominal GDP in the quarter `back` before the newest breakdown quarter becomes `ratio` times the quarter before it; domestic demand takes the difference, so that the identity still holds."""
    v = w[0]
    q = _l(_i(BE) - back)
    prev = _l(_i(BE) - back - 1)
    new = v["gdp_nom"][prev] * ratio
    v["gdp_nom"][q] = new
    v["dd_nom"][q] = new - v["ex_nom"][q] + v["im_nom"][q]
    return q


def test_nominal_gdp_may_move_by_up_to_15_percent_in_a_quarter():
    for ratio in (1.1499, 0.8501):
        w = _world()
        _step(w, ratio)
        assert _err(w) is None, ratio
    w = _world()
    q = _step(w, 1.1501)
    assert _err(w) == f"nominal GDP moved by +15.01% in {q}, outside -15% to +15%"
    w = _world()
    q = _step(w, 0.8499)
    assert _err(w) == f"nominal GDP moved by -15.01% in {q}, outside -15% to +15%"
    w = _world()
    q = _step(w, 1.2, back=20)                                                                               # an older quarter is looked at too
    assert _err(w) == f"nominal GDP moved by +20.00% in {q}, outside -15% to +15%"


def test_the_growth_rates_must_follow_the_real_level_within_a_billionth_over_the_whole_window():
    tol = 2 ** -30
    for sid in ("gdp_q", "gdp_y"):
        for sign in (1, -1):
            w = _world()
            w[0][sid][RE] += sign * tol
            r = _run(w)
            assert r["detail"]["largest_growth_gap"] == 9.31e-10, (sid, sign)                                  # exactly the tolerance is allowed, and reported as a size
            w = _world()
            w[0][sid][RE] += sign * 2 * tol
            assert _err(w) == f"{NAMES[sid]} {GROWTH_MSG} {RE} (off by {sign * 2 * tol:+.9f})", (sid, sign)
    w = _world()
    q = _l(_i(RE) - 10)
    w[0]["gdp_q"][q] += 0.01
    assert _err(w) == f"{NAMES['gdp_q']} {GROWTH_MSG} {q} (off by +0.010000000)"                             # an older quarter is looked at
    old = _l(_i(RE) - 44)                                                                                    # the oldest quarter has no quarter before it in the fetch, so only the contributions look at it
    w = _world()
    w[0]["gdp_q"][old] += 1.0
    w[0]["dd_c"][old] += 1.0
    assert _err(w) is None
    for back in range(41, 45):                                                                               # the year-on-year rate needs the level four quarters earlier: the oldest four have none
        w = _world()
        w[0]["gdp_y"][_l(_i(RE) - back)] += 1.0
        assert _err(w) is None, back
    w = _world()
    w[0]["gdp_y"][_l(_i(RE) - 40)] += 1.0
    assert _err(w) == f"{NAMES['gdp_y']} {GROWTH_MSG} {_l(_i(RE) - 40)} (off by +1.000000000)"


def test_nominal_gdp_must_be_domestic_demand_plus_exports_minus_imports_within_the_tolerance():
    for off, ok in ((2 ** -7, True), (2 ** -6, True), (-2 ** -6, True), (2 ** -6 + 2 ** -7, False), (-(2 ** -6 + 2 ** -7), False)):
        w = _world()
        w[0]["gdp_nom"][BE] += off
        if ok:
            assert _run(w)["detail"]["largest_nominal_gap"] == abs(off), off                                    # a gap of exactly 0.015625 (2 to the power -6) is allowed, and reported as a size
        else:
            assert _err(w) == f"{NOMINAL_MSG} {BE} (off by {off:+.4f} millions of euro)", off
    w = _world()
    q = _l(_i(BE) - 44)                                                                                      # the oldest quarter of the breakdown is looked at too
    w[0]["gdp_nom"][q] += 1.0
    assert _err(w) == f"{NOMINAL_MSG} {q} (off by +1.0000 millions of euro)"
    for sid in ("dd_nom", "ex_nom", "im_nom"):
        w = _world()
        w[0][sid][BE] += 1.0
        sign = "-" if sid != "im_nom" else "+"
        assert _err(w) == f"{NOMINAL_MSG} {BE} (off by {sign}1.0000 millions of euro)", sid


def test_the_contributions_must_add_up_to_real_gdp_growth_within_the_tolerance():
    for off, ok in ((2 ** -21, True), (2 ** -20, True), (-2 ** -20, True), (2 ** -19, False), (-2 ** -19, False)):
        w = _exact_world()
        w[0]["im_c"][RE] += off
        if ok:
            assert _run(w)["detail"]["largest_contribution_gap"] == {2 ** -21: 4.76837e-07, 2 ** -20: 9.53674e-07, -2 ** -20: 9.53674e-07}[off], off          # exactly 2 to the power -20 is allowed, and reported as a size
        else:
            assert _err(w) == f"{CONTRIB_MSG} {RE} (off by {off:+.6f} points)", off
    for sid in ("dd_c", "ex_c", "im_c"):
        w = _world()
        q = _l(_i(BE) - 10)                                                                                  # an older quarter is looked at too
        w[0][sid][q] += 0.01
        assert _err(w) == f"{CONTRIB_MSG} {q} (off by +0.010000 points)", sid
    w = _world(RE, BE)                                                                                       # real GDP a quarter ahead: the oldest breakdown quarter has no growth rate to compare with, so it is skipped
    oldest = _l(_i(BE) - 44)
    w[0]["dd_c"][oldest] = 5.0
    r = _run(w)
    assert r["detail"]["contribution_quarters_checked"] == 44
    w = _world(RE, RE)                                                                                       # the same quarter: all 45 are compared
    w[0]["dd_c"][_l(_i(RE) - 44)] = 5.0
    assert _err(w) == f"{CONTRIB_MSG} {_l(_i(RE) - 44)} (off by +4.884100 points)"
    assert _run(_world(RE, RE))["detail"]["contribution_quarters_checked"] == 45


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    w = _world()
    w[1]["gdp_nom"] = ("PC", "6")
    w[0]["gdp_y"].pop(RE)
    assert _err(w).startswith("the ECB reports nominal GDP in other units")                                  # the units before the end quarters
    w = _world()
    w[0]["gdp_y"].pop(RE)
    w[0]["im_c"].pop(BE)
    assert _err(w) == "the real GDP series end on different quarters"                                         # real before breakdown
    w = _world()
    w[0]["im_c"].pop(BE)
    w[0]["gdp_q"].pop(_l(_i(RE) - 5))
    assert _err(w) == "the GDP breakdown series end on different quarters"                                    # the end quarters before the holes
    w = _world("2026-Q4", "2026-Q2")
    w[0]["gdp_q"].pop(_l(_i("2026-Q4") - 5))
    assert _err(w).startswith("real GDP and its breakdown end more than a quarter apart")                      # a distance of two quarters before the holes
    w = _world()
    w[0]["gdp_real"].pop(_l(_i(RE) - 5))
    w[0]["gdp_q"][RE] = 50.0
    assert _err(w) == f"real GDP is missing for {_l(_i(RE) - 5)}"                                              # a hole before the ranges
    w = _world()
    w[0]["gdp_q"][RE] = 50.0
    w[0]["gdp_nom"][BE] *= 1.5
    assert _err(w).startswith("real GDP growth on the previous quarter is 50.0000")                            # the ranges before the nominal move
    w = _world()
    _step(w, 1.2)
    w[0]["gdp_q"][RE] += 0.1
    assert _err(w).startswith("nominal GDP moved by +20.00%")                                                  # the nominal move before the growth rates
    w = _world()
    w[0]["gdp_q"][RE] += 0.1
    w[0]["gdp_nom"][BE] += 1.0
    assert _err(w).startswith(f"{NAMES['gdp_q']} {GROWTH_MSG} {RE}")                                           # the growth rates before the nominal identity
    w = _world()
    w[0]["gdp_nom"][BE] += 1.0
    w[0]["ex_c"][BE] += 0.1
    assert _err(w).startswith(f"{NOMINAL_MSG} {BE}")                                                           # the nominal identity before the contributions
    w = _world()
    w[0]["ex_c"][BE] += 0.1
    assert _err(w).startswith(f"{CONTRIB_MSG} {BE}")


def test_the_real_record_passes_every_check_and_is_pinned():
    assert _err(_real()) is None
    v = _real()[0]
    q = sorted(v["gdp_nom"], key=_i)
    ch = [100 * (v["gdp_nom"][b] / v["gdp_nom"][a] - 1) for a, b in zip(q, q[1:])]
    assert (round(min(ch), 3), round(max(ch), 3)) == (-10.151, 10.393)                                         # the real nominal extremes in the fetched window are inside the bound of 15% (2020-Q2 and 2020-Q3)


def test_the_limits_and_tolerances_are_the_ones_set_from_the_real_record():
    assert S.LIMITS == LIMITS and S.NOMINAL_MOVE == (-15.0, 15.0)
    assert (S.NOMINAL_TOLERANCE, S.CONTRIBUTION_TOLERANCE, S.GROWTH_TOLERANCE) == (0.015625, 2 ** -20, 2 ** -30)
    assert (S.LAST_N, S.WINDOW_QUARTERS, S.MIN_WINDOW_QUARTERS, S.OVERDUE_AFTER_DAYS) == (45, 40, 36, 135)
    assert (S.TTL, S.FAIL_TTL) == (21600.0, 120.0)
    assert S.BASE == "https://data-api.ecb.europa.eu/service/data/MNA/" and S.NAMES == NAMES
    assert S.SERIES == {"gdp_nom": ("Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.V.N", LEVEL), "gdp_real": ("Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N", LEVEL), "gdp_q": ("Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.G1", GROWTH),
                        "gdp_y": ("Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY", GROWTH), "dd_nom": ("Q.Y.I10.W0.S1.S1.D.P3T5._Z._Z._Z.EUR.V.N", LEVEL), "dd_c": ("Q.Y.I10.W0.S1.S1.D.P3T5._Z._Z._Z.EUR_R_B1GQ.Y.GO1", CONTRIB),
                        "ex_nom": ("Q.Y.I10.W1.S1.S1.D.P6._Z._Z._Z.EUR.V.N", LEVEL), "ex_c": ("Q.Y.I10.W1.S1.S1.D.P6._Z._Z._Z.EUR_R_B1GQ.Y.GO1", CONTRIB), "im_nom": ("Q.Y.I10.W1.S1.S1.C.P7._Z._Z._Z.EUR.V.N", LEVEL),
                        "im_c": ("Q.Y.I10.W1.S1.S1.C.P7._Z._Z._Z.EUR_R_B1GQ.Y.GO1", CONTRIB)}
    assert S.REQUESTS == (("Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.V+LR.N+G1+GY", ("gdp_nom", "gdp_real", "gdp_q", "gdp_y")), ("Q.Y.I10.W0.S1.S1.D.P3T5._Z._Z._Z.EUR+EUR_R_B1GQ.V+Y.N+GO1", ("dd_nom", "dd_c")),
                          ("Q.Y.I10.W1.S1.S1.D.P6._Z._Z._Z.EUR+EUR_R_B1GQ.V+Y.N+GO1", ("ex_nom", "ex_c")), ("Q.Y.I10.W1.S1.S1.C.P7._Z._Z._Z.EUR+EUR_R_B1GQ.V+Y.N+GO1", ("im_nom", "im_c")))
    assert S.PAGE == "https://data-api.ecb.europa.eu/service/data/MNA/Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.G1"
    assert S.REAL == REAL and S.BREAK == BREAK


HEAD = "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT_MEASURE,UNIT_MULT\n"
OK = "MNA.Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.G1"


def test_the_real_layout_of_a_response_is_read():
    v, units, status = S.parse(F["raw_head"], ("gdp_q",))
    assert v == {"gdp_q": {"2015-Q3": 0.43440061808739383, "2015-Q4": 0.5046196833793815}} and units == {"gdp_q": GROWTH} and status == {"gdp_q": "A"}
    assert F["raw_head"].startswith("KEY,FREQ,ADJUSTMENT,REF_AREA,COUNTERPART_AREA,REF_SECTOR,COUNTERPART_SECTOR,ACCOUNTING_ENTRY,STO,INSTR_ASSET,ACTIVITY,EXPENDITURE,UNIT_MEASURE,PRICES,TRANSFORMATION,TIME_PERIOD,OBS_VALUE,OBS_STATUS,")


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_quarter_are_an_error():
    text = HEAD + f"{OK},2026-Q2,0.5,A,EUR,1\n{OK},26-Q3,1,A,EUR,1\n{OK},202-Q3,1,A,EUR,1\n{OK},2026-Q1,,M,EUR,1\n{OK},2025-Q4,n/a,A,EUR,1\n{OK},2025,1,A,EUR,1\n{OK},2025-Q5,1,A,EUR,1\n{OK},2025-Q0,1,A,EUR,1\n{OK},2025-q3,1,A,EUR,1\n{OK},2025-Q03,1,A,EUR,1\n{OK},2025Q3,1,A,EUR,1\n{OK},2025-Q3x,1,A,EUR,1\n{OK},2025-Q3T00,1,A,EUR,1\n{OK},2025-09,1,A,EUR,1\n"
    text += f"{OK},2025-Q2,nan,A,EUR,1\n{OK},2025-Q1,inf,A,EUR,1\nMNA.Q.Y.I9.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.G1,2026-Q2,0.9,A,EUR,1\nMNA.A.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.G1,2026,0.8,A,EUR,1\nMNA.Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY,2026-Q2,0.7,A,EUR,1\n"
    v, units, status = S.parse(text, ("gdp_q",))
    assert v == {"gdp_q": {"2026-Q2": 0.5}} and units == {"gdp_q": GROWTH} and status == {"gdp_q": "A"}      # a quarter with no value, a year, bad quarters, nan, inf, the 20-country area, another frequency and another series are all left out
    padded = HEAD + f"{OK},2026-Q2,0.5, P , EUR , 1 \n"
    assert S.parse(padded, ("gdp_q",))[1] == {"gdp_q": GROWTH} and S.parse(padded, ("gdp_q",))[2] == {"gdp_q": "P"}      # spaces around a unit or a status are not a different one
    two = HEAD + f"{OK},2026-Q1,0.1,A,EUR,1\n{OK},2026-Q3,0.3,P,EUR,1\n{OK},2026-Q2,0.2,A,EUR,1\n"
    assert S.parse(two, ("gdp_q",))[2] == {"gdp_q": "P"}                                                      # the status is the newest quarter's, whatever the order of the rows
    two = HEAD + f"{OK},2025-Q4,0.3,P,EUR,1\n{OK},2026-Q1,0.1,A,EUR,1\n"
    assert S.parse(two, ("gdp_q",))[2] == {"gdp_q": "A"}
    with pytest.raises(ValueError, match=r"gdp_q has two values for 2026-Q2"):
        S.parse(text + f"{OK},2026-Q2,0.1,A,EUR,1\n", ("gdp_q",))
    with pytest.raises(ValueError, match=r"no values for dd_c"):
        S.parse(text, ("gdp_q", "dd_c"))
    with pytest.raises(ValueError, match=r"the source returned no values for dd_c, ex_c$"):
        S.parse(text, ("dd_c", "ex_c"))


def _text(ids, units=None):
    rows = []
    for sid in ids:
        d = F["series"][sid]
        unit = units.get(sid, d["unit"]) if units else d["unit"]
        rows += [f"MNA.{S.SERIES[sid][0]},{q},{x!r},{st},{unit[0]},{unit[1]}" for q, x, st in zip(d["quarters"], d["values"], d["status"])]
    return HEAD + "\n".join(rows) + "\n"


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ids_of(path):
    for key, ids in S.REQUESTS:
        if path == "/service/data/MNA/" + key:
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

    svc = S.EuroGdp(client=_transport(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["growth"]["quarter_on_quarter"] == 0.41 and len(seen) == 4 and r["source"].startswith("European Central Bank")
    assert (r["age_days"], r["freshness"], r["provisional"]) == (49, "CURRENT", False)
    later = asyncio.run(S.EuroGdp(client=_transport(_handler)).overview(datetime(2026, 12, 31, 12, tzinfo=timezone.utc)))
    assert (later["age_days"], later["as_of"]) == (92, "2026-12-31T12:00:00+00:00")                            # the age is counted to the day given, not to the machine's
    base = "/service/data/MNA/"
    assert {req.url.path: req.url.params["lastNObservations"] for req in seen} == {base + key: "45" for key, ids in S.REQUESTS}
    assert all(req.url.params["format"] == "csvdata" for req in seen) and all(req.headers["user-agent"] == "ATLAS research terminal" for req in seen)
    assert all("%2B" not in str(req.url) for req in seen) and sum("+" in str(req.url) for req in seen) == 4      # the + that joins the values of one dimension must reach the ECB as it is
    asyncio.run(svc.overview(NOW))
    assert len(seen) == 4


def test_a_provisional_newest_growth_rate_reaches_the_card():
    key = "MNA." + S.SERIES["gdp_q"][0]
    q, x = F["series"]["gdp_q"]["quarters"][-1], F["series"]["gdp_q"]["values"][-1]
    row = (f"{key},{q},{x!r},A,EUR,1", f"{key},{q},{x!r},P,EUR,1")
    assert row[0] in _text(("gdp_q",)) and row[1] not in _text(("gdp_q",))
    r = asyncio.run(S.EuroGdp(client=_transport(lambda req: _handler(req, row))).overview(NOW))
    assert r["available"] is True and r["provisional"] is True


def test_an_unexpected_missing_key_reads_as_unavailable_not_as_a_crash(monkeypatch):
    def boom(*args):
        raise KeyError("gdp_q")

    monkeypatch.setattr(S, "summarize", boom)
    r = asyncio.run(S.EuroGdp(client=_transport(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"].startswith("The euro-area GDP could not be read right now (") and "growth" not in r


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(S.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = S.EuroGdp(client=_transport(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 4
    clock["t"] += S.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 4                                                                                         # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 8                                  # two minutes on it asks again
    clock["t"] += S.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 8
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 12 and (S.FAIL_TTL, S.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(S.EuroGdp(client=_transport(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "growth" not in r
    last = F["series"]["gdp_q"]["values"][-1]
    slip = (f"{last!r}", f"{last * 100!r}")                                                                     # a decimal slip in the newest growth rate: a check failing shows nothing either
    assert slip[0] in _text(("gdp_q",)) and slip[1] not in _text(("gdp_q",))
    r = asyncio.run(S.EuroGdp(client=_transport(lambda req: _handler(req, slip))).overview(NOW))
    assert r["available"] is False and "real GDP growth on the previous quarter is 41.1988 in 2026-Q3, outside -15 to 15" in r["reason"] and "growth" not in r


def test_a_response_in_other_units_is_refused_and_shows_nothing():
    for sid, what in (("gdp_nom", "nominal GDP"), ("gdp_q", "real GDP growth on the previous quarter"), ("im_c", "the contribution of imports to growth")):
        r = asyncio.run(S.EuroGdp(client=_transport(lambda req, s=sid: _handler(req, units={s: ("EUR", "3")}))).overview(NOW))
        assert r["available"] is False and f"the ECB reports {what} in other units than the card assumes" in r["reason"] and "growth" not in r, sid


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(S.EuroGdp(client=_transport(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The euro-area GDP could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(S.EuroGdp(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "growth" not in d
    assert d["reason"] == "Demo mode: the real euro-area GDP is not shown because made-up values would look real."


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-gdp")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
